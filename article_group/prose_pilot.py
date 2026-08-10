"""prose_pilot: 试点版「材料-推进-句法」后台写作检查（human-writing 吸收，v1）。

来源
----
本模块吸收 human-writing（github.com/KKKKhazix/human-writing，commit 4fda173f）
的三类能力，改写为若雨随影后台试点工具：
  1. 材料清单前置（原 SKILL.md 材料门槛）：写前/评审时核对可追溯材料是否足够。
  2. 段落新增量（原 SKILL.md 段落推进）：每段是否带来新事实/动作/例子/后果。
  3. 句法软警告（原 scripts/check_prose.py 的 warning 层）：
     同构排比、句长过齐、段落开场重复、洞察路标过密、抒情词过密、长前置成分。

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
import statistics
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
# 段落推进检测
# --------------------------------------------------------------------------
# 内容段：以汉字开头、长度 >= 30 字的段落参与推进检测（排除标题/导语/页脚）。
# 推进信号：新事实锚点、新数字/日期、动作动词、结果/后果、举例、转折、
# 人物/作品专名、问句。原文复述（段首是引号/原话）或纯感受重复判为停滞。
_PARA_MIN_LEN = 30
_ADVANCE_SIGNALS = [
    re.compile(r"[《》]"),
    re.compile(r"\d{1,2}月\d{1,2}日|\d{4}年"),
    re.compile(r"\d+(?:\.\d+)?[万千万亿个部届人天年次座轮批月元%％]"),
    re.compile(r"(宣布|发布|官宣|定档|上映|开售|上线|开播|上线|推出|启动|落地|成立|签约|投产|完成|通过|获批)"),
    re.compile(r"(导演|编剧|主演|监制|饰演|出演|担任|加盟)"),
    re.compile(r"(导致|使得|带来|变成|引发|推动|挤压|淘汰|改写|翻盘|崩了|救了|成了)"),
    re.compile(r"(例如|比如|举例|以[^。！？]{1,16}为例|还有[^。！？]{1,16}(也在|同样|跟着))"),
    re.compile(r"(但|不过|然而|偏偏|讽刺的是|有意思的是|没想到|结果)"),
    re.compile(r"[？?]"),
]
_PAUSE_SIGNALS = [
    re.compile(r"^(“[^”]{2,40}”|『[^』]{2,40}』|“[^”]{2,40}$)"),  # 原话复述开头
    re.compile(r"(还是那句话|说到底|归根结底|也就是说|换句话说)"),
    re.compile(r"(这里|上文|前面|刚才|正如前文|如前面所)"),
]

# 段落开场重复：相邻内容段中，开场 6 字完全相同视为重复开场。
_OPENER_LEN = 6


def _han_len(text: str) -> int:
    return len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))


def _is_content_para(p: str) -> bool:
    if _han_len(p) < _PARA_MIN_LEN:
        return False
    return bool(re.match(r"^[\u3400-\u4dbf\u4e00-\u9fff“”‘’『』「」《》\d这那]", p))


def _para_advance_status(p: str) -> dict[str, Any]:
    """单段推进判断：has_new / pause / thin。"""
    signals = [pat.search(p) for pat in _ADVANCE_SIGNALS]
    hits = [m.group(0)[:24] for m in signals if m]
    pauses = [pat.search(p) for pat in _PAUSE_SIGNALS]
    pause_hits = [m.group(0)[:24] for m in pauses if m]
    if pause_hits:
        return {"verdict": "pause", "hits": hits, "pause_hits": pause_hits}
    if hits:
        return {"verdict": "has_new", "hits": hits, "pause_hits": []}
    return {"verdict": "thin", "hits": [], "pause_hits": []}


def _opener(p: str) -> str:
    stripped = re.sub(r"^(“|『|「)", "", p)
    return stripped[:_OPENER_LEN]


# --------------------------------------------------------------------------
# 句法软警告（从 check_prose.py 的 warning 层移植，改为本项目口径）
# --------------------------------------------------------------------------
_JUDGMENT_MARKERS = ("真正", "其实", "本质上", "说到底", "归根结底", "关键在", "重点在")
_LYRIC_WORDS = ("时光", "岁月", "梦想", "温柔", "治愈", "感动", "力量",
                "光", "温度", "答案", "意义", "瞬间", "我们", "人生")
_LONG_LEFT = re.compile(r"[，,][^，。！？]{18,}[的地得]")


def _sentence_lengths(text: str) -> list[int]:
    return [len(s) for s in re.split(r"[。！？!?]", text) if _han_len(s) >= 4]


def _anaphora_windows(text: str) -> list[str]:
    """同句内三连以上同构小句（以相同 2 字开头），返回示例。"""
    windows = []
    for m in re.finditer(r"[^。！？]{8,80}", text):
        seg = m.group(0)
        clauses = re.split(r"[，,；;：:]", seg)
        if len(clauses) < 3:
            continue
        head = [re.sub(r"^(“|『)", "", c)[:2] for c in clauses]
        for i in range(len(head) - 2):
            if head[i] and head[i] == head[i + 1] == head[i + 2]:
                windows.append(seg[:60])
                break
    return windows


def _syntax_warnings(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    # 1) 同构排比
    for w in _anaphora_windows(text)[:3]:
        out.append({"signal": "同构排比", "detail": w})
    # 2) 句长变异系数过低（句子过于整齐）
    lens = _sentence_lengths(text)
    if len(lens) >= 8:
        cv = statistics.pstdev(lens) / (statistics.mean(lens) or 1)
        if cv < 0.42:
            out.append({
                "signal": "句长过齐",
                "detail": f"变异系数 {cv:.2f} (<0.42)，共 {len(lens)} 句——长短句差距小，节奏像机器排的",
            })
    # 3) 洞察路标/抒情词过密
    for marker in _JUDGMENT_MARKERS:
        n = text.count(marker)
        if n >= 3:
            out.append({"signal": "洞察路标", "detail": f"“{marker}”出现 {n} 次"})
    for word in _LYRIC_WORDS:
        n = text.count(word)
        if n >= 4:
            out.append({"signal": "抒情词过密", "detail": f"“{word}”出现 {n} 次"})
    # 4) 长前置成分（主干出现晚）
    long_left = [m.group(0)[:40] for m in _LONG_LEFT.finditer(text)][:3]
    if long_left:
        out.append({"signal": "长前置成分", "detail": "；".join(long_left)})
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
def analyze_text(text: str, title: str, ledger_quotes: list[dict[str, Any]]) -> dict[str, Any]:
    paragraphs = [p for p in re.split(r"\n+", text) if p.strip()]
    paras = [re.sub(r"^[#\-\d\.、\s]+", "", p).strip() for p in paragraphs]
    paras = [p for p in paras if _is_content_para(p)]

    # 段落推进
    adv = [_para_advance_status(p) for p in paras]
    thin = [i + 1 for i, a in enumerate(adv) if a["verdict"] == "thin"]
    pauses = [i + 1 for i, a in enumerate(adv) if a["verdict"] == "pause"]

    # 开场重复
    repeat_openers: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for i, p in enumerate(paras):
        op = _opener(p)
        if op in seen and i - seen[op] <= 3:
            repeat_openers.append({"para": i + 1, "opener": op,
                                   "first_seen": seen[op] + 1})
        else:
            seen.setdefault(op, i)

    # 材料清单
    counts = _claim_material_counts(text)
    matched: list[dict[str, Any]] = []
    for quote in ledger_quotes:
        if _ledger_quote_match(text, quote["text"]):
            matched.append(quote)

    # 句法软警告
    warnings = _syntax_warnings(text)

    return {
        "title": title,
        "chars": _han_len(text),
        "content_paragraphs": len(paras),
        "material": {
            "anchors": counts,
            "anchor_total": sum(counts.values()),
            "bare_threshold": _MATERIAL_BARE_MIN,
            "below_threshold": sum(counts.values()) < _MATERIAL_BARE_MIN,
            "ledger_matched_quotes": len(matched),
            "matched_sources": sorted({f"{q['source_id']}:{q['title'][:30]}" for q in matched}),
        },
        "progression": {
            "thin_paragraphs": thin,
            "pause_paragraphs": pauses,
            "repeated_openers": repeat_openers,
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
    parser = argparse.ArgumentParser(description="试点版材料-推进-句法后台检查（advisory only）")
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
