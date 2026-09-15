"""run_gates：日更共享门禁接线的测试（2026-09-15 制度化）。"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from article_group.git_hygiene import validate_infra_ready
from article_group.run_gates import (
    build_compliance_gate_record,
    build_compliance_not_run_record,
    build_git_hygiene_snapshot,
    build_task_hierarchy_report,
    run_all_gates,
)

DAILY_005 = Path("runs/2026-09-15/daily-005")
needs_daily_005 = pytest.mark.skipif(
    not (DAILY_005 / "batch.json").exists(),
    reason="runs/ 是本地审计目录（gitignore），daily-005 不在当前工作树时不跑集成断言",
)


def test_compliance_record_is_explicit_not_run():
    record = build_compliance_not_run_record()
    assert record["schema_version"] == "compliance-gate-v1"
    assert record["full_gate"] == "not_run"
    assert "social_topic" in record["full_gate_reason"]
    assert record["publication_authorization"] == "not_authorized"


def test_compliance_gate_record_not_run_for_non_social_pool():
    pool = {"candidates": [{"candidate_id": "cand-1", "topic_mode": "craft"}]}
    record = build_compliance_gate_record(pool)
    assert record["full_gate"] == "not_run"
    assert "social_topic" in record["full_gate_reason"]


def test_compliance_gate_record_missing_pool_is_not_run():
    record = build_compliance_gate_record(None)
    assert record["full_gate"] == "not_run"
    assert "候选池缺失" in record["full_gate_reason"]


def test_compliance_gate_record_enforces_social_pool():
    pool = {
        "candidates": [
            {"candidate_id": "cand-social", "topic_type": "social",
             "recommendation": "A"},  # 缺 five_gates 声明 → 硬错误
        ]
    }
    record = build_compliance_gate_record(pool)
    assert record["full_gate"] == "run"
    assert record["mode"] == "social_topic"
    assert record["social_candidates"] == 1
    assert record["pass"] is False
    assert "candidate_cand-social_social_topic_requires_five_gates" in record["errors"]


def test_compliance_gate_record_passes_valid_social_declaration():
    pool = {
        "candidates": [
            {
                "candidate_id": "cand-social",
                "topic_type": "social",
                "recommendation": "A",
                "five_gates": {
                    "gate1_news_license": "PASS",
                    "gate2_privacy": "PASS",
                    "gate3_judicial": "PASS",
                    "gate4_copyright": "PASS",
                    "gate5_sensationalism": "PASS",
                    "overall": "PASS",
                },
            }
        ]
    }
    record = build_compliance_gate_record(pool)
    assert record["full_gate"] == "run"
    assert record["pass"] is True
    assert record["errors"] == []


def test_git_hygiene_snapshot_matches_live_repo():
    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    expected_missing = validate_infra_ready(tracked)
    snapshot = build_git_hygiene_snapshot()
    assert snapshot["schema_version"] == "git-hygiene-v1"
    assert snapshot["mode"] == "infra_ready"
    assert snapshot["missing"] == expected_missing
    assert snapshot["pass"] is (not expected_missing)


def test_run_all_gates_writes_artifacts_and_reports_fail_without_exit(tmp_path):
    writes: dict[str, object] = {}

    def writer(rel: str, value: object) -> None:
        writes[rel] = value

    summary = run_all_gates(tmp_path, writer, fail_on_error=False)
    assert summary["task_hierarchy_contract"] == "fail"
    assert summary["compliance_gate"] == "not_run"
    assert set(writes) == {
        "task-hierarchy-validation-report.json",
        "review/gates/git-hygiene.json",
        "review/gates/compliance-gate.json",
    }
    hierarchy = writes["task-hierarchy-validation-report.json"]
    assert hierarchy["pass"] is False
    assert "missing:group_manifest" in hierarchy["errors"]


def test_run_all_gates_reports_social_five_gates_failure(tmp_path):
    import json

    (tmp_path / "candidate-pool.json").write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "candidate_id": "cand-social",
                        "topic_type": "social",
                        "recommendation": "A",  # 缺 five_gates 声明
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    writes: dict[str, object] = {}

    def writer(rel: str, value: object) -> None:
        writes[rel] = value

    summary = run_all_gates(tmp_path, writer, fail_on_error=False)
    assert summary["compliance_gate"] == "fail"
    compliance = writes["review/gates/compliance-gate.json"]
    assert compliance["full_gate"] == "run"
    assert compliance["pass"] is False


def test_run_all_gates_exits_nonzero_on_gate_failure(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        run_all_gates(tmp_path, lambda rel, value: None)
    assert exc.value.code == 1
    assert "RUN GATES FAILED" in capsys.readouterr().err


@needs_daily_005
def test_run_all_gates_passes_on_daily_005():
    report = build_task_hierarchy_report(DAILY_005)
    assert report["pass"] is True
    assert report["errors"] == []
