from __future__ import annotations

from copy import deepcopy

from article_group.v5.quota import derive_dynamic_quotas, validate_quota_plan
from article_group.v5.strategy import (
    advance_strategy_state,
    build_strategy_library,
    build_strategy_record,
    validate_strategy_library,
)


RUN_ID = "run-quota-strategy-001"
GENERATED_AT = "2026-09-09T10:00:00+08:00"


def _history_row(
    sample_id: str,
    day: str,
    *,
    topic_type: str = "人物",
    completion_rate: float = 0.60,
    rpm: float = 12.0,
    risk_score: float = 0.10,
    failure_type: str | None = None,
    consecutive_failures: int = 0,
    usable: bool = True,
) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "date": day,
        "topic_type": topic_type,
        "completion_rate": completion_rate,
        "rpm": rpm,
        "risk_score": risk_score,
        "failure_type": failure_type,
        "consecutive_failures": consecutive_failures,
        "usable": usable,
    }


def _four_week_history() -> list[dict[str, object]]:
    return [
        _history_row("old", "2026-08-10", completion_rate=0.99, rpm=99.0),
        _history_row("w1", "2026-08-18", completion_rate=0.20, rpm=10.0),
        _history_row("w2", "2026-08-25", completion_rate=0.80, rpm=20.0),
        _history_row("w3", "2026-09-01", completion_rate=0.60, rpm=30.0),
        _history_row("w4", "2026-09-08", completion_rate=0.40, rpm=40.0),
    ]


def _testing_strategy() -> dict[str, object]:
    return build_strategy_record(
        strategy_id="strategy-001",
        version=1,
        run_id=RUN_ID,
        applicable_topic_types=["人物"],
        hypothesis="具体关系冲突提高完成率",
        evidence_samples=["seed-001"],
        success_conditions=["completion_rate >= 0.60"],
        failure_boundary=["risk_score >= 0.70"],
        last_validated_at="2026-09-08T10:00:00+08:00",
        state="testing",
        generated_at=GENERATED_AT,
    )


def _successful_correlations() -> list[dict[str, object]]:
    return [
        {"sample_id": "sample-1", "date": "2026-09-01", "usable": True, "correlation": True},
        {"sample_id": "sample-2", "date": "2026-09-02", "usable": True, "correlation": True},
        {"sample_id": "sample-3", "date": "2026-09-09", "usable": True, "correlation": True},
    ]


def _supported_evidence() -> list[dict[str, object]]:
    return [
        {"sample_id": "sample-1", "date": "2026-08-25", "usable": True, "outcome": "success"},
        {"sample_id": "sample-2", "date": "2026-08-26", "usable": True, "outcome": "success"},
        {"sample_id": "sample-3", "date": "2026-09-08", "usable": True, "outcome": "success"},
    ]


def test_quota_recommendation_is_clamped_and_not_auto_applied():
    plan = derive_dynamic_quotas(
        _four_week_history(),
        {"人物": {"share": 0.5}},
        run_id=RUN_ID,
        generated_at=GENERATED_AT,
    )

    recommendation = plan["payload"]["recommendations"][0]

    assert 0.05 <= recommendation["recommended_share"] <= 0.60
    assert plan["payload"]["auto_apply"] is False
    assert plan["payload"]["controller_only"] is True
    assert plan["payload"]["publication_authorization"] == "not_authorized"
    assert validate_quota_plan(plan) == []


def test_insufficient_history_keeps_baseline_and_exposes_reason():
    plan = derive_dynamic_quotas(
        [],
        {"新片": {"share": 0.4}},
        run_id=RUN_ID,
        generated_at=GENERATED_AT,
    )

    recommendation = plan["payload"]["recommendations"][0]

    assert recommendation["recommended_share"] == 0.4
    assert plan["payload"]["data_sufficiency"] == "insufficient"
    assert plan["payload"]["insufficiency_reasons"]
    assert "no_usable_history" in plan["payload"]["insufficiency_reasons"]
    assert validate_quota_plan(plan) == []


def test_quota_uses_only_latest_four_calendar_weeks_and_median_metrics():
    plan = derive_dynamic_quotas(
        _four_week_history(),
        {"人物": {"share": 0.5}},
        run_id=RUN_ID,
        generated_at=GENERATED_AT,
    )

    recommendation = plan["payload"]["recommendations"][0]

    assert recommendation["sample_count"] == 4
    assert recommendation["week_count"] == 4
    assert recommendation["medians"]["completion_rate"] == 0.50
    assert recommendation["medians"]["rpm"] == 25.0
    assert "2026-08-10" not in plan["payload"]["included_dates"]
    assert plan["payload"]["lookback_weeks"] == 4


