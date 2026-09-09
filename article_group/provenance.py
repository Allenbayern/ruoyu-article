"""Cross-artifact source eligibility checks for current article claims."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load_manifest(run_root: Path) -> dict[str, Any] | None:
    path = run_root / "source-manifest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def validate_current_source_provenance(
    batch: dict[str, Any], run_root: Path
) -> list[str]:
    """Reject excluded sources from all current-draft reference fields."""
    manifest = _load_manifest(run_root)
    if manifest is None:
        return ["source_manifest_unreadable"]
    sources = manifest.get("sources")
    if not isinstance(sources, list):
        return ["source_manifest_sources_invalid"]

    source_map = {
        source.get("source_id"): source
        for source in sources
        if isinstance(source, dict) and isinstance(source.get("source_id"), str)
    }
    excluded = {
        source_id
        for source_id, source in source_map.items()
        if source.get("eligible_for_current_draft") is False
        or source.get("role") == "context-only-excluded"
    }
    errors: list[str] = []
    def validate_record(record: dict[str, Any], aid: str, *, label: str) -> None:
        prefix = "" if label == "article" else f"{label}:"
        current_refs: set[str] = set()
        source_refs = record.get("source_refs")
        if isinstance(source_refs, list):
            current_refs.update(item for item in source_refs if isinstance(item, str))
        for mapping in record.get("claim_mappings", []) if isinstance(record.get("claim_mappings"), list) else []:
            if isinstance(mapping, dict) and isinstance(mapping.get("source_id"), str):
                current_refs.add(mapping["source_id"])
            if isinstance(mapping, dict) and isinstance(mapping.get("source_ids"), list):
                current_refs.update(
                    item for item in mapping["source_ids"] if isinstance(item, str)
                )
        for claim in record.get("permitted_claims", []) if isinstance(record.get("permitted_claims"), list) else []:
            if isinstance(claim, dict):
                refs = claim.get("source_ids")
                if isinstance(refs, list):
                    current_refs.update(item for item in refs if isinstance(item, str))
        for source_id in sorted(current_refs):
            if source_id not in source_map:
                errors.append(f"current_source_unknown:{prefix}{aid}:{source_id}")
            elif source_id in excluded:
                errors.append(f"excluded_source_in_current_ref:{prefix}{aid}:{source_id}")
        exclusion_refs = record.get("exclusion_evidence_refs", [])
        if isinstance(exclusion_refs, list):
            for source_id in exclusion_refs:
                if source_id not in excluded:
                    errors.append(f"invalid_exclusion_evidence_ref:{prefix}{aid}:{source_id}")

    for article in batch.get("articles", []) if isinstance(batch.get("articles"), list) else []:
        if isinstance(article, dict):
            validate_record(article, str(article.get("article_id", "unknown")), label="article")

    # New runs may carry machine-readable task-card extracts.  They are checked
    # separately from article records so a stale/excluded source cannot hide in
    # a task-card-only reference path.  Legacy Markdown task cards remain
    # historical evidence and are not reinterpreted by this new contract.
    task_cards_dir = run_root / "task-cards"
    if task_cards_dir.is_dir():
        for path in sorted(task_cards_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                errors.append(f"task_card_source_record_unreadable:{path.name}")
                continue
            if not isinstance(payload, dict):
                errors.append(f"task_card_source_record_invalid:{path.name}")
                continue
            validate_record(
                payload,
                str(payload.get("article_id", path.stem)),
                label="task_card",
            )
    return errors
