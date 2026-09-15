"""Option A（2026-09-15 裁定）：task-hierarchy 对齐 1.0 契约 + 真校验。

生成器修复前的历史形状（article_id/status、crawl-task-v1、group-manifest-v1）
必须被 1.0 契约拒绝；修复后每个 run 必须通过 validate_task_hierarchy_run。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from article_group.article_task_v1 import (
    validate_crawl_task,
    validate_task_binding,
    validate_task_hierarchy_run,
)

DAILY_005 = Path("runs/2026-09-15/daily-005")
needs_daily_005 = pytest.mark.skipif(
    not (DAILY_005 / "batch.json").exists(),
    reason="runs/ 是本地审计目录（gitignore），daily-005 不在当前工作树时不跑集成断言",
)

# 生成器修复前的历史形状（2026-09-15/daily-005 原始产物）
LEGACY_GROUP = {
    "schema_version": "group-manifest-v1",
    "run_id": "2026-09-15/daily-005",
    "article_ids": ["art-001", "art-002"],
    "selection_rerun": True,
    "publication_authorization": "not_authorized",
}
LEGACY_ARTICLE = {
    "schema_version": "article-task-v1",
    "article_id": "art-001",
    "crawl_task_id": "crawl-art-001",
    "status": "content_passed",
    "brief_path": "briefs/writing-brief-art-001.md",
    "task_card_path": "task-cards/task-card-art-001.md",
}
LEGACY_CRAWL = {
    "schema_version": "crawl-task-v1",
    "crawl_task_id": "crawl-art-001",
    "article_id": "art-001",
    "status": "accepted",
}


def test_legacy_daily_shapes_rejected_by_binding():
    errors = validate_task_binding(
        group=LEGACY_GROUP, article=LEGACY_ARTICLE, crawl=LEGACY_CRAWL
    )
    for expected in (
        "schema_version",  # group-manifest-v1 / crawl-task-v1 都不是 1.0 契约名
        "missing:group_id",
        "missing:article_task_id",
        "missing:topic_id",
        "missing:topic_version",
        "missing:state",
        "invalid:state",  # crawl 的 status:"accepted" 不是契约 state
    ):
        assert expected in errors, f"{expected} 应出现在 {errors}"


def test_crawl_task_parent_v1_schema_enforced():
    errors = validate_crawl_task(LEGACY_CRAWL)
    assert "schema_version" in errors
    assert "missing:article_task_id" in errors
    assert "missing:topic_id" in errors
    assert "missing:topic_version" in errors
    assert "missing:state" in errors


def test_validate_task_hierarchy_run_reports_missing_artifacts(tmp_path):
    report = validate_task_hierarchy_run(tmp_path)
    assert report["schema_version"] == "task-hierarchy-validation-v1"
    assert report["pass"] is False
    assert "missing:group_manifest" in report["errors"]
    assert "missing:article_tasks" in report["errors"]


@needs_daily_005
def test_daily_005_task_hierarchy_passes_contract_gate():
    report = validate_task_hierarchy_run(DAILY_005)
    assert report["pass"], report["errors"]
    assert report["errors"] == []
    assert {item["article_id"] for item in report["articles"]} == {"art-001", "art-002"}


@needs_daily_005
def test_daily_005_article_state_capped_below_final_review():
    # 日更不产出 1.0 editorial-judgment schema 家族，article-task 不得宣称
    # final_review/delivered（否则契约会要求缺失的 judgment 记录）。
    for aid in ("art-001", "art-002"):
        record = json.loads(
            (DAILY_005 / f"task-hierarchy/article-task-{aid}.json").read_text(
                encoding="utf-8"
            )
        )
        assert record["schema_version"] == "article-task-v1"
        assert record["article_task_id"] == f"at-{aid}"
        assert record["group_id"]
        assert record["topic_id"] == aid
        assert record["topic_version"] == 1
        assert record["state"] in {"title_review", "content_passed", "content_review"}
        assert record["publication_authorization"] == "not_authorized"