def test_quota_uses_daily_topic_medians_before_cross_day_median():
    history = [
        _history_row("day-1-a", "2026-09-01", completion_rate=0.10),
        _history_row("day-1-b", "2026-09-01", completion_rate=0.10),
        _history_row("day-1-c", "2026-09-01", completion_rate=0.10),
        _history_row("day-2", "2026-09-02", completion_rate=0.90),
        _history_row("day-3", "2026-09-08", completion_rate=0.50),
    ]

    plan = derive_dynamic_quotas(
        history,
        {"人物": {"share": 0.5}},
        run_id=RUN_ID,
        generated_at=GENERATED_AT,
    )

    assert plan["payload"]["recommendations"][0]["medians"]["completion_rate"] == 0.50


def test_quota_exposes_risk_cap_cooldown_and_failure_downweight():
    history = [
        _history_row(
            "risk-1",
            "2026-09-01",
            topic_type="争议",
            risk_score=0.90,
            failure_type="good_data_high_risk",
            consecutive_failures=3,
        ),
        _history_row(
            "risk-2",
            "2026-09-08",
            topic_type="争议",
            risk_score=0.85,
            failure_type="good_data_high_risk",
            consecutive_failures=2,
        ),
        _history_row(
            "risk-3",
            "2026-09-08",
            topic_type="争议",
            risk_score=0.80,
            failure_type="good_data_high_risk",
            consecutive_failures=1,
        ),
    ]

    plan = derive_dynamic_quotas(
        history,
        {"争议": {"share": 0.50, "cooldown_days": 5}},
        run_id=RUN_ID,
        generated_at=GENERATED_AT,
        high_risk_cap=0.20,
    )
    recommendation = plan["payload"]["recommendations"][0]

    assert recommendation["recommended_share"] <= 0.20
    assert recommendation["high_risk_cap"] == 0.20
    assert recommendation["cooldown_days"] >= 5
    assert 0 < recommendation["consecutive_failure_downweight"] < 1
    assert recommendation["risk_level"] == "high"
    assert recommendation["failure_counts"]["good_data_high_risk"] == 3


def test_quota_exposes_explicit_bound_and_floor_fields_from_history_risk():
    history = [
        _history_row("high-1", "2026-09-01", risk_score=0.80),
        _history_row("high-2", "2026-09-02", risk_score=0.80),
        _history_row("high-3", "2026-09-08", risk_score=0.80),
    ]
    for row in history:
        row.pop("risk_score")
        row["risk_level"] = "high"

    plan = derive_dynamic_quotas(
        history,
        {"人物": {"share": 0.5}},
        run_id=RUN_ID,
        generated_at=GENERATED_AT,
    )
    recommendation = plan["payload"]["recommendations"][0]

    assert recommendation["min_share"] == 0.05
    assert recommendation["max_share"] == 0.60
    assert recommendation["completion_rate_floor"] == recommendation["completion_floor"]
    assert recommendation["failure_downweight"] == recommendation["consecutive_failure_downweight"]
    assert recommendation["risk_level"] == "high"


def test_quota_detects_boolean_high_risk_and_trailing_failures_without_precomputed_count():
    history = [
        _history_row(
            "fail-1",
            "2026-09-01",
            failure_type="click_low_completion",
        ),
        _history_row(
            "fail-2",
            "2026-09-02",
            failure_type="click_low_completion",
        ),
        _history_row(
            "fail-3",
            "2026-09-08",
            failure_type="click_low_completion",
        ),
    ]
    for row in history:
        row.pop("risk_score")
        row.pop("consecutive_failures")
        row["high_risk"] = True

    plan = derive_dynamic_quotas(
        history,
        {"人物": {"share": 0.5}},
        run_id=RUN_ID,
        generated_at=GENERATED_AT,
    )
    recommendation = plan["payload"]["recommendations"][0]

    assert recommendation["risk_level"] == "high"
    assert recommendation["consecutive_failures"] == 3
    assert recommendation["consecutive_failure_downweight"] == 0.7


def test_quota_validation_rejects_controller_boundary_mutation():
    plan = derive_dynamic_quotas(
        _four_week_history(),
        {"人物": {"share": 0.5}},
        run_id=RUN_ID,
        generated_at=GENERATED_AT,
    )
    invalid = deepcopy(plan)
    invalid["payload"]["auto_apply"] = True
    invalid["payload"]["recommendations"][0]["recommended_share"] = 0.90

    errors = validate_quota_plan(invalid)

    assert "auto_apply_must_be_false" in errors
    assert "invalid:recommendation:0:recommended_share" in errors


def test_quota_validation_checks_recommendation_bounds_and_positive_requirements():
    plan = derive_dynamic_quotas(
        _four_week_history(),
        {"人物": {"share": 0.5}},
        run_id=RUN_ID,
        generated_at=GENERATED_AT,
    )
    invalid = deepcopy(plan)
    invalid["payload"]["recommendations"][0]["min_samples"] = 0
    invalid["payload"]["recommendations"][0]["share_bounds"] = {
        "min": 0.90,
        "max": 0.95,
    }

    errors = validate_quota_plan(invalid)

    assert "invalid:recommendation:0:min_samples" in errors
    assert "invalid:recommendation:0:share_bounds" in errors


