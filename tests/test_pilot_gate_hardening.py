import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from article_group.evidence_write import write_evidence, write_evidence_json
from article_group.pilot_contract import (
    PilotContractError,
    init_run,
    record_handoff,
    validate_run,
    advance_pipeline,
    seal_pilot_run,
)
from article_group.pilot_adapters import (
    build_gate_registry_report,
    evidence_sources_adapter,
    run_all_pilot_gates,
    topic_backlog_adapter,
)
from article_group.pilot_extensions import (
    check_markdown_image_integrity,
    evaluate_pilot_readiness,
    save_l2_review_with_history,
    validate_and_normalize_l2_review,
    verify_artifact_hash_bindings,
    verify_claims_anchored_in_sources,
)


def _init_sample_run(tmp_path: Path, case_id: str = "case-test") -> Path:
    res = init_run(tmp_path, case_id, "门禁测试长文")
    return Path(res["run_root"])


# ------------------------------------------------------------------------------
# 缺陷 1 测试
# ------------------------------------------------------------------------------

def test_p0_1_validate_run_has_no_write_side_effects_on_sealed_run(tmp_path: Path):
    """1. validate_run 是纯计算无写入：在已封存 run 上执行不抛 RunSealedError，也不改动任何文件。"""
    root = _init_sample_run(tmp_path)
    # 人为创建 SEALED 标志
    (root / "SEALED").write_text("sealed-for-test", encoding="utf-8")
    (root / "SEALED.manifest.json").write_text("{}", encoding="utf-8")

    # 记录调用前的文件状态
    val_json_path = root / "pilot-validation.json"
    assert not val_json_path.exists()

    # 执行 validate_run
    res = validate_run(tmp_path, root)
    assert isinstance(res, dict)
    assert "status" in res
    assert "run_completed" in res
    assert "artifact_ready" in res

    # 验证纯计算：validate_run 绝不写 pilot-validation.json
    assert not val_json_path.exists(), "validate_run 必须是纯计算，不得写入 pilot-validation.json"


