import importlib.util
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest

TZ = timezone(timedelta(hours=8))

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "scripts" / "run_experimental_article_candidate_batch.py"

# Synthetic fixture path — tests must not depend on real legacy file paths.
MAIN_SCRIPT_PATH = Path(os.environ.get(
    'MEDIA_INTEL_MAIN_SCRIPT',
    str(Path.home() / 'hermes-static-refresh' / 'scripts' / 'media_intel_most_important_article.py')
))


def load_module():
    spec = importlib.util.spec_from_file_location("run_experimental_article_candidate_batch", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def independent_direct_source_packet_rows():
    return [
        {
            "source": "review_a",
            "title": "《海岸线》结局引发争议",
            "content": "《海岸线》结局让观众围绕人物选择出现持续且具体的讨论。",
            "url": "https://evidence.example/review-a",
            "signal_role": "audience_reaction_signal",
            "work_key": "douban:coastline",
            "work_title": "海岸线",
        },
        {
            "source": "social_b",
            "title": "海岸线观众讨论人物选择",
            "content": "围绕《海岸线》人物选择的分歧在社交讨论中持续扩散。",
            "url": "https://evidence.example/social-b",
            "signal_role": "social_discussion_signal",
            "work_key": "douban:coastline",
            "work_title": "海岸线",
        },
        {
            "source_id": "independent_direct_source_packet",
            "generic_eligibility_credit": False,
            "requires_attribution_in_output": True,
            "work_key": "douban:coastline",
            "supplementary_attributed_evidence": [
                {
                    "url": "https://direct.example/coastline-interview",
                    "published_at": "2026-07-10T09:00:00+08:00",
                    "publisher": "Direct Source",
                    "work_key": "douban:coastline",
                    "source_locator": "interview:coastline",
                    "source_role": "writer_attributed_supplement",
                    "epistemic_status": "attributed_reporting",
                    "attribution": "Direct Source reported that the production decision was contested.",
                }
            ],
        },
    ]


def test_independent_direct_source_packet_is_retained_only_as_writer_attributed_supplement(independent_direct_source_packet_rows):
    module = load_module()
    generic_rows = independent_direct_source_packet_rows[:2]
    with_packet = module._live_evidence_candidate(independent_direct_source_packet_rows, 1)
    without_packet = module._live_evidence_candidate(generic_rows, 1)

    assert with_packet["supplementary_attributed_evidence"] == independent_direct_source_packet_rows[2]["supplementary_attributed_evidence"]
    assert with_packet["supplementary_attributed_evidence_requires_attribution"] is True
    for key in ("source", "tier", "score", "write_readiness", "ready_for_publish", "review_required", "review_flags", "publish_block_reasons", "claim_candidates"):
        assert with_packet[key] == without_packet[key]
    assert with_packet["evidence_bundle"]["source_roles"] == without_packet["evidence_bundle"]["source_roles"]
    assert with_packet["evidence_bundle"]["cross_source_count"] == without_packet["evidence_bundle"]["cross_source_count"]
    assert all(item["source"] != "independent_direct_source_packet" for item in with_packet["live_evidence"])


def test_independent_direct_source_packet_cannot_make_generic_evidence_eligible(independent_direct_source_packet_rows):
    module = load_module()
    packet = independent_direct_source_packet_rows[2]
    only_generic_row = independent_direct_source_packet_rows[:1]

    with_packet = module._live_evidence_candidate([*only_generic_row, packet], 1)
    without_packet = module._live_evidence_candidate(only_generic_row, 1)

    assert with_packet["tier"] == without_packet["tier"] == "C"
    assert with_packet["score"] == without_packet["score"] == 0
    assert with_packet["ready_for_publish"] is without_packet["ready_for_publish"] is False
    assert with_packet["review_required"] is without_packet["review_required"] is True
    assert with_packet["evidence_bundle"]["cross_source_count"] == without_packet["evidence_bundle"]["cross_source_count"] == 1
    assert with_packet["evidence_bundle"]["source_roles"] == without_packet["evidence_bundle"]["source_roles"]
    assert with_packet["claim_candidates"] == without_packet["claim_candidates"]
    assert "requires_at_least_2_distinct_sources" in with_packet["publish_block_reasons"]


def test_good_article_candidate_schema_and_boundaries():
    module = load_module()
    result = module.run_batch()
    assert result["label"] == "experimental_candidate"
    assert result["migration_gate_confirmed"] is True
    assert result["openclaw_hunter"] == {"active_task_runner": False, "writes_production_outputs": False}
    assert result["openclaw_director"] == {"active_final_reviewer": False, "writes_production_outputs": False}
    assert result["review_required"] is True
    assert result["auto_publish"] is False
    assert result["final_owner"] == "gpt55"
    assert result["publish_ready"] is False
    assert result["stable_production_claim"] is False
    assert result["sample_limit"] == 10
    assert result["article_source_path"] == str(module.ARTICLE_SAMPLE)
    assert 1 <= result["total_article_candidates"] <= 10
    assert result["mixed_article_material_count"] >= result["total_article_candidates"]
    assert result["output_path"].endswith(f"daily_article_experimental_candidate_{result['run_date']}.json")
    assert result["markdown_output_path"].endswith(f"daily_article_experimental_candidate_{result['run_date']}.md")
    assert "daily_video_candidate_package" not in result
    assert "manju_story_mother_candidates" not in result


def test_article_runner_filters_article_lane_without_video_or_manju_package():
    result = load_module().run_batch()
    assert result["pipeline_change"]["filter_article_lane_only"] is True
    assert result["pipeline_change"]["lanes"] == ["article_lane"]
    assert result["daily_article_candidate_package"]["lane"] == "article"
    assert result["daily_article_candidate_package"]["source_policy"]["rejects"] == [
        "marriage_emotion", "folk_story", "generic_emotion", "xhs_life_reflection", "no_film_tv_anchor"
    ]
    assert result["daily_article_candidate_package"]["rejected_from_article_lane"]
    assert result["rejected_from_article_lane_count"] == len(result["daily_article_candidate_package"]["rejected_from_article_lane"])


def test_articles_are_ranked_abc_and_a_candidates_have_required_package_fields():
    result = load_module().run_batch()
    buckets = result["article_candidate_buckets"]
    assert set(buckets) == {"A", "B", "C"}
    assert 0 <= len(buckets["A"]) <= 3
    for candidate in buckets["A"]:
        assert candidate["lane"] == "article"
        assert candidate["good_article_candidate"]["has_clear_topic"] is True
        assert candidate["good_article_candidate"]["film_tv_relevance"] is True
        assert candidate["good_article_candidate"]["publish_ready"] is False
        assert candidate["main_topic"]
        assert candidate["title_candidates"]
        assert candidate["narrative_structure"]
        assert candidate["review_flags"]
        assert candidate["requires_main_controller_review"] is True
        assert candidate["ready_for_publish"] is False
    for tier in buckets.values():
        for candidate in tier:
            assert candidate["lane"] == "article"
            assert candidate["film_tv_relevance"] is True


def test_non_film_tv_candidates_are_not_promoted_to_a():
    result = load_module().run_batch()
    a_topics = "\n".join(c["main_topic"] for c in result["article_candidate_buckets"]["A"])
    for topic in ["民间故事:兄弟俩", "36岁感悟|与其离婚", "你听过或写过最棒的故事是哪一个"]:
        assert topic not in a_topics
    assert "not_film_tv_relevant" in json.dumps(result["failure_collection"], ensure_ascii=False)


def test_generated_title_candidate_words_do_not_create_film_tv_relevance():
    module = load_module()
    package = module.build_article_package({"raw_line": "- 1. 泰山景区建 135 公里刀片刺绳隔离网 [zhihu] 基础分 80 潜力分 20 articleability 95", "source_line": 1, "pool": "A池", "source": "zhihu", "title": "泰山景区建 135 公里刀片刺绳隔离网，出于哪些考虑？为何争议这么大？", "base_score": 80, "production_score": 18, "potential_score": 20, "semantic_score": 0, "articleability": 95, "reason": "公共议题，不是影视题", "title_candidates": ["泰山景区隔离网，这次观众会怎么看？"], "reference_hints": []})
    assert package["film_tv_relevance"] is False
    assert package["tier"] == "C"


def test_diagnostic_film_tv_weak_note_does_not_create_film_tv_relevance():
    module = load_module()
    package = module.build_article_package({"raw_line": "- 1. 生活感悟：越到中年越要学会独处 [xhs] 影视映射弱或缺失 基础分 80 潜力分 20 articleability 95", "source_line": 1, "pool": "A池", "source": "xhs", "title": "生活感悟：越到中年越要学会独处", "base_score": 80, "production_score": 18, "potential_score": 20, "semantic_score": 0, "articleability": 95, "reason": "影视映射弱或缺失", "title_candidates": [], "reference_hints": []})
    assert package["film_tv_relevance"] is False
    assert package["tier"] == "C"
    assert package["lane"] == "article_reject"
    assert "not_film_tv_relevant" in package["review_flags"]


def test_article_buckets_do_not_backfill_a_tier_to_three():
    module = load_module()
    film_candidate = module.build_article_package({"raw_line": "- 2. 某电影观众吵翻：结局为什么让人寒了心 [douban_review] 基础分 80 潜力分 20 articleability 90", "source_line": 2, "pool": "C池", "source": "douban_review", "title": "某电影观众吵翻：结局为什么让人寒了心", "base_score": 80, "production_score": 18, "potential_score": 20, "semantic_score": 0, "articleability": 90, "reason": "真实电影争议", "title_candidates": [], "reference_hints": []})
    weak_film_candidate = module.build_article_package({"raw_line": "- 3. 某导演新片片单更新 [douban_review] 基础分 50 潜力分 10 articleability 60", "source_line": 3, "pool": "C池", "source": "douban_review", "title": "某导演新片片单更新", "base_score": 50, "production_score": 10, "potential_score": 10, "semantic_score": 0, "articleability": 60, "reason": "电影资讯但冲突不足", "title_candidates": [], "reference_hints": []})
    buckets = module.bucket_articles([film_candidate, weak_film_candidate])
    assert len(buckets["A"]) == 1
    assert buckets["A"][0]["main_topic"] == "某电影观众吵翻：结局为什么让人寒了心"
    assert weak_film_candidate in buckets["B"]


def test_article_buckets_dedupe_duplicate_topics_before_a_tier():
    module = load_module()
    first = module.build_article_package({"raw_line": "- 2. 香港演员吴启华卖20岁肖像权拍AI电影 [zhihu] 基础分 80 潜力分 20 articleability 90", "source_line": 2, "pool": "A池", "source": "zhihu", "title": "香港演员吴启华卖20岁肖像权拍AI电影，如何看待这一选择？对行业意味着什么？", "base_score": 80, "production_score": 18, "potential_score": 20, "semantic_score": 0, "articleability": 90, "reason": "演员肖像权与AI电影", "title_candidates": [], "reference_hints": []})
    duplicate = module.build_article_package({"raw_line": first["main_topic"], "source_line": 3, "pool": "A池", "source": "zhihu", "title": first["main_topic"], "base_score": 80, "production_score": 18, "potential_score": 20, "semantic_score": 0, "articleability": 90, "reason": "演员肖像权与AI电影", "title_candidates": [], "reference_hints": []})
    buckets = module.bucket_articles([first, duplicate])
    assert len(buckets["A"]) == 1


def test_failure_collection_keeps_non_a_candidates_for_pipeline_repair():
    result = load_module().run_batch()
    failures = result["failure_collection"]
    assert failures
    assert all(item["label"] == "experimental_candidate" for item in failures)
    assert all(item["ready_for_publish"] is False for item in failures)
    assert any(item["reason"] for item in failures)
    assert result["repair_focus"] == ["article_zero_main_or_backup", "film_tv_relevance_gate"]
    assert {item["lane"] for item in failures} == {"article_group"}


def test_output_file_written_and_no_publish_or_suite_claims():
    result = load_module().run_batch()
    output_path = Path(result["output_path"])
    markdown_path = Path(result["markdown_output_path"])
    assert output_path.exists() and markdown_path.exists()
    assert "ready_for_publish: false" in markdown_path.read_text(encoding="utf-8")
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["run_id"] == result["run_id"]
    assert data["new_real_sources_landed"] is False
    assert data["publish_ready"] is False
    assert data["canonical_suite_green"] is False
    assert data["suite_green"] is False


def test_default_live_fetcher_resolves_sibling_runner_when_batch_is_dynamically_loaded(tmp_path, monkeypatch):
    module = load_module()
    expected_live_runner = MODULE_PATH.parent / "article_production_live_run.py"
    calls = []

    class FakeLoader:
        def exec_module(self, loaded_module):
            loaded_module.collect_live_backfill_rows = lambda: []

    class FakeSpec:
        loader = FakeLoader()

    def fake_spec_from_file_location(name, location):
        calls.append((name, Path(location)))
        return FakeSpec()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module.importlib.util, "spec_from_file_location", fake_spec_from_file_location)
    monkeypatch.setattr(module.importlib.util, "module_from_spec", lambda _spec: type("LiveRunner", (), {})())
    result = module.run_batch(tmp_path / "default-live.json", use_live_evidence=True)

    assert calls == [("article_production_live_run", expected_live_runner)]
    assert result["live_evidence_enabled"] is True
    assert result["article_source_path"] == "live_evidence"


