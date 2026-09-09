from __future__ import annotations

from typing import Any

import pytest

from article_group.v5.experiment import (
    assess_experiment,
    build_experiment_record,
    validate_experiment_record,
)


def _record() -> dict[str, Any]:
    return build_experiment_record(
        experiment_id="exp-001",
        run_id="run-001",
        topic_id="topic-001",
        topic_version=1,
        hypothesis="动作冲突提高点击",
        changed_variable="title_angle",
        controls=["topic", "length", "publish_window"],
        metrics=["ctr", "completion_rate"],
        design="same_topic_different_title",
        treatment_ids=["a-2"],
        control_ids=["a-1"],
        week_start="2026-09-07",
        generated_at="2026-09-09T10:00:00+08:00",
    )


def _observation(
    article_id: str,
    arm: str,
    *,
    platform: str = "toutiao",
    publish_window: str = "morning",
    distribution_conditions: str = "organic",
) -> dict[str, Any]:
    return {
        "article_id": article_id,
        "arm": arm,
        "topic_id": "topic-001",
        "topic_type": "film",
        "length": 1000,
        "platform": platform,
        "publish_window": publish_window,
        "distribution_conditions": distribution_conditions,
        "metrics": {"ctr": 0.10, "completion_rate": 0.50},
    }


def _same_topic_observations() -> list[dict[str, Any]]:
    return [
        _observation("a-1", "control"),
        _observation("a-2", "treatment"),
    ]


def _confounded_observations() -> list[dict[str, Any]]:
    return [
        _observation("a-1", "control", platform="wechat"),
        _observation("a-2", "treatment"),
    ]


def _controlled_observations() -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for index in range(1, 4):
        observations.append(_observation(f"c-{index}", "control"))
        observations.append(_observation(f"t-{index}", "treatment"))
    return observations


def _controlled_record() -> dict[str, Any]:
    return build_experiment_record(
        experiment_id="exp-001",
        run_id="run-001",
        topic_id="topic-001",
        topic_version=1,
        hypothesis="动作冲突提高点击",
        changed_variable="title_angle",
        controls=["topic", "length", "publish_window"],
        metrics=["ctr", "completion_rate"],
        design="same_topic_different_title",
        treatment_ids=["t-1", "t-2", "t-3"],
        control_ids=["c-1", "c-2", "c-3"],
        week_start="2026-09-07",
        generated_at="2026-09-09T10:00:00+08:00",
    )


def test_experiment_requires_one_changed_variable_and_controls() -> None:
    record = _record()

    assert validate_experiment_record(record) == []
    assert record["schema_version"] == "v5-experiment-record-v1"
    assert record["payload"]["publication_authorization"] == "not_authorized"


def test_experiment_validation_rejects_invalid_design_date_and_overlapping_arms() -> None:
    record = _record()
    payload = dict(record["payload"])
    payload.update(
        {
            "changed_variable": "",
            "controls": [],
            "metrics": [],
            "design": "not-a-design",
            "treatment_ids": ["same-id"],
            "control_ids": ["same-id"],
            "week_start": "2026-02-30",
        }
    )
    invalid = {**record, "payload": payload}

    errors = validate_experiment_record(invalid)

    assert "invalid:changed_variable" in errors
    assert "invalid:controls" in errors
    assert "invalid:metrics" in errors
    assert "invalid:design" in errors
    assert "invalid:week_start" in errors
    assert "overlap:treatment_control_ids" in errors


def test_experiment_validation_rejects_duplicate_ids_and_duplicate_controls() -> None:
    record = _controlled_record()
    payload = dict(record["payload"])
    payload.update(
        {
            "treatment_ids": ["t-1", "t-1", "t-2"],
            "control_ids": ["c-1", "c-2", "c-2"],
            "controls": ["topic", "topic"],
        }
    )

    errors = validate_experiment_record({**record, "payload": payload})

    assert "duplicate:treatment_ids" in errors
    assert "duplicate:control_ids" in errors
    assert "duplicate:controls" in errors


def test_experiment_validation_rejects_changed_variable_as_a_control() -> None:
    record = _record()
    payload = dict(record["payload"])
    payload["controls"] = ["topic", "title_angle"]

    errors = validate_experiment_record({**record, "payload": payload})

    assert "overlap:changed_variable_controls" in errors


def test_observations_do_not_become_causal_without_controlled_confirmation() -> None:
    result = assess_experiment(_record(), _same_topic_observations())

    assert result["attribution_status"] == "observational"
    assert result["causal_claims"] == []
    assert not isinstance(result["causal_claims"], bool)


def test_confounding_is_reported_when_platform_and_window_change() -> None:
    result = assess_experiment(_record(), _confounded_observations())

    assert result["attribution_status"] == "confounded"
    assert "platform" in result["confounders"]


def test_supported_under_design_requires_three_per_arm_and_controller_approval() -> None:
    result = assess_experiment(
        _controlled_record(),
        _controlled_observations(),
        controller_decision="approve_causal_support",
    )

    assert result["attribution_status"] == "supported_under_design"
    assert result["observations_per_arm"] == {"control": 3, "treatment": 3}
    assert result["causal_claims"] == []


