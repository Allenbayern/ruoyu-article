"""Style gate: machine-enforced editorial redlines for Ruoyu article batches.

Canonical source of the rules: Allen's verbatim feedback (2026-08-06,
controlled-014) — 读后感/审稿腔句式、来源自证、流程标识 must not appear in
reader-facing article text. This module turns those redlines into a scanner so
future batches are blocked mechanically instead of relying on reviewer luck.

Severity model:
- error   : must be fixed before the article can advance (S5 gate fail)
- warning : needs controller judgment (e.g. comment-vs-film-fact boundary,
            opening hook without a fact anchor)
- info    : process hint (e.g. ordinary release-date claims need a current
            date-source check; explicit release-history wording gets a
            conditional history hint)

Design principles (from compliance_gate.py heritage):
- Patterns are precise phrases learned from real negative samples, never bare
  generic tokens. "报道" alone is NOT flagged (safe patterns like
  "公开报道只确认了动作和日期" are legitimate); only named-source phrasing and
  the verbatim offending constructions are.
- `scan_style` is a triage signal, not an autonomous editorial verdict. The
  controller reviews hits in context before acting.
"""

from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path
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
    # 泛化媒体名+报道转述句式（controlled-016 教训 B3：初稿 3 处违规全部人工发现）
    (r"[一-龥]{2,8}(财经|商报|新闻|日报|晚报|周刊|快报|电视台)[^。！？]{0,4}在报道[中里]",
     "source:媒体在报道中", "来源自证：点名媒体+在报道中转述（新浪财经在报道中评价/北京商报在报道里用了一个词）"),
    (r"[一-龥]{2,8}(财经|商报|新闻|日报|晚报|周刊|快报|电视台)在(梳理|盘点|回顾)[^。！？]{0,12}(时|中)",
     "source:媒体在梳理", "来源自证：点名媒体+在梳理…时转述（荔枝新闻在梳理这场风波时）"),
    (r"(?:本文|本稿|这篇文章)[^。！？；]{0,24}(?:发布信息|资料介绍)",
     "source:发布信息自述", "来源自证：文章主体把发布信息/资料介绍写成后台说明"),
    (r"资料介绍", "source:资料介绍自述", "来源自证：'资料介绍'是素材/流程自述，不是读者内容"),
    # 2026-09-16 读者面自证扩展（daily-006 教训）：稿件形态词+媒体名点名、
    # "补了关键细节"式来源补充说明——归因与原文核对属于后台账本。
    (r"补了[^。！？]{0,6}关键细节", "source:补了关键细节", "来源自证：'补了…关键细节'是来源补充说明，属于后台账本"),
    (r"[一-龥]{2,10}(之家|娱乐|电影网|财经|商报|新闻|日报|晚报|周刊|快报|电视台)的(通稿|奖单|文案|导语|报道|介绍)",
     "source:媒体+稿件词", "来源自证：点名媒体并标注通稿/奖单等稿件形态"),
    (r"(通稿|奖单|文案|新闻导语)把", "source:通稿把", "来源自证：'通稿把…'转述句式"),
    (r"(通稿|奖单|文案|导语)(写的是|写道|介绍|概括)", "source:通稿写的是", "来源自证：'通稿写的是…'转述句式"),
]

# Ambiguous editorial framing is a controller warning rather than an automatic
# error: "行业观察" can be a legitimate column label, but often leaks the
# writer's backstage framing into a reader-facing sentence.
_SOURCE_CONTEXT_WARNING: list[tuple[str, str, str]] = [
    (r"行业观察", "source:行业观察", "可能是后台栏目/审稿框架用语，需改成具体事实或明确观点"),
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
    # 2026-09-16 元观察句（读者面自证扩展）
    (r"这是[^。！？]{0,14}(呈现|写出)的观感", "tone:观感自白", "元观察句：向读者解释自己的写作判断"),
    (r"不是来源里写明的", "tone:来源写明自白", "元观察句：'不是来源里写明的…'"),
    (r"来源里(写明|写|没有|并未|无)", "tone:来源提及", "读者面来源提及：来源核对属于后台账本"),
]

