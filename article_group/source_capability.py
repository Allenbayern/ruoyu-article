"""Narrative capability ceilings for material sources and claims."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


CAPABILITY_LEVELS = (
    "event_exists",
    "character_setup",
    "scene_action",
    "dialogue",
    "audience_reaction",
    "mechanism",
    "outcome",
)
_RANK = {level: index for index, level in enumerate(CAPABILITY_LEVELS)}

# These are conservative ceilings.  An explicit source_capability may lower
# or raise the ceiling only when the source record actually documents that
# stronger capture.
DEFAULT_SOURCE_CAPABILITIES = {
    "page_metadata": "character_setup",
    "platform_synopsis": "character_setup",
    "official_synopsis": "character_setup",
    "page_fulltext": "character_setup",
    "media_report": "character_setup",
    "interview": "dialogue",
    "video_watched": "scene_action",
    "scene_verified": "scene_action",
    "dialogue_transcript": "dialogue",
    "audience_sample": "audience_reaction",
    "secondary_discussion": "event_exists",
    "industry_context": "mechanism",
    "outcome_report": "outcome",
}
_SOURCE_CAPABILITY_KEYS = (
    "source_capability",
    "capability_level",
    "max_claim_level",
    "narrative_capability",
)
_SOURCE_TYPE_KEYS = ("capture_type", "source_type", "source_kind", "source_role")
_SOURCE_REF_KEYS = ("source_ids", "source_refs", "material_ids", "material_refs", "source_id")


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _source_id(source: Mapping[str, Any]) -> str:
    value = source.get("source_id") or source.get("material_id") or source.get("id")
    return str(value).strip() if _nonblank(value) else ""


def _source_type(source: Mapping[str, Any]) -> str:
    for key in _SOURCE_TYPE_KEYS:
        value = source.get(key)
        if _nonblank(value):
            return str(value).strip()
    return ""


def _explicit_capability(source: Mapping[str, Any]) -> object:
    for key in _SOURCE_CAPABILITY_KEYS:
        if key in source:
            return source.get(key)
    return None


def _capability_rank(value: object) -> int | None:
    if isinstance(value, str):
        return _RANK.get(value.strip())
    if isinstance(value, list) and value:
        ranks = [_RANK.get(item.strip()) for item in value if isinstance(item, str)]
        if len(ranks) == len(value) and ranks:
            return max(ranks)
    return None


def _flatten_claims(claims: object) -> list[Mapping[str, Any]]:
    if isinstance(claims, list):
        return [item for item in claims if isinstance(item, Mapping)]
    if not isinstance(claims, Mapping):
        return []
    flattened: list[Mapping[str, Any]] = []
    for value in claims.values():
        if isinstance(value, list):
            flattened.extend(item for item in value if isinstance(item, Mapping))
    return flattened


def _claim_refs(claim: Mapping[str, Any]) -> list[str]:
    for key in _SOURCE_REF_KEYS:
        value = claim.get(key)
        if isinstance(value, list):
            return [str(item).strip() for item in value if _nonblank(item)]
        if _nonblank(value):
            return [str(value).strip()]
    return []


def source_capability_rank(source: Mapping[str, Any]) -> int | None:
    """Return the maximum narrative rank a source can support."""

    explicit = _explicit_capability(source)
    if explicit is not None:
        return _capability_rank(explicit)
    return _RANK.get(DEFAULT_SOURCE_CAPABILITIES.get(_source_type(source), ""))


def validate_claim_capabilities(
    sources: object,
    claims: object,
    *,
    strict: bool = False,
) -> list[str]:
    """Ensure every claim's required level is within every source ceiling.

    In compatibility mode the graph is ignored unless it contains a claim
    level or an explicit source capability.  Strict callers get fail-closed
    validation for the complete graph.
    """

    errors: list[str] = []
    source_items = [item for item in sources if isinstance(item, Mapping)] if isinstance(sources, list) else []
    source_map: dict[str, Mapping[str, Any]] = {}
    for index, source in enumerate(source_items):
        source_id = _source_id(source)
        if not source_id:
            if strict:
                errors.append(f"missing:source_id:{index}")
            continue
        if source_id in source_map:
            errors.append(f"duplicate:source_id:{source_id}")
        source_map[source_id] = source
        explicit = _explicit_capability(source)
        rank = source_capability_rank(source)
        if strict and explicit is None:
            errors.append(f"missing:source_capability:{source_id}")
        if strict and rank is None:
            errors.append(f"invalid:source_capability:{source_id}")

    claim_items = _flatten_claims(claims)
    for index, claim in enumerate(claim_items):
        claim_id = claim.get("claim_id") or claim.get("id") or index
        label = str(claim_id).strip()
        required = claim.get("claim_level") or claim.get("required_claim_level")
        graph_is_used = strict or required is not None or any(
            key in claim for key in _SOURCE_CAPABILITY_KEYS
        )
        if not graph_is_used:
            continue
        if not _nonblank(required) or required not in _RANK:
            errors.append(f"invalid:claim_level:{label}")
            continue
        refs = _claim_refs(claim)
        if not refs:
            errors.append(f"missing:claim_source:{label}")
            continue
        for source_id in refs:
            source = source_map.get(source_id)
            if source is None:
                errors.append(f"unknown_source:{label}:{source_id}")
                continue
            rank = source_capability_rank(source)
            if rank is None:
                errors.append(f"invalid:source_capability:{source_id}")
                continue
            if _RANK[required] > rank:
                errors.append(f"claim_level_exceeds_source_capability:{label}:{source_id}")
    return sorted(set(errors))


__all__ = [
    "CAPABILITY_LEVELS",
    "DEFAULT_SOURCE_CAPABILITIES",
    "source_capability_rank",
    "validate_claim_capabilities",
]
