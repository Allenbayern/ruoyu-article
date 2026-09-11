"""Shared contract for article-first production.

The article-first lane deliberately has no title contract while content is
being written.  Title packaging is a later, separately bound artifact.
Historical records may still contain the old title fields; callers should
identify those records explicitly rather than copying the fields forward.
"""

from __future__ import annotations

from collections.abc import Mapping

ARTICLE_FIRST_CONTRACT_VERSION = "article-first-v1"

ARTICLE_FIRST_STATES = (
    "brief_locked",
    "drafting_content",
    "content_review",
    "content_passed",
    "title_packaging",
    "title_review",
    "final_review",
    "delivered",
)

CONTENT_STATES = frozenset(
    {"brief_locked", "drafting_content", "content_review", "content_passed"}
)
TITLE_STATES = frozenset({"title_packaging", "title_review"})
POSTDRAFT_FIELDS = frozenset({"reader_takeaway", "reader_takeaway_locator"})
TITLE_PACKAGING_RESULTS = ("selected", "return_article", "return_material")
TITLE_PACKAGING_ROUTES = {
    "selected": "title_review",
    "return_article": "content_review",
    "return_material": "material_return",
}
HARD_INFORMATION_TYPES = frozenset(
    {"fact", "scene", "action", "relationship", "mechanism", "specific_context"}
)

# These names are intentionally broader than the old title_promise field.  A
# nested occurrence is still a title-first input and must not reach the body
# writer or content review record.
TITLE_FIRST_FIELDS = frozenset(
    {
        "title",
        "title_promise",
        "title_skeleton",
        "title_directions",
        "title_core_fact",
        "title_candidate_matrix",
        "title_candidates",
        "title_evidence_ref",
        "title_qc_ref",
        "title_qc_draft_path",
        "title_qc_draft_sha256",
        "title_review_target",
        "title_selection_note",
        "selected_title_id",
        "opening_fulfillment_plan",
        "opening_fulfillment_locator",
        "title_pack",
        "title_pack_path",
        "title_review_path",
        "delivery_path",
        "title_review_result",
    }
)
_TITLE_LEGACY_FIELDS = frozenset(
    {
        "title_promise",
        "title_candidates",
        "title_candidate_matrix",
        "title_evidence_ref",
        "title_qc_ref",
        "title_qc_draft_path",
        "title_qc_draft_sha256",
        "title_review_target",
        "opening_fulfillment_plan",
        "opening_fulfillment_locator",
    }
)

_TRANSITIONS = {
    ("brief_locked", "drafting_content"),
    ("drafting_content", "content_review"),
    ("content_review", "drafting_content"),
    ("content_review", "content_passed"),
    ("content_passed", "title_packaging"),
    ("title_packaging", "title_review"),
    ("title_packaging", "content_review"),
    ("title_review", "content_review"),
    ("title_review", "title_packaging"),
    ("title_review", "final_review"),
    ("final_review", "title_review"),
    ("final_review", "delivered"),
}


