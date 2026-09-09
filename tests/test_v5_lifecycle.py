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


def _record(state: str = "draft") -> dict[str, Any]:
    return build_content_lifecycle(
        article_id="article-001",
        run_id=RUN_ID,
        generated_at=GENERATED_AT,
        state=state,
    )


def _draft() -> dict[str, Any]:
    return _record("draft")


def _published() -> dict[str, Any]:
    return _record("published")


def _publication_event(**overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "event_type": "published",
        "published_at": "2026-09-09T09:00:00+08:00",
        "platform": "toutiao",
        "event_id": "publication-001",
    }
    event.update(overrides)
    return event


def _observation(trend: str, evidence_ref: str) -> dict[str, object]:
    return {
        "event_type": "observation",
        "observed_at": "2026-09-09T12:00:00+08:00",
        "trend": trend,
        "evidence_ref": evidence_ref,
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


@pytest.mark.parametrize("missing", ["published_at", "platform"])
def test_incomplete_publication_event_cannot_publish_draft(missing: str):
    event = _publication_event()
    event.pop(missing)

    result = advance_content_lifecycle(_draft(), [event])

    assert result["payload"]["state"] == "draft"
    assert "publication_event_required" in result["payload"]["blockers"]


def test_published_observation_can_become_rising_but_evergreen_needs_controller():
    rising = advance_content_lifecycle(_published(), _rising_events())

    assert rising["payload"]["state"] == "rising"
    assert rising["payload"]["evidence_refs"] == ["metrics/rising-001.json"]

    evergreen = advance_content_lifecycle(
        rising, _stable_events(), controller_decision="approve_evergreen"
    )

    assert evergreen["payload"]["state"] == "evergreen"
    assert evergreen["payload"]["publication_authorization"] == "not_authorized"


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


def test_lifecycle_validation_accepts_closed_record_and_rejects_unknown_state():
    record = _draft()

    assert validate_lifecycle_record(record) == []

    invalid = {**record, "payload": {**record["payload"], "state": "viral"}}
    assert "invalid:state" in validate_lifecycle_record(invalid)


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
