"""prose_pilot: 后台「材料-密度」写作检查（human-writing 吸收，v2 精简）。

来源
----
本模块吸收 human-writing（github.com/KKKKhazix/human-writing，commit 4fda173f），
2026-08-10 盲测后精简为两个已采纳通道：
  1. 材料清单前置（原 SKILL.md 材料门槛）：写前/评审时核对可追溯材料是否足够。
  2. 判断词密度（洞察路标过密）：「真正/其实/本质上/说到底…」单篇 ≥3 次提示。
  段落推进（thin/pause）、同构排比、句长过齐、抒情词、长前置成分均已弃用
  （盲测 precision 不达 80% 门槛，见 runs/2026-08-10/prose-pilot/README.md）。


边界（与既有体系的关系）
------------------------
- 本模块只输出 advisory 报告，绝不改变 style_gate / compliance_gate /
  workflow 的任何判定，不写回稿件，不阻断发布。接入生产门禁需另行决议。
- 不采用 human-writing 的全局冒号/破折号/翻案句硬禁令（与读者面成稿
  规范冲突，且对已通过审查的成品误伤率高）；也不采用其「读者面显式
  来源可见化」要求（若雨规范：证据留后台 ledger，读者面不自证来源）。
- 材料清单锚点与 citations-ledger.json 的 quotes 做逐字或近似匹配，
  只做报告，不做自动判罚。

用法
----
    python -m article_group.prose_pilot <delivery.html> [--ledger <citations-ledger.json>]
    python -m article_group.prose_pilot <plain-text-file> [--ledger ...]

输出：JSON（结构见 analyze_html / analyze_text）。退出码：0（无硬失败，
本工具永远为 advisory，正常返回 0；文件不可读返回 2）。
"""

from __future__ import annotations

import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------
# 材料锚点信号（与 style_gate.fact_density_check 保持同族，但输出清单）
# --------------------------------------------------------------------------
_MATERIAL_ANCHORS = [
    (re.compile(r"[《》]"), "作品名"),
    (re.compile(r"\d{1,2}月\d{1,2}日"), "具体日期"),
    (re.compile(r"\d{4}年"), "年份"),
    (re.compile(r"\d+(?:\.\d+)?[万千万亿个部届人天年次座轮批月元%％]"), "数量/比例"),
    (re.compile(r"(国家电影局|商务部|文化和旅游部|文旅|联盟|协会|委员会|研究院|院线|影院|平台|票务)"), "机构/平台"),
    (re.compile(r"(监制|导演|编剧|主演|制片人)"), "主创身份"),
    (re.compile(r"https?://|www\.|\.com|\.cn|\.gov|\.org"), "来源链接"),
]

_MATERIAL_BARE_MIN = 5  # human-writing 材料门槛参照值（非硬性，仅提示）

# 直接引用原文的口语标记：材料清单里带这些的条目计入「可追溯材料」。
_LEDGER_QUOTE_MARKERS = ("原文", "原文写道", "官方", "官宣", "报道", "数据显示")

# --------------------------------------------------------------------------
def _han_len(text: str) -> int:
    return len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))





# --------------------------------------------------------------------------
# 句法软警告（从 check_prose.py 的 warning 层移植，改为本项目口径）
# --------------------------------------------------------------------------
_JUDGMENT_MARKERS = ("真正", "其实", "本质上", "说到底", "归根结底", "关键在", "重点在")


def _syntax_warnings(text: str) -> list[dict[str, Any]]:
    """已采纳的密度信号：判断词（洞察路标）过密。

    盲测结论（2026-08-10）：仅此信号与材料清单达 80% 验收门槛；
    同构排比/句长过齐/抒情词/长前置成分均未采纳，段落推进通道已弃用。
    """
    out: list[dict[str, Any]] = []
    for marker in _JUDGMENT_MARKERS:
        n = text.count(marker)
        if n >= 3:
            out.append({"signal": "洞察路标", "detail": f"“{marker}”出现 {n} 次"})
    return out


