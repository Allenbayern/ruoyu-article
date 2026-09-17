from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from article_group import case_distill
from article_group.case_contract import CaseContractError, validate_case_card
from article_group.viral_research_contract import (
    ViralResearchContractError,
    _platform_matches_case_contract,
    validate_local_ref,
)
from article_group.viral_research_evidence import (
    ViralResearchEvidenceError,
    scan_evidence_file,
)
from article_group.viral_research_package import (
    ViralResearchPackageError,
    validate_package_root,
)
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


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _semantic_pass() -> dict[str, Any]:
    return {
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
    }


def _validate_report_schema(report: Mapping[str, Any]) -> None:
    try:
        from jsonschema import Draft202012Validator, FormatChecker

        schema_path = (
            Path(__file__).resolve().parents[1]
            / "schemas"
            / "viral-research-distillation-report.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(report),
            key=lambda item: list(item.absolute_path),
        )
    except (OSError, json.JSONDecodeError, ImportError) as exc:
        raise _error("report_schema_unavailable") from exc
    if errors:
        location = ".".join(str(part) for part in errors[0].absolute_path)
        raise _error("report_schema_error", f"{location}:{errors[0].message}")


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


def _routing_record(sample: Mapping[str, Any]) -> dict[str, Any]:
    """Keep non-selected routing output free of evidence references/content."""
    record: dict[str, Any] = {}
    for field in ("sample_id", "account_id", "platform", "qualification_status", "exclusion_reason"):
        if field in sample and sample[field] not in (None, ""):
            record[field] = sample[field]
    return record


