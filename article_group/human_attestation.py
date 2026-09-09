"""Validation of explicit human editor attestations."""

from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
import re
from typing import Any


def _resolve_inside(root: Path, raw: object) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts or "\x00" in raw:
        return None
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return resolved


def validate_human_attestation(
    attestation: dict[str, Any] | None,
    run_root: Path,
    article_id: str,
    delivery_htmls: list[Path],
    *,
    review_surface: str = "html_delivery",
    markdown_paths: list[Path] | None = None,
) -> list[str]:
    """Validate the attestation for the selected review surface.

    ``human-attestation-v1`` remains the strict HTML-bound historical format.
    New Markdown batches use ``human-attestation-v3`` and cannot smuggle HTML
    bindings into the attestation.
    """
    if not isinstance(attestation, dict):
        return ["human_attestation_missing"]
    errors: list[str] = []
    if review_surface == "markdown_codex":
        return _validate_markdown_attestation(
            attestation,
            run_root,
            article_id,
            markdown_paths or [],
        )

    return _validate_html_attestation(attestation, run_root, article_id, delivery_htmls)


def _validate_common(
    attestation: dict[str, Any], article_id: str, schema_version: str
) -> list[str]:
    errors: list[str] = []
    required = (
        "schema_version", "article_id", "reviewer_kind", "reviewer_role",
        "reviewer_identity", "reviewed_at", "decision", "attestation_ref",
    )
    for field in required:
        if not isinstance(attestation.get(field), str) or not attestation[field].strip():
            errors.append(f"human_attestation_missing:{field}")
    if attestation.get("schema_version") != schema_version:
        errors.append("human_attestation_schema_version_invalid")
    if attestation.get("article_id") != article_id:
        errors.append("human_attestation_article_id_mismatch")
    if attestation.get("reviewer_kind") != "human":
        errors.append("reviewer_kind_must_be_human")
    if attestation.get("reviewer_role") != "human_editor":
        errors.append("reviewer_role_must_be_human_editor")
    identity = str(attestation.get("reviewer_identity", "")).strip().lower()
    if any(token in identity for token in ("controller", "codex", "luna", "terra", "sol", "agent", "model", "ai")):
        errors.append("reviewer_identity_not_human")
    try:
        reviewed_at = datetime.fromisoformat(str(attestation.get("reviewed_at", "")))
        if reviewed_at.tzinfo is None:
            errors.append("human_attestation_reviewed_at_timezone_missing")
    except ValueError:
        errors.append("human_attestation_reviewed_at_invalid")
    if attestation.get("decision") not in {"accept", "approved"}:
        errors.append("human_attestation_decision_not_accept")
    return errors


def _validate_html_attestation(
    attestation: dict[str, Any],
    run_root: Path,
    article_id: str,
    delivery_htmls: list[Path],
) -> list[str]:
    errors = _validate_common(attestation, article_id, "human-attestation-v1")
    for field in ("html_path", "html_sha256"):
        if not isinstance(attestation.get(field), str) or not attestation[field].strip():
            errors.append(f"human_attestation_missing:{field}")

    target = _resolve_inside(run_root, attestation.get("html_path"))
    delivery_targets = {path.resolve() for path in delivery_htmls}
    if target is None or not target.is_file() or target not in delivery_targets:
        errors.append("human_attestation_html_not_current_delivery")
    declared_hash = attestation.get("html_sha256")
    if not isinstance(declared_hash, str) or len(declared_hash) != 64:
        errors.append("human_attestation_html_hash_invalid")
    elif target is not None and target.is_file():
        actual_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual_hash != declared_hash.lower():
            errors.append("human_attestation_html_hash_mismatch")
    return errors


def _validate_markdown_attestation(
    attestation: dict[str, Any],
    run_root: Path,
    article_id: str,
    markdown_paths: list[Path],
) -> list[str]:
    errors = _validate_common(attestation, article_id, "human-attestation-v3")
    for field in ("markdown_path", "markdown_sha256"):
        if not isinstance(attestation.get(field), str) or not attestation[field].strip():
            errors.append(f"human_attestation_missing:{field}")
    if "html_path" in attestation or "html_sha256" in attestation:
        errors.append("human_attestation_html_fields_forbidden")

    target = _resolve_inside(run_root, attestation.get("markdown_path"))
    markdown_targets = {path.resolve() for path in markdown_paths}
    if target is None or not target.is_file() or target not in markdown_targets:
        errors.append("human_attestation_markdown_not_current_review")
    declared_hash = attestation.get("markdown_sha256")
    if not isinstance(declared_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", declared_hash):
        errors.append("human_attestation_markdown_hash_invalid")
    elif target is not None and target.is_file():
        actual_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual_hash != declared_hash.lower():
            errors.append("human_attestation_markdown_hash_mismatch")
    return errors
