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
            "art-002: revalidation_stale:d2",
            "art-001: style_gate_warning:fact_density",
        ],
    }

    result = assess_content_readiness(report)

    assert result["content_status"] == "CONTENT_BLOCKED"
    assert result["content_blockers"] == report["human_judgment_items"]


def test_content_delivery_treats_review_state_fields_as_governance():
    """A-B2: 复核/交付状态属于治理项，不得锁死内容门禁（与 final_review 的 8 个标记一致）。"""

    from article_group.content_delivery import assess_content_readiness

    report = {
        "verdict": "PENDING",
        "human_judgment_items": [
            "art-001: independent_review=pending",
            "art-001: delivery_state=pending_independent_review",
            "art-002: html_delivery_state=withheld",
            "art-001: controller_acceptance=pending",
        ],
    }

    result = assess_content_readiness(report)

    assert result["content_status"] == "CONTENT_READY"
    assert result["content_blockers"] == []
    assert len(result["governance_items"]) == 4


def test_content_delivery_record_binds_current_markdown(tmp_path: Path):
    from article_group.content_delivery import _build_content_delivery_record_from_report

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

    result = _build_content_delivery_record_from_report(run_dir, report)

    assert result["content_status"] == "CONTENT_READY"
    assert result["publication_authorization"] == "not_authorized"
    assert result["articles"][0]["markdown_path"] == "drafts/art-001.md"
    assert result["articles"][0]["markdown_sha256"]


def test_content_delivery_record_carries_four_review_dimensions(tmp_path: Path):
    from article_group.content_delivery import _build_content_delivery_record_from_report

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "batch.json").write_text(
        json.dumps(
            {
                "run_id": "r1",
                "articles": [],
                "publication_authorization": "not_authorized",
            }
        ),
        encoding="utf-8",
    )

    result = _build_content_delivery_record_from_report(
        run_dir,
        {
            "verdict": "PENDING",
            "content_result": "PENDING",
            "evidence_result": "PASS",
            "governance_result": "PENDING",
            "publication_authorization": "not_authorized",
            "human_judgment_items": ["style warning"],
        },
    )

    assert result["content_result"] == "PENDING"
    assert result["evidence_result"] == "PASS"
    assert result["governance_result"] == "PENDING"
    assert result["publication_authorization"] == "not_authorized"


def test_article_first_content_delivery_requires_selected_title_pack(tmp_path: Path):
    from article_group.content_delivery import _build_content_delivery_record_from_report

    run_dir = tmp_path / "article-first"
    (run_dir / "delivery").mkdir(parents=True)
    (run_dir / "drafts").mkdir()
    (run_dir / "review").mkdir()
    (run_dir / "delivery" / "delivery.md").write_text(
        "# 正式标题\n\n正文。\n", encoding="utf-8"
    )
    (run_dir / "drafts" / "body.md").write_text("正文。\n", encoding="utf-8")
    _write_json = lambda path, value: path.write_text(
        json.dumps(value, ensure_ascii=False), encoding="utf-8"
    )
    _write_json(run_dir / "batch.json", {
        "run_id": "article-first",
        "article_first_contract_version": "article-first-v1",
        "legacy_compatibility": True,
        "review_surface": "markdown_codex",
        "publication_authorization": "not_authorized",
        "articles": [{
            "article_id": "art-001",
            "body_draft_path": "drafts/body.md",
            "content_fidelity_path": "review/content.json",
            "title_pack_path": "review/title-pack.json",
            "delivery_path": "delivery/delivery.md",
        }],
    })
    report = {
        "verdict": "PUBLISHABLE",
        "review_surface": "markdown_codex",
        "publication_authorization": "not_authorized",
        "human_judgment_items": [],
    }

    result = _build_content_delivery_record_from_report(run_dir, report)

    assert result["content_status"] == "CONTENT_BLOCKED"
    assert "art-001:content_fidelity_missing_or_unreadable" in result["content_blockers"]


