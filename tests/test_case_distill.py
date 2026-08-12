"""P2 蒸馏脚本（case_distill）RED 测试 — 契约锁定。

验收要点（设计 ④蒸馏 + P2 行）：
- 输入一批结构卡（≥5 张）；每张先经 case_contract 校验，跨域/资格不匹配即拒绝
- 正向候选只聚合 qualified_viral 卡的技巧观察；observed_pending / research_only 的同类观察
  只进 excluded_observations[]，不得计入频次
- supporting_qualified_samples[] 每项含 sample_id、快照引用、表现档案引用
- 输出候选 JSON：technique / technique_type / frequency / supporting_qualified_samples[] /
  performance_evidence_refs[] / excluded_observations[] / negative_cards[] / risk_note
- 不把不同账号/平台/发布时间的绝对量机械相加（输出无 totals/sum 字段）
"""

from __future__ import annotations

import pytest

from article_group.case_contract import CaseContractError, RESEARCH_DOMAIN
from article_group.case_distill import distill_candidates


def _card(
    sample_id: str,
    *,
    status: str,
    observations: list[dict[str, object]] | None = None,
    view: int = 200_000,
    negative_patterns: list[str] | None = None,
    evidence_domain: str = RESEARCH_DOMAIN,
    snapshot_ref: str | None = None,
) -> dict[str, object]:
    """构造一张可通过 case_contract 校验的结构卡。

    qualified_viral:  view >= 100_000 且 observed
    observed_pending: view < 阈值（observed 但未达标）
    research_only:    必填可见指标无 observed 值
    """
    if status == "research_only":
        metrics: list[dict[str, object]] = []
    elif status == "observed_pending":
        metrics = [
            {
                "metric": "view",
                "value": min(view, 50_000),  # observed 但未达阈值
                "status": "observed",
                "source": "official_api",
                "observed_at": "2026-08-11T12:30:10+08:00",
                "evidence_ref": f"metrics/{sample_id}.api.json",
            }
        ]
    else:
        metrics = [
            {
                "metric": "view",
                "value": max(view, 100_000),
                "status": "observed",
                "source": "official_api",
                "observed_at": "2026-08-11T12:30:10+08:00",
                "evidence_ref": f"metrics/{sample_id}.api.json",
            }
        ]
    card: dict[str, object] = {
        "sample_id": sample_id,
        "evidence_domain": evidence_domain,
        "snapshot_ref": snapshot_ref or f"sources/{sample_id}.clean.md#sha256=abc",
        "performance_evidence_ref": f"metrics/{sample_id}.api.json",
        "metric_plan": [
            {"metric": "view", "visible": True, "required": True}
        ],
        "metrics": metrics,
        "threshold_or_rank_rule": {
            "platform": "bilibili",
            "baseline": "column",
            "window": "2026-08-11",
            "rule": "gte",
            "minimums": {"view": 100_000},
        },
        "qualification_reason": "view >= 100000 observed",
        "qualification_status": status,
    }
    if observations is not None:
        card["technique_observations"] = observations
    if negative_patterns is not None:
        card["negative_patterns"] = negative_patterns
    return card


def _obs(technique: str, technique_type: str, **extra: object) -> dict[str, object]:
    item: dict[str, object] = {"technique": technique, "technique_type": technique_type}
    item.update(extra)
    return item


def six_qualified() -> dict[str, dict[str, object]]:
    return {
        f"s{i}": _card(
            f"s{i}",
            status="qualified_viral",
            observations=[_obs("栏目化标题+提问式站队", "title")],
        )
        for i in range(1, 7)
    }


def test_distill_groups_by_technique_and_type() -> None:
    cards = six_qualified()
    cards["s1"]["technique_observations"] = [  # type: ignore[assignment]
        _obs("栏目化标题+提问式站队", "title"),
        _obs("剧透预警当钩子", "opening"),
    ]
    cards["s2"]["technique_observations"] = [  # type: ignore[assignment]
        _obs("栏目化标题+提问式站队", "title"),
    ]
    candidates = distill_candidates(cards)
    by_name = {c["technique"]: c for c in candidates}
    assert set(by_name) == {"栏目化标题+提问式站队", "剧透预警当钩子"}
    assert by_name["栏目化标题+提问式站队"]["frequency"] == 6
    assert by_name["栏目化标题+提问式站队"]["technique_type"] == "title"
    assert by_name["剧透预警当钩子"]["frequency"] == 1


def test_distill_supporting_samples_carry_refs() -> None:
    candidates = distill_candidates(six_qualified())
    (candidate,) = candidates
    for supporting in candidate["supporting_qualified_samples"]:
        assert supporting["sample_id"]
        assert supporting["snapshot_ref"].startswith("sources/")
        assert supporting["performance_evidence_ref"].startswith("metrics/")
    assert len(candidate["performance_evidence_refs"]) == 6


def test_distill_observed_pending_excluded_from_frequency() -> None:
    cards = six_qualified()
    cards["s7"] = _card(
        "s7",
        status="observed_pending",
        observations=[_obs("栏目化标题+提问式站队", "title")],
    )
    candidates = distill_candidates(cards)
    (candidate,) = candidates
    assert candidate["frequency"] == 6  # 观察样本不计入
    excluded = candidate["excluded_observations"]
    assert any(
        e["sample_id"] == "s7" and e["qualification_status"] == "observed_pending"
        for e in excluded
    )


