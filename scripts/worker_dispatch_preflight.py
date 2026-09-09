#!/usr/bin/env python3
"""Validate a worker dispatch without fetching sources or reading raw HTML."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from article_group.worker_contract import build_worker_dispatch_record
from scripts.codex_skill_inventory import build_report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requested-skill", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--codex-skills-root", type=Path, default=Path.home() / ".codex" / "skills"
    )
    parser.add_argument("--fallback-allowed", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


def _registered_skills(report: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for source in report.get("sources", []):
        if not isinstance(source, dict):
            continue
        for entry in source.get("skills", []):
            if not isinstance(entry, dict):
                continue
            directory = entry.get("directory")
            if isinstance(directory, str) and directory.strip():
                names.add(directory.strip())
            metadata = entry.get("metadata")
            if isinstance(metadata, dict):
                name = metadata.get("name")
                if isinstance(name, str) and name.strip():
                    names.add(name.strip())
    return names


def _load_input(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("worker input must be a JSON object")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        worker_input = _load_input(args.input)
        inventory = build_report(args.project_root, args.codex_skills_root)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"INPUT_ERROR:{exc}")
        return 2

    record = build_worker_dispatch_record(
        requested_skill=args.requested_skill,
        registered_skills=_registered_skills(inventory),
        fallback_allowed=args.fallback_allowed,
        stage=args.stage,
        worker_input=worker_input,
    )
    record["input_path"] = str(args.input)
    record["input_sha256"] = _sha256(args.input)
    record["registered_skill_count"] = len(_registered_skills(inventory))
    rendered = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if record["status"] != "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
