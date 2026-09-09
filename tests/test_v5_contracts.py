from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from article_group.v5.contracts import (
    ARTIFACT_SCHEMA_VERSIONS,
    EXPERIMENT_DESIGNS,
    FAILURE_TYPES,
    LIFECYCLE_STATES,
    PUBLICATION_AUTHORIZATION,
    STRATEGY_STATES,
    new_artifact_envelope,
    payload_of,
    validate_v5_artifact_envelope,
)


SCHEMA_PATH = Path("schemas/editorial-pipeline-v5/v5-artifact.schema.json")


def test_v5_envelope_round_trip_and_closed_top_level():
    artifact = new_artifact_envelope(
        "v5-experiment-record-v1",
        "v5-fixture-001",
        {"x": 1},
        generated_at="2026-09-09T10:00:00+08:00",
    )

    assert set(artifact) == {
        "schema_version",
        "run_id",
        "generated_at",
        "input_hashes",
        "payload",
    }
    assert artifact["input_hashes"] == {}
    assert payload_of(artifact) == {"x": 1}
    assert validate_v5_artifact_envelope(
        artifact,
        "v5-experiment-record-v1",
        run_id="v5-fixture-001",
    ) == []

    assert "invalid:top_level" in validate_v5_artifact_envelope(
        {**artifact, "publication_authorization": "authorized"},
        "v5-experiment-record-v1",
        run_id="v5-fixture-001",
    )


def test_v5_constants_keep_publication_and_missing_metric_boundaries():
    assert PUBLICATION_AUTHORIZATION == "not_authorized"
    assert "v5-verification-v1" in ARTIFACT_SCHEMA_VERSIONS
    assert "draft" in LIFECYCLE_STATES
    assert "observational" in EXPERIMENT_DESIGNS
    assert "insufficient_data" in FAILURE_TYPES
    assert STRATEGY_STATES == (
        "provisional",
        "testing",
        "supported",
        "deprecated",
        "retired",
    )


def test_v5_envelope_rejects_unknown_identity_and_malformed_fields():
    artifact = new_artifact_envelope(
        "v5-experiment-record-v1",
        "v5-fixture-001",
        {},
        generated_at="2026-09-09T10:00:00+08:00",
    )

    errors = validate_v5_artifact_envelope(
        {
            **artifact,
            "schema_version": "unknown",
            "run_id": "v5-fixture-002",
            "generated_at": "not-a-date",
            "input_hashes": {"source.json": "not-a-sha256"},
        },
        "v5-experiment-record-v1",
        run_id="v5-fixture-001",
    )

    assert "unknown:schema_version" in errors
    assert "mismatch:run_id" in errors
    assert "invalid:generated_at" in errors
    assert "invalid:input_hashes" in errors


def test_v5_envelope_recursively_rejects_authorization_escalation():
    artifact = new_artifact_envelope(
        "v5-experiment-record-v1",
        "v5-fixture-001",
        {
            "nested": {
                "publication_authorization": "authorized",
                "items": [{"publication_authorization": "approved"}],
            }
        },
        generated_at="2026-09-09T10:00:00+08:00",
    )

    errors = validate_v5_artifact_envelope(
        artifact,
        "v5-experiment-record-v1",
        run_id="v5-fixture-001",
    )

    assert "publication_authorization_must_be_not_authorized" in errors


def test_v5_envelope_allows_recursive_not_authorized_values():
    artifact = new_artifact_envelope(
        "v5-experiment-record-v1",
        "v5-fixture-001",
        {
            "nested": {
                "publication_authorization": "not_authorized",
                "items": [{"publication_authorization": "not_authorized"}],
            }
        },
        generated_at="2026-09-09T10:00:00+08:00",
    )

    assert validate_v5_artifact_envelope(
        artifact,
        "v5-experiment-record-v1",
        run_id="v5-fixture-001",
    ) == []


def test_v5_schema_is_closed_and_matches_a_valid_envelope():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    artifact = new_artifact_envelope(
        "v5-experiment-record-v1",
        "v5-fixture-001",
        {"x": 1},
        generated_at="2026-09-09T10:00:00+08:00",
    )

    assert list(validator.iter_errors(artifact)) == []
    assert any(
        error.validator == "additionalProperties"
        for error in validator.iter_errors({**artifact, "unknown": True})
    )
    assert any(
        error.validator == "enum"
        for error in validator.iter_errors({**artifact, "schema_version": "unknown"})
    )


def test_v5_schema_rejects_authorization_escalation_recursively():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    artifact = new_artifact_envelope(
        "v5-experiment-record-v1",
        "v5-fixture-001",
        {"nested": {"publication_authorization": "authorized"}},
        generated_at="2026-09-09T10:00:00+08:00",
    )

    assert list(validator.iter_errors(artifact))
