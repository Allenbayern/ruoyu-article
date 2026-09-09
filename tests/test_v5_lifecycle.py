from __future__ import annotations

from typing import Any

import pytest

from article_group.v5.lifecycle import (
    build_content_lifecycle,
    advance_content_lifecycle,
    validate_lifecycle_record,
)


RUN_ID = "run-lifecycle-001"
GENERATED_AT = "2026-09-09T10:00:00+08:00"
ARTICLE_ID = "article-001"


def _record(state: str = "draft") -> dict[str, Any]:
    return build_content_lifecycle(
        article_id=ARTICLE_ID,
        run_id=RUN_ID,
        generated_at=GENERATED_AT,
        state=state,
    )


def _draft() -> dict[str, Any]:
    return _record("draft")


def _published() -> dict[str, Any]:
    result = advance_content_lifecycle(_draft(), [_publication_event()])
    assert result["payload"]["state"] == "published"
    return result


def _publication_event(**overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "event_type": "published",
        "article_id": ARTICLE_ID,
        "published_at": "2026-09-09T09:00:00+08:00",
        "platform": "toutiao",
        "event_id": "publication-001",
    }
    event.update(overrides)
    return event


def _observation(trend: str, evidence_ref: str) -> dict[str, object]:
    event: dict[str, object] = {
        "event_type": "observation",
        "article_id": ARTICLE_ID,
        "observed_at": "2026-09-09T12:00:00+08:00",
        "trend": trend,
        "evidence_ref": evidence_ref,
        "metrics": {
            "window": {
                "start": "2026-09-09T09:00:00+08:00",
                "end": "2026-09-09T12:00:00+08:00",
            },
            "impressions": 1000,
            "clicks": 100,
        },
    }
    return event


def _observation_window() -> dict[str, object]:
    return {
        "start": "2026-09-09T09:00:00+08:00",
        "end": "2026-09-09T12:00:00+08:00",
    }


def _rising_events() -> list[dict[str, object]]:
    return [_observation("rising", "metrics/rising-001.json")]


def _stable_events() -> list[dict[str, object]]:
    return [_observation("stable", "metrics/stable-001.json")]


def test_draft_cannot_become_published_without_external_publication_event():
    result = advance_content_lifecycle(_draft(), [])

    assert result["payload"]["state"] == "draft"
    assert "publication_event_required" in result["payload"]["blockers"]


def test_draft_becomes_published_only_with_complete_external_publication_event():
    result = advance_content_lifecycle(_draft(), [_publication_event()])

    assert result["payload"]["state"] == "published"
    assert result["payload"]["evidence_refs"] == ["publication-001"]
    assert result["payload"]["publication_authorization"] == "not_authorized"
    assert validate_lifecycle_record(result) == []


@pytest.mark.parametrize(
    "missing",
    ["article_id", "published_at", "platform"],
)
def test_incomplete_publication_event_cannot_publish_draft(missing: str):
    event = _publication_event()
    event.pop(missing)

    result = advance_content_lifecycle(_draft(), [event])

    assert result["payload"]["state"] == "draft"
    assert "publication_event_required" in result["payload"]["blockers"]


@pytest.mark.parametrize("published_at", ["not-a-time", "2026-02-30T09:00:00+08:00"])
def test_publication_event_requires_legal_rfc3339_timestamp(published_at: str):
    result = advance_content_lifecycle(
        _draft(), [_publication_event(published_at=published_at)]
    )

    assert result["payload"]["state"] == "draft"
    assert "publication_event_required" in result["payload"]["blockers"]


def test_publication_event_requires_explicit_reference_and_never_falls_back_to_index():
    event = _publication_event()
    event.pop("event_id")

    result = advance_content_lifecycle(_draft(), [event])

    assert result["payload"]["state"] == "draft"
    assert "publication_event_required" in result["payload"]["blockers"]
    assert result["payload"]["evidence_refs"] == []
    assert not any(
        reference.startswith("event:")
        for reference in result["payload"]["evidence_refs"]
    )


def test_publication_event_accepts_evidence_ref_as_explicit_reference():
    event = _publication_event()
    event.pop("event_id")
    event["evidence_ref"] = "publication/toutiao/article-001.json"

    result = advance_content_lifecycle(_draft(), [event])

    assert result["payload"]["state"] == "published"
    assert result["payload"]["evidence_refs"] == [
        "publication/toutiao/article-001.json"
    ]


def test_publication_event_must_match_the_lifecycle_article():
    result = advance_content_lifecycle(
        _draft(), [_publication_event(article_id="article-999")]
    )

    assert result["payload"]["state"] == "draft"
    assert result["payload"]["evidence_refs"] == []