def test_live_evidence_strict_path_promotes_only_valid_cross_source_candidate(tmp_path):
    module = load_module()
    rows = [
        {"source": "review_a", "source_name": "Review A", "title": "《海岸线》结局引发争议", "content": "《海岸线》结局让观众围绕人物选择出现持续且具体的讨论。", "summary": "影片结局的角色选择引发持续讨论。", "url": "https://evidence.example/review-a", "signal_role": "audience_reaction_signal", "narrative_roles": ["audience_sentiment", "review_comments"]},
        {"source": "social_b", "source_name": "Social B", "title": "海岸线观众讨论人物选择", "content": "围绕《海岸线》人物选择的分歧在社交讨论中持续扩散。", "summary": "社交讨论聚焦人物选择分歧。", "url": "https://evidence.example/social-b", "signal_role": "social_discussion_signal", "narrative_roles": ["social_discussion"]},
    ]
    result = module.run_batch(tmp_path / "live.json", live_rows=rows, use_live_evidence=True)
    candidates = result["article_candidate_buckets"]["A"]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["ready_for_publish"] is True
    assert candidate["review_required"] is False
    assert candidate["auto_publish"] is False
    assert candidate["publish_block_reasons"] == []
    assert result["review_required"] is False


def test_live_evidence_a_bucket_retains_all_six_strict_eligible_works(tmp_path):
    module = load_module()
    rows = []
    for index in range(1, 7):
        work_key = f"douban:{index}"
        work_title = f"测试电影作品{index}号"
        rows.extend([
            {"source": f"review_{index}", "title": f"《{work_title}》观众争议", "content": f"《{work_title}》观众围绕角色选择、剧情冲突和结局展开持续而具体的讨论分歧。", "url": f"https://evidence.example/{index}/review", "signal_role": "audience_reaction_signal", "work_key": work_key, "work_title": work_title},
            {"source": f"official_{index}", "title": work_title, "content": f"电影《{work_title}》围绕具体人物的关键选择与剧情危机展开，提供足够具体的角色和故事上下文。", "url": f"https://evidence.example/{index}/official", "signal_role": "article_body_signal", "work_key": work_key, "work_title": work_title},
        ])

    result = module.run_batch(tmp_path / "six-strict.json", live_rows=rows, use_live_evidence=True)

    assert len(result["article_candidate_buckets"]["A"]) == 6
    assert {item["work_key"] for item in result["article_candidate_buckets"]["A"]} == {
        f"douban:{index}" for index in range(1, 7)
    }


