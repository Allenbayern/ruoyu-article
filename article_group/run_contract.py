"""Run-level contract and phase-boundary validation for article-first runs.

New article-first runs must declare the complete run contract.  Historical
compatibility is an explicit opt-out (``legacy_compatibility: true``); an
unmarked record is not allowed to masquerade as either lane at a production
boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
import re
from typing import Any

from .article_first import TITLE_FIRST_FIELDS


PRODUCTION_CONTRACT = "article-first-v1"
BRIEF_CONTRACT = "writing-brief-v2"
TITLE_CONTRACT = "title-pack-v1"
REQUIRED_RUN_CONTRACT = {
    "production_contract": PRODUCTION_CONTRACT,
    "brief_contract": BRIEF_CONTRACT,
    "title_contract": TITLE_CONTRACT,
    "legacy_compatibility": False,
}
CONTRACT_MARKERS = frozenset(
    {"production_contract", "brief_contract", "title_contract", "legacy_compatibility", "run_contract_required"}
)
_STRICT_CONTRACT_MARKERS = frozenset(
    {"production_contract", "brief_contract", "title_contract", "run_contract_required"}
)
_TITLE_FIELDS_LOWER = frozenset(field.lower() for field in TITLE_FIRST_FIELDS)
_LEGACY_RUN_FIELDS = frozenset(
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


def _has_nonempty_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return any(_has_nonempty_value(child) for child in value.values())
    if isinstance(value, list):
        return any(_has_nonempty_value(child) for child in value)
    return bool(value)


def _walk_keys(value: object, prefix: str = "") -> list[tuple[str, str, object]]:
    found: list[tuple[str, str, object]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                continue
            path = f"{prefix}.{key}" if prefix else key
            found.append((path, key, child))
            found.extend(_walk_keys(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_walk_keys(child, f"{prefix}[{index}]"))
    return found


def _safe_relative_path(root: Path, raw: object) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts or "\x00" in raw:
        return None
    try:
        resolved_root = root.resolve()
        resolved = (root / candidate).resolve()
        resolved.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved


def is_strict_run_contract(record: object) -> bool:
    """Return whether a record explicitly opts into the new run contract."""

    if not isinstance(record, Mapping):
        return False
    return bool(
        record.get("legacy_compatibility") is False
        or any(marker in record for marker in _STRICT_CONTRACT_MARKERS)
    )


def is_explicit_legacy_compatibility(record: object) -> bool:
    """Return whether a record explicitly opts into historical compatibility.

    A compatibility marker combined with any new-contract marker is a mixed
    lane and therefore remains strict so ``validate_run_contract`` can reject
    it rather than silently selecting one interpretation.
    """

    if not isinstance(record, Mapping) or record.get("legacy_compatibility") is not True:
        return False
    return not any(marker in record for marker in _STRICT_CONTRACT_MARKERS)


def _validate_root_title_fields(record: Mapping[str, Any]) -> list[str]:
    """Reject title-first inputs placed on the run manifest itself.

    Child article artifacts are validated by their own phase.  Keeping this
    check at the root avoids rejecting a legitimate downstream title pack
    merely because the batch manifest references it.
    """

    errors: list[str] = []
    for key, value in record.items():
        if not isinstance(key, str):
            continue
        normalized = key.lower()
        # An independent-review record legitimately contains
        # title_pack_path/title_pack_sha256, but a run manifest itself has no
        # title field.  A selected title belongs under its article record, so
        # reject both ``title`` and the legacy capitalized ``Title`` here.
        if normalized in _LEGACY_RUN_FIELDS or normalized == "title":
            if _has_nonempty_value(value):
                errors.append(f"forbidden_run_field:{normalized}")
    return errors


def _validate_nested_legacy_fields(record: Mapping[str, Any]) -> list[str]:
    """Reject legacy title inputs hidden inside a strict run manifest."""

    errors: list[str] = []
    for path, key, value in _walk_keys(record):
        if not _has_nonempty_value(value):
            continue
        normalized = key.lower()
        if normalized in _LEGACY_RUN_FIELDS or (normalized == "title" and key != "title"):
            errors.append(f"forbidden_run_field:{path}")
    return errors


_BRIEF_FIELD_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(Title|title_promise|title_skeleton|title_directions|"
    r"title_core_fact|title_candidates|title_candidate_matrix|title_evidence_ref|"
    r"title_qc_ref|title_qc_draft_path|title_qc_draft_sha256|title_review_target|"
    r"opening_fulfillment_plan|opening_fulfillment_locator)\s*:",
    re.IGNORECASE | re.MULTILINE,
)
_BRIEF_PATH_KEYS = frozenset(
    {
        "brief_path",
        "writing_brief_path",
        "task_card_path",
        "article_task_card_path",
        "crawl_task_path",
    }
)


def _referenced_brief_paths(record: Mapping[str, Any]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []

    def walk(value: object, prefix: str = "") -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if not isinstance(key, str):
                    continue
                path = f"{prefix}.{key}" if prefix else key
                normalized = key.lower()
                if (
                    normalized in _BRIEF_PATH_KEYS
                    or ("brief" in normalized and normalized.endswith("path"))
                    or ("task_card" in normalized and normalized.endswith("path"))
                ) and isinstance(child, str):
                    found.append((path, child))
                elif normalized in {"brief", "writing_brief", "task_card"} and isinstance(child, str):
                    found.append((path, child))
                walk(child, path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{prefix}[{index}]")

    walk(record)
    return found


def validate_referenced_contract_artifacts(
    run_root: str | Path,
    record: Mapping[str, Any] | object,
) -> list[str]:
    """Scan referenced brief/task-card artifacts for legacy title inputs."""

    if not isinstance(record, Mapping):
        return ["record_must_be_an_object"]
    if not is_strict_run_contract(record):
        return []
    root = Path(run_root)
    errors: list[str] = []
    for field_path, raw_path in _referenced_brief_paths(record):
        target = _safe_relative_path(root, raw_path)
        if target is None or not target.is_file():
            errors.extend(("contract_mismatch", f"contract_artifact_missing:{field_path}"))
            continue
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            errors.extend(("contract_mismatch", f"contract_artifact_unreadable:{field_path}"))
            continue
        payload: object = None
        if target.suffix.lower() == ".json":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = None
        if isinstance(payload, Mapping):
            errors.extend(validate_phase_contract_fields(payload, "brief"))
            continue
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, Mapping):
                    errors.extend(validate_phase_contract_fields(item, "brief"))
            continue
        for match in _BRIEF_FIELD_RE.finditer(text):
            field = match.group(1).lower()
            prefix = "forbidden_content_field" if field == "title_skeleton" else "forbidden_precontent_field"
            errors.append(f"{prefix}:{field}")
    if errors:
        errors.append("contract_mismatch")
    return sorted(set(errors))


def validate_run_contract(
    record: Mapping[str, Any] | object,
    *,
    require_explicit: bool = True,
) -> list[str]:
    """Return deterministic errors for a run-level article-first contract.

    ``require_explicit=False`` is the read-compatibility mode for historical
    manifests.  It does not upgrade the record into strict mode.
    """

    if not isinstance(record, Mapping):
        return ["record_must_be_an_object"]
    strict = is_strict_run_contract(record)
    if not strict:
        if is_explicit_legacy_compatibility(record):
            return []
        return ["contract_mismatch", "run_contract_required"] if require_explicit else []

    errors: list[str] = []
    for field, expected in REQUIRED_RUN_CONTRACT.items():
        if field not in record:
            errors.append(f"missing:{field}")
            continue
        if record.get(field) != expected:
            errors.append(f"mismatch:{field}")
            if field == "legacy_compatibility":
                errors.append("legacy_compatibility_must_be_false")
    if "run_contract_required" in record and record.get("run_contract_required") is not True:
        errors.append("mismatch:run_contract_required")
    errors.extend(_validate_root_title_fields(record))
    errors.extend(_validate_nested_legacy_fields(record))
    if errors:
        errors.insert(0, "contract_mismatch")
    return sorted(set(errors))


def validate_phase_contract_fields(record: Mapping[str, Any] | object, phase: str) -> list[str]:
    """Apply the phase boundary with case-insensitive legacy-field detection."""

    if not isinstance(record, Mapping):
        return ["record_must_be_an_object"]
    errors: list[str] = []
    for path, key, value in _walk_keys(record):
        normalized = key.lower()
        if normalized not in _TITLE_FIELDS_LOWER or not _has_nonempty_value(value):
            continue
        path_parts = re.sub(r"\[[^\]]+\]", "", path.lower()).split(".")
        source_metadata_title = normalized == "title" and key == "title" and any(
            part in {"sources", "materials"} for part in path_parts
        )
        if phase == "title":
            if normalized == "title" and key != "title":
                errors.append("forbidden_legacy_title_field:title")
            elif normalized == "title_skeleton":
                errors.append("forbidden_discovery_field:title_skeleton")
            elif normalized in {field.lower() for field in TITLE_FIRST_FIELDS} and normalized != "title":
                # The title phase accepts the actual title and modern title
                # pack fields, but not the old title-first inputs.
                legacy = normalized in {
                    "title_promise",
                    "title_candidates",
                    "title_candidate_matrix",
                    "title_evidence_ref",
                    "title_qc_ref",
                    "title_qc_draft_path",
                    "title_qc_draft_sha256",
                    "title_review_target",
                    "title_directions",
                    "opening_fulfillment_plan",
                    "opening_fulfillment_locator",
                }
                if legacy:
                    errors.append(f"forbidden_legacy_title_field:{normalized}")
        elif phase in {"discovery", "brief", "material", "content", "content_review", "writing"}:
            if phase == "discovery" and normalized == "title_skeleton":
                continue
            if source_metadata_title:
                continue
            prefix = "forbidden_content_field" if normalized == "title_skeleton" else "forbidden_precontent_field"
            errors.append(f"{prefix}:{normalized}")
    if phase in {"discovery", "brief", "material", "writing"}:
        for path, key, value in _walk_keys(record):
            if key.lower() in {"reader_takeaway", "reader_takeaway_locator"} and _has_nonempty_value(value):
                errors.append(f"forbidden_precontent_field:{key.lower()}")
    if errors:
        errors.append("contract_mismatch")
    return sorted(set(errors))


def validate_run_root_contract(
    run_root: str | Path,
    *,
    manifest_name: str = "batch.json",
    require_explicit: bool = True,
) -> list[str]:
    """Load one run manifest and validate its root contract without mutation."""

    root = Path(run_root)
    manifest = root / manifest_name
    try:
        record = json.loads(manifest.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [f"missing:run_manifest:{manifest_name}"]
    except (OSError, json.JSONDecodeError):
        return [f"invalid:run_manifest:{manifest_name}"]
    return validate_run_contract(record, require_explicit=require_explicit)


def validate_article_first_run_lane(
    record: Mapping[str, Any] | object,
    *,
    detected: bool,
) -> list[str]:
    """Require a declared lane whenever article-first artifacts are present.

    ``detected`` is supplied by the caller because artifact detection differs
    between the batch and single-article boundaries.  The explicit historical
    marker is the only compatibility escape hatch.
    """

    if not detected:
        return []
    if is_explicit_legacy_compatibility(record):
        return []
    if not is_strict_run_contract(record):
        return [
            "contract_mismatch",
            "run_contract_required",
            "article_first_lane_unmarked",
        ]
    return []


__all__ = [
    "BRIEF_CONTRACT",
    "CONTRACT_MARKERS",
    "PRODUCTION_CONTRACT",
    "REQUIRED_RUN_CONTRACT",
    "TITLE_CONTRACT",
    "is_explicit_legacy_compatibility",
    "is_strict_run_contract",
    "validate_article_first_run_lane",
    "validate_phase_contract_fields",
    "validate_referenced_contract_artifacts",
    "validate_run_contract",
    "validate_run_root_contract",
]
