"""step_log：追加式步骤日志（耗时、空档、失败步骤、产物哈希）。

背景：daily-008 的 65 个证据文件被最后一次打包在同一秒重写，事后无法复原
"哪一步先跑"，且有 56 分钟无产物落盘无法解释。本模块用 append-only 的
JSONL 记录每一步，保证时间线不会被打包覆盖。
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from article_group.step_log import (
    GAP_ALERT_SECONDS,
    STEP_LOG_NAME,
    StepLog,
    main,
    read_steps,
    record_step,
    render_markdown,
    snapshot_artifacts,
    timeline,
)


def _at(hour: int, minute: int, second: int = 0) -> dt.datetime:
    return dt.datetime(2026, 9, 16, hour, minute, second).astimezone()


def test_record_step_appends_jsonl(tmp_path: Path):
    record_step(tmp_path, name="discovery", started_at=_at(10, 5), finished_at=_at(10, 6))
    record_step(tmp_path, name="source_manifest", started_at=_at(10, 6), finished_at=_at(10, 8))
    lines = (tmp_path / STEP_LOG_NAME).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["name"] == "discovery" and first["status"] == "ok"
    assert first["seconds"] == 60.0
    assert first["schema_version"] == "run-step-log-v1"


def test_log_is_append_only(tmp_path: Path):
    record_step(tmp_path, name="a", started_at=_at(10, 0), finished_at=_at(10, 1))
    before = (tmp_path / STEP_LOG_NAME).read_text(encoding="utf-8")
    record_step(tmp_path, name="b", started_at=_at(10, 1), finished_at=_at(10, 2))
    after = (tmp_path / STEP_LOG_NAME).read_text(encoding="utf-8")
    assert after.startswith(before)  # 前面的行一字未改


def test_context_manager_records_failure_and_reraises(tmp_path: Path):
    with pytest.raises(RuntimeError):
        with StepLog(tmp_path, "reviews_and_delivery"):
            raise RuntimeError("gate exploded")
    step = read_steps(tmp_path)[0]
    assert step["status"] == "failed"
    assert step["error"].startswith("RuntimeError:gate exploded")


def test_snapshot_artifacts_hashes_and_marks_missing(tmp_path: Path):
    target = tmp_path / "delivery" / "art-001"
    target.mkdir(parents=True)
    (target / "delivery.md").write_text("正文", encoding="utf-8")
    snapshot = snapshot_artifacts(tmp_path, ["delivery/art-001/delivery.md", "delivery/art-002/delivery.md"])
    assert snapshot[0]["path"] == "delivery/art-001/delivery.md"
    assert snapshot[0]["bytes"] == len("正文".encode())
    assert len(snapshot[0]["sha256"]) == 64
    assert snapshot[1]["missing"] is True


def test_timeline_reports_gap_and_idle(tmp_path: Path):
    record_step(tmp_path, name="l2_review_r1", started_at=_at(10, 27), finished_at=_at(10, 28))
    record_step(tmp_path, name="l2_review_r2", started_at=_at(11, 23), finished_at=_at(11, 24))
    report = timeline(tmp_path)
    assert report["step_count"] == 2
    assert report["steps"][1]["gap_before_seconds"] == pytest.approx(
        (dt.datetime(2026, 9, 16, 11, 23).astimezone()
         - dt.datetime(2026, 9, 16, 10, 28).astimezone()).total_seconds()
    )
    assert report["big_gaps"] == [{"name": "l2_review_r2", "gap_seconds": report["steps"][1]["gap_before_seconds"]}]
    assert report["wall_seconds"] > 0
    assert report["publication_authorization"] == "not_authorized"


def test_timeline_flags_failed_steps(tmp_path: Path):
    record_step(tmp_path, name="gates", started_at=_at(10, 0), finished_at=_at(10, 1), status="failed",
                error="gate:style_gate")
    report = timeline(tmp_path)
    assert report["failed_steps"] == ["gates"]


def test_timeline_without_log_is_empty_not_error(tmp_path: Path):
    report = timeline(tmp_path)
    assert report["steps"] == [] and report["step_count"] == 0
    assert report["big_gaps"] == []


def test_read_steps_skips_malformed_lines(tmp_path: Path):
    path = tmp_path / STEP_LOG_NAME
    path.write_text('{"name": "ok", "started_at": "2026-09-16T10:00:00+08:00", '
                    '"finished_at": "2026-09-16T10:01:00+08:00", "seconds": 60.0}\n'
                    'not json\n', encoding="utf-8")
    steps = read_steps(tmp_path)
    assert [s["name"] for s in steps] == ["ok"]


def test_render_markdown_contains_table_and_boundary(tmp_path: Path):
    record_step(tmp_path, name="discovery", started_at=_at(10, 5), finished_at=_at(10, 6))
    text = render_markdown(timeline(tmp_path))
    assert "| 步骤 | 状态 |" in text
    assert "not_authorized" in text
    assert "discovery" in text


def test_cli_prints_timeline_and_writes_markdown(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    record_step(tmp_path, name="discovery", started_at=_at(10, 5), finished_at=_at(10, 6))
    record_step(tmp_path, name="l2_review", started_at=_at(10, 27), finished_at=_at(10, 28))
    out_path = tmp_path / "STEP-LOG.md"
    assert main([str(tmp_path), "--markdown", str(out_path)]) == 0
    out = capsys.readouterr().out
    assert "步骤数 2" in out and "空档" in out
    assert out_path.is_file() and "discovery" in out_path.read_text(encoding="utf-8")


def test_cli_json_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    record_step(tmp_path, name="discovery", started_at=_at(10, 5), finished_at=_at(10, 6))
    assert main([str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["step_count"] == 1
    assert payload["steps"][0]["name"] == "discovery"


def test_cli_without_log_reports_absence(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    assert main([str(tmp_path)]) == 0
    assert "无步骤日志" in capsys.readouterr().out


def test_gap_threshold_is_two_minutes():
    assert GAP_ALERT_SECONDS == 120
