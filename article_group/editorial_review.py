"""Fail-closed validator for the bounded four-stage editorial-review protocol.

The protocol is deliberately additive and opt-in. This module reads a per-run
record and immutable artifact references; it never edits a draft, changes a
workflow state, fetches a source, grants publication authority, or sends a
message. A PASS here only means the record structure, hashes, and stage
boundaries are complete. Editorial judgment, increment, and human confirmation
live in article_group.editorial_judgment and are not replaced by this validator.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


PROTOCOL_VERSION = "1.0"
CARD_VERSION = "1.0"
STAGE_ORDER = (
    "project_precheck",
    "prewrite",
    "postdraft",
    "prepublication",
)
STAGE_LABELS = {
    "project_precheck": "立项前",
    "prewrite": "写作前",
    "postdraft": "成稿后",
    "prepublication": "发布前",
}
STAGE_ALIASES = {**{value: key for key, value in STAGE_LABELS.items()}}
STAGE_ALIASES.update({key: key for key in STAGE_ORDER})

# These are intentionally contracts for the reviewer's declared scope, not
# automated judgments about whether a human's prose is good.
STAGE_CONTRACTS: dict[str, dict[str, Any]] = {
    "project_precheck": {
        "objective": "define_article_scope",
        "review_mode": "human",
        "scope_id": "topic_definition_only",
        "allowed_actions": (
            "define_core_question",
            "define_target_reader",
            "classify_article_type",
            "declare_scope_exclusions",
        ),
        "required_checks": ("core_question", "target_reader", "article_type", "scope_exclusions"),
        "required_forbidden_actions": (
            "write_draft",
            "assert_unsourced_fact",
            "authorize_publication",
        ),
        "handoff_to": "prewrite",
        "required_card": "topic_card",
    },
    "prewrite": {
        "objective": "bound_permitted_claims",
        "review_mode": "human_and_mechanical",
        "scope_id": "fact_boundary_only",
        "allowed_actions": (
            "map_claim_to_source",
            "declare_permitted_claim",
            "declare_prohibited_claim",
            "record_coverage_gap",
            "record_conflict",
        ),
        "required_checks": ("claim_source_links", "prohibited_claims", "coverage_gaps", "conflicts"),
        "required_forbidden_actions": (
            "change_topic_scope",
            "write_unsourced_claim",
            "authorize_publication",
        ),
        "handoff_to": "postdraft",
        "required_card": "fact_card",
    },
    "postdraft": {
        "objective": "edit_human_writing",
        "review_mode": "human",
        "scope_id": "human_writing_only",
        "allowed_actions": (
            "edit_structure",
            "edit_viewpoint",
            "edit_tone",
            "edit_narrative",
        ),
        "required_checks": ("structure", "viewpoint", "tone", "narrative"),
        "required_forbidden_actions": (
            "add_unsourced_fact",
            "rewrite_fact_boundary",
            "authorize_publication",
        ),
        "handoff_to": "prepublication",
        "required_card": None,
    },
    "prepublication": {
        "objective": "verify_distribution_and_facts",
        "review_mode": "human_and_mechanical",
        "scope_id": "distribution_verification_only",
        "allowed_actions": (
            "review_title",
            "review_opening",
            "verify_sources",
            "verify_digits",
            "verify_links",
            "verify_page_cleanup",
        ),
        "required_checks": ("title", "opening", "sources", "digits", "links", "page_cleanup"),
        "required_forbidden_actions": (
            "change_editorial_thesis",
            "expand_fact_scope",
            "authorize_publication",
        ),
        "handoff_to": "controller_review",
        "required_card": None,
    },
}

DRAFT_PASS_ORDER = (
    "facts_draft",
    "editorial_draft",
    "recommender_optimization",
    "final_prepublication_review",
)
DRAFT_PASS_OBJECTIVES = {
    "facts_draft": "render_only_permitted_claims",
    "editorial_draft": "shape_structure_viewpoint_tone_narrative",
    "recommender_optimization": "test_title_opening_and_distribution_fit",
    "final_prepublication_review": "recheck_sources_digits_links_and_page_cleanup",
}
DRAFT_PASS_STAGE = {
    "facts_draft": "prewrite",
    "editorial_draft": "postdraft",
    "recommender_optimization": "prepublication",
    "final_prepublication_review": "prepublication",
}

STOP_DRAFT_REASON_CODES = frozenset(
    {
        "missing_topic_card",
        "missing_fact_card",
        "scope_undefined",
        "source_unavailable",
        "claim_not_supported",
        "unresolved_conflict",
        "fact_card_not_ready",
        "stage_failed",
        "draft_scope_drift",
        "multiple_objectives",
        "round_exceeded",
        "handoff_missing",
        "human_review_pending",
        "publication_requested",
        "out_of_scope",
    }
)

_ARTIFACT_DIGEST = re.compile(r"^[0-9a-fA-F]{64}$")
_HTTP_URL = re.compile(r"^https?://[^\s]+$")
_ALLOWED_CHECK_STATUSES = {"pass", "fail", "pending", "not_applicable", "not_run"}
_ALLOWED_STAGE_STATUSES = {"pass", "fail", "blocked", "stop", "not_run"}
_ALLOWED_PASS_STATUSES = {"planned", "pass", "blocked", "not_applicable", "not_run"}
_ALLOWED_STOP_DISPOSITIONS = {"continue", "hold", "revise", "archive", "reject"}
_ALLOWED_CARD_DECISIONS = {
    "proceed",
    "ready_for_draft",
    "waiting_source",
    "draft_only",
    "stop",
    "hold",
    "reject",
}


class EditorialRecordInputError(ValueError):
    """Raised when the record or an immutable artifact cannot be loaded."""


class _JSONDict(dict[str, Any]):
    """JSON object retaining duplicate keys so input cannot be overwritten silently."""

    def __init__(self, pairs: list[tuple[str, Any]]) -> None:
        super().__init__()
        self.duplicate_fields: list[str] = []
        for key, value in pairs:
            if key in self:
                if key not in self.duplicate_fields:
                    self.duplicate_fields.append(key)
                continue
            self[key] = value


def _json_pairs_hook(pairs: list[tuple[str, Any]]) -> _JSONDict:
    return _JSONDict(pairs)


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: object) -> bool:
    return isinstance(value, list) and all(_nonblank(item) for item in value)


def _dedupe(errors: list[str]) -> list[str]:
    return list(dict.fromkeys(errors))


def _record_label(record: object) -> str:
    if isinstance(record, dict) and _nonblank(record.get("article_id")):
        return str(record["article_id"]).strip()
    return "unknown"


def _append_required(errors: list[str], mapping: object, fields: tuple[str, ...], prefix: str) -> None:
    if not isinstance(mapping, dict):
        errors.append(f"{prefix}_missing")
        return
    for field in fields:
        if field not in mapping or mapping[field] is None or (
            isinstance(mapping[field], str) and not mapping[field].strip()
        ):
            errors.append(f"{prefix}_field_missing:{field}")


def _safe_relative_path(value: object, root: Path, label: str, errors: list[str]) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"artifact_path_missing:{label}")
        return None
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        errors.append(f"artifact_path_unsafe:{label}")
        return None
    try:
        resolved = (root.resolve() / candidate).resolve()
    except (OSError, RuntimeError, ValueError):
        errors.append(f"artifact_path_unsafe:{label}")
        return None
    if root.resolve() not in resolved.parents or not resolved.is_file():
        errors.append(f"artifact_file_missing:{label}")
        return None
    return resolved


def _read_json_artifact(path: Path, label: str, errors: list[str]) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_json_pairs_hook)
    except (OSError, UnicodeError, json.JSONDecodeError):
        errors.append(f"artifact_json_invalid:{label}")
        return None
    if not isinstance(payload, dict):
        errors.append(f"artifact_json_not_object:{label}")
        return None
    duplicate = _nested_duplicate_field(payload, label)
    if duplicate is not None:
        errors.append(duplicate)
        return None
    return payload


def _nested_duplicate_field(payload: object, label: str) -> str | None:
    if isinstance(payload, _JSONDict) and payload.duplicate_fields:
        return f"artifact_duplicate_field:{label}:{payload.duplicate_fields[0]}"
    if isinstance(payload, dict):
        for value in payload.values():
            result = _nested_duplicate_field(value, label)
            if result is not None:
                return result
    elif isinstance(payload, list):
        for value in payload:
            result = _nested_duplicate_field(value, label)
            if result is not None:
                return result
    return None


def _validate_artifact_reference(
    reference: object,
    run_root: Path,
    label: str,
    errors: list[str],
    *,
    expected_card_type: str | None = None,
    expected_run_id: str | None = None,
    expected_article_id: str | None = None,
) -> dict[str, Any] | None:
    if not isinstance(reference, dict):
        error_code = f"card_ref_missing:{expected_card_type}" if expected_card_type else f"artifact_ref_missing:{label}"
        errors.append(error_code)
        return None
    version = reference.get("version")
    if not _nonblank(version):
        errors.append(f"artifact_version_missing:{label}")
    digest = reference.get("sha256")
    if not isinstance(digest, str) or not _ARTIFACT_DIGEST.fullmatch(digest):
        errors.append(f"artifact_digest_invalid:{label}")
    path = _safe_relative_path(reference.get("path"), run_root.resolve(), label, errors)
    if path is None:
        return None
    try:
        actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        errors.append(f"artifact_file_unreadable:{label}")
        return None
    if isinstance(digest, str) and _ARTIFACT_DIGEST.fullmatch(digest):
        if actual_digest != digest.lower():
            errors.append(f"artifact_digest_mismatch:{label}")

    if expected_card_type is None:
        return None
    payload = _read_json_artifact(path, label, errors)
    if payload is None:
        return None
    _validate_card_payload(
        payload,
        expected_card_type,
        expected_run_id,
        expected_article_id,
        label,
        errors,
    )
    if version != payload.get("card_version"):
        errors.append(f"artifact_version_mismatch:{label}")
    return payload


def _validate_card_payload(
    card: dict[str, Any],
    expected_type: str,
    expected_run_id: str | None,
    expected_article_id: str | None,
    label: str,
    errors: list[str],
) -> None:
    if card.get("card_version") != CARD_VERSION:
        errors.append(f"card_version_invalid:{label}")
    if card.get("card_type") != expected_type:
        errors.append(f"card_type_invalid:{label}:{expected_type}")
    if expected_run_id is not None and card.get("run_id") != expected_run_id:
        errors.append(f"card_run_id_mismatch:{label}")
    if expected_article_id is not None and card.get("article_id") != expected_article_id:
        errors.append(f"card_article_id_mismatch:{label}")

    if expected_type == "topic_card":
        _validate_topic_card(card, label, errors)
    elif expected_type == "fact_card":
        _validate_fact_card(card, label, errors)


def _validate_topic_card(card: dict[str, Any], label: str, errors: list[str]) -> None:
    _append_required(
        errors,
        card,
        ("core_question", "target_reader", "article_type", "one_sentence_scope", "decision", "decided_by", "decided_at"),
        label,
    )
    if not _string_list(card.get("out_of_scope")) or not card["out_of_scope"]:
        errors.append(f"topic_card_out_of_scope_invalid:{label}")
    raw_stop_reasons = card.get("stop_reasons")
    if not _string_list(raw_stop_reasons):
        errors.append(f"topic_card_stop_reasons_invalid:{label}")
        stop_reasons: list[str] = []
    else:
        stop_reasons = [str(reason) for reason in raw_stop_reasons] if isinstance(raw_stop_reasons, list) else []
        for reason in stop_reasons:
            if reason not in STOP_DRAFT_REASON_CODES:
                errors.append(f"topic_card_stop_reason_invalid:{label}:{reason}")
    decision = card.get("decision")
    if decision not in _ALLOWED_CARD_DECISIONS:
        errors.append(f"topic_card_decision_invalid:{label}")
    elif decision == "proceed" and stop_reasons:
        errors.append(f"topic_card_proceed_with_stop_reason:{label}")
    elif decision != "proceed" and not stop_reasons:
        errors.append(f"topic_card_stop_reason_required:{label}")


def _validate_fact_card(card: dict[str, Any], label: str, errors: list[str]) -> None:
    _append_required(
        errors,
        card,
        ("sources", "permitted_claims", "prohibited_claims", "coverage_gaps", "unresolved_conflicts", "decision", "decided_by", "decided_at"),
        label,
    )
    decision = card.get("decision")
    ready_for_draft = decision == "ready_for_draft"
    sources = card.get("sources")
    source_ids: set[str] = set()
    if not isinstance(sources, list) or (ready_for_draft and not sources):
        errors.append(f"fact_card_sources_invalid:{label}")
    else:
        for index, source in enumerate(sources):
            source_label = f"{label}:source-{index + 1}"
            if not isinstance(source, dict):
                errors.append(f"fact_card_source_invalid:{source_label}")
                continue
            source_id = source.get("source_id")
            if not _nonblank(source_id):
                errors.append(f"fact_card_source_id_missing:{source_label}")
            else:
                source_id = str(source_id).strip()
                if source_id in source_ids:
                    errors.append(f"fact_card_duplicate_source_id:{label}:{source_id}")
                source_ids.add(source_id)
            if not _HTTP_URL.fullmatch(str(source.get("url", ""))):
                errors.append(f"fact_card_source_url_invalid:{source_label}")
            if not _nonblank(source.get("locator")):
                errors.append(f"fact_card_source_locator_missing:{source_label}")
            if not _nonblank(source.get("source_level")):
                errors.append(f"fact_card_source_level_missing:{source_label}")
            if not _nonblank(source.get("accessed_at")):
                errors.append(f"fact_card_source_accessed_at_missing:{source_label}")

    permitted = card.get("permitted_claims")
    claim_ids: set[str] = set()
    if not isinstance(permitted, list) or (ready_for_draft and not permitted):
        errors.append(f"fact_card_permitted_claims_invalid:{label}")
    else:
        for index, claim in enumerate(permitted):
            claim_label = f"{label}:claim-{index + 1}"
            if not isinstance(claim, dict):
                errors.append(f"fact_card_claim_invalid:{claim_label}")
                continue
            claim_id = claim.get("claim_id")
            if not _nonblank(claim_id):
                errors.append(f"fact_card_claim_id_missing:{claim_label}")
            else:
                claim_id = str(claim_id).strip()
                if claim_id in claim_ids:
                    errors.append(f"fact_card_duplicate_claim_id:{label}:{claim_id}")
                claim_ids.add(claim_id)
            if not _nonblank(claim.get("claim")):
                errors.append(f"fact_card_claim_text_missing:{claim_label}")
            if claim.get("claim_type") not in {"fact", "attributed_view", "inference", "attribution"}:
                errors.append(f"fact_card_claim_type_invalid:{claim_label}")
            source_refs = claim.get("source_ids")
            if not _string_list(source_refs) or not source_refs:
                errors.append(f"fact_card_claim_sources_invalid:{claim_label}")
            elif not set(source_refs).issubset(source_ids):
                errors.append(f"fact_card_claim_source_unresolved:{claim_label}")
            if not _nonblank(claim.get("limitation")):
                errors.append(f"fact_card_claim_limitation_missing:{claim_label}")

    if not isinstance(card.get("prohibited_claims"), list):
        errors.append(f"fact_card_prohibited_claims_invalid:{label}")
    else:
        for index, claim in enumerate(card["prohibited_claims"]):
            if not isinstance(claim, dict) or not _nonblank(claim.get("claim")) or not _nonblank(claim.get("reason")):
                errors.append(f"fact_card_prohibited_claim_invalid:{label}:{index + 1}")
    for field in ("coverage_gaps", "unresolved_conflicts"):
        if not _string_list(card.get(field)):
            errors.append(f"fact_card_{field}_invalid:{label}")
    if not _nonblank(card.get("data_as_of")):
        errors.append(f"fact_card_data_as_of_missing:{label}")
    if card.get("update_required_before_publication") not in {"yes", "no"}:
        errors.append(f"fact_card_update_required_invalid:{label}")
    if not _nonblank(card.get("update_trigger")):
        errors.append(f"fact_card_update_trigger_missing:{label}")
    raw_stop_reasons = card.get("stop_reasons")
    if not _string_list(raw_stop_reasons):
        errors.append(f"fact_card_stop_reasons_invalid:{label}")
        stop_reasons = []
    else:
        stop_reasons = [str(reason) for reason in raw_stop_reasons] if isinstance(raw_stop_reasons, list) else []
        for reason in stop_reasons:
            if reason not in STOP_DRAFT_REASON_CODES:
                errors.append(f"fact_card_stop_reason_invalid:{label}:{reason}")
    if decision not in _ALLOWED_CARD_DECISIONS:
        errors.append(f"fact_card_decision_invalid:{label}")
    elif ready_for_draft and stop_reasons:
        errors.append(f"fact_card_ready_with_stop_reason:{label}")
    elif not ready_for_draft and not stop_reasons:
        errors.append(f"fact_card_stop_reason_required:{label}")
    if card.get("unresolved_conflicts") and ready_for_draft:
        errors.append(f"fact_card_conflicts_unresolved:{label}")


def _canonical_stage_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return STAGE_ALIASES.get(value.strip())


def _validate_scope(stage: dict[str, Any], stage_id: str, errors: list[str]) -> None:
    scope = stage.get("scope")
    label = STAGE_LABELS[stage_id]
    if not isinstance(scope, dict):
        errors.append(f"stage_scope_missing:{stage_id}")
        return
    contract = STAGE_CONTRACTS[stage_id]
    if scope.get("scope_id") != contract["scope_id"]:
        errors.append(f"stage_scope_id_invalid:{stage_id}")
    for field in ("allowed_actions", "forbidden_actions"):
        if not _string_list(scope.get(field)) or not scope[field]:
            errors.append(f"stage_scope_{field}_invalid:{stage_id}")
    allowed = set(scope.get("allowed_actions", [])) if isinstance(scope.get("allowed_actions"), list) else set()
    expected_allowed = set(contract["allowed_actions"])
    for missing in sorted(expected_allowed - allowed):
        errors.append(f"stage_scope_allowed_missing:{stage_id}:{missing}")
    for unexpected in sorted(allowed - expected_allowed):
        errors.append(f"stage_scope_allowed_unexpected:{stage_id}:{unexpected}")
    if isinstance(scope.get("allowed_actions"), list) and isinstance(scope.get("forbidden_actions"), list):
        overlap = set(scope["allowed_actions"]) & set(scope["forbidden_actions"])
        if overlap:
            errors.append(f"stage_scope_overlap:{stage_id}:{','.join(sorted(overlap))}")
    forbidden = set(scope.get("forbidden_actions", [])) if isinstance(scope.get("forbidden_actions"), list) else set()
    for required in contract["required_forbidden_actions"]:
        if required not in forbidden:
            errors.append(f"stage_scope_forbidden_missing:{stage_id}:{required}")
    if scope.get("reader_facing") is not False:
        errors.append(f"stage_scope_reader_facing_must_be_false:{stage_id}")
    # Keep the label in the error path for operators reading a failed report.
    if not _nonblank(scope.get("description")):
        errors.append(f"stage_scope_description_missing:{label}")


def _same_reference(left: object, right: object) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    return left.get("path") == right.get("path") and left.get("sha256") == right.get("sha256")


def _validate_stage(
    stage: object,
    expected_stage_id: str,
    index: int,
    run_root: Path,
    record: dict[str, Any],
    card_refs: dict[str, Any],
    errors: list[str],
) -> str:
    if not isinstance(stage, dict):
        errors.append(f"stage_invalid:{expected_stage_id}:{index}")
        return "not_run"
    actual_id = _canonical_stage_id(stage.get("stage_id"))
    if actual_id != expected_stage_id:
        errors.append(f"stage_order_invalid:{index + 1}:{stage.get('stage_id')}")
    contract = STAGE_CONTRACTS[expected_stage_id]
    if stage.get("label") != STAGE_LABELS[expected_stage_id]:
        errors.append(f"stage_label_invalid:{expected_stage_id}")
    round_value = stage.get("round")
    if not isinstance(round_value, int) or isinstance(round_value, bool) or round_value < 1:
        errors.append(f"stage_round_must_be_positive:{expected_stage_id}")
    if stage.get("objective") != contract["objective"]:
        errors.append(f"stage_objective_invalid:{expected_stage_id}")
    objectives = stage.get("objectives")
    if not isinstance(objectives, list) or not _string_list(objectives) or len(objectives) != 1:
        errors.append(f"stage_single_objective_invalid:{expected_stage_id}")
    elif objectives[0] != contract["objective"]:
        errors.append(f"stage_single_objective_invalid:{expected_stage_id}")
    if stage.get("review_mode") != contract["review_mode"]:
        errors.append(f"stage_review_mode_invalid:{expected_stage_id}")
    _validate_scope(stage, expected_stage_id, errors)

    status = stage.get("status")
    if status not in _ALLOWED_STAGE_STATUSES:
        errors.append(f"stage_status_invalid:{expected_stage_id}")
        status = "not_run"
    checks = stage.get("checks")
    if not isinstance(checks, dict):
        errors.append(f"stage_checks_missing:{expected_stage_id}")
        checks = {}
    for check in contract["required_checks"]:
        if check not in checks:
            errors.append(f"stage_check_missing:{expected_stage_id}:{check}")
        elif checks[check] not in _ALLOWED_CHECK_STATUSES:
            errors.append(f"stage_check_status_invalid:{expected_stage_id}:{check}")
        elif status == "pass" and checks[check] != "pass":
            errors.append(f"stage_check_not_pass:{expected_stage_id}:{check}")
        elif status == "not_run" and checks[check] != "not_run":
            errors.append(f"stage_check_not_not_run:{expected_stage_id}:{check}")

    evidence_refs = stage.get("evidence_refs")
    if not isinstance(evidence_refs, list):
        errors.append(f"stage_evidence_refs_missing:{expected_stage_id}")
        evidence_refs = []
    elif status == "not_run":
        if evidence_refs:
            errors.append(f"stage_evidence_refs_forbidden:{expected_stage_id}")
            evidence_refs = []
    elif not evidence_refs:
        errors.append(f"stage_evidence_refs_missing:{expected_stage_id}")
    for evidence_index, reference in enumerate(evidence_refs):
        _validate_artifact_reference(
            reference,
            run_root,
            f"stage:{expected_stage_id}:evidence-{evidence_index + 1}",
            errors,
        )
    required_card = contract["required_card"]
    if required_card is not None and status != "not_run":
        expected_ref = card_refs.get(required_card)
        if not any(_same_reference(reference, expected_ref) for reference in evidence_refs):
            errors.append(f"stage_card_evidence_missing:{expected_stage_id}:{required_card}")

    if status == "pass":
        _append_required(errors, stage, ("completed_by", "completed_at", "decision_note"), f"stage:{expected_stage_id}")
    elif status in {"fail", "blocked", "stop"} and not _nonblank(stage.get("decision_note")):
        errors.append(f"stage_decision_note_missing:{expected_stage_id}")
    handoff_to = _canonical_stage_id(stage.get("handoff_to")) or stage.get("handoff_to")
    if handoff_to != contract["handoff_to"]:
        errors.append(f"stage_handoff_invalid:{expected_stage_id}")
    return status


def _validate_draft_passes(
    record: dict[str, Any], stage_statuses: dict[str, str], errors: list[str]
) -> None:
    passes = record.get("draft_passes")
    if not isinstance(passes, list) or not (3 <= len(passes) <= 4):
        errors.append("draft_passes_must_contain_three_or_four")
        return
    seen: set[str] = set()
    pass_ids: list[str] = []
    for index, item in enumerate(passes):
        label = f"draft_pass:{index + 1}"
        if not isinstance(item, dict):
            errors.append(f"{label}_invalid")
            continue
        pass_id = item.get("pass_id")
        if pass_id not in DRAFT_PASS_ORDER:
            errors.append(f"{label}_id_invalid")
            continue
        if pass_id in seen:
            errors.append(f"draft_pass_duplicate:{pass_id}")
        seen.add(pass_id)
        pass_ids.append(pass_id)
        round_value = item.get("round")
        if not isinstance(round_value, int) or isinstance(round_value, bool) or round_value < 1:
            errors.append(f"draft_pass_round_must_be_positive:{pass_id}")
        if item.get("objective") != DRAFT_PASS_OBJECTIVES[pass_id]:
            errors.append(f"draft_pass_objective_invalid:{pass_id}")
        objectives = item.get("objectives")
        if not isinstance(objectives, list) or not _string_list(objectives) or len(objectives) != 1:
            errors.append(f"draft_pass_single_objective_invalid:{pass_id}")
        elif objectives[0] != DRAFT_PASS_OBJECTIVES[pass_id]:
            errors.append(f"draft_pass_single_objective_invalid:{pass_id}")
        if item.get("stage_id") != DRAFT_PASS_STAGE[pass_id]:
            errors.append(f"draft_pass_stage_invalid:{pass_id}")
        if item.get("status") not in _ALLOWED_PASS_STATUSES:
            errors.append(f"draft_pass_status_invalid:{pass_id}")
        if not _nonblank(item.get("decision_note")):
            errors.append(f"draft_pass_decision_note_missing:{pass_id}")
        pass_stage = DRAFT_PASS_STAGE[pass_id]
        if item.get("status") == "pass" and stage_statuses.get(pass_stage) != "pass":
            errors.append(f"draft_pass_after_stage_failure_must_not_pass:{pass_id}")
    expected_order = [pass_id for pass_id in DRAFT_PASS_ORDER if pass_id in seen]
    if pass_ids != expected_order:
        errors.append("draft_pass_order_invalid")
    if pass_ids and pass_ids[0] != "facts_draft":
        errors.append("draft_pass_must_start_with_facts_draft")
    required_passes = {"facts_draft", "editorial_draft", "final_prepublication_review"}
    for missing in sorted(required_passes - seen):
        errors.append(f"draft_pass_required_missing:{missing}")
    first_stopped_stage_index = next(
        (
            index
            for index, stage_id in enumerate(STAGE_ORDER)
            if stage_statuses.get(stage_id) in {"fail", "blocked", "stop"}
        ),
        None,
    )
    if first_stopped_stage_index is not None:
        for item in passes:
            if not isinstance(item, dict):
                continue
            pass_id = item.get("pass_id")
            if not isinstance(pass_id, str):
                continue
            pass_stage = DRAFT_PASS_STAGE.get(pass_id)
            if pass_stage is None:
                continue
            if STAGE_ORDER.index(pass_stage) > first_stopped_stage_index and item.get("status") != "not_run":
                errors.append(f"draft_pass_after_stage_failure_must_be_not_run:{pass_id}")
    if all(stage_statuses.get(stage_id) == "pass" for stage_id in STAGE_ORDER):
        for item in passes:
            if isinstance(item, dict) and item.get("pass_id") in DRAFT_PASS_ORDER:
                if item.get("status") != "pass":
                    errors.append(f"draft_pass_not_pass:{item['pass_id']}")


def _validate_stop_draft(
    record: dict[str, Any],
    stage_statuses: dict[str, str],
    run_root: Path,
    errors: list[str],
) -> list[str]:
    stop = record.get("stop_draft")
    if not isinstance(stop, dict):
        errors.append("stop_draft_missing")
        return []
    triggered = stop.get("triggered")
    if not isinstance(triggered, bool):
        errors.append("stop_draft_triggered_invalid")
        triggered = False
    raw_reasons = stop.get("reason_codes")
    if not _string_list(raw_reasons):
        errors.append("stop_draft_reason_codes_invalid")
        reasons: list[str] = []
    else:
        reasons = list(raw_reasons)
        for reason in reasons:
            if reason not in STOP_DRAFT_REASON_CODES:
                errors.append(f"stop_draft_reason_invalid:{reason}")
    stage_id = _canonical_stage_id(stop.get("stage_id")) if stop.get("stage_id") is not None else None
    disposition = stop.get("draft_disposition")
    if disposition not in _ALLOWED_STOP_DISPOSITIONS:
        errors.append("stop_draft_disposition_invalid")
    evidence_refs = stop.get("evidence_refs")
    if triggered:
        if not isinstance(evidence_refs, list) or not evidence_refs:
            errors.append("stop_draft_evidence_refs_missing")
        else:
            for index, reference in enumerate(evidence_refs):
                _validate_artifact_reference(
                    reference,
                    run_root,
                    f"stop_draft:evidence-{index + 1}",
                    errors,
                )
        if not reasons:
            errors.append("stop_draft_reason_codes_required")
        if stage_id is None:
            errors.append("stop_draft_stage_required")
        elif stage_statuses.get(stage_id) not in {"fail", "blocked", "stop"}:
            errors.append(f"stop_draft_stage_not_failed:{stage_id}")
        if disposition == "continue":
            errors.append("stop_draft_triggered_cannot_continue")
    else:
        if evidence_refs not in (None, []):
            errors.append("stop_draft_evidence_refs_must_be_empty_when_not_triggered")
        if stage_id is not None:
            errors.append("stop_draft_stage_must_be_null_when_not_triggered")
        if reasons:
            errors.append("stop_draft_reasons_must_be_empty_when_not_triggered")
        if disposition != "continue":
            errors.append("stop_draft_disposition_must_continue_when_not_triggered")
    return reasons


def _validate_handoff(
    record: dict[str, Any],
    stage_statuses: dict[str, str],
    run_root: Path,
    errors: list[str],
) -> None:
    handoff = record.get("handoff")
    if not isinstance(handoff, dict):
        errors.append("handoff_missing")
        return
    all_pass = all(stage_statuses.get(stage_id) == "pass" for stage_id in STAGE_ORDER)
    expected_status = "ready" if all_pass else "blocked"
    if handoff.get("status") != expected_status:
        errors.append(f"handoff_status_invalid:expected={expected_status}")
    expected_from = "prepublication" if all_pass else next(
        (stage_id for stage_id in STAGE_ORDER if stage_statuses.get(stage_id) != "pass"),
        "project_precheck",
    )
    expected_to = "controller_review" if all_pass else "evidence_intake"
    from_stage = _canonical_stage_id(handoff.get("from_stage")) or handoff.get("from_stage")
    if from_stage != expected_from:
        errors.append("handoff_from_stage_invalid")
    if handoff.get("to") != expected_to:
        errors.append("handoff_to_invalid")
    if not _nonblank(handoff.get("handoff_at")):
        errors.append("handoff_at_missing")
    if not _nonblank(handoff.get("note")):
        errors.append("handoff_note_missing")
    evidence_refs = handoff.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        errors.append("handoff_evidence_refs_missing")
    else:
        for index, reference in enumerate(evidence_refs):
            _validate_artifact_reference(
                reference,
                run_root,
                f"handoff:evidence-{index + 1}",
                errors,
            )


def _validate_supersedes_record_reference(
    record: dict[str, Any],
    run_root: Path,
    run_id: str,
    article_id: str,
    errors: list[str],
) -> None:
    revision = record.get("record_revision")
    reference = record.get("supersedes_record_ref")
    if revision == 1:
        if reference not in (None, ""):
            errors.append("supersedes_record_ref_must_be_blank_for_initial_revision")
        return
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        return
    if not isinstance(reference, dict):
        errors.append("supersedes_record_ref_required")
        return

    label = "supersedes_record"
    version = reference.get("version")
    if not _nonblank(version):
        errors.append(f"artifact_version_missing:{label}")
    digest = reference.get("sha256")
    if not isinstance(digest, str) or not _ARTIFACT_DIGEST.fullmatch(digest):
        errors.append(f"artifact_digest_invalid:{label}")
    path = _safe_relative_path(reference.get("path"), run_root.resolve(), label, errors)
    if path is None:
        return
    try:
        actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        errors.append(f"artifact_file_unreadable:{label}")
        return
    if isinstance(digest, str) and _ARTIFACT_DIGEST.fullmatch(digest):
        if actual_digest != digest.lower():
            errors.append(f"artifact_digest_mismatch:{label}")

    previous = _read_json_artifact(path, label, errors)
    if previous is None:
        return
    if version != previous.get("protocol_version"):
        errors.append("supersedes_record_version_mismatch")
    if previous.get("protocol_version") != PROTOCOL_VERSION:
        errors.append("supersedes_record_protocol_version_invalid")
    if previous.get("run_id") != run_id:
        errors.append("supersedes_record_run_id_mismatch")
    if previous.get("article_id") != article_id:
        errors.append("supersedes_record_article_id_mismatch")
    if previous.get("record_revision") != revision - 1:
        errors.append("supersedes_record_revision_invalid")


def evaluate_editorial_record(record: dict[str, Any], run_root: Path) -> dict[str, Any]:
    """Return a deterministic pass, blocked, or invalid report for one record."""
    errors: list[str] = []
    if not isinstance(record, dict):
        return {
            "verdict": "FAIL",
            "errors": ["record_must_be_an_object"],
            "stop_reasons": [],
            "next_action": "evidence_intake",
            "publication_authorization": "not_authorized",
        }
    if not isinstance(run_root, Path):
        run_root = Path(run_root)
    if record.get("protocol_version") != PROTOCOL_VERSION:
        errors.append("protocol_version_invalid")
    revision = record.get("record_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        errors.append("record_revision_invalid")
    if not _nonblank(record.get("run_id")):
        errors.append("run_id_missing")
    if not _nonblank(record.get("article_id")):
        errors.append("article_id_missing")
    if record.get("publication_authorization", "not_authorized") != "not_authorized":
        errors.append("publication_authorization_must_be_not_authorized")
    for field in ("authorization_by", "authorized_at", "authorization_ref", "authorized_publication_scope"):
        if field in record and record[field] not in (None, ""):
            errors.append(f"authorization_field_must_be_blank:{field}")

    run_id = str(record.get("run_id", "")).strip()
    article_id = str(record.get("article_id", "")).strip()
    _validate_supersedes_record_reference(record, run_root, run_id, article_id, errors)
    card_refs = record.get("card_refs")
    card_payloads: dict[str, dict[str, Any] | None] = {}
    if not isinstance(card_refs, dict):
        errors.append("card_refs_missing")
        card_refs = {}
    else:
        # `selection_card` is accepted as a migration alias without mutating
        # the caller's record; templates use the stable key `topic_card`.
        card_refs = dict(card_refs)
        if "topic_card" not in card_refs and "selection_card" in card_refs:
            card_refs["topic_card"] = card_refs["selection_card"]
        for card_type in ("topic_card", "fact_card"):
            reference = card_refs.get(card_type)
            card_payloads[card_type] = _validate_artifact_reference(
                reference,
                run_root,
                card_type,
                errors,
                expected_card_type=card_type,
                expected_run_id=run_id,
                expected_article_id=article_id,
            )

    stages = record.get("stages")
    stage_statuses: dict[str, str] = {}
    if not isinstance(stages, list) or len(stages) != len(STAGE_ORDER):
        errors.append("stages_must_contain_exactly_four")
        stages = stages if isinstance(stages, list) else []
    for index, stage_id in enumerate(STAGE_ORDER):
        stage = stages[index] if index < len(stages) else None
        stage_statuses[stage_id] = _validate_stage(
            stage,
            stage_id,
            index,
            run_root,
            record,
            card_refs,
            errors,
        )
    topic_card = card_payloads.get("topic_card")
    if stage_statuses.get("project_precheck") == "pass" and (
        not isinstance(topic_card, dict) or topic_card.get("decision") != "proceed"
    ):
        errors.append("stage_card_decision_blocks:project_precheck:topic_card")
    fact_card = card_payloads.get("fact_card")
    if stage_statuses.get("prewrite") == "pass" and (
        not isinstance(fact_card, dict) or fact_card.get("decision") != "ready_for_draft"
    ):
        errors.append("stage_card_decision_blocks:prewrite:fact_card")
    # Once one stage stops, later stages must remain explicitly unrun. A later
    # green stage would make the handoff ambiguous and is therefore fail-closed.
    seen_stop = False
    for stage_id in STAGE_ORDER:
        status = stage_statuses[stage_id]
        if status in {"fail", "blocked", "stop"}:
            seen_stop = True
        elif seen_stop and status != "not_run":
            errors.append(f"stage_after_failure_must_be_not_run:{stage_id}")

    _validate_draft_passes(record, stage_statuses, errors)
    stop_reasons = _validate_stop_draft(record, stage_statuses, run_root, errors)
    _validate_handoff(record, stage_statuses, run_root, errors)

    all_pass = all(stage_statuses.get(stage_id) == "pass" for stage_id in STAGE_ORDER)
    stop = record.get("stop_draft")
    stop_triggered = isinstance(stop, dict) and stop.get("triggered") is True
    if all_pass and stop_triggered:
        errors.append("stop_draft_cannot_be_triggered_after_all_stages_pass")
    if not all_pass and not stop_triggered:
        errors.append("stop_draft_required_after_stage_failure")

    errors = _dedupe(errors)
    if errors:
        verdict = "FAIL"
    elif all_pass:
        verdict = "PASS"
    else:
        verdict = "BLOCKED"
    return {
        "verdict": verdict,
        "errors": errors,
        "stop_reasons": stop_reasons,
        "next_action": "controller_review" if verdict == "PASS" else "evidence_intake",
        "publication_authorization": "not_authorized",
    }


def validate_editorial_record(record: dict[str, Any], run_root: Path) -> dict[str, Any]:
    """Compatibility alias for callers that use the validator naming convention."""
    return evaluate_editorial_record(record, run_root)


def _load_record(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_json_pairs_hook)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EditorialRecordInputError(f"record_load_failed:{path}") from exc
    if not isinstance(payload, dict):
        raise EditorialRecordInputError("record_must_be_an_object")
    duplicate = _nested_duplicate_field(payload, "record")
    if duplicate is not None:
        raise EditorialRecordInputError(duplicate)
    return payload


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", required=True, type=Path, help="Per-run editorial-review JSON record")
    parser.add_argument("--run-root", required=True, type=Path, help="Run root containing referenced artifacts")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        record = _load_record(args.record)
    except EditorialRecordInputError as exc:
        print(f"INPUT_ERROR:{exc}", file=sys.stderr)
        return 2
    report = evaluate_editorial_record(record, args.run_root)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
