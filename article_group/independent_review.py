"""Per-article independent review attempts. Timeout stays UNVERIFIED."""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
from typing import Any
import re

from .run_contract import (
    is_strict_run_contract,
    validate_phase_contract_fields,
    validate_run_contract,
)


SCHEMA_VERSION = "article-independent-review-v1"
DEFAULT_MAX_ATTEMPTS = 3
PASS_DECISIONS = {"approve", "approved", "pass"}
UNVERIFIED_DECISIONS = {"timeout", "evidence_insufficient"}
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _safe_path(root: Path, raw: object) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts or "\x00" in raw:
        return None
    try:
        resolved_root = root.resolve()
        resolved = (root / path).resolve()
        resolved.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _manifest_run_id(root: Path) -> str:
    """Use the batch's canonical run ID before falling back to directory name."""

    try:
        payload = json.loads((root / "batch.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        payload = None
    if isinstance(payload, Mapping):
        run_id = payload.get("run_id")
        if isinstance(run_id, str) and run_id.strip():
            return run_id.strip()
    return root.name


def build_independent_review_binding(
    run_root: str | Path,
    *,
    artifact_path: str,
    body_path: str,
    title_pack_path: str,
    created_from_run: str | None = None,
) -> dict[str, str]:
    """Create the immutable artifact binding for a new strict review."""

    root = Path(run_root)
    paths = {
        "artifact_path": artifact_path,
        "body_path": body_path,
        "title_pack_path": title_pack_path,
    }
    resolved: dict[str, Path] = {}
    for label, raw in paths.items():
        target = _safe_path(root, raw)
        if target is None or not target.is_file():
            raise ValueError(f"binding_{label}_missing_or_invalid")
        resolved[label] = target
    digests = {
        "artifact_sha256": _sha256(resolved["artifact_path"]),
        "body_sha256": _sha256(resolved["body_path"]),
        "title_pack_sha256": _sha256(resolved["title_pack_path"]),
    }
    if any(value is None for value in digests.values()):
        raise ValueError("binding_artifact_unreadable")
    return {
        "artifact_path": Path(artifact_path).as_posix(),
        "artifact_sha256": str(digests["artifact_sha256"]),
        "body_path": Path(body_path).as_posix(),
        "body_sha256": str(digests["body_sha256"]),
        "title_pack_path": Path(title_pack_path).as_posix(),
        "title_pack_sha256": str(digests["title_pack_sha256"]),
        "created_from_run": (created_from_run or _manifest_run_id(root)),
    }


def _validate_strict_binding(
    record: Mapping[str, Any],
    errors: list[str],
    *,
    run_root: str | Path | None,
    expected_artifact_path: str | None,
    expected_body_path: str | None,
    expected_title_pack_path: str | None,
    expected_run_id: str | None,
) -> None:
    required = (
        "artifact_path",
        "artifact_sha256",
        "body_path",
        "body_sha256",
        "title_pack_path",
        "title_pack_sha256",
        "created_from_run",
    )
    for field in required:
        if not _nonblank(record.get(field)):
            errors.append(f"missing:{field}")
    for field in ("artifact_sha256", "body_sha256", "title_pack_sha256"):
        value = record.get(field)
        if not isinstance(value, str) or not _SHA256.fullmatch(value):
            errors.append(f"invalid:{field}")

    expected = {
        "artifact_path": expected_artifact_path,
        "body_path": expected_body_path,
        "title_pack_path": expected_title_pack_path,
    }
    for field, expected_path in expected.items():
        if expected_path and record.get(field) != expected_path:
            errors.append("stale_review")
            errors.append(f"{field}_mismatch")
    if expected_run_id and record.get("created_from_run") != expected_run_id:
        errors.append("stale_review")
        errors.append("created_from_run_mismatch")

    root = Path(run_root) if run_root is not None else None
    if root is None:
        return
    actuals = (
        ("artifact_path", "artifact_sha256"),
        ("body_path", "body_sha256"),
        ("title_pack_path", "title_pack_sha256"),
        ("draft_path", "draft_sha256"),
    )
    for path_field, hash_field in actuals:
        target = _safe_path(root, record.get(path_field))
        if target is None or not target.is_file():
            errors.append("stale_review")
            errors.append(f"{path_field}_missing_or_invalid")
            continue
        actual = _sha256(target)
        if actual is None or actual != str(record.get(hash_field, "")).lower():
            errors.append("stale_review")
            errors.append(f"{hash_field}_mismatch")


def validate_independent_review_record(
    record: Mapping[str, Any] | object,
    *,
    run_root: str | Path | None = None,
    expected_artifact_path: str | None = None,
    expected_body_path: str | None = None,
    expected_title_pack_path: str | None = None,
    expected_run_id: str | None = None,
    strict: bool | None = None,
) -> list[str]:
    if not isinstance(record, Mapping):
        return ["record_must_be_an_object"]
    errors: list[str] = []
    declared_strict = is_strict_run_contract(record)
    strict = declared_strict if strict is None else bool(strict or declared_strict)
    if is_strict_run_contract(record):
        errors.extend(validate_run_contract(record))
    if strict:
        errors.extend(validate_phase_contract_fields(record, "title"))
    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version")
    for field in ("article_task_id", "article_id", "draft_path", "status", "decision", "next_step"):
        if not _nonblank(record.get(field)):
            errors.append(f"missing:{field}")
    digest = record.get("draft_sha256")
    if not _nonblank(digest) or not _SHA256.fullmatch(str(digest)):
        errors.append("invalid:draft_sha256")
    attempt = record.get("attempt")
    max_attempts = record.get("max_attempts", DEFAULT_MAX_ATTEMPTS)
    if type(attempt) is not int or attempt < 1:
        errors.append("invalid:attempt")
    if type(max_attempts) is not int or max_attempts < 1:
        errors.append("invalid:max_attempts")
    if record.get("publication_authorization", "not_authorized") != "not_authorized":
        errors.append("publication_authorization_must_be_not_authorized")
    status = record.get("status")
    decision = record.get("decision")
    if status == "UNVERIFIED" or decision == "timeout":
        if not _nonblank(record.get("timeout_reason")):
            errors.append("missing:timeout_reason")
        if decision in PASS_DECISIONS:
            errors.append("timeout_cannot_pass")
    if record.get("l2_required") is True and not _nonblank(record.get("l2_risk_basis")):
        errors.append("l2_requires_risk_basis")
    if strict:
        _validate_strict_binding(
            record,
            errors,
            run_root=run_root,
            expected_artifact_path=expected_artifact_path,
            expected_body_path=expected_body_path,
            expected_title_pack_path=expected_title_pack_path,
            expected_run_id=expected_run_id,
        )
    return sorted(set(errors))


def evaluate_independent_review(
    record: Mapping[str, Any] | object,
    **kwargs: Any,
) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        return {"status": "invalid", "pass": False, "errors": ["record_must_be_an_object"]}
    errors = validate_independent_review_record(record, **kwargs)
    status = record.get("status") if isinstance(record.get("status"), str) else "invalid"
    decision = record.get("decision")
    passed = (
        not errors
        and status != "UNVERIFIED"
        and decision in PASS_DECISIONS
    )
    return {
        "status": "stale_review" if "stale_review" in errors else (status if not errors else "invalid"),
        "decision": decision,
        "pass": passed,
        "errors": errors,
    }


def plan_resume(
    previous: Mapping[str, Any] | object,
    *,
    current_draft_path: str,
    current_draft_sha256: str,
) -> dict[str, Any]:
    if not isinstance(previous, Mapping):
        return {"action": "blocked", "reason": "invalid_previous_record"}
    errors = validate_independent_review_record(previous)
    if errors:
        return {"action": "blocked", "reason": "invalid_previous_record", "errors": errors}
    status = previous.get("status")
    decision = previous.get("decision")
    if status != "UNVERIFIED" and decision != "timeout":
        return {"action": "blocked", "reason": "not_resumable"}
    attempt = int(previous.get("attempt", 1))
    max_attempts = int(previous.get("max_attempts", DEFAULT_MAX_ATTEMPTS))
    if attempt >= max_attempts:
        return {"action": "blocked", "reason": "retry_limit"}
    resumed = {
        "action": "resume_article",
        "article_task_id": previous.get("article_task_id"),
        "article_id": previous.get("article_id"),
        "attempt": attempt + 1,
        "max_attempts": max_attempts,
        "draft_path": current_draft_path,
        "draft_sha256": current_draft_sha256,
        "scope": "single_article",
        "rerun_batch": False,
        "previous_status": status,
        "previous_timeout_reason": previous.get("timeout_reason"),
        "next_step": "retry_narrowed_review",
        "l2_required": previous.get("l2_required") is True,
        "l2_risk_basis": previous.get("l2_risk_basis") or "",
        "publication_authorization": "not_authorized",
    }
    # A retry must keep the exact artifact chain that was reviewed.  Dropping
    # any of these fields would make the next attempt look unbound and could
    # accidentally pair an old review with a new title or delivery artifact.
    for field in (
        "artifact_path",
        "artifact_sha256",
        "body_path",
        "body_sha256",
        "title_pack_path",
        "title_pack_sha256",
        "created_from_run",
        "production_contract",
        "brief_contract",
        "title_contract",
        "legacy_compatibility",
    ):
        if field in previous:
            resumed[field] = previous[field]
    return resumed


__all__ = [
    "build_independent_review_binding",
    "DEFAULT_MAX_ATTEMPTS",
    "SCHEMA_VERSION",
    "evaluate_independent_review",
    "plan_resume",
    "validate_independent_review_record",
]
