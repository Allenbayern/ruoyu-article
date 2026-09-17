"""close_out：一条命令收尾（证据核对 → 人工验收 → 总复核 → 记录 → 复制版）。

安全口径测试：未显式 --confirm 不写任何东西；存在失效证据时阻断收尾；
人工签字只走既有合法入口（子进程调用 scripts/record_controller_acceptance.py）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from article_group.close_out import (
    MARKER_BEGIN,
    MARKER_END,
    close_out,
    main,
    write_close_out_section,
)
from article_group.step_log import read_steps


def _stub_renderer(tmp_path: Path) -> str:
    """离线渲染桩：不碰 docker/网络，返回带内联样式的片段。"""
    script = tmp_path / "stub_render.py"
    script.write_text(
        "import pathlib, sys\n"
        "text = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')\n"
        "body = ''.join(f'<p style=\"margin:0 0 1.2em\">{l}</p>' for l in text.splitlines() if l.strip())\n"
        "print(f'<section style=\"font-size:16px\">{body}</section>')\n",
        encoding="utf-8",
    )
    return f"{sys.executable} {script} {{md_file}} {{theme}}"


def _run(tmp_path: Path, *, with_approval: bool = False) -> Path:
    root = tmp_path / "daily-900"
    (root / "delivery" / "art-001").mkdir(parents=True)
    (root / "review" / "art-001").mkdir(parents=True)
    (root / "delivery" / "art-001" / "delivery.md").write_text("# 标题\n\n正文。\n", encoding="utf-8")
    (root / "batch.json").write_text(json.dumps({
        "articles": [{"article_id": "art-001", "gate_status": {"controller_acceptance": "pending",
                                                              "article_rule_compliance": "pending"}}],
        "publication_authorization": "not_authorized",
        "delivery_state": "withheld",
    }, ensure_ascii=False), encoding="utf-8")
    (root / "review" / "final-review.json").write_text(json.dumps({
        "verdict": "PUBLISHABLE", "content_result": "PASS", "evidence_result": "PASS",
        "governance_result": "PASS", "publication_authorization": "not_authorized",
    }, ensure_ascii=False), encoding="utf-8")
    if with_approval:
        (root / "review" / "art-001" / "independent-review.json").write_text(json.dumps({
            "status": "complete", "decision": "approve",
            "artifact_sha256": "0" * 64,   # 故意与当前交付不符
        }, ensure_ascii=False), encoding="utf-8")
    return root


def _stub_runner(calls: list[list[str]]):
    def runner(argv, cwd):
        calls.append(list(argv))
        return subprocess.CompletedProcess(args=list(argv), returncode=0, stdout="ok", stderr="")
    return runner


def test_without_confirm_nothing_is_written(tmp_path: Path):
    root = _run(tmp_path)
    report = close_out(root, confirm=False)
    assert report["status"] == "confirmation_required"
    assert report["steps"] == []
    assert not (root / "RUN-RECORD.md").exists()
    assert not (root / "review" / "evidence-rebind-report.json").exists()


def test_stale_evidence_blocks_close_out(tmp_path: Path):
    root = _run(tmp_path, with_approval=True)
    calls: list[list[str]] = []
    report = close_out(root, confirm=True, runner=_stub_runner(calls))
    assert report["status"] == "blocked_stale_evidence"
    assert "independent-review.json" in report["reason"]
    assert calls == []  # 阻断在验收之前，没跑任何子进程


def test_happy_path_runs_every_step_and_writes_section(tmp_path: Path):
    root = _run(tmp_path)
    calls: list[list[str]] = []
    report = close_out(root, identity="owner", ref="会话确认", confirm=True,
                       runner=_stub_runner(calls), repo_root=tmp_path,
                       renderer_cmd=_stub_renderer(tmp_path))
    assert report["status"] == "ok", report
    assert [step["name"] for step in report["steps"]] == [
        "evidence_rebind", "controller_acceptance", "final_review",
        "run_record_machine", "wechat_render", "run_record_section", "step_log_markdown",
        "seal",
    ]
    # 人工签字走既有合法入口
    assert any(call[1].endswith("record_controller_acceptance.py") for call in calls)
    assert any("article_group.final_review" in " ".join(call) for call in calls)
    assert any("article_group.run_record" in " ".join(call) for call in calls)

    run_record = (root / "RUN-RECORD.md").read_text(encoding="utf-8")
    assert MARKER_BEGIN in run_record and MARKER_END in run_record
    assert "controller_acceptance=accepted" in run_record
    assert "署名 `owner`" in run_record
    assert "not_authorized" in run_record
    assert "art-001:article_rule_compliance" in run_record  # pending 项如实列出

    steps = [step["name"] for step in read_steps(root)]
    assert "close_out:controller_acceptance" in steps
    assert "close_out:seal" in steps
    assert (root / "STEP-LOG.md").is_file()

    # 收尾即封存：SEALED 标记含验收人与交付哈希，供后续工具守门
    from article_group.run_state import sealed_reason
    sealed = json.loads((root / "SEALED").read_text(encoding="utf-8"))
    assert sealed["sealed_by"] == "owner"
    assert sealed["schema_version"] == "run-sealed-v1"
    assert sealed["articles"][0]["article_id"] == "art-001"
    assert len(sealed["articles"][0]["delivery_sha256"]) == 64
    assert sealed_reason(root).startswith("sealed_at=")


def test_section_is_idempotent_and_not_duplicated(tmp_path: Path):
    root = _run(tmp_path)
    write_close_out_section(root, f"{MARKER_BEGIN}\n第一次\n{MARKER_END}")
    write_close_out_section(root, f"{MARKER_BEGIN}\n第二次\n{MARKER_END}")
    text = (root / "RUN-RECORD.md").read_text(encoding="utf-8")
    assert text.count(MARKER_BEGIN) == 1 and text.count(MARKER_END) == 1
    assert "第二次" in text and "第一次" not in text


def test_section_appends_heading_when_no_marker(tmp_path: Path):
    root = _run(tmp_path)
    (root / "RUN-RECORD.md").write_text("# RUN-RECORD\n\n## 8. 未验证与遗留\n\n- 某条\n", encoding="utf-8")
    write_close_out_section(root, f"{MARKER_BEGIN}\n内容\n{MARKER_END}")
    text = (root / "RUN-RECORD.md").read_text(encoding="utf-8")
    assert "## 9. 收尾与发布记录" in text
    assert "## 8. 未验证与遗留" in text  # 原有小节保留


def test_allow_stale_evidence_proceeds_and_reports(tmp_path: Path):
    root = _run(tmp_path, with_approval=True)
    calls: list[list[str]] = []
    report = close_out(root, confirm=True, allow_stale_evidence=True,
                       runner=_stub_runner(calls), renderer_cmd=_stub_renderer(tmp_path))
    assert report["status"] == "ok"
    assert calls  # 显式放行后继续
    assert "stale" not in report["reason"]


def test_failed_step_is_recorded_and_propagated(tmp_path: Path):
    root = _run(tmp_path)

    def failing_runner(argv, cwd):
        raise RuntimeError("record_controller_acceptance not found")

    with pytest.raises(RuntimeError):
        close_out(root, confirm=True, runner=failing_runner, repo_root=tmp_path)
    steps = read_steps(root)
    failed = [step for step in steps if step["status"] == "failed"]
    assert [step["name"] for step in failed] == ["close_out:controller_acceptance"]


def test_cli_requires_confirm(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    root = _run(tmp_path)
    assert main(["--run-root", str(root)]) == 1
    assert "confirmation_required" in capsys.readouterr().out


def test_close_out_never_authorizes_publication(tmp_path: Path):
    root = _run(tmp_path)
    calls: list[list[str]] = []
    report = close_out(root, confirm=True, runner=_stub_runner(calls), repo_root=tmp_path,
                       renderer_cmd=_stub_renderer(tmp_path))
    assert report["publication_authorization"] == "not_authorized"
    batch = json.loads((root / "batch.json").read_text(encoding="utf-8"))
    assert batch["publication_authorization"] == "not_authorized"
    assert batch["delivery_state"] == "withheld"
