from article_group.article_task_v1 import *

def group():
    return {"schema_version":"article-group-v1","group_id":"g1","run_id":"r1","articles":[{"article_task_id":"a1"}],"publication_authorization":"not_authorized"}

def article():
    return {"schema_version":"article-task-v1","group_id":"g1","article_task_id":"a1","topic_id":"t1","topic_version":1,"state":"research_requested"}

def crawl():
    return {"schema_version":"crawl-task-parent-v1","crawl_task_id":"c1","article_task_id":"a1","topic_id":"t1","topic_version":1,"state":"material_ready"}

def test_parent_child_binding_passes():
    assert validate_task_binding(group=group(), article=article(), crawl=crawl()) == []

def test_parent_child_topic_drift_fails():
    c=crawl(); c["topic_version"]=2
    assert "topic_version_mismatch" in validate_task_binding(group=group(), article=article(), crawl=c)

def test_article_cannot_finish_without_acceptance():
    errors=validate_completion(group_state="delivered", article_state="delivered", crawl_state="material_ready", article_acceptance="pending", delivery_status="CONTENT_READY")
    assert "article_acceptance_required" in errors

def test_group_cannot_finish_with_incomplete_article():
    errors=validate_completion(group_state="closed", article_state="editorial_review", crawl_state="material_ready", article_acceptance="pending", delivery_status="CONTENT_BLOCKED")
    assert "group_closed_with_incomplete_article" in errors


from tests.test_editorial_judgment import judgment_record
from tests.test_material_acceptance import heart_metadata_pack, scene_supported_pack


def test_material_accepted_requires_acceptance_record():
    item = article()
    item["state"] = "material_accepted"
    errors = validate_article_task(item, group=group())
    assert "material_acceptance_record_required" in errors


def test_metadata_only_pack_cannot_enter_material_accepted():
    item = article()
    item["state"] = "material_accepted"
    item["article_task_id"] = "at-art-001"
    item["topic_id"] = "cand-heart-001"
    batch = group()
    batch["articles"] = [{"article_task_id": "at-art-001"}]
    errors = validate_article_task(
        item,
        group=batch,
        material_acceptance=heart_metadata_pack(),
    )
    assert "material_acceptance_not_accept" in errors


def test_supported_pack_can_enter_material_accepted():
    item = article()
    item["state"] = "material_accepted"
    item["article_task_id"] = "at-art-003"
    item["topic_id"] = "topic-scene-001"
    batch = group()
    batch["articles"] = [{"article_task_id": "at-art-003"}]
    errors = validate_article_task(
        item,
        group=batch,
        material_acceptance=scene_supported_pack(),
    )
    assert errors == []


def test_final_review_requires_editorial_judgment_not_just_structure():
    item = article()
    item["state"] = "final_review"
    item["article_task_id"] = "at-art-001"
    item["topic_id"] = "cand-heart-001"
    batch = group()
    batch["articles"] = [{"article_task_id": "at-art-001"}]
    errors = validate_article_task(
        item,
        group=batch,
        material_acceptance=heart_metadata_pack(
            core_question="官方预告把告白放在了哪个节目节点？",
            intended_claim_kinds=["program_schedule"],
            missing_materials=[],
            unanswerable_questions=[],
            decision="accept",
            return_rule="",
            title_directions=[{
                "title": "告白被放在了第6期之后的哪个预告里",
                "click_reason": "只问官方节点",
                "evidence_refs": ["src-heart-teaser"],
                "opening_fulfillment_locator": "首屏写出预告标题",
                "distinct_angle": "预告节点",
            }],
        ),
        editorial_judgment=judgment_record(judgment_result="return_research"),
    )
    assert "structure_pass_is_not_judgment_pass" in errors
    assert "editorial_judgment_not_pass" in errors


def test_article_first_task_cannot_enter_title_packaging_before_content_passed():
    from article_group.article_first import ARTICLE_FIRST_CONTRACT_VERSION

    task = {
        "schema_version": "article-task-v1",
        "group_id": "g1",
        "article_task_id": "a1",
        "topic_id": "t1",
        "topic_version": 1,
        "state": "title_packaging",
        "article_first_contract_version": ARTICLE_FIRST_CONTRACT_VERSION,
    }

    assert "content_pass_required_before_title_packaging" in validate_article_task(task)


