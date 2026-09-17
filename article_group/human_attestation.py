"""Validation of explicit human editor attestations."""

from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
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
) -> list[str]:
    if not isinstance(attestation, dict):
        return ["human_attestation_missing"]
    errors: list[str] = []
    required = (
        "schema_version", "article_id", "reviewer_kind", "reviewer_role",
        "reviewer_identity", "reviewed_at", "decision", "html_path",
        "html_sha256", "attestation_ref",
    )
    for field in required:
        if not isinstance(attestation.get(field), str) or not attestation[field].strip():
            errors.append(f"human_attestation_missing:{field}")
    if attestation.get("schema_version") != "human-attestation-v1":
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
