"""Codex review adapter for the Ruoyu controlled-production workflow.

This is an evidence-producing sidecar. It never edits artifacts, changes workflow
state, grants publication authority, or replaces deterministic local gates.

Modes:
    normal: Codex native ``review`` using the Luna route.
    l2:    read-only Codex ``exec`` using the Sol route and review schema.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


SCHEMA_VERSION = "codex-review-contract-1.0"
DEFAULT_SCHEMA = Path(__file__).resolve().parent.parent / "schemas" / "codex-review-contract.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_id(run_root: Path) -> str:
    return run_root.name or "codex-review"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _build_prompt(args: argparse.Namespace) -> str:
    criteria = args.acceptance or "Review the changed files for correctness, regressions, negative paths, and test coverage."
    return (
        "You are an independent evidence reviewer. Do not modify files, do not publish, "
        "do not merge, and do not authorize any external action. Read the original request, "
        "the repository changes, and the acceptance criteria independently. Report only "
        "evidence-backed findings and coverage gaps.\n\n"
        f"Original request: {args.request}\n"
        f"Acceptance criteria: {criteria}\n"
        f"Run root / artifact context: {args.run_root}\n"
        f"Additional focus: {args.focus or 'none'}\n"
        "Use exact file paths, line numbers where possible, commands, and counterexamples."
    )


def _base_record(args: argparse.Namespace, mode: str, command: list[str]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": _run_id(args.run_root),
        "risk_tier": args.risk,
        "review_mode": mode,
        "original_request": args.request,
        "acceptance_criteria": args.acceptance or "",
        "artifact_context": str(args.run_root),
        "started_at": _utc_now(),
        "command": command,
        "decision": "evidence_insufficient",
        "findings": [],
        "coverage_gaps": ["review_not_completed"],
        "publication_authorization": "not_authorized",
    }


def _parse_l2_output(text: str) -> dict[str, Any] | None:
    for line in reversed(text.splitlines()):
        candidate = line.strip()
        if not candidate.startswith("{"):
            continue
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "decision" in value and "findings" in value:
            return value
    return None


def run_review(args: argparse.Namespace) -> int:
    codex = shutil.which("codex")
    if codex is None:
        raise SystemExit("codex executable not found in PATH")
    if not args.run_root.exists():
        raise SystemExit(f"run root does not exist: {args.run_root}")

    if args.mode == "normal":
        command = [
            codex,
            "review",
            "-c",
            'model="gpt-5.6-luna"',
            "-c",
            'model_reasoning_effort="max"',
            "--uncommitted",
        ]
        if args.base:
            command = [
                codex,
                "review",
                "-c",
                'model="gpt-5.6-luna"',
                "-c",
                'model_reasoning_effort="max"',
                "--base",
                args.base,
            ]
        if args.focus:
            command.append(args.focus)
    else:
        command = [
            codex,
            "exec",
            "-m",
            "gpt-5.6-sol",
            "-c",
            'model_reasoning_effort="high"',
            "-s",
            "read-only",
            "--output-schema",
            str(args.schema),
            _build_prompt(args),
        ]

    record = _base_record(args, args.mode, command)
    if getattr(args, "article_task_id", None):
        record["article_task_id"] = args.article_task_id
    if getattr(args, "article_id", None):
        record["article_id"] = args.article_id
    if getattr(args, "draft_path", None):
        record["draft_path"] = args.draft_path
    if getattr(args, "draft_sha256", None):
        record["draft_sha256"] = args.draft_sha256
    record["attempt"] = getattr(args, "attempt", 1) or 1
    if getattr(args, "l2_required", False):
        record["l2_required"] = True
        record["l2_risk_basis"] = args.l2_risk_basis or ""
    started = datetime.now(timezone.utc)
    run_kwargs = {
        "cwd": args.repo,
        "text": True,
        "capture_output": True,
        "check": False,
        "env": os.environ.copy(),
    }
    if getattr(args, "timeout_seconds", None):
        run_kwargs["timeout"] = args.timeout_seconds
    try:
        completed = subprocess.run(command, **run_kwargs)
    except subprocess.TimeoutExpired as exc:
        record["error"] = f"codex_review_timeout:{exc}"
        record["status"] = "UNVERIFIED"
        record["decision"] = "timeout"
        record["coverage_gaps"] = ["review_timeout"]
        record["timeout_reason"] = "review_deadline_exceeded"
        record["next_step"] = "resume_single_article" if record.get("article_task_id") else "resume_review"
        record["scope"] = "single_article" if record.get("article_task_id") else "batch"
        completed = None
    except OSError as exc:
        record["error"] = f"codex_invocation_failed:{exc}"
        completed = None

    output = "" if completed is None else (completed.stdout + completed.stderr)
    output_path = args.output.with_suffix(".log")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output, encoding="utf-8")
    record["output_path"] = str(output_path)
    record["output_sha256"] = _sha256(output_path)
    record["finished_at"] = _utc_now()
    record["duration_seconds"] = round((datetime.now(timezone.utc) - started).total_seconds(), 3)

    if completed is not None:
        record["exit_code"] = completed.returncode
        if args.mode == "l2":
            structured = _parse_l2_output(output)
            if structured is not None:
                for key in ("decision", "scope_reviewed", "findings", "non_findings", "coverage_gaps"):
                    if key in structured:
                        record[key] = structured[key]
                record["coverage_gaps"] = structured.get("coverage_gaps", [])
                record["structured_result"] = True
            else:
                record["error"] = "l2_structured_result_missing"
        else:
            record["decision"] = "review_completed" if completed.returncode == 0 else "review_failed"
            record["coverage_gaps"] = [] if completed.returncode == 0 else ["codex_review_nonzero_exit"]

    _write_json(args.output, record)
    print(json.dumps({"output": str(args.output), "exit_code": record.get("exit_code"), "decision": record["decision"]}, ensure_ascii=False))
    return 0 if record.get("exit_code") == 0 and record["decision"] not in {"evidence_insufficient", "review_failed"} else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Codex as an evidence-producing review sidecar.")
    parser.add_argument("--mode", choices=("normal", "l2"), required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--acceptance")
    parser.add_argument("--focus")
    parser.add_argument("--base")
    parser.add_argument("--risk", choices=("L0", "L1", "L2"), default="L1")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--timeout-seconds", type=float)
    parser.add_argument("--article-task-id")
    parser.add_argument("--article-id")
    parser.add_argument("--draft-path")
    parser.add_argument("--draft-sha256")
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--l2-required", action="store_true")
    parser.add_argument("--l2-risk-basis", default="")
    return parser


def main() -> int:
    return run_review(build_parser().parse_args())


if __name__ == "__main__":
    sys.exit(main())
