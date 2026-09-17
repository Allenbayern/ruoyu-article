"""Build a tiny read-only preview site for the daily-008 deliverables.

Output: <本脚本所在目录>/{index.html,exp/*.html,docs/*.html}
Source markdown stays where it is; this only renders reading copies.

路径全部由脚本自身位置推导（Linux 原生，可整目录搬迁，不绑定任何机器）：
    ROOT  = 本脚本所在目录        <repo>/previews/preview-web
    REPO  = ROOT 的祖父目录        <repo>（项目根）
    DAILY = <repo>/previews/daily-008-preview
    EXP   = <repo>/experiments/length-experiment-008

成品文章 markdown 的取用顺序（只读，绝不写入 runs/）：
    1) DAILY/art-00X.md（预览目录自带副本，若有）
    2) <RUN>/delivery/art-00X/delivery.md（SEALED run 的交付原稿；迁移时
       因「字节相同、不重复搬运」未随预览目录回收，故这里回退读取）
RUN 可用环境变量 DAILY_RUN 覆盖（默认 2026-09-16/daily-008）。
"""
from __future__ import annotations

import html
import os
import pathlib
import re
import shutil

ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parents[1]
DAILY = REPO / "previews" / "daily-008-preview"
EXP = REPO / "experiments" / "length-experiment-008"
RUN = REPO / "runs" / os.environ.get("DAILY_RUN", "2026-09-16/daily-008")

# Mac 回收件里残留的绝对路径 → 当前仓库里的位置。
# 用仓库相对写法：既不绑定 /Users/Allen，也不绑定 /home/allen。
LEGACY_PREFIXES = (
    ("/Users/Allen/Documents/dsh/preview-web", "previews/preview-web"),
    ("/Users/Allen/Documents/dsh/daily-008-preview", "previews/daily-008-preview"),
    ("/Users/Allen/Documents/dsh/length-experiment-008", "experiments/length-experiment-008"),
)


def portable(text: str) -> str:
    """把 Mac 时代的绝对路径改写成仓库相对路径（渲染层安全网）。

    源 markdown 里可能仍留着 Mac 路径（例如 experiments/ 下的提案稿），
    生成 HTML 前统一改写，保证产物里不出现 /Users/Allen。
    """
    for legacy, relative in LEGACY_PREFIXES:
        text = text.replace(legacy, relative)
    return text


def read_source(candidates: list[pathlib.Path], *, note: str = "") -> str:
    """按顺序取第一个存在的源文件；缺失时给出可执行的报错。"""
    for index, path in enumerate(candidates):
        if path.is_file():
            if index:
                suffix = f"（{note}）" if note else ""
                print(f"note: {candidates[0]} 不存在，改用 {path}{suffix}")
            return path.read_text(encoding="utf-8")
    joined = "、".join(str(path) for path in candidates)
    raise SystemExit(f"error: 源文件缺失，无法生成预览：{joined}")


def article_sources(aid: str) -> list[pathlib.Path]:
    """成品文章 markdown 的候选来源：预览目录副本 → SEALED run 交付原稿（只读）。"""
    return [DAILY / f"{aid}.md", RUN / "delivery" / aid / "delivery.md"]

