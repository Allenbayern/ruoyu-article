"""Tests for the compliance sync CLI (five-gates checklist projection)."""

from __future__ import annotations

import json

from article_group.sync_compliance import format_gate, iter_candidate_files


def test_iter_candidate_files_reads_pool(tmp_path):
    pool = {
        "run_id": "t",
        "candidates": [
            {
                "candidate_id": "soc-01",
                "topic_type": "social",
                "five_gates": {
                    "gate1_news_license": "PASS",
                    "gate2_privacy": "PASS",
                    "gate3_judicial": "PASS",
                    "gate4_copyright": "PASS",
                    "gate5_sensationalism": "PASS",
                    "result": "PASS",
                },
            },
            {"candidate_id": "film-01", "topic_type": "film"},
        ],
    }
    path = tmp_path / "pool.json"
    path.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")

    cids = [c["candidate_id"] for _, c in iter_candidate_files(path)]
    assert cids == ["soc-01", "film-01"]


def test_iter_candidate_files_reads_directory(tmp_path):
    (tmp_path / "a.json").write_text(
        json.dumps({"candidate_id": "x", "topic_type": "social"}), encoding="utf-8"
    )
    (tmp_path / "b.json").write_text(
        json.dumps({"candidate_id": "y", "topic_type": "film"}), encoding="utf-8"
    )
    (tmp_path / "note.txt").write_text("not json", encoding="utf-8")

    cids = sorted(c["candidate_id"] for _, c in iter_candidate_files(tmp_path))
    assert cids == ["x", "y"]


def test_format_gate_renders_pass_fail_na():
    assert "✅" in format_gate("PASS")
    assert "❌" in format_gate("FAIL")
    assert "N/A" in format_gate("")


def test_sync_cli_generates_checklist(tmp_path):
    from article_group.sync_compliance import main

    pool = {
        "candidates": [
            {
                "candidate_id": "soc-01",
                "topic_type": "social",
                "recommendation": "A",
                "five_gates": {
                    "gate1_news_license": "PASS",
                    "gate2_privacy": "PASS",
                    "gate3_judicial": "PASS",
                    "gate4_copyright": "PASS",
                    "gate5_sensationalism": "PASS",
                    "result": "PASS",
                },
            },
            {"candidate_id": "film-01", "topic_type": "film", "recommendation": "B"},
        ]
    }
    in_path = tmp_path / "pool.json"
    out_path = tmp_path / "checklist.md"
    in_path.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")

    exit_code = main(["-i", str(in_path), "-o", str(out_path)])
    assert exit_code == 0

    text = out_path.read_text(encoding="utf-8")
    assert "soc-01" in text
    assert "✅ PASS" in text
    assert "film-01" not in text  # film candidates filtered out


def test_sync_cli_renders_tristate_overall_with_priority_and_processing_angle(tmp_path):
    from article_group.sync_compliance import main

    pool = {
        "candidates": [
            {
                "candidate_id": "conditional",
                "topic_type": "social",
                "recommendation": "A",
                "compliant_angle": "Use an institutional-analysis angle.",
                "five_gates": {
                    "gate1_news_license": "CONDITIONAL",
                    "gate2_privacy": "PASS",
                    "gate3_judicial": "PASS",
                    "gate4_copyright": "PASS",
                    "gate5_sensationalism": "PASS",
                    "overall": "CONDITIONAL",
                    "result": "PASS",
                },
            },
            {
                "candidate_id": "archived-fail",
                "topic_type": "social",
                "recommendation": "Archive",
                "five_gates": {
                    "gate1_news_license": "FAIL",
                    "gate2_privacy": "PASS",
                    "gate3_judicial": "PASS",
                    "gate4_copyright": "PASS",
                    "gate5_sensationalism": "PASS",
                    "result": "FAIL",
                },
            },
        ]
    }
    in_path = tmp_path / "pool.json"
    out_path = tmp_path / "checklist.md"
    in_path.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")

    assert main(["-i", str(in_path), "-o", str(out_path)]) == 0

    text = out_path.read_text(encoding="utf-8")
    assert "🟡 CONDITIONAL" in text
    assert "❌ FAIL" in text
    assert "Use an institutional-analysis angle." in text
    assert "archived-fail" in text


def test_sync_cli_handles_no_social_candidates(tmp_path):
    from article_group.sync_compliance import main

    in_path = tmp_path / "pool.json"
    out_path = tmp_path / "checklist.md"
    in_path.write_text(
        json.dumps({"candidates": [{"candidate_id": "film-01", "topic_type": "film"}]}),
        encoding="utf-8",
    )
    exit_code = main(["-i", str(in_path), "-o", str(out_path)])
    assert exit_code == 0
    assert "未发现任何社会热点候选" in out_path.read_text(encoding="utf-8")
