"""Material acceptance is an Article Task gate, not a crawl completeness check."""
from __future__ import annotations

from article_group.material_acceptance import (
    evaluate_material_acceptance,
    validate_material_acceptance_record,
)


def _source(
    source_id: str,
    *,
    capture_type: str,
    declared_source_level: str,
    locator: str,
    obtained_facts: list[str],
) -> dict:
    return {
        "source_id": source_id,
        "capture_type": capture_type,
        "declared_source_level": declared_source_level,
        "locator": locator,
        "obtained_facts": obtained_facts,
    }


def _title_direction(
    title: str,
    *,
    click_reason: str,
    evidence_refs: list[str],
    opening_fulfillment_locator: str,
    distinct_angle: str,
) -> dict:
    return {
        "title": title,
        "click_reason": click_reason,
        "evidence_refs": evidence_refs,
        "opening_fulfillment_locator": opening_fulfillment_locator,
        "distinct_angle": distinct_angle,
    }


def heart_metadata_pack(**overrides) -> dict:
    record = {
        "schema_version": "article-material-acceptance-v1",
        "article_task_id": "at-art-001",
        "topic_id": "cand-heart-001",
        "topic_version": 1,
        "core_question": "告白之后，谁愿意持续照顾对方？",
        "intended_claim_kinds": ["guest_behavior", "audience_psychology"],
        "sources": [
            _source(
                "src-heart-series",
                capture_type="page_metadata",
                declared_source_level="metadata",
                locator="datePublished: 2026-08-03; episode_all: 10",
                obtained_facts=["节目页标注2026-08-03上线，共10期"],
            ),
            _source(
                "src-heart-ep6-letter",
                capture_type="page_metadata",
                declared_source_level="metadata",
                locator="title: 第6期上：纸短情长 星涵书信传情思念满溢",
                obtained_facts=["第6期上官方标题含书信与思念"],
            ),
            _source(
                "src-heart-ep6-date",
                capture_type="page_metadata",
                declared_source_level="metadata",
                locator="title: 第6期下：星涵约会",
                obtained_facts=["第6期下官方标题含约会"],
            ),
            _source(
                "src-heart-teaser",
                capture_type="page_metadata",
                declared_source_level="metadata",
                locator="title: 9月9日真心时刻预告",
                obtained_facts=["官方预告出现告白节点"],
            ),
        ],
        "obtained_facts": [
            "节目页标注2026-08-03上线，共10期",
            "第6期上官方标题含书信与思念",
            "第6期下官方标题含约会",
            "官方预告出现告白节点",
        ],
        "supported_analyses": ["官方预告把书信、约会、告白安排在连续节目节点"],
        "missing_materials": [
            {"gap": "节目场面与对话", "needed_for": "guest_behavior"},
            {"gap": "有范围的观众样本", "needed_for": "audience_psychology"},
        ],
        "unanswerable_questions": ["观众为什么等待", "谁愿意持续照顾对方"],
        "decision": "return_research",
        "return_rule": "补节目场面、对话或收窄到预告节点本身能支撑的问题",
        "title_directions": [],
    }
    record.update(overrides)
    return record


def scene_supported_pack(**overrides) -> dict:
    record = {
        "schema_version": "article-material-acceptance-v1",
        "article_task_id": "at-art-003",
        "topic_id": "topic-scene-001",
        "topic_version": 1,
        "core_question": "告白之后，男嘉宾有没有继续接住女嘉宾的求助？",
        "intended_claim_kinds": ["guest_behavior"],
        "sources": [
            _source(
                "src-episode-scene",
                capture_type="scene_verified",
                declared_source_level="scene_notes",
                locator="第6期 00:18-00:24 女嘉宾求助后男嘉宾递水并留下",
                obtained_facts=["女嘉宾告白后当场求助，男嘉宾递水并留下"],
            ),
            _source(
                "src-episode-page",
                capture_type="page_metadata",
                declared_source_level="metadata",
                locator="title: 第6期下：告白后的选择",
                obtained_facts=["官方标题把该段标为告白后的选择"],
            ),
        ],
        "obtained_facts": [
            "女嘉宾告白后当场求助，男嘉宾递水并留下",
            "官方标题把该段标为告白后的选择",
        ],
        "supported_analyses": ["这段可写的是当场有没有接住求助，不是观众是否都在等待"],
        "missing_materials": [],
        "unanswerable_questions": [],
        "decision": "accept",
        "return_rule": "",
        "title_directions": [
            _title_direction(
                "告白之后，他有没有接住她的求助",
                click_reason="具体动作，读者能站队",
                evidence_refs=["src-episode-scene"],
                opening_fulfillment_locator="首屏写递水并留下的场面",
                distinct_angle="当场求助与回应",
            ),
            _title_direction(
                "告白过了，为什么还要看他会不会留下",
                click_reason="把节点从告白改成留下",
                evidence_refs=["src-episode-scene", "src-episode-page"],
                opening_fulfillment_locator="首屏对照官方标题和当场留下",
                distinct_angle="留下与否，不是告白本身",
            ),
        ],
    }
    record.update(overrides)
    return record


