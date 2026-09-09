from __future__ import annotations

from copy import deepcopy

import pytest

from article_group.editorial_pipeline_v3 import (
    validate_v5_transition_context as v3_validate_v5_transition_context,
)
from article_group.v5.experiment import (
    build_experiment_record,
)
from article_group.v5.integration import validate_v5_transition_context
from article_group.v5.resources import (
    plan_resource_allocation,
    validate_resource_plan,
)


RUN_ID = "run-resources-001"
GENERATED_AT = "2026-09-09T10:00:00+08:00"


def _candidates() -> list[dict[str, object]]:
    return [
        {
            "candidate_id": "high-ready",
            "value_score": 0.90,
            "evidence_readiness": 0.90,
            "potential_score": 0.50,
            "controversy_score": 0.10,
            "risk_score": 0.10,
        },
        {
            "candidate_id": "high-low-readiness",
            "value_score": 0.90,
            "evidence_readiness": 0.20,
            "potential_score": 0.50,
            "controversy_score": 0.10,
            "risk_score": 0.10,
        },
        {
            "candidate_id": "high-risk-low-value",
            "value_score": 0.20,
            "evidence_readiness": 0.90,
            "potential_score": 0.20,
            "controversy_score": 0.40,
            "risk_score": 0.90,
        },
        {
            "candidate_id": "controversial-potential",
            "value_score": 0.60,
            "evidence_readiness": 0.40,
            "potential_score": 0.90,
            "controversy_score": 0.90,
            "risk_score": 0.60,
        },
        {
            "candidate_id": "ordinary",
            "value_score": 0.50,
            "evidence_readiness": 0.50,
            "potential_score": 0.40,
            "controversy_score": 0.20,
            "risk_score": 0.20,
        },
    ]


def _experiment() -> dict[str, object]:
    return build_experiment_record(
        experiment_id="experiment-001",
        run_id=RUN_ID,
        topic_id="topic-001",
        topic_version=1,
        hypothesis="具体人物动作提高点击",
        changed_variable="title_angle",
        controls=["topic", "publish_window", "platform_distribution"],
        metrics=["ctr", "completion_rate"],
        design="controlled",
        treatment_ids=["article-t"],
        control_ids=["article-c"],
        week_start="2026-09-07",
        generated_at=GENERATED_AT,
        fixed_publish_window={"start": "18:00", "end": "20:00"},
        distribution_conditions={"platform": "fixture", "account_state": "stable"},
    )


def test_resource_tiers_follow_value_readiness_and_risk() -> None:
    plan = plan_resource_allocation(
        _candidates(), budget=20, run_id=RUN_ID, generated_at=GENERATED_AT
    )
    actions = {
        item["candidate_id"]: item["action"]
        for item in plan["payload"]["allocations"]
    }

    assert actions["high-ready"] == "full_capture"
    assert actions["high-low-readiness"] == "evidence_recovery"
    assert actions["high-risk-low-value"] == "stop"
    assert actions["controversial-potential"] == "sol_review"
    assert actions["ordinary"] == "light_capture"
    assert validate_resource_plan(plan) == []

    for allocation in plan["payload"]["allocations"]:
        assert {"owner", "estimated_cost", "reason", "controller_review_required", "auto_apply"} <= set(allocation)
        assert allocation["auto_apply"] is False
    assert plan["payload"]["publication_authorization"] == "not_authorized"


def test_resource_plan_is_bounded_and_rejects_invalid_inputs() -> None:
    plan = plan_resource_allocation(
        _candidates(), budget=1, run_id=RUN_ID, generated_at=GENERATED_AT
    )
    assert plan["payload"]["total_allocated_cost"] <= 1
    assert validate_resource_plan(plan) == []

    invalid = deepcopy(plan)
    invalid["payload"]["allocations"][0]["auto_apply"] = True
    assert "auto_apply_must_be_false" in validate_resource_plan(invalid)

    with pytest.raises(ValueError, match="duplicate_candidate_id"):
        plan_resource_allocation(
            [_candidates()[0], _candidates()[0]],
            budget=20,
            run_id=RUN_ID,
            generated_at=GENERATED_AT,
        )


def test_research_gate_requires_article_group_experiment_and_non_stop_plan() -> None:
    errors = validate_v5_transition_context(
        "approved",
        "researching",
        experiment_record=None,
        resource_plan=None,
    )
    assert "missing:v5_experiment" in errors
    assert "missing:v5_resource_plan" in errors

    stop_plan = plan_resource_allocation(
        [_candidates()[2]], budget=20, run_id=RUN_ID, generated_at=GENERATED_AT
    )
    errors = validate_v5_transition_context(
        "approved",
        "researching",
        experiment_record=_experiment(),
        resource_plan=stop_plan,
    )
    assert "v5_resource_plan_contains_stop" in errors

    good_plan = plan_resource_allocation(
        [_candidates()[0]], budget=20, run_id=RUN_ID, generated_at=GENERATED_AT
    )
    assert validate_v5_transition_context(
        "approved",
        "researching",
        experiment_record=_experiment(),
        resource_plan=good_plan,
    ) == []


def test_writing_gate_surfaces_archived_retired_and_failure_blockers() -> None:
    errors = validate_v5_transition_context(
        "material_ready",
        "writing",
        lifecycle_record={"payload": {"state": "archived"}},
        strategy_library={
            "payload": {"strategies": [{"payload": {"state": "retired"}}]}
        },
        failure_report={
            "payload": {
                "samples": [
                    {"categories": ["insufficient_data"]},
                    {"categories": ["good_data_high_risk"]},
                ]
            }
        },
    )

    assert "v5_lifecycle_archived" in errors
    assert "v5_strategy_retired" in errors
    assert "v5_failure_insufficient_data" in errors
    assert "v5_failure_high_risk_requires_review" in errors


def test_v5_never_replaces_review_to_closed_or_grants_authorization() -> None:
    assert validate_v5_transition_context("review", "closed") == []
    assert v3_validate_v5_transition_context("review", "closed") == []

    errors = validate_v5_transition_context(
        "approved",
        "researching",
        experiment_record={"nested": {"publication_authorization": "authorized"}},
        resource_plan=None,
    )
    assert "publication_authorization_must_be_not_authorized" in errors


def test_v5_checks_v3_transition_before_context() -> None:
    errors = validate_v5_transition_context(
        "precheck",
        "researching",
        experiment_record=_experiment(),
        resource_plan=None,
    )
    assert errors == ["transition_not_allowed:precheck->researching"]
