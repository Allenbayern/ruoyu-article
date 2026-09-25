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


@pytest.fixture(autouse=True)
def isolated_seal_anchor_store(tmp_path_factory, monkeypatch):
    """封存锚点存储必须隔离到 tmp —— 测试不许写 run 之外的生产证据库。

    2026-09-25 实测：不隔离时跑一次套件会往 `/home/allen/seal-anchors` 写一批
    pytest 残留（那里曾累积 58 个，全部来自测试；真实 run 的锚点一个都没有）。
    危害不止"脏"：锚点文件名只按「日期-批次」派生，**同名 run 会互相覆盖摘要**，
    而摘要正是 `run_seal.verify` 用来判「清单有没有被改写」的唯一依据——
    测试把真实 run 的锚点覆盖掉，那道防线就永久失效且不可恢复。

    同时清掉离机推送开关：否则测试会去连 mac-backup。
    """
    from article_group import run_seal

    store = tmp_path_factory.mktemp("seal-anchors")
    monkeypatch.setenv(run_seal.ANCHOR_DIR_ENV, str(store))
    monkeypatch.delenv(run_seal.ANCHOR_PUSH_ENV, raising=False)
    return store
