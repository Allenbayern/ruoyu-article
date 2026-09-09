"""Offline, bounded recommendations for V5 topic quotas.

The quota module describes what a controller may consider.  It never mutates
the supplied baseline and never applies a recommendation to a scheduler.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import date, datetime, timedelta
import math
import statistics
from typing import Any

from .contracts import (
    PUBLICATION_AUTHORIZATION,
    new_artifact_envelope,
    payload_of,
    validate_v5_artifact_envelope,
)


_SCHEMA_VERSION = "v5-dynamic-quotas-v1"
_DEFAULT_MIN_SHARE = 0.05
_DEFAULT_MAX_SHARE = 0.60
_DEFAULT_HIGH_RISK_CAP = 0.20
_DEFAULT_MIN_SAMPLES = 3
_DEFAULT_MIN_WEEKS = 2
_DEFAULT_COMPLETION_FLOOR = 0.50
_DEFAULT_COOLDOWN_DAYS = 7
_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "completion_rate": ("completion_rate", "completion", "completion_ratio"),
    "rpm": ("rpm", "revenue_per_thousand"),
    "risk_score": ("risk_score", "risk"),
}
_DATE_FIELDS = (
    "date",
    "day",
    "week_start",
    "week",
    "observed_at",
    "published_at",
    "measured_at",
    "timestamp",
    "created_at",
)
_TOPIC_FIELDS = ("topic_type", "topic", "type", "topic_family")
_SAMPLE_ID_FIELDS = ("sample_id",)
_FAILURE_FIELDS = ("failure_type", "failure_types", "failure_category", "categories")
_CONSECUTIVE_FIELDS = (
    "consecutive_failures",
    "consecutive_failure_count",
    "consecutive_failed_attempts",
)


def _is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


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


def _record_date(record: Mapping[str, Any]) -> date | None:
    for field in _DATE_FIELDS:
        parsed = _parse_date(record.get(field))
        if parsed is not None:
            return parsed
    return None


def _topic_type(record: Mapping[str, Any]) -> str:
    for field in _TOPIC_FIELDS:
        value = _text(record.get(field))
        if value:
            return value
    return ""


def _sample_id(record: Mapping[str, Any]) -> str | None:
    for field in _SAMPLE_ID_FIELDS:
        value = _text(record.get(field))
        if value:
            return value
    return None


def _metric(record: Mapping[str, Any], name: str) -> float | None:
    containers: list[Mapping[str, Any]] = [record]
    nested = record.get("metrics")
    if isinstance(nested, Mapping):
        containers.append(nested)
    for container in containers:
        for field in _METRIC_ALIASES.get(name, (name,)):
            value = container.get(field)
            if _is_number(value):
                numeric = float(value)
                if name == "completion_rate" and not 0 <= numeric <= 1:
                    continue
                if name == "risk_score" and not 0 <= numeric <= 1:
                    continue
                if numeric < 0:
                    continue
                return numeric
    return None


def _failure_types(record: Mapping[str, Any]) -> list[str]:
    for field in _FAILURE_FIELDS:
        value = record.get(field)
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return sorted(
                {
                    item.strip()
                    for item in value
                    if isinstance(item, str) and item.strip()
                }
            )
    return []


def _consecutive_failures(record: Mapping[str, Any]) -> int:
    for field in _CONSECUTIVE_FIELDS:
        value = record.get(field)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        if _is_number(value) and float(value).is_integer() and float(value) >= 0:
            return int(value)
    return 0


def _is_usable(record: Mapping[str, Any]) -> bool:
    if _sample_id(record) is None:
        return False
    explicit = record.get("usable")
    if explicit is False:
        return False
    status = record.get("status")
    if isinstance(status, str) and status.strip().casefold() in {
        "unusable",
        "invalid",
        "insufficient_data",
        "missing",
    }:
        return False
    if explicit is not None and not isinstance(explicit, bool):
        return False
    return any(_metric(record, metric) is not None for metric in _METRIC_ALIASES)


def _deduplicate_records(
    records: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Keep one latest observation per declared sample identity."""

    latest: dict[str, Mapping[str, Any]] = {}
    latest_dates: dict[str, date | None] = {}
    for record in records:
        sample_id = _sample_id(record)
        if sample_id is None:
            continue
        observed_date = _record_date(record)
        previous = latest.get(sample_id)
        previous_date = latest_dates.get(sample_id)
        if previous is None or (
            observed_date is not None
            and (previous_date is None or observed_date >= previous_date)
        ):
            latest[sample_id] = record
            latest_dates[sample_id] = observed_date
    return sorted(
        latest.values(),
        key=lambda record: (
            _record_date(record) or date.min,
            _sample_id(record) or "",
        ),
    )


def _safe_bound(value: object, fallback: float) -> float:
    if not _is_number(value):
        return fallback
    return min(1.0, max(0.0, float(value)))


