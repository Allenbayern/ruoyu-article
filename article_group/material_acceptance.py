"""Article Task material acceptance: crawled pages are not automatically writable."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import re

from .article_first import (
    ARTICLE_FIRST_CONTRACT_VERSION,
    HARD_INFORMATION_TYPES,
    validate_phase_field_boundary,
)
from .material_requirements import (
    evaluate_material_requirements,
    validate_material_requirements,
)
from .run_contract import (
    is_strict_run_contract,
    validate_phase_contract_fields,
    validate_run_contract,
)
from .source_capability import (
    CAPABILITY_LEVELS,
    source_capability_rank,
    validate_claim_capabilities,
)


SCHEMA_VERSION = "article-material-acceptance-v1"
DECISIONS = ("accept", "return_research", "reselect_angle")
REFERENCE_SHAPES = frozenset(
    {
        "workplace_reality_check",
        "relationship_plot_recap",
        "audience_culture_explainer",
        "adaptation_comparison",
        "viewing_commentary",
        "setting_observation",
    }
)
DENSE_REFERENCE_SHAPES = frozenset(REFERENCE_SHAPES - {"setting_observation"})
CLAIM_KINDS = (
    "program_schedule",
    "program_titles",
    "guest_behavior",
    "audience_psychology",
    "character_motivation",
    "audience_consensus",
    "dialogue",
    "scene_action",
)
CAPTURE_CAPABILITIES = {
    "page_metadata": {"program_schedule", "program_titles", "dates", "uploader_copy"},
    "page_fulltext": {"article_body_facts", "program_schedule", "program_titles"},
    "video_watched": {"guest_behavior", "scene_action"},
    "dialogue_transcript": {"dialogue", "attributed_speech", "guest_behavior"},
    "scene_verified": {"guest_behavior", "scene_action"},
    "audience_sample": {"scoped_audience_reaction", "audience_psychology"},
    "secondary_discussion": {"secondhand_claim"},
}
CLAIM_KIND_REQUIREMENTS = {
    "program_schedule": {"program_schedule", "program_titles", "dates"},
    "program_titles": {"program_titles", "program_schedule"},
    "guest_behavior": {"guest_behavior", "scene_action", "dialogue"},
    "audience_psychology": {"audience_psychology", "scoped_audience_reaction"},
    "character_motivation": {"dialogue", "attributed_speech", "guest_behavior"},
    "audience_consensus": set(),
    "dialogue": {"dialogue", "attributed_speech"},
    "scene_action": {"scene_action", "guest_behavior"},
}
FULLTEXT_CAPTURE_TYPES = {"page_fulltext", "dialogue_transcript"}
_SOURCE_CAPABILITY_KEYS = frozenset(
    {"source_capability", "capability_level", "max_claim_level", "narrative_capability"}
)
_CAPABILITY_CLAIM_KINDS = {
    "event_exists": {"program_schedule", "program_titles"},
    "character_setup": set(),
    "scene_action": {"guest_behavior", "scene_action"},
    "dialogue": {"guest_behavior", "character_motivation", "dialogue"},
    "audience_reaction": {"audience_psychology"},
    "mechanism": set(),
    "outcome": set(),
}
_TITLE_PUNCT = re.compile(r"[\s，。！？、：；,.!?:;“”\"'（）()【】\[\]《》]")
_TITLE_EQUIV = (
    ("有没有", ""),
    ("是否", ""),
    ("了", ""),
)


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: object) -> bool:
    return isinstance(value, list) and all(_nonblank(item) for item in value)


def _normalize_title(value: str) -> str:
    text = value.strip().lower()
    for source, target in _TITLE_EQUIV:
        text = text.replace(source, target)
    return _TITLE_PUNCT.sub("", text)


def _capabilities(sources: list[Mapping[str, Any]]) -> set[str]:
    caps: set[str] = set()
    for source in sources:
        if any(key in source for key in _SOURCE_CAPABILITY_KEYS):
            rank = source_capability_rank(source)
            if rank is not None:
                for level in CAPABILITY_LEVELS[: rank + 1]:
                    caps.update(_CAPABILITY_CLAIM_KINDS[level])
            continue
        capture = source.get("capture_type")
        caps.update(CAPTURE_CAPABILITIES.get(capture, set()))
    return caps


def _claim_kind_supported(kind: str, capabilities: set[str]) -> bool:
    required = CLAIM_KIND_REQUIREMENTS.get(kind)
    if required is None:
        return False
    if kind == "audience_consensus":
        return False
    return bool(required & capabilities)


def _source_ids(sources: list[Mapping[str, Any]]) -> set[str]:
    return {
        source["source_id"]
        for source in sources
        if isinstance(source.get("source_id"), str) and source["source_id"].strip()
    }


def validate_material_acceptance_record(
    record: Mapping[str, Any] | object,
    *,
    strict: bool | None = None,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(record, Mapping):
        return ["record_must_be_an_object"]
    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version")
    for field in (
        "article_task_id",
        "topic_id",
        "core_question",
        "decision",
    ):
        if not _nonblank(record.get(field)):
            errors.append(f"missing:{field}")
    if type(record.get("topic_version")) is not int or record.get("topic_version", 0) < 1:
        errors.append("invalid:topic_version")
    reference_shape = record.get("reference_shape")
    if reference_shape is not None:
        if not _nonblank(reference_shape) or reference_shape not in REFERENCE_SHAPES:
            errors.append("invalid:reference_shape")
        else:
            expected_floor = 5 if reference_shape in DENSE_REFERENCE_SHAPES else 3
            if "reader_gain_floor" in record and record.get("reader_gain_floor") != expected_floor:
                errors.append("invalid:reader_gain_floor_for_reference_shape")
    intended = record.get("intended_claim_kinds")
    if not isinstance(intended, list) or not intended or not all(isinstance(item, str) for item in intended):
        errors.append("invalid:intended_claim_kinds")
    else:
        for kind in intended:
            if kind not in CLAIM_KINDS:
                errors.append(f"invalid:intended_claim_kind:{kind}")
    sources = record.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("missing:sources")
        sources = []
    seen_ids: set[str] = set()
    for source in sources:
        if not isinstance(source, Mapping):
            errors.append("invalid:source")
            continue
        source_id = source.get("source_id")
        if not _nonblank(source_id):
            errors.append("missing:source_id")
            continue
        if source_id in seen_ids:
            errors.append(f"duplicate:source_id:{source_id}")
        seen_ids.add(str(source_id))
        capture = source.get("capture_type")
        if capture not in CAPTURE_CAPABILITIES:
            errors.append(f"invalid:capture_type:{source_id}")
        if not _nonblank(source.get("locator")):
            errors.append(f"missing:locator:{source_id}")
        if not _string_list(source.get("obtained_facts")):
            errors.append(f"invalid:obtained_facts:{source_id}")
        level = source.get("declared_source_level")
        if not _nonblank(level):
            errors.append(f"missing:declared_source_level:{source_id}")
        elif level == "fulltext" and capture not in FULLTEXT_CAPTURE_TYPES:
            errors.append(f"source_level_fulltext_for_metadata:{source_id}")
    if not _string_list(record.get("obtained_facts")):
        errors.append("invalid:obtained_facts")
    analyses = record.get("supported_analyses")
    if not isinstance(analyses, list) or not all(isinstance(item, str) for item in analyses):
        errors.append("invalid:supported_analyses")
    missing = record.get("missing_materials")
    if not isinstance(missing, list):
        errors.append("invalid:missing_materials")
    else:
        for item in missing:
            if not isinstance(item, Mapping) or not _nonblank(item.get("gap")) or not _nonblank(item.get("needed_for")):
                errors.append("invalid:missing_material")
    unanswerable = record.get("unanswerable_questions")
    if not isinstance(unanswerable, list) or not all(isinstance(item, str) for item in unanswerable):
        errors.append("invalid:unanswerable_questions")
    decision = record.get("decision")
    if decision not in DECISIONS:
        errors.append("invalid:decision")
    if decision in {"return_research", "reselect_angle"} and not _nonblank(record.get("return_rule")):
        errors.append("missing:return_rule")
    declared_strict = is_strict_run_contract(record)
    strict = declared_strict if strict is None else bool(strict or declared_strict)
    if strict:
        errors.extend(validate_phase_contract_fields(record, "material"))
    elif record.get("article_first_contract_version") == ARTICLE_FIRST_CONTRACT_VERSION:
        # Discovery signals and postdraft judgments must not leak into the
        # material-to-writing handoff.  Empty compatibility placeholders are
        # handled by the shared boundary helper and do not become inputs.
        errors.extend(validate_phase_field_boundary(record, "material"))
    if strict:
        if is_strict_run_contract(record):
            errors.extend(validate_run_contract(record))
        errors.extend(
            _validate_readiness(record, require_pass=record.get("decision") == "accept")
        )
        errors.extend(
            validate_claim_capabilities(
                sources,
                record.get("claims", []),
                # A returned/reselected pack is allowed to identify the
                # missing capture before the capability graph is complete.
                # Once the pack claims acceptance, the graph becomes a hard
                # boundary for every source and claim.
                strict=record.get("decision") == "accept",
            )
        )
    elif "claims" in record:
        errors.extend(
            validate_claim_capabilities(
                sources,
                record.get("claims"),
                strict=False,
            )
        )
    errors.extend(_validate_content_value_plan(record, strict=strict))
    errors.extend(_validate_title_directions(record, sources, strict=strict))
    # 2026-09-16：材料等级门槛（opt-in）。只有声明了 `material_requirements`
    # 的材料包才受约束：篇幅上限由材料等级决定，缺场面层时不能按长稿验收。
    errors.extend(validate_material_requirements(record))
    return sorted(set(errors))


def _readiness_values(record: Mapping[str, Any]) -> tuple[object, object]:
    readiness = record.get("readiness")
    if isinstance(readiness, Mapping):
        return (
            readiness.get("material_ready_for_draft", record.get("material_ready_for_draft")),
            readiness.get("editorial_value_ready", record.get("editorial_value_ready")),
        )
    return record.get("material_ready_for_draft"), record.get("editorial_value_ready")


def _validate_readiness(
    record: Mapping[str, Any],
    *,
    require_pass: bool,
) -> list[str]:
    material_ready, editorial_ready = _readiness_values(record)
    errors: list[str] = []
    if type(material_ready) is not bool:
        errors.append("missing:material_ready_for_draft")
    elif require_pass and not material_ready:
        errors.append("material_not_ready_for_draft")
    if type(editorial_ready) is not bool:
        errors.append("missing:editorial_value_ready")
    elif require_pass and not editorial_ready:
        errors.append("editorial_value_not_ready")
    return errors


def _validate_content_value_plan(
    record: Mapping[str, Any],
    *,
    strict: bool = False,
) -> list[str]:
    """Validate an optional article-first material-to-content bridge.

    The bridge describes what the material can support.  It is not a title
    promise and it deliberately has no ``reader_takeaway`` field; that
    judgment belongs to postdraft content review.
    """

    if not strict and record.get("article_first_contract_version") != ARTICLE_FIRST_CONTRACT_VERSION:
        return []
    plan = record.get("content_value_plan")
    if plan is None:
        if strict and record.get("decision") == "accept":
            return ["missing:content_value_plan"]
        # Existing material packs can be explicitly upgraded one field at a
        # time. The hard content gate remains responsible for the three-item
        # body audit after drafting.
        return []
    if not isinstance(plan, Mapping):
        return ["invalid:content_value_plan"]
    errors: list[str] = []
    raw_sources = record.get("sources")
    source_items = raw_sources if isinstance(raw_sources, list) else []
    known_source_ids = _source_ids(
        [item for item in source_items if isinstance(item, Mapping)]
    )
    items = plan.get("hard_information_plan")
    if not isinstance(items, list) or not items:
        errors.append("invalid:content_value_plan_hard_information_plan")
    else:
        kinds: set[str] = set()
        ids: set[str] = set()
        reference_shape = record.get("reference_shape")
        for index, item in enumerate(items):
            if not isinstance(item, Mapping):
                errors.append(f"invalid:content_value_plan_item:{index}")
                continue
            plan_id = item.get("plan_id")
            if not _nonblank(plan_id) or str(plan_id) in ids:
                errors.append(f"invalid:content_value_plan_id:{index}")
            else:
                ids.add(str(plan_id))
            kind = item.get("kind")
            if not _nonblank(kind):
                errors.append(f"missing:content_value_plan_kind:{index}")
            else:
                if kind not in HARD_INFORMATION_TYPES:
                    errors.append(f"invalid:content_value_plan_kind:{index}")
                else:
                    kinds.add(str(kind))
            refs = item.get("material_refs")
            if not _string_list(refs):
                errors.append(f"missing:content_value_plan_refs:{index}")
            elif strict:
                for ref in refs:
                    if ref not in known_source_ids:
                        errors.append(
                            f"unknown:content_value_plan_material_ref:{index}:{ref}"
                        )
            if reference_shape in REFERENCE_SHAPES and not _nonblank(item.get("reader_gain")):
                errors.append(f"missing:content_value_plan_reader_gain:{index}")
        if len(items) < 3:
            errors.append("content_value_plan_requires_at_least_3")
        if len(kinds) < 2:
            errors.append("content_value_plan_requires_two_types")
        if reference_shape in DENSE_REFERENCE_SHAPES:
            if len(items) < 5:
                errors.append("content_value_plan_requires_at_least_5_for_reference_shape")
            if len(kinds) < 3:
                errors.append("content_value_plan_requires_three_concrete_support_kinds")
    opening_refs = plan.get("opening_support_refs")
    if not _string_list(opening_refs):
        errors.append("missing:content_value_plan_opening_support")
    elif strict:
        for ref in opening_refs:
            if ref not in known_source_ids:
                errors.append(f"unknown:content_value_plan_opening_support:{ref}")
    if not _nonblank(plan.get("explanation_mechanism")):
        errors.append("missing:content_value_plan_explanation_mechanism")
    return errors


def _validate_title_directions(
    record: Mapping[str, Any],
    sources: list[Any],
    *,
    strict: bool = False,
) -> list[str]:
    errors: list[str] = []
    directions = record.get("title_directions", [])
    decision = record.get("decision")
    if directions in (None,):
        directions = []
    if not isinstance(directions, list):
        return ["invalid:title_directions"]
    if strict or record.get("article_first_contract_version") == ARTICLE_FIRST_CONTRACT_VERSION:
        # Empty compatibility placeholders are tolerated while old producers
        # migrate, but no actual candidate may steer the body writer before
        # content_passed creates the title-package phase.
        if directions:
            return ["title_directions_forbidden_before_content_passed"]
        return []
    if decision != "accept":
        if directions:
            errors.append("title_directions_forbidden_unless_accepted")
        return errors
    if not directions:
        errors.append("title_directions_required_on_accept")
        return errors
    if len(directions) > 3:
        errors.append("title_directions_exceed_three")
    known_ids = _source_ids([item for item in sources if isinstance(item, Mapping)])
    normalized_titles: list[str] = []
    normalized_angles: list[str] = []
    for index, item in enumerate(directions):
        if not isinstance(item, Mapping):
            errors.append(f"invalid:title_direction:{index}")
            continue
        for field in ("title", "click_reason", "opening_fulfillment_locator", "distinct_angle"):
            if not _nonblank(item.get(field)):
                errors.append(f"missing:title_direction_{field}:{index}")
        refs = item.get("evidence_refs")
        if not _string_list(refs):
            errors.append(f"invalid:title_direction_evidence:{index}")
        else:
            for ref in refs:
                if ref not in known_ids:
                    errors.append(f"title_direction_evidence_missing:{ref}")
        title = item.get("title")
        angle = item.get("distinct_angle")
        if _nonblank(title):
            normalized_titles.append(_normalize_title(str(title)))
        if _nonblank(angle):
            normalized_angles.append(_normalize_title(str(angle)))
    if len(normalized_titles) != len(set(normalized_titles)) or len(normalized_angles) != len(set(normalized_angles)):
        errors.append("title_directions_not_distinct")
    return errors


def compute_blocking_gaps(record: Mapping[str, Any]) -> list[str]:
    sources = record.get("sources")
    if not isinstance(sources, list):
        return []
    capabilities = _capabilities([item for item in sources if isinstance(item, Mapping)])
    gaps: list[str] = []
    intended = record.get("intended_claim_kinds")
    if isinstance(intended, list):
        for kind in intended:
            if isinstance(kind, str) and not _claim_kind_supported(kind, capabilities):
                gaps.append(kind)
    return gaps


def evaluate_material_acceptance(
    record: Mapping[str, Any] | object,
    *,
    strict: bool | None = None,
) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        return {
            "status": "invalid",
            "errors": ["record_must_be_an_object"],
            "blocking_gaps": [],
            "decision": None,
            "material_ready_for_draft": False,
            "editorial_value_ready": False,
        }
    declared_strict = is_strict_run_contract(record)
    strict = declared_strict if strict is None else bool(strict or declared_strict)
    errors = validate_material_acceptance_record(record, strict=strict)
    blocking_gaps = compute_blocking_gaps(record)
    decision = record.get("decision")
    material_ready, editorial_ready = _readiness_values(record)
    if not strict:
        if type(material_ready) is not bool:
            material_ready = not blocking_gaps and not any(
                _nonblank(item)
                for item in (record.get("unanswerable_questions") or [])
            )
        if type(editorial_ready) is not bool:
            editorial_ready = decision == "accept" and isinstance(
                record.get("content_value_plan"), Mapping
            )
    unanswerable = record.get("unanswerable_questions")
    if decision == "accept":
        for kind in blocking_gaps:
            errors.append(f"accept_requires_supported_claim_kind:{kind}")
        if isinstance(unanswerable, list) and any(_nonblank(item) for item in unanswerable):
            errors.append("core_question_unanswerable")
        if strict and (material_ready is not True or editorial_ready is not True):
            errors.append("accept_requires_both_readiness")
    errors = sorted(set(errors))
    if errors:
        status = "invalid"
    elif decision in DECISIONS:
        status = decision
    else:
        status = "invalid"
    return {
        "status": status,
        "errors": errors,
        "blocking_gaps": blocking_gaps,
        "decision": decision if decision in DECISIONS else None,
        "material_ready_for_draft": material_ready is True,
        "editorial_value_ready": editorial_ready is True,
        "material_requirements": evaluate_material_requirements(record),
    }


__all__ = [
    "SCHEMA_VERSION",
    "REFERENCE_SHAPES",
    "DENSE_REFERENCE_SHAPES",
    "compute_blocking_gaps",
    "evaluate_material_acceptance",
    "validate_material_acceptance_record",
]
