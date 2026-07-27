"""Offline, synthetic-only gates for a three-slot article batch.

This module never fetches sources, drafts reader content, renders HTML, sends messages,
or publishes. It validates controller-supplied records and creates a review-ready
manifest for a first controlled production run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import json
import re

SLOTS = ("A", "B", "C")
EDITORIAL_READY = "R7 editorial-ready"
MECHANICALLY_VERIFIED = "R7 mechanically-verified"
AWAITING_INDEPENDENT_REVIEW = "R7.5 awaiting-independent-review"
REVIEW_READY = "R8 review-ready"
# Articles eligible for offline mechanical batch validation / build_controlled_run.
MECHANICAL_INPUT_STATES = {EDITORIAL_READY, MECHANICALLY_VERIFIED}
# Manifest states that may be promoted to R8 only with Sol approve + controller accept.
R8_PROMOTION_SOURCE_STATES = {MECHANICALLY_VERIFIED, AWAITING_INDEPENDENT_REVIEW}
CONTROLLER_ACCEPTANCE_VALUES = {
    "accepted",
    "approved_after_re-review",
    "controller_accepted_r8_review_ready",
}
TERMINAL_STATES = {"H4 draft-only", "H5 rejected", "A archived"}

ALLOWED_TRANSITIONS = {
    "R0 radar": {"R1 normalized-candidates"},
    "R1 normalized-candidates": {"R2 editorial-queue", "A archived", "H5 rejected"},
    "R2 editorial-queue": {"R3 slots-locked", "A archived", "H5 rejected"},
    "R3 slots-locked": {"R4 evidence-ready", "H1 waiting-source", "H2 backup-switch"},
    "R4 evidence-ready": {"R5 brief-ready", "H1 waiting-source", "H4 draft-only"},
    "R5 brief-ready": {"R6 drafting", "H2 backup-switch", "H4 draft-only"},
    "R6 drafting": {EDITORIAL_READY, "H3 needs-revision", "H4 draft-only"},
    # Mechanical green is not R8: editorial-ready may only advance to mechanical verify.
    EDITORIAL_READY: {MECHANICALLY_VERIFIED, "H3 needs-revision", "H4 draft-only"},
    MECHANICALLY_VERIFIED: {
        AWAITING_INDEPENDENT_REVIEW,
        "H3 needs-revision",
        "H4 draft-only",
    },
    AWAITING_INDEPENDENT_REVIEW: {REVIEW_READY, "H3 needs-revision", "H4 draft-only"},
    REVIEW_READY: {"H3 needs-revision", "H4 draft-only"},
    "H1 waiting-source": {"R4 evidence-ready", "H2 backup-switch", "H4 draft-only"},
    "H2 backup-switch": {"R3 slots-locked", "H4 draft-only"},
    "H3 needs-revision": {"R6 drafting", EDITORIAL_READY, "H4 draft-only"},
}


class BatchValidationError(ValueError):
    """Raised when a batch cannot enter the controlled review-ready handoff."""


def validate_transition(current: str, target: str) -> None:
    if current in TERMINAL_STATES:
        raise BatchValidationError(f"terminal_state_cannot_advance:{current}")
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise BatchValidationError(f"invalid_transition:{current}->{target}")


def _nonblank_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_delivery_authorization(record: dict[str, Any]) -> list[str]:
    authorization = record.get("publication_authorization", "not_authorized")
    audit_fields = (
        "authorization_by",
        "authorized_at",
        "authorization_ref",
        "authorized_publication_scope",
    )
    if authorization == "not_authorized":
        # Missing fields or exactly empty strings are allowed. Whitespace and all
        # non-string values are rejected so metadata cannot hide behind truthiness.
        invalid_fields = [
            field
            for field in audit_fields
            if field in record and (not isinstance(record[field], str) or record[field] != "")
        ]
        return ["authorization_metadata_must_be_blank_when_not_authorized"] if invalid_fields else []
    if authorization != "granted":
        return ["invalid_publication_authorization"]
    missing = [field for field in audit_fields if not _nonblank_string(record.get(field))]
    return [f"missing_authorization_metadata:{','.join(missing)}"] if missing else []


def _require(record: dict[str, Any], fields: tuple[str, ...], prefix: str) -> list[str]:
    return [f"{prefix}:{field}" for field in fields if not record.get(field)]


def _chinese_character_count(text: str) -> int:
    return len(re.sub(r"[^\u4e00-\u9fff]", "", text))


def _title_length(title: str) -> int:
    return _chinese_character_count(title)


def _normalized_claim_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def validate_claim_inventory(article: dict[str, Any], markdown_text: str | None = None) -> list[str]:
    """Return deterministic errors for a declared, verifiable material-claim inventory."""
    aid = article.get("article_id", "unknown")
    errors: list[str] = []
    mappings = article.get("claim_mappings")
    if not isinstance(mappings, list) or not mappings:
        return [f"claim_mappings_invalid:{aid}"]

    mapping_ids: list[str] = []
    expected_status = {"fact": "direct", "attribution": "attributed", "inference": "inference"}
    for index, mapping in enumerate(mappings):
        if not isinstance(mapping, dict):
            errors.append(f"claim_mapping_invalid:{aid}:{index}")
            continue
        claim_id = mapping.get("claim_id")
        label = claim_id.strip() if _nonblank_string(claim_id) else str(index)
        if not _nonblank_string(claim_id):
            errors.append(f"claim_mapping_missing:{aid}:{label}:claim_id")
        else:
            mapping_ids.append(claim_id.strip())
        for field in ("claim_text", "draft_locator", "claim_type", "support_status"):
            if not _nonblank_string(mapping.get(field)):
                errors.append(f"claim_mapping_missing:{aid}:{label}:{field}")

        claim_type = mapping.get("claim_type")
        if not _nonblank_string(claim_type):
            errors.append(f"claim_mapping_invalid_type:{aid}:{label}")
        elif claim_type not in expected_status:
            errors.append(f"claim_mapping_invalid_type:{aid}:{label}:{claim_type}")
        else:
            if mapping.get("support_status") != expected_status[claim_type]:
                errors.append(f"claim_mapping_support_status_mismatch:{aid}:{label}")
            if claim_type in {"fact", "attribution"}:
                if not _nonblank_string(mapping.get("source_id")):
                    errors.append(f"claim_mapping_missing_source:{aid}:{label}")
                if not _nonblank_string(mapping.get("locator")):
                    errors.append(f"claim_mapping_missing_locator:{aid}:{label}")
            elif not _nonblank_string(mapping.get("limitation")):
                errors.append(f"claim_mapping_missing_limitation:{aid}:{label}")

        if markdown_text is not None and _nonblank_string(mapping.get("draft_locator")):
            if _normalized_claim_text(mapping["draft_locator"]) not in _normalized_claim_text(markdown_text):
                errors.append(f"claim_mapping_draft_locator_not_found:{aid}:{label}")

    duplicates = sorted({claim_id for claim_id in mapping_ids if mapping_ids.count(claim_id) > 1})
    errors.extend(f"duplicate_claim_id:{aid}:{claim_id}" for claim_id in duplicates)

    material_ids = article.get("material_claim_ids")
    if not isinstance(material_ids, list) or not material_ids:
        errors.append(f"material_claim_ids_invalid:{aid}")
    else:
        valid_material_ids = [item.strip() for item in material_ids if _nonblank_string(item)]
        if len(valid_material_ids) != len(material_ids) or len(set(valid_material_ids)) != len(valid_material_ids):
            errors.append(f"material_claim_ids_invalid:{aid}")
        missing_mappings = sorted(set(valid_material_ids) - set(mapping_ids))
        undeclared_mappings = sorted(set(mapping_ids) - set(valid_material_ids))
        errors.extend(f"material_claim_ids_missing_mappings:{aid}:{claim_id}" for claim_id in missing_mappings)
        errors.extend(f"claim_mappings_undeclared_material_claims:{aid}:{claim_id}" for claim_id in undeclared_mappings)

    return errors


def validate_batch(batch: dict[str, Any], artifact_root: Path | None = None) -> list[str]:
    """Return all deterministic reasons a batch cannot be handed to independent review.

    When ``artifact_root`` is supplied, every declared internal artifact must be a
    safe relative path that resolves inside that root and already exists.
    """
    if not isinstance(batch, dict):
        return ["batch_must_be_a_dict"]
    errors: list[str] = []
    if batch.get("publication_authorization", "not_authorized") != "not_authorized":
        errors.append("controlled_run_must_not_authorize_publication")
    errors.extend(validate_delivery_authorization(batch))

    articles = batch.get("articles", [])
    if len(articles) != 3:
        return errors + ["batch_must_contain_exactly_three_articles"]

    seen: dict[str, set[str]] = {
        "slot": set(), "work": set(), "primary_atom": set(), "reader_intent": set(), "angle": set()
    }
    for article in articles:
        article_id = article.get("article_id", "unknown")
        errors.extend(_require(article, ("article_id", "slot", "work", "primary_atom", "reader_intent", "angle"), f"missing:{article_id}"))
        state = article.get("state")
        if state not in MECHANICAL_INPUT_STATES:
            errors.append(f"article_not_mechanically_eligible:{article_id}:{state}")
        for field in seen:
            value = article.get(field)
            if value in seen[field]:
                errors.append(f"duplicate_{field}:{value}")
            elif value:
                seen[field].add(value)

        artifact_fields = ("markdown_path", "evidence_pack_path", "writing_brief_path")
        errors.extend(_require(article, artifact_fields, f"missing_artifact:{article_id}"))
        markdown_text: str | None = None
        if artifact_root:
            root = artifact_root.resolve()
            for field in artifact_fields:
                declared_path = article.get(field)
                if not declared_path:
                    continue
                candidate_path = Path(declared_path)
                if candidate_path.is_absolute() or ".." in candidate_path.parts:
                    errors.append(f"unsafe_artifact_path:{article_id}:{field}")
                    continue
                resolved = (root / candidate_path).resolve()
                if root not in resolved.parents or not resolved.is_file():
                    errors.append(f"missing_artifact_file:{article_id}:{field}")
                    continue
                text = resolved.read_text(encoding="utf-8")
                if field == "markdown_path":
                    markdown_text = text
                if not text.strip():
                    errors.append(f"empty_artifact_file:{article_id}:{field}")
                    continue
                if field == "markdown_path":
                    character_count = _chinese_character_count(text)
                    if not 1500 <= character_count <= 2200:
                        errors.append(f"markdown_character_count_out_of_range:{article_id}:{character_count}")
        errors.extend(_require(article, ("title", "claim_coverage", "claim_mappings", "concrete_support_types"), f"missing_gate:{article_id}"))
        errors.extend(validate_claim_inventory(article, markdown_text))
        if article.get("claim_coverage") != "complete":
            errors.append(f"claim_coverage_incomplete:{article_id}")
        support_types = article.get("concrete_support_types")
        normalized_support_types = {
            item.strip()
            for item in support_types
            if isinstance(item, str) and item.strip()
        } if isinstance(support_types, (list, tuple)) else set()
        if len(normalized_support_types) < 2:
            errors.append(f"insufficient_concrete_support:{article_id}")
        if _title_length(article.get("title", "")) > 30:
            errors.append(f"title_too_long:{article_id}")
        if article.get("html_delivery_state") not in {"withheld", "not_requested"}:
            errors.append(f"html_out_of_scope_for_controlled_run:{article_id}")
        errors.extend(validate_delivery_authorization(article))
        if article.get("publication_authorization", "not_authorized") != "not_authorized":
            errors.append(f"article_publication_not_authorized:{article_id}")

    if seen["slot"] != set(SLOTS):
        errors.append("slots_must_be_A_B_C")
    return errors


def build_controlled_run(batch: dict[str, Any], output_dir: Path) -> Path:
    """Write a local mechanically-verified manifest after deterministic gates pass.

    This never emits R8. R8 requires ``promote_to_review_ready`` with Sol approve
    and an explicit controller acceptance value.
    """
    errors = validate_batch(batch, output_dir)
    if errors:
        raise BatchValidationError(";".join(errors))

    output_dir.mkdir(parents=True, exist_ok=True)
    articles = []
    for article in batch["articles"]:
        record = dict(article)
        record["state"] = MECHANICALLY_VERIFIED
        articles.append(record)
    manifest = {
        "run_id": batch["run_id"],
        "created_at": datetime.now(UTC).isoformat(),
        "mode": "controlled_first_run",
        "state": MECHANICALLY_VERIFIED,
        "publication_authorization": "not_authorized",
        "delivery_state": "withheld_pending_independent_review_and_controller_acceptance",
        "network_actions": "none",
        "article_count": 3,
        "articles": articles,
    }
    target = output_dir / "controlled-run-manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return target


def promote_to_review_ready(
    manifest: dict[str, Any],
    *,
    sol_decision: object,
    controller_acceptance: object,
    sol_review_ref: str = "",
    controller_acceptance_ref: str = "",
) -> dict[str, Any]:
    """Promote a mechanical/awaiting manifest to R8 only with Sol approve + controller accept.

    Never grants publication authority. Sol timeout / needs_changes /
    evidence_insufficient / incomplete labels cannot mint R8.
    """
    if not isinstance(manifest, dict):
        raise BatchValidationError("manifest_must_be_a_dict")
    if manifest.get("publication_authorization", "not_authorized") != "not_authorized":
        raise BatchValidationError("controlled_run_must_not_authorize_publication")

    current_state = manifest.get("state")
    if not isinstance(current_state, str) or not current_state.strip():
        raise BatchValidationError(f"manifest_not_ready_for_r8_promotion:{current_state!r}")
    if current_state not in R8_PROMOTION_SOURCE_STATES:
        raise BatchValidationError(f"manifest_not_ready_for_r8_promotion:{current_state}")

    # Exact labels only: no strip/case folding on authorization vocabulary (S4-F03).
    if sol_decision != "approve":
        raise BatchValidationError(f"sol_decision_not_approve:{sol_decision!r}")

    if controller_acceptance not in CONTROLLER_ACCEPTANCE_VALUES:
        raise BatchValidationError(
            f"controller_acceptance_required:{controller_acceptance!r}"
        )

    if current_state == MECHANICALLY_VERIFIED:
        validate_transition(MECHANICALLY_VERIFIED, AWAITING_INDEPENDENT_REVIEW)
        validate_transition(AWAITING_INDEPENDENT_REVIEW, REVIEW_READY)
    else:
        validate_transition(AWAITING_INDEPENDENT_REVIEW, REVIEW_READY)

    promoted = dict(manifest)
    promoted["state"] = REVIEW_READY
    promoted["publication_authorization"] = "not_authorized"
    promoted["sol_decision"] = sol_decision
    promoted["controller_acceptance"] = controller_acceptance
    if _nonblank_string(sol_review_ref):
        promoted["sol_review_ref"] = sol_review_ref.strip()
    if _nonblank_string(controller_acceptance_ref):
        promoted["controller_acceptance_ref"] = controller_acceptance_ref.strip()

    articles = promoted.get("articles", [])
    if isinstance(articles, list):
        rewritten = []
        for article in articles:
            if isinstance(article, dict):
                record = dict(article)
                record["state"] = REVIEW_READY
                rewritten.append(record)
            else:
                rewritten.append(article)
        promoted["articles"] = rewritten
    return promoted