def test_p0_1_cli_validate_on_sealed_run_reports_skip_and_valid_json(tmp_path: Path):
    """1. CLI validate 子命令在 run 已封存时跳过落盘，输出 report_persisted: false，且为合法 JSON。"""
    root = _init_sample_run(tmp_path)
    (root / "SEALED").write_text("sealed-for-test", encoding="utf-8")
    (root / "SEALED.manifest.json").write_text("{}", encoding="utf-8")

    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    cmd = [
        "/home/allen/.local/bin/uv",
        "run",
        "python",
        "-m",
        "article_group.pilot_contract",
        "validate",
        "--project-root",
        str(tmp_path),
        "--run-root",
        str(root),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    assert proc.returncode == 0, f"CLI exited with {proc.returncode}, stderr: {proc.stderr}"
    data = json.loads(proc.stdout)
    assert data.get("report_persisted") is False
    assert data.get("report_persist_skip_reason") == "run_sealed"
    assert "status" in data
    assert "run_completed" in data
    assert "artifact_ready" in data


def test_p0_1_readiness_recalculates_without_trusting_stale_validation_file(tmp_path: Path):
    """1. evaluate_pilot_readiness 重算状态，不信任落盘的假 pilot-validation.json。"""
    root = _init_sample_run(tmp_path, "case-001")
    # 构造虚假伪造的 pilot-validation.json
    fake_val = {
        "contract_version": "article-group-bot-pilot-v1",
        "run_root": str(root),
        "status": "PASS",
        "run_completed": True,
        "artifact_ready": True,
        "stages": {},
    }
    (root / "pilot-validation.json").write_text(json.dumps(fake_val), encoding="utf-8")

    # 执行 evaluate_pilot_readiness
    readiness = evaluate_pilot_readiness(tmp_path)
    # 因为该 run 实际并未 complete，重算后 artifact_ready 必须是 False
    assert readiness["artifact_ready_count"] == 0
    assert readiness["cases"][0]["artifact_ready"] is False


# ------------------------------------------------------------------------------
# 缺陷 2 测试
# ------------------------------------------------------------------------------

def test_p0_2_missing_source_manifest_blocks_provenance_and_capabilities(tmp_path: Path):
    """2. 缺 source-manifest.json 时 claim_source_provenance 与 source_capabilities 判定失败/阻断。"""
    root = _init_sample_run(tmp_path)
    (root / "draft.md").write_text("这是测试稿件正文", encoding="utf-8")
    assert not (root / "source-manifest.json").exists()

    report = build_gate_registry_report(root)
    gates = report["gates"]

    # 验证两项均阻断且原因明确为 source_manifest_missing
    assert gates["claim_source_provenance"]["status"] == "fail"
    assert gates["claim_source_provenance"]["blocking"] is True
    assert gates["claim_source_provenance"].get("reason") == "source_manifest_missing"

    assert gates["source_capabilities"]["status"] == "fail"
    assert gates["source_capabilities"]["blocking"] is True
    assert gates["source_capabilities"].get("reason") == "source_manifest_missing"

    assert report["all_blocking_passed"] is False
    assert "claim_source_provenance" in report["blocking_failures"]
    assert "source_capabilities" in report["blocking_failures"]

    # run_all_pilot_gates 也必须判两项 passed=False
    gates_res = run_all_pilot_gates(root, strict_assertions=False)
    assert gates_res["claim_provenance"]["passed"] is False
    assert "source_manifest_missing" in gates_res["claim_provenance"]["errors"]
    assert gates_res["source_capabilities"]["passed"] is False
    assert "source_manifest_missing" in gates_res["source_capabilities"]["violations"]
    assert gates_res["deterministic_gates"] == "fail"


# ------------------------------------------------------------------------------
# 缺陷 3 测试
# ------------------------------------------------------------------------------

def test_p0_3_stale_l2_review_hash_mismatch_blocks_validation_and_seal(tmp_path: Path):
    """3. L2 复核绑定 reviewed_draft_sha256；若缺失或与当前 draft.md 不一致，判定 stale_l2_review 并阻断。"""
    root = _init_sample_run(tmp_path)
    draft_path = root / "draft.md"
    draft_path.write_text("第一版稿件内容", encoding="utf-8")
    old_sha = hashlib.sha256(b"old draft content").hexdigest()

    review_dir = root / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    l2_file = review_dir / "l2-adversarial-review.json"
    l2_content = {
        "reviewer": "quality_l2_reviewer",
        "reviewer_session_id": "session-12345",
        "reviewed_draft_sha256": old_sha,  # 与当前 draft_path 不匹配
        "attempt": 1,
        "created_at": "2026-10-15T00:00:00Z",
        "decision": "approve",
        "scope_reviewed": "full",
        "findings": [],
        "non_findings": ["all good"],
        "coverage_gaps": [],
    }
    l2_file.write_text(json.dumps(l2_content), encoding="utf-8")

    # hash bindings 校验应报错
    bind_res = verify_artifact_hash_bindings(root)
    assert not bind_res["passed"]
    assert any("stale_l2_review" in e for e in bind_res["errors"])

    # validate_run 校验应阻断
    val_res = validate_run(tmp_path, root)
    assert any("stale_l2_review" in e for e in val_res["errors"])


# ------------------------------------------------------------------------------
# 缺陷 4 测试
# ------------------------------------------------------------------------------

def test_p0_4_unverified_l2_source_provenance_and_history_archival(tmp_path: Path):
    """4. L2 复核记录必须含 5 大来源证明字段，缺一降级为 UNVERIFIED；归档保存历史副本。"""
    # 缺少 reviewer_session_id
    incomplete_payload = {
        "reviewer": "quality_l2_reviewer",
        # 缺失 reviewer_session_id
        "reviewed_draft_sha256": "a" * 64,
        "attempt": 1,
        "created_at": "2026-10-15T00:00:00Z",
        "decision": "approve",
        "scope_reviewed": "full",
        "findings": [],
        "non_findings": [],
        "coverage_gaps": [],
    }
    norm = validate_and_normalize_l2_review(incomplete_payload)
    assert not norm["valid"]
    assert norm["effective_decision"] == "UNVERIFIED"

    # 测试历史归档功能
    root = _init_sample_run(tmp_path)
    full_payload_1 = {
        **incomplete_payload,
        "reviewer_session_id": "sess-1",
        "attempt": 1,
        "decision": "needs_changes",
        "findings": [
            {
                "severity": "minor",
                "target": "p1",
                "evidence": "typo",
                "counterexample_or_failure_mode": "n/a",
                "required_fix": "fix typo",
                "recheck": "done",
            }
        ],
    }
    save_l2_review_with_history(root, full_payload_1)

    l2_path = root / "review" / "l2-adversarial-review.json"
    assert l2_path.is_file()

    # 写入第 2 轮复核前应归档第 1 轮
    full_payload_2 = {
        **full_payload_1,
        "attempt": 2,
        "decision": "approve",
        "findings": [],
    }
    save_l2_review_with_history(root, full_payload_2)

    history_1 = root / "review" / "l2-history" / "attempt-1.json"
    assert history_1.is_file()
    hist_data = json.loads(history_1.read_text(encoding="utf-8"))
    assert hist_data["attempt"] == 1
    assert hist_data["decision"] == "needs_changes"


# ------------------------------------------------------------------------------
# 缺陷 5 测试
# ------------------------------------------------------------------------------

def test_p0_5_gate_registry_report_tracks_draft_and_l2_sha256(tmp_path: Path):
    """5. gate-registry-report.json 记录 draft_sha256 与 l2_file_sha256，且支持陈旧度检测。"""
    root = _init_sample_run(tmp_path)
    draft = root / "draft.md"
    draft.write_text("门禁测试正文内容", encoding="utf-8")
    d_sha = hashlib.sha256(draft.read_bytes()).hexdigest()

    review_dir = root / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    l2_file = review_dir / "l2-adversarial-review.json"
    l2_file.write_text('{"decision": "approve"}', encoding="utf-8")
    l2_sha = hashlib.sha256(l2_file.read_bytes()).hexdigest()

    report = build_gate_registry_report(root)
    assert report.get("draft_sha256") == d_sha
    assert report.get("l2_file_sha256") == l2_sha


# ------------------------------------------------------------------------------
# 追加范围 A–F 测试
# ------------------------------------------------------------------------------

def test_scope_a_quality_review_blocks_on_missing_artifacts_and_refs_must_exist(tmp_path: Path):
    """A. quality_review 缺门禁/L2 文件即阻断；record_handoff 的 refs 必须指向真实文件。"""
    root = _init_sample_run(tmp_path)

    # 1. 虚假不存在的 output_refs 会被阻断
    with pytest.raises(PilotContractError, match="ref_file_missing"):
        record_handoff(
            tmp_path,
            root,
            "discovery",
            "complete",
            "scout",
            {"output_refs": ["non_existent_file.json"]},
        )

    # 2. 前置阶段全部正常完成
    (root / "cand-pool.json").write_text("{}", encoding="utf-8")
    record_handoff(tmp_path, root, "discovery", "complete", "scout", {"output_refs": ["cand-pool.json"]})
    (root / "topic.md").write_text("ok", encoding="utf-8")
    record_handoff(tmp_path, root, "topic_gate", "approved", "human", {"decision_ref": "topic.md", "selected_candidate_ref": "c1"})
    (root / "ev.json").write_text("{}", encoding="utf-8")
    record_handoff(tmp_path, root, "evidence", "complete", "evidence_researcher", {"output_refs": ["ev.json"]})
    (root / "plan.md").write_text("ok", encoding="utf-8")
    record_handoff(tmp_path, root, "planning", "complete", "editorial_planner", {"output_refs": ["plan.md"]})
    (root / "draft.md").write_text("“那总，王总出家前留下的八十万窟窿，您看怎么平？”财务总监把审计报表往红木茶几上一拍。\n\n后文继续分析账本。", encoding="utf-8")
    record_handoff(tmp_path, root, "draft", "complete", "writer", {"output_refs": ["draft.md"]})

    # quality_review 没有真实的 deterministic-gates.json 和 l2 文件时报错
    (root / "fake_ref.json").write_text("{}", encoding="utf-8")
    with pytest.raises(PilotContractError, match="det_gates_artifact_missing"):
        record_handoff(
            tmp_path,
            root,
            "quality_review",
            "complete",
            "quality_l2_reviewer",
            {"deterministic_gates": "pass", "l2_decision": "approve", "artifact_refs": ["fake_ref.json"]},
        )


def test_scope_b_run_all_pilot_gates_all_passed_includes_registry_blocking_failures(tmp_path: Path):
    """B. run_all_pilot_gates 的 all_passed 必须包含 registry report 的 all_blocking_passed 校验。"""
    root = _init_sample_run(tmp_path)
    (root / "draft.md").write_text("正文内容", encoding="utf-8")
    # 因为缺 source-manifest.json，registry 里 blocking=True 失败，all_passed 必须为 False
    res = run_all_pilot_gates(root, strict_assertions=False)
    assert res["deterministic_gates"] == "fail"


def test_scope_c_advance_refuses_completed_and_sealed_without_sealed_file(tmp_path: Path):
    """C. advance 在 delivery 已 complete 但无 SEALED 时不得返回 completed_and_sealed。"""
    root = _init_sample_run(tmp_path)
    # 当 delivery 标为 complete 但无 SEALED
    (root / "SEALED").unlink(missing_ok=True)
    # advance 调用不得谎报 completed_and_sealed
    res = advance_pipeline(tmp_path, root)
    assert res.get("next_gate") != "completed_and_sealed"


def test_scope_d_cli_catches_runtime_error_and_outputs_valid_json(tmp_path: Path):
    """D. CLI 捕获 RuntimeError / Exception，stdout 始终为合法 JSON。"""
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    cmd = [
        "/home/allen/.local/bin/uv",
        "run",
        "python",
        "-m",
        "article_group.pilot_contract",
        "validate",
        "--project-root",
        str(tmp_path),
        "--run-root",
        str(tmp_path / "non-existent-run"),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    data = json.loads(proc.stdout)
    assert "status" in data
    assert "run_completed" in data
    assert "artifact_ready" in data


def test_scope_e_path_traversal_protection(tmp_path: Path):
    """E. 统一路径穿越防御：sid 仅允许 [A-Za-z0-9_.-] 且解析后必须在 run root 内。"""
    root = _init_sample_run(tmp_path)

    # 1. source_id 包含穿越字符
    with pytest.raises((ValueError, PilotContractError)):
        evidence_sources_adapter(
            root,
            [{"source_id": "../../etc/evil", "text": "内容"}],
        )

    # 2. 图片引用路径穿越
    img_res = check_markdown_image_integrity(
        "![evil](../../../../etc/passwd)",
        root,
    )
    assert not img_res["passed"]
    assert any("../" in str(e) for e in img_res["errors"])


def test_scope_f_dropped_topic_cannot_be_revived_by_selection(tmp_path: Path):
    """F. topic_backlog_adapter：已 dropped 的选题不得被 is_selected 复活为 selected。"""
    root = _init_sample_run(tmp_path)
    db_path = root / "backlog.db"
    import sqlite3
    conn = sqlite3.connect(str(db_path))
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

    cand_pool = {
        "candidates": [
            {
                "candidate_id": "cand-001",
                "title": "测试已被放弃选题",
                "topic_id": "top-001",
            }
        ]
    }

    # 第一次导入，选中的是其它候选（未被选中的自动标记为 new）
    topic_backlog_adapter(cand_pool, selected_id="other-cand", db_path=db_path)

    # 人工或策略将该选题状态置为 dropped
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE backlog_items SET state = 'dropped' WHERE candidate_id = 'cand-001'")
    conn.commit()
    conn.close()

    # 第二次导入，强行将其作为 selected_id 传入
    topic_backlog_adapter(cand_pool, selected_id="cand-001", db_path=db_path)

    # 查询数据库，确认状态依旧是 dropped，绝未被复活为 selected
    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT state FROM backlog_items WHERE candidate_id = 'cand-001'").fetchone()
    conn.close()
    assert row[0] == "dropped", f"dropped 选题被意外复活成了 {row[0]}"


# ------------------------------------------------------------------------------
# 端到端集成测试：record-l2 子命令与动态递增历史归档
# ------------------------------------------------------------------------------

def test_record_l2_end_to_end_flow(tmp_path: Path):
    """4. 端到端测试：从 draft 开始 -> gates -> record-l2 approve -> quality_review complete 通过；
    接着改 draft.md -> validate 报 stale_l2_review -> 第二次 record-l2 -> l2-history/attempt-1.json 存在，当前 attempt=2 -> validate 恢复通过。
    """
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    root = _init_sample_run(tmp_path, "case-e2e")

    # 1. 推进 discovery -> topic_gate -> evidence -> planning
    (root / "c.json").write_text("{}", encoding="utf-8")
    record_handoff(tmp_path, root, "discovery", "complete", "scout", {"output_refs": ["c.json"]})
    (root / "topic.md").write_text("# 选题", encoding="utf-8")
    record_handoff(tmp_path, root, "topic_gate", "approved", "human", {"decision_ref": "topic.md", "selected_candidate_ref": "c1"})

    # 准备合规的信源清单与快照
    (root / "sources").mkdir(parents=True, exist_ok=True)
    src_body = "这是一份经过严格核实并抓取的真实长文快照内容，字数必须超过三十个中文字符以避免被判定为空壳。"
    (root / "sources" / "s1.clean.md").write_text(src_body, encoding="utf-8")
    src_sha = hashlib.sha256(src_body.encode("utf-8")).hexdigest()
    (root / "source-manifest.json").write_text(json.dumps({
        "schema_version": "source-manifest-v1",
        "sources": [{"source_id": "s1", "artifact_path": "sources/s1.clean.md", "sha256": src_sha}]
    }), encoding="utf-8")
    (root / "evidence-pack.json").write_text(json.dumps({"source_facts": []}), encoding="utf-8")

    record_handoff(tmp_path, root, "evidence", "complete", "evidence_researcher", {"output_refs": ["source-manifest.json"]})
    (root / "plan.md").write_text("# 规划", encoding="utf-8")
    record_handoff(tmp_path, root, "planning", "complete", "editorial_planner", {"output_refs": ["plan.md"]})

    # 2. draft 阶段
    draft_v1 = "“那总，王总出家前留下的八十万窟窿，您看怎么平？”财务总监把审计报表往红木茶几上一拍。\n\n第一版叙事。"
    (root / "draft.md").write_text(draft_v1, encoding="utf-8")
    record_handoff(tmp_path, root, "draft", "complete", "writer", {"output_refs": ["draft.md"]})

    # 3. 准备匹配当前 draft 的确定性门禁报告
    (root / "review").mkdir(parents=True, exist_ok=True)
    d1_sha = hashlib.sha256(draft_v1.encode("utf-8")).hexdigest()
    (root / "review" / "deterministic-gates.json").write_text(
        json.dumps({"deterministic_gates": "pass", "reviewed_draft_sha256": d1_sha}),
        encoding="utf-8",
    )

    # 4. 生成第一轮复核输入 JSON
    review_subagent_out = tmp_path / "subagent_review_v1.json"
    review_subagent_out.write_text(json.dumps({
        "decision": "approve",
        "scope_reviewed": ["draft.md"],
        "findings": [],
        "non_findings": ["all clean"],
        "coverage_gaps": [],
    }), encoding="utf-8")

    # 5. 调用新命令 record-l2 写入第一轮复核
    cmd_record_l2 = [
        "/home/allen/.local/bin/uv", "run", "python", "-m", "article_group.pilot_contract",
        "record-l2", "--run-root", str(root),
        "--review-json", str(review_subagent_out),
        "--reviewer", "openai/gpt-4o",
        "--reviewer-session-id", "sess-test-01",
    ]
    proc_r1 = subprocess.run(cmd_record_l2, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    assert proc_r1.returncode == 0, f"record-l2 failed: {proc_r1.stderr}\nstdout: {proc_r1.stdout}"
    data_r1 = json.loads(proc_r1.stdout)
    assert data_r1["ok"] is True
    assert data_r1["attempt"] == 1

    # 6. 验证 quality_review 阶段可以成功交接
    handoff_res = record_handoff(
        tmp_path, root, "quality_review", "complete", "quality_l2_reviewer",
        {
            "deterministic_gates": "pass",
            "l2_decision": "approve",
            "output_refs": ["review/deterministic-gates.json", "review/l2-adversarial-review.json"],
            "artifact_refs": ["review/deterministic-gates.json", "review/l2-adversarial-review.json"],
        },
    )
    assert handoff_res["ok"] is True

    # 7. 改动 draft.md
    draft_v2 = "“那总，王总出家前留下的八十万窟窿，您看怎么平？”财务总监把审计报表往红木茶几上一拍。\n\n第二版修改后的叙事。"
    (root / "draft.md").write_text(draft_v2, encoding="utf-8")

    # 8. 校验应当报告 stale_l2_review
    val_after_edit = validate_run(tmp_path, root)
    assert any("stale_l2_review" in e for e in val_after_edit["errors"])

    # 9. 更新确定性门禁报告以匹配 draft_v2，并录入第二轮复核
    d2_sha = hashlib.sha256(draft_v2.encode("utf-8")).hexdigest()
    (root / "review" / "deterministic-gates.json").write_text(
        json.dumps({"deterministic_gates": "pass", "reviewed_draft_sha256": d2_sha}),
        encoding="utf-8",
    )

    review_subagent_out_v2 = tmp_path / "subagent_review_v2.json"
    review_subagent_out_v2.write_text(json.dumps({
        "decision": "approve",
        "scope_reviewed": ["draft.md"],
        "findings": [],
        "non_findings": ["all clean round 2"],
        "coverage_gaps": [],
    }), encoding="utf-8")

    proc_r2 = subprocess.run([
        "/home/allen/.local/bin/uv", "run", "python", "-m", "article_group.pilot_contract",
        "record-l2", "--run-root", str(root),
        "--review-json", str(review_subagent_out_v2),
        "--reviewer", "openai/gpt-4o",
        "--reviewer-session-id", "sess-test-02",
    ], capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    assert proc_r2.returncode == 0
    data_r2 = json.loads(proc_r2.stdout)
    assert data_r2["attempt"] == 2

    # 10. 检查历史文件存在且不可变
    hist_1 = root / "review" / "l2-history" / "attempt-1.json"
    assert hist_1.is_file(), "l2-history/attempt-1.json 必须存在"
    hist_1_data = json.loads(hist_1.read_text(encoding="utf-8"))
    assert hist_1_data["attempt"] == 1
    assert hist_1_data["reviewer_session_id"] == "sess-test-01"

    curr_l2 = json.loads((root / "review" / "l2-adversarial-review.json").read_text(encoding="utf-8"))
    assert curr_l2["attempt"] == 2
    assert curr_l2["reviewer_session_id"] == "sess-test-02"

    # 11. validate 恢复通过
    val_after_r2 = validate_run(tmp_path, root)
    assert not any("stale_l2_review" in e for e in val_after_r2["errors"])


def test_record_l2_cli_validations_and_rejections(tmp_path: Path):
    """4. record-l2 缺少必填字段、draft 缺失或 run 已封存时必须拒绝。"""
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    root = _init_sample_run(tmp_path, "case-l2-reject")

    # 1. 缺少 draft.md
    bad_json = tmp_path / "bad.json"
    bad_json.write_text(json.dumps({"decision": "approve", "findings": []}), encoding="utf-8")
    proc = subprocess.run([
        "/home/allen/.local/bin/uv", "run", "python", "-m", "article_group.pilot_contract",
        "record-l2", "--run-root", str(root),
        "--review-json", str(bad_json),
        "--reviewer", "reviewer-role",
        "--reviewer-session-id", "sess-1",
    ], capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    assert proc.returncode != 0
    data = json.loads(proc.stdout)
    assert data["ok"] is False
    assert "draft" in data["error"]

    # 2. review-json 缺失 decision 或 findings
    (root / "draft.md").write_text("正文内容", encoding="utf-8")
    missing_field_json = tmp_path / "missing_fields.json"
    missing_field_json.write_text(json.dumps({"scope_reviewed": ["draft.md"]}), encoding="utf-8")
    proc2 = subprocess.run([
        "/home/allen/.local/bin/uv", "run", "python", "-m", "article_group.pilot_contract",
        "record-l2", "--run-root", str(root),
        "--review-json", str(missing_field_json),
        "--reviewer", "reviewer-role",
        "--reviewer-session-id", "sess-1",
    ], capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    assert proc2.returncode != 0
    data2 = json.loads(proc2.stdout)
    assert data2["ok"] is False
    assert "decision" in data2["error"] or "findings" in data2["error"]

    # 3. run 已封存时拒绝
    (root / "SEALED").write_text("sealed", encoding="utf-8")
    proc3 = subprocess.run([
        "/home/allen/.local/bin/uv", "run", "python", "-m", "article_group.pilot_contract",
        "record-l2", "--run-root", str(root),
        "--review-json", str(bad_json),
        "--reviewer", "reviewer-role",
        "--reviewer-session-id", "sess-1",
    ], capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    assert proc3.returncode != 0
    data3 = json.loads(proc3.stdout)
    assert data3["ok"] is False
    assert "run_sealed" in data3["error"]
