from __future__ import annotations

import pytest

from article_group.case_contract import (
    CaseContractError,
    assess_qualification,
    validate_case_card,
    validate_fact_evidence_pack,
    validate_feedback_record,
    validate_technique_candidate,
)


def qualified_case() -> dict:
    return {
        "sample_id": "wx-qualified-001",
        "evidence_domain": "competitive_research_evidence",
        "snapshot_ref": "runs/2026-08-12/viral-research/raw.html#sha256=abc",
        "performance_evidence_ref": "runs/2026-08-12/viral-research/metadata.json",
        "metric_plan": [
            {"metric": "read_count", "visible": True, "required": True},
            {"metric": "like_count", "visible": True, "required": True},
            {"metric": "comment_count", "visible": False, "required": False},
        ],
        "metrics": [
            {
                "metric": "read_count",
                "value": 150000,
                "status": "observed",
                "source": "platform_client",
                "observed_at": "2026-08-12T10:00:00+08:00",
                "evidence_ref": "screenshots/read.png",
            },
            {
                "metric": "like_count",
                "value": 7000,
                "status": "observed",
                "source": "platform_client",
                "observed_at": "2026-08-12T10:00:00+08:00",
                "evidence_ref": "screenshots/like.png",
            },
            {
                "metric": "comment_count",
                "value": None,
                "status": "not_verifiable_offsite",
                "source": "platform_policy",
                "observed_at": "2026-08-12T10:00:00+08:00",
                "evidence_ref": "runs/README.md#platform-limits",
            },
        ],
        "threshold_or_rank_rule": {
            "platform": "weixin",
            "baseline": "film-account-2026q3",
            "window": "published_plus_7d",
            "rule": "read_count >= 100000 and like_count >= 5000",
            "minimums": {"read_count": 100000, "like_count": 5000},
        },
        "qualification_reason": "Two required visible article-level metrics meet the declared rule.",
    }


def test_qualified_case_is_admitted() -> None:
    card = qualified_case()
    assert assess_qualification(card) == "qualified_viral"
    assert validate_case_card(card) == "qualified_viral"


def test_single_read_metric_is_observed_pending_not_qualified() -> None:
    card = qualified_case()
    card["metrics"] = [card["metrics"][0]]
    assert assess_qualification(card) == "observed_pending"


def test_below_declared_threshold_is_observed_pending_not_qualified() -> None:
    card = qualified_case()
    card["metrics"][1]["value"] = 4999
    assert assess_qualification(card) == "observed_pending"


def test_cross_domain_case_is_rejected() -> None:
    card = qualified_case()
    card["evidence_domain"] = "ruoyu_article_fact_evidence"
    with pytest.raises(CaseContractError, match="competitive_research_evidence"):
        validate_case_card(card)


def test_missing_evidence_reference_is_rejected() -> None:
    card = qualified_case()
    card["metrics"][0]["evidence_ref"] = ""
    with pytest.raises(CaseContractError, match="metric_evidence_ref_missing"):
        validate_case_card(card)


def test_technique_requires_qualified_supporting_sample() -> None:
    cases = {"wx-qualified-001": qualified_case()}
    technique = {
        "technique_id": "T-Q01",
        "kind": "title",
        "name": "数字落差",
        "qualified_sample_refs": ["wx-qualified-001"],
    }
    validate_technique_candidate(technique, cases)


def test_technique_rejects_pending_sample() -> None:
    pending = qualified_case()
    pending["metrics"] = [pending["metrics"][0]]
    technique = {
        "technique_id": "T-P01",
        "kind": "title",
        "name": "数字落差",
        "qualified_sample_refs": ["wx-qualified-001"],
    }
    with pytest.raises(CaseContractError, match="technique_support_not_qualified"):
        validate_technique_candidate(technique, {"wx-qualified-001": pending})


def test_feedback_cannot_change_competitive_qualification() -> None:
    card = qualified_case()
    feedback = {
        "evidence_domain": "production_feedback_evidence",
        "article_id": "ruoyu-001",
        "technique_ids": ["T-Q01"],
        "proposed_qualification_status": "research_only",
    }
    with pytest.raises(CaseContractError, match="feedback_cannot_change_qualification"):
        validate_case_card(card, feedback=feedback)


def test_fact_evidence_requires_independent_snapshot_and_claim_locator() -> None:
    fact_pack = {
        "evidence_domain": "ruoyu_article_fact_evidence",
        "article_id": "ruoyu-001",
        "claims": [
            {
                "claim_id": "C01",
                "source_snapshot_ref": "runs/2026-08-12/facts/source.html#sha256=def",
                "claim_locator": "#paragraph-4",
            }
        ],
    }
    validate_fact_evidence_pack(fact_pack)


def test_fact_evidence_rejects_competitive_reference() -> None:
    fact_pack = {
        "evidence_domain": "ruoyu_article_fact_evidence",
        "article_id": "ruoyu-001",
        "competitive_sample_refs": ["wx-qualified-001"],
        "claims": [
            {
                "claim_id": "C01",
                "source_snapshot_ref": "runs/2026-08-12/facts/source.html#sha256=def",
                "claim_locator": "#paragraph-4",
            }
        ],
    }
    with pytest.raises(CaseContractError, match="fact_evidence_cannot_reference_competitive_samples"):
        validate_fact_evidence_pack(fact_pack)


