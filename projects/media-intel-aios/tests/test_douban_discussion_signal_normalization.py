import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "scripts" / "article_production_live_run.py"


def load_module():
    spec = importlib.util.spec_from_file_location("article_production_live_run_discussion_signal", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fetch_success(url):
    if "j/search_subjects" in url:
        return {
            "subjects": [
                {
                    "id": "36225840",
                    "title": "超级少女",
                    "rate": "5.5",
                    "url": "https://movie.douban.com/subject/36225840/",
                }
            ]
        }
    if "j/subject_abstract" in url:
        return {
            "subject": {
                "title": "超级少女 Supergirl",
                "rate": "5.5",
                "url": "https://movie.douban.com/subject/36225840/",
                "short_comment": {
                    "id": "comment-42",
                    "url": "https://movie.douban.com/subject/36225840/comments/comment-42/",
                    "content": "  观众短评认为故事主线薄弱，但讨论度很高。\n",
                },
            }
        }
    raise AssertionError(url)


def test_douban_success_adds_raw_work_level_discussion_signal(monkeypatch):
    mod = load_module()
    monkeypatch.setattr(mod, "_fetch_json_url", _fetch_success)

    result = mod.fetch_audience_reaction_signal()

    assert result["success"] is True
    assert result["status"] == "focused_live_verified"
    assert result["structured_signals"]["review_comments"] == ["观众短评认为故事主线薄弱，但讨论度很高。"]
    assert result["discussion_signal"] == {
        "platform": "douban",
        "work_key": "douban:36225840",
        "work_title": "超级少女 Supergirl",
        "source_url": "https://movie.douban.com/subject/36225840/",
        "fetched_at": result["finished_at"],
        "comment_samples": [
            {
                "text": "  观众短评认为故事主线薄弱，但讨论度很高。\n",
                "id": "comment-42",
                "url": "https://movie.douban.com/subject/36225840/comments/comment-42/",
                "rating": "5.5",
            }
        ],
        "rating": "5.5",
        "sentiment_hint": "mixed_or_negative",
        "status": "focused_live_verified",
        "sample_window": {
            "count": 0,
            "source": "douban_subject_abstract.short_comments",
            "collected_at": result["finished_at"],
            "min_samples": 3,
            "status": "insufficient_samples",
        },
    }
    assert "consensus" not in result["discussion_signal"]
    assert "controversy" not in result["discussion_signal"]


def test_douban_missing_required_normalization_field_fails_closed(monkeypatch):
    mod = load_module()

    def fetch_missing_source_url(url):
        payload = _fetch_success(url)
        if "j/subject_abstract" in url:
            payload["subject"]["url"] = ""
        return payload

    monkeypatch.setattr(mod, "_fetch_json_url", fetch_missing_source_url)
    result = mod.fetch_audience_reaction_signal()

    assert result["success"] is False
    assert result["status"] == "ERROR"
    assert result["discussion_signal"]["status"] == "ERROR"
    assert result["discussion_signal"]["comment_samples"] == []
    assert result["discussion_signal"]["work_key"] == "douban:36225840"


@pytest.mark.parametrize("field, value", [("title", ""), ("url", "not-a-url")])
def test_douban_missing_or_invalid_work_metadata_fails_closed(monkeypatch, field, value):
    mod = load_module()

    def fetch_invalid_metadata(url):
        payload = _fetch_success(url)
        if "j/subject_abstract" in url:
            payload["subject"][field] = value
        return payload

    monkeypatch.setattr(mod, "_fetch_json_url", fetch_invalid_metadata)
    result = mod.fetch_audience_reaction_signal()

    assert result["success"] is False
    assert result["status"] == "ERROR"
    assert result["discussion_signal"]["status"] == "ERROR"
    assert result["discussion_signal"]["comment_samples"] == []


def test_douban_no_comment_and_fetch_error_have_safe_empty_discussion_signal(monkeypatch):
    mod = load_module()

    def fetch_no_comment(url):
        payload = _fetch_success(url)
        if "j/subject_abstract" in url:
            payload["subject"]["short_comment"] = {"content": "  \n"}
        return payload

    monkeypatch.setattr(mod, "_fetch_json_url", fetch_no_comment)
    no_comment = mod.fetch_audience_reaction_signal()
    assert no_comment["success"] is False
    assert no_comment["discussion_signal"]["status"] == "ERROR"
    assert no_comment["discussion_signal"]["comment_samples"] == []

    monkeypatch.setattr(mod, "_fetch_json_url", lambda _url: (_ for _ in ()).throw(TimeoutError("forced timeout")))
    fetch_error = mod.fetch_audience_reaction_signal()
    assert fetch_error["success"] is False
    assert fetch_error["discussion_signal"]["status"] == "ERROR"
    assert fetch_error["discussion_signal"]["comment_samples"] == []


def test_discussion_signal_is_additive_and_does_not_change_generic_eligibility(monkeypatch):
    mod = load_module()
    monkeypatch.setattr(mod, "_fetch_json_url", _fetch_success)

    result = mod.fetch_audience_reaction_signal()

    assert result["source_id"] == "douban_reviews_discussions"
    assert result["signal_role"] == "audience_reaction_signal"
    assert result["narrative_roles"] == ["audience_sentiment", "review_comments", "social_discussion"]
    assert mod.VERIFIED_SOURCE_POOL["douban_reviews_discussions"]["production_eligible"] is True
    assert mod.VERIFIED_SOURCE_POOL["douban_reviews_discussions"]["allowed_use"] == ["audience_sentiment", "review_comments", "social_discussion"]
