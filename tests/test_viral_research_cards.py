from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest

from article_group.viral_research_cards import (
    ViralResearchCardError,
    build_case_card,
    validate_case_card_envelope,
    write_case_cards,
)
from article_group.viral_research_contract import normalize_sample_id


def _ref(root: Path, relative: str, content: str) -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"{relative}#sha256={digest}"


def _sample(root: Path) -> dict:
    published_at = "2026-08-25T09:00:00+08:00"
    return {
        "sample_id": normalize_sample_id(
            platform="wechat",
            account_id="acct-1",
            canonical_url="https://example.com/article/1",
            published_at=published_at,
        ),
        "platform": "wechat",
        "account_id": "acct-1",
        "title": "Film case",
        "canonical_url": "https://example.com/article/1",
        "published_at": published_at,
        "capture_status": "complete",
        "raw_ref": _ref(root, "raw/a.html", "<html>a</html>"),
        "clean_ref": _ref(root, "clean/a.md", "# a"),
        "metadata_ref": _ref(root, "metadata/a.json", "{}"),
        "shape": {"medium": "long_form", "content_domain": "film"},
        "qualification_status": "qualified_viral",
    }


def test_build_case_card_attaches_hashed_evidence_without_copying_body(tmp_path: Path):
    sample = _sample(tmp_path)
    card = build_case_card(sample, run_root=tmp_path)
    assert card["schema_version"] == "viral-research-case-card-v1"
    assert card["evidence"]["clean_ref"].startswith("clean/a.md#sha256=")
    assert card["automatic_publication_authority"] if "automatic_publication_authority" in card else True
    assert not (tmp_path / "cards").exists()
    assert validate_case_card_envelope(card, run_root=tmp_path)["sample_id"] == sample["sample_id"]


def test_card_rejects_evidence_path_escape(tmp_path: Path):
    sample = _sample(tmp_path)
    sample["clean_ref"] = "../outside.md#sha256=" + "a" * 64
    with pytest.raises(ViralResearchCardError, match="path_escape"):
        build_case_card(sample, run_root=tmp_path)


def test_card_rejects_unsafe_sample_id(tmp_path: Path):
    sample = _sample(tmp_path)
    sample["sample_id"] = "../escape"
    with pytest.raises(ViralResearchCardError, match="sample_id_unsafe"):
        build_case_card(sample, run_root=tmp_path)


def test_write_case_cards_is_non_overwriting(tmp_path: Path):
    sample = _sample(tmp_path)
    output = tmp_path / "cards"
    manifest = write_case_cards([sample], run_root=tmp_path, output_root=output)
    assert manifest["card_count"] == 1
    assert len(list(output.glob("*.json"))) == 2
    with pytest.raises(ViralResearchCardError, match="artifact_exists"):
        write_case_cards([sample], run_root=tmp_path, output_root=output)


def test_case_contract_delegation_is_recorded(tmp_path: Path, monkeypatch):
    sample = _sample(tmp_path)
    called = {}

    def fake_validate(payload):
        called["sample_id"] = payload["sample_id"]
        return "research_only"

    monkeypatch.setattr("article_group.viral_research_cards.validate_case_card", fake_validate)
    card = build_case_card(sample, run_root=tmp_path, case_contract_card={"sample_id": sample["sample_id"]})
    assert called["sample_id"] == sample["sample_id"]
    assert card["case_contract"]["status"] == "validated"
    assert card["case_contract"]["qualification_status"] == "research_only"


import copy
import json

from article_group.viral_research_cards import attach_client_evidence
from article_group.viral_research_package import build_package


