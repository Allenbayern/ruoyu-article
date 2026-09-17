from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from article_group.viral_research_package import (
    ViralResearchPackageError,
    build_package,
    validate_package_root,
)
from article_group.viral_research_contract import normalize_sample_id
from scripts.codex_viral_research_package import main as package_cli


def _ref(root: Path, relative: str, content: str) -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return relative


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
        "snapshot_ref": sample.get("clean_ref", "clean/missing.md"),
        "performance_evidence_ref": sample["metadata_ref"],
        "metric_plan_version": "fixture-v1",
        "metric_plan_frozen_at": "2026-08-25T08:00:00+08:00",
        "client_evidence": {
            "evidence_ref": "metadata/article.json#sha256=" + hashlib.sha256(b'{"views": 100}').hexdigest(),
            "original_display": "100000 views",
            "observed_at": "2026-08-25T09:00:00+08:00",
            "confirmer": "fixture-reviewer",
            "sha256": hashlib.sha256(b'{"views": 100}').hexdigest(),
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
                "evidence_ref": "metadata/article.json",
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


def _capture(
    root: Path,
    *,
    lane: str = "wechat_long_form",
    capture_status: str = "full",
    qualification_status: str = "qualified_viral",
    include_clean: bool = True,
    content_domain: str = "film",
    include_case_contract: bool = True,
) -> Path:
    raw_ref = _ref(root, "raw/article.html", "<html>article</html>")
    metadata_ref = _ref(root, "metadata/article.json", '{"views": 100}')
    sample = {
        "platform": "wechat",
        "account_id": "account-001",
        "title": "A film article",
        "canonical_url": "https://example.com/article/1",
        "published_at": "2026-08-25T09:00:00+08:00",
        "capture_status": capture_status,
        "raw_ref": raw_ref,
        "metadata_ref": metadata_ref,
        "shape": {"medium": "long_form", "content_domain": content_domain},
        "qualification_status": qualification_status,
        "source_lane": lane,
    }
    if include_clean:
        sample["clean_ref"] = _ref(root, "clean/article.md", "# article")
    if qualification_status == "qualified_viral" and include_case_contract:
        sample["case_contract_card"] = _case_contract_card(sample)
    capture = {
        "run_id": "run-20260825-001",
        "created_at": "2026-08-25T09:05:00+08:00",
        "source_lanes": [lane],
        "samples": [sample],
    }
    path = root / "capture-manifest.json"
    path.write_text(json.dumps(capture, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_full_capture_builds_evidence_checked_package_without_body_copy(tmp_path: Path):
    capture = _capture(tmp_path)
    output = tmp_path / "viral-research" / "package"
    manifest = build_package(capture, run_root=tmp_path, output_root=output)

    assert manifest["status"] == "evidence_checked"
    assert len(manifest["samples"]) == 1
    assert (output / "manifest.json").is_file()
    assert (output / "samples.jsonl").is_file()
    assert (output / "exclusions.jsonl").is_file()
    assert (output / "integrity.json").is_file()
    assert not (output / "raw").exists()
    assert validate_package_root(output)["status"] == "evidence_checked"
    sample = manifest["samples"][0]
    qualification = sample["qualification_evidence"]
    assert qualification["sample_id"] == sample["sample_id"]
    assert qualification["account_id"] == sample["account_id"]
    assert qualification["snapshot_ref"] == sample["clean_ref"]
    assert qualification["performance_evidence_ref"] == sample["metadata_ref"]


def test_qualification_status_alone_cannot_qualify_without_case_contract_evidence(tmp_path: Path):
    capture = _capture(
        tmp_path,
        qualification_status="qualified_viral",
        include_case_contract=False,
    )
    manifest = build_package(
        capture,
        run_root=tmp_path,
        output_root=tmp_path / "viral-research" / "package",
    )

    assert all(
        sample["qualification_status"] != "qualified_viral"
        for sample in manifest["samples"]
    )
    assert manifest["status"] != "evidence_checked"


@pytest.mark.parametrize("payload", [
    '{"authorization":"should-not-enter-package","views":100}',
    '{"authority":{"promotion_status":"promising"},"views":100}',
])
def test_capture_client_evidence_is_scanned_before_qualification(
    tmp_path: Path, payload: str
):
    capture = _capture(tmp_path)
    metadata = tmp_path / "metadata" / "article.json"
    metadata.write_text(payload, encoding="utf-8")
    data = json.loads(capture.read_text(encoding="utf-8"))
    digest = hashlib.sha256(metadata.read_bytes()).hexdigest()
    card = data["samples"][0]["case_contract_card"]
    card["client_evidence"]["evidence_ref"] = f"metadata/article.json#sha256={digest}"
    card["client_evidence"]["sha256"] = digest
    capture.write_text(json.dumps(data), encoding="utf-8")

    manifest = build_package(
        capture,
        run_root=tmp_path,
        output_root=tmp_path / "viral-research" / "package",
    )

    assert manifest["samples"][0]["qualification_status"] != "qualified_viral"


@pytest.mark.parametrize(
    ("field", "value"),
    [("account_id", "other-account"), ("snapshot_ref", "clean/other.md")],
)
def test_mismatched_case_contract_cannot_qualify(tmp_path: Path, field: str, value: str):
    capture = _capture(tmp_path)
    data = json.loads(capture.read_text(encoding="utf-8"))
    data["samples"][0]["case_contract_card"][field] = value
    capture.write_text(json.dumps(data), encoding="utf-8")

    manifest = build_package(
        capture,
        run_root=tmp_path,
        output_root=tmp_path / "viral-research" / "package",
    )

    assert manifest["samples"][0]["qualification_status"] != "qualified_viral"


def test_case_contract_platform_mismatch_cannot_qualify(tmp_path: Path):
    capture = _capture(tmp_path)
    data = json.loads(capture.read_text(encoding="utf-8"))
    data["samples"][0]["case_contract_card"]["threshold_or_rank_rule"]["platform"] = "toutiao"
    capture.write_text(json.dumps(data), encoding="utf-8")

    manifest = build_package(
        capture,
        run_root=tmp_path,
        output_root=tmp_path / "viral-research" / "package",
    )

    assert manifest["samples"][0]["qualification_status"] != "qualified_viral"


def test_source_lane_cannot_upgrade_non_wechat_platform(tmp_path: Path):
    capture = _capture(tmp_path)
    data = json.loads(capture.read_text(encoding="utf-8"))
    sample = data["samples"][0]
    sample["platform"] = "toutiao"
    sample["case_contract_card"]["threshold_or_rank_rule"]["platform"] = "toutiao"
    capture.write_text(json.dumps(data), encoding="utf-8")

    manifest = build_package(
        capture,
        run_root=tmp_path,
        output_root=tmp_path / "viral-research" / "package",
    )

    assert manifest["samples"][0]["qualification_status"] != "qualified_viral"


def test_package_without_persisted_qualification_evidence_is_rejected(tmp_path: Path):
    capture = _capture(tmp_path)
    package_root = tmp_path / "viral-research" / "package"
    build_package(capture, run_root=tmp_path, output_root=package_root)

    manifest_path = package_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["samples"][0].pop("qualification_evidence")
    samples = [json.loads(line) for line in (package_root / "samples.jsonl").read_text(encoding="utf-8").splitlines()]
    samples[0].pop("qualification_evidence")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (package_root / "samples.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in samples),
        encoding="utf-8",
    )

    with pytest.raises(ViralResearchPackageError, match="integrity|qualification"):
        validate_package_root(package_root)


def test_package_integrity_rejects_manifest_status_tamper(tmp_path: Path):
    capture = _capture(tmp_path)
    package_root = tmp_path / "viral-research" / "package"
    build_package(capture, run_root=tmp_path, output_root=package_root)
    manifest_path = package_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["status"] = "research_only"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ViralResearchPackageError, match="package_integrity_mismatch"):
        validate_package_root(package_root)


def test_package_status_must_match_recomputed_sample_state(tmp_path: Path):
    capture = _capture(tmp_path)
    package_root = tmp_path / "viral-research" / "package"
    build_package(capture, run_root=tmp_path, output_root=package_root)
    manifest_path = package_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["status"] = "research_only"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    integrity_path = package_root / "integrity.json"
    integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
    integrity["manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    integrity_path.write_text(
        json.dumps(integrity, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ViralResearchPackageError, match="package_status_mismatch"):
        validate_package_root(package_root)


def test_package_rejects_exclusions_ref_to_another_file(tmp_path: Path):
    capture = _capture(tmp_path)
    package_root = tmp_path / "viral-research" / "package"
    build_package(capture, run_root=tmp_path, output_root=package_root)
    decoy = tmp_path / "decoy.jsonl"
    decoy.write_text("{\"not\":\"the package exclusions\"}\n", encoding="utf-8")
    manifest_path = package_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["exclusions_ref"] = (
        "decoy.jsonl#sha256=" + hashlib.sha256(decoy.read_bytes()).hexdigest()
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    integrity_path = package_root / "integrity.json"
    integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
    integrity["manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    integrity_path.write_text(
        json.dumps(integrity, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ViralResearchPackageError, match="exclusions_ref_mismatch"):
        validate_package_root(package_root)


def test_named_capture_revision_is_preserved_in_valid_package(tmp_path: Path):
    capture = _capture(tmp_path)
    data = json.loads(capture.read_text(encoding="utf-8"))
    data["samples"][0]["revision_id"] = "crawl-2026-08-25-a"
    capture.write_text(json.dumps(data), encoding="utf-8")

    manifest = build_package(
        capture,
        run_root=tmp_path,
        output_root=tmp_path / "viral-research" / "package",
    )

    assert manifest["status"] == "evidence_checked"
    assert manifest["samples"][0]["revision_id"] == "crawl-2026-08-25-a"


def test_missing_clean_snapshot_is_blocked_with_machine_error(tmp_path: Path):
    capture = _capture(tmp_path, include_clean=False)
    manifest = build_package(
        capture, run_root=tmp_path, output_root=tmp_path / "viral-research" / "package"
    )
    assert manifest["status"] == "blocked"
    assert any("capture_ref_missing" in error for error in manifest["errors"])
    exclusion_lines = (tmp_path / "viral-research" / "package" / "exclusions.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert any("capture_ref_missing" in line for line in exclusion_lines)


def test_existing_output_is_immutable(tmp_path: Path):
    capture = _capture(tmp_path)
    output = tmp_path / "viral-research" / "package"
    build_package(capture, run_root=tmp_path, output_root=output)
    before = (output / "manifest.json").read_bytes()
    with pytest.raises(ViralResearchPackageError, match="artifact_exists"):
        build_package(capture, run_root=tmp_path, output_root=output)
    assert (output / "manifest.json").read_bytes() == before


def test_output_root_must_stay_inside_run_root(tmp_path: Path):
    capture = _capture(tmp_path)
    with pytest.raises(ViralResearchPackageError, match="path_escape"):
        build_package(
            capture,
            run_root=tmp_path,
            output_root=tmp_path.parent / "outside-package",
        )


def test_newrank_discovery_without_full_text_is_research_only(tmp_path: Path):
    capture = _capture(
        tmp_path,
        lane="newrank_discovery",
        capture_status="discovery_only",
        qualification_status="research_only",
        include_clean=False,
    )
    data = json.loads(capture.read_text(encoding="utf-8"))
    data["samples"][0].pop("raw_ref")
    data["samples"][0].pop("metadata_ref")
    capture.write_text(json.dumps(data), encoding="utf-8")
    manifest = build_package(
        capture, run_root=tmp_path, output_root=tmp_path / "viral-research" / "package"
    )
    assert manifest["status"] == "research_only"
    assert manifest["samples"] == []
    assert "full_text_capture_missing" in (
        tmp_path / "viral-research" / "package" / "exclusions.jsonl"
    ).read_text(encoding="utf-8")


def test_non_film_record_is_written_to_exclusions(tmp_path: Path):
    capture = _capture(tmp_path, content_domain="gaming")
    manifest = build_package(
        capture, run_root=tmp_path, output_root=tmp_path / "viral-research" / "package"
    )
    assert manifest["status"] == "research_only"
    assert manifest["samples"] == []
    exclusions = (
        tmp_path / "viral-research" / "package" / "exclusions.jsonl"
    ).read_text(encoding="utf-8")
    assert "non_film_content" in exclusions


def test_duplicate_logical_identity_is_not_counted_twice(tmp_path: Path):
    capture = _capture(tmp_path)
    data = json.loads(capture.read_text(encoding="utf-8"))
    data["samples"].append(dict(data["samples"][0]))
    capture.write_text(json.dumps(data), encoding="utf-8")
    manifest = build_package(
        capture, run_root=tmp_path, output_root=tmp_path / "viral-research" / "package"
    )
    assert manifest["status"] == "blocked"
    assert "duplicate_sample_identity" in manifest["errors"][0]


def test_revision_is_kept_as_a_distinct_capture_revision(tmp_path: Path):
    capture = _capture(tmp_path)
    data = json.loads(capture.read_text(encoding="utf-8"))
    revised = dict(data["samples"][0])
    revised["revision"] = 2
    data["samples"].append(revised)
    capture.write_text(json.dumps(data), encoding="utf-8")
    manifest = build_package(
        capture, run_root=tmp_path, output_root=tmp_path / "viral-research" / "package"
    )
    assert manifest["status"] == "evidence_checked"
    assert len(manifest["samples"]) == 2


def test_cli_returns_zero_only_for_complete_package(tmp_path: Path, capsys):
    capture = _capture(tmp_path)
    output = tmp_path / "viral-research" / "package"
    assert (
        package_cli(
            [
                "--capture-manifest",
                str(capture),
                "--run-root",
                str(tmp_path),
                "--output-root",
                str(output),
            ]
        )
        == 0
    )
    assert '"status": "evidence_checked"' in capsys.readouterr().out


def test_cli_returns_two_for_incomplete_package(tmp_path: Path, capsys):
    capture = _capture(tmp_path, include_clean=False)
    output = tmp_path / "viral-research" / "package"
    assert (
        package_cli(
            [
                "--capture-manifest",
                str(capture),
                "--run-root",
                str(tmp_path),
                "--output-root",
                str(output),
            ]
        )
        == 2
    )
    assert "package_incomplete" in capsys.readouterr().out


def test_cli_argument_error_is_stable(capsys):
    with pytest.raises(SystemExit) as error:
        package_cli([])
    assert error.value.code == 2
    assert capsys.readouterr().err == "argument_error\n"
