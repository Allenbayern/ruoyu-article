from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from article_group import case_distill
from article_group.case_contract import CaseContractError, validate_case_card
from article_group.viral_research_contract import (
    ViralResearchContractError,
    validate_local_ref,
)
from article_group.viral_research_package import validate_package_root
from article_group.viral_research_selection import (
    MIN_DISTINCT_ACCOUNTS,
    MIN_QUALIFIED_SAMPLES,
    SelectionCriteria,
    SelectionResult,
    select_shape_matched_samples,
)

DISTILL_SCHEMA_VERSION = "viral-research-distillation-report-v1"
PREPARE_SCHEMA_VERSION = "viral-research-distill-prepare-v1"


class ViralResearchDistillError(ValueError):
    """Raised when bounded viral-research preparation/finalization fails."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}:{detail}" if detail else code)


def _error(code: str, detail: str = "") -> ViralResearchDistillError:
    return ViralResearchDistillError(code, detail)


def _load_object(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _error(code, path.name) from exc
    if not isinstance(value, dict):
        raise _error(code, path.name)
    return value


def _write_new(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists():
        raise _error("artifact_exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _criteria_shape(criteria: SelectionCriteria | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(criteria, SelectionCriteria):
        return criteria.as_shape()
    if not isinstance(criteria, Mapping):
        raise _error("criteria_invalid")
    return dict(criteria)


def _sample_ref(sample: Mapping[str, Any], field: str, *, run_root: Path) -> str:
    reference = sample.get(field)
    if not isinstance(reference, str) or not reference.strip():
        raise _error("evidence_ref_missing", field)
    try:
        path, digest = validate_local_ref(reference, root=run_root)
    except ViralResearchContractError as exc:
        raise _error(str(exc).split(":", 1)[0], field) from exc
    return f"{path.relative_to(run_root).as_posix()}#sha256={digest}"


def prepare_distill_input(
    package_root: str | Path,
    *,
    criteria: SelectionCriteria | Mapping[str, Any],
    output_path: str | Path,
) -> dict[str, Any]:
    """Write the bounded, read-only input manifest for one semantic pass."""
    package = Path(package_root).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise _error("artifact_exists")
    try:
        manifest = validate_package_root(package)
    except ViralResearchContractError as exc:
        raise _error("contract_failed", str(exc).split(":", 1)[0]) from exc
    run_root = package.parent.parent
    shape = _criteria_shape(criteria)
    selection = select_shape_matched_samples(
        manifest.get("samples", []),
        target_shape=shape,
        min_samples=MIN_QUALIFIED_SAMPLES,
        min_accounts=MIN_DISTINCT_ACCOUNTS,
    )
    if not selection.ready:
        raise _error(selection.reason or "insufficient_qualified_samples")
    selected: list[dict[str, Any]] = []
    for sample in selection.selected:
        sample_id = str(sample["sample_id"])
        selected.append(
            {
                "sample_id": sample_id,
                "account_id": str(sample["account_id"]),
                "snapshot_ref": _sample_ref(sample, "clean_ref", run_root=run_root),
                "performance_evidence_ref": _sample_ref(
                    sample, "metadata_ref", run_root=run_root
                ),
                "card_ref": f"{sample_id}.json",
                "qualification_status": sample["qualification_status"],
            }
        )
    payload: dict[str, Any] = {
        "schema_version": PREPARE_SCHEMA_VERSION,
        "package_run_id": manifest["run_id"],
        "criteria": shape,
        "minimum_cards": MIN_QUALIFIED_SAMPLES,
        "minimum_distinct_accounts": MIN_DISTINCT_ACCOUNTS,
        "ready_for_distill": True,
        "selected_sample_ids": [item["sample_id"] for item in selected],
        "selected": selected,
        "pending": list(selection.pending),
        "excluded": list(selection.excluded),
        "allowed_snapshot_refs": [item["snapshot_ref"] for item in selected],
        "allowed_card_refs": [item["card_ref"] for item in selected],
        "allowed_performance_refs": [
            item["performance_evidence_ref"] for item in selected
        ],
        "semantic_pass": {
            "mode": "explicit_codex_trigger_required",
            "allowed_reads": [
                "selected.card_ref",
                "selected.snapshot_ref",
                "selected.performance_evidence_ref",
            ],
            "instruction": (
                "Read only the listed hashed snapshot/card/performance references. "
                "Return semantic observations as validated case cards. "
                "Do not change qualification status, write canonical rules, publish, or promote rules."
            ),
        },
    }
    _write_new(output, payload)
    return payload


def _safe_card_path(cards_root: Path, card_ref: Any) -> Path:
    if not isinstance(card_ref, str) or not card_ref.strip():
        raise _error("card_ref_missing")
    relative = Path(card_ref)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
        raise _error("card_path_escape")
    path = (cards_root / relative).resolve(strict=False)
    root = cards_root.resolve()
    if root not in path.parents or not path.is_file():
        raise _error("card_missing", card_ref)
    return path


def _validate_card_refs(card: Mapping[str, Any], selected: Mapping[str, Any]) -> None:
    if card.get("sample_id") != selected.get("sample_id"):
        raise _error("card_sample_id_mismatch", str(selected.get("sample_id")))
    for field in ("snapshot_ref", "performance_evidence_ref"):
        if card.get(field) != selected.get(field):
            raise _error("card_evidence_ref_mismatch", field)


def _positive_or_excluded(
    candidates: list[dict[str, Any]],
    cards: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    positive: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for raw_candidate in candidates:
        candidate = dict(raw_candidate)
        supporting = candidate.get("supporting_qualified_samples", [])
        accounts = {
            str(cards[item["sample_id"]].get("account_id"))
            for item in supporting
            if isinstance(item, Mapping) and item.get("sample_id") in cards
        }
        if len(supporting) >= 2 and len(accounts) >= 2:
            candidate["verification_state"] = "promising"
            candidate["automatic_publication_authority"] = False
            candidate["promotion_status"] = "provisional_only"
            positive.append(candidate)
        else:
            excluded.append(
                {
                    "technique": candidate.get("technique"),
                    "technique_type": candidate.get("technique_type"),
                    "reason": "insufficient_cross_account_support",
                    "supporting_qualified_samples": supporting,
                    "excluded_observations": candidate.get("excluded_observations", []),
                }
            )
    return positive, excluded


def finalize_distillation(
    prepared_input: str | Path,
    *,
    cards_root: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Validate semantic cards and write a provisional review packet."""
    prepared_path = Path(prepared_input).expanduser().resolve()
    cards = Path(cards_root).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise _error("artifact_exists")
    prepared = _load_object(prepared_path, "prepared_input_unavailable")
    if prepared.get("schema_version") != PREPARE_SCHEMA_VERSION:
        raise _error("prepared_schema_error")
    if prepared.get("ready_for_distill") is not True:
        raise _error("insufficient_qualified_samples")
    selected = prepared.get("selected")
    if not isinstance(selected, list) or len(selected) < MIN_QUALIFIED_SAMPLES:
        raise _error("insufficient_qualified_samples")
    card_map: dict[str, dict[str, Any]] = {}
    for selected_item in selected:
        if not isinstance(selected_item, Mapping):
            raise _error("selected_item_invalid")
        sample_id = str(selected_item.get("sample_id") or "")
        card_path = _safe_card_path(cards, selected_item.get("card_ref"))
        card = _load_object(card_path, "card_unreadable")
        _validate_card_refs(card, selected_item)
        try:
            validate_case_card(card)
        except CaseContractError as exc:
            raise _error("case_contract_failed", str(exc)) from exc
        card_map[sample_id] = card
    if len(card_map) < MIN_QUALIFIED_SAMPLES:
        raise _error("insufficient_qualified_samples")
    try:
        candidates = case_distill.distill_candidates(card_map)
    except CaseContractError as exc:
        raise _error("case_distill_failed", str(exc)) from exc
    positive, excluded = _positive_or_excluded(candidates, card_map)
    negative_patterns = [
        {
            "sample_id": sample_id,
            "patterns": list(card.get("negative_patterns", [])),
        }
        for sample_id, card in card_map.items()
        if isinstance(card.get("negative_patterns"), list)
        and card.get("negative_patterns")
    ]
    for candidate in candidates:
        if candidate.get("excluded_observations"):
            excluded.append(
                {
                    "technique": candidate.get("technique"),
                    "technique_type": candidate.get("technique_type"),
                    "reason": "observation_only",
                    "observations": candidate["excluded_observations"],
                }
            )
    report: dict[str, Any] = {
        "schema_version": DISTILL_SCHEMA_VERSION,
        "package_run_id": prepared.get("package_run_id"),
        "criteria": prepared.get("criteria", {}),
        "selected_sample_ids": prepared["selected_sample_ids"],
        "positive_candidates": positive,
        "negative_patterns": negative_patterns,
        "excluded_observations": excluded,
        "coverage_gaps": [],
        "promotion_status": "provisional_only",
        "verification_state": "promising" if positive else "observation_only",
        "automatic_publication_authority": False,
    }
    _write_new(output, report)
    return report