def _build_package(tmp_path: Path) -> tuple[Path, str]:
    (tmp_path / "raw").mkdir()
    (tmp_path / "clean").mkdir()
    (tmp_path / "metadata").mkdir()
    (tmp_path / "raw" / "a.html").write_text("<html>a</html>", encoding="utf-8")
    (tmp_path / "clean" / "a.md").write_text("# a", encoding="utf-8")
    (tmp_path / "metadata" / "a.json").write_text("{}", encoding="utf-8")
    capture = {
        "run_id": "run-attach-001",
        "created_at": "2026-08-25T09:05:00+08:00",
        "source_lanes": ["wechat_long_form"],
        "samples": [
            {
                "platform": "wechat",
                "account_id": "acct-1",
                "title": "Film case",
                "canonical_url": "https://example.com/article/1",
                "published_at": "2026-08-25T09:00:00+08:00",
                "capture_status": "full",
                "raw_ref": "raw/a.html",
                "clean_ref": "clean/a.md",
                "metadata_ref": "metadata/a.json",
                "shape": {"medium": "long_form", "content_domain": "film"},
                "qualification_status": "observed_pending",
                "source_lane": "wechat_long_form",
            }
        ],
    }
    capture_path = tmp_path / "capture.json"
    capture_path.write_text(json.dumps(capture), encoding="utf-8")
    package_root = tmp_path / "viral-research" / "package"
    manifest = build_package(capture_path, run_root=tmp_path, output_root=package_root)
    return package_root, manifest["samples"][0]["sample_id"]


def _write_evidence(tmp_path: Path, **overrides) -> Path:
    display = tmp_path / "client-display.txt"
    display.write_text("views=1000 likes=100", encoding="utf-8")
    digest = hashlib.sha256(display.read_bytes()).hexdigest()
    evidence = {
        "evidence_domain": "competitive_research_evidence",
        "evidence_ref": f"client-display.txt#sha256={digest}",
        "original_display": "views=1000 likes=100",
        "observed_at": "2026-08-25T10:00:00+08:00",
        "confirmer": "reviewer-1",
        "sha256": digest,
        "sanitized": True,
        "metric_plan_version": "wechat-metrics-v1",
        "metric_plan_frozen_at": "2026-08-25T08:00:00+08:00",
        "metric_plan": [
            {"metric": "view_count", "visible": True, "required": True},
        ],
        "threshold_or_rank_rule": {
            "version": "wechat-rule-v1",
            "frozen_at": "2026-08-25T08:00:00+08:00",
            "platform": "wechat",
            "baseline": "research",
            "window": "publication",
            "rule": "view_count minimum",
            "minimums": {"view_count": 100},
            "rank_maximums": {},
        },
        "metrics": [
            {
                "metric": "view_count",
                "value": 1000,
                "status": "observed",
                "source": "client_dashboard",
                "observed_at": "2026-08-25T10:00:00+08:00",
                "evidence_ref": f"client-display.txt#sha256={digest}",
            }
        ],
    }
    evidence.update(overrides)
    path = tmp_path / "sanitized-evidence.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_valid_sanitized_evidence_writes_new_revision_and_keeps_pending_package(tmp_path: Path):
    package_root, sample_id = _build_package(tmp_path)
    before = (package_root / "manifest.json").read_bytes()
    evidence = _write_evidence(tmp_path)
    revision = tmp_path / "viral-research" / "package" / "revisions" / "rev-001"

    result = attach_client_evidence(
        package_root=package_root,
        sample_id=sample_id,
        evidence_file=evidence,
        output_revision=revision,
    )

    assert result["derived_qualification_status"] == "qualified_viral"
    assert result["automatic_publication_authority"] is False
    assert (revision / "revision.json").is_file()
    assert (revision / "evidence.json").is_file()
    assert (package_root / "manifest.json").read_bytes() == before
    assert json.loads((package_root / "manifest.json").read_text())["samples"][0]["qualification_status"] == "observed_pending"


def test_output_revision_must_be_inside_package_revisions(tmp_path: Path):
    package_root, sample_id = _build_package(tmp_path)
    evidence = _write_evidence(tmp_path)
    with pytest.raises(ViralResearchCardError, match="path_escape"):
        attach_client_evidence(
            package_root=package_root,
            sample_id=sample_id,
            evidence_file=evidence,
            output_revision=tmp_path / "outside-revision",
        )


