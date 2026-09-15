"""run_record：RUN-RECORD 机器节自动组装测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from article_group.run_record import build_run_record

DAILY_005 = Path("runs/2026-09-15/daily-005")
needs_daily_005 = pytest.mark.skipif(
    not (DAILY_005 / "batch.json").exists(),
    reason="runs/ 是本地审计目录（gitignore），daily-005 不在当前工作树时不跑集成断言",
)


@needs_daily_005
def test_build_run_record_assembles_machine_sections():
    text = build_run_record(DAILY_005)
    for section in (
        "## 1. 本次任务是什么",
        "## 2. 选题与来源",
        "## 3. 两篇成稿",
        "## 4. 门禁与证据",
        "## 5. 独立 L2 对抗复核",
        "## 6. 收口状态（分栏）",
        "## 7. 本轮顺带修掉的工具缺陷（有测试）",
        "## 8. 未验证与遗留",
    ):
        assert section in text, section
    # 机器节内容来自真实产物
    assert "task-hierarchy 1.0 契约" in text
    assert "claim↔来源溯源核验" in text
    assert "compliance_gate（五道门）" in text
    assert "not_run" in text  # compliance 显式记录
    assert "CONTENT_READY" in text
    assert "《交锋》" in text
    assert "__待填__" in text  # 人工叙事节占位


@needs_daily_005
def test_build_run_record_gate_verdicts_match_artifacts():
    import json

    text = build_run_record(DAILY_005)
    hierarchy = json.loads((DAILY_005 / "task-hierarchy-validation-report.json").read_text(encoding="utf-8"))
    assert hierarchy["pass"] is True
    assert "| task-hierarchy 1.0 契约 | `task-hierarchy-validation-report.json` | pass |" in text
