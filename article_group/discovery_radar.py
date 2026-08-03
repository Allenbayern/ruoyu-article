"""Isolated R0 discovery-radar artifact builder.

This module converts verified Yuafeng discovery results into an explicit local
R0 artifact. It is not a candidate pool and never carries evidence or claims.
No network request occurs on import.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Final

from article_group.yuafeng_hot import (
    _VALID_AGGREGATE_ACTIONS,
    fetch_aggregate,
    fetch_tencent_news,
    fetch_uc_hot,
)

_SCHEMA_VERSION: Final = "1"
_ALLOWED_SOURCES: Final = frozenset({"uc", "tencent", "aggregate"})
_PROHIBITED_RECORD_FIELDS: Final = frozenset({
    "evidence_atom_ids", "primary_atom", "claim", "claim_id", "claim_text",
    "candidate_id", "candidate_pool_id", "candidates", "recommendation",
    "content_value_scores", "reader_intent", "angle", "event_time",
})
_REQUIRED_RECORD_FIELDS: Final = frozenset({
    "source", "endpoint", "fetched_at", "locator", "item_index", "flags",
    "source_role", "evidence_eligible",
})
_ALLOWED_ARTIFACT_FIELDS: Final = frozenset({
    "schema_version", "artifact_type", "state", "observed_at", "source_layer",
    "candidate_pool_eligible", "evidence_eligible", "next_action", "records",
})


class DiscoveryRadarError(ValueError):
    """Raised when a discovery radar cannot be safely built or validated."""


def _validate_page(value: object, field: str) -> None:
    if value is not None and (
        isinstance(value, bool) or not isinstance(value, int) or value < 1
    ):
        raise DiscoveryRadarError(f"invalid_{field}")


def _validate_descriptor(descriptor: object) -> dict[str, Any]:
    if not isinstance(descriptor, dict):
        raise DiscoveryRadarError("source_descriptor_must_be_a_dict")
    name = descriptor.get("name")
    if name not in _ALLOWED_SOURCES:
        raise DiscoveryRadarError("invalid_source_name")

    if name == "uc":
        if set(descriptor) != {"name"}:
            raise DiscoveryRadarError("invalid_uc_descriptor")
    elif name == "tencent":
        if not set(descriptor) <= {"name", "page", "type_"}:
            raise DiscoveryRadarError("invalid_tencent_descriptor")
        _validate_page(descriptor.get("page"), "tencent_page")
        type_ = descriptor.get("type_")
        if type_ is not None and (
            not isinstance(type_, str) or not type_ or type_ != type_.strip()
        ):
            raise DiscoveryRadarError("invalid_tencent_type")
    else:
        if not set(descriptor) <= {"name", "action", "page"}:
            raise DiscoveryRadarError("invalid_aggregate_descriptor")
        action = descriptor.get("action")
        if action not in _VALID_AGGREGATE_ACTIONS:
            raise DiscoveryRadarError("invalid_aggregate_action")
        _validate_page(descriptor.get("page"), "aggregate_page")
    return descriptor


def _validate_fetch_result(result: object) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise DiscoveryRadarError("invalid_fetch_result")
    if result.get("source_role") != "discovery":
        raise DiscoveryRadarError("fetch_result_not_discovery")
    if result.get("evidence_eligible") is not False:
        raise DiscoveryRadarError("fetch_result_evidence_eligible")
    for field in ("source", "endpoint", "fetched_at", "items"):
        if field not in result:
            raise DiscoveryRadarError(f"fetch_result_missing_{field}")
    if not all(isinstance(result[field], str) and result[field] for field in ("source", "endpoint", "fetched_at")):
        raise DiscoveryRadarError("invalid_fetch_result_metadata")
    if not isinstance(result["items"], list) or not all(isinstance(item, dict) for item in result["items"]):
        raise DiscoveryRadarError("invalid_fetch_result_items")
    return result


def _record(result: dict[str, Any], item: dict[str, Any], index: int) -> dict[str, Any]:
    title = item.get("title")
    url = item.get("url")
    locator = title.strip() if isinstance(title, str) and title.strip() else (
        url.strip() if isinstance(url, str) and url.strip() else f"item:{index}"
    )
    return {
        "source": result["source"],
        "endpoint": result["endpoint"],
        "fetched_at": result["fetched_at"],
        "locator": locator,
        "item_index": index,
        "flags": "needs_editorial_research",
        "source_role": "discovery",
        "evidence_eligible": False,
    }


def build_yuafeng_discovery_radar(
    output_path: str | Path,
    sources: list[dict[str, Any]],
    *,
    _fetchers: dict[str, Callable[..., dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Build one caller-addressed, atomic R0 discovery-only JSON artifact."""
    if not isinstance(sources, list) or not 1 <= len(sources) <= 10:
        raise DiscoveryRadarError("sources_must_be_a_bounded_list")
    descriptors = [_validate_descriptor(item) for item in sources]
    path = Path(output_path)
    if path.suffix != ".json" or not path.parent.is_dir():
        raise DiscoveryRadarError("output_path_must_have_existing_json_parent")

    fetchers = _fetchers or {
        "uc": fetch_uc_hot,
        "tencent": fetch_tencent_news,
        "aggregate": fetch_aggregate,
    }
    records: list[dict[str, Any]] = []
    for descriptor in descriptors:
        name = descriptor["name"]
        try:
            fetcher = fetchers[name]
        except KeyError as exc:
            raise DiscoveryRadarError("missing_fetcher") from None
        kwargs = {key: descriptor[key] for key in ("page", "type_", "action") if key in descriptor}
        result = _validate_fetch_result(fetcher(**kwargs))
        records.extend(_record(result, item, index) for index, item in enumerate(result["items"]))

    artifact = {
        "schema_version": _SCHEMA_VERSION,
        "artifact_type": "discovery_radar",
        "state": "R0 radar",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "source_layer": "discovery-only",
        "candidate_pool_eligible": False,
        "evidence_eligible": False,
        "next_action": "needs_editorial_research",
        "records": records,
    }
    errors = validate_discovery_radar(artifact)
    if errors:
        raise DiscoveryRadarError("invalid_built_radar:" + ",".join(errors))
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return artifact


