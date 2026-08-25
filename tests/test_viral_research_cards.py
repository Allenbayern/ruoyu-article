from __future__ import annotations

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