# 2b) 自我提醒句 — writing-process reminders leaked into reader-facing text.
#    Allen 2026-08-12 (controlled-018, verbatim): "还没上映的电影，不能提前
#    写出它的票房……这句话在文章中有什么意义吗，这不就是你提醒自己的一句话吗？
#    我希望这些要求能记下来，不能每次都让我提醒。" Redline is NOT the boundary
#    itself (预测/口碑/制式/观看条件 口径是合规内容), it is the REMINDER
#    phrasing addressed at the writer: "还没上映…不能提前写出…", "这条边界
#    不难写，却很容易被忘掉" — internal self-talk, not article content.
_SELF_REMINDER: list[tuple[str, str, str]] = [
    (r"还没上映的电影，不能提前写出它的票房", "tone:未上映提醒句", "自我提醒句（用户点名）：写作要求不得出现在正文"),
    (r"不能提前写出[^。！？]{0,12}票房", "tone:不能提前写票房", "自我提醒句：'不能提前写出…票房'变体"),
    (r"这条边界不难写", "tone:边界自白", "自我提醒句：'这条边界不难写'是写作提醒不是内容"),
    (r"很容易在(热搜|转发|讨论)里被忘掉", "tone:易被忘掉自白", "自我提醒句：'很容易被忘掉'是写作提醒不是内容"),
]

# 2c) 编辑/审核自证 — source and fact-checking workflow language leaked
#     into reader-facing prose.  This is intentionally a combination rule:
#     ordinary attribution ("公开报道只确认了…") remains valid, while a
#     writer/editor subject claiming that the article was audited and released
#     is an internal production statement, not reader-facing content.
_EDITORIAL_SELF_ATTESTATION: list[tuple[str, str, str]] = [
    (
        r"(?:本文|本稿|本篇文章|这篇文章)[^。！？；]{0,24}"
        r"(?:来源审计|来源核验|来源审核|事实核查|事实核验|事实审核|证据审计|证据核验)",
        "tone:editorial-self-attestation",
        "后台审核自证：文章主体声称已完成来源/事实审核",
    ),
    (
        r"(?:编辑部|新闻室)[^。！？；]{0,24}"
        r"(?:来源审计|来源核验|来源审核|事实核查|事实核验|事实审核|证据审计|证据核验)",
        "tone:editorial-self-attestation",
        "后台审核自证：编辑/新闻室声称已完成来源/事实审核",
    ),
    (
        r"(?:编辑部|新闻室)[^。！？；]{0,24}"
        r"(?:核验|核查|审核|审计)[^。！？；]{0,16}"
        r"(?:发布|刊发|出稿|推出)",
        "tone:editorial-self-attestation",
        "后台发布自证：编辑/新闻室把审核流程写成发布说明",
    ),
]

