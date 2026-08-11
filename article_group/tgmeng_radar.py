"""Isolated R0 tgmeng discovery-radar artifact builder.

Converts verified tgmeng discovery results into an explicit local R0
artifact. It is not a candidate pool and never carries evidence or
claims. No network request occurs on import. Mirrors the Yuafeng
discovery-radar contract (source_role=discovery, evidence_eligible=False).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Final

from article_group.tgmeng_hot import (
    _BOARDS,
    _CANDY_TYPES,
    TgmengHotError,
    fetch_board,
    fetch_candy,
)

_SCHEMA_VERSION: Final = "1"
_ALLOWED_SOURCES: Final = frozenset(_BOARDS | {"candy"})
_PROHIBITED_RECORD_FIELDS: Final = frozenset({
    "evidence_atom_ids", "primary_atom", "claim", "claim_id", "claim_text",
    "verdict", "source_url", "captured_at", "media_path",
})


class DiscoveryRadarError(ValueError):
    """Raised for invalid radar descriptors, fetch results, or output paths."""


def _validate_descriptor(descriptor: object) -> dict[str, Any]:
    if not isinstance(descriptor, dict):
        raise DiscoveryRadarError("source_descriptor_must_be_a_dict")
    name = descriptor.get("name")
    if name not in _ALLOWED_SOURCES:
        raise DiscoveryRadarError("invalid_source_name")

    if name == "candy":
        if set(descriptor) != {"name", "type"}:
            raise DiscoveryRadarError("invalid_candy_descriptor")
        candy_type = descriptor["type"]
        if candy_type not in _CANDY_TYPES:
            raise DiscoveryRadarError("invalid_candy_type")
    else:
        if set(descriptor) != {"name"}:
            raise DiscoveryRadarError("invalid_board_descriptor")
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
    if not all(
        isinstance(result[field], str) and result[field]
        for field in ("source", "endpoint", "fetched_at")
    ):
        raise DiscoveryRadarError("invalid_fetch_result_metadata")
    if not isinstance(result["items"], list) or not all(
        isinstance(item, dict) for item in result["items"]
    ):
        raise DiscoveryRadarError("invalid_fetch_result_items")
    return result


def _record(result: dict[str, Any], item: dict[str, Any], index: int) -> dict[str, Any]:
    title = item.get("title")
    url = item.get("url")
    locator = title.strip() if isinstance(title, str) and title.strip() else (
        url.strip() if isinstance(url, str) and url.strip() else f"item:{index}"
    )
    record = {
        "source": result["source"],
        "endpoint": result["endpoint"],
        "fetched_at": result["fetched_at"],
        "locator": locator,
        "item_index": index,
        "flags": "needs_editorial_research",
        "source_role": "discovery",
        "evidence_eligible": False,
    }
    score = item.get("score")
    if isinstance(score, str) and score.strip():
        record["score"] = score.strip()
    return record


def build_tgmeng_discovery_radar(
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
        name: (lambda _name=name: fetch_board(_name)) for name in _BOARDS
    }
    fetchers.setdefault("candy", fetch_candy)

    artifact: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "artifact_type": "discovery_radar",
        "builder": "tgmeng_radar",
        "state": "R0 radar",
        "source_layer": "discovery-only",
        "candidate_pool_eligible": False,
        "evidence_eligible": False,
        "next_action": "needs_editorial_research",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "records": [],
        "summary": {},
    }
    for descriptor in descriptors:
        name = descriptor["name"]
        try:
            if name == "candy":
                result = fetchers["candy"](descriptor["type"])
            else:
                result = fetchers[name]()
        except TgmengHotError as error:
            artifact.setdefault("errors", []).append(
                {"source": name, "code": str(error)}
            )
            continue
        validated = _validate_fetch_result(result)
        if not validated["items"]:
            artifact.setdefault("errors", []).append(
                {"source": validated["source"], "code": "source_empty"}
            )
            continue
        for index, item in enumerate(validated["items"]):
            record = _record(validated, item, index)
            record = {k: v for k, v in record.items() if k not in _PROHIBITED_RECORD_FIELDS}
            artifact["records"].append(record)

    artifact["summary"] = {
        "record_count": len(artifact["records"]),
        "source_count": len({r["source"] for r in artifact["records"]}),
        "error_count": len(artifact.get("errors", [])),
    }

    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(artifact, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return artifact


def validate_discovery_radar(artifact: object) -> list[str]:
    """Return a list of contract violations (empty list == valid)."""
    problems: list[str] = []
    if not isinstance(artifact, dict):
        return ["artifact_must_be_a_dict"]
    if artifact.get("artifact_type") != "discovery_radar":
        problems.append("wrong_artifact_type")
    if artifact.get("schema_version") != _SCHEMA_VERSION:
        problems.append("wrong_schema_version")
    if artifact.get("state") != "R0 radar":
        problems.append("wrong_state")
    if artifact.get("candidate_pool_eligible") is not False:
        problems.append("candidate_pool_eligible")
    if artifact.get("evidence_eligible") is not False:
        problems.append("artifact_evidence_eligible")
    records = artifact.get("records")
    if not isinstance(records, list):
        return problems + ["records_must_be_a_list"]
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            problems.append(f"record_{index}_not_a_dict")
            continue
        if record.get("source_role") != "discovery":
            problems.append(f"record_{index}_not_discovery")
        if record.get("evidence_eligible") is not False:
            problems.append(f"record_{index}_evidence_eligible")
        for field in ("source", "endpoint", "fetched_at", "locator"):
            if not isinstance(record.get(field), str) or not record.get(field):
                problems.append(f"record_{index}_missing_{field}")
        for field in _PROHIBITED_RECORD_FIELDS:
            if field in record:
                problems.append(f"record_{index}_prohibited_{field}")
    return problems