def test_main_selection_skips_three_historical_finals_and_selects_three_new_strict_a(tmp_path):
    module = load_module()
    spec = importlib.util.spec_from_file_location("media_intel_most_important_article_regression", MAIN_SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    main_runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main_runner)
    rows = []
    for index in range(1, 7):
        work_key = f"douban:{index}"
        work_title = f"测试电影作品{index}号"
        rows.extend([
            {"source": f"review_{index}", "title": f"《{work_title}》观众争议", "content": f"《{work_title}》观众围绕角色选择、剧情冲突和结局展开持续而具体的讨论分歧。", "url": f"https://evidence.example/{index}/review", "signal_role": "audience_reaction_signal", "work_key": work_key, "work_title": work_title},
            {"source": f"official_{index}", "title": work_title, "content": f"电影《{work_title}》围绕具体人物的关键选择与剧情危机展开，提供足够具体的角色和故事上下文。", "url": f"https://evidence.example/{index}/official", "signal_role": "article_body_signal", "work_key": work_key, "work_title": work_title},
        ])
    result = module.run_batch(tmp_path / "six-for-selection.json", live_rows=rows, use_live_evidence=True)
    historical = {main_runner.normalize_topic(f"测试电影作品{index}号") for index in range(1, 4)}

    selected, status, duplicates = main_runner.select_article_group(result, historical, limit=3)

    assert status == "PASS_ARTICLE_GROUP_3"
    assert [item["work_key"] for item in selected] == ["douban:4", "douban:5", "douban:6"]
    assert {main_runner.normalize_topic(title) for title in duplicates} == historical
    assert all(item["selection_mode"] == "strict_importance_threshold" for item in selected)


