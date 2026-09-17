"""占位符凭证在生产入口必须**可见**（只标不阻断，不改变任何资格判定）。

背景：爆款库里 14 张自称 `qualified_viral` 的卡，`client_evidence.sha256` 是 64 个 0。
检测函数（`case_contract.case_card_warnings`）早在 df50d54 就落地了，但**没有生产消费方**——
收集器没人传，等于不可见。本组用例覆盖这些卡真正流经的四条路径：

| 路径 | 期望 |
|---|---|
| legacy 索引（14 张卡真正被读的地方） | 记录带 warnings/warning_codes，pack 带 warning_counts、usable_with_warnings_count |
| package 组装 | 资格被降级时，原因随 sample 落盘，不再无声 |
| 卡片信封（`cards.build_case_card`） | `case_contract.warnings` 随信封落盘并通过 schema |
| distill / 新 contract | 占位符是**硬拒**（摘要绑定），不是 warning——用测试钉住，避免补一条用不到的通道 |

硬约束：warning 不改 `qualification_status`、不改 `usable_for_positive_patterns`、
不改 `promotion_status`。收紧成硬失败会把现有唯一一批合格语料清零（见 case_contract 注释）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from article_group.case_contract import PLACEHOLDER_WARNING_CODE
from article_group.viral_research_cards import build_case_card
from article_group.viral_research_distill import (
    ViralResearchDistillError,
    finalize_distillation,
)
from article_group.viral_research_package import build_package, validate_package_root
from scripts.codex_viral_library_index import build_index

ALL_ZERO = "0" * 64


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _legacy_card(sample_id: str, *, sha256: str) -> dict:
    return {
        "sample_id": sample_id,
        "qualification_status": "qualified_viral",
        "snapshot_ref": f"clean/{sample_id}.md#sha256={'a' * 64}",
        "performance_evidence_ref": f"metrics/{sample_id}.json",
        "metrics": [],
        "client_evidence": {
            "evidence_ref": f"metrics/{sample_id}.json#sha256={'b' * 64}",
            "original_display": "200000 views",
            "observed_at": "2026-08-11T10:00:00+08:00",
            "confirmer": "reviewer-1",
            "sha256": sha256,
            "sanitized": True,
        },
        "technique_observations": [{"technique_id": "WX-O1"}],
    }


def _legacy_run(tmp_path: Path, cards: dict[str, dict]) -> Path:
    run = Path("runs/2026-08-11/viral-research")
    for sample_id, card in cards.items():
        _write_json(tmp_path / run / "wechat-viral" / "cards" / f"{sample_id}.json", card)
        (tmp_path / run / "wechat-viral" / "clean").mkdir(parents=True, exist_ok=True)
        (tmp_path / run / "wechat-viral" / "clean" / f"{sample_id}.md").write_text(
            "# 快照\n", encoding="utf-8"
        )
        (tmp_path / run / "wechat-viral" / "metrics").mkdir(parents=True, exist_ok=True)
        (tmp_path / run / "wechat-viral" / "metrics" / f"{sample_id}.json").write_text(
            '{"views": 200000}', encoding="utf-8"
        )
    return run


def _wechat_pack(index: dict) -> dict:
    packs = index["evidence_library"]["packs"]
    return next(pack for pack in packs if pack["pack"] == "wechat-viral")


# ---- ① legacy 索引：14 张卡真正被读的地方 ----


def test_index_surfaces_placeholder_client_evidence(tmp_path: Path) -> None:
    run = _legacy_run(tmp_path, {
        "wx-placeholder": _legacy_card("wx-placeholder", sha256=ALL_ZERO),
        "wx-real": _legacy_card("wx-real", sha256=hashlib.sha256(b"real").hexdigest()),
    })
    pack = _wechat_pack(build_index(project_root=tmp_path, evidence_run=run))

    records = {record["sample_id"]: record for record in pack["samples"]}
    flagged = records["wx-placeholder"]
    assert [item["code"] for item in flagged["warnings"]] == [PLACEHOLDER_WARNING_CODE]
    assert flagged["warning_codes"] == [PLACEHOLDER_WARNING_CODE]
    assert flagged["warnings"][0]["severity"] == "warning"
    # 只标不阻断：资格判定与"可用于正向模式"完全不变
    assert flagged["qualification_status"] == "qualified_viral"
    assert flagged["usable_for_positive_patterns"] is True
    assert pack["usable_with_warnings_count"] == 1
    assert pack["warning_counts"] == {PLACEHOLDER_WARNING_CODE: 1}

    clean = records["wx-real"]
    assert "warnings" not in clean and "warning_codes" not in clean
    assert pack["qualified_usable_count"] == 2  # 两张都仍算可用


# ---- ② package 组装：降级不再无声 ----


def test_package_downgrade_records_placeholder_warning(tmp_path: Path) -> None:
    from tests.test_viral_research_package import _capture

    capture = _capture(tmp_path)
    payload = json.loads(capture.read_text(encoding="utf-8"))
    payload["samples"][0]["case_contract_card"]["client_evidence"]["sha256"] = ALL_ZERO
    capture.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    output = tmp_path / "viral-research" / "package"
    manifest = build_package(capture, run_root=tmp_path, output_root=output)
    sample = manifest["samples"][0]

    assert sample["qualification_status"] != "qualified_viral"  # 摘要绑定不上 → 降级
    codes = {item["code"] for item in sample.get("warnings", [])}
    assert PLACEHOLDER_WARNING_CODE in codes  # 降级原因写得出来
    assert validate_package_root(output)["status"] == manifest["status"]  # 产物仍自洽


# ---- ③ 卡片信封：warning 随卡落盘（并经 schema 校验） ----


def test_card_envelope_carries_case_contract_warnings(tmp_path: Path) -> None:
    from tests.test_viral_research_package import _capture

    capture = _capture(tmp_path)
    payload = json.loads(capture.read_text(encoding="utf-8"))
    sample = dict(payload["samples"][0])
    card = sample["case_contract_card"]
    card["client_evidence"]["sha256"] = ALL_ZERO
    sample["sample_id"] = card["sample_id"]  # 信封要求 sample_id（夹具里由卡片推导）
    for field, relative in (
        ("raw_ref", "raw/article.html"),
        ("clean_ref", "clean/article.md"),
        ("metadata_ref", "metadata/article.json"),
    ):
        path = tmp_path / relative
        sample[field] = f"{relative}#sha256={hashlib.sha256(path.read_bytes()).hexdigest()}"

    envelope = build_case_card(sample, run_root=tmp_path, case_contract_card=card)

    contract = envelope["case_contract"]
    assert contract["status"] == "validated"
    assert [item["code"] for item in contract["warnings"]] == [PLACEHOLDER_WARNING_CODE]
    # build_case_card 内部会对信封跑 schema 校验：能返回就说明 schema 已放行该字段


# ---- ④ distill：对占位符是硬拒，不是 warning（钉住，避免死通道） ----


def test_distill_hard_rejects_placeholder_client_evidence(tmp_path: Path) -> None:
    from tests.test_viral_research_distill import _criteria, _prepare_and_write_cards

    prepare_path, cards_root, _ = _prepare_and_write_cards(tmp_path)
    manifest_path = cards_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = manifest["cards"][0]
    card_path = cards_root / entry["card_ref"]
    card = json.loads(card_path.read_text(encoding="utf-8"))
    card["client_evidence"]["sha256"] = ALL_ZERO
    card_path.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    entry["sha256"] = hashlib.sha256(card_path.read_bytes()).hexdigest()  # 保持卡片批次绑定有效
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    with pytest.raises(ViralResearchDistillError) as excinfo:
        finalize_distillation(
            prepare_path,
            package_root=cards_root.parent / "package",
            criteria=_criteria(),
            cards_root=cards_root,
            output_path=tmp_path / "review.json",
        )
    # 摘要是硬绑定：占位符在这里根本到不了 warning 通道（所以 distill 不接收集器）
    assert getattr(excinfo.value, "code", "") == "card_client_evidence_sha256_mismatch"
    assert not (tmp_path / "review.json").exists()
