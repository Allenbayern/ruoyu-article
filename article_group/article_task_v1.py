"""Article Group 1.0 parent/child task contracts.

Article Task owns editorial progress. Crawl Task is a bound research child;
V3/V4/V5 remain implementation details of that child.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .editorial_judgment import evaluate_editorial_judgment
from .article_first import (
    ARTICLE_FIRST_CONTRACT_VERSION,
    ARTICLE_FIRST_STATES,
    TITLE_PACKAGING_RESULTS,
    is_article_first_record,
    validate_phase_field_boundary,
)
from .content_fidelity import CONTENT_FIDELITY_SCHEMA, evaluate_content_fidelity
from .material_acceptance import evaluate_material_acceptance
from .title_pack_fidelity import TITLE_PACK_SCHEMA, evaluate_title_pack

ARTICLE_STATES = tuple(dict.fromkeys((
    "idea", "precheck", "angle_approved", "research_requested", "research_received",
    "material_accepted", "brief_locked", "drafting", "editorial_review", "revision",
    "final_review", "delivered", "closed", *ARTICLE_FIRST_STATES,
)))
GROUP_STATES = ("planning", "selecting", "articles_in_progress", "batch_review", "partially_delivered", "delivered", "closed")
CRAWL_STATES = ("approved", "researching", "material_ready", "returned", "closed")
PUBLICATION_AUTHORIZATION = "not_authorized"
MATERIAL_ACCEPTED_STATES = (
    "material_accepted",
    "brief_locked",
    "drafting",
    "editorial_review",
    "revision",
    "final_review",
    "drafting_content",
    "content_review",
    "content_passed",
    "title_packaging",
    "title_review",
    "delivered",
    "closed",
)
EDITORIAL_JUDGMENT_REQUIRED_STATES = ("final_review", "delivered", "closed")


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


def _validate_material_acceptance(
    article: Mapping[str, Any],
    material_acceptance: Mapping[str, Any] | None,
) -> list[str]:
    state = article.get("state")
    if state not in MATERIAL_ACCEPTED_STATES:
        return []
    if material_acceptance is None:
        return ["material_acceptance_record_required"]
    errors: list[str] = []
    if material_acceptance.get("article_task_id") != article.get("article_task_id"):
        errors.append("material_acceptance_article_task_id_mismatch")
    if material_acceptance.get("topic_id") != article.get("topic_id"):
        errors.append("material_acceptance_topic_id_mismatch")
    if material_acceptance.get("topic_version") != article.get("topic_version"):
        errors.append("material_acceptance_topic_version_mismatch")
    result = evaluate_material_acceptance(material_acceptance)
    if result["status"] != "accept":
        errors.append("material_acceptance_not_accept")
    return sorted(set(errors))


def _validate_editorial_judgment(
    article: Mapping[str, Any],
    editorial_judgment: Mapping[str, Any] | None,
) -> list[str]:
    state = article.get("state")
    if state not in EDITORIAL_JUDGMENT_REQUIRED_STATES:
        return []
    if editorial_judgment is None:
        return ["editorial_judgment_record_required"]
    errors: list[str] = []
    if editorial_judgment.get("article_task_id") != article.get("article_task_id"):
        errors.append("editorial_judgment_article_task_id_mismatch")
    result = evaluate_editorial_judgment(editorial_judgment)
    if result["structure_result"] == "pass" and result["judgment_result"] != "pass":
        errors.append("structure_pass_is_not_judgment_pass")
    if result["combined_result"] != "pass":
        errors.append("editorial_judgment_not_pass")
    return sorted(set(errors))


def _validate_article_first_task(
    article: Mapping[str, Any],
    *,
    content_fidelity: Mapping[str, Any] | None = None,
    title_pack: Mapping[str, Any] | None = None,
) -> list[str]:
    if not is_article_first_record(article):
        return []
    state = article.get("state")
    errors: list[str] = []
    if state in {"brief_locked", "drafting_content"}:
        phase = "writing"
    elif state in {"content_review", "content_passed"}:
        phase = "content_review"
    elif state in {"title_packaging", "title_review"}:
        phase = "title"
    else:
        phase = ""
    if phase in {"writing", "content_review", "title"}:
        errors.extend(validate_phase_field_boundary(article, phase))

    if (
        isinstance(content_fidelity, Mapping)
        and content_fidelity.get("schema_version") == CONTENT_FIDELITY_SCHEMA
    ):
        content_status = evaluate_content_fidelity(content_fidelity).get("status")
    else:
        content_status = (
            content_fidelity.get(
                "status",
                content_fidelity.get("result", content_fidelity.get("content_result")),
            )
            if isinstance(content_fidelity, Mapping)
            else article.get(
                "content_fidelity_status",
                article.get("content_fidelity_result", article.get("content_result")),
            )
        )
    content_declared = isinstance(content_fidelity, Mapping) or bool(
        any(
            isinstance(article.get(field), str) and article[field].strip()
            for field in ("content_fidelity_path", "content_fidelity_record_path")
        )
    )
    content_passed = content_status == "pass"
    if state in {"content_review", "content_passed", "title_packaging", "title_review", "final_review", "delivered"} and not content_declared:
        errors.append("content_fidelity_record_required")
    if state == "content_passed" and not content_passed:
        errors.append("content_fidelity_pass_required")
    if state == "title_packaging" and not content_passed:
        errors.append("content_pass_required_before_title_packaging")
    title_declared = isinstance(title_pack, Mapping) or bool(
        isinstance(article.get("title_pack_path"), str)
        and article["title_pack_path"].strip()
    )
    if state in {"title_review", "final_review", "delivered"} and not title_declared:
        errors.append("title_pack_record_required")
    if isinstance(title_pack, Mapping) and title_pack.get("schema_version") == TITLE_PACK_SCHEMA:
        title_result = evaluate_title_pack(title_pack).get("status")
    else:
        title_result = (
            title_pack.get(
                "status",
                title_pack.get("result", title_pack.get("title_pack_result")),
            )
            if isinstance(title_pack, Mapping)
            else article.get("title_pack_result")
        )
    if state in {"title_review", "final_review", "delivered"}:
        if title_result != "selected":
            errors.append("title_pack_selected_required")
    if state in {"final_review", "delivered"}:
        if not content_passed:
            errors.append("content_fidelity_pass_required")
        if not isinstance(article.get("title_review_path"), str) or not article["title_review_path"].strip():
            errors.append("title_review_record_required")
        if article.get("title_review_result") != "pass":
            errors.append("title_review_pass_required")
        if state == "delivered" and title_result != "selected":
            errors.append("selected_title_required_before_delivery")
    if state == "delivered":
        if not isinstance(article.get("delivery_path"), str) or not article["delivery_path"].strip():
            errors.append("delivery_artifact_required")
        if article.get("final_review_result") != "pass":
            errors.append("final_review_pass_required")
    if title_result is not None and title_result not in TITLE_PACKAGING_RESULTS:
        errors.append("invalid:title_pack_result")
    return sorted(set(errors))


def validate_article_task(
    value: Mapping[str, Any],
    *,
    group: Mapping[str, Any] | None = None,
    material_acceptance: Mapping[str, Any] | None = None,
    editorial_judgment: Mapping[str, Any] | None = None,
    content_fidelity: Mapping[str, Any] | None = None,
    title_pack: Mapping[str, Any] | None = None,
) -> list[str]:
    errors = _required(value, ("schema_version", "group_id", "article_task_id", "topic_id", "topic_version", "state"))
    if value.get("schema_version") != "article-task-v1": errors.append("schema_version")
    if value.get("state") not in ARTICLE_STATES: errors.append("invalid:state")
    if type(value.get("topic_version")) is not int or value.get("topic_version", 0) < 1: errors.append("invalid:topic_version")
    if group is not None:
        if value.get("group_id") != group.get("group_id"): errors.append("group_id_mismatch")
        if value.get("article_task_id") not in {a.get("article_task_id") for a in group.get("articles", []) if isinstance(a, Mapping)}: errors.append("article_task_not_in_group")
    errors.extend(_validate_material_acceptance(value, material_acceptance))
    errors.extend(_validate_editorial_judgment(value, editorial_judgment))
    errors.extend(_validate_article_first_task(value, content_fidelity=content_fidelity, title_pack=title_pack))
    return sorted(set(errors))


def validate_crawl_task(value: Mapping[str, Any], *, article: Mapping[str, Any] | None = None) -> list[str]:
    errors = _required(value, ("schema_version", "crawl_task_id", "article_task_id", "topic_id", "topic_version", "state"))
    if value.get("schema_version") != "crawl-task-parent-v1": errors.append("schema_version")
    if value.get("state") not in CRAWL_STATES: errors.append("invalid:state")
    if article is not None:
        for key in ("article_task_id", "topic_id", "topic_version"):
            if value.get(key) != article.get(key): errors.append(f"{key}_mismatch")
    return sorted(set(errors))


def validate_task_binding(
    *,
    group: Mapping[str, Any],
    article: Mapping[str, Any],
    crawl: Mapping[str, Any],
    material_acceptance: Mapping[str, Any] | None = None,
    editorial_judgment: Mapping[str, Any] | None = None,
    content_fidelity: Mapping[str, Any] | None = None,
    title_pack: Mapping[str, Any] | None = None,
) -> list[str]:
    errors = validate_group_manifest(group)
    errors.extend(
        validate_article_task(
            article,
            group=group,
            material_acceptance=material_acceptance,
            editorial_judgment=editorial_judgment,
            content_fidelity=content_fidelity,
            title_pack=title_pack,
        )
    )
    errors.extend(validate_crawl_task(crawl, article=article))
    return sorted(set(errors))


def validate_completion(
    *,
    group_state: str,
    article_state: str,
    crawl_state: str,
    article_acceptance: str,
    delivery_status: str,
    material_acceptance_status: str | None = None,
    editorial_judgment_result: str | None = None,
    structure_result: str | None = None,
    independent_review_status: str | None = None,
    cross_batch_history_status: str | None = None,
    content_fidelity_result: str | None = None,
    title_pack_result: str | None = None,
    article_first_contract_version: str | None = None,
    title_review_result: str | None = None,
    final_review_result: str | None = None,
) -> list[str]:
    errors = []
    if group_state not in GROUP_STATES: errors.append("invalid:group_state")
    if article_state not in ARTICLE_STATES: errors.append("invalid:article_state")
    if crawl_state not in CRAWL_STATES: errors.append("invalid:crawl_state")
    if article_state in MATERIAL_ACCEPTED_STATES and crawl_state not in {"material_ready", "closed"}: errors.append("article_started_without_crawl_material")
    if article_state in {"delivered", "closed"} and article_acceptance != "accepted": errors.append("article_acceptance_required")
    if article_state in {"delivered", "closed"} and delivery_status != "CONTENT_READY": errors.append("content_ready_required")
    if article_state in MATERIAL_ACCEPTED_STATES and material_acceptance_status != "accept":
        errors.append("material_acceptance_not_accept")
    if article_state in EDITORIAL_JUDGMENT_REQUIRED_STATES:
        if structure_result == "pass" and editorial_judgment_result != "pass":
            errors.append("structure_pass_is_not_judgment_pass")
        if editorial_judgment_result != "pass":
            errors.append("editorial_judgment_not_pass")
    if article_state == "content_passed" and content_fidelity_result != "pass":
        errors.append("content_fidelity_pass_required")
    if article_state in {"title_packaging", "title_review", "final_review", "delivered"} and content_fidelity_result != "pass":
        errors.append("content_fidelity_pass_required")
    if article_state in {"title_review", "final_review", "delivered"} and title_pack_result != "selected":
        errors.append("title_pack_selected_required")
    article_first_completion = (
        article_first_contract_version == ARTICLE_FIRST_CONTRACT_VERSION
        or article_state in {"title_packaging", "title_review"}
        or content_fidelity_result is not None
        or title_pack_result is not None
        or title_review_result is not None
        or final_review_result is not None
    )
    if article_first_completion and article_state in {"final_review", "delivered"} and title_review_result != "pass":
        errors.append("title_review_pass_required")
    if article_state == "delivered" and title_pack_result != "selected":
        errors.append("selected_title_required_before_delivery")
    if article_first_completion and article_state == "delivered":
        if final_review_result != "pass":
            errors.append("final_review_pass_required")
    if article_state in {"delivered", "closed"}:
        if independent_review_status in {None, "UNVERIFIED", "timeout", "pending"}:
            errors.append("independent_review_not_pass")
        if cross_batch_history_status == "not_loaded":
            errors.append("cross_batch_history_not_loaded")
    if group_state in {"delivered", "closed"} and article_state not in {"delivered", "closed"}: errors.append("group_closed_with_incomplete_article")
    return sorted(set(errors))


__all__ = [
    "ARTICLE_STATES",
    "GROUP_STATES",
    "CRAWL_STATES",
    "MATERIAL_ACCEPTED_STATES",
    "EDITORIAL_JUDGMENT_REQUIRED_STATES",
    "validate_group_manifest",
    "validate_article_task",
    "validate_crawl_task",
    "validate_task_binding",
    "validate_completion",
]
