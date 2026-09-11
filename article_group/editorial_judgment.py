"""Editorial judgment is separate from four-stage record structure."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import re

from .article_first import ARTICLE_FIRST_CONTRACT_VERSION, validate_phase_field_boundary


SCHEMA_VERSION = "article-editorial-judgment-v1"
JUDGMENT_RESULTS = ("pass", "return_research", "fail")
STRUCTURE_RESULTS = ("pass", "fail", "blocked")
INCREMENT_KINDS = (
    "new_fact",
    "new_judgment",
    "restatement",
    "character_motivation",
    "audience_consensus",
)
MOTIVATION_OR_CONSENSUS = {"character_motivation", "audience_consensus"}
LAYER_NAMES = ("machine_check", "model_editorial_review", "human_confirmation")
_NON_HUMAN_TOKENS = (
    "editorial-protocol-record",
    "controller",
    "codex",
    "luna",
    "terra",
    "sol",
    "agent",
    "model",
    "ai",
    "machine",
    "validator",
    "gpt-",
)
_INTERNAL_REVIEW_PATTERNS = (
    re.compile(r"未知不是文章的缺口"),
    re.compile(r"以编辑部存档为准"),
    re.compile(r"must-prove", re.I),
    re.compile(r"coverage gap", re.I),
    re.compile(r"review_mode"),
    re.compile(r"核验通过"),
    re.compile(r"本轮仅完成"),
)
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_human_identity(value: object) -> bool:
    if not _nonblank(value):
        return False
    identity = str(value).strip().lower()
    return not any(token in identity for token in _NON_HUMAN_TOKENS)


def find_internal_review_language(text: str) -> list[str]:
    if not isinstance(text, str) or not text:
        return []
    hits: list[str] = []
    for pattern in _INTERNAL_REVIEW_PATTERNS:
        match = pattern.search(text)
        if match:
            hits.append(match.group(0))
    return hits


def _validate_layer(name: str, layer: object, errors: list[str]) -> None:
    if not isinstance(layer, Mapping):
        errors.append(f"missing:actor_layer:{name}")
        return
    if not _nonblank(layer.get("by")):
        errors.append(f"missing:actor_layer_by:{name}")
    result = layer.get("result")
    if result not in {"pass", "fail", "return_research", "pending"}:
        errors.append(f"invalid:actor_layer_result:{name}")
    if name == "model_editorial_review" and result in {"pass", "fail", "return_research"}:
        notes = layer.get("paragraph_notes")
        if not isinstance(notes, list) or not notes:
            errors.append("model_review_requires_paragraph_notes")
        else:
            for index, note in enumerate(notes):
                if not isinstance(note, Mapping) or not _nonblank(note.get("locator")) or not _nonblank(note.get("note")):
                    errors.append(f"invalid:paragraph_note:{index}")
    if name == "human_confirmation":
        identity = layer.get("by")
        if _nonblank(identity) and not _is_human_identity(identity):
            errors.append("human_confirmation_not_human")
        if result == "pass":
            if not _nonblank(layer.get("attestation_ref")):
                errors.append("human_confirmation_missing_attestation")
            if not _nonblank(layer.get("checked_at")):
                errors.append("human_confirmation_missing_checked_at")


def _validate_increments(record: Mapping[str, Any], errors: list[str]) -> None:
    increments = record.get("section_increments")
    if not isinstance(increments, list) or not increments:
        errors.append("missing:section_increments")
        return
    judgment_result = record.get("judgment_result")
    for item in increments:
        if not isinstance(item, Mapping):
            errors.append("invalid:section_increment")
            continue
        section_id = item.get("section_id")
        if not _nonblank(section_id):
            errors.append("missing:section_id")
            section_id = "unknown"
        for field in ("locator", "added_material", "advanced_judgment", "difference_from_previous"):
            if not _nonblank(item.get(field)):
                errors.append(f"missing:section_{field}:{section_id}")
        kind = item.get("increment_kind")
        if kind not in INCREMENT_KINDS:
            errors.append(f"invalid:increment_kind:{section_id}")
        support = item.get("supporting_material_ids", [])
        if not isinstance(support, list) or not all(isinstance(entry, str) for entry in support):
            errors.append(f"invalid:supporting_material_ids:{section_id}")
            support = []
        if kind in MOTIVATION_OR_CONSENSUS and not [entry for entry in support if _nonblank(entry)]:
            errors.append(f"unsupported_motivation_or_consensus:{section_id}")
        if kind == "restatement" and judgment_result == "pass":
            errors.append("section_increment_restatement")


def _validate_findings(record: Mapping[str, Any], errors: list[str]) -> None:
    findings = record.get("findings")
    if not isinstance(findings, list):
        errors.append("invalid:findings")
        return
    if record.get("judgment_result") == "return_research" and not findings:
        errors.append("return_research_requires_findings")
    for index, item in enumerate(findings):
        if not isinstance(item, Mapping):
            errors.append(f"invalid:finding:{index}")
            continue
        for field in ("locator", "defect", "basis", "action"):
            if not _nonblank(item.get(field)):
                errors.append(f"missing:finding_{field}:{index}")
        if record.get("judgment_result") == "pass" and item.get("action") == "return_research":
            errors.append("pass_cannot_keep_return_research_finding")


def _validate_scoring(record: Mapping[str, Any], errors: list[str]) -> None:
    scoring = record.get("scoring_evidence")
    if not isinstance(scoring, Mapping):
        errors.append("missing:scoring_evidence")
        return
    total = scoring.get("total_score")
    if isinstance(total, bool) or not isinstance(total, (int, float)):
        errors.append("invalid:total_score")
        return
    why = scoring.get("why_worth_reading")
    if not isinstance(why, list):
        errors.append("invalid:why_worth_reading")
        return
    if record.get("judgment_result") == "pass" and total >= 75:
        usable = [
            item
            for item in why
            if isinstance(item, Mapping)
            and _nonblank(item.get("locator"))
            and _nonblank(item.get("argument"))
        ]
        if not usable:
            errors.append("scoring_missing_why_worth_reading")


def _is_article_first_record(record: Mapping[str, Any]) -> bool:
    return (
        record.get("article_first_contract_version") == ARTICLE_FIRST_CONTRACT_VERSION
        or "content_fidelity_ref" in record
        or "content_fidelity_result" in record
    )


def _validate_content_fidelity_binding(
    record: Mapping[str, Any],
    errors: list[str],
) -> None:
    """Require postdraft judgment to point at the independently reviewed body."""

    if not _is_article_first_record(record):
        return
    reference = record.get("content_fidelity_ref")
    if (
        not isinstance(reference, Mapping)
        or not _nonblank(reference.get("path"))
        or not _SHA256.fullmatch(str(reference.get("sha256", "")))
    ):
        errors.append("content_fidelity_ref_required")
    result = record.get("content_fidelity_result")
    if result not in {"pass", "return_article", "return_material"}:
        errors.append("content_fidelity_result_required")
    elif record.get("judgment_result") == "pass" and result != "pass":
        errors.append("content_fidelity_pass_required")


def validate_editorial_judgment(
    record: Mapping[str, Any] | object,
    *,
    draft_text: str | None = None,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(record, Mapping):
        return ["record_must_be_an_object"]
    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version")
    modern = _is_article_first_record(record)
    path_value = record.get("body_draft_path") if modern else None
    if not path_value:
        path_value = record.get("draft_path")
    for field, value in (
        ("article_task_id", record.get("article_task_id")),
        ("article_id", record.get("article_id")),
        ("draft_path", path_value),
    ):
        if not _nonblank(value):
            errors.append(f"missing:{field}")
    digest = record.get("body_sha256") if modern and record.get("body_sha256") else record.get("draft_sha256")
    if not _nonblank(digest) or not _SHA256.fullmatch(str(digest)):
        errors.append("invalid:draft_sha256")
    if record.get("structure_result") not in STRUCTURE_RESULTS:
        errors.append("invalid:structure_result")
    if record.get("judgment_result") not in JUDGMENT_RESULTS:
        errors.append("invalid:judgment_result")
    structure_ref = record.get("structure_record_ref")
    if not isinstance(structure_ref, Mapping) or not _nonblank(structure_ref.get("path")) or not _SHA256.fullmatch(str(structure_ref.get("sha256", ""))):
        errors.append("invalid:structure_record_ref")
    layers = record.get("actor_layers")
    if not isinstance(layers, Mapping):
        errors.append("missing:actor_layers")
        layers = {}
    for name in LAYER_NAMES:
        _validate_layer(name, layers.get(name), errors)
    human = layers.get("human_confirmation") if isinstance(layers, Mapping) else None
    if record.get("judgment_result") == "pass":
        if not isinstance(human, Mapping) or human.get("result") != "pass":
            errors.append("human_confirmation_required_for_pass")
    _validate_increments(record, errors)
    _validate_findings(record, errors)
    _validate_scoring(record, errors)
    if modern:
        # This record is created after the body has been drafted/reviewed, so
        # postdraft reader evidence is legal here.  It still remains title-free
        # until the separate title-packaging phase.
        errors.extend(validate_phase_field_boundary(record, "content_review"))
        _validate_content_fidelity_binding(record, errors)
    if draft_text is not None and find_internal_review_language(draft_text):
        errors.append("internal_review_language")
    return sorted(set(errors))


def evaluate_editorial_judgment(
    record: Mapping[str, Any] | object,
    *,
    draft_text: str | None = None,
) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        return {
            "structure_result": None,
            "judgment_result": None,
            "combined_result": "invalid",
            "errors": ["record_must_be_an_object"],
        }
    errors = validate_editorial_judgment(record, draft_text=draft_text)
    structure_result = record.get("structure_result") if record.get("structure_result") in STRUCTURE_RESULTS else None
    judgment_result = record.get("judgment_result") if record.get("judgment_result") in JUDGMENT_RESULTS else None
    if errors:
        combined = "invalid"
    elif structure_result == "pass" and judgment_result == "pass":
        combined = "pass"
    elif judgment_result in JUDGMENT_RESULTS:
        combined = judgment_result
    else:
        combined = "invalid"
    return {
        "structure_result": structure_result,
        "judgment_result": judgment_result,
        "combined_result": combined,
        "errors": errors,
    }


__all__ = [
    "SCHEMA_VERSION",
    "evaluate_editorial_judgment",
    "find_internal_review_language",
    "validate_editorial_judgment",
]
