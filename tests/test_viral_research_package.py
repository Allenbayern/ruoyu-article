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
from scripts.codex_viral_research_package import main as package_cli


def _ref(root: Path, relative: str, content: str) -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return relative


def _capture(
    root: Path,
    *,
    lane: str = "wechat_long_form",
    capture_status: str = "full",
    qualification_status: str = "qualified_viral",
    include_clean: bool = True,
    content_domain: str = "film",
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
    assert not (output / "raw").exists()
    assert validate_package_root(output)["status"] == "evidence_checked"


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
