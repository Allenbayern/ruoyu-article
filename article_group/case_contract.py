from __future__ import annotations

from numbers import Real
from typing import Any


QUALIFICATION_STATUSES = frozenset(
    {"qualified_viral", "observed_pending", "research_only"}
)
RESEARCH_DOMAIN = "competitive_research_evidence"
FACT_DOMAIN = "ruoyu_article_fact_evidence"
FEEDBACK_DOMAIN = "production_feedback_evidence"


class CaseContractError(ValueError):
    """Raised when a record violates the v1.1 research-evidence contract."""


def _require(condition: object, code: str) -> None:
    if not condition:
        raise CaseContractError(code)


def _mapping(value: object, code: str) -> dict[str, Any]:
    _require(isinstance(value, dict), code)
    return value


def _items(value: object, code: str) -> list[object]:
    _require(isinstance(value, list), code)
    return value


def _text(value: object, code: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()), code)
    return value.strip()


def _number(value: object, code: str) -> float:
    _require(isinstance(value, Real) and not isinstance(value, bool), code)
    return float(value)


def _metric_map(card: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw_metric in _items(card.get("metrics"), "metrics_must_be_a_list"):
        metric = _mapping(raw_metric, "metric_must_be_an_object")
        name = _text(metric.get("metric"), "metric_name_missing")
        _require(name not in result, f"duplicate_metric:{name}")
        result[name] = metric
    return result


def _validate_metric_plan(
    card: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    planned: dict[str, dict[str, Any]] = {}
    plan_items = _items(card.get("metric_plan"), "metric_plan_must_be_a_list")
    _require(plan_items, "metric_plan_missing")
    for raw_item in plan_items:
        item = _mapping(raw_item, "metric_plan_item_must_be_an_object")
        name = _text(item.get("metric"), "metric_plan_name_missing")
        _require(name not in planned, f"duplicate_metric_plan:{name}")
        _require(isinstance(item.get("visible"), bool), f"metric_visibility_missing:{name}")
        _require(isinstance(item.get("required"), bool), f"metric_required_missing:{name}")
        _require(
            not (item["required"] and not item["visible"]),
            f"metric_required_but_not_visible:{name}",
        )
        planned[name] = item

    metrics = _metric_map(card)
    _require(
        not (set(metrics) - set(planned)),
        "metric_not_declared_in_plan",
    )
    for name, metric in metrics.items():
        _text(metric.get("source"), "metric_source_missing")
        _text(metric.get("observed_at"), "metric_observed_at_missing")
        _text(metric.get("evidence_ref"), "metric_evidence_ref_missing")
        status = metric.get("status")
        _require(
            status in {"observed", "not_verifiable_offsite"},
            f"invalid_metric_status:{name}",
        )
        if status == "observed":
            _require(metric.get("value") is not None, f"observed_metric_value_missing:{name}")
        else:
            _require(metric.get("value") is None, f"unverifiable_metric_has_value:{name}")
    return planned, metrics


def _thresholds(
    rule: dict[str, Any],
    key: str,
    code: str,
) -> dict[str, float]:
    raw_thresholds = rule.get(key, {})
    _require(isinstance(raw_thresholds, dict), code)
    thresholds: dict[str, float] = {}
    for metric, value in raw_thresholds.items():
        thresholds[_text(metric, f"{code}_metric_missing")] = _number(
            value, f"{code}_value_invalid"
        )
    return thresholds


def _validate_rule(
    card: dict[str, Any], planned: dict[str, dict[str, Any]]
) -> tuple[dict[str, float], dict[str, float]]:
    rule = _mapping(card.get("threshold_or_rank_rule"), "threshold_or_rank_rule_missing")
    for key in ("platform", "baseline", "window", "rule"):
        _text(rule.get(key), f"threshold_rule_{key}_missing")
    minimums = _thresholds(rule, "minimums", "threshold_rule_minimums_invalid")
    rank_maximums = _thresholds(
        rule, "rank_maximums", "threshold_rule_rank_maximums_invalid"
    )
    _require(minimums or rank_maximums, "threshold_rule_criteria_missing")
    _require(
        not ((set(minimums) | set(rank_maximums)) - set(planned)),
        "threshold_rule_metric_not_in_plan",
    )
    _text(card.get("qualification_reason"), "qualification_reason_missing")
    return minimums, rank_maximums


def _thresholds_met(
    metrics: dict[str, dict[str, Any]],
    minimums: dict[str, float],
    rank_maximums: dict[str, float],
) -> bool:
    for name, minimum in minimums.items():
        metric = metrics.get(name)
        if metric is None or metric.get("status") != "observed":
            return False
        value = metric.get("value")
        if not isinstance(value, Real) or isinstance(value, bool) or value < minimum:
            return False
    for name, maximum in rank_maximums.items():
        metric = metrics.get(name)
        if metric is None or metric.get("status") != "observed":
            return False
        value = metric.get("value")
        if not isinstance(value, Real) or isinstance(value, bool) or value > maximum:
            return False
    return True


def assess_qualification(card: dict[str, Any]) -> str:
    """Return the highest defensible status without inventing missing metrics."""
    _require(card.get("evidence_domain") == RESEARCH_DOMAIN, RESEARCH_DOMAIN)
    planned, metrics = _validate_metric_plan(card)
    minimums, rank_maximums = _validate_rule(card, planned)
    required_visible = {
        name
        for name, item in planned.items()
        if item["visible"] and item["required"]
    }
    observed_required = {
        name
        for name in required_visible
        if name in metrics and metrics[name].get("status") == "observed"
    }
    if not observed_required:
        return "research_only"
    if observed_required != required_visible:
        return "observed_pending"
    if not _thresholds_met(metrics, minimums, rank_maximums):
        return "observed_pending"
    return "qualified_viral"


def validate_fact_evidence_pack(pack: dict[str, Any]) -> None:
    _require(pack.get("evidence_domain") == FACT_DOMAIN, FACT_DOMAIN)
    _text(pack.get("article_id"), "fact_article_id_missing")
    _require(
        not pack.get("competitive_sample_refs"),
        "fact_evidence_cannot_reference_competitive_samples",
    )
    _require(
        pack.get("qualification_status") is None,
        "fact_evidence_cannot_carry_qualification",
    )
    claims = _items(pack.get("claims"), "fact_claims_must_be_a_list")
    _require(claims, "fact_claims_missing")
    for raw_claim in claims:
        claim = _mapping(raw_claim, "fact_claim_must_be_an_object")
        _text(claim.get("claim_id"), "fact_claim_id_missing")
        _text(claim.get("source_snapshot_ref"), "fact_source_snapshot_ref_missing")
        _text(claim.get("claim_locator"), "fact_claim_locator_missing")


def validate_feedback_record(
    feedback: dict[str, Any],
    *,
    techniques: dict[str, dict[str, Any]] | None = None,
) -> None:
    _require(feedback.get("evidence_domain") == FEEDBACK_DOMAIN, FEEDBACK_DOMAIN)
    _text(feedback.get("article_id"), "feedback_article_id_missing")
    technique_ids = _items(feedback.get("technique_ids"), "feedback_technique_ids_must_be_a_list")
    _require(technique_ids, "feedback_technique_ids_missing")
    _require(
        "qualification_status" not in feedback
        and "proposed_qualification_status" not in feedback,
        "feedback_cannot_change_qualification",
    )
    _require("claims" not in feedback, "feedback_cannot_carry_claims")
    if techniques is not None:
        _require(isinstance(techniques, dict), "feedback_techniques_registry_invalid")
        for raw_technique_id in technique_ids:
            technique_id = _text(raw_technique_id, "feedback_technique_id_invalid")
            technique = techniques.get(technique_id)
            _require(
                technique is not None,
                f"feedback_technique_unresolvable:{technique_id}",
            )
            _require(
                isinstance(technique, dict)
                and bool(
                    _items(
                        technique.get("qualified_sample_refs"),
                        "feedback_technique_refs_invalid",
                    )
                ),
                f"feedback_technique_not_formal:{technique_id}",
            )
    observations = _items(feedback.get("observations"), "feedback_observations_must_be_a_list")
    _require(observations, "feedback_observations_missing")
    for raw_observation in observations:
        observation = _mapping(raw_observation, "feedback_observation_must_be_an_object")
        _text(observation.get("metric"), "feedback_metric_missing")
        _require(observation.get("value") is not None, "feedback_metric_value_missing")
        _text(observation.get("source"), "feedback_metric_source_missing")
        _text(observation.get("observed_at"), "feedback_metric_observed_at_missing")
        _text(observation.get("evidence_ref"), "feedback_metric_evidence_ref_missing")


def validate_case_card(
    card: dict[str, Any],
    *,
    feedback: dict[str, Any] | None = None,
    techniques: dict[str, dict[str, Any]] | None = None,
) -> str:
    _text(card.get("sample_id"), "sample_id_missing")
    _text(card.get("snapshot_ref"), "snapshot_ref_missing")
    _text(card.get("performance_evidence_ref"), "performance_evidence_ref_missing")
    status = assess_qualification(card)
    declared_status = card.get("qualification_status")
    if declared_status is not None:
        _require(declared_status in QUALIFICATION_STATUSES, "invalid_qualification_status")
        _require(declared_status == status, "qualification_status_mismatch")
    if feedback is not None:
        validate_feedback_record(feedback, techniques=techniques)
    return status


def validate_technique_candidate(
    technique: dict[str, Any], cases: dict[str, dict[str, Any]]
) -> None:
    _text(technique.get("technique_id"), "technique_id_missing")
    _require(
        technique.get("kind") in {"title", "opening", "structure", "interaction"},
        "invalid_technique_kind",
    )
    refs = _items(technique.get("qualified_sample_refs"), "qualified_sample_refs_must_be_a_list")
    _require(refs, "qualified_sample_refs_missing")
    for raw_ref in refs:
        ref = _text(raw_ref, "qualified_sample_ref_invalid")
        _require(ref in cases, f"sample_ref_unresolvable:{ref}")
        _require(
            validate_case_card(cases[ref]) == "qualified_viral",
            "technique_support_not_qualified",
        )