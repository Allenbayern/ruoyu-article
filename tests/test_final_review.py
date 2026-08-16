"""final_review（prepublication 总复核层）测试。

6 类用例：证据缺失 / 机械失败 / 发布不变量 / 重复指纹 / 存疑触发 / 全通过。
用 tmp_path 构造最小批次产物，不依赖 runs/ 存量。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from article_group.final_review import (
    BLOCKED,
    PENDING,
    PUBLISHABLE,
    evaluate_batch,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _make_batch(root: Path, *, preflight_status: str = "PASS",
                auth: str = "not_authorized",
                style_error: int = 0, style_warning: bool = False,
                with_style: bool = True, with_prose: bool = True,
                with_editorial: bool = False) -> Path:
    """构造一个最小可复核批次目录，返回 batch 目录。"""
    batch = root / "controlled-999"
    _write_json(batch / "batch.json", {
        "run_id": "2026-08-16/controlled-999",
        "articles": [
            {
                "article_id": "art-001",
                "work": "《测试电影》的票房奇迹",
                "reader_question": "为什么《测试电影》一夜爆红",
                "publication_authorization": auth,
            },
            {
                "article_id": "art-002",
                "work": "《另一部片》的口碑分化",
                "reader_question": "为什么《另一部片》口碑两极",
                "publication_authorization": auth,
            },
        ],
    })
    _write_json(batch / "preflight-report.json", {
        "status": preflight_status,
        "run_id": "2026-08-16/controlled-999",
    })
    if with_style:
        hits = [{"severity": "warning", "rule": "claim:age-inference",
                 "reason": "无源年龄推算"}] if style_warning else []
        _write_json(batch / "review" / "style-gate-art-001.json", {
            "article_count": 1,
            "pass": style_error == 0,
            "articles": [{
                "index": 1,
                "title": "测试文章标题",
                "char_count": 1800,
                "error_count": style_error,
                "hits": hits,
            }],
        })
    if with_prose:
        _write_json(batch / "review" / "prose-pilot-report.json", {
            "advisory": True,
            "batches": [{"name": "controlled-999-v1",
                         "articles": [{"label": "art-001-v1#1", "advisory": True,
                                       "title": "测试文章标题", "chars": 1850}]}],
        })
    if with_editorial:
        # 合法的四阶段记录最小形态（协议 v1.0）
        _write_json(batch / "review" / "editorial-record.json", {
            "protocol_version": "1.0",
            "record_revision": 1,
            "run_id": "2026-08-16/controlled-999",
            "article_id": "art-001",
            "publication_authorization": "not_authorized",
            "card_refs": {},
            "stages": [],
            "stop_draft": None,
        })
    (batch / "review" / "ruoyu-art-001-2026-08-16.html").write_text(
        "<h2>测试文章标题</h2>", encoding="utf-8")
    return batch


def test_evidence_missing_batch_json(tmp_path: Path) -> None:
    batch = tmp_path / "controlled-888"
    batch.mkdir(parents=True)
    report = evaluate_batch(batch)
    assert report["verdict"] == BLOCKED
    assert report["reason"] == "evidence_missing:batch.json"


def test_evidence_missing_preflight(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path)
    (batch / "preflight-report.json").unlink()
    report = evaluate_batch(batch)
    assert report["verdict"] == BLOCKED
    assert report["reason"] == "evidence_missing:preflight-report.json"


def test_mechanical_gate_preflight_fail(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path, preflight_status="FAIL")
    report = evaluate_batch(batch)
    assert report["verdict"] == BLOCKED
    assert report["reason"] == "gate:preflight"


def test_mechanical_gate_style_error(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path, style_error=2)
    report = evaluate_batch(batch)
    assert report["verdict"] == BLOCKED
    assert report["reason"] == "gate:style_gate"


def test_publication_authorization_violation(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path, auth="authorized")
    report = evaluate_batch(batch)
    assert report["verdict"] == BLOCKED
    assert report["reason"] == "gate:publication_authorization"


def test_style_warning_triggers_pending(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path, style_warning=True)
    report = evaluate_batch(batch)
    assert report["verdict"] == PENDING
    assert any("claim:age-inference" in i for i in report["human_judgment_items"])


def test_all_pass_publishable(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path)
    report = evaluate_batch(batch)
    assert report["verdict"] == PUBLISHABLE
    assert report["publication_authorization"] == "not_authorized"


def test_editorial_record_invalid_blocks(tmp_path: Path) -> None:
    """editorial-record 存在但校验失败 → 必须 BLOCKED（fail-closed）。

    合法记录的四阶段契约校验由 editorial_review 自身测试覆盖；
    final_review 只保证消费侧不放过非法记录。
    """
    batch = _make_batch(tmp_path, with_editorial=True)
    report = evaluate_batch(batch)
    assert report["verdict"] == BLOCKED
    assert report["reason"] == "gate:editorial_review"


def test_prose_missing_blocks(tmp_path: Path) -> None:
    """证据链缺失 = BLOCKED（fail-closed）：prose-pilot 报告是必需产物。"""
    batch = _make_batch(tmp_path, with_prose=False)
    report = evaluate_batch(batch)
    assert report["verdict"] == BLOCKED
    assert report["reason"] == "evidence_missing:prose-pilot-report.json"


def test_char_count_divergence_pending(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path)
    # 把 prose chars 改成与 style_gate 差 > 15%
    p = batch / "review" / "prose-pilot-report.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["batches"][0]["articles"][0]["chars"] = 2400  # 1800 vs 2400 = 25% 差
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    report = evaluate_batch(batch)
    assert report["verdict"] == PENDING
    assert any("style_gate=" in i for i in report["human_judgment_items"])
