"""V5's additive adapter around the existing V3 state machine."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from article_group.editorial_pipeline_v3 import validate_transition

from .contracts import PUBLICATION_AUTHORIZATION
from .experiment import validate_experiment_record
from .resources import validate_resource_plan


def _payload(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    nested = value.get("payload")
    return nested if isinstance(nested, Mapping) else value


def _authorization_error(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str) and "authorization" in key.casefold():
                if nested != PUBLICATION_AUTHORIZATION:
                    return True
            if _authorization_error(nested):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_authorization_error(nested) for nested in value)
    return False


def _prefixed(errors: list[str], prefix: str, new_errors: list[str]) -> None:
    errors.extend(f"{prefix}:{error}" for error in new_errors)


def validate_v5_transition_context(
    from_state: str,
    to_state: str,
    *,
    experiment_record: Mapping[str, Any] | None = None,
    lifecycle_record: Mapping[str, Any] | None = None,
    dna_record: Mapping[str, Any] | None = None,
    failure_report: Mapping[str, Any] | None = None,
    quota_plan: Mapping[str, Any] | None = None,
    strategy_library: Mapping[str, Any] | None = None,
    resource_plan: Mapping[str, Any] | None = None,
) -> list[str]:
    """Add V5 gates without replacing V3's state or review/controller gate."""

    errors = validate_transition(from_state, to_state)
    if errors:
        return errors

    supplied = (
        experiment_record,
        lifecycle_record,
        dna_record,
        failure_report,
        quota_plan,
        strategy_library,
        resource_plan,
    )
    if any(_authorization_error(value) for value in supplied):
        errors.append("publication_authorization_must_be_not_authorized")

    if from_state == "approved" and to_state == "researching":
        if experiment_record is None:
            errors.append("missing:v5_experiment")
        else:
            _prefixed(errors, "v5_experiment", validate_experiment_record(experiment_record))
        if resource_plan is None:
            errors.append("missing:v5_resource_plan")
        else:
            _prefixed(errors, "v5_resource_plan", validate_resource_plan(resource_plan))
            allocations = _payload(resource_plan).get("allocations")
            if isinstance(allocations, list) and any(
                isinstance(item, Mapping) and item.get("action") == "stop"
                for item in allocations
            ):
                errors.append("v5_resource_plan_contains_stop")

    if from_state == "material_ready" and to_state == "writing":
        lifecycle_state = _payload(lifecycle_record).get("state")
        if lifecycle_state == "archived":
            errors.append("v5_lifecycle_archived")
        elif lifecycle_state == "retired":
            errors.append("v5_lifecycle_retired")

        strategies = _payload(strategy_library).get("strategies")
        if isinstance(strategies, list):
            for strategy in strategies:
                if _payload(strategy).get("state") == "retired":
                    errors.append("v5_strategy_retired")
                    break

        samples = _payload(failure_report).get("samples")
        if isinstance(samples, list):
            for sample in samples:
                if not isinstance(sample, Mapping):
                    continue
                categories = sample.get("categories")
                if (
                    sample.get("status") == "insufficient_data"
                    or isinstance(categories, list)
                    and "insufficient_data" in categories
                ):
                    errors.append("v5_failure_insufficient_data")
                high_risk = (
                    isinstance(categories, list)
                    and "good_data_high_risk" in categories
                )
                risk_score = sample.get("risk_score")
                if not high_risk and isinstance(risk_score, (int, float)):
                    high_risk = not isinstance(risk_score, bool) and risk_score >= 0.70
                if not high_risk and sample.get("risk_level") in {"high", "critical"}:
                    high_risk = True
                if high_risk:
                    errors.append("v5_failure_high_risk_requires_review")

    # review -> closed intentionally has no V5 shortcut: the caller must run
    # V3's existing strict review/controller gate separately.
    return list(dict.fromkeys(errors))


__all__ = ["validate_v5_transition_context"]
