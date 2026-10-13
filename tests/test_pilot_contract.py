"""Regression tests for the manual Article Group Bot pilot contract."""

from __future__ import annotations

from pathlib import Path

from article_group.pilot_contract import (
    init_run,
    record_handoff,
    validate_run,
)


def _payload(**extra):
    payload = {
        "summary": "阶段完成",
        "output_refs": ["artifact.json"],
        "artifact_refs": ["artifact.json"],
        "next_action": "推进下一阶段",
    }
    payload.update(extra)
    return payload


def _complete_run(tmp_path: Path) -> Path:
    result = init_run(tmp_path, "case-001", "测试长文")
    root = Path(result["run_root"])
    record_handoff(tmp_path, root, "discovery", "complete", "scout", _payload())
    record_handoff(
        tmp_path,
        root,
        "topic_gate",
        "approved",
        "human",
        _payload(decision_ref="topic-decision.md", selected_candidate_ref="candidate-001"),
    )
    record_handoff(tmp_path, root, "evidence", "complete", "evidence_researcher", _payload())
    record_handoff(tmp_path, root, "planning", "complete", "editorial_planner", _payload())
    record_handoff(tmp_path, root, "draft", "complete", "writer", _payload())
    record_handoff(
        tmp_path,
        root,
        "quality_review",
        "complete",
        "quality_l2_reviewer",
        _payload(deterministic_gates="pass", l2_decision="approve", quality_gate_ref="review/gates.json"),
    )
    record_handoff(
        tmp_path,
        root,
        "final_gate",
        "approved",
        "human",
        _payload(decision_ref="final-decision.md"),
    )
    record_handoff(
        tmp_path,
        root,
        "delivery",
        "complete",
        "controller",
        _payload(artifact_status="content_ready", artifact_refs=["delivery/article.md"]),
    )
    return root


def test_initial_run_is_explicitly_in_progress_and_not_ready(tmp_path: Path):
    result = init_run(tmp_path, "case-001", "测试长文")
    report = validate_run(tmp_path, result["run_root"])

    assert report["status"] == "IN_PROGRESS"
    assert report["run_completed"] is False
    assert report["artifact_ready"] is False
    assert report["stages"]["topic_gate"] == "not_run"
    assert (Path(result["run_root"]) / "RUN-RECORD.md").is_file()


def test_complete_run_is_pass_but_publication_stays_unauthorized(tmp_path: Path):
    root = _complete_run(tmp_path)
    report = validate_run(tmp_path, root)

    assert report["status"] == "PASS"
    assert report["run_completed"] is True
    assert report["artifact_ready"] is True
    assert report["publication_authorization"] == "not_authorized"


def test_downstream_pass_after_blocked_stage_is_fail_closed(tmp_path: Path):
    result = init_run(tmp_path, "case-002")
    root = Path(result["run_root"])
    record_handoff(
        tmp_path,
        root,
        "discovery",
        "blocked",
        "scout",
        _payload(blocking_issues=["候选没有足够来源"]),
    )

    report = validate_run(tmp_path, root)
    assert report["status"] == "BLOCKED"
    assert any("downstream" not in error for error in report["errors"])


def test_quality_review_requires_deterministic_gates_and_l2_approval(tmp_path: Path):
    result = init_run(tmp_path, "case-003")
    root = Path(result["run_root"])
    record_handoff(tmp_path, root, "discovery", "complete", "scout", _payload())
    record_handoff(
        tmp_path,
        root,
        "topic_gate",
        "approved",
        "human",
        _payload(decision_ref="topic-decision.md"),
    )
    record_handoff(tmp_path, root, "evidence", "complete", "evidence_researcher", _payload())
    record_handoff(tmp_path, root, "planning", "complete", "editorial_planner", _payload())
    record_handoff(tmp_path, root, "draft", "complete", "writer", _payload())

    try:
        record_handoff(
            tmp_path,
            root,
            "quality_review",
            "complete",
            "quality_l2_reviewer",
            _payload(deterministic_gates="pass", l2_decision="needs_changes"),
        )
    except ValueError as exc:
        assert "l2_approve_required" in str(exc)
    else:  # pragma: no cover - contract must reject the handoff
        raise AssertionError("unapproved L2 handoff was accepted")


def test_cli_subcommands_end_to_end(tmp_path: Path):
    from article_group.pilot_contract import main, seal_pilot_run
    import json

    # 1. 跑通完整 run
    root = _complete_run(tmp_path)
    (root / "draft.md").write_text("# 测试标题\n\n正文叙事段落...\n", encoding="utf-8")

    # 2. 测试 readiness CLI
    ret = main(["readiness", "--project-root", str(tmp_path)])
    assert ret == 0

    # 3. 验证密封
    seal_res = seal_pilot_run(tmp_path, root, signer="controller")
    assert seal_res["ok"] is True
    assert (root / "SEALED").is_file()
    assert (root / "SEALED.manifest.json").is_file()

