"""Article Group 1.0 parent/child task contracts.

Article Task owns editorial progress. Crawl Task is a bound research child;
V3/V4/V5 remain implementation details of that child.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ARTICLE_STATES = ("idea", "precheck", "angle_approved", "research_requested", "research_received", "material_accepted", "brief_locked", "drafting", "editorial_review", "revision", "final_review", "delivered", "closed")
GROUP_STATES = ("planning", "selecting", "articles_in_progress", "batch_review", "partially_delivered", "delivered", "closed")
CRAWL_STATES = ("approved", "researching", "material_ready", "returned", "closed")
PUBLICATION_AUTHORIZATION = "not_authorized"

def _required(value: Mapping[str, Any], fields: tuple[str, ...]) -> list[str]:
    return [f"missing:{field}" for field in fields if not value.get(field)]

def validate_group_manifest(value: Mapping[str, Any]) -> list[str]:
    errors = _required(value, ("schema_version", "group_id", "run_id", "articles"))
    if value.get("schema_version") != "article-group-v1": errors.append("schema_version")
    if not isinstance(value.get("articles"), list) or not value["articles"]: errors.append("articles_must_be_nonempty_list")
    ids = []
    for article in value.get("articles", []):
        if not isinstance(article, Mapping) or not article.get("article_task_id"): errors.append("article_task_id_missing")
        elif article["article_task_id"] in ids: errors.append("duplicate:article_task_id")
        else: ids.append(article["article_task_id"])
    if value.get("publication_authorization", PUBLICATION_AUTHORIZATION) != PUBLICATION_AUTHORIZATION: errors.append("publication_authorization_must_be_not_authorized")
    return sorted(set(errors))

def validate_article_task(value: Mapping[str, Any], *, group: Mapping[str, Any] | None = None) -> list[str]:
    errors = _required(value, ("schema_version", "group_id", "article_task_id", "topic_id", "topic_version", "state"))
    if value.get("schema_version") != "article-task-v1": errors.append("schema_version")
    if value.get("state") not in ARTICLE_STATES: errors.append("invalid:state")
    if type(value.get("topic_version")) is not int or value.get("topic_version", 0) < 1: errors.append("invalid:topic_version")
    if group is not None:
        if value.get("group_id") != group.get("group_id"): errors.append("group_id_mismatch")
        if value.get("article_task_id") not in {a.get("article_task_id") for a in group.get("articles", []) if isinstance(a, Mapping)}: errors.append("article_task_not_in_group")
    return sorted(set(errors))

def validate_crawl_task(value: Mapping[str, Any], *, article: Mapping[str, Any] | None = None) -> list[str]:
    errors = _required(value, ("schema_version", "crawl_task_id", "article_task_id", "topic_id", "topic_version", "state"))
    if value.get("schema_version") != "crawl-task-parent-v1": errors.append("schema_version")
    if value.get("state") not in CRAWL_STATES: errors.append("invalid:state")
    if article is not None:
        for key in ("article_task_id", "topic_id", "topic_version"):
            if value.get(key) != article.get(key): errors.append(f"{key}_mismatch")
    return sorted(set(errors))

def validate_task_binding(*, group: Mapping[str, Any], article: Mapping[str, Any], crawl: Mapping[str, Any]) -> list[str]:
    errors = validate_group_manifest(group)
    errors.extend(validate_article_task(article, group=group))
    errors.extend(validate_crawl_task(crawl, article=article))
    return sorted(set(errors))

def validate_completion(*, group_state: str, article_state: str, crawl_state: str, article_acceptance: str, delivery_status: str) -> list[str]:
    errors = []
    if group_state not in GROUP_STATES: errors.append("invalid:group_state")
    if article_state not in ARTICLE_STATES: errors.append("invalid:article_state")
    if crawl_state not in CRAWL_STATES: errors.append("invalid:crawl_state")
    if article_state in {"research_received", "material_accepted", "drafting", "editorial_review", "revision", "final_review", "delivered", "closed"} and crawl_state not in {"material_ready", "closed"}: errors.append("article_started_without_crawl_material")
    if article_state in {"delivered", "closed"} and article_acceptance != "accepted": errors.append("article_acceptance_required")
    if article_state in {"delivered", "closed"} and delivery_status != "CONTENT_READY": errors.append("content_ready_required")
    if group_state in {"delivered", "closed"} and article_state not in {"delivered", "closed"}: errors.append("group_closed_with_incomplete_article")
    return sorted(set(errors))

__all__ = ["ARTICLE_STATES", "GROUP_STATES", "CRAWL_STATES", "validate_group_manifest", "validate_article_task", "validate_crawl_task", "validate_task_binding", "validate_completion"]