def test_causal_support_is_not_granted_without_controller_approval() -> None:
    result = assess_experiment(_controlled_record(), _controlled_observations())

    assert result["attribution_status"] == "observational"
    assert result["causal_claims"] == []


def test_unknown_observation_ids_do_not_bypass_declared_experiment_arms() -> None:
    observations = [
        _observation("unknown-control", "control"),
        _observation("unknown-treatment", "treatment"),
    ]

    result = assess_experiment(_record(), observations)

    assert result["attribution_status"] == "inconclusive"
    assert result["observations_per_arm"] == {"control": 0, "treatment": 0}


def test_observations_without_ids_do_not_fall_back_to_arm_labels() -> None:
    observations = [_observation("a-1", "control"), _observation("a-2", "treatment")]
    for observation in observations:
        observation.pop("article_id")

    result = assess_experiment(_record(), observations)

    assert result["attribution_status"] == "inconclusive"
    assert result["observations_per_arm"] == {"control": 0, "treatment": 0}


def test_duplicate_observation_ids_do_not_count_as_unique_samples() -> None:
    observations: list[dict[str, Any]] = []
    for arm, observation_id in (("control", "c-1"), ("treatment", "t-1")):
        observations.extend(
            [_observation(observation_id, arm) for _ in range(3)]
        )

    result = assess_experiment(
        _controlled_record(),
        observations,
        controller_decision="approve_causal_support",
    )

    assert result["attribution_status"] == "inconclusive"
    assert result["observations_per_arm"] == {"control": 0, "treatment": 0}


def test_declared_control_difference_is_reported_as_confounding() -> None:
    observations = _controlled_observations()
    observations[0]["length"] = 900

    result = assess_experiment(
        _controlled_record(),
        observations,
        controller_decision="approve_causal_support",
    )

    assert result["attribution_status"] == "confounded"
    assert "length" in result["confounders"]


def test_missing_declared_control_does_not_support_causal_attribution() -> None:
    observations = _controlled_observations()
    observations[0].pop("length")

    result = assess_experiment(
        _controlled_record(),
        observations,
        controller_decision="approve_causal_support",
    )

    assert result["attribution_status"] == "observational"
    assert result["observations_per_arm"] == {"control": 3, "treatment": 3}


@pytest.mark.parametrize(
    ("field", "values"),
    [
        ("platform", ["toutiao", "wechat", "bilibili"]),
        ("publish_window", ["morning", "noon", "evening"]),
        ("distribution_conditions", ["organic", "paid", "boosted"]),
        ("topic_type", ["film", "series", "documentary"]),
    ],
)
def test_within_arm_mixing_is_confounding_even_when_value_sets_match(
    field: str, values: list[str]
) -> None:
    observations: list[dict[str, Any]] = []
    for index, value in enumerate(values, start=1):
        control = _observation(f"c-{index}", "control")
        treatment = _observation(f"t-{index}", "treatment")
        control[field] = value
        treatment[field] = value
        observations.extend((control, treatment))

    result = assess_experiment(
        _controlled_record(),
        observations,
        controller_decision="approve_causal_support",
    )

    assert result["attribution_status"] == "confounded"
    assert field in result["confounders"]


def test_record_level_window_and_distribution_constraints_must_match_observations() -> None:
    record = build_experiment_record(
        experiment_id="exp-001",
        run_id="run-001",
        topic_id="topic-001",
        topic_version=1,
        hypothesis="动作冲突提高点击",
        changed_variable="title_angle",
        controls=["topic", "length", "publish_window"],
        metrics=["ctr", "completion_rate"],
        design="same_topic_different_title",
        treatment_ids=["t-1", "t-2", "t-3"],
        control_ids=["c-1", "c-2", "c-3"],
        week_start="2026-09-07",
        generated_at="2026-09-09T10:00:00+08:00",
        fixed_publish_window={"label": "morning"},
        distribution_conditions={"mode": "organic"},
    )
    observations = _controlled_observations()
    for observation in observations:
        observation["publish_window"] = {"label": "evening"}
        observation["distribution_conditions"] = {"mode": "paid"}

    result = assess_experiment(
        record,
        observations,
        controller_decision="approve_causal_support",
    )

    assert result["attribution_status"] == "confounded"
    assert "publish_window" in result["confounders"]
    assert "distribution_conditions" in result["confounders"]


def test_two_unique_observations_per_arm_cannot_be_supported() -> None:
    record = build_experiment_record(
        experiment_id="exp-001",
        run_id="run-001",
        topic_id="topic-001",
        topic_version=1,
        hypothesis="动作冲突提高点击",
        changed_variable="title_angle",
        controls=["topic", "length", "publish_window"],
        metrics=["ctr", "completion_rate"],
        design="same_topic_different_title",
        treatment_ids=["t-1", "t-2"],
        control_ids=["c-1", "c-2"],
        week_start="2026-09-07",
        generated_at="2026-09-09T10:00:00+08:00",
    )
    observations = [
        _observation("c-1", "control"),
        _observation("c-2", "control"),
        _observation("t-1", "treatment"),
        _observation("t-2", "treatment"),
    ]

    result = assess_experiment(
        record,
        observations,
        controller_decision="approve_causal_support",
    )

    assert result["attribution_status"] == "observational"
    assert result["observations_per_arm"] == {"control": 2, "treatment": 2}
