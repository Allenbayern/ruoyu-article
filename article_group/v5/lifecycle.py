"""Offline, non-authorizing content lifecycle helpers for Article Group V5."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
import hashlib
import json
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
_OBSERVATION_STATES = frozenset({"stable", "rising", "decaying"})
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
    return _NEXT_ACTIONS.get(state, "review_lifecycle_state")


def _event_reference(event: Mapping[str, Any], index: int) -> str:
    for key in (
        "evidence_ref",
        "event_id",
        "observation_id",
        "source_ref",
        "ref",
        "id",
    ):
        reference = _text(event.get(key))
        if reference:
            return reference
    return f"event:{index}"


def _event_type(event: Mapping[str, Any]) -> str:
    return _text(event.get("event_type"))


def _complete_publication_event(event: Mapping[str, Any]) -> bool:
    return (
        _event_type(event) == "published"
        and bool(_text(event.get("published_at")))
        and bool(_text(event.get("platform")))
    )


def _publication_evidence(
    events: Sequence[object],
) -> tuple[bool, bool, list[str]]:
    publication_seen = False
    complete = False
    references: list[str] = []
    for index, event in enumerate(events):
        if not isinstance(event, Mapping) or _event_type(event) != "published":
            continue
        publication_seen = True
        references.append(_event_reference(event, index))
        if _complete_publication_event(event):
            complete = True
    return publication_seen, complete, references


def _observation_trend(event: Mapping[str, Any]) -> str | None:
    for key in ("trend", "observation_trend"):
        value = _text(event.get(key))
        if value:
            return value

    for key in ("observation", "metrics"):
        nested = event.get(key)
        if isinstance(nested, Mapping):
            value = _text(nested.get("trend"))
            if value:
                return value

    event_state = _event_type(event)
    if event_state in _OBSERVATION_STATES:
        return event_state

    state = _text(event.get("state"))
    return state or None


def _observation_evidence(
    events: Sequence[object],
) -> tuple[bool, str | None, str | None, list[str]]:
    observed = False
    candidates: list[tuple[object, int, str, str]] = []
    references: list[str] = []

    for index, event in enumerate(events):
        if not isinstance(event, Mapping) or _event_type(event) == "published":
            continue

        trend = _observation_trend(event)
        event_type = _event_type(event)
        is_observation = bool(
            trend
            or event_type in _OBSERVATION_EVENT_TYPES
            or any(
                key in event
                for key in ("observed_at", "observation", "metrics")
            )
        )
        if not is_observation:
            continue

        observed = True
        reference = _event_reference(event, index)
        references.append(reference)
        if trend not in _OBSERVATION_STATES:
            continue

        timestamp = event.get("observed_at", event.get("timestamp"))
        parsed_timestamp: object = None
        if isinstance(timestamp, str) and timestamp.strip():
            try:
                parsed_timestamp = datetime.fromisoformat(
                    timestamp.replace("Z", "+00:00")
                )
            except ValueError:
                parsed_timestamp = timestamp
        candidates.append((parsed_timestamp, index, trend, reference))

    if not candidates:
        return observed, None, None, references

    def sort_key(candidate: tuple[object, int, str, str]) -> tuple[int, object, int]:
        timestamp, index, _, _ = candidate
        if isinstance(timestamp, datetime):
            return (0, timestamp, index)
        if isinstance(timestamp, str):
            return (1, timestamp, index)
        return (2, "", index)

    _, _, trend, reference = max(candidates, key=sort_key)
    return observed, trend, reference, references


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

    payload = {
        "article_id": article_id,
        "state": state,
        "blockers": [],
        "evidence_refs": [],
        "next_action": _next_action(state),
        "publication_authorization": PUBLICATION_AUTHORIZATION,
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
    if payload.get("state") not in LIFECYCLE_STATES:
        errors.append("invalid:state")
    for field in ("blockers", "evidence_refs"):
        if not _valid_string_list(payload.get(field)):
            errors.append(f"invalid:{field}")
    if not _text(payload.get("next_action")):
        errors.append("invalid:next_action")
    if payload.get("publication_authorization") != PUBLICATION_AUTHORIZATION:
        errors.append("publication_authorization_must_be_not_authorized")

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
    state = source_state if source_state in _STATE_INDEX else "draft"

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
        list(existing_refs) if _valid_string_list(existing_refs) else []
    )
    publication_seen, publication_complete, publication_refs = _publication_evidence(
        event_items
    )
    observed, trend, trend_reference, observation_refs = _observation_evidence(
        event_items
    )
    evidence_refs = _unique(
        [*evidence_refs, *publication_refs, *observation_refs]
    )

    target_state = state
    reason = "no_supported_transition"
    can_advance = not record_errors and events_valid and decision_valid

    if can_advance and controller_decision == "archive":
        if state != "archived":
            target_state = "archived"
            reason = "controller_approved_archive"
    elif can_advance and controller_decision == "approve_evergreen":
        if state == "draft":
            blockers.append("evergreen_requires_published_content")
            reason = "evergreen_requires_published_content"
        elif state not in {"evergreen", "archived"}:
            target_state = "evergreen"
            reason = "controller_approved_evergreen"
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

    if trend is not None:
        payload["observation_trend"] = trend
    if trend_reference is not None:
        payload["observation_trend_ref"] = trend_reference

    payload["state"] = target_state
    payload["blockers"] = _unique(blockers)
    payload["evidence_refs"] = evidence_refs
    payload["next_action"] = _next_action(target_state)
    payload["transition"] = {
        "from": state,
        "to": target_state,
        "reason": reason,
    }
    payload["publication_authorization"] = PUBLICATION_AUTHORIZATION
    if controller_decision is not None:
        payload["controller_decision"] = controller_decision

    return _record_result(record, payload, event_items)


__all__ = [
    "advance_content_lifecycle",
    "build_content_lifecycle",
    "validate_lifecycle_record",
]
