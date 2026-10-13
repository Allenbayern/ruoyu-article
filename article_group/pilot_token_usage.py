"""Per-run token accounting for the Article Group pilot.

为什么需要（2026-10-13）：
试点跑了 6 例（case-001…006），run 里只落了 `coordination_seconds` /
`manual_intervention` / `l2_blocker_major`，**没有任何 token 记录**。事后只能
从 `~/.dsh/sessions/*/session.v{3,4}.jsonl.zstd` 反推，既慢又容易算错口径——
控制会话连跑 6 例会累积上下文，单看会话总量会把"每篇成本"算成 26M/例。

本模块做的事：把会话日志里的逐 step usage，**按 run 归因**落到
`<run>/metrics/token-usage.json`，并把三个数分列，不混算成本：

- `fresh_input`：新输入（未命中缓存，单价最高）
- `cache_read`：缓存重读（单价低，但量最大，是"长会话税"的可见指标）
- `output`：模型输出

归因是**保守近似**：只统计"该 step 的工具调用参数里出现 run 根路径或 case id"
的 usage。同一会话里与本文无关的步骤（方案设计、插件安装、debug、对照实验）
不会计入，因此是下限而不是全量。

读取范围只限于本机 DSH 会话目录，只读、不联网、不碰凭据；写盘点只写
`<run>/metrics/token-usage.json`，走 `evidence_write` 留底记账。

Usage::

    uv run python -m article_group.pilot_token_usage \
      --project-root . --run-root runs/2026-10-13/dsh-pilot-case-005
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Iterable, Iterator

from .evidence_write import RunSealedError, write_evidence_json
from .runs_guard import SealedWriteBlocked

SCHEMA_VERSION = "pilot-token-usage-v1"
DEFAULT_SESSIONS_ROOT = "~/.dsh/sessions"
SESSION_FILE_NAMES = ("session.v4.jsonl.zstd", "session.v3.jsonl.zstd")
DECOMPRESS_TIMEOUT_SECONDS = 180
ATTRIBUTION_METHOD = "step_tool_args_match_v1"
_ATTRIBUTION_LIMITS = [
    "只统计工具调用参数里出现 run 根路径或 case id 的 step；同一会话中的方案设计、插件安装、debug、对照实验不计入。",
    "计数为保守下限，不是会话全量；控制会话里与本文无关的上下文重读不会被分摊进来。",
    "跨 run 的 step 会同时计入各自 run，因此各 run 之和可能大于会话全量。",
]


class TokenUsageError(RuntimeError):
    """token 归因失败（会话目录不可读、zstd 缺失、日志损坏等）。"""


def sessions_root(override: str | Path | None = None) -> Path:
    if override:
        return Path(override).expanduser()
    env = os.environ.get("DSH_SESSIONS_ROOT")
    if env:
        return Path(env).expanduser()
    return Path(DEFAULT_SESSIONS_ROOT).expanduser()


def case_id_from_run_root(run_root: str | Path) -> str:
    """`runs/2026-10-13/dsh-pilot-case-005` → `case-005`。"""
    name = Path(run_root).name
    if name.startswith("dsh-pilot-"):
        return name[len("dsh-pilot-"):]
    return name


def _decompress(session_file: Path, *, timeout: int = DECOMPRESS_TIMEOUT_SECONDS) -> bytes:
    binary = shutil.which("zstd")
    if binary is None:
        raise TokenUsageError("zstd_not_found_in_path")
    try:
        done = subprocess.run(
            [binary, "-dc", str(session_file)],
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - 取决于日志体量
        raise TokenUsageError(f"zstd_timeout:{session_file.name}") from exc
    if done.returncode != 0:
        raise TokenUsageError(f"zstd_failed:{session_file.name}:{done.stderr.decode('utf-8', 'ignore').strip()}")
    return done.stdout


def iter_session_files(root: Path) -> Iterator[tuple[str, str, Path]]:
    """产出 (workspace, session_id, session_file)。"""
    if not root.is_dir():
        return
    for workspace_dir in sorted(root.iterdir()):
        if not workspace_dir.is_dir():
            continue
        for session_dir in sorted(workspace_dir.iterdir()):
            if not session_dir.is_dir():
                continue
            for name in SESSION_FILE_NAMES:
                candidate = session_dir / name
                if candidate.is_file():
                    yield workspace_dir.name, session_dir.name, candidate
                    break


def _usage_of(record: dict[str, Any]) -> dict[str, int] | None:
    usage = record.get("usage")
    if not isinstance(usage, dict):
        return None
    return {
        "fresh_input": int(usage.get("inputTokens") or 0),
        "output": int(usage.get("outputTokens") or 0),
        "cache_read": int(usage.get("cacheReadTokens") or 0),
        "cache_write": int(usage.get("cacheWriteTokens") or 0),
        "reasoning": int(usage.get("reasoningTokens") or 0),
    }


def _events(session_file: Path) -> Iterator[dict[str, Any]]:
    raw = _decompress(session_file)
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(event, dict):
            yield event


def _blank_tally() -> dict[str, int]:
    return {
        "steps": 0,
        "calls": 0,
        "fresh_input": 0,
        "output": 0,
        "cache_read": 0,
        "cache_write": 0,
        "reasoning": 0,
    }


def _add(tally: dict[str, int], usage: dict[str, int], *, steps: int = 0, calls: int = 0) -> None:
    tally["steps"] += steps
    tally["calls"] += calls
    for key in ("fresh_input", "output", "cache_read", "cache_write", "reasoning"):
        tally[key] += int(usage.get(key) or 0)


def _raw_total(tally: dict[str, int]) -> int:
    return tally["fresh_input"] + tally["output"] + tally["cache_read"]


def scan_session(session_file: Path, needles: Iterable[str]) -> dict[str, Any]:
    """扫描单个会话：全量 usage + 命中 `needles` 的 step usage。

    归因口径：一条 assistant 消息若**自身或其触发的工具调用**参数里出现 needle，
    则这一步的 usage 计入该 run。工具调用按文件顺序挂到最近一条 assistant 消息上。
    """
    needle_list = [n for n in needles if n]
    model = ""
    session_usage = _blank_tally()
    matched_usage = _blank_tally()
    seen_message_ids: set[str] = set()
    step_usages: list[dict[str, int] | None] = []
    step_matched: list[bool] = []

    for event in _events(session_file):
        kind = event.get("type")
        data = event.get("data") or {}
        if kind == "request/header" and not model:
            header = data.get("header") or {}
            config = header.get("config") or {}
            provider = config.get("provider") or ""
            name = config.get("model") or ""
            model = f"{provider}/{name}".strip("/")
            continue
        if kind == "assistant/message":
            message = data.get("message") or {}
            message_id = message.get("id") or data.get("id")
            usage = _usage_of(data) or _usage_of(message)
            if message_id and message_id in seen_message_ids:
                continue
            if message_id:
                seen_message_ids.add(message_id)
            if usage is None:
                step_usages.append(None)
                step_matched.append(False)
                continue
            _add(session_usage, usage, steps=1, calls=1)
            step_usages.append(usage)
            step_matched.append(False)
            continue
        if kind == "tool/call" and step_usages:
            blob = json.dumps(data, ensure_ascii=False)
            if any(needle in blob for needle in needle_list):
                step_matched[-1] = True

    for index, usage in enumerate(step_usages):
        if usage is not None and step_matched[index]:
            _add(matched_usage, usage, steps=1, calls=1)

    return {
        "session_id": session_file.parent.name,
        "session_file": str(session_file),
        "model": model,
        "session_usage": session_usage,
        "session_raw": _raw_total(session_usage),
        "matched_usage": matched_usage,
        "matched_raw": _raw_total(matched_usage),
    }


def collect_run_token_usage(
    run_root: str | Path,
    *,
    case_id: str | None = None,
    include_case_ref: bool = True,
    sessions_dir: str | Path | None = None,
) -> dict[str, Any]:
    """归因一个 run 的 token 用量（只读会话目录，不写文件）。"""
    root = Path(run_root).expanduser().resolve()
    if not root.is_dir():
        raise TokenUsageError(f"run_root_not_found:{root}")
    resolved_case = case_id or case_id_from_run_root(root)
    needles = [str(root)]
    if include_case_ref:
        needles.append(root.name)
        needles.append(resolved_case)

    sessions = sessions_root(sessions_dir)
    if not sessions.is_dir():
        raise TokenUsageError(f"sessions_root_not_found:{sessions}")

    sessions_scanned = 0
    attributed: list[dict[str, Any]] = []
    totals = _blank_tally()
    for workspace, _session_id, session_file in iter_session_files(sessions):
        sessions_scanned += 1
        try:
            result = scan_session(session_file, needles)
        except TokenUsageError as exc:
            if "zstd_not_found" in str(exc):
                raise
            continue
        if result["matched_usage"]["steps"] == 0:
            continue
        result["workspace"] = workspace
        attributed.append(result)
        _add(
            totals,
            result["matched_usage"],
            steps=result["matched_usage"]["steps"],
            calls=result["matched_usage"]["calls"],
        )

    attributed.sort(key=lambda item: item["matched_raw"], reverse=True)
    for item in attributed:
        item["matched_share_of_session"] = (
            round(item["matched_raw"] / item["session_raw"], 4) if item["session_raw"] else 0.0
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "run_root": str(root),
        "case_id": resolved_case,
        "attribution": {
            "method": ATTRIBUTION_METHOD,
            "needles": needles,
            "limits": list(_ATTRIBUTION_LIMITS),
        },
        "sessions_root": str(sessions),
        "sessions_scanned": sessions_scanned,
        "attributed_session_count": len(attributed),
        "totals": {
            "steps": totals["steps"],
            "calls": totals["calls"],
            "fresh_input": totals["fresh_input"],
            "output": totals["output"],
            "cache_read": totals["cache_read"],
            "cache_write": totals["cache_write"],
            "reasoning": totals["reasoning"],
            "raw_tokens": _raw_total(totals),
            "cache_read_share": (
                round(totals["cache_read"] / _raw_total(totals), 4) if _raw_total(totals) else 0.0
            ),
        },
        "sessions": [
            {
                "session_id": item["session_id"],
                "workspace": item["workspace"],
                "model": item["model"],
                "matched": item["matched_usage"],
                "matched_raw": item["matched_raw"],
                "session_raw": item["session_raw"],
                "matched_share_of_session": item["matched_share_of_session"],
                "session_file": item["session_file"],
            }
            for item in attributed
        ],
    }


def record_run_token_usage(
    project_root: str | Path,
    run_root: str | Path,
    *,
    case_id: str | None = None,
    include_case_ref: bool = True,
    sessions_dir: str | Path | None = None,
    author: str = "token-accounting",
) -> dict[str, Any]:
    """归因并写入 `<run>/metrics/token-usage.json`。"""
    report = collect_run_token_usage(
        run_root,
        case_id=case_id,
        include_case_ref=include_case_ref,
        sessions_dir=sessions_dir,
    )
    target = Path(report["run_root"]) / "metrics" / "token-usage.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_evidence_json(
            target,
            report,
            run_dir=Path(report["run_root"]),
            reason="pilot:token-usage",
            author=author,
        )
    except (RunSealedError, SealedWriteBlocked) as exc:
        raise TokenUsageError(f"run_sealed_write_blocked:{exc}") from exc
    return {
        "ok": True,
        "run_root": report["run_root"],
        "case_id": report["case_id"],
        "metrics_path": str(target),
        "attributed_session_count": report["attributed_session_count"],
        "totals": report["totals"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Article Group pilot per-run token accounting")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--case-id", default=None)
    parser.add_argument("--no-case-ref", action="store_true", help="只按 run 根路径归因，不按 case id 匹配")
    parser.add_argument("--sessions-dir", default=None, help="DSH 会话目录（默认 ~/.dsh/sessions）")
    parser.add_argument("--dry-run", action="store_true", help="只输出，不写 metrics/token-usage.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.dry_run:
            result = collect_run_token_usage(
                args.run_root,
                case_id=args.case_id,
                include_case_ref=not args.no_case_ref,
                sessions_dir=args.sessions_dir,
            )
        else:
            result = record_run_token_usage(
                args.project_root,
                args.run_root,
                case_id=args.case_id,
                include_case_ref=not args.no_case_ref,
                sessions_dir=args.sessions_dir,
            )
    except TokenUsageError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
