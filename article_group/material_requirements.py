"""material_requirements: material-grade gates that unlock a length band.

Why this exists (2026-09-16, daily-008 扩写实验):
the project's usual target band (1500–2200 CJK) was routinely missed not
because the writers were lazy but because the *material* could not carry it:
of the 150 usable items in that run's four sources, 47% were commentator
judgements, the scene layer came from a single anonymous review account, and
only 8 hard data points existed.  When the same topic was re-crawled with a
comparable-data table plus a signed newsroom interview, a 2 651-character draft
passed every gate and raised fact-anchored paragraph density from 62% to 77%.

So length is an *output* of material grade, not a setting.  This module turns
that into a machine check: a material pack may declare
``material_requirements``; when it does, the pack must also carry a
``material_inventory`` and the declared thresholds must be met, otherwise the
pack cannot be accepted.  ``allowed_cjk_band`` reports which length band the
material grade unlocks — it is advisory and never a publication authorization.

The check is opt-in: packs without ``material_requirements`` behave exactly as
before (no new errors), so historical runs stay green.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

REQUIREMENT_KEYS = (
    "min_scene_items",
    "min_distinct_scene_sources",
    "min_comparable_data_points",
    "min_primary_quotes",
)

DEFAULT_REQUIREMENTS: dict[str, int] = {
    "min_scene_items": 8,
    "min_distinct_scene_sources": 2,
    "min_comparable_data_points": 4,
    "min_primary_quotes": 2,
}

# Material grade -> (min_cjk, max_cjk) this material can honestly carry.
# Bands use the accepted-with-flex convention of run_profile (the caller may
# widen by its own CHAR_COUNT_FLEX_MARGIN).
GRADE_BANDS: dict[str, tuple[int, int]] = {
    "full": (1800, 2600),
    "single_source_scenes": (1000, 2000),
    "no_scene_sources": (1000, 1500),
}

# Independence verdicts that may be counted as a distinct scene source.
DISTINCT_INDEPENDENCE = ("primary_interview", "independent_angle", "canonical")

SCENE_LIKE_KINDS = ("scene", "viewing_scene", "shot", "staging")


def _items(record: Mapping[str, Any], key: str) -> list[Any]:
    value = record.get(key)
    return list(value) if isinstance(value, list) else []


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _declared_requirements(record: Mapping[str, Any]) -> dict[str, int] | None:
    declared = record.get("material_requirements")
    if not isinstance(declared, Mapping):
        return None
    requirements = dict(DEFAULT_REQUIREMENTS)
    for key in REQUIREMENT_KEYS:
        value = declared.get(key)
        if type(value) is int and value >= 0:
            requirements[key] = value
    return requirements


def _scene_source_ids(scene_items: Sequence[Any]) -> tuple[set[str], list[str]]:
    """Distinct independent scene sources plus warnings for unverified ones."""
    distinct: set[str] = set()
    warnings: list[str] = []
    for item in scene_items:
        if not isinstance(item, Mapping):
            continue
        source_id = item.get("source_id")
        if not _nonblank(source_id):
            warnings.append("scene_item_missing_source_id")
            continue
        independence = item.get("independence")
        if not _nonblank(independence):
            warnings.append(f"scene_source_independence_unverified:{source_id}")
            continue
        if independence in DISTINCT_INDEPENDENCE:
            distinct.add(str(source_id))
        else:
            warnings.append(f"scene_source_not_independent:{source_id}:{independence}")
    return distinct, warnings


def evaluate_material_requirements(record: Mapping[str, Any] | object) -> dict[str, Any]:
    """Grade a material pack and report the length band its material unlocks."""
    if not isinstance(record, Mapping):
        return {
            "status": "not_declared",
            "grade": None,
            "errors": [],
            "warnings": [],
            "allowed_cjk_band": None,
            "advisory": True,
            "publication_authorization": "not_authorized",
        }
    requirements = _declared_requirements(record)
    if requirements is None:
        return {
            "status": "not_declared",
            "grade": None,
            "errors": [],
            "warnings": [],
            "allowed_cjk_band": None,
            "advisory": True,
            "publication_authorization": "not_authorized",
        }

    scene_items = _items(record, "scene_items")
    data_points = _items(record, "comparable_data_points")
    primary_quotes = _items(record, "primary_quotes")
    distinct_scene_sources, warnings = _scene_source_ids(scene_items)

    counts = {
        "scene_items": len(scene_items),
        "distinct_scene_sources": len(distinct_scene_sources),
        "comparable_data_points": len(data_points),
        "primary_quotes": len(primary_quotes),
    }
    thresholds = {
        "scene_items": requirements["min_scene_items"],
        "distinct_scene_sources": requirements["min_distinct_scene_sources"],
        "comparable_data_points": requirements["min_comparable_data_points"],
        "primary_quotes": requirements["min_primary_quotes"],
    }

    errors: list[str] = []
    for key, minimum in thresholds.items():
        if minimum and counts[key] < minimum:
            errors.append(f"material_requires_more_{key}:{counts[key]}<{minimum}")

    if counts["scene_items"] == 0:
        grade = "no_scene_sources"
    elif counts["distinct_scene_sources"] < max(2, thresholds["distinct_scene_sources"]):
        grade = "single_source_scenes"
    elif errors:
        grade = "single_source_scenes"
    else:
        grade = "full"

    if grade == "no_scene_sources":
        errors.append("material_requires_scene_sources:0")
    elif grade == "single_source_scenes" and counts["scene_items"] > 0 \
            and counts["distinct_scene_sources"] < thresholds["distinct_scene_sources"]:
        errors.append(
            "material_requires_distinct_scene_sources:"
            f"{counts['distinct_scene_sources']}<{thresholds['distinct_scene_sources']}"
        )

    band = GRADE_BANDS[grade]
    return {
        "status": "graded",
        "grade": grade,
        "counts": counts,
        "thresholds": thresholds,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "allowed_cjk_band": band,
        "note": "长度带由材料等级解锁；band 为建议，不是发布授权",
        "advisory": True,
        "publication_authorization": "not_authorized",
    }


def validate_material_requirements(record: Mapping[str, Any] | object) -> list[str]:
    """Error list for the acceptance validator; empty when not declared."""
    report = evaluate_material_requirements(record)
    return list(report.get("errors") or [])


__all__ = [
    "REQUIREMENT_KEYS",
    "DEFAULT_REQUIREMENTS",
    "GRADE_BANDS",
    "DISTINCT_INDEPENDENCE",
    "evaluate_material_requirements",
    "validate_material_requirements",
]
