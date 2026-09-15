"""V3 editorial state transitions and artifact contracts.

The Article Group owns the topic and the state transition. A crawl task may
only work on an approved topic, and a material pack may only open the writing
gate when its evidence boundaries and audit records are present.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from .run_contract import (
    is_strict_run_contract,
    validate_phase_contract_fields,
    validate_run_contract,
)
from .source_capability import validate_claim_capabilities

STATES = (
    "idea",
    "precheck",
    "approved",
    "researching",
    "material_ready",
    "writing",
    "review",
    "returned",
    "closed",
)

TOPIC_CARD_SCHEMA_VERSION = "topic-card-v1"
CRAWL_TASK_SCHEMA_VERSION = "crawl-task-v1"
MATERIAL_PACK_SCHEMA_VERSION = "material-pack-v1"

_ALLOWED = {
    "idea": {"precheck", "closed"},
    "precheck": {"approved", "returned", "closed"},
    "approved": {"researching", "returned", "closed"},
    "researching": {"material_ready", "returned", "closed"},
    "material_ready": {"writing", "returned", "closed"},
    "writing": {"review", "returned", "closed"},
    "review": {"closed", "returned"},
    "returned": {"precheck", "researching", "closed"},
    "closed": set(),
}

_MISSING = object()
_SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "editorial-pipeline-v3"
_SCHEMA_CACHE: dict[str, Draft202012Validator] = {}
_MATERIAL_CATEGORIES = (
    "body_facts",
    "industry_context",
    "audience_reactions",
    "cross_check_facts",
)
_REQUIRED_MATERIAL_LABELS = ("正文事实", "行业背景", "观众反应", "复核事实")
_REQUIRED_DELIVERABLES = (
    "material-pack.json",
    "source-audit.json",
    "screening-log.md",
    "gap-list.md",
)


@dataclass(frozen=True)
class Transition:
    from_state: str
    to_state: str


def _schema_validator(name: str) -> Draft202012Validator | None:
    validator = _SCHEMA_CACHE.get(name)
    if validator is not None:
        return validator

    path = _SCHEMA_DIR / f"{name}.schema.json"
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
    except (OSError, json.JSONDecodeError):
        return None

    _SCHEMA_CACHE[name] = validator
    return validator


def _schema_errors(name: str, value: object) -> list[str]:
    validator = _schema_validator(name)
    if validator is None:
        return [f"schema_unavailable:{name}"]

    errors: list[str] = []
    for error in validator.iter_errors(value):
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        message = " ".join(error.message.split())
        errors.append(f"schema.{error.validator}:{path}:{message}")
    return sorted(set(errors))


def _is_mapping(value: object) -> bool:
    return isinstance(value, Mapping)


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _get(value: object, key: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return default


def _append_if(errors: list[str], condition: bool, message: str) -> None:
    if condition and message not in errors:
        errors.append(message)


def _matching_identity(
    artifact: Mapping[str, Any],
    topic_card: Mapping[str, Any] | None,
    *,
    topic_id_field: str = "topic_id",
    version_field: str = "topic_version",
) -> list[str]:
    if topic_card is None:
        return []

    errors: list[str] = []
    if topic_id_field in artifact and "topic_id" in topic_card:
        _append_if(
            errors,
            artifact[topic_id_field] != topic_card["topic_id"],
            "topic_mismatch",
        )
    if version_field in artifact and "version" in topic_card:
        _append_if(
            errors,
            artifact[version_field] != topic_card["version"],
            "topic_version_mismatch",
        )
    return errors


def _valid_topic_reference(topic_card: Mapping[str, Any] | None) -> bool:
    return (
        topic_card is not None
        and _is_mapping(topic_card)
        and not validate_topic_card(topic_card)
    )


def validate_transition(
    from_state: str,
    to_state: str,
    *,
    topic_card: Mapping[str, Any] | None | object = _MISSING,
    crawl_task: Mapping[str, Any] | None | object = _MISSING,
    material_pack: Mapping[str, Any] | None | object = _MISSING,
    strict: bool | None = None,
) -> list[str]:
    """Validate a V3 transition and, when supplied, its artifact gate.

    The original two-argument API remains a lightweight state-only check for
    compatibility. Supplying any artifact argument turns on the relevant
    contract checks. Call :func:`validate_pipeline_transition` when a strict
    gate is required even if no artifacts are available yet.
    """

    errors: list[str] = []
    if from_state not in STATES:
        errors.append(f"unknown_from_state:{from_state}")
    if to_state not in STATES:
        errors.append(f"unknown_to_state:{to_state}")
    if errors:
        return errors
    if to_state not in _ALLOWED[from_state]:
        return [f"transition_not_allowed:{from_state}->{to_state}"]

    artifact_validation = any(
        artifact is not _MISSING
        for artifact in (topic_card, crawl_task, material_pack)
    )
    if not artifact_validation and strict is not True:
        return []

    return _validate_transition_artifacts(
        from_state,
        to_state,
        topic_card=None if topic_card is _MISSING else topic_card,
        crawl_task=None if crawl_task is _MISSING else crawl_task,
        material_pack=None if material_pack is _MISSING else material_pack,
        strict=strict,
    )


def validate_pipeline_transition(
    from_state: str,
    to_state: str,
    *,
    topic_card: Mapping[str, Any] | None = None,
    crawl_task: Mapping[str, Any] | None = None,
    material_pack: Mapping[str, Any] | None = None,
    strict: bool | None = None,
) -> list[str]:
    """Strictly validate a transition, including required artifact gates."""

    errors = validate_transition(from_state, to_state)
    if errors:
        return errors
    return _validate_transition_artifacts(
        from_state,
        to_state,
        topic_card=topic_card,
        crawl_task=crawl_task,
        material_pack=material_pack,
        strict=strict,
    )


def _validate_transition_artifacts(
    from_state: str,
    to_state: str,
    *,
    topic_card: Mapping[str, Any] | None,
    crawl_task: Mapping[str, Any] | None,
    material_pack: Mapping[str, Any] | None,
    strict: bool | None = None,
) -> list[str]:
    errors: list[str] = []

    if from_state == "precheck" and to_state == "approved":
        if topic_card is None:
            errors.append("missing:topic_card")
        else:
            card_for_approval = topic_card
            if _is_mapping(topic_card) and topic_card.get("status") == "precheck":
                # Validate the candidate against the target contract without
                # mutating the caller's current precheck record.
                card_for_approval = {**topic_card, "status": "approved"}
            errors.extend(validate_topic_card(card_for_approval))
            _append_if(
                errors,
                _get(topic_card, "status") not in {"precheck", "approved"},
                "topic_card_not_approved",
            )

    if from_state == "approved" and to_state == "researching":
        if topic_card is None:
            errors.append("missing:topic_card")
        else:
            errors.extend(validate_topic_card(topic_card))
            _append_if(
                errors,
                _get(topic_card, "status") != "approved",
                "topic_not_approved_for_crawl",
            )
        if crawl_task is None:
            errors.append("missing:crawl_task")
        else:
            errors.extend(validate_crawl_task(crawl_task, topic_card=topic_card))
            _append_if(
                errors,
                _get(crawl_task, "status") != "researching",
                "crawl_task_not_researching",
            )

    if from_state == "researching" and to_state == "material_ready":
        if topic_card is None:
            errors.append("missing:topic_card")
        else:
            errors.extend(validate_topic_card(topic_card))
            _append_if(
                errors,
                _get(topic_card, "status") != "approved",
                "topic_not_approved_for_crawl",
            )
        if crawl_task is None:
            errors.append("missing:crawl_task")
        else:
            errors.extend(validate_crawl_task(crawl_task, topic_card=topic_card))
            _append_if(
                errors,
                _get(crawl_task, "status") != "material_ready",
                "crawl_task_not_material_ready",
            )
        if material_pack is None:
            errors.append("missing:material_pack")
        else:
            errors.extend(
                validate_material_pack(
                    material_pack,
                    topic_card=topic_card,
                    crawl_task=crawl_task,
                    strict=strict,
                )
            )
            _append_if(
                errors,
                _get(material_pack, "status") != "material_ready",
                "material_pack_not_ready",
            )

    if from_state == "material_ready" and to_state == "writing":
        if topic_card is None:
            errors.append("missing:topic_card")
        else:
            errors.extend(validate_topic_card(topic_card))
            _append_if(
                errors,
                _get(topic_card, "status") != "approved",
                "topic_not_approved_for_writing",
            )
        if crawl_task is None:
            errors.append("missing:crawl_task")
        else:
            errors.extend(validate_crawl_task(crawl_task, topic_card=topic_card))
            _append_if(
                errors,
                _get(crawl_task, "status") != "material_ready",
                "crawl_task_not_material_ready",
            )
        if material_pack is None:
            errors.append("missing:material_pack")
        else:
            errors.extend(
                validate_material_pack(
                    material_pack,
                    topic_card=topic_card,
                    crawl_task=crawl_task,
                    strict=strict,
                )
            )
            _append_if(
                errors,
                _get(material_pack, "status") != "material_ready",
                "material_pack_not_ready",
            )

    if from_state == "returned" and to_state == "precheck":
        if topic_card is None:
            errors.append("missing:topic_card")
        else:
            errors.extend(validate_topic_card(topic_card))
            _append_if(
                errors,
                _get(topic_card, "status") != "precheck",
                "topic_card_not_in_precheck",
            )

    if from_state == "returned" and to_state == "researching":
        if topic_card is None:
            errors.append("missing:topic_card")
        else:
            errors.extend(validate_topic_card(topic_card))
            _append_if(
                errors,
                _get(topic_card, "status") != "approved",
                "topic_not_approved_for_crawl",
            )
        if crawl_task is None:
            errors.append("missing:crawl_task")
        else:
            errors.extend(validate_crawl_task(crawl_task, topic_card=topic_card))
            _append_if(
                errors,
                _get(crawl_task, "status") != "researching",
                "crawl_task_not_researching",
            )

    return _unique_errors(errors)


def validate_topic_card(card: object) -> list[str]:
    """Validate the V3 topic-card shape and approval prerequisites."""

    errors = _schema_errors("topic-card-v1", card)
    if not _is_mapping(card):
        return errors

    topic_object = card.get("object")
    if _is_mapping(topic_object):
        _append_if(
            errors,
            not any(
                _nonblank(topic_object.get(key))
                for key in ("work_or_person", "event")
            ),
            "topic_requires_concrete_object",
        )

    status = card.get("status")
    if status in {"precheck", "approved"}:
        for field in (
            "core_question",
            "target_reader",
            "article_type",
            "conflict_or_contrast",
            "reader_benefit",
        ):
            _append_if(
                errors,
                not _nonblank(card.get(field)),
                f"{status}_requires:{field}",
            )
        _append_if(
            errors,
            not _nonblank(_get(card.get("freshness"), "reason")),
            f"{status}_requires:freshness.reason",
        )
        _append_if(
            errors,
            not _nonblank(_get(card.get("historical_dedupe"), "new_angle")),
            f"{status}_requires:historical_dedupe.new_angle",
        )
        requirements = card.get("material_requirements")
        if isinstance(requirements, list):
            for label in _REQUIRED_MATERIAL_LABELS:
                _append_if(
                    errors,
                    label not in requirements,
                    f"{status}_missing_material_requirement:{label}",
                )
        acceptance = card.get("acceptance")
        if _is_mapping(acceptance):
            _append_if(
                errors,
                type(acceptance.get("min_concrete_support_types")) is not int
                or acceptance.get("min_concrete_support_types", 0) < 2,
                f"{status}_requires:min_concrete_support_types>=2",
            )

    if status == "approved":
        for field in ("article_group_owner", "decided_by", "decided_at", "deadline"):
            _append_if(
                errors,
                not _nonblank(card.get(field)),
                f"approved_topic_requires:{field}",
            )

        dedupe = card.get("historical_dedupe")
        if _is_mapping(dedupe):
            for field in ("same_work", "same_event_cluster", "near_title"):
                _append_if(
                    errors,
                    dedupe.get(field) not in {"pass", "override"},
                    f"approved_topic_dedupe_incomplete:{field}",
                )
            if any(
                dedupe.get(field) == "override"
                for field in ("same_work", "same_event_cluster", "near_title")
            ):
                _append_if(
                    errors,
                    not (
                        _nonblank(dedupe.get("override_reason"))
                        or _nonblank(card.get("override_reason"))
                    ),
                    "approved_topic_requires:override_reason",
                )

    if status == "returned":
        reasons = card.get("return_reasons")
        _append_if(
            errors,
            not isinstance(reasons, list) or not reasons,
            "returned_requires_reason",
        )

    return _unique_errors(errors)


def validate_crawl_task(
    task: object,
    *,
    topic_card: Mapping[str, Any] | None = None,
) -> list[str]:
    """Validate a crawl task and bind it to an approved topic/version."""

    errors = _schema_errors("crawl-task-v1", task)
    if not _is_mapping(task):
        return errors

    if topic_card is not None:
        if not _valid_topic_reference(topic_card):
            errors.append("invalid:topic_card")
        if _is_mapping(topic_card):
            errors.extend(_matching_identity(task, topic_card))
            _append_if(
                errors,
                topic_card.get("status") != "approved",
                "topic_not_approved_for_crawl",
            )

    deliverables = task.get("deliverables")
    if isinstance(deliverables, list):
        for required in _REQUIRED_DELIVERABLES:
            _append_if(
                errors,
                required not in deliverables,
                f"missing:deliverable:{required}",
            )

    retry = task.get("retry")
    _append_if(
        errors,
        task.get("status") in {"researching", "material_ready"}
        and isinstance(retry, Mapping)
        and retry.get("state") == "exhausted",
        "crawl_task_retry_exhausted",
    )

    if task.get("status") == "returned":
        reasons = task.get("return_reasons")
        _append_if(
            errors,
            not isinstance(reasons, list) or not reasons,
            "returned_requires_reason",
        )

    return _unique_errors(errors)


def validate_material_pack(
    pack: object,
    *,
    topic_card: Mapping[str, Any] | None = None,
    crawl_task: Mapping[str, Any] | None = None,
    strict: bool | None = None,
) -> list[str]:
    """Validate material evidence, audit visibility, and readiness criteria."""

    errors = _schema_errors("material-pack-v1", pack)
    if not _is_mapping(pack):
        return errors

    if topic_card is not None:
        if not _valid_topic_reference(topic_card):
            errors.append("invalid:topic_card")
        if _is_mapping(topic_card):
            errors.extend(_matching_identity(pack, topic_card))
            _append_if(
                errors,
                topic_card.get("status") != "approved",
                "topic_not_approved_for_material",
            )

    if crawl_task is not None:
        if not _is_mapping(crawl_task):
            errors.append("invalid:crawl_task")
        else:
            _append_if(
                errors,
                pack.get("crawl_task_id") != crawl_task.get("task_id"),
                "crawl_task_mismatch",
            )
            _append_if(
                errors,
                pack.get("topic_id") != crawl_task.get("topic_id"),
                "topic_mismatch",
            )
            _append_if(
                errors,
                pack.get("topic_version") != crawl_task.get("topic_version"),
                "topic_version_mismatch",
            )

    declared_strict = is_strict_run_contract(pack)
    strict = declared_strict if strict is None else bool(strict or declared_strict)
    if is_strict_run_contract(pack):
        errors.extend(validate_run_contract(pack))

    material_ids: set[str] = set()
    capability_sources: list[Mapping[str, Any]] = []
    materials = pack.get("materials")
    if isinstance(materials, Mapping):
        for category in _MATERIAL_CATEGORIES:
            entries = materials.get(category)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not _is_mapping(entry):
                    continue
                material_id = entry.get("material_id")
                if isinstance(material_id, str):
                    _append_if(
                        errors,
                        material_id in material_ids,
                        f"duplicate:material_id:{material_id}",
                    )
                    material_ids.add(material_id)
                capability_sources.append(entry)
                _append_if(
                    errors,
                    entry.get("category") != category,
                    f"material_category_mismatch:{category}",
                )
                _append_if(
                    errors,
                    category in {"body_facts", "cross_check_facts"}
                    and entry.get("source_role") == "discovery_signal",
                    "discovery_signal_not_fact_proof",
                )
                if category == "audience_reactions":
                    _append_if(
                        errors,
                        not _nonblank(entry.get("sample_scope")),
                        "audience_material_requires_sample_scope",
                    )
                    _append_if(
                        errors,
                        entry.get("generalization_allowed") is not False,
                        "audience_material_forbids_generalization",
                    )

    claims = pack.get("claims")
    if isinstance(claims, Mapping):
        claim_ids: set[str] = set()
        for bucket in ("facts", "attributed_views", "audience_reactions", "inferences"):
            entries = claims.get(bucket)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not _is_mapping(entry):
                    continue
                claim_id = entry.get("claim_id")
                if isinstance(claim_id, str):
                    _append_if(
                        errors,
                        claim_id in claim_ids,
                        f"duplicate:claim_id:{claim_id}",
                    )
                    claim_ids.add(claim_id)
                refs = entry.get("material_ids")
                if isinstance(refs, list):
                    for material_id in refs:
                        _append_if(
                            errors,
                            material_id not in material_ids,
                            f"unknown_material_ref:{material_id}",
                        )

    if strict:
        errors.extend(validate_phase_contract_fields(pack, "material"))
        errors.extend(
            validate_claim_capabilities(
                capability_sources,
                claims,
                # A returned pack is an explicit hand-back of incomplete
                # research.  Capability completeness becomes a hard gate only
                # when the pack declares that it is ready to open writing.
                strict=pack.get("status") == "material_ready",
            )
        )
        acceptance = pack.get("acceptance")
        if _is_mapping(acceptance):
            errors.extend(
                _validate_readiness_fields(
                    acceptance,
                    require_pass=pack.get("status") == "material_ready",
                )
            )

    if pack.get("status") == "material_ready":
        _validate_material_ready_gate(
            errors, pack, material_ids, topic_card, strict=strict
        )
    elif pack.get("status") == "returned":
        reasons = pack.get("return_reasons")
        _append_if(
            errors,
            not isinstance(reasons, list) or not reasons,
            "returned_requires_reason",
        )

    source_audit = pack.get("source_audit")
    retry_state = pack.get("retry_state")
    if _is_mapping(source_audit) and _is_mapping(retry_state):
        _append_if(
            errors,
            source_audit.get("version") != retry_state.get("version"),
            "audit_retry_version_mismatch",
        )
        _append_if(
            errors,
            pack.get("version") != source_audit.get("version"),
            "pack_audit_version_mismatch",
        )
        _append_if(
            errors,
            source_audit.get("retry_required")
            and retry_state.get("state") in {"not_required", "complete"},
            "retry_state_inconsistent",
        )

    return _unique_errors(errors)


def _validate_readiness_fields(
    acceptance: Mapping[str, Any],
    *,
    require_pass: bool,
) -> list[str]:
    """Require explicit readiness values, but allow an explicit return."""

    errors: list[str] = []
    material_ready = acceptance.get("material_ready_for_draft")
    editorial_ready = acceptance.get("editorial_value_ready")
    if type(material_ready) is not bool:
        errors.append("missing:material_ready_for_draft")
    elif require_pass and not material_ready:
        errors.append("material_not_ready_for_draft")
    if type(editorial_ready) is not bool:
        errors.append("missing:editorial_value_ready")
    elif require_pass and not editorial_ready:
        errors.append("editorial_value_not_ready")
    if require_pass and (material_ready is not True or editorial_ready is not True):
        errors.append("material_ready_requires_both_readiness")
    return errors


def _validate_material_ready_gate(
    errors: list[str],
    pack: Mapping[str, Any],
    material_ids: set[str],
    topic_card: Mapping[str, Any] | None,
    *,
    strict: bool = False,
) -> None:
    materials = pack.get("materials")
    if isinstance(materials, Mapping):
        for category in _MATERIAL_CATEGORIES:
            entries = materials.get(category)
            _append_if(
                errors,
                not isinstance(entries, list) or not entries,
                f"material_ready_missing:{category}",
            )

    acceptance = pack.get("acceptance")
    if not isinstance(acceptance, Mapping):
        return

    _append_if(
        errors,
        acceptance.get("core_question_preserved") is not True,
        "material_ready_question_drift",
    )
    support_types = acceptance.get("concrete_support_types")
    min_support_types = 2
    if _is_mapping(topic_card) and _is_mapping(topic_card.get("acceptance")):
        configured_min = topic_card["acceptance"].get("min_concrete_support_types")
        if isinstance(configured_min, int) and not isinstance(configured_min, bool):
            min_support_types = configured_min
    _append_if(
        errors,
        not isinstance(support_types, list)
        or len({item for item in support_types if isinstance(item, str)}) < min_support_types,
        "material_ready_requires_two_support_types",
    )

    opening_ids = acceptance.get("opening_support_material_ids")
    opening_required = True
    if _is_mapping(topic_card) and _is_mapping(topic_card.get("acceptance")):
        opening_required = topic_card["acceptance"].get("opening_support_required") is not False
    _append_if(
        errors,
        opening_required
        and (
            not isinstance(opening_ids, list)
            or not opening_ids
            or any(
                not isinstance(material_id, str) or material_id not in material_ids
                for material_id in opening_ids
            )
        ),
        "material_ready_requires_opening_support",
    )
    _append_if(
        errors,
        acceptance.get("key_facts_traceable") is not True,
        "material_ready_requires_traceable_facts",
    )
    _append_if(
        errors,
        acceptance.get("industry_context_relevant") is not True,
        "material_ready_requires_industry_context",
    )
    _append_if(
        errors,
        acceptance.get("audience_sample_scoped") is not True,
        "material_ready_requires_audience_scope",
    )
    _append_if(
        errors,
        acceptance.get("duplicates_screened") is not True,
        "material_ready_requires_duplicate_screening",
    )
    _append_if(
        errors,
        acceptance.get("failed_sources_visible") is not True,
        "material_ready_requires_failed_sources",
    )
    _append_if(
        errors,
        isinstance(acceptance.get("blocking_gaps"), list)
        and bool(acceptance.get("blocking_gaps")),
        "material_ready_has_blocking_gap",
    )

    audience_sample = pack.get("audience_sample")
    _append_if(
        errors,
        not isinstance(audience_sample, Mapping)
        or not _nonblank(audience_sample.get("scope"))
        or audience_sample.get("generalization_allowed") is not False,
        "material_ready_requires_audience_boundary",
    )

    source_audit = pack.get("source_audit")
    retry_state = pack.get("retry_state")
    _append_if(
        errors,
        isinstance(source_audit, Mapping) and source_audit.get("retry_required") is True,
        "material_ready_has_retry_requirement",
    )
    _append_if(
        errors,
        isinstance(retry_state, Mapping)
        and retry_state.get("state") in {"in_progress", "required", "exhausted"},
        "material_ready_has_retry_requirement",
    )


def validate_identity(record: object) -> list[str]:
    """Validate the common topic identity used by the state machine."""

    if not _is_mapping(record):
        return ["invalid:record"]

    errors: list[str] = []
    for field in ("topic_id", "topic_version", "status"):
        if field not in record or record[field] in (None, ""):
            errors.append(f"missing:{field}")
    if "status" in record and record.get("status") not in STATES:
        errors.append("invalid:status")
    if "topic_version" in record and (
        type(record["topic_version"]) is not int or record["topic_version"] < 1
    ):
        errors.append("invalid:topic_version")
    return _unique_errors(errors)


def validate_v4_transition_context(
    from_state: str,
    to_state: str,
    *,
    portfolio_plan: Mapping[str, Any] | None,
    evidence_graph: Mapping[str, Any] | None,
    gap_report: Mapping[str, Any] | None,
    recovery_actions: Mapping[str, Any] | None,
) -> list[str]:
    """Apply V4 context gates without changing the V3 state machine.

    This adapter is intentionally additive.  The caller must still run the
    existing V3 artifact/controller validation, especially for ``review`` to
    ``closed``.  It never starts a crawl, changes a topic, or grants delivery
    or publication authority.
    """

    errors = validate_transition(from_state, to_state)
    if errors:
        return errors

    # Keep authorization outside this adapter's result.  A supplied artifact
    # may only carry the explicit non-authorizing value.
    def authorization_errors(label: str, value: object) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                if key == "publication_authorization" and nested != "not_authorized":
                    errors.append(f"forbidden:{label}:publication_authorization")
                elif isinstance(nested, (Mapping, list, tuple)):
                    authorization_errors(label, nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                authorization_errors(label, nested)

    for label, value in (
        ("portfolio", portfolio_plan),
        ("evidence", evidence_graph),
        ("gaps", gap_report),
        ("recovery", recovery_actions),
    ):
        authorization_errors(label, value)

    def payload(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            return {}
        nested = value.get("payload")
        return nested if isinstance(nested, Mapping) else value

    if from_state == "approved" and to_state == "researching":
        if not isinstance(portfolio_plan, Mapping):
            errors.append("missing:v4_portfolio")
        else:
            portfolio_payload = payload(portfolio_plan)
            selected_ids = portfolio_payload.get("selected_article_ids")
            from .v4.portfolio import portfolio_gate_for_transition

            errors.extend(portfolio_gate_for_transition(portfolio_plan, selected_ids))

    if from_state == "material_ready" and to_state == "writing":
        if not isinstance(evidence_graph, Mapping):
            errors.append("missing:v4_evidence_graph")
        else:
            from .v4.evidence_graph import validate_evidence_graph_structure

            errors.extend(
                f"evidence_graph:{error}"
                for error in validate_evidence_graph_structure(evidence_graph)
            )
            graph_payload = payload(evidence_graph)
            nodes = graph_payload.get("nodes")
            if isinstance(nodes, Mapping):
                for node_id in sorted(
                    node_id
                    for node_id, node in nodes.items()
                    if isinstance(node_id, str)
                    and isinstance(node, Mapping)
                    and node.get("status") == "stale"
                ):
                    errors.append(f"stale:evidence:{node_id}")

        if not isinstance(gap_report, Mapping):
            errors.append("missing:v4_gap_report")
        else:
            gaps_payload = payload(gap_report)
            blocking = gaps_payload.get("blocking_gaps")
            if blocking is None:
                errors.append("missing:blocking_gaps")
            elif not isinstance(blocking, list):
                errors.append("invalid:blocking_gaps")
            else:
                for gap_id in blocking:
                    if isinstance(gap_id, str) and gap_id.strip():
                        errors.append(f"blocking_gap:{gap_id}")
                    else:
                        errors.append("invalid:blocking_gap")

        recovery_payload = payload(recovery_actions)
        actions = recovery_payload.get("actions")
        if isinstance(actions, list):
            for action in actions:
                if not isinstance(action, Mapping):
                    continue
                if action.get("action_type") == "block_writing" or action.get(
                    "next_state"
                ) == "blocked":
                    errors.append("recovery:blocks_writing")

    # ``review -> closed`` deliberately has no replacement V4 shortcut here.
    # Existing V3 review/controller evidence remains the required gate in the
    # caller that invokes validate_pipeline_transition.
    return _unique_errors(errors)


def validate_v5_transition_context(
    from_state: str,
    to_state: str,
    *,
    experiment_record: Mapping[str, Any] | None = None,
    lifecycle_record: Mapping[str, Any] | None = None,
    dna_record: Mapping[str, Any] | None = None,
    failure_report: Mapping[str, Any] | None = None,
    quota_plan: Mapping[str, Any] | None = None,
    strategy_library: Mapping[str, Any] | None = None,
    resource_plan: Mapping[str, Any] | None = None,
) -> list[str]:
    """Lazily delegate V5 gates while keeping the V3 module dependency-free."""

    from article_group.v5.integration import validate_v5_transition_context as _delegate

    return _delegate(
        from_state,
        to_state,
        experiment_record=experiment_record,
        lifecycle_record=lifecycle_record,
        dna_record=dna_record,
        failure_report=failure_report,
        quota_plan=quota_plan,
        strategy_library=strategy_library,
        resource_plan=resource_plan,
    )


def _unique_errors(errors: list[str]) -> list[str]:
    return list(dict.fromkeys(errors))
