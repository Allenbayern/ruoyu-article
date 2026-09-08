import json
from pathlib import Path

from article_group.v4.contracts import (
    ARTIFACT_SCHEMA_VERSIONS,
    EDGE_TYPES,
    EFFECT_STATES,
    GAP_TYPES,
    NODE_TYPES,
    new_artifact_envelope,
    parse_json_object,
    safe_relative_path,
    sha256_file,
    validate_artifact_envelope,
    validate_node_type,
)


def test_v4_envelope_requires_run_identity():
    errors = validate_artifact_envelope(
        {"schema_version": "v4-portfolio-plan-v1", "payload": {}},
        "v4-portfolio-plan-v1",
        run_id="controlled-002",
    )
    assert "missing:run_id" in errors


def test_v4_path_rejects_traversal():
    assert safe_relative_path(Path("/tmp/run"), "../draft.md") is None


def test_v4_unknown_node_type_fails_contract():
    assert "invalid:node_type" in validate_node_type("unknown")


def test_v4_envelope_round_trip_is_valid():
    envelope = new_artifact_envelope(
        "v4-portfolio-plan-v1",
        "controlled-002",
        {"decision": "selected"},
        generated_at="2026-09-08T10:00:00+08:00",
    )

    assert envelope["input_hashes"] == {}
    assert validate_artifact_envelope(
        envelope, "v4-portfolio-plan-v1", run_id="controlled-002"
    ) == []


def test_v4_envelope_rejects_unknown_schema_and_run_mismatch():
    envelope = new_artifact_envelope(
        "v4-portfolio-plan-v1",
        "controlled-002",
        {},
        generated_at="2026-09-08T10:00:00+08:00",
    )

    errors = validate_artifact_envelope(
        {**envelope, "schema_version": "unknown"},
        "v4-portfolio-plan-v1",
        run_id="controlled-003",
    )

    assert "unknown:schema_version" in errors
    assert "mismatch:run_id" in errors


def test_v4_hash_entries_must_be_sha256():
    envelope = new_artifact_envelope(
        "v4-portfolio-plan-v1",
        "controlled-002",
        {},
        generated_at="2026-09-08T10:00:00+08:00",
    )

    errors = validate_artifact_envelope(
        {**envelope, "input_hashes": {"source.json": "not-a-hash"}},
        "v4-portfolio-plan-v1",
        run_id="controlled-002",
    )

    assert "invalid:input_hashes" in errors


def test_v4_json_parser_accepts_only_objects():
    assert parse_json_object('{"ok": true}') == {"ok": True}
    assert parse_json_object("[]") is None
    assert parse_json_object("not json") is None


def test_v4_path_stays_inside_run_root(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    assert safe_relative_path(root, "draft.md") == root / "draft.md"
    assert safe_relative_path(root, "/etc/passwd") is None


def test_v4_sha256_file_is_deterministic(tmp_path):
    path = tmp_path / "sample.txt"
    path.write_bytes(b"v4")
    assert sha256_file(path) == (
        "8e38a1ea5c681c8e9a08f1af465f1f07d33d931de8f71af45ecbe957751c9a86"
    )


def test_v4_vocabularies_are_frozen_and_publication_agnostic():
    assert ARTIFACT_SCHEMA_VERSIONS == (
        "v4-portfolio-plan-v1",
        "v4-evidence-graph-v1",
        "v4-gap-priority-v1",
        "v4-template-signals-v1",
        "v4-effect-feedback-v1",
        "v4-recovery-actions-v1",
        "v4-verification-v1",
    )
    assert NODE_TYPES == (
        "topic",
        "claim",
        "source",
        "material",
        "title",
        "opening",
        "paragraph",
        "review",
    )
    assert EDGE_TYPES == (
        "supports",
        "supported_by",
        "captured_as",
        "materialized_as",
        "reviewed_by",
    )
    assert GAP_TYPES == (
        "title_core_fact",
        "opening_support",
        "key_fact_cross_check",
        "audience_sample",
        "industry_relevance",
        "source_failure",
        "dynamic_fact_revalidation",
        "dedupe_context",
    )
    assert EFFECT_STATES == (
        "candidate",
        "adopted",
        "measured",
        "validated",
        "reusable_pattern",
    )


def test_v4_schema_rejects_publication_field(tmp_path):
    schema_path = Path("schemas/editorial-pipeline-v4/v4-artifact.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert "publication_authorization" not in schema["properties"]
