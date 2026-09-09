from article_group.editorial_pipeline_v3 import (
    validate_crawl_task,
    validate_identity,
    validate_material_pack,
    validate_pipeline_transition,
    validate_topic_card,
    validate_transition,
)


def _topic_card(*, status="approved", topic_id="topic-20260906-001", version=1):
    return {
        "schema_version": "topic-card-v1",
        "topic_id": topic_id,
        "version": version,
        "status": status,
        "article_group_owner": "article-group",
        "object": {"work_or_person": "示例作品", "event": "新片上映"},
        "core_question": "这部作品为什么值得现在讨论？",
        "target_reader": "关心影视行业变化的普通读者",
        "article_type": "作品评论",
        "conflict_or_contrast": "口碑与市场表现之间存在反差",
        "reader_benefit": "帮助读者理解作品的行业位置和观众反馈",
        "freshness": {"mode": "same-day", "reason": "今日出现新的可核查触发点"},
        "historical_dedupe": {
            "same_work": "pass",
            "same_event_cluster": "pass",
            "near_title": "pass",
            "new_angle": "从行业位置和观众反应交叉解释作品",
        },
        "material_requirements": ["正文事实", "行业背景", "观众反应", "复核事实"],
        "out_of_scope": [],
        "risk_tags": [],
        "acceptance": {"min_concrete_support_types": 2, "opening_support_required": True},
        "deadline": "2026-09-06T18:00:00+08:00",
        "decided_by": "editor",
        "decided_at": "2026-09-06T09:00:00+08:00",
    }


def _crawl_task(topic_card):
    return {
        "schema_version": "crawl-task-v1",
        "task_id": "crawl-20260906-001",
        "topic_id": topic_card["topic_id"],
        "topic_version": topic_card["version"],
        "status": "researching",
        "owner": "crawler",
        "objective": "为已确认的文章问题准备可复核材料",
        "required_materials": {
            "body_facts": ["完整正文和关键事实"],
            "industry_context": ["与题目直接相关的行业背景"],
            "audience_reactions": ["有范围说明的观众反应"],
            "cross_check_facts": ["关键事实的第二出处"],
        },
        "source_constraints": {
            "discovery_is_proof": False,
            "raw_html_as_writer_input": False,
        },
        "stop_conditions": ["关键事实可复核", "至少两类具体支撑"],
        "retry": {"max_attempts_per_source": 1, "state": "not_started"},
        "deliverables": [
            "material-pack.json",
            "source-audit.json",
            "screening-log.md",
            "gap-list.md",
        ],
        "created_at": "2026-09-06T09:10:00+08:00",
        "due_at": "2026-09-06T12:00:00+08:00",
    }


def _material(material_id, category, source_role):
    return {
        "material_id": material_id,
        "category": category,
        "title": "可复核材料",
        "source_url": f"https://example.com/{material_id}",
        "source_role": source_role,
        "source_level": "fulltext",
        "captured_at": "2026-09-06T09:30:00+08:00",
        "locator": "正文第1段",
        "supports": ["一条可定位的具体主张"],
        "cannot_support": [],
    }


