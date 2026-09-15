"""daily-005 run 报告集成断言：门禁显式化 + prose_pilot / git_hygiene 真接入。

这些断言锁住 run 报告里的制度性事实：
- task-hierarchy 1.0 契约门禁真实运行且通过；
- compliance_gate 未跑必须显式记录 not_run + 原因（不许静默跳过）；
- git_hygiene 基础设施就绪快照与仓库实况一致；
- prose_pilot 报告是真实材料/密度分析，不是占位摘要。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from article_group.git_hygiene import validate_infra_ready
from article_group.prose_pilot import analyze_text

RUN = Path("runs/2026-09-15/daily-005")

pytestmark = pytest.mark.skipif(
    not (RUN / "batch.json").exists(),
    reason="runs/ 是本地审计目录（gitignore），daily-005 不在当前工作树时不跑集成断言",
)


def _load(rel: str) -> dict:
    return json.loads((RUN / rel).read_text(encoding="utf-8"))


def test_task_hierarchy_validation_report_passes():
    report = _load("task-hierarchy-validation-report.json")
    assert report["schema_version"] == "task-hierarchy-validation-v1"
    assert report["pass"] is True
    assert report["errors"] == []
    assert {a["article_id"] for a in report["articles"]} == {"art-001", "art-002"}


def test_compliance_gate_not_run_is_explicit():
    gate = _load("review/gates/compliance-gate.json")
    assert gate["schema_version"] == "compliance-gate-v1"
    assert gate["full_gate"] == "not_run"
    assert "social_topic" in gate["full_gate_reason"]
    preflight = _load("preflight-report.json")
    assert preflight["checks"]["compliance_gate"] == "not_run"
    assert preflight["checks"]["task_hierarchy_contract"] == "pass"


def test_git_hygiene_report_matches_live_repo():
    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    missing = validate_infra_ready(tracked)
    report = _load("review/gates/git-hygiene.json")
    assert report["schema_version"] == "git-hygiene-v1"
    assert report["mode"] == "infra_ready"
    assert report["missing"] == missing
    assert report["pass"] is (not missing)


def test_prose_pilot_report_is_real_analysis():
    from scripts.run_real_daily_005 import MATERIAL_SPECS, SOURCE_IDS, SOURCES

    report = _load("review/prose-pilot-report.json")
    assert report["schema_version"] == "prose-pilot-v1"
    assert report["advisory"] is True
    batch = report["batches"][0]
    by_id = {a["article_id"]: a for a in batch["articles"]}
    assert set(by_id) == {"art-001", "art-002"}
    for aid in ("art-001", "art-002"):
        text = (RUN / f"delivery/{aid}/delivery.md").read_text(encoding="utf-8")
        ledger_quotes = [
            {
                "source_id": source_id,
                "title": SOURCES[source_id].get("captured_from", source_id),
                "url": SOURCES[source_id].get("source_url", ""),
                "text": fact,
            }
            for source_id in SOURCE_IDS[aid]
            for fact in MATERIAL_SPECS[aid]["by_source"].get(source_id, [])
        ]
        expected = analyze_text(text, by_id[aid]["title"], ledger_quotes)
        assert by_id[aid]["material"] == expected["material"]
        assert by_id[aid]["syntax_warnings"] == expected["syntax_warnings"]
        assert by_id[aid]["advisory"] is True


def test_batch_gate_status_backfilled_from_real_artifacts():
    # ③（2026-09-15）：batch.json 的 gate_status 不再手写，必须等于从
    # 真实门禁产物重算的值。
    from article_group.content_fidelity import evaluate_content_fidelity
    from article_group.title_pack_fidelity import evaluate_title_pack

    batch = _load("batch.json")
    for article in batch["articles"]:
        aid = article["article_id"]
        pack = _load(f"material-packs/{aid}.json")
        readiness = pack.get("readiness", {})
        cf = _load(f"review/{aid}/content-fidelity.json")
        tp = _load(f"review/{aid}/title-pack.json")
        style = _load(f"review/style-gate-markdown-{aid}.json")
        independent = _load(f"review/{aid}/independent-review.json")
        expected = {
            "material_ready_for_draft": "pass" if readiness.get("material_ready_for_draft") else "fail",
            "editorial_value_ready": "pass" if readiness.get("editorial_value_ready") else "fail",
            "content_fidelity": str(evaluate_content_fidelity(cf, strict=True).get("status")),
            "title_pack": str(evaluate_title_pack(tp).get("status")),
            "style_gate": "pass" if style.get("pass") and not style.get("error_total") else "fail",
            "independent_review": str(independent.get("status", "pending")).lower(),
        }
        for key, want in expected.items():
            assert article["gate_status"][key] == want, (
                aid, key, article["gate_status"][key], want,
            )
    assert set(batch["run_gates"]) >= {
        "portfolio_gate",
        "task_hierarchy_contract",
        "claim_source_provenance",
        "git_hygiene_infra",
        "compliance_gate",
    }


def test_delivery_hashes_unchanged_after_gate_wiring():
    # 门禁接入不得改动交付正文（2026-09-15 两篇交付哈希基线）。
    import hashlib

    expected = {
        "art-001": "9425d9bd364e1114cf4b8739688138909f87dd88e27d36629ab55b52770602f0",
        "art-002": "e00f5ab2b87291db0cb325bf3f53f7bd00787fb720fd7612d93ac8c6e179d8ad",
    }
    for aid, want in expected.items():
        got = hashlib.sha256((RUN / f"delivery/{aid}/delivery.md").read_bytes()).hexdigest()
        assert got == want, f"{aid} 交付哈希漂移: {got}"
