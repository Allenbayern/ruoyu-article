"""Pure, offline helpers for Article Group V4 artifact contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

ARTIFACT_SCHEMA_VERSIONS = (
    "v4-portfolio-plan-v1",
    "v4-evidence-graph-v1",
    "v4-gap-priority-v1",
    "v4-template-signals-v1",
    "v4-effect-feedback-v1",
    "v4-recovery-actions-v1",
    "v4-verification-v1",
)

NODE_TYPES = (
    "topic",
    "claim",
    "source",
    "material",
    "title",
    "opening",
    "paragraph",
    "review",
)

EDGE_TYPES = (
    "supports",
    "supported_by",
    "captured_as",
    "materialized_as",
    "reviewed_by",
)

GAP_TYPES = (
    "title_core_fact",
    "opening_support",
    "key_fact_cross_check",
    "audience_sample",
    "industry_relevance",
    "source_failure",
    "dynamic_fact_revalidation",
    "dedupe_context",
)

EFFECT_STATES = (
    "candidate",
    "adopted",
    "measured",
    "validated",
    "reusable_pattern",
)

_SHA256_LENGTH = 64


def parse_json_object(value: str | bytes | Path) -> dict[str, Any] | None:
    """Parse JSON and return a dictionary only; malformed/non-object input is rejected."""

    try:
        text = value.read_text(encoding="utf-8") if isinstance(value, Path) else value
        parsed = json.loads(text)
    except (OSError, TypeError, ValueError, UnicodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def safe_relative_path(root: Path, raw_path: object) -> Path | None:
    """Resolve a relative path only when it remains below the supplied run root."""

    if not isinstance(raw_path, str) or not raw_path or Path(raw_path).is_absolute():
        return None
    root = root.resolve()
    candidate = (root / raw_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of an explicitly supplied file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def new_artifact_envelope(
    schema_version: str,
    run_id: str,
    payload: Mapping[str, Any],
    *,
    generated_at: str,
) -> dict[str, Any]:
    """Create a V4 envelope without adding publication or environment state."""

    return {
        "schema_version": schema_version,
        "run_id": run_id,
        "generated_at": generated_at,
        "input_hashes": {},
        "payload": dict(payload),
    }


def validate_node_type(value: object) -> list[str]:
    return [] if value in NODE_TYPES else ["invalid:node_type"]


def validate_artifact_envelope(
    value: Mapping[str, Any],
    expected_schema: str,
    *,
    run_id: str,
) -> list[str]:
    """Return stable errors for an envelope, failing closed on identity/hash issues."""

    errors: list[str] = []
    if not isinstance(value, Mapping):
        return ["invalid:artifact"]

    schema = value.get("schema_version")
    if schema is None:
        errors.append("missing:schema_version")
    elif schema not in ARTIFACT_SCHEMA_VERSIONS:
        errors.append("unknown:schema_version")
    elif schema != expected_schema:
        errors.append("mismatch:schema_version")

    if not isinstance(value.get("run_id"), str) or not value["run_id"].strip():
        errors.append("missing:run_id")
    elif value["run_id"] != run_id:
        errors.append("mismatch:run_id")

    if "generated_at" not in value:
        errors.append("missing:generated_at")
    if "payload" not in value:
        errors.append("missing:payload")
    elif not isinstance(value["payload"], Mapping):
        errors.append("invalid:payload")

    hashes = value.get("input_hashes")
    if hashes is None:
        errors.append("missing:input_hashes")
    elif not isinstance(hashes, Mapping) or any(
        not isinstance(key, str)
        or not isinstance(digest, str)
        or len(digest) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in digest.lower())
        for key, digest in hashes.items()
    ):
        errors.append("invalid:input_hashes")

    return errors
