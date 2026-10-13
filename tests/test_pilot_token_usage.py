"""Regression tests for pilot per-run token accounting (2026-10-13).

口径：只归因"工具调用参数里出现 run 根路径 / case id"的 step，因此
无关步骤不计入（保守下限），同会话全量单独保留。
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from article_group.pilot_token_usage import (
    TokenUsageError,
    case_id_from_run_root,
    collect_run_token_usage,
    record_run_token_usage,
    scan_session,
)

HAS_ZSTD = subprocess.run(["which", "zstd"], capture_output=True).returncode == 0
pytestmark = pytest.mark.skipif(not HAS_ZSTD, reason="需要 zstd 才能读取会话日志")


def _line(event: dict) -> bytes:
    return (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")


def _assistant(message_id: str, *, fresh: int, output: int, cache_read: int) -> dict:
    return {
        "type": "assistant/message",
        "data": {
            "turn": 1,
            "step": 1,
            "message": {"id": message_id, "role": "assistant", "content": []},
            "usage": {
                "inputTokens": fresh,
                "outputTokens": output,
                "cacheReadTokens": cache_read,
                "cacheWriteTokens": 0,
                "reasoningTokens": 0,
            },
        },
    }


def _tool_call(name: str, arguments: dict) -> dict:
    return {
        "type": "tool/call",
        "data": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }


def _write_session(sessions_root: Path, session_id: str, events: list[dict]) -> Path:
    session_dir = sessions_root / "--home-allen-dsh--" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    raw = b"".join(_line(event) for event in events)
    target = session_dir / "session.v4.jsonl.zstd"
    subprocess.run(["zstd", "-q", "-f", "-o", str(target)], input=raw, check=True)
    return target


def test_case_id_from_run_root() -> None:
    assert case_id_from_run_root("runs/2026-10-13/dsh-pilot-case-005") == "case-005"
    assert case_id_from_run_root("/tmp/legacy-case-001") == "legacy-case-001"


def test_scan_session_attributes_only_matching_steps(tmp_path: Path) -> None:
    run_root = tmp_path / "runs" / "2026-10-13" / "dsh-pilot-case-005"
    events = [
        {"type": "session", "id": "s-1", "cwd": "/home/allen/dsh", "delegationDepth": 0},
        {"type": "request/header", "data": {"header": {"config": {"provider": "newapi", "model": "gemini-3.8-flash-high"}}}},
        _assistant("m-1", fresh=100, output=10, cache_read=1000),
        _tool_call("read", {"file_path": str(run_root / "draft.md")}),
        _assistant("m-2", fresh=200, output=20, cache_read=2000),
        _tool_call("bash", {"command": "ls /tmp/unrelated"}),
        _assistant("m-3", fresh=300, output=30, cache_read=3000),
        _tool_call("bash", {"command": "echo 'dsh-pilot-case-005/handoffs/draft.json'"}),
    ]
    session_file = _write_session(tmp_path / "sessions", "s-1", events)

    result = scan_session(session_file, [str(run_root), "case-005"])

    assert result["model"] == "newapi/gemini-3.8-flash-high"
    assert result["session_usage"]["fresh_input"] == 600
    assert result["session_usage"]["cache_read"] == 6000
    assert result["session_raw"] == 6660
    # m-1（run 根路径）与 m-3（case id 字符串）计入；m-2 无关，不计
    assert result["matched_usage"]["fresh_input"] == 400
    assert result["matched_usage"]["cache_read"] == 4000
    assert result["matched_usage"]["output"] == 40
    assert result["matched_usage"]["steps"] == 2
    assert result["matched_raw"] == 4440


def test_collect_counts_only_matching_sessions(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    run_root = tmp_path / "runs" / "2026-10-13" / "dsh-pilot-case-005"
    run_root.mkdir(parents=True)
    _write_session(sessions, "s-hit", [
        {"type": "session", "id": "s-hit"},
        _assistant("m-1", fresh=100, output=10, cache_read=1000),
        _tool_call("read", {"file_path": str(run_root / "draft.md")}),
    ])
    _write_session(sessions, "s-miss", [
        {"type": "session", "id": "s-miss"},
        _assistant("m-2", fresh=999, output=99, cache_read=9999),
        _tool_call("read", {"file_path": "/somewhere/else.md"}),
    ])

    report = collect_run_token_usage(run_root, sessions_dir=sessions)

    assert report["case_id"] == "case-005"
    assert report["sessions_scanned"] == 2
    assert report["attributed_session_count"] == 1
    assert report["totals"]["raw_tokens"] == 1110
    assert report["totals"]["fresh_input"] == 100
    assert report["totals"]["output"] == 10
    assert report["totals"]["cache_read"] == 1000
    assert report["sessions"][0]["session_id"] == "s-hit"
    assert report["sessions"][0]["matched_share_of_session"] == 1.0
    assert report["attribution"]["method"] == "step_tool_args_match_v1"


def test_record_writes_metrics_and_changelog(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    run_root = tmp_path / "runs" / "2026-10-13" / "dsh-pilot-case-006"
    (run_root / "metrics").mkdir(parents=True)
    _write_session(sessions, "s-hit", [
        {"type": "session", "id": "s-hit"},
        _assistant("m-1", fresh=50, output=5, cache_read=500),
        _tool_call("read", {"file_path": str(run_root / "draft.md")}),
    ])

    result = record_run_token_usage(tmp_path, run_root, sessions_dir=sessions)

    assert result["ok"] is True
    written = Path(result["metrics_path"])
    assert written.is_file()
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "pilot-token-usage-v1"
    assert payload["totals"]["raw_tokens"] == 555
    assert (run_root / "evidence-changelog.jsonl").is_file()
    entries = [
        json.loads(line)
        for line in (run_root / "evidence-changelog.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(entry.get("reason") == "pilot:token-usage" for entry in entries)


def test_unknown_run_root_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(TokenUsageError):
        collect_run_token_usage(tmp_path / "nope", sessions_dir=tmp_path / "sessions")


def test_sealed_run_blocks_write_with_clear_error(tmp_path: Path) -> None:
    """封存 run 必须拒写，且给出可读错误（而不是裸 traceback）。"""
    sessions = tmp_path / "sessions"
    run_root = tmp_path / "runs" / "2026-10-13" / "dsh-pilot-case-007"
    (run_root / "metrics").mkdir(parents=True)
    (run_root / "SEALED").write_text("sealed_at=2026-10-13T18:52:10+08:00,by=controller\n", encoding="utf-8")
    _write_session(sessions, "s-hit", [
        {"type": "session", "id": "s-hit"},
        _assistant("m-1", fresh=50, output=5, cache_read=500),
        _tool_call("read", {"file_path": str(run_root / "draft.md")}),
    ])

    with pytest.raises(TokenUsageError, match="run_sealed_write_blocked"):
        record_run_token_usage(tmp_path, run_root, sessions_dir=sessions)

    # dry-run 仍然只读可用
    report = collect_run_token_usage(run_root, sessions_dir=sessions)
    assert report["totals"]["raw_tokens"] == 555
