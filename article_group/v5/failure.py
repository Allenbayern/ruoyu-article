"""Offline failure classification and failure-sample artifacts for V5.

The classifier is intentionally evidence-first: a missing or unavailable
metric remains ``None`` and cannot satisfy a threshold.  A recommendation is
an input for controller review and never an automatic action.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib
import json
import math
from typing import Any

from .contracts import (
    FAILURE_TYPES,
    PUBLICATION_AUTHORIZATION,
    new_artifact_envelope,
    payload_of,
    validate_v5_artifact_envelope,
)


_SCHEMA_VERSION = "v5-failure-samples-v1"
_CLASSIFIABLE_FAILURE_TYPES = tuple(
    failure_type for failure_type in FAILURE_TYPES if failure_type != "insufficient_data"
)
_METRIC_NAMES = (
    "impressions",
    "reads",
    "clicks",
    "ctr",
    "completion_rate",
    "interactions",
    "interaction_rate",
    "revenue",
    "rpm",
    "risk_score",
)
_RATE_METRICS = frozenset({"ctr", "completion_rate", "interaction_rate"})
_METRIC_STATUS_VALUES = frozenset({"available", "unavailable"})
_DEFAULT_THRESHOLDS: dict[str, float] = {
    "exposure_without_click_min_impressions": 1000.0,
    "exposure_without_click_max_ctr": 0.02,
    "click_low_completion_min_reads": 1.0,
    "click_low_completion_max_completion_rate": 0.35,
    "high_completion_low_exposure_min_completion_rate": 0.70,
    "high_completion_low_exposure_max_impressions": 1000.0,
    "high_interaction_low_revenue_min_interaction_rate": 0.08,
    "high_interaction_low_revenue_max_rpm": 1.0,
    "good_data_high_risk_min_impressions": 1000.0,
    "good_data_high_risk_min_reads": 100.0,
    "good_data_high_risk_min_completion_rate": 0.50,
    "good_data_high_risk_min_risk_score": 0.70,
}
FAILURE_THRESHOLDS = dict(_DEFAULT_THRESHOLDS)
_THRESHOLD_ALIASES = {
    "min_impressions": "exposure_without_click_min_impressions",
    "exposure_min_impressions": "exposure_without_click_min_impressions",
    "max_ctr": "exposure_without_click_max_ctr",
    "low_ctr": "exposure_without_click_max_ctr",
    "low_completion_rate": "click_low_completion_max_completion_rate",
    "min_completion_rate": "high_completion_low_exposure_min_completion_rate",
    "max_exposure": "high_completion_low_exposure_max_impressions",
    "min_interaction_rate": "high_interaction_low_revenue_min_interaction_rate",
    "max_rpm": "high_interaction_low_revenue_max_rpm",
    "min_risk_score": "good_data_high_risk_min_risk_score",
}
_RATE_THRESHOLDS = frozenset(
    {
        "exposure_without_click_max_ctr",
        "click_low_completion_max_completion_rate",
        "high_completion_low_exposure_min_completion_rate",
        "high_interaction_low_revenue_min_interaction_rate",
        "good_data_high_risk_min_completion_rate",
        "good_data_high_risk_min_risk_score",
    }
)
_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "impressions": ("impressions", "exposure", "views"),
    "reads": ("reads", "read_count", "clicks"),
    "clicks": ("clicks", "click_count"),
    "ctr": ("ctr", "click_through_rate"),
    "completion_rate": ("completion_rate", "completion"),
    "interactions": ("interactions", "engagements", "engagement_count"),
    "interaction_rate": ("interaction_rate", "engagement_rate"),
    "revenue": ("revenue", "earnings"),
    "rpm": ("rpm", "revenue_per_thousand"),
    "risk_score": ("risk_score",),
}
_RECOMMENDATIONS = {
    "exposure_without_click": (
        "change the title or opening and retest click-through before scaling exposure"
    ),
    "click_low_completion": (
        "change the opening promise and pacing to improve completion after the click"
    ),
    "high_completion_low_exposure": (
        "test distribution timing or platform reach while preserving the completed opening"
    ),
    "high_interaction_low_revenue": (
        "review monetization placement and audience fit before copying the format"
    ),
    "good_data_high_risk": (
        "escalate to human risk review and stop automatic reuse of this pattern"
    ),
}
_EVIDENCE_CONTRACT = {
    "exposure_without_click": {
        "metrics": ("impressions", "ctr"),
        "thresholds": (
            "exposure_without_click_min_impressions",
            "exposure_without_click_max_ctr",
        ),
        "comparisons": (
            ("impressions", ">=", "exposure_without_click_min_impressions"),
            ("ctr", "<", "exposure_without_click_max_ctr"),
        ),
    },
    "click_low_completion": {
        "metrics": ("reads", "completion_rate"),
        "thresholds": (
            "click_low_completion_min_reads",
            "click_low_completion_max_completion_rate",
        ),
        "comparisons": (
            ("reads", ">=", "click_low_completion_min_reads"),
            ("completion_rate", "<", "click_low_completion_max_completion_rate"),
        ),
    },
    "high_completion_low_exposure": {
        "metrics": ("completion_rate", "impressions"),
        "thresholds": (
            "high_completion_low_exposure_min_completion_rate",
            "high_completion_low_exposure_max_impressions",
        ),
        "comparisons": (
            (
                "completion_rate",
                ">=",
                "high_completion_low_exposure_min_completion_rate",
            ),
            (
                "impressions",
                "<",
                "high_completion_low_exposure_max_impressions",
            ),
        ),
    },
    "high_interaction_low_revenue": {
        "metrics": ("interaction_rate", "rpm"),
        "thresholds": (
            "high_interaction_low_revenue_min_interaction_rate",
            "high_interaction_low_revenue_max_rpm",
        ),
        "comparisons": (
            (
                "interaction_rate",
                ">=",
                "high_interaction_low_revenue_min_interaction_rate",
            ),
            ("rpm", "<", "high_interaction_low_revenue_max_rpm"),
        ),
    },
    "good_data_high_risk": {
        "metrics": ("impressions", "reads", "completion_rate", "risk_score"),
        "thresholds": (
            "good_data_high_risk_min_impressions",
            "good_data_high_risk_min_reads",
            "good_data_high_risk_min_completion_rate",
            "good_data_high_risk_min_risk_score",
        ),
        "comparisons": (
            ("impressions", ">=", "good_data_high_risk_min_impressions"),
            ("reads", ">=", "good_data_high_risk_min_reads"),
            (
                "completion_rate",
                ">=",
                "good_data_high_risk_min_completion_rate",
            ),
            ("risk_score", ">=", "good_data_high_risk_min_risk_score"),
        ),
    },
}


def _is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
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


def _metric_container(event: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = event.get("metrics")
    return nested if isinstance(nested, Mapping) else {}


def _raw_metric(event: Mapping[str, Any], metric: str) -> tuple[object, bool]:
    nested = _metric_container(event)
    for alias in _METRIC_ALIASES[metric]:
        if alias in event:
            return event.get(alias), True
        if alias in nested:
            return nested.get(alias), True
    return None, False


def _raw_status(event: Mapping[str, Any], metric: str) -> object:
    nested = _metric_container(event)
    for source in (event, nested):
        direct = f"{metric}_status"
        if direct in source:
            return source.get(direct)
        statuses = source.get("metric_status")
        if isinstance(statuses, Mapping) and metric in statuses:
            return statuses.get(metric)
    return None


def _normalise_metric(
    event: Mapping[str, Any], metric: str
) -> tuple[object, str, str | None]:
    raw, present = _raw_metric(event, metric)
    status = _raw_status(event, metric)
    if status is not None and status not in _METRIC_STATUS_VALUES:
        return None, "unavailable", f"{metric}_status"
    if status == "unavailable" or not present or raw is None:
        return None, "unavailable", metric
    if not _is_number(raw):
        return None, "unavailable", metric
    numeric = float(raw)
    if numeric < 0 or (metric in _RATE_METRICS and numeric > 1):
        return None, "unavailable", metric
    return raw, "available", None


def _normalise_metrics(
    event: Mapping[str, Any],
) -> tuple[dict[str, object], dict[str, str], list[str], list[str]]:
    metrics: dict[str, object] = {}
    statuses: dict[str, str] = {}
    missing: list[str] = []
    invalid: list[str] = []
    for metric in _METRIC_NAMES:
        value, status, problem = _normalise_metric(event, metric)
        metrics[metric] = value
        statuses[metric] = status
        if problem is not None and problem.endswith("_status"):
            invalid.append(problem)

    derived_metrics: list[str] = []
    if statuses["ctr"] == "unavailable":
        clicks = metrics["clicks"]
        impressions = metrics["impressions"]
        if (
            statuses["clicks"] == "available"
            and statuses["impressions"] == "available"
            and isinstance(clicks, (int, float))
            and isinstance(impressions, (int, float))
            and impressions > 0
        ):
            derived_ctr = clicks / impressions
            if 0 <= derived_ctr <= 1:
                metrics["ctr"] = derived_ctr
                statuses["ctr"] = "available"
                derived_metrics.append("ctr")
                if "ctr" in missing:
                    missing.remove("ctr")

    if statuses["interactions"] == "unavailable":
        component_values: list[float] = []
        nested = _metric_container(event)
        for key in ("likes", "comments", "favorites", "shares"):
            value = event.get(key, nested.get(key))
            if _is_number(value) and float(value) >= 0:
                component_values.append(float(value))
        if component_values:
            metrics["interactions"] = sum(component_values)
            statuses["interactions"] = "available"
            derived_metrics.append("interactions")
            if "interactions" in missing:
                missing.remove("interactions")

    if statuses["interaction_rate"] == "unavailable":
        interactions = metrics["interactions"]
        reads = metrics["reads"]
        denominator = reads if isinstance(reads, (int, float)) and reads > 0 else None
        if (
            statuses["interactions"] == "available"
            and denominator is not None
            and isinstance(interactions, (int, float))
        ):
            derived_interaction_rate = interactions / denominator
            if 0 <= derived_interaction_rate <= 1:
                metrics["interaction_rate"] = derived_interaction_rate
                statuses["interaction_rate"] = "available"
                derived_metrics.append("interaction_rate")
                if "interaction_rate" in missing:
                    missing.remove("interaction_rate")

    if statuses["rpm"] == "unavailable":
        revenue = metrics["revenue"]
        impressions = metrics["impressions"]
        if (
            statuses["revenue"] == "available"
            and statuses["impressions"] == "available"
            and isinstance(revenue, (int, float))
            and isinstance(impressions, (int, float))
            and impressions > 0
        ):
            metrics["rpm"] = revenue / impressions * 1000
            statuses["rpm"] = "available"
            derived_metrics.append("rpm")
            if "rpm" in missing:
                missing.remove("rpm")

    # Preserve the evidence boundary: a derived rate is usable only because
    # its underlying exported values were present; it is never a zero fill.
    return metrics, statuses, sorted(set(missing)), derived_metrics + invalid


def _valid_threshold_value(key: str, value: object) -> bool:
    return (
        _is_number(value)
        and float(value) >= 0
        and (key not in _RATE_THRESHOLDS or float(value) <= 1)
    )


def _valid_threshold_mapping(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == set(_DEFAULT_THRESHOLDS)
        and all(
            isinstance(key, str) and _valid_threshold_value(key, threshold)
            for key, threshold in value.items()
        )
    )


def _resolved_thresholds(
    thresholds: Mapping[str, float] | None,
) -> tuple[dict[str, float], list[str]]:
    result = dict(_DEFAULT_THRESHOLDS)
    if thresholds is None:
        return result, []
    if not isinstance(thresholds, Mapping):
        return result, ["invalid:thresholds"]
    errors: list[str] = []
    seen: set[str] = set()
    for raw_key, raw_value in thresholds.items():
        if not isinstance(raw_key, str):
            errors.append("invalid:threshold:key")
            continue
        key = raw_key if raw_key in result else _THRESHOLD_ALIASES.get(raw_key)
        if key is None:
            errors.append(f"unknown:threshold:{raw_key}")
            continue
        if key in seen:
            errors.append(f"duplicate:threshold:{key}")
            continue
        seen.add(key)
        if not _valid_threshold_value(key, raw_value):
            errors.append(f"invalid:threshold:{key}")
            continue
        numeric = float(raw_value)
        result[key] = numeric
    return result, errors


def _has_metrics(
    statuses: Mapping[str, str],
    metrics: Mapping[str, object],
    names: Sequence[str],
    missing: set[str],
) -> bool:
    complete = True
    for name in names:
        if statuses.get(name) != "available" or metrics.get(name) is None:
            missing.add(name)
            complete = False
    return complete


def _comparison(
    metric: str,
    value: object,
    operator: str,
    threshold: object,
) -> dict[str, Any]:
    return {
        "metric": metric,
        "value": value,
        "operator": operator,
        "threshold": threshold,
    }


def _evidence(
    metrics: Mapping[str, object],
    threshold_values: Mapping[str, float],
    metric_names: Sequence[str],
    threshold_names: Sequence[str],
    comparisons: Sequence[Mapping[str, Any]],
    *,
    extra_metrics: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    actual_metrics = {name: metrics.get(name) for name in metric_names}
    if extra_metrics:
        actual_metrics.update(extra_metrics)
    return {
        "metrics": actual_metrics,
        "thresholds": {
            name: threshold_values[name] for name in threshold_names
        },
        "comparisons": [dict(item) for item in comparisons],
    }


def _comparison_holds(value: object, operator: object, threshold: object) -> bool:
    if not _is_number(value) or not _is_number(threshold):
        return False
    if operator == ">=":
        return float(value) >= float(threshold)
    if operator == "<":
        return float(value) < float(threshold)
    return False


def classify_failure_sample(
    event: Mapping[str, Any],
    *,
    thresholds: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Classify one metric event using only available, non-zero-filled data."""

    raw_event = event if isinstance(event, Mapping) else {}
    resolved, threshold_errors = _resolved_thresholds(thresholds)
    metrics, statuses, input_missing, derivations = _normalise_metrics(raw_event)
    missing_metrics: set[str] = set(input_missing)
    categories: list[str] = []
    evidence: dict[str, dict[str, Any]] = {}
    recommendations: dict[str, str] = {}
    evaluated_categories = 0
    if _has_metrics(
        statuses,
        metrics,
        ("impressions", "ctr"),
        missing_metrics,
    ):
        evaluated_categories += 1
        if (
            float(metrics["impressions"]) >= resolved[
                "exposure_without_click_min_impressions"
            ]
            and float(metrics["ctr"]) < resolved["exposure_without_click_max_ctr"]
        ):
            category = "exposure_without_click"
            categories.append(category)
            evidence[category] = _evidence(
                metrics,
                resolved,
                ("impressions", "ctr"),
                (
                    "exposure_without_click_min_impressions",
                    "exposure_without_click_max_ctr",
                ),
                (
                    _comparison(
                        "impressions",
                        metrics["impressions"],
                        ">=",
                        resolved["exposure_without_click_min_impressions"],
                    ),
                    _comparison(
                        "ctr",
                        metrics["ctr"],
                        "<",
                        resolved["exposure_without_click_max_ctr"],
                    ),
                ),
            )
            recommendations[category] = _RECOMMENDATIONS[category]

    if _has_metrics(
        statuses,
        metrics,
        ("reads", "completion_rate"),
        missing_metrics,
    ):
        evaluated_categories += 1
        if (
            float(metrics["reads"]) >= resolved["click_low_completion_min_reads"]
            and float(metrics["completion_rate"])
            < resolved["click_low_completion_max_completion_rate"]
        ):
            category = "click_low_completion"
            categories.append(category)
            evidence[category] = _evidence(
                metrics,
                resolved,
                ("reads", "completion_rate"),
                (
                    "click_low_completion_min_reads",
                    "click_low_completion_max_completion_rate",
                ),
                (
                    _comparison(
                        "reads",
                        metrics["reads"],
                        ">=",
                        resolved["click_low_completion_min_reads"],
                    ),
                    _comparison(
                        "completion_rate",
                        metrics["completion_rate"],
                        "<",
                        resolved["click_low_completion_max_completion_rate"],
                    ),
                ),
            )
            recommendations[category] = _RECOMMENDATIONS[category]

    if _has_metrics(
        statuses,
        metrics,
        ("impressions", "completion_rate"),
        missing_metrics,
    ):
        evaluated_categories += 1
        if (
            float(metrics["completion_rate"])
            >= resolved["high_completion_low_exposure_min_completion_rate"]
            and float(metrics["impressions"])
            < resolved["high_completion_low_exposure_max_impressions"]
        ):
            category = "high_completion_low_exposure"
            categories.append(category)
            evidence[category] = _evidence(
                metrics,
                resolved,
                ("completion_rate", "impressions"),
                (
                    "high_completion_low_exposure_min_completion_rate",
                    "high_completion_low_exposure_max_impressions",
                ),
                (
                    _comparison(
                        "completion_rate",
                        metrics["completion_rate"],
                        ">=",
                        resolved["high_completion_low_exposure_min_completion_rate"],
                    ),
                    _comparison(
                        "impressions",
                        metrics["impressions"],
                        "<",
                        resolved["high_completion_low_exposure_max_impressions"],
                    ),
                ),
            )
            recommendations[category] = _RECOMMENDATIONS[category]

    if _has_metrics(
        statuses,
        metrics,
        ("interaction_rate", "rpm"),
        missing_metrics,
    ):
        evaluated_categories += 1
        if (
            float(metrics["interaction_rate"])
            >= resolved["high_interaction_low_revenue_min_interaction_rate"]
            and float(metrics["rpm"])
            < resolved["high_interaction_low_revenue_max_rpm"]
        ):
            category = "high_interaction_low_revenue"
            categories.append(category)
            evidence[category] = _evidence(
                metrics,
                resolved,
                ("interaction_rate", "rpm"),
                (
                    "high_interaction_low_revenue_min_interaction_rate",
                    "high_interaction_low_revenue_max_rpm",
                ),
                (
                    _comparison(
                        "interaction_rate",
                        metrics["interaction_rate"],
                        ">=",
                        resolved["high_interaction_low_revenue_min_interaction_rate"],
                    ),
                    _comparison(
                        "rpm",
                        metrics["rpm"],
                        "<",
                        resolved["high_interaction_low_revenue_max_rpm"],
                    ),
                ),
            )
            recommendations[category] = _RECOMMENDATIONS[category]

    if _has_metrics(
        statuses,
        metrics,
        ("impressions", "reads", "completion_rate", "risk_score"),
        missing_metrics,
    ):
        evaluated_categories += 1
        if (
            float(metrics["impressions"])
            >= resolved["good_data_high_risk_min_impressions"]
            and float(metrics["reads"]) >= resolved["good_data_high_risk_min_reads"]
            and float(metrics["completion_rate"])
            >= resolved["good_data_high_risk_min_completion_rate"]
            and float(metrics["risk_score"])
            >= resolved["good_data_high_risk_min_risk_score"]
        ):
            category = "good_data_high_risk"
            categories.append(category)
            evidence[category] = _evidence(
                metrics,
                resolved,
                (
                    "impressions",
                    "reads",
                    "completion_rate",
                    "risk_score",
                ),
                (
                    "good_data_high_risk_min_impressions",
                    "good_data_high_risk_min_reads",
                    "good_data_high_risk_min_completion_rate",
                    "good_data_high_risk_min_risk_score",
                ),
                (
                    _comparison(
                        "impressions",
                        metrics["impressions"],
                        ">=",
                        resolved["good_data_high_risk_min_impressions"],
                    ),
                    _comparison(
                        "reads",
                        metrics["reads"],
                        ">=",
                        resolved["good_data_high_risk_min_reads"],
                    ),
                    _comparison(
                        "completion_rate",
                        metrics["completion_rate"],
                        ">=",
                        resolved["good_data_high_risk_min_completion_rate"],
                    ),
                    _comparison(
                        "risk_score",
                        metrics["risk_score"],
                        ">=",
                        resolved["good_data_high_risk_min_risk_score"],
                    ),
                ),
            )
            recommendations[category] = _RECOMMENDATIONS[category]

    if threshold_errors:
        categories = ["insufficient_data"]
        evidence = {}
        recommendations = {}
        status = "insufficient_data"
    elif categories:
        status = "classified"
    elif evaluated_categories < len(_CLASSIFIABLE_FAILURE_TYPES) or missing_metrics:
        categories = ["insufficient_data"]
        evidence = {}
        recommendations = {}
        status = "insufficient_data"
    else:
        status = "no_failure"

    missing_metrics = sorted(set(missing_metrics))
    result: dict[str, Any] = {
        "article_id": raw_event.get("article_id"),
        "categories": categories,
        "status": status,
        "metrics": metrics,
        "metric_status": statuses,
        "missing_metrics": missing_metrics,
        "thresholds": {} if threshold_errors else resolved,
        "evidence": evidence,
        "recommendations": recommendations,
        "suggested_changes": deepcopy(recommendations),
        "derived_metrics": sorted(set(derivations)),
        "publication_authorization": PUBLICATION_AUTHORIZATION,
        "auto_apply": False,
    }
    if threshold_errors:
        result["threshold_errors"] = threshold_errors
    for key in ("event_id", "evidence_ref", "platform", "published_at"):
        value = raw_event.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value
    return result