def test_strategy_record_has_complete_fields_and_validates_through_library():
    strategy = _testing_strategy()
    library = build_strategy_library([strategy], run_id=RUN_ID, generated_at=GENERATED_AT)

    payload = strategy["payload"]
    assert set(
        (
            "strategy_id",
            "version",
            "applicable_topic_types",
            "hypothesis",
            "evidence_samples",
            "success_conditions",
            "failure_boundary",
            "last_validated_at",
            "state",
        )
    ) <= set(payload)
    assert payload["auto_apply"] is False
    assert payload["controller_only"] is True
    assert validate_strategy_library(library) == []


def test_strategy_cannot_become_supported_from_correlation_alone():
    result = advance_strategy_state(_testing_strategy(), _successful_correlations())

    assert result["payload"]["state"] == "testing"
    assert result["payload"]["recommended_state"] == "supported"
    assert result["payload"]["evidence_summary"]["usable_sample_count"] == 3
    assert result["payload"]["evidence_summary"]["week_count"] >= 2


def test_controller_approval_and_cross_week_samples_support_strategy():
    result = advance_strategy_state(
        _testing_strategy(),
        _supported_evidence(),
        controller_decision="approve_support",
    )

    assert result["payload"]["state"] == "supported"
    assert result["payload"]["controller_decision"] == "approve_support"
    assert result["payload"]["transition"]["from"] == "testing"
    assert result["payload"]["transition"]["to"] == "supported"


def test_strategy_state_changes_require_explicit_controller_decisions():
    provisional = build_strategy_record(
        strategy_id="strategy-002",
        version=1,
        run_id=RUN_ID,
        applicable_topic_types=["作品"],
        hypothesis="具体场景提高互动",
        evidence_samples=[],
        success_conditions=["interaction_rate >= 0.08"],
        failure_boundary=["risk_score >= 0.70"],
        last_validated_at="2026-09-08T10:00:00+08:00",
        generated_at=GENERATED_AT,
    )

    held = advance_strategy_state(provisional, [])
    testing = advance_strategy_state(provisional, [], controller_decision="start_testing")
    held_supported = advance_strategy_state(
        {**testing, "payload": {**testing["payload"], "state": "testing"}},
        _supported_evidence(),
    )

    assert held["payload"]["state"] == "provisional"
    assert testing["payload"]["state"] == "testing"
    assert held_supported["payload"]["state"] == "testing"
    assert held_supported["payload"]["recommended_state"] == "supported"


def test_start_testing_explicitly_updates_recommended_state():
    provisional = build_strategy_record(
        strategy_id="strategy-003",
        version=1,
        run_id=RUN_ID,
        applicable_topic_types=["文化现象"],
        hypothesis="具体冲突提高讨论",
        evidence_samples=[],
        success_conditions=["comments >= 10"],
        failure_boundary=["risk_score >= 0.70"],
        last_validated_at="2026-09-08T10:00:00+08:00",
        generated_at=GENERATED_AT,
    )

    result = advance_strategy_state(
        provisional,
        [],
        controller_decision="start_testing",
    )

    assert result["payload"]["state"] == "testing"
    assert result["payload"]["recommended_state"] == "testing"


def test_strategy_support_requires_three_usable_samples_across_two_weeks():
    evidence = _supported_evidence()
    evidence[-1]["usable"] = False
    evidence[-1]["unusable_reason"] = "missing_completion_rate"

    result = advance_strategy_state(
        _testing_strategy(), evidence, controller_decision="approve_support"
    )

    assert result["payload"]["state"] == "testing"
    assert result["payload"]["recommended_state"] == "testing"
    assert "insufficient_usable_evidence" in result["payload"]["blockers"]


def test_strategy_rejects_ambiguous_evidence_identity():
    evidence = _supported_evidence()
    evidence[0]["article_id"] = "article-1"

    result = advance_strategy_state(
        _testing_strategy(), evidence, controller_decision="approve_support"
    )

    assert result["payload"]["state"] == "testing"
    assert "missing:evidence:0:sample_id" in result["payload"]["errors"]


def test_strategy_library_rejects_duplicate_versions_and_authorization_escalation():
    strategy = _testing_strategy()
    library = build_strategy_library(
        [strategy, deepcopy(strategy)], run_id=RUN_ID, generated_at=GENERATED_AT
    )
    library["payload"]["strategies"][0]["payload"]["publication_authorization"] = (
        "authorized"
    )

    errors = validate_strategy_library(library)

    assert "duplicate:strategy:strategy-001:1" in errors
    assert "publication_authorization_must_be_not_authorized" in errors
