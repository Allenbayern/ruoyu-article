"""Tests for B8 Human-Tone Adversarial Dual Review Evaluator (scripts/b8_dual_review_evaluator.py)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from scripts import b8_dual_review_evaluator


def test_b8_dual_review_evaluates_at_least_five_cases() -> None:
    """验证 B8 双复核评测引擎覆盖至少 5 篇真实案例，且数据结构完整。"""
    res = b8_dual_review_evaluator.evaluate_dual_reviews(b8_dual_review_evaluator.TARGET_CASES)
    assert res["schema_version"] == "b8-dual-review-evaluation-v1"
    stats = res["stats"]
    assert stats["case_count"] >= 5
    assert stats["case_count"] == len(res["cases"])


def test_b8_dual_review_inter_rater_agreement_is_reliable() -> None:
    """验证双审视角在决策与 Q1~Q3 三问判定上的一致性达到高可靠性标准（>=90%）。"""
    res = b8_dual_review_evaluator.evaluate_dual_reviews(b8_dual_review_evaluator.TARGET_CASES)
    stats = res["stats"]
    assert stats["decision_agreement_rate"] >= 0.9
    assert stats["q1_agreement_rate"] >= 0.9
    assert stats["q2_agreement_rate"] >= 0.9
    assert stats["q3_agreement_rate"] >= 0.9


def test_b8_dual_review_evidence_quotes_are_strictly_verbatim() -> None:
    """验证双审提出的所有 findings 引用证据在对应 draft.md 中 100% 逐字命中。"""
    res = b8_dual_review_evaluator.evaluate_dual_reviews(b8_dual_review_evaluator.TARGET_CASES)
    stats = res["stats"]
    assert stats["quote_match_rate"] == 1.0
    assert stats["total_findings"] > 0
    assert stats["total_quote_matched"] == stats["total_findings"]

    for case in res["cases"]:
        assert case["reviewer_a"]["quote_verification"]["pass"] is True
        assert case["reviewer_b"]["quote_verification"]["pass"] is True
        assert len(case["reviewer_a"]["quote_verification"]["mismatched"]) == 0
        assert len(case["reviewer_b"]["quote_verification"]["mismatched"]) == 0


def test_b8_dual_review_render_markdown_report() -> None:
    """验证 Markdown 报告渲染完整且包含三问细分解析。"""
    res = b8_dual_review_evaluator.evaluate_dual_reviews(b8_dual_review_evaluator.TARGET_CASES)
    md = b8_dual_review_evaluator.render_markdown_report(res)
    assert "# B8 人味儿固定三问扩跑双复核可靠性验证报告" in md
    assert "## 一、 评测案例与双审裁定汇总" in md
    assert "## 二、 B8 人味儿固定三问细分对照解析" in md
    assert "## 三、 扩跑验证结论" in md
    assert "case-010" in md
    assert "case-011" in md
    assert "case-009" in md
    assert "case-001" in md
    assert "case-006" in md


def test_b8_dual_review_main_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """验证 CLI 命令行能够正常输出并落盘。"""
    out_dir = tmp_path / "b8_eval_cli"
    monkeypatch.setattr(b8_dual_review_evaluator.sys, "argv", ["b8_dual_review_evaluator.py", "--out-dir", str(out_dir)])
    rc = b8_dual_review_evaluator.main()
    assert rc == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "PASS"
    assert payload["cases_evaluated"] >= 5
    assert (out_dir / "b8-dual-review-report.json").is_file()
    assert (out_dir / "b8-dual-review-report.md").is_file()