def _safe_positive_int(value: object, fallback: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    if _is_number(value) and float(value).is_integer() and float(value) > 0:
        return int(value)
    return fallback


def _safe_nonnegative_int(value: object, fallback: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if _is_number(value) and float(value).is_integer() and float(value) >= 0:
        return int(value)
    return fallback


def _strict_share(value: object, field: str) -> float:
    if not _is_number(value) or not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"invalid:bounds:{field}")
    return float(value)


def _strict_positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"invalid:config:{field}")
    return value


def _strict_nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"invalid:config:{field}")
    return value


def _configured_baseline(
    topic_type: str,
    config: Mapping[str, Any],
    *,
    minimum_share: float,
    maximum_share: float,
) -> float:
    values: list[tuple[str, float]] = []
    for field in ("share", "baseline_share", "recommended_share"):
        if field in config:
            if not _is_number(config[field]):
                raise ValueError(f"invalid:baseline_share:{topic_type}")
            value = float(config[field])
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"invalid:baseline_share:{topic_type}")
            values.append((field, value))
    if not values:
        return minimum_share
    baseline = values[0][1]
    if any(value != baseline for _field, value in values[1:]):
        raise ValueError(f"conflicting:baseline_share:{topic_type}")
    if not minimum_share <= baseline <= maximum_share:
        raise ValueError(f"invalid:baseline_share:{topic_type}")
    return baseline


def _validate_quota_inputs(
    base_quotas: Mapping[str, Mapping[str, Any]],
    *,
    lookback_weeks: object,
    min_share: object,
    max_share: object,
    high_risk_cap: object,
) -> tuple[dict[str, dict[str, Any]], int, float, float, float]:
    if not isinstance(base_quotas, Mapping):
        raise ValueError("invalid:base_quotas")
    if isinstance(lookback_weeks, bool) or not isinstance(lookback_weeks, int) or lookback_weeks <= 0:
        raise ValueError("invalid:config:lookback_weeks")
    minimum_share = _strict_share(min_share, "min_share")
    maximum_share = _strict_share(max_share, "max_share")
    risk_cap = _strict_share(high_risk_cap, "high_risk_cap")
    if minimum_share > maximum_share:
        raise ValueError("invalid:bounds:min_share_max_share")
    if risk_cap < minimum_share or risk_cap > maximum_share:
        raise ValueError("invalid:bounds:high_risk_cap")

    configs: dict[str, dict[str, Any]] = {}
    for topic, raw_config in base_quotas.items():
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("invalid:base_quotas:topic")
        if not isinstance(raw_config, Mapping):
            raise ValueError(f"invalid:base_quotas:{topic}")
        config = dict(raw_config)
        _configured_baseline(
            topic,
            config,
            minimum_share=minimum_share,
            maximum_share=maximum_share,
        )
        if "min_samples" in config:
            _strict_positive_int(config["min_samples"], f"{topic}:min_samples")
        if "min_weeks" in config:
            _strict_positive_int(config["min_weeks"], f"{topic}:min_weeks")
        if "cooldown_days" in config:
            _strict_nonnegative_int(config["cooldown_days"], f"{topic}:cooldown_days")
        if "completion_floor" in config:
            _strict_share(config["completion_floor"], f"{topic}:completion_floor")
        if "rpm_floor" in config:
            if not _is_number(config["rpm_floor"]) or float(config["rpm_floor"]) < 0:
                raise ValueError(f"invalid:config:{topic}:rpm_floor")
        if "high_risk" in config and not isinstance(config["high_risk"], bool):
            raise ValueError(f"invalid:config:{topic}:high_risk")
        if "risk_level" in config and _text(config["risk_level"]).casefold() not in {
            "low",
            "medium",
            "high",
            "critical",
        }:
            raise ValueError(f"invalid:config:{topic}:risk_level")
        configs[topic] = config
    return configs, lookback_weeks, minimum_share, maximum_share, risk_cap


def _week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


def _risk_level(config: Mapping[str, Any], records: Sequence[Mapping[str, Any]]) -> str:
    if config.get("high_risk") is True:
        return "high"
    configured = _text(config.get("risk_level")).casefold()
    if configured in {"high", "critical"}:
        return "high"
    if configured == "medium":
        configured = "medium"
    if any(record.get("high_risk") is True for record in records):
        return "high"
    record_levels = {
        _text(record.get("risk_level")).casefold()
        for record in records
    }
    if any(level in {"high", "critical"} for level in record_levels):
        return "high"
    scores = [_metric(record, "risk_score") for record in records]
    scores = [score for score in scores if score is not None]
    if scores and max(scores) >= 0.70:
        return "high"
    if configured == "medium" or (scores and max(scores) >= 0.40):
        return "medium"
    return "low"


