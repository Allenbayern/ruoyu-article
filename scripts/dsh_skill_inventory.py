#!/usr/bin/env python3
"""Emit a stable, read-only inventory of project and Codex skills.

Only direct ``*/SKILL.md`` frontmatter is inspected. Authentication files,
environment files, cookies, tokens, and arbitrary skill payloads are ignored.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_SKILLS_ROOT = Path.home() / ".agents" / "skills"
LEGACY_CODEX_SKILLS_ROOT = Path.home() / ".codex" / "skills"


def default_user_skills_root() -> Path:
    """Return the user-level skills root.

    The harness-neutral ``~/.agents/skills`` location wins when it exists; the
    historical Codex root stays as a read-only fallback so audits remain valid
    while the Codex CLI is being retired.
    """
    if AGENT_SKILLS_ROOT.is_dir():
        return AGENT_SKILLS_ROOT
    return LEGACY_CODEX_SKILLS_ROOT


DEFAULT_CODEX_SKILLS_ROOT = default_user_skills_root()
_METADATA_KEYS = {"name", "description"}
_REDACTIONS = (
    (re.compile(r"(?i)\bBearer\s+[^\s,;]+"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)\b(?:api[_ -]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"), "[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]+\b"), "[REDACTED]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9_]+\b"), "[REDACTED]"),
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="List project and Codex SKILL.md frontmatter without reading credential files."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
        help="Project root containing .agents/skills (default: repository root)",
    )
    parser.add_argument(
        "--codex-skills-root",
        type=Path,
        default=DEFAULT_CODEX_SKILLS_ROOT,
        help="User skills root (default: ~/.agents/skills, falling back to ~/.codex/skills)",
    )
    return parser


def _clean_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    for pattern, replacement in _REDACTIONS:
        value = pattern.sub(replacement, value)
    return value[:240]


def _frontmatter(path: Path) -> dict[str, str]:
    """Read only a bounded frontmatter prefix from one SKILL.md file."""
    metadata: dict[str, str] = {}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            if handle.readline(16_384).strip() != "---":
                return metadata
            for _ in range(96):
                line = handle.readline(16_384)
                if not line or line.strip() == "---":
                    break
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key = key.strip()
                if key in _METADATA_KEYS:
                    metadata[key] = _clean_value(value)
    except OSError:
        return {}
    return metadata


def _skill_entry(skill_file: Path, source: str) -> dict[str, Any]:
    return {
        "directory": skill_file.parent.name,
        "metadata": _frontmatter(skill_file),
        "skill_file": str(skill_file),
        "source": source,
    }


def _scan_root(root: Path, source: str) -> dict[str, Any]:
    root = root.expanduser()
    entries: list[dict[str, Any]] = []
    if root.is_dir() and not root.is_symlink():
        try:
            children = sorted(root.iterdir(), key=lambda path: path.name)
        except OSError:
            children = []
        for child in children:
            if child.is_symlink() or not child.is_dir():
                continue
            skill_file = child / "SKILL.md"
            if skill_file.is_symlink() or not skill_file.is_file():
                continue
            entries.append(_skill_entry(skill_file, source))
    return {
        "exists": root.is_dir() and not root.is_symlink(),
        "root": str(root),
        "skills": entries,
        "source": source,
    }


def build_report(project_root: Path, codex_skills_root: Path) -> dict[str, Any]:
    project_root = project_root.expanduser()
    codex_skills_root = codex_skills_root.expanduser()
    project_skills_root = project_root / ".agents" / "skills"
    sources = [
        _scan_root(project_skills_root, "project"),
        _scan_root(codex_skills_root, "codex-user"),
    ]
    return {
        "read_only": True,
        "schema_version": "codex-skill-inventory-1",
        "sources": sources,
        "summary": {
            "project_skill_count": len(sources[0]["skills"]),
            "codex_user_skill_count": len(sources[1]["skills"]),
            "total_skill_count": sum(len(source["skills"]) for source in sources),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = build_report(args.project_root, args.codex_skills_root)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
