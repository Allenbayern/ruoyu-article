"""Skill registration and explicit fallback decisions for article workers."""

from __future__ import annotations

from typing import Any

_FALLBACK_ALLOWED_STAGES = {"drafting", "title_generation", "structure_generation"}
_STRUCTURED_INPUT_KINDS = {"structured_extract", "fact_card"}
_RAW_HTML_KEYS = {"raw_html", "html", "html_body", "html_content", "source_html"}


def resolve_worker_capability(
    *,
    requested_skill: str,
    registered_skills: set[str],
    fallback_allowed: bool,
    stage: str,
) -> dict[str, object]:
    if requested_skill in registered_skills:
        return {
            "status": "registered",
            "requested_skill": requested_skill,
            "fallback_used": False,
        }
    if fallback_allowed and stage in _FALLBACK_ALLOWED_STAGES:
        return {
            "status": "fallback",
            "requested_skill": requested_skill,
            "fallback_used": True,
            "fallback_reason": "requested_skill_not_registered",
        }
    return {
        "status": "blocked",
        "requested_skill": requested_skill,
        "fallback_used": False,
        "block_reason": "requested_skill_not_registered_for_stage",
    }


def validate_worker_input(worker_input: object) -> list[str]:
    """Require a bounded structured extract/fact card at the worker boundary."""
    if not isinstance(worker_input, dict):
        return ["worker_input_must_be_object"]

    errors: list[str] = []
    input_kind = worker_input.get("input_kind")
    if input_kind not in _STRUCTURED_INPUT_KINDS:
        errors.append("worker_input_kind_invalid")

    for key in sorted(_RAW_HTML_KEYS):
        value = worker_input.get(key)
        if value not in (None, "", [], {}):
            errors.append(f"worker_raw_html_not_allowed:{key}")

    structured_payload = (
        worker_input.get("extract")
        if input_kind == "structured_extract"
        else worker_input.get("fact_card")
    )
    if not isinstance(structured_payload, dict) or not structured_payload:
        errors.append("worker_structured_extract_missing")
    return errors


def build_worker_dispatch_record(
    *,
    requested_skill: str,
    registered_skills: set[str],
    fallback_allowed: bool,
    stage: str,
    worker_input: object,
) -> dict[str, Any]:
    """Create an auditable, non-authorizing worker dispatch decision."""
    capability = resolve_worker_capability(
        requested_skill=requested_skill,
        registered_skills=registered_skills,
        fallback_allowed=fallback_allowed,
        stage=stage,
    )
    input_errors = validate_worker_input(worker_input)
    status = "blocked" if capability["status"] == "blocked" or input_errors else capability["status"]
    record: dict[str, Any] = {
        "schema_version": "worker-dispatch-v1",
        "stage": stage,
        "requested_skill": requested_skill,
        "status": status,
        "capability": capability,
        "input_errors": input_errors,
        "publication_authorization": "not_authorized",
    }
    if input_errors:
        record["block_reason"] = "worker_input_contract_failed"
    return record
