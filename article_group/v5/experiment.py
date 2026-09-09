"""Offline V5 experiment records and cautious attribution assessment."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import date
from typing import Any

from .contracts import (
    EXPERIMENT_DESIGNS,
    PUBLICATION_AUTHORIZATION,
    new_artifact_envelope,
    payload_of,
    validate_v5_artifact_envelope,
)


_SCHEMA_VERSION = "v5-experiment-record-v1"
_MINIMUM_OBSERVATIONS_PER_ARM = 3
_ARMS = ("control", "treatment")
_CONTROLLED_FIELDS = (
    "topic_id",
    "topic_type",
    "platform",
    "publish_window",
    "distribution_conditions",
)
_REQUIRED_PAYLOAD_FIELDS = (
    "experiment_id",
    "topic_id",
    "topic_version",
    "hypothesis",
    "changed_variable",
    "controls",
    "metrics",
    "design",
    "treatment_ids",
    "control_ids",
    "week_start",
    "publication_authorization",
)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _sequence(value: object) -> list[object] | None:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        return None
    return list(value)


def _string_list(value: object, *, non_empty: bool = True) -> bool:
    items = _sequence(value)
    if items is None or (non_empty and not items):
        return False
    return all(isinstance(item, str) and item.strip() for item in items)


def _valid_date(value: object) -> bool:
    if not isinstance(value, str) or value != value.strip():
        return False
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return False
    return parsed.isoformat() == value


def _frozen(value: object) -> object:
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _frozen(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_frozen(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(_frozen(item) for item in value))
    return value


def _observation_value(observation: Mapping[str, Any], field: str) -> object:
    aliases = {
        "topic_id": ("topic_id",),
        "topic_type": ("topic_type", "type"),
        "platform": ("platform",),
        "publish_window": ("publish_window", "window"),
        "distribution_conditions": (
            "distribution_conditions",
            "distribution",
        ),
    }
    for key in aliases[field]:
        if key in observation:
            return observation[key]
    return None


def _observation_id(observation: Mapping[str, Any]) -> object:
    for key in ("article_id", "observation_id", "id"):
        if key in observation:
            return observation[key]
    return None


def _observation_arm(
    observation: Mapping[str, Any],
    treatment_ids: set[str],
    control_ids: set[str],
) -> str | None:
    observation_id = _observation_id(observation)
    if isinstance(observation_id, str):
        if observation_id in treatment_ids:
            return "treatment"
        if observation_id in control_ids:
            return "control"
        return None
    if observation_id is not None:
        return None
    arm = observation.get("arm", observation.get("group"))
    return arm if arm in _ARMS else None


def build_experiment_record(
    *,
    experiment_id: str,
    run_id: str,
    topic_id: str,
    topic_version: int,
    hypothesis: str,
    changed_variable: str,
    controls: Sequence[str],
    metrics: Sequence[str],
    design: str,
    treatment_ids: Sequence[str],
    control_ids: Sequence[str],
    week_start: str,
    generated_at: str,
    fixed_publish_window: Mapping[str, Any] | None = None,
    distribution_conditions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a closed V5 experiment envelope without publication authority."""

    payload = {
        "experiment_id": experiment_id,
        "topic_id": topic_id,
        "topic_version": topic_version,
        "hypothesis": hypothesis,
        "changed_variable": changed_variable,
        "controls": list(controls),
        "metrics": list(metrics),
        "design": design,
        "treatment_ids": list(treatment_ids),
        "control_ids": list(control_ids),
        "week_start": week_start,
        "fixed_publish_window": deepcopy(dict(fixed_publish_window or {})),
        "distribution_conditions": deepcopy(dict(distribution_conditions or {})),
        "publication_authorization": PUBLICATION_AUTHORIZATION,
    }
    return new_artifact_envelope(
        _SCHEMA_VERSION,
        run_id,
        payload,
        generated_at=generated_at,
    )


