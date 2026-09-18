"""wechat_render: turn sealed deliveries into paste-ready 公众号 pages.

Why this exists (2026-09-16):
the daily pipeline ends at ``delivery/art-00X/delivery.md`` — Markdown.  The
WeChat backend strips ``class``/``<style>`` and keeps only **inline** styles, so
"paste the Markdown" is not a delivery step a human should repeat every day.
This module renders each sealed delivery through an external Markdown→WeChat
renderer (default: 文颜 CLI, Apache-2.0, inside Docker), writes the rendered
fragment plus a one-click-copy page into ``<run>/wechat/``, and records hashes.

Boundaries:
- the render step never grants publication.  ``publication_authorization`` stays
  ``not_authorized`` in every artifact it writes;
- it is non-fatal: an unavailable renderer (no docker, no network) records
  ``status: unavailable`` with a reason instead of failing the run;
- it does not touch existing gates, manifests or delivery files.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import html
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "wechat-render-v1"
DEFAULT_THEME = "default"
TIMEOUT_SECONDS = 300
STDERR_TAIL = 400


def _pipeline_fingerprint() -> str:
    """本模块源码的哈希：渲染/归一/复制页代码一变，缓存整体失效。

    只按输入（markdown 哈希、主题、结构、命令）做缓存键是不够的——
    归一规则、内联样式表、复制页模板都在本模块里，改了它们必须重渲染。
    用整文件哈希是刻意保守的做法：宁可多渲染一次，也不给出旧版式的产物。
    """

    return sha256_bytes(Path(__file__).read_bytes())[:16]


# Placeholders: {md_file} {md_name} {workdir} {theme}
DEFAULT_RENDERER_CMD = (
    "docker run --rm -v {workdir}:/w -w /w node:22-alpine "
    "npx --yes @wenyan-md/cli render -f {md_name} -t {theme}"
)

COPY_PAGE_CSS = """
body{margin:0;background:#f4f4f2;font-family:-apple-system,"PingFang SC","Noto Sans CJK SC",sans-serif}
.bar{position:sticky;top:0;z-index:9;display:flex;gap:.6em;align-items:center;flex-wrap:wrap;padding:.7em 1em;background:#1f2023;color:#fff;font-size:14px}
.bar b{font-weight:600}.bar span{color:#aaa}
button{font:inherit;font-size:14px;padding:.45em 1em;border-radius:6px;border:0;cursor:pointer;background:#07c160;color:#fff}
button.ghost{background:#3a3b3f;color:#ddd}
.hint{padding:.6em 1em;background:#fffbe6;color:#7a5b00;font-size:13px;border-bottom:1px solid #f0e6c8}
.hint code{background:#f4ecd8;padding:.1em .35em;border-radius:3px}
.sheet{max-width:720px;margin:1.4em auto 4em;background:#fff;border-radius:10px;box-shadow:0 1px 3px rgba(0,0,0,.08);padding:2.2em 1.6em}
.toast{position:fixed;left:50%;bottom:2em;transform:translateX(-50%);background:#1f2023;color:#fff;padding:.6em 1.2em;border-radius:20px;font-size:14px;opacity:0;transition:opacity .25s;pointer-events:none}
.toast.on{opacity:.95}
@media (max-width:600px){.sheet{margin:0;border-radius:0;padding:1.2em 1em}}
"""

COPY_PAGE_SCRIPT = """
function toast(msg){
  const t=document.getElementById('toast');
  t.textContent=msg; t.classList.add('on'); setTimeout(()=>t.classList.remove('on'),1800);
}
function copyArticle(){
  const node=document.getElementById('wx-article');
  const range=document.createRange(); range.selectNodeContents(node);
  const sel=window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
  let ok=false;
  try{ ok=document.execCommand('copy'); }catch(e){ ok=false; }
  sel.removeAllRanges();
  if(ok){ toast('已复制，去公众号后台粘贴吧'); }
  else if(navigator.clipboard && window.isSecureContext){
    const blob=new Blob([node.innerHTML],{type:'text/html'});
    navigator.clipboard.write([new ClipboardItem({'text/html':blob})]).then(
      ()=>toast('已复制，去公众号后台粘贴吧'), ()=>toast('浏览器拦截了剪贴板，请手动全选复制'));
  } else { toast('浏览器拦截了剪贴板，请手动 Cmd/Ctrl+A 全选复制'); }
}
function copySource(){
  const node=document.getElementById('wx-article');
  const textarea=document.createElement('textarea');
  textarea.value=node.innerHTML;
  document.body.appendChild(textarea); textarea.select();
  let ok=false;
  try{ ok=document.execCommand('copy'); }catch(e){ ok=false; }
  document.body.removeChild(textarea);
  if(ok){ toast('已复制 HTML 源码，去编辑器粘贴进“HTML/源码”模式'); }
  else { toast('复制失败，请手动选择页面下方源码框复制'); }
}
function showSource(){
  const node=document.getElementById('wx-article');
  const box=document.getElementById('srcbox');
  box.value=node.innerHTML;
  box.style.display=box.style.display==='none'?'block':'none';
}
"""


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def cjk_chars(text: str) -> int:
    return len(_CJK_RE.findall(text))


# 2026-09-16：公众号原生结构样式。
# 起因：文颜默认主题是"博主个人风"——H1 居中带文字阴影、H2 居中带下边框、
# p 用 margin:1em 0，粘进后台后与后台默认段距叠加，标题还会和后台标题栏
# 重复一遍，用户只能靠后台/编辑器的"一键排版"再修一次。这里把渲染结果
# 归一到后台原生结构：去掉正文 H1（标题走后台标题栏）、小标题左对齐无阴影、
# 段距只给下边距，字体交给后台默认。
WECHAT_NATIVE_STYLES = {
    "section": "",
    "h2": ("margin: 1.8em 0 .7em; font-size: 1.05em; font-weight: bold; "
           "text-align: left; line-height: 1.6; color: #222;"),
    "h3": ("margin: 1.4em 0 .5em; font-size: 1em; font-weight: bold; "
           "text-align: left; line-height: 1.6; color: #222;"),
    "p": "margin: 0 0 1.2em; line-height: 1.75; font-size: 16px; color: #333;",
    "blockquote": ("margin: 1.2em 0; padding: .4em 1em; border-left: 3px solid #ddd; "
                   "color: #666; line-height: 1.75;"),
    "li": "margin: 0 0 .5em; line-height: 1.75; font-size: 16px; color: #333;",
}
_DROP_ATTRS = re.compile(r'\s(?:id|data-provider|data-theme)="[^"]*"')
_H1_RE = re.compile(r"<h1\b[^>]*>.*?</h1>\s*", re.S)


def normalize_for_wechat(rendered: str, *, drop_title: bool = True) -> str:
    """Re-style a rendered fragment into 公众号-native inline styles.

    Deterministic post-processing instead of trusting a third-party theme:
    the theme can change under us, the rules below cannot.
    """
    text = rendered.strip()
    if drop_title:
        # 正文标题行与公众号标题栏重复，去掉第一处 H1。
        text = _H1_RE.sub("", text, count=1)
    text = _DROP_ATTRS.sub("", text)
    text = re.sub(
        r"<section\b[^>]*>",
        '<section style="line-height: 1.75; font-size: 16px; color: #333;">',
        text, count=1,
    )
    for tag in ("h2", "h3", "p", "blockquote", "li"):
        style = WECHAT_NATIVE_STYLES[tag]
        text = re.sub(rf"<{tag}\b[^>]*>", f'<{tag} style="{style}">', text)
    # 渲染器给行内元素加的 <span> 没有样式价值，去掉可减少后台解析噪音。
    text = re.sub(r"<span(?:\s[^>]*)?>", "", text)
    text = text.replace("</span>", "")
    return text.strip()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _now() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def copy_page(*, title: str, note: str, body_html: str, editor_url: str = "") -> str:
    """Wrap a rendered article into a page whose button copies rich HTML."""
    editor = (
        f'  <button class="ghost" onclick="location.href=\'{html.escape(editor_url, quote=True)}\'">'
        "用编辑器改排版</button>\n" if editor_url else ""
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · 公众号复制版</title>
<style>{COPY_PAGE_CSS}
.srcbox{{display:none;width:calc(100% - 2em);min-height:220px;margin:1em;font:12px/1.5 ui-monospace,Menlo,monospace;
 white-space:pre-wrap;word-break:break-all;border:1px solid #ddd;border-radius:6px;padding:.6em;background:#fafafa}}
</style></head>
<body>
<div class="bar">
  <b>{html.escape(title)}</b><span>{html.escape(note)}</span>
  <button onclick="copyArticle()">复制全文（含样式）</button>
  <button class="ghost" onclick="copySource()">复制 HTML 源码</button>
  <button class="ghost" onclick="showSource()">看源码</button>
  <button class="ghost" onclick="history.back()">← 返回</button>
{editor}</div>
<div class="hint">标题请填到后台的「标题」栏，正文从这里复制（已去掉重复标题行）。
点「复制全文」后到公众号后台正文 <code>Cmd/Ctrl+V</code> 即可；若浏览器拦截剪贴板，
就在文章区域 <code>Cmd/Ctrl+A</code> 全选再复制。若后台仍要重排，改用「复制 HTML 源码」，
粘进 135/壹伴/doocs 编辑器的“HTML/源码”模式。</div>
<div class="sheet"><div id="wx-article">{body_html}</div></div>
<textarea class="srcbox" id="srcbox" readonly></textarea>
<div class="toast" id="toast">已复制</div>
<script>{COPY_PAGE_SCRIPT}</script>
</body></html>
"""


def index_page(*, run_id: str, items: Sequence[Mapping[str, str]]) -> str:
    rows = "\n".join(
        f'<li><a href="{html.escape(str(item["href"]), quote=True)}">{html.escape(str(item["title"]))}</a>'
        f' — {html.escape(str(item.get("note", "")))}</li>'
        for item in items
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>公众号复制版 · {html.escape(run_id)}</title>
<style>
body{{max-width:760px;margin:2.5em auto;padding:0 1.2em;line-height:1.9;font-family:-apple-system,"PingFang SC",sans-serif}}
a{{color:#0a58ca}} li{{margin:.5em 0}} .meta{{color:#777;font-size:.88em;margin-top:3em}}
</style></head><body>
<h1>公众号复制版 · {html.escape(run_id)}</h1>
<p>打开任一链接 → 点「复制全文（含样式）」→ 到公众号后台正文粘贴。样式已内联。</p>
<ul>
{rows}
</ul>
<p class="meta">渲染：文颜 CLI（Apache-2.0，主题见 manifest）·
publication_authorization: not_authorized（预览用，未发布）</p>
</body></html>
"""


def _renderer_argv(command: str, *, workdir: Path, md_name: str, theme: str) -> list[str]:
    formatted = command.format(
        workdir=str(workdir), md_file=str(workdir / md_name), md_name=md_name, theme=theme,
    )
    return shlex.split(formatted)


def render_markdown(
    markdown: str,
    *,
    theme: str = DEFAULT_THEME,
    renderer_cmd: str = DEFAULT_RENDERER_CMD,
    timeout: int = TIMEOUT_SECONDS,
) -> tuple[str, str]:
    """Render Markdown to a WeChat-style fragment. Returns (html, renderer_used)."""
    with tempfile.TemporaryDirectory(prefix="wxrender-") as tmp:
        workdir = Path(tmp)
        md_name = "article.md"
        (workdir / md_name).write_text(markdown, encoding="utf-8")
        argv = _renderer_argv(renderer_cmd, workdir=workdir, md_name=md_name, theme=theme)
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError as exc:
            raise RendererUnavailable(f"renderer_not_found:{argv[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise RendererUnavailable(f"renderer_timeout:{timeout}s") from exc
        if proc.returncode != 0:
            tail = (proc.stderr or "").strip().splitlines()[-3:]
            raise RendererFailed(f"renderer_exit:{proc.returncode}:" + " / ".join(tail)[:STDERR_TAIL])
        output = (proc.stdout or "").strip()
        if not output:
            raise RendererFailed("renderer_empty_output")
        return output, " ".join(argv)


class RendererUnavailable(RuntimeError):
    """The renderer could not be executed at all (missing binary/daemon/network)."""


class RendererFailed(RuntimeError):
    """The renderer ran but did not produce usable output."""


def _delivery_files(run_dir: Path) -> list[tuple[str, Path]]:
    delivery_dir = run_dir / "delivery"
    found: list[tuple[str, Path]] = []
    if not delivery_dir.is_dir():
        return found
    for path in sorted(delivery_dir.glob("*/delivery.md")):
        found.append((path.parent.name, path))
    return found


def _previous_manifest(root: Path) -> dict[str, Any]:
    """上一份 wechat/manifest.json（读不到就当成没有缓存）。"""

    try:
        payload = json.loads((root / "wechat" / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _previous_entries(root: Path) -> dict[str, Mapping[str, Any]]:
    manifest = _previous_manifest(root)
    entries = manifest.get("articles")
    out: dict[str, Mapping[str, Any]] = {}
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, Mapping) and isinstance(entry.get("article_id"), str):
                out[str(entry["article_id"])] = entry
    return out


def _cache_reusable(
    root: Path,
    entry: Mapping[str, Any],
    *,
    source_sha256: str,
    theme: str,
    style: str,
    renderer_cmd: str,
    fingerprint: str,
    previous_theme: str,
    previous_style: str,
) -> bool:
    """这条缓存还能不能用：输入、渲染参数、代码指纹、产物哈希都要对得上。

    渲染一次要跑 docker + npx（实测每篇约 200 s），但它慢不是放松校验的理由：
    只要有一项对不上就重渲染，宁可慢也不能给出与当前稿件/当前版式不符的产物。
    """

    # 主题/结构记在上一份 manifest 的顶层（每篇一篇记录里没有 theme 字段）。
    if previous_theme != theme or previous_style != style:
        return False
    if entry.get("source_sha256") != source_sha256:
        return False
    if entry.get("style") != style:
        return False
    # 比模板而不是展开后的命令：展开结果里带着每次新建的临时工作目录。
    if entry.get("renderer_cmd_template") != renderer_cmd:
        return False
    # 旧版本记录没有指纹/复制页哈希 → 无法证明产物与当前代码一致，按缓存未命中处理。
    if entry.get("pipeline_fingerprint") != fingerprint:
        return False
    if style == "native" and entry.get("dropped_title") is not True:
        return False
    fragment_path = root / str(entry.get("fragment_path") or "")
    page_path = root / str(entry.get("copy_page_path") or "")
    if not fragment_path.is_file() or not page_path.is_file():
        return False
    if sha256_bytes(fragment_path.read_bytes()) != entry.get("fragment_sha256"):
        return False
    if sha256_bytes(page_path.read_bytes()) != entry.get("copy_page_sha256"):
        return False
    return True


def render_run(
    run_dir: str | Path,
    *,
    theme: str = DEFAULT_THEME,
    renderer_cmd: str | None = None,
    editor_url: str = "",
    style: str = "native",
    force: bool = False,
    title_lookup: Mapping[str, str] | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Render every sealed delivery of a run into ``<run>/wechat/``.

    ``style``: ``native`` (default) normalizes the renderer output to
    公众号-native structure (drops the duplicated H1, left-aligns headings,
    removes text shadows); ``theme`` keeps the renderer theme untouched.

    ``use_cache`` (default true): reuse the previous manifest's output when the
    delivery hash, theme, style, renderer command, pipeline fingerprint and the
    recorded output hashes all still match — a re-run of a batch whose articles
    did not change then costs nothing instead of one docker+npx render per
    article (实测每篇约 200 s，daily-009 一天重渲染 13 次 / 2581 s).
    ``use_cache=False`` (CLI ``--no-cache``) forces a full re-render.

    Always returns a report; never raises for renderer problems (they land in
    ``status``/``reason`` so the caller can record ``not_run`` honestly).
    """

    root = Path(run_dir)
    command = renderer_cmd or os.environ.get("WECHAT_RENDER_CMD") or DEFAULT_RENDERER_CMD
    if style not in {"native", "theme"}:
        style = "native"
    fingerprint = _pipeline_fingerprint()
    previous_manifest = _previous_manifest(root)
    previous = _previous_entries(root)
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": f"{root.parent.name}/{root.name}" if root.parent.name[:4].isdigit() else root.name,
        "theme": theme,
        "style": style,
        "generated_at": _now(),
        "articles": [],
        "status": "ok",
        "reason": "",
        "publication_authorization": "not_authorized",
        "advisory": True,
        "cache": {
            "enabled": use_cache,
            "hits": 0,
            "misses": 0,
            "pipeline_fingerprint": fingerprint,
            "reused_from": str(previous_manifest.get("generated_at") or ""),
        },
    }
    if not force:
        from article_group.run_state import sealed_reason

        blocked = sealed_reason(root)
        if blocked:
            report["status"] = "run_sealed"
            report["reason"] = f"run 已封存（{blocked}）：加 force 才会重渲染"
            return report

    deliveries = _delivery_files(root)
    if not deliveries:
        report.update(status="no_deliveries", reason="delivery/art-*/delivery.md not found")
        _write_manifest(root, report, force=force)
        return report

    out_dir = root / "wechat"
    # 不在这里 mkdir：目录由 write_evidence 在令牌内按需创建（force 时才进令牌，
    # 显式 mkdir 会在封存 run 上被 runs_guard 拦下，等于 force 半生效）。
    index_items: list[dict[str, str]] = []
    for article_id, md_path in deliveries:
        markdown = md_path.read_text(encoding="utf-8")
        source_sha256 = sha256_bytes(md_path.read_bytes())
        title = (title_lookup or {}).get(article_id) or markdown.splitlines()[0].lstrip("# ").strip()
        note = f"{theme} 主题 · {style} 结构 · {cjk_chars(markdown)} 字"
        cached = previous.get(article_id) if use_cache else None
        if isinstance(cached, Mapping) and _cache_reusable(
            root,
            cached,
            source_sha256=source_sha256,
            theme=theme,
            style=style,
            renderer_cmd=command,
            fingerprint=fingerprint,
            previous_theme=str(previous_manifest.get("theme") or ""),
            previous_style=str(previous_manifest.get("style") or ""),
        ):
            entry = dict(cached)
            entry["cached"] = True
            entry["title"] = title
            entry["cjk_chars"] = cjk_chars(markdown)
            entry["inline_style_count"] = (root / str(entry["fragment_path"])).read_text(
                encoding="utf-8"
            ).count('style="')
            report["articles"].append(entry)
            report["cache"]["hits"] += 1
            index_items.append({"href": f"{article_id}.html", "title": title, "note": note})
            continue
        report["cache"]["misses"] += 1
        try:
            fragment, used = render_markdown(markdown, theme=theme, renderer_cmd=command)
        except RendererUnavailable as exc:
            report.update(status="unavailable", reason=str(exc))
            _write_manifest(root, report, force=force)
            return report
        except RendererFailed as exc:
            report.update(status="failed", reason=f"{article_id}:{exc}")
            _write_manifest(root, report, force=force)
            return report

        if style == "native":
            fragment = normalize_for_wechat(fragment, drop_title=True)
        wx_path = out_dir / f"{article_id}.wx.html"
        _write_out(wx_path, fragment + "\n", root, "wechat_render:fragment", force)
        page = copy_page(
            title=title,
            note=note,
            body_html=fragment,
            editor_url=editor_url,
        )
        page_path = out_dir / f"{article_id}.html"
        _write_out(page_path, page, root, "wechat_render:copy_page", force)
        report["articles"].append({
            "article_id": article_id,
            "title": title,
            "source_path": str(md_path.relative_to(root)),
            "source_sha256": source_sha256,
            "fragment_path": str(wx_path.relative_to(root)),
            "fragment_sha256": sha256_bytes(wx_path.read_bytes()),
            "copy_page_path": str(page_path.relative_to(root)),
            "copy_page_sha256": sha256_bytes(page_path.read_bytes()),
            "inline_style_count": fragment.count('style="'),
            "cjk_chars": cjk_chars(markdown),
            "style": style,
            "dropped_title": style == "native",
            "renderer_cmd": used,
            "renderer_cmd_template": command,
            "pipeline_fingerprint": fingerprint,
            "cached": False,
        })
        index_items.append({
            "href": f"{article_id}.html", "title": title,
            "note": note,
        })

    _write_out(out_dir / "index.html",
               index_page(run_id=report["run_id"], items=index_items),
               root, "wechat_render:index", force)
    report["index_path"] = str((out_dir / "index.html").relative_to(root))
    _write_manifest(root, report, force=force)
    return report


def _write_out(path: Path, content: str, root: Path, reason: str, force: bool) -> None:
    """所有 wechat 产物统一走留底+记账+封存守门通道。"""
    from article_group.evidence_write import RunSealedError, write_evidence

    try:
        write_evidence(path, content, run_dir=root, reason=reason, force=force)
    except RunSealedError:
        # 封存 run 上渲染被拒绝：记录状态而不抛，交由调用方判定
        raise


def _write_manifest(root: Path, report: Mapping[str, Any], *, force: bool = False) -> None:
    from article_group.evidence_write import write_evidence

    target = root / "wechat" / "manifest.json"
    write_evidence(target, json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                   run_dir=root, reason="wechat_render:manifest", force=force)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m article_group.wechat_render",
        description="渲染已封存交付稿为可直接粘贴进公众号后台的排版版（不授权发布）",
    )
    parser.add_argument("--run-root", required=True, type=Path, help="run 根目录")
    parser.add_argument("--theme", default=DEFAULT_THEME, help="文颜主题（default/orangeheart/pie/...）")
    parser.add_argument("--style", choices=("native", "theme"), default="native",
                        help="native=公众号后台原生结构（默认，去重复标题/左对齐/无阴影）；"
                             "theme=保留渲染器主题原样")
    parser.add_argument("--renderer-cmd", default=None,
                        help="自定义渲染命令模板，占位符 {md_file} {md_name} {workdir} {theme}")
    parser.add_argument("--editor-url", default="", help="复制页上附带的排版编辑器地址（可选）")
    parser.add_argument("--force", action="store_true", help="在已封存 run 上强制重渲染")
    parser.add_argument("--no-cache", action="store_true",
                        help="忽略上次渲染缓存（输入/参数/代码指纹任一变化本来就会自动重渲染）")
    parser.add_argument("--json", action="store_true", help="输出完整报告 JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = render_run(
        args.run_root,
        theme=args.theme,
        renderer_cmd=args.renderer_cmd,
        editor_url=args.editor_url,
        style=args.style,
        force=args.force,
        use_cache=not args.no_cache,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        cache = report.get("cache") or {}
        print(f"status={report['status']} theme={report['theme']} "
              f"cache={cache.get('hits', 0)} hit / {cache.get('misses', 0)} miss")
        for item in report["articles"]:
            flag = "（缓存复用）" if item.get("cached") else ""
            print(f"  {item['article_id']}: {item['copy_page_path']} "
                  f"({item['cjk_chars']} 字, {item['inline_style_count']} 处内联样式){flag}")
        if report.get("index_path"):
            print(f"  index: {report['index_path']}")
        if report["reason"]:
            print(f"  reason: {report['reason']}")
    return 0 if report["status"] in {"ok", "no_deliveries"} else 0


__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_THEME",
    "DEFAULT_RENDERER_CMD",
    "WECHAT_NATIVE_STYLES",
    "RendererUnavailable",
    "RendererFailed",
    "cjk_chars",
    "normalize_for_wechat",
    "copy_page",
    "index_page",
    "render_markdown",
    "render_run",
    "main",
]

if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
