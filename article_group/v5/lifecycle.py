"""Offline, non-authorizing content lifecycle helpers for Article Group V5."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re
from typing import Any

from .contracts import (
    LIFECYCLE_STATES,
    PUBLICATION_AUTHORIZATION,
    new_artifact_envelope,
    payload_of,
    validate_v5_artifact_envelope,
)


_SCHEMA_VERSION = "v5-content-lifecycle-v1"
_STATE_INDEX = {state: index for index, state in enumerate(LIFECYCLE_STATES)}
_GATED_STATES = frozenset({"published", "evergreen", "archived"})
_OBSERVATION_STATES = frozenset(
    {"observing", "stable", "rising", "decaying"}
)
_OBSERVATION_EVENT_TYPES = frozenset(
    {"observation", "observed", "metric", "metrics", "observing"}
)
_CONTROLLER_DECISIONS = frozenset({"approve_evergreen", "archive"})
_REQUIRED_PAYLOAD_FIELDS = (
    "article_id",
    "state",
    "blockers",
    "evidence_refs",
    "next_action",
    "publication_authorization",
)
_NEXT_ACTIONS = {
    "draft": "obtain_external_publication_evidence",
    "published": "record_observations",
    "observing": "record_observation_trend",
    "stable": "monitor_trend",
    "rising": "append_related_content",
    "decaying": "stop_repeated_followup",
    "evergreen": "consider_evergreen_candidate",
    "archived": "retain_learning_only",
}
_RFC3339_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(?:\.[0-9]+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$"
)
_PSEUDO_EVENT_REFERENCE = re.compile(r"event:[0-9]+$")
_INVALID_TREND = object()


def _unique(values: Sequence[object]) -> list[str]:
    return list(dict.fromkeys(value for value in values if isinstance(value, str)))


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def _valid_string_list(value: object) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def _valid_evidence_refs(value: object) -> bool:
    return _valid_string_list(value) and all(
        _PSEUDO_EVENT_REFERENCE.fullmatch(item.strip()) is None
        for item in value
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


def _next_action(state: object) -> str:
    return (
        _NEXT_ACTIONS.get(state, "review_lifecycle_state")
        if isinstance(state, str)
        else "review_lifecycle_state"
    )


def _event_reference(event: Mapping[str, Any]) -> str | None:
    for key in ("evidence_ref", "event_id"):
        reference = _text(event.get(key))
        if reference and _PSEUDO_EVENT_REFERENCE.fullmatch(reference) is None:
            return reference
    return None


def _event_type(event: Mapping[str, Any]) -> str:
    return _text(event.get("event_type"))


def _parse_rfc3339(value: object) -> datetime | None:
    if not isinstance(value, str) or value != value.strip():
        return None
    if _RFC3339_PATTERN.fullmatch(value) is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _complete_publication_event(
    event: Mapping[str, Any], article_id: str
) -> bool:
    return (
        _event_type(event) == "published"
        and _text(event.get("article_id")) == article_id
        and _parse_rfc3339(event.get("published_at")) is not None
        and bool(_text(event.get("platform")))
        and _event_reference(event) is not None
    )


def _publication_evidence(
    events: Sequence[object],
    article_id: str,
) -> tuple[bool, bool, list[dict[str, str]]]:
    publication_seen = False
    complete = False
    evidence: list[dict[str, str]] = []
    for event in events:
        if not isinstance(event, Mapping) or _event_type(event) != "published":
            continue
        publication_seen = True
        reference = _event_reference(event)
        if _complete_publication_event(event, article_id):
            complete = True
            if reference is not None:
                evidence.append(
                    {
                        "article_id": article_id,
                        "published_at": event["published_at"],
                        "platform": _text(event.get("platform")),
                        "ref": reference,
                    }
                )
    return publication_seen, complete, evidence


def _observation_trend(
    event: Mapping[str, Any],
) -> tuple[str | None | object, bool]:
    for key in ("trend", "observation_trend"):
        if key in event:
            value = _text(event.get(key))
            return (value, True) if value else (_INVALID_TREND, True)

    for key in ("observation", "metrics"):
        nested = event.get(key)
        if isinstance(nested, Mapping) and "trend" in nested:
            value = _text(nested.get("trend"))
            return (value, True) if value else (_INVALID_TREND, True)

    return None, False


def _non_empty_record(value: object) -> bool:
    if isinstance(value, Mapping):
        return bool(value)
    return _is_sequence(value) and bool(value)


def _observation_timestamp(event: Mapping[str, Any]) -> datetime | None:
    timestamp_keys = [
        key for key in ("observed_at", "timestamp") if key in event
    ]
    if not timestamp_keys:
        return None
    parsed = [
        _parse_rfc3339(event.get(key))
        for key in timestamp_keys
    ]
    if any(value is None for value in parsed):
        return None
    return parsed[0]


def _observation_timestamp_value(event: Mapping[str, Any]) -> str | None:
    for key in ("observed_at", "timestamp"):
        if key in event and isinstance(event.get(key), str):
            return event[key]
    return None


def _valid_observation_event(
    event: Mapping[str, Any], article_id: str
) -> tuple[
    bool,
    datetime | None,
    str | None,
    str | None,
    str | None,
]:
    if _event_type(event) not in _OBSERVATION_EVENT_TYPES:
        return False, None, None, None, None
    if _text(event.get("article_id")) != article_id:
        return False, None, None, None, None

    timestamp = _observation_timestamp(event)
    reference = _event_reference(event)
    has_metrics = any(
        _non_empty_record(event.get(key))
        for key in ("metrics", "window", "observation_window")
    )
    if timestamp is None or reference is None or not has_metrics:
        return False, None, None, None, None

    trend, trend_present = _observation_trend(event)
    if trend_present and (
        trend is _INVALID_TREND
        or not isinstance(trend, str)
        or trend not in _OBSERVATION_STATES
    ):
        return False, None, None, None, None
    return (
        True,
        timestamp,
        trend if isinstance(trend, str) else None,
        reference,
        _observation_timestamp_value(event),
    )


def _observation_evidence_record(
    event: Mapping[str, Any],
    *,
    article_id: str,
    timestamp: str,
    reference: str,
    trend: str | None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "article_id": article_id,
        "timestamp": timestamp,
        "ref": reference,
    }
    for key in ("metrics", "window", "observation_window"):
        value = event.get(key)
        if not _non_empty_record(value):
            continue
        evidence["window" if key == "observation_window" else key] = deepcopy(
            value
        )
    if trend is not None:
        evidence["trend"] = trend
    return evidence


def _observation_evidence(
    events: Sequence[object],
    article_id: str,
) -> tuple[
    bool,
    str | None,
    str | None,
    list[str],
    bool,
    list[dict[str, Any]],
]:
    observed = False
    candidates: list[tuple[datetime, int, str | None, str]] = []
    references: list[str] = []
    evidence: list[dict[str, Any]] = []
    invalid_observation = False

    for index, event in enumerate(events):
        if not isinstance(event, Mapping) or _event_type(event) == "published":
            continue

        valid, timestamp, trend, reference, timestamp_value = (
            _valid_observation_event(event, article_id)
        )
        if not valid:
            if (
                _event_type(event) in _OBSERVATION_EVENT_TYPES
                or _event_type(event) in _OBSERVATION_STATES
                or any(
                    key in event
                    for key in (
                        "observed_at",
                        "timestamp",
                        "observation",
                        "metrics",
                        "window",
                        "observation_window",
                        "trend",
                        "observation_trend",
                    )
                )
            ):
                invalid_observation = True
            continue

        observed = True
        if (
            timestamp is None
            or timestamp_value is None
            or reference is None
        ):
            continue
        references.append(reference)
        evidence.append(
            _observation_evidence_record(
                event,
                article_id=article_id,
                timestamp=timestamp_value,
                reference=reference,
                trend=trend,
            )
        )
        candidates.append((timestamp, index, trend, reference))

    if not candidates:
        return observed, None, None, references, invalid_observation, evidence

    def sort_key(
        candidate: tuple[datetime, int, str | None, str]
    ) -> tuple[datetime, int]:
        timestamp, index, _, _ = candidate
        return timestamp, index

    _, _, trend, reference = max(candidates, key=sort_key)
    return observed, trend, reference, references, invalid_observation, evidence


def _evidence_records(value: object) -> list[Mapping[str, Any]] | None:
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, list) and all(
        isinstance(item, Mapping) for item in value
    ):
        return list(value)
    return None


def _publication_evidence_payload(
    evidence: Sequence[Mapping[str, Any]],
) -> object:
    if not evidence:
        return []
    if len(evidence) == 1:
        return deepcopy(dict(evidence[0]))
    return deepcopy([dict(item) for item in evidence])


def _valid_publication_evidence(
    value: object,
    article_id: str,
) -> tuple[bool, set[str]]:
    records = _evidence_records(value)
    if records is None:
        return False, set()
    refs: set[str] = set()
    valid = True
    for evidence in records:
        reference = _text(evidence.get("ref"))
        item_valid = (
            _text(evidence.get("article_id")) == article_id
            and _parse_rfc3339(evidence.get("published_at")) is not None
            and bool(_text(evidence.get("platform")))
            and bool(reference)
            and _PSEUDO_EVENT_REFERENCE.fullmatch(reference) is None
        )
        if not item_valid:
            valid = False
            continue
        refs.add(reference)
    return valid, refs


def _valid_observation_evidence(
    value: object,
    article_id: str,
) -> tuple[bool, set[str], dict[str, set[str]]]:
    records = _evidence_records(value)
    if records is None:
        return False, set(), {}
    refs: set[str] = set()
    trends: dict[str, set[str]] = {}
    valid = True
    for evidence in records:
        reference = _text(evidence.get("ref"))
        timestamp = evidence.get("timestamp", evidence.get("observed_at"))
        has_metrics = any(
            _non_empty_record(evidence.get(key))
            for key in ("metrics", "window", "observation_window")
        )
        trend = evidence.get("trend")
        item_valid = (
            _text(evidence.get("article_id")) == article_id
            and _parse_rfc3339(timestamp) is not None
            and bool(reference)
            and _PSEUDO_EVENT_REFERENCE.fullmatch(reference) is None
            and has_metrics
            and (
                trend is None
                or (
                    isinstance(trend, str)
                    and trend in _OBSERVATION_STATES
                )
            )
        )
        if not item_valid:
            valid = False
            continue
        refs.add(reference)
        if isinstance(trend, str):
            trends.setdefault(reference, set()).add(trend)
    return valid, refs, trends


def _record_result(
    record: Mapping[str, Any],
    payload: Mapping[str, Any],
    events: Sequence[object],
) -> dict[str, Any]:
    run_id = record.get("run_id") if isinstance(record.get("run_id"), str) else "v5-local"
    generated_at = (
        record.get("generated_at")
        if isinstance(record.get("generated_at"), str)
        else "1970-01-01T00:00:00Z"
    )
    result = new_artifact_envelope(
        _SCHEMA_VERSION,
        run_id,
        payload,
        generated_at=generated_at,
    )
    input_hashes = record.get("input_hashes")
    if isinstance(input_hashes, Mapping):
        result["input_hashes"] = deepcopy(dict(input_hashes))
    events_hash = _stable_hash(events)
    if events_hash is not None:
        result["input_hashes"]["events"] = events_hash
    return result


def build_content_lifecycle(
    *,
    article_id: str,
    run_id: str,
    generated_at: str,
    state: str = "draft",
) -> dict[str, Any]:
    """Build a closed V5 lifecycle envelope without publication authority."""

    if state not in LIFECYCLE_STATES:
        raise ValueError("invalid_lifecycle_state")
    if state in _GATED_STATES:
        raise ValueError("gated_lifecycle_state_requires_transition")
    if state != "draft":
        raise ValueError("observation_lifecycle_state_requires_transition")

    payload = {
        "article_id": article_id,
        "state": state,
        "blockers": [],
        "evidence_refs": [],
        "next_action": _next_action(state),
        "publication_authorization": PUBLICATION_AUTHORIZATION,
        "publication_evidence": [],
        "observation_evidence": [],
    }
    return new_artifact_envelope(
        _SCHEMA_VERSION,
        run_id,
        payload,
        generated_at=generated_at,
    )


def validate_lifecycle_record(record: Mapping[str, Any]) -> list[str]:
    """Return stable validation errors for a V5 lifecycle envelope."""

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

    for field in _REQUIRED_PAYLOAD_FIELDS:
        if field not in payload:
            errors.append(f"missing:payload:{field}")

    if not _text(payload.get("article_id")):
        errors.append("invalid:article_id")
    state = payload.get("state")
    state_valid = isinstance(state, str) and state in LIFECYCLE_STATES
    if not state_valid:
        errors.append("invalid:state")
    if not _valid_string_list(payload.get("blockers")):
        errors.append("invalid:blockers")
    if not _valid_evidence_refs(payload.get("evidence_refs")):
        errors.append("invalid:evidence_refs")
    next_action = payload.get("next_action")
    if not _text(next_action):
        errors.append("invalid:next_action")
    elif state_valid and next_action != _NEXT_ACTIONS[state]:
        errors.append("next_action_state_mismatch")
    if payload.get("publication_authorization") != PUBLICATION_AUTHORIZATION:
        errors.append("publication_authorization_must_be_not_authorized")

    publication_evidence = payload.get("publication_evidence")
    publication_evidence_valid, publication_refs = _valid_publication_evidence(
        publication_evidence,
        _text(payload.get("article_id")),
    )
    if publication_evidence is not None and not publication_evidence_valid:
        errors.append("invalid:publication_evidence")

    observation_evidence = payload.get("observation_evidence")
    (
        observation_evidence_valid,
        observation_refs,
        observation_trends,
    ) = _valid_observation_evidence(
        observation_evidence,
        _text(payload.get("article_id")),
    )
    if observation_evidence is not None and not observation_evidence_valid:
        errors.append("invalid:observation_evidence")

    evidence_refs = payload.get("evidence_refs")
    if _valid_evidence_refs(evidence_refs):
        evidence_ref_set = set(evidence_refs)
        structured_refs = publication_refs | observation_refs
        if structured_refs - evidence_ref_set:
            errors.append("evidence_refs_missing_structured_evidence")
        if evidence_ref_set - structured_refs:
            errors.append("evidence_refs_not_backed_by_structured_evidence")
    else:
        evidence_ref_set = set()

    if state_valid and state != "draft":
        if not publication_evidence_valid or not publication_refs:
            errors.append("published_state_requires_publication_evidence")

    if state_valid and state in _OBSERVATION_STATES:
        if not observation_evidence_valid or not observation_refs:
            errors.append("observation_state_requires_observation_evidence")
        if state in {"stable", "rising", "decaying"}:
            if payload.get("observation_trend") != state:
                errors.append("observation_trend_state_mismatch")
            trend_reference = _text(payload.get("observation_trend_ref"))
            if (
                not trend_reference
                or trend_reference not in observation_refs
                or state not in observation_trends.get(trend_reference, set())
            ):
                errors.append("observation_trend_ref_mismatch")

    if state_valid and state in _GATED_STATES:
        if not _valid_evidence_refs(evidence_refs) or not evidence_refs:
            errors.append("gated_state_requires_evidence")

        transition = payload.get("transition")
        if not isinstance(transition, Mapping):
            errors.append("missing:transition")
        else:
            from_state = transition.get("from")
            to_state = transition.get("to")
            reason = transition.get("reason")
            transition_valid = (
                isinstance(from_state, str)
                and from_state in LIFECYCLE_STATES
                and to_state == state
                and _text(reason) != ""
            )
            if transition_valid and _STATE_INDEX[state] <= _STATE_INDEX[from_state]:
                transition_valid = False
            if not transition_valid:
                errors.append("invalid:transition")

        if state in {"evergreen", "archived"}:
            expected_decision = (
                "approve_evergreen"
                if state == "evergreen"
                else "archive"
            )
            if payload.get("controller_decision") != expected_decision:
                errors.append("gated_state_requires_controller_decision")

    return list(dict.fromkeys(errors))


def advance_content_lifecycle(
    record: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    *,
    controller_decision: str | None = None,
) -> dict[str, Any]:
    """Advance a lifecycle only when recorded evidence supports the move."""

    if not isinstance(record, Mapping):
        record = {}

    source_payload = payload_of(record)
    payload = deepcopy(dict(source_payload))
    record_errors = validate_lifecycle_record(record)
    source_state = source_payload.get("state")
    state = (
        source_state
        if isinstance(source_state, str) and source_state in _STATE_INDEX
        else "draft"
    )

    blockers: list[str] = []
    if record_errors:
        blockers.extend(record_errors)

    events_valid = _is_sequence(events)
    event_items: list[object] = list(events) if events_valid else []
    if not events_valid:
        blockers.append("invalid:events")

    decision_valid = controller_decision is None or (
        isinstance(controller_decision, str)
        and controller_decision in _CONTROLLER_DECISIONS
    )
    if not decision_valid:
        blockers.append("invalid:controller_decision")

    existing_refs = source_payload.get("evidence_refs")
    evidence_refs = (
        list(existing_refs) if _valid_evidence_refs(existing_refs) else []
    )
    existing_publication_evidence = _evidence_records(
        source_payload.get("publication_evidence")
    ) or []
    existing_observation_evidence = _evidence_records(
        source_payload.get("observation_evidence")
    ) or []
    article_id = _text(source_payload.get("article_id"))
    (
        publication_seen,
        publication_complete,
        publication_evidence,
    ) = _publication_evidence(
        event_items,
        article_id,
    )
    (
        observed,
        trend,
        trend_reference,
        observation_refs,
        invalid_observation,
        observation_evidence,
    ) = _observation_evidence(event_items, article_id)
    all_publication_evidence = [
        *existing_publication_evidence,
        *publication_evidence,
    ]
    all_observation_evidence = [
        *existing_observation_evidence,
        *observation_evidence,
    ]
    evidence_refs = _unique(
        [
            *evidence_refs,
            *[
                _text(item.get("ref"))
                for item in publication_evidence
            ],
            *observation_refs,
        ]
    )
    if invalid_observation:
        blockers.append("observation_event_invalid")

    target_state = state
    reason = "no_supported_transition"
    terminal_decision_mismatch = (
        state == "archived"
        and controller_decision not in (None, "archive")
    ) or (
        state == "evergreen"
        and controller_decision not in (None, "approve_evergreen", "archive")
    )
    if terminal_decision_mismatch:
        blockers.append("controller_decision_mismatch")

    can_advance = (
        not record_errors
        and events_valid
        and decision_valid
        and not invalid_observation
        and not terminal_decision_mismatch
    )

    if can_advance and controller_decision == "archive":
        if state != "archived":
            if evidence_refs:
                target_state = "archived"
                reason = "controller_approved_archive"
            else:
                blockers.append("gated_state_requires_evidence")
                reason = "archive_requires_evidence"
    elif can_advance and controller_decision == "approve_evergreen":
        if state == "draft":
            blockers.append("evergreen_requires_published_content")
            reason = "evergreen_requires_published_content"
        elif state not in {"evergreen", "archived"}:
            if evidence_refs:
                target_state = "evergreen"
                reason = "controller_approved_evergreen"
            else:
                blockers.append("gated_state_requires_evidence")
                reason = "evergreen_requires_evidence"
    elif can_advance:
        if state == "draft":
            if publication_complete:
                target_state = "published"
                reason = "external_publication_event_recorded"
            else:
                blockers.append("publication_event_required")
                reason = (
                    "publication_event_incomplete"
                    if publication_seen
                    else "publication_event_required"
                )
        elif state in {"evergreen", "archived"}:
            reason = "terminal_state"
        elif trend is not None:
            trend_index = _STATE_INDEX[trend]
            state_index = _STATE_INDEX[state]
            if trend_index > state_index:
                target_state = trend
                reason = f"observation_trend:{trend}"
            elif trend_index < state_index:
                blockers.append("forward_only_transition")
                reason = "forward_only_transition"
        elif observed:
            if state == "published":
                target_state = "observing"
                reason = "observation_window_recorded"
            elif state == "observing":
                blockers.append("observation_trend_required")
                reason = "observation_trend_required"

    if can_advance and trend is not None and trend_reference is not None:
        if (
            state in _GATED_STATES
            or _STATE_INDEX[trend] >= _STATE_INDEX[state]
        ):
            payload["observation_trend"] = trend
            payload["observation_trend_ref"] = trend_reference

    payload["state"] = target_state
    payload["blockers"] = _unique(blockers)
    payload["evidence_refs"] = evidence_refs
    payload["publication_evidence"] = _publication_evidence_payload(
        all_publication_evidence
    )
    payload["observation_evidence"] = deepcopy(
        [dict(item) for item in all_observation_evidence]
    )
    payload["next_action"] = _next_action(target_state)
    previous_transition = payload.get("transition")
    if (
        target_state == state
        and state in _GATED_STATES
        and isinstance(previous_transition, Mapping)
    ):
        payload["transition"] = deepcopy(dict(previous_transition))
    else:
        payload["transition"] = {
            "from": state,
            "to": target_state,
            "reason": reason,
        }
    payload["publication_authorization"] = PUBLICATION_AUTHORIZATION
    if controller_decision is not None and not terminal_decision_mismatch:
        payload["controller_decision"] = controller_decision

    return _record_result(record, payload, event_items)


__all__ = [
    "advance_content_lifecycle",
    "build_content_lifecycle",
    "validate_lifecycle_record",
]
