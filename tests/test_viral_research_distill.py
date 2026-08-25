from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from article_group.viral_research_distill import (
    ViralResearchDistillError,
    finalize_distillation,
    prepare_distill_input,
)
from article_group.viral_research_contract import normalize_sample_id
from article_group.viral_research_package import build_package
from article_group.viral_research_selection import SelectionCriteria


def _case_contract_card(sample: dict) -> dict:
    sample_id = normalize_sample_id(
        platform=sample["platform"],
        account_id=sample["account_id"],
        canonical_url=sample["canonical_url"],
        published_at=sample["published_at"],
    )
    return {
        "sample_id": sample_id,
        "evidence_domain": "competitive_research_evidence",
        "evidence_origin": "client",
        "account_id": sample["account_id"],
        "subject_category": "film",
        "snapshot_ref": sample["clean_ref"],
        "performance_evidence_ref": sample["metadata_ref"],
        "metric_plan_version": "fixture-v1",
        "metric_plan_frozen_at": "2026-08-25T08:00:00+08:00",
        "client_evidence": {
            "evidence_ref": f"{sample['metadata_ref']}#sha256={hashlib.sha256(b'{}').hexdigest()}",
            "original_display": "100000 views",
            "observed_at": "2026-08-25T09:00:00+08:00",
            "confirmer": "fixture-reviewer",
            "sha256": hashlib.sha256(b"{}").hexdigest(),
            "sanitized": True,
        },
        "metric_plan": [{"metric": "view", "visible": True, "required": True}],
        "metrics": [
            {
                "metric": "view",
                "value": 100000,
                "status": "observed",
                "source": "fixture_client",
                "observed_at": "2026-08-25T09:00:00+08:00",
                    "evidence_ref": f"{sample['metadata_ref']}#sha256={hashlib.sha256(b'{}').hexdigest()}",
            }
        ],
        "threshold_or_rank_rule": {
            "version": "fixture-rule-v1",
            "frozen_at": "2026-08-25T08:00:00+08:00",
            "platform": "wechat",
            "baseline": "fixture",
            "window": "publication",
            "rule": "gte",
            "minimums": {"view": 100000},
        },
        "qualification_reason": "Synthetic client evidence meets the frozen fixture rule.",
        "qualification_status": "qualified_viral",
    }


def _build_package(tmp_path: Path, count: int = 5, *, include_pending: bool = False) -> Path:
    for folder in ("raw", "clean", "metadata"):
        (tmp_path / folder).mkdir()
    samples = []
    for index in range(count):
        (tmp_path / "raw" / f"a-{index}.html").write_text(f"<html>{index}</html>", encoding="utf-8")
        (tmp_path / "clean" / f"a-{index}.md").write_text(f"# article {index}", encoding="utf-8")
        (tmp_path / "metadata" / f"a-{index}.json").write_text("{}", encoding="utf-8")
        sample = {
            "platform": "wechat", "account_id": f"acct-{index % 3}",
            "title": f"Film case {index}", "canonical_url": f"https://example.com/article/{index}",
            "published_at": f"2026-08-25T09:{index:02d}:00+08:00", "capture_status": "full",
            "raw_ref": f"raw/a-{index}.html", "clean_ref": f"clean/a-{index}.md",
            "metadata_ref": f"metadata/a-{index}.json",
            "shape": {"medium": "long_form", "content_domain": "film", "narrative_purpose": "review_or_analysis"},
            "qualification_status": "qualified_viral", "source_lane": "wechat_long_form",
        }
        sample["case_contract_card"] = _case_contract_card(sample)
        samples.append(sample)
    if include_pending:
        pending = dict(samples[0])
        pending["account_id"] = "acct-pending"
        pending["canonical_url"] = "https://example.com/article/pending"
        pending["published_at"] = "2026-08-25T10:00:00+08:00"
        pending["qualification_status"] = "observed_pending"
        pending.pop("case_contract_card", None)
        samples.append(pending)
    capture = {"run_id": "run-distill-001", "created_at": "2026-08-25T09:05:00+08:00",
               "source_lanes": ["wechat_long_form"], "samples": samples}
    capture_path = tmp_path / "capture.json"
    capture_path.write_text(json.dumps(capture), encoding="utf-8")
    package_root = tmp_path / "viral-research" / "package"
    build_package(capture_path, run_root=tmp_path, output_root=package_root)
    return package_root


