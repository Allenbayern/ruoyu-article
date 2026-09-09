from __future__ import annotations

import copy
import json
from pathlib import Path

from article_group.v4.evidence_graph import (
    _find_output,
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
        "draft_two": "drafts/art-002.md",
        "material": "materials/src-1.md",
        "material_pack": "inputs/task-results/crawl-1/material-pack.json",
        "material_pack_two": "inputs/task-results/crawl-2/material-pack.json",
        "review": "review/art-001/independent-review.json",
        "source_manifest": "source-manifest.json",
    }
    for relative, text in {
        files["topic"]: '{"topic_id":"top-1"}',
        files["fact"]: '{"claims":[{"claim_id":"cl-1","claim_type":"release","source_ids":["src-1"],"locator":"fact claim locator"}]}',
        files["ledger"]: '{"claims":[{"claim_id":"cl-1","source_ids":["src-1"],"draft_locator":"p1-s1; p2-s1","source_locator":"ledger source locator"}]}',
        files["draft"]: "# A title\n\nOpening.\n\nParagraph one.\n",
        files["draft_two"]: "# A title two\n\nOpening.\n\nParagraph one.\n",
        files["material"]: "Captured source material.\n",
        files["review"]: '{"review_id":"rev-1","article_id":"art-001"}',
        files["material_pack"]: '{"materials":{"body_facts":[{"material_id":"m-1","source_id":"src-1","locator":"material locator"}]}}',
        files["material_pack_two"]: '{"materials":{"body_facts":[{"material_id":"m-2","source_id":"src-1","locator":"material locator two"}]}}',
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
            "topic_card_path": files["topic"],
            "draft_path": files["draft"],
            "material_path": files["material"],
            "material_pack_path": files["material_pack_two"],
            "review_path": files["review"],
            "claims": [{"claim_id": "cl-1", "claim_type": "release", "source_ids": ["src-1"]}],
            "title_claim_ids": ["cl-1"],
            "title": "A title",
            "opening": "Opening.",
            "paragraphs": [{"id": "p1-s1", "text": "Paragraph one.", "claim_ids": ["cl-1"]}],
        }, {
            "article_id": "art-002",
            "topic_id": "top-2",
            "fact_card_path": files["fact"],
            "citation_ledger_path": files["ledger"],
            "topic_card_path": files["topic"],
            "draft_path": files["draft_two"],
            "material_pack_path": files["material_pack"],
            "review_path": files["review"],
            "claims": [{"claim_id": "cl-1", "claim_type": "release", "source_ids": ["src-1"]}],
            "title_claim_ids": ["cl-1"],
            "title": "A title two",
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
    assert changed["payload"]["invalidations"][0]["source_id"] == "source:src-1"
    assert changed["payload"]["invalidations"][0]["reason"] == "source_unavailable"


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


def test_real_controlled_002_uses_run_manifest_material_packs_and_locators():
    root = Path("runs/2026-09-07/controlled-002")
    batch = json.loads((root / "batch.json").read_text(encoding="utf-8"))
    batch["articles"] = [
        {**article, "topic_card_path": f"review/{article['article_id']}/topic-card.json"}
        for article in batch["articles"]
    ]
    graph = build_evidence_graph(root, batch)
    nodes = graph["payload"]["nodes"]
    edges = graph["payload"]["edges"]
    assert "topic:topic-20260906-001" in nodes
    assert "topic:topic-20260906-002" in nodes
    assert {"material:m-kong-body", "material:m-kong-industry", "material:m-amai-body"} <= set(nodes)
    assert any(node_id.startswith("paragraph:art-001:") for node_id in nodes)
    assert any(node_id.startswith("paragraph:art-002:") for node_id in nodes)
    assert all(edge["locator"] for edge in edges)
    for article_id in ("art-001", "art-002"):
        ledger = json.loads((root / f"review/{article_id}/citations-ledger.json").read_text(encoding="utf-8"))
        for claim in ledger["claims"]:
            claim_id = claim["claim_id"]
            tokens = [token.strip() for token in claim["draft_locator"].split(";")]
            materialized = [
                edge for edge in edges
                if edge["from"] == f"claim:{article_id}:{claim_id}"
                and edge["edge_type"] == "materialized_as"
            ]
            assert {edge["locator"] for edge in materialized} >= set(tokens)
    assert all(
        not (edge["to"].startswith("title:") and edge["locator"].startswith("p1-"))
        for edge in edges
    )
    assert validate_evidence_graph(graph, root) == []


def test_source_impact_does_not_cross_to_sibling_sources(tmp_path: Path):
    root = Path("runs/2026-09-07/controlled-002")
    graph = build_evidence_graph(root, json.loads((root / "batch.json").read_text(encoding="utf-8")))
    impacted = trace_impact(graph, "source:src-kong-body")
    assert "source:src-kong-cross" not in impacted
    assert "source:src-kong-industry" not in impacted
    assert "material:m-kong-body" in impacted
    assert any(item.startswith("claim:art-001:") for item in impacted)
    changed = invalidate_source(graph, "src-kong-body", "unavailable")
    assert changed["payload"]["nodes"]["source:src-kong-cross"]["status"] == "present"
    assert changed["payload"]["nodes"]["source:src-kong-industry"]["status"] == "present"


def test_material_without_manifest_binding_blocks_graph(tmp_path: Path):
    batch = _minimal_batch(tmp_path)
    pack_path = tmp_path / batch["articles"][0]["material_pack_path"]
    pack_path.write_text('{"materials":{"body_facts":[{"material_id":"m-1","locator":"material locator"}]}}', encoding="utf-8")
    graph = build_evidence_graph(tmp_path, batch)
    assert any("material_binding" in error for error in graph["payload"]["build_errors"])
    assert any("material" in error for error in validate_evidence_graph(graph, tmp_path))


def test_incomplete_batches_fail_closed_even_when_default_files_exist():
    root = Path("runs/2026-09-07/controlled-002")
    batch = json.loads((root / "batch.json").read_text(encoding="utf-8"))
    for articles in ([], batch["articles"][:1]):
        broken = {**batch, "articles": articles}
        graph = build_evidence_graph(root, broken)
        assert graph["payload"].get("build_errors")
        assert validate_evidence_graph(graph, root)


def test_manifest_mapping_missing_does_not_fall_back_to_conventional_paths(tmp_path: Path):
    batch = _minimal_batch(tmp_path)
    manifest = {
        "run_id": "controlled-002",
        "selected_articles": [{"article_id": "art-001", "topic_id": "top-1"}],
        "outputs": {"drafts": [batch["articles"][0]["draft_path"]]},
        "inputs": {"material_packs": [batch["articles"][0]["material_pack_path"]]},
    }
    (tmp_path / "run-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    broken = {key: value for key, value in batch.items() if key != "articles"}
    broken["articles"] = [{"article_id": "art-001"}]
    graph = build_evidence_graph(tmp_path, broken)
    assert any("fact:art-001" in error or "ledger:art-001" in error for error in graph["payload"]["build_errors"])
    assert validate_evidence_graph(graph, tmp_path)


def test_existing_conventional_topic_path_without_mapping_fails_closed(tmp_path: Path):
    batch = _minimal_batch(tmp_path)
    batch["articles"] = [{key: value for key, value in batch["articles"][0].items() if key != "topic_card_path"}]
    graph = build_evidence_graph(tmp_path, batch)
    assert any("topic:art-001" in error for error in graph["payload"]["build_errors"])
    assert validate_evidence_graph(graph, tmp_path)


def test_no_manifest_empty_or_single_article_fails_closed(tmp_path: Path):
    valid = _minimal_batch(tmp_path)
    for articles in ([], valid["articles"][:1]):
        broken = {key: value for key, value in valid.items() if key != "articles"}
        broken["articles"] = articles
        graph = build_evidence_graph(tmp_path, broken)
        assert any("article_count" in error or "articles" in error for error in graph["payload"]["build_errors"])
        assert validate_evidence_graph(graph, tmp_path)


def test_validation_requires_node_and_edge_contract_fields(tmp_path: Path):
    graph = build_evidence_graph(tmp_path, _minimal_batch(tmp_path))
    node = graph["payload"]["nodes"]["source:src-1"]
    edge = graph["payload"]["edges"][0]
    for field in ("node_id", "node_type", "status", "artifact_path", "artifact_sha256"):
        broken = copy.deepcopy(graph)
        del broken["payload"]["nodes"]["source:src-1"][field]
        assert any(f"node:{field}" in error for error in validate_evidence_graph(broken, tmp_path))
    for field in ("from", "to", "edge_type", "locator", "created_at"):
        broken = copy.deepcopy(graph)
        del broken["payload"]["edges"][0][field]
        assert any(f"edge:{field}" in error for error in validate_evidence_graph(broken, tmp_path))
    assert node and edge


def test_validation_rejects_bad_status_types_and_empty_edge_values(tmp_path: Path):
    graph = build_evidence_graph(tmp_path, _minimal_batch(tmp_path))
    for value in ("unknown", 1, None):
        broken = copy.deepcopy(graph)
        broken["payload"]["nodes"]["source:src-1"]["status"] = value
        assert any("status" in error for error in validate_evidence_graph(broken, tmp_path))
    for field in ("from", "to", "edge_type", "locator", "created_at"):
        broken = copy.deepcopy(graph)
        broken["payload"]["edges"][0][field] = ""
        assert any(f"edge:{field}" in error for error in validate_evidence_graph(broken, tmp_path))


def test_validation_rejects_wrong_node_and_edge_field_types(tmp_path: Path):
    graph = build_evidence_graph(tmp_path, _minimal_batch(tmp_path))
    for field in ("node_id", "node_type", "artifact_path", "artifact_sha256"):
        broken = copy.deepcopy(graph)
        broken["payload"]["nodes"]["source:src-1"][field] = ["wrong"]
        assert any(field in error for error in validate_evidence_graph(broken, tmp_path))
    for field in ("from", "to", "edge_type", "locator", "created_at"):
        broken = copy.deepcopy(graph)
        broken["payload"]["edges"][0][field] = ["wrong"]
        assert any(f"edge:{field}" in error for error in validate_evidence_graph(broken, tmp_path))


def test_malformed_required_json_cannot_be_bypassed_by_inline_claims(tmp_path: Path):
    batch = _minimal_batch(tmp_path)
    (tmp_path / batch["articles"][0]["fact_card_path"]).write_text("{bad", encoding="utf-8")
    graph = build_evidence_graph(tmp_path, batch)
    assert graph["payload"]["build_errors"]
    assert any("fact" in error for error in validate_evidence_graph(graph, tmp_path))


def test_duplicate_article_ids_with_distinct_artifacts_fail_closed(tmp_path: Path):
    batch = _minimal_batch(tmp_path)
    duplicate_draft = tmp_path / "drafts/art-001-duplicate.md"
    duplicate_draft.write_text("# A title\n\nOpening.\n", encoding="utf-8")
    batch["articles"][1] = {
        **batch["articles"][1],
        "article_id": "art-001",
        "draft_path": "drafts/art-001-duplicate.md",
    }
    graph = build_evidence_graph(tmp_path, batch)
    assert any("duplicate:article_id" in error for error in graph["payload"].get("build_errors", []))
    assert any("duplicate" in error for error in validate_evidence_graph(graph, tmp_path))


def test_duplicate_node_id_with_distinct_artifact_fails_closed(tmp_path: Path):
    graph = build_evidence_graph(tmp_path, _minimal_batch(tmp_path))
    other = tmp_path / "sources/other.md"
    other.write_text("Another source.\n", encoding="utf-8")
    broken = copy.deepcopy(graph)
    source = dict(broken["payload"]["nodes"]["source:src-1"])
    source["artifact_path"] = "sources/other.md"
    source["artifact_sha256"] = None
    broken["payload"]["nodes"]["source:src-1-copy"] = source
    assert any("duplicate:node" in error or "mismatch:node_id" in error for error in validate_evidence_graph(broken, tmp_path))


def test_graph_input_hashes_protect_source_manifest_binding(tmp_path: Path):
    batch = _minimal_batch(tmp_path)
    graph = build_evidence_graph(tmp_path, batch)
    assert graph["input_hashes"]
    assert any("source-manifest.json" in key for key in graph["input_hashes"])
    manifest_path = tmp_path / batch["source_manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    (tmp_path / "sources/other.md").write_text("Rebound source.\n", encoding="utf-8")
    manifest["sources"][0]["path"] = "sources/other.md"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    errors = validate_evidence_graph(graph, tmp_path)
    assert any("input_hash" in error or "source_mapping" in error for error in errors)


def test_output_mapping_does_not_match_article_id_substrings_or_ambiguity():
    errors: list[str] = []
    outputs = {"drafts": ["drafts/art-0010.md", "drafts/art-001.md"]}
    assert _find_output(outputs, "drafts", "art-001", errors) == "drafts/art-001.md"
    assert errors == []
    ambiguous: list[str] = []
    outputs["drafts"] = ["drafts/art-001/first.md", "drafts/art-001/second.md"]
    assert _find_output(outputs, "drafts", "art-001", ambiguous) == ""
    assert any("ambiguous" in error for error in ambiguous)


def test_draft_locators_require_one_matching_real_h1(tmp_path: Path):
    batch = _minimal_batch(tmp_path)
    draft_path = tmp_path / batch["articles"][0]["draft_path"]
    draft_path.write_text("Opening without a title.\n\nBody.\n", encoding="utf-8")
    graph = build_evidence_graph(tmp_path, batch)
    assert any("h1" in error for error in graph["payload"].get("build_errors", []))
    assert validate_evidence_graph(graph, tmp_path)

    draft_path.write_text("# A title\n\nOpening.\n\n# Another title\n\nBody.\n", encoding="utf-8")
    repeated = build_evidence_graph(tmp_path, batch)
    assert any("h1" in error for error in repeated["payload"].get("build_errors", []))
    assert validate_evidence_graph(repeated, tmp_path)


def test_draft_title_must_match_input_and_locator_comes_from_markdown(tmp_path: Path):
    batch = _minimal_batch(tmp_path)
    graph = build_evidence_graph(tmp_path, batch)
    assert graph["payload"]["nodes"]["title:art-001"]["locator"] == "h1:A title"
    draft_path = tmp_path / batch["articles"][0]["draft_path"]
    draft_path.write_text("# Different title\n\nOpening.\n\nBody.\n", encoding="utf-8")
    broken = build_evidence_graph(tmp_path, batch)
    assert any("title" in error for error in broken["payload"].get("build_errors", []))
    assert validate_evidence_graph(broken, tmp_path)


def test_publication_authorization_is_outside_graph_boundary(tmp_path: Path):
    graph = build_evidence_graph(tmp_path, _minimal_batch(tmp_path))
    assert "publication_authorization" not in graph
    assert "publication_authorization" not in graph["payload"]
    broken = copy.deepcopy(graph)
    broken["payload"]["publication_authorization"] = "authorized"
    assert any("publication_authorization" in error for error in validate_evidence_graph(broken, tmp_path))


def test_missing_claim_source_and_material_locators_fail_closed(tmp_path: Path):
    batch = _minimal_batch(tmp_path)
    ledger_path = tmp_path / batch["articles"][0]["citation_ledger_path"]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["claims"][0]["source_locator"] = ""
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    source_broken = build_evidence_graph(tmp_path, batch)
    assert any("source_locator" in error for error in source_broken["payload"].get("build_errors", []))
    assert validate_evidence_graph(source_broken, tmp_path)

    batch = _minimal_batch(tmp_path)
    fact_path = tmp_path / batch["articles"][0]["fact_card_path"]
    fact = json.loads(fact_path.read_text(encoding="utf-8"))
    fact["claims"][0]["locator"] = ""
    ledger_path = tmp_path / batch["articles"][0]["citation_ledger_path"]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["claims"][0]["draft_locator"] = ""
    fact_path.write_text(json.dumps(fact), encoding="utf-8")
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    claim_broken = build_evidence_graph(tmp_path, batch)
    assert any("claim_locator" in error for error in claim_broken["payload"].get("build_errors", []))
    assert validate_evidence_graph(claim_broken, tmp_path)

    batch = _minimal_batch(tmp_path)
    pack_path = tmp_path / batch["articles"][0]["material_pack_path"]
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    pack["materials"]["body_facts"][0]["locator"] = ""
    pack_path.write_text(json.dumps(pack), encoding="utf-8")
    material_broken = build_evidence_graph(tmp_path, batch)
    assert any("material_locator" in error for error in material_broken["payload"].get("build_errors", []))
    assert validate_evidence_graph(material_broken, tmp_path)


def test_discovery_source_can_be_retained_but_cannot_prove_a_claim(tmp_path: Path):
    batch = _minimal_batch(tmp_path)
    manifest_path = tmp_path / batch["source_manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sources"][0]["source_role"] = "discovery_signal"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    graph = build_evidence_graph(tmp_path, batch)

    assert "source:src-1" in graph["payload"]["nodes"]
    assert any("discovery_source_support" in error for error in graph["payload"].get("build_errors", []))
    assert validate_evidence_graph(graph, tmp_path)
