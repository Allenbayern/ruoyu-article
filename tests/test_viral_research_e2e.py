from __future__ import annotations

import json
import hashlib
import shutil
from pathlib import Path

import pytest

from article_group.viral_research_contract import validate_local_ref
from article_group.viral_research_distill import ViralResearchDistillError, finalize_distillation, prepare_distill_input
from article_group.viral_research_package import build_package
from article_group.viral_research_selection import SelectionCriteria

FIXTURE_CAPTURE = Path(__file__).parent / "fixtures" / "viral_research" / "capture"


def test_readme_documents_canonical_viral_research_run_root_layout():
    readme = (Path(__file__).resolve().parents[1] / "README.zh-CN.md").read_text(
        encoding="utf-8"
    )

    assert "RUN_ROOT=runs/<run-id>\n" in readme
    assert "RUN_ROOT=runs/<run-id>/viral-research" not in readme
    assert '--output-root "$RUN_ROOT/viral-research/package"' in readme
    assert '--package-root "$RUN_ROOT/viral-research/package"' in readme
    assert '--cards-root "$RUN_ROOT/viral-research/cards"' in readme


def _run_root(tmp_path: Path) -> Path:
    run_root = tmp_path / "run"
    shutil.copytree(FIXTURE_CAPTURE, run_root)
    return run_root


def _criteria() -> SelectionCriteria:
    return SelectionCriteria(platform="wechat", medium="long_form", content_domain="film", narrative_purpose="review_or_analysis")


def _card(selected: dict) -> dict:
    sample_id = selected["sample_id"]
    evidence_ref = selected["performance_evidence_ref"]
    evidence_digest = evidence_ref.rsplit("#sha256=", 1)[1]
    return {
        "sample_id": sample_id, "platform": selected["platform"],
        "evidence_domain": "competitive_research_evidence", "evidence_origin": "client",
        "account_id": selected["account_id"], "subject_category": "film",
        "snapshot_ref": selected["snapshot_ref"], "performance_evidence_ref": selected["performance_evidence_ref"],
        "metric_plan_version": "fixture-v1", "metric_plan_frozen_at": "2026-08-25T08:00:00+08:00",
        "client_evidence": {"evidence_ref": evidence_ref, "original_display": "synthetic views",
                            "observed_at": "2026-08-25T10:00:00+08:00", "confirmer": "fixture-reviewer",
                            "sha256": evidence_digest, "sanitized": True},
        "metric_plan": [{"metric": "view", "visible": True, "required": True}],
        "metrics": [{"metric": "view", "value": 200000, "status": "observed", "source": "fixture_client",
                     "observed_at": "2026-08-25T10:00:00+08:00", "evidence_ref": evidence_ref}],
        "threshold_or_rank_rule": {"version": "fixture-rule-v1", "frozen_at": "2026-08-25T08:00:00+08:00",
                                   "platform": "wechat", "baseline": "fixture", "window": "publication",
                                   "rule": "gte", "minimums": {"view": 100000}},
        "qualification_reason": "synthetic evidence only", "qualification_status": "qualified_viral",
        "technique_observations": [{"technique": "栏目化标题", "technique_type": "title"}],
    }


