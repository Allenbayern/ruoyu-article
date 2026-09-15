from __future__ import annotations

import importlib.util


def test_run_profile_module_exists_and_validates_two_article_daily_contract():
    assert importlib.util.find_spec("article_group.run_profile") is not None

    from article_group.run_profile import get_run_profile, validate_batch_profile

    profile = get_run_profile("two_article_daily")
    assert profile.article_count == 2
    assert profile.slot_labels == ("A", "B")
    # 2026-09-16 controller ruling：字数要求允许 ±100 误差，下限 1000→900，
    # 上限 2700→2800；篇幅以素材为准。
    assert profile.min_cjk_chars == 900
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
