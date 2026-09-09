"""Deterministic, offline article DNA extraction for Article Group V5.

DNA is a descriptive comparison signal.  It deliberately does not assert
that a text is factual, successful, causal, or authorized for publication.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
import re
from typing import Any

from .contracts import (
    PUBLICATION_AUTHORIZATION,
    new_artifact_envelope,
    payload_of,
    validate_v5_artifact_envelope,
)


_SCHEMA_VERSION = "v5-article-dna-v1"
_FEATURE_SOURCES = frozenset({"explicit", "derived", "unavailable"})
_EVIDENCE_ROLE = "descriptive_signal_only"

# The aliases make the extractor tolerant of the field names already used by
# the article-group inputs while keeping one stable output vocabulary.
_FEATURE_NAMES = (
    "topic_type",
    "title_structure",
    "character_presence",
    "number_presence",
    "relationship_conflict",
    "concrete_scene",
    "film_list",
    "emotion_direction",
    "character_count",
    "paragraph_count",
    "opening_info_type",
    "ending_type",
    "published_at",
    "platform",
)
_EXPLICIT_FIELDS: dict[str, tuple[str, ...]] = {
    "topic_type": ("topic_type", "topic_mode"),
    "title_structure": ("title_structure", "title_pattern"),
    "character_presence": (
        "character_presence",
        "person_presence",
        "people_presence",
    ),
    "number_presence": ("number_presence", "numeric_presence"),
    "relationship_conflict": ("relationship_conflict",),
    "concrete_scene": ("concrete_scene",),
    "film_list": ("film_list", "film_list_presence"),
    "emotion_direction": ("emotion_direction",),
    "character_count": ("character_count", "char_count"),
    "paragraph_count": ("paragraph_count",),
    "opening_info_type": ("opening_info_type",),
    "ending_type": ("ending_type",),
    "published_at": ("published_at", "publish_time", "published_time"),
    "platform": ("platform",),
}
_TITLE_QUESTION = re.compile(r"[?？]")
_NUMBER = re.compile(r"[0-9０-９零一二三四五六七八九十百千万亿]")
_FILM_TITLE = re.compile(r"《[^》]{1,80}》")
_SCENE_WORDS = (
    "夜里",
    "夜晚",
    "晚上",
    "清晨",
    "凌晨",
    "片场",
    "走出",
    "站在",
    "门口",
    "房间",
    "街上",
    "街头",
    "机场",
    "医院",
    "现场",
    "那天",
    "此刻",
    "第一幕",
    "具体场景",
)
_PERSON_WORDS = (
    "他",
    "她",
    "演员",
    "导演",
    "观众",
    "父亲",
    "母亲",
    "爸爸",
    "妈妈",
    "主角",
    "主创",
    "人物",
    "网友",
    "一家",
    "两人",
)
_RELATIONSHIP_WORDS = (
    "关系",
    "夫妻",
    "父子",
    "母女",
    "兄弟",
    "姐妹",
    "情侣",
    "爱人",
    "朋友",
    "亲子",
    "离婚",
    "分手",
    "冲突",
    "对立",
    "选择",
    "背叛",
    "误会",
    "争执",
)
_POSITIVE_WORDS = (
    "喜欢",
    "治愈",
    "温暖",
    "希望",
    "高光",
    "感动",
    "幸福",
    "成长",
    "胜利",
    "惊喜",
    "浪漫",
)
_NEGATIVE_WORDS = (
    "失去",
    "崩溃",
    "争议",
    "愤怒",
    "遗憾",
    "悲伤",
    "痛苦",
    "失败",
    "背叛",
    "死亡",
    "离开",
    "焦虑",
    "孤独",
)
_ENDING_SUMMARY_WORDS = (
    "因此",
    "所以",
    "最终",
    "归根结底",
    "总之",
    "这意味着",
)
_ENDING_QUESTION_WORDS = (
    "你怎么看",
    "你会",
    "值得吗",
    "说说",
    "评论",
)


def _usable(value: object) -> bool:
    return value is not None and not (
        isinstance(value, str) and not value.strip()
    )


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _feature(value: object = None, source: str = "unavailable") -> dict[str, Any]:
    if source == "unavailable":
        value = None
    return {"value": deepcopy(value), "source": source}


def _nested_explicit_value(article: Mapping[str, Any], name: str) -> object:
    nested = article.get("features")
    if not isinstance(nested, Mapping) or name not in nested:
        return None
    value = nested.get(name)
    if isinstance(value, Mapping) and "value" in value:
        return value.get("value")
    return value


def _first_explicit_value(
    article: Mapping[str, Any],
    metric_event: Mapping[str, Any] | None,
    fields: tuple[str, ...],
) -> object:
    for field in fields:
        if field in article and _usable(article.get(field)):
            return article.get(field)
        nested = _nested_explicit_value(article, field)
        if _usable(nested):
            return nested
    if metric_event is not None:
        for field in fields:
            if field in metric_event and _usable(metric_event.get(field)):
                return metric_event.get(field)
    return None


def _draft_text(article: Mapping[str, Any], draft_text: str | None) -> str:
    if isinstance(draft_text, str) and draft_text.strip():
        return draft_text
    for field in ("draft_text", "body", "content", "text"):
        candidate = article.get(field)
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return ""


def _title(article: Mapping[str, Any]) -> str:
    return _text(article.get("title"))


def _title_structure(title: str) -> str | None:
    if not title:
        return None
    question = bool(_TITLE_QUESTION.search(title))
    numeric = bool(_NUMBER.search(title))
    if question and numeric:
        return "question_numeric"
    if question:
        return "question"
    if numeric:
        return "numeric"
    if any(word in title for word in _RELATIONSHIP_WORDS):
        return "conflict"
    return "statement"


def _contains_any(value: str, words: tuple[str, ...]) -> bool:
    return bool(value) and any(word in value for word in words)


def _emotion_direction(value: str) -> str | None:
    if not value:
        return None
    positive = sum(value.count(word) for word in _POSITIVE_WORDS)
    negative = sum(value.count(word) for word in _NEGATIVE_WORDS)
    if positive and negative:
        return "mixed"
    if positive:
        return "positive"
    if negative:
        return "negative"
    return "neutral"


def _opening_info_type(text: str) -> str | None:
    if not text:
        return None
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not first:
        return None
    if _contains_any(first, _SCENE_WORDS):
        return "具体场景"
    if _NUMBER.search(first):
        return "数字"
    if _contains_any(first, _PERSON_WORDS):
        return "人物"
    if _TITLE_QUESTION.search(first):
        return "问题"
    return "观点"


def _ending_type(text: str) -> str | None:
    if not text:
        return None
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n|\r?\n", text) if part.strip()]
    ending = paragraphs[-1] if paragraphs else ""
    if not ending:
        return None
    if _TITLE_QUESTION.search(ending) or _contains_any(
        ending, _ENDING_QUESTION_WORDS
    ):
        return "question"
    if _contains_any(ending, _ENDING_SUMMARY_WORDS):
        return "summary"
    return "statement"


def _paragraph_count(text: str) -> int | None:
    if not text.strip():
        return None
    return len(
        [part for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]
    )


def _stable_hash(value: object) -> str | None:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError):
        return None
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _derived_feature_values(title: str, text: str) -> dict[str, object]:
    combined = "\n".join(part for part in (title, text) if part)
    if not combined:
        return {
            "title_structure": None,
            "character_presence": None,
            "number_presence": None,
            "relationship_conflict": None,
            "concrete_scene": None,
            "film_list": None,
            "emotion_direction": None,
        }
    return {
        "title_structure": _title_structure(title),
        "character_presence": _contains_any(combined, _PERSON_WORDS),
        "number_presence": bool(_NUMBER.search(combined)),
        "relationship_conflict": _contains_any(combined, _RELATIONSHIP_WORDS),
        "concrete_scene": _contains_any(combined, _SCENE_WORDS),
        "film_list": bool(
            "片单" in combined
            or "影单" in combined
            or len(_FILM_TITLE.findall(combined)) >= 2
        ),
        "emotion_direction": _emotion_direction(combined),
    }


def extract_article_dna(
    article: Mapping[str, Any],
    *,
    draft_text: str | None = None,
    metric_event: Mapping[str, Any] | None = None,
    run_id: str = "v5-local",
    generated_at: str = "1970-01-01T00:00:00Z",
) -> dict[str, Any]:
    """Extract stable descriptive features without making factual claims."""

    raw_article = article if isinstance(article, Mapping) else {}
    raw_metric_event = metric_event if isinstance(metric_event, Mapping) else None
    text = _draft_text(raw_article, draft_text)
    title = _title(raw_article)
    derived = _derived_feature_values(title, text)

    features: dict[str, dict[str, Any]] = {}
    for name in _FEATURE_NAMES:
        explicit = _first_explicit_value(
            raw_article,
            raw_metric_event if name in {"published_at", "platform"} else None,
            _EXPLICIT_FIELDS[name],
        )
        if _usable(explicit):
            features[name] = _feature(explicit, "explicit")
            continue

        if name in derived and _usable(derived[name]):
            features[name] = _feature(derived[name], "derived")
            continue

        if name == "character_count" and text:
            features[name] = _feature(len(text), "derived")
        elif name == "paragraph_count" and text:
            features[name] = _feature(_paragraph_count(text), "derived")
        elif name == "opening_info_type" and text:
            features[name] = _feature(_opening_info_type(text), "derived")
        elif name == "ending_type" and text:
            features[name] = _feature(_ending_type(text), "derived")
        else:
            features[name] = _feature()

    article_id = _first_explicit_value(
        raw_article,
        raw_metric_event,
        ("article_id", "id"),
    )
    metric_snapshot = (
        deepcopy(dict(raw_metric_event)) if raw_metric_event is not None else None
    )
    payload: dict[str, Any] = {
        "article_id": article_id,
        "features": features,
        "evidence_role": _EVIDENCE_ROLE,
        "fact_proof": False,
        "metric_event": metric_snapshot,
        "metric_event_status": (
            "available" if raw_metric_event else "unavailable"
        ),
        "publication_authorization": PUBLICATION_AUTHORIZATION,
    }
    result = new_artifact_envelope(
        _SCHEMA_VERSION,
        run_id,
        payload,
        generated_at=generated_at,
    )
    input_hashes: dict[str, str] = {}
    for key, value in (
        ("article", raw_article),
        ("draft_text", draft_text),
        ("metric_event", raw_metric_event),
    ):
        digest = _stable_hash(value)
        if digest is not None:
            input_hashes[key] = digest
    result["input_hashes"] = input_hashes
    return result


def validate_article_dna(record: Mapping[str, Any]) -> list[str]:
    """Return stable validation errors for one article DNA artifact."""

    if not isinstance(record, Mapping):
        return ["invalid:artifact"]

    run_id = record.get("run_id") if isinstance(record.get("run_id"), str) else ""
    errors = validate_v5_artifact_envelope(
        record,
        _SCHEMA_VERSION,
        run_id=run_id,
    )
    payload = payload_of(record)
    if not isinstance(payload, Mapping):
        return list(dict.fromkeys(errors))

    article_id = payload.get("article_id")
    if not isinstance(article_id, str) or not article_id.strip():
        errors.append("invalid:article_id")

    features = payload.get("features")
    if not isinstance(features, Mapping) or not features:
        errors.append("invalid:features")
        features = {}
    else:
        for name in _FEATURE_NAMES:
            if name not in features:
                errors.append(f"missing:feature:{name}")
        for name, item in features.items():
            if not isinstance(name, str) or not isinstance(item, Mapping):
                errors.append(f"invalid:feature:{name}")
                continue
            if set(item) != {"value", "source"}:
                errors.append(f"invalid:feature:{name}")
                continue
            source = item.get("source")
            if source not in _FEATURE_SOURCES:
                errors.append(f"invalid:feature:{name}")
            elif source == "unavailable" and item.get("value") is not None:
                errors.append(f"invalid:feature:{name}:unavailable_value")
            elif source != "unavailable" and item.get("value") is None:
                errors.append(f"invalid:feature:{name}:missing_value")

    if payload.get("evidence_role") != _EVIDENCE_ROLE:
        errors.append("dna_must_be_descriptive_signal_only")
    if payload.get("fact_proof") is True:
        errors.append("dna_must_not_be_fact_proof")
    if payload.get("publication_authorization") != PUBLICATION_AUTHORIZATION:
        errors.append("publication_authorization_must_be_not_authorized")

    metric_status = payload.get("metric_event_status")
    metric_event = payload.get("metric_event")
    if metric_status not in {"available", "unavailable"}:
        errors.append("invalid:metric_event_status")
    elif metric_status == "available" and not isinstance(metric_event, Mapping):
        errors.append("invalid:metric_event")
    elif (
        metric_status == "unavailable"
        and metric_event is not None
        and metric_event != {}
    ):
        errors.append("invalid:metric_event:unavailable_value")

    return list(dict.fromkeys(errors))


__all__ = ["extract_article_dna", "validate_article_dna"]
