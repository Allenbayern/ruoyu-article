"""RED tests for source snapshot, material sufficiency, and per-article gates."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest


# --- valid minimal fixture helpers ---


def _want_text(content: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- source manifest tests ---


def test_snapshot_digest_mismatch_blocks_manifest(tmp_path: Path):
    from article_group.prewrite import validate_source_manifest

    snap = _want_text("hello world", tmp_path / "sources" / "page.html")
    manifest = {
        "sources": [
            {
                "source_id": "S1",
                "relative_path": "sources/page.html",
                "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
                "url": "https://example.com",
                "role": "confirmed-primary",
                "independence_group": "example",
                "captured_at": "2026-07-26T00:00:00+08:00",
            }
        ]
    }
    errors = validate_source_manifest(manifest, tmp_path)
    assert any("digest" in err.lower() or "sha" in err.lower() or "mismatch" in err.lower() for err in errors)


def test_valid_source_manifest_passes(tmp_path: Path):
    from article_group.prewrite import validate_source_manifest

    snap = _want_text("hello world", tmp_path / "sources" / "page.html")
    manifest = {
        "sources": [
            {
                "source_id": "S1",
                "relative_path": "sources/page.html",
                "sha256": _sha256(snap),
                "url": "https://finance.sina.com.cn/news/123",
                "role": "confirmed-primary",
                "independence_group": "example",
                "captured_at": "2026-07-26T00:00:00+08:00",
            }
        ]
    }
    errors = validate_source_manifest(manifest, tmp_path)
    assert errors == []


def test_confirmed_primary_synthetic_url_is_rejected(tmp_path: Path):
    from article_group.prewrite import validate_source_manifest

    snap = _want_text("official announcement", tmp_path / "sources" / "page.html")
    manifest = {
        "sources": [{
            "source_id": "S1",
            "relative_path": "sources/page.html",
            "sha256": _sha256(snap),
            "url": "synthetic://generated-source",
            "role": "confirmed-primary",
            "independence_group": "official",
        }]
    }

    errors = validate_source_manifest(manifest, tmp_path)

    assert any("S1" in error and "synthetic" in error for error in errors)


def test_confirmed_primary_synthetic_url_with_whitespace_and_mixed_case_is_rejected(tmp_path: Path):
    from article_group.prewrite import validate_source_manifest

    snap = _want_text("official announcement", tmp_path / "sources" / "page.html")
    manifest = {
        "sources": [{
            "source_id": "S1",
            "relative_path": "sources/page.html",
            "sha256": _sha256(snap),
            "url": " \tSYNTHETIC://generated-source ",
            "role": "confirmed-primary",
            "independence_group": "official",
        }]
    }

    errors = validate_source_manifest(manifest, tmp_path)

    assert "source_S1_confirmed_primary_synthetic_url" in errors


def test_confirmed_primary_placeholder_url_is_rejected(tmp_path: Path):
    from article_group.prewrite import validate_source_manifest

    snap = _want_text("official announcement", tmp_path / "sources" / "page.html")
    manifest = {
        "sources": [{
            "source_id": "S1",
            "relative_path": "sources/page.html",
            "sha256": _sha256(snap),
            "url": "https://example.com/original-url",
            "role": "confirmed-primary",
            "independence_group": "official",
        }]
    }

    errors = validate_source_manifest(manifest, tmp_path)

    assert any("S1" in error and "placeholder" in error for error in errors)


def test_real_publisher_url_with_original_url_slug_is_allowed(tmp_path: Path):
    from article_group.prewrite import validate_source_manifest

    snap = _want_text("official announcement", tmp_path / "sources" / "page.html")
    manifest = {
        "sources": [{
            "source_id": "S1",
            "relative_path": "sources/page.html",
            "sha256": _sha256(snap),
            "url": "https://news.qq.com/original-url/report-123",
            "role": "confirmed-primary",
            "independence_group": "qq-news",
        }]
    }

    errors = validate_source_manifest(manifest, tmp_path)

    assert errors == []


def test_confirmed_primary_ai_generated_snapshot_is_rejected(tmp_path: Path):
    from article_group.prewrite import validate_source_manifest

    snap = _want_text("<html><body>本文由AI生成</body></html>", tmp_path / "sources" / "page.html")
    manifest = {
        "sources": [{
            "source_id": "S1",
            "relative_path": "sources/page.html",
            "sha256": _sha256(snap),
            "url": "https://studio.example/news",
            "role": "confirmed-primary",
            "independence_group": "studio",
        }]
    }

    errors = validate_source_manifest(manifest, tmp_path)

    assert any("S1" in error and "ai_generated" in error for error in errors)


def test_confirmed_primary_ai_generated_snapshot_with_case_and_whitespace_is_rejected(tmp_path: Path):
    from article_group.prewrite import validate_source_manifest

    for index, marker in enumerate(("本文由ai生成", "本文由\n AI \t生成")):
        snap = _want_text(marker, tmp_path / "sources" / f"page-{index}.html")
        manifest = {
            "sources": [{
                "source_id": f"S{index}",
                "relative_path": f"sources/page-{index}.html",
                "sha256": _sha256(snap),
                "url": f"https://studio.example/news/{index}",
                "role": "confirmed-primary",
                "independence_group": "studio",
            }]
        }

        errors = validate_source_manifest(manifest, tmp_path)

        assert f"source_S{index}_confirmed_primary_ai_generated_snapshot" in errors


def test_confirmed_primaries_with_same_digest_cannot_claim_independence(tmp_path: Path):
    from article_group.prewrite import validate_source_manifest

    snap = _want_text("same captured report", tmp_path / "sources" / "page.html")
    manifest = {
        "sources": [
            {
                "source_id": "S1",
                "relative_path": "sources/page.html",
                "sha256": _sha256(snap),
                "url": "https://source-one.test/report",
                "role": "confirmed-primary",
                "independence_group": "publisher-one",
            },
            {
                "source_id": "S2",
                "relative_path": "sources/page.html",
                "sha256": _sha256(snap),
                "url": "https://source-two.test/report",
                "role": "confirmed-primary",
                "independence_group": "publisher-two",
            },
        ]
    }

    errors = validate_source_manifest(manifest, tmp_path)

    assert any("S1" in error and "S2" in error and "independence" in error for error in errors)


def test_non_primary_ai_generated_snapshots_are_allowed(tmp_path: Path):
    from article_group.prewrite import validate_source_manifest

    snap = _want_text("<html><body>本文由AI生成</body></html>", tmp_path / "sources" / "page.html")
    manifest = {
        "sources": [
            {
                "source_id": "S1",
                "relative_path": "sources/page.html",
                "sha256": _sha256(snap),
                "url": "https://secondary.test/report",
                "role": "attributed-secondary",
                "independence_group": "secondary",
            },
            {
                "source_id": "S2",
                "relative_path": "sources/page.html",
                "sha256": _sha256(snap),
                "url": "https://quarantined.test/report",
                "role": "quarantined",
                "independence_group": "quarantined",
            },
        ]
    }

    assert validate_source_manifest(manifest, tmp_path) == []


def test_source_path_escape_is_rejected():
    from article_group.prewrite import validate_source_manifest

    manifest = {
        "sources": [
            {
                "source_id": "S1",
                "relative_path": "../outside.html",
                "sha256": "x",
                "url": "https://example.com",
                "role": "confirmed-primary",
                "independence_group": "example",
                "captured_at": "2026-07-26T00:00:00+08:00",
            }
        ]
    }
    errors = validate_source_manifest(manifest, Path("/tmp"))
    assert any("unsafe" in err.lower() or ".." in err for err in errors)


def test_claim_locator_missing_from_snapshot_blocks(tmp_path: Path):
    from article_group.prewrite import validate_claim_locators

    snap = _want_text("<p>some content</p>", tmp_path / "sources" / "page.html")
    manifest = {
        "sources": [
            {
                "source_id": "S1",
                "relative_path": "sources/page.html",
                "sha256": _sha256(snap),
            }
        ]
    }
    claims = [
        {
            "claim_id": "C1",
            "source_id": "S1",
            "locator": "this-text-does-not-appear-anywhere",
        }
    ]
    errors = validate_claim_locators(claims, manifest, tmp_path)
    assert any("locator" in err.lower() or "missing" in err.lower() or "not found" in err.lower() for err in errors)


def test_valid_claim_locator_passes(tmp_path: Path):
    from article_group.prewrite import validate_claim_locators

    snap = _want_text("July 10, 2026 theatrical release", tmp_path / "sources" / "page.html")
    manifest = {
        "sources": [
            {
                "source_id": "S1",
                "relative_path": "sources/page.html",
                "sha256": _sha256(snap),
            }
        ]
    }
    claims = [
        {
            "claim_id": "C1",
            "source_id": "S1",
            "locator": "July 10, 2026",
        }
    ]
    errors = validate_claim_locators(claims, manifest, tmp_path)
    assert errors == []


# --- material sufficiency tests ---


def test_single_official_synopsis_is_insufficient_for_long_form():
    from article_group.prewrite import assess_material_sufficiency

    result = assess_material_sufficiency(
        evidence_atom_ids=["a1", "a2"],
        concrete_anchor_ids=["anchor1"],
        source_roles=["confirmed-primary"],
    )
    assert result["decision"] != "ready-for-brief"


def test_three_atoms_and_three_anchors_can_enter_brief():
    from article_group.prewrite import assess_material_sufficiency

    result = assess_material_sufficiency(
        evidence_atom_ids=["a1", "a2", "a3"],
        concrete_anchor_ids=["x1", "x2", "x3"],
        source_roles=["confirmed-primary", "independent-review"],
    )
    assert result["decision"] == "ready-for-brief"


def test_inference_only_claim_count_does_not_increase_capacity():
    from article_group.prewrite import assess_material_sufficiency

    # 2 evidence atoms but only 1 concrete anchor and 1 source role
    result = assess_material_sufficiency(
        evidence_atom_ids=["a1", "a2"],
        concrete_anchor_ids=["x1"],
        source_roles=["confirmed-primary"],
    )
    # capacity should be low — not enough for long-form
    assert result.get("capacity_points", 0) < 1000


def test_capacity_formula_below_1500_is_H4():
    from article_group.prewrite import assess_material_sufficiency

    result = assess_material_sufficiency(
        evidence_atom_ids=["a1"],
        concrete_anchor_ids=["x1"],
        source_roles=["confirmed-primary"],
    )
    assert result["decision"] == "H4 draft-only"


# --- per-article gate tests ---


def test_article_must_prove_claim_ids_match_evidence(tmp_path: Path):
    from article_group.prewrite import validate_article_stage

    _want_text("文" * 1500, tmp_path / "slots" / "A" / "draft.md")
    _want_text("evidence", tmp_path / "slots" / "A" / "evidence-pack.md")
    _want_text("brief", tmp_path / "slots" / "A" / "writing-brief.md")

    article = {
        "article_id": "art-A",
        "slot": "A",
        "state": "R8 review-ready",
        "markdown_path": "slots/A/draft.md",
        "evidence_pack_path": "slots/A/evidence-pack.md",
        "writing_brief_path": "slots/A/writing-brief.md",
        "title": "一个合格的标题",
        "claim_coverage": "complete",
        "material_claim_ids": ["C1"],
        "claim_mappings": [{
            "claim_id": "C1", "claim_text": "文", "draft_locator": "文",
            "claim_type": "fact", "source_id": "S1", "locator": "text",
            "support_status": "direct", "limitation": "",
        }],
        "concrete_support_types": ["character", "scene"],
        "html_delivery_state": "withheld",
        "publication_authorization": "not_authorized",
    }
    # The must_prove claim list should match
    evidence_ids = {"C1"}
    errors = validate_article_stage(article, evidence_ids, tmp_path)
    assert not any("must_prove" in err.lower() for err in errors)


def test_article_stage_rejects_non_string_claim_type_without_crashing(tmp_path: Path):
    from article_group.prewrite import validate_article_stage

    _want_text("文" * 1500, tmp_path / "slots" / "A" / "draft.md")
    _want_text("evidence", tmp_path / "slots" / "A" / "evidence-pack.md")
    _want_text("brief", tmp_path / "slots" / "A" / "writing-brief.md")
    article = {
        "article_id": "art-A", "slot": "A", "state": "R8 review-ready",
        "markdown_path": "slots/A/draft.md", "evidence_pack_path": "slots/A/evidence-pack.md",
        "writing_brief_path": "slots/A/writing-brief.md", "title": "标题",
        "claim_coverage": "complete", "material_claim_ids": ["C1"],
        "claim_mappings": [{
            "claim_id": "C1", "claim_text": "文", "draft_locator": "文",
            "claim_type": ["fact"], "source_id": "S1", "locator": "text",
            "support_status": "direct", "limitation": "",
        }],
        "concrete_support_types": ["character", "scene"],
        "html_delivery_state": "withheld", "publication_authorization": "not_authorized",
    }

    errors = validate_article_stage(article, {"C1"}, tmp_path)

    assert any("claim_mapping_invalid_type:art-A:C1" in error for error in errors)


def test_article_short_draft_is_rejected_by_article_stage(tmp_path: Path):
    from article_group.prewrite import validate_article_stage

    _want_text("短", tmp_path / "slots" / "A" / "draft.md")
    _want_text("evidence", tmp_path / "slots" / "A" / "evidence-pack.md")
    _want_text("brief", tmp_path / "slots" / "A" / "writing-brief.md")

    article = {
        "article_id": "art-A",
        "slot": "A",
        "state": "R8 review-ready",
        "markdown_path": "slots/A/draft.md",
        "evidence_pack_path": "slots/A/evidence-pack.md",
        "writing_brief_path": "slots/A/writing-brief.md",
        "title": "标题",
        "claim_coverage": "complete",
        "material_claim_ids": ["C1"],
        "claim_mappings": [{
            "claim_id": "C1", "claim_text": "文", "draft_locator": "文",
            "claim_type": "fact", "source_id": "S1", "locator": "text",
            "support_status": "direct", "limitation": "",
        }],
        "concrete_support_types": ["character", "scene"],
        "html_delivery_state": "withheld",
        "publication_authorization": "not_authorized",
    }
    errors = validate_article_stage(article, set(), tmp_path)
    assert any("count" in err.lower() or "character" in err.lower() or "1500" in err for err in errors)