def test_metadata_only_pack_cannot_accept_guest_or_audience_analysis():
    result = evaluate_material_acceptance(
        heart_metadata_pack(decision="accept", return_rule="", title_directions=[
            _title_direction(
                "他们为什么还在等待",
                click_reason="等待",
                evidence_refs=["src-heart-teaser"],
                opening_fulfillment_locator="首屏",
                distinct_angle="等待",
            )
        ])
    )
    assert result["status"] != "accept"
    assert "accept_requires_supported_claim_kind:guest_behavior" in result["errors"]
    assert "accept_requires_supported_claim_kind:audience_psychology" in result["errors"]
    assert "core_question_unanswerable" in result["errors"]


def test_program_titles_are_not_fulltext():
    errors = validate_material_acceptance_record(
        heart_metadata_pack(
            sources=[
                _source(
                    "src-heart-ep6-letter",
                    capture_type="page_metadata",
                    declared_source_level="fulltext",
                    locator="title: 第6期上：纸短情长",
                    obtained_facts=["第6期上官方标题含书信"],
                )
            ]
        )
    )
    assert "source_level_fulltext_for_metadata:src-heart-ep6-letter" in errors


def test_honest_metadata_pack_can_return_to_research():
    result = evaluate_material_acceptance(heart_metadata_pack())
    assert result["errors"] == []
    assert result["status"] == "return_research"
    assert "guest_behavior" in result["blocking_gaps"]
    assert "audience_psychology" in result["blocking_gaps"]


def test_narrow_schedule_question_can_accept_metadata():
    result = evaluate_material_acceptance(
        heart_metadata_pack(
            core_question="官方预告把告白放在了哪个节目节点？",
            intended_claim_kinds=["program_schedule"],
            missing_materials=[],
            unanswerable_questions=[],
            decision="accept",
            return_rule="",
            title_directions=[
                _title_direction(
                    "告白被放在了第6期之后的哪个预告里",
                    click_reason="只问官方节点，不猜嘉宾动机",
                    evidence_refs=["src-heart-teaser"],
                    opening_fulfillment_locator="首屏写出预告标题和日期",
                    distinct_angle="预告节点",
                )
            ],
        )
    )
    assert result["errors"] == []
    assert result["status"] == "accept"


def test_accept_requires_one_to_three_distinct_title_directions():
    result = evaluate_material_acceptance(
        scene_supported_pack(
            title_directions=[
                _title_direction(
                    "告白之后，他有没有接住她的求助",
                    click_reason="具体动作",
                    evidence_refs=["src-episode-scene"],
                    opening_fulfillment_locator="首屏写递水",
                    distinct_angle="当场求助",
                ),
                _title_direction(
                    "告白之后，他是否接住了她的求助",
                    click_reason="近义改写",
                    evidence_refs=["src-episode-scene"],
                    opening_fulfillment_locator="首屏写递水",
                    distinct_angle="当场求助",
                ),
            ]
        )
    )
    assert "title_directions_not_distinct" in result["errors"]


