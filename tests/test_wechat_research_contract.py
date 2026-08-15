from __future__ import annotations

from copy import deepcopy

import pytest

from article_group.case_contract import (
    CaseContractError,
    QUALIFICATION_STATUSES,
    assess_qualification,
    validate_case_card,
    validate_technique_candidate,
)


CLIENT_OBSERVED_AT = "2026-08-10T10:00:00+08:00"


def client_case(sample_id: str = "client-1", *, account_id: str = "account-client", subject: str = "电影") -> dict:
    return {
        "sample_id": sample_id,
        "evidence_domain": "competitive_research_evidence",
        "evidence_origin": "client",
        "account_id": account_id,
        "subject_category": subject,
        "snapshot_ref": f"sources/{sample_id}.clean.md#sha256={'a' * 64}",
        "performance_evidence_ref": f"metrics/{sample_id}.json",
        "metric_plan_version": "article-metric-v0",
        "metric_plan_frozen_at": "2026-08-10T09:00:00+08:00",
        "client_evidence": {
            "evidence_ref": "evidence/client-1.png",
            "original_display": "150000 reads",
            "observed_at": CLIENT_OBSERVED_AT,
            "confirmer": "reviewer-1",
            "sha256": "3" * 64,
            "sanitized": True,
        },
        "metric_plan": [
            {"metric": "read_count", "visible": True, "required": True},
            {"metric": "like_count", "visible": True, "required": True},
        ],
        "metrics": [
            {
                "metric": "read_count",
                "value": 150000,
                "status": "observed",
                "source": "platform_client",
                "observed_at": CLIENT_OBSERVED_AT,
                "evidence_ref": f"evidence/{sample_id}-read.png",
            },
            {
                "metric": "like_count",
                "value": 7000,
                "status": "observed",
                "source": "platform_client",
                "observed_at": CLIENT_OBSERVED_AT,
                "evidence_ref": f"evidence/{sample_id}-like.png",
            },
        ],
        "threshold_or_rank_rule": {
            "version": "article-rule-v0",
            "frozen_at": "2026-08-10T09:00:00+08:00",
            "platform": "weixin",
            "baseline": "film-account-2026q3",
            "window": "published_plus_7d",
            "rule": "read_count >= 100000 and like_count >= 5000",
            "minimums": {"read_count": 100000, "like_count": 5000},
        },
        "qualification_reason": "Client-origin observations meet the frozen article rule.",
    }


def vendor_case(
    sample_id: str = "vendor-1",
    *,
    account_id: str = "account-vendor-1",
    subject: str = "电影",
    second_at: str = "2026-08-12T10:01:00+08:00",
) -> dict:
    return {
        "sample_id": sample_id,
        "evidence_domain": "competitive_research_evidence",
        "evidence_origin": "vendor",
        "account_id": account_id,
        "subject_category": subject,
        "snapshot_ref": f"sources/{sample_id}.clean.md#sha256={'b' * 64}",
        "performance_evidence_ref": f"metrics/{sample_id}.json",
        "publication_time": "2026-08-10T08:00:00+08:00",
        "vendor_rule": {
            "version": "v0",
            "source": "newrank",
            "source_batch_rank_max": 5,
        },
        "vendor_observations": [
            {
                "observed_at": "2026-08-11T10:00:00+08:00",
                "source_batch_rank": 2,
                "metrics": {"readNum": 100001, "likeNum": 321},
                "raw_batch_ref": f"raw/{sample_id}-day1.json",
                "raw_batch_sha256": "1" * 64,
                "immutable": True,
            },
            {
                "observed_at": second_at,
                "source_batch_rank": 3,
                "metrics": {"readNum": 100001, "judgeIndex": 88},
                "raw_batch_ref": f"raw/{sample_id}-day2.json",
                "raw_batch_sha256": "2" * 64,
                "immutable": True,
            },
        ],
        "qualification_reason": "Two immutable vendor observations satisfy vendor rule v0.",
    }


def test_qualification_statuses_are_exactly_the_four_contract_states() -> None:
    assert QUALIFICATION_STATUSES == frozenset(
        {"qualified_viral", "vendor_qualified", "observed_pending", "research_only"}
    )


def test_client_origin_and_frozen_plan_rule_are_required_for_qualified_viral() -> None:
    card = client_case()
    assert assess_qualification(card) == "qualified_viral"

    card = client_case()
    card.pop("evidence_origin")
    card["metrics"][0]["source"] = "newrank_vendor"
    card["metrics"][1]["source"] = "newrank_vendor"
    with pytest.raises(CaseContractError, match="client_origin_evidence_required"):
        assess_qualification(card)

    card = client_case()
    card.pop("metric_plan_frozen_at")
    with pytest.raises(CaseContractError, match="client_metric_plan_not_prefrozen"):
        validate_case_card(card)

    card = client_case()
    card["threshold_or_rank_rule"]["frozen_at"] = "2026-08-10T11:00:00+08:00"
    with pytest.raises(CaseContractError, match="client_rule_not_prefrozen"):
        validate_case_card(card)