def test_main_runner_titles_use_specific_review_detail_instead_of_shared_sample_label():
    spec = importlib.util.spec_from_file_location("media_intel_most_important_article_titles", MAIN_SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    main_runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main_runner)

    first = main_runner.clean_title(
        "卡罗来纳的卡罗琳 Carolina Caroline (2025)",
        angle="audience_emotion_gap",
        primary_atom="《卡罗来纳的卡罗琳 Carolina Caroline (2025)》短评样本显示：刚逃完婚，还没有杀够",
    )
    second = main_runner.clean_title(
        "火遮眼 (2025)",
        angle="audience_emotion_gap",
        primary_atom="《火遮眼 (2025)》短评样本显示：豆包我们编了二十场精彩纷呈的打戏",
    )

    assert "短评样本" not in first
    assert "短评样本" not in second
    assert first != second
    assert main_runner.validate_title_quality(second, "火遮眼 (2025)", [first])["passed"] is True

    truncated_work = main_runner.clean_title(
        "卡罗来纳的卡罗琳 Carolina Caroline\u200e (2025)",
        angle="audience_emotion_gap",
        primary_atom="《卡罗来纳的卡罗琳 Carolina Caroline\u200e (2025)》短评样本显示：刚逃完婚，还没有杀够",
    )
    assert truncated_work
    assert "短评样本" not in truncated_work
    assert "逃完婚" not in truncated_work
    assert "卡罗来纳的卡罗琳 Carolina Caroline" in truncated_work
    assert "逃离小镇为何撞进犯罪与爱情" in truncated_work
    assert "internal" not in truncated_work.lower()