def _material_pack(topic_card, crawl_task):
    return {
        "schema_version": "material-pack-v1",
        "pack_id": "pack-20260906-001",
        "topic_id": topic_card["topic_id"],
        "topic_version": topic_card["version"],
        "version": 1,
        "crawl_task_id": crawl_task["task_id"],
        "status": "material_ready",
        "materials": {
            "body_facts": [_material("m-body", "body_facts", "independent_fact")],
            "industry_context": [
                _material("m-industry", "industry_context", "industry_context")
            ],
            "audience_reactions": [
                {
                    **_material("m-audience", "audience_reactions", "audience_reaction"),
                    "sample_scope": "该平台公开短评样本，不代表全部观众",
                    "generalization_allowed": False,
                }
            ],
            "cross_check_facts": [
                _material("m-cross", "cross_check_facts", "independent_fact")
            ],
        },
        "claims": {
            "facts": [
                {"claim_id": "claim-1", "text": "可复核事实", "material_ids": ["m-body"]}
            ],
            "attributed_views": [],
            "audience_reactions": [
                {"claim_id": "claim-2", "text": "观众观点", "material_ids": ["m-audience"]}
            ],
            "inferences": [],
        },
        "acceptance": {
            "core_question_preserved": True,
            "concrete_support_types": ["body_facts", "industry_context"],
            "opening_support_material_ids": ["m-body"],
            "key_facts_traceable": True,
            "industry_context_relevant": True,
            "audience_sample_scoped": True,
            "duplicates_screened": True,
            "failed_sources_visible": True,
            "gaps": [],
            "blocking_gaps": [],
            "prohibited_claims": [],
        },
        "audience_sample": {
            "scope": "某平台截至2026-09-06的公开短评样本",
            "observed_at": "2026-09-06T09:35:00+08:00",
            "generalization_allowed": False,
        },
        "source_audit": {
            "version": 1,
            "failed_sources": [],
            "screened_out": [],
            "retry_required": False,
        },
        "retry_state": {"version": 1, "state": "not_required", "attempts": 0},
        "deliverables": {
            "source_audit": "source-audit.json",
            "screening_log": "screening-log.md",
            "gap_list": "gap-list.md",
            "retry_state": "retry-state.json",
        },
        "created_at": "2026-09-06T09:40:00+08:00",
        "updated_at": "2026-09-06T09:40:00+08:00",
    }

def test_v3_requires_approved_before_research():
 assert validate_transition('precheck','researching')
 assert validate_transition('approved','researching')==[]

def test_v3_blocks_writing_before_material_ready():
 assert validate_transition('researching','writing')
 assert validate_transition('material_ready','writing')==[]

def test_v3_identity():
 assert validate_identity({'topic_id':'t1','topic_version':1,'status':'approved'})==[]
 assert 'missing:topic_id' in validate_identity({'topic_version':1,'status':'idea'})


def test_v3_artifact_contracts_accept_a_complete_chain():
    topic_card = _topic_card()
    crawl_task = _crawl_task(topic_card)
    material_pack = _material_pack(topic_card, crawl_task)

    assert validate_topic_card(topic_card) == []
    assert validate_crawl_task(crawl_task, topic_card=topic_card) == []
    assert validate_material_pack(
        material_pack, topic_card=topic_card, crawl_task=crawl_task
    ) == []
    assert (
        validate_transition(
            "approved",
            "researching",
            topic_card=topic_card,
            crawl_task=crawl_task,
        )
        == []
    )
    assert (
        validate_transition(
            "researching",
            "material_ready",
            topic_card=topic_card,
            crawl_task={**crawl_task, "status": "material_ready"},
            material_pack=material_pack,
        )
        == []
    )
    assert (
        validate_pipeline_transition(
            "material_ready",
            "writing",
            topic_card=topic_card,
            crawl_task={**crawl_task, "status": "material_ready"},
            material_pack=material_pack,
        )
        == []
    )


def test_v3_crawl_cannot_start_from_unapproved_or_drifted_topic():
    topic_card = _topic_card(status="precheck")
    crawl_task = _crawl_task(topic_card)

    errors = validate_crawl_task(crawl_task, topic_card=topic_card)
    assert "topic_not_approved_for_crawl" in errors

    topic_card = _topic_card()
    crawl_task = _crawl_task(topic_card)
    crawl_task["topic_id"] = "topic-other"
    errors = validate_crawl_task(crawl_task, topic_card=topic_card)
    assert "topic_mismatch" in errors


def test_v3_material_ready_requires_evidence_and_boundaries():
    topic_card = _topic_card()
    crawl_task = _crawl_task(topic_card)
    material_pack = _material_pack(topic_card, crawl_task)
    material_pack["acceptance"]["concrete_support_types"] = ["body_facts"]
    material_pack["acceptance"]["audience_sample_scoped"] = False

    errors = validate_material_pack(
        material_pack, topic_card=topic_card, crawl_task=crawl_task
    )
    assert "material_ready_requires_two_support_types" in errors
    assert "material_ready_requires_audience_scope" in errors


