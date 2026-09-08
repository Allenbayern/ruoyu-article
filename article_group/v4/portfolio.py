"""Deterministic, offline composition of the V4 daily article portfolio."""

from __future__ import annotations

from itertools import combinations
from typing import Any, Mapping

from .contracts import new_artifact_envelope

_READINESS_PRIORITY = {"high": 2, "medium": 1, "low": 0}


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _role(candidate: Mapping[str, Any]) -> set[str]:
    values = {
        _text(candidate.get("content_map")).lower(),
        _text(candidate.get("traffic_class")).lower(),
        _text(candidate.get("topic_mode")).lower(),
    }
    roles: set[str] = set()
    if values & {"flow", "current", "same-day", "release_event", "a"}:
        roles.add("flow")
    if values & {"depth", "deep", "b", "revisit", "craft"}:
        roles.add("depth")
    if values & {"evergreen", "revival", "revisit"}:
        roles.add("evergreen")
    return roles


def _normalize(candidate: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "candidate_id",
        "content_map",
        "topic_mode",
        "event_cluster_id",
        "work_or_person",
        "traffic_class",
        "selection_reason",
        "reader_gap",
        "content_value_score",
        "evidence_readiness",
    )
    result = {field: candidate.get(field) for field in fields}
    result["candidate_id"] = _text(result["candidate_id"])
    for field in fields[1:8]:
        result[field] = _text(result[field])
    result["evidence_readiness"] = _text(result["evidence_readiness"]).lower()
    return result


def _history_works(history: object) -> set[str]:
    works: set[str] = set()
    if not isinstance(history, list):
        return works
    for item in history:
        if not isinstance(item, Mapping):
            continue
        articles = item.get("selected_articles", item.get("selected_candidates", []))
        if isinstance(articles, list):
            for article in articles:
                if isinstance(article, Mapping) and _text(article.get("work_or_person")):
                    works.add(_text(article["work_or_person"]))
        if isinstance(item.get("work_or_person"), str):
            works.add(_text(item["work_or_person"]))
    return works


def _pair_errors(
    pair: tuple[Mapping[str, Any], Mapping[str, Any]], history_works: set[str]
) -> list[str]:
    left, right = pair
    errors: list[str] = []
    if (
        _text(left.get("event_cluster_id"))
        and left.get("event_cluster_id") == right.get("event_cluster_id")
    ):
        errors.append("duplicate:event_cluster_id")
    if _text(left.get("work_or_person")) and left.get("work_or_person") == right.get("work_or_person"):
        errors.append("duplicate:work_or_person")
    if (
        _text(left.get("work_or_person")) in history_works
        or _text(right.get("work_or_person")) in history_works
    ):
        errors.append("history:work_or_person")
    return errors


def _priority(pair: tuple[Mapping[str, Any], Mapping[str, Any]]) -> tuple[int, int]:
    value = sum(
        item.get("content_value_score") or 0
        for item in pair
        if isinstance(item.get("content_value_score"), (int, float))
    )
    readiness = sum(
        _READINESS_PRIORITY.get(_text(item.get("evidence_readiness")).lower(), -1)
        for item in pair
    )
    return (value, readiness)


def build_daily_portfolio(
    candidates: object,
    history: object,
    *,
    profile: str = "two_article_daily",
    run_id: str,
    planned_at: str,
) -> dict[str, Any]:
    """Compose a supplied candidate pool; this function never discovers topics."""

    normalized = (
        [
            _normalize(candidate)
            for candidate in candidates
            if isinstance(candidate, Mapping)
        ]
        if isinstance(candidates, list)
        else []
    )
    missing: list[str] = []
    if profile != "two_article_daily":
        missing.append(f"unsupported:profile:{profile}")

    roles = [_role(candidate) for candidate in normalized]
    if not any("flow" in item for item in roles):
        missing.append("missing:flow")
    if not any("depth" in item for item in roles):
        missing.append("missing:depth")
    if not any("evergreen" in item for item in roles):
        missing.append("missing:evergreen")

    history_works = _history_works(history)
    valid: list[tuple[int, tuple[Mapping[str, Any], Mapping[str, Any]]]] = []
    rejected: list[str] = []
    for index, pair in enumerate(combinations(normalized, 2)):
        pair_roles = _role(pair[0]) | _role(pair[1])
        if not ({"flow", "depth"} <= pair_roles):
            continue
        errors = _pair_errors(pair, history_works)
        if errors:
            rejected.extend(errors)
            continue
        if not any("flow" in _role(item) for item in pair) or not any(
            "depth" in _role(item) and "evergreen" in _role(item)
            for item in pair
        ):
            rejected.extend(["missing:evergreen", "missing:depth"])
            continue
        valid.append((index, pair))

    selected: tuple[Mapping[str, Any], Mapping[str, Any]] | None = None
    if not missing and valid:
        selected = max(valid, key=lambda entry: (_priority(entry[1]), -entry[0]))[1]
    elif not valid:
        missing.append("no_valid_combination")

    if selected is None:
        selected_articles: list[dict[str, Any]] = []
    else:
        selected_articles = [dict(item) for item in selected]
    constraint_errors = list(dict.fromkeys([*missing, *rejected]))
    plan = {
        **new_artifact_envelope(
            "v4-portfolio-plan-v1",
            run_id,
            {},
            generated_at=planned_at,
        ),
        "profile": profile,
        "decision": "selected" if selected is not None else "needs_controller",
        "selected_article_ids": [item["candidate_id"] for item in selected_articles],
        "selected_articles": selected_articles,
        "candidate_count": len(normalized),
        "missing_constraints": constraint_errors,
        "publication_authorization": "not_authorized",
    }
    return plan


def validate_portfolio(plan: object) -> list[str]:
    if not isinstance(plan, Mapping):
        return ["invalid:portfolio"]
    errors: list[str] = []
    if plan.get("publication_authorization", "not_authorized") != "not_authorized":
        errors.append("publication_authorization_must_be_not_authorized")
    if plan.get("decision") == "selected":
        articles = plan.get("selected_articles")
        if not isinstance(articles, list) or len(articles) != 2:
            errors.append("selected:requires_two_articles")
        else:
            errors.extend(_pair_errors((articles[0], articles[1]), set()))
            roles = [_role(article) if isinstance(article, Mapping) else set() for article in articles]
            if not any("flow" in role for role in roles):
                errors.append("missing:flow")
            if not any("depth" in role and "evergreen" in role for role in roles):
                errors.append("missing:evergreen")
    elif plan.get("decision") != "needs_controller":
        errors.append("invalid:decision")
    if plan.get("decision") == "needs_controller" and plan.get("selected_article_ids"):
        errors.append("needs_controller:must_not_select_articles")
    if isinstance(plan.get("missing_constraints"), list):
        errors.extend(
            item
            for item in plan["missing_constraints"]
            if item not in errors
        )
    else:
        errors.append("invalid:missing_constraints")
    return list(dict.fromkeys(errors))


def portfolio_gate_for_transition(plan: object, article_ids: object) -> list[str]:
    """Return blockers for a caller's transition proposal; never changes V3 states."""

    errors = validate_portfolio(plan)
    if not isinstance(plan, Mapping) or plan.get("decision") != "selected":
        errors.append("portfolio:not_selected")
    if isinstance(plan, Mapping) and plan.get("selected_article_ids") != article_ids:
        errors.append("portfolio:article_ids_mismatch")
    return list(dict.fromkeys(errors))