def test_live_evidence_strict_path_blocks_invalid_evidence(tmp_path):
    module = load_module()
    rows = [{"source": "only_one", "title": "《海岸线》讨论", "content": "太短", "url": "not-a-url", "signal_role": "social_discussion_signal", "narrative_roles": ["social_discussion"]}]
    result = module.run_batch(tmp_path / "invalid.json", live_rows=rows, use_live_evidence=True)
    candidates = [item for bucket in result["article_candidate_buckets"].values() for item in bucket]
    assert candidates and all(candidate["ready_for_publish"] is False for candidate in candidates)
    assert any("distinct_sources" in reason or "http" in reason or "claim" in reason for reason in candidates[0]["publish_block_reasons"])
    assert result["review_required"] is True


def test_live_evidence_groups_translated_titles_by_work_key_and_uses_douban_readable_title(tmp_path):
    module = load_module()
    rows = [
        {"source": "douban_reviews_discussions", "title": "《痴迷 Obsession(2025)》短评", "content": "《痴迷》短评里，观众围绕角色选择和结局出现持续、具体的讨论与分歧。", "url": "https://movie.douban.com/subject/1234567/comments", "signal_role": "audience_reaction_signal", "narrative_roles": ["audience_sentiment"], "work_key": "douban:1234567", "work_title": "痴迷 Obsession(2025)"},
        {"source": "letterboxd_work_context", "title": "Obsession (2025)", "content": "This same-work description supplies sufficiently detailed plot and character context for the article body evidence.", "url": "https://letterboxd.com/film/obsession-2025/", "signal_role": "article_body_signal", "narrative_roles": ["plot_character_context"], "work_key": "douban:1234567", "work_title": "痴迷 Obsession(2025)"},
    ]

    result = module.run_batch(tmp_path / "same-work.json", live_rows=rows, use_live_evidence=True)

    candidates = result["article_candidate_buckets"]["A"]
    assert len(candidates) == 1
    assert candidates[0]["work_key"] == "douban:1234567"
    assert candidates[0]["main_topic"] == "痴迷 Obsession(2025)"
    assert {item["source"] for item in candidates[0]["live_evidence"]} == {"douban_reviews_discussions", "letterboxd_work_context"}


