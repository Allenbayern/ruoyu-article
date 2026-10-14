"""Unit tests for pilot_adapters: dailyhot, backlog, sources and gate registry."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
import pytest

from article_group.pilot_adapters import (
    dailyhot_scout_adapter,
    topic_backlog_adapter,
    evidence_sources_adapter,
    build_gate_registry_report,
)


def test_dailyhot_scout_adapter(tmp_path: Path):
    # 模拟 dailyhot classified json
    classified_file = tmp_path / "test.classified.json"
    dummy_data = {
        "items": [
            {
                "film": True,
                "dispute": 2,
                "hot": 1000,
                "title": "老实人被逼疯绝境反扑",
                "desc": "详细经过描述",
                "source": "douban",
                "source_label": "豆瓣讨论",
                "url": "http://example.com/1",
            },
            {
                "film": False,
                "dispute": 0,
                "hot": 500,
                "title": "天气预报",
                "desc": "无关内容",
            },
        ]
    }
    classified_file.write_text(json.dumps(dummy_data, ensure_ascii=False), encoding="utf-8")

    run_dir = tmp_path / "run_test_adapter"
    run_dir.mkdir()

    pool = dailyhot_scout_adapter(classified_file, run_dir, top_n=3)
    assert pool["total_film_hits"] == 1
    assert len(pool["candidates"]) == 1
    cand = pool["candidates"][0]
    assert cand["candidate_id"] == "cand-01"
    assert cand["viral_pillar"]["pillar_id"] == "p1_honest_retaliation"
    assert (run_dir / "candidate-pool.json").exists()


def test_topic_backlog_adapter(tmp_path: Path):
    # 初始化一个临时 sqlite db
    db_file = tmp_path / "test-backlog.sqlite"
    conn = sqlite3.connect(db_file)
    conn.execute("""
    CREATE TABLE backlog_items (
        item_key TEXT PRIMARY KEY,
        candidate_id TEXT,
        title TEXT,
        first_seen_at TEXT,
        last_seen_at TEXT,
        seen_count INTEGER,
        first_run_dir TEXT,
        last_run_dir TEXT,
        state TEXT
    );
    """)
    conn.commit()
    conn.close()

    candidate_pool = {
        "candidates": [
            {"candidate_id": "cand-01", "work_title": "选中的题材"},
            {"candidate_id": "cand-02", "work_title": "未选中的备选题材"},
        ]
    }

    res = topic_backlog_adapter(candidate_pool, selected_id="cand-01", db_path=db_file, run_dir="run-1")
    assert res["selected"] == 1
    assert res["added"] == 2

    # 查库验证
    conn2 = sqlite3.connect(db_file)
    conn2.row_factory = sqlite3.Row
    items = {row["title"]: row["state"] for row in conn2.execute("SELECT title, state FROM backlog_items").fetchall()}
    assert items["选中的题材"] == "selected"
    assert items["未选中的备选题材"] == "new"
    conn2.close()


def test_evidence_sources_adapter(tmp_path: Path):
    run_dir = tmp_path / "run_sources"
    run_dir.mkdir()

    sources = [
        {
            "source_id": "src-01",
            "title": "第一手专访报道",
            "url": "http://news.example.com/1",
            "text": "这是专访正文详细记录...",
            "source_role": "confirmed-primary",
        }
    ]

    manifest = evidence_sources_adapter(run_dir, sources)
    assert manifest["sources_count"] == 1
    assert (run_dir / "source-manifest.json").exists()
    assert (run_dir / "sources" / "src-01.clean.md").exists()
    assert len(manifest["sources"][0]["sha256"]) == 64


def test_build_gate_registry_report(tmp_path: Path):
    run_dir = tmp_path / "run_gates"
    run_dir.mkdir()
    review_dir = run_dir / "review"
    review_dir.mkdir()

    # 写入假标题冻结
    (review_dir / "title-freeze.json").write_text(
        json.dumps({"status": "frozen_ok", "title": "测试标题"}, ensure_ascii=False),
        encoding="utf-8"
    )

    report = build_gate_registry_report(run_dir)
    assert report["gates"]["title_freeze"]["status"] == "pass"
    assert report["gates"]["prose_pilot"]["status"] == "not_run"  # draft.md 缺失，显式报告 not_run
    assert report["gates"]["zhuque_detector"]["status"] == "not_run"
    assert (review_dir / "gate-registry-report.json").exists()
