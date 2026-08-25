from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from article_group.viral_research_distill import (
    ViralResearchDistillError,
    finalize_distillation,
    prepare_distill_input,
)
from article_group.viral_research_package import build_package
from article_group.viral_research_selection import SelectionCriteria


def _build_package(tmp_path: Path, count: int = 5) -> Path:
    for folder in ("raw", "clean", "metadata"):
        (tmp_path / folder).mkdir()
    samples = []
    for index in range(count):
        (tmp_path / "raw" / f"a-{index}.html").write_text(f"<html>{index}</html>", encoding="utf-8")
        (tmp_path / "clean" / f"a-{index}.md").write_text(f"# article {index}", encoding="utf-8")
        (tmp_path / "metadata" / f"a-{index}.json").write_text("{}", encoding="utf-8")
        samples.append({
            "platform": "wechat", "account_id": f"acct-{index % 3}",
            "title": f"Film case {index}", "canonical_url": f"https://example.com/article/{index}",
            "published_at": f"2026-08-25T09:{index:02d}:00+08:00", "capture_status": "full",
            "raw_ref": f"raw/a-{index}.html", "clean_ref": f"clean/a-{index}.md",
            "metadata_ref": f"metadata/a-{index}.json",
            "shape": {"medium": "long_form", "content_domain": "film", "narrative_purpose": "review_or_analysis"},
            "qualification_status": "qualified_viral", "source_lane": "wechat_long_form",
        })
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
    if status == "research_only":
        metrics = []
    elif status == "observed_pending":
        metrics = [{"metric": "view", "value": 50_000, "status": "observed", "source": "client_dashboard",
                    "observed_at": "2026-08-25T10:00:00+08:00", "evidence_ref": f"metrics/{sample_id}.json"}]
    else:
        metrics = [{"metric": "view", "value": 200_000, "status": "observed", "source": "client_dashboard",
                    "observed_at": "2026-08-25T10:00:00+08:00", "evidence_ref": f"metrics/{sample_id}.json"}]
    return {
        "sample_id": sample_id, "evidence_domain": "competitive_research_evidence", "evidence_origin": "client",
        "account_id": account_id or f"account-{sample_id}", "subject_category": "film",
        "snapshot_ref": selected["snapshot_ref"], "performance_evidence_ref": selected["performance_evidence_ref"],
        "metric_plan_version": "article-metric-v0", "metric_plan_frozen_at": "2026-08-25T08:00:00+08:00",
        "client_evidence": {"evidence_ref": f"evidence/{sample_id}.json", "original_display": "200000 views",
                            "observed_at": "2026-08-25T10:00:00+08:00", "confirmer": "reviewer-1",
                            "sha256": "3" * 64, "sanitized": True},
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
        card = _semantic_card(selected["sample_id"], selected)
        (cards_root / selected["card_ref"]).write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    return prepare_path, cards_root, prepared


def test_prepare_refuses_fewer_than_five_usable_samples(tmp_path: Path):
    package_root = _build_package(tmp_path, count=4)
    with pytest.raises(ViralResearchDistillError, match="insufficient_qualified_samples"):
        prepare_distill_input(package_root, criteria=_criteria(), output_path=tmp_path / "prepare.json")


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


def test_finalize_reports_promising_without_authority(tmp_path: Path):
    prepare_path, cards_root, prepared = _prepare_and_write_cards(tmp_path)
    report = finalize_distillation(prepare_path, cards_root=cards_root, output_path=tmp_path / "review.json")
    assert report["promotion_status"] == "provisional_only"
    assert report["automatic_publication_authority"] is False
    assert report["verification_state"] == "promising"
    assert report["positive_candidates"][0]["supporting_qualified_samples"]
    assert report["coverage_gaps"] == []


def test_finalize_rejects_missing_snapshot_or_performance_ref(tmp_path: Path):
    prepare_path, cards_root, prepared = _prepare_and_write_cards(tmp_path)
    card_path = cards_root / prepared["selected"][0]["card_ref"]
    card = json.loads(card_path.read_text())
    card["snapshot_ref"] = "clean/missing.md#sha256=" + "a" * 64
    card_path.write_text(json.dumps(card), encoding="utf-8")
    with pytest.raises(ViralResearchDistillError, match="card_evidence_ref_mismatch"):
        finalize_distillation(prepare_path, cards_root=cards_root, output_path=tmp_path / "report.json")


def test_finalize_excludes_observed_pending_from_positive_frequency(tmp_path: Path):
    prepare_path, cards_root, prepared = _prepare_and_write_cards(tmp_path)
    pending = copy.deepcopy(prepared["selected"][0])
    pending["sample_id"] = "pending-extra"
    pending["card_ref"] = "pending-extra.json"
    prepared["selected"].append(pending)
    prepared["selected_sample_ids"].append("pending-extra")
    pending_card = _semantic_card("pending-extra", pending, status="observed_pending")
    (cards_root / pending["card_ref"]).write_text(json.dumps(pending_card), encoding="utf-8")
    prepared_path = tmp_path / "prepared-with-pending.json"
    prepared_path.write_text(json.dumps(prepared), encoding="utf-8")
    report = finalize_distillation(prepared_path, cards_root=cards_root, output_path=tmp_path / "report.json")
    candidate = report["positive_candidates"][0]
    assert candidate["frequency"] == 5
    assert any(item["sample_id"] == "pending-extra" for item in candidate["excluded_observations"])


def test_one_account_technique_is_excluded_not_positive(tmp_path: Path):
    prepare_path, cards_root, prepared = _prepare_and_write_cards(tmp_path)
    for selected in prepared["selected"]:
        path = cards_root / selected["card_ref"]
        card = json.loads(path.read_text())
        card["account_id"] = "same-account"
        path.write_text(json.dumps(card), encoding="utf-8")
    report = finalize_distillation(prepare_path, cards_root=cards_root, output_path=tmp_path / "report.json")
    assert report["positive_candidates"] == []
    assert any(item["reason"] == "insufficient_cross_account_support" for item in report["excluded_observations"])


def test_research_only_observations_are_not_positive(tmp_path: Path):
    prepare_path, cards_root, prepared = _prepare_and_write_cards(tmp_path)
    for selected in prepared["selected"]:
        path = cards_root / selected["card_ref"]
        card = json.loads(path.read_text())
        card["qualification_status"] = "research_only"
        card["metrics"] = []
        path.write_text(json.dumps(card), encoding="utf-8")
    report = finalize_distillation(prepare_path, cards_root=cards_root, output_path=tmp_path / "report.json")
    assert report["positive_candidates"] == []
    assert report["excluded_observations"]


def test_inflated_qualification_status_is_rejected(tmp_path: Path):
    prepare_path, cards_root, prepared = _prepare_and_write_cards(tmp_path)
    path = cards_root / prepared["selected"][0]["card_ref"]
    card = json.loads(path.read_text())
    card["metrics"][0]["value"] = 1
    path.write_text(json.dumps(card), encoding="utf-8")
    with pytest.raises(ViralResearchDistillError, match="case_contract_failed"):
        finalize_distillation(prepare_path, cards_root=cards_root, output_path=tmp_path / "report.json")


def test_finalize_refuses_overwrite(tmp_path: Path):
    prepare_path, cards_root, _ = _prepare_and_write_cards(tmp_path)
    output = tmp_path / "report.json"
    finalize_distillation(prepare_path, cards_root=cards_root, output_path=output)
    with pytest.raises(ViralResearchDistillError, match="artifact_exists"):
        finalize_distillation(prepare_path, cards_root=cards_root, output_path=output)


def test_cli_help_is_available(capsys):
    from scripts.codex_viral_distill import main
    try:
        main(["--help"])
    except SystemExit as error:
        assert error.code == 0
    assert "prepare" in capsys.readouterr().out