def test_title_promise_must_bind_obtained_evidence():
    result = evaluate_material_acceptance(
        scene_supported_pack(
            title_directions=[
                _title_direction(
                    "全网都在等他的答案",
                    click_reason="热度",
                    evidence_refs=["missing-audience-sample"],
                    opening_fulfillment_locator="首屏写全网等待",
                    distinct_angle="观众热度",
                )
            ]
        )
    )
    assert "title_direction_evidence_missing:missing-audience-sample" in result["errors"]


def test_more_than_three_title_directions_fail():
    extras = [
        _title_direction(
            f"方向{index}",
            click_reason="理由",
            evidence_refs=["src-episode-scene"],
            opening_fulfillment_locator="首屏",
            distinct_angle=f"角度{index}",
        )
        for index in range(4)
    ]
    errors = validate_material_acceptance_record(scene_supported_pack(title_directions=extras))
    assert "title_directions_exceed_three" in errors


def test_return_research_must_not_carry_title_directions():
    errors = validate_material_acceptance_record(
        heart_metadata_pack(
            title_directions=[
                _title_direction(
                    "谁愿意持续照顾对方",
                    click_reason="照顾",
                    evidence_refs=["src-heart-teaser"],
                    opening_fulfillment_locator="首屏",
                    distinct_angle="照顾",
                )
            ]
        )
    )
    assert "title_directions_forbidden_unless_accepted" in errors


def test_article_first_material_acceptance_does_not_require_title_directions():
    from article_group.article_first import ARTICLE_FIRST_CONTRACT_VERSION

    result = evaluate_material_acceptance(
        scene_supported_pack(
            article_first_contract_version=ARTICLE_FIRST_CONTRACT_VERSION,
            title_directions=[],
            content_value_plan={
                "hard_information_plan": [
                    {"plan_id": "i1", "kind": "action", "material_refs": ["src-episode-scene"]},
                    {"plan_id": "i2", "kind": "scene", "material_refs": ["src-episode-scene"]},
                    {"plan_id": "i3", "kind": "relationship", "material_refs": ["src-episode-page"]},
                ],
                "opening_support_refs": ["src-episode-scene"],
                "explanation_mechanism": "动作顺序解释关系变化",
            },
        )
    )

    assert result["status"] == "accept"
    assert not any("title_direction" in error for error in result["errors"])


def test_information_dense_reference_shape_requires_five_hard_information_items():
    from article_group.article_first import ARTICLE_FIRST_CONTRACT_VERSION

    record = scene_supported_pack(
        article_first_contract_version=ARTICLE_FIRST_CONTRACT_VERSION,
        reference_shape="relationship_plot_recap",
        title_directions=[],
        content_value_plan={
            "hard_information_plan": [
                {"plan_id": "i1", "kind": "action", "material_refs": ["src-episode-scene"]},
                {"plan_id": "i2", "kind": "scene", "material_refs": ["src-episode-scene"]},
                {"plan_id": "i3", "kind": "relationship", "material_refs": ["src-episode-page"]},
                {"plan_id": "i4", "kind": "mechanism", "material_refs": ["src-episode-scene"]},
            ],
            "opening_support_refs": ["src-episode-scene"],
            "explanation_mechanism": "动作顺序解释关系变化",
        },
    )

    errors = validate_material_acceptance_record(record)

    assert "content_value_plan_requires_at_least_5_for_reference_shape" in errors


def test_information_dense_reference_shape_requires_three_concrete_support_kinds():
    from article_group.article_first import ARTICLE_FIRST_CONTRACT_VERSION

    record = scene_supported_pack(
        article_first_contract_version=ARTICLE_FIRST_CONTRACT_VERSION,
        reference_shape="relationship_plot_recap",
        title_directions=[],
        content_value_plan={
            "hard_information_plan": [
                {"plan_id": "i1", "kind": "action", "material_refs": ["src-episode-scene"]},
                {"plan_id": "i2", "kind": "action", "material_refs": ["src-episode-scene"]},
                {"plan_id": "i3", "kind": "action", "material_refs": ["src-episode-scene"]},
                {"plan_id": "i4", "kind": "action", "material_refs": ["src-episode-scene"]},
                {"plan_id": "i5", "kind": "action", "material_refs": ["src-episode-scene"]},
            ],
            "opening_support_refs": ["src-episode-scene"],
            "explanation_mechanism": "动作顺序解释关系变化",
        },
    )

    errors = validate_material_acceptance_record(record)

    assert "content_value_plan_requires_three_concrete_support_kinds" in errors