# 3) 流程标识 — pipeline artifacts must not leak into reader-facing text.
_PIPELINE_MARKERS: list[tuple[str, str, str]] = [
    (r"候选稿", "pipeline:候选稿", "流程标识：候选稿"),
    (r"CONTROLLED-?\d*", "pipeline:CONTROLLED", "流程标识：批次号"),
    (r"事实边界以", "pipeline:事实边界以", "流程标识：页脚事实边界声明"),
    (r"注：本文参考来源", "pipeline:参考来源注", "流程标识：参考来源脚注"),
    # 2026-09-16 过程框架与免责句（读者面自证扩展）
    (r"从事实层面看", "pipeline:从事实层面看", "过程框架句：向审核者说明，不是向读者讲述"),
    (r"目前能确认的只有", "pipeline:能确认的只有", "过程框架句：'目前能确认的只有…'"),
    (r"官方口径", "pipeline:官方口径", "后台免责用语：'官方口径'"),
    (r"不构成对[^。！？]{0,12}的承诺", "pipeline:不构成承诺", "免责声明句：证据边界属于后台账本"),
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

# 5) 档期/日期断言 — conditional process hints, never a hidden gate.
#    Ordinary date claims only need the current date source checked. Explicit
#    release-history wording gets a separate conditional history hint.
_DATE_CLAIM = re.compile(
    r"(定档|上映|公映|开画)[^。！？]{0,12}?\d{1,2}月\d{1,2}日|"
    r"\d{1,2}月\d{1,2}日[^。！？]{0,12}?(上映|定档|公映)"
)
_RELEASE_HISTORY_CLAIM = re.compile(
    r"(撤档|改档|提档|延期|重定档|反复定档)"
)

# 5b) 无源断言启发式 — unsourced inference patterns (controlled-016 教训 B4:
#     "周星驰当时四十一岁" 年份/年龄推算无源易错；"零大规模路演" 单源不支撑的
#     修饰断言。warning (controller judgment) — machine cannot decide
#     semantics; these are triage signals, not blockers.
_UNSOURCED_CLAIM: list[tuple[str, str, str]] = [
    (r"(当时|彼时|那年|时年|年方)[一二三四五六七八九十百千万零〇两]{1,6}岁",
     "claim:age-inference", "警告：年龄/年份推算（'当时四十一岁'类）——推算无源易错，须核验或删除"),
    (r"零[^。！？]{0,12}(宣发|路演|宣传|推广|营销)",
     "claim:zero-modifier", "警告：'零…'修饰断言（'零大规模路演'类）——单源不支撑的修饰性断言宁可删"),
]

# 6) 中文数字锚点 — fact density / opening hook anchors in Chinese numerals
#    (controlled-016 教训 A4: "三千六百五十万"/"八月六日"/"二〇二二年" 不锚定,
#    初稿被迫改写阿拉伯数字，写作风格受工具限制).
_CN_NUM = r"[一二三四五六七八九十百千万亿零〇两]"
_CN_QUANTITY = re.compile(rf"{_CN_NUM}{{2,10}}[个部届人天年次座轮批月万]")
_CN_DATE = re.compile(rf"{_CN_NUM}{{1,2}}月{_CN_NUM}{{1,3}}日")


def _cn_anchored(text: str) -> bool:
    """True if text carries a Chinese-numeral fact anchor (date or quantity)."""
    return bool(_CN_DATE.search(text) or _CN_QUANTITY.search(text))


def _compile(table: list[tuple[str, str, str]]) -> list[tuple[re.Pattern, str, str]]:
    return [(re.compile(p), label, reason) for p, label, reason in table]


_SOURCE_RULES = _compile(_SOURCE_SELF_CONFESSION)
_TONE_RULES = _compile(
    _READING_REPORT_TONE + _SELF_REMINDER + _EDITORIAL_SELF_ATTESTATION
)
_PIPELINE_RULES = _compile(_PIPELINE_MARKERS)
_BOUNDARY_RULES = _compile(_COMMENT_AS_FACT)
_UNSOURCED_RULES = _compile(_UNSOURCED_CLAIM)
_SOURCE_CONTEXT_WARNING_RULES = _compile(_SOURCE_CONTEXT_WARNING)


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
    Release-specific hints are conditional and info-only: a normal release
    date claim asks for a current date-source check, while explicit wording
    about release changes asks for a release-history check. Neither is a
    general requirement or a final_review pending trigger.
    """
    hits: list[dict[str, str]] = []
    hits.extend(_scan_rules(text, _SOURCE_RULES, "error"))
    hits.extend(_scan_rules(text, _TONE_RULES, "error"))
    hits.extend(_scan_rules(text, _PIPELINE_RULES, "error"))
    hits.extend(_scan_rules(text, _BOUNDARY_RULES, "warning"))
    hits.extend(_scan_rules(text, _UNSOURCED_RULES, "warning"))
    hits.extend(_scan_rules(text, _SOURCE_CONTEXT_WARNING_RULES, "warning"))
    date_match = _DATE_CLAIM.search(text)
    if date_match:
        hits.append({
            "severity": "info",
            "rule": "date:release-claim",
            "reason": "普通上映/定档日期断言：只需核对当前日期来源，不要求撤档史核验",
            "match": date_match.group(0)[:60],
        })
    history_match = _RELEASE_HISTORY_CLAIM.search(text)
    if history_match:
        hits.append({
            "severity": "info",
            "rule": "release-history:claim",
            "reason": "正文明确出现档期变更历史叙事：提示核对相关历史来源；仅作条件性信息提示，不构成通用门禁",
            "match": history_match.group(0)[:60],
        })
    return hits


def hook_declaration_check(hook: str, text: str) -> dict[str, Any]:
    """Verify the strongest-hook declaration (P0-3, generalized).

    Every article must declare its strongest verification hook — the single
    fact claim / truth gap most worth checking. The declaration is generic:
    a release-date mention does not automatically require a release-history
    declaration; explicit release-history wording is handled by the
    conditional info hint in ``scan_style``.
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
            "reason": "未声明最强钩子（data-hook）：审查无从核验。须按本篇实际主题声明最值得核查的事实断言/真相缺口；档期/上映日期不会自动要求撤档史核验",
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
        or _cn_anchored(first)                           # 中文数字日期/数量锚点（016 A4）
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


# 标题缺口信号（P3）：问号 / 悬念词 / 反差结构 / 数字。
# Canon 标题原则：标题制造读者想验证的心理缺口（误会/真相/秘密/情绪/悬念），
# 至少命中一个。
_TITLE_GAP_SIGNALS = (
    r"[？?]",
    r"为什么|怎么|到底|究竟|还能|终于|还在|变了|这次|居然|竟然|意外|反转|难得|稀罕",
    r"不是[^，。]{1,12}，是",
    r"\d",
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
                   "标题无缺口信号（问号/悬念词/反差/数字至少其一）——读者缺少点开理由"),
        "title": title[:60],
    }


