import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "far_east_films_all_the_good_eyes.html"
ANCHOR = {
    "subject_id": "36372941",
    "title": "森中有林 / All the Good Eyes (2026)",
    "url": "https://movie.douban.com/subject/36372941/",
}
URL = "https://fareastfilms.com/fef-news/trailer-all-the-good-eyes/"


def load_live():
    path = ROOT / "scripts" / "article_production_live_run.py"
    spec = importlib.util.spec_from_file_location("live_far_east_films_direct_source_packet", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fixture() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def packet_with_html(monkeypatch, html: str, *, final_url: str = URL, anchor: dict | None = None):
    mod = load_live()
    monkeypatch.setattr(mod, "_fetch_html_url", lambda url, **_kwargs: {"url": final_url, "html": html})
    return mod.fetch_far_east_films_direct_body_packet(anchor or ANCHOR)


def test_far_east_films_packet_extracts_one_attributed_synopsis_atom(monkeypatch):
    result = packet_with_html(monkeypatch, fixture())

    assert result["success"] is True
    assert result["source_id"] == "independent_direct_source_packet"
    assert result["generic_eligibility_credit"] is False
    assert result["requires_attribution_in_output"] is True
    assert result["work_key"] == "douban:36372941"
    assert len(result["supplementary_attributed_evidence"]) == 1
    atom = result["supplementary_attributed_evidence"][0]
    assert atom["source_role"] == "far_east_films_editorial_synopsis"
    assert atom["epistemic_status"] == "attributed_editorial_synopsis"
    assert atom["attribution"] == "Far East Films editorial synopsis"
    assert atom["url"] == atom["canonical_url"] == URL
    assert atom["published_at"] == "2026-04-08"
    assert atom["root_locator"] == "main#main.site-main > .page-content > .entry-content"
    assert "After losing an eye" in atom["source_text"]


def test_far_east_films_packet_fails_closed_for_exact_final_canonical_date_root_and_identity(monkeypatch):
    cases = [
        ("final", fixture(), "https://fareastfilms.com/fef-news/wrong/", ANCHOR),
        ("canonical", fixture().replace(URL, "https://fareastfilms.com/fef-news/wrong/", 1), URL, ANCHOR),
        ("date", fixture().replace("2026-04-08T00:00:00+00:00", "2026-04-09T00:00:00+00:00"), URL, ANCHOR),
        ("root", fixture().replace('class="entry-content"', 'class="wrong-content"'), URL, ANCHOR),
        ("identity", fixture(), URL, {**ANCHOR, "title": "森中有林 (2025)"}),
    ]
    for name, html, final_url, anchor in cases:
        result = packet_with_html(monkeypatch, html, final_url=final_url, anchor=anchor)
        assert result["success"] is False, name
        assert result["supplementary_attributed_evidence"] == [], name


def test_far_east_films_packet_requires_title_byline_synopsis_and_body(monkeypatch):
    for name, html in [
        ("title", fixture().replace("Trailer: ‘All the Good Eyes’", "Trailer: ‘Wrong Film’")),
        ("byline", fixture().replace("Phil Mills", "Anonymous")),
        ("synopsis", fixture().replace("Synopsis:", "Summary:")),
        ("body", fixture().replace("After losing an eye in a violent incident", "Short")),
    ]:
        result = packet_with_html(monkeypatch, html)
        assert result["success"] is False, name
        assert result["supplementary_attributed_evidence"] == [], name


def test_far_east_films_packet_is_explicit_opt_in_only(monkeypatch):
    mod = load_live()
    calls = []
    audience = [{"success": True, "source_id": "douban_reviews_discussions", "live_subject": ANCHOR, "top_signals": []}]
    monkeypatch.setattr(mod, "fetch_audience_reaction_signals", lambda subject_limit=mod.DOUBAN_LIVE_SUBJECT_LIMIT: audience)
    monkeypatch.setattr(mod, "fetch_bilibili_same_work_enrichment", lambda _subject: {"success": True})
    monkeypatch.setattr(mod, "fetch_far_east_films_direct_body_packet", lambda subject: calls.append(subject["subject_id"]) or {"success": False})
    for name in ("fetch_article_body_signal", "fetch_weibo_entertainment_hotsearch_signal", "fetch_weibo_topic_search_signal", "fetch_zhihu_movie_hot_topics_signal", "fetch_bilibili_movie_zone_hot_signal", "fetch_xiaohongshu_movie_notes_signal", "fetch_douyin_movie_hot_signal"):
        monkeypatch.setattr(mod, name, lambda: {"success": False, "source_id": "ignored", "status": "ERROR"})

    mod.collect_live_backfill_rows()
    assert calls == []
    mod.collect_live_backfill_rows(requested_far_east_films_direct_body_subject_ids={"36372941"})
    assert calls == ["36372941"]
