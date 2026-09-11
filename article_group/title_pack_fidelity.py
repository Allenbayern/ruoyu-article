"""Post-content title packaging contract.

The title pack is created only after a body has passed content review.  It
contains references to existing body/material evidence, but it never edits or
extends that body.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import re
from typing import Any

from .article_first import TITLE_PACKAGING_RESULTS
from .content_fidelity import _locator_exists

TITLE_PACK_SCHEMA = "article-title-pack-v1"
TITLE_REVIEW_SCHEMA = "article-title-review-v1"
TITLE_REVIEW_RESULTS = ("pass", "return_article", "return_material")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_TITLE_FORBIDDEN_WRITE_KEYS = {
    "title_promise",
    "title_skeleton",
    "body_additions",
    "new_body_facts",
    "additional_body_facts",
    "new_body_content",
    "content_additions",
    "append_body",
    "body_revision",
    "body_revision_required",
    "body_changes",
    "rewrite_body",
    "supplement_body",
}


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(_nonblank(item) for item in value)


def _normalized(value: object) -> str:
    return re.sub(r"\s+", "", value).strip().lower() if isinstance(value, str) else ""


def _walk_forbidden_keys(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str) and key in _TITLE_FORBIDDEN_WRITE_KEYS:
                found.append(key)
            found.extend(_walk_forbidden_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_forbidden_keys(child))
    return found


def title_pack_result(record: Mapping[str, Any] | object) -> str | None:
    if not isinstance(record, Mapping):
        return None
    result = record.get("result", record.get("title_pack_result"))
    return result if result in TITLE_PACKAGING_RESULTS else None


def _validate_ref(value: object, field: str, errors: list[str]) -> None:
    if not isinstance(value, Mapping) or not _nonblank(value.get("path")):
        errors.append(f"invalid:{field}")
        return
    if not _SHA256.fullmatch(str(value.get("sha256", ""))):
        errors.append(f"invalid:{field}_sha256")


def validate_title_pack(
    record: Mapping[str, Any] | object,
    *,
    body_text: str | None = None,
) -> list[str]:
    """Return title-stage errors without changing the body or adding facts."""

    if not isinstance(record, Mapping):
        return ["record_must_be_an_object"]
    errors: list[str] = []
    for field in (
        "schema_version",
        "article_id",
        "body_path",
        "body_sha256",
        "content_fidelity_ref",
        "created_after_content_pass",
        "result",
    ):
        if field not in record or record.get(field) in (None, "", []):
            errors.append(f"missing:{field}")
    if record.get("schema_version") != TITLE_PACK_SCHEMA:
        errors.append("schema_version")
    if not _nonblank(record.get("article_id")):
        errors.append("missing:article_id")
    digest = record.get("body_sha256")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        errors.append("invalid:body_sha256")
    elif body_text is not None and digest.lower() != hashlib.sha256(body_text.encode("utf-8")).hexdigest():
        errors.append("title_pack_stale_body")
    if record.get("created_after_content_pass") is not True:
        errors.append("content_pass_required_before_title_packaging")
    _validate_ref(record.get("content_fidelity_ref"), "content_fidelity_ref", errors)

    for key in _walk_forbidden_keys(record):
        errors.append(f"forbidden_title_pack_field:{key}")

    result = record.get("result", record.get("title_pack_result"))
    if result not in TITLE_PACKAGING_RESULTS:
        errors.append("invalid:result")
    directions = record.get("directions")
    if "directions" not in record:
        errors.append("missing:directions")
        directions = []
    elif not isinstance(directions, list):
        errors.append("invalid:directions")
        directions = []
    if len(directions) > 3:
        errors.append("title_directions_exceed_three")

    ids: set[str] = set()
    titles: set[str] = set()
    angles: set[str] = set()
    selected_ids: list[str] = []
    for index, item in enumerate(directions):
        label = str(index)
        if not isinstance(item, Mapping):
            errors.append(f"invalid:title_direction:{index}")
            continue
        title_id = item.get("title_id")
        if not _nonblank(title_id):
            errors.append(f"missing:title_direction_title_id:{index}")
        else:
            label = str(title_id).strip()
            if label in ids:
                errors.append(f"duplicate:title_direction_id:{label}")
            ids.add(label)
        title = item.get("title")
        if not _nonblank(title):
            errors.append(f"missing:title_direction_title:{label}")
        else:
            normalized_title = _normalized(title)
            if normalized_title in titles:
                errors.append("title_directions_not_distinct")
            titles.add(normalized_title)
            title_length = len(re.findall(r"[\u4e00-\u9fff]", str(title)))
            if title_length > 30:
                errors.append(f"title_too_long:{label}")
        angle = item.get("distinct_angle")
        if not _nonblank(angle):
            errors.append(f"missing:title_direction_distinct_angle:{label}")
        else:
            normalized_angle = _normalized(angle)
            if normalized_angle in angles:
                errors.append("title_directions_not_distinct")
            angles.add(normalized_angle)

        body_locators = item.get("body_locators")
        if not _string_list(body_locators):
            errors.append("title_core_fact_missing_body_support")
        elif body_text is not None:
            for locator in body_locators:
                if not _locator_exists(locator, body_text):
                    errors.append(f"title_core_fact_body_locator_not_found:{label}")
        source_locators = item.get("source_locators")
        if not _string_list(source_locators):
            errors.append("title_core_fact_missing_source_support")
        if item.get("selected") is True:
            selected_ids.append(label)

    selected_title_id = record.get("selected_title_id")
    if result == "selected":
        if not directions:
            errors.append("selected_title_requires_direction")
        if len(selected_ids) != 1:
            errors.append("selected_title_requires_exactly_one_direction")
        if not _nonblank(selected_title_id):
            errors.append("selected_title_id_required")
        elif selected_title_id not in selected_ids:
            errors.append("selected_title_id_mismatch")
    elif result in {"return_article", "return_material"}:
        if not _nonblank(record.get("return_reason")):
            errors.append("return_result_requires_reason")
        if selected_ids:
            errors.append("return_result_cannot_select_title")

    return sorted(set(errors))


def evaluate_title_pack(
    record: Mapping[str, Any] | object,
    *,
    body_text: str | None = None,
) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        return {"schema_version": TITLE_PACK_SCHEMA, "status": "invalid", "errors": ["record_must_be_an_object"]}
    errors = validate_title_pack(record, body_text=body_text)
    result = title_pack_result(record)
    status = "invalid" if errors else result or "invalid"
    return {
        "schema_version": TITLE_PACK_SCHEMA,
        "article_id": record.get("article_id"),
        "status": status,
        "result": result,
        "errors": errors,
        "selected_title_id": record.get("selected_title_id"),
    }


def validate_title_review(
    record: Mapping[str, Any] | object,
    *,
    title_pack: Mapping[str, Any] | None = None,
) -> list[str]:
    """Validate the separate title-review handoff after packaging."""

    if not isinstance(record, Mapping):
        return ["record_must_be_an_object"]
    errors: list[str] = []
    for field in (
        "schema_version",
        "article_id",
        "title_pack_ref",
        "created_after_title_packaging",
        "result",
    ):
        if field not in record or record.get(field) in (None, "", []):
            errors.append(f"missing:{field}")
    if record.get("schema_version") != TITLE_REVIEW_SCHEMA:
        errors.append("schema_version")
    if not _nonblank(record.get("article_id")):
        errors.append("missing:article_id")
    _validate_ref(record.get("title_pack_ref"), "title_pack_ref", errors)
    if record.get("created_after_title_packaging") is not True:
        errors.append("title_packaging_required_before_title_review")
    result = record.get("result")
    if result not in TITLE_REVIEW_RESULTS:
        errors.append("invalid:result")
    if result == "pass":
        if not _nonblank(record.get("selected_title_id")):
            errors.append("selected_title_id_required")
        if isinstance(title_pack, Mapping):
            if title_pack.get("result") != "selected":
                errors.append("title_pack_selected_required")
            elif record.get("selected_title_id") != title_pack.get("selected_title_id"):
                errors.append("title_review_selected_title_mismatch")
    elif result in {"return_article", "return_material"} and not _nonblank(record.get("return_reason")):
        errors.append("return_result_requires_reason")
    return sorted(set(errors))


def evaluate_title_review(
    record: Mapping[str, Any] | object,
    *,
    title_pack: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        return {
            "schema_version": TITLE_REVIEW_SCHEMA,
            "status": "invalid",
            "errors": ["record_must_be_an_object"],
        }
    errors = validate_title_review(record, title_pack=title_pack)
    result = record.get("result")
    return {
        "schema_version": TITLE_REVIEW_SCHEMA,
        "article_id": record.get("article_id"),
        "status": "invalid" if errors else result,
        "result": result if result in TITLE_REVIEW_RESULTS else None,
        "selected_title_id": record.get("selected_title_id"),
        "errors": errors,
    }


__all__ = [
    "TITLE_PACK_SCHEMA",
    "TITLE_REVIEW_RESULTS",
    "TITLE_REVIEW_SCHEMA",
    "evaluate_title_pack",
    "evaluate_title_review",
    "title_pack_result",
    "validate_title_review",
    "validate_title_pack",
]