# 薄小节检查（2026-09-16，daily-008 扩写实验）：
# 该期原稿 1032 字，两个小节各只有 111 字（"6.7分"节＝分数+票房+三个差评词，
# "姜文没变"节＝一句标题式判断），是把本该展开的机制压成了提纲。
# 同材料扩写版与补料版的最薄小节分别为 210 / 215 字，门禁全绿。
# 判据：任一 H2+ 小节正文 < 150 CJK 字 → warning（补材料或合并小节，不放行空转）。
THIN_SECTION_MIN_CJK = 150
_CJK_COUNT_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def _markdown_sections(markdown_text: str) -> list[tuple[str, int]]:
    """Return (heading, body CJK count) for every H2+ section."""
    sections: list[tuple[str, int]] = []
    heading: str | None = None
    body: list[str] = []
    frontmatter = False
    for index, raw_line in enumerate(markdown_text.splitlines()):
        line = raw_line.strip()
        if index == 0 and line == "---":
            frontmatter = True
            continue
        if frontmatter:
            if line == "---":
                frontmatter = False
            continue
        match = re.match(r"^#{2,6}\s+(.+?)\s*$", raw_line)
        if match:
            if heading is not None:
                sections.append((heading, len(_CJK_COUNT_RE.findall("".join(body)))))
            heading = _markdown_visible_text(match.group(1))
            body = []
            continue
        if heading is not None:
            body.append(line)
    if heading is not None:
        sections.append((heading, len(_CJK_COUNT_RE.findall("".join(body)))))
    return sections