def test_client_metric_plan_must_freeze_before_client_observation() -> None:
    card = client_case()
    card["metric_plan_frozen_at"] = "2026-08-10T11:00:00+08:00"
    with pytest.raises(CaseContractError, match="client_metric_plan_not_prefrozen"):
        validate_case_card(card)


def test_client_rule_and_plan_must_precede_every_metric_observation() -> None:
    card = client_case()
    card["metrics"][1]["observed_at"] = "2026-08-10T08:00:00+08:00"
    with pytest.raises(CaseContractError, match="client_metric_plan_not_prefrozen"):
        validate_case_card(card)


def test_vendor_qualified_requires_two_immutable_batches_and_never_client_source() -> None:
    card = vendor_case()
    assert assess_qualification(card) == "vendor_qualified"
    assert validate_case_card(card) == "vendor_qualified"
    assert all(
        observation["metrics"]
        for observation in card["vendor_observations"]
    )
    assert all(
        "platform_client" not in str(observation)
        for observation in card["vendor_observations"]
    )


def test_vendor_with_only_one_observation_is_pending() -> None:
    card = vendor_case()
    card["vendor_observations"] = card["vendor_observations"][:1]
    assert assess_qualification(card) == "observed_pending"


def test_vendor_second_observation_after_seven_days_is_pending() -> None:
    card = vendor_case(second_at="2026-08-18T10:01:00+08:00")
    assert assess_qualification(card) == "observed_pending"


def test_vendor_observation_before_publication_is_rejected() -> None:
    card = vendor_case()
    card["vendor_observations"][0]["observed_at"] = "2026-08-09T10:00:00+08:00"
    with pytest.raises(CaseContractError, match="vendor_observation_before_publication"):
        validate_case_card(card)


def test_vendor_requires_read_and_like_or_judge() -> None:
    card = vendor_case()
    card["vendor_observations"][0]["metrics"] = {"readNum": 100001}
    card["vendor_observations"][1]["metrics"] = {"readNum": 100001}
    assert assess_qualification(card) == "observed_pending"


def test_vendor_requires_each_raw_batch_reference_and_digest() -> None:
    card = vendor_case()
    card["vendor_observations"][1].pop("raw_batch_sha256")
    with pytest.raises(CaseContractError, match="vendor_raw_batch_sha256_missing"):
        validate_case_card(card)


def test_vendor_rejects_reused_raw_batch_reference() -> None:
    card = vendor_case()
    card["vendor_observations"][1]["raw_batch_ref"] = card["vendor_observations"][0]["raw_batch_ref"]
    with pytest.raises(CaseContractError, match="vendor_raw_batch_ref_reused"):
        validate_case_card(card)


def test_vendor_observation_rank_cannot_exceed_declared_v0_ceiling() -> None:
    card = vendor_case()
    card["vendor_rule"]["source_batch_rank_max"] = 2
    card["vendor_observations"][1]["source_batch_rank"] = 3
    with pytest.raises(CaseContractError, match="vendor_source_batch_rank_exceeds_rule"):
        validate_case_card(card)


def test_vendor_metrics_must_be_numeric_and_vendor_labelled() -> None:
    card = vendor_case()
    card["vendor_observations"][0]["metrics"]["readNum"] = "100001"
    with pytest.raises(CaseContractError, match="vendor_read_num_invalid"):
        validate_case_card(card)

    card = vendor_case()
    card["vendor_observations"][0]["source"] = "platform_client"
    with pytest.raises(CaseContractError, match="vendor_client_value_mislabelled"):
        validate_case_card(card)


def test_vendor_record_requires_a_qualification_reason() -> None:
    card = vendor_case()
    card.pop("qualification_reason")
    with pytest.raises(CaseContractError, match="qualification_reason_missing"):
        validate_case_card(card)


def test_mixed_technique_requires_client_vendor_diversity_and_no_auto_publication() -> None:
    client = client_case(account_id="account-client", subject="电影")
    vendor_a = vendor_case("vendor-a", account_id="account-vendor-a", subject="剧集")
    vendor_b = vendor_case("vendor-b", account_id="account-vendor-b", subject="人物")
    cases = {"client": client, "vendor-a": vendor_a, "vendor-b": vendor_b}
    technique = {
        "technique_id": "T-MIX-01",
        "kind": "title",
        "name": "跨来源验证",
        "qualified_sample_refs": ["client", "vendor-a", "vendor-b"],
        "evidence_basis": "mixed_client_vendor",
        "verification_state": "verified",
        "automatic_publication_authority": False,
    }
    validate_technique_candidate(technique, cases)