def _build_and_prepare(tmp_path: Path) -> tuple[Path, Path, Path]:
    run_root = _run_root(tmp_path)
    package_root = run_root / "viral-research" / "package"
    package = build_package(run_root / "manifest.json", run_root=run_root, output_root=package_root)
    assert package["status"] in {"evidence_checked", "observed_pending", "research_only"}
    prepare_path = run_root / "viral-research" / "distillation" / "prepare.json"
    prepared = prepare_distill_input(package_root, criteria=_criteria(), output_path=prepare_path)
    assert len(prepared["selected"]) == 5
    cards_root = run_root / "viral-research" / "cards"
    cards_root.mkdir(parents=True)
    for selected in prepared["selected"]:
        (cards_root / selected["card_ref"]).write_text(json.dumps(_card(selected), ensure_ascii=False), encoding="utf-8")
    (cards_root / "manifest.json").write_text(
        json.dumps(
            {
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
                        "sample_id": item["sample_id"],
                        "card_ref": item["card_ref"],
                        "sha256": hashlib.sha256(
                            (cards_root / item["card_ref"]).read_bytes()
                        ).hexdigest(),
                    }
                    for item in prepared["selected"]
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return run_root, prepare_path, cards_root


def test_fixture_runs_package_prepare_finalize_with_provisional_boundary(tmp_path: Path):
    run_root, prepare_path, cards_root = _build_and_prepare(tmp_path)
    report_path = run_root / "viral-research" / "review" / "viral-distill-review.json"
    report = finalize_distillation(
        prepare_path,
        package_root=run_root / "viral-research" / "package",
        criteria=_criteria(),
        cards_root=cards_root,
        output_path=report_path,
    )
    assert report["promotion_status"] == "provisional_only"
    assert report["automatic_publication_authority"] is False
    assert report["coverage_gaps"] == []
    serialized = json.dumps(report, ensure_ascii=False).lower()
    assert "total" not in serialized and "sum(" not in serialized
    assert "token" not in serialized and "cookie" not in serialized and "session" not in serialized and "vault" not in serialized
    for selected in json.loads(prepare_path.read_text())["selected"]:
        validate_local_ref(selected["snapshot_ref"], root=run_root)
        validate_local_ref(selected["performance_evidence_ref"], root=run_root)


def test_fixture_revision_is_not_counted_as_second_selected_sample(tmp_path: Path):
    _, prepare_path, _ = _build_and_prepare(tmp_path)
    prepared = json.loads(prepare_path.read_text())
    assert len(prepared["selected_sample_ids"]) == len(set(prepared["selected_sample_ids"]))


def test_missing_clean_snapshot_fails_closed(tmp_path: Path):
    run_root = _run_root(tmp_path)
    (run_root / "clean" / "sample-001.md").unlink()
    package = build_package(run_root / "manifest.json", run_root=run_root, output_root=run_root / "viral-research" / "package")
    assert package["status"] == "blocked"
    assert any("missing_ref" in error or "capture_ref_missing" in error for error in package["errors"])


def test_changed_body_after_manifest_creation_fails_hash_gate(tmp_path: Path):
    run_root = _run_root(tmp_path)
    (run_root / "clean" / "sample-001.md").write_text("changed", encoding="utf-8")
    package = build_package(run_root / "manifest.json", run_root=run_root, output_root=run_root / "viral-research" / "package")
    assert package["status"] == "blocked"
    assert "sha256_mismatch" in json.dumps(package)


def test_reference_outside_run_root_fails_closed(tmp_path: Path):
    run_root = _run_root(tmp_path)
    manifest_path = run_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["samples"][0]["clean_ref"] = "../outside.md#sha256=" + "a" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    package = build_package(manifest_path, run_root=run_root, output_root=run_root / "viral-research" / "package")
    assert package["status"] == "blocked"
    assert "path_escape" in json.dumps(package)


def test_fewer_than_five_selected_samples_refuses_prepare(tmp_path: Path):
    run_root = _run_root(tmp_path)
    manifest_path = run_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["samples"] = [item for item in manifest["samples"] if item["canonical_url"].endswith(("/001", "/002", "/003", "/pending"))]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    package_root = run_root / "viral-research" / "package"
    build_package(manifest_path, run_root=run_root, output_root=package_root)
    with pytest.raises(ViralResearchDistillError, match="insufficient_qualified_samples"):
        prepare_distill_input(package_root, criteria=_criteria(), output_path=run_root / "viral-research" / "distillation" / "prepare.json")


def test_inflated_semantic_card_fails_finalize(tmp_path: Path):
    _, prepare_path, cards_root = _build_and_prepare(tmp_path)
    card_path = next(path for path in cards_root.glob("*.json") if path.name != "manifest.json")
    card = json.loads(card_path.read_text())
    card["metrics"][0]["value"] = 1
    card_path.write_text(json.dumps(card), encoding="utf-8")
    with pytest.raises(ViralResearchDistillError, match="card_batch_manifest_mismatch"):
        finalize_distillation(
            prepare_path,
            package_root=cards_root.parent / "package",
            criteria=_criteria(),
            cards_root=cards_root,
            output_path=cards_root.parent / "review" / "report.json",
        )
