#!/usr/bin/env python3
"""Read-only structural audit for DSH review inputs and recent run layout."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, NoReturn, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOME_AGENTS = Path.home() / "AGENTS.md"
DEFAULT_PROJECT_AGENTS = PROJECT_ROOT / "AGENTS.md"
DEFAULT_SKILLS_ROOT = (
    Path.home() / ".agents" / "skills"
    if (Path.home() / ".agents" / "skills").is_dir()
    else Path.home() / ".codex" / "skills"
)
DEFAULT_SCHEMA = PROJECT_ROOT / "schemas" / "codex-review-contract.json"
DEFAULT_RUNS_ROOT = PROJECT_ROOT / "runs"


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, "argument_error\n")


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(description="Audit DSH review governance and run structure without writing files.")
    parser.add_argument("--home-agents", type=Path, default=DEFAULT_HOME_AGENTS)
    parser.add_argument("--project-agents", type=Path, default=DEFAULT_PROJECT_AGENTS)
    parser.add_argument("--skills-root", type=Path, default=DEFAULT_SKILLS_ROOT)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    parser.add_argument("--recent-limit", type=int, default=10)
    parser.add_argument("--month", help="Monthly snapshot key in YYYY-MM format")
    parser.add_argument("--output-root", type=Path, help="Write one immutable monthly snapshot here")
    return parser


def _valid_month(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m")
    except ValueError:
        return False
    return True


def _file_info(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "is_file": path.is_file(),
        "bytes": None,
        "sha256": None,
    }
    if path.is_file():
        try:
            raw = path.read_bytes()
            info["bytes"] = len(raw)
            info["sha256"] = hashlib.sha256(raw).hexdigest()
        except OSError:
            info["readable"] = False
        else:
            info["readable"] = True
    else:
        info["readable"] = False
    return info


def _load_schema(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.is_file():
        return None, "missing"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return None, type(error).__name__
    if not isinstance(value, dict):
        return None, "not_object"
    return value, None


def _skills_report(root: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    if root.is_dir():
        for path in sorted(root.glob("*/SKILL.md")):
            entries.append({"name": path.parent.name, **_file_info(path)})
    return {"root": str(root), "exists": root.is_dir(), "skill_count": len(entries), "entries": entries}


def _recent_runs(root: Path, limit: int) -> dict[str, Any]:
    if not root.is_dir():
        return {"root": str(root), "exists": False, "entries": []}
    directories = [path for path in root.iterdir() if path.is_dir()]
    directories.sort(key=lambda path: (path.stat().st_mtime_ns, path.name), reverse=True)
    entries: list[dict[str, Any]] = []
    for path in directories[: max(0, limit)]:
        children = sorted(item.name for item in path.iterdir()) if path.is_dir() else []
        entries.append(
            {
                "name": path.name,
                "path": str(path),
                "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                "children": children[:100],
                "child_count": len(children),
            }
        )
    return {"root": str(root), "exists": True, "entries": entries}


def _write_monthly_snapshot(report: dict[str, Any], month: str, output_root: Path) -> tuple[Path, Path] | None:
    output_root = output_root.expanduser()
    report_path = output_root / f"codex-review-audit-{month}.json"
    manifest_path = output_root / f"codex-review-audit-{month}.json.manifest.json"
    if report_path.exists() or manifest_path.exists():
        return None
    output_root.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    report_sha256 = hashlib.sha256(report_path.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "codex-review-audit-manifest-1.0",
                "month": month,
                "report": str(report_path),
                "report_sha256": report_sha256,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return report_path, manifest_path


def build_report(
    *,
    home_agents: Path = DEFAULT_HOME_AGENTS,
    project_agents: Path = DEFAULT_PROJECT_AGENTS,
    skills_root: Path = DEFAULT_SKILLS_ROOT,
    schema_path: Path = DEFAULT_SCHEMA,
    runs_root: Path = DEFAULT_RUNS_ROOT,
    recent_limit: int = 10,
) -> dict[str, Any]:
    schema, schema_error = _load_schema(schema_path)
    required_fields = schema.get("required", []) if isinstance(schema, dict) else []
    if not isinstance(required_fields, list):
        required_fields = []
    report: dict[str, Any] = {
        "schema_version": "codex-review-audit-1.0",
        "read_only": True,
        "mutation": {"files_written": [], "files_deleted": [], "external_actions": []},
        "inputs": {
            "home_agents": _file_info(home_agents),
            "project_agents": _file_info(project_agents),
            "codex_skills_root": {"path": str(skills_root), "exists": skills_root.is_dir()},
            "review_schema": _file_info(schema_path),
            "runs_root": {"path": str(runs_root), "exists": runs_root.is_dir()},
        },
        "checks": {
            "home_agents": {"present": home_agents.is_file()},
            "project_agents": {"present": project_agents.is_file()},
            "codex_skills": _skills_report(skills_root),
            "review_schema": {
                "valid_json": schema_error is None,
                "error": schema_error,
                "required_fields": [str(item) for item in required_fields if isinstance(item, str)],
                "additional_properties": schema.get("additionalProperties") if isinstance(schema, dict) else None,
            },
            "recent_runs": _recent_runs(runs_root, recent_limit),
        },
        "coverage_gaps": [
            "This is a structural/read-only audit; it does not judge article facts, prose quality, or publication readiness.",
            "Recent-run presence and file hashes do not prove that a review decision was independently authorized.",
        ],
    }
    return report


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.recent_limit < 0:
        print("argument_error")
        return 2
    if (args.month is None) != (args.output_root is None):
        print("argument_error")
        return 2
    if args.month is not None and not _valid_month(args.month):
        print("month_invalid")
        return 2
    report = build_report(
        home_agents=args.home_agents.expanduser(),
        project_agents=args.project_agents.expanduser(),
        skills_root=args.skills_root.expanduser(),
        schema_path=args.schema.expanduser(),
        runs_root=args.runs_root.expanduser(),
        recent_limit=args.recent_limit,
    )
    if args.month is not None and args.output_root is not None:
        written = _write_monthly_snapshot(report, args.month, args.output_root)
        if written is None:
            print("artifact_exists")
            return 2
        print(json.dumps({"status": "written", "month": args.month, "report": str(written[0]), "manifest": str(written[1])}, ensure_ascii=False, sort_keys=True))
        required_ok = (
            report["checks"]["home_agents"]["present"]
            and report["checks"]["project_agents"]["present"]
            and report["checks"]["review_schema"]["valid_json"]
        )
        return 0 if required_ok else 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    required_ok = (
        report["checks"]["home_agents"]["present"]
        and report["checks"]["project_agents"]["present"]
        and report["checks"]["review_schema"]["valid_json"]
    )
    return 0 if required_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