def test_attach_refuses_tampered_package(tmp_path: Path):
    package_root, sample_id = _build_package(tmp_path)
    integrity = package_root / "integrity.json"
    integrity.unlink()
    evidence = _write_evidence(tmp_path)
    with pytest.raises(ViralResearchCardError, match="package_integrity"):
        attach_client_evidence(
            package_root=package_root,
            sample_id=sample_id,
            evidence_file=evidence,
            output_revision=package_root / "revisions" / "tampered-package",
        )


def test_missing_confirmer_is_rejected_and_revision_is_not_created(tmp_path: Path):
    package_root, sample_id = _build_package(tmp_path)
    evidence = _write_evidence(tmp_path)
    data = json.loads(evidence.read_text())
    data.pop("confirmer")
    evidence.write_text(json.dumps(data), encoding="utf-8")
    revision = tmp_path / "viral-research" / "package" / "revisions" / "missing-confirmer"
    try:
        attach_client_evidence(package_root=package_root, sample_id=sample_id, evidence_file=evidence, output_revision=revision)
    except ViralResearchCardError as error:
        assert "client_evidence_confirmer_missing" in str(error)
    else:
        raise AssertionError("expected missing confirmer")
    assert not revision.exists()


def test_missing_timestamp_is_rejected(tmp_path: Path):
    package_root, sample_id = _build_package(tmp_path)
    evidence = _write_evidence(tmp_path)
    data = json.loads(evidence.read_text())
    data.pop("observed_at")
    evidence.write_text(json.dumps(data), encoding="utf-8")
    try:
        attach_client_evidence(
            package_root=package_root,
            sample_id=sample_id,
            evidence_file=evidence,
            output_revision=tmp_path / "viral-research" / "package" / "revisions" / "missing-timestamp",
        )
    except ViralResearchCardError as error:
        assert "client_evidence_observed_at_missing" in str(error)
    else:
        raise AssertionError("expected missing timestamp")


def test_non_hex_sha256_is_rejected(tmp_path: Path):
    package_root, sample_id = _build_package(tmp_path)
    evidence = _write_evidence(tmp_path, sha256="not-a-digest")
    try:
        attach_client_evidence(
            package_root=package_root,
            sample_id=sample_id,
            evidence_file=evidence,
            output_revision=tmp_path / "viral-research" / "package" / "revisions" / "bad-sha",
        )
    except ViralResearchCardError as error:
        assert "client_evidence_sha256_missing" in str(error)
    else:
        raise AssertionError("expected invalid digest")


def test_unsanitized_evidence_is_rejected(tmp_path: Path):
    package_root, sample_id = _build_package(tmp_path)
    evidence = _write_evidence(tmp_path, sanitized=False)
    try:
        attach_client_evidence(
            package_root=package_root,
            sample_id=sample_id,
            evidence_file=evidence,
            output_revision=tmp_path / "viral-research" / "package" / "revisions" / "unsanitized",
        )
    except ViralResearchCardError as error:
        assert "client_evidence_not_sanitized" in str(error)
    else:
        raise AssertionError("expected unsanitized evidence")


def test_evidence_ref_outside_run_root_is_rejected(tmp_path: Path):
    package_root, sample_id = _build_package(tmp_path)
    evidence = _write_evidence(tmp_path, evidence_ref="../outside.txt#sha256=" + "a" * 64)
    try:
        attach_client_evidence(
            package_root=package_root,
            sample_id=sample_id,
            evidence_file=evidence,
            output_revision=tmp_path / "viral-research" / "package" / "revisions" / "authority",
        )
    except ViralResearchCardError as error:
        assert "path_escape" in str(error)
    else:
        raise AssertionError("expected path escape")


def test_attachment_cannot_set_qualification_status(tmp_path: Path):
    package_root, sample_id = _build_package(tmp_path)
    evidence = _write_evidence(tmp_path, qualification_status="qualified_viral")
    try:
        attach_client_evidence(
            package_root=package_root,
            sample_id=sample_id,
            evidence_file=evidence,
            output_revision=tmp_path / "viral-research" / "package" / "revisions" / "metadata-marker",
        )
    except ViralResearchCardError as error:
        assert "qualification_status_forbidden" in str(error)
    else:
        raise AssertionError("expected forbidden authority field")


