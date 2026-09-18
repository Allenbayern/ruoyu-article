"""日更交付的"可点开预览页"生成器（2026-09-18 接入 daily_engine）。

**为什么要它**：run 里的 Markdown 与公众号 HTML 本身**点不开**——它们躺在
`runs/` 里，没有被任何服务托管；controller 要的是"标题能点、点开能读"的链接。
本模块把 run 既有产物渲染成一套自包含静态站点，写进 run 内的 `preview/`：

- `preview/index.html`：目录页，**标题即链接**，另给公众号复制版入口与交付状态；
- `preview/art-00N.html`：阅读页，自包含、**零外链**（内网/离线可读）、
  适配手机 / 暗色 / 打印，正文与 Markdown 成稿**逐段一致**（有测试钉死）；
- `preview/wechat/**`：把既有的公众号复制版原样搬进来，站点自洽。

**边界**：只读 run 内既有产物（`delivery/`、`wechat/`、`batch.json`、
`review/*.json`），不改正文、不产生新事实；`build()` 的每次写入都走
`evidence_write` 留底通道（封存 run 上默认拒绝），并如实记录
`preview/publish-record.json`（发布到主机静态根是**另一个动作**，见
`publish()` 与 `scripts/publish_preview.py`，产物生成与主机交付分离）。

预览页是给 controller 看的**未发布**内部页，页内显式标注
`publication_authorization: not_authorized`。
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from .evidence_write import RunSealedError, write_evidence  # 留底通道（写手清单测试按此识别）

READING_CSS = """
:root{--fg:#1a1a1a;--fg2:#5b5b5b;--bg:#f5f5f3;--card:#fff;--line:#e6e6e2;--accent:#0a58ca}
@media (prefers-color-scheme:dark){:root{--fg:#e8e8e6;--fg2:#a0a0a0;--bg:#141414;--card:#1c1c1c;--line:#2c2c2c;--accent:#7fb0ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC","Microsoft YaHei",sans-serif;
  font-size:17.5px;line-height:1.95;letter-spacing:.01em;-webkit-text-size-adjust:100%}
.bar{position:sticky;top:0;z-index:9;display:flex;flex-wrap:wrap;gap:.9em;align-items:center;
  padding:.55em 1.1em;background:color-mix(in srgb,var(--card) 88%,transparent);
  backdrop-filter:saturate(1.4) blur(8px);border-bottom:1px solid var(--line);font-size:.86em}
.bar a{color:var(--accent);text-decoration:none}
.bar a:hover{text-decoration:underline}
.badge{margin-left:auto;color:var(--fg2);border:1px solid var(--line);border-radius:999px;padding:.05em .7em;white-space:nowrap}
.wrap{max-width:760px;margin:0 auto;padding:2.6em 1.3em 5em}
article{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:2.4em 2.2em 2.8em;
  box-shadow:0 1px 2px rgba(0,0,0,.04)}
h1{font-size:1.55em;line-height:1.4;margin:0 0 .5em;font-weight:700}
.meta{color:var(--fg2);font-size:.8em;line-height:1.7;border-bottom:1px solid var(--line);padding-bottom:1.1em;margin-bottom:1.6em}
.meta code{font-size:.95em;background:transparent;color:inherit}
h2{font-size:1.16em;line-height:1.6;margin:2.1em 0 .7em;padding-left:.6em;border-left:3px solid var(--accent);font-weight:700}
p{margin:1.05em 0;text-align:justify}
p:first-of-type{margin-top:.2em}
footer{color:var(--fg2);font-size:.8em;text-align:center;margin-top:2.2em;line-height:1.9}
@media (max-width:560px){body{font-size:17px}.wrap{padding:1.4em .8em 3em}article{padding:1.6em 1.2em 2em;border-radius:10px}}
@media print{body{background:#fff}.bar,footer{display:none}article{border:0;box-shadow:none;padding:0}.wrap{max-width:none;padding:0}}
"""

INDEX_CSS = """
:root{--fg:#1a1a1a;--fg2:#5b5b5b;--bg:#f5f5f3;--card:#fff;--line:#e6e6e2;--accent:#0a58ca}
@media (prefers-color-scheme:dark){:root{--fg:#e8e8e6;--fg2:#a0a0a0;--bg:#141414;--card:#1c1c1c;--line:#2c2c2c;--accent:#7fb0ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC",sans-serif;line-height:1.8}
.wrap{max-width:820px;margin:0 auto;padding:3em 1.3em 4em}
h1{font-size:1.5em;margin:0 0 .3em}
.sub{color:var(--fg2);font-size:.88em;margin-bottom:2em}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:1.5em 1.6em;margin:0 0 1.2em;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.card h2{margin:0 0 .45em;font-size:1.3em;line-height:1.5}
.card h2 a{color:var(--fg);text-decoration:none;border-bottom:2px solid transparent}
.card h2 a:hover{color:var(--accent);border-bottom-color:var(--accent)}
.hook{color:var(--fg2);font-size:.9em;margin:.2em 0 .9em}
.links{display:flex;flex-wrap:wrap;gap:.6em;margin:.2em 0 .9em}
.links a{display:inline-block;font-size:.85em;text-decoration:none;color:var(--accent);border:1px solid var(--line);border-radius:999px;padding:.18em .8em}
.links a:hover{background:color-mix(in srgb,var(--accent) 10%,transparent)}
.kv{color:var(--fg2);font-size:.78em;line-height:1.9;word-break:break-all}
.kv code{font-size:.95em}
.note{color:var(--fg2);font-size:.8em;border-top:1px solid var(--line);padding-top:1.2em;margin-top:2em;line-height:1.9}
"""


def md_to_html(body: str) -> str:
    """把本项目成稿（H1 + H2 + 段落）渲染为 HTML。

    正文不使用强调/列表/链接语法，因此只处理标题与段落；遇到未知行按普通段落
    处理——渲染失败的方向只能是"退化成段落"，不会丢内容。
    """
    out: list[str] = []
    for block in re.split(r"\n\s*\n", body.strip()):
        line = block.strip()
        if not line:
            continue
        if line.startswith("## "):
            out.append(f"<h2>{html.escape(line[3:].strip())}</h2>")
        elif line.startswith("# "):
            continue
        else:
            out.append("<p>" + html.escape(line).replace("\n", "<br>") + "</p>")
    return "\n".join(out)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_article(run_root: Path, article_id: str) -> dict:
    """读一篇成稿（Markdown 为规范稿），返回渲染所需的全部字段。"""
    delivery = run_root / f"delivery/{article_id}/delivery.md"
    if not delivery.is_file():
        raise FileNotFoundError(f"缺少成稿：{delivery}")
    raw = delivery.read_text(encoding="utf-8")
    title, _, body = raw.partition("\n")
    title = title.lstrip("# ").strip()
    body = body.strip()
    return {
        "article_id": article_id,
        "title": title,
        "body": body,
        "body_html": md_to_html(body),
        "cjk_chars": len(re.findall(r"[\u4e00-\u9fff]", body)),
        "sha256": _sha256(delivery),
    }


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def delivery_status(run_root: Path, batch: dict) -> str:
    """交付状态：content-delivery 优先，缺失时退回 batch 的 gate_status。"""
    record = _load_json(run_root / "review/content-delivery.json")
    if isinstance(record.get("content_status"), str) and record["content_status"]:
        return record["content_status"]
    statuses = {
        str(article.get("gate_status", {}).get("content_fidelity") or "")
        for article in batch.get("articles", [])
        if isinstance(article, dict)
    }
    return "PENDING_L2" if statuses else "UNKNOWN"


def slug(run_root: Path) -> str:
    """主机静态根下的目录名：`<日期>-<run 名>`，如 `2026-09-17-daily-009`。"""
    run_root = Path(run_root).resolve()
    return f"{run_root.parent.name}-{run_root.name}"


def _write(run_root: Path, relative: str, content: str | bytes, reason: str) -> None:
    """run 内写入一律走留底通道（封存 run 上会抛 RunSealedError）。"""
    write_evidence(
        run_root / relative,
        content if isinstance(content, bytes) else content.encode("utf-8"),
        run_dir=run_root,
        reason=f"preview_site:{reason}",
    )


def build(run_root: str | Path, *, articles: list[str] | None = None) -> dict:
    """生成 `preview/` 站点（幂等；重复生成会覆盖并留底）。

    :param run_root: run 根目录。
    :param articles: 要渲染的 article_id；默认取 `batch.json` 的 articles 顺序。
    :returns: 摘要（页面路径、每篇 CJK 数与哈希、交付状态）。
    """
    run_root = Path(run_root)
    batch = _load_json(run_root / "batch.json")
    ids = articles or [a["article_id"] for a in batch.get("articles", []) if isinstance(a, dict) and a.get("article_id")]
    if not ids:
        raise ValueError(f"batch.json 未给出 articles：{run_root / 'batch.json'}")
    hooks = {
        a["article_id"]: a.get("review_hook", "")
        for a in batch.get("articles", [])
        if isinstance(a, dict) and a.get("article_id")
    }
    final = _load_json(run_root / "review/final-review.json")
    status = delivery_status(run_root, batch)
    rendered = [read_article(run_root, aid) for aid in ids]

    # 1) 公众号复制版原样搬进站点（缺失时只记录，不阻断）
    copied: list[str] = []
    for relative in ("wechat/index.html", "wechat/manifest.json"):
        src = run_root / relative
        if src.is_file():
            _write(run_root, f"preview/{relative}", src.read_bytes(), f"copy:{relative}")
            copied.append(f"preview/{relative}")
    for art in rendered:
        for suffix in (".html", ".wx.html"):
            relative = f"wechat/{art['article_id']}{suffix}"
            src = run_root / relative
            if src.is_file():
                _write(run_root, f"preview/{relative}", src.read_bytes(), f"copy:{relative}")
                copied.append(f"preview/{relative}")

    # 2) 目录页：标题即链接
    cards: list[str] = []
    for art in rendered:
        aid = art["article_id"]
        hook = html.escape(hooks.get(aid, ""))
        cards.append(
            f"""<div class="card">
  <h2><a href="{aid}.html">{html.escape(art['title'])}</a></h2>
  {f'<p class="hook">最强钩子：{hook}</p>' if hook else ''}
  <div class="links">
    <a href="{aid}.html">阅读</a>
    <a href="wechat/{aid}.html">公众号复制版（点「复制全文（含样式）」）</a>
    <a href="wechat/{aid}.wx.html">复制片段 HTML</a>
  </div>
  <div class="kv">article_id <code>{aid}</code> · CJK <code>{art['cjk_chars']}</code> ·
  sha256 <code>{art['sha256'][:16]}…</code> · content_status <code>{html.escape(status)}</code></div>
</div>"""
        )
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    finals = " · ".join(
        f"{key} <code>{html.escape(str(final.get(key)))}</code>"
        for key in ("content_result", "evidence_result", "governance_result", "verdict")
        if final.get(key) is not None
    )
    index = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>日更文章预览 · {html.escape(slug(run_root))}</title>
<style>{INDEX_CSS}</style></head><body><div class="wrap">
<h1>日更文章预览 · {html.escape(slug(run_root))}</h1>
<p class="sub">{len(rendered)} 篇 Markdown 成稿；内容栏 <strong>{html.escape(status)}</strong>。<strong>点标题即读</strong>。</p>
{''.join(cards)}
<div class="note">
{f'终审：{finals}<br>' if finals else ''}
publication_authorization: <code>not_authorized</code> —— 本页仅供预览与人工签署，系统未发布、未推送。<br>
页面生成：{generated}（源：<code>runs/{html.escape(slug(run_root))}/</code>）
</div></div></body></html>"""
    _write(run_root, "preview/index.html", index, "index")

    # 3) 阅读页
    for art in rendered:
        aid = art["article_id"]
        page = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(art['title'])}</title>
<style>{READING_CSS}</style></head><body>
<div class="bar">
  <a href="index.html">← 返回目录</a>
  <a href="wechat/{aid}.html">公众号复制版</a>
  <span class="badge">内部预览 · 未发布 · {html.escape(status)}</span>
</div>
<div class="wrap"><article>
<h1>{html.escape(art['title'])}</h1>
<div class="meta">{aid} · CJK {art['cjk_chars']} 字 · sha256 <code>{art['sha256'][:16]}…</code> ·
run <code>{html.escape(slug(run_root))}</code></div>
{art['body_html']}
</article>
<footer>publication_authorization: not_authorized · 本页为交付前内部预览</footer>
</div></body></html>"""
        _write(run_root, f"preview/{aid}.html", page, f"article:{aid}")

    return {
        "status": "ok",
        "run_id": slug(run_root),
        "content_status": status,
        "index_path": "preview/index.html",
        "index_sha256": _sha256(run_root / "preview/index.html"),
        "articles": [
            {"article_id": a["article_id"], "title": a["title"], "cjk_chars": a["cjk_chars"], "sha256": a["sha256"]}
            for a in rendered
        ],
        "copied": copied,
        "publication_authorization": "not_authorized",
    }


def publish(
    run_root: str | Path,
    root: str | Path,
    *,
    name: str | None = None,
    base_url: str | None = None,
) -> dict:
    """把 `preview/` 复制到主机静态根下（交付动作，产物生成之外的独立一步）。

    只复制、不改 run 内产物；落地页必须在 `root` 之内（越界即拒绝，fail-closed）。
    发布事实（时间、目标、哈希）记进 `preview/publish-record.json`（走留底通道）。
    """
    run_root = Path(run_root).resolve()
    source = run_root / "preview"
    if not (source / "index.html").is_file():
        raise FileNotFoundError(f"预览页尚未生成：{source / 'index.html'}（先运行 build()）")
    destination_root = Path(root).expanduser().resolve()
    if not destination_root.is_dir():
        raise NotADirectoryError(f"静态根不存在：{destination_root}")
    target = (destination_root / (name or slug(run_root))).resolve()
    if destination_root != target and destination_root not in target.parents:
        raise ValueError(f"发布目标越界：{target} 不在 {destination_root} 之内")

    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    pages = sorted(p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file())
    base = (base_url or "").rstrip("/")
    record = {
        "schema_version": "preview-publish-v1",
        "published_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_root": str(run_root),
        "static_root": str(destination_root),
        "target": str(target),
        "base_url": base,
        "index_url": f"{base}/{target.name}/" if base else f"{target.name}/",
        "files": pages,
        "index_sha256": _sha256(target / "index.html"),
        "publication_authorization": "not_authorized",
    }
    try:
        _write(run_root, "preview/publish-record.json", json.dumps(record, ensure_ascii=False, indent=2) + "\n", "publish-record")
    except RunSealedError:
        # 封存 run 不允许再写记录：发布本身仍可完成，但如实标注未记账
        record["record_error"] = "run_sealed_publish_record_not_written"
    return record


__all__ = [
    "READING_CSS",
    "INDEX_CSS",
    "md_to_html",
    "read_article",
    "delivery_status",
    "slug",
    "build",
    "publish",
]
