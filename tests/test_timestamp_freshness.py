"""Tests for timestamp, freshness window, and time sanity validation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def _recent_past() -> str:
    return (datetime.now(UTC) - timedelta(hours=2)).isoformat()


def _future() -> str:
    return (datetime.now(UTC) + timedelta(days=30)).isoformat()


def _days_ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


# --- freshness classification ---

def test_future_candidate_event_time_is_rejected():
    from article_group.prewrite import validate_candidate_pool

    from test_prewrite_contract import valid_candidate_pool
    pool = valid_candidate_pool()
    pool["candidates"][0]["event_time"] = _future()
    errors = validate_candidate_pool(pool)
    # Should produce an error about event_time being in the future
    assert any(
        "event_time" in err.lower() and ("future" in err.lower() or "after" in err.lower())
        for err in errors
    ) or any("future" in err.lower() for err in errors)


def test_ten_day_old_release_without_new_trigger_is_not_fermenting():
    from article_group.prewrite import classify_freshness

    result = classify_freshness(
        event_time=_days_ago(10),
        observed_at=_recent_past(),
        freshness_window="fermenting-1-3d",
        current_trigger="",
    )
    assert result != "ok"


def test_true_same_day_passes():
    from article_group.prewrite import classify_freshness

    result = classify_freshness(
        event_time=_recent_past(),
        observed_at=_recent_past(),
        freshness_window="same-day",
        current_trigger="新片上映",
    )
    assert result == "ok"


def test_revival_requires_current_trigger():
    from article_group.prewrite import classify_freshness

    result = classify_freshness(
        event_time=_days_ago(30),
        observed_at=_recent_past(),
        freshness_window="revival",
        current_trigger="",
    )
    assert result != "ok"


def test_fermenting_window_outside_1_to_3_days_is_rejected():
    from article_group.prewrite import classify_freshness

    result = classify_freshness(
        event_time=_days_ago(5),
        observed_at=_recent_past(),
        freshness_window="fermenting-1-3d",
        current_trigger="still discussed",
    )
    assert result != "ok"


def test_older_than_72h_fermenting_rejected():
    from article_group.prewrite import classify_freshness

    result = classify_freshness(
        event_time=_days_ago(4),
        observed_at=_recent_past(),
        freshness_window="fermenting-1-3d",
        current_trigger="someone posted about it",
    )
    assert result != "ok"


def test_evergreen_cannot_be_labeled_same_day():
    from article_group.prewrite import classify_freshness

    result = classify_freshness(
        event_time=_days_ago(60),
        observed_at=_recent_past(),
        freshness_window="same-day",
        current_trigger="",
    )
    assert result != "ok"


def test_valid_fermenting_accepts_1_to_3_days():
    from article_group.prewrite import classify_freshness

    result = classify_freshness(
        event_time=_days_ago(2),
        observed_at=_recent_past(),
        freshness_window="fermenting-1-3d",
        current_trigger="第二批讨论开始",
    )
    assert result == "ok"


def test_observed_before_event_rejected():
    from article_group.prewrite import classify_freshness

    result = classify_freshness(
        event_time=_recent_past(),
        observed_at=_days_ago(1),
        freshness_window="same-day",
        current_trigger="上映",
    )
    assert result != "ok"


def test_future_observed_at_is_rejected():
    from article_group.prewrite import validate_candidate_pool

    from test_prewrite_contract import valid_candidate_pool
    pool = valid_candidate_pool()
    pool["observed_at"] = _future()
    errors = validate_candidate_pool(pool)
    assert any("future" in err.lower() for err in errors)