def test_nested_authority_fields_are_rejected(tmp_path: Path):
    package_root, sample_id = _build_package(tmp_path)
    evidence = _write_evidence(
        tmp_path,
        authority={"qualification_status": "qualified_viral"},
    )
    with pytest.raises(ViralResearchCardError, match="authority_field_forbidden"):
        attach_client_evidence(
            package_root=package_root,
            sample_id=sample_id,
            evidence_file=evidence,
            output_revision=package_root / "revisions" / "nested-authority",
        )


def test_credential_marker_is_rejected(tmp_path: Path):
    package_root, sample_id = _build_package(tmp_path)
    evidence = _write_evidence(tmp_path, session="should-not-enter-evidence")
    try:
        attach_client_evidence(
            package_root=package_root,
            sample_id=sample_id,
            evidence_file=evidence,
            output_revision=package_root / "revisions" / "credential-marker",
        )
    except ViralResearchCardError as error:
        assert "credential_marker" in str(error)
    else:
        raise AssertionError("expected credential marker rejection")


def test_credential_marker_in_evidence_file_is_rejected(tmp_path: Path):
    package_root, sample_id = _build_package(tmp_path)
    evidence = _write_evidence(tmp_path)
    display = tmp_path / "client-display.txt"
    display.write_text("views=1000 cookie=should-not-enter", encoding="utf-8")
    digest = hashlib.sha256(display.read_bytes()).hexdigest()
    data = json.loads(evidence.read_text(encoding="utf-8"))
    data["evidence_ref"] = f"client-display.txt#sha256={digest}"
    data["sha256"] = digest
    data["metrics"][0]["evidence_ref"] = data["evidence_ref"]
    evidence.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ViralResearchCardError, match="credential_marker"):
        attach_client_evidence(
            package_root=package_root,
            sample_id=sample_id,
            evidence_file=evidence,
            output_revision=package_root / "revisions" / "file-marker",
        )


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"token":"SECRET"}', "credential_marker"),
        (base64.b64encode(b'{"token":"SECRET"}').decode("ascii"), "evidence_format_unsupported"),
    ],
)
def test_encoded_evidence_content_is_not_allowed(tmp_path: Path, content: str, expected: str):
    package_root, sample_id = _build_package(tmp_path)
    evidence = _write_evidence(tmp_path)
    display = tmp_path / "client-display.txt"
    if expected == "credential_marker":
        display.write_bytes(content.encode("utf-16"))
    else:
        display.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(display.read_bytes()).hexdigest()
    data = json.loads(evidence.read_text(encoding="utf-8"))
    data["evidence_ref"] = f"client-display.txt#sha256={digest}"
    data["sha256"] = digest
    data["metrics"][0]["evidence_ref"] = data["evidence_ref"]
    evidence.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ViralResearchCardError, match=expected):
        attach_client_evidence(
            package_root=package_root,
            sample_id=sample_id,
            evidence_file=evidence,
            output_revision=package_root / "revisions" / "encoded-marker",
        )


def test_existing_revision_is_not_overwritten(tmp_path: Path):
    package_root, sample_id = _build_package(tmp_path)
    evidence = _write_evidence(tmp_path)
    revision = tmp_path / "viral-research" / "package" / "revisions" / "existing"
    revision.parent.mkdir(parents=True)
    revision.mkdir()
    (revision / "sentinel").write_text("keep", encoding="utf-8")
    try:
        attach_client_evidence(
            package_root=package_root,
            sample_id=sample_id,
            evidence_file=evidence,
            output_revision=revision,
        )
    except ViralResearchCardError as error:
        assert "artifact_exists" in str(error)
    else:
        raise AssertionError("expected artifact exists")
    assert (revision / "sentinel").read_text() == "keep"