def validate_discovery_radar(artifact: object) -> list[str]:
    """Return reasons an artifact violates the R0 discovery-only contract."""
    if not isinstance(artifact, dict):
        return ["artifact_must_be_a_dict"]
    errors: list[str] = []
    expected = {
        "artifact_type": "discovery_radar", "state": "R0 radar",
        "source_layer": "discovery-only", "candidate_pool_eligible": False,
        "evidence_eligible": False, "next_action": "needs_editorial_research",
    }
    for field, value in expected.items():
        if artifact.get(field) != value:
            errors.append(f"invalid_{field}")
    observed_at = artifact.get("observed_at")
    try:
        observed = datetime.fromisoformat(observed_at) if isinstance(observed_at, str) else None
    except ValueError:
        observed = None
    if observed is None or observed.tzinfo is None or observed.utcoffset() != timezone.utc.utcoffset(observed):
        errors.append("invalid_observed_at_utc")
    for field in artifact:
        if field not in _ALLOWED_ARTIFACT_FIELDS:
            errors.append(f"prohibited_top_level_{field}")
    if not isinstance(artifact.get("records"), list):
        return errors + ["records_must_be_a_list"]
    for index, record in enumerate(artifact["records"]):
        if not isinstance(record, dict):
            errors.append(f"record_{index}_must_be_a_dict")
            continue
        for field in _REQUIRED_RECORD_FIELDS:
            if field not in record:
                errors.append(f"record_{index}_missing_{field}")
        for field in _PROHIBITED_RECORD_FIELDS:
            if field in record:
                errors.append(f"record_{index}_prohibited_{field}")
        if record.get("source_role") != "discovery":
            errors.append(f"record_{index}_invalid_source_role")
        if record.get("evidence_eligible") is not False:
            errors.append(f"record_{index}_invalid_evidence_eligible")
    return errors
