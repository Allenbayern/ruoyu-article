"""run_gates：日更共享门禁接线的测试（2026-09-15 制度化）。"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from article_group.git_hygiene import validate_infra_ready
from article_group.run_gates import (
    build_assertion_coverage_gate,
    build_compliance_gate_record,
    build_compliance_not_run_record,
    build_git_hygiene_snapshot,
    build_independent_review_gate,
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
    assert summary["claim_source_provenance"] == "fail"
    assert summary["editorial_protocol"] == "fail"
    assert summary["independent_review"] == "fail"
    assert summary["topic_five_questions"] == "fail"
    assert summary["compliance_gate"] == "not_run"
    assert set(writes) == {
        "task-hierarchy-validation-report.json",
        "review/gates/claim-source-check.json",
        "review/gates/editorial-protocol.json",
        "review/gates/independent-review.json",
        "review/gates/topic-five-questions.json",
        "review/gates/git-hygiene.json",
        "review/gates/compliance-gate.json",
        "review/gates/assertion-coverage.json",
        "review/gates/editorial-gate.json",
    }
    hierarchy = writes["task-hierarchy-validation-report.json"]
    assert hierarchy["pass"] is False
    assert "missing:group_manifest" in hierarchy["errors"]
    claims = writes["review/gates/claim-source-check.json"]
    assert claims["pass"] is False
    assert "missing:material_packs" in claims["errors"]
    editorial = writes["review/gates/editorial-protocol.json"]
    assert editorial["pass"] is False
    assert "missing:article_tasks" in editorial["errors"]
    independent = writes["review/gates/independent-review.json"]
    assert independent["pass"] is False
    assert "missing:article_tasks" in independent["errors"]
    five_questions = writes["review/gates/topic-five-questions.json"]
    assert five_questions["pass"] is False
    assert "missing:topic_five_questions" in five_questions["errors"]


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


def test_independent_review_gate_blocks_completed_non_approve(tmp_path):
    # ⑧：L2 已完成但 decision 非 approve* → 内容阻塞。
    import json

    (tmp_path / "task-hierarchy").mkdir()
    (tmp_path / "task-hierarchy/article-task-art-001.json").write_text(
        json.dumps({"article_id": "art-001"}), encoding="utf-8"
    )
    (tmp_path / "review").mkdir()
    (tmp_path / "review/art-001").mkdir(parents=True)
    (tmp_path / "review/art-001/independent-review.json").write_text(
        json.dumps({"decision": "needs_changes", "status": "DONE"}), encoding="utf-8"
    )
    report = build_independent_review_gate(tmp_path)
    assert report["pass"] is False
    assert "gate:independent_review:art-001:decision:needs_changes" in report["errors"]

    (tmp_path / "review/art-001/independent-review.json").write_text(
        json.dumps({"decision": "human_review_required", "status": "PENDING"}), encoding="utf-8"
    )
    report = build_independent_review_gate(tmp_path)
    assert report["pass"] is True


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


# --- 正文断言 ↔ 账本覆盖门禁（2026-09-18，B1）--------------------------------


def _assertion_run(run_root: Path, *, body: str, ledger: str) -> Path:
    import json

    (run_root / "task-hierarchy").mkdir(parents=True, exist_ok=True)
    (run_root / "task-hierarchy/article-task-art-001.json").write_text(
        json.dumps({"article_id": "art-001"}), encoding="utf-8"
    )
    (run_root / "delivery/art-001").mkdir(parents=True, exist_ok=True)
    (run_root / "delivery/art-001/delivery.md").write_text(f"# 标题\n\n{body}\n", encoding="utf-8")
    (run_root / "material-packs").mkdir(parents=True, exist_ok=True)
    (run_root / "material-packs/art-001.json").write_text(
        json.dumps({"obtained_facts_by_source": {"src-a": [ledger]}}), encoding="utf-8"
    )
    (run_root / "review/art-001").mkdir(parents=True, exist_ok=True)
    return run_root


def test_assertion_coverage_gate_blocks_an_unbacked_time_span(tmp_path):
    """daily-008 漏过的那一类：读者面写了跨度，账本里没有对应条目。"""

    _assertion_run(tmp_path, body="十几年过去，这句台词还在被引用。", ledger="剧组在片场拍了一百天。")

    report = build_assertion_coverage_gate(tmp_path)

    assert report["pass"] is False
    assert report["checked_articles"] == 1
    assert any("assertion_not_in_ledger:time_span" in error for error in report["errors"])
    assert report["articles"][0]["article_id"] == "art-001"


def test_assertion_coverage_gate_passes_when_the_ledger_covers_the_claim(tmp_path):
    _assertion_run(
        tmp_path,
        body="十几年过去，这句台词还在被引用。",
        ledger="十几年过去，这句台词还在被引用（观众行为观察）。",
    )

    report = build_assertion_coverage_gate(tmp_path)

    assert report["pass"] is True
    assert report["errors"] == []


def test_assertion_coverage_gate_records_warnings_without_blocking(tmp_path):
    """引号/数字类缺口只记录：009 的 warning 就是这一类，不阻断。"""

    _assertion_run(tmp_path, body="他说：“我只拍我信的。”全片 135 分钟。", ledger="他谈了创作方法。")

    report = build_assertion_coverage_gate(tmp_path)

    assert report["pass"] is True
    assert any("quote" in warning for warning in report["warnings"])


def test_assertion_coverage_gate_flags_a_missing_delivery(tmp_path):
    import json

    (tmp_path / "task-hierarchy").mkdir()
    (tmp_path / "task-hierarchy/article-task-art-001.json").write_text(
        json.dumps({"article_id": "art-001"}), encoding="utf-8"
    )

    report = build_assertion_coverage_gate(tmp_path)

    assert report["pass"] is False
    assert report["errors"] == ["art-001:delivery_missing"]


def test_assertion_coverage_gate_writes_per_article_reports(tmp_path):
    _assertion_run(tmp_path, body="十几年过去，这句台词还在被引用。", ledger="剧组在片场拍了一百天。")
    writes: dict[str, dict] = {}

    build_assertion_coverage_gate(
        tmp_path, write_article_reports=lambda rel, value: writes.__setitem__(rel, value)
    )

    assert "review/art-001/assertion-coverage.json" in writes
    assert writes["review/art-001/assertion-coverage.json"]["aid"] == "art-001"


def test_run_all_gates_blocks_on_an_unbacked_assertion(tmp_path, capsys):
    _assertion_run(tmp_path, body="十几年过去，这句台词还在被引用。", ledger="剧组在片场拍了一百天。")

    with pytest.raises(SystemExit) as exc:
        run_all_gates(tmp_path, lambda rel, value: None)
    assert exc.value.code == 1
    assert "assertion_not_in_ledger" in capsys.readouterr().err

    summary = run_all_gates(tmp_path, lambda rel, value: None, fail_on_error=False)
    assert summary["assertion_coverage"] == "fail"
