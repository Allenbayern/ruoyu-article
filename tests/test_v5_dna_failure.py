from __future__ import annotations

from typing import Any

import pytest

from article_group.v5.dna import extract_article_dna, validate_article_dna
from article_group.v5.failure import (
    build_failure_artifact,
    classify_failure_sample,
    validate_failure_artifact,
)


RUN_ID = "run-dna-failure-001"
GENERATED_AT = "2026-09-09T10:00:00+08:00"


def test_dna_marks_derived_features_and_keeps_explicit_platform():
    dna = extract_article_dna(
        {
            "article_id": "a-001",
            "topic_type": "人物",
            "platform": "wechat",
            "title": "他为什么回头？",
            "opening_info_type": "具体场景",
        },
        draft_text="夜里十一点，演员走出片场。",
        run_id=RUN_ID,
        generated_at=GENERATED_AT,
    )

    assert dna["payload"]["features"]["topic_type"] == {
        "value": "人物",
        "source": "explicit",
    }
    assert dna["payload"]["features"]["platform"] == {
        "value": "wechat",
        "source": "explicit",
    }
    assert dna["payload"]["features"]["opening_info_type"] == {
        "value": "具体场景",
        "source": "explicit",
    }
    assert dna["payload"]["features"]["title_structure"]["source"] == (
        "derived"
    )
    assert dna["payload"]["evidence_role"] == "descriptive_signal_only"
    assert dna["payload"]["publication_authorization"] == "not_authorized"
    assert validate_article_dna(dna) == []


def test_dna_text_derivation_is_deterministic_and_never_claims_fact_proof():
    article = {
        "article_id": "a-002",
        "title": "3个关系冲突，为什么还要回头？",
        "platform": "toutiao",
    }
    draft = "第一段有一个具体场景。\n\n第二段写两个人的选择。"

    first = extract_article_dna(article, draft_text=draft)
    second = extract_article_dna(article, draft_text=draft)

    assert first["payload"]["features"] == second["payload"]["features"]
    assert first["payload"]["features"]["title_structure"]["value"] == (
        "question_numeric"
    )
    assert first["payload"]["features"]["character_count"]["value"] == len(
        draft
    )
    assert first["payload"]["features"]["paragraph_count"]["value"] == 2
    assert first["payload"]["evidence_role"] != "fact_proof"
    assert first["payload"].get("fact_proof") is not True


def test_dna_missing_features_are_explicitly_unavailable():
    dna = extract_article_dna({"article_id": "a-003"})

    features = dna["payload"]["features"]
    assert features["platform"] == {"value": None, "source": "unavailable"}
    assert features["topic_type"] == {"value": None, "source": "unavailable"}
    assert features["title_structure"] == {
        "value": None,
        "source": "unavailable",
    }
    assert all(
        isinstance(feature, dict)
        and set(feature) == {"value", "source"}
        and feature["source"] in {"explicit", "derived", "unavailable"}
        for feature in features.values()
    )
    assert validate_article_dna(dna) == []


def test_empty_metric_event_is_unavailable_and_dna_remains_valid():
    dna = extract_article_dna({"article_id": "a-003b"}, metric_event={})

    assert dna["payload"]["metric_event"] == {}
    assert dna["payload"]["metric_event_status"] == "unavailable"
    assert validate_article_dna(dna) == []


def test_dna_explicit_values_are_not_replaced_by_text_derivation():
    dna = extract_article_dna(
        {
            "article_id": "a-004",
            "topic_type": "作品",
            "platform": "custom-platform",
            "title": "标题里有数字3和问号？",
            "title_structure": "editor_declared",
        },
        draft_text="有一个场景和一段关系冲突。",
    )

    features = dna["payload"]["features"]
    assert features["topic_type"] == {"value": "作品", "source": "explicit"}
    assert features["platform"] == {
        "value": "custom-platform",
        "source": "explicit",
    }
    assert features["title_structure"] == {
        "value": "editor_declared",
        "source": "explicit",
    }


def test_dna_validator_rejects_invalid_feature_source_and_authorization():
    dna = extract_article_dna({"article_id": "a-005"})
    invalid = {
        **dna,
        "payload": {
            **dna["payload"],
            "features": {
                **dna["payload"]["features"],
                "platform": {"value": "wechat", "source": "inferred"},
            },
            "publication_authorization": "authorized",
        },
    }

    errors = validate_article_dna(invalid)

    assert "invalid:feature:platform" in errors
    assert "publication_authorization_must_be_not_authorized" in errors


def test_missing_metrics_are_not_classified_as_zero_failure():
    result = classify_failure_sample(
        {
            "article_id": "a-006",
            "impressions": None,
            "impressions_status": "unavailable",
        }
    )

    assert result["categories"] == ["insufficient_data"]
    assert result["metrics"]["impressions"] is None
    assert result["metric_status"]["impressions"] == "unavailable"
    assert result["metrics"]["impressions"] != 0