def _criteria() -> SelectionCriteria:
    return SelectionCriteria(platform="wechat", medium="long_form", content_domain="film", narrative_purpose="review_or_analysis")


def _semantic_card(sample_id: str, selected: dict, *, status: str = "qualified_viral",
                   account_id: str | None = None, technique: str = "栏目化标题") -> dict:
    evidence_ref = selected["performance_evidence_ref"]
    evidence_digest = evidence_ref.rsplit("#sha256=", 1)[1]
    if status == "research_only":
        metrics = []
    elif status == "observed_pending":
        metrics = [{"metric": "view", "value": 50_000, "status": "observed", "source": "client_dashboard",
                    "observed_at": "2026-08-25T10:00:00+08:00", "evidence_ref": evidence_ref}]
    else:
        metrics = [{"metric": "view", "value": 200_000, "status": "observed", "source": "client_dashboard",
                    "observed_at": "2026-08-25T10:00:00+08:00", "evidence_ref": evidence_ref}]
    return {
        "sample_id": sample_id, "evidence_domain": "competitive_research_evidence", "evidence_origin": "client",
        "platform": selected.get("platform", "wechat"),
        "account_id": account_id or f"account-{sample_id}", "subject_category": "film",
        "snapshot_ref": selected["snapshot_ref"], "performance_evidence_ref": selected["performance_evidence_ref"],
        "metric_plan_version": "article-metric-v0", "metric_plan_frozen_at": "2026-08-25T08:00:00+08:00",
        "client_evidence": {"evidence_ref": evidence_ref, "original_display": "200000 views",
                            "observed_at": "2026-08-25T10:00:00+08:00", "confirmer": "reviewer-1",
                            "sha256": evidence_digest, "sanitized": True},
        "metric_plan": [{"metric": "view", "visible": True, "required": True}], "metrics": metrics,
        "threshold_or_rank_rule": {"version": "article-rule-v0", "frozen_at": "2026-08-25T08:00:00+08:00",
                                   "platform": "wechat", "baseline": "research", "window": "publication",
                                   "rule": "gte", "minimums": {"view": 100_000}},
        "qualification_reason": "view evidence checked", "qualification_status": status,
        "technique_observations": [{"technique": technique, "technique_type": "title"}],
    }