def test_legacy_article_first_plan_keeps_existing_three_item_threshold():
    from article_group.article_first import ARTICLE_FIRST_CONTRACT_VERSION

    record = scene_supported_pack(
        article_first_contract_version=ARTICLE_FIRST_CONTRACT_VERSION,
        title_directions=[],
        content_value_plan={
            "hard_information_plan": [
                {"plan_id": "i1", "kind": "action", "material_refs": ["src-episode-scene"]},
                {"plan_id": "i2", "kind": "scene", "material_refs": ["src-episode-scene"]},
                {"plan_id": "i3", "kind": "relationship", "material_refs": ["src-episode-page"]},
            ],
            "opening_support_refs": ["src-episode-scene"],
            "explanation_mechanism": "动作顺序解释关系变化",
        },
    )

    errors = validate_material_acceptance_record(record)

    assert "content_value_plan_requires_at_least_5_for_reference_shape" not in errors
    assert "content_value_plan_requires_three_concrete_support_kinds" not in errors


def test_reference_shape_must_be_from_supported_set():
    errors = validate_material_acceptance_record(
        scene_supported_pack(reference_shape="generic_viral_template")
    )

    assert "invalid:reference_shape" in errors


def test_dense_reference_shape_requires_reader_gain_floor_five_when_declared():
    errors = validate_material_acceptance_record(
        scene_supported_pack(
            reference_shape="relationship_plot_recap",
            reader_gain_floor=3,
        )
    )

    assert "invalid:reader_gain_floor_for_reference_shape" in errors


def test_declared_reference_shape_requires_reader_gain_for_each_plan_item():
    from article_group.article_first import ARTICLE_FIRST_CONTRACT_VERSION

    record = scene_supported_pack(
        article_first_contract_version=ARTICLE_FIRST_CONTRACT_VERSION,
        reference_shape="setting_observation",
        title_directions=[],
        content_value_plan={
            "hard_information_plan": [
                {"plan_id": "i1", "kind": "action", "material_refs": ["src-episode-scene"]},
                {"plan_id": "i2", "kind": "scene", "material_refs": ["src-episode-scene"]},
                {"plan_id": "i3", "kind": "relationship", "material_refs": ["src-episode-page"]},
            ],
            "opening_support_refs": ["src-episode-scene"],
            "explanation_mechanism": "动作顺序解释关系变化",
        },
    )

    errors = validate_material_acceptance_record(record)

    assert "missing:content_value_plan_reader_gain:0" in errors


def test_article_first_material_acceptance_rejects_discovery_title_skeleton():
    from article_group.article_first import ARTICLE_FIRST_CONTRACT_VERSION

    result = evaluate_material_acceptance(
        scene_supported_pack(
            article_first_contract_version=ARTICLE_FIRST_CONTRACT_VERSION,
            title_skeleton="发现层标题信号",
            title_directions=[],
        )
    )

    assert "forbidden_content_field:title_skeleton" in result["errors"]


def test_strict_material_acceptance_separates_fact_readiness_from_editorial_value():
    from article_group.article_first import ARTICLE_FIRST_CONTRACT_VERSION

    record = scene_supported_pack(
        article_first_contract_version=ARTICLE_FIRST_CONTRACT_VERSION,
        production_contract="article-first-v1",
        brief_contract="writing-brief-v2",
        title_contract="title-pack-v1",
        legacy_compatibility=False,
        title_directions=[],
        material_ready_for_draft=True,
        editorial_value_ready=False,
        content_value_plan={
            "hard_information_plan": [
                {"plan_id": "i1", "kind": "action", "material_refs": ["src-episode-scene"]},
                {"plan_id": "i2", "kind": "scene", "material_refs": ["src-episode-scene"]},
                {"plan_id": "i3", "kind": "relationship", "material_refs": ["src-episode-page"]},
            ],
            "opening_support_refs": ["src-episode-scene"],
            "explanation_mechanism": "动作顺序解释关系变化",
        },
    )

    result = evaluate_material_acceptance(record)

    assert result["material_ready_for_draft"] is True
    assert result["editorial_value_ready"] is False
    assert "editorial_value_not_ready" in result["errors"]
    assert result["status"] != "accept"


