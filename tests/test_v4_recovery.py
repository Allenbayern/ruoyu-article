from __future__ import annotations

from article_group.v4.contracts import new_artifact_envelope
from article_group.v4.recovery import derive_recovery_actions, validate_recovery_actions


CREATED_AT = "2026-09-08T10:00:00+08:00"


def _graph() -> dict[str, object]:
    nodes = {
        node_id: {
            "node_id": node_id,
            "node_type": node_type,
            "status": "present",
            "artifact_path": f"{node_type}.json",
            "artifact_sha256": "0" * 64,
        }
        for node_id, node_type in (
            ("source:src-1", "source"),
            ("material:m-1", "material"),
            ("claim:art-001:c-1", "claim"),
            ("title:art-001", "title"),
            ("opening:art-001", "opening"),
            ("paragraph:art-001:p1-s1", "paragraph"),
            ("review:art-001:r-1", "review"),
        )
    }
    nodes["source:src-1"]["source_role"] = "primary"
    nodes["claim:art-001:c-1"]["claim_type"] = "fact"
    edges = [
        {"from": "claim:art-001:c-1", "to": "source:src-1", "edge_type": "supported_by", "locator": "c-1", "created_at": CREATED_AT},
        {"from": "source:src-1", "to": "material:m-1", "edge_type": "captured_as", "locator": "m-1", "created_at": CREATED_AT},
        {"from": "claim:art-001:c-1", "to": "title:art-001", "edge_type": "materialized_as", "locator": "title", "created_at": CREATED_AT},
        {"from": "claim:art-001:c-1", "to": "opening:art-001", "edge_type": "materialized_as", "locator": "opening", "created_at": CREATED_AT},
        {"from": "claim:art-001:c-1", "to": "paragraph:art-001:p1-s1", "edge_type": "materialized_as", "locator": "p1-s1", "created_at": CREATED_AT},
        {"from": "title:art-001", "to": "review:art-001:r-1", "edge_type": "reviewed_by", "locator": "review", "created_at": CREATED_AT},
        {"from": "opening:art-001", "to": "review:art-001:r-1", "edge_type": "reviewed_by", "locator": "review", "created_at": CREATED_AT},
        {"from": "paragraph:art-001:p1-s1", "to": "review:art-001:r-1", "edge_type": "reviewed_by", "locator": "review", "created_at": CREATED_AT},
    ]
    return new_artifact_envelope(
        "v4-evidence-graph-v1",
        "run-1",
        {"nodes": nodes, "edges": edges},
        generated_at=CREATED_AT,
    )


def test_source_failure_traces_stale_downstream_nodes_and_is_not_authorized():
    actions = derive_recovery_actions(
        _graph(),
        [{
            "event_id": "event-1",
            "event_type": "source_failure",
            "source_id": "src-1",
            "reason": "source unavailable",
            "evidence_refs": ["audit/source.json"],
        }],
        run_id="run-1",
        created_at=CREATED_AT,
    )

    action = actions["payload"]["actions"][0]
    assert actions["schema_version"] == "v4-recovery-actions-v1"
    assert "material:m-1" in action["affected_nodes"]
    assert "paragraph:art-001:p1-s1" in action["affected_nodes"]
    assert action["next_state"] == "stale"
    assert action["publication_authorization"] == "not_authorized"
    assert validate_recovery_actions(actions) == []


def test_all_recovery_events_produce_explicit_safe_actions():
    events = [
        {"event_id": "01", "event_type": "title_changed", "affected_nodes": ["title:art-001"], "evidence_refs": ["title.json"]},
        {"event_id": "02", "event_type": "fact_changed", "affected_nodes": ["claim:art-001:c-1"], "evidence_refs": ["fact.json"]},
        {"event_id": "03", "event_type": "duplicate_topic", "affected_nodes": ["topic:topic-1"], "evidence_refs": ["portfolio.json"]},
        {"event_id": "04", "event_type": "material_insufficient", "affected_nodes": ["material:m-1"], "evidence_refs": ["material.json"]},
        {"event_id": "05", "event_type": "high_risk", "affected_nodes": ["claim:art-001:c-1"], "evidence_refs": ["risk.json"]},
        {"event_id": "06", "event_type": "gap_failed_twice", "gap_id": "gap-1", "affected_nodes": ["claim:art-001:c-1"], "evidence_refs": ["gap.json"]},
    ]

    actions = derive_recovery_actions(_graph(), events, run_id="run-1", created_at=CREATED_AT)
    by_event = {action["event_type"]: action for action in actions["payload"]["actions"]}

    assert by_event["title_changed"]["next_state"] == "recheck"
    assert by_event["fact_changed"]["next_state"] == "recheck"
    assert by_event["duplicate_topic"]["next_state"] == "precheck"
    assert by_event["material_insufficient"]["next_state"] == "blocked"
    assert by_event["high_risk"]["required_owner"] == "controller"
    assert by_event["gap_failed_twice"]["action_type"] == "switch_topic_recommended"
    assert all(action["publication_authorization"] == "not_authorized" for action in by_event.values())
    assert all(action["next_state"] not in {"closed", "R8", "published"} for action in by_event.values())
    assert validate_recovery_actions(actions) == []


def test_malformed_inputs_fail_closed_and_validator_rejects_unsafe_actions():
    actions = derive_recovery_actions(
        {"payload": []},
        [{"event_type": "high_risk"}],
        run_id="run-1",
        created_at=CREATED_AT,
    )
    assert actions["payload"]["actions"] == []
    assert validate_recovery_actions(actions)

    unsafe = {
        "schema_version": "v4-recovery-actions-v1",
        "run_id": "run-1",
        "generated_at": CREATED_AT,
        "input_hashes": {},
        "payload": {"actions": [{"action_type": "publish", "next_state": "closed"}]},
    }
    errors = validate_recovery_actions(unsafe)
    assert any("action" in error for error in errors)
    assert any("authorization" in error for error in errors)
