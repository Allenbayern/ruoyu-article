import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "scripts" / "article_production_live_run.py"


def load_module():
    spec = importlib.util.spec_from_file_location("article_production_live_run", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fake_maoyan_success():
    return {
        "source_id": "maoyan_realtime_boxoffice",
        "source_name": "猫眼专业版实时票房",
        "role": "P0_market_data",
        "signal_role": "market_signal",
        "fetch_path": "direct_live",
        "started_at": "2026-06-30T00:00:00+00:00",
        "finished_at": "2026-06-30T00:00:01+00:00",
        "duration_ms": 10,
        "success": True,
        "raw_url": "https://piaofang.maoyan.com/dashboard-ajax/movie",
        "status": "PASS: endpoint returned 3 extracted movie rows",
        "fields_extracted": ["title", "rank", "release_info", "sum_box_desc", "show_count", "box_rate", "show_count_rate", "avg_seat_view"],
        "observation": {
            "source_id": "maoyan_realtime_boxoffice",
            "source_name": "猫眼专业版实时票房",
            "priority": "P0",
            "source_role": "film_box_office_market_data",
            "observed_at": "2026-06-30T00:00:00+00:00",
            "raw_url": "https://piaofang.maoyan.com/dashboard-ajax/movie",
            "access_status": "PASS: endpoint returned 3 extracted movie rows",
            "extracted_items": [
                {"item_id": "maoyan_movie_1545588", "title": "四渡", "category": "film", "rank": 1, "metrics": {"release_info": "上映5天", "sum_box_desc": "1.02亿", "show_count": 89891, "box_rate": "32.7%", "show_count_rate": "23.5%", "avg_seat_view": "0.6%"}},
                {"item_id": "maoyan_movie_1490532", "title": "玩具总动员5", "category": "film", "rank": 2, "metrics": {"release_info": "上映12天", "sum_box_desc": "2.09亿", "show_count": 56406, "box_rate": "16.8%", "show_count_rate": "14.7%", "avg_seat_view": "0.5%"}},
                {"item_id": "maoyan_movie_1591067", "title": "后室", "category": "film", "rank": 3, "metrics": {"release_info": "上映5天", "sum_box_desc": "4480.5万", "show_count": 49359, "box_rate": "15.5%", "show_count_rate": "12.9%", "avg_seat_view": "0.6%"}},
            ],
        },
        "candidate": {"topic_id": "film_tv_maoyan_boxoffice_20260630_001"},
        "error": None,
    }


def _guduo_result(category, category_cn, names):
    return {
        "source_name": "骨朵热度指数",
        "source_type": "heat_rank",
        "category": category,
        "category_cn": category_cn,
        "rank_date": "2026-06-28",
        "rank_type": "DAILY",
        "fetch_time": "2026-06-30T00:00:00Z",
        "fetch_mode": "remote_api",
        "sample_evidence_path": None,
        "item_count": len(names),
        "items": [
            {"rank": i + 1, "name": name, "category": category, "show_id": 28000 + i, "gdi": 75.0 - i, "rise": 1 - i, "platforms": ["爱奇艺"], "release_date": "2026-06-20", "days": 5 + i}
            for i, name in enumerate(names)
        ],
    }


def fake_guduo_success():
    return {
        "source_id": "guduo",
        "source_name": "骨朵热度指数",
        "role": "P1_heat_rank",
        "signal_role": "heat_signal",
        "fetch_path": "direct_live",
        "started_at": "2026-06-30T00:00:00+00:00",
        "finished_at": "2026-06-30T00:00:01+00:00",
        "duration_ms": 12,
        "success": True,
        "raw_url_pattern": "http://d2.guduomedia.com/m/v3/billboard/list?type=DAILY&category={CATEGORY}&date={DATE}&platformId=",
        "status": "OK",
        "fields_extracted": ["rank", "name", "category", "gdi", "rise", "platforms", "release_date", "days"],
        "results": {
            "NETWORK_DRAMA": _guduo_result("NETWORK_DRAMA", "网络剧", ["昨夜将至", "莫离", "南部档案"]),
            "NETWORK_VARIETY": _guduo_result("NETWORK_VARIETY", "网络综艺", ["地球超新鲜 第2季", "乘风2026", "哈哈哈哈哈 第六季"]),
            "NETWORK_MOVIE": _guduo_result("NETWORK_MOVIE", "网络电影", ["重出江湖", "盲蛇", "史诡记之黄泉村"]),
            "ALL_ANIME": _guduo_result("ALL_ANIME", "动漫", ["凡人修仙传年番", "仙逆", "斩神之凡尘神域 第2季"]),
        },
        "error": None,
    }

def fake_article_body_signal_success():
    return {
        "source_id": "toutiao_deep_film_tv_articles",
        "source_name": "头条深度影视文章样本",
        "role": "P1A_article_body_pattern",
        "signal_role": "article_body_signal",
        "narrative_roles": ["plot_character_context"],
        "allowed_use": ["article_structure_signal", "plot_character_context", "angle_pattern_support"],
        "can_be_main_narrative_source": True,
        "fetch_path": "verified_baseline_reconnected",
        "started_at": "2026-06-30T00:00:00+00:00",
        "finished_at": "2026-06-30T00:00:01+00:00",
        "duration_ms": 5,
        "success": True,
        "status": "focused_verifier_passed",
        "fields_extracted": ["title_pattern", "hook_pattern", "outline_pattern", "angle_candidate", "claim_candidate"],
        "sample_signals": ["深度文标题通常先建立判断冲突，再解释作品或市场现象"],
        "error": None,
    }


def fake_audience_reaction_signal_success():
    return {
        "source_id": "douban_reviews_discussions",
        "source_name": "豆瓣短评/讨论 live signal",
        "role": "P1C_audience_reaction",
        "signal_role": "audience_reaction_signal",
        "narrative_roles": ["audience_sentiment", "review_comments", "social_discussion"],
        "allowed_use": ["audience_sentiment", "review_comments", "social_discussion"],
        "can_be_main_narrative_source": True,
        "fetch_path": "direct_live",
        "started_at": "2026-06-30T00:00:00+00:00",
        "finished_at": "2026-06-30T00:00:01+00:00",
        "duration_ms": 5,
        "success": True,
        "status": "focused_live_verified",
        "fields_extracted": ["subject_id", "title", "rate", "short_comment", "sentiment_keyword"],
        "structured_signals": {
            "audience_emotion": "mixed_to_positive",
            "review_comments": ["观众短评样本"],
            "social_discussion": ["观众短评样本"],
            "sentiment_keyword": "mixed_to_positive",
        },
        "sample_signals": ["观众争议应被用来寻找问题意识，而不是替代事实核验"],
        "error": None,
    }


def fake_weibo_entertainment_hotsearch_success():
    return {
        "source_id": "weibo_entertainment_hotsearch",
        "source_name": "微博文娱热搜 live signal",
        "role": "P0_social_hotsearch",
        "signal_role": "social_discussion_signal",
        "narrative_roles": ["hot_search", "social_discussion"],
        "allowed_use": ["entertainment hot-search discovery", "social discussion signal"],
        "can_be_main_narrative_source": True,
        "fetch_path": "direct_live",
        "started_at": "2026-06-30T00:00:00+00:00",
        "finished_at": "2026-06-30T00:00:01+00:00",
        "duration_ms": 5,
        "success": True,
        "status": "focused_live_verified",
        "fields_extracted": ["word", "rank", "heat", "flag_desc", "topic_flag", "url"],
        "structured_signals": {
            "hot_search": [{"word": "金鹰奖最佳女主角候选", "rank": 1, "heat": 2128645, "flag_desc": "新", "topic_flag": 1, "url": "https://s.weibo.com/weibo?q=金鹰奖最佳女主角候选"}],
            "social_discussion": ["金鹰奖最佳女主角候选"],
        },
        "forbidden_use": ["verified_facts", "whole-network generalization", "single-topic conclusion", "publish-ready evidence"],
        "sample_signals": ["微博热搜话题：金鹰奖最佳女主角候选（heat=2128645, flag=新）"],
        "error": None,
    }


def fake_weibo_topic_search_success():
    return {
        "source_id": "weibo_topic_search",
        "source_name": "微博话题搜索 live signal",
        "role": "P0_social_topic_search",
        "signal_role": "social_discussion_signal",
        "narrative_roles": ["social_discussion", "hot_search"],
        "allowed_use": ["topic search discovery", "social discussion signal"],
        "can_be_main_narrative_source": True,
        "fetch_path": "direct_live",
        "started_at": "2026-06-30T00:00:00+00:00",
        "finished_at": "2026-06-30T00:00:01+00:00",
        "duration_ms": 5,
        "success": False,
        "status": "live_inaccessible",
        "fields_extracted": [],
        "signal_allowed_use_detail": ["topic search discovery", "social discussion signal extraction"],
        "forbidden_use": ["verified_facts", "whole-network generalization", "single-topic conclusion", "publish-ready evidence"],
        "sample_signals": [],
        "error": "PermissionError('weibo topic search requires login or visitor verification')",
    }


def fake_zhihu_movie_hot_topics_success():
    return {
        "source_id": "zhihu_movie_hot_topics",
        "source_name": "知乎影视热议话题 live signal",
        "role": "P0_zhihu_movie_hot_topics",
        "signal_role": "social_discussion_signal",
        "narrative_roles": ["social_discussion", "audience_sentiment"],
        "allowed_use": ["movie hot-topic discovery", "question/argument signal"],
        "can_be_main_narrative_source": True,
        "fetch_path": "direct_live",
        "started_at": "2026-06-30T00:00:00+00:00",
        "finished_at": "2026-06-30T00:00:01+00:00",
        "duration_ms": 5,
        "success": True,
        "status": "focused_live_verified",
        "fields_extracted": ["title", "rank", "heat", "url", "excerpt"],
        "structured_signals": {
            "hot_topics": [{"title": "暑期档电影为什么讨论度这么高", "rank": 1, "heat": "热", "url": "https://www.zhihu.com/question/1", "excerpt": "围绕暑期档、票房和观众口碑。"}],
            "social_discussion": ["暑期档电影为什么讨论度这么高"],
        },
        "signal_allowed_use_detail": ["movie hot-topic discovery", "question/argument signal extraction"],
        "forbidden_use": ["verified_facts", "whole-network generalization", "single-topic conclusion", "publish-ready evidence"],
        "sample_signals": ["知乎热议：暑期档电影为什么讨论度这么高"],
        "error": None,
    }


def fake_bilibili_movie_zone_hot_success():
    return {
        "source_id": "bilibili_movie_zone_hot",
        "source_name": "B站电影分区热门 live signal",
        "role": "P0_bilibili_movie_zone_hot",
        "signal_role": "social_discussion_signal",
        "narrative_roles": ["hot_search", "social_discussion"],
        "allowed_use": ["movie-zone hot item discovery", "social discussion signal"],
        "can_be_main_narrative_source": True,
        "fetch_path": "direct_live",
        "started_at": "2026-06-30T00:00:00+00:00",
        "finished_at": "2026-06-30T00:00:01+00:00",
        "duration_ms": 5,
        "success": True,
        "status": "focused_live_verified",
        "fields_extracted": ["title", "rank", "heat", "danmaku", "like", "owner", "url"],
        "structured_signals": {
            "hot_items": [{"title": "电影解读视频冲上分区热门", "rank": 1, "heat": 120000, "danmaku": 2300, "like": 9000, "owner": "影迷UP", "url": "https://www.bilibili.com/video/BV1xx411c7mD"}],
            "social_discussion": ["电影解读视频冲上分区热门"],
        },
        "signal_allowed_use_detail": ["movie-zone hot item discovery", "social discussion signal extraction", "video engagement signal extraction"],
        "forbidden_use": ["verified_facts", "whole-network generalization", "single-video conclusion", "publish-ready evidence"],
        "sample_signals": ["B站电影区热门：电影解读视频冲上分区热门（播放=120000）"],
        "error": None,
    }


def fake_xiaohongshu_movie_notes_success():
    return {
        "source_id": "xiaohongshu_movie_notes",
        "source_name": "小红书影视笔记搜索 live signal",
        "role": "P1_xiaohongshu_movie_notes",
        "signal_role": "audience_reaction_signal",
        "narrative_roles": ["audience_sentiment", "social_discussion"],
        "allowed_use": ["movie note sentiment", "social discussion signal"],
        "can_be_main_narrative_source": True,
        "fetch_path": "direct_live",
        "started_at": "2026-06-30T00:00:00+00:00",
        "finished_at": "2026-06-30T00:00:01+00:00",
        "duration_ms": 5,
        "success": False,
        "status": "live_inaccessible",
        "fields_extracted": [],
        "signal_allowed_use_detail": ["movie note sentiment", "social discussion signal extraction"],
        "forbidden_use": ["verified_facts", "whole-network generalization", "single-note conclusion", "publish-ready evidence"],
        "sample_signals": [],
        "error": "PermissionError('xiaohongshu search requires login or signed request')",
    }


def fake_douyin_movie_hot_success():
    return {
        "source_id": "douyin_movie_hot",
        "source_name": "抖音电影热点 live signal",
        "role": "P1_douyin_movie_hot",
        "signal_role": "social_discussion_signal",
        "narrative_roles": ["hot_search", "social_discussion"],
        "allowed_use": ["short-video hot discovery", "social discussion signal"],
        "can_be_main_narrative_source": True,
        "fetch_path": "direct_live",
        "started_at": "2026-06-30T00:00:00+00:00",
        "finished_at": "2026-06-30T00:00:01+00:00",
        "duration_ms": 5,
        "success": True,
        "status": "focused_live_verified",
        "fields_extracted": ["title", "rank", "heat", "video_count", "url"],
        "structured_signals": {
            "hot_items": [{"title": "电影名场面在抖音二创爆了", "rank": 1, "heat": 320000, "video_count": 1200, "url": "https://www.douyin.com/search/%E7%94%B5%E5%BD%B1"}],
            "social_discussion": ["电影名场面在抖音二创爆了"],
        },
        "signal_allowed_use_detail": ["short-video hot discovery", "social discussion signal extraction", "video engagement signal extraction"],
        "forbidden_use": ["verified_facts", "whole-network generalization", "single-video conclusion", "publish-ready evidence"],
        "sample_signals": ["抖音电影热点：电影名场面在抖音二创爆了（热度=320000）"],
        "error": None,
    }


def fake_article_body_signal_fail():
    row = fake_article_body_signal_success()
    row.update({"success": False, "status": "ERROR", "error": "forced article body signal failure"})
    return row


def fake_audience_reaction_signal_fail():
    row = fake_audience_reaction_signal_success()
    row.update({"success": False, "status": "ERROR", "error": "forced audience reaction signal failure"})
    return row


def fake_weibo_entertainment_hotsearch_fail():
    row = fake_weibo_entertainment_hotsearch_success()
    row.update({"success": False, "status": "ERROR", "error": "forced weibo hotsearch failure", "fields_extracted": []})
    return row


def fake_zhihu_movie_hot_topics_fail():
    row = fake_zhihu_movie_hot_topics_success()
    row.update({"success": False, "status": "ERROR", "error": "forced zhihu failure", "fields_extracted": [], "sample_signals": []})
    return row


def fake_bilibili_movie_zone_hot_fail():
    row = fake_bilibili_movie_zone_hot_success()
    row.update({"success": False, "status": "ERROR", "error": "forced bilibili failure", "fields_extracted": [], "sample_signals": []})
    return row


def fake_xiaohongshu_movie_notes_fail():
    row = fake_xiaohongshu_movie_notes_success()
    row.update({"success": False, "status": "ERROR", "error": "forced xiaohongshu failure", "fields_extracted": [], "sample_signals": []})
    return row


def fake_douyin_movie_hot_fail():
    row = fake_douyin_movie_hot_success()
    row.update({"success": False, "status": "ERROR", "error": "forced douyin failure", "fields_extracted": [], "sample_signals": []})
    return row


def fake_maoyan_fail():
    return {
        "source_id": "maoyan_realtime_boxoffice",
        "source_name": "猫眼专业版实时票房",
        "role": "P0_market_data",
        "signal_role": "market_signal",
        "fetch_path": "direct_live",
        "started_at": "2026-06-30T00:00:00+00:00",
        "finished_at": "2026-06-30T00:00:01+00:00",
        "duration_ms": 10,
        "success": False,
        "raw_url": "https://piaofang.maoyan.com/dashboard-ajax/movie",
        "status": "ERROR",
        "fields_extracted": ["title"],
        "observation": {"extracted_items": []},
        "candidate": {},
        "error": "forced maoyan failure",
    }


def fake_guduo_fail():
    return {
        "source_id": "guduo",
        "source_name": "骨朵热度指数",
        "role": "P1_heat_rank",
        "signal_role": "heat_signal",
        "fetch_path": "direct_live",
        "started_at": "2026-06-30T00:00:00+00:00",
        "finished_at": "2026-06-30T00:00:01+00:00",
        "duration_ms": 12,
        "success": False,
        "raw_url_pattern": "http://d2.guduomedia.com/m/v3/billboard/list?type=DAILY&category={CATEGORY}&date={DATE}&platformId=",
        "status": "ERROR",
        "fields_extracted": ["rank"],
        "results": {},
        "error": {"NETWORK_DRAMA": "forced guduo failure"},
    }


def run_with_fakes(tmp_path, monkeypatch, maoyan_result=None, guduo_result=None, article_body_result=None, audience_result=None, weibo_result=None, weibo_topic_result=None, zhihu_result=None, bilibili_result=None, xiaohongshu_result=None, douyin_result=None, run_id="smoke"):
    mod = load_module()
    monkeypatch.setattr(mod, "fetch_maoyan", lambda: maoyan_result if maoyan_result is not None else fake_maoyan_success())
    monkeypatch.setattr(mod, "fetch_guduo", lambda rank_date=None: guduo_result if guduo_result is not None else fake_guduo_success())
    monkeypatch.setattr(mod, "fetch_article_body_signal", lambda: article_body_result if article_body_result is not None else fake_article_body_signal_success())
    monkeypatch.setattr(mod, "fetch_audience_reaction_signal", lambda: audience_result if audience_result is not None else fake_audience_reaction_signal_success())
    monkeypatch.setattr(mod, "fetch_weibo_entertainment_hotsearch_signal", lambda: weibo_result if weibo_result is not None else fake_weibo_entertainment_hotsearch_success())
    monkeypatch.setattr(mod, "fetch_weibo_topic_search_signal", lambda: weibo_topic_result if weibo_topic_result is not None else fake_weibo_topic_search_success())
    monkeypatch.setattr(mod, "fetch_zhihu_movie_hot_topics_signal", lambda: zhihu_result if zhihu_result is not None else fake_zhihu_movie_hot_topics_success())
    monkeypatch.setattr(mod, "fetch_bilibili_movie_zone_hot_signal", lambda: bilibili_result if bilibili_result is not None else fake_bilibili_movie_zone_hot_success())
    monkeypatch.setattr(mod, "fetch_xiaohongshu_movie_notes_signal", lambda: xiaohongshu_result if xiaohongshu_result is not None else fake_xiaohongshu_movie_notes_success())
    monkeypatch.setattr(mod, "fetch_douyin_movie_hot_signal", lambda: douyin_result if douyin_result is not None else fake_douyin_movie_hot_success())
    result = mod.run(tmp_path, run_id=run_id)
    out_dir = Path(result["output_dir"])
    return mod, result, out_dir


def load_outputs(out_dir):
    return {
        "article": (out_dir / "article.html").read_text(encoding="utf-8"),
        "sources": json.loads((out_dir / "sources.json").read_text(encoding="utf-8")),
        "audit": json.loads((out_dir / "fetch_audit.json").read_text(encoding="utf-8")),
        "summary": json.loads((out_dir / "run_summary.json").read_text(encoding="utf-8")),
        "verification": json.loads((out_dir / "verification.json").read_text(encoding="utf-8")),
    }


EXPECTED_SOURCE_POOL = {
    "maoyan_realtime_boxoffice",
    "guduo",
    "toutiao_deep_film_tv_articles",
    "douban_reviews_discussions",
    "weibo_entertainment_hotsearch",
    "weibo_topic_search",
    "zhihu_movie_hot_topics",
    "bilibili_movie_zone_hot",
    "xiaohongshu_movie_notes",
    "douyin_movie_hot",
}
EXPECTED_DEFAULT_SUCCESS = {
    "maoyan_realtime_boxoffice",
    "guduo",
    "toutiao_deep_film_tv_articles",
    "douban_reviews_discussions",
    "weibo_entertainment_hotsearch",
    "zhihu_movie_hot_topics",
    "bilibili_movie_zone_hot",
    "douyin_movie_hot",
}


def test_runner_import_version_and_source_pool_guard():
    mod = load_module()
    assert mod.RUNNER_VERSION == "0.3.4"
    assert set(mod.VERIFIED_SOURCE_POOL) == EXPECTED_SOURCE_POOL
    for source_id, spec in mod.VERIFIED_SOURCE_POOL.items():
        assert spec["source_id"] == source_id
        assert spec["signal_role"] in {"market_signal", "heat_signal", "article_body_signal", "audience_reaction_signal", "social_discussion_signal"}
        assert isinstance(spec["live_fetch_allowed"], bool)
        assert spec["production_eligible"] is True
    assert mod.VERIFIED_SOURCE_POOL["maoyan_realtime_boxoffice"]["signal_role"] == "market_signal"
    assert mod.VERIFIED_SOURCE_POOL["maoyan_realtime_boxoffice"]["allowed_use"] == ["candidate_discovery", "boxoffice_data_support"]
    assert mod.VERIFIED_SOURCE_POOL["maoyan_realtime_boxoffice"]["can_be_main_narrative_source"] is False
    assert mod.VERIFIED_SOURCE_POOL["guduo"]["signal_role"] == "heat_signal"
    assert mod.VERIFIED_SOURCE_POOL["guduo"]["allowed_use"] == ["heat_discovery", "heat_data_support"]
    assert mod.VERIFIED_SOURCE_POOL["guduo"]["can_be_main_narrative_source"] is False


def test_article_production_smoke_success_path(tmp_path, monkeypatch):
    _mod, result, out_dir = run_with_fakes(tmp_path, monkeypatch)
    outputs = load_outputs(out_dir)
    assert result["verification"]["status"] == "PASS"
    assert outputs["summary"]["article_count"] == 1
    assert outputs["summary"]["canonical_suite_green"] is False
    assert outputs["summary"]["article_lane"] == "self_media_production_candidate"
    assert outputs["summary"]["self_media_ready"] is True
    assert outputs["summary"]["missing_source_roles"] == []
    assert outputs["verification"]["verification_type"] == "focused_ad_hoc"
    assert outputs["verification"]["canonical_suite_green"] is False
    assert set(outputs["summary"]["sources_successful"]) == EXPECTED_DEFAULT_SUCCESS
    for name in ["article.html", "sources.json", "fetch_audit.json", "run_summary.json", "verification.json"]:
        assert (out_dir / name).exists(), name


def test_html_minimum_content_quality_assertions(tmp_path, monkeypatch):
    _mod, _result, out_dir = run_with_fakes(tmp_path, monkeypatch)
    outputs = load_outputs(out_dir)
    html = outputs["article"]
    verification = outputs["verification"]
    assert len(html.encode("utf-8")) > 2500
    assert "<title>" in html and "<h1>" in html
    assert "<strong>导语：</strong>" in html
    assert html.count("<section>") >= 4
    assert html.count("<p>") >= 6
    assert "结尾" in html
    for forbidden in ["TODO", "TBD", "{{", "}}", "lorem ipsum"]:
        assert forbidden.lower() not in html.lower()
    assert verification["checks"]["html_minimum_bytes"] is True
    assert verification["checks"]["html_no_obvious_placeholders"] is True


def test_output_schema_and_cross_file_consistency(tmp_path, monkeypatch):
    _mod, _result, out_dir = run_with_fakes(tmp_path, monkeypatch)
    outputs = load_outputs(out_dir)
    sources = outputs["sources"]
    audit = outputs["audit"]
    summary = outputs["summary"]
    verification = outputs["verification"]
    assert sources["article_file"] == "article.html"
    assert len(sources["sources"]) == len(audit["sources"])
    assert {s["source_id"] for s in sources["sources"]} == EXPECTED_SOURCE_POOL
    assert {s["signal_role"] for s in sources["sources"]} == {"market_signal", "heat_signal", "article_body_signal", "audience_reaction_signal", "social_discussion_signal"}
    assert set(summary["sources_successful"]) == {src["source_id"] for src in audit["sources"] if src["success"]}
    assert set(summary["sources_failed"]) == {src["source_id"] for src in audit["sources"] if not src["success"]}
    assert summary["article_count"] == 1
    assert verification["status"] == "PASS"
    assert verification["checks"]["sources_summary_audit_count_match"] is True
    assert verification["checks"]["summary_audit_success_sets_match"] is True


def test_source_skeleton_and_buckets_are_persisted_by_signal_role(tmp_path, monkeypatch):
    _mod, _result, out_dir = run_with_fakes(tmp_path, monkeypatch)
    outputs = load_outputs(out_dir)
    sources = outputs["sources"]
    audit = outputs["audit"]
    summary = outputs["summary"]
    skeleton = sources["source_skeleton"]
    buckets = sources["source_buckets"]

    assert audit["source_skeleton"] == skeleton
    assert audit["source_buckets"] == buckets
    assert len(skeleton) == len(audit["sources"])
    assert {entry["source_id"] for entry in skeleton} == EXPECTED_SOURCE_POOL
    assert {bucket for bucket, entries in buckets.items() if entries} == {
        "market_results",
        "heat_results",
        "article_body_results",
        "audience_reaction_results",
        "social_results",
    }
    assert summary["source_buckets"] == {
        bucket: [entry["source_id"] for entry in entries]
        for bucket, entries in buckets.items()
    }
    for entry in skeleton:
        assert {
            "source_id",
            "source_name",
            "role",
            "signal_role",
            "source_bucket",
            "narrative_roles",
            "allowed_use",
            "can_be_main_narrative_source",
            "fetch_path",
            "success",
            "status",
            "fields_extracted",
            "html_social_results_eligible",
        }.issubset(entry)
        assert entry["source_bucket"] in buckets
        assert entry["source_id"] in summary["source_buckets"][entry["source_bucket"]]


def test_social_results_bucket_is_exactly_html_social_discussion_signals(tmp_path, monkeypatch):
    _mod, _result, out_dir = run_with_fakes(tmp_path, monkeypatch)
    outputs = load_outputs(out_dir)
    social_bucket = outputs["sources"]["source_buckets"]["social_results"]
    audience_bucket = outputs["sources"]["source_buckets"]["audience_reaction_results"]

    assert {entry["source_id"] for entry in social_bucket} == {
        "weibo_entertainment_hotsearch",
        "weibo_topic_search",
        "zhihu_movie_hot_topics",
        "bilibili_movie_zone_hot",
        "douyin_movie_hot",
    }
    assert all(entry["signal_role"] == "social_discussion_signal" for entry in social_bucket)
    assert all(entry["html_social_results_eligible"] is True for entry in social_bucket)
    assert [entry["source_id"] for entry in audience_bucket] == ["douban_reviews_discussions", "xiaohongshu_movie_notes"]
    assert all(entry["signal_role"] == "audience_reaction_signal" for entry in audience_bucket)
    assert all(entry["html_social_results_eligible"] is False for entry in audience_bucket)
    assert "douyin_movie_hot" in outputs["summary"]["source_buckets"]["social_results"]
    assert "douban_reviews_discussions" not in outputs["summary"]["source_buckets"]["social_results"]
    assert "xiaohongshu_movie_notes" not in outputs["summary"]["source_buckets"]["social_results"]


def test_xiaohongshu_movie_notes_live_adapter_failure_is_safe(monkeypatch):
    mod = load_module()

    def fake_fetch_json(_url, **_kwargs):
        return {"code": -101, "success": False, "msg": "无登录信息，或登录信息为空", "data": {}}

    monkeypatch.setattr(mod, "_fetch_json_url", fake_fetch_json)
    result = mod.fetch_xiaohongshu_movie_notes_signal()
    assert result["source_id"] == "xiaohongshu_movie_notes"
    assert result["success"] is False
    assert result["status"] == "live_inaccessible"
    assert result["fetch_path"] == "direct_live"
    assert result["fields_extracted"] == []
    assert "登录" in result["error"] or "login" in result["error"].lower()
    assert "verified_facts" in result["forbidden_use"]


def test_douyin_movie_hot_live_adapter_failure_is_safe(monkeypatch):
    mod = load_module()

    def fake_fetch_json(_url, **_kwargs):
        return {"status_code": -1, "status_msg": "login required or signature verification failed", "data": {}}

    monkeypatch.setattr(mod, "_fetch_json_url", fake_fetch_json)
    result = mod.fetch_douyin_movie_hot_signal()
    assert result["source_id"] == "douyin_movie_hot"
    assert result["success"] is False
    assert result["status"] == "live_inaccessible"
    assert result["fetch_path"] == "direct_live"
    assert result["fields_extracted"] == []
    assert "login" in result["error"].lower() or "signature" in result["error"].lower()
    assert "verified_facts" in result["forbidden_use"]


def test_guduo_failure_maoyan_success_continues_and_audits_failure(tmp_path, monkeypatch):
    _mod, result, out_dir = run_with_fakes(tmp_path, monkeypatch, guduo_result=fake_guduo_fail(), run_id="guduo_fail")
    outputs = load_outputs(out_dir)
    assert result["verification"]["status"] == "PASS"
    assert outputs["summary"]["article_quality_gate"]["status"] == "PASS"
    assert set(outputs["summary"]["sources_successful"]) == EXPECTED_DEFAULT_SUCCESS - {"guduo"}
    assert set(outputs["summary"]["sources_failed"]) == {"guduo", "weibo_topic_search", "xiaohongshu_movie_notes"}
    failed = [src for src in outputs["audit"]["sources"] if src["source_id"] == "guduo"][0]
    assert failed["success"] is False
    assert failed["error"]
    assert (out_dir / "article.html").exists()


def test_maoyan_failure_guduo_success_continues_and_audits_failure(tmp_path, monkeypatch):
    _mod, result, out_dir = run_with_fakes(tmp_path, monkeypatch, maoyan_result=fake_maoyan_fail(), run_id="maoyan_fail")
    outputs = load_outputs(out_dir)
    assert result["verification"]["status"] == "PASS"
    assert outputs["summary"]["article_quality_gate"]["status"] == "PASS"
    assert set(outputs["summary"]["sources_successful"]) == EXPECTED_DEFAULT_SUCCESS - {"maoyan_realtime_boxoffice"}
    assert set(outputs["summary"]["sources_failed"]) == {"maoyan_realtime_boxoffice", "weibo_topic_search", "xiaohongshu_movie_notes"}
    failed = [src for src in outputs["audit"]["sources"] if src["source_id"] == "maoyan_realtime_boxoffice"][0]
    assert failed["success"] is False
    assert failed["error"]
    assert "长视频" in outputs["article"] or "骨朵" in outputs["article"]


def test_consecutive_runs_use_independent_output_dirs(tmp_path, monkeypatch):
    mod = load_module()
    monkeypatch.setattr(mod, "fetch_maoyan", fake_maoyan_success)
    monkeypatch.setattr(mod, "fetch_guduo", lambda rank_date=None: fake_guduo_success())
    monkeypatch.setattr(mod, "fetch_article_body_signal", fake_article_body_signal_success)
    monkeypatch.setattr(mod, "fetch_audience_reaction_signal", fake_audience_reaction_signal_success)
    monkeypatch.setattr(mod, "fetch_weibo_entertainment_hotsearch_signal", fake_weibo_entertainment_hotsearch_success)
    monkeypatch.setattr(mod, "fetch_weibo_topic_search_signal", fake_weibo_topic_search_success)
    monkeypatch.setattr(mod, "fetch_zhihu_movie_hot_topics_signal", fake_zhihu_movie_hot_topics_success)
    monkeypatch.setattr(mod, "fetch_bilibili_movie_zone_hot_signal", fake_bilibili_movie_zone_hot_success)
    monkeypatch.setattr(mod, "fetch_xiaohongshu_movie_notes_signal", fake_xiaohongshu_movie_notes_success)
    monkeypatch.setattr(mod, "fetch_douyin_movie_hot_signal", fake_douyin_movie_hot_success)
    dirs = []
    for index in range(3):
        result = mod.run(tmp_path, run_id=f"stable_{index}")
        assert result["verification"]["status"] == "PASS"
        dirs.append(Path(result["output_dir"]))
    assert len(set(dirs)) == 3
    for index, out_dir in enumerate(dirs):
        assert out_dir.name == f"stable_{index}"
        assert (out_dir / "article.html").exists()
        summary = json.loads((out_dir / "run_summary.json").read_text(encoding="utf-8"))
        assert summary["run_id"] == f"stable_{index}"


def test_observability_fields_present(tmp_path, monkeypatch):
    _mod, _result, out_dir = run_with_fakes(tmp_path, monkeypatch)
    outputs = load_outputs(out_dir)
    summary = outputs["summary"]
    audit = outputs["audit"]
    for field in ["run_id", "started_at", "finished_at", "duration_ms", "stage_status", "article_generation_duration_ms", "verification_duration_ms", "article_lane", "source_role_coverage", "missing_source_roles", "self_media_ready"]:
        assert field in summary
    assert summary["stage_status"] == {"fetch": "PASS", "generate": "PASS", "verify": "PASS"}
    for source in audit["sources"]:
        assert "duration_ms" in source
        assert "status" in source


def test_score_threshold_and_attribution_quality(tmp_path, monkeypatch):
    _mod, _result, out_dir = run_with_fakes(tmp_path, monkeypatch)
    outputs = load_outputs(out_dir)
    assert outputs["summary"]["selected_topic"]["score"] >= 80
    assert outputs["verification"]["checks"]["summary_score_meets_threshold"] is True
    assert outputs["verification"]["article_lane"] == "self_media_production_candidate"
    assert outputs["verification"]["self_media_ready"] is True
    assert outputs["verification"]["missing_source_roles"] == []
    html = outputs["article"]
    assert "Source Attribution / 使用来源" in html
    for source in outputs["sources"]["sources"]:
        assert source["source_id"] in EXPECTED_SOURCE_POOL
        if source["success"]:
            assert source["source_name"] in html
        else:
            assert source["source_name"] not in html




def test_full_role_coverage_moves_lane_to_self_media_candidate(tmp_path, monkeypatch):
    _mod, _result, out_dir = run_with_fakes(tmp_path, monkeypatch)
    verification = load_outputs(out_dir)["verification"]
    assert verification["article_lane"] == "self_media_production_candidate"
    assert verification["self_media_ready"] is True
    assert verification["missing_source_roles"] == []
    assert verification["canonical_suite_green"] is False
    successful_roles = set(verification["source_role_coverage"]["successful_roles"])
    assert successful_roles == {"market_signal", "heat_signal", "article_body_signal", "audience_reaction_signal", "social_discussion_signal"}
    assert verification["source_role_coverage"]["self_media_ready"] is True
    assert verification["checks"]["article_quality_gate_passed"] is True





def test_maoyan_guduo_only_is_data_observation_not_final_quality_acceptance(tmp_path, monkeypatch):
    _mod, result, out_dir = run_with_fakes(
        tmp_path,
        monkeypatch,
        article_body_result=fake_article_body_signal_fail(),
        audience_result=fake_audience_reaction_signal_fail(),
        weibo_result=fake_weibo_entertainment_hotsearch_fail(),
        zhihu_result=fake_zhihu_movie_hot_topics_fail(),
        bilibili_result=fake_bilibili_movie_zone_hot_fail(),
        douyin_result=fake_douyin_movie_hot_fail(),
        run_id="market_heat_only",
    )
    outputs = load_outputs(out_dir)
    assert outputs["summary"]["article_lane"] == "data_observation"
    assert outputs["summary"]["output_type"] == "data_observation_draft"
    assert outputs["summary"]["self_media_ready"] is False
    assert outputs["summary"]["article_quality_gate"]["status"] == "FAIL"
    assert outputs["summary"]["article_quality_gate"]["reason"] == "source_pool_insufficient"
    assert outputs["summary"]["article_quality_gate"]["quality_acceptance_standard"] == "smoke_only_not_final_article_quality"
    assert outputs["verification"]["status"] == "FAIL"
    assert outputs["verification"]["article_lane"] == "data_observation"
    assert outputs["verification"]["self_media_ready"] is False
    assert outputs["verification"]["missing_source_roles"]
    assert "影视自媒体爆款文章" not in outputs["article"]
    assert "数据观察稿" in outputs["article"]


def test_self_media_quality_gate_requires_two_narrative_roles(tmp_path, monkeypatch):
    _mod, _result, out_dir = run_with_fakes(tmp_path, monkeypatch)
    outputs = load_outputs(out_dir)
    gate = outputs["summary"]["article_quality_gate"]
    verification = outputs["verification"]
    assert gate["status"] == "PASS"
    assert gate["minimum_required_roles"] == 2
    assert set(gate["eligible_narrative_roles"]) == {
        "audience_sentiment",
        "social_discussion",
        "review_comments",
        "hot_search",
        "plot_character_context",
    }
    assert len(gate["present_narrative_roles"]) >= 2
    assert verification["checks"]["article_quality_gate_passed"] is True
    assert verification["article_lane"] == "self_media_production_candidate"





def test_requested_priority_source_registry_covers_p0_p1_p2_sources():
    mod = load_module()
    expected_p0 = {
        "douban_movie_reviews",
        "douban_tv_reviews",
        "weibo_entertainment_hotsearch",
        "weibo_topic_search",
        "zhihu_movie_hot_topics",
        "bilibili_movie_zone_hot",
    }
    expected_p1 = {
        "xiaohongshu_movie_notes",
        "douyin_movie_hot",
        "toutiao_entertainment_hot",
        "baidu_hot_search_entertainment",
    }
    expected_p2 = {
        "1905_movie_news",
        "mtime_movie_news",
        "sir_movie",
        "dumuzhi",
        "yulezibenlun",
        "yingshidushe",
    }
    registry = mod.PRIORITY_SOURCE_REGISTRY
    assert {k for k, v in registry.items() if v["priority"] == "P0"} == expected_p0
    assert {k for k, v in registry.items() if v["priority"] == "P1"} == expected_p1
    assert {k for k, v in registry.items() if v["priority"] == "P2"} == expected_p2
    for source_id, spec in registry.items():
        assert spec["source_id"] == source_id
        assert set(spec["narrative_roles"]).issubset(mod.SELF_MEDIA_NARRATIVE_SOURCE_ROLES)
        assert spec["allowed_use"]
        assert spec["production_boundary"]
        assert spec["status"] == "planned_not_live_verified"


def test_priority_source_registry_keeps_p0_first_and_aliases():
    mod = load_module()
    assert mod.PRIORITY_SOURCE_ORDER[:6] == [
        "douban_movie_reviews",
        "douban_tv_reviews",
        "weibo_entertainment_hotsearch",
        "weibo_topic_search",
        "zhihu_movie_hot_topics",
        "bilibili_movie_zone_hot",
    ]
    assert mod.PRIORITY_SOURCE_ALIASES["毒眸"] == "dumuzhi"
    assert mod.PRIORITY_SOURCE_ALIASES["娱乐资本论"] == "yulezibenlun"
    assert mod.PRIORITY_SOURCE_ALIASES["影视独舌"] == "yingshidushe"


def test_douban_audience_reaction_live_adapter_success(monkeypatch):
    mod = load_module()
    calls = []

    def fake_fetch_json(url):
        calls.append(url)
        if "j/search_subjects" in url:
            return {"subjects": [{"id": "36225840", "title": "超级少女", "rate": "5.5", "url": "https://movie.douban.com/subject/36225840/"}]}
        if "j/subject_abstract" in url:
            return {"subject": {"title": "超级少女 Supergirl", "rate": "5.5", "url": "https://movie.douban.com/subject/36225840/", "short_comment": {"content": "  观众短评认为故事主线薄弱，但讨论度很高。\n"}}}
        raise AssertionError(url)

    monkeypatch.setattr(mod, "_fetch_json_url", fake_fetch_json)
    result = mod.fetch_audience_reaction_signal()
    assert result["source_id"] == "douban_reviews_discussions"
    assert result["success"] is True
    assert result["status"] == "focused_live_verified"
    assert result["fetch_path"] == "direct_live"
    assert result["fields_extracted"] == ["subject_id", "title", "rate", "short_comment", "sentiment_keyword"]
    assert result["structured_signals"]["review_comments"] == ["观众短评认为故事主线薄弱，但讨论度很高。"]
    assert result["structured_signals"]["audience_emotion"] == "mixed_or_negative"
    assert "verified_facts" in result["forbidden_use"]
    assert len(calls) == 2


def test_douban_audience_reaction_live_adapter_failure_is_safe(monkeypatch):
    mod = load_module()

    def fake_fetch_json(_url):
        raise TimeoutError("forced douban timeout")

    monkeypatch.setattr(mod, "_fetch_json_url", fake_fetch_json)
    result = mod.fetch_audience_reaction_signal()
    assert result["source_id"] == "douban_reviews_discussions"
    assert result["success"] is False
    assert result["status"] == "ERROR"
    assert result["fetch_path"] == "direct_live"
    assert result["fields_extracted"] == []
    assert "forced douban timeout" in result["error"]
    assert result["narrative_roles"] == ["audience_sentiment", "review_comments", "social_discussion"]



def test_weibo_entertainment_hotsearch_live_adapter_success(monkeypatch):
    mod = load_module()

    def fake_fetch_json(url, **_kwargs):
        assert url == mod.WEIBO_HOTSEARCH_URL
        return {
            "ok": 1,
            "data": {
                "realtime": [
                    {"word": "金鹰奖最佳女主角候选", "realpos": 1, "num": 2128645, "flag_desc": "盛典", "topic_flag": 1},
                    {"word": "上海国际电影节", "realpos": 2, "num": 998877, "label_name": "热", "topic_flag": 1},
                ]
            },
        }

    monkeypatch.setattr(mod, "_fetch_json_url", fake_fetch_json)
    result = mod.fetch_weibo_entertainment_hotsearch_signal()
    assert result["source_id"] == "weibo_entertainment_hotsearch"
    assert result["success"] is True
    assert result["status"] == "focused_live_verified"
    assert result["fetch_path"] == "direct_live"
    assert result["signal_role"] == "social_discussion_signal"
    assert result["narrative_roles"] == ["hot_search", "social_discussion"]
    assert result["fields_extracted"] == ["word", "rank", "heat", "flag_desc", "topic_flag", "url"]
    assert result["structured_signals"]["hot_search"][0]["word"] == "金鹰奖最佳女主角候选"
    assert "verified_facts" in result["forbidden_use"]


def test_weibo_entertainment_hotsearch_live_adapter_failure_is_safe(monkeypatch):
    mod = load_module()

    def fake_fetch_json(_url, **_kwargs):
        raise TimeoutError("forced weibo timeout")

    monkeypatch.setattr(mod, "_fetch_json_url", fake_fetch_json)
    result = mod.fetch_weibo_entertainment_hotsearch_signal()
    assert result["source_id"] == "weibo_entertainment_hotsearch"
    assert result["success"] is False
    assert result["status"] == "ERROR"
    assert result["fetch_path"] == "direct_live"
    assert result["fields_extracted"] == []
    assert "forced weibo timeout" in result["error"]
    assert "verified_facts" in result["forbidden_use"]


def test_bilibili_same_work_enrichment_accepts_matching_bv_with_detail_text(monkeypatch):
    mod = load_module()
    anchor = {"subject_id": "36225840", "title": "超级少女 Supergirl", "url": "https://movie.douban.com/subject/36225840/"}

    def fake_fetch_json(url, **_kwargs):
        if "search/type" in url:
            assert "%E8%B6%85%E7%BA%A7%E5%B0%91%E5%A5%B3" in url
            return {"code": 0, "data": {"result": [{"title": "《超级少女》剧情解读", "bvid": "BV1xx411c7mD"}]}}
        if "web-interface/view" in url:
            assert "bvid=BV1xx411c7mD" in url
            return {"code": 0, "data": {"bvid": "BV1xx411c7mD", "title": "《超级少女》剧情解读", "desc": "这是一段超过二十字的具体剧情讨论文本，用于验证同作品讨论证据。", "stat": {"view": 120000, "danmaku": 2300, "like": 9000}}}
        raise AssertionError(url)

    monkeypatch.setattr(mod, "_fetch_json_url", fake_fetch_json)
    result = mod.fetch_bilibili_same_work_enrichment(anchor)
    assert result["source_id"] == "bilibili_work_detail"
    assert result["success"] is True
    assert result["signal_role"] == "social_discussion_signal"
    assert result["narrative_roles"] == ["social_discussion"]
    assert result["raw_url"] == "https://api.bilibili.com/x/web-interface/view?bvid=BV1xx411c7mD"
    assert result["structured_signals"]["social_discussion"][0]["url"] == "https://www.bilibili.com/video/BV1xx411c7mD"


def test_bilibili_same_work_enrichment_excludes_mismatch_missing_detail_or_video_url(monkeypatch):
    mod = load_module()
    anchor = {"subject_id": "36225840", "title": "超级少女", "url": "https://movie.douban.com/subject/36225840/"}

    def fake_fetch_json(url, **_kwargs):
        if "search/type" in url:
            return {"code": 0, "data": {"result": [
                {"title": "完全不相干的电影解读", "bvid": "BV1xx411c7mD"},
                {"title": "超级少女", "bvid": ""},
                {"title": "超级少女剧情解读", "bvid": "BV1yy411c7mD"},
            ]}}
        if "web-interface/view" in url:
            return {"code": 0, "data": {"bvid": "BV1yy411c7mD", "title": "超级少女剧情解读", "desc": "太短"}}
        raise AssertionError(url)

    monkeypatch.setattr(mod, "_fetch_json_url", fake_fetch_json)
    result = mod.fetch_bilibili_same_work_enrichment(anchor)
    assert result["success"] is False
    assert result["status"] == "ERROR"
    assert result["fields_extracted"] == []


def test_collect_live_backfill_rows_exports_douban_and_same_work_bilibili_rows(monkeypatch):
    mod = load_module()
    douban = fake_audience_reaction_signal_success() | {
        "live_subject": {"subject_id": "36225840", "title": "超级少女", "url": "https://movie.douban.com/subject/36225840/"},
        "sample_signals": ["《超级少女》短评样本显示：观众围绕人物动机展开讨论。"],
    }
    bilibili = {
        "source_id": "bilibili_work_detail", "source_name": "B站同作品视频详情 live signal", "role": "P1C_bilibili_same_work_discussion",
        "signal_role": "social_discussion_signal", "narrative_roles": ["social_discussion"], "allowed_use": ["same-work social discussion signal"],
        "can_be_main_narrative_source": True, "fetch_path": "direct_live_same_work", "success": True, "status": "focused_live_verified",
        "raw_url": "https://api.bilibili.com/x/web-interface/view?bvid=BV1xx411c7mD", "fields_extracted": ["bvid", "title", "desc", "url"],
        "top_signals": [{"title": "超级少女剧情解读", "description": "这是一段超过二十字的具体剧情讨论文本，用于验证同作品讨论证据。", "url": "https://www.bilibili.com/video/BV1xx411c7mD"}],
        "structured_signals": {"social_discussion": [{"title": "超级少女剧情解读", "description": "这是一段超过二十字的具体剧情讨论文本，用于验证同作品讨论证据。", "url": "https://www.bilibili.com/video/BV1xx411c7mD"}]},
        "sample_signals": ["B站同作品讨论《超级少女》：这是一段超过二十字的具体剧情讨论文本，用于验证同作品讨论证据。"], "error": None,
    }
    failed = lambda: {"success": False, "source_id": "ignored", "status": "ERROR"}
    monkeypatch.setattr(mod, "fetch_article_body_signal", failed)
    monkeypatch.setattr(mod, "fetch_audience_reaction_signal", lambda: douban)
    monkeypatch.setattr(mod, "fetch_bilibili_same_work_enrichment", lambda _anchor: bilibili)
    monkeypatch.setattr(mod, "fetch_weibo_entertainment_hotsearch_signal", failed)
    monkeypatch.setattr(mod, "fetch_weibo_topic_search_signal", failed)
    monkeypatch.setattr(mod, "fetch_zhihu_movie_hot_topics_signal", failed)
    monkeypatch.setattr(mod, "fetch_bilibili_movie_zone_hot_signal", failed)
    monkeypatch.setattr(mod, "fetch_xiaohongshu_movie_notes_signal", failed)
    monkeypatch.setattr(mod, "fetch_douyin_movie_hot_signal", failed)

    rows = mod.collect_live_backfill_rows(query="超级少女")
    assert [row["source"] for row in rows] == ["douban_reviews_discussions", "bilibili_work_detail"]
    assert rows[1]["url"] == "https://www.bilibili.com/video/BV1xx411c7mD"


def test_bilibili_movie_zone_hot_live_adapter_success(monkeypatch):
    mod = load_module()

    def fake_fetch_json(url, **kwargs):
        assert url == mod.BILIBILI_MOVIE_ZONE_HOT_URL
        assert kwargs["headers"]["Referer"] == "https://www.bilibili.com/v/movie/"
        return {
            "code": 0,
            "data": {
                "list": [
                    {
                        "title": "电影解读视频冲上分区热门",
                        "bvid": "BV1xx411c7mD",
                        "owner": {"name": "影迷UP"},
                        "stat": {"view": 120000, "danmaku": 2300, "like": 9000},
                    },
                    {
                        "title": "暑期档新片讨论",
                        "bvid": "BV1yy411c7mD",
                        "owner": {"name": "电影观察"},
                        "stat": {"view": 88000, "danmaku": 1200, "like": 5600},
                    },
                ]
            },
        }

    monkeypatch.setattr(mod, "_fetch_json_url", fake_fetch_json)
    result = mod.fetch_bilibili_movie_zone_hot_signal()
    assert result["source_id"] == "bilibili_movie_zone_hot"
    assert result["success"] is True
    assert result["status"] == "focused_live_verified"
    assert result["fetch_path"] == "direct_live"
    assert result["signal_role"] == "social_discussion_signal"
    assert result["narrative_roles"] == ["hot_search", "social_discussion"]
    assert result["fields_extracted"] == ["title", "rank", "heat", "danmaku", "like", "owner", "url"]
    assert result["structured_signals"]["hot_items"][0]["title"] == "电影解读视频冲上分区热门"
    assert result["structured_signals"]["hot_items"][0]["url"] == "https://www.bilibili.com/video/BV1xx411c7mD"
    assert "verified_facts" in result["forbidden_use"]


def test_bilibili_movie_zone_hot_live_adapter_failure_is_safe(monkeypatch):
    mod = load_module()

    def fake_fetch_json(_url, **_kwargs):
        return {"code": -352, "message": "risk control"}

    monkeypatch.setattr(mod, "_fetch_json_url", fake_fetch_json)
    result = mod.fetch_bilibili_movie_zone_hot_signal()
    assert result["source_id"] == "bilibili_movie_zone_hot"
    assert result["success"] is False
    assert result["status"] == "live_inaccessible"
    assert result["fetch_path"] == "direct_live"
    assert result["fields_extracted"] == []
    assert "risk control" in result["error"]
    assert "verified_facts" in result["forbidden_use"]


def test_letterboxd_same_work_context_accepts_matching_film_page(monkeypatch):
    mod = load_module()
    anchor = {"subject_id": "123", "title": "痴迷 Obsession‎ (2025)", "url": "https://movie.douban.com/subject/123/"}
    page_url = "https://letterboxd.com/film/obsession-2025/"
    page_html = """<html><head>
      <link rel=\"canonical\" href=\"https://letterboxd.com/film/obsession-2025/\">
      <meta name=\"description\" content=\"A detailed plot description with enough concrete character and story context for conservative same-work evidence.\">
      <title>Obsession (2025) • Film</title></head></html>"""
    monkeypatch.setattr(mod, "_fetch_html_url", lambda url, **_kwargs: {"url": page_url, "html": page_html})

    result = mod.fetch_letterboxd_same_work_context(anchor)

    assert result["success"] is True
    assert result["source_id"] == "letterboxd_work_context"
    assert result["signal_role"] == "article_body_signal"
    assert result["narrative_roles"] == ["plot_character_context"]
    assert result["top_signals"][0]["url"] == page_url
    assert result["top_signals"][0]["description"].startswith("A detailed plot")


def test_letterboxd_same_work_context_rejects_mismatch_missing_year_and_short_description(monkeypatch):
    mod = load_module()
    anchor = {"subject_id": "123", "title": "痴迷 Obsession‎ (2025)", "url": "https://movie.douban.com/subject/123/"}
    page_url = "https://letterboxd.com/film/obsession-2025/"
    cases = [
        "<link rel=\"canonical\" href=\"https://letterboxd.com/film/other-2025/\"><meta name=\"description\" content=\"A detailed plot description that is long enough to be considered context evidence.\"><title>Other (2025)</title>",
        "<link rel=\"canonical\" href=\"https://letterboxd.com/film/obsession/\"><meta name=\"description\" content=\"A detailed plot description that is long enough to be considered context evidence.\"><title>Obsession</title>",
        "<link rel=\"canonical\" href=\"https://letterboxd.com/film/obsession-2025/\"><meta name=\"description\" content=\"Too short\"><title>Obsession (2025)</title>",
    ]
    for page_html in cases:
        monkeypatch.setattr(mod, "_fetch_html_url", lambda url, html=page_html, **_kwargs: {"url": page_url, "html": html})
        result = mod.fetch_letterboxd_same_work_context(anchor)
        assert result["success"] is False
        assert result["fields_extracted"] == []


def test_collect_live_backfill_rows_uses_letterboxd_when_bilibili_same_work_fails(monkeypatch):
    mod = load_module()
    douban = fake_audience_reaction_signal_success() | {
        "live_subject": {"subject_id": "123", "title": "痴迷 Obsession‎ (2025)", "url": "https://movie.douban.com/subject/123/"},
        "sample_signals": ["《痴迷》短评样本显示：观众围绕人物动机展开讨论。"],
    }
    bilibili_failed = {"source_id": "bilibili_work_detail", "success": False, "status": "live_inaccessible"}
    letterboxd = {
        "source_id": "letterboxd_work_context", "source_name": "Letterboxd同作品页面剧情上下文", "role": "P1C_letterboxd_same_work_context",
        "signal_role": "article_body_signal", "narrative_roles": ["plot_character_context"], "success": True, "status": "focused_live_verified",
        "top_signals": [{"title": "Obsession (2025)", "description": "A detailed plot description with enough concrete character and story context for conservative same-work evidence.", "url": "https://letterboxd.com/film/obsession-2025/"}],
    }
    failed = lambda: {"success": False, "source_id": "ignored", "status": "ERROR"}
    monkeypatch.setattr(mod, "fetch_article_body_signal", failed)
    monkeypatch.setattr(mod, "fetch_audience_reaction_signal", lambda: douban)
    monkeypatch.setattr(mod, "fetch_bilibili_same_work_enrichment", lambda _anchor: bilibili_failed)
    monkeypatch.setattr(mod, "fetch_letterboxd_same_work_context", lambda _anchor: letterboxd)
    monkeypatch.setattr(mod, "fetch_weibo_entertainment_hotsearch_signal", failed)
    monkeypatch.setattr(mod, "fetch_weibo_topic_search_signal", failed)
    monkeypatch.setattr(mod, "fetch_zhihu_movie_hot_topics_signal", failed)
    monkeypatch.setattr(mod, "fetch_bilibili_movie_zone_hot_signal", failed)
    monkeypatch.setattr(mod, "fetch_xiaohongshu_movie_notes_signal", failed)
    monkeypatch.setattr(mod, "fetch_douyin_movie_hot_signal", failed)

    rows = mod.collect_live_backfill_rows(query="痴迷")

    assert [row["source"] for row in rows] == ["douban_reviews_discussions", "letterboxd_work_context"]
    assert rows[1]["url"] == "https://letterboxd.com/film/obsession-2025/"


def test_douban_audience_reaction_signals_uses_configurable_limit_above_three_without_duplicate_subjects_or_blocking(monkeypatch):
    mod = load_module()
    abstract_calls = []

    def fake_fetch_json(url, **_kwargs):
        if "j/search_subjects" in url:
            return {"subjects": [
                {"id": "101", "title": "作品一", "rate": "8.0", "url": "https://movie.douban.com/subject/101/"},
                {"id": "101", "title": "作品一重复", "rate": "8.0", "url": "https://movie.douban.com/subject/101/"},
                {"id": "102", "title": "作品二", "rate": "7.0", "url": "https://movie.douban.com/subject/102/"},
                {"id": "103", "title": "作品三", "rate": "6.0", "url": "https://movie.douban.com/subject/103/"},
                {"id": "104", "title": "作品四", "rate": "6.0", "url": "https://movie.douban.com/subject/104/"},
                {"id": "105", "title": "作品五", "rate": "6.0", "url": "https://movie.douban.com/subject/105/"},
            ]}
        subject_id = url.split("subject_id=", 1)[1]
        abstract_calls.append(subject_id)
        if subject_id == "102":
            raise TimeoutError("subject two failed")
        return {"subject": {"title": f"作品{subject_id}", "rate": "8.0", "url": f"https://movie.douban.com/subject/{subject_id}/", "short_comment": {"content": f"作品{subject_id} 的具体观众讨论。"}}}

    monkeypatch.setattr(mod, "_fetch_json_url", fake_fetch_json)
    results = mod.fetch_audience_reaction_signals(subject_limit=5)

    assert [result["live_subject"]["subject_id"] for result in results if result["success"]] == ["101", "103", "104", "105"]
    assert [result["live_subject"]["subject_id"] for result in results if not result["success"]] == ["102"]
    assert abstract_calls == ["101", "102", "103", "104", "105"]


def test_collect_live_backfill_rows_passes_explicit_subject_limit_and_preserves_work_keys(monkeypatch):
    mod = load_module()
    requested_limits = []
    subjects = [
        {"subject_id": str(subject_id), "title": f"作品{subject_id} Work {subject_id} (2026)", "url": f"https://movie.douban.com/subject/{subject_id}/"}
        for subject_id in range(101, 106)
    ]
    douban_results = [
        fake_audience_reaction_signal_success() | {"live_subject": subject, "sample_signals": [f"《{subject['title']}》短评：具体讨论。"]}
        for subject in subjects
    ]
    failed = lambda: {"success": False, "source_id": "ignored", "status": "ERROR"}

    def audience(subject_limit):
        requested_limits.append(subject_limit)
        return douban_results

    monkeypatch.setattr(mod, "fetch_audience_reaction_signals", audience)
    monkeypatch.setattr(mod, "fetch_bilibili_same_work_enrichment", lambda anchor: {"source_id": "bilibili_work_detail", "source_name": "B站同作品", "signal_role": "social_discussion_signal", "narrative_roles": ["social_discussion"], "success": True, "status": "focused_live_verified", "live_subject": anchor, "top_signals": [{"title": anchor["title"], "description": "具体同作品讨论证据。", "url": f"https://b.example/{anchor['subject_id']}"}]})
    for name in ("fetch_article_body_signal", "fetch_weibo_entertainment_hotsearch_signal", "fetch_weibo_topic_search_signal", "fetch_zhihu_movie_hot_topics_signal", "fetch_bilibili_movie_zone_hot_signal", "fetch_xiaohongshu_movie_notes_signal", "fetch_douyin_movie_hot_signal"):
        monkeypatch.setattr(mod, name, failed)

    rows = mod.collect_live_backfill_rows(query="作品", subject_limit=5)

    assert requested_limits == [5]
    assert {row["work_key"] for row in rows} == {f"douban:{subject_id}" for subject_id in range(101, 106)}


def test_collect_live_backfill_rows_enriches_each_top_three_work_and_uses_letterboxd_only_for_bilibili_failure(monkeypatch):
    mod = load_module()
    subjects = [
        {"subject_id": "101", "title": "作品一 Work One (2026)", "url": "https://movie.douban.com/subject/101/"},
        {"subject_id": "102", "title": "作品二 Work Two (2026)", "url": "https://movie.douban.com/subject/102/"},
        {"subject_id": "103", "title": "作品三 Work Three (2026)", "url": "https://movie.douban.com/subject/103/"},
    ]
    douban_results = [
        fake_audience_reaction_signal_success() | {"live_subject": subject, "sample_signals": [f"《{subject['title']}》短评：具体讨论。"]}
        for subject in subjects
    ]
    bilibili_calls = []
    letterboxd_calls = []
    failed = lambda: {"success": False, "source_id": "ignored", "status": "ERROR"}

    def bilibili(anchor):
        bilibili_calls.append(anchor["subject_id"])
        if anchor["subject_id"] == "102":
            return {"source_id": "bilibili_work_detail", "success": False, "status": "ERROR"}
        return {"source_id": "bilibili_work_detail", "source_name": "B站同作品", "signal_role": "social_discussion_signal", "narrative_roles": ["social_discussion"], "success": True, "status": "focused_live_verified", "live_subject": anchor, "top_signals": [{"title": anchor["title"], "description": "具体同作品讨论证据。", "url": f"https://b.example/{anchor['subject_id']}"}]}

    def letterboxd(anchor):
        letterboxd_calls.append(anchor["subject_id"])
        return {"source_id": "letterboxd_work_context", "source_name": "Letterboxd同作品", "signal_role": "article_body_signal", "narrative_roles": ["plot_character_context"], "success": True, "status": "focused_live_verified", "live_subject": anchor, "top_signals": [{"title": anchor["title"], "description": "具体同作品剧情上下文证据。", "url": f"https://l.example/{anchor['subject_id']}"}]}

    monkeypatch.setattr(mod, "fetch_audience_reaction_signals", lambda subject_limit=mod.DOUBAN_LIVE_SUBJECT_LIMIT: douban_results)
    monkeypatch.setattr(mod, "fetch_bilibili_same_work_enrichment", bilibili)
    monkeypatch.setattr(mod, "fetch_letterboxd_same_work_context", letterboxd)
    for name in ("fetch_article_body_signal", "fetch_weibo_entertainment_hotsearch_signal", "fetch_weibo_topic_search_signal", "fetch_zhihu_movie_hot_topics_signal", "fetch_bilibili_movie_zone_hot_signal", "fetch_xiaohongshu_movie_notes_signal", "fetch_douyin_movie_hot_signal"):
        monkeypatch.setattr(mod, name, failed)

    rows = mod.collect_live_backfill_rows(query="作品")

    assert bilibili_calls == ["101", "102", "103"]
    assert letterboxd_calls == ["102"]
    assert {row["work_key"] for row in rows} == {"douban:101", "douban:102", "douban:103"}
    assert {row["live_subject"]["subject_id"] for row in rows} == {"101", "102", "103"}
    assert {row["source"] for row in rows if row["work_key"] == "douban:102"} == {"douban_reviews_discussions", "letterboxd_work_context"}


def test_bilibili_same_work_enrichment_rejects_same_title_different_year(monkeypatch):
    mod = load_module()
    anchor = {"subject_id": "2026", "title": "苦涩的圣诞节 Amarga Navidad (2026)", "url": "https://movie.douban.com/subject/2026/"}

    def fake_fetch_json(url, **_kwargs):
        if "search/type" in url:
            return {"code": 0, "data": {"result": [{"title": "苦涩的圣诞节 (2025) 解析", "bvid": "BVwrong"}]}}
        raise AssertionError("wrong-year candidate must not fetch detail: " + url)

    monkeypatch.setattr(mod, "_fetch_json_url", fake_fetch_json)
    result = mod.fetch_bilibili_same_work_enrichment(anchor)

    assert result["success"] is False
    assert result["failure_reason"] == "same_work_year_mismatch"
    assert result["fields_extracted"] == []


def test_bilibili_same_work_enrichment_checks_multiple_candidates_and_accepts_matching_year(monkeypatch):
    mod = load_module()
    anchor = {"subject_id": "2026", "title": "苦涩的圣诞节 Amarga Navidad (2026)", "url": "https://movie.douban.com/subject/2026/"}
    detail_calls = []

    def fake_fetch_json(url, **_kwargs):
        if "search/type" in url:
            assert "%E8%8B%A6%E6%B6%A9%E7%9A%84%E5%9C%A3%E8%AF%9E%E8%8A%82" in url
            assert "Amarga+Navidad" in url and "2026" in url
            return {"code": 0, "data": {"result": [
                {"title": "苦涩的圣诞节 Amarga Navidad 剧情解读 (2025)", "bvid": "BVwrong"},
                {"title": "苦涩的圣诞节 Amarga Navidad 剧情解读 (2026)", "bvid": "BVright"},
            ]}}
        if "web-interface/view" in url:
            detail_calls.append(url)
            return {"code": 0, "data": {"bvid": "BVright", "title": "苦涩的圣诞节 Amarga Navidad (2026) 剧情解读", "desc": "这是一段超过二十字的具体剧情讨论文本，用于验证同年同作品讨论证据。", "stat": {"view": 12}}}
        raise AssertionError(url)

    monkeypatch.setattr(mod, "_fetch_json_url", fake_fetch_json)
    result = mod.fetch_bilibili_same_work_enrichment(anchor)

    assert result["success"] is True
    assert result["top_signals"][0]["bvid"] == "BVright"
    assert len(detail_calls) == 1


def test_collect_year_mismatch_uses_letterboxd_and_exports_no_wrong_year_bilibili(monkeypatch):
    mod = load_module()
    anchor = {"subject_id": "2026", "title": "苦涩的圣诞节 Amarga Navidad (2026)", "url": "https://movie.douban.com/subject/2026/"}
    douban = fake_audience_reaction_signal_success() | {"live_subject": anchor, "sample_signals": ["《苦涩的圣诞节》短评：具体讨论。"]}
    letterboxd = {"source_id": "letterboxd_work_context", "source_name": "Letterboxd同作品", "signal_role": "article_body_signal", "narrative_roles": ["plot_character_context"], "success": True, "status": "focused_live_verified", "live_subject": anchor, "top_signals": [{"title": "Amarga Navidad (2026)", "description": "A detailed plot description with enough concrete character and story context for conservative evidence.", "url": "https://letterboxd.com/film/amarga-navidad-2026/"}]}
    failed = lambda: {"success": False, "source_id": "ignored", "status": "ERROR"}
    monkeypatch.setattr(mod, "fetch_audience_reaction_signals", lambda subject_limit=mod.DOUBAN_LIVE_SUBJECT_LIMIT: [douban])
    monkeypatch.setattr(mod, "fetch_bilibili_same_work_enrichment", lambda _anchor: {"source_id": "bilibili_work_detail", "success": False, "status": "ERROR", "failure_reason": "same_work_year_mismatch"})
    monkeypatch.setattr(mod, "fetch_letterboxd_same_work_context", lambda _anchor: letterboxd)
    for name in ("fetch_article_body_signal", "fetch_weibo_entertainment_hotsearch_signal", "fetch_weibo_topic_search_signal", "fetch_zhihu_movie_hot_topics_signal", "fetch_bilibili_movie_zone_hot_signal", "fetch_xiaohongshu_movie_notes_signal", "fetch_douyin_movie_hot_signal"):
        monkeypatch.setattr(mod, name, failed)

    rows = mod.collect_live_backfill_rows(query="苦涩的圣诞节")
    assert [row["source"] for row in rows] == ["douban_reviews_discussions", "letterboxd_work_context"]


def test_collect_does_not_attempt_letterboxd_for_anchor_without_english_title(monkeypatch):
    mod = load_module()
    anchor = {"subject_id": "forest", "title": "森中有林 (2026)", "url": "https://movie.douban.com/subject/forest/"}
    douban = fake_audience_reaction_signal_success() | {"live_subject": anchor, "sample_signals": ["《森中有林》短评：具体讨论。"]}
    failed = lambda: {"success": False, "source_id": "ignored", "status": "ERROR"}
    letterboxd_calls = []
    monkeypatch.setattr(mod, "fetch_audience_reaction_signals", lambda subject_limit=mod.DOUBAN_LIVE_SUBJECT_LIMIT: [douban])
    monkeypatch.setattr(mod, "fetch_bilibili_same_work_enrichment", lambda _anchor: {"source_id": "bilibili_work_detail", "success": False, "status": "ERROR"})
    monkeypatch.setattr(mod, "fetch_letterboxd_same_work_context", lambda candidate: letterboxd_calls.append(candidate) or {"success": True})
    for name in ("fetch_article_body_signal", "fetch_weibo_entertainment_hotsearch_signal", "fetch_weibo_topic_search_signal", "fetch_zhihu_movie_hot_topics_signal", "fetch_bilibili_movie_zone_hot_signal", "fetch_xiaohongshu_movie_notes_signal", "fetch_douyin_movie_hot_signal"):
        monkeypatch.setattr(mod, name, failed)

    rows = mod.collect_live_backfill_rows(query="森中有林")
    assert [row["source"] for row in rows] == ["douban_reviews_discussions"]
    assert letterboxd_calls == []


def test_1905_same_work_context_accepts_explicit_mapping_with_all_identity_anchors(monkeypatch):
    mod = load_module()
    anchor = {"subject_id": "36372941", "title": "森中有林 (2026)", "url": "https://movie.douban.com/subject/36372941/"}
    page_url = "https://www.1905.com/mdb/film/2258502/"
    page_html = """<html><head><link rel=\"canonical\" href=\"https://www.1905.com/mdb/film/2258502/\"></head>
    <body><h1>森中有林 All The Good Eyes (2026)</h1><p>剧情：于和伟饰演的角色在森林深处卷入一段关系与选择，这是一段足够具体的人物和作品剧情上下文。</p></body></html>"""
    monkeypatch.setattr(mod, "_fetch_html_url", lambda url, **_kwargs: {"url": page_url, "html": page_html})

    result = mod.fetch_1905_same_work_context(anchor)

    assert result["success"] is True
    assert result["source_id"] == "1905_same_work_context"
    assert result["signal_role"] == "article_body_signal"
    assert result["narrative_roles"] == ["plot_character_context"]
    assert result["top_signals"][0]["url"] == page_url
    assert result["live_subject"] == anchor


def test_1905_same_work_context_rejects_mapping_mismatch_and_missing_identity_or_context(monkeypatch):
    mod = load_module()
    mapped_anchor = {"subject_id": "36372941", "title": "森中有林 (2026)", "url": "https://movie.douban.com/subject/36372941/"}
    page_url = "https://www.1905.com/mdb/film/2258502/"
    bad_pages = [
        {"url": "https://www.1905.com/mdb/film/other", "html": "森中有林 All The Good Eyes 2026 于和伟 这是一段足够长的剧情上下文。"},
        {"url": page_url, "html": "<link rel=\"canonical\" href=\"https://www.1905.com/mdb/film/2258502/\">森中有林 All The Good Eyes 2026 这是一段足够长的剧情上下文。"},
        {"url": page_url, "html": "<link rel=\"canonical\" href=\"https://www.1905.com/mdb/film/2258502/\">森中有林 All The Good Eyes 2026 于和伟 太短"},
    ]
    for fetched in bad_pages:
        monkeypatch.setattr(mod, "_fetch_html_url", lambda _url, item=fetched, **_kwargs: item)
        result = mod.fetch_1905_same_work_context(mapped_anchor)
        assert result["success"] is False
        assert result["fields_extracted"] == []
        assert "live_subject" not in result

    unmapped = mod.fetch_1905_same_work_context({"subject_id": "not-mapped", "title": "森中有林 (2026)", "url": "https://movie.douban.com/subject/not-mapped/"})
    assert unmapped["success"] is False
    assert unmapped["raw_url"] is None


def test_collect_uses_1905_for_mapped_forest_work_and_batch_is_strict_ready(monkeypatch, tmp_path):
    mod = load_module()
    batch_spec = importlib.util.spec_from_file_location("article_candidate_batch_1905", ROOT / "scripts" / "run_experimental_article_candidate_batch.py")
    assert batch_spec is not None and batch_spec.loader is not None
    batch = importlib.util.module_from_spec(batch_spec)
    batch_spec.loader.exec_module(batch)
    anchor = {"subject_id": "36372941", "title": "森中有林 (2026)", "url": "https://movie.douban.com/subject/36372941/"}
    douban = fake_audience_reaction_signal_success() | {"live_subject": anchor, "top_signals": [{"title": "《森中有林》短评", "description": "观众围绕人物选择与森林意象出现持续、具体的讨论和分歧。", "url": "https://movie.douban.com/subject/36372941/comments"}]}
    same_work = {"source_id": "1905_same_work_context", "source_name": "1905同作品页面剧情上下文", "role": "P1C_1905_same_work_context", "signal_role": "article_body_signal", "narrative_roles": ["plot_character_context"], "success": True, "status": "focused_live_verified", "live_subject": anchor, "top_signals": [{"title": "森中有林 All The Good Eyes (2026)", "description": "于和伟饰演的角色在森林深处卷入一段关系与选择，这是一段足够具体的人物和作品剧情上下文。", "url": "https://www.1905.com/mdb/film/2258502"}]}
    failed = lambda: {"success": False, "source_id": "ignored", "status": "ERROR"}
    monkeypatch.setattr(mod, "fetch_audience_reaction_signals", lambda subject_limit=mod.DOUBAN_LIVE_SUBJECT_LIMIT: [douban])
    monkeypatch.setattr(mod, "fetch_bilibili_same_work_enrichment", lambda _anchor: {"source_id": "bilibili_work_detail", "success": False, "status": "ERROR"})
    monkeypatch.setattr(mod, "fetch_1905_same_work_context", lambda _anchor: same_work)
    monkeypatch.setattr(mod, "fetch_letterboxd_same_work_context", lambda _anchor: (_ for _ in ()).throw(AssertionError("no English anchor means no Letterboxd request")))
    for name in ("fetch_article_body_signal", "fetch_weibo_entertainment_hotsearch_signal", "fetch_weibo_topic_search_signal", "fetch_zhihu_movie_hot_topics_signal", "fetch_bilibili_movie_zone_hot_signal", "fetch_xiaohongshu_movie_notes_signal", "fetch_douyin_movie_hot_signal"):
        monkeypatch.setattr(mod, name, failed)

    rows = mod.collect_live_backfill_rows(query="森中有林")
    assert [row["source"] for row in rows] == ["douban_reviews_discussions", "1905_same_work_context"]
    assert {row["work_key"] for row in rows} == {"douban:36372941"}
    result = batch.run_batch(tmp_path / "forest-1905.json", live_rows=rows, use_live_evidence=True)
    assert result["publish_ready"] is True
    assert result["article_candidate_buckets"]["A"][0]["work_key"] == "douban:36372941"