def _prepare_and_write_cards(tmp_path: Path, *, count: int = 5) -> tuple[Path, Path, dict]:
    package_root = _build_package(tmp_path, count=count)
    prepare_path = tmp_path / "viral-research" / "distillation" / "prepare.json"
    prepared = prepare_distill_input(package_root, criteria=_criteria(), output_path=prepare_path)
    cards_root = tmp_path / "viral-research" / "cards"
    cards_root.mkdir()
    for selected in prepared["selected"]:
        card = _semantic_card(
            selected["sample_id"], selected, account_id=selected["account_id"]
        )
        (cards_root / selected["card_ref"]).write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    card_manifest = {
        "schema_version": "viral-research-card-batch-v1",
        "prepare_sha256": hashlib.sha256(prepare_path.read_bytes()).hexdigest(),
        "package_manifest_sha256": hashlib.sha256(
            (package_root / "manifest.json").read_bytes()
        ).hexdigest(),
        "package_integrity_sha256": hashlib.sha256(
            (package_root / "integrity.json").read_bytes()
        ).hexdigest(),
        "criteria": prepared["criteria"],
        "selected_sample_ids": prepared["selected_sample_ids"],
        "cards": [
            {
                "sample_id": selected["sample_id"],
                "card_ref": selected["card_ref"],
                "sha256": hashlib.sha256(
                    (cards_root / selected["card_ref"]).read_bytes()
                ).hexdigest(),
            }
            for selected in prepared["selected"]
        ],
    }
    (cards_root / "manifest.json").write_text(
        json.dumps(card_manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    return prepare_path, cards_root, prepared


def test_prepare_refuses_fewer_than_five_usable_samples(tmp_path: Path):
    package_root = _build_package(tmp_path, count=4)
    with pytest.raises(ViralResearchDistillError, match="insufficient_qualified_samples"):
        prepare_distill_input(package_root, criteria=_criteria(), output_path=tmp_path / "prepare.json")


def test_prepare_refuses_blocked_package_even_with_qualified_rows(tmp_path: Path):
    package_root = _build_package(tmp_path)
    manifest_path = package_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["status"] = "blocked"
    manifest["errors"] = ["capture_ref_missing"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ViralResearchDistillError, match="blocked|integrity"):
        prepare_distill_input(
            package_root,
            criteria=_criteria(),
            output_path=tmp_path / "blocked-prepare.json",
        )


def test_prepare_writes_bounded_read_only_manifest(tmp_path: Path):
    package_root = _build_package(tmp_path)
    output = tmp_path / "prepare.json"
    prepared = prepare_distill_input(package_root, criteria=_criteria(), output_path=output)
    assert prepared["ready_for_distill"] is True
    assert prepared["semantic_pass"]["mode"] == "explicit_codex_trigger_required"
    assert all("#sha256=" in ref for ref in prepared["allowed_snapshot_refs"])
    assert all("#sha256=" in ref for ref in prepared["allowed_performance_refs"])
    assert "vault" not in json.dumps(prepared).lower()
    assert "token" not in json.dumps(prepared).lower()


def test_prepare_routes_nonselected_samples_without_evidence_refs(tmp_path: Path):
    package_root = _build_package(tmp_path, include_pending=True)
    output = tmp_path / "viral-research" / "distillation" / "prepare.json"
    with pytest.raises(ViralResearchDistillError, match="package_not_evidence_checked"):
        prepare_distill_input(package_root, criteria=_criteria(), output_path=output)


def test_finalize_reports_promising_without_authority(tmp_path: Path):
    prepare_path, cards_root, prepared = _prepare_and_write_cards(tmp_path)
    report = finalize_distillation(
        prepare_path,
        package_root=cards_root.parent / "package",
        criteria=_criteria(),
        cards_root=cards_root,
        output_path=tmp_path / "review.json",
    )
    assert report["promotion_status"] == "provisional_only"
    assert report["automatic_publication_authority"] is False
    assert report["verification_state"] == "promising"
    assert report["positive_candidates"][0]["supporting_qualified_samples"]
    assert report["coverage_gaps"] == []


def test_finalize_writes_schema_validated_report(tmp_path: Path):
    prepare_path, cards_root, _ = _prepare_and_write_cards(tmp_path)
    report = finalize_distillation(
        prepare_path,
        package_root=cards_root.parent / "package",
        criteria=_criteria(),
        cards_root=cards_root,
        output_path=tmp_path / "review.json",
    )
    from jsonschema import Draft202012Validator, FormatChecker

    schema = json.loads(
        (Path(__file__).parents[1] / "schemas" / "viral-research-distillation-report.json").read_text(
            encoding="utf-8"
        )
    )
    assert list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(report)) == []


def test_finalize_requires_the_original_package_and_digest_binding(tmp_path: Path):
    prepare_path, cards_root, prepared = _prepare_and_write_cards(tmp_path)
    prepared["package_run_id"] = "forged-run"
    forged_prepare = tmp_path / "forged-prepare.json"
    forged_prepare.write_text(json.dumps(prepared), encoding="utf-8")

    with pytest.raises(ViralResearchDistillError, match="prepared_package_run_id_mismatch"):
        finalize_distillation(
            forged_prepare,
            package_root=cards_root.parent / "package",
            criteria=_criteria(),
            cards_root=cards_root,
            output_path=tmp_path / "report.json",
        )

    (cards_root.parent / "package").rename(cards_root.parent / "package-missing")
    with pytest.raises(ViralResearchDistillError, match="package_integrity_failed"):
        finalize_distillation(
            prepare_path,
            package_root=cards_root.parent / "package",
            criteria=_criteria(),
            cards_root=cards_root,
            output_path=tmp_path / "report-missing-package.json",
        )


def test_finalize_requires_a_bound_card_batch_manifest(tmp_path: Path):
    prepare_path, cards_root, _ = _prepare_and_write_cards(tmp_path)
    (cards_root / "manifest.json").unlink()
    with pytest.raises(ViralResearchDistillError, match="card_batch_manifest_unavailable"):
        finalize_distillation(
            prepare_path,
            package_root=cards_root.parent / "package",
            criteria=_criteria(),
            cards_root=cards_root,
            output_path=tmp_path / "report.json",
        )


def test_finalize_rejects_missing_snapshot_or_performance_ref(tmp_path: Path):
    prepare_path, cards_root, prepared = _prepare_and_write_cards(tmp_path)
    card_path = cards_root / prepared["selected"][0]["card_ref"]
    card = json.loads(card_path.read_text())
    card["snapshot_ref"] = "clean/missing.md#sha256=" + "a" * 64
    card_path.write_text(json.dumps(card), encoding="utf-8")
    with pytest.raises(ViralResearchDistillError, match="card_batch_manifest_mismatch"):
        finalize_distillation(
            prepare_path,
            package_root=cards_root.parent / "package",
            criteria=_criteria(),
            cards_root=cards_root,
            output_path=tmp_path / "report.json",
        )


def test_finalize_rejects_semantic_card_account_mismatch(tmp_path: Path):
    prepare_path, cards_root, prepared = _prepare_and_write_cards(tmp_path)
    selected = prepared["selected"][0]
    card_path = cards_root / selected["card_ref"]
    card = json.loads(card_path.read_text(encoding="utf-8"))
    card["account_id"] = "unexpected-account"
    card_path.write_text(json.dumps(card), encoding="utf-8")

    with pytest.raises(ViralResearchDistillError, match="card_batch_manifest_mismatch"):
        finalize_distillation(
            prepare_path,
            package_root=cards_root.parent / "package",
            criteria=_criteria(),
            cards_root=cards_root,
            output_path=tmp_path / "report.json",
        )


def test_finalize_rejects_semantic_card_platform_mismatch(tmp_path: Path):
    prepare_path, cards_root, prepared = _prepare_and_write_cards(tmp_path)
    selected = prepared["selected"][0]
    card_path = cards_root / selected["card_ref"]
    card = json.loads(card_path.read_text(encoding="utf-8"))
    card["platform"] = "toutiao"
    card_path.write_text(json.dumps(card), encoding="utf-8")

    with pytest.raises(ViralResearchDistillError, match="card_batch_manifest_mismatch"):
        finalize_distillation(
            prepare_path,
            package_root=cards_root.parent / "package",
            criteria=_criteria(),
            cards_root=cards_root,
            output_path=tmp_path / "report.json",
        )


@pytest.mark.parametrize(
    ("tampered_snapshot_ref", "expected_error"),
    [
        ("../outside.md#sha256=" + "a" * 64, "prepared_selection_mismatch"),
        ("clean/a-0.md#sha256=" + "0" * 64, "prepared_selection_mismatch"),
    ],
)
def test_finalize_revalidates_selected_and_card_evidence_refs(
    tmp_path: Path,
    tampered_snapshot_ref: str,
    expected_error: str,
):
    prepare_path, cards_root, prepared = _prepare_and_write_cards(tmp_path)
    selected = prepared["selected"][0]
    selected["snapshot_ref"] = tampered_snapshot_ref
    card_path = cards_root / selected["card_ref"]
    card = json.loads(card_path.read_text(encoding="utf-8"))
    card["snapshot_ref"] = tampered_snapshot_ref
    card_path.write_text(json.dumps(card), encoding="utf-8")
    tampered_prepare_path = tmp_path / f"prepared-{expected_error}.json"
    tampered_prepare_path.write_text(json.dumps(prepared), encoding="utf-8")

    with pytest.raises(ViralResearchDistillError, match=expected_error):
        finalize_distillation(
            tampered_prepare_path,
            package_root=cards_root.parent / "package",
            criteria=_criteria(),
            cards_root=cards_root,
            output_path=tmp_path / f"report-{expected_error}.json",
        )


def test_finalize_excludes_observed_pending_from_positive_frequency(tmp_path: Path):
    prepare_path, cards_root, prepared = _prepare_and_write_cards(tmp_path)
    pending = copy.deepcopy(prepared["selected"][0])
    pending["sample_id"] = "pending-extra"
    pending["card_ref"] = "pending-extra.json"
    prepared["selected"].append(pending)
    prepared["selected_sample_ids"].append("pending-extra")
    pending_card = _semantic_card(
        "pending-extra", pending, status="observed_pending", account_id=pending["account_id"]
    )
    (cards_root / pending["card_ref"]).write_text(json.dumps(pending_card), encoding="utf-8")
    prepared_path = tmp_path / "prepared-with-pending.json"
    prepared_path.write_text(json.dumps(prepared), encoding="utf-8")
    with pytest.raises(ViralResearchDistillError, match="prepared_selection_mismatch"):
        finalize_distillation(
            prepared_path,
            package_root=cards_root.parent / "package",
            criteria=_criteria(),
            cards_root=cards_root,
            output_path=tmp_path / "report.json",
        )


def test_one_account_technique_is_excluded_not_positive(tmp_path: Path):
    prepare_path, cards_root, prepared = _prepare_and_write_cards(tmp_path)
    for selected in prepared["selected"]:
        selected["account_id"] = "same-account"
        path = cards_root / selected["card_ref"]
        card = json.loads(path.read_text())
        card["account_id"] = "same-account"
        path.write_text(json.dumps(card), encoding="utf-8")
    prepared_path = tmp_path / "prepared-one-account.json"
    prepared_path.write_text(json.dumps(prepared), encoding="utf-8")
    with pytest.raises(ViralResearchDistillError, match="prepared_selection_mismatch"):
        finalize_distillation(
            prepared_path,
            package_root=cards_root.parent / "package",
            criteria=_criteria(),
            cards_root=cards_root,
            output_path=tmp_path / "report.json",
        )


def test_research_only_observations_are_not_positive(tmp_path: Path):
    prepare_path, cards_root, prepared = _prepare_and_write_cards(tmp_path)
    for selected in prepared["selected"]:
        path = cards_root / selected["card_ref"]
        card = json.loads(path.read_text())
        card["qualification_status"] = "research_only"
        card["metrics"] = []
        path.write_text(json.dumps(card), encoding="utf-8")
    with pytest.raises(ViralResearchDistillError, match="card_batch_manifest_mismatch"):
        finalize_distillation(
            prepare_path,
            package_root=cards_root.parent / "package",
            criteria=_criteria(),
            cards_root=cards_root,
            output_path=tmp_path / "report.json",
        )


def test_inflated_qualification_status_is_rejected(tmp_path: Path):
    prepare_path, cards_root, prepared = _prepare_and_write_cards(tmp_path)
    path = cards_root / prepared["selected"][0]["card_ref"]
    card = json.loads(path.read_text())
    card["metrics"][0]["value"] = 1
    path.write_text(json.dumps(card), encoding="utf-8")
    with pytest.raises(ViralResearchDistillError, match="card_batch_manifest_mismatch"):
        finalize_distillation(
            prepare_path,
            package_root=cards_root.parent / "package",
            criteria=_criteria(),
            cards_root=cards_root,
            output_path=tmp_path / "report.json",
        )


@pytest.mark.parametrize("evidence_field", ["client_evidence", "metric"])
def test_finalize_scans_semantic_card_evidence_files(
    tmp_path: Path, evidence_field: str
):
    prepare_path, cards_root, prepared = _prepare_and_write_cards(tmp_path)
    unsafe_path = tmp_path / "unsafe-evidence.json"
    unsafe_path.write_text('{"token":"SECRET"}', encoding="utf-8")
    unsafe_digest = hashlib.sha256(unsafe_path.read_bytes()).hexdigest()
    unsafe_ref = f"unsafe-evidence.json#sha256={unsafe_digest}"

    selected = prepared["selected"][0]
    card_path = cards_root / selected["card_ref"]
    card = json.loads(card_path.read_text(encoding="utf-8"))
    if evidence_field == "client_evidence":
        card["client_evidence"]["evidence_ref"] = unsafe_ref
        card["client_evidence"]["sha256"] = unsafe_digest
    else:
        card["metrics"][0]["evidence_ref"] = unsafe_ref
    card_path.write_text(json.dumps(card), encoding="utf-8")

    batch_path = cards_root / "manifest.json"
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    batch["cards"][0]["sha256"] = hashlib.sha256(card_path.read_bytes()).hexdigest()
    batch_path.write_text(json.dumps(batch, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    with pytest.raises(ViralResearchDistillError, match="card_.*evidence_scan_failed"):
        finalize_distillation(
            prepare_path,
            package_root=cards_root.parent / "package",
            criteria=_criteria(),
            cards_root=cards_root,
            output_path=tmp_path / "report.json",
        )


def test_finalize_refuses_overwrite(tmp_path: Path):
    prepare_path, cards_root, _ = _prepare_and_write_cards(tmp_path)
    output = tmp_path / "report.json"
    finalize_distillation(
        prepare_path,
        package_root=cards_root.parent / "package",
        criteria=_criteria(),
        cards_root=cards_root,
        output_path=output,
    )
    with pytest.raises(ViralResearchDistillError, match="artifact_exists"):
        finalize_distillation(
            prepare_path,
            package_root=cards_root.parent / "package",
            criteria=_criteria(),
            cards_root=cards_root,
            output_path=output,
        )


def test_cli_help_is_available(capsys):
    from scripts.codex_viral_distill import main
    try:
        main(["--help"])
    except SystemExit as error:
        assert error.code == 0
    assert "prepare" in capsys.readouterr().out
