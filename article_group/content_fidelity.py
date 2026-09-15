"""Content-stage fidelity checks for the article-first lane.

This module intentionally knows nothing about headline strength.  It checks
whether a title-free body gives the reader independently supported facts,
scenes, mechanisms, and a usable judgment before any title package exists.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import re
from typing import Any

from .article_first import (
    HARD_INFORMATION_TYPES,
    validate_phase_field_boundary,
)
from .run_contract import is_strict_run_contract, validate_phase_contract_fields, validate_run_contract

CONTENT_FIDELITY_SCHEMA = "article-content-fidelity-v1"
CONTENT_RESULTS = ("pass", "return_article", "return_material")
CONTENT_GAIN_KINDS = HARD_INFORMATION_TYPES | {"judgment"}
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_PARAGRAPH_LOCATOR = re.compile(r"^p([1-9][0-9]*)(?:-s([1-9][0-9]*))?$")
_H2_LOCATOR = re.compile(r"^(?:h2|section):.+$")
_FENCE = re.compile(r"^[ \t]*```")


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalized(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", "", value).strip().lower()


def _string_list(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(_nonblank(item) for item in value)


def _body_paragraphs(body_text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    in_fence = False
    for line in body_text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        stripped = line.strip()
        if _FENCE.match(line):
            if current:
                blocks.append(" ".join(current))
                current = []
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not stripped or stripped.startswith("#"):
            if current:
                blocks.append(" ".join(current))
                current = []
            continue
        current.append(stripped)
    if current:
        blocks.append(" ".join(current))
    return blocks


def _body_has_h1(body_text: str) -> bool:
    """Find real H1 headings while ignoring fenced-code examples."""

    in_fence = False
    for line in body_text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence and re.match(r"^[ \t]{0,3}#[ \t]+\S.*$", line):
            return True
    return False


def _paragraph_root(locator: object) -> str:
    if not _nonblank(locator):
        return ""
    match = _PARAGRAPH_LOCATOR.fullmatch(str(locator).strip())
    return f"p{match.group(1)}" if match else ""


def _locator_exists(locator: object, body_text: str | None) -> bool:
    if not _nonblank(locator):
        return False
    if body_text is None:
        return True
    value = str(locator).strip()
    paragraph_match = _PARAGRAPH_LOCATOR.fullmatch(value)
    if paragraph_match:
        paragraph_number = int(paragraph_match.group(1))
        return paragraph_number <= len(_body_paragraphs(body_text))
    if _H2_LOCATOR.fullmatch(value):
        label = value.split(":", 1)[1].strip().lower()
        headings = [
            line.strip()[3:].strip().lower()
            for line in body_text.splitlines()
            if re.match(r"^[ \t]{0,3}##[ \t]+", line)
        ]
        return any(label in heading or heading in label for heading in headings)
    # A free-text locator is accepted when its locator text is present in the
    # body. This keeps source-style locators useful without pretending that an
    # arbitrary label proves a paragraph exists.
    return value in body_text


def _hash_matches(record: Mapping[str, Any], body_text: str | None, errors: list[str]) -> None:
    digest = record.get("body_sha256")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        errors.append("invalid:body_sha256")
        return
    if body_text is not None and digest.lower() != hashlib.sha256(body_text.encode("utf-8")).hexdigest():
        errors.append("content_body_hash_mismatch")


def content_body_path(record: Mapping[str, Any] | object) -> str:
    if not isinstance(record, Mapping):
        return ""
    value = record.get("body_path") or record.get("body_draft_path")
    return value.strip() if isinstance(value, str) else ""


def _validate_hard_information(
    record: Mapping[str, Any],
    body_text: str | None,
    errors: list[str],
) -> tuple[int, int, bool]:
    items = record.get("hard_information")
    if not isinstance(items, list):
        errors.append("invalid:hard_information")
        return 0, 0, False
    if len(items) < 3:
        errors.append("hard_information_requires_at_least_3")

    ids: set[str] = set()
    independence_keys: list[str] = []
    normalized_texts: list[str] = []
    kinds: set[str] = set()
    valid = True
    for index, item in enumerate(items):
        label = str(item.get("information_id", index)) if isinstance(item, Mapping) else str(index)
        if not isinstance(item, Mapping):
            errors.append(f"invalid:hard_information_item:{index}")
            valid = False
            continue
        information_id = item.get("information_id")
        if not _nonblank(information_id):
            errors.append(f"missing:hard_information_id:{label}")
            valid = False
        else:
            normalized_id = str(information_id).strip()
            if normalized_id in ids:
                errors.append(f"duplicate:hard_information_id:{normalized_id}")
                valid = False
            ids.add(normalized_id)
            label = normalized_id

        if not _nonblank(item.get("text")):
            errors.append(f"missing:hard_information_text:{label}")
            valid = False
        else:
            normalized_texts.append(_normalized(item.get("text")))

        kind = item.get("kind")
        if kind not in HARD_INFORMATION_TYPES:
            errors.append(f"invalid:hard_information_kind:{label}")
            valid = False
        else:
            kinds.add(str(kind))

        body_locator = item.get("body_locator")
        if not _nonblank(body_locator):
            errors.append(f"missing:hard_information_body_locator:{label}")
            valid = False
        elif not _locator_exists(body_locator, body_text):
            errors.append(f"hard_information_body_locator_not_found:{label}")
            valid = False

        source_locators = item.get("source_locators")
        # ``source_refs`` can identify a source record, but it does not prove
        # that the declared fact can be found at a concrete source location.
        # The article-first gate therefore requires the explicit locator list.
        if not _string_list(source_locators):
            errors.append(f"missing:hard_information_source_locator:{label}")
            valid = False

        independence_key = item.get("independence_key")
        if not _nonblank(independence_key):
            errors.append(f"missing:hard_information_independence_key:{label}")
            valid = False
        else:
            independence_keys.append(str(independence_key).strip())

    if len(kinds) < 2:
        errors.append("hard_information_requires_two_types")
    if len(independence_keys) != len(set(independence_keys)) or len(independence_keys) != len(items):
        errors.append("hard_information_not_independent")
        valid = False
    if len(normalized_texts) != len(set(normalized_texts)):
        errors.append("hard_information_not_independent")
        valid = False
    return len(items), len(kinds), valid


def _validate_section_increments(
    record: Mapping[str, Any],
    body_text: str | None,
    errors: list[str],
) -> bool:
    increments = record.get("section_increments")
    if not isinstance(increments, list) or not increments:
        errors.append("missing:section_increments")
        return False
    seen_sections: set[str] = set()
    seen_gains: set[str] = set()
    covered_paragraphs: set[str] = set()
    valid = True
    for index, item in enumerate(increments):
        if not isinstance(item, Mapping):
            errors.append(f"invalid:section_increment:{index}")
            valid = False
            continue
        section_id = item.get("section_id")
        label = str(section_id).strip() if _nonblank(section_id) else str(index)
        if not _nonblank(section_id):
            errors.append(f"missing:section_id:{label}")
            valid = False
        elif label in seen_sections:
            errors.append(f"duplicate:section_id:{label}")
            valid = False
        seen_sections.add(label)

        locator = item.get("body_locator") or item.get("locator")
        if not _nonblank(locator):
            errors.append(f"missing:section_body_locator:{label}")
            valid = False
        elif not _locator_exists(locator, body_text):
            errors.append(f"section_body_locator_not_found:{label}")
            valid = False
        paragraph_root = _paragraph_root(locator)
        if paragraph_root:
            covered_paragraphs.add(paragraph_root)

        gain = item.get("reader_gain")
        if not _nonblank(gain):
            errors.append(f"missing:section_reader_gain:{label}")
            valid = False
        else:
            normalized_gain = _normalized(gain)
            if normalized_gain in seen_gains:
                errors.append("section_increment_restatement")
                valid = False
            seen_gains.add(normalized_gain)

        kind = item.get("gain_kind") or item.get("increment_kind")
        if kind == "restatement":
            errors.append("section_increment_restatement")
            valid = False
        elif kind not in CONTENT_GAIN_KINDS:
            errors.append(f"invalid:section_gain_kind:{label}")
            valid = False

        refs = item.get("material_refs") or item.get("supporting_material_ids")
        if not _string_list(refs):
            errors.append(f"missing:section_material_refs:{label}")
            valid = False
    if body_text is not None:
        major_paragraphs = {
            f"p{index}"
            for index, paragraph in enumerate(_body_paragraphs(body_text), 1)
            if _nonblank(paragraph)
        }
        for paragraph in sorted(major_paragraphs, key=lambda value: int(value[1:])):
            if paragraph not in covered_paragraphs:
                errors.append(f"section_increment_missing_major_paragraph:{paragraph}")
                valid = False
    return valid


def _validate_standalone(
    record: Mapping[str, Any],
    body_text: str | None,
    errors: list[str],
) -> bool:
    check = record.get("standalone_check")
    if not isinstance(check, Mapping):
        errors.append("missing:standalone_check")
        return False
    valid = check.get("status") == "pass"
    if not valid:
        errors.append("standalone_check_not_pass")
    for field in ("object_locator", "problem_locator", "explanation_locator", "judgment_locator"):
        locator = check.get(field)
        if not _nonblank(locator):
            errors.append(f"missing:standalone_{field}")
            valid = False
        elif not _locator_exists(locator, body_text):
            errors.append(f"standalone_locator_not_found:{field}")
            valid = False
    return valid


def _validate_core_judgment(
    record: Mapping[str, Any],
    body_text: str | None,
    errors: list[str],
    *,
    strict: bool,
) -> dict[str, Any]:
    """Validate the judgment a reader should be able to repeat.

    The fields are mandatory only for an explicitly strict run.  If a legacy
    record contains any of them, validating the supplied subset still catches
    malformed data without making historical records impossible to read.
    """

    fields_present = any(
        field in record
        for field in (
            "core_judgment",
            "judgment_basis",
            "judgment_strength",
            "reader_can_repeat",
            "unsupported_scenario_boundary",
        )
    )
    if not strict and not fields_present:
        return {"status": "not_applicable", "basis_count": 0}

    core_valid = _nonblank(record.get("core_judgment"))
    if not core_valid:
        errors.append("missing:core_judgment")
    basis = record.get("judgment_basis")
    if not isinstance(basis, list):
        errors.append("missing:judgment_basis" if basis is None else "invalid:judgment_basis")
        basis = []
    if len(basis) < 2:
        errors.append("core_judgment_requires_two_bases")
    seen_locators: set[str] = set()
    seen_facts: set[str] = set()
    basis_valid = len(basis) >= 2
    for index, item in enumerate(basis):
        if not isinstance(item, Mapping):
            errors.append(f"invalid:judgment_basis_item:{index}")
            basis_valid = False
            continue
        locator = item.get("locator")
        fact = item.get("fact_or_scene")
        explanation = item.get("explanation")
        if not _nonblank(locator):
            errors.append(f"missing:judgment_basis_locator:{index}")
            basis_valid = False
        elif not _locator_exists(locator, body_text):
            errors.append(f"judgment_basis_locator_not_found:{index}")
            basis_valid = False
        if not _nonblank(fact):
            errors.append(f"missing:judgment_basis_fact_or_scene:{index}")
            basis_valid = False
        if not _nonblank(explanation):
            errors.append(f"missing:judgment_basis_explanation:{index}")
            basis_valid = False
        locator_key = _normalized(locator)
        fact_key = _normalized(fact)
        if locator_key and locator_key in seen_locators:
            errors.append("judgment_basis_not_independent")
            basis_valid = False
        if fact_key and fact_key in seen_facts:
            errors.append("judgment_basis_not_independent")
            basis_valid = False
        if locator_key:
            seen_locators.add(locator_key)
        if fact_key:
            seen_facts.add(fact_key)

    strength = record.get("judgment_strength")
    if strength not in {"supported", "too_strong", "too_weak"}:
        errors.append("missing:judgment_strength" if strength is None else "invalid:judgment_strength")
        strength_valid = False
    else:
        strength_valid = True
    if type(record.get("reader_can_repeat")) is not bool:
        errors.append("missing:reader_can_repeat")
        reader_repeatable = False
    else:
        reader_repeatable = record.get("reader_can_repeat") is True
    if not _nonblank(record.get("unsupported_scenario_boundary")):
        errors.append("missing:unsupported_scenario_boundary")
        boundary_valid = False
    else:
        boundary_valid = True

    if strength != "supported":
        errors.append("judgment_not_supported")
    if record.get("reader_can_repeat") is not True:
        errors.append("reader_judgment_not_repeatable")
    return {
        "status": "pass"
        if core_valid
        and basis_valid
        and strength_valid
        and strength == "supported"
        and reader_repeatable
        and boundary_valid
        else "fail",
        "basis_count": len(basis),
    }


def validate_content_fidelity(
    record: Mapping[str, Any] | object,
    *,
    body_text: str | None = None,
    strict: bool | None = None,
) -> list[str]:
    """Return deterministic content-stage errors; no title is required."""

    if not isinstance(record, Mapping):
        return ["record_must_be_an_object"]
    declared_strict = is_strict_run_contract(record)
    strict = declared_strict if strict is None else bool(strict or declared_strict)
    errors: list[str] = []
    if is_strict_run_contract(record):
        errors.extend(validate_run_contract(record))
    for field in (
        "schema_version",
        "article_id",
        "core_object",
        "reader_question",
        "explanation_mechanism",
        "mechanism_locator",
        "reader_takeaway",
        "reader_takeaway_locator",
    ):
        if not _nonblank(record.get(field)):
            errors.append(f"missing:{field}")
    if not content_body_path(record):
        errors.append("missing:body_path")
    if record.get("schema_version") != CONTENT_FIDELITY_SCHEMA:
        errors.append("schema_version")
    if not _SHA256.fullmatch(str(record.get("body_sha256", ""))):
        errors.append("invalid:body_sha256")
    else:
        _hash_matches(record, body_text, errors)

    errors.extend(
        validate_phase_contract_fields(record, "content_review")
        if strict
        else validate_phase_field_boundary(record, "content_review")
    )
    if body_text is not None:
        if _body_has_h1(body_text):
            errors.append("content_body_must_not_have_h1")
        if not _locator_exists(record.get("mechanism_locator"), body_text):
            errors.append("mechanism_locator_not_found")
        if not _locator_exists(record.get("reader_takeaway_locator"), body_text):
            errors.append("reader_takeaway_locator_not_found")

    _validate_hard_information(record, body_text, errors)
    _validate_section_increments(record, body_text, errors)
    _validate_standalone(record, body_text, errors)
    _validate_core_judgment(record, body_text, errors, strict=strict)

    result = record.get("result", record.get("content_result"))
    if result not in CONTENT_RESULTS:
        errors.append("invalid:result")
    elif result in {"return_article", "return_material"} and not _nonblank(record.get("return_reason")):
        errors.append("return_result_requires_reason")
    return sorted(set(errors))


def evaluate_content_fidelity(
    record: Mapping[str, Any] | object,
    *,
    body_text: str | None = None,
    strict: bool | None = None,
) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        return {
            "schema_version": CONTENT_FIDELITY_SCHEMA,
            "status": "invalid",
            "errors": ["record_must_be_an_object"],
            "content_checks": {},
        }
    declared_strict = is_strict_run_contract(record)
    strict = declared_strict if strict is None else bool(strict or declared_strict)
    errors = validate_content_fidelity(record, body_text=body_text, strict=strict)
    items = record.get("hard_information")
    count = len(items) if isinstance(items, list) else 0
    kinds = {
        item.get("kind")
        for item in items
        if isinstance(item, Mapping) and item.get("kind") in HARD_INFORMATION_TYPES
    } if isinstance(items, list) else set()
    increments = record.get("section_increments")
    standalone = record.get("standalone_check")
    checks = {
        "hard_information_count": {
            "status": "pass" if count >= 3 else "fail",
            "count": count,
            "minimum": 3,
        },
        "hard_information_independence": {
            "status": "pass" if "hard_information_not_independent" not in errors and len(kinds) >= 2 else "fail",
            "types": sorted(str(kind) for kind in kinds),
        },
        "section_progression": {
            "status": "pass" if isinstance(increments, list) and increments and not any(error.startswith(("missing:section", "invalid:section", "section_", "duplicate:section")) for error in errors) else "fail",
            "section_count": len(increments) if isinstance(increments, list) else 0,
        },
        "title_free_standalone": {
            "status": "pass" if "content_body_must_not_have_h1" not in errors and isinstance(standalone, Mapping) and standalone.get("status") == "pass" and not any(error.startswith("standalone_") or error.startswith("missing:standalone") for error in errors) else "fail",
        },
    }
    judgment = record.get("judgment_basis")
    judgment_errors = {
        error
        for error in errors
        if error.startswith(
            (
                "core_judgment",
                "judgment_",
                "missing:core_judgment",
                "missing:judgment_",
                "missing:reader_can_repeat",
                "missing:unsupported_scenario_boundary",
                "reader_judgment",
                "invalid:judgment_",
            )
        )
    }
    judgment_applicable = strict or isinstance(judgment, list) or any(
        field in record
        for field in (
            "core_judgment",
            "judgment_basis",
            "judgment_strength",
            "reader_can_repeat",
            "unsupported_scenario_boundary",
        )
    )
    checks["core_judgment"] = {
        "status": (
            "pass"
            if judgment_applicable and not judgment_errors
            else "not_applicable"
            if not judgment_applicable
            else "fail"
        ),
        "basis_count": len(judgment) if isinstance(judgment, list) else 0,
        "minimum": 2,
    }
    result = record.get("result", record.get("content_result"))
    if errors:
        status = "invalid"
    elif result in CONTENT_RESULTS:
        status = result
    else:
        status = "invalid"
    return {
        "schema_version": CONTENT_FIDELITY_SCHEMA,
        "article_id": record.get("article_id"),
        "status": status,
        "errors": errors,
        "content_checks": checks,
    }


__all__ = [
    "CONTENT_FIDELITY_SCHEMA",
    "CONTENT_GAIN_KINDS",
    "CONTENT_RESULTS",
    "content_body_path",
    "evaluate_content_fidelity",
    "validate_content_fidelity",
]