def build_failure_artifact(
    events: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    generated_at: str,
) -> dict[str, Any]:
    """Build a closed failure-sample envelope from caller-supplied events."""

    raw_events = list(events) if isinstance(events, Sequence) and not isinstance(
        events, (str, bytes, bytearray)
    ) else []
    samples = [classify_failure_sample(event) for event in raw_events]
    payload = {
        "samples": samples,
        "sample_count": len(samples),
        "auto_apply": False,
        "publication_authorization": PUBLICATION_AUTHORIZATION,
    }
    result = new_artifact_envelope(
        _SCHEMA_VERSION,
        run_id,
        payload,
        generated_at=generated_at,
    )
    digest = _stable_hash(raw_events)
    if digest is not None:
        result["input_hashes"] = {"events": digest}
    return result


def _valid_metric_output(
    metric: str,
    value: object,
    status: object,
) -> bool:
    if status not in _METRIC_STATUS_VALUES:
        return False
    if status == "unavailable":
        return value is None
    if not _is_number(value):
        return False
    return float(value) >= 0 and (
        metric not in _RATE_METRICS or float(value) <= 1
    )


def _validate_failure_sample(sample: object, index: int) -> list[str]:
    prefix = f"sample:{index}"
    if not isinstance(sample, Mapping):
        return [f"invalid:{prefix}"]
    errors: list[str] = []
    article_id = sample.get("article_id")
    if not isinstance(article_id, str) or not article_id.strip():
        errors.append(f"invalid:{prefix}:article_id")
    categories = sample.get("categories")
    if not isinstance(categories, list):
        errors.append(f"invalid:{prefix}:categories")
        categories = []
    elif any(
        not isinstance(category, str) or category not in FAILURE_TYPES
        for category in categories
    ) or len(categories) != len(set(categories)):
        errors.append(f"invalid:{prefix}:categories")
    if "insufficient_data" in categories and categories != ["insufficient_data"]:
        errors.append(f"invalid:{prefix}:categories")

    status = sample.get("status")
    if status not in {"classified", "insufficient_data", "no_failure"}:
        errors.append(f"invalid:{prefix}:status")
    elif categories == ["insufficient_data"] and status != "insufficient_data":
        errors.append(f"invalid:{prefix}:status")
    elif not categories and status != "no_failure":
        errors.append(f"invalid:{prefix}:status")
    elif categories and categories != ["insufficient_data"] and status != "classified":
        errors.append(f"invalid:{prefix}:status")

    metrics = sample.get("metrics")
    statuses = sample.get("metric_status")
    if not isinstance(metrics, Mapping) or not isinstance(statuses, Mapping):
        errors.append(f"invalid:{prefix}:metrics")
        metrics = {}
        statuses = {}
    else:
        for metric in _METRIC_NAMES:
            if metric not in metrics or metric not in statuses:
                errors.append(f"missing:{prefix}:metric:{metric}")
                continue
            if not _valid_metric_output(
                metric,
                metrics.get(metric),
                statuses.get(metric),
            ):
                errors.append(f"invalid:{prefix}:metric:{metric}")

    thresholds = sample.get("thresholds")
    if not _valid_threshold_mapping(thresholds):
        errors.append(f"invalid:{prefix}:thresholds")
        thresholds = {}

    evidence = sample.get("evidence")
    recommendations = sample.get("recommendations")
    suggested_changes = sample.get("suggested_changes")
    if not isinstance(evidence, Mapping):
        errors.append(f"invalid:{prefix}:evidence")
        evidence = {}
    if not isinstance(recommendations, Mapping):
        errors.append(f"invalid:{prefix}:recommendations")
        recommendations = {}
    if not isinstance(suggested_changes, Mapping):
        errors.append(f"invalid:{prefix}:suggested_changes")
        suggested_changes = {}

    if categories == ["insufficient_data"]:
        if evidence or recommendations or suggested_changes:
            errors.append(f"invalid:{prefix}:insufficient_data_details")
        missing_metrics = sample.get("missing_metrics")
        if not isinstance(missing_metrics, list) or not missing_metrics or any(
            not isinstance(metric, str) or metric not in _METRIC_NAMES
            for metric in missing_metrics
        ):
            errors.append(f"invalid:{prefix}:missing_metrics")
    elif not categories:
        if evidence or recommendations or suggested_changes:
            errors.append(f"invalid:{prefix}:no_failure_details")
    else:
        if set(evidence) != set(categories) or set(recommendations) != set(categories):
            errors.append(f"invalid:{prefix}:classification_details")
        if set(suggested_changes) != set(categories) or (
            isinstance(recommendations, Mapping)
            and isinstance(suggested_changes, Mapping)
            and suggested_changes != recommendations
        ):
            errors.append(f"invalid:{prefix}:suggested_changes")
        for category in categories:
            detail = evidence.get(category)
            if not isinstance(detail, Mapping):
                errors.append(f"invalid:{prefix}:evidence:{category}")
                continue
            contract = _EVIDENCE_CONTRACT.get(category)
            if contract is None:
                continue
            if set(detail) != {"metrics", "thresholds", "comparisons"}:
                errors.append(f"invalid:{prefix}:evidence:{category}")
            detail_metrics = detail.get("metrics")
            detail_thresholds = detail.get("thresholds")
            comparisons = detail.get("comparisons")
            expected_metrics = contract["metrics"]
            metrics_valid = isinstance(detail_metrics, Mapping) and set(
                detail_metrics
            ) == set(expected_metrics)
            if not metrics_valid or any(
                statuses.get(metric) != "available"
                or detail_metrics.get(metric) != metrics.get(metric)
                for metric in expected_metrics
            ):
                errors.append(f"invalid:{prefix}:evidence:{category}:metrics")
            expected_thresholds = contract["thresholds"]
            thresholds_valid = isinstance(detail_thresholds, Mapping) and set(
                detail_thresholds
            ) == set(expected_thresholds)
            if not thresholds_valid or any(
                not _valid_threshold_value(
                    threshold_name,
                    detail_thresholds.get(threshold_name),
                )
                or not _valid_threshold_mapping(thresholds)
                or detail_thresholds.get(threshold_name)
                != thresholds.get(threshold_name)
                for threshold_name in expected_thresholds
            ):
                errors.append(f"invalid:{prefix}:evidence:{category}:thresholds")
            expected_comparisons = contract["comparisons"]
            if not isinstance(comparisons, list) or len(comparisons) != len(
                expected_comparisons
            ):
                errors.append(f"invalid:{prefix}:evidence:{category}:comparisons")
            else:
                for comparison, (
                    metric,
                    operator,
                    threshold_name,
                ) in zip(comparisons, expected_comparisons):
                    comparison_valid = (
                        isinstance(comparison, Mapping)
                        and set(comparison)
                        == {"metric", "value", "operator", "threshold"}
                        and comparison.get("metric") == metric
                        and comparison.get("operator") == operator
                        and comparison.get("value") == metrics.get(metric)
                        and comparison.get("threshold")
                        == thresholds.get(threshold_name)
                        and _comparison_holds(
                            comparison.get("value"),
                            comparison.get("operator"),
                            comparison.get("threshold"),
                        )
                    )
                    if not comparison_valid:
                        errors.append(
                            f"invalid:{prefix}:evidence:{category}:comparisons"
                        )
            if not isinstance(recommendations.get(category), str) or not recommendations[
                category
            ].strip():
                errors.append(f"invalid:{prefix}:recommendation:{category}")
            if not isinstance(suggested_changes.get(category), str) or not suggested_changes[
                category
            ].strip():
                errors.append(f"invalid:{prefix}:suggested_change:{category}")

    if sample.get("publication_authorization") != PUBLICATION_AUTHORIZATION:
        errors.append(
            f"invalid:{prefix}:publication_authorization_must_be_not_authorized"
        )
    if sample.get("auto_apply") is not False:
        errors.append(f"invalid:{prefix}:auto_apply")
    return errors


def validate_failure_artifact(record: Mapping[str, Any]) -> list[str]:
    """Return stable validation errors for a failure-sample envelope."""

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

    samples = payload.get("samples")
    sample_count = payload.get("sample_count")
    if not isinstance(samples, list):
        errors.append("invalid:payload:samples")
        samples = []
    if isinstance(sample_count, bool) or not isinstance(sample_count, int):
        errors.append("invalid:payload:sample_count")
    elif sample_count != len(samples):
        errors.append("mismatch:payload:sample_count")
    for index, sample in enumerate(samples):
        errors.extend(_validate_failure_sample(sample, index))

    if payload.get("auto_apply") is not False:
        errors.append("auto_apply_must_be_false")
    if payload.get("publication_authorization") != PUBLICATION_AUTHORIZATION:
        errors.append("publication_authorization_must_be_not_authorized")
    return list(dict.fromkeys(errors))


__all__ = [
    "FAILURE_THRESHOLDS",
    "build_failure_artifact",
    "classify_failure_sample",
    "validate_failure_artifact",
]