def _selected_records(
    manifest: Mapping[str, Any],
    *,
    shape: Mapping[str, Any],
    run_root: Path,
) -> tuple[SelectionResult, list[dict[str, Any]]]:
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
                "platform": str(sample["platform"]),
                "account_id": str(sample["account_id"]),
                "snapshot_ref": _sample_ref(sample, "clean_ref", run_root=run_root),
                "performance_evidence_ref": _sample_ref(
                    sample, "metadata_ref", run_root=run_root
                ),
                "card_ref": f"{sample_id}.json",
                "qualification_status": sample["qualification_status"],
            }
        )
    return selection, selected


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
    except ViralResearchPackageError as exc:
        package_code = getattr(exc, "code", "")
        if package_code in {"blocked", "package_blocked"}:
            raise _error("package_blocked") from exc
        raise _error("contract_failed", str(exc).split(":", 1)[0]) from exc
    except ViralResearchContractError as exc:
        raise _error("contract_failed", str(exc).split(":", 1)[0]) from exc
    if manifest.get("status") != "evidence_checked":
        raise _error("package_not_evidence_checked")
    run_root = package.parent.parent
    shape = _criteria_shape(criteria)
    selection, selected = _selected_records(
        manifest, shape=shape, run_root=run_root
    )
    package_manifest_path = package / "manifest.json"
    package_integrity_path = package / "integrity.json"
    payload: dict[str, Any] = {
        "schema_version": PREPARE_SCHEMA_VERSION,
        "package_run_id": manifest["run_id"],
        "package_manifest_sha256": _sha256_file(package_manifest_path),
        "package_integrity_sha256": _sha256_file(package_integrity_path),
        "criteria": shape,
        "minimum_cards": MIN_QUALIFIED_SAMPLES,
        "minimum_distinct_accounts": MIN_DISTINCT_ACCOUNTS,
        "ready_for_distill": True,
        "selected_sample_ids": [item["sample_id"] for item in selected],
        "selected": selected,
        "pending": [_routing_record(item) for item in selection.pending],
        "excluded": [_routing_record(item) for item in selection.excluded],
        "allowed_snapshot_refs": [item["snapshot_ref"] for item in selected],
        "allowed_card_refs": [item["card_ref"] for item in selected],
        "allowed_performance_refs": [
            item["performance_evidence_ref"] for item in selected
        ],
        "semantic_pass": _semantic_pass(),
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
    if card.get("account_id") != selected.get("account_id"):
        raise _error("card_account_id_mismatch", str(selected.get("sample_id")))
    if card.get("platform") != selected.get("platform"):
        raise _error("card_platform_mismatch", str(selected.get("sample_id")))
    if card.get("qualification_status") != selected.get("qualification_status"):
        raise _error("card_qualification_status_mismatch", str(selected.get("sample_id")))
    if not _platform_matches_case_contract(selected.get("platform"), card):
        raise _error("card_contract_platform_mismatch", str(selected.get("sample_id")))
    for field in ("snapshot_ref", "performance_evidence_ref"):
        if card.get(field) != selected.get(field):
            raise _error("card_evidence_ref_mismatch", field)


def _validate_card_evidence(card: Mapping[str, Any], *, run_root: Path) -> None:
    client_evidence = card.get("client_evidence")
    if not isinstance(client_evidence, Mapping):
        raise _error("card_client_evidence_missing")
    try:
        evidence_path, evidence_digest = validate_local_ref(
            str(client_evidence.get("evidence_ref")), root=run_root
        )
    except ViralResearchContractError as exc:
        raise _error("card_client_evidence_ref_invalid", str(exc).split(":", 1)[0]) from exc
    if client_evidence.get("sha256") != evidence_digest:
        raise _error("card_client_evidence_sha256_mismatch")
    try:
        scan_evidence_file(evidence_path, expected_digest=evidence_digest)
    except ViralResearchEvidenceError as exc:
        raise _error("card_client_evidence_scan_failed", exc.code) from exc
    metrics = card.get("metrics")
    if not isinstance(metrics, list):
        raise _error("card_metrics_missing")
    for metric in metrics:
        if not isinstance(metric, Mapping):
            raise _error("card_metric_invalid")
        try:
            metric_path, metric_digest = validate_local_ref(
                str(metric.get("evidence_ref")), root=run_root
            )
        except ViralResearchContractError as exc:
            raise _error("card_metric_evidence_ref_invalid", str(exc).split(":", 1)[0]) from exc
        try:
            scan_evidence_file(metric_path, expected_digest=metric_digest)
        except ViralResearchEvidenceError as exc:
            raise _error("card_metric_evidence_scan_failed", exc.code) from exc


def _card_batch_manifest(
    cards_root: Path,
    *,
    prepared_path: Path,
    prepared: Mapping[str, Any],
    selected: list[Mapping[str, Any]],
) -> None:
    manifest_path = cards_root / "manifest.json"
    batch = _load_object(manifest_path, "card_batch_manifest_unavailable")
    if batch.get("schema_version") != "viral-research-card-batch-v1":
        raise _error("card_batch_manifest_schema_error")
    if batch.get("prepare_sha256") != _sha256_file(prepared_path):
        raise _error("card_batch_prepare_mismatch")
    if batch.get("package_manifest_sha256") != prepared.get("package_manifest_sha256"):
        raise _error("card_batch_package_mismatch")
    if batch.get("package_integrity_sha256") != prepared.get("package_integrity_sha256"):
        raise _error("card_batch_integrity_mismatch")
    if batch.get("criteria") != prepared.get("criteria"):
        raise _error("card_batch_criteria_mismatch")
    if batch.get("selected_sample_ids") != prepared.get("selected_sample_ids"):
        raise _error("card_batch_selection_mismatch")
    expected_cards: list[dict[str, Any]] = []
    for item in selected:
        card_path = _safe_card_path(cards_root, item.get("card_ref"))
        expected_cards.append(
            {
                "sample_id": item.get("sample_id"),
                "card_ref": item.get("card_ref"),
                "sha256": _sha256_file(card_path),
            }
        )
    if batch.get("cards") != expected_cards:
        raise _error("card_batch_manifest_mismatch")


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
    package_root: str | Path,
    criteria: SelectionCriteria | Mapping[str, Any],
    cards_root: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Validate semantic cards and write a provisional review packet."""
    prepared_path = Path(prepared_input).expanduser().resolve()
    package = Path(package_root).expanduser().resolve()
    cards = Path(cards_root).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise _error("artifact_exists")
    prepared = _load_object(prepared_path, "prepared_input_unavailable")
    if prepared.get("schema_version") != PREPARE_SCHEMA_VERSION:
        raise _error("prepared_schema_error")
    if prepared.get("ready_for_distill") is not True:
        raise _error("insufficient_qualified_samples")
    if package.name != "package" or cards.name != "cards" or package.parent != cards.parent:
        raise _error("path_escape", "package_cards_boundary")
    try:
        package_manifest = validate_package_root(package)
    except ViralResearchPackageError as exc:
        raise _error("package_integrity_failed", getattr(exc, "code", "package")) from exc
    if package_manifest.get("status") != "evidence_checked":
        raise _error("package_not_evidence_checked")
    package_manifest_path = package / "manifest.json"
    package_integrity_path = package / "integrity.json"
    if prepared.get("package_run_id") != package_manifest.get("run_id"):
        raise _error("prepared_package_run_id_mismatch")
    if prepared.get("package_manifest_sha256") != _sha256_file(package_manifest_path):
        raise _error("prepared_package_manifest_mismatch")
    if prepared.get("package_integrity_sha256") != _sha256_file(package_integrity_path):
        raise _error("prepared_package_integrity_mismatch")
    selected = prepared.get("selected")
    if not isinstance(selected, list) or len(selected) < MIN_QUALIFIED_SAMPLES:
        raise _error("insufficient_qualified_samples")
    expected_shape = _criteria_shape(criteria)
    if prepared.get("criteria") != expected_shape:
        raise _error("prepared_criteria_mismatch")
    run_root = package.parent.parent
    selection, expected_selected = _selected_records(
        package_manifest, shape=expected_shape, run_root=run_root
    )
    expected_pending = [_routing_record(item) for item in selection.pending]
    expected_excluded = [_routing_record(item) for item in selection.excluded]
    expected_ids = [item["sample_id"] for item in expected_selected]
    expected_snapshot_refs = [item["snapshot_ref"] for item in expected_selected]
    expected_card_refs = [item["card_ref"] for item in expected_selected]
    expected_performance_refs = [item["performance_evidence_ref"] for item in expected_selected]
    if (
        selected != expected_selected
        or prepared.get("selected_sample_ids") != expected_ids
        or prepared.get("allowed_snapshot_refs") != expected_snapshot_refs
        or prepared.get("allowed_card_refs") != expected_card_refs
        or prepared.get("allowed_performance_refs") != expected_performance_refs
        or prepared.get("pending") != expected_pending
        or prepared.get("excluded") != expected_excluded
        or prepared.get("minimum_cards") != MIN_QUALIFIED_SAMPLES
        or prepared.get("minimum_distinct_accounts") != MIN_DISTINCT_ACCOUNTS
        or prepared.get("semantic_pass") != _semantic_pass()
    ):
        raise _error("prepared_selection_mismatch")
    _card_batch_manifest(
        cards,
        prepared_path=prepared_path,
        prepared=prepared,
        selected=expected_selected,
    )
    card_map: dict[str, dict[str, Any]] = {}
    for selected_item in expected_selected:
        if not isinstance(selected_item, Mapping):
            raise _error("selected_item_invalid")
        sample_id = str(selected_item.get("sample_id") or "")
        for field in ("snapshot_ref", "performance_evidence_ref"):
            _sample_ref(selected_item, field, run_root=run_root)
        card_path = _safe_card_path(cards, selected_item.get("card_ref"))
        card = _load_object(card_path, "card_unreadable")
        _validate_card_refs(card, selected_item)
        _validate_card_evidence(card, run_root=run_root)
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
    _validate_report_schema(report)
    _write_new(output, report)
    from article_group.evidence_write import anchor_artifact

    anchor_artifact(  # new-only（存在即拒）：账本只记一条产物级锚点（报告本身在 run 内才记）
        output, reason="viral_research:distill",
        digest=_sha256_file(output),
    )
    return report
