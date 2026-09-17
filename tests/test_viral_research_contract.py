from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from article_group.viral_research_contract import (
    PACKAGE_SCHEMA_VERSION,
    ViralResearchContractError,
    assess_sample_state,
    normalize_sample_id,
    validate_local_ref,
    evidence_cluster_id,
    validate_package_manifest,
)


def _write_ref(root: Path, relative: str, content: str) -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"{relative}#sha256={digest}"


def valid_package_fixture(root: Path) -> dict:
    raw_ref = _write_ref(root, "raw/sample.html", "<html>raw</html>")
    clean_ref = _write_ref(root, "clean/sample.md", "# Clean")
    metadata_ref = _write_ref(root, "metadata/sample.json", '{"views": 10}')
    exclusions_ref = _write_ref(root, "exclusions.jsonl", "")
    published_at = "2026-08-25T10:00:00+08:00"
    sample = {
        "sample_id": normalize_sample_id(
            platform="wechat",
            account_id="acct-001",
            canonical_url="https://example.com/article/1",
            published_at=published_at,
        ),
        "platform": "wechat",
        "account_id": "acct-001",
        "title": "A qualified sample",
        "canonical_url": "https://example.com/article/1",
        "published_at": published_at,
        "capture_status": "complete",
        "raw_ref": raw_ref,
        "clean_ref": clean_ref,
        "metadata_ref": metadata_ref,
        "evidence_cluster": evidence_cluster_id(
            {"raw_ref": raw_ref, "clean_ref": clean_ref, "metadata_ref": metadata_ref}
        ),
        "shape": {
            "medium": "long_form",
            "content_domain": "film",
            "narrative_purpose": "review",
        },
        "qualification_status": "qualified_viral",
    }
    sample["qualification_evidence"] = {
        "sample_id": sample["sample_id"],
        "evidence_domain": "competitive_research_evidence",
        "evidence_origin": "client",
        "account_id": sample["account_id"],
        "subject_category": "film",
        "snapshot_ref": clean_ref,
        "performance_evidence_ref": metadata_ref,
        "metric_plan_version": "fixture-v1",
        "metric_plan_frozen_at": "2026-08-25T09:00:00+08:00",
        "client_evidence": {
            "evidence_ref": metadata_ref,
            "original_display": "100000 views",
            "observed_at": "2026-08-25T10:00:00+08:00",
            "confirmer": "fixture-reviewer",
            "sha256": metadata_ref.split("#sha256=", 1)[1],
            "sanitized": True,
        },
        "metric_plan": [{"metric": "view", "visible": True, "required": True}],
        "metrics": [{
            "metric": "view", "value": 100000, "status": "observed",
            "source": "fixture_client", "observed_at": "2026-08-25T10:00:00+08:00",
            "evidence_ref": metadata_ref,
        }],
        "threshold_or_rank_rule": {
            "version": "fixture-rule-v1", "frozen_at": "2026-08-25T09:00:00+08:00",
            "platform": "wechat", "baseline": "fixture", "window": "publication",
            "rule": "gte", "minimums": {"view": 100000},
        },
        "qualification_reason": "Synthetic fixture evidence meets the frozen rule.",
        "qualification_status": "qualified_viral",
    }
    return {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "run_id": "run-20260825-001",
        "status": "captured",
        "created_at": "2026-08-25T10:05:00+08:00",
        "source_lanes": ["wechat_long_form"],
        "samples": [sample],
        "exclusions_ref": exclusions_ref,
        "errors": [],
    }


def test_full_sample_with_local_hashed_refs_is_valid(tmp_path: Path):
    package = valid_package_fixture(tmp_path)
    assert validate_package_manifest(package, root=tmp_path) == "evidence_checked"


def test_reference_outside_run_root_is_rejected(tmp_path: Path):
    package = valid_package_fixture(tmp_path)
    package["samples"][0]["clean_ref"] = "../outside.md#sha256=" + "a" * 64
    with pytest.raises(ViralResearchContractError, match="path_escape"):
        validate_package_manifest(package, root=tmp_path)


