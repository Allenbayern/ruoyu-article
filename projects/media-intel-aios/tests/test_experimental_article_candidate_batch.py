import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "scripts" / "run_experimental_article_candidate_batch.py"
ARTICLE_SAMPLE = Path("/Users/Allen/.openclaw/workspace/handover-hotspot/04-QUALITY-FEEDBACK/article-approved-latest.md")



def load_module():
    spec = importlib.util.spec_from_file_location("run_experimental_article_candidate_batch", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_good_article_candidate_schema_and_boundaries():
    module = load_module()
    result = module.run_batch()
    assert result["label"] == "experimental_candidate"
    assert result["migration_gate_confirmed"] is True
    assert result["openclaw_hunter"] == {
        "active_task_runner": False,
        "writes_production_outputs": False,
    }
    assert result["openclaw_director"] == {
        "active_final_reviewer": False,
        "writes_production_outputs": False,
    }
    assert result["review_required"] is True
    assert result["auto_publish"] is False
    assert result["final_owner"] == "gpt55"
    assert result["publish_ready"] is False
    assert result["stable_production_claim"] is False
    assert result["sample_limit"] == 10
    assert result["article_source_path"] == str(ARTICLE_SAMPLE)
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
        "marriage_emotion",
        "folk_story",
        "generic_emotion",
        "xhs_life_reflection",
        "no_film_tv_anchor",
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
        assert candidate["good_article_candidate"] == {
            "has_clear_topic": True,
            "has_conflict_or_tension": True,
            "has_readable_title": True,
            "has_structure": True,
            "has_non_empty_claim_candidates": True,
            "review_flags_present": True,
            "film_tv_relevance": True,
            "label": "experimental_candidate",
            "publish_ready": False,
        }
        assert candidate["film_tv_relevance"] is True
        assert candidate["film_tv_relevance_reason"]
        assert candidate["main_topic"]
        assert candidate["backup_angles"]
        assert candidate["title_candidates"]
        assert candidate["narrative_structure"]
        assert candidate["claim_candidates"]
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
    wrong_topics = [
        "民间故事:兄弟俩",
        "36岁感悟|与其离婚",
        "你听过或写过最棒的故事是哪一个",
    ]
    for topic in wrong_topics:
        assert topic not in a_topics
    failures = json.dumps(result["failure_collection"], ensure_ascii=False)
    assert "not_film_tv_relevant" in failures


def test_generated_title_candidate_words_do_not_create_film_tv_relevance():
    module = load_module()
    package = module.build_article_package({
        "raw_line": "- 1. 泰山景区建 135 公里刀片刺绳隔离网，出于哪些考虑？为何争议这么大？这会对当地生态造成影响吗？ [zhihu] 基础分 80 潜力分 20 articleability 95",
        "source_line": 1,
        "pool": "A池",
        "source": "zhihu",
        "title": "泰山景区建 135 公里刀片刺绳隔离网，出于哪些考虑？为何争议这么大？这会对当地生态造成影响吗？",
        "base_score": 80,
        "production_score": 18,
        "potential_score": 20,
        "semantic_score": 0,
        "articleability": 95,
        "reason": "公共议题，不是影视题",
        "title_candidates": ["泰山景区隔离网，这次观众会怎么看？"],
        "reference_hints": [],
    })
    assert package["film_tv_relevance"] is False
    assert package["tier"] == "C"


def test_diagnostic_film_tv_weak_note_does_not_create_film_tv_relevance():
    module = load_module()
    package = module.build_article_package({
        "raw_line": "- 1. 生活感悟：越到中年越要学会独处 [xhs] 影视映射弱或缺失 基础分 80 潜力分 20 articleability 95",
        "source_line": 1,
        "pool": "A池",
        "source": "xhs",
        "title": "生活感悟：越到中年越要学会独处",
        "base_score": 80,
        "production_score": 18,
        "potential_score": 20,
        "semantic_score": 0,
        "articleability": 95,
        "reason": "影视映射弱或缺失",
        "title_candidates": [],
        "reference_hints": [],
    })
    assert package["film_tv_relevance"] is False
    assert package["tier"] == "C"
    assert package["lane"] == "article_reject"
    assert "not_film_tv_relevant" in package["review_flags"]


def test_article_buckets_do_not_backfill_a_tier_to_three():
    module = load_module()
    film_candidate = module.build_article_package({
        "raw_line": "- 2. 某电影观众吵翻：结局为什么让人寒了心 [douban_review] 基础分 80 潜力分 20 articleability 90",
        "source_line": 2,
        "pool": "C池",
        "source": "douban_review",
        "title": "某电影观众吵翻：结局为什么让人寒了心",
        "base_score": 80,
        "production_score": 18,
        "potential_score": 20,
        "semantic_score": 0,
        "articleability": 90,
        "reason": "真实电影争议",
        "title_candidates": [],
        "reference_hints": [],
    })
    weak_film_candidate = module.build_article_package({
        "raw_line": "- 3. 某导演新片片单更新 [douban_review] 基础分 50 潜力分 10 articleability 60",
        "source_line": 3,
        "pool": "C池",
        "source": "douban_review",
        "title": "某导演新片片单更新",
        "base_score": 50,
        "production_score": 10,
        "potential_score": 10,
        "semantic_score": 0,
        "articleability": 60,
        "reason": "电影资讯但冲突不足",
        "title_candidates": [],
        "reference_hints": [],
    })
    buckets = module.bucket_articles([film_candidate, weak_film_candidate])
    assert len(buckets["A"]) == 1
    assert buckets["A"][0]["main_topic"] == "某电影观众吵翻：结局为什么让人寒了心"
    assert weak_film_candidate in buckets["B"]


def test_article_buckets_dedupe_duplicate_topics_before_a_tier():
    module = load_module()
    first = module.build_article_package({
        "raw_line": "- 2. 香港演员吴启华卖20岁肖像权拍AI电影，如何看待这一选择？对行业意味着什么？ [zhihu] 基础分 80 潜力分 20 articleability 90",
        "source_line": 2,
        "pool": "A池",
        "source": "zhihu",
        "title": "香港演员吴启华卖20岁肖像权拍AI电影，如何看待这一选择？对行业意味着什么？",
        "base_score": 80,
        "production_score": 18,
        "potential_score": 20,
        "semantic_score": 0,
        "articleability": 90,
        "reason": "演员肖像权与AI电影",
        "title_candidates": [],
        "reference_hints": [],
    })
    duplicate = module.build_article_package({
        "raw_line": first["main_topic"],
        "source_line": 3,
        "pool": "A池",
        "source": "zhihu",
        "title": first["main_topic"],
        "base_score": 80,
        "production_score": 18,
        "potential_score": 20,
        "semantic_score": 0,
        "articleability": 90,
        "reason": "演员肖像权与AI电影",
        "title_candidates": [],
        "reference_hints": [],
    })
    buckets = module.bucket_articles([first, duplicate])
    assert len(buckets["A"]) == 1
    assert buckets["A"][0]["main_topic"] == first["main_topic"]


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
    assert output_path.exists()
    assert markdown_path.exists()
    assert "approved" not in output_path.name
    assert "publish_ready" not in output_path.name
    assert "stable_production" not in output_path.name
    assert "ready_for_publish: false" in markdown_path.read_text(encoding="utf-8")
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["run_id"] == result["run_id"]
    assert data["new_real_sources_landed"] is False
    assert data["publish_ready"] is False
    assert data["canonical_suite_green"] is False
    assert data["suite_green"] is False
