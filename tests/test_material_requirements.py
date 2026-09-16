"""材料等级门槛（material_requirements）：篇幅上限由材料解锁，不是设定值。

背景（2026-09-16，daily-008 扩写实验）：那期的 150 条可用材料里 47% 是评论者判断，
场面层来自单一匿名影评号，只有 8 条硬数据；补上同口径数据表与署名记者采访之后，
2 651 字的成稿门禁全绿、事实锚点段落比例从 62% 升到 77%。
"""
from __future__ import annotations

from article_group.material_acceptance import (
    evaluate_material_acceptance,
    validate_material_acceptance_record,
)
from article_group.material_requirements import (
    DEFAULT_REQUIREMENTS,
    GRADE_BANDS,
    evaluate_material_requirements,
    validate_material_requirements,
)

REQUIREMENTS = dict(DEFAULT_REQUIREMENTS)


def _scene(item_id: str, source_id: str, independence: str | None) -> dict:
    item = {"item_id": item_id, "source_id": source_id, "kind": "scene"}
    if independence is not None:
        item["independence"] = independence
    return item


def _record(**inventory) -> dict:
    return {
        "material_requirements": REQUIREMENTS,
        "scene_items": inventory.get("scene_items", []),
        "comparable_data_points": inventory.get("comparable_data_points", []),
        "primary_quotes": inventory.get("primary_quotes", []),
    }


def test_requirements_are_opt_in():
    report = evaluate_material_requirements({"article_task_id": "at-1"})
    assert report["status"] == "not_declared"
    assert report["errors"] == []
    assert report["allowed_cjk_band"] is None
    assert validate_material_requirements({"article_task_id": "at-1"}) == []


def test_full_material_grade_unlocks_long_band():
    record = _record(
        scene_items=[_scene(f"sc-{i}", f"src-{i % 2}", "primary_interview") for i in range(8)],
        comparable_data_points=[{"point_id": f"dp-{i}"} for i in range(4)],
        primary_quotes=[{"quote_id": f"q-{i}"} for i in range(2)],
    )
    report = evaluate_material_requirements(record)
    assert report["grade"] == "full"
    assert report["errors"] == []
    assert report["allowed_cjk_band"] == GRADE_BANDS["full"]
    assert report["publication_authorization"] == "not_authorized"


def test_single_source_scene_layer_caps_the_band():
    record = _record(
        scene_items=[_scene(f"sc-{i}", "src-one", "independent_angle") for i in range(8)],
        comparable_data_points=[{"point_id": f"dp-{i}"} for i in range(4)],
        primary_quotes=[{"quote_id": f"q-{i}"} for i in range(2)],
    )
    report = evaluate_material_requirements(record)
    assert report["grade"] == "single_source_scenes"
    assert "material_requires_distinct_scene_sources:1<2" in report["errors"]
    assert report["allowed_cjk_band"] == GRADE_BANDS["single_source_scenes"]


def test_missing_scene_layer_falls_back_to_short_band():
    record = _record(comparable_data_points=[{"point_id": "dp-1"}])
    report = evaluate_material_requirements(record)
    assert report["grade"] == "no_scene_sources"
    assert "material_requires_scene_sources:0" in report["errors"]
    assert report["allowed_cjk_band"] == GRADE_BANDS["no_scene_sources"]


def test_syndicated_rewrite_does_not_count_as_a_distinct_scene_source():
    """两篇改写转载共用同一原稿：只算一个独立来源（见 source_independence）。"""
    record = _record(
        scene_items=[
            _scene("sc-1", "src-chaoxin", "canonical"),
            _scene("sc-2", "src-qianjiang", "syndicated_rewrite"),
        ],
        comparable_data_points=[{"point_id": "dp-1"}],
    )
    report = evaluate_material_requirements(record)
    assert report["counts"]["distinct_scene_sources"] == 1
    assert any(item.startswith("scene_source_not_independent:src-qianjiang")
               for item in report["warnings"])


def test_unverified_independence_is_warned_not_counted():
    record = _record(scene_items=[_scene("sc-1", "src-x", None)])
    report = evaluate_material_requirements(record)
    assert report["counts"]["distinct_scene_sources"] == 0
    assert "scene_source_independence_unverified:src-x" in report["warnings"]


def test_thresholds_are_declared_thin_material():
    record = _record(scene_items=[_scene("sc-1", "src-a", "canonical")])
    report = evaluate_material_requirements(record)
    assert "material_requires_more_scene_items:1<8" in report["errors"]
    assert "material_requires_more_comparable_data_points:0<4" in report["errors"]


def test_acceptance_validator_stays_green_without_declared_requirements():
    record = {
        "schema_version": "article-material-acceptance-v1",
        "article_task_id": "at-1",
        "topic_id": "t-1",
        "topic_version": 1,
        "core_question": "q",
        "decision": "return_research",
        "intended_claim_kinds": ["program_schedule"],
        "sources": [],
        "obtained_facts": [],
        "supported_analyses": [],
        "missing_materials": [],
    }
    errors = validate_material_acceptance_record(record, strict=False)
    assert not any("material_requires" in error for error in errors)


def test_acceptance_validator_reports_declared_thresholds():
    record = {
        "schema_version": "article-material-acceptance-v1",
        "article_task_id": "at-1",
        "topic_id": "t-1",
        "topic_version": 1,
        "core_question": "q",
        "decision": "return_research",
        "intended_claim_kinds": ["program_schedule"],
        "sources": [],
        "obtained_facts": [],
        "supported_analyses": [],
        "missing_materials": [],
        "material_requirements": REQUIREMENTS,
        "scene_items": [
            _scene("sc-1", "src-a", "canonical"),
            _scene("sc-2", "src-b", "primary_interview"),
        ],
    }
    errors = validate_material_acceptance_record(record, strict=False)
    assert "material_requires_more_scene_items:2<8" in errors
    result = evaluate_material_acceptance(record, strict=False)
    assert result["status"] == "invalid"
    assert result["material_requirements"]["grade"] == "single_source_scenes"
