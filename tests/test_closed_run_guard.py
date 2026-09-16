"""已收尾 run 的证据保护（run_state + 各写证据 CLI 的 --force 守卫）。

事故背景（2026-09-17）：daily-008 收尾后，为演示扩展后的预检工具，直接在
已收尾 run 上重跑 ledger_coverage_precheck.py，覆盖了 review/art-001/
ledger-coverage-precheck.json（10:20 那版，记录的是修复前的缺口）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from article_group import evidence_rebind
from article_group.run_state import closed_reason, run_is_closed
from scripts import ledger_coverage_precheck as pre


def _run(tmp_path: Path, *, accepted: bool = False, attestation: bool = False) -> Path:
    root = tmp_path / "daily-900"
    (root / "delivery" / "art-001").mkdir(parents=True)
    (root / "material-packs").mkdir(parents=True)
    (root / "delivery" / "art-001" / "delivery.md").write_text("# 标题\n\n正文。\n", encoding="utf-8")
    (root / "material-packs" / "art-001.json").write_text(
        json.dumps({"obtained_facts_by_source": {"src-a": ["一条事实"]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "batch.json").write_text(json.dumps({
        "articles": [{
            "article_id": "art-001",
            "gate_status": {"controller_acceptance": "accepted" if accepted else "pending"},
        }],
    }, ensure_ascii=False), encoding="utf-8")
    if attestation:
        target = root / "review" / "attestation"
        target.mkdir(parents=True, exist_ok=True)
        (target / "art-001.human.json").write_text(json.dumps({"decision": "accept"}), encoding="utf-8")
    return root


def test_run_is_closed_detects_acceptance(tmp_path: Path):
    open_run = _run(tmp_path / "a")
    assert run_is_closed(open_run) is False and closed_reason(open_run) == ""
    closed_run = _run(tmp_path / "b", accepted=True)
    assert run_is_closed(closed_run) is True
    assert "controller_acceptance=accepted:art-001" in closed_reason(closed_run)


def test_run_is_closed_detects_attestation(tmp_path: Path):
    root = _run(tmp_path / "c", attestation=True)
    assert run_is_closed(root) is True
    assert closed_reason(root) == "human_attestation_present"


def test_precheck_refuses_to_overwrite_closed_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _run(tmp_path, accepted=True)
    review = root / "review" / "art-001"
    review.mkdir(parents=True, exist_ok=True)
    record = review / "ledger-coverage-precheck.json"
    record.write_text('{"schema_version": "ledger-coverage-precheck-v1", "frozen": true}', encoding="utf-8")
    before = record.read_text(encoding="utf-8")

    def no_llm(*_args, **_kwargs):
        raise pre.LlmUnavailable("offline")

    monkeypatch.setattr(pre, "llm_chat", no_llm)
    monkeypatch.setattr(sys, "argv", ["x", "--run-root", str(root), "--aid", "art-001"])
    assert pre.main() == 2
    assert record.read_text(encoding="utf-8") == before  # 一字未改


def test_precheck_force_allows_rerun_on_closed_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _run(tmp_path, accepted=True)

    def no_llm(*_args, **_kwargs):
        raise pre.LlmUnavailable("offline")

    monkeypatch.setattr(pre, "llm_chat", no_llm)
    monkeypatch.setattr(sys, "argv", ["x", "--run-root", str(root), "--aid", "art-001", "--force"])
    assert pre.main() == 0
    record = json.loads(
        (root / "review" / "art-001" / "ledger-coverage-precheck.json").read_text(encoding="utf-8")
    )
    assert record["schema_version"] == "ledger-coverage-precheck-v1"


def test_evidence_rebind_refuses_apply_on_closed_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _run(tmp_path, accepted=True)
    (root / "review" / "art-001").mkdir(parents=True, exist_ok=True)
    (root / "review" / "art-001" / "independent-review.json").write_text(json.dumps({
        "status": "complete", "decision": "approve", "artifact_sha256": "0" * 64,
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["x", "--run-root", str(root), "--apply"])
    assert evidence_rebind.main() == 2
    record = json.loads(
        (root / "review" / "art-001" / "independent-review.json").read_text(encoding="utf-8")
    )
    assert "stale" not in record


def test_evidence_rebind_force_applies_on_closed_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _run(tmp_path, accepted=True)
    (root / "review" / "art-001").mkdir(parents=True, exist_ok=True)
    (root / "review" / "art-001" / "independent-review.json").write_text(json.dumps({
        "status": "complete", "decision": "approve", "artifact_sha256": "0" * 64,
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["x", "--run-root", str(root), "--apply", "--force"])
    assert evidence_rebind.main() == 0
    record = json.loads(
        (root / "review" / "art-001" / "independent-review.json").read_text(encoding="utf-8")
    )
    assert record["stale"] is True
