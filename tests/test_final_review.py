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
                "candidate_id": "cand-001",
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


def test_fact_density_warning_triggers_pending(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path)
    style_path = batch / "review" / "style-gate-art-001.json"
    style = json.loads(style_path.read_text(encoding="utf-8"))
    style["articles"][0]["fact_density"] = {
        "status": "warning",
        "reason": "事实锚点段落仅 4/16 (<1/3)",
    }
    style["articles"][0]["hits"] = []
    style_path.write_text(json.dumps(style, ensure_ascii=False), encoding="utf-8")

    report = evaluate_batch(batch)

    assert report["verdict"] == PENDING
    assert any(
        "fact_density" in item and "4/16" in item
        for item in report["human_judgment_items"]
    )


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("opening_hook", "开头缺少事实锚点"),
        ("title_gap", "标题缺少心理缺口"),
        ("fact_density", "事实锚点段落仅 4/16"),
        ("hook_declaration", "未声明最强钩子"),
        ("closing_interaction", "结尾互动检查需要人工判断"),
    ],
)
def test_structured_style_warning_triggers_pending(
    tmp_path: Path, field: str, reason: str
) -> None:
    batch = _make_batch(tmp_path)
    style_path = batch / "review" / "style-gate-art-001.json"
    style = json.loads(style_path.read_text(encoding="utf-8"))
    style["articles"][0][field] = {"status": "warning", "reason": reason}
    style["articles"][0]["hits"] = []
    style_path.write_text(json.dumps(style, ensure_ascii=False), encoding="utf-8")

    report = evaluate_batch(batch)

    assert report["verdict"] == PENDING
    assert any(f"{field}: {reason}" in item for item in report["human_judgment_items"])


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
    batch = _make_batch(tmp_path, with_style=True, with_prose=True)
    # prose chars 与 style chars 差距超阈值 → PENDING
    prose = json.loads((batch / "review" / "prose-pilot-report.json").read_text())
    prose["batches"][0]["articles"][0]["chars"] = 2600
    (batch / "review" / "prose-pilot-report.json").write_text(
        json.dumps(prose, ensure_ascii=False), encoding="utf-8")
    report = evaluate_batch(batch)
    assert report["verdict"] == PENDING
    assert report["publication_authorization"] == "not_authorized"


def _fake_history_with_duplicate(exclude_run: str = "") -> list[dict]:
    """历史批次含《测试电影》旧文 → check_cross_batch 应报 same_work error。

    签名与 collect_history 一致（接受 exclude_run），供 monkeypatch 替换。
    """
    assert exclude_run != "controlled-015"  # 排除本批时不命中（防御性）
    return [{
        "batch_dir": "controlled-015",
        "path": "/fake/controlled-015/review/frozen/x.html",
        "titles": ["《测试电影》的票房奇迹（旧角度）"],
        "works": ["测试电影"],
        "recent3": True,
    }]


def test_cross_batch_duplicate_without_waiver_blocks(tmp_path: Path, monkeypatch) -> None:
    """跨批重复、无人工裁决注记 → BLOCKED（机器只拦未裁决重复）。"""
    batch = _make_batch(tmp_path, with_style=True, with_prose=True)
    monkeypatch.setattr("article_group.final_review.collect_history",
                        _fake_history_with_duplicate)
    report = evaluate_batch(batch)
    assert report["verdict"] == BLOCKED
    assert "cross_batch" in str(report.get("reason", ""))


def test_cross_batch_duplicate_with_waiver_passes(tmp_path: Path, monkeypatch) -> None:
    """跨批重复、但 portfolio-gate-report.json 已有人工裁决豁免注记 → 放行。

    026 真实形态：controller_adjudication.result = 'cand-001 红灯确认豁免（confirmed_new_angle）'，
    adjudicated=True，机器 respect 人工裁决、绝不自造豁免。
    """
    batch = _make_batch(tmp_path, with_style=True, with_prose=True)
    _write_json(batch / "portfolio-gate-report.json", {
        "pass": False,
        "errors": [{"level": "error", "candidate": "cand-001",
                     "id": "portfolio.cross_batch.same_work.recent"}],
        "controller_adjudication": {
            "recorded_at": "2026-08-16 22:40 CST",
            "adjudicator": "controller",
            "adjudicated": True,
            "result": "cand-001 红灯确认豁免（confirmed_new_angle）",
        },
    })
    monkeypatch.setattr("article_group.final_review.collect_history",
                        _fake_history_with_duplicate)
    report = evaluate_batch(batch)
    assert report["verdict"] == PUBLISHABLE
    assert report["adjudicated_waivers"], "豁免注记应进入结果"
    assert report["adjudicated_waivers"][0]["candidate"] == "cand-001"
    assert "confirmed_new_angle" in report["adjudicated_waivers"][0]["verdict"]


def test_waiver_requires_candidate_match(tmp_path: Path, monkeypatch) -> None:
    """裁决注记存在但 candidate 不匹配 → 不豁免（仍 BLOCKED）。"""
    batch = _make_batch(tmp_path, with_style=True, with_prose=True)
    _write_json(batch / "portfolio-gate-report.json", {
        "controller_adjudication": {
            "adjudicated": True,
            "result": "cand-999 确认豁免",
        },
    })
    monkeypatch.setattr("article_group.final_review.collect_history",
                        _fake_history_with_duplicate)
    report = evaluate_batch(batch)
    assert report["verdict"] == BLOCKED


def test_waiver_requires_adjudicated_flag(tmp_path: Path, monkeypatch) -> None:
    """注记存在但 adjudicated 非 True → 不豁免（机器不自行解读）。"""
    batch = _make_batch(tmp_path, with_style=True, with_prose=True)
    _write_json(batch / "portfolio-gate-report.json", {
        "controller_adjudication": {
            "adjudicated": False,
            "result": "cand-001 确认豁免",
        },
    })
    monkeypatch.setattr("article_group.final_review.collect_history",
                        _fake_history_with_duplicate)
    report = evaluate_batch(batch)
    assert report["verdict"] == BLOCKED
