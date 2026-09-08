from __future__ import annotations

from article_group.v4.contracts import validate_artifact_envelope
from article_group.v4.effect_feedback import (
    aggregate_effects,
    advance_pattern_lifecycle,
    validate_metric_event,
)


RUN_ID = "run-effect-1"
GENERATED_AT = "2026-09-08T10:00:00+08:00"
GROUP_KEYS = ("topic_family", "title_angle", "structure_signature", "platform")
METRICS = (
    "impressions",
    "reads",
    "ctr",
    "completion_rate",
    "read_time_seconds",
    "likes",
    "comments",
    "favorites",
    "shares",
    "revenue",
    "rpm",
)


def _event(
    article_id: str = "article-1",
    *,
    day: int = 1,
    topic_family: str = "family-a",
    title_angle: str = "angle-a",
    structure_signature: str = "structure-a",
    platform: str = "toutiao",
    **overrides: object,
) -> dict[str, object]:
    event: dict[str, object] = {
        "article_id": article_id,
        "published_at": f"2026-09-{day:02d}T10:00:00+08:00",
        "platform": platform,
        "topic_family": topic_family,
        "title_angle": title_angle,
        "structure_signature": structure_signature,
        "impressions": 1000,
        "reads": 100,
        "ctr": 0.10,
        "completion_rate": 0.50,
        "read_time_seconds": 60,
        "likes": 10,
        "comments": 2,
        "favorites": 3,
        "shares": 4,
        "revenue": 1.5,
        "rpm": 15.0,
        "baseline": {"reference_id": "baseline-toutiao", "ctr": 0.08},
    }
    for metric in METRICS:
        event[f"{metric}_status"] = "available"
    event.update(overrides)
    return event


def _three_valid_events() -> list[dict[str, object]]:
    return [
        _event("article-1", day=1, impressions=1000, reads=100, ctr=0.10),
        _event("article-2", day=1, impressions=2000, reads=200, ctr=0.20),
        _event("article-3", day=2, impressions=3000, reads=300, ctr=0.30),
    ]


def _adopted_pattern() -> dict[str, object]:
    return {
        "pattern_id": "pattern-1",
        "state": "adopted",
        "run_id": RUN_ID,
        "generated_at": GENERATED_AT,
        "topic_family": "family-a",
        "title_angle": "angle-a",
        "structure_signature": "structure-a",
        "platform": "toutiao",
        "baseline": {"reference_id": "baseline-toutiao", "ctr": 0.08},
        "baseline_confirmed": True,
    }


def test_missing_platform_metric_is_unavailable_not_zero() -> None:
    event = _event(ctr=None, ctr_status="unavailable")

    assert validate_metric_event(event) == []
    assert event["ctr"] is None
    assert validate_metric_event(_event(ctr=0, ctr_status="unavailable"))


def test_metric_event_rejects_missing_identity_and_platform() -> None:
    event = _event(article_id="", platform="")
    event.pop("published_at")

    errors = validate_metric_event(event)

    assert errors == [
        "missing:article_id",
        "missing:published_at",
        "missing:platform",
    ]


def test_metric_event_rejects_negative_values_and_out_of_range_rates() -> None:
    event = _event(impressions=-1, ctr=1.01, completion_rate=-0.01)

    errors = validate_metric_event(event)

    assert "invalid:negative:impressions" in errors
    assert "invalid:rate:ctr" in errors
    assert "invalid:rate:completion_rate" in errors


def test_metric_event_rejects_future_timestamp() -> None:
    event = _event(published_at="2099-01-01T00:00:00Z")

    assert validate_metric_event(event) == ["future:published_at"]


def test_metric_event_rejects_unavailable_metric_with_zero_filled_value() -> None:
    event = _event(revenue=0, revenue_status="unavailable")

    assert "invalid:unavailable_value:revenue" in validate_metric_event(event)


def test_metric_event_rejects_nonfinite_and_boolean_metrics() -> None:
    event = _event(impressions=True, ctr=float("nan"))

    errors = validate_metric_event(event)

    assert "invalid:metric:impressions" in errors
    assert "invalid:metric:ctr" in errors


def test_null_metric_requires_an_explicit_unavailable_status() -> None:
    event = _event(ctr=None)
    event.pop("ctr_status")

    assert "missing:metric_status:ctr" in validate_metric_event(event)


def test_aggregate_effects_uses_medians_and_retains_availability_and_baseline() -> None:
    events = _three_valid_events()
    events[0]["ctr"] = None
    events[0]["ctr_status"] = "unavailable"

    rows = aggregate_effects(events, group_by=GROUP_KEYS)

    assert len(rows) == 1
    row = rows[0]
    assert row["group"] == {
        "topic_family": "family-a",
        "title_angle": "angle-a",
        "structure_signature": "structure-a",
        "platform": "toutiao",
    }
    assert row["sample_count"] == 3
    assert row["distinct_published_dates"] == 2
    assert row["available_metric_count"]["ctr"] == 2
    assert row["statistics"]["impressions"]["median"] == 2000
    assert row["statistics"]["ctr"]["median"] == 0.25
    assert row["statistics"]["ctr"]["available_count"] == 2
    assert row["baseline"] == {"reference_id": "baseline-toutiao", "ctr": 0.08}


