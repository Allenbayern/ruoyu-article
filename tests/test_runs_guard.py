"""runs/ 只读自检本身的测试：快照与差异判定必须真的能发现改动。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests._runs_guard import (
    ALLOW_ENV,
    diff,
    format_changes,
    is_clean,
    sha256_file,
    snapshot,
)


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    (root / "2026-09-16" / "daily-900" / "review").mkdir(parents=True)
    (root / "2026-09-16" / "daily-900" / "batch.json").write_text("{}", encoding="utf-8")
    (root / "2026-09-16" / "daily-900" / "review" / "x.json").write_text("旧内容", encoding="utf-8")
    return root


def test_unchanged_tree_is_clean(tmp_path: Path):
    root = _tree(tmp_path)
    assert is_clean(diff(snapshot(root), snapshot(root)))


def test_added_removed_and_changed_are_detected(tmp_path: Path):
    root = _tree(tmp_path)
    before = snapshot(root)
    (root / "2026-09-16" / "daily-900" / "review" / "new.json").write_text("新", encoding="utf-8")
    (root / "2026-09-16" / "daily-900" / "batch.json").unlink()
    (root / "2026-09-16" / "daily-900" / "review" / "x.json").write_text("改过的内容", encoding="utf-8")

    changes = diff(before, snapshot(root))
    assert changes["added"] == ["2026-09-16/daily-900/review/new.json"]
    assert changes["removed"] == ["2026-09-16/daily-900/batch.json"]
    assert changes["changed"] == ["2026-09-16/daily-900/review/x.json"]
    assert is_clean(changes) is False
    assert "changed(1)" in format_changes(changes)


def test_same_size_rewrite_is_still_detected(tmp_path: Path):
    """同长度覆盖也必须被发现（mtime_ns 会变）。"""
    root = _tree(tmp_path)
    target = root / "2026-09-16" / "daily-900" / "review" / "x.json"
    before = snapshot(root)
    target.write_text("新内容", encoding="utf-8")  # 与 "旧内容" 同为 3 字
    changes = diff(before, snapshot(root))
    assert changes["changed"] == ["2026-09-16/daily-900/review/x.json"]


def test_missing_root_is_empty_snapshot(tmp_path: Path):
    assert snapshot(tmp_path / "nope") == {}
    assert is_clean(diff({}, {}))


def test_sha256_helper_handles_missing_file(tmp_path: Path):
    assert sha256_file(tmp_path / "missing") == ""


def test_conftest_wires_the_guard_for_the_repo_runs_dir():
    import conftest

    assert conftest.RUNS_DIR.name == "runs"
    assert conftest.RUNS_DIR.is_absolute()
    assert ALLOW_ENV == "RUOYU_ALLOW_RUNS_WRITES"


def test_allow_env_defaults_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(ALLOW_ENV, raising=False)
    assert os.environ.get(ALLOW_ENV) != "1"
