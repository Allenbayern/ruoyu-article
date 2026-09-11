"""Per-article independent review attempts. Timeout stays UNVERIFIED."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import re


SCHEMA_VERSION = "article-independent-review-v1"
DEFAULT_MAX_ATTEMPTS = 3
PASS_DECISIONS = {"approve", "approved", "pass"}
UNVERIFIED_DECISIONS = {"timeout", "evidence_insufficient"}
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_independent_review_record(record: Mapping[str, Any] | object) -> list[str]:
    if not isinstance(record, Mapping):
        return ["record_must_be_an_object"]
    errors: list[str] = []
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
    return sorted(set(errors))


def evaluate_independent_review(record: Mapping[str, Any] | object) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        return {"status": "invalid", "pass": False, "errors": ["record_must_be_an_object"]}
    errors = validate_independent_review_record(record)
    status = record.get("status") if isinstance(record.get("status"), str) else "invalid"
    decision = record.get("decision")
    passed = (
        not errors
        and status != "UNVERIFIED"
        and decision in PASS_DECISIONS
    )
    return {
        "status": status if not errors else "invalid",
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
    return {
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


__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "SCHEMA_VERSION",
    "evaluate_independent_review",
    "plan_resume",
    "validate_independent_review_record",
]