def test_mixed_technique_rejects_missing_vendor_support() -> None:
    client = client_case()
    vendor = vendor_case("vendor-a", account_id="account-vendor-a", subject="剧集")
    technique = {
        "technique_id": "T-MIX-02",
        "kind": "opening",
        "name": "不足的混合证据",
        "qualified_sample_refs": ["client", "vendor-a"],
        "evidence_basis": "mixed_client_vendor",
        "verification_state": "verified",
        "automatic_publication_authority": False,
    }
    with pytest.raises(CaseContractError, match="mixed_requires_two_vendor_qualified"):
        validate_technique_candidate(technique, {"client": client, "vendor-a": vendor})


def test_mixed_technique_rejects_duplicate_account_or_subject_category() -> None:
    client = client_case(account_id="same", subject="电影")
    vendor_a = vendor_case("vendor-a", account_id="same", subject="剧集")
    vendor_b = vendor_case("vendor-b", account_id="another", subject="剧集")
    technique = {
        "technique_id": "T-MIX-03",
        "kind": "structure",
        "name": "重复来源",
        "qualified_sample_refs": ["client", "vendor-a", "vendor-b"],
        "evidence_basis": "mixed_client_vendor",
        "verification_state": "verified",
        "automatic_publication_authority": False,
    }
    with pytest.raises(CaseContractError, match="mixed_needs_three_distinct_accounts"):
        validate_technique_candidate(
            technique,
            {"client": client, "vendor-a": vendor_a, "vendor-b": vendor_b},
        )

    vendor_a["account_id"] = "account-vendor-a"
    with pytest.raises(CaseContractError, match="mixed_needs_three_distinct_subject_categories"):
        validate_technique_candidate(
            technique,
            {"client": client, "vendor-a": vendor_a, "vendor-b": vendor_b},
        )


def test_pending_and_research_only_cannot_support_technique() -> None:
    pending = vendor_case("pending")
    pending["vendor_observations"] = pending["vendor_observations"][:1]
    technique = {
        "technique_id": "T-PENDING",
        "kind": "title",
        "name": "待补采样本",
        "qualified_sample_refs": ["pending"],
    }
    with pytest.raises(CaseContractError, match="technique_support_not_qualified"):
        validate_technique_candidate(technique, {"pending": pending})


def test_client_only_technique_path_is_preserved() -> None:
    validate_technique_candidate(
        {
            "technique_id": "T-CLIENT",
            "kind": "title",
            "name": "客户端路径",
            "qualified_sample_refs": ["client"],
            "automatic_publication_authority": False,
        },
        {"client": client_case()},
    )


def test_client_only_technique_requires_explicit_no_publication_authority() -> None:
    base = {
        "technique_id": "T-CLIENT-AUTHORITY",
        "kind": "title",
        "name": "客户端发布边界",
        "qualified_sample_refs": ["client"],
    }
    for authority in (True, None):
        technique = deepcopy(base)
        if authority is not None:
            technique["automatic_publication_authority"] = authority
        with pytest.raises(CaseContractError, match="client_only_publication_authority_must_be_false"):
            validate_technique_candidate(technique, {"client": client_case()})

    allowed = deepcopy(base)
    allowed["automatic_publication_authority"] = False
    validate_technique_candidate(allowed, {"client": client_case()})


def test_mixed_technique_requires_verified_state_and_explicit_no_authority() -> None:
    cases = {
        "client": client_case(account_id="a1", subject="电影"),
        "vendor-a": vendor_case("vendor-a", account_id="a2", subject="剧集"),
        "vendor-b": vendor_case("vendor-b", account_id="a3", subject="人物"),
    }
    base = {
        "technique_id": "T-MIX-04",
        "kind": "interaction",
        "name": "状态边界",
        "qualified_sample_refs": list(cases),
        "evidence_basis": "mixed_client_vendor",
        "automatic_publication_authority": False,
    }
    with pytest.raises(CaseContractError, match="mixed_verification_state_must_be_verified"):
        validate_technique_candidate(base, cases)

    base["verification_state"] = "verified"
    base.pop("automatic_publication_authority")
    with pytest.raises(CaseContractError, match="mixed_publication_authority_missing"):
        validate_technique_candidate(base, cases)
