"""Deterministic, offline composition of the V4 daily article portfolio."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import combinations
import math
from typing import Any, Mapping

from .contracts import new_artifact_envelope, validate_artifact_envelope

_READINESS_PRIORITY = {"high": 2, "medium": 1, "low": 0}
_FRESHNESS_TO_ROLE = {
    "same-day": "flow",
    "fermenting-1-3d": "flow",
    "revival": "evergreen",
}
_CONTENT_MAP_LABELS = {
    "a": "A", "a新片事件": "A", "新片事件": "A",
    "b": "B", "b作品深度": "B", "作品深度": "B",
    "c": "C", "c文化现象": "C", "文化现象": "C",
    "d": "D", "d人物争议": "D", "人物争议": "D",
    "flow": "flow", "depth": "depth", "evergreen": "evergreen",
    "culture": "culture",
}


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _canonical_content_map(value: object) -> str:
    return _CONTENT_MAP_LABELS.get("".join(_text(value).lower().split()), "")


def _sequence(value: object) -> list[object] | None:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        return None
    return list(value)


def _role(candidate: Mapping[str, Any]) -> set[str]:
    roles: set[str] = set()
    content_map = _text(candidate.get("content_map"))
    if content_map in {"A", "flow"}:
        roles.add("flow")
    if content_map in {"B", "depth"}:
        roles.add("depth")
    if content_map == "evergreen":
        roles.add("evergreen")
    topic_mode = _text(candidate.get("topic_mode")).lower()
    if topic_mode in {"current", "release_event"}:
        roles.add("flow")
    if topic_mode in {"depth", "revisit", "craft"}:
        roles.add("depth")
    if topic_mode in {"evergreen", "revisit"}:
        roles.add("evergreen")
    traffic_class = _text(candidate.get("traffic_class")).lower()
    if traffic_class in {"flow", "current"}:
        roles.add("flow")
    if traffic_class in {"depth", "deep"}:
        roles.add("depth")
    if traffic_class in {"evergreen", "revival"}:
        roles.add("evergreen")
    freshness_role = _FRESHNESS_TO_ROLE.get(
        _text(candidate.get("freshness_window")).lower()
    )
    if freshness_role:
        roles.add(freshness_role)
    return roles


def _normalize(candidate: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "candidate_id": _text(candidate.get("candidate_id")),
        "content_map": _canonical_content_map(candidate.get("content_map")),
        "topic_mode": _text(candidate.get("topic_mode")),
        "event_cluster_id": _text(candidate.get("event_cluster_id")),
        "work_or_person": _text(
            candidate.get("work_or_person")
            or candidate.get("work")
            or candidate.get("core_person_or_event")
        ),
        "traffic_class": _text(candidate.get("traffic_class")),
        "freshness_window": _text(candidate.get("freshness_window")).lower(),
        "selection_reason": _text(
            candidate.get("selection_reason")
            or candidate.get("reason")
            or candidate.get("why_now")
        ),
        "reader_gap": _text(
            candidate.get("reader_gap")
            or candidate.get("reader_question")
            or candidate.get("reader_intent")
        ),
        "content_value_score": candidate.get("content_value_score"),
        "evidence_readiness": _text(candidate.get("evidence_readiness")).lower(),
    }
    if result["content_value_score"] is None:
        result["content_value_score"] = candidate.get("editorial_value_score")
    if not result["traffic_class"]:
        result["traffic_class"] = result["freshness_window"]
    return result


def _history_works(history: object) -> tuple[set[str], list[str]]:
    items = _sequence(history)
    if items is None:
        return set(), ["invalid:history"]
    works: set[str] = set()
    errors: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            errors.append("invalid:history_item")
            continue
        articles = item.get("selected_articles", item.get("selected_candidates", []))
        if articles is not None and not isinstance(articles, list):
            errors.append("invalid:history_selected_articles")
            continue
        for article in articles or []:
            if isinstance(article, Mapping) and _text(article.get("work_or_person")):
                works.add(_text(article["work_or_person"]))
        if _text(item.get("work_or_person")):
            works.add(_text(item["work_or_person"]))
    return works, list(dict.fromkeys(errors))


def _pair_errors(
    pair: tuple[Mapping[str, Any], Mapping[str, Any]], history_works: set[str]
) -> list[str]:
    left, right = pair
    errors: list[str] = []
    checks = (
        ("event_cluster_id", "duplicate:event_cluster_id"),
        ("work_or_person", "duplicate:work_or_person"),
        ("content_map", "duplicate:content_map"),
        ("candidate_id", "duplicate:candidate_id"),
    )
    for field, error in checks:
        if _text(left.get(field)) == _text(right.get(field)):
            errors.append(error)
    if (
        _text(left.get("work_or_person")) in history_works
        or _text(right.get("work_or_person")) in history_works
    ):
        errors.append("history:work_or_person")
    return errors


def _quality_errors(candidate: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in (
        "candidate_id", "content_map", "event_cluster_id", "work_or_person",
        "selection_reason", "reader_gap",
    ):
        if not _text(candidate.get(field)):
            errors.append(f"missing:{field}")
    if (
        _text(candidate.get("freshness_window"))
        and _text(candidate.get("freshness_window")) not in _FRESHNESS_TO_ROLE
    ):
        errors.append("invalid:freshness_window")
    score = candidate.get("content_value_score")
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
        or not 1 <= score <= 5
    ):
        errors.append("invalid:content_value_score")
    if _text(candidate.get("evidence_readiness")) not in _READINESS_PRIORITY:
        errors.append("invalid:evidence_readiness")
    return errors


def _priority(pair: tuple[Mapping[str, Any], Mapping[str, Any]]) -> tuple[float, int]:
    return (
        sum(float(item["content_value_score"]) for item in pair),
        sum(_READINESS_PRIORITY[item["evidence_readiness"]] for item in pair),
    )


def build_daily_portfolio(
    candidates: object,
    history: object,
    *,
    profile: str = "two_article_daily",
    run_id: str,
    planned_at: str,
) -> dict[str, Any]:
    candidate_items = _sequence(candidates)
    normalized: list[dict[str, Any]] = []
    input_errors: list[str] = []
    if candidate_items is None:
        input_errors.append("invalid:candidates")
    else:
        for item in candidate_items:
            if not isinstance(item, Mapping):
                input_errors.append("invalid:candidate")
            else:
                normalized.append(_normalize(item))
    history_works, history_errors = _history_works(history)
    input_errors.extend(history_errors)
    if profile != "two_article_daily":
        input_errors.append(f"unsupported:profile:{profile}")
    roles = [_role(candidate) for candidate in normalized]
    missing: list[str] = []
    if not any("flow" in role for role in roles):
        missing.append("missing:flow")
    if not any({"depth", "evergreen"} & role for role in roles):
        missing.append("missing:depth_or_evergreen")
    valid: list[tuple[int, tuple[Mapping[str, Any], Mapping[str, Any]]]] = []
    rejected: list[str] = []
    for index, pair in enumerate(combinations(normalized, 2)):
        if not any("flow" in _role(item) for item in pair):
            continue
        if not any({"depth", "evergreen"} & _role(item) for item in pair):
            continue
        errors = _pair_errors(pair, history_works)
        errors.extend(error for item in pair for error in _quality_errors(item))
        if errors:
            rejected.extend(errors)
            continue
        valid.append((index, pair))
    selected: tuple[Mapping[str, Any], Mapping[str, Any]] | None = None
    if not input_errors and not missing and valid:
        selected = max(valid, key=lambda entry: (_priority(entry[1]), -entry[0]))[1]
    elif not valid:
        missing.append("no_valid_combination")
    selected_articles = [] if selected is None else [dict(item) for item in selected]
    payload = {
        "profile": profile,
        "decision": "selected" if selected is not None else "needs_controller",
        "selected_article_ids": [item["candidate_id"] for item in selected_articles],
        "selected_articles": selected_articles,
        "candidate_count": len(normalized),
        "missing_constraints": list(dict.fromkeys([*input_errors, *missing, *rejected])),
        "publication_authorization": "not_authorized",
    }
    return new_artifact_envelope(
        "v4-portfolio-plan-v1", run_id, payload, generated_at=planned_at
    )


def validate_portfolio(plan: object) -> list[str]:
    if not isinstance(plan, Mapping):
        return ["invalid:portfolio"]
    if set(plan) != {"schema_version", "run_id", "generated_at", "input_hashes", "payload"}:
        return ["invalid:portfolio"]
    payload = plan.get("payload")
    if not isinstance(payload, Mapping):
        return ["invalid:payload"]
    errors = validate_artifact_envelope(
        plan, "v4-portfolio-plan-v1", run_id=plan.get("run_id", "")
    )
    if payload.get("profile") != "two_article_daily":
        errors.append("invalid:profile")
    authorization = payload.get("publication_authorization")
    if not isinstance(authorization, str) or authorization != "not_authorized":
        errors.append("publication_authorization_must_be_not_authorized")
    decision = payload.get("decision")
    if decision not in {"selected", "needs_controller"}:
        errors.append("invalid:decision")
    missing_constraints = payload.get("missing_constraints")
    if not isinstance(missing_constraints, list):
        errors.append("invalid:missing_constraints")
    else:
        for item in missing_constraints:
            if not isinstance(item, str):
                errors.append("invalid:missing_constraints_item")
            else:
                errors.append(item)
    selected_articles = payload.get("selected_articles")
    if not isinstance(selected_articles, list):
        errors.append("invalid:selected_articles")
        selected_articles = []
    elif any(not isinstance(article, Mapping) for article in selected_articles):
        errors.append("invalid:selected_articles_item")
    selected_ids = payload.get("selected_article_ids")
    if decision == "selected":
        if not isinstance(selected_ids, list):
            errors.append("invalid:selected_article_ids")
        elif (
            len(selected_ids) != 2
            or any(not isinstance(item, str) or not item.strip() for item in selected_ids)
            or len(set(selected_ids)) != 2
        ):
            errors.append("invalid:selected_article_ids")
        if len(selected_articles) != 2:
            errors.append("selected:requires_two_articles")
        if len(selected_articles) == 2 and all(
            isinstance(article, Mapping) for article in selected_articles
        ):
            errors.extend(
                error for article in selected_articles for error in _quality_errors(article)
            )
            errors.extend(_pair_errors((selected_articles[0], selected_articles[1]), set()))
            article_ids = [article.get("candidate_id") for article in selected_articles]
            if isinstance(selected_ids, list) and selected_ids != article_ids:
                errors.append("selected:article_ids_mismatch")
            roles = [_role(article) for article in selected_articles]
            if not any("flow" in role for role in roles):
                errors.append("missing:flow")
            if not any({"depth", "evergreen"} & role for role in roles):
                errors.append("missing:depth_or_evergreen")
    elif decision == "needs_controller" and selected_ids not in ([], None):
        errors.append("needs_controller:must_not_select_articles")
    return list(dict.fromkeys(error for error in errors if isinstance(error, str)))


def portfolio_gate_for_transition(plan: object, article_ids: object) -> list[str]:
    """Return blockers without changing V3 states or granting authorization."""

    errors = validate_portfolio(plan)
    payload = plan.get("payload") if isinstance(plan, Mapping) else None
    proposed_ids = _sequence(article_ids)
    if proposed_ids is None or len(proposed_ids) != 2 or any(
        not isinstance(item, str) or not item.strip() for item in proposed_ids
    ) or len(set(proposed_ids)) != 2:
        errors.append("invalid:article_ids")
    if not isinstance(payload, Mapping) or payload.get("decision") != "selected":
        errors.append("portfolio:not_selected")
    elif payload.get("selected_article_ids") != proposed_ids:
        errors.append("portfolio:article_ids_mismatch")
    return list(dict.fromkeys(errors))
