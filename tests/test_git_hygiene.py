"""Slice 6 RED: git hygiene gates for infra-first and daily-run-only commits."""

from __future__ import annotations

import pytest


def test_classify_path_categories():
    from article_group.git_hygiene import classify_path

    assert classify_path("article_group/workflow.py") == "infra"
    assert classify_path("tests/test_workflow.py") == "infra"
    assert classify_path("templates/writing-brief.md") == "infra"
    assert classify_path("docs/plans/x.md") == "infra"
    assert classify_path("pyproject.toml") == "infra"
    assert classify_path("README.md") == "infra"
    assert classify_path(".gitignore") == "infra"
    assert classify_path("./.gitignore") == "infra"
    assert classify_path("runs/2026-07-28/controlled-007/articles/A/article-draft.md") == "daily_run"
    assert classify_path("reviews/slice6-controller-acceptance.md") == "review_audit"
    assert classify_path("article_group/__pycache__/x.pyc") == "cache"
    assert classify_path("tests/__pycache__/y.pyc") == "cache"
    assert classify_path("mystery.bin") == "other"


def test_validate_daily_commit_paths_allows_only_single_run_tree():
    from article_group.git_hygiene import validate_daily_commit_paths

    ok = [
        "runs/2026-07-28/controlled-007/articles/A/article-draft.md",
        "runs/2026-07-28/controlled-007/controlled-run-manifest.json",
    ]
    assert validate_daily_commit_paths(ok) == []


def test_validate_daily_commit_paths_rejects_infra_mixed_in():
    from article_group.git_hygiene import validate_daily_commit_paths

    paths = [
        "runs/2026-07-28/controlled-007/articles/A/article-draft.md",
        "article_group/workflow.py",
    ]
    errors = validate_daily_commit_paths(paths)
    assert "daily_commit_contains_non_run_path:article_group/workflow.py" in errors


def test_validate_daily_commit_paths_rejects_multiple_run_ids():
    from article_group.git_hygiene import validate_daily_commit_paths

    paths = [
        "runs/2026-07-28/controlled-007/a.md",
        "runs/2026-07-28/controlled-008/b.md",
    ]
    errors = validate_daily_commit_paths(paths)
    assert any(err.startswith("daily_commit_multiple_run_ids:") for err in errors)


def test_validate_daily_commit_paths_rejects_malformed_run_path():
    from article_group.git_hygiene import validate_daily_commit_paths

    errors = validate_daily_commit_paths(["runs/not-a-date/controlled-007/x.md"])
    assert "daily_commit_invalid_run_path:runs/not-a-date/controlled-007/x.md" in errors


def test_validate_daily_commit_paths_rejects_empty_and_non_list():
    from article_group.git_hygiene import validate_daily_commit_paths

    assert "daily_commit_paths_empty" in validate_daily_commit_paths([])
    assert validate_daily_commit_paths(None) == ["daily_commit_paths_must_be_a_list"]  # type: ignore[arg-type]
    assert validate_daily_commit_paths([None, 1]) == [  # type: ignore[list-item]
        "daily_commit_path_must_be_a_str:None",
        "daily_commit_path_must_be_a_str:1",
    ]


def test_validate_infra_ready_requires_core_tracked_files():
    from article_group.git_hygiene import REQUIRED_INFRA_PATHS, validate_infra_ready

    tracked = set(REQUIRED_INFRA_PATHS)
    assert validate_infra_ready(tracked) == []

    missing = set(REQUIRED_INFRA_PATHS) - {"pyproject.toml", ".gitignore"}
    errors = validate_infra_ready(missing)
    assert "infra_missing:pyproject.toml" in errors
    assert "infra_missing:.gitignore" in errors


def test_validate_infra_ready_rejects_non_iterable_without_crashing():
    from article_group.git_hygiene import validate_infra_ready

    assert validate_infra_ready(None) == ["tracked_paths_must_be_an_iterable_of_str"]  # type: ignore[arg-type]
    assert validate_infra_ready(123) == ["tracked_paths_must_be_an_iterable_of_str"]  # type: ignore[arg-type]


def test_validate_workspace_status_flags_cache_and_blocks_daily_when_infra_untracked():
    from article_group.git_hygiene import validate_workspace_status

    # Clean enough for daily only when required infra is tracked and no cache staged intent.
    status = {
        "tracked": {
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
        },
        "untracked": [
            "runs/2026-07-28/controlled-007/articles/A/article-draft.md",
        ],
        "staged": [
            "runs/2026-07-28/controlled-007/articles/A/article-draft.md",
        ],
    }
    assert validate_workspace_status(status, mode="daily_commit") == []

    dirty = {
        **status,
        "untracked": status["untracked"] + ["article_group/__pycache__/x.pyc"],
        "staged": status["staged"] + ["article_group/__pycache__/x.pyc"],
    }
    errors = validate_workspace_status(dirty, mode="daily_commit")
    assert "cache_must_not_be_committed:article_group/__pycache__/x.pyc" in errors


def test_validate_workspace_status_daily_mode_requires_infra_ready():
    from article_group.git_hygiene import validate_workspace_status

    status = {
        "tracked": {"article_group/workflow.py"},  # incomplete infra
        "untracked": ["runs/2026-07-28/controlled-007/a.md"],
        "staged": ["runs/2026-07-28/controlled-007/a.md"],
    }
    errors = validate_workspace_status(status, mode="daily_commit")
    assert any(err.startswith("infra_missing:") for err in errors)


def test_validate_workspace_status_rejects_bad_mode_and_shape():
    from article_group.git_hygiene import validate_workspace_status

    assert validate_workspace_status({}, mode="nope") == ["invalid_hygiene_mode:nope"]
    assert validate_workspace_status(None, mode="daily_commit") == [  # type: ignore[arg-type]
        "workspace_status_must_be_a_dict"
    ]


@pytest.mark.parametrize("bad_extra", [None, 0, {}, True, ["nested"]])
def test_validate_workspace_status_daily_mode_rejects_non_string_staged_entries(
    bad_extra: object,
):
    from article_group.git_hygiene import REQUIRED_INFRA_PATHS, validate_workspace_status

    run_path = "runs/2026-07-28/controlled-007/articles/A/article-draft.md"
    status = {
        "tracked": set(REQUIRED_INFRA_PATHS),
        "untracked": [],
        "staged": [run_path, bad_extra],
    }
    errors = validate_workspace_status(status, mode="daily_commit")
    assert any(err.startswith("daily_commit_path_must_be_a_str:") for err in errors)


def test_validate_workspace_status_daily_mode_rejects_only_non_string_staged():
    from article_group.git_hygiene import REQUIRED_INFRA_PATHS, validate_workspace_status

    status = {
        "tracked": set(REQUIRED_INFRA_PATHS),
        "untracked": [],
        "staged": [None],
    }
    errors = validate_workspace_status(status, mode="daily_commit")
    assert "daily_commit_path_must_be_a_str:None" in errors