def test_content_delivery_cannot_be_unlocked_by_a_caller_supplied_final_report(
    tmp_path: Path,
):
    from article_group.content_delivery import build_content_delivery_record

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "batch.json").write_text(
        json.dumps(
            {
                "run_id": "2026-09-13/run",
                "review_surface": "markdown_codex",
                "articles": [],
            }
        ),
        encoding="utf-8",
    )

    result = build_content_delivery_record(
        run_dir,
        review_report={
            "verdict": "PUBLISHABLE",
            "content_result": "PASS",
            "evidence_result": "PASS",
            "governance_result": "PASS",
            "publication_authorization": "not_authorized",
            "human_judgment_items": [],
        },
    )

    assert result["content_status"] == "CONTENT_BLOCKED"
    assert "final_review_record_missing" in result["content_blockers"]


def test_content_delivery_rejects_a_stale_persisted_final_review(tmp_path: Path):
    from article_group.content_delivery import build_content_delivery_record
    from article_group.final_review import build_final_review_record

    run_dir = tmp_path / "run"
    (run_dir / "review").mkdir(parents=True)
    (run_dir / "batch.json").write_text(
        json.dumps(
            {
                "run_id": "2026-09-13/run",
                "review_surface": "markdown_codex",
                "articles": [],
            }
        ),
        encoding="utf-8",
    )
    current = build_final_review_record(run_dir)
    current["verdict"] = "PUBLISHABLE"
    (run_dir / "review" / "final-review.json").write_text(
        json.dumps(current), encoding="utf-8"
    )

    result = build_content_delivery_record(run_dir)

    assert result["content_status"] == "CONTENT_BLOCKED"
    assert "stale_final_review" in result["content_blockers"]
    assert "final_review_result_mismatch:verdict" in result["content_blockers"]


def test_content_delivery_rejects_a_caller_report_that_is_not_bound_to_current_review(
    tmp_path: Path,
):
    from article_group.content_delivery import build_content_delivery_record
    from article_group.final_review import build_final_review_record

    run_dir = tmp_path / "run"
    (run_dir / "review").mkdir(parents=True)
    (run_dir / "batch.json").write_text(
        json.dumps(
            {
                "run_id": "2026-09-13/run",
                "review_surface": "markdown_codex",
                "articles": [],
            }
        ),
        encoding="utf-8",
    )
    current = build_final_review_record(run_dir)
    (run_dir / "review" / "final-review.json").write_text(
        json.dumps(current), encoding="utf-8"
    )
    supplied = dict(current)
    supplied["verdict"] = "PUBLISHABLE"

    result = build_content_delivery_record(run_dir, review_report=supplied)

    assert result["content_status"] == "CONTENT_BLOCKED"
    assert "review_report_not_current" in result["content_blockers"]


def test_final_review_writer_persists_run_and_surface_bindings(tmp_path: Path):
    from article_group.final_review import write_final_review_report

    run_dir = tmp_path / "run"
    (run_dir / "review").mkdir(parents=True)
    (run_dir / "batch.json").write_text(
        json.dumps(
            {
                "run_id": "2026-09-13/run",
                "review_surface": "markdown_codex",
                "articles": [],
            }
        ),
        encoding="utf-8",
    )

    path = write_final_review_report(run_dir)
    record = json.loads(path.read_text(encoding="utf-8"))

    assert path == run_dir / "review" / "final-review.json"
    assert record["final_review_schema"] == "final-review-v1"
    assert record["run_id"] == "2026-09-13/run"
    assert len(record["batch_sha256"]) == 64
    assert record["reviewed_artifacts"] == []


def test_content_delivery_treats_readability_attestation_as_governance():
    """A1（2026-09-15）：人工可读性签署未完成属治理项，不得锁死内容门禁。"""

    from article_group.content_delivery import assess_content_readiness

    report = {
        "verdict": "PENDING",
        "human_judgment_items": [
            "art-001: human_readability_attestation=pending (pending)",
            "art-002: human_readability_attestation=pending (pending)",
        ],
    }

    result = assess_content_readiness(report)

    assert result["content_status"] == "CONTENT_READY"
    assert result["content_blockers"] == []
    assert len(result["governance_items"]) == 2
