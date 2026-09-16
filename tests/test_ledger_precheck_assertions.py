"""账本预检器（ledger_coverage_precheck）的确定性断言缺口扩展。

daily-008 的 2 条 L2 major（时间跨度「十几年过去」、受众行为「台词还在被引用」）
当时整轮漏过；本测试锁定"LLM 不可用时预检也能报出这两类"。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts import ledger_coverage_precheck as pre

DELIVERY_GAPS = "# 标题\n\n## 第一节\n\n十几年过去，《让子弹飞》的台词还在被引用。\n"
DELIVERY_OK = (
    "# 标题\n\n## 第一节\n\n"
    "十多年来，庞大的影迷群体把《让子弹飞》盘到包浆，他们对片中的台词金句如数家珍。\n"
)


def _run(tmp_path: Path, delivery: str, *, facts=("影片由姜文执导",)) -> Path:
    root = tmp_path / "daily-900"
    (root / "delivery" / "art-001").mkdir(parents=True)
    (root / "material-packs").mkdir(parents=True)
    (root / "delivery" / "art-001" / "delivery.md").write_text(delivery, encoding="utf-8")
    (root / "material-packs" / "art-001.json").write_text(
        json.dumps({"obtained_facts_by_source": {"src-a": list(facts)}}, ensure_ascii=False),
        encoding="utf-8",
    )
    return root


def test_prompt_lists_the_two_missed_categories():
    assert "时间跨度" in pre.SYSTEM_PROMPT
    assert "受众行为" in pre.SYSTEM_PROMPT
    assert "daily-008" in pre.SYSTEM_PROMPT


def test_assertion_gaps_flags_008_regression(tmp_path: Path):
    root = _run(tmp_path, DELIVERY_GAPS)
    gaps = pre.assertion_gaps(root, "art-001")
    assert any(item.startswith("assertion_not_in_ledger:time_span:") for item in gaps["assertion_errors"])
    assert any(item.startswith("assertion_not_in_ledger:audience_action:") for item in gaps["assertion_errors"])
    assert gaps["assertion_uncovered"]


def test_assertion_gaps_clean_when_ledger_covers(tmp_path: Path):
    root = _run(
        tmp_path, DELIVERY_OK,
        facts=["十多年来，庞大的影迷群体把《让子弹飞》盘到包浆，他们对片中的台词金句如数家珍"],
    )
    gaps = pre.assertion_gaps(root, "art-001")
    assert gaps["assertion_errors"] == []
    assert gaps["assertion_uncovered"] == []


def test_main_writes_deterministic_gaps_even_without_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """强制 LLM 不可用：确定性断言缺口照常产出（这条路径不依赖凭据/网络）。"""
    root = _run(tmp_path, DELIVERY_GAPS)

    def no_llm(*_args, **_kwargs):
        raise pre.LlmUnavailable("no credentials in test env")

    monkeypatch.setattr(pre, "llm_chat", no_llm)
    monkeypatch.setattr(sys, "argv", ["ledger_coverage_precheck.py", "--run-root", str(root),
                                      "--aid", "art-001"])
    assert pre.main() == 0
    record = json.loads(
        (root / "review" / "art-001" / "ledger-coverage-precheck.json").read_text(encoding="utf-8")
    )
    assert record["schema_version"] == "ledger-coverage-precheck-v1"
    assert any("time_span" in item for item in record["assertion_errors"])
    assert "assertion_warnings" in record and "orphan_ledger" in record
    # LLM 不可用只影响 llm_gaps，不影响确定性断言结果
    assert record["llm_status"].startswith("skipped")
    assert record["llm_gaps"] == []
    assert record["publication_authorization"] == "not_authorized"


def test_main_reports_orphan_ledger_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _run(tmp_path, DELIVERY_GAPS, facts=("这条事实正文里没有提到过",))

    def no_llm(*_args, **_kwargs):
        raise pre.LlmUnavailable("no credentials in test env")

    monkeypatch.setattr(pre, "llm_chat", no_llm)
    monkeypatch.setattr(sys, "argv", ["x", "--run-root", str(root), "--aid", "art-001"])
    pre.main()
    record = json.loads(
        (root / "review" / "art-001" / "ledger-coverage-precheck.json").read_text(encoding="utf-8")
    )
    assert record["orphan_ledger"] == [{"ref": "pack:src-a", "text": "这条事实正文里没有提到过"}]
