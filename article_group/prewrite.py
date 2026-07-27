"""Pre-write validation gates for candidate pools and editorial selection.

This module validates controller-supplied structured records before any article
draft enters R6. It never fetches sources, ranks topics, or writes reader content.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse


class PrewriteValidationError(ValueError):
    """Raised when pre-write constraints are not satisfied."""


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _parse_timestamp(iso_str: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(iso_str)
        # Require timezone
        if dt.tzinfo is None:
            return None
        return dt
    except (ValueError, TypeError):
        return None


def validate_candidate_pool(pool: dict[str, Any]) -> list[str]:
    """Return deterministic reasons the candidate pool cannot proceed to editorial selection."""
    errors: list[str] = []

    if not isinstance(pool, dict):
        return ["candidate_pool_must_be_a_dict"]

    # Time / metadata
    if not pool.get("timezone"):
        errors.append("candidate_pool_missing_timezone")
    observed_at = _parse_timestamp(pool.get("observed_at", ""))
    if observed_at is None:
        errors.append("candidate_pool_invalid_or_missing_observed_at")
    elif observed_at > _now_utc():
        errors.append("candidate_pool_future_observed_at")

    # Candidates cardinality
    candidates = pool.get("candidates", [])
    if not isinstance(candidates, list):
        return errors + ["candidates_must_be_a_list"]
    if len(candidates) < 10:
        errors.append(f"candidate_pool_requires_at_least_10_candidates_got_{len(candidates)}")

    required_candidate_fields = (
        "candidate_id", "work", "core_person_or_event", "primary_atom",
        "reader_intent", "angle", "title_skeleton", "ending_destination",
        "event_time", "observed_at", "freshness_window", "current_trigger",
        "content_value_scores", "source_roles", "evidence_atom_ids",
        "concrete_anchor_ids", "recommendation",
    )
    required_score_dimensions = ("emotion", "narrative", "share", "human", "freshness")

    for candidate in candidates:
        cid = candidate.get("candidate_id", "unknown")

        # Required fields
        for field in required_candidate_fields:
            if not candidate.get(field) and candidate.get(field) != 0:
                errors.append(f"candidate_{cid}_missing_{field}")

        # Numeric scores
        scores = candidate.get("content_value_scores")
        if isinstance(scores, dict):
            for dim in required_score_dimensions:
                if dim not in scores or not isinstance(scores[dim], (int, float)):
                    errors.append(f"candidate_{cid}_invalid_or_missing_score_{dim}")
        else:
            errors.append(f"candidate_{cid}_content_value_scores_must_be_dict")

        # Reject reason required for Archive/Reject/Wait
        recommendation = candidate.get("recommendation", "")
        reason = candidate.get("reject_or_wait_reason", "")
        if recommendation in ("Archive", "Reject", "Wait") and not reason:
            errors.append(f"candidate_{cid}_missing_reject_reason_for_{recommendation}")

        # Timestamps
        candidate_event = _parse_timestamp(candidate.get("event_time", ""))
        candidate_observed = _parse_timestamp(candidate.get("observed_at", ""))
        if candidate_event is None:
            errors.append(f"candidate_{cid}_invalid_event_time")
        elif candidate_event > _now_utc():
            errors.append(f"candidate_{cid}_future_event_time")
        if candidate_observed is None:
            errors.append(f"candidate_{cid}_invalid_observed_at")

    return errors


def validate_slot_decisions(
    decisions: dict[str, Any],
    candidate_ids: set[str] | None = None,
) -> list[str]:
    """Return deterministic reasons slot assignments cannot proceed.

    When ``candidate_ids`` is supplied, every primary and backup id must be present.
    """
    errors: list[str] = []
    slots = decisions.get("slots", [])
    if len(slots) != 3:
        return [f"slot_decisions_require_exactly_3_slots_got_{len(slots)}"]

    primary_ids: set[str] = set()
    backup_ids: set[str] = set()
    all_ids: set[str] = set()

    for slot in slots:
        slot_label = slot.get("slot", "unknown")
        primary = slot.get("primary_candidate_id", "")
        backup = slot.get("backup_candidate_id", "")

        if not primary or not backup:
            errors.append(f"slot_{slot_label}_missing_primary_or_backup")
            continue

        if primary in primary_ids:
            errors.append(f"slot_{slot_label}_duplicate_primary_{primary}")
        if backup in backup_ids:
            errors.append(f"slot_{slot_label}_duplicate_backup_{backup}")

        # Primary cannot appear as any other slot's backup
        if primary in backup_ids:
            errors.append(f"slot_{slot_label}_primary_{primary}_appears_as_another_backup")

        # Backup cannot appear as any other slot's primary
        if backup in primary_ids:
            errors.append(f"slot_{slot_label}_backup_{backup}_appears_as_another_primary")

        primary_ids.add(primary)
        backup_ids.add(backup)
        all_ids.add(primary)
        all_ids.add(backup)

    expected_slots = {"A", "B", "C"}
    actual_slots = {slot.get("slot", "") for slot in slots}
    if actual_slots != expected_slots:
        errors.append(f"slot_labels_must_be_A_B_C_got_{sorted(actual_slots)}")

    if candidate_ids:
        for cid in sorted(all_ids):
            if cid not in candidate_ids:
                errors.append(f"slot_references_unknown_candidate_{cid}")

    return errors


def _hours_delta(earlier: datetime, later: datetime) -> float:
    return (later - earlier).total_seconds() / 3600


def classify_freshness(
    *,
    event_time: str,
    observed_at: str,
    freshness_window: str,
    current_trigger: str,
) -> str:
    """Return 'ok' or an error tag explaining why the freshness claim is invalid.

    Rules:
    - same-day: current_trigger must have occurred within 24 hours of observed_at.
    - fermenting-1-3d: >24 and <=72 hours between event_time and observed_at.
    - revival: original event may be old, but current_trigger must be non-empty.
    - evergreen: no current trigger needed, but cannot claim same-day/fermenting.
    - observed_at must be >= event_time.
    """
    evt = _parse_timestamp(event_time)
    obs = _parse_timestamp(observed_at)
    if evt is None or obs is None:
        return "invalid_timestamp_format"

    hours = _hours_delta(evt, obs)
    if hours < 0:
        return "observed_before_event"

    trigger = (current_trigger or "").strip()
    window = (freshness_window or "").strip()

    if window == "same-day":
        if hours > 24:
            return f"same_day_requires_event_within_24h_got_{hours:.0f}h"
        if not trigger:
            return "same_day_requires_current_trigger"
        return "ok"

    if window == "fermenting-1-3d":
        if hours <= 24:
            return f"fermenting_requires_event_older_than_24h_got_{hours:.0f}h"
        if hours > 72:
            return f"fermenting_requires_event_within_72h_got_{hours:.0f}h"
        if not trigger:
            return "fermenting_requires_current_trigger"
        return "ok"

    if window == "revival":
        if not trigger:
            return "revival_requires_current_trigger"
        return "ok"

    if window == "evergreen":
        if trigger and hours <= 24:
            return "evergreen_with_active_trigger_consider_other_window"
        return "ok"

    return f"unknown_freshness_window_{window}"


# --- source snapshot and locator verification ---


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_relative(declared: str) -> bool:
    candidate = Path(declared)
    return not (candidate.is_absolute() or ".." in candidate.parts)


def _is_placeholder_url(url: object) -> bool:
    normalized = str(url).strip().lower()
    parsed = urlparse(normalized)
    hostname = (parsed.hostname or "").rstrip(".")
    placeholder_hosts = {
        "example.com",
        "example.net",
        "example.org",
        "www.example.com",
        "www.example.net",
        "www.example.org",
    }
    return hostname in placeholder_hosts


def validate_source_manifest(manifest: dict[str, Any], run_root: Path) -> list[str]:
    """Verify that every declared source exists in run_root with matching digest."""
    errors: list[str] = []
    sources = manifest.get("sources", [])
    if not isinstance(sources, list) or not sources:
        return ["source_manifest_missing_or_empty_sources"]

    confirmed_primary_by_digest: dict[str, list[tuple[str, str]]] = {}

    for src in sources:
        sid = src.get("source_id", "unknown")
        rel = src.get("relative_path", "")
        declared_digest = src.get("sha256", "")

        if src.get("role") == "confirmed-primary" and str(src.get("url", "")).strip().lower().startswith("synthetic://"):
            errors.append(f"source_{sid}_confirmed_primary_synthetic_url")
        if src.get("role") == "confirmed-primary" and _is_placeholder_url(src.get("url", "")):
            errors.append(f"source_{sid}_confirmed_primary_placeholder_url")

        if not rel or not _safe_relative(rel):
            errors.append(f"source_{sid}_unsafe_or_missing_relative_path")
            continue

        resolved = (run_root / rel).resolve()
        if run_root.resolve() not in resolved.parents or not resolved.is_file():
            errors.append(f"source_{sid}_file_not_found")
            continue

        actual_digest = _sha256_file(resolved)
        if actual_digest != declared_digest:
            errors.append(f"source_{sid}_digest_mismatch")
        if src.get("role") == "confirmed-primary":
            text = resolved.read_text(encoding="utf-8", errors="replace")
            if re.search(r"本文由\s*ai\s*生成", text, flags=re.IGNORECASE):
                errors.append(f"source_{sid}_confirmed_primary_ai_generated_snapshot")
            confirmed_primary_by_digest.setdefault(actual_digest, []).append(
                (str(sid), str(src.get("independence_group", "")))
            )

    for duplicate_sources in confirmed_primary_by_digest.values():
        source_ids = sorted(source_id for source_id, _ in duplicate_sources)
        groups = {group for _, group in duplicate_sources}
        if len(source_ids) > 1 and len(groups) > 1:
            errors.append(
                "confirmed_primary_duplicate_digest_claims_independence_"
                + "_".join(source_ids)
            )

    return errors


def _normalize_locator_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def validate_claim_locators(
    claims: list[dict[str, Any]],
    manifest: dict[str, Any],
    run_root: Path,
) -> list[str]:
    """Verify that each claim's locator text appears in the corresponding source snapshot."""
    errors: list[str] = []

    source_map: dict[str, dict[str, Any]] = {}
    for src in manifest.get("sources", []):
        source_map[src.get("source_id", "")] = src

    for claim in claims:
        cid = claim.get("claim_id", "unknown")
        sid = claim.get("source_id", "")
        locator = claim.get("locator", "")

        if sid not in source_map:
            errors.append(f"claim_{cid}_unknown_source_{sid}")
            continue

        src = source_map[sid]
        rel = src.get("relative_path", "")
        resolved = (run_root / rel).resolve()
        try:
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError:
            errors.append(f"claim_{cid}_cannot_read_source_{sid}")
            continue

        normalized_text = _normalize_locator_text(text)
        normalized_locator = _normalize_locator_text(locator)
        if normalized_locator not in normalized_text:
            errors.append(f"claim_{cid}_locator_not_found_in_{sid}")

    return errors