def test_article_first_content_passed_requires_content_fidelity_record_and_pass():
    task = {
        "schema_version": "article-task-v1",
        "group_id": "g1",
        "article_task_id": "a1",
        "topic_id": "t1",
        "topic_version": 1,
        "state": "content_passed",
        "article_first_contract_version": "article-first-v1",
    }

    errors = validate_article_task(task)

    assert "content_fidelity_record_required" in errors
    assert "content_fidelity_pass_required" in errors


def test_article_first_content_state_cannot_self_certify_content_pass():
    task = {
        "schema_version": "article-task-v1",
        "group_id": "g1",
        "article_task_id": "a1",
        "topic_id": "t1",
        "topic_version": 1,
        "state": "title_packaging",
        "article_first_contract_version": "article-first-v1",
        "content_fidelity_path": "review/content-fidelity.json",
        "content_state": "content_passed",
    }

    errors = validate_article_task(task)

    assert "content_pass_required_before_title_packaging" in errors


def test_article_first_title_review_cannot_use_path_without_selected_result():
    task = {
        "schema_version": "article-task-v1",
        "group_id": "g1",
        "article_task_id": "a1",
        "topic_id": "t1",
        "topic_version": 1,
        "state": "title_review",
        "article_first_contract_version": "article-first-v1",
        "content_fidelity_path": "review/content-fidelity.json",
        "content_fidelity_status": "pass",
        "title_pack_path": "review/title-pack.json",
    }

    errors = validate_article_task(task)

    assert "title_pack_selected_required" in errors


def test_article_first_delivery_requires_title_review_final_review_and_delivery_artifact():
    task = {
        "schema_version": "article-task-v1",
        "group_id": "g1",
        "article_task_id": "a1",
        "topic_id": "t1",
        "topic_version": 1,
        "state": "delivered",
        "article_first_contract_version": "article-first-v1",
        "content_fidelity_path": "review/content-fidelity.json",
        "content_fidelity_status": "pass",
        "title_pack_path": "review/title-pack.json",
        "title_pack_result": "selected",
    }

    errors = validate_article_task(task)

    assert "title_review_pass_required" in errors
    assert "delivery_artifact_required" in errors
    assert "final_review_pass_required" in errors


def test_article_first_completion_requires_review_results_before_delivery():
    errors = validate_completion(
        group_state="delivered",
        article_state="delivered",
        crawl_state="material_ready",
        article_acceptance="accepted",
        delivery_status="CONTENT_READY",
        material_acceptance_status="accept",
        editorial_judgment_result="pass",
        structure_result="pass",
        independent_review_status="approve",
        cross_batch_history_status="loaded",
        content_fidelity_result="pass",
        title_pack_result="selected",
        article_first_contract_version="article-first-v1",
        title_review_result="pending",
        final_review_result="pending",
    )

    assert "title_review_pass_required" in errors
    assert "final_review_pass_required" in errors


def test_delivered_completion_rejects_structure_pass_without_judgment():
    errors = validate_completion(
        group_state="delivered",
        article_state="delivered",
        crawl_state="material_ready",
        article_acceptance="accepted",
        delivery_status="CONTENT_READY",
        material_acceptance_status="accept",
        structure_result="pass",
        editorial_judgment_result="return_research",
    )
    assert "structure_pass_is_not_judgment_pass" in errors
    assert "editorial_judgment_not_pass" in errors


def test_timeout_independent_review_cannot_deliver():
    errors = validate_completion(
        group_state="delivered",
        article_state="delivered",
        crawl_state="material_ready",
        article_acceptance="accepted",
        delivery_status="CONTENT_READY",
        material_acceptance_status="accept",
        structure_result="pass",
        editorial_judgment_result="pass",
        independent_review_status="UNVERIFIED",
        cross_batch_history_status="loaded",
    )
    assert "independent_review_not_pass" in errors


def test_unloaded_cross_batch_history_cannot_deliver():
    errors = validate_completion(
        group_state="delivered",
        article_state="delivered",
        crawl_state="material_ready",
        article_acceptance="accepted",
        delivery_status="CONTENT_READY",
        material_acceptance_status="accept",
        structure_result="pass",
        editorial_judgment_result="pass",
        independent_review_status="approve",
        cross_batch_history_status="not_loaded",
    )
    assert "cross_batch_history_not_loaded" in errors