def test_hash_mismatch_is_rejected(tmp_path: Path):
    package = valid_package_fixture(tmp_path)
    package["samples"][0]["clean_ref"] = "clean/sample.md#sha256=" + "b" * 64
    with pytest.raises(ViralResearchContractError, match="sha256_mismatch"):
        validate_package_manifest(package, root=tmp_path)


def test_incomplete_capture_cannot_be_evidence_checked(tmp_path: Path):
    package = valid_package_fixture(tmp_path)
    sample = package["samples"][0]
    sample["capture_status"] = "partial"
    assert assess_sample_state(sample) == "research_only"


def test_duplicate_logical_identity_is_rejected_without_revision_marker(tmp_path: Path):
    package = valid_package_fixture(tmp_path)
    package["samples"].append(copy.deepcopy(package["samples"][0]))
    with pytest.raises(ViralResearchContractError, match="duplicate_sample_identity"):
        validate_package_manifest(package, root=tmp_path)


def test_revision_marker_allows_distinct_capture_revision(tmp_path: Path):
    package = valid_package_fixture(tmp_path)
    revised = copy.deepcopy(package["samples"][0])
    revised["revision"] = 2
    package["samples"].append(revised)
    assert validate_package_manifest(package, root=tmp_path) == "evidence_checked"


def test_symlink_escape_is_rejected(tmp_path: Path):
    outside = tmp_path.parent / "viral-research-outside"
    outside.mkdir()
    target = outside / "secret.md"
    target.write_text("secret", encoding="utf-8")
    link = tmp_path / "clean" / "link.md"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    with pytest.raises(ViralResearchContractError, match="path_escape"):
        validate_local_ref(f"clean/link.md#sha256={digest}", root=tmp_path)


def test_invalid_hash_shape_is_rejected(tmp_path: Path):
    package = valid_package_fixture(tmp_path)
    package["samples"][0]["clean_ref"] = "clean/sample.md#sha256=xyz"
    with pytest.raises(ViralResearchContractError, match="invalid_hash"):
        validate_package_manifest(package, root=tmp_path)


def test_naive_or_non_shanghai_timestamp_is_rejected(tmp_path: Path):
    package = valid_package_fixture(tmp_path)
    package["created_at"] = "2026-08-25T10:05:00Z"
    with pytest.raises(ViralResearchContractError, match="timestamp_timezone"):
        validate_package_manifest(package, root=tmp_path)


def test_sample_id_must_be_stable_identity(tmp_path: Path):
    package = valid_package_fixture(tmp_path)
    package["samples"][0]["sample_id"] = "sample-arbitrary"
    with pytest.raises(ViralResearchContractError, match="sample_id_mismatch"):
        validate_package_manifest(package, root=tmp_path)


def test_pending_and_blocked_states_fail_closed(tmp_path: Path):
    package = valid_package_fixture(tmp_path)
    pending = package["samples"][0]
    pending["qualification_status"] = "observed_pending"
    assert assess_sample_state(pending) == "observed_pending"
    pending["capture_status"] = "blocked"
    assert assess_sample_state(pending) == "blocked"


def test_manifest_errors_are_blocked_even_if_status_is_rewritten(tmp_path: Path):
    package = valid_package_fixture(tmp_path)
    package["status"] = "research_only"
    package["errors"] = ["capture_ref_missing"]
    assert validate_package_manifest(package, root=tmp_path) == "blocked"


def test_exclusions_ref_must_bind_to_local_hashed_file(tmp_path: Path):
    package = valid_package_fixture(tmp_path)
    package["exclusions_ref"] = "other.jsonl#sha256=" + "a" * 64
    with pytest.raises(ViralResearchContractError, match="exclusions_ref_invalid|missing_ref"):
        validate_package_manifest(package, root=tmp_path)


def test_schema_exposes_required_manifest_and_sample_fields():
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas" / "viral-research-package.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(
        ["schema_version", "run_id", "status", "created_at", "source_lanes", "samples", "exclusions_ref", "errors"]
    ).issubset(schema["required"])
    assert set(
        [
            "sample_id",
            "platform",
            "account_id",
            "title",
            "canonical_url",
            "published_at",
            "capture_status",
            "raw_ref",
            "clean_ref",
            "metadata_ref",
            "evidence_cluster",
            "shape",
            "qualification_status",
        ]
    ).issubset(schema["$defs"]["sample"]["required"])
