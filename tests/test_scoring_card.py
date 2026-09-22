"""评分卡诚实化单测（2026-09-21）。

背景：评分卡的分项分与总分在 daily_engine 里是字面常量（三篇一律 86），却要过
``final_review`` 的 ``_SCORING_FLOORS``（总分 ≥75、证据分 ≥15）——对任何稿件恒真，
于是"评分卡校验"成了摆设（L2：任何一稿都会得到 86 分）。这里钉住三件事：

1. 卡里必须自述 ``card_kind=template_unmeasured`` / ``measured=false``；
2. 历史字段保留且仍满足下游的区间/下限/求和校验（否则会打断 final_review）；
3. ``measured_signals`` 必须是真算出来的（硬信息落段率、风格记录的结构量）。
"""

from __future__ import annotations

import hashlib
import math

from article_group.scoring_card import (
    TEMPLATE_COMPONENTS,
    TEMPLATE_TOTAL,
    build_scoring_card,
    hard_information_coverage,
)

BODY = "第一段。\n\n## 小节\n\n第二段。\n\n第三段。"
STYLE_GATE = {
    "pass": True,
    "error_total": 0,
    "articles": [
        {"char_count": 1234, "error_count": 0, "thin_section": {"status": "ok"}},
    ],
}
CONTENT_FIDELITY = {
    "hard_information": [
        {"information_id": "i1", "body_locator": "p1"},
        {"information_id": "i2", "body_locator": "p2"},
        {"information_id": "i3", "body_locator": "p9"},  # 越界：正文只有 3 段
    ]
}


def _digest(_path: str) -> str:
    return hashlib.sha256(b"x").hexdigest()


def test_card_declares_itself_unmeasured() -> None:
    card = build_scoring_card(
        aid="art-001",
        delivery_path="delivery/art-001/delivery.md",
        body=BODY,
        digest_fn=_digest,
        style_gate=STYLE_GATE,
        content_fidelity=CONTENT_FIDELITY,
    )
    assert card["card_kind"] == "template_unmeasured"
    assert card["measured"] is False
    assert "不是对该稿的测量" in card["note"]


def test_legacy_fields_still_satisfy_downstream_validation() -> None:
    """分值可以换成实测，但**这轮**只把它们标注为非测量；下游校验不能被打断。"""
    card = build_scoring_card(
        aid="art-001",
        delivery_path="delivery/art-001/delivery.md",
        body=BODY,
        digest_fn=_digest,
    )
    assert card["total_score"] == TEMPLATE_TOTAL == 86
    for field, value in TEMPLATE_COMPONENTS.items():
        assert card[field] == value
    components = sum(card[field] for field in TEMPLATE_COMPONENTS)
    assert math.isclose(card["total_score"], components, rel_tol=0, abs_tol=1e-9)
    # 下限：总分 ≥75、证据分 ≥15（_SCORING_FLOORS）
    assert card["total_score"] >= 75
    assert card["evidence_score"] >= 15


def test_measured_signals_are_actually_computed() -> None:
    card = build_scoring_card(
        aid="art-001",
        delivery_path="delivery/art-001/delivery.md",
        body=BODY,
        digest_fn=_digest,
        style_gate=STYLE_GATE,
        content_fidelity=CONTENT_FIDELITY,
    )
    signals = card["measured_signals"]
    # 正文 3 段：i1/i2 落段，i3 指向 p9 越界
    assert signals["hard_information_coverage"] == {"total": 3, "located": 2, "ratio": 0.667}
    assert signals["style_record"] == {
        "status": True,
        "error_count": 0,
        "char_count": 1234,
        "thin_section": "ok",
    }


def test_coverage_handles_missing_ledger_gracefully() -> None:
    assert hard_information_coverage(None, ["a", "b"]) == {"total": 0, "located": 0, "ratio": None}
    assert hard_information_coverage({"hard_information": []}, [])["ratio"] is None


def test_card_binds_artifact_hash() -> None:
    card = build_scoring_card(
        aid="art-001",
        delivery_path="delivery/art-001/delivery.md",
        body=BODY,
        digest_fn=lambda rel: f"sha-of:{rel}",
    )
    assert card["artifact_sha256"] == "sha-of:delivery/art-001/delivery.md"
    assert card["reader_takeaway_locator"] == "p3"
