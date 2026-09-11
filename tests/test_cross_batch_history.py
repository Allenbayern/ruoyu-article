"""Empty history input is not a cross-batch pass."""
from article_group.portfolio_gate import (
    check_cross_batch,
    interpret_history_input,
    validate_cross_batch_report,
)


def test_bare_empty_list_is_not_loaded():
    result = interpret_history_input([])
    assert result["history_status"] == "not_loaded"
    assert result["attempted"] is False


def test_missing_history_is_not_loaded():
    result = interpret_history_input(None)
    assert result["history_status"] == "not_loaded"


def test_explicit_empty_history_after_load_is_not_a_fake_pass():
    result = interpret_history_input(
        {
            "history_status": "empty_history",
            "attempted": True,
            "source": "runs/*/controlled-*",
            "batches": [],
        }
    )
    assert result["history_status"] == "empty_history"
    issues = check_cross_batch(
        [{"candidate_id": "c1", "work": "《测试》", "reader_question": "为什么"}],
        [],
        history_status="empty_history",
    )
    assert all(issue["id"] != "portfolio.cross_batch.history_not_loaded" for issue in issues)
    assert any(issue["id"] == "portfolio.cross_batch.no_history" for issue in issues)
    assert all(issue["level"] != "error" for issue in issues)


def test_not_loaded_history_cannot_claim_cross_batch_pass():
    issues = check_cross_batch(
        [{"candidate_id": "c1", "work": "《测试》", "reader_question": "为什么"}],
        [],
        history_status="not_loaded",
    )
    assert any(issue["id"] == "portfolio.cross_batch.history_not_loaded" for issue in issues)
    errors = validate_cross_batch_report(
        {
            "checked": True,
            "history_status": "not_loaded",
            "window_batches": 0,
            "batches": [],
            "matches": [],
        }
    )
    assert "cross_batch_checked_without_loaded_history" in errors


def test_empty_list_without_status_cannot_pass():
    issues = check_cross_batch(
        [{"candidate_id": "c1", "work": "《测试》", "reader_question": "为什么"}],
        [],
    )
    assert any(issue["id"] == "portfolio.cross_batch.history_not_loaded" for issue in issues)


def test_content_similarity_uses_historical_question_not_historical_title():
    issues = check_cross_batch(
        [{
            "candidate_id": "c1",
            "work": "《新作》",
            "reader_question": "为什么这段关系会在门口改变",
            "primary_atom": "关系变化",
        }],
        [{
            "batch_dir": "old-1",
            "titles": ["为什么这段关系会在门口改变？"],
            "works": [],
            "content_fingerprints": ["为什么另一段关系会在门口改变"],
            "recent3": True,
        }],
        history_status="loaded",
    )

    assert any(issue["id"] == "portfolio.cross_batch.title_near_duplicate" for issue in issues)


def test_historical_title_alone_cannot_trigger_content_similarity():
    issues = check_cross_batch(
        [{
            "candidate_id": "c1",
            "work": "《新作》",
            "reader_question": "为什么这段关系会在门口改变",
        }],
        [{
            "batch_dir": "old-1",
            "titles": ["为什么这段关系会在门口改变？"],
            "works": [],
            "recent3": True,
        }],
        history_status="loaded",
    )

    assert all(issue["id"] != "portfolio.cross_batch.title_near_duplicate" for issue in issues)
