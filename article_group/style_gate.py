"""Style gate: machine-enforced editorial redlines for Ruoyu article batches.

Canonical source of the rules: Allen's verbatim feedback (2026-08-06,
controlled-014) — 读后感/审稿腔句式、来源自证、流程标识 must not appear in
reader-facing article text. This module turns those redlines into a scanner so
future batches are blocked mechanically instead of relying on reviewer luck.

Severity model:
- error   : must be fixed before the article can advance (S5 gate fail)
- warning : needs controller judgment (e.g. comment-vs-film-fact boundary,
            opening hook without a fact anchor)
- info    : process hint (e.g. release-date claim needs version cross-check)

Design principles (from compliance_gate.py heritage):
- Patterns are precise phrases learned from real negative samples, never bare
  generic tokens. "报道" alone is NOT flagged (safe patterns like
  "公开报道只确认了动作和日期" are legitimate); only named-source phrasing and
  the verbatim offending constructions are.
- `scan_style` is a triage signal, not an autonomous editorial verdict. The
  controller reviews hits in context before acting.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

# --------------------------------------------------------------------------
# Redline pattern tables. Each entry: (compiled pattern, label, reason)
# --------------------------------------------------------------------------

# 1) 来源自证 — named-source confession in reader-facing text.
#    Allen 2026-08-06: "不要老是主动招供信息来源……只作为审核时的关闸即可，
#    不用在文章中可以体现" (verbatim). The `data-source` attribute is the
#    audit anchor; visible prose must not name the source outlet.
_SOURCE_SELF_CONFESSION: list[tuple[str, str, str]] = [
    (r"人民时评", "source:人民时评", "来源自证：点名媒体评论栏目"),
    (r"《人民日报》", "source:人民日报", "来源自证：点名媒体"),
    (r"人民日报海外版", "source:人民日报海外版", "来源自证：点名媒体"),
    (r"央视网", "source:央视网", "来源自证：点名媒体"),
    (r"北青网", "source:北青网", "来源自证：点名媒体"),
    (r"羊城晚报", "source:羊城晚报", "来源自证：点名媒体"),
    (r"Mtime", "source:Mtime", "来源自证：点名媒体"),
    (r"报道以[^。]{0,20}为例", "source:报道以…为例", "来源自证：'报道以…为例'句式"),
    (r"报道还(提到|称|说)", "source:报道还", "来源自证：'报道还提到'句式"),
    (r"公开报道还", "source:公开报道还", "来源自证：'公开报道还'句式"),
    (r"在这篇报道的讨论中", "source:在这篇报道", "来源自证：'在这篇报道'句式"),
    (r"公开简介", "source:公开简介", "来源自证：'公开简介'句式"),
    (r"据[^。！？]{0,12}报道", "source:据…报道", "来源自证：'据…报道'句式"),
    (r"资料：", "source:资料行", "来源自证：可见'资料：'来源行"),
]

# 2) 读后感 / 审稿腔 — reviewer self-talk in reader-facing prose.
#    Allen verbatim: "这个说法的重点不在于把观影变成一张消费清单，而在于提醒
#    我们……观众根本不在乎你什么说法，这有点作者或审稿者的自说自话，AI味
#    太重了，更有点像写读后感。"
_READING_REPORT_TONE: list[tuple[str, str, str]] = [
    (r"重点不在于[^。！？]{0,40}?而在于", "tone:重点不在于…而在于", "读后感句式（用户点名）"),
    (r"不在于[^。！？]{0,40}?而在于", "tone:不在于…而在于", "读后感句式同类变体"),
    (r"阅读入口", "tone:阅读入口", "审稿腔：'阅读入口'"),
    (r"事实边界", "tone:事实边界", "审稿腔：'事实边界'"),
    (r"信息到这里已经足够", "tone:信息到这里已经足够", "审稿腔：事实收束自白"),
    (r"这里既是[^。]{0,30}也是", "tone:这里既是…也是", "审稿腔：'这里既是…也是…'"),
    (r"对这部作品的阅读", "tone:对这部作品的阅读", "审稿腔：'对这部作品的阅读'"),
    (r"从这份已公开的简介出发", "tone:从…简介出发", "审稿腔：'从…简介出发'"),
    (r"这个例子让", "tone:这个例子让", "审稿腔：'这个例子让…'总结句"),
    (r"这里的[\"“'][^\"”']{1,14}[\"”']很重要", "tone:这里的X很重要", "审稿腔：'这里的X很重要'"),
    (r"把边界说清楚", "tone:把边界说清楚", "审稿腔：'把边界说清楚'"),
]

# 3) 流程标识 — pipeline artifacts must not leak into reader-facing text.
_PIPELINE_MARKERS: list[tuple[str, str, str]] = [
    (r"候选稿", "pipeline:候选稿", "流程标识：候选稿"),
    (r"CONTROLLED-?\d*", "pipeline:CONTROLLED", "流程标识：批次号"),
    (r"事实边界以", "pipeline:事实边界以", "流程标识：页脚事实边界声明"),
    (r"注：本文参考来源", "pipeline:参考来源注", "流程标识：参考来源脚注"),
]

# 4) 观点-事实边界 — comment judgment written as film fact (八仙篇教训:
#    "重新定义了'仙'的内涵" was 人民时评's comment, not a verified film fact).
#    Generalized word family (P0-2): any judgment verb + abstract-noun target
#    is a signal that comment may have been written as film fact. Warnings
#    (controller judgment), never errors — machine cannot decide semantics.
_COMMENT_AS_FACT: list[tuple[str, str, str]] = [
    (r"重新定义了?[^。！？]{0,16}的内涵", "boundary:重新定义…内涵", "警告：'重新定义…内涵'可能是评论判断而非影片事实"),
    (r"重新定义", "boundary:重新定义", "警告：'重新定义'类判断词，确认是影片事实还是评论观点"),
    (r"(重构|重塑|颠覆|解构|改写了?)[^。！？]{0,16}的(内涵|意义|定义|神话|想象|叙事|表达)", "boundary:判断词+抽象名词", "警告：'重构/重塑/颠覆…的X'可能是评论判断而非影片事实"),
    (r"(拉下|拽下|请下)了?神坛|走下神坛", "boundary:神坛修辞", "警告：'走下神坛'类修辞判断，确认是影片事实还是评论观点"),
]

# 5) 档期/日期断言 — process hint: release-date claims need version
#    cross-check (《不想失去你》教训: 海报 6/5 vs 官宣 8/19, 三次定档).
_DATE_CLAIM = re.compile(
    r"(定档|上映|公映|开画)[^。！？]{0,12}?\d{1,2}月\d{1,2}日|"
    r"\d{1,2}月\d{1,2}日[^。！？]{0,12}?(上映|定档|公映)"
)


def _compile(table: list[tuple[str, str, str]]) -> list[tuple[re.Pattern, str, str]]:
    return [(re.compile(p), label, reason) for p, label, reason in table]


_SOURCE_RULES = _compile(_SOURCE_SELF_CONFESSION)
_TONE_RULES = _compile(_READING_REPORT_TONE)
_PIPELINE_RULES = _compile(_PIPELINE_MARKERS)
_BOUNDARY_RULES = _compile(_COMMENT_AS_FACT)


class _TextParser(HTMLParser):
    """Extract visible text from an HTML fragment (article or full page)."""

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
    """Return visible text of an HTML fragment with whitespace normalized."""
    parser = _TextParser()
    parser.feed(html_fragment)
    parser.close()
    return re.sub(r"\s+", "", "".join(parser.parts))


def _scan_rules(text: str, rules: list[tuple[re.Pattern, str, str]],
                severity: str) -> list[dict[str, str]]:
    hits = []
    for pattern, label, reason in rules:
        for m in pattern.finditer(text):
            hits.append({
                "severity": severity,
                "rule": label,
                "reason": reason,
                "match": m.group(0)[:60],
            })
    return hits


def scan_style(text: str) -> list[dict[str, str]]:
    """Scan visible article text; return all redline hits (triage signal).

    Severities: error (must fix), warning (controller judgment), info (hint).
    """
    hits: list[dict[str, str]] = []
    hits.extend(_scan_rules(text, _SOURCE_RULES, "error"))
    hits.extend(_scan_rules(text, _TONE_RULES, "error"))
    hits.extend(_scan_rules(text, _PIPELINE_RULES, "error"))
    hits.extend(_scan_rules(text, _BOUNDARY_RULES, "warning"))
    date_match = _DATE_CLAIM.search(text)
    if date_match:
        hits.append({
            "severity": "warning",
            "rule": "date:release-claim",
            "reason": "档期断言=档期类最强钩子实例：若本篇 data-hook 最强钩子为档期类，必须做撤档史版本核验（搜该片'定档/撤档/延期'历史，列出每次定档/撤档日期+来源，取最新官宣；海报/票务/旧物料日期不得直接采用）",
            "match": date_match.group(0)[:60],
        })
    return hits


def hook_declaration_check(hook: str, text: str) -> dict[str, Any]:
    """Verify the strongest-hook declaration (P0-3, generalized).

    Every article must declare its strongest verification hook — the single
    fact claim / truth gap most worth checking (撤档史 is only the date-type
    instance for 不想失去你; each article's own strongest hook differs).
    The declaration lives in the <article data-hook="…"> attribute, invisible
    to readers, serving as the audit anchor for reviewers/controller.

    - missing : no declaration — reviewers have no anchor to verify against
    - mismatch: declared keywords do not appear in the article text at all —
                the declaration looks invalid
    - ok      : declared and at least partially grounded in the text
    Severity: warning (controller judgment), never a blocker by itself.
    """
    if not hook:
        return {
            "status": "missing",
            "reason": "未声明最强钩子（data-hook）：审查无从核验。须声明本篇最值得核查的事实断言/真相缺口（档期类钩子须做撤档史版本核验：定档/撤档/延期史+来源+最新官宣）",
            "hook": "",
        }
    keys = [k for k in re.split(r"[，,、:：;；\s]+", hook) if len(k) >= 2]
    present = [k for k in keys if k in text]
    if not present:
        return {
            "status": "mismatch",
            "reason": f"最强钩子声明与正文不符：{keys} 均未出现在正文——声明疑似无效",
            "hook": hook[:80],
        }
    unmatched = [k for k in keys if k not in text]
    return {
        "status": "ok",
        "reason": f"最强钩子已声明且正文可锚定（未匹配: {unmatched or '无'}）",
        "hook": hook[:80],
    }


def opening_hook_check(paragraphs: list[str]) -> dict[str, Any]:
    """Check the first paragraph for a 3-second hook (Canon 结构原则1, P0-1).

    The opening must give the reader a reason to continue: a fact anchor
    (named work 《…》, a date, a quantity claim, an organization), a suspense
    signal (question, 为什么/怎么/到底/居然…), or a contrast structure
    (不是…而是…). Pure atmosphere prose — however long — is flagged as a
    warning (reader has no reason to continue in 3 seconds). Length alone is
    NOT an anchor: a 60-char mood sentence is still a mood sentence.
    """
    if not paragraphs:
        return {"status": "no_paragraphs"}
    first = paragraphs[0][:80]
    anchor = (
        re.search(r"[《》]", first)                      # 专名（作品）
        or re.search(r"\d{1,2}月\d{1,2}日", first)       # 日期
        or re.search(r"(\d+[个部届人天年次座轮批月])", first)  # 数量断言/时间（非序号）
        or re.search(r"(国家电影局|商务部|文旅|联盟|协会|委员会|影院|片方)", first)  # 机构
        or re.search(r"[？?]", first)                    # 悬念：问句
        or re.search(r"为什么|怎么|到底|究竟|居然|竟然|意外|反转", first)  # 悬念/反差词
        or re.search(r"不是[^。！？]{1,16}(而是|，是)", first)  # 反差结构
    )
    return {
        "status": "ok" if anchor else "warning",
        "reason": ("开头含3秒钩子（事实锚点/悬念/反差）"
                   if anchor else
                   "开头疑似纯意境句，无事实锚点、悬念或反差（Canon：先甩结果/事实，不从背景铺开）"),
        "first_40": first[:40],
    }


# 标题缺口信号（P3）：问号 / 悬念词 / 反差结构 / 数字 / 专名。
# Canon 标题原则：标题制造读者想验证的心理缺口（误会/真相/秘密/情绪/悬念），
# 至少命中一个。
_TITLE_GAP_SIGNALS = (
    r"[？?]",
    r"为什么|怎么|到底|究竟|还能|终于|还在|变了|这次|居然|竟然|意外|反转|难得|稀罕",
    r"不是[^，。]{1,12}，是",
    r"\d",
    r"[《]",
    r"秘密|真相|悬念|误会|遗憾|错过|可能|或许",
)


def title_gap_check(title: str) -> dict[str, Any]:
    """Check a title for at least one psychological-gap signal (P3)."""
    if not title:
        return {"status": "no_title"}
    signals = [p for p in _TITLE_GAP_SIGNALS if re.search(p, title)]
    return {
        "status": "ok" if signals else "warning",
        "reason": (f"标题含缺口信号: {signals}"
                   if signals else
                   "标题无缺口信号（问号/悬念词/反差/数字/专名至少其一）——读者缺少点开理由"),
        "title": title[:60],
    }


def fact_density_check(paragraphs: list[str]) -> dict[str, Any]:
    """Estimate fact-base thickness per article (P2: 八仙篇事实底座最薄教训).

    A paragraph counts as a fact anchor if it carries a work name 《…》, a
    number, a date (X月Y日), an organization name (…局/…部/…联盟/…协会), or a
    person title (监制/导演/编剧/主演). If fewer than ~1/3 of paragraphs are
    anchored, the piece likely floats on interpretation alone — a warning, not
    an error (short commentary pieces may legitimately be denser in prose).
    """
    if not paragraphs:
        return {"status": "no_paragraphs"}
    anchored = 0
    for p in paragraphs:
        if (
            re.search(r"[《》]", p)
            or re.search(r"\d{1,2}月\d{1,2}日", p)            # 具体日期
            or re.search(r"(\d+[个部届人天年次座轮批月])", p)  # 数量断言/时间（非序号）
            or re.search(r"(国家电影局|商务部|文旅|联盟|协会|委员会)", p)
            or re.search(r"监制|导演|编剧|主演", p)
        ):
            anchored += 1
    ratio = anchored / len(paragraphs)
    return {
        "status": "ok" if ratio >= 1 / 3 else "warning",
        "reason": (f"事实锚点段落 {anchored}/{len(paragraphs)} (≥1/3)"
                   if ratio >= 1 / 3 else
                   f"事实锚点段落仅 {anchored}/{len(paragraphs)} (<1/3)——事实底座偏薄，多为感受/解读段（P2 教训）"),
        "anchored_paragraphs": anchored,
        "total_paragraphs": len(paragraphs),
    }


def validate_batch_style(html_text: str) -> dict[str, Any]:
    """Validate a full delivery HTML: per-article scan + global pipeline scan.

    Returns a dict with per-article results and an overall pass/fail. Fail
    means at least one `error`-severity hit in reader-facing text.
    """
    articles = re.findall(r"<article\b([^>]*)>(.*?)</article>", html_text, re.S)
    h2s = re.findall(r"<h2[^>]*>(.*?)</h2>", html_text, re.S)
    titles = [visible_text(h) for h in h2s]
    per_article: list[dict[str, Any]] = []
    for i, (attrs, article) in enumerate(articles):
        title = titles[i] if i < len(titles) else f"article-{i + 1}"
        paras_html = re.findall(r"<p[^>]*>(.*?)</p>", article, re.S)
        paras = [visible_text(p) for p in paras_html]
        full = "".join(paras)
        hits = scan_style(full)
        hook = opening_hook_check(paras)
        hook_match = re.search(r'data-hook="([^"]*)"', attrs)
        per_article.append({
            "index": i + 1,
            "title": title,
            "char_count": len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", full)),
            "hits": hits,
            "hit_count": len(hits),
            "error_count": sum(1 for h in hits if h["severity"] == "error"),
            "opening_hook": hook,
            "title_gap": title_gap_check(title),
            "fact_density": fact_density_check(paras),
            "hook_declaration": hook_declaration_check(
                hook_match.group(1) if hook_match else "", full),
        })
    global_hits = _scan_rules(visible_text(html_text), _PIPELINE_RULES, "error")
    errors = [h for a in per_article for h in a["hits"]
              if h["severity"] == "error"] + global_hits
    return {
        "article_count": len(per_article),
        "articles": per_article,
        "global_hits": global_hits,
        "pass": len(errors) == 0,
        "error_total": len(errors),
    }


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    if len(sys.argv) != 2:
        print("usage: python -m article_group.style_gate <delivery.html>")
        sys.exit(2)
    result = validate_batch_style(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["pass"] else 1)