def _consecutive_failure_count(records: Sequence[Mapping[str, Any]]) -> int:
    explicit = max(
        (_consecutive_failures(record) for record in records),
        default=0,
    )
    if explicit > 0:
        return explicit
    ordered = sorted(
        records,
        key=lambda record: _record_date(record) or date.min,
        reverse=True,
    )
    trailing = 0
    for record in ordered:
        if not _failure_types(record):
            break
        trailing += 1
    return trailing


def _median(values: Sequence[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _recommendation(
    topic_type: str,
    config: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    minimum_share: float,
    maximum_share: float,
    high_risk_cap: float,
    insufficient_reason: str | None = None,
) -> dict[str, Any]:
    baseline = _configured_baseline(
        topic_type,
        config,
        minimum_share=minimum_share,
        maximum_share=maximum_share,
    )
    min_samples = _safe_positive_int(config.get("min_samples"), _DEFAULT_MIN_SAMPLES)
    min_weeks = _safe_positive_int(config.get("min_weeks"), _DEFAULT_MIN_WEEKS)
    completion_floor_base = _safe_bound(
        config.get("completion_floor"), _DEFAULT_COMPLETION_FLOOR
    )
    cooldown_base = _safe_nonnegative_int(
        config.get("cooldown_days"), _DEFAULT_COOLDOWN_DAYS
    )
    usable_candidates = [record for record in records if _is_usable(record)]
    usable = _deduplicate_records(usable_candidates)
    missing_sample_id_count = sum(
        1
        for record in usable_candidates
        if _sample_id(record) is None
    )
    sample_ids = sorted(
        sample_id
        for record in usable
        if (sample_id := _sample_id(record)) is not None
    )
    dates = sorted(
        {
            parsed.isoformat()
            for record in usable
            if (parsed := _record_date(record)) is not None
        }
    )
    week_starts = sorted(
        {
            (parsed - timedelta(days=parsed.weekday())).isoformat()
            for record in usable
            if (parsed := _record_date(record)) is not None
        }
    )
    records_by_date: dict[str, list[Mapping[str, Any]]] = {}
    for record in usable:
        parsed = _record_date(record)
        if parsed is not None:
            records_by_date.setdefault(parsed.isoformat(), []).append(record)
    daily_statistics: dict[str, dict[str, float | None]] = {}
    for day, day_records in sorted(records_by_date.items()):
        daily_statistics[day] = {
            metric: _median(
                [
                    value
                    for record in day_records
                    if (value := _metric(record, metric)) is not None
                ]
            )
            for metric in ("completion_rate", "rpm", "risk_score")
        }
    medians = {
        metric: _median(
            [
                day_values[metric]
                for day_values in daily_statistics.values()
                if day_values[metric] is not None
            ]
        )
        for metric in ("completion_rate", "rpm", "risk_score")
    }
    failure_counts: Counter[str] = Counter()
    for record in usable:
        failure_counts.update(_failure_types(record))
    consecutive = _consecutive_failure_count(usable)
    risk_level = _risk_level(config, usable)
    enough_data = len(usable) >= min_samples and len(week_starts) >= min_weeks
    reasons: list[str] = []
    if insufficient_reason:
        reasons.append(insufficient_reason)
    if missing_sample_id_count:
        reasons.append("missing_sample_id")
    if not usable:
        reasons.append("no_usable_history")
    elif len(usable) < min_samples:
        reasons.append("minimum_samples_not_met")
    if usable and len(week_starts) < min_weeks:
        reasons.append("minimum_weeks_not_met")

    failure_downweight = max(0.25, 1.0 - 0.10 * consecutive)
    cooldown_days = cooldown_base + consecutive * 2
    completion_floor = completion_floor_base
    recommended_share = baseline
    if enough_data:
        completion = medians["completion_rate"]
        rpm = medians["rpm"]
        if completion is not None:
            completion_floor = max(
                completion_floor_base,
                min(1.0, completion * 0.80),
            )
        completion_signal = (
            min(2.0, max(0.0, completion / max(completion_floor_base, 0.01)))
            if completion is not None
            else 1.0
        )
        rpm_floor = _metric(config, "rpm_floor") or 1.0
        rpm_signal = (
            min(2.0, max(0.0, rpm / max(rpm_floor, 0.01)))
            if rpm is not None
            else 1.0
        )
        quality_multiplier = 0.75 + 0.125 * completion_signal + 0.125 * rpm_signal
        recommended_share = baseline * quality_multiplier * failure_downweight
        reasons.append("median_metrics")
    else:
        reasons.append("baseline_retained_data_insufficient")

    if risk_level == "high":
        if enough_data:
            capped = min(recommended_share, high_risk_cap)
            if capped < recommended_share:
                reasons.append("high_risk_cap_applied")
            recommended_share = capped
        else:
            reasons.append("high_risk_cap_deferred_data_insufficient")
    if enough_data:
        recommended_share = min(
            maximum_share,
            max(minimum_share, recommended_share),
        )
    reasons = _unique(reasons)

    return {
        "topic_type": topic_type,
        "baseline_share": baseline,
        "recommended_share": round(float(recommended_share), 6),
        "min_share": minimum_share,
        "max_share": maximum_share,
        "share_bounds": {"min": minimum_share, "max": maximum_share},
        "min_samples": min_samples,
        "min_weeks": min_weeks,
        "completion_floor": round(float(completion_floor), 6),
        "completion_rate_floor": round(float(completion_floor), 6),
        "high_risk_cap": high_risk_cap,
        "cooldown_days": cooldown_days,
        "consecutive_failures": consecutive,
        "consecutive_failure_downweight": round(failure_downweight, 6),
        "failure_downweight": round(failure_downweight, 6),
        "risk_level": risk_level,
        "sample_ids": sample_ids,
        "sample_count": len(sample_ids),
        "week_count": len(week_starts),
        "dates": dates,
        "daily_medians": daily_statistics,
        "medians": medians,
        "failure_counts": dict(sorted(failure_counts.items())),
        "data_sufficiency": "sufficient" if enough_data else "insufficient",
        "reasons": reasons,
    }


def derive_dynamic_quotas(
    history: Sequence[Mapping[str, Any]],
    base_quotas: Mapping[str, Mapping[str, Any]],
    *,
    run_id: str,
    generated_at: str,
    lookback_weeks: int = 4,
    min_share: float = 0.05,
    max_share: float = 0.60,
    high_risk_cap: float = 0.20,
) -> dict[str, Any]:
    """Derive bounded, controller-only quota recommendations."""

    configs, weeks, minimum_share, maximum_share, risk_cap = _validate_quota_inputs(
        base_quotas,
        lookback_weeks=lookback_weeks,
        min_share=min_share,
        max_share=max_share,
        high_risk_cap=high_risk_cap,
    )
    input_rows = [
        dict(row)
        for row in history
        if isinstance(row, Mapping)
    ] if isinstance(history, Sequence) and not isinstance(history, (str, bytes, bytearray)) else []
    dated_rows = [
        (row, parsed)
        for row in input_rows
        if (parsed := _record_date(row)) is not None and _topic_type(row)
    ]
    anchor = max((parsed for _row, parsed in dated_rows), default=None)
    if anchor is None:
        anchor = _parse_date(generated_at)
        if anchor is None:
            raise ValueError("invalid:generated_at")
    if anchor is None:
        window_start = None
        window_end = None
        filtered_rows: list[Mapping[str, Any]] = []
    else:
        anchor_week = anchor - timedelta(days=anchor.weekday())
        window_start = anchor_week - timedelta(weeks=weeks - 1)
        window_end = anchor_week + timedelta(days=6)
        filtered_rows = [
            row
            for row, parsed in dated_rows
            if window_start <= parsed <= window_end
        ]

    observed_topics = {
        _topic_type(row)
        for row in filtered_rows
        if _is_usable(row) and _topic_type(row)
    }
    topics = sorted(set(configs) | observed_topics)
    if not topics:
        topics = ["unclassified"]

    by_topic: dict[str, list[Mapping[str, Any]]] = {topic: [] for topic in topics}
    for row in filtered_rows:
        topic = _topic_type(row)
        if topic in by_topic:
            by_topic[topic].append(row)

    recommendations = [
        _recommendation(
            topic,
            configs.get(topic, {}),
            rows,
            minimum_share=minimum_share,
            maximum_share=maximum_share,
            high_risk_cap=risk_cap,
            insufficient_reason="missing_baseline" if topic not in configs else None,
        )
        for topic, rows in sorted(by_topic.items())
    ]
    sufficient = [
        recommendation["data_sufficiency"] == "sufficient"
        for recommendation in recommendations
    ]
    if not any(sufficient):
        data_sufficiency = "insufficient"
    elif all(sufficient):
        data_sufficiency = "sufficient"
    else:
        data_sufficiency = "partial"
    insufficiency_reasons = _unique(
        reason
        for recommendation in recommendations
        if recommendation["data_sufficiency"] != "sufficient"
        for reason in recommendation["reasons"]
        if reason in {
            "no_usable_history",
            "minimum_samples_not_met",
            "minimum_weeks_not_met",
            "missing_baseline",
        }
    )
    if not filtered_rows:
        insufficiency_reasons = _unique(["no_usable_history", *insufficiency_reasons])

    included_dates = sorted(
        {
            date_value
            for recommendation in recommendations
            for date_value in recommendation["dates"]
        }
    )
    included_sample_ids = sorted(
        {
            sample_id
            for recommendation in recommendations
            for sample_id in recommendation["sample_ids"]
        }
    )

    payload = {
        "base_quotas": deepcopy(configs),
        "lookback_weeks": weeks,
        "lookback_start": window_start.isoformat() if window_start else None,
        "lookback_end": window_end.isoformat() if window_end else None,
        "included_dates": included_dates,
        "included_sample_ids": included_sample_ids,
        "sample_count": len(included_sample_ids),
        "week_count": len(
            {
                _week_start(parsed).isoformat()
                for date_value in included_dates
                if (parsed := _parse_date(date_value)) is not None
            }
        ),
        "data_sufficiency": data_sufficiency,
        "insufficiency_reasons": insufficiency_reasons,
        "recommendations": recommendations,
        "bounds": {
            "min_share": minimum_share,
            "max_share": maximum_share,
            "high_risk_cap": risk_cap,
        },
        "auto_apply": False,
        "controller_only": True,
        "publication_authorization": PUBLICATION_AUTHORIZATION,
    }
    return new_artifact_envelope(
        _SCHEMA_VERSION,
        run_id,
        payload,
        generated_at=generated_at,
    )


def _validate_number(
    value: object,
    error: str,
    errors: list[str],
    *,
    lower: float | None = None,
    upper: float | None = None,
) -> None:
    if not _is_number(value):
        errors.append(error)
        return
    numeric = float(value)
    if lower is not None and numeric < lower:
        errors.append(error)
    if upper is not None and numeric > upper:
        errors.append(error)


def validate_quota_plan(plan: Mapping[str, Any]) -> list[str]:
    """Return stable validation errors for a dynamic-quota artifact."""

    if not isinstance(plan, Mapping):
        return ["invalid:artifact"]
    run_id = plan.get("run_id") if isinstance(plan.get("run_id"), str) else ""
    errors = validate_v5_artifact_envelope(
        plan,
        _SCHEMA_VERSION,
        run_id=run_id,
    )
    payload = payload_of(plan)
    if not isinstance(payload, Mapping):
        return list(dict.fromkeys(errors))
    required = (
        "base_quotas",
        "lookback_weeks",
        "lookback_start",
        "lookback_end",
        "included_dates",
        "included_sample_ids",
        "sample_count",
        "week_count",
        "data_sufficiency",
        "insufficiency_reasons",
        "recommendations",
        "bounds",
        "auto_apply",
        "controller_only",
        "publication_authorization",
    )
    for field in required:
        if field not in payload:
            errors.append(f"missing:payload:{field}")
    if not isinstance(payload.get("base_quotas"), Mapping):
        errors.append("invalid:payload:base_quotas")
        base_quotas: Mapping[str, Any] = {}
    else:
        base_quotas = payload["base_quotas"]
    weeks = payload.get("lookback_weeks")
    valid_weeks = not isinstance(weeks, bool) and isinstance(weeks, int) and weeks > 0
    if not valid_weeks:
        errors.append("invalid:payload:lookback_weeks")
    start = _parse_date(payload.get("lookback_start"))
    end = _parse_date(payload.get("lookback_end"))
    valid_window = start is not None and end is not None and valid_weeks
    if start is None:
        errors.append("invalid:payload:lookback_start")
    if end is None:
        errors.append("invalid:payload:lookback_end")
    if valid_window and (
        start.weekday() != 0
        or end.weekday() != 6
        or (end - start).days + 1 != weeks * 7
    ):
        errors.append("invalid:payload:window")
    payload_data_sufficiency = payload.get("data_sufficiency")
    if not isinstance(payload_data_sufficiency, str) or payload_data_sufficiency not in (
        "sufficient",
        "partial",
        "insufficient",
    ):
        errors.append("invalid:payload:data_sufficiency")
    reasons = payload.get("insufficiency_reasons")
    if not isinstance(reasons, list) or any(not isinstance(reason, str) for reason in reasons):
        errors.append("invalid:payload:insufficiency_reasons")
    bounds = payload.get("bounds")
    if not isinstance(bounds, Mapping):
        errors.append("invalid:payload:bounds")
        bounds = {}
    _validate_number(bounds.get("min_share"), "invalid:bounds:min_share", errors, lower=0, upper=1)
    _validate_number(bounds.get("max_share"), "invalid:bounds:max_share", errors, lower=0, upper=1)
    _validate_number(bounds.get("high_risk_cap"), "invalid:bounds:high_risk_cap", errors, lower=0, upper=1)
    if _is_number(bounds.get("min_share")) and _is_number(bounds.get("max_share")) and float(bounds["min_share"]) > float(bounds["max_share"]):
        errors.append("invalid:bounds:ordering")
    if (
        _is_number(bounds.get("min_share"))
        and _is_number(bounds.get("max_share"))
        and _is_number(bounds.get("high_risk_cap"))
        and not (
            float(bounds["min_share"])
            <= float(bounds["high_risk_cap"])
            <= float(bounds["max_share"])
        )
    ):
        errors.append("invalid:bounds:high_risk_cap")
    if payload.get("auto_apply") is not False:
        errors.append("auto_apply_must_be_false")
    if payload.get("controller_only") is not True:
        errors.append("controller_only_must_be_true")
    if payload.get("publication_authorization") != PUBLICATION_AUTHORIZATION:
        errors.append("publication_authorization_must_be_not_authorized")

    for topic, config in base_quotas.items():
        if not isinstance(topic, str) or not topic.strip() or not isinstance(config, Mapping):
            errors.append("invalid:payload:base_quotas")
            continue
        baseline_values = []
        for field in ("share", "baseline_share", "recommended_share"):
            if field in config:
                value = config[field]
                if not _is_number(value) or not 0 <= float(value) <= 1:
                    errors.append(f"invalid:baseline_share:{topic}")
                else:
                    baseline_values.append(float(value))
        if baseline_values and any(value != baseline_values[0] for value in baseline_values[1:]):
            errors.append(f"conflicting:baseline_share:{topic}")
        if baseline_values and _is_number(bounds.get("min_share")) and _is_number(bounds.get("max_share")):
            if not float(bounds["min_share"]) <= baseline_values[0] <= float(bounds["max_share"]):
                errors.append(f"invalid:baseline_share:{topic}")
        if "min_samples" in config and (
            isinstance(config["min_samples"], bool)
            or not isinstance(config["min_samples"], int)
            or config["min_samples"] <= 0
        ):
            errors.append(f"invalid:config:{topic}:min_samples")
        if "min_weeks" in config and (
            isinstance(config["min_weeks"], bool)
            or not isinstance(config["min_weeks"], int)
            or config["min_weeks"] <= 0
        ):
            errors.append(f"invalid:config:{topic}:min_weeks")
        if "cooldown_days" in config and (
            isinstance(config["cooldown_days"], bool)
            or not isinstance(config["cooldown_days"], int)
            or config["cooldown_days"] < 0
        ):
            errors.append(f"invalid:config:{topic}:cooldown_days")
        if "completion_floor" in config and (
            not _is_number(config["completion_floor"])
            or not 0 <= float(config["completion_floor"]) <= 1
        ):
            errors.append(f"invalid:config:{topic}:completion_floor")
        if "rpm_floor" in config and (
            not _is_number(config["rpm_floor"])
            or float(config["rpm_floor"]) < 0
        ):
            errors.append(f"invalid:config:{topic}:rpm_floor")
        if "high_risk" in config and not isinstance(config["high_risk"], bool):
            errors.append(f"invalid:config:{topic}:high_risk")
        if "risk_level" in config and _text(config["risk_level"]).casefold() not in {
            "low",
            "medium",
            "high",
            "critical",
        }:
            errors.append(f"invalid:config:{topic}:risk_level")

    included_dates = payload.get("included_dates")
    included_date_values: list[date] = []
    if not isinstance(included_dates, list):
        errors.append("invalid:payload:included_dates")
    else:
        for value in included_dates:
            parsed = _parse_date(value)
            if parsed is None:
                errors.append("invalid:payload:included_dates")
                continue
            included_date_values.append(parsed)
        if len(included_date_values) != len(set(included_date_values)):
            errors.append("invalid:payload:included_dates")
        if valid_window and any(
            parsed < start or parsed > end for parsed in included_date_values
        ):
            errors.append("invalid:payload:included_dates")
            errors.append("invalid:payload:included_dates:boundary")

    included_sample_ids = payload.get("included_sample_ids")
    if not isinstance(included_sample_ids, list) or any(
        not isinstance(sample_id, str) or not sample_id.strip()
        for sample_id in (included_sample_ids if isinstance(included_sample_ids, list) else ())
    ):
        errors.append("invalid:payload:included_sample_ids")
        included_sample_ids = []
    elif len(included_sample_ids) != len(set(included_sample_ids)):
        errors.append("invalid:payload:included_sample_ids")
    sample_count = payload.get("sample_count")
    valid_sample_count = isinstance(sample_count, int) and not isinstance(sample_count, bool) and sample_count >= 0
    if not valid_sample_count:
        errors.append("invalid:payload:sample_count")
    elif sample_count != len(included_sample_ids):
        errors.append("mismatch:payload:sample_count")
    week_count = payload.get("week_count")
    valid_week_count = isinstance(week_count, int) and not isinstance(week_count, bool) and week_count >= 0
    if not valid_week_count:
        errors.append("invalid:payload:week_count")
    elif week_count != len({_week_start(parsed) for parsed in included_date_values}):
        errors.append("mismatch:payload:week_count")

    recommendations = payload.get("recommendations")
    if not isinstance(recommendations, list):
        errors.append("invalid:payload:recommendations")
        recommendations = []
    seen_topics: set[str] = set()
    minimum = bounds.get("min_share")
    maximum = bounds.get("max_share")
    risk_cap = bounds.get("high_risk_cap")
    recommendation_dates: set[date] = set()
    recommendation_sample_ids: set[str] = set()
    recommendation_statuses: list[str] = []
    for index, recommendation in enumerate(recommendations):
        prefix = f"recommendation:{index}"
        if not isinstance(recommendation, Mapping):
            errors.append(f"invalid:{prefix}")
            continue
        topic = recommendation.get("topic_type")
        if not isinstance(topic, str) or not topic.strip():
            errors.append(f"invalid:{prefix}:topic_type")
        elif topic in seen_topics:
            errors.append(f"duplicate:{prefix}:topic_type")
        else:
            seen_topics.add(topic)
        if _is_number(minimum) and _is_number(maximum):
            _validate_number(
                recommendation.get("recommended_share"),
                f"invalid:{prefix}:recommended_share",
                errors,
                lower=float(minimum),
                upper=float(maximum),
            )
        else:
            _validate_number(recommendation.get("recommended_share"), f"invalid:{prefix}:recommended_share", errors)
        for field in ("baseline_share", "completion_floor", "high_risk_cap", "min_share", "max_share"):
            _validate_number(recommendation.get(field), f"invalid:{prefix}:{field}", errors, lower=0, upper=1)
        if (
            _is_number(minimum)
            and recommendation.get("min_share") != minimum
        ):
            errors.append(f"invalid:{prefix}:min_share")
        if (
            _is_number(maximum)
            and recommendation.get("max_share") != maximum
        ):
            errors.append(f"invalid:{prefix}:max_share")
        if (
            _is_number(risk_cap)
            and recommendation.get("high_risk_cap") != risk_cap
        ):
            errors.append(f"invalid:{prefix}:high_risk_cap")
        if _is_number(minimum) and _is_number(maximum) and _is_number(recommendation.get("baseline_share")):
            if not float(minimum) <= float(recommendation["baseline_share"]) <= float(maximum):
                errors.append(f"invalid:{prefix}:baseline_share")
        for field in ("min_samples", "min_weeks"):
            value = recommendation.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                errors.append(f"invalid:{prefix}:{field}")
        for field in ("cooldown_days", "sample_count", "week_count", "consecutive_failures"):
            value = recommendation.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                errors.append(f"invalid:{prefix}:{field}")
        sample_ids = recommendation.get("sample_ids")
        if not isinstance(sample_ids, list) or any(
            not isinstance(sample_id, str) or not sample_id.strip()
            for sample_id in (sample_ids if isinstance(sample_ids, list) else ())
        ):
            errors.append(f"invalid:{prefix}:sample_ids")
            sample_ids = []
        elif len(sample_ids) != len(set(sample_ids)):
            errors.append(f"invalid:{prefix}:sample_ids")
        if isinstance(recommendation.get("sample_count"), int) and not isinstance(recommendation.get("sample_count"), bool):
            if recommendation["sample_count"] != len(sample_ids):
                errors.append(f"mismatch:{prefix}:sample_count")
        recommendation_sample_ids.update(sample_ids)
        share_bounds = recommendation.get("share_bounds")
        if not isinstance(share_bounds, Mapping):
            errors.append(f"invalid:{prefix}:share_bounds")
        else:
            _validate_number(
                share_bounds.get("min"),
                f"invalid:{prefix}:share_bounds",
                errors,
                lower=0,
                upper=1,
            )
            _validate_number(
                share_bounds.get("max"),
                f"invalid:{prefix}:share_bounds",
                errors,
                lower=0,
                upper=1,
            )
            if (
                _is_number(minimum)
                and share_bounds.get("min") != minimum
            ) or (
                _is_number(maximum)
                and share_bounds.get("max") != maximum
            ):
                errors.append(f"invalid:{prefix}:share_bounds")
        _validate_number(
            recommendation.get("consecutive_failure_downweight"),
            f"invalid:{prefix}:consecutive_failure_downweight",
            errors,
            lower=0,
            upper=1,
        )
        recommendation_risk_level = recommendation.get("risk_level")
        if not isinstance(recommendation_risk_level, str) or recommendation_risk_level not in (
            "low",
            "medium",
            "high",
        ):
            errors.append(f"invalid:{prefix}:risk_level")
        if (
            recommendation.get("risk_level") == "high"
            and recommendation.get("data_sufficiency") == "sufficient"
            and _is_number(risk_cap)
            and _is_number(recommendation.get("recommended_share"))
            and float(recommendation["recommended_share"]) > float(risk_cap)
        ):
            errors.append(f"invalid:{prefix}:high_risk_cap")
        medians = recommendation.get("medians")
        if not isinstance(medians, Mapping):
            errors.append(f"invalid:{prefix}:medians")
        else:
            for metric in ("completion_rate", "rpm", "risk_score"):
                value = medians.get(metric)
                if value is not None and not _is_number(value):
                    errors.append(f"invalid:{prefix}:median:{metric}")
        dates = recommendation.get("dates")
        parsed_dates = [
            parsed
            for value in (dates if isinstance(dates, list) else ())
            if (parsed := _parse_date(value)) is not None
        ]
        if not isinstance(dates, list) or len(parsed_dates) != len(dates):
            errors.append(f"invalid:{prefix}:dates")
        else:
            if len(parsed_dates) != len(set(parsed_dates)):
                errors.append(f"invalid:{prefix}:dates")
            if valid_window and any(parsed < start or parsed > end for parsed in parsed_dates):
                errors.append(f"invalid:{prefix}:dates:boundary")
            if not set(parsed_dates) <= set(included_date_values):
                errors.append(f"invalid:{prefix}:dates_relationship")
            recommendation_dates.update(parsed_dates)
            derived_week_count = len({_week_start(parsed) for parsed in parsed_dates})
            if recommendation.get("week_count") != derived_week_count:
                errors.append(f"mismatch:{prefix}:week_count")
                errors.append(f"invalid:{prefix}:week_count_relationship")
            recommendation_sample_count = recommendation.get("sample_count")
            if (
                isinstance(recommendation_sample_count, int)
                and not isinstance(recommendation_sample_count, bool)
                and recommendation_sample_count < len(parsed_dates)
            ):
                errors.append(f"invalid:{prefix}:sample_count_relationship")
        failure_counts = recommendation.get("failure_counts")
        if not isinstance(failure_counts, Mapping) or any(
            not isinstance(key, str)
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            for key, value in (failure_counts.items() if isinstance(failure_counts, Mapping) else ())
        ):
            errors.append(f"invalid:{prefix}:failure_counts")
        if not isinstance(recommendation.get("reasons"), list) or any(
            not isinstance(reason, str) for reason in recommendation.get("reasons", [])
        ):
            errors.append(f"invalid:{prefix}:reasons")
        data_sufficiency = recommendation.get("data_sufficiency")
        if not isinstance(data_sufficiency, str) or data_sufficiency not in (
            "sufficient",
            "insufficient",
        ):
            errors.append(f"invalid:{prefix}:data_sufficiency")
        else:
            recommendation_statuses.append(data_sufficiency)
            min_samples = recommendation.get("min_samples")
            min_weeks = recommendation.get("min_weeks")
            valid_relationship_inputs = (
                isinstance(recommendation.get("sample_count"), int)
                and not isinstance(recommendation.get("sample_count"), bool)
                and isinstance(recommendation.get("week_count"), int)
                and not isinstance(recommendation.get("week_count"), bool)
                and isinstance(min_samples, int)
                and not isinstance(min_samples, bool)
                and isinstance(min_weeks, int)
                and not isinstance(min_weeks, bool)
            )
            if valid_relationship_inputs:
                expected = (
                    "sufficient"
                    if recommendation["sample_count"] >= min_samples
                    and recommendation["week_count"] >= min_weeks
                    else "insufficient"
                )
                if data_sufficiency != expected:
                    errors.append(f"invalid:{prefix}:data_sufficiency_relationship")
            if data_sufficiency == "insufficient" and _is_number(recommendation.get("baseline_share")) and _is_number(recommendation.get("recommended_share")) and recommendation["recommended_share"] != recommendation["baseline_share"]:
                errors.append(f"invalid:{prefix}:baseline_retention")

    if set(included_date_values) != recommendation_dates:
        errors.append("mismatch:payload:included_dates")
    if set(included_sample_ids) != recommendation_sample_ids:
        errors.append("mismatch:payload:included_sample_ids")
    if valid_sample_count and sample_count != len(recommendation_sample_ids):
        errors.append("mismatch:payload:sample_count")
    if valid_week_count and week_count != len({_week_start(parsed) for parsed in recommendation_dates}):
        errors.append("mismatch:payload:week_count")
    if recommendation_statuses:
        expected_payload_status = (
            "sufficient"
            if all(status == "sufficient" for status in recommendation_statuses)
            else "insufficient"
            if all(status == "insufficient" for status in recommendation_statuses)
            else "partial"
        )
        if payload.get("data_sufficiency") != expected_payload_status:
            errors.append("invalid:payload:data_sufficiency_relationship")
    return list(dict.fromkeys(errors))


__all__ = ["derive_dynamic_quotas", "validate_quota_plan"]
