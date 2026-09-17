#!/usr/bin/env python3
"""Run the existing article lane as a candidate/evidence-only sidecar.

The wrapper requires an explicit JSONL input, invokes the repository's
``run_daily_pipeline.py --lane article`` entry point, and records only local
candidate/evidence artifacts. It never invokes publication or Hermes/Kanban
operations.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, NoReturn, Sequence


ROOT = Path(__file__).resolve().parents[1]
ARTICLE_PIPELINE_ROOT = ROOT / "projects" / "media-intel-aios"
ARTICLE_PIPELINE = ARTICLE_PIPELINE_ROOT / "scripts" / "run_daily_pipeline.py"

REQUIRED_ARTIFACTS = (
    "today-hook-dispatch.jsonl",
    "today-hook-dispatch.md",
    "director-review.md",
    "latest-feedback.md",
    "article-approved-latest.md",
    "reference-candidate-export.jsonl",
)


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, "argument_error\n")


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        description="Run the existing article lane for local candidate/evidence output only."
    )
    parser.add_argument("--date", required=True, help="Article-lane date in YYYY-MM-DD format")
    parser.add_argument("--input", type=Path, help="Explicit DailyHot JSONL input")
    parser.add_argument("--output-root", type=Path, required=True, help="Fresh local output root")
    return parser


def _valid_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _read_jsonl(path: Path) -> int:
    """Validate enough of the input to avoid invoking the lane on empty data."""
    count = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw in enumerate(handle, start=1):
                line = raw.strip()
                if not line:
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"line {line_number} is not an object")
                count += 1
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return -1
    return count


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _last_json_object(text: str) -> dict[str, Any] | None:
    for line in reversed(text.splitlines()):
        candidate = line.strip()
        if not candidate:
            continue
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _command(*, date_value: str, input_path: Path, output_root: Path) -> list[str]:
    return [
        sys.executable,
        str(ARTICLE_PIPELINE),
        "--lane",
        "article",
        "--date",
        date_value,
        "--dailyhot-article",
        str(input_path),
        "--output-root",
        str(output_root),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not _valid_date(args.date):
        print("date_invalid")
        return 2
    if args.input is None:
        print("input_unavailable")
        return 2
    if not args.input.is_file() or args.input.is_symlink():
        print("input_unavailable")
        return 2
    input_count = _read_jsonl(args.input)
    if input_count < 1:
        print("input_unavailable" if input_count == 0 else "input_invalid")
        return 2
    if not ARTICLE_PIPELINE.is_file():
        print("lane_unavailable")
        return 2

    output_root = args.output_root.expanduser()
    manifest_path = output_root / "codex-daily-article-run.json"
    if output_root.exists() and any(output_root.iterdir()):
        print("output_exists")
        return 2

    command = _command(date_value=args.date, input_path=args.input, output_root=output_root)
    try:
        completed = subprocess.run(
            command,
            cwd=ARTICLE_PIPELINE_ROOT,
            text=True,
            capture_output=True,
            check=False,
            env=os.environ.copy(),
        )
    except OSError:
        print("lane_failed")
        return 2

    summary = _last_json_object((completed.stdout or "") + "\n" + (completed.stderr or ""))
    missing = [name for name in REQUIRED_ARTIFACTS if not (output_root / name).is_file()]
    if completed.returncode != 0:
        print("lane_failed")
        return 2
    if missing:
        print("evidence_incomplete")
        return 2

    artifact_hashes = {
        name: _sha256(output_root / name)
        for name in REQUIRED_ARTIFACTS
    }
    manifest: dict[str, Any] = {
        "schema_version": "codex-daily-article-run-1.0",
        "status": "candidate_evidence_only",
        "date": args.date,
        "input": {"path": str(args.input), "jsonl_objects": input_count, "sha256": _sha256(args.input)},
        "command": command,
        "lane": "article",
        "pipeline_summary": summary or {},
        "artifacts": artifact_hashes,
        "publication_authorized": False,
        "publication_performed": False,
        "hermes_modified": False,
        "kanban_modified": False,
        "coverage_gaps": [
            "This wrapper verifies local lane artifacts only; it does not establish factual truth or publication readiness.",
            "The nested lane may report retry or source errors inside its summary; controller review remains required.",
        ],
        "created_at": datetime.now().astimezone().isoformat(),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    _write_manifest(manifest_path, manifest)
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "date": args.date,
                "output_root": str(output_root),
                "manifest": str(manifest_path),
                "candidate_count": (summary or {}).get("article_count"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
