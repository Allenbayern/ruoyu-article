"""client_evidence 占位符哈希检测：让"语义为空的凭证"可见（warning 级，不阻断）。

背景（2026-09-17 实测确认）：
爆款库 11 张 ``qualified_viral`` 卡的 ``client_evidence.sha256`` 全部是 64 个 0。
``case_contract._validate_client_origin`` 只校验 ``[0-9a-fA-F]{64}`` 格式，全零照样
通过——契约要求 ``client_confirmed`` 回链到截图/录屏并给出 SHA-256，全零不是哈希，
是占位符，凭证因此语义为空。

硬约束：检测只做 **warning**，不做 error。收紧成硬失败会把项目现有唯一一批合格
语料清零，所以本轮"让缺陷可见"，不"让卡失效"。

注意区分：正文快照的哈希是**真实存在**的，在卡的 ``snapshot_ref``
（``…md#sha256=<64hex>``）与 ``metrics/*.client.json`` 的 ``snapshot_sha256`` 里；
``client_evidence.sha256`` 指的是**另一个东西**（客户端证据即截图/录屏的哈希）。
本模块的任何断言都不允许把快照哈希填进 ``client_evidence.sha256``。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from article_group.case_contract import (
    PLACEHOLDER_WARNING_CODE,
    WARNING_SEVERITY,
    CaseContractError,
    assess_qualification,
    case_card_warnings,
    client_evidence_sha256_is_placeholder,
    placeholder_sha256_kind,
    validate_case_card,
)
from article_group.case_distill import distill_candidates

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_CARDS_DIR = (
    REPO_ROOT / "runs" / "2026-08-11" / "viral-research" / "wechat-viral" / "cards"
)

ALL_ZERO = "0" * 64
# 一个真实形状的哈希（逐位有变化），用于"不误报"断言。
REAL_LOOKING = "c1e74936a5ff555c613140608930080641d622280b0c3919234ff7879e6973bf"
CLIENT_OBSERVED_AT = "2026-08-10T10:00:00+08:00"


def client_card(sha256: str) -> dict:
    """构造一张能通过校验、状态为 qualified_viral 的 client-origin 卡。"""
    return {
        "sample_id": "wx-placeholder-fixture",
        "evidence_domain": "competitive_research_evidence",
        "evidence_origin": "client",
        "account_id": "account-client",
        "subject_category": "电影",
        "snapshot_ref": f"raw_articles/example.md#sha256={REAL_LOOKING}",
        "performance_evidence_ref": "wechat-viral/metrics/wx-placeholder-fixture.client.json",
        "metric_plan_version": "article-metric-v0",
        "metric_plan_frozen_at": "2026-08-10T09:00:00+08:00",
        "client_evidence": {
            "evidence_ref": "wechat-viral/metrics/wx-placeholder-fixture.client.json",
            "original_display": "10万+（≥100,000）",
            "observed_at": CLIENT_OBSERVED_AT,
            "confirmer": "Allen",
            "sha256": sha256,
            "sanitized": True,
        },
        "metric_plan": [{"metric": "view", "visible": True, "required": True}],
        "metrics": [
            {
                "metric": "view",
                "value": 100000,
                "status": "observed",
                "source": "wechat_client",
                "observed_at": CLIENT_OBSERVED_AT,
                "evidence_ref": "wechat-viral/metrics/wx-placeholder-fixture.client.json",
            }
        ],
        "threshold_or_rank_rule": {
            "platform": "wechat",
            "baseline": "wechat_gongzhonghao",
            "window": "published_2026",
            "rule": "gte",
            "minimums": {"view": 100000},
            "version": "article-rule-v0",
            "frozen_at": "2026-08-10T09:00:00+08:00",
        },
        "qualification_reason": "Allen 微信客户端确认阅读量 ≥10万+（测试夹具）",
        "qualification_status": "qualified_viral",
    }


# --------------------------------------------------------------- (a) 占位符检测


def test_all_zero_sha256_is_detected_as_placeholder() -> None:
    card = client_card(ALL_ZERO)
    assert placeholder_sha256_kind(ALL_ZERO) == "repeated_hex_char:0"
    assert client_evidence_sha256_is_placeholder(card) is True


@pytest.mark.parametrize("char", list("0123456789abcdefABCDEF"))
def test_any_single_repeated_hex_char_is_a_placeholder(char: str) -> None:
    """全零/全 f"之类"：单一十六进制字符重复 64 次，信息熵为零。"""
    assert client_evidence_sha256_is_placeholder(client_card(char * 64)) is True


def test_sequential_hex_cycle_is_a_placeholder() -> None:
    assert (
        placeholder_sha256_kind("0123456789abcdef" * 4) == "sequential_hex_cycle"
    )
    assert placeholder_sha256_kind(("0123456789abcdef" * 4).upper()) == "sequential_hex_cycle"


# ------------------------------------------------------------- (b) 不误报断言


def test_varied_real_hash_is_not_reported_as_placeholder() -> None:
    card = client_card(REAL_LOOKING)
    assert client_evidence_sha256_is_placeholder(card) is False
    assert case_card_warnings(card) == []


def test_snapshot_hashes_in_fixture_do_not_trip_the_detector() -> None:
    """快照哈希（snapshot_ref 里那个真实哈希）与 client_evidence.sha256 是两回事。"""
    card = client_card(REAL_LOOKING)
    assert REAL_LOOKING in card["snapshot_ref"]
    assert case_card_warnings(card) == []


def test_missing_or_malformed_sha256_is_out_of_scope_for_the_detector() -> None:
    """缺失/格式非法由 _sha256 的 error 级校验负责，不由占位符检测负责。"""
    assert placeholder_sha256_kind(None) is None
    assert placeholder_sha256_kind("") is None
    assert placeholder_sha256_kind("z" * 64) is None
    assert placeholder_sha256_kind("0" * 63) is None  # 长度不足
    assert placeholder_sha256_kind("0" * 65) is None
    assert client_evidence_sha256_is_placeholder({}) is False
    assert client_evidence_sha256_is_placeholder({"client_evidence": "not-an-object"}) is False


# ------------------------------------------- (a) warning 产出 + 不阻断（关键）


def test_placeholder_produces_warning_but_card_still_qualifies() -> None:
    card = client_card(ALL_ZERO)
    warnings: list[dict] = []

    status = validate_case_card(card, warnings=warnings)

    # 不阻断：状态不受影响
    assert status == "qualified_viral"
    assert assess_qualification(card) == "qualified_viral"
    # 可见：warning 已上报
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning["code"] == PLACEHOLDER_WARNING_CODE
    assert warning["severity"] == WARNING_SEVERITY == "warning"
    assert warning["field"] == "client_evidence.sha256"
    assert warning["kind"] == "repeated_hex_char:0"
    assert warning["remediation"] == "re_attest_client_evidence"


def test_warning_is_opt_in_and_return_value_is_unchanged() -> None:
    """既有调用方不传收集器时，返回值与行为完全不变（向后兼容）。"""
    placeholder_card = client_card(ALL_ZERO)
    clean_card = client_card(REAL_LOOKING)

    assert validate_case_card(placeholder_card) == "qualified_viral"
    assert validate_case_card(clean_card) == "qualified_viral"
    assert case_card_warnings(placeholder_card)[0]["severity"] == "warning"


def test_clean_card_yields_no_warnings() -> None:
    warnings: list[dict] = []
    assert validate_case_card(client_card(REAL_LOOKING), warnings=warnings) == "qualified_viral"
    assert warnings == []


def test_assess_qualification_return_type_and_semantics_are_unchanged() -> None:
    """硬约束：assess_qualification 仍返回 str 状态，占位符不改变判定。"""
    result = assess_qualification(client_card(ALL_ZERO))
    assert isinstance(result, str)
    assert result == "qualified_viral"


def test_vendor_card_without_client_evidence_yields_no_warning() -> None:
    vendor = {
        "evidence_domain": "competitive_research_evidence",
        "evidence_origin": "vendor",
    }
    assert client_evidence_sha256_is_placeholder(vendor) is False
    assert case_card_warnings(vendor) == []


# ------------------------------------------- 生产入口：蒸馏管线真实上报 warning


def test_distill_reports_placeholder_warning_with_sample_id() -> None:
    """case_distill.distill_candidates 是这 11 张卡的真实生产消费入口。"""
    cards = {
        f"wx-card-{index}": client_card(ALL_ZERO) for index in range(5)
    }
    for sample_id, card in cards.items():
        card["sample_id"] = sample_id
        card["technique_observations"] = [
            {"technique_id": "WX-O2", "technique": "热点开场", "technique_type": "opening"}
        ]

    warnings: list[dict] = []
    candidates = distill_candidates(cards, warnings=warnings)

    assert candidates  # 蒸馏照常产出，不被 warning 阻断
    assert len(warnings) == 5
    assert {item["sample_id"] for item in warnings} == set(cards)
    assert {item["code"] for item in warnings} == {PLACEHOLDER_WARNING_CODE}


def test_distill_without_warning_collector_still_enforces_existing_contract() -> None:
    """签名扩展没有放宽任何既有校验：<5 张仍然按原契约拒绝。"""
    cards = {"wx-card-0": client_card(REAL_LOOKING)}
    cards["wx-card-0"]["technique_observations"] = [
        {"technique_id": "WX-O2", "technique": "热点开场", "technique_type": "opening"}
    ]
    with pytest.raises(CaseContractError, match="distill_needs_at_least_5_cards"):
        distill_candidates(cards)


# ------------------------------------------------------- (c) 11 张真实卡回归


requires_real_cards = pytest.mark.skipif(
    not REAL_CARDS_DIR.is_dir(),
    reason="runs/ 是本地审计目录（gitignore），爆款库语料不在当前工作树时不跑集成断言",
)


def real_cards() -> list[tuple[Path, dict]]:
    paths = sorted(
        path for path in REAL_CARDS_DIR.glob("*.json") if not path.name.startswith("_")
    )
    return [(path, json.loads(path.read_text(encoding="utf-8"))) for path in paths]


@requires_real_cards
def test_real_cards_are_still_all_qualified_viral() -> None:
    """(c) 现有 11 张卡必须仍然全部通过校验，状态仍是 qualified_viral。"""
    cards = real_cards()
    assert len(cards) == 11, f"爆款库卡数变了：{len(cards)}"

    for path, card in cards:
        warnings: list[dict] = []
        status = validate_case_card(card, warnings=warnings)
        assert status == "qualified_viral", f"{path.name}: {status}"
        assert card["qualification_status"] == "qualified_viral", path.name
        # (a) 在真实数据上同样成立：占位符被看见，但卡不作废
        assert len(warnings) == 1, f"{path.name}: {warnings}"
        assert warnings[0]["code"] == PLACEHOLDER_WARNING_CODE, path.name


@requires_real_cards
def test_real_cards_carry_the_pending_re_attestation_marking() -> None:
    """标注落在卡本身（手法 A）：逐卡一一对应，且不改动 sha256 原值。"""
    cards = real_cards()
    for path, card in cards:
        evidence = card["client_evidence"]
        assert evidence["sha256_status"] == "placeholder_pending_re_attestation", path.name
        assert evidence["sha256"] == ALL_ZERO, (
            f"{path.name}: 原始占位值应被保留以便追溯，而不是被替换掉"
        )
        # 快照哈希与 client_evidence.sha256 必须是不同的东西，不能互相顶替
        assert "#sha256=" in card["snapshot_ref"]
        assert card["snapshot_ref"].split("#sha256=", 1)[1].rstrip("`") != evidence["sha256"], (
            f"{path.name}: client_evidence.sha256 被错误地填成了快照哈希"
        )


@requires_real_cards
def test_real_cards_are_not_silently_promoted_or_demoted() -> None:
    """回归护栏：本轮修复不得改变任何一张卡的资格状态或证据指纹。"""
    cards = real_cards()
    assert sum(
        card["qualification_status"] == "qualified_viral" for _path, card in cards
    ) == 11
    for path, card in cards:
        assert card["evidence_origin"] == "client", path.name
        assert card["client_evidence"]["sanitized"] is True, path.name