def test_distill_research_only_excluded_from_frequency() -> None:
    cards = six_qualified()
    cards["s8"] = _card(
        "s8",
        status="research_only",
        observations=[_obs("栏目化标题+提问式站队", "title")],
    )
    candidates = distill_candidates(cards)
    (candidate,) = candidates
    assert candidate["frequency"] == 6
    assert any(
        e["sample_id"] == "s8" and e["qualification_status"] == "research_only"
        for e in candidate["excluded_observations"]
    )


def test_distill_rejects_cross_domain_card() -> None:
    cards = six_qualified()
    cards["x1"] = _card(
        "x1",
        status="qualified_viral",
        evidence_domain="ruoyu_article_fact_evidence",
    )
    with pytest.raises(CaseContractError):
        distill_candidates(cards)


def test_distill_rejects_fewer_than_five_cards() -> None:
    cards = {f"s{i}": _card(f"s{i}", status="qualified_viral") for i in range(1, 5)}
    with pytest.raises(CaseContractError) as exc:
        distill_candidates(cards)
    assert "at_least_5" in str(exc.value)


def test_distill_rejects_missing_technique_observations() -> None:
    cards = six_qualified()
    del cards["s1"]["technique_observations"]  # type: ignore[misc]
    with pytest.raises(CaseContractError) as exc:
        distill_candidates(cards)
    assert "technique_observations" in str(exc.value)


def test_distill_rejects_unknown_technique_type() -> None:
    cards = six_qualified()
    cards["s1"]["technique_observations"] = [  # type: ignore[assignment]
        _obs("标题承诺", "bogus_type"),
    ]
    with pytest.raises(CaseContractError) as exc:
        distill_candidates(cards)
    assert "invalid_technique_type" in str(exc.value)


def test_distill_aggregates_negative_cards() -> None:
    cards = six_qualified()
    cards["s2"]["negative_patterns"] = ["关注+免责声明模板"]  # type: ignore[assignment]
    candidates = distill_candidates(cards)
    (candidate,) = candidates
    assert "s2" in candidate["negative_cards"]


def test_distill_no_absolute_metric_summation() -> None:
    cards = six_qualified()
    cards["s1"]["technique_observations"] = [  # type: ignore[assignment]
        _obs("栏目化标题+提问式站队", "title"),
        _obs("剧透预警当钩子", "opening"),
    ]
    candidates = distill_candidates(cards)
    for candidate in candidates:
        output = repr(candidate).lower()
        # 输出是证据：可追溯 refs 而非汇总绝对量
        assert "total" not in output
        assert "sum(" not in output
        assert candidate["risk_note"] == ""


def test_distill_groups_by_technique_id_across_wording() -> None:
    """真实蒸馏缺口回归：同向技巧带同一 technique_id 时按 ID 归并。

    6 张卡中 cv3922553/cv2080294/cv4769321 都拆出了「数据开场」类观察，
    但措辞不同（数据开场定调/票房数字/规模数字铺陈）。若各带 technique_id=B01，
    应聚为 1 条候选、frequency=3，而非 3 条 freq=1。
    """
    cards = six_qualified()
    cards["s1"]["technique_observations"] = [  # type: ignore[assignment]
        {"technique": "数据开场定调（票房/排名数字）", "technique_type": "opening", "technique_id": "B01"},
    ]
    cards["s2"]["technique_observations"] = [  # type: ignore[assignment]
        {"technique": "规模数字铺陈开场", "technique_type": "opening", "technique_id": "B01"},
    ]
    cards["s3"]["technique_observations"] = [  # type: ignore[assignment]
        {"technique": "方法论透明开场", "technique_type": "opening", "technique_id": "B01"},
    ]
    for sid in ("s4", "s5", "s6"):
        cards[sid]["technique_observations"] = [  # type: ignore[assignment]
            {"technique": "结尾直接提问收束", "technique_type": "interaction", "technique_id": "B02"},
        ]

    candidates = distill_candidates(cards)
    assert len(candidates) == 2
    by_type = {c["technique_type"]: c for c in candidates}
    opening = by_type["opening"]
    assert opening["frequency"] == 3
    assert opening["technique_id"] == "B01"
    assert [s["sample_id"] for s in opening["supporting_qualified_samples"]] == [
        "s1", "s2", "s3",
    ]
    assert len(opening["performance_evidence_refs"]) == 3
    interaction = by_type["interaction"]
    assert interaction["frequency"] == 3
    assert [s["sample_id"] for s in interaction["supporting_qualified_samples"]] == [
        "s4", "s5", "s6",
    ]


def test_distill_technique_id_without_id_keeps_name_key() -> None:
    """无 technique_id 的观察仍按 (technique, type) 精确聚合（向后兼容）。"""
    cards = six_qualified()
    cards["s1"]["technique_observations"] = [  # type: ignore[assignment]
        {"technique": "A 技巧", "technique_type": "title"},
    ]
    cards["s2"]["technique_observations"] = [  # type: ignore[assignment]
        {"technique": "A 技巧", "technique_type": "title"},
    ]
    cards["s3"]["technique_observations"] = [  # type: ignore[assignment]
        {"technique": "A 技巧（变体措辞）", "technique_type": "title"},
    ]
    candidates = distill_candidates(cards)
    # s1-s2 A 技巧×2、s3 变体×1、s4-s6 默认栏目化×3 → 共 3 个候选
    assert len(candidates) == 3
    freqs = {c["frequency"] for c in candidates}
    assert freqs == {1, 2, 3}


def test_distill_rejects_blank_technique_id() -> None:
    cards = six_qualified()
    cards["s1"]["technique_observations"] = [  # type: ignore[assignment]
        {"technique": "某技巧", "technique_type": "title", "technique_id": "  "},
    ]
    with pytest.raises(CaseContractError):
        distill_candidates(cards)
