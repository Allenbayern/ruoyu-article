from __future__ import annotations

from article_group.v4.contracts import GAP_TYPES, new_artifact_envelope
from article_group.v4.gap_priority import (
    derive_gap_tasks,
    rank_gap_tasks,
    record_gap_attempt,
)


def gap(gap_type: str, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "gap_id": f"gap-{gap_type}",
        "gap_type": gap_type,
        "blocking": False,
        "impact": 1,
        "risk": 1,
        "confidence": 1,
        "effort": 1,
        "affected_nodes": [],
        "failed_source_ids": [],
        "retryable": True,
        "attempts": 0,
        "created_at": "2026-09-08T10:00:00+08:00",
        "evidence_refs": [],
    }
    value.update(overrides)
    return value


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
    nodes["claim:art-001:c-1"]["locator"] = "fact:claim-1"
    nodes["material:m-1"]["locator"] = "material:m-1"
    nodes["title:art-001"]["locator"] = "h1:title"
    nodes["opening:art-001"]["locator"] = "opening"
    nodes["paragraph:art-001:p1-s1"]["locator"] = "p1-s1"
    nodes["review:art-001:r-1"]["locator"] = "review"
    edges = [
        {"from": "claim:art-001:c-1", "to": "source:src-1", "edge_type": "supported_by", "locator": "c-1", "created_at": "2026-09-08T10:00:00+08:00"},
        {"from": "source:src-1", "to": "material:m-1", "edge_type": "captured_as", "locator": "m-1", "created_at": "2026-09-08T10:00:00+08:00"},
        {"from": "claim:art-001:c-1", "to": "title:art-001", "edge_type": "materialized_as", "locator": "title", "created_at": "2026-09-08T10:00:00+08:00"},
        {"from": "claim:art-001:c-1", "to": "opening:art-001", "edge_type": "materialized_as", "locator": "opening", "created_at": "2026-09-08T10:00:00+08:00"},
        {"from": "claim:art-001:c-1", "to": "paragraph:art-001:p1-s1", "edge_type": "materialized_as", "locator": "p1-s1", "created_at": "2026-09-08T10:00:00+08:00"},
        {"from": "title:art-001", "to": "review:art-001:r-1", "edge_type": "reviewed_by", "locator": "review", "created_at": "2026-09-08T10:00:00+08:00"},
        {"from": "opening:art-001", "to": "review:art-001:r-1", "edge_type": "reviewed_by", "locator": "review", "created_at": "2026-09-08T10:00:00+08:00"},
        {"from": "paragraph:art-001:p1-s1", "to": "review:art-001:r-1", "edge_type": "reviewed_by", "locator": "review", "created_at": "2026-09-08T10:00:00+08:00"},
    ]
    return new_artifact_envelope(
        "v4-evidence-graph-v1",
        "run-1",
        {"nodes": nodes, "edges": edges},
        generated_at="2026-09-08T10:00:00+08:00",
    )


def test_exact_priority_order_is_applied_and_input_is_not_mutated():
    gaps = [
        gap("audience_sample", gap_id="gap-z", blocking=False, impact=3, risk=3, confidence=3, effort=1),
        gap("title_core_fact", gap_id="gap-b", blocking=True, impact=2, risk=1, confidence=1, effort=5),
        gap("opening_support", gap_id="gap-a", blocking=True, impact=2, risk=1, confidence=1, effort=2),
        gap("key_fact_cross_check", gap_id="gap-c", blocking=True, impact=2, risk=1, confidence=1, effort=2),
    ]
    ranked = rank_gap_tasks(gaps)

    assert [item["gap_id"] for item in ranked] == ["gap-a", "gap-c", "gap-b", "gap-z"]
    assert gaps[0]["gap_id"] == "gap-z"


def test_blocking_title_fact_gap_outranks_nonblocking_audience_gap():
    ranked = rank_gap_tasks([
        gap("audience_sample", blocking=False, impact=3, risk=1, confidence=2, effort=1),
        gap("title_core_fact", blocking=True, impact=3, risk=3, confidence=3, effort=2),
    ])
    assert ranked[0]["gap_type"] == "title_core_fact"


def test_derive_maps_all_gap_types_and_preserves_audit_details():
    audits = [
        {
            "audit_id": f"audit-{index}",
            "gap_type": gap_type,
            "status": "missing",
            "blocking": gap_type in {"title_core_fact", "opening_support"},
            "impact": index + 1,
            "risk": 3,
            "confidence": 2,
            "effort": 2,
            "affected_nodes": ["title:art-001"] if gap_type in {"title_core_fact", "source_failure"} else [],
            "failed_source_ids": ["src-failed"] if gap_type == "source_failure" else [],
            "retryable": gap_type != "dedupe_context",
            "attempts": 1,
            "created_at": "2026-09-08T10:00:00+08:00",
            "evidence_refs": [f"audit/{index}.json"],
        }
        for index, gap_type in enumerate(GAP_TYPES)
    ]

    derived = derive_gap_tasks(_graph(), audits)

    assert {item["gap_type"] for item in derived} == set(GAP_TYPES)
    source_gap = next(item for item in derived if item["gap_type"] == "source_failure")
    assert source_gap["failed_source_ids"] == ["src-failed"]
    assert source_gap["affected_nodes"] == ["title:art-001"]
    assert source_gap["retryable"] is True
    assert source_gap["attempts"] == 1


def test_graph_source_failure_is_visible_when_audit_is_empty():
    graph = _graph()
    graph["payload"]["nodes"]["source:src-1"]["status"] = "stale"

    tasks = derive_gap_tasks(graph, [])

    assert len(tasks) == 1
    assert tasks[0]["gap_type"] == "source_failure"
    assert tasks[0]["failed_source_ids"] == ["src-1"]
    assert "source:src-1" in tasks[0]["affected_nodes"]
    assert "paragraph:art-001:p1-s1" in tasks[0]["affected_nodes"]


def test_two_failed_attempts_recommend_topic_switch_without_switching_it():
    updated = record_gap_attempt(
        gap("source_failure", attempts=1),
        outcome="failed",
        evidence_ref="audit.json",
    )

    assert updated["attempts"] == 2
    assert updated["consecutive_failures"] == 2
    assert updated["disposition"] == "switch_topic_recommended"
    assert "topic_switched" not in updated
    assert updated["evidence_refs"] == ["audit.json"]


def test_success_resets_consecutive_failures_and_invalid_input_fails_closed():
    updated = record_gap_attempt(
        gap("source_failure", attempts=1, consecutive_failures=1),
        outcome="succeeded",
        evidence_ref=None,
    )
    assert updated["attempts"] == 2
    assert updated["consecutive_failures"] == 0
    assert updated["disposition"] == "resolved"
    assert rank_gap_tasks([{"gap_type": "not-a-gap"}]) == []
    assert derive_gap_tasks({"payload": []}, []) == []


def test_malformed_graph_paths_roles_and_edges_block_gap_derivation():
    missing_path = _graph()
    del missing_path["payload"]["nodes"]["source:src-1"]["artifact_path"]
    assert derive_gap_tasks(missing_path, []) == []

    missing_role = _graph()
    del missing_role["payload"]["nodes"]["source:src-1"]["source_role"]
    assert derive_gap_tasks(missing_role, []) == []

    missing_edges = _graph()
    missing_edges["payload"]["edges"] = []
    assert derive_gap_tasks(missing_edges, []) == []
