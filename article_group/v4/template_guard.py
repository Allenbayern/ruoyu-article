"""Deterministic, offline anti-template signals for Article Group V4."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import re
import unicodedata
from typing import Any

from .contracts import new_artifact_envelope, validate_artifact_envelope


_SCHEMA = "v4-template-signals-v1"
_EPOCH = "1970-01-01T00:00:00Z"
_ENVELOPE_KEYS = {
    "schema_version",
    "run_id",
    "generated_at",
    "input_hashes",
    "payload",
}
_SIGNAL_TYPES = (
    "title_skeleton",
    "opening_fact_suspense",
    "h2_paragraph_progression",
    "number_adjective_combination",
    "mechanical_ending_question",
)
_SEVERITIES = {"info", "warning", "manual_review"}
_DECISIONS = {"info", "warning", "manual_review"}

_DEFAULT_THRESHOLDS: dict[str, dict[str, int | float]] = {
    "title_skeleton": {
        "min_matches": 2,
        "min_shared_units": 2,
    },
    "opening_fact_suspense": {
        "min_matches": 2,
        "min_fact_features": 1,
        "min_suspense_features": 1,
    },
    "h2_paragraph_progression": {
        "min_matches": 2,
        "min_h2_count": 2,
        "min_paragraph_count": 2,
    },
    "number_adjective_combination": {
        "min_matches": 2,
        "min_number_tokens": 1,
        "min_adjective_groups": 1,
    },
    "mechanical_ending_question": {
        "min_matches": 2,
    },
}

_RFC3339_SUBSET = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-3][0-9]T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(?:\.[0-9]+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$"
)

_NUMBER_RE = re.compile(
    r"(?:\d+(?:[.,]\d+)?%?|[〇零一二三四五六七八九十百千万亿两]+)"
    r"(?:年|月|日|次|部|人|分钟|小时|亿|万|%){0,1}"
)
_WORK_RE = re.compile(r'[《〈「『【\["]([^》〉」』】\]"]+)[》〉」』】\]"]')
_H2_TAG_RE = re.compile(r"</?h[1-6][^>]*>", re.IGNORECASE)
_H2_LINE_RE = re.compile(r"^[ \t]{0,3}#{2,6}[ \t]+(.+?)\s*$", re.MULTILINE)
_LEADING_H2_RE = re.compile(r"^[ \t]*(?:#{1,6}[ \t]*)+")
_LEADING_NUMBER_RE = re.compile(
    r"^[ \t]*(?:第[ \t]*)?(?:[0-9]+|[一二三四五六七八九十百千万亿]+)"
    r"[ \t]*(?:[.．、:：)）\-—]+[ \t]*)?"
)

_STOP_PHRASES = (
    "为什么",
    "为何",
    "凭什么",
    "难道",
    "究竟",
    "到底",
    "什么",
    "如何",
    "怎么",
    "怎样",
    "是否",
    "哪些",
    "哪个",
    "哪种",
    "以及",
    "因为",
    "所以",
    "但是",
    "然而",
    "不过",
    "只是",
    "如果",
    "那么",
    "就是",
    "这是",
    "这部",
    "这场",
    "一个",
    "一种",
)
_STOP_TOKENS = {
    "的",
    "了",
    "着",
    "过",
    "是",
    "在",
    "和",
    "与",
    "及",
    "把",
    "被",
    "让",
    "从",
    "到",
    "对",
    "为",
    "向",
    "由",
    "也",
    "都",
    "就",
    "而",
    "却",
    "又",
    "还",
    "更",
    "很",
    "最",
    "太",
    "地",
    "得",
    "吗",
    "呢",
    "吧",
    "啊",
    "呀",
    "这",
    "那",
    "其",
    "我",
    "你",
    "他",
    "她",
    "它",
    "我们",
    "大家",
    "读者",
    "观众",
}
_TOKEN_RE = re.compile(r"<[A-Z_]+>|[A-Za-z]+(?:[-'][A-Za-z]+)?|[0-9]+(?:\.[0-9]+)?|[\u3400-\u9fff]+")

_FACT_MARKERS = {
    "上映": "release",
    "定档": "release",
    "改档": "release",
    "撤档": "release",
    "首映": "release",
    "票房": "metric",
    "评分": "metric",
    "导演": "credit",
    "编剧": "credit",
    "主演": "credit",
    "主创": "credit",
    "确认": "statement",
    "官宣": "statement",
    "公布": "statement",
    "获奖": "award",
    "入围": "award",
    "发布": "statement",
}
_SUSPENSE_MARKERS = {
    "但": "contrast",
    "却": "contrast",
    "然而": "contrast",
    "不过": "contrast",
    "反而": "contrast",
    "只是": "contrast",
    "真正": "reveal",
    "关键": "reveal",
    "问题": "reveal",
    "答案": "reveal",
    "意外": "reveal",
    "没想到": "reveal",
    "直到": "reveal",
    "为什么": "question",
    "为何": "question",
    "怎么": "question",
    "如何": "question",
    "究竟": "question",
}
_ADJECTIVE_TERMS = (
    "惊人的反转",
    "残酷的选择",
    "漫长的等待",
    "意外的结局",
    "真实的情感",
    "强烈的冲突",
    "复杂的关系",
    "唯一的答案",
    "巨大的变化",
    "高能反转",
    "惊人",
    "残酷",
    "漫长",
    "意外",
    "真实",
    "强烈",
    "复杂",
    "唯一",
    "巨大",
    "温柔",
    "孤独",
    "清醒",
    "荒诞",
    "压抑",
    "细腻",
    "宏大",
    "疯狂",
    "冷峻",
)
_ADJECTIVE_RE = re.compile("|".join(re.escape(term) for term in _ADJECTIVE_TERMS))


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _first_text(candidate: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = candidate.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    payload = candidate.get("payload")
    if isinstance(payload, Mapping):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _candidate_view(candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = candidate.get("payload")
    if isinstance(payload, Mapping):
        merged = dict(payload)
        merged.update(candidate)
        return merged
    return candidate


def _candidate_id(candidate: Mapping[str, Any], *, fallback: str = "") -> str:
    view = _candidate_view(candidate)
    for key in ("candidate_id", "article_id", "content_id", "id"):
        value = _text(view.get(key))
        if value:
            return value
    return fallback


def _strip_markup(value: str) -> str:
    value = _H2_TAG_RE.sub(" ", value)
    value = re.sub(r"<[^>]+>", " ", value)
    return _LEADING_H2_RE.sub("", value)


def _replace_numbers(value: str) -> str:
    return _NUMBER_RE.sub(" <NUM> ", value)


def _normalize_punctuation(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", _strip_markup(value)).lower()
    chars: list[str] = []
    for char in normalized:
        category = unicodedata.category(char)
        chars.append(" " if category[0] in {"P", "S"} else char)
    return " ".join("".join(chars).split())


def _remove_phrases(value: str, phrases: Sequence[str]) -> str:
    result = value
    for phrase in sorted(phrases, key=len, reverse=True):
        result = result.replace(phrase, " ")
    return result


def _tokens(value: str, *, remove_stopwords: bool = True) -> list[str]:
    placeholders: list[str] = []

    def protect(match: re.Match[str]) -> str:
        placeholders.append(match.group(1))
        return f" QZPLACEHOLDER{len(placeholders) - 1}QZ "

    protected = re.sub(r"<([A-Z_]+)>", protect, _replace_numbers(value))
    normalized = _normalize_punctuation(protected)
    normalized = _remove_phrases(normalized, _STOP_PHRASES)
    tokens = _TOKEN_RE.findall(normalized)
    if remove_stopwords:
        tokens = [token for token in tokens if token not in _STOP_TOKENS]
    return [
        f"<{placeholders[int(token[len('qzplaceholder'):-2])].upper()}>"
        if token.startswith("qzplaceholder") and token.endswith("qz")
        and token[len("qzplaceholder"):-2].isdigit()
        else token
        for token in tokens
    ]


def _normalize_phrase(value: str) -> str:
    normalized = _normalize_punctuation(_replace_numbers(value))
    return normalized.replace("< num >", "<NUM>").strip()


def _sequence_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _body_texts(candidate: Mapping[str, Any]) -> list[str]:
    view = _candidate_view(candidate)
    values: list[str] = []
    for key in ("body", "content", "article", "draft", "markdown"):
        value = view.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value)
    return values


def _title_text(candidate: Mapping[str, Any]) -> str:
    return _first_text(candidate, "title", "title_text", "headline", "h1", "标题")


def _opening_text(candidate: Mapping[str, Any]) -> str:
    return _first_text(
        candidate,
        "opening",
        "opening_text",
        "lead",
        "first_screen",
        "first_screen_text",
        "首屏",
        "开头",
    )


def _h2_texts(candidate: Mapping[str, Any]) -> list[str]:
    view = _candidate_view(candidate)
    for key in ("h2", "h2s", "headings", "h2_labels", "sections"):
        values = _sequence_strings(view.get(key))
        if values:
            return values
    headings: list[str] = []
    for body in _body_texts(view):
        headings.extend(match.group(1).strip() for match in _H2_LINE_RE.finditer(body))
        headings.extend(
            match.group(1).strip()
            for match in re.finditer(
                r"<h2[^>]*>(.*?)</h2>", body, flags=re.IGNORECASE | re.DOTALL
            )
        )
    return headings


def _paragraph_texts(candidate: Mapping[str, Any]) -> list[str]:
    view = _candidate_view(candidate)
    for key in (
        "paragraphs",
        "paragraph_texts",
        "body_paragraphs",
        "content_paragraphs",
    ):
        values = _sequence_strings(view.get(key))
        if values:
            return values
    for body in _body_texts(view):
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", body) if part.strip()]
        paragraphs = [
            _H2_LINE_RE.sub("", _H2_TAG_RE.sub("", paragraph)).strip()
            for paragraph in paragraphs
        ]
        if paragraphs:
            return paragraphs
    return []


def _ending_text(candidate: Mapping[str, Any]) -> str:
    view = _candidate_view(candidate)
    for key in ("ending", "ending_text", "conclusion", "last_paragraph", "结尾"):
        value = view.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            values = _sequence_strings(value)
            if values:
                return values[-1]
    paragraphs = _paragraph_texts(view)
    return paragraphs[-1] if paragraphs else ""


def _all_content_text(candidate: Mapping[str, Any]) -> str:
    view = _candidate_view(candidate)
    parts: list[str] = []
    for key in ("title", "title_text", "headline", "opening", "opening_text", "lead"):
        value = view.get(key)
        if isinstance(value, str):
            parts.append(value)
    for key in ("h2", "h2s", "headings", "h2_labels", "sections", "paragraphs", "paragraph_texts", "body_paragraphs", "content_paragraphs"):
        value = view.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            parts.extend(item for item in value if isinstance(item, str))
    parts.extend(_body_texts(view))
    ending = _ending_text(view)
    if ending:
        parts.append(ending)
    return "\n".join(parts)


def _title_fingerprint(candidate: Mapping[str, Any]) -> dict[str, Any]:
    raw = _title_text(candidate)
    if not raw:
        return {"raw": "", "tokens": [], "fingerprint": "", "unit_count": 0}
    normalized = _WORK_RE.sub(" <WORK> ", raw)
    tokens = _tokens(normalized)
    return {
        "raw": raw,
        "tokens": tokens,
        "fingerprint": " ".join(tokens),
        "unit_count": len(tokens),
    }


def _fact_suspense_fingerprint(candidate: Mapping[str, Any]) -> dict[str, Any]:
    raw = _opening_text(candidate)
    normalized = _normalize_punctuation(raw)
    fact_features: set[str] = set()
    if _NUMBER_RE.search(raw):
        fact_features.add("number")
    if _WORK_RE.search(raw):
        fact_features.add("work")
    for marker, feature in _FACT_MARKERS.items():
        if marker in raw:
            fact_features.add(feature)
    suspense_features: set[str] = set()
    if "?" in normalized or "？" in raw:
        suspense_features.add("question")
    for marker, feature in _SUSPENSE_MARKERS.items():
        if marker in raw:
            suspense_features.add(feature)
    return {
        "raw": raw,
        "fact_features": sorted(fact_features),
        "suspense_features": sorted(suspense_features),
        "has_fact": bool(fact_features),
        "has_suspense": bool(suspense_features),
        "fingerprint": {
            "fact": sorted(fact_features),
            "suspense": sorted(suspense_features),
        },
    }


def _normalize_h2(value: str) -> str:
    value = _LEADING_NUMBER_RE.sub("", _strip_markup(value))
    tokens = _tokens(value)
    return " ".join(tokens)


def _phase(value: str) -> str:
    if any(marker in value for marker in ("为什么", "为何", "怎么", "如何", "究竟", "？", "?")):
        return "question"
    if any(marker in value for marker in ("但", "却", "然而", "不过", "反而", "只是", "争议")):
        return "contrast"
    if any(marker in value for marker in ("观众", "读者", "选择", "站在", "怎么看")):
        return "audience"
    if any(marker in value for marker in ("事实", "信息", "上映", "定档", "票房", "主创", "导演", "主演")):
        return "fact"
    if any(marker in value for marker in ("观点", "判断", "关键", "意义", "原因", "答案", "解读")):
        return "judgment"
    return "context"


def _progression_fingerprint(candidate: Mapping[str, Any]) -> dict[str, Any]:
    h2s = _h2_texts(candidate)
    paragraphs = _paragraph_texts(candidate)
    normalized_h2 = [_normalize_h2(value) for value in h2s]
    normalized_h2 = [value for value in normalized_h2 if value]
    h2_phases = [_phase(value) for value in h2s if value.strip()]
    paragraph_phases = [_phase(value) for value in paragraphs if value.strip()]
    fingerprint = {
        "h2": normalized_h2,
        "h2_phases": h2_phases,
        "paragraph_phases": paragraph_phases,
    }
    return {
        "h2s": normalized_h2,
        "paragraphs": paragraphs,
        "h2_count": len(normalized_h2),
        "paragraph_count": len(paragraphs),
        "fingerprint": fingerprint,
        "usable": len(normalized_h2) >= 2 and len(paragraphs) >= 2,
    }


def _number_tokens(candidate: Mapping[str, Any]) -> list[str]:
    view = _candidate_view(candidate)
    explicit: list[str] = []
    for key in ("number_tokens", "numbers", "numeric_tokens", "数字"):
        values = _sequence_strings(view.get(key))
        if values:
            explicit.extend(values)
    source = " ".join(explicit) if explicit else _all_content_text(view)
    return ["<NUM>"] if _NUMBER_RE.search(source) else []


def _adjective_groups(candidate: Mapping[str, Any]) -> list[str]:
    view = _candidate_view(candidate)
    explicit: list[str] = []
    for key in (
        "adjective_groups",
        "adjectives",
        "descriptor_groups",
        "形容词组",
    ):
        values = _sequence_strings(view.get(key))
        if values:
            explicit.extend(values)
    source = " ".join(explicit) if explicit else _all_content_text(view)
    groups = explicit or _ADJECTIVE_RE.findall(source)
    normalized: list[str] = []
    for group in groups:
        value = _normalize_phrase(group)
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def _number_adjective_fingerprint(candidate: Mapping[str, Any]) -> dict[str, Any]:
    numbers = _number_tokens(candidate)
    adjectives = _adjective_groups(candidate)
    return {
        "number_tokens": numbers,
        "adjective_groups": adjectives,
        "fingerprint": numbers + adjectives if numbers and adjectives else [],
        "usable": bool(numbers and adjectives),
    }


def _mechanical_ending_kind(candidate: Mapping[str, Any]) -> dict[str, Any]:
    raw = _ending_text(candidate)
    normalized = _normalize_punctuation(raw)
    is_question = bool(
        "?" in normalized
        or "？" in raw
        or re.search(r"(?:吗|呢|怎么看|怎么想|觉得|认为|选择)$", normalized)
    )
    kind = ""
    if is_question and re.search(r"(?:你|大家|观众|读者).{0,16}(?:怎么看|怎么想|觉得|认为)", raw):
        kind = "opinion_question"
    elif is_question and re.search(r"(?:你|大家|观众|读者).{0,16}(?:会|要不要|是否).{0,8}(?:吗|呢|？|\?)", raw):
        kind = "choice_question"
    elif is_question and re.search(r"(?:你|大家|观众|读者).{0,12}(?:吗|呢|？|\?)", raw):
        kind = "generic_audience_question"
    return {
        "raw": raw,
        "normalized": normalized,
        "kind": kind,
        "is_mechanical_question": bool(kind),
        "fingerprint": kind,
    }


def _stable_hash(value: object) -> str | None:
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, UnicodeError):
        return None
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or _RFC3339_SUBSET.fullmatch(value) is None:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _metadata(current: object) -> tuple[str, str, list[str]]:
    if not isinstance(current, Mapping):
        return "__invalid__", _EPOCH, ["invalid:current"]
    view = _candidate_view(current)
    run_id = _text(view.get("run_id") or view.get("batch_run_id"))
    generated_at = _text(
        view.get("generated_at")
        or view.get("analyzed_at")
        or view.get("created_at")
    )
    errors: list[str] = []
    if not run_id:
        errors.append("missing:run_id")
    if not generated_at:
        errors.append("missing:generated_at")
    elif not _valid_timestamp(generated_at):
        errors.append("invalid:generated_at")
    return run_id or "__invalid__", generated_at if _valid_timestamp(generated_at) else _EPOCH, errors


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if isinstance(value, str) and value))


def _invalid_signal(signal_type: str, threshold: Mapping[str, int | float]) -> dict[str, Any]:
    return {
        "signal_type": signal_type,
        "name": signal_type,
        "severity": "info",
        "evidence": {
            "match_count": 0,
            "history_count": 0,
            "reason": "input_not_analyzed",
        },
        "matched_history_ids": [],
        "threshold": dict(threshold),
    }


def _signal(
    signal_type: str,
    *,
    evidence: Mapping[str, Any],
    matched_history_ids: Sequence[str],
    threshold: Mapping[str, int | float],
) -> dict[str, Any]:
    matches = _unique(matched_history_ids)
    min_matches = int(threshold["min_matches"])
    severity = "warning" if len(matches) >= min_matches else "info"
    evidence_payload = dict(evidence)
    evidence_payload.setdefault("match_count", len(matches))
    evidence_payload.setdefault("history_count", 0)
    return {
        "signal_type": signal_type,
        "name": signal_type,
        "severity": severity,
        "evidence": evidence_payload,
        "matched_history_ids": matches,
        "threshold": dict(threshold),
    }


def _history_items(history: object, window: int) -> tuple[list[tuple[str, Mapping[str, Any]]], list[str]]:
    errors: list[str] = []
    if isinstance(history, (str, bytes, bytearray)) or not isinstance(history, Sequence):
        return [], ["invalid:history"]
    raw_items = list(history)[-window:]
    items: list[tuple[str, Mapping[str, Any]]] = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, Mapping):
            errors.append(f"invalid:history_item:{index}")
            continue
        fallback = f"history-{index}"
        candidate_id = _candidate_id(raw, fallback=fallback)
        if candidate_id == fallback and not _candidate_id(raw):
            errors.append(f"missing:history_id:{index}")
        items.append((candidate_id, raw))
    return items, errors


def _title_signal(current: Mapping[str, Any], history: Sequence[tuple[str, Mapping[str, Any]]]) -> dict[str, Any]:
    threshold = _DEFAULT_THRESHOLDS["title_skeleton"]
    current_fp = _title_fingerprint(current)
    matches: list[str] = []
    for history_id, candidate in history:
        history_fp = _title_fingerprint(candidate)
        if (
            current_fp["unit_count"] >= threshold["min_shared_units"]
            and current_fp["fingerprint"]
            and current_fp["fingerprint"] == history_fp["fingerprint"]
            and history_fp["unit_count"] >= threshold["min_shared_units"]
        ):
            matches.append(history_id)
    return _signal(
        "title_skeleton",
        evidence={
            "current_fingerprint": current_fp["fingerprint"],
            "current_unit_count": current_fp["unit_count"],
            "match_count": len(matches),
            "history_count": len(history),
        },
        matched_history_ids=matches,
        threshold=threshold,
    )


def _opening_signal(current: Mapping[str, Any], history: Sequence[tuple[str, Mapping[str, Any]]]) -> dict[str, Any]:
    threshold = _DEFAULT_THRESHOLDS["opening_fact_suspense"]
    current_fp = _fact_suspense_fingerprint(current)
    matches: list[str] = []
    for history_id, candidate in history:
        history_fp = _fact_suspense_fingerprint(candidate)
        if (
            current_fp["has_fact"]
            and current_fp["has_suspense"]
            and history_fp["has_fact"]
            and history_fp["has_suspense"]
            and current_fp["fingerprint"] == history_fp["fingerprint"]
        ):
            matches.append(history_id)
    return _signal(
        "opening_fact_suspense",
        evidence={
            "current_fingerprint": current_fp["fingerprint"],
            "current_fact_features": current_fp["fact_features"],
            "current_suspense_features": current_fp["suspense_features"],
            "current_has_fact": current_fp["has_fact"],
            "current_has_suspense": current_fp["has_suspense"],
            "match_count": len(matches),
            "history_count": len(history),
        },
        matched_history_ids=matches,
        threshold=threshold,
    )


def _progression_signal(current: Mapping[str, Any], history: Sequence[tuple[str, Mapping[str, Any]]]) -> dict[str, Any]:
    threshold = _DEFAULT_THRESHOLDS["h2_paragraph_progression"]
    current_fp = _progression_fingerprint(current)
    matches: list[str] = []
    for history_id, candidate in history:
        history_fp = _progression_fingerprint(candidate)
        if (
            current_fp["usable"]
            and history_fp["usable"]
            and current_fp["fingerprint"] == history_fp["fingerprint"]
        ):
            matches.append(history_id)
    return _signal(
        "h2_paragraph_progression",
        evidence={
            "current_fingerprint": current_fp["fingerprint"],
            "h2_count": current_fp["h2_count"],
            "paragraph_count": current_fp["paragraph_count"],
            "match_count": len(matches),
            "history_count": len(history),
        },
        matched_history_ids=matches,
        threshold=threshold,
    )


def _number_adjective_signal(current: Mapping[str, Any], history: Sequence[tuple[str, Mapping[str, Any]]]) -> dict[str, Any]:
    threshold = _DEFAULT_THRESHOLDS["number_adjective_combination"]
    current_fp = _number_adjective_fingerprint(current)
    matches: list[str] = []
    for history_id, candidate in history:
        history_fp = _number_adjective_fingerprint(candidate)
        if (
            current_fp["usable"]
            and history_fp["usable"]
            and current_fp["fingerprint"] == history_fp["fingerprint"]
        ):
            matches.append(history_id)
    return _signal(
        "number_adjective_combination",
        evidence={
            "current_number_tokens": current_fp["number_tokens"],
            "current_adjective_groups": current_fp["adjective_groups"],
            "current_fingerprint": current_fp["fingerprint"],
            "match_count": len(matches),
            "history_count": len(history),
        },
        matched_history_ids=matches,
        threshold=threshold,
    )


def _ending_signal(current: Mapping[str, Any], history: Sequence[tuple[str, Mapping[str, Any]]]) -> dict[str, Any]:
    threshold = _DEFAULT_THRESHOLDS["mechanical_ending_question"]
    current_fp = _mechanical_ending_kind(current)
    matches: list[str] = []
    for history_id, candidate in history:
        history_fp = _mechanical_ending_kind(candidate)
        if (
            current_fp["is_mechanical_question"]
            and history_fp["is_mechanical_question"]
            and current_fp["fingerprint"] == history_fp["fingerprint"]
        ):
            matches.append(history_id)
    return _signal(
        "mechanical_ending_question",
        evidence={
            "current_fingerprint": current_fp["fingerprint"],
            "current_is_mechanical_question": current_fp["is_mechanical_question"],
            "match_count": len(matches),
            "history_count": len(history),
        },
        matched_history_ids=matches,
        threshold=threshold,
    )


def analyze_template_signals(
    current: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]],
    *,
    window: int = 5,
) -> dict[str, Any]:
    """Compare a candidate with only the recent history window.

    The result is evidence for human/controller review. It never rejects a
    candidate automatically and never grants publication authorization.
    """

    run_id, generated_at, errors = _metadata(current)
    if isinstance(window, bool) or not isinstance(window, int) or window <= 0:
        errors.append("invalid:window")
        safe_window = 0
    else:
        safe_window = window

    current_id = ""
    current_mapping: Mapping[str, Any] | None = None
    if isinstance(current, Mapping):
        current_mapping = current
        current_id = _candidate_id(current)
        if not current_id:
            errors.append("missing:current_id")
    else:
        errors.append("invalid:current")

    history_items, history_errors = _history_items(history, safe_window) if safe_window else ([], [])
    errors.extend(history_errors)

    current_hash = _stable_hash(current)
    history_hash = _stable_hash(history)
    input_hashes: dict[str, str] = {}
    if current_hash is not None:
        input_hashes["current"] = current_hash
    else:
        errors.append("invalid:input_hashes:current")
    if history_hash is not None:
        input_hashes["history"] = history_hash
    else:
        errors.append("invalid:input_hashes:history")

    if current_mapping is None:
        signals = [_invalid_signal(signal_type, _DEFAULT_THRESHOLDS[signal_type]) for signal_type in _SIGNAL_TYPES]
    else:
        signal_builders = (
            _title_signal,
            _opening_signal,
            _progression_signal,
            _number_adjective_signal,
            _ending_signal,
        )
        signals = [builder(current_mapping, history_items) for builder in signal_builders]

    if errors:
        decision = "manual_review"
    elif any(signal["severity"] == "warning" for signal in signals):
        decision = "manual_review"
    else:
        decision = "info"

    payload: dict[str, Any] = {
        "candidate_id": current_id,
        "window": safe_window,
        "history_count": len(history_items),
        "history_ids": [history_id for history_id, _ in history_items],
        "decision": decision,
        "auto_reject": False,
        "thresholds": deepcopy(_DEFAULT_THRESHOLDS),
        "signals": signals,
        "errors": _unique(errors),
        "publication_authorization": "not_authorized",
    }
    report = new_artifact_envelope(
        _SCHEMA,
        run_id,
        payload,
        generated_at=generated_at,
    )
    report["input_hashes"] = input_hashes
    return report


def _valid_threshold(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    min_matches = value.get("min_matches")
    if isinstance(min_matches, bool) or not isinstance(min_matches, int) or min_matches <= 0:
        return False
    for key, item in value.items():
        if not isinstance(key, str):
            return False
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return False
        if not math.isfinite(float(item)) or float(item) < 0:
            return False
    return True


def _validate_signal(signal: object, index: int, history_ids: set[str]) -> list[str]:
    errors: list[str] = []
    if not isinstance(signal, Mapping):
        return [f"invalid:signal:{index}"]
    signal_type = signal.get("signal_type")
    if signal_type not in _SIGNAL_TYPES:
        errors.append(f"invalid:signal_type:{index}")
    if "name" in signal and signal.get("name") != signal_type:
        errors.append(f"mismatch:signal_name:{index}")
    if signal.get("severity") not in _SEVERITIES:
        errors.append(f"invalid:severity:{index}")
    evidence = signal.get("evidence")
    if not isinstance(evidence, Mapping):
        errors.append(f"invalid:evidence:{index}")
    else:
        match_count = evidence.get("match_count")
        if isinstance(match_count, bool) or not isinstance(match_count, int) or match_count < 0:
            errors.append(f"invalid:evidence_match_count:{index}")
    matched = signal.get("matched_history_ids")
    if not isinstance(matched, list) or any(not isinstance(item, str) or not item for item in matched):
        errors.append(f"invalid:matched_history_ids:{index}")
        matched = []
    elif len(set(matched)) != len(matched):
        errors.append(f"unstable:matched_history_ids:{index}")
    else:
        if any(item not in history_ids for item in matched):
            errors.append(f"unknown:matched_history_id:{index}")
    threshold = signal.get("threshold")
    if not _valid_threshold(threshold):
        errors.append(f"invalid:threshold:{index}")
        threshold = {"min_matches": 1}
    if isinstance(evidence, Mapping) and isinstance(matched, list):
        match_count = evidence.get("match_count")
        if isinstance(match_count, int) and match_count != len(matched):
            errors.append(f"mismatch:evidence_match_count:{index}")
        min_matches = threshold.get("min_matches") if isinstance(threshold, Mapping) else None
        if isinstance(min_matches, int):
            if signal.get("severity") == "warning" and len(matched) < min_matches:
                errors.append(f"warning:below_threshold:{index}")
            if signal.get("severity") == "info" and len(matched) >= min_matches:
                errors.append(f"info:meets_threshold:{index}")
    return errors


def validate_template_signals(report: Mapping[str, Any]) -> list[str]:
    """Validate the closed V4 template-signal envelope, failing closed."""

    if not isinstance(report, Mapping):
        return ["invalid:template_signals"]
    raw_run_id = report.get("run_id")
    expected_run_id = raw_run_id if isinstance(raw_run_id, str) and raw_run_id.strip() else "__missing__"
    errors = validate_artifact_envelope(report, _SCHEMA, run_id=expected_run_id)
    if set(report) != _ENVELOPE_KEYS:
        errors.append("invalid:top_level")
    hashes = report.get("input_hashes")
    if isinstance(hashes, Mapping) and set(hashes) != {"current", "history"}:
        errors.append("invalid:input_hashes_keys")

    payload = report.get("payload")
    if not isinstance(payload, Mapping):
        return list(dict.fromkeys(errors + ["invalid:payload"]))

    required = (
        "candidate_id",
        "window",
        "history_count",
        "history_ids",
        "decision",
        "auto_reject",
        "thresholds",
        "signals",
        "errors",
        "publication_authorization",
    )
    for key in required:
        if key not in payload:
            errors.append(f"missing:payload:{key}")

    candidate_id = payload.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        errors.append("invalid:candidate_id")
    window = payload.get("window")
    if isinstance(window, bool) or not isinstance(window, int) or window <= 0:
        errors.append("invalid:window")
    history_count = payload.get("history_count")
    if isinstance(history_count, bool) or not isinstance(history_count, int) or history_count < 0:
        errors.append("invalid:history_count")
    history_ids = payload.get("history_ids")
    if not isinstance(history_ids, list) or any(not isinstance(item, str) or not item for item in history_ids):
        errors.append("invalid:history_ids")
        history_id_set: set[str] = set()
    else:
        history_id_set = set(history_ids)
        if len(history_id_set) != len(history_ids):
            errors.append("unstable:history_ids")
        if isinstance(history_count, int) and len(history_ids) != history_count:
            errors.append("mismatch:history_count")

    decision = payload.get("decision")
    if decision not in _DECISIONS:
        errors.append("invalid:decision")
    if payload.get("auto_reject") is not False:
        errors.append("auto_reject_must_be_false")
    if payload.get("publication_authorization") != "not_authorized":
        errors.append("publication_authorization_must_be_not_authorized")

    declared_errors = payload.get("errors")
    if not isinstance(declared_errors, list) or any(not isinstance(item, str) or not item for item in declared_errors):
        errors.append("invalid:errors")
    elif declared_errors:
        errors.extend(f"input:{item}" for item in declared_errors)

    thresholds = payload.get("thresholds")
    if not isinstance(thresholds, Mapping):
        errors.append("invalid:thresholds")
    else:
        for signal_type in _SIGNAL_TYPES:
            if signal_type not in thresholds:
                errors.append(f"missing:thresholds:{signal_type}")
            elif not _valid_threshold(thresholds[signal_type]):
                errors.append(f"invalid:thresholds:{signal_type}")

    signals = payload.get("signals")
    if not isinstance(signals, list):
        errors.append("invalid:signals")
    else:
        signal_types = [signal.get("signal_type") for signal in signals if isinstance(signal, Mapping)]
        if signal_types != list(_SIGNAL_TYPES):
            errors.append("invalid:signal_order")
        if len(signals) != len(_SIGNAL_TYPES):
            errors.append("invalid:signal_count")
        errors.extend(
            _validate_signal(signal, index, history_id_set)
            for index, signal in enumerate(signals)
        )

        has_warning = any(
            isinstance(signal, Mapping) and signal.get("severity") == "warning"
            for signal in signals
        )
        if decision == "info" and has_warning:
            errors.append("decision_must_be_manual_review")

        if isinstance(thresholds, Mapping):
            for signal in signals:
                if isinstance(signal, Mapping):
                    signal_type = signal.get("signal_type")
                    if signal_type in thresholds and signal.get("threshold") != thresholds[signal_type]:
                        errors.append(f"mismatch:threshold:{signal_type}")

    return list(dict.fromkeys(error for error in errors if isinstance(error, str)))
