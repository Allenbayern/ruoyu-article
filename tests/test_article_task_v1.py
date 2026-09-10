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