CSS = """
:root{color-scheme:light dark}
body{max-width:780px;margin:0 auto;padding:2.5em 1.2em 5em;font-family:-apple-system,"PingFang SC","Noto Sans CJK SC",sans-serif;line-height:1.95;color:#1b1b1b;background:#fbfbfa}
h1{font-size:1.65em;line-height:1.5;margin:0 0 1em}
h2{font-size:1.2em;margin:2em 0 .6em;padding-top:.2em}
h3{font-size:1.05em;margin:1.4em 0 .4em}
p{margin:.85em 0}
table{border-collapse:collapse;width:100%;margin:1em 0;font-size:.94em}
th,td{border:1px solid #ddd;padding:.45em .6em;text-align:left;vertical-align:top}
th{background:#f2f2ef}
code{background:#f0f0ec;padding:.1em .3em;border-radius:3px;font-size:.92em}
a{color:#0a58ca}
.nav{margin:0 0 2em;padding:.7em 1em;background:#f2f2ef;border-radius:8px;font-size:.92em}
.meta{margin-top:3.5em;padding-top:1em;border-top:1px solid #e2e2de;color:#777;font-size:.85em}
ul.index{font-size:1.05em;line-height:2.1;padding-left:1.2em}
blockquote{margin:1em 0;padding:.4em 1em;border-left:3px solid #ddd;color:#555}
@media (prefers-color-scheme:dark){
 body{background:#17181a;color:#e6e6e6}
 th{background:#232427}th,td{border-color:#333}
 code{background:#232427}.nav{background:#232427}.meta{color:#999;border-color:#333}
 a{color:#7db4ff}
}
"""

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_URL = re.compile(r"(https?://[^\s<>()|]+)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = _MD_LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', text)
    text = _URL.sub(lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>', text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return text


def render(markdown: str, *, title: str, footer: str) -> str:
    markdown = portable(markdown)
    title = portable(title)
    footer = portable(footer)
    lines = markdown.splitlines()
    out: list[str] = []
    buf: list[str] = []
    table: list[list[str]] = []

    def flush_para() -> None:
        nonlocal buf
        if buf:
            out.append(f"<p>{inline(' '.join(buf))}</p>")
            buf = []

    def flush_table() -> None:
        nonlocal table
        if not table:
            return
        head, *body = table
        out.append("<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>")
        for row in body:
            out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>")
        out.append("</tbody></table>")
        table = []

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            flush_para()
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(set(c) <= set("-: ") and c for c in cells):
                continue
            table.append(cells)
            continue
        flush_table()
        if not stripped:
            flush_para()
            continue
        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if heading:
            flush_para()
            level = min(len(heading.group(1)) + 0, 4)
            out.append(f"<h{max(level, 2)}>{inline(heading.group(2))}</h{max(level, 2)}>")
            continue
        if stripped.startswith("> "):
            flush_para()
            out.append(f"<blockquote>{inline(stripped[2:])}</blockquote>")
            continue
        if re.match(r"^([-*+]|\d+\.)\s+", stripped):
            flush_para()
            item = re.sub(r"^([-*+]|\d+\.)\s+", "", stripped)
            out.append(f"<p>• {inline(item)}</p>")
            continue
        buf.append(stripped)
    flush_para()
    flush_table()
    cjk = len(_CJK.findall(markdown))
    body = "\n".join(out)
    return (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body>"
        f'<div class="nav"><a href="/">← 预览首页</a> · <a href="/daily-008/index.html">daily-008 成品</a> · '
        f'<a href="/docs/comparison.html">实验对照报告</a> · <a href="/docs/links.html">链接清单</a></div>'
        f"<h1>{html.escape(title)}</h1>"
        f"{body}"
        f'<p class="meta">{html.escape(footer)} · CJK {cjk} 字 · '
        "publication_authorization: not_authorized（未发布，仅供本地/内网阅读）</p>"
        "</body></html>"
    )


def scan_legacy_paths() -> list[tuple[str, int, str]]:
    """扫本目录下生成的 HTML，确认没有 /Users/ 残留（生成器自检）。"""
    hits: list[tuple[str, int, str]] = []
    for path in sorted(ROOT.rglob("*.html")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "/Users/" in line:
                hits.append((str(path.relative_to(ROOT)), number, line.strip()))
    return hits


def main() -> None:
    (ROOT / "exp").mkdir(parents=True, exist_ok=True)
    (ROOT / "docs").mkdir(parents=True, exist_ok=True)
    shutil.copytree(DAILY, ROOT / "daily-008", dirs_exist_ok=True)

    articles = [
        ("art-001", "art-001 《让子弹飞》之后，姜文为什么一部比一部拧巴", "daily-008 终稿"),
        ("art-002", "art-002 《还珠格格》第三部为什么像另一部剧", "daily-008 终稿"),
    ]
    for aid, title, footer in articles:
        text = portable(read_source(article_sources(aid), note="读 SEALED run 交付原稿（只读）"))
        target = ROOT / "exp" / f"{aid}.html"
        target.write_text(render(text, title=title, footer=footer), encoding="utf-8")
        print("written", target)
        # 站内也放一份纯文本（daily-008/art-00X.md），链接清单里的「纯文本」列才有落点
        served = ROOT / "daily-008" / f"{aid}.md"
        served.write_text(text, encoding="utf-8")
        print("written", served)

    exp_pages = [
        # v1000 基线就是 art-001 终稿（两份字节相同：迁移比对已认定，且本脚本渲染
        # 复现出的 exp/v1000.html 与 exp/art-001.html 正文一致）。experiments/ 下没有
        # v1000.md，故按候选链回退到成品原稿。
        (
            [EXP / "exp" / "v1000.md", *article_sources("art-001")],
            "v1000 原终稿（1032 字）",
            "扩写实验基线",
        ),
        ([EXP / "exp" / "v1800-r2.md"], "v1800-r2 同材料扩写（1973 字）", "扩写实验 · 7 处 minor 已修"),
        ([EXP / "exp" / "v2400-r2.md"], "v2400-r2 补料成稿（2651 字）", "扩写实验 · 补料后"),
    ]
    for candidates, title, footer in exp_pages:
        target = ROOT / "exp" / f"{candidates[0].stem}.html"
        text = read_source(candidates, note="v1000 基线＝art-001 终稿，两份字节相同")
        target.write_text(render(text, title=title, footer=footer), encoding="utf-8")
        print("written", target)

    for name, title, footer in [
        ("comparison.md", "扩写对照实验全过程与裁定", "daily-008 长度实验"),
        ("material-gap-spec-008.md", "材料缺口规格与补料实测", "抓取侧规格"),
        ("length-policy-proposal.md", "字数口径分层提案（含落地状态）", "提案，未执行的部分已标注"),
    ]:
        src = EXP / name
        target = ROOT / "docs" / (src.stem + ".html")
        target.write_text(
            render(read_source([src]), title=title, footer=footer), encoding="utf-8"
        )
        print("written", target)

    (ROOT / "docs" / "links.html").write_text(
        render(read_source([DAILY / "links.md"]), title="daily-008 文章与来源链接", footer="链接清单"),
        encoding="utf-8",
    )
    print("written", ROOT / "docs" / "links.html")

    index = [
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>若雨随影 · daily-008 预览</title><style>{CSS}</style></head><body>",
        "<h1>若雨随影 · daily-008 预览</h1>",
        '<p class="meta">只读预览 · publication_authorization: not_authorized（未发布）</p>',
        "<h2>本期成品（两篇）</h2>",
        '<ul class="index">',
        '<li><a href="/exp/art-001.html">《让子弹飞》之后，姜文为什么一部比一部拧巴</a>（1032 字）</li>',
        '<li><a href="/exp/art-002.html">《还珠格格》第三部为什么像另一部剧</a>（935 字）</li>',
        "</ul>",
        "<h2>长度实验：三版对照（同一题 art-001）</h2>",
        '<ul class="index">',
        '<li><a href="/exp/v1000.html">v1000 原终稿</a> — 1032 字，2 个小节各 111 字</li>',
        '<li><a href="/exp/v1800-r2.html">v1800-r2 同材料扩写</a> — 1973 字，门禁全绿</li>',
        '<li><a href="/exp/v2400-r2.html">v2400-r2 补料成稿</a> — 2651 字，事实密度 20/26</li>',
        "</ul>",
        "<h2>公众号复制版（打开→点复制→粘贴进后台）</h2>",
        '<ul class="index">',
        '<li><a href="/wx/index.html">复制版列表</a> — 文颜渲染，样式已内联</li>',
        '<li><a href="/wx/art-001.html">art-001 复制版</a> · <a href="/wx/art-002.html">art-002 复制版</a></li>',
        "</ul>",
        "<h2>过程文档</h2>",
        '<ul class="index">',
        '<li><a href="/docs/comparison.html">扩写对照实验全过程与裁定</a></li>',
        '<li><a href="/docs/material-gap-spec-008.html">材料缺口规格与补料实测</a></li>',
        '<li><a href="/docs/length-policy-proposal.html">字数口径分层提案</a></li>',
        '<li><a href="/docs/links.html">文章与来源链接清单</a></li>',
        "</ul>",
        f'<p class="meta">内网只读服务 · python3 -m http.server · 目录 {ROOT}</p>',
        "</body></html>",
    ]
    (ROOT / "index.html").write_text("\n".join(index), encoding="utf-8")
    print("written", ROOT / "index.html")

    leftovers = scan_legacy_paths()
    if leftovers:
        print(f"WARN: {len(leftovers)} 处仍残留 Mac 路径，请检查对应源 markdown：")
        for relative, number, line in leftovers[:20]:
            print(f"  {relative}:{number}: {line[:140]}")
    else:
        print(f"OK: {ROOT} 下生成的 HTML 里没有 /Users/ 残留")


if __name__ == "__main__":
    main()