def validate_experiment_record(record: Mapping[str, Any]) -> list[str]:
    """Return stable validation errors for a V5 experiment record."""

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

    for field in ("experiment_id", "topic_id", "hypothesis", "changed_variable"):
        if not _text(payload.get(field)):
            errors.append(f"invalid:{field}")

    topic_version = payload.get("topic_version")
    if isinstance(topic_version, bool) or not isinstance(topic_version, int) or topic_version <= 0:
        errors.append("invalid:topic_version")

    if not _string_list(payload.get("controls")):
        errors.append("invalid:controls")
    if not _string_list(payload.get("metrics")):
        errors.append("invalid:metrics")
    if payload.get("design") not in EXPERIMENT_DESIGNS:
        errors.append("invalid:design")

    treatment_ids = payload.get("treatment_ids")
    control_ids = payload.get("control_ids")
    if not _string_list(treatment_ids):
        errors.append("invalid:treatment_ids")
    if not _string_list(control_ids):
        errors.append("invalid:control_ids")
    if _string_list(treatment_ids) and _string_list(control_ids):
        if set(treatment_ids) & set(control_ids):
            errors.append("overlap:treatment_control_ids")

    if not _valid_date(payload.get("week_start")):
        errors.append("invalid:week_start")
    if payload.get("publication_authorization") != PUBLICATION_AUTHORIZATION:
        errors.append("publication_authorization_must_be_not_authorized")

    for field in ("fixed_publish_window", "distribution_conditions"):
        value = payload.get(field)
        if value is not None and not isinstance(value, Mapping):
            errors.append(f"invalid:{field}")

    return list(dict.fromkeys(errors))


def _confounders(
    observations: list[tuple[str, Mapping[str, Any]]],
    expected_topic_id: object,
) -> tuple[list[str], bool]:
    confounders: list[str] = []
    complete_controls = True
    for field in _CONTROLLED_FIELDS:
        values_by_arm: dict[str, list[object]] = {arm: [] for arm in _ARMS}
        for arm, observation in observations:
            value = _observation_value(observation, field)
            if value is None:
                complete_controls = False
            else:
                values_by_arm[arm].append(_frozen(value))

        if field == "topic_id":
            if any(value != expected_topic_id for values in values_by_arm.values() for value in values):
                confounders.append(field)
        elif values_by_arm["control"] and values_by_arm["treatment"]:
            if set(values_by_arm["control"]) != set(values_by_arm["treatment"]):
                confounders.append(field)

    return list(dict.fromkeys(confounders)), complete_controls


def assess_experiment(
    record: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
    *,
    controller_decision: str | None = None,
) -> dict[str, Any]:
    """Assess recorded observations without turning correlation into a claim."""

    payload = payload_of(record) if isinstance(record, Mapping) else {}
    result: dict[str, Any] = {
        "experiment_id": payload.get("experiment_id"),
        "attribution_status": "inconclusive",
        "confounders": [],
        "causal_claims": [],
        "observations_per_arm": {"control": 0, "treatment": 0},
        "publication_authorization": PUBLICATION_AUTHORIZATION,
    }
    if controller_decision is not None:
        result["controller_decision"] = controller_decision

    record_errors = validate_experiment_record(record)
    if record_errors:
        result["errors"] = record_errors
        return result

    items = _sequence(observations)
    if items is None or any(not isinstance(item, Mapping) for item in items):
        result["errors"] = ["invalid:observations"]
        return result

    treatment_ids = set(payload["treatment_ids"])
    control_ids = set(payload["control_ids"])
    assigned: list[tuple[str, Mapping[str, Any]]] = []
    for observation in items:
        arm = _observation_arm(observation, treatment_ids, control_ids)
        if arm is not None:
            assigned.append((arm, observation))

    counts = {arm: sum(1 for assigned_arm, _ in assigned if assigned_arm == arm) for arm in _ARMS}
    result["observations_per_arm"] = counts
    if not assigned or not all(counts[arm] for arm in _ARMS):
        result["errors"] = ["insufficient:both_arms"]
        return result

    confounders, complete_controls = _confounders(assigned, payload["topic_id"])
    result["confounders"] = confounders
    if confounders:
        result["attribution_status"] = "confounded"
        return result

    if (
        all(counts[arm] >= _MINIMUM_OBSERVATIONS_PER_ARM for arm in _ARMS)
        and complete_controls
        and payload.get("design") != "observational"
        and controller_decision == "approve_causal_support"
    ):
        result["attribution_status"] = "supported_under_design"
    else:
        result["attribution_status"] = "observational"
    return result