def test_failure_classifier_separates_exposure_without_click_and_low_completion():
    result = classify_failure_sample(
        {
            "article_id": "a-007",
            "impressions": 5000,
            "ctr": 0.01,
            "reads": 300,
            "completion_rate": 0.2,
        }
    )

    assert result["categories"] == [
        "exposure_without_click",
        "click_low_completion",
    ]
    assert set(result["evidence"]) == set(result["categories"])
    assert set(result["recommendations"]) == set(result["categories"])
    for category in result["categories"]:
        evidence = result["evidence"][category]
        assert evidence["metrics"]
        assert evidence["thresholds"]
        assert result["recommendations"][category]
    assert result["publication_authorization"] == "not_authorized"
    assert result["auto_apply"] is False


@pytest.mark.parametrize(
    ("event", "category"),
    [
        (
            {
                "article_id": "a-008",
                "impressions": 500,
                "reads": 400,
                "ctr": 0.08,
                "completion_rate": 0.8,
            },
            "high_completion_low_exposure",
        ),
        (
            {
                "article_id": "a-009",
                "impressions": 5000,
                "reads": 1000,
                "interactions": 500,
                "revenue": 0.2,
            },
            "high_interaction_low_revenue",
        ),
        (
            {
                "article_id": "a-010",
                "impressions": 5000,
                "reads": 1000,
                "ctr": 0.08,
                "completion_rate": 0.8,
                "risk_score": 0.9,
            },
            "good_data_high_risk",
        ),
    ],
)
def test_failure_classifier_reports_each_remaining_category_with_evidence(
    event: dict[str, Any], category: str
):
    result = classify_failure_sample(event)

    assert result["categories"] == [category]
    assert result["evidence"][category]["metrics"]
    assert result["evidence"][category]["thresholds"]
    assert result["recommendations"][category]


def test_good_data_high_risk_with_level_has_non_null_risk_evidence():
    result = classify_failure_sample(
        {
            "article_id": "a-010b",
            "impressions": 5000,
            "reads": 1000,
            "completion_rate": 0.8,
            "risk_level": "high",
        }
    )

    assert result["categories"] == ["good_data_high_risk"]
    detail = result["evidence"]["good_data_high_risk"]
    assert detail["metrics"]["risk_level"] == "high"
    assert all(value is not None for value in detail["metrics"].values())


def test_complete_non_failure_sample_has_no_categories_and_validates():
    artifact = build_failure_artifact(
        [
            {
                "article_id": "a-010c",
                "impressions": 5000,
                "ctr": 0.05,
                "reads": 500,
                "completion_rate": 0.8,
                "interactions": 10,
                "revenue": 10.0,
                "risk_score": 0.2,
            }
        ],
        run_id=RUN_ID,
        generated_at=GENERATED_AT,
    )

    sample = artifact["payload"]["samples"][0]
    assert sample["categories"] == []
    assert sample["status"] == "no_failure"
    assert validate_failure_artifact(artifact) == []


def test_threshold_override_changes_category_and_is_recorded_in_evidence():
    event = {
        "article_id": "a-011",
        "impressions": 5000,
        "ctr": 0.015,
    }

    default_result = classify_failure_sample(event)
    stricter_result = classify_failure_sample(
        event,
        thresholds={"exposure_without_click_max_ctr": 0.01},
    )

    assert "exposure_without_click" in default_result["categories"]
    assert stricter_result["categories"] == ["insufficient_data"]
    assert stricter_result["thresholds"]["exposure_without_click_max_ctr"] == 0.01


def test_missing_category_metric_returns_only_insufficient_data():
    result = classify_failure_sample(
        {
            "article_id": "a-012",
            "impressions": 5000,
            "ctr": None,
            "ctr_status": "unavailable",
            "reads": 300,
            "completion_rate": None,
            "completion_rate_status": "unavailable",
        }
    )

    assert result["categories"] == ["insufficient_data"]
    assert result["evidence"] == {}
    assert result["recommendations"] == {}


def test_failure_artifact_builds_and_validates_classified_samples():
    artifact = build_failure_artifact(
        [
            {
                "article_id": "a-013",
                "impressions": 5000,
                "ctr": 0.01,
                "reads": 300,
                "completion_rate": 0.2,
            },
            {
                "article_id": "a-014",
                "impressions": None,
                "impressions_status": "unavailable",
            },
        ],
        run_id=RUN_ID,
        generated_at=GENERATED_AT,
    )

    assert artifact["payload"]["sample_count"] == 2
    assert len(artifact["payload"]["samples"]) == 2
    assert artifact["payload"]["publication_authorization"] == "not_authorized"
    assert artifact["payload"]["auto_apply"] is False
    assert validate_failure_artifact(artifact) == []


def test_failure_validator_rejects_malformed_sample_and_authorization():
    artifact = build_failure_artifact(
        [{"article_id": "a-015", "impressions": None}],
        run_id=RUN_ID,
        generated_at=GENERATED_AT,
    )
    invalid = {
        **artifact,
        "payload": {
            **artifact["payload"],
            "publication_authorization": "authorized",
            "samples": [{"article_id": "a-015", "categories": ["made_up"]}],
        },
    }

    errors = validate_failure_artifact(invalid)

    assert "invalid:sample:0:categories" in errors
    assert "publication_authorization_must_be_not_authorized" in errors
