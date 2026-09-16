"""step_log: append-only step ledger for a run.

Why this exists (daily-008 复盘, 2026-09-17):
the run's 65 evidence files were all rewritten in the same second by the final
packaging step, so ``mtime`` could not answer "which stage ran when", and a
56-minute window with zero artifact writes was unexplainable after the fact.
This module appends one JSON line per stage — name, start, end, status,
artifacts with hashes, notes — so the timeline survives packaging.

Properties:
- **append-only**: never rewrites earlier lines, so it cannot erase evidence;
- **failure is recorded, not raised**: an exception inside a stage is logged as
  ``status=failed`` and then re-raised to the caller (the engine's own error
  handling is unchanged);
- **advisory**: the log is evidence of *what the pipeline did*, never an
  authorization. ``publication_authorization`` stays untouched everywhere.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

STEP_LOG_NAME = "step-log.jsonl"
SCHEMA_VERSION = "run-step-log-v1"
GAP_ALERT_SECONDS = 120


def _now() -> _dt.datetime:
    return _dt.datetime.now().astimezone()


def _stamp(value: _dt.datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_artifacts(root: Path, paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    """Hash the artifacts a stage produced (missing files are recorded as such)."""
    out: list[dict[str, Any]] = []
    for raw in paths:
        path = Path(raw)
        resolved = path if path.is_absolute() else root / path
        try:
            relative = str(resolved.relative_to(root))
        except ValueError:
            relative = str(resolved)
        entry: dict[str, Any] = {"path": relative}
        if resolved.is_file():
            entry["sha256"] = sha256_file(resolved)
            entry["bytes"] = resolved.stat().st_size
        else:
            entry["missing"] = True
        out.append(entry)
    return out


def step_log_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / STEP_LOG_NAME


def record_step(
    run_dir: str | Path,
    *,
    name: str,
    started_at: _dt.datetime,
    finished_at: _dt.datetime | None = None,
    status: str = "ok",
    artifacts: Iterable[str | Path] = (),
    note: str = "",
    error: str = "",
) -> dict[str, Any]:
    """Append one step record; returns the record that was written."""
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    finished = finished_at or _now()
    entry: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "status": status,
        "started_at": _stamp(started_at),
        "finished_at": _stamp(finished),
        "seconds": round((finished - started_at).total_seconds(), 3),
        "artifacts": snapshot_artifacts(root, artifacts),
    }
    if note:
        entry["note"] = note
    if error:
        entry["error"] = error
    with step_log_path(root).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


class StepLog:
    """Context manager: ``with StepLog(run_dir, "discovery"): discovery()``."""

    def __init__(
        self,
        run_dir: str | Path,
        name: str,
        *,
        artifacts: Iterable[str | Path] = (),
        note: str = "",
    ) -> None:
        self.run_dir = Path(run_dir)
        self.name = name
        self.artifacts = list(artifacts)
        self.note = note
        self.started_at = _now()
        self.entry: dict[str, Any] | None = None

    def __enter__(self) -> "StepLog":
        return self

    def __exit__(self, exc_type, exc, _tb) -> bool:
        error = "" if exc is None else f"{exc_type.__name__}:{exc}"[:300]
        self.entry = record_step(
            self.run_dir,
            name=self.name,
            started_at=self.started_at,
            status="failed" if exc is not None else "ok",
            artifacts=self.artifacts,
            note=self.note,
            error=error,
        )
        return False  # never swallow the exception


def read_steps(run_dir: str | Path) -> list[dict[str, Any]]:
    """Read the append-only log; malformed lines are skipped, not fatal."""
    path = step_log_path(run_dir)
    if not path.is_file():
        return []
    steps: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            steps.append(dict(payload))
    return steps


def _parse(stamp: object) -> _dt.datetime | None:
    if not isinstance(stamp, str):
        return None
    try:
        return _dt.datetime.fromisoformat(stamp)
    except ValueError:
        return None


def timeline(run_dir: str | Path) -> dict[str, Any]:
    """Summarize the run: per-step duration, and idle gaps between steps."""
    steps = read_steps(run_dir)
    rows: list[dict[str, Any]] = []
    previous_end: _dt.datetime | None = None
    total_idle = 0.0
    for step in steps:
        started, finished = _parse(step.get("started_at")), _parse(step.get("finished_at"))
        gap = 0.0
        if started is not None and previous_end is not None:
            gap = max(0.0, (started - previous_end).total_seconds())
            total_idle += gap
        rows.append({
            "name": step.get("name"),
            "status": step.get("status"),
            "started_at": step.get("started_at"),
            "finished_at": step.get("finished_at"),
            "seconds": step.get("seconds"),
            "gap_before_seconds": round(gap, 3),
            "artifacts": len(step.get("artifacts") or []),
            "error": step.get("error", ""),
        })
        if finished is not None:
            previous_end = finished
    wall = 0.0
    if rows:
        first, last = _parse(rows[0]["started_at"]), _parse(rows[-1]["finished_at"])
        if first and last:
            wall = (last - first).total_seconds()
    return {
        "schema_version": SCHEMA_VERSION,
        "run_dir": str(run_dir),
        "steps": rows,
        "step_count": len(rows),
        "failed_steps": [row["name"] for row in rows if row["status"] == "failed"],
        "wall_seconds": round(wall, 3),
        "idle_seconds": round(total_idle, 3),
        "big_gaps": [
            {"name": row["name"], "gap_seconds": row["gap_before_seconds"]}
            for row in rows if row["gap_before_seconds"] >= GAP_ALERT_SECONDS
        ],
        "publication_authorization": "not_authorized",
        "advisory": True,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        f"# 运行步骤日志 · {report.get('run_dir', '')}",
        "",
        f"- 步骤数：{report.get('step_count')}　墙钟：{report.get('wall_seconds')}s　"
        f"空档合计：{report.get('idle_seconds')}s",
        f"- 失败步骤：{report.get('failed_steps') or '无'}",
        f"- ≥{GAP_ALERT_SECONDS}s 空档：{report.get('big_gaps') or '无'}",
        "",
        "| 步骤 | 状态 | 开始 | 结束 | 耗时(s) | 前置空档(s) | 产物 |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in report.get("steps", []):
        lines.append(
            f"| {row['name']} | {row['status']} | {str(row['started_at'])[11:19]} | "
            f"{str(row['finished_at'])[11:19]} | {row['seconds']} | "
            f"{row['gap_before_seconds']} | {row['artifacts']} |"
        )
    lines.append("")
    lines.append("> 本日志是流程证据，不构成任何发布授权（publication_authorization: not_authorized）。")
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m article_group.step_log",
        description="查看 run 的步骤日志（耗时、空档、失败步骤、产物）",
    )
    parser.add_argument("run_root", type=Path, help="run 根目录")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--markdown", type=Path, default=None,
                        help="把 Markdown 版时间线写到指定文件（如 <run>/STEP-LOG.md）")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = timeline(args.run_root)
    if args.markdown is not None:
        args.markdown.write_text(render_markdown(report), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if not report["steps"]:
        print(f"{args.run_root}: 无步骤日志（{STEP_LOG_NAME} 不存在）")
        return 0
    print(f"步骤数 {report['step_count']}　墙钟 {report['wall_seconds']}s　"
          f"空档合计 {report['idle_seconds']}s")
    for row in report["steps"]:
        flag = "!" if row["status"] == "failed" else " "
        gap = f"+{row['gap_before_seconds']}s 空档" if row["gap_before_seconds"] >= GAP_ALERT_SECONDS else ""
        print(f"{flag} {str(row['started_at'])[11:19]} {str(row['finished_at'])[11:19]} "
              f"{row['seconds']:>8.2f}s  {row['name']}  {gap}")
    if report["big_gaps"]:
        print(f"≥{GAP_ALERT_SECONDS}s 空档：{report['big_gaps']}")
    return 0


__all__ = [
    "STEP_LOG_NAME",
    "SCHEMA_VERSION",
    "GAP_ALERT_SECONDS",
    "StepLog",
    "record_step",
    "read_steps",
    "timeline",
    "render_markdown",
    "step_log_path",
    "snapshot_artifacts",
    "sha256_file",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
