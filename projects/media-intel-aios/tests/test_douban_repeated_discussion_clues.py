import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "scripts" / "article_production_live_run.py"


def load_module():
    spec = importlib.util.spec_from_file_location("article_production_live_run_repeated_clues", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def samples(*rows):
    return [
        {
            "id": sample_id,
            "url": f"https://movie.douban.com/subject/36225840/comments/{sample_id}/",
            "content": text,
        }
        for sample_id, text in rows
    ]


def test_repeated_concrete_keyword_is_auditable_and_writer_discovery_only():
    mod = load_module()

    signal = mod._normalize_douban_discussion_signal(
        subject_id="36225840",
        title="超级少女 Supergirl",
        source_url="https://movie.douban.com/subject/36225840/",
        short_comment={"content": "保留的 P0 短评"},
        rating="5.5",
        fetched_at="2026-07-12T00:00:00+00:00",
        raw_comment_samples=samples(
            ("a", "这个结局让人物选择显得突兀。"),
            ("b", "我一直在想结局是否改变了人物命运。"),
            ("c", "摄影和配乐都很好。"),
        ),
    )

    assert signal["comment_samples"][0]["text"] == "保留的 P0 短评"
    assert signal["sample_window"] == {
        "count": 3,
        "source": "douban_subject_abstract.short_comments",
        "collected_at": "2026-07-12T00:00:00+00:00",
        "min_samples": 3,
        "status": "complete",
    }
    assert signal["repeated_clues"] == [{"keyword": "结局", "count": 2, "sample_ids": ["a", "b"]}]
    assert "consensus" not in signal
    assert "controversy" not in signal
    assert "public_opinion" not in signal


def test_one_off_and_generic_words_do_not_produce_clues():
    mod = load_module()

    signal = mod._normalize_douban_discussion_signal(
        subject_id="36225840",
        title="超级少女",
        source_url="https://movie.douban.com/subject/36225840/",
        short_comment={"content": "保留的 P0 短评"},
        rating="5.5",
        fetched_at="2026-07-12T00:00:00+00:00",
        raw_comment_samples=samples(
            ("a", "这部电影的剧情不错。"),
            ("b", "电影剧情很普通。"),
            ("c", "摄影值得一看。"),
        ),
    )

    assert signal["sample_window"]["status"] == "complete"
    assert signal["repeated_clues"] == []


@pytest.mark.parametrize(
    "raw_samples",
    [
        samples(("same", "结局令人意外。"), ("same", "结局仍然意外。"), ("c", "摄影不错。")),
        [
            {"id": "a", "url": "https://movie.douban.com/subject/36225840/comments/a/", "content": "结局令人意外。"},
            {"id": "b", "url": "", "content": "结局仍然意外。"},
            {"id": "c", "url": "https://movie.douban.com/subject/36225840/comments/c/", "content": "摄影不错。"},
        ],
    ],
)
def test_invalid_explicit_raw_samples_fail_closed(raw_samples):
    mod = load_module()

    with pytest.raises(ValueError, match="raw comment samples"):
        mod._normalize_douban_discussion_signal(
            subject_id="36225840",
            title="超级少女",
            source_url="https://movie.douban.com/subject/36225840/",
            short_comment={"content": "保留的 P0 短评"},
            rating="5.5",
            fetched_at="2026-07-12T00:00:00+00:00",
            raw_comment_samples=raw_samples,
        )


def test_insufficient_explicit_samples_fail_closed_without_inference():
    mod = load_module()

    signal = mod._normalize_douban_discussion_signal(
        subject_id="36225840",
        title="超级少女",
        source_url="https://movie.douban.com/subject/36225840/",
        short_comment={"content": "保留的 P0 短评"},
        rating="5.5",
        fetched_at="2026-07-12T00:00:00+00:00",
        raw_comment_samples=samples(("a", "结局令人意外。"), ("b", "结局仍然意外。")),
    )

    assert signal["sample_window"]["count"] == 2
    assert signal["sample_window"]["status"] == "insufficient_samples"
    assert "repeated_clues" not in signal


def test_bad_work_identity_fails_closed():
    mod = load_module()

    with pytest.raises(ValueError, match="numeric subject id"):
        mod._normalize_douban_discussion_signal(
            subject_id="bad",
            title="超级少女",
            source_url="https://movie.douban.com/subject/36225840/",
            short_comment={"content": "保留的 P0 短评"},
            rating="5.5",
            fetched_at="2026-07-12T00:00:00+00:00",
            raw_comment_samples=samples(("a", "结局令人意外。"), ("b", "结局仍然意外。"), ("c", "摄影不错。")),
        )


def test_live_adapter_keeps_generic_fields_unchanged_when_only_one_public_sample_exists(monkeypatch):
    mod = load_module()

    def fetch(url):
        if "j/search_subjects" in url:
            return {"subjects": [{"id": "36225840", "title": "超级少女", "rate": "5.5", "url": "https://movie.douban.com/subject/36225840/"}]}
        if "j/subject_abstract" in url:
            return {"subject": {"title": "超级少女", "rate": "5.5", "url": "https://movie.douban.com/subject/36225840/", "short_comment": {"content": "唯一短评"}}}
        raise AssertionError(url)

    monkeypatch.setattr(mod, "_fetch_json_url", fetch)
    result = mod.fetch_audience_reaction_signal()

    assert result["success"] is True
    assert result["signal_role"] == "audience_reaction_signal"
    assert result["structured_signals"]["review_comments"] == ["唯一短评"]
    assert result["discussion_signal"]["sample_window"]["status"] == "insufficient_samples"
    assert "repeated_clues" not in result["discussion_signal"]


def test_live_adapter_uses_only_explicit_direct_raw_sample_list(monkeypatch):
    mod = load_module()

    def fetch(url):
        if "j/search_subjects" in url:
            return {"subjects": [{"id": "36225840", "title": "超级少女", "rate": "5.5", "url": "https://movie.douban.com/subject/36225840/"}]}
        if "j/subject_abstract" in url:
            return {"subject": {
                "title": "超级少女", "rate": "5.5", "url": "https://movie.douban.com/subject/36225840/",
                "short_comment": {"content": "保留的 P0 短评"},
                "short_comments": samples(
                    ("a", "这个结局让人物选择显得突兀。"),
                    ("b", "我一直在想结局是否改变了人物命运。"),
                    ("c", "摄影和配乐都很好。"),
                ),
            }}
        raise AssertionError(url)

    monkeypatch.setattr(mod, "_fetch_json_url", fetch)
    result = mod.fetch_audience_reaction_signal()

    signal = result["discussion_signal"]
    assert result["success"] is True
    assert signal["sample_window"]["count"] == 3
    assert signal["raw_comment_samples"] == samples(
        ("a", "这个结局让人物选择显得突兀。"),
        ("b", "我一直在想结局是否改变了人物命运。"),
        ("c", "摄影和配乐都很好。"),
    )
    assert signal["repeated_clues"] == [{"keyword": "结局", "count": 2, "sample_ids": ["a", "b"]}]
