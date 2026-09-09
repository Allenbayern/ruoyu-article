from __future__ import annotations

import json
from pathlib import Path


def test_content_delivery_is_ready_when_only_governance_items_remain():
    from article_group.content_delivery import assess_content_readiness

    report = {
        "verdict": "PENDING",
        "human_judgment_items": [
            "art-001: human_editor_attestation=pending_or_missing",
            "art-001: human_attestation_missing",
            "editorial-review-record-art-001.json:prepublication:"
            "human_review_completed_by_nonhuman_provenance",
            "art-001: controller_acceptance=pending",
        ],
    }

    result = assess_content_readiness(report)

    assert result["content_status"] == "CONTENT_READY"
    assert result["content_blockers"] == []
    assert len(result["governance_items"]) == 4


def test_content_delivery_blocks_content_review_items():
    from article_group.content_delivery import assess_content_readiness

    report = {
        "verdict": "PENDING",
        "human_judgment_items": [
            "art-001: independent_review=pending",
            "art-002: revalidation_stale:d2",
        ],
    }

    result = assess_content_readiness(report)

    assert result["content_status"] == "CONTENT_BLOCKED"
    assert result["content_blockers"] == report["human_judgment_items"]


def test_content_delivery_record_binds_current_markdown(tmp_path: Path):
    from article_group.content_delivery import build_content_delivery_record

    run_dir = tmp_path / "run"
    (run_dir / "drafts").mkdir(parents=True)
    (run_dir / "review").mkdir()
    markdown = "# 《测试片》标题？\n\n这是成品正文。\n"
    (run_dir / "drafts" / "art-001.md").write_text(markdown, encoding="utf-8")
    (run_dir / "batch.json").write_text(
        json.dumps(
            {
                "run_id": "demo/run",
                "review_surface": "markdown_codex",
                "publication_authorization": "not_authorized",
                "articles": [
                    {
                        "article_id": "art-001",
                        "title": "《测试片》标题？",
                        "markdown_path": "drafts/art-001.md",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    report = {
        "verdict": "PENDING",
        "review_surface": "markdown_codex",
        "publication_authorization": "not_authorized",
        "human_judgment_items": ["art-001: human_attestation_missing"],
    }

    result = build_content_delivery_record(run_dir, review_report=report)

    assert result["content_status"] == "CONTENT_READY"
    assert result["publication_authorization"] == "not_authorized"
    assert result["articles"][0]["markdown_path"] == "drafts/art-001.md"
    assert result["articles"][0]["markdown_sha256"]