def test_strict_material_claim_cannot_upgrade_metadata_to_scene():
    from article_group.article_first import ARTICLE_FIRST_CONTRACT_VERSION

    record = heart_metadata_pack(
        article_first_contract_version=ARTICLE_FIRST_CONTRACT_VERSION,
        production_contract="article-first-v1",
        brief_contract="writing-brief-v2",
        title_contract="title-pack-v1",
        legacy_compatibility=False,
        claims=[
            {
                "claim_id": "c-scene",
                "claim_level": "scene_action",
                "source_ids": ["src-heart-teaser"],
            }
        ],
    )

    errors = validate_material_acceptance_record(record)

    assert "claim_level_exceeds_source_capability:c-scene:src-heart-teaser" in errors


def test_strict_return_research_can_declare_readiness_false():
    from article_group.article_first import ARTICLE_FIRST_CONTRACT_VERSION

    record = heart_metadata_pack(
        article_first_contract_version=ARTICLE_FIRST_CONTRACT_VERSION,
        production_contract="article-first-v1",
        brief_contract="writing-brief-v2",
        title_contract="title-pack-v1",
        legacy_compatibility=False,
        material_ready_for_draft=False,
        editorial_value_ready=False,
        content_value_plan=None,
        title_directions=[],
    )

    result = evaluate_material_acceptance(record)

    assert result["status"] == "return_research"
    assert result["errors"] == []
    assert result["material_ready_for_draft"] is False
    assert result["editorial_value_ready"] is False


def test_strict_material_plan_references_must_name_declared_sources():
    from article_group.article_first import ARTICLE_FIRST_CONTRACT_VERSION

    record = scene_supported_pack(
        article_first_contract_version=ARTICLE_FIRST_CONTRACT_VERSION,
        production_contract="article-first-v1",
        brief_contract="writing-brief-v2",
        title_contract="title-pack-v1",
        legacy_compatibility=False,
        material_ready_for_draft=True,
        editorial_value_ready=True,
        title_directions=[],
        content_value_plan={
            "hard_information_plan": [
                {
                    "plan_id": "i1",
                    "kind": "action",
                    "material_refs": ["missing-source"],
                },
                {
                    "plan_id": "i2",
                    "kind": "scene",
                    "material_refs": ["src-episode-scene"],
                },
                {
                    "plan_id": "i3",
                    "kind": "relationship",
                    "material_refs": ["src-episode-page"],
                },
            ],
            "opening_support_refs": ["missing-opening-source"],
            "explanation_mechanism": "动作顺序解释关系变化",
        },
    )

    errors = validate_material_acceptance_record(record)

    assert "unknown:content_value_plan_material_ref:0:missing-source" in errors
    assert "unknown:content_value_plan_opening_support:missing-opening-source" in errors


def test_strict_marker_cannot_be_downgraded_by_strict_false():
    from article_group.article_first import ARTICLE_FIRST_CONTRACT_VERSION

    record = scene_supported_pack(
        article_first_contract_version=ARTICLE_FIRST_CONTRACT_VERSION,
        production_contract="article-first-v1",
        brief_contract="writing-brief-v2",
        title_contract="title-pack-v1",
        legacy_compatibility=False,
        title_directions=[],
        material_ready_for_draft=True,
        editorial_value_ready=True,
        content_value_plan={
            "hard_information_plan": [
                {
                    "plan_id": "i1",
                    "kind": "action",
                    "material_refs": ["src-episode-scene"],
                },
                {
                    "plan_id": "i2",
                    "kind": "scene",
                    "material_refs": ["src-episode-scene"],
                },
                {
                    "plan_id": "i3",
                    "kind": "relationship",
                    "material_refs": ["src-episode-page"],
                },
            ],
            "opening_support_refs": ["src-episode-scene"],
            "explanation_mechanism": "动作顺序解释关系变化",
        },
    )

    errors = validate_material_acceptance_record(record, strict=False)

    assert errors
    assert "missing:source_capability:src-episode-scene" in errors
