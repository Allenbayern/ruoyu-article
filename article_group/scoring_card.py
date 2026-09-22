"""评分卡的诚实化（2026-09-21，daily-010/011 独立编读 + L2 复盘）。

问题：``review/scoring/<aid>.json`` 的分项分与总分在 daily_engine 里是**字面常量**
（三篇一律 total 86 = 21+17+17+13+9+5+4），而 ``final_review`` 会按 ``_SCORING_LIMITS``
与 ``_SCORING_FLOORS`` 校验它——于是"总分必须 ≥75、证据分必须 ≥15"这道门对任何稿件都
恒真，评分卡成了看起来像证据、实际不是的产物（L2 原话："任何一稿都会得到 86 分"；
脚本里的同类常量卡还能追到 generate_daily_001/002）。

本模块做两件事，都刻意不越界去发明"更精确"的分数：

1. 保留历史字段（下游 ``final_review`` 的区间/下限/求和校验照旧跑），但显式标注
   ``card_kind=template_unmeasured`` / ``measured=false``，并把"为什么"写进 note；
   ``final_review`` 会据此把该篇记为人工裁决项，而不是让它冒充质量证据。
2. 把**真能测**的信号单独记进 ``measured_signals``：硬信息落段率（账本 vs 正文）与
   风格记录的结构量（错误数、字数、薄节状态）。判断类维度（原创判断、信息增量）
   机器测不了——它们仍是模板常量，不假装测过。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

SCHEMA_VERSION = "article-scoring-card-v1"

# 历史模板常量（2026-09-17 起沿用）。**不是测量值**：据此判断稿件质量会复现
# "产物自述通过"的失败模式。
TEMPLATE_COMPONENTS: dict[str, int] = {
    "evidence_score": 21,
    "original_judgment_score": 17,
    "information_gain_score": 17,
    "structure_score": 13,
    "title_value_score": 9,
    "readability_score": 5,
    "compliance_score": 4,
}
TEMPLATE_TOTAL = sum(TEMPLATE_COMPONENTS.values())  # 86

TEMPLATE_NOTE = (
    "分项分与总分是历史模板常量（2026-09-17 起沿用），不是对该稿的测量，"
    "不得作为质量判据或门禁依据；可测信号见 measured_signals，"
    "判断类维度（原创判断、信息增量）机器测不了，等人工裁决。"
)


def _paragraphs(body: str) -> list[str]:
    return [p for p in body.split("\n\n") if p and not p.startswith("## ")]


def _locator_index(locator: object) -> int:
    text = str(locator or "")
    if len(text) > 1 and text[0] == "p" and text[1:].isdigit():
        return int(text[1:]) - 1
    return -1


def hard_information_coverage(
    record: Mapping[str, Any] | None, paragraphs: list[str]
) -> dict[str, Any]:
    """硬信息落段率：账本条目里有多少条的 ``body_locator`` 真的指向正文某段。"""

    items = (record or {}).get("hard_information")
    if not isinstance(items, list) or not items:
        return {"total": 0, "located": 0, "ratio": None}
    located = 0
    for item in items:
        index = _locator_index((item or {}).get("body_locator") if isinstance(item, Mapping) else None)
        if 0 <= index < len(paragraphs):
            located += 1
    return {"total": len(items), "located": located, "ratio": round(located / len(items), 3)}


def build_scoring_card(
    *,
    aid: str,
    delivery_path: str,
    body: str,
    digest_fn: Callable[[str], str],
    style_gate: Mapping[str, Any] | None = None,
    content_fidelity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """构造评分卡：历史字段照旧 + 标注非测量 + 附真实信号。"""

    paragraphs = _paragraphs(body)
    style_articles = (style_gate or {}).get("articles")
    style_article = style_articles[0] if isinstance(style_articles, list) and style_articles else {}
    if not isinstance(style_article, Mapping):
        style_article = {}
    thin = style_article.get("thin_section")
    return {
        "schema_version": SCHEMA_VERSION,
        "article_id": aid,
        "artifact_path": delivery_path,
        "artifact_sha256": digest_fn(delivery_path),
        "card_kind": "template_unmeasured",
        "measured": False,
        "note": TEMPLATE_NOTE,
        "total_score": TEMPLATE_TOTAL,
        **TEMPLATE_COMPONENTS,
        "first_screen_value": "首段给出具体事件与人物动作",
        "reader_takeaway": "核心判断可转述",
        "reader_takeaway_locator": f"p{len(paragraphs)}",
        "body_fulfillment": "正文逐段推进并标出未验证边界",
        "measured_signals": {
            "hard_information_coverage": hard_information_coverage(content_fidelity, paragraphs),
            "style_record": {
                "status": (style_gate or {}).get("pass"),
                "error_count": style_article.get("error_count"),
                "char_count": style_article.get("char_count"),
                "thin_section": (thin or {}).get("status") if isinstance(thin, Mapping) else None,
            },
        },
    }