def test_published_observation_can_become_rising_but_evergreen_needs_controller():
    rising = advance_content_lifecycle(_published(), _rising_events())

    assert rising["payload"]["state"] == "rising"
    assert rising["payload"]["evidence_refs"] == [
        "publication-001",
        "metrics/rising-001.json",
    ]

    evergreen = advance_content_lifecycle(
        rising, _stable_events(), controller_decision="approve_evergreen"
    )

    assert evergreen["payload"]["state"] == "evergreen"
    assert evergreen["payload"]["publication_authorization"] == "not_authorized"
    assert validate_lifecycle_record(evergreen) == []


def test_evergreen_is_not_derived_from_observations_without_controller():
    result = advance_content_lifecycle(_published(), _stable_events())

    assert result["payload"]["state"] == "stable"
    assert result["payload"]["state"] != "evergreen"


def test_archived_content_has_learning_only_action():
    result = advance_content_lifecycle(
        _published(), [], controller_decision="archive"
    )

    assert result["payload"]["state"] == "archived"
    assert result["payload"]["next_action"] == "retain_learning_only"
    assert validate_lifecycle_record(result) == []


@pytest.mark.parametrize(
    ("target_state", "trend"),
    [
        ("observing", ""),
        ("stable", "stable"),
        ("rising", "rising"),
        ("decaying", "decaying"),
    ],
)
@pytest.mark.parametrize(
    "invalid_field",
    ["article_id", "observed_at", "evidence_ref", "metrics"],
)
def test_each_observation_state_requires_complete_evidence(
    target_state: str, trend: str, invalid_field: str
):
    event = _observation(trend, f"metrics/{target_state}-001.json")
    if target_state == "observing":
        event.pop("trend")
    event.pop(invalid_field)

    result = advance_content_lifecycle(_published(), [event])

    assert result["payload"]["state"] == "published"
    assert result["payload"]["state"] != target_state
    assert not any(
        reference.startswith("event:")
        for reference in result["payload"]["evidence_refs"]
    )


def test_observation_timestamp_alias_is_supported_when_it_is_legal_rfc3339():
    event = _observation("rising", "metrics/rising-timestamp-001.json")
    event.pop("observed_at")
    event["timestamp"] = "2026-09-09T12:00:00+08:00"

    result = advance_content_lifecycle(_published(), [event])

    assert result["payload"]["state"] == "rising"


@pytest.mark.parametrize(
    "timestamp_field",
    ["observed_at", "timestamp"],
)
def test_observation_requires_legal_rfc3339_timestamp(timestamp_field: str):
    event = _observation("rising", "metrics/rising-invalid-time.json")
    if timestamp_field == "timestamp":
        event.pop("observed_at")
    event[timestamp_field] = "not-a-time"

    result = advance_content_lifecycle(_published(), [event])

    assert result["payload"]["state"] == "published"


def test_observation_requires_non_empty_metrics_or_window_record():
    event = _observation("stable", "metrics/stable-empty.json")
    event.pop("metrics")
    event["window"] = {}

    result = advance_content_lifecycle(_published(), [event])

    assert result["payload"]["state"] == "published"
    assert result["payload"]["evidence_refs"] == ["publication-001"]


def test_observation_accepts_a_non_empty_window_without_metrics():
    event = _observation("stable", "metrics/stable-window.json")
    event.pop("metrics")
    event["window"] = _observation_window()

    result = advance_content_lifecycle(_published(), [event])

    assert result["payload"]["state"] == "stable"


def test_observation_requires_explicit_reference_and_never_falls_back_to_index():
    event = _observation("rising", "metrics/rising-no-ref.json")
    event.pop("evidence_ref")

    result = advance_content_lifecycle(_published(), [event])

    assert result["payload"]["state"] == "published"
    assert result["payload"]["evidence_refs"] == ["publication-001"]
    assert not any(
        reference.startswith("event:")
        for reference in result["payload"]["evidence_refs"]
    )


def test_observation_event_type_cannot_be_used_as_a_pseudo_trend():
    event = _observation("", "metrics/rising-pseudo.json")
    event["event_type"] = "rising"

    result = advance_content_lifecycle(_published(), [event])

    assert result["payload"]["state"] == "published"
    assert result["payload"]["evidence_refs"] == ["publication-001"]