def test_feedback_requires_observations_and_cannot_carry_qualification() -> None:
    feedback = {
        "evidence_domain": "production_feedback_evidence",
        "article_id": "ruoyu-001",
        "technique_ids": ["T-Q01"],
        "observations": [
            {
                "metric": "read_count",
                "value": 5000,
                "source": "platform_client",
                "observed_at": "2026-08-12T10:00:00+08:00",
                "evidence_ref": "screenshots/ruoyu-read.png",
            }
        ],
    }
    validate_feedback_record(feedback)
    feedback["qualification_status"] = "qualified_viral"
    with pytest.raises(CaseContractError, match="feedback_cannot_change_qualification"):
        validate_feedback_record(feedback)


def test_fact_evidence_rejects_unknown_domain() -> None:
    fact_pack = {
        "evidence_domain": "unknown_domain",
        "article_id": "ruoyu-001",
        "claims": [
            {
                "claim_id": "C01",
                "source_snapshot_ref": "runs/2026-08-12/facts/source.html#sha256=def",
                "claim_locator": "#paragraph-4",
            }
        ],
    }
    with pytest.raises(CaseContractError, match="ruoyu_article_fact_evidence"):
        validate_fact_evidence_pack(fact_pack)


def test_fact_evidence_rejects_qualification_vocabulary() -> None:
    fact_pack = {
        "evidence_domain": "ruoyu_article_fact_evidence",
        "article_id": "ruoyu-001",
        "qualification_status": "qualified_viral",
        "claims": [
            {
                "claim_id": "C01",
                "source_snapshot_ref": "runs/2026-08-12/facts/source.html#sha256=def",
                "claim_locator": "#paragraph-4",
            }
        ],
    }
    with pytest.raises(
        CaseContractError, match="fact_evidence_cannot_carry_qualification"
    ):
        validate_fact_evidence_pack(fact_pack)


def test_feedback_rejects_claims_vocabulary() -> None:
    feedback = {
        "evidence_domain": "production_feedback_evidence",
        "article_id": "ruoyu-001",
        "technique_ids": ["T-Q01"],
        "claims": [{"claim_id": "C01", "source_snapshot_ref": "x", "claim_locator": "y"}],
        "observations": [
            {
                "metric": "read_count",
                "value": 5000,
                "source": "platform_client",
                "observed_at": "2026-08-12T10:00:00+08:00",
                "evidence_ref": "screenshots/ruoyu-read.png",
            }
        ],
    }
    with pytest.raises(CaseContractError, match="feedback_cannot_carry_claims"):
        validate_feedback_record(feedback)


def test_feedback_technique_ref_must_resolve_to_formal_technique() -> None:
    feedback = {
        "evidence_domain": "production_feedback_evidence",
        "article_id": "ruoyu-001",
        "technique_ids": ["T-MISSING"],
        "observations": [
            {
                "metric": "read_count",
                "value": 5000,
                "source": "platform_client",
                "observed_at": "2026-08-12T10:00:00+08:00",
                "evidence_ref": "screenshots/ruoyu-read.png",
            }
        ],
    }
    with pytest.raises(
        CaseContractError, match="feedback_technique_unresolvable:T-MISSING"
    ):
        validate_feedback_record(feedback, techniques={})


def test_feedback_technique_ref_must_be_formal() -> None:
    techniques = {
        "T-OBS": {
            "technique_id": "T-OBS",
            "kind": "title",
            "name": "观察条目",
            "qualified_sample_refs": [],
        }
    }
    feedback = {
        "evidence_domain": "production_feedback_evidence",
        "article_id": "ruoyu-001",
        "technique_ids": ["T-OBS"],
        "observations": [
            {
                "metric": "read_count",
                "value": 5000,
                "source": "platform_client",
                "observed_at": "2026-08-12T10:00:00+08:00",
                "evidence_ref": "screenshots/ruoyu-read.png",
            }
        ],
    }
    with pytest.raises(CaseContractError, match="feedback_technique_not_formal:T-OBS"):
        validate_feedback_record(feedback, techniques=techniques)


def test_feedback_resolves_existing_formal_technique() -> None:
    techniques = {
        "T-Q01": {
            "technique_id": "T-Q01",
            "kind": "title",
            "name": "数字落差",
            "qualified_sample_refs": ["wx-qualified-001"],
        }
    }
    feedback = {
        "evidence_domain": "production_feedback_evidence",
        "article_id": "ruoyu-001",
        "technique_ids": ["T-Q01"],
        "observations": [
            {
                "metric": "read_count",
                "value": 5000,
                "source": "platform_client",
                "observed_at": "2026-08-12T10:00:00+08:00",
                "evidence_ref": "screenshots/ruoyu-read.png",
            }
        ],
    }
    validate_feedback_record(feedback, techniques=techniques)
    validate_case_card(qualified_case(), feedback=feedback, techniques=techniques)
