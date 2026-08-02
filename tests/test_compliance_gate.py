"""Acceptance tests for the social-topic three-state compliance core."""

from __future__ import annotations

from article_group.compliance_gate import (
    GATE_KEYS,
    SOCIAL_TOPIC_TYPE,
    scan_social_redlines,
    validate_five_gates,
    validate_pool_five_gates,
)


def five_gates(*, overall: str | None = None, result: str | None = None, gate1: str = "PASS") -> dict[str, str]:
    gates = {
        "gate1_news_license": gate1,
        "gate2_privacy": "PASS",
        "gate3_judicial": "PASS",
        "gate4_copyright": "PASS",
        "gate5_sensationalism": "PASS",
    }
    if overall is not None:
        gates["overall"] = overall
    if result is not None:
        gates["result"] = result
    return gates


def social_candidate(candidate_id: str, *, recommendation: object = "A", gates: dict[str, str] | None = None, **extra: object) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "topic_type": SOCIAL_TOPIC_TYPE,
        "recommendation": recommendation,
        "five_gates": gates or five_gates(overall="PASS"),
        **extra,
    }


def test_public_api_symbols_remain_available():
    assert SOCIAL_TOPIC_TYPE == "social"
    assert len(GATE_KEYS) == 5
    assert callable(validate_five_gates)
    assert callable(validate_pool_five_gates)
    assert callable(scan_social_redlines)


def test_social_candidate_rejects_missing_unknown_and_inconsistent_grades():
    missing_gate = social_candidate("missing", gates={"overall": "PASS"})
    unknown_gate = social_candidate("unknown", gates=five_gates(overall="MAYBE"))
    inconsistent = social_candidate("inconsistent", gates=five_gates(overall="PASS", gate1="FAIL"))

    assert "candidate_missing_invalid_gate_gate1_news_license" in validate_five_gates(missing_gate)
    assert "candidate_unknown_invalid_overall_MAYBE" in validate_five_gates(unknown_gate)
    assert "candidate_inconsistent_overall_inconsistent_declared_PASS_expected_FAIL" in validate_five_gates(inconsistent)


def test_fail_candidate_cannot_recommend_editorial_slots():
    candidate = social_candidate("failed", recommendation="B", gates=five_gates(overall="FAIL", gate1="FAIL"))

    assert validate_five_gates(candidate) == ["candidate_failed_failed_gate_cannot_recommend_B"]


def test_archived_fail_candidate_is_retained_without_poisoning_pool():
    eligible_pass = social_candidate("eligible")

    for recommendation in ("Archive", "Reject", "Wait"):
        retained_fail = social_candidate(
            "retained",
            recommendation=recommendation,
            gates=five_gates(overall="FAIL", gate1="FAIL"),
        )

        assert validate_five_gates(retained_fail) == []
        assert validate_pool_five_gates({"candidates": [retained_fail, eligible_pass]}) == []


def test_conditional_editorial_candidate_requires_nonblank_processing_note():
    candidate = social_candidate("conditional", gates=five_gates(overall="CONDITIONAL", gate1="CONDITIONAL"))

    assert validate_five_gates(candidate) == ["candidate_conditional_conditional_requires_compliant_angle"]


def test_conditional_editorial_candidate_accepts_traceable_custom_processing_note():
    candidate = social_candidate(
        "conditional",
        gates=five_gates(overall="CONDITIONAL", gate1="CONDITIONAL"),
        compliant_angle="Use an institutional-analysis angle; omit case-specific details.",
    )

    assert validate_five_gates(candidate) == []


def test_conditional_editorial_candidate_rejects_non_string_processing_notes():
    for value in (None, [], {}, 0, False):
        candidate = social_candidate(
            "conditional-invalid-angle",
            gates=five_gates(overall="CONDITIONAL", gate1="CONDITIONAL"),
            compliant_angle=value,
        )

        assert validate_five_gates(candidate) == [
            "candidate_conditional-invalid-angle_conditional_requires_compliant_angle"
        ]


def test_social_candidate_rejects_missing_unknown_and_non_string_recommendations():
    for value in ("a", "D", "Publish", None, ["A"]):
        candidate = social_candidate("invalid-recommendation", recommendation=value)

        assert validate_five_gates(candidate) == [
            "candidate_invalid-recommendation_invalid_recommendation"
        ]

    missing_recommendation = social_candidate("missing-recommendation")
    del missing_recommendation["recommendation"]

    assert validate_five_gates(missing_recommendation) == [
        "candidate_missing-recommendation_invalid_recommendation"
    ]


def test_legacy_result_is_accepted_when_overall_is_absent():
    legacy_pass = social_candidate("legacy-pass", gates=five_gates(result="PASS"))
    legacy_fail = social_candidate("legacy-fail", recommendation="Wait", gates=five_gates(result="FAIL", gate1="FAIL"))

    assert validate_five_gates(legacy_pass) == []
    assert validate_five_gates(legacy_fail) == []


def test_overall_takes_precedence_and_reports_conflicting_legacy_result():
    candidate = social_candidate("conflict", gates=five_gates(overall="PASS", result="FAIL"))

    assert validate_five_gates(candidate) == ["candidate_conflict_overall_conflicts_with_result_overall_PASS_result_FAIL"]


def test_non_social_candidates_do_not_require_five_gates():
    assert validate_five_gates({"candidate_id": "film", "topic_type": "film", "recommendation": "A"}) == []


def test_single_low_confidence_scan_hint_does_not_enforce_fail():
    candidate = social_candidate("hint", title="案件有罪", gates=five_gates(overall="PASS"))

    assert scan_social_redlines("案件有罪") == ["hint:judicial_predict:有罪"]
    assert validate_five_gates(candidate) == []