def test_observation_trends_move_forward_and_do_not_regress_state():
    rising = advance_content_lifecycle(_published(), _rising_events())
    stable_after_rising = advance_content_lifecycle(rising, _stable_events())

    assert stable_after_rising["payload"]["state"] == "rising"
    assert "forward_only_transition" in stable_after_rising["payload"]["blockers"]


def test_archived_state_is_terminal_even_when_new_observations_arrive():
    archived = advance_content_lifecycle(
        _published(), [], controller_decision="archive"
    )
    result = advance_content_lifecycle(archived, _rising_events())

    assert result["payload"]["state"] == "archived"
    assert result["payload"]["next_action"] == "retain_learning_only"
    assert validate_lifecycle_record(result) == []


def test_published_record_remains_valid_when_no_new_event_arrives():
    result = advance_content_lifecycle(_published(), [])

    assert result["payload"]["state"] == "published"
    assert validate_lifecycle_record(result) == []


def test_lifecycle_validation_accepts_closed_record_and_rejects_unknown_state():
    record = _draft()

    assert validate_lifecycle_record(record) == []

    invalid = {**record, "payload": {**record["payload"], "state": "viral"}}
    assert "invalid:state" in validate_lifecycle_record(invalid)


@pytest.mark.parametrize("state", ["published", "evergreen", "archived"])
def test_builder_rejects_direct_construction_of_gated_states(state: str):
    with pytest.raises(ValueError, match="gated"):
        _record(state)


@pytest.mark.parametrize(
    ("state", "controller_key"),
    [("published", None), ("evergreen", "controller_decision"), ("archived", "controller_decision")],
)
def test_validator_rejects_gated_state_without_transition_evidence_or_controller(
    state: str, controller_key: str | None
):
    payload = dict(_draft()["payload"])
    payload["state"] = state
    payload["next_action"] = {
        "published": "record_observations",
        "evergreen": "consider_evergreen_candidate",
        "archived": "retain_learning_only",
    }[state]
    if controller_key is not None:
        payload.pop(controller_key, None)

    errors = validate_lifecycle_record({**_draft(), "payload": payload})

    assert "missing:transition" in errors
    assert "gated_state_requires_evidence" in errors
    if state in {"evergreen", "archived"}:
        assert "gated_state_requires_controller_decision" in errors


def test_validator_requires_next_action_to_match_state():
    invalid = {
        **_draft(),
        "payload": {
            **_draft()["payload"],
            "next_action": "publish_now",
        },
    }

    errors = validate_lifecycle_record(invalid)

    assert "next_action_state_mismatch" in errors


def test_validator_rejects_gated_transition_with_wrong_target_state():
    archived = advance_content_lifecycle(
        _published(), [], controller_decision="archive"
    )
    invalid = {
        **archived,
        "payload": {
            **archived["payload"],
            "transition": {
                **archived["payload"]["transition"],
                "to": "evergreen",
            },
        },
    }

    assert "invalid:transition" in validate_lifecycle_record(invalid)


def test_lifecycle_validation_rejects_authorization_escalation():
    record = _draft()
    invalid = {
        **record,
        "payload": {
            **record["payload"],
            "publication_authorization": "authorized",
        },
    }

    assert "publication_authorization_must_be_not_authorized" in (
        validate_lifecycle_record(invalid)
    )


def test_mixed_valid_and_invalid_observation_batch_cannot_advance():
    valid = _observation("rising", "metrics/rising-mixed-valid.json")
    invalid = _observation("stable", "metrics/stable-mixed-invalid.json")
    invalid["observed_at"] = "not-a-time"

    result = advance_content_lifecycle(_published(), [valid, invalid])

    assert result["payload"]["state"] == "published"
    assert "observation_event_invalid" in result["payload"]["blockers"]


@pytest.mark.parametrize("state", ["observing", "stable", "rising", "decaying"])
def test_builder_only_constructs_draft(state: str):
    with pytest.raises(ValueError):
        _record(state)


def test_advance_persists_structured_publication_evidence():
    result = advance_content_lifecycle(_draft(), [_publication_event()])

    assert result["payload"]["publication_evidence"] == {
        "article_id": ARTICLE_ID,
        "published_at": "2026-09-09T09:00:00+08:00",
        "platform": "toutiao",
        "ref": "publication-001",
    }
    assert validate_lifecycle_record(result) == []


