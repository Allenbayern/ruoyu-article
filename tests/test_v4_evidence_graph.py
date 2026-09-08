from __future__ import annotations

import copy
from pathlib import Path

from article_group.v4.evidence_graph import (
    build_evidence_graph,
    invalidate_source,
    trace_impact,
    validate_evidence_graph,
)


def _minimal_batch(root: Path) -> dict:
    files = {
        "topic": "topic.json",
        "fact": "review/art-001/fact-card.json",
        "ledger": "review/art-001/citations-ledger.json",
        "draft": "drafts/art-001.md",
        "material": "materials/src-1.md",
        "review": "review/art-001/independent-review.json",
        "source_manifest": "source-manifest.json",
    }
    for relative, text in {
        files["topic"]: '{"topic_id":"top-1"}',
        files["fact"]: '{"claims":[{"claim_id":"cl-1","claim_type":"release","source_ids":["src-1"]}]}',
        files["ledger"]: '{"claims":[{"claim_id":"cl-1","source_ids":["src-1"]}]}',
        files["draft"]: "# A title\n\nOpening.\n\nParagraph one.\n",
        files["material"]: "Captured source material.\n",
        files["review"]: '{"review_id":"rev-1","article_id":"art-001"}',
        files["source_manifest"]: '{"sources":[{"source_id":"src-1","path":"sources/src-1.md","source_role":"primary"}]}',
        "sources/src-1.md": "Primary source.\n",
    }.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return {
        "run_id": "controlled-002",
        "generated_at": "2026-09-08T10:00:00+08:00",
        "topic": {"topic_id": "top-1", "path": files["topic"]},
        "articles": [{
            "article_id": "art-001",
            "topic_id": "top-1",
            "fact_card_path": files["fact"],
            "citation_ledger_path": files["ledger"],
            "draft_path": files["draft"],
            "material_path": files["material"],
            "review_path": files["review"],
            "claims": [{"claim_id": "cl-1", "claim_type": "release", "source_ids": ["src-1"]}],
            "title": "A title",
            "opening": "Opening.",
            "paragraphs": [{"id": "p1-s1", "text": "Paragraph one.", "claim_ids": ["cl-1"]}],
        }],
        "source_manifest_path": files["source_manifest"],
    }


def test_build_uses_closed_payload_and_all_eight_node_types(tmp_path: Path):
    graph = build_evidence_graph(tmp_path, _minimal_batch(tmp_path))
    assert set(graph["payload"]) == {"nodes", "edges"}
    assert {node["node_type"] for node in graph["payload"]["nodes"].values()} == {
        "topic", "claim", "source", "material", "title", "opening", "paragraph", "review"
    }
    assert validate_evidence_graph(graph, tmp_path) == []
    assert all("artifact_path" in node and "artifact_sha256" in node for node in graph["payload"]["nodes"].values())


def test_source_invalidation_marks_all_downstream_nodes_stale(tmp_path: Path):
    graph = build_evidence_graph(tmp_path, _minimal_batch(tmp_path))
    changed = invalidate_source(graph, "src-1", "source_unavailable")
    impacted = trace_impact(changed, "source:src-1")
    assert "paragraph:art-001:p1-s1" in impacted
    assert all(changed["payload"]["nodes"][node]["status"] == "stale" for node in impacted)
    assert changed != graph
    assert changed["payload"]["nodes"]["source:src-1"]["invalidation_reasons"] == ["source_unavailable"]


def test_validation_rejects_hash_mismatch_unknown_edge_and_isolated_title(tmp_path: Path):
    graph = build_evidence_graph(tmp_path, _minimal_batch(tmp_path))
    broken = copy.deepcopy(graph)
    broken["payload"]["nodes"]["source:src-1"]["artifact_sha256"] = "0" * 64
    broken["payload"]["edges"].append({"from": "source:src-1", "to": "title:art-001", "edge_type": "supports"})
    broken["payload"]["nodes"]["title:art-001"]["status"] = "present"
    errors = validate_evidence_graph(broken, tmp_path)
    assert any("hash" in error for error in errors)
    assert any("edge" in error for error in errors)

    isolated = copy.deepcopy(graph)
    isolated["payload"]["edges"] = [edge for edge in isolated["payload"]["edges"] if edge["to"] != "title:art-001"]
    assert any("isolated:title" in error for error in validate_evidence_graph(isolated, tmp_path))


def test_validation_rejects_traversal_and_missing_source_stays_visible(tmp_path: Path):
    batch = _minimal_batch(tmp_path)
    batch["articles"][0]["claims"][0]["source_ids"].append("src-missing")
    graph = build_evidence_graph(tmp_path, batch)
    missing = graph["payload"]["nodes"]["source:src-missing"]
    assert missing["status"] == "missing"
    assert missing["artifact_sha256"] is None
    missing["artifact_path"] = "../secret"
    assert any("path" in error for error in validate_evidence_graph(graph, tmp_path))


def test_build_is_stable_without_timestamp_and_malformed_graph_returns_errors(tmp_path: Path):
    batch = _minimal_batch(tmp_path)
    batch.pop("generated_at")
    assert build_evidence_graph(tmp_path, batch) == build_evidence_graph(tmp_path, batch)
    errors = validate_evidence_graph({"payload": {"nodes": [], "edges": "bad"}}, tmp_path)
    assert errors
