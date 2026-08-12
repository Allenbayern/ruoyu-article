"""P2 蒸馏脚本 — 一批结构卡 → 候选原则 JSON（证据，非写入授权）。

契约（设计 ④原则提炼 + P2 验收行）：
- 输入一批结构卡（>= 5 张），每张先经 case_contract.validate_case_card 校验；
  跨域（evidence_domain 非 competitive_research_evidence）、资格不匹配、字段缺失即拒绝
- 只聚合 qualified_viral 卡的技巧观察进正向候选；observed_pending / research_only 的
  同类观察只进 excluded_observations[]，不得计入 frequency
- supporting_qualified_samples[] 每项含 sample_id、snapshot_ref、performance_evidence_ref
- 输出候选 JSON：technique / technique_type / frequency / supporting_qualified_samples[] /
  performance_evidence_refs[] / excluded_observations[] / negative_cards[] / risk_note
- 样本表现数据只做可追溯比较：输出不含汇总绝对量（total/sum），不跨账号/平台相加
- 蒸馏输出是证据，不是自动写入 canonical 的授权
"""

from __future__ import annotations

from typing import Any

from article_group.case_contract import (
    _items,
    _mapping,
    _require,
    _text,
    QUALIFICATION_STATUSES,
    validate_case_card,
)

MIN_CARDS = 5

TECHNIQUE_TYPES = frozenset({"title", "opening", "structure", "interaction"})


def _validate_observations(card: dict[str, Any]) -> list[dict[str, Any]]:
    raw_observations = _items(
        card.get("technique_observations"),
        "technique_observations_must_be_a_list",
    )
    _require(
        bool(raw_observations),
        "technique_observations_must_not_be_empty",
    )
    observations: list[dict[str, Any]] = []
    for raw in raw_observations:
        obs = _mapping(raw, "technique_observation_must_be_an_object")
        _text(obs.get("technique"), "technique_missing")
        technique_type = _text(
            obs.get("technique_type"), "technique_type_missing"
        )
        _require(
            technique_type in TECHNIQUE_TYPES,
            f"invalid_technique_type:{technique_type}",
        )
        # 可选归并键：technique_id（跨卡同向技巧共用；为空视为未提供）
        technique_id = obs.get("technique_id")
        if technique_id is not None:
            technique_id = _text(technique_id, "technique_id_must_be_text")
            _require(
                bool(technique_id.strip()),
                "technique_id_must_not_be_blank",
            )
            obs["technique_id"] = technique_id.strip()
        observations.append(obs)
    return observations


def _observation_key(obs: dict[str, Any]) -> tuple[str, str, str]:
    """归并键：有 technique_id 用 ID，否则用 technique 精确名（向后兼容）。"""
    technique_id = obs.get("technique_id")
    if technique_id:
        return (technique_id, obs["technique_type"], "id")
    return (obs["technique"], obs["technique_type"], "name")


def distill_candidates(cards: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """一批结构卡 -> 候选原则 JSON 列表（每技巧一条，按 frequency 降序）。"""
    _require(isinstance(cards, dict), "cards_must_be_a_mapping")
    _require(
        len(cards) >= MIN_CARDS,
        f"distill_needs_at_least_{MIN_CARDS}_cards",
    )

    # 分组前先逐卡校验：跨域/资格不匹配/缺字段在此拒绝
    validated: dict[str, dict[str, Any]] = {}
    for sample_id, card in cards.items():
        _require(
            isinstance(card, dict),
            f"card_must_be_an_object:{sample_id}",
        )
        status = validate_case_card(card)
        observations = _validate_observations(card)
        validated[sample_id] = {
            **card,
            "_status": status,
            "_observations": observations,
        }

    # 技巧键 -> 候选聚合（frequency 只计 qualified_viral）
    candidates: dict[tuple[str, str, str], dict[str, Any]] = {}
    negative_cards: list[str] = []

    for sample_id, card in validated.items():
        status = card["_status"]
        if card.get("negative_patterns"):
            negative_cards.append(sample_id)
        for obs in card["_observations"]:
            technique = _text(obs.get("technique"), "technique_missing")
            technique_type = _text(obs.get("technique_type"), "technique_type_missing")
            key = _observation_key(obs)
            candidate = candidates.setdefault(
                key,
                {
                    "technique": technique,
                    "technique_type": technique_type,
                    "technique_id": obs.get("technique_id"),
                    "frequency": 0,
                    "supporting_qualified_samples": [],
                    "performance_evidence_refs": [],
                    "excluded_observations": [],
                    "negative_cards": [],
                    "risk_note": "",
                },
            )
            if status == "qualified_viral":
                candidate["frequency"] += 1
                candidate["supporting_qualified_samples"].append(
                    {
                        "sample_id": sample_id,
                        "snapshot_ref": _text(card.get("snapshot_ref"), "snapshot_ref_missing"),
                        "performance_evidence_ref": _text(
                            card.get("performance_evidence_ref"),
                            "performance_evidence_ref_missing",
                        ),
                    }
                )
                ref = card["performance_evidence_ref"]
                if ref not in candidate["performance_evidence_refs"]:
                    candidate["performance_evidence_refs"].append(ref)
            else:
                candidate["excluded_observations"].append(
                    {
                        "sample_id": sample_id,
                        "qualification_status": status,
                        "technique": technique,
                        "technique_type": technique_type,
                    }
                )

    ordered = sorted(
        candidates.values(),
        key=lambda c: (-c["frequency"], c["technique"], c["technique_type"]),
    )
    for candidate in ordered:
        candidate["negative_cards"] = [
            sid for sid in negative_cards if sid not in candidate["negative_cards"]
        ]
    return ordered
