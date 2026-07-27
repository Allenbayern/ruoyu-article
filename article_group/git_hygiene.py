"""Git hygiene gates for infrastructure-first and daily-run-only commits.

This module never runs git, never stages files, and never authorizes push or
publication. Callers supply path lists / workspace status snapshots; the
functions return deterministic fail-closed error codes.
"""

from __future__ import annotations

from collections.abc import Iterable
import re
from typing import Any

# Core infrastructure that must be tracked before a daily-run-only commit is allowed.
REQUIRED_INFRA_PATHS: tuple[str, ...] = (
    "pyproject.toml",
    ".gitignore",
    "README.md",
    "article_group/__init__.py",
    "article_group/workflow.py",
    "article_group/prewrite.py",
    "article_group/delivery.py",
    "article_group/git_hygiene.py",
    "tests/test_workflow.py",
    "tests/test_prewrite_contract.py",
    "tests/test_source_and_article_gates.py",
    "tests/test_plain_delivery.py",
    "tests/test_git_hygiene.py",
    "tests/test_delivery_authorization.py",
    "tests/test_timestamp_freshness.py",
    "templates/controlled-first-run-brief.md",
    "templates/candidate-card.md",
    "templates/delivery-checklist.md",
    "templates/evidence-pack.md",
    "templates/writing-brief.md",
)

_DAILY_RUN_RE = re.compile(
    r"^runs/(?P<date>\d{4}-\d{2}-\d{2})/(?P<run>controlled-\d{3})(?:/.*)?$"
)
_CACHE_RE = re.compile(r"(^|/)" r"__pycache__(/|$)" r"|\.pyc$")

_INFRA_PREFIXES = (
    "article_group/",
    "tests/",
    "templates/",
    "docs/",
)
_INFRA_ROOT_FILES = {
    "pyproject.toml",
    "README.md",
    ".gitignore",
    "ARTICLE_GROUP_OPERATING_CONTRACT_v1_DRAFT.md",
}


def _normalize_repo_path(path: str) -> str:
    """Normalize a repo-relative path without stripping meaningful leading dots.

    ``str.lstrip('./')`` is unsafe: it treats the argument as a character set, so
    ``.gitignore`` would collapse to ``gitignore``.
    """
    normalized = path.strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def classify_path(path: object) -> str:
    """Classify a repo-relative path for hygiene decisions."""
    if not isinstance(path, str) or not path.strip():
        return "other"
    normalized = _normalize_repo_path(path)
    if _CACHE_RE.search(normalized):
        return "cache"
    if normalized.startswith("runs/"):
        return "daily_run" if _DAILY_RUN_RE.match(normalized) else "other"
    if normalized.startswith("reviews/"):
        return "review_audit"
    if normalized in _INFRA_ROOT_FILES or normalized.startswith(_INFRA_PREFIXES):
        return "infra"
    return "other"


def validate_daily_commit_paths(paths: object) -> list[str]:
    """Return errors if paths are not exactly one controlled run tree under runs/."""
    if not isinstance(paths, list):
        return ["daily_commit_paths_must_be_a_list"]
    if not paths:
        return ["daily_commit_paths_empty"]

    errors: list[str] = []
    run_ids: set[str] = set()
    for item in paths:
        if not isinstance(item, str):
            errors.append(f"daily_commit_path_must_be_a_str:{item!r}")
            continue
        normalized = _normalize_repo_path(item)
        category = classify_path(normalized)
        if category == "cache":
            errors.append(f"cache_must_not_be_committed:{normalized}")
            continue
        match = _DAILY_RUN_RE.match(normalized)
        if match is None:
            if category == "infra" or category == "review_audit" or category == "other":
                if normalized.startswith("runs/"):
                    errors.append(f"daily_commit_invalid_run_path:{normalized}")
                else:
                    errors.append(f"daily_commit_contains_non_run_path:{normalized}")
            else:
                errors.append(f"daily_commit_invalid_run_path:{normalized}")
            continue
        run_ids.add(f"{match.group('date')}/{match.group('run')}")

    if len(run_ids) > 1:
        errors.append(f"daily_commit_multiple_run_ids:{','.join(sorted(run_ids))}")
    return errors


def validate_infra_ready(tracked_paths: object) -> list[str]:
    """Return missing required infrastructure paths from a tracked-path snapshot."""
    if isinstance(tracked_paths, (str, bytes)) or not isinstance(tracked_paths, Iterable):
        return ["tracked_paths_must_be_an_iterable_of_str"]

    tracked: set[str] = set()
    for item in tracked_paths:
        if not isinstance(item, str):
            return ["tracked_paths_must_be_an_iterable_of_str"]
        tracked.add(_normalize_repo_path(item))

    return [f"infra_missing:{path}" for path in REQUIRED_INFRA_PATHS if path not in tracked]


def validate_workspace_status(status: object, *, mode: str) -> list[str]:
    """Validate a workspace status snapshot for infra or daily-commit readiness.

    Expected ``status`` shape::

        {
          "tracked": Iterable[str],
          "untracked": list[str],
          "staged": list[str],
        }
    """
    if mode not in {"infra_commit", "daily_commit"}:
        return [f"invalid_hygiene_mode:{mode}"]
    if not isinstance(status, dict):
        return ["workspace_status_must_be_a_dict"]

    errors: list[str] = []
    tracked = status.get("tracked", [])
    errors.extend(validate_infra_ready(tracked))

    staged = status.get("staged", [])
    untracked = status.get("untracked", [])
    if not isinstance(staged, list):
        errors.append("staged_paths_must_be_a_list")
        staged = []
    if not isinstance(untracked, list):
        errors.append("untracked_paths_must_be_a_list")
        untracked = []

    for path in staged:
        if isinstance(path, str) and classify_path(path) == "cache":
            errors.append(f"cache_must_not_be_committed:{_normalize_repo_path(path)}")

    if mode == "daily_commit":
        # Daily commits may only stage a single run tree, and only after infra is ready.
        if any(err.startswith("infra_missing:") for err in errors):
            return errors
        # Pass the original staged list through: non-string entries must fail closed
        # inside validate_daily_commit_paths (S6-F01). Never filter them away first.
        errors.extend(validate_daily_commit_paths(staged))
    return errors