def test_v3_each_audience_source_keeps_its_sample_boundary():
    topic_card = _topic_card()
    crawl_task = _crawl_task(topic_card)
    material_pack = _material_pack(topic_card, crawl_task)
    audience_material = material_pack["materials"]["audience_reactions"][0]
    del audience_material["sample_scope"]
    audience_material["generalization_allowed"] = True

    errors = validate_material_pack(
        material_pack, topic_card=topic_card, crawl_task=crawl_task
    )
    assert "audience_material_requires_sample_scope" in errors
    assert "audience_material_forbids_generalization" in errors


def test_v3_material_ready_rejects_blocking_gaps():
    topic_card = _topic_card()
    crawl_task = _crawl_task(topic_card)
    material_pack = _material_pack(topic_card, crawl_task)
    material_pack["acceptance"]["blocking_gaps"] = ["关键事实仍缺少可定位出处"]

    errors = validate_material_pack(
        material_pack, topic_card=topic_card, crawl_task=crawl_task
    )
    assert "material_ready_has_blocking_gap" in errors


def test_v3_transition_requires_the_matching_artifact_for_each_gate():
    topic_card = _topic_card()
    crawl_task = _crawl_task(topic_card)

    errors = validate_transition(
        "researching",
        "material_ready",
        topic_card=topic_card,
        crawl_task=crawl_task,
    )
    assert "missing:material_pack" in errors

    material_pack = _material_pack(topic_card, crawl_task)
    material_pack["status"] = "returned"
    errors = validate_transition(
        "material_ready",
        "writing",
        topic_card=topic_card,
        crawl_task={**crawl_task, "status": "material_ready"},
        material_pack=material_pack,
    )
    assert "material_pack_not_ready" in errors


def test_v3_strict_transition_has_no_artifact_bypass():
    errors = validate_pipeline_transition("approved", "researching")
    assert "missing:topic_card" in errors
    assert "missing:crawl_task" in errors


def test_v3_discovery_signal_cannot_be_used_as_fact_proof():
    topic_card = _topic_card()
    crawl_task = _crawl_task(topic_card)
    material_pack = _material_pack(topic_card, crawl_task)
    material_pack["materials"]["body_facts"][0]["source_role"] = "discovery_signal"

    errors = validate_material_pack(
        material_pack, topic_card=topic_card, crawl_task=crawl_task
    )
    assert "discovery_signal_not_fact_proof" in errors


def test_v3_precheck_must_be_concrete_before_approval():
    topic_card = _topic_card(status="precheck")
    topic_card["core_question"] = ""

    errors = validate_topic_card(topic_card)
    assert "precheck_requires:core_question" in errors
    assert "approved_requires:core_question" in validate_pipeline_transition(
        "precheck", "approved", topic_card=topic_card
    )

    ready_precheck = _topic_card(status="precheck")
    assert validate_pipeline_transition(
        "precheck", "approved", topic_card=ready_precheck
    ) == []


def test_v3_material_pack_binds_the_same_topic_version():
    topic_card = _topic_card()
    crawl_task = _crawl_task(topic_card)
    material_pack = _material_pack(topic_card, crawl_task)
    material_pack["topic_version"] = 2

    errors = validate_material_pack(
        material_pack, topic_card=topic_card, crawl_task=crawl_task
    )
    assert "topic_version_mismatch" in errors
    assert errors.count("topic_version_mismatch") == 1


def test_v3_material_pack_audit_and_retry_bind_to_pack_version():
    topic_card = _topic_card()
    crawl_task = _crawl_task(topic_card)
    material_pack = _material_pack(topic_card, crawl_task)
    material_pack["source_audit"]["version"] = 2

    errors = validate_material_pack(
        material_pack, topic_card=topic_card, crawl_task=crawl_task
    )
    assert "audit_retry_version_mismatch" in errors
    assert "pack_audit_version_mismatch" in errors


def test_v3_returned_artifacts_keep_a_reason_for_the_next_action():
    topic_card = _topic_card(status="returned")
    assert "returned_requires_reason" in validate_topic_card(topic_card)
    topic_card["return_reasons"] = ["需要补齐关键事实出处"]
    assert validate_topic_card(topic_card) == []

    crawl_task = _crawl_task(_topic_card())
    crawl_task["status"] = "returned"
    assert "returned_requires_reason" in validate_crawl_task(crawl_task)
    crawl_task["return_reasons"] = ["来源失败，需重试"]
    assert validate_crawl_task(crawl_task) == []
