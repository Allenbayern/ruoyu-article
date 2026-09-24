from __future__ import annotations

import importlib.util


def test_run_profile_module_exists_and_validates_two_article_daily_contract():
    assert importlib.util.find_spec("article_group.run_profile") is not None

    from article_group.run_profile import get_run_profile, validate_batch_profile

    profile = get_run_profile("two_article_daily")
    assert profile.article_count == 2
    assert profile.slot_labels == ("A", "B")
    # 2026-09-23 controller ruling（取代 2026-09-16 的下限口径）：1000 字出头的
    # 成稿被判单薄，下限 900→1500（= 编辑目标下限），上限维持 2800。
    assert profile.min_cjk_chars == 1500
    assert profile.max_cjk_chars == 2800
    batch = {
        "run_profile": "two_article_daily",
        "articles": [{"article_id": "art-001", "slot": "A"}, {"article_id": "art-002", "slot": "B"}],
    }
    assert validate_batch_profile(batch, require_explicit=True) == []


def test_run_profile_rejects_wrong_cardinality_and_missing_explicit_profile():
    from article_group.run_profile import validate_batch_profile

    wrong_count = {
        "run_profile": "two_article_daily",
        "articles": [{"article_id": "art-001", "slot": "A"}],
    }
    assert "article_count_mismatch:two_article_daily:expected=2:actual=1" in validate_batch_profile(
        wrong_count, require_explicit=True
    )
    missing = {"articles": [{"article_id": "art-001", "slot": "A"}]}
    assert validate_batch_profile(missing, require_explicit=True) == ["run_profile_missing"]


def test_run_profile_supports_legacy_three_slot_profile_without_changing_slot_labels():
    from article_group.run_profile import validate_batch_profile

    batch = {
        "run_profile": "three_slot_controlled",
        "articles": [
            {"article_id": "art-001", "slot": "A"},
            {"article_id": "art-002", "slot": "B"},
            {"article_id": "art-003", "slot": "C"},
        ],
    }
    assert validate_batch_profile(batch, require_explicit=True) == []


def test_three_article_daily_profile_matches_daily_gates():
    """三篇日更 profile（daily-011 起）：A/B/C 三槽，字数与门槛口径同两篇。"""

    from article_group.run_profile import get_run_profile, validate_batch_profile

    profile = get_run_profile("three_article_daily")
    assert profile.article_count == 3
    assert profile.slot_labels == ("A", "B", "C")
    assert profile.min_cjk_chars == 1500
    assert profile.max_cjk_chars == 2800

    batch = {
        "run_profile": "three_article_daily",
        "articles": [
            {"article_id": "art-001", "slot": "A"},
            {"article_id": "art-002", "slot": "B"},
            {"article_id": "art-003", "slot": "C"},
        ],
    }
    assert validate_batch_profile(batch, require_explicit=True) == []

    two_only = {
        "run_profile": "three_article_daily",
        "articles": [
            {"article_id": "art-001", "slot": "A"},
            {"article_id": "art-002", "slot": "B"},
        ],
    }
    assert "article_count_mismatch:three_article_daily:expected=3:actual=2" in validate_batch_profile(
        two_only, require_explicit=True
    )
