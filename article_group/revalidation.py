"""Fail-closed validation for publication-time dynamic-fact revalidation."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_path(root: Path, raw: object) -> Path | None:
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


def _required_claim_ids(fact_card: dict[str, Any]) -> set[str]:
    explicit = fact_card.get("revalidation_claim_ids")
    if isinstance(explicit, list) and all(isinstance(item, str) and item.strip() for item in explicit):
        return {item.strip() for item in explicit}
    return {
        str(claim.get("claim_id"))
        for claim in fact_card.get("permitted_claims", [])
        if isinstance(claim, dict) and isinstance(claim.get("claim_id"), str)
    }


def validate_revalidation_record(
    fact_card: dict[str, Any],
    record: dict[str, Any] | None,
    run_root: Path,
    *,
    now: datetime | None = None,
) -> list[str]:
    """Validate a new source snapshot for every dynamic claim in a fact card."""
    if fact_card.get("update_required_before_publication") != "yes":
        return []
    if record is None:
        return ["revalidation_missing"]

    errors: list[str] = []
    if record.get("schema_version") != "revalidation-v1":
        errors.append("revalidation_schema_version_invalid")
    if record.get("article_id") != fact_card.get("article_id"):
        errors.append("revalidation_article_id_mismatch")
    if record.get("decision") != "pass":
        errors.append("revalidation_decision_not_pass")

    checked_at = _parse_timestamp(record.get("checked_at"))
    data_as_of = _parse_timestamp(fact_card.get("data_as_of"))
    current = now or datetime.now(timezone.utc)
    if checked_at is None:
        errors.append("revalidation_checked_at_invalid")
    else:
        if checked_at > current:
            errors.append("revalidation_checked_at_in_future")
        if data_as_of is not None and checked_at <= data_as_of:
            errors.append("revalidation_not_newer_than_fact_card")

    required = _required_claim_ids(fact_card)
    claims = record.get("claims")
    if not isinstance(claims, list):
        errors.append("revalidation_claims_invalid")
        claims = []
    by_id = {
        claim.get("claim_id"): claim
        for claim in claims
        if isinstance(claim, dict) and isinstance(claim.get("claim_id"), str)
    }
    actual = set(by_id)
    if actual != required:
        errors.append("revalidation_claim_coverage_mismatch")

    for claim_id in sorted(required):
        claim = by_id.get(claim_id)
        if not isinstance(claim, dict):
            errors.append(f"revalidation_claims_missing_snapshot:{claim_id}")
            continue
        if claim.get("status") != "confirmed":
            errors.append(f"revalidation_claim_status_not_confirmed:{claim_id}")
        max_age = claim.get("max_age_hours")
        if isinstance(max_age, bool) or not isinstance(max_age, (int, float)) or max_age <= 0:
            errors.append(f"revalidation_max_age_invalid:{claim_id}")
        elif checked_at is not None and (current - checked_at).total_seconds() > float(max_age) * 3600:
            errors.append(f"revalidation_stale:{claim_id}")

        snapshot = claim.get("source_snapshot")
        if not isinstance(snapshot, dict):
            errors.append(f"revalidation_claims_missing_snapshot:{claim_id}")
            continue
        path = _safe_path(run_root, snapshot.get("path"))
        if path is None or not path.is_file():
            errors.append(f"revalidation_snapshot_path_invalid:{claim_id}")
            continue
        declared_hash = snapshot.get("sha256")
        if not isinstance(declared_hash, str) or _sha256(path) != declared_hash.lower():
            errors.append(f"revalidation_snapshot_hash_mismatch:{claim_id}")
        locator = snapshot.get("locator")
        if not isinstance(locator, str) or not locator.strip():
            errors.append(f"revalidation_locator_missing:{claim_id}")
        else:
            try:
                source_text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                errors.append(f"revalidation_snapshot_unreadable:{claim_id}")
            else:
                if locator not in source_text:
                    errors.append(f"revalidation_locator_not_found:{claim_id}")
    return errors