# --------------------------------------------------------------------------
# HTML 文本提取（与 style_gate.visible_text 同构，避免跨模块依赖）
# --------------------------------------------------------------------------
class _TextParser(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in {"script", "style"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip > 0:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip == 0:
            self.parts.append(data)


def visible_text(html_fragment: str) -> str:
    parser = _TextParser()
    parser.feed(html_fragment)
    parser.close()
    return re.sub(r"\s+", "", "".join(parser.parts))


# --------------------------------------------------------------------------
# 材料清单（含 ledger 匹配）
# --------------------------------------------------------------------------
def _claim_material_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pat, label in _MATERIAL_ANCHORS:
        n = len(pat.findall(text))
        if n:
            counts[label] = n
    return counts


def _ledger_quote_match(claim: str, quote: str) -> bool:
    if not claim or not quote:
        return False
    c = re.sub(r"\s+", "", claim)
    q = re.sub(r"\s+", "", quote)
    if len(c) < 4 or len(q) < 4:
        return False
    if c in q or q in c:
        return True
    # 任一 10 字连续片段命中即视为可追溯
    if len(c) >= 10:
        for i in range(0, len(c) - 9, 3):
            if c[i:i + 10] in q:
                return True
    return False


def _ledger_from_path(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    quotes: list[dict[str, Any]] = []
    for src in data.get("sources", []):
        for q in src.get("quotes", []):
            quotes.append({
                "source_id": src.get("id"),
                "title": src.get("title"),
                "url": src.get("url"),
                "text": q.get("text", ""),
            })
    return quotes


# --------------------------------------------------------------------------
# 主分析
# --------------------------------------------------------------------------
def _is_section_header(p: str) -> bool:
    """章节小标题：短（≤14 字）且不以句末标点收尾的独立段。

    若雨随影成稿用独立 `<p>` 作章节小标题（如「谁在给 9.4 分」）。
    这类结构段不属于内容段，不参与 thin/pause 判定。
    """
    if _han_len(p) > 14:
        return False
    return not bool(re.search(r"[。！？!?…]$", p))


def analyze_text(text: str, title: str, ledger_quotes: list[dict[str, Any]]) -> dict[str, Any]:
    paragraphs = [re.sub(r"^[#\-\d\.、\s]+", "", p).strip()
                  for p in re.split(r"\n+", text) if p.strip()]

    # 材料清单（已采纳候选 A）
    counts = _claim_material_counts(text)
    matched: list[dict[str, Any]] = []
    for quote in ledger_quotes:
        if _ledger_quote_match(text, quote["text"]):
            matched.append(quote)

    # 判断词密度（已采纳候选 B）
    warnings = _syntax_warnings(text)

    return {
        "title": title,
        "chars": _han_len(text),
        "content_paragraphs": len(paragraphs),
        "material": {
            "anchors": counts,
            "anchor_total": sum(counts.values()),
            "bare_threshold": _MATERIAL_BARE_MIN,
            "below_threshold": sum(counts.values()) < _MATERIAL_BARE_MIN,
            "ledger_matched_quotes": len(matched),
            "matched_sources": sorted({f"{q['source_id']}:{q['title'][:30]}" for q in matched}),
        },
        "syntax_warnings": warnings,
        "advisory": True,
    }


def analyze_html(html_text: str, ledger_quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    articles = re.findall(r"<article\b[^>]*>(.*?)</article>", html_text, re.S)
    results = []
    for i, article in enumerate(articles):
        heading = re.search(r"<h[12][^>]*>(.*?)</h[12]>", article, re.S)
        title = visible_text(heading.group(1)) if heading else f"article-{i + 1}"
        paras_html = re.findall(r"<p[^>]*>(.*?)</p>", article, re.S)
        full = "\n".join(visible_text(p) for p in paras_html)
        results.append(analyze_text(full, title, ledger_quotes))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="后台材料/密度检查（advisory only；材料清单 + 判断词密度）")
    parser.add_argument("path", help="HTML 交付文件或纯文本文件")
    parser.add_argument("--ledger", help="citations-ledger.json 路径（可选）")
    args = parser.parse_args(argv)

    try:
        raw = Path(args.path).read_text(encoding="utf-8")
    except OSError as e:
        print(f"无法读取 {args.path}: {e}", file=__import__("sys").stderr)
        return 2

    ledger_quotes = _ledger_from_path(args.ledger)
    if "<article" in raw:
        results = analyze_html(raw, ledger_quotes)
    else:
        results = [analyze_text(raw, Path(args.path).stem, ledger_quotes)]

    print(json.dumps({
        "advisory": True,
        "note": "试点输出，仅作人工审读参考；不改变任何 gate 状态，不阻断发布。",
        "articles": results,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())