def thin_section_check(
    sections: list[tuple[str, int]],
    *,
    minimum: int = THIN_SECTION_MIN_CJK,
) -> dict[str, Any]:
    """Flag outline-style sections that carry too little text to explain anything."""
    if not sections:
        return {"status": "info", "reason": "无 H2 小节：按单段文本判定", "sections": []}
    thin = [
        {"heading": heading, "cjk": count}
        for heading, count in sections
        if count < minimum
    ]
    if thin:
        detail = "、".join(f"{item['heading']}({item['cjk']}字)" for item in thin)
        return {
            "status": "warning",
            "reason": f"薄小节 {len(thin)}/{len(sections)} 节 <{minimum} CJK 字：{detail}"
                      "——该节缺材料展开，应补材料或合并小节",
            "thin_sections": thin,
            "sections": len(sections),
        }
    counts = [count for _, count in sections]
    return {
        "status": "ok",
        "reason": f"最薄小节 {min(counts)} CJK 字 (≥{minimum})",
        "thin_sections": [],
        "sections": len(sections),
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
            or _cn_anchored(p)                                # 中文数字日期/数量锚点（016 A4）
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


# 结尾互动问句（爆文视角候选观察⑦，2026-08-16 入规则）：
# 「结尾可留互动问句提评论率」——021–025 十篇 + 026 两篇连续空转，
# 仅入规则日志不足驱动执行，故落为机械检查点。检测对象 = 文章末段
# （不含 .sources 引用附录）。读者侧互动问句 = 以问号收尾 + 第二人称
# 或祈使性互动词（你/你们/大家/来/愿意/会）。
_CLOSING_QUESTION = re.compile(r"[？?]\s*$")
_CLOSING_READER_WORD = re.compile(r"(你|你们|大家|愿意|会去|来聊聊|你会|你还会)")
_CLOSING_ACCEPTABLE = re.compile(
    r"(你|你们|大家|愿意|会去|来聊聊|你会|你还会)[^。！？]{0,24}[？?]"
)


def closing_interaction_check(paragraphs: list[str]) -> dict[str, Any]:
    """Check the final paragraph for a reader-facing interaction question (⑦).

    Candidate observation ⑦ (viral-lens, research_only): an ending question
    addressed to the reader ("你会去看吗"/"你还会回信吗") is the strongest
    comment-rate lever identified across 021–025 and consistently missing.
    Severity: info — a suggestion, never a blocker (factual-boundary wording
    must stay intact; articles whose ending is a definitive fact statement
    may legitimately omit a question).
    """
    if not paragraphs:
        return {"status": "no_paragraphs"}
    last = paragraphs[-1]
    ends_with_question = bool(_CLOSING_QUESTION.search(last))
    has_reader_word = bool(_CLOSING_READER_WORD.search(last))
    # 直接匹配 互动词+问号 组合；宽松回退：末段本身即以问号收尾且含互动词
    acceptable = bool(_CLOSING_ACCEPTABLE.search(last)) or (
        ends_with_question and has_reader_word
    )
    if acceptable:
        return {
            "status": "ok",
            "reason": "末段含读者互动问句（候选观察⑦：结尾互动问句提评论率）",
            "last_40": last[-40:],
        }
    return {
        "status": "info",
        "reason": ("末段无读者互动问句（候选观察⑦，research_only 建议）："
                   "可考虑以'你会…吗''你还会…吗'类读者问句收尾提评论率——"
                   "不违反事实边界时执行；结论性收尾可不改"),
        "last_40": last[-40:],
    }


def validate_batch_style(html_text: str) -> dict[str, Any]:
    """Validate a full delivery HTML: per-article scan + global pipeline scan.

    Returns a dict with per-article results and an overall pass/fail. Fail
    means at least one `error`-severity hit in reader-facing text.
    """
    articles = re.findall(r"<article\b([^>]*)>(.*?)</article>", html_text, re.S)
    per_article: list[dict[str, Any]] = []
    for i, (attrs, article) in enumerate(articles):
        # 文末「资料来源」引用附录（.sources）：Allen 2026-08-15 明确要求
        # 「资料来源区建议保留；正式发布时最好做成可点击的一手链接」。
        # 来源自证红线（正文不点名媒体）不适用于该引用附录；tone/pipeline/
        # boundary 规则仍照扫两区。
        src_match = re.search(r'(<div class="sources">.*?</div>)', article, re.S)
        body_html, sources_html = (article, "")
        if src_match:
            body_html = article[:src_match.start()] + article[src_match.end():]
            sources_html = src_match.group(1)
        # 标题约定：每篇 <article> 内一个 h1 或 h2 作标题，取第一个出现的
        # 标题标签；多个标题标签并存属不合规交付（行为为取第一个），
        # 绝不跨文章串用全局 h2 索引（h1/h2 混用或数量不一时会错位）。
        heading_match = re.search(r"<h[12][^>]*>(.*?)</h[12]>", article, re.S)
        title = (visible_text(heading_match.group(1)) if heading_match
                 else f"article-{i + 1}")
        paras_html = re.findall(r"<p([^>]*)>(.*?)</p>", body_html, re.S)
        paras = [
            visible_text(inner)
            for attrs, inner in paras_html
            if not re.search(r'''\bclass\s*=\s*["'][^"']*\bkicker\b''', attrs, re.I)
        ]
        full = "".join(paras)
        hits = scan_style(full)
        if sources_html:
            src_paras = [visible_text(p)
                         for p in re.findall(r"<p[^>]*>(.*?)</p>", sources_html, re.S)]
            src_full = "".join(src_paras)
            hits.extend(_scan_rules(src_full, _TONE_RULES, "error"))
            hits.extend(_scan_rules(src_full, _PIPELINE_RULES, "error"))
            hits.extend(_scan_rules(src_full, _BOUNDARY_RULES, "warning"))
        hook = opening_hook_check(paras)
        # ``data-hook`` is the canonical hook anchor.  ``data-topic`` remains
        # accepted for compatibility with the intermediate public-safe runs;
        # neither attribute may carry internal evidence-ledger names.
        hook_match = re.search(r'(?:data-hook|data-topic)="([^"]*)"', attrs)
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
            "closing_interaction": closing_interaction_check(paras),
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


def _markdown_visible_text(value: str) -> str:
    """Remove Markdown presentation syntax while retaining reader text."""
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", value)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"(?:\*\*|__|~~|\*|_)", "", text)
    text = re.sub(r"^\s{0,3}(?:[-*+]\s+|>\s+|\d+[.)]\s+)", "", text)
    return re.sub(r"\s+", "", text)


def _markdown_title_and_paragraphs(markdown_text: str) -> tuple[str, list[str], str, str]:
    """Return the first H1 title, body paragraphs, and an optional hook marker."""
    lines = markdown_text.splitlines()
    title = ""
    title_index: int | None = None
    hook = ""
    content_lines: list[str] = []
    in_frontmatter = False
    frontmatter_seen = False
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if index == 0 and line == "---":
            in_frontmatter = True
            frontmatter_seen = True
            continue
        if in_frontmatter:
            if line == "---":
                in_frontmatter = False
                continue
            hook_match = re.match(r"(?:hook|data-hook)\s*:\s*(.+)$", line, re.I)
            if hook_match:
                hook = hook_match.group(1).strip()
            continue
        if not title:
            heading = re.match(r"^#\s+(.+?)\s*$", raw_line)
            if heading:
                title = _markdown_visible_text(heading.group(1))
                title_index = index
                continue
        content_lines.append(raw_line)

    if not title:
        title = "article-1"

    blocks: list[list[str]] = []
    heading_lines: list[str] = []
    current: list[str] = []
    for raw_line in content_lines:
        if not raw_line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        if re.match(r"^#{2,6}\s+", raw_line):
            if current:
                blocks.append(current)
                current = []
            # 2026-09-15（B3 口径修正）：小标题是结构，不是段落。此前把 H2 当成独立
            # 段落计入 fact_density 分母，系统性低估"事实底座 ≥1/3 段落"（F5）。
            # HTML 路径本来就只取 <p>，此改动让 Markdown 路径与之一致。
            heading_lines.append(re.sub(r"^#{2,6}\s+", "", raw_line))
            continue
        current.append(raw_line)
    if current:
        blocks.append(current)

    paragraphs = [
        _markdown_visible_text(" ".join(block))
        for block in blocks
        if _markdown_visible_text(" ".join(block))
    ]
    heading_text = "".join(_markdown_visible_text(line) for line in heading_lines)
    # ``frontmatter_seen`` is intentionally only a parsing aid; keeping this
    # local makes the function tolerant of ordinary drafts without metadata.
    del frontmatter_seen, title_index
    return title, paragraphs, hook, heading_text


def validate_markdown_text(markdown_text: str, *, hook: str = "") -> dict[str, Any]:
    """Run the reader-facing style gate on one Markdown article."""
    title, paragraphs, parsed_hook, heading_text = _markdown_title_and_paragraphs(markdown_text)
    declared_hook = hook or parsed_hook
    # 小标题仍参与红线扫描，只是不再充当段落密度的分母。
    full = "".join(paragraphs) + heading_text
    hits = scan_style(full)
    hook = opening_hook_check(paragraphs)
    title_result = title_gap_check(title)
    density = fact_density_check(paragraphs)
    thin = thin_section_check(_markdown_sections(markdown_text))
    closing = closing_interaction_check(paragraphs)
    hook_result = hook_declaration_check(declared_hook, full)
    article = {
        "index": 1,
        "title": title,
        "char_count": len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", full)),
        "hits": hits,
        "hit_count": len(hits),
        "error_count": sum(1 for hit in hits if hit["severity"] == "error"),
        "opening_hook": hook,
        "title_gap": title_result,
        "fact_density": density,
        "thin_section": thin,
        "closing_interaction": closing,
        "hook_declaration": hook_result,
    }
    global_hits = _scan_rules(_markdown_visible_text(markdown_text), _PIPELINE_RULES, "error")
    errors = [
        hit for hit in article["hits"] if hit["severity"] == "error"
    ] + global_hits
    return {
        "artifact_type": "markdown",
        "article_count": 1,
        "articles": [article],
        "global_hits": global_hits,
        "pass": len(errors) == 0,
        "error_total": len(errors),
    }


def validate_markdown_file(path: Path, *, hook: str = "") -> dict[str, Any]:
    """Run Markdown style checks and seal the exact bytes that were scanned."""
    payload = path.read_bytes()
    result = validate_markdown_text(payload.decode("utf-8"), hook=hook)
    result["artifact_path"] = str(path.resolve())
    result["artifact_sha256"] = hashlib.sha256(payload).hexdigest()
    return result


def validate_delivery_file(path: Path) -> dict[str, Any]:
    """Run the style gate and seal the exact HTML bytes that were scanned.

    The in-memory validator remains path-independent for unit tests and other
    callers.  The file-level entry point is used by the CLI so final_review can
    prove that the style report belongs to the frozen delivery artifact rather
    than to an earlier draft or an untracked copy.
    """
    payload = path.read_bytes()
    result = validate_batch_style(payload.decode("utf-8"))
    result["artifact_type"] = "html"
    result["artifact_path"] = str(path.resolve())
    result["artifact_sha256"] = hashlib.sha256(payload).hexdigest()
    return result


def _detect_artifact_type(text: str, path: Path) -> str:
    """Classify a delivery artifact so the gate can never scan nothing.

    The historical HTML-only entry point silently returned ``pass: true`` with
    ``article_count: 0`` for a Markdown file — a green result over zero scanned
    articles (the trap the workflow notes warn about).  Detection is therefore
    explicit and fail-closed: Markdown is recognised by heading structure,
    HTML by a document/body/article element, and anything else is ``unknown``.
    """
    stripped = text.lstrip()
    if re.search(r"<(!doctype|html|body)\b", stripped[:4096], re.IGNORECASE) or re.search(
        r"<article\b", text, re.IGNORECASE
    ):
        return "html"
    if re.search(r"(?m)^\s{0,3}#\s+\S", text):
        return "markdown"
    if path.suffix.lower() in {".md", ".markdown"}:
        return "markdown"
    if path.suffix.lower() in {".html", ".htm"}:
        return "html"
    return "unknown"


def validate_artifact_file(path: Path, *, hook: str = "") -> dict[str, Any]:
    """Validate a delivery artifact on the surface that matches its content.

    Markdown deliveries go through :func:`validate_markdown_file` (H2 headings
    excluded from the fact-density denominator, ``review_hook`` bound from the
    batch manifest); HTML deliveries keep the historical batch surface.  An
    artifact that cannot be classified is reported as an error instead of
    passing vacuously.
    """
    payload = path.read_bytes()
    text = payload.decode("utf-8")
    kind = _detect_artifact_type(text, path)
    if kind == "markdown":
        return validate_markdown_file(path, hook=hook)
    if kind == "html":
        return validate_delivery_file(path)
    return {
        "artifact_type": "unknown",
        "article_count": 0,
        "articles": [],
        "global_hits": [],
        "pass": False,
        "error_total": 1,
        "errors": ["artifact_type_unrecognized"],
        "artifact_path": str(path.resolve()),
        "artifact_sha256": hashlib.sha256(payload).hexdigest(),
    }


if __name__ == "__main__":
    import argparse
    import json
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description=(
            "Style gate for a delivery artifact. Markdown and HTML are detected "
            "automatically; unclassifiable files fail closed."
        )
    )
    parser.add_argument("artifact", type=Path, help="delivery.md or frozen delivery.html")
    parser.add_argument(
        "--hook",
        default="",
        help="strongest-hook declaration for Markdown deliveries (batch.json review_hook)",
    )
    args = parser.parse_args()
    if not args.artifact.is_file():
        print(json.dumps({"error": "artifact_missing", "path": str(args.artifact)}, ensure_ascii=False))
        sys.exit(2)
    result = validate_artifact_file(args.artifact, hook=args.hook)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["pass"] else 1)
