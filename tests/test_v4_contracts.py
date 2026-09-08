import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

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


def test_v4_envelope_rejects_unknown_top_level_fields_and_bad_timestamp():
    envelope = new_artifact_envelope(
        "v4-portfolio-plan-v1",
        "controlled-002",
        {},
        generated_at="2026-09-08T10:00:00+08:00",
    )

    assert "invalid:top_level" in validate_artifact_envelope(
        {**envelope, "publication_authorization": "not_authorized"},
        "v4-portfolio-plan-v1",
        run_id="controlled-002",
    )
    assert "invalid:top_level" in validate_artifact_envelope(
        {**envelope, "unknown": True},
        "v4-portfolio-plan-v1",
        run_id="controlled-002",
    )
    assert "invalid:generated_at" in validate_artifact_envelope(
        {**envelope, "generated_at": "not-a-date"},
        "v4-portfolio-plan-v1",
        run_id="controlled-002",
    )


def test_v4_generated_at_python_and_schema_have_matching_rfc3339_subset():
    schema = json.loads(
        Path("schemas/editorial-pipeline-v4/v4-artifact.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    envelope = new_artifact_envelope(
        "v4-portfolio-plan-v1",
        "controlled-002",
        {},
        generated_at="2026-09-08T10:00:00+08:00",
    )
    cases = {
        "2026-09-08T10:00:00+08:00": True,
        "2026-09-08T10:00:00.123Z": True,
        "2024-02-29T10:00:00Z": True,
        "2026-09-08 10:00:00+08:00": False,
        "2026-09-08T10:00:00": False,
        "2026-09-08T10:00:60Z": False,
        "2026-02-30T10:00:00Z": False,
        "2026-09-08T10:60:00Z": False,
        "2026-09-08T24:00:00Z": False,
        "2023-02-29T10:00:00Z": False,
        "2026-09-08t10:00:00Z": False,
        "2026-09-08T10:00:00+0800": False,
        "2026-09-08T10:00:00Z\n": False,
        "2026-09-08T10:00:00Z\r\n": False,
    }

    for generated_at, accepted in cases.items():
        candidate = {**envelope, "generated_at": generated_at}
        python_accepted = not validate_artifact_envelope(
            candidate, "v4-portfolio-plan-v1", run_id="controlled-002"
        )
        schema_accepted = not list(validator.iter_errors(candidate))
        assert python_accepted is accepted, generated_at
        assert schema_accepted is accepted, generated_at


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


def test_v4_schema_enforces_closed_envelope():
    schema_path = Path("schemas/editorial-pipeline-v4/v4-artifact.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    valid = new_artifact_envelope(
        "v4-portfolio-plan-v1",
        "controlled-002",
        {},
        generated_at="2026-09-08T10:00:00+08:00",
    )

    assert list(validator.iter_errors(valid)) == []
    assert any(error.validator == "type" for error in validator.iter_errors([]))
    for field in (
        "schema_version",
        "run_id",
        "generated_at",
        "input_hashes",
        "payload",
    ):
        missing = {key: value for key, value in valid.items() if key != field}
        assert any(
            error.validator == "required" for error in validator.iter_errors(missing)
        )
    for extra in (
        {"publication_authorization": "not_authorized"},
        {"unknown": True},
    ):
        assert any(
            error.validator == "additionalProperties"
            for error in validator.iter_errors({**valid, **extra})
        )
    for bad_timestamp in (None, "not-a-date"):
        assert list(
            validator.iter_errors({**valid, "generated_at": bad_timestamp})
        )