def _walk_keys(value: object, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str):
                path = f"{prefix}.{key}" if prefix else key
                if key in TITLE_FIRST_FIELDS and _has_nonempty_value(child):
                    found.append(path)
                found.extend(_walk_keys(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_walk_keys(child, f"{prefix}[{index}]"))
    return found


def _has_nonempty_value(value: object) -> bool:
    """Treat empty title placeholders as absent while rejecting real values."""

    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return any(_has_nonempty_value(child) for child in value.values())
    if isinstance(value, list):
        return any(_has_nonempty_value(child) for child in value)
    return bool(value)


def is_article_first_record(record: object) -> bool:
    """Return true only for an explicitly declared modern record.

    The path triplet is accepted as a migration convenience, but an old title
    field alone never upgrades a historical record into the modern lane.
    """

    if not isinstance(record, Mapping):
        return False
    if record.get("article_first_contract_version") == ARTICLE_FIRST_CONTRACT_VERSION:
        return True
    return all(
        isinstance(record.get(field), str) and bool(record[field].strip())
        for field in ("body_draft_path", "title_pack_path", "delivery_path")
    )


def title_packaging_route(result: object) -> str | None:
    """Return the only legal next handoff for a title-package result."""

    if not isinstance(result, str):
        return None
    return TITLE_PACKAGING_ROUTES.get(result)


def validate_article_first_transition(
    from_state: str,
    to_state: str,
    *,
    decision: str | None = None,
) -> list[str]:
    """Validate the article-first state graph and explicit return semantics."""

    if from_state not in ARTICLE_FIRST_STATES:
        return [f"unknown_article_first_from_state:{from_state}"]
    if to_state == "material_return":
        if from_state == "content_review":
            if decision != "return_material":
                return ["material_return_requires_content_review_decision"]
            return []
        if from_state not in {"title_packaging", "title_review"} or decision != "return_material":
            return ["material_return_requires_title_packaging_decision"]
        return []
    if to_state not in ARTICLE_FIRST_STATES:
        return [f"unknown_article_first_to_state:{to_state}"]
    if from_state in CONTENT_STATES and from_state != "content_passed" and to_state in TITLE_STATES | {"final_review", "delivered"}:
        return ["content_pass_required_before_title_packaging"]
    if (from_state, to_state) not in _TRANSITIONS:
        return [f"article_first_transition_not_allowed:{from_state}->{to_state}"]
    if from_state == "title_packaging" and to_state == "content_review":
        if decision != "return_article":
            return ["title_packaging_return_article_decision_required"]
    if from_state == "title_review" and to_state == "content_review":
        if decision != "return_article":
            return ["title_review_return_article_decision_required"]
    if from_state == "title_packaging" and to_state == "title_review":
        if decision not in (None, "selected"):
            return [f"title_packaging_invalid_decision:{decision}"]
    if from_state == "title_review" and to_state == "final_review":
        if decision not in (None, "pass"):
            return [f"title_review_invalid_decision:{decision}"]
    if from_state == "title_review" and to_state == "title_packaging":
        if decision not in (None, "selected"):
            return [f"title_review_invalid_decision:{decision}"]
    return []


def validate_phase_field_boundary(record: object, phase: str) -> list[str]:
    """Reject title-first fields at the phase where they are not allowed."""

    if not isinstance(record, Mapping):
        return ["record_must_be_an_object"]
    if phase == "title":
        errors: list[str] = []
        for path in _walk_keys(record):
            field = path.rsplit(".", 1)[-1]
            if "[" in field:
                field = field.split("[", 1)[0]
            if field == "title_skeleton":
                errors.append(f"forbidden_discovery_field:{field}")
            elif field in _TITLE_LEGACY_FIELDS:
                errors.append(f"forbidden_legacy_title_field:{field}")
        return sorted(set(errors))
    if phase not in {"discovery", "brief", "material", "content", "content_review", "writing"}:
        return []

    errors: list[str] = []
    for path in _walk_keys(record):
        field = path.rsplit(".", 1)[-1]
        if "[" in field:
            field = field.split("[", 1)[0]
        if phase == "discovery" and field == "title_skeleton":
            continue
        prefix = "forbidden_content_field" if field == "title_skeleton" else "forbidden_precontent_field"
        errors.append(f"{prefix}:{field}")
    if phase in {"discovery", "brief", "material", "writing"}:
        for path in _walk_keys_by_fields(record, POSTDRAFT_FIELDS):
            field = path.rsplit(".", 1)[-1]
            errors.append(f"forbidden_precontent_field:{field}")
    return sorted(set(errors))


def _walk_keys_by_fields(
    value: object,
    wanted: frozenset[str],
    prefix: str = "",
) -> list[str]:
    """Find non-empty fields that are valid only after the body is drafted."""

    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str):
                path = f"{prefix}.{key}" if prefix else key
                if key in wanted and _has_nonempty_value(child):
                    found.append(path)
                found.extend(_walk_keys_by_fields(child, wanted, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_walk_keys_by_fields(child, wanted, f"{prefix}[{index}]"))
    return found


__all__ = [
    "ARTICLE_FIRST_CONTRACT_VERSION",
    "ARTICLE_FIRST_STATES",
    "CONTENT_STATES",
    "HARD_INFORMATION_TYPES",
    "POSTDRAFT_FIELDS",
    "TITLE_FIRST_FIELDS",
    "TITLE_PACKAGING_RESULTS",
    "TITLE_PACKAGING_ROUTES",
    "TITLE_STATES",
    "is_article_first_record",
    "title_packaging_route",
    "validate_article_first_transition",
    "validate_phase_field_boundary",
]