# --- material sufficiency ---


def assess_material_sufficiency(
    *,
    evidence_atom_ids: list[str],
    concrete_anchor_ids: list[str],
    source_roles: list[str],
) -> dict[str, Any]:
    """Return a pre-write decision based on whether the topic can support a long-form article.

    The capacity score is a conservative routing signal, not a quality judgment.
    It does not replace editorial review or source truth verification.
    """
    atoms = len(evidence_atom_ids) if isinstance(evidence_atom_ids, list) else 0
    anchors = len(concrete_anchor_ids) if isinstance(concrete_anchor_ids, list) else 0
    roles = len(source_roles) if isinstance(source_roles, list) else 0

    capacity = (
        250 * atoms
        + 200 * anchors
        + 150 * max(0, roles - 1)
    )

    if capacity >= 1500:
        decision = "ready-for-brief"
    else:
        decision = "H4 draft-only"

    return {
        "decision": decision,
        "capacity_points": capacity,
        "atoms": atoms,
        "anchors": anchors,
        "source_roles": roles,
    }


# --- per-article stage validation ---


def _article_chinese_char_count(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    return len(re.sub(r"[^\u4e00-\u9fff]", "", text))


def validate_article_stage(
    article: dict[str, Any],
    evidence_claim_ids: set[str],
    run_root: Path,
) -> list[str]:
    """Validate a single article draft immediately after it is written.

    This runs per-article before the batch gate. Failure means H3 or H4 for
    this slot without blocking the other two.
    """
    errors: list[str] = []
    aid = article.get("article_id", "unknown")
    slot = article.get("slot", "unknown")

    # File existence and safety
    for field in ("markdown_path", "evidence_pack_path", "writing_brief_path"):
        declared = article.get(field, "")
        if not declared or not _safe_relative(declared):
            errors.append(f"article_{aid}_{field}_unsafe_or_missing")
            continue
        resolved = (run_root / declared).resolve()
        if run_root.resolve() not in resolved.parents or not resolved.is_file():
            errors.append(f"article_{aid}_{field}_not_found")

    if errors:
        return errors

    # Chinese character count from the actual Markdown file
    md_path = (run_root / article["markdown_path"]).resolve()
    char_count = _article_chinese_char_count(md_path)
    if not 1500 <= char_count <= 2200:
        errors.append(f"article_{aid}_character_count_{char_count}_out_of_1500_2200")

    # Title length
    title = article.get("title", "")
    title_chars = len(re.sub(r"[^\u4e00-\u9fff]", "", title))
    if title_chars > 30:
        errors.append(f"article_{aid}_title_too_long_{title_chars}")

    # Must-prove claim coverage
    claim_ids = {
        cm.get("claim_id", "")
        for cm in (article.get("claim_mappings") or [])
        if isinstance(cm, dict) and cm.get("claim_id")
    }
    missing = evidence_claim_ids - claim_ids
    if missing:
        errors.append(f"article_{aid}_missing_must_prove_claims_{','.join(sorted(missing))}")

    # Concrete support types
    support_types = article.get("concrete_support_types", [])
    if isinstance(support_types, (list, tuple)):
        norm = {s.strip() for s in support_types if isinstance(s, str) and s.strip()}
    else:
        norm = set()
    if len(norm) < 2:
        errors.append(f"article_{aid}_insufficient_concrete_support")

    # HTML — must be withheld or not_requested
    html_state = article.get("html_delivery_state", "")
    if html_state not in ("withheld", "not_requested"):
        errors.append(f"article_{aid}_html_must_be_withheld")

    # Publication — must be not_authorized
    auth = article.get("publication_authorization", "not_authorized")
    if auth != "not_authorized":
        errors.append(f"article_{aid}_must_be_not_authorized")

    return errors
