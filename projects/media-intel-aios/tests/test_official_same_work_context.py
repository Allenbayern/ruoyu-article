import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_module():
    path = ROOT / "scripts" / "article_production_live_run.py"
    spec = importlib.util.spec_from_file_location("article_production_live_run_official", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CASES = [
    ({"subject_id": "36877245", "title": "火遮眼 The Furious (2025)", "url": "https://movie.douban.com/subject/36877245/"}, "https://www.youtube.com/watch?v=J6nia3eu5RY", '<script>var ytInitialPlayerResponse = {"videoDetails":{"title":"《火遮眼》The Furious 官方預告","shortDescription":"導演：谷垣健治 主演：謝苗。王偉的女兒雨晴被兒童走私組織擄走，他與記者納文聯手追查地下組織。"},"microformat":{"playerMicroformatRenderer":{"uploadDate":"2026-06-01","publishDate":"2026-06-01"}}};</script>'),
    ({"subject_id": "36916000", "title": "诺曼底72小时 Pressure (2026)", "url": "https://movie.douban.com/subject/36916000/"}, "https://www.focusfeatures.com/pressure", '<html><head><title>Pressure | Focus Features</title><meta property="og:description" content="In the tense 72 hours before D-Day, Pressure follows General Dwight D. Eisenhower and Captain James Stagg as they face an impossible choice about the invasion and fate of the war."></head><body>May 29, 2026 | Drama <dl><dt>Starring</dt><dd>Andrew Scott, Brendan Fraser</dd><dt>Directed By</dt><dd>Anthony Maras</dd></dl></body></html>'),
    ({"subject_id": "37042683", "title": "卡罗来纳的卡罗琳 Carolina Caroline (2025)", "url": "https://movie.douban.com/subject/37042683/"}, "https://www.youtube.com/watch?v=-x_4XLUE1qc", '<script>var ytInitialPlayerResponse = {"videoDetails":{"title":"Carolina Caroline - Official Teaser Trailer","shortDescription":"Directed by Adam Carter Rehmeier. Samara Weaving stars as Caroline Daniels, whose desire to leave her small Texas town brings her together with a charismatic con man played by Kyle Gallner on a journey of crime and passion."},"microformat":{"playerMicroformatRenderer":{"uploadDate":"2026-03-23","publishDate":"2026-03-23"}}};</script>'),
]


def test_official_same_work_context_accepts_each_explicit_mapping(monkeypatch):
    mod = load_module()
    for anchor, page_url, page_html in CASES:
        monkeypatch.setattr(mod, "_fetch_html_url", lambda _url, u=page_url, body=page_html, **_kwargs: {"url": u, "html": body})
        result = mod.fetch_official_same_work_context(anchor)
        assert result["success"] is True
        assert result["source_id"] == "official_same_work_context"
        assert result["signal_role"] == "article_body_signal"
        assert result["live_subject"] == anchor
        assert result["top_signals"][0]["url"] == page_url
        assert len(result["top_signals"][0]["description"]) >= 20


def test_official_same_work_context_rejects_identity_or_context_failure(monkeypatch):
    mod = load_module()
    for anchor, page_url, page_html in CASES:
        bad_pages = [
            {"url": page_url + "-wrong", "html": page_html},
            {"url": page_url, "html": page_html.replace("2026", "2025")},
            {"url": page_url, "html": page_html.replace("谷垣健治", "其他導演").replace("Anthony Maras", "Other Director").replace("Adam Carter Rehmeier", "Other Director")},
            {"url": page_url, "html": page_html.replace("王偉的女兒雨晴被兒童走私組織擄走，他與記者納文聯手追查地下組織。", "太短").replace("In the tense 72 hours before D-Day, Pressure follows General Dwight D. Eisenhower and Captain James Stagg as they face an impossible choice about the invasion and fate of the war.", "Too short").replace("Samara Weaving stars as Caroline Daniels, whose desire to leave her small Texas town brings her together with a charismatic con man played by Kyle Gallner on a journey of crime and passion.", "Too short")},
        ]
        for fetched in bad_pages:
            monkeypatch.setattr(mod, "_fetch_html_url", lambda _url, item=fetched, **_kwargs: item)
            result = mod.fetch_official_same_work_context(anchor)
            assert result["success"] is False
            assert result["fields_extracted"] == []
            assert "live_subject" not in result
    assert mod.fetch_official_same_work_context({"subject_id": "unknown", "title": "The Furious (2026)", "url": "https://movie.douban.com/subject/unknown/"})["success"] is False


def test_collect_then_batch_yields_three_strict_ready_work_keys(monkeypatch, tmp_path):
    mod = load_module()
    batch_path = ROOT / "scripts" / "run_experimental_article_candidate_batch.py"
    spec = importlib.util.spec_from_file_location("article_candidate_batch_official", batch_path)
    assert spec and spec.loader
    batch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(batch)
    anchors = [case[0] for case in CASES]
    audience = [{"source_id": "douban_reviews_discussions", "source_name": "豆瓣短评", "signal_role": "audience_reaction_signal", "narrative_roles": ["audience_sentiment", "review_comments"], "success": True, "status": "focused_live_verified", "live_subject": a, "top_signals": [{"title": f"《{a['title']}》短评", "description": "观众围绕角色选择、剧情冲突和结局展开了持续而具体的讨论与分歧。", "url": a["url"] + "comments"}]} for a in anchors]
    official = {a["subject_id"]: {"source_id": "official_same_work_context", "source_name": "官方同作品页面剧情上下文", "signal_role": "article_body_signal", "narrative_roles": ["plot_character_context"], "success": True, "status": "focused_live_verified", "live_subject": a, "top_signals": [{"title": a["title"], "description": "影片围绕具体人物的关键选择与犯罪或战争危机展开，这是一段足够具体的剧情和人物上下文证据。", "url": u}]} for a, u, _ in CASES}
    failed = lambda: {"success": False, "source_id": "ignored", "status": "ERROR"}
    monkeypatch.setattr(mod, "fetch_audience_reaction_signals", lambda subject_limit=mod.DOUBAN_LIVE_SUBJECT_LIMIT: audience)
    monkeypatch.setattr(mod, "fetch_bilibili_same_work_enrichment", lambda _a: failed())
    monkeypatch.setattr(mod, "fetch_1905_same_work_context", lambda _a: failed())
    monkeypatch.setattr(mod, "fetch_official_same_work_context", lambda a: official[a["subject_id"]])
    monkeypatch.setattr(mod, "fetch_letterboxd_same_work_context", lambda _a: (_ for _ in ()).throw(AssertionError("official success must stop fallback")))
    for name in ("fetch_article_body_signal", "fetch_weibo_entertainment_hotsearch_signal", "fetch_weibo_topic_search_signal", "fetch_zhihu_movie_hot_topics_signal", "fetch_bilibili_movie_zone_hot_signal", "fetch_xiaohongshu_movie_notes_signal", "fetch_douyin_movie_hot_signal"):
        monkeypatch.setattr(mod, name, failed)
    rows = mod.collect_live_backfill_rows()
    assert len(rows) == 6
    expected = {"douban:36877245", "douban:36916000", "douban:37042683"}
    assert {row["work_key"] for row in rows} == expected
    result = batch.run_batch(tmp_path / "official-three.json", live_rows=rows, use_live_evidence=True)
    assert result["publish_ready"] is True
    assert len(result["article_candidate_buckets"]["A"]) == 3
    assert {item["work_key"] for item in result["article_candidate_buckets"]["A"]} == expected