def test_advance_persists_structured_observation_evidence_and_trend_binding():
    result = advance_content_lifecycle(_published(), _rising_events())

    assert result["payload"]["observation_evidence"] == [
        {
            "article_id": ARTICLE_ID,
            "timestamp": "2026-09-09T12:00:00+08:00",
            "ref": "metrics/rising-001.json",
            "metrics": {
                "window": {
                    "start": "2026-09-09T09:00:00+08:00",
                    "end": "2026-09-09T12:00:00+08:00",
                },
                "impressions": 1000,
                "clicks": 100,
            },
            "trend": "rising",
        }
    ]
    assert result["payload"]["observation_trend"] == "rising"
    assert result["payload"]["observation_trend_ref"] == (
        "metrics/rising-001.json"
    )
    assert validate_lifecycle_record(result) == []


def test_validator_rejects_published_record_with_only_fake_evidence_ref():
    invalid = {
        **_draft(),
        "payload": {
            **_draft()["payload"],
            "state": "published",
            "next_action": "record_observations",
            "evidence_refs": ["fake-ref"],
            "transition": {
                "from": "draft",
                "to": "published",
                "reason": "fabricated",
            },
        },
    }

    assert validate_lifecycle_record(invalid)


def test_validator_rejects_observation_state_without_structured_evidence():
    invalid = {
        **_draft(),
        "payload": {
            **_draft()["payload"],
            "state": "rising",
            "next_action": "append_related_content",
            "evidence_refs": ["fake-ref"],
            "transition": {
                "from": "published",
                "to": "rising",
                "reason": "fabricated",
            },
            "publication_evidence": {
                "article_id": ARTICLE_ID,
                "published_at": "2026-09-09T09:00:00+08:00",
                "platform": "toutiao",
                "ref": "fake-ref",
            },
        },
    }

    assert "observation_state_requires_observation_evidence" in (
        validate_lifecycle_record(invalid)
    )


@pytest.mark.parametrize("field", ["article_id", "timestamp", "ref", "metrics"])
def test_validator_rejects_malformed_observation_evidence(field: str):
    valid = advance_content_lifecycle(_published(), _rising_events())
    evidence = valid["payload"]["observation_evidence"][0]
    if field == "article_id":
        evidence[field] = "article-999"
    elif field == "timestamp":
        evidence[field] = "not-a-time"
    elif field == "ref":
        evidence[field] = "fake-ref"
    else:
        evidence.pop(field)

    errors = validate_lifecycle_record(valid)
    if field == "ref":
        assert "evidence_refs_missing_structured_evidence" in errors
        assert "evidence_refs_not_backed_by_structured_evidence" in errors
    else:
        assert "invalid:observation_evidence" in errors


def test_validator_requires_observation_trend_state_and_reference_to_match():
    rising = advance_content_lifecycle(_published(), _rising_events())

    wrong_state = {
        **rising,
        "payload": {
            **rising["payload"],
            "observation_trend": "stable",
        },
    }
    wrong_ref = {
        **rising,
        "payload": {
            **rising["payload"],
            "observation_trend_ref": "fake-ref",
        },
    }

    assert "observation_trend_state_mismatch" in validate_lifecycle_record(
        wrong_state
    )
    assert "observation_trend_ref_mismatch" in validate_lifecycle_record(
        wrong_ref
    )


def test_forward_only_observation_does_not_overwrite_current_trend_metadata():
    rising = advance_content_lifecycle(_published(), _rising_events())
    result = advance_content_lifecycle(rising, _stable_events())

    assert result["payload"]["state"] == "rising"
    assert result["payload"]["observation_trend"] == "rising"
    assert result["payload"]["observation_trend_ref"] == (
        "metrics/rising-001.json"
    )
    assert validate_lifecycle_record(result) == []


def test_archived_mismatched_controller_decision_preserves_valid_metadata():
    archived = advance_content_lifecycle(
        _published(), [], controller_decision="archive"
    )
    previous_transition = archived["payload"]["transition"]

    result = advance_content_lifecycle(
        archived, [], controller_decision="approve_evergreen"
    )

    assert result["payload"]["state"] == "archived"
    assert result["payload"]["controller_decision"] == "archive"
    assert result["payload"]["transition"] == previous_transition
    assert "controller_decision_mismatch" in result["payload"]["blockers"]
    assert validate_lifecycle_record(result) == []


def test_evergreen_can_explicitly_transition_to_archived():
    evergreen = advance_content_lifecycle(
        advance_content_lifecycle(_published(), _rising_events()),
        _stable_events(),
        controller_decision="approve_evergreen",
    )

    result = advance_content_lifecycle(
        evergreen, [], controller_decision="archive"
    )

    assert result["payload"]["state"] == "archived"
    assert result["payload"]["controller_decision"] == "archive"
    assert validate_lifecycle_record(result) == []
