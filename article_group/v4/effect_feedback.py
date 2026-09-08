"""Pure, offline effect feedback and pattern lifecycle helpers for V4.

The module consumes only caller-supplied metric exports.  It never contacts a
platform and it treats an unavailable metric as missing evidence rather than
as a zero-valued observation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import statistics
from typing import Any

from .contracts import EFFECT_STATES, new_artifact_envelope, validate_artifact_envelope


_SCHEMA = "v4-effect-feedback-v1"
_EPOCH = "1970-01-01T00:00:00Z"
_ENVELOPE_KEYS = frozenset(
    {"schema_version", "run_id", "generated_at", "input_hashes", "payload"}
)
_GROUP_KEYS = (
    "topic_family",
    "title_angle",
    "structure_signature",
    "platform",
)
_METRICS = (
    "impressions",
    "reads",
    "ctr",
    "completion_rate",
    "read_time_seconds",
    "likes",
    "comments",
    "favorites",
    "shares",
    "revenue",
    "rpm",
)
_RATE_METRICS = frozenset({"ctr", "completion_rate"})
_CORE_METRICS = (
    "impressions",
    "reads",
    "ctr",
    "completion_rate",
    "read_time_seconds",
)
_METRIC_STATUS_VALUES = frozenset({"available", "unavailable"})
_ADOPTION_DECISIONS = frozenset({"adopt", "approve_adoption"})
_BASELINE_DECISIONS = frozenset(
    {"approve_baseline", "confirm_baseline", "approve_validate"}
)
_CONTROLLER_DECISIONS = (
    _ADOPTION_DECISIONS | _BASELINE_DECISIONS | {"approve_reuse"}
)
_RFC3339_SUBSET = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(?:\.[0-9]+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$"
)


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if isinstance(value, str)))


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def _is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or _RFC3339_SUBSET.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _stable_json(value: object) -> str | None:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError):
        return None


def _stable_hash(value: object) -> str | None:
    encoded = _stable_json(value)
    if encoded is None:
        return None
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _metric_status(event: Mapping[str, Any], metric: str) -> object:
    direct_key = f"{metric}_status"
    if direct_key in event:
        return event.get(direct_key)
    statuses = event.get("metric_status")
    if isinstance(statuses, Mapping) and metric in statuses:
        return statuses.get(metric)
    return None


def _validate_metric_value(
    event: Mapping[str, Any], metric: str, errors: list[str]
) -> None:
    if metric not in event:
        errors.append(f"missing:metric:{metric}")
        return

    value = event.get(metric)
    status = _metric_status(event, metric)
    if status is not None and status not in _METRIC_STATUS_VALUES:
        errors.append(f"invalid:metric_status:{metric}")
        return

    if status == "unavailable":
        if value is not None:
            errors.append(f"invalid:unavailable_value:{metric}")
        return

    if value is None:
        errors.append(
            f"missing:metric_status:{metric}"
            if status is None
            else f"missing:metric_value:{metric}"
        )
        return
    if not _is_number(value):
        errors.append(f"invalid:metric:{metric}")
        return
    if metric in _RATE_METRICS:
        if not 0 <= float(value) <= 1:
            errors.append(f"invalid:rate:{metric}")
    elif float(value) < 0:
        errors.append(f"invalid:negative:{metric}")


def validate_metric_event(event: Mapping[str, Any]) -> list[str]:
    """Return stable validation errors for one real metric-export event.

    Every metric is either a finite, non-negative number (rates are bounded by
    0 and 1) or an explicit ``null`` paired with an ``unavailable`` status.
    Missing or malformed records are rejected without changing the caller's
    mapping.
    """

    if not isinstance(event, Mapping):
        return ["invalid:event"]

    errors: list[str] = []
    article_id = event.get("article_id")
    if not isinstance(article_id, str) or not article_id.strip():
        errors.append("missing:article_id")

    published_at = event.get("published_at")
    if published_at is None or (
        isinstance(published_at, str) and not published_at.strip()
    ):
        errors.append("missing:published_at")
    else:
        parsed = _parse_timestamp(published_at)
        if parsed is None:
            errors.append("invalid:published_at")
        elif parsed.astimezone(timezone.utc) > datetime.now(timezone.utc):
            errors.append("future:published_at")

    platform = event.get("platform")
    if not isinstance(platform, str) or not platform.strip():
        errors.append("missing:platform")

    statuses = event.get("metric_status")
    if statuses is not None and not isinstance(statuses, Mapping):
        errors.append("invalid:metric_status")
    elif isinstance(statuses, Mapping):
        for metric in sorted(
            statuses,
            key=lambda value: (type(value).__name__, repr(value)),
        ):
            if metric not in _METRICS:
                errors.append(f"unknown:metric_status:{metric}")

    for metric in _METRICS:
        _validate_metric_value(event, metric, errors)

    publication_status = event.get("publication_status")
    if publication_status is not None and publication_status != "published":
        errors.append("invalid:publication_status")

    return _unique(errors)


def _event_errors(
    metric_events: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    if not _is_sequence(metric_events):
        return [], ["invalid:metric_events"]

    valid: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, event in enumerate(metric_events):
        if not isinstance(event, Mapping):
            errors.append(f"invalid:event:{index}")
            continue
        event_errors = validate_metric_event(event)
        if event_errors:
            errors.extend(f"event:{index}:{error}" for error in event_errors)
        else:
            valid.append(dict(event))
    return valid, _unique(errors)


def _group_fields(
    event: Mapping[str, Any], group_by: Sequence[str]
) -> dict[str, str] | None:
    group: dict[str, str] = {}
    for key in group_by:
        value = event.get(key)
        if not isinstance(value, str) or not value.strip():
            return None
        group[key] = value.strip()
    return group


def _baseline_value(event: Mapping[str, Any]) -> object:
    if "baseline" in event:
        return event.get("baseline")
    return event.get("baseline_reference")


def _valid_baseline(value: object) -> bool:
    return (
        value is None
        or (isinstance(value, str) and bool(value.strip()))
        or isinstance(value, Mapping)
    )


def _baseline_for_events(events: Sequence[Mapping[str, Any]]) -> tuple[object, bool]:
    values = [_baseline_value(event) for event in events]
    if any(not _valid_baseline(value) for value in values):
        return None, False
    present = [value for value in values if value is not None]
    if not present:
        return None, True
    signatures: dict[str, object] = {}
    for value in present:
        signature = _stable_json(value)
        if signature is None:
            return None, False
        signatures.setdefault(signature, value)
    if len(signatures) != 1:
        return None, False
    return deepcopy(next(iter(signatures.values()))), True


def _metric_statistics(events: Sequence[Mapping[str, Any]]) -> tuple[
    dict[str, dict[str, Any]], dict[str, int], dict[str, Any]
]:
    statistics_by_metric: dict[str, dict[str, Any]] = {}
    available_counts: dict[str, int] = {}
    medians: dict[str, Any] = {}
    for metric in _METRICS:
        values = [
            event[metric]
            for event in events
            if event.get(metric) is not None
        ]
        available_counts[metric] = len(values)
        median = statistics.median(values) if values else None
        statistics_by_metric[metric] = {
            "median": median,
            "available_count": len(values),
        }
        medians[metric] = median
    return statistics_by_metric, available_counts, medians


def _published_dates(events: Sequence[Mapping[str, Any]]) -> list[str]:
    dates: set[str] = set()
    for event in events:
        parsed = _parse_timestamp(event.get("published_at"))
        if parsed is not None:
            dates.add(parsed.date().isoformat())
    return sorted(dates)


def _summary(
    events: Sequence[Mapping[str, Any]],
    *,
    group: Mapping[str, str] | None = None,
    baseline: object = None,
) -> dict[str, Any]:
    metric_statistics, available_counts, medians = _metric_statistics(events)
    dates = _published_dates(events)
    article_ids = sorted(
        {
            event["article_id"]
            for event in events
            if isinstance(event.get("article_id"), str)
        }
    )
    result: dict[str, Any] = {
        "sample_count": len(events),
        "unique_article_count": len(article_ids),
        "article_ids": article_ids,
        "distinct_published_dates": len(dates),
        "published_dates": dates,
        "available_metric_count": available_counts,
        "available_metric_counts": deepcopy(available_counts),
        "statistics": metric_statistics,
        "medians": medians,
        "baseline": deepcopy(baseline),
        "baseline_reference": deepcopy(baseline),
        "publication_authorization": "not_authorized",
    }
    if group is not None:
        result["group"] = dict(group)
        result["group_by"] = list(group)
        for key, value in group.items():
            result[key] = value
    return result


def _valid_group_by(group_by: Sequence[str]) -> list[str] | None:
    if not _is_sequence(group_by):
        return None
    keys = list(group_by)
    if not keys or any(not isinstance(key, str) for key in keys):
        return None
    if len(set(keys)) != len(keys):
        return None
    if any(key not in _GROUP_KEYS for key in keys):
        return None
    return keys


def aggregate_effects(
    metric_events: Sequence[Mapping[str, Any]],
    *,
    group_by: Sequence[str],
) -> list[dict[str, Any]]:
    """Aggregate valid exported events into deterministic median summaries.

    This function fails closed with an empty list when any input event or
    grouping key is malformed.  It never turns an unavailable metric into a
    zero and it does not fabricate a baseline when one was not supplied.
    """

    keys = _valid_group_by(group_by)
    if keys is None:
        return []
    events, errors = _event_errors(metric_events)
    if errors or not events:
        return []

    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    groups: dict[tuple[str, ...], dict[str, str]] = {}
    for event in events:
        group = _group_fields(event, keys)
        if group is None:
            return []
        group_key = tuple(group[key] for key in keys)
        grouped.setdefault(group_key, []).append(event)
        groups[group_key] = group

    rows: list[dict[str, Any]] = []
    for group_key in sorted(grouped):
        group_events = grouped[group_key]
        baseline, baseline_ok = _baseline_for_events(group_events)
        if not baseline_ok:
            return []
        rows.append(
            _summary(group_events, group=groups[group_key], baseline=baseline)
        )
    return rows


def _pattern_payload(pattern: Mapping[str, Any]) -> tuple[Mapping[str, Any], bool]:
    return (
        pattern["payload"],
        True,
    ) if pattern.get("schema_version") == _SCHEMA and isinstance(
        pattern.get("payload"), Mapping
    ) else (pattern, False)


def _baseline_confirmed(
    pattern: Mapping[str, Any], controller_decision: str | None
) -> bool:
    if pattern.get("baseline_confirmed") is True:
        return True
    if pattern.get("controller_baseline_confirmed") is True:
        return True
    baseline_status = pattern.get("baseline_status")
    if isinstance(baseline_status, str) and baseline_status in {
        "confirmed",
        "approved",
    }:
        return True
    baseline = pattern.get("baseline")
    if isinstance(baseline, Mapping) and baseline.get("confirmed") is True:
        return True
    return (
        isinstance(controller_decision, str)
        and controller_decision in _BASELINE_DECISIONS
    )


def _pattern_baseline(
    pattern: Mapping[str, Any], events: Sequence[Mapping[str, Any]]
) -> tuple[object, bool]:
    if "baseline" in pattern:
        value = pattern.get("baseline")
        return (deepcopy(value), _valid_baseline(value) and value is not None)
    if "baseline_reference" in pattern:
        value = pattern.get("baseline_reference")
        return (deepcopy(value), _valid_baseline(value) and value is not None)
    return _baseline_for_events(events)


def _validate_pattern(
    pattern: Mapping[str, Any],
    *,
    envelope: bool,
    controller_decision: str | None,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(pattern, Mapping):
        return ["invalid:pattern"]
    if not envelope:
        pattern_id = pattern.get("pattern_id")
        if not isinstance(pattern_id, str) or not pattern_id.strip():
            errors.append("missing:pattern_id")
    state = pattern.get("state")
    if state not in EFFECT_STATES:
        errors.append("invalid:state")
    if controller_decision is not None and (
        not isinstance(controller_decision, str)
        or controller_decision not in _CONTROLLER_DECISIONS
    ):
        errors.append("invalid:controller_decision")
    return errors


def _lifecycle_payload(
    pattern: Mapping[str, Any],
    metric_events: Sequence[Mapping[str, Any]],
    *,
    controller_decision: str | None,
    envelope: bool,
) -> dict[str, Any]:
    result = deepcopy(dict(pattern))
    pattern_errors = _validate_pattern(
        pattern,
        envelope=envelope,
        controller_decision=controller_decision,
    )
    errors = list(pattern_errors)
    valid_events, event_errors = _event_errors(metric_events)
    errors.extend(event_errors)
    if not _is_sequence(metric_events):
        valid_events = []

    baseline, baseline_ok = _pattern_baseline(pattern, valid_events)
    if not baseline_ok:
        errors.append("invalid:baseline")
    baseline_confirmed = _baseline_confirmed(pattern, controller_decision)

    summary = _summary(valid_events, baseline=baseline)
    result.update(summary)
    result["baseline"] = deepcopy(baseline)
    result["baseline_reference"] = deepcopy(baseline)
    result["validation"] = {
        "minimum_published_samples": 3,
        "minimum_distinct_published_dates": 2,
        "core_metrics": list(_CORE_METRICS),
        "sample_requirement_met": summary["unique_article_count"] >= 3,
        "date_requirement_met": summary["distinct_published_dates"] >= 2,
        "core_metrics_complete": all(
            summary["available_metric_count"][metric] == len(valid_events)
            for metric in _CORE_METRICS
        )
        and bool(valid_events),
        "baseline_present": baseline is not None and baseline_ok,
        "baseline_confirmed": baseline_confirmed,
        "validated": False,
    }

    evidence_shape_ready = (
        summary["unique_article_count"] >= 3
        and summary["distinct_published_dates"] >= 2
        and result["validation"]["core_metrics_complete"]
        and result["validation"]["baseline_present"]
    )
    if evidence_shape_ready and not baseline_confirmed:
        errors.append("missing:baseline_confirmation")

    raw_state = pattern.get("state")
    state = raw_state if raw_state in EFFECT_STATES else raw_state
    explicit_adoption = (
        isinstance(controller_decision, str)
        and controller_decision in _ADOPTION_DECISIONS
    ) or any(
        pattern.get(key) is True
        for key in ("adopted", "adoption_confirmed")
    )
    if raw_state == "candidate" and explicit_adoption and not pattern_errors and not event_errors:
        state = "adopted"

    has_valid_evidence = not event_errors
    evidence_ready = (
        summary["unique_article_count"] >= 3
        and summary["distinct_published_dates"] >= 2
        and result["validation"]["core_metrics_complete"]
        and result["validation"]["baseline_present"]
        and baseline_confirmed
    )
    if state in {"adopted", "measured"} and has_valid_evidence and not pattern_errors:
        if valid_events:
            state = "measured"
        if state == "measured" and evidence_ready and not errors:
            state = "validated"
    elif state == "validated" and errors and not has_valid_evidence:
        state = "validated"

    if state == "validated":
        result["validation"]["validated"] = evidence_ready or raw_state == "validated"
        if (
            controller_decision == "approve_reuse"
            and not errors
        ):
            state = "reusable_pattern"
    elif state == "reusable_pattern":
        result["validation"]["validated"] = True

    if state == "candidate" and raw_state == "candidate" and not explicit_adoption:
        result["validation"]["validated"] = False

    result["state"] = state
    result["reusable"] = state == "reusable_pattern"
    if controller_decision is not None:
        result["controller_decision"] = controller_decision
    elif "controller_decision" in result:
        result["controller_decision"] = result.get("controller_decision")
    result["errors"] = _unique(errors)
    result["publication_authorization"] = "not_authorized"
    result["transition"] = {
        "from": raw_state,
        "to": state,
    }
    return result


def _envelope_result(
    pattern: Mapping[str, Any],
    payload: Mapping[str, Any],
    metric_events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    run_id = pattern.get("run_id") if isinstance(pattern.get("run_id"), str) else ""
    generated_at = (
        pattern.get("generated_at")
        if isinstance(pattern.get("generated_at"), str)
        else _EPOCH
    )
    result = new_artifact_envelope(
        _SCHEMA,
        run_id,
        payload,
        generated_at=generated_at,
    )
    original_hashes = pattern.get("input_hashes")
    if isinstance(original_hashes, Mapping):
        result["input_hashes"] = deepcopy(dict(original_hashes))
    metric_hash = _stable_hash(metric_events)
    if metric_hash is not None:
        result["input_hashes"]["metric_events"] = metric_hash
    return result


def advance_pattern_lifecycle(
    pattern: Mapping[str, Any],
    metric_events: Sequence[Mapping[str, Any]],
    *,
    controller_decision: str | None = None,
) -> dict[str, Any]:
    """Advance only evidence-supported lifecycle states.

    Plain pattern records remain convenient for in-memory callers.  When the
    supplied pattern is already a ``v4-effect-feedback-v1`` envelope, the
    returned value is a new closed envelope with the updated payload and
    deterministic input hashes.
    """

    if not isinstance(pattern, Mapping):
        return {
            "state": None,
            "reusable": False,
            "errors": ["invalid:pattern"],
            "validation": {"validated": False},
            "publication_authorization": "not_authorized",
        }

    raw_payload, envelope = _pattern_payload(pattern)
    envelope_errors: list[str] = []
    if envelope:
        raw_run_id = pattern.get("run_id")
        expected_run_id = (
            raw_run_id if isinstance(raw_run_id, str) and raw_run_id.strip() else "__missing__"
        )
        envelope_errors.extend(
            validate_artifact_envelope(
                pattern,
                _SCHEMA,
                run_id=expected_run_id,
            )
        )
        if set(pattern) != _ENVELOPE_KEYS:
            envelope_errors.append("invalid:top_level")

    payload = _lifecycle_payload(
        raw_payload,
        metric_events,
        controller_decision=controller_decision,
        envelope=envelope,
    )
    if envelope_errors:
        payload["errors"] = _unique([*envelope_errors, *payload.get("errors", [])])
        payload["validation"]["validated"] = False
        if payload.get("state") == "reusable_pattern":
            payload["state"] = "validated"
            payload["reusable"] = False

    if envelope:
        return _envelope_result(pattern, payload, metric_events)

    pattern_hash = _stable_hash(pattern)
    events_hash = _stable_hash(metric_events)
    input_hashes: dict[str, str] = {}
    if pattern_hash is not None:
        input_hashes["pattern"] = pattern_hash
    if events_hash is not None:
        input_hashes["metric_events"] = events_hash
    payload["input_hashes"] = input_hashes
    if isinstance(pattern.get("run_id"), str):
        payload["run_id"] = pattern["run_id"]
    if isinstance(pattern.get("generated_at"), str):
        payload["generated_at"] = pattern["generated_at"]
    payload["schema_version"] = _SCHEMA
    return payload


__all__ = [
    "aggregate_effects",
    "advance_pattern_lifecycle",
    "validate_metric_event",
]
