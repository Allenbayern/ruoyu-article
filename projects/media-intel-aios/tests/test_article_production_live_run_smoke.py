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


def run_with_fakes(tmp_path, monkeypatch, maoyan_result=None, guduo_result=None, article_body_result=None, audience_result=None, weibo_result=None, weibo_topic_result=None, zhihu_result=None, run_id="smoke"):
    mod = load_module()
    monkeypatch.setattr(mod, "fetch_maoyan", lambda: maoyan_result if maoyan_result is not None else fake_maoyan_success())
    monkeypatch.setattr(mod, "fetch_guduo", lambda rank_date=None: guduo_result if guduo_result is not None else fake_guduo_success())
    monkeypatch.setattr(mod, "fetch_article_body_signal", lambda: article_body_result if article_body_result is not None else fake_article_body_signal_success())
    monkeypatch.setattr(mod, "fetch_audience_reaction_signal", lambda: audience_result if audience_result is not None else fake_audience_reaction_signal_success())
    monkeypatch.setattr(mod, "fetch_weibo_entertainment_hotsearch_signal", lambda: weibo_result if weibo_result is not None else fake_weibo_entertainment_hotsearch_success())
    monkeypatch.setattr(mod, "fetch_weibo_topic_search_signal", lambda: weibo_topic_result if weibo_topic_result is not None else fake_weibo_topic_search_success())
    monkeypatch.setattr(mod, "fetch_zhihu_movie_hot_topics_signal", lambda: zhihu_result if zhihu_result is not None else fake_zhihu_movie_hot_topics_success())
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
}
EXPECTED_DEFAULT_SUCCESS = {
    "maoyan_realtime_boxoffice",
    "guduo",
    "toutiao_deep_film_tv_articles",
    "douban_reviews_discussions",
    "weibo_entertainment_hotsearch",
    "zhihu_movie_hot_topics",
}


def test_runner_import_version_and_source_pool_guard():
    mod = load_module()
    assert mod.RUNNER_VERSION == "0.3.1"
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


def test_guduo_failure_maoyan_success_continues_and_audits_failure(tmp_path, monkeypatch):
    _mod, result, out_dir = run_with_fakes(tmp_path, monkeypatch, guduo_result=fake_guduo_fail(), run_id="guduo_fail")
    outputs = load_outputs(out_dir)
    assert result["verification"]["status"] == "PASS"
    assert outputs["summary"]["article_quality_gate"]["status"] == "PASS"
    assert set(outputs["summary"]["sources_successful"]) == EXPECTED_DEFAULT_SUCCESS - {"guduo"}
    assert set(outputs["summary"]["sources_failed"]) == {"guduo", "weibo_topic_search"}
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
    assert set(outputs["summary"]["sources_failed"]) == {"maoyan_realtime_boxoffice", "weibo_topic_search"}
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
