"""Versioned V5 strategy records with explicit controller state changes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import date, datetime, timedelta
import math
from typing import Any

from .contracts import (
    PUBLICATION_AUTHORIZATION,
    STRATEGY_STATES,
    new_artifact_envelope,
    payload_of,
    validate_v5_artifact_envelope,
)


_SCHEMA_VERSION = "v5-strategy-library-v1"
_STRATEGY_RECORD_SCHEMA = "v5-strategy-library-v1"
_MINIMUM_USABLE_SAMPLES = 3
_MINIMUM_WEEKS = 2
_CONTROLLER_DECISIONS = frozenset(
    {"start_testing", "approve_support", "deprecate", "retire"}
)
_VALID_TRANSITIONS = frozenset(
    {
        (state, state)
        for state in STRATEGY_STATES
    }
    | {
        ("provisional", "testing"),
        ("testing", "supported"),
        ("supported", "deprecated"),
        ("deprecated", "retired"),
    }
)
_EVIDENCE_ID_FIELDS = ("sample_id", "evidence_id", "article_id", "id")
_EVIDENCE_DATE_FIELDS = (
    "date",
    "week_start",
    "observed_at",
    "published_at",
    "measured_at",
    "timestamp",
)
_OBSERVATIONAL_FIELDS = (
    "evidence_type",
    "design",
    "attribution_status",
    "evidence_status",
)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _sequence(value: object) -> list[object] | None:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        return None
    return list(value)


def _string_list(value: object, *, non_empty: bool = True) -> bool:
    values = _sequence(value)
    if values is None or (non_empty and not values):
        return False
    return all(isinstance(item, str) and item.strip() for item in values)


def _unique_string_list(value: object, *, non_empty: bool = True) -> bool:
    if not _string_list(value, non_empty=non_empty):
        return False
    values = _sequence(value) or []
    return len(values) == len(set(values))


def _copy_strings(value: object) -> list[str]:
    values = _sequence(value) or []
    return [item.strip() for item in values if isinstance(item, str) and item.strip()]


def _parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _strategy_errors(
    strategy: Mapping[str, Any],
    *,
    prefix: str = "",
) -> list[str]:
    if not isinstance(strategy, Mapping):
        return [f"{prefix}invalid:strategy"]
    run_id = strategy.get("run_id") if isinstance(strategy.get("run_id"), str) else ""
    errors = validate_v5_artifact_envelope(
        strategy,
        _STRATEGY_RECORD_SCHEMA,
        run_id=run_id,
    )
    payload = payload_of(strategy)
    if not isinstance(payload, Mapping):
        return [f"{prefix}{error}" for error in errors]
    required = (
        "strategy_id",
        "version",
        "applicable_topic_types",
        "hypothesis",
        "evidence_samples",
        "success_conditions",
        "failure_boundary",
        "last_validated_at",
        "state",
        "controller_only",
        "auto_apply",
        "publication_authorization",
    )
    for field in required:
        if field not in payload:
            errors.append(f"missing:payload:{field}")
    if not _text(payload.get("strategy_id")):
        errors.append("invalid:strategy_id")
    version = payload.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version <= 0:
        errors.append("invalid:version")
    if not _unique_string_list(payload.get("applicable_topic_types")):
        errors.append("invalid:applicable_topic_types")
    if not _text(payload.get("hypothesis")):
        errors.append("invalid:hypothesis")
    if not _unique_string_list(payload.get("evidence_samples"), non_empty=False):
        errors.append("invalid:evidence_samples")
    for field in ("success_conditions", "failure_boundary"):
        if not _unique_string_list(payload.get(field)):
            errors.append(f"invalid:{field}")
    if not _valid_timestamp(payload.get("last_validated_at")):
        errors.append("invalid:last_validated_at")
    if payload.get("state") not in STRATEGY_STATES:
        errors.append("invalid:state")
    if "recommended_state" in payload:
        if payload.get("recommended_state") not in STRATEGY_STATES:
            errors.append("invalid:recommended_state")
    if "transition" in payload:
        transition = payload.get("transition")
        if not isinstance(transition, Mapping):
            errors.append("invalid:transition")
        else:
            from_state = transition.get("from")
            to_state = transition.get("to")
            if from_state not in STRATEGY_STATES:
                errors.append("invalid:transition:from")
            if to_state not in STRATEGY_STATES:
                errors.append("invalid:transition:to")
            if (
                from_state in STRATEGY_STATES
                and to_state in STRATEGY_STATES
                and (from_state, to_state) not in _VALID_TRANSITIONS
            ):
                errors.append("invalid:transition")
            if to_state in STRATEGY_STATES and to_state != payload.get("state"):
                errors.append("invalid:transition:to")
    if "controller_decision" in payload:
        decision = payload.get("controller_decision")
        if not isinstance(decision, str) or decision not in _CONTROLLER_DECISIONS:
            errors.append("invalid:controller_decision")
    if payload.get("controller_only") is not True:
        errors.append("controller_only_must_be_true")
    if payload.get("auto_apply") is not False:
        errors.append("auto_apply_must_be_false")
    if payload.get("publication_authorization") != PUBLICATION_AUTHORIZATION:
        errors.append("publication_authorization_must_be_not_authorized")
    return list(dict.fromkeys(f"{prefix}{error}" for error in errors))


def build_strategy_record(
    *,
    strategy_id: str,
    version: int,
    run_id: str,
    applicable_topic_types: Sequence[str],
    hypothesis: str,
    evidence_samples: Sequence[str],
    success_conditions: Sequence[str],
    failure_boundary: Sequence[str],
    last_validated_at: str,
    state: str = "provisional",
    generated_at: str,
) -> dict[str, Any]:
    """Build a complete versioned strategy record.

    The returned record is a recommendation artifact.  It carries no
    publication or execution authority.
    """

    payload = {
        "strategy_id": strategy_id,
        "version": version,
        "applicable_topic_types": _copy_strings(applicable_topic_types),
        "hypothesis": hypothesis,
        "evidence_samples": _copy_strings(evidence_samples),
        "success_conditions": _copy_strings(success_conditions),
        "failure_boundary": _copy_strings(failure_boundary),
        "last_validated_at": last_validated_at,
        "state": state,
        "controller_only": True,
        "auto_apply": False,
        "publication_authorization": PUBLICATION_AUTHORIZATION,
    }
    return new_artifact_envelope(
        _STRATEGY_RECORD_SCHEMA,
        run_id,
        payload,
        generated_at=generated_at,
    )


def _evidence_id(evidence: Mapping[str, Any]) -> str | None:
    values = [
        value
        for field in _EVIDENCE_ID_FIELDS
        if isinstance(value := evidence.get(field), str) and value.strip()
    ]
    if len(values) != 1:
        return None
    return values[0].strip()


def _evidence_date(evidence: Mapping[str, Any]) -> date | None:
    for field in _EVIDENCE_DATE_FIELDS:
        parsed = _parse_date(evidence.get(field))
        if parsed is not None:
            return parsed
    return None


def _evidence_usable(evidence: Mapping[str, Any]) -> bool:
    usable = evidence.get("usable")
    if usable is not None:
        return usable is True
    status = _text(evidence.get("status")).casefold()
    if status in {"unusable", "invalid", "insufficient_data", "missing"}:
        return False
    return _evidence_id(evidence) is not None and _evidence_date(evidence) is not None


def _is_observational_only(evidence: Mapping[str, Any]) -> bool:
    if evidence.get("correlation") is True or evidence.get("observational_only") is True:
        return True
    if evidence.get("causal") is False:
        return True
    observational_values = {
        "observational",
        "observational_only",
        "observational-only",
        "correlation",
        "correlational",
    }
    return any(
        _text(evidence.get(field)).casefold() in observational_values
        for field in _OBSERVATIONAL_FIELDS
    )


def _summarise_evidence(
    evidence: Sequence[Mapping[str, Any]],
    declared_sample_ids: Sequence[str],
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    declared_ids = set(declared_sample_ids)
    if isinstance(evidence, (str, bytes, bytearray)) or not isinstance(evidence, Sequence):
        return (
            {
                "input_sample_count": 0,
                "usable_sample_count": 0,
                "usable_sample_ids": [],
                "weeks": [],
                "week_count": 0,
                "minimum_usable_samples": _MINIMUM_USABLE_SAMPLES,
                "minimum_weeks": _MINIMUM_WEEKS,
                "sample_requirement_met": False,
                "week_requirement_met": False,
                "support_requirements_met": False,
                "declared_sample_ids": sorted(declared_ids),
                "bound_sample_ids": [],
                "unbound_sample_ids": [],
                "observational_only_sample_ids": [],
            },
            ["invalid:evidence"],
        )
    items = list(evidence)
    accepted: list[tuple[str, date, Mapping[str, Any]]] = []
    seen_ids: set[str] = set()
    unbound_ids: set[str] = set()
    observational_ids: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            errors.append(f"invalid:evidence:{index}")
            continue
        sample_id = _evidence_id(item)
        sample_date = _evidence_date(item)
        if sample_id is None:
            errors.append(f"missing:evidence:{index}:sample_id")
            continue
        if sample_date is None:
            errors.append(f"missing:evidence:{index}:date")
            continue
        if sample_id in seen_ids:
            errors.append(f"duplicate:evidence:{sample_id}")
            continue
        seen_ids.add(sample_id)
        if sample_id not in declared_ids:
            unbound_ids.add(sample_id)
            errors.append(f"unbound:evidence:{sample_id}")
            continue
        if _is_observational_only(item):
            observational_ids.add(sample_id)
        if _evidence_usable(item):
            accepted.append((sample_id, sample_date, item))
    weeks = sorted(
        {
            (sample_date - timedelta(days=sample_date.weekday())).isoformat()
            for _sample_id, sample_date, _item in accepted
        }
    )
    sample_ids = sorted(sample_id for sample_id, _date_value, _item in accepted)
    sample_count = len(sample_ids)
    week_count = len(weeks)
    summary = {
        "input_sample_count": len(items),
        "usable_sample_count": sample_count,
        "usable_sample_ids": sample_ids,
        "weeks": weeks,
        "week_count": week_count,
        "minimum_usable_samples": _MINIMUM_USABLE_SAMPLES,
        "minimum_weeks": _MINIMUM_WEEKS,
        "sample_requirement_met": sample_count >= _MINIMUM_USABLE_SAMPLES,
        "week_requirement_met": week_count >= _MINIMUM_WEEKS,
        "support_requirements_met": (
            sample_count >= _MINIMUM_USABLE_SAMPLES
            and week_count >= _MINIMUM_WEEKS
        ),
        "declared_sample_ids": sorted(declared_ids),
        "bound_sample_ids": sample_ids,
        "unbound_sample_ids": sorted(unbound_ids),
        "observational_only_sample_ids": sorted(observational_ids),
    }
    return summary, errors


def _result_envelope(strategy: Mapping[str, Any]) -> tuple[dict[str, Any], Mapping[str, Any]]:
    if (
        isinstance(strategy, Mapping)
        and isinstance(strategy.get("payload"), Mapping)
        and all(key in strategy for key in ("schema_version", "run_id", "generated_at", "input_hashes"))
    ):
        result = deepcopy(dict(strategy))
        return result, result["payload"]
    run_id = _text(strategy.get("run_id")) if isinstance(strategy, Mapping) else ""
    generated_at = _text(strategy.get("generated_at")) if isinstance(strategy, Mapping) else ""
    payload = dict(payload_of(strategy)) if isinstance(strategy, Mapping) else {}
    return (
        new_artifact_envelope(
            _STRATEGY_RECORD_SCHEMA,
            run_id or "invalid-run",
            payload,
            generated_at=generated_at or "1970-01-01T00:00:00+00:00",
        ),
        payload,
    )


def advance_strategy_state(
    strategy: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
    *,
    controller_decision: str | None = None,
) -> dict[str, Any]:
    """Assess evidence and apply only an explicitly authorized transition."""

    result, original_payload = _result_envelope(strategy)
    payload = deepcopy(dict(original_payload))
    validation_errors = _strategy_errors(strategy)
    declared_sample_ids = _copy_strings(payload.get("evidence_samples"))
    summary, evidence_errors = _summarise_evidence(evidence, declared_sample_ids)
    errors = list(dict.fromkeys(validation_errors + evidence_errors))
    observational_only = bool(summary["observational_only_sample_ids"])
    if observational_only:
        errors.append("observational_only_evidence_cannot_support")
    current_state = payload.get("state")
    if current_state not in STRATEGY_STATES:
        current_state = "provisional"
    support_ready = bool(summary["support_requirements_met"]) and not any(
        error.startswith("invalid:evidence")
        or error.startswith("missing:evidence")
        or error.startswith("duplicate:evidence")
        or error.startswith("unbound:evidence")
        for error in evidence_errors
    ) and not observational_only and not validation_errors
    recommended_state = current_state
    if (
        current_state == "testing"
        and support_ready
        and controller_decision == "approve_support"
    ):
        recommended_state = "supported"

    blockers: list[str] = []
    if current_state == "testing" and not support_ready:
        blockers.append("insufficient_usable_evidence")
    if current_state == "testing" and summary["unbound_sample_ids"]:
        blockers.append("evidence_not_declared_by_strategy")
    if current_state == "testing" and observational_only:
        blockers.append("observational_only_evidence_cannot_support")
    if current_state == "testing" and support_ready:
        blockers.append("controller_approval_required")
    if current_state == "supported" and not support_ready:
        blockers.append("state_claim_not_supported")

    decision = controller_decision
    if decision is not None and (
        not isinstance(decision, str) or decision not in _CONTROLLER_DECISIONS
    ):
        errors.append("invalid:controller_decision")
        decision = None

    if errors:
        recommended_state = current_state

    next_state = current_state
    if not errors:
        if current_state == "provisional" and decision == "start_testing":
            next_state = "testing"
        elif current_state == "testing" and decision == "approve_support" and support_ready:
            next_state = "supported"
        elif current_state == "supported" and decision == "deprecate":
            next_state = "deprecated"
        elif current_state == "deprecated" and decision == "retire":
            next_state = "retired"
        elif decision is not None and decision not in {
            "start_testing" if current_state == "provisional" else "",
            "approve_support" if current_state == "testing" else "",
            "deprecate" if current_state == "supported" else "",
            "retire" if current_state == "deprecated" else "",
        }:
            errors.append(f"invalid:transition:{current_state}:{decision}")

    if next_state != current_state:
        blockers = [
            blocker
            for blocker in blockers
            if blocker not in {"controller_approval_required"}
        ]
        recommended_state = next_state
    payload["state"] = next_state
    payload["recommended_state"] = recommended_state
    payload["evidence_summary"] = summary
    payload["blockers"] = list(dict.fromkeys(blockers))
    payload["errors"] = list(dict.fromkeys(errors))
    payload["transition"] = {"from": current_state, "to": next_state}
    payload["controller_only"] = True
    payload["auto_apply"] = False
    payload["publication_authorization"] = PUBLICATION_AUTHORIZATION
    if controller_decision is not None:
        payload["controller_decision"] = controller_decision
    result["payload"] = payload
    return result


def build_strategy_library(
    strategies: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    generated_at: str,
) -> dict[str, Any]:
    """Build a closed strategy library without selecting or publishing a strategy."""

    if isinstance(strategies, (str, bytes, bytearray)) or not isinstance(strategies, Sequence):
        raise ValueError("invalid_strategies")
    items: list[dict[str, Any]] = []
    for index, strategy in enumerate(strategies):
        if not isinstance(strategy, Mapping):
            raise ValueError(
                f"invalid_strategy_member:{index}:invalid:strategy:{index}"
            )
        member_errors = _strategy_errors(strategy)
        if member_errors:
            raise ValueError(
                f"invalid_strategy_member:{index}:{member_errors[0]}"
            )
        items.append(deepcopy(dict(strategy)))
    payload = {
        "strategies": items,
        "strategy_count": len(items),
        "controller_only": True,
        "auto_apply": False,
        "publication_authorization": PUBLICATION_AUTHORIZATION,
    }
    return new_artifact_envelope(
        _SCHEMA_VERSION,
        run_id,
        payload,
        generated_at=generated_at,
    )


def validate_strategy_library(library: Mapping[str, Any]) -> list[str]:
    """Return stable validation errors for a V5 strategy library."""

    if not isinstance(library, Mapping):
        return ["invalid:artifact"]
    run_id = library.get("run_id") if isinstance(library.get("run_id"), str) else ""
    errors = validate_v5_artifact_envelope(
        library,
        _SCHEMA_VERSION,
        run_id=run_id,
    )
    payload = payload_of(library)
    if not isinstance(payload, Mapping):
        return list(dict.fromkeys(errors))
    for field in (
        "strategies",
        "strategy_count",
        "controller_only",
        "auto_apply",
        "publication_authorization",
    ):
        if field not in payload:
            errors.append(f"missing:payload:{field}")
    strategies = payload.get("strategies")
    if not isinstance(strategies, list):
        errors.append("invalid:payload:strategies")
        strategies = []
    count = payload.get("strategy_count")
    if isinstance(count, bool) or not isinstance(count, int) or count != len(strategies):
        errors.append("mismatch:payload:strategy_count")
    if payload.get("controller_only") is not True:
        errors.append("controller_only_must_be_true")
    if payload.get("auto_apply") is not False:
        errors.append("auto_apply_must_be_false")
    if payload.get("publication_authorization") != PUBLICATION_AUTHORIZATION:
        errors.append("publication_authorization_must_be_not_authorized")
    seen: set[tuple[str, int]] = set()
    for index, strategy in enumerate(strategies):
        errors.extend(
            f"strategy:{index}:{error}"
            for error in _strategy_errors(strategy)
        )
        nested = payload_of(strategy) if isinstance(strategy, Mapping) else {}
        strategy_id = _text(nested.get("strategy_id"))
        version = nested.get("version")
        if strategy_id and isinstance(version, int) and not isinstance(version, bool):
            key = (strategy_id, version)
            if key in seen:
                errors.append(f"duplicate:strategy:{strategy_id}:{version}")
            seen.add(key)
    return list(dict.fromkeys(errors))


__all__ = [
    "advance_strategy_state",
    "build_strategy_library",
    "build_strategy_record",
    "validate_strategy_library",
]
