"""五问选题预检（2026-09-16 用户拍板）：结构必填 + 枚举校验 + 质量警告。

候选卡必须携带五问字段：

- ``reader``（读者）：谁会点进来；
- ``landing``（落点）：读者拿走什么；
- ``emotion``（情绪）：承载的集体情绪；
- ``remove_timestamp_test``（删节点测试）：删掉今天的新闻节点后是否仍有价值，
  沿用 portfolio_gate 的 pass/risk/fail 三态；``fail`` 的候选按编辑准则不得入选；
- ``social_motive``（社交原动力）：显摆新知 / 找同类 / 表达立场 / 送温暖。

机器只管三件事：

1. 结构必填：字段缺失或空值 = error（阻断，写入 preflight/gates）；
2. 枚举校验：social_motive 与 remove_timestamp_test 的取值集合 = error；
3. 质量提示：落点过短、兜底话术、落点等于作品名等 = warning（不阻断，
   供 controller/L2 参考——内容质量判断不机器化）。
"""
from __future__ import annotations

from typing import Any

FIVE_QUESTION_FIELDS = (
    "reader",
    "landing",
    "emotion",
    "remove_timestamp_test",
    "social_motive",
)

SOCIAL_MOTIVES = frozenset({"显摆新知", "找同类", "表达立场", "送温暖"})
REMOVE_TIMESTAMP_VALUES = frozenset({"pass", "risk", "fail"})

_LANDING_BOILERPLATE = ("值得一看", "了解一下", "值得关注", "介绍这部")
_LANDING_MIN_CHARS = 6
_EMOTION_MIN_CHARS = 2


def _text(value: object) -> str:
    return str(value).strip() if isinstance(value, str) else ""


def evaluate(selected: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate the five-question fields of the selected candidates.

    ``selected`` 即 selected-candidates 记录里的候选条目（含 candidate_id、
    reader/landing/emotion/remove_timestamp_test/social_motive）。返回记录可直接
    写入 review/topic-five-questions.json。
    """
    errors: list[str] = []
    warnings: list[str] = []
    articles: list[dict[str, Any]] = []
    if not selected:
        errors.append("missing:selected_candidates")
    for cand in selected:
        cid = _text(cand.get("candidate_id")) or "?"
        row_errors: list[str] = []
        row_warnings: list[str] = []
        for field in FIVE_QUESTION_FIELDS:
            if not _text(cand.get(field)):
                row_errors.append(f"five_questions_missing:{field}")
                errors.append(f"{cid}:five_questions_missing:{field}")
        social_motive = _text(cand.get("social_motive"))
        if social_motive and social_motive not in SOCIAL_MOTIVES:
            row_errors.append(f"social_motive_invalid:{social_motive}")
            errors.append(f"{cid}:social_motive_invalid:{social_motive}")
        rtt = _text(cand.get("remove_timestamp_test"))
        if rtt and rtt not in REMOVE_TIMESTAMP_VALUES:
            row_errors.append(f"remove_timestamp_test_invalid:{rtt}")
            errors.append(f"{cid}:remove_timestamp_test_invalid:{rtt}")
        elif rtt == "fail":
            # 编辑准则：删掉今天的新闻节点后没有价值的题目不进入写作。
            row_errors.append("remove_timestamp_test_fail_selected")
            errors.append(f"{cid}:remove_timestamp_test_fail_selected")
        elif rtt == "risk":
            row_warnings.append("remove_timestamp_test_risk_selected")
            warnings.append(f"{cid}:remove_timestamp_test_risk_selected")
        landing = _text(cand.get("landing"))
        if landing:
            if len(landing) < _LANDING_MIN_CHARS:
                row_warnings.append("landing_too_short")
                warnings.append(f"{cid}:landing_too_short")
            if any(term in landing for term in _LANDING_BOILERPLATE):
                row_warnings.append("landing_boilerplate")
                warnings.append(f"{cid}:landing_boilerplate")
            if _text(cand.get("work_title")) and landing == _text(cand.get("work_title")):
                row_warnings.append("landing_equals_work_title")
                warnings.append(f"{cid}:landing_equals_work_title")
        emotion = _text(cand.get("emotion"))
        if emotion and len(emotion) < _EMOTION_MIN_CHARS:
            row_warnings.append("emotion_too_short")
            warnings.append(f"{cid}:emotion_too_short")
        articles.append(
            {
                "candidate_id": cid,
                "five_questions": {
                    field: _text(cand.get(field)) for field in FIVE_QUESTION_FIELDS
                },
                "errors": row_errors,
                "warnings": row_warnings,
            }
        )
    return {
        "schema_version": "topic-five-questions-v1",
        "status": "fail" if errors else "pass",
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "articles": articles,
        "publication_authorization": "not_authorized",
    }


__all__ = [
    "FIVE_QUESTION_FIELDS",
    "REMOVE_TIMESTAMP_VALUES",
    "SOCIAL_MOTIVES",
    "evaluate",
]
