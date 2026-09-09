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
_FIELD_ALIASES = {
    "topic": ("topic_id", "topic"),
    "topic_id": ("topic_id", "topic"),
    "topic_type": ("topic_type", "type"),
    "type": ("topic_type", "type"),
    "platform": ("platform",),
    "publish_window": ("publish_window", "window"),
    "window": ("publish_window", "window"),
    "distribution_conditions": (
        "distribution_conditions",
        "distribution",
    ),
    "distribution": (
        "distribution_conditions",
        "distribution",
    ),
}
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


def _has_duplicates(value: object) -> bool:
    items = _sequence(value)
    return bool(items) and len(items) != len(set(items))


def _canonical_field(value: object) -> str:
    field = value.strip() if isinstance(value, str) else ""
    return {
        "topic": "topic_id",
        "type": "topic_type",
        "window": "publish_window",
        "distribution": "distribution_conditions",
    }.get(field, field)


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
    aliases = _FIELD_ALIASES.get(_canonical_field(field), (field,))
    for key in aliases:
        if key in observation:
            return observation[key]
    return None


def _observation_id(observation: Mapping[str, Any]) -> object:
    present = [
        observation[key]
        for key in ("article_id", "observation_id", "id")
        if key in observation
    ]
    if len(present) != 1:
        return None
    value = present[0]
    return value if isinstance(value, str) and value.strip() else None


def _observation_arm(
    observation: Mapping[str, Any],
    treatment_ids: set[str],
    control_ids: set[str],
) -> str | None:
    observation_id = _observation_id(observation)
    if not isinstance(observation_id, str):
        return None
    in_treatment = observation_id in treatment_ids
    in_control = observation_id in control_ids
    if in_treatment == in_control:
        return None
    return "treatment" if in_treatment else "control"


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

    controls = payload.get("controls")
    controls_valid = _string_list(controls)
    if not controls_valid:
        errors.append("invalid:controls")
    elif _has_duplicates([_canonical_field(item) for item in controls]):
        errors.append("duplicate:controls")
    if not _string_list(payload.get("metrics")):
        errors.append("invalid:metrics")
    if payload.get("design") not in EXPERIMENT_DESIGNS:
        errors.append("invalid:design")

    changed_variable = payload.get("changed_variable")
    if controls_valid and _text(changed_variable):
        canonical_controls = {_canonical_field(item) for item in controls}
        if _canonical_field(changed_variable) in canonical_controls:
            errors.append("overlap:changed_variable_controls")

    treatment_ids = payload.get("treatment_ids")
    control_ids = payload.get("control_ids")
    if not _string_list(treatment_ids):
        errors.append("invalid:treatment_ids")
    if not _string_list(control_ids):
        errors.append("invalid:control_ids")
    if _string_list(treatment_ids) and _has_duplicates(treatment_ids):
        errors.append("duplicate:treatment_ids")
    if _string_list(control_ids) and _has_duplicates(control_ids):
        errors.append("duplicate:control_ids")
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


def _constraint_matches(
    declared: Mapping[str, Any],
    actual: object,
) -> bool:
    if _frozen(declared) == _frozen(actual):
        return True
    if isinstance(actual, Mapping) or len(declared) != 1:
        return False
    key, value = next(iter(declared.items()))
    if str(key) not in {
        "label",
        "mode",
        "name",
        "value",
        "window",
        "publish_window",
        "distribution",
        "distribution_conditions",
    }:
        return False
    return _frozen(value) == _frozen(actual)


def _confounders(
    observations: list[tuple[str, Mapping[str, Any]]],
    payload: Mapping[str, Any],
) -> tuple[list[str], bool]:
    confounders: list[str] = []
    complete_controls = True
    checked_fields: set[str] = set()

    def add_confounder(field: str) -> None:
        if field not in confounders:
            confounders.append(field)

    def check_field(
        observation_field: str,
        report_field: str,
        *,
        expected: object = None,
        has_expected: bool = False,
    ) -> None:
        nonlocal complete_controls
        values: list[object] = []
        for _arm, observation in observations:
            value = _observation_value(observation, observation_field)
            if value is None:
                complete_controls = False
                continue
            values.append(_frozen(value))

        if len(set(values)) > 1:
            add_confounder(report_field)
        if has_expected and any(value != _frozen(expected) for value in values):
            add_confounder(report_field)

        checked_fields.add(_canonical_field(observation_field))

    for field in _CONTROLLED_FIELDS:
        check_field(
            field,
            field,
            expected=payload.get("topic_id"),
            has_expected=field == "topic_id",
        )

    controls = payload.get("controls", ())
    for declared_field in controls:
        canonical_field = _canonical_field(declared_field)
        if canonical_field in checked_fields:
            continue
        check_field(
            canonical_field,
            declared_field.strip(),
            expected=payload.get("topic_id"),
            has_expected=canonical_field == "topic_id",
        )

    for record_field, observation_field in (
        ("fixed_publish_window", "publish_window"),
        ("distribution_conditions", "distribution_conditions"),
    ):
        declared_value = payload.get(record_field)
        if not isinstance(declared_value, Mapping) or not declared_value:
            continue
        for _arm, observation in observations:
            actual_value = _observation_value(observation, observation_field)
            if actual_value is None:
                complete_controls = False
            elif not _constraint_matches(declared_value, actual_value):
                add_confounder(observation_field)

    return confounders, complete_controls


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
    assigned_candidates: list[tuple[str, str, Mapping[str, Any]]] = []
    for observation in items:
        observation_id = _observation_id(observation)
        arm = _observation_arm(observation, treatment_ids, control_ids)
        if arm is not None and isinstance(observation_id, str):
            assigned_candidates.append((observation_id, arm, observation))

    occurrences: dict[str, int] = {}
    for observation_id, _arm, _observation in assigned_candidates:
        occurrences[observation_id] = occurrences.get(observation_id, 0) + 1
    assigned = [
        (arm, observation)
        for observation_id, arm, observation in assigned_candidates
        if occurrences[observation_id] == 1
    ]

    counts = {arm: sum(1 for assigned_arm, _ in assigned if assigned_arm == arm) for arm in _ARMS}
    result["observations_per_arm"] = counts
    if not assigned or not all(counts[arm] for arm in _ARMS):
        result["errors"] = ["insufficient:both_arms"]
        return result

    confounders, complete_controls = _confounders(assigned, payload)
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
