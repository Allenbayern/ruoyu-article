"""pytest 级护栏：跑测试不得改动真实审计目录 runs/。

2026-09-17 事故：为演示扩展后的预检，在已收尾的 daily-008 上重跑，覆盖了
review/art-001/ledger-coverage-precheck.json。CLI 侧已有封存守门；这里是第二层。

需要故意写 runs/ 的集成测试，设 RUOYU_ALLOW_RUNS_WRITES=1 显式放行。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tests._runs_guard import ALLOW_ENV, diff, format_changes, is_clean, snapshot  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent
RUNS_DIR = REPO_ROOT / "runs"


@pytest.fixture(scope="session", autouse=True)
def guard_runs_dir() -> None:
    if os.environ.get(ALLOW_ENV) == "1" or not RUNS_DIR.is_dir():
        yield
        return
    before = snapshot(RUNS_DIR)
    yield
    changes = diff(before, snapshot(RUNS_DIR))
    if not is_clean(changes):
        pytest.fail(
            "测试改动了 runs/ 下的审计证据（这是只读区域）：\n"
            + format_changes(changes)
            + "\n请在 tmp_path 里造沙盘（scripts/run_sandbox.py），"
              f"或显式设 {ALLOW_ENV}=1 放行。",
            pytrace=False,
        )