def test_aggregate_effects_is_stable_and_rejects_malformed_groups() -> None:
    events = [
        _event("article-b", topic_family="family-b"),
        _event("article-a", topic_family="family-a"),
    ]

    first = aggregate_effects(events, group_by=("topic_family", "platform"))
    second = aggregate_effects(list(reversed(events)), group_by=("topic_family", "platform"))

    assert first == second
    assert [row["group"]["topic_family"] for row in first] == ["family-a", "family-b"]
    assert aggregate_effects(events, group_by=("unknown",)) == []
    assert aggregate_effects([_event("bad", ctr=2)], group_by=("platform",)) == []


def test_adopted_pattern_reaches_validated_only_with_sample_date_and_baseline_evidence() -> None:
    result = advance_pattern_lifecycle(_adopted_pattern(), _three_valid_events())

    assert result["state"] == "validated"
    assert result["reusable"] is False
    assert result["sample_count"] == 3
    assert result["distinct_published_dates"] == 2
    assert result["validation"]["baseline_confirmed"] is True


def test_fewer_than_three_distinct_published_articles_stops_at_measured() -> None:
    result = advance_pattern_lifecycle(_adopted_pattern(), _three_valid_events()[:2])

    assert result["state"] == "measured"
    assert result["validation"]["sample_requirement_met"] is False
    assert result["validation"]["validated"] is False


def test_missing_core_metric_stops_at_measured() -> None:
    events = _three_valid_events()
    events[0]["completion_rate"] = None
    events[0]["completion_rate_status"] = "unavailable"

    result = advance_pattern_lifecycle(_adopted_pattern(), events)

    assert result["state"] == "measured"
    assert result["validation"]["core_metrics_complete"] is False
    assert result["validation"]["validated"] is False


def test_missing_baseline_confirmation_stops_at_measured() -> None:
    pattern = _adopted_pattern()
    pattern.pop("baseline_confirmed")

    result = advance_pattern_lifecycle(pattern, _three_valid_events())

    assert result["state"] == "measured"
    assert result["reusable"] is False
    assert "missing:baseline_confirmation" in result["errors"]


def test_validated_pattern_requires_explicit_controller_approval_for_reuse() -> None:
    validated = advance_pattern_lifecycle(
        _adopted_pattern(), _three_valid_events(), controller_decision="approve_reuse"
    )

    assert validated["state"] == "reusable_pattern"
    assert validated["reusable"] is True
    assert validated["controller_decision"] == "approve_reuse"


def test_candidate_can_only_be_adopted_by_an_explicit_adoption_decision() -> None:
    pattern = _adopted_pattern()
    pattern["state"] = "candidate"

    held = advance_pattern_lifecycle(pattern, [])
    adopted = advance_pattern_lifecycle(pattern, [], controller_decision="adopt")

    assert held["state"] == "candidate"
    assert adopted["state"] == "adopted"


def test_enveloped_lifecycle_result_is_closed_and_keeps_publication_unauthorized() -> None:
    pattern = {
        "schema_version": "v4-effect-feedback-v1",
        "run_id": RUN_ID,
        "generated_at": GENERATED_AT,
        "input_hashes": {"pattern": "a" * 64},
        "payload": _adopted_pattern(),
    }

    result = advance_pattern_lifecycle(pattern, _three_valid_events())

    assert set(result) == {
        "schema_version",
        "run_id",
        "generated_at",
        "input_hashes",
        "payload",
    }
    assert validate_artifact_envelope(
        result, "v4-effect-feedback-v1", run_id=RUN_ID
    ) == []
    assert result["payload"]["state"] == "validated"
    assert result["payload"]["publication_authorization"] == "not_authorized"
    assert "metric_events" in result["input_hashes"]


def test_malformed_lifecycle_input_fails_closed_without_fabricating_validation() -> None:
    result = advance_pattern_lifecycle({"state": "adopted"}, [_event("article-1")])

    assert result["state"] == "adopted"
    assert result["reusable"] is False
    assert result["errors"]
    assert result["validation"]["validated"] is False


def test_unhashable_controller_and_metric_status_inputs_fail_closed() -> None:
    controller_result = advance_pattern_lifecycle(
        _adopted_pattern(), _three_valid_events(), controller_decision=[]  # type: ignore[arg-type]
    )
    event = _event(metric_status={1: "available", "ctr": "available"})

    assert controller_result["reusable"] is False
    assert "invalid:controller_decision" in controller_result["errors"]
    assert validate_metric_event(event)