def test_live_evidence_does_not_merge_rows_with_different_work_keys(tmp_path):
    module = load_module()
    rows = [
        {"source": "douban_a", "title": "《痴迷 Obsession(2025)》短评", "content": "《痴迷》观众围绕角色选择和结局出现持续、具体的讨论与分歧。", "url": "https://evidence.example/douban-a", "signal_role": "audience_reaction_signal", "work_key": "douban:111"},
        {"source": "letterboxd_b", "title": "Obsession (2025)", "content": "This separate work has sufficiently detailed plot and character context for article body evidence.", "url": "https://evidence.example/letterboxd-b", "signal_role": "article_body_signal", "work_key": "douban:222"},
    ]

    result = module.run_batch(tmp_path / "different-work.json", live_rows=rows, use_live_evidence=True)

    candidates = [item for bucket in result["article_candidate_buckets"].values() for item in bucket]
    assert len(candidates) == 2
    assert {c["work_key"] for c in candidates} == {"douban:111", "douban:222"}


# ── Negative tests for path migration ──


def test_old_mac_path_absent_does_not_load():
    """Verify that the removed /Users/Allen path cannot be imported."""
    old_mac_path = Path("/Users/Allen/.hermes/scripts/media_intel_most_important_article.py")
    assert not old_mac_path.exists(), (
        f"Legacy Mac path {old_mac_path} must not exist on Linux. "
        "If it exists via symlink, the migration is incomplete."
    )


def test_openclaw_path_absent_on_linux():
    """Verify the legacy OpenClaw path is absent on Linux."""
    old_openclaw = Path("/Users/Allen/.openclaw/workspace/handover-hotspot/04-QUALITY-FEEDBACK/article-approved-latest.md")
    assert not old_openclaw.exists(), (
        f"Legacy OpenClaw path {old_openclaw} must not exist on Linux."
    )


def test_linux_root_paths_resolve():
    """Verify the actual Linux project and script paths exist."""
    project_root = Path.home() / "Projects" / "media-intel-aios"
    assert project_root.is_dir(), f"Project root {project_root} not found"
    runner = project_root / "scripts" / "run_experimental_article_candidate_batch.py"
    assert runner.exists(), f"Runner {runner} not found"


def test_stale_input_rejects_old_file(tmp_path, monkeypatch):
    """Verify run_batch raises ValueError when the input file is older than 24h."""
    # Remove the autouse conftest skip so the guard fires.
    monkeypatch.delenv("MEDIA_INTEL_SKIP_STALE_CHECK", raising=False)

    stale = tmp_path / "article-approved-latest.md"
    stale.write_text("- 1. 测试文章标题 [douban] 基础分 80 潜力分 20 articleability 90\n 推荐原因：好的影视话题\n")
    # Set mtime to 48 hours ago.
    old_mtime = (datetime.now(TZ) - timedelta(hours=48)).timestamp()
    os.utime(stale, (old_mtime, old_mtime))

    module = load_module()
    monkeypatch.setattr(module, "ARTICLE_SAMPLE", stale)

    with pytest.raises(ValueError, match="Stale input"):
        module.run_batch(tmp_path / "stale-output.json")

