"""Tests for the institutional five-question topic preflight (2026-09-16)."""

from __future__ import annotations

from article_group.topic_preflight import evaluate


def clean_candidate(**overrides):
    value = {
        "candidate_id": "cand-1",
        "work_title": "兰香如故",
        "reader": "正在追《兰香如故》、被杜翠雀气得睡不着又在讨论她的观众",
        "landing": "看懂一个疯批女配的坏都有来处：才华被锁死才是悲剧的起点",
        "emotion": "又气又放不下",
        "remove_timestamp_test": "pass",
        "social_motive": "表达立场",
    }
    value.update(overrides)
    return value


def test_clean_candidate_passes():
    report = evaluate([clean_candidate()])
    assert report["status"] == "pass"
    assert report["errors"] == []
    assert report["warnings"] == []


def test_missing_field_is_error():
    report = evaluate([clean_candidate(landing="")])
    assert report["status"] == "fail"
    assert "cand-1:five_questions_missing:landing" in report["errors"]


def test_missing_field_blank_whitespace_is_error():
    report = evaluate([clean_candidate(emotion="   ")])
    assert "cand-1:five_questions_missing:emotion" in report["errors"]


def test_invalid_social_motive_is_error():
    report = evaluate([clean_candidate(social_motive="涨粉")])
    assert report["status"] == "fail"
    assert "cand-1:social_motive_invalid:涨粉" in report["errors"]


def test_invalid_remove_timestamp_test_is_error():
    report = evaluate([clean_candidate(remove_timestamp_test="maybe")])
    assert "cand-1:remove_timestamp_test_invalid:maybe" in report["errors"]


def test_remove_timestamp_fail_selected_blocks():
    # 编辑准则：删掉今天的新闻节点后没有价值的题目不进入写作。
    report = evaluate([clean_candidate(remove_timestamp_test="fail")])
    assert report["status"] == "fail"
    assert "cand-1:remove_timestamp_test_fail_selected" in report["errors"]


def test_remove_timestamp_risk_warns_but_passes():
    report = evaluate([clean_candidate(remove_timestamp_test="risk")])
    assert report["status"] == "pass"
    assert "cand-1:remove_timestamp_test_risk_selected" in report["warnings"]


def test_landing_boilerplate_warns():
    report = evaluate([clean_candidate(landing="这部作品值得一看")])
    assert report["status"] == "pass"
    assert "cand-1:landing_boilerplate" in report["warnings"]


def test_landing_too_short_warns():
    report = evaluate([clean_candidate(landing="好看")])
    assert "cand-1:landing_too_short" in report["warnings"]


def test_landing_equal_work_title_warns():
    report = evaluate([clean_candidate(landing="兰香如故")])
    assert "cand-1:landing_equals_work_title" in report["warnings"]


def test_empty_selection_is_error():
    report = evaluate([])
    assert report["status"] == "fail"
    assert "missing:selected_candidates" in report["errors"]


def test_every_social_motive_value_is_accepted():
    for motive in ("显摆新知", "找同类", "表达立场", "送温暖"):
        report = evaluate([clean_candidate(social_motive=motive)])
        assert report["status"] == "pass", motive
