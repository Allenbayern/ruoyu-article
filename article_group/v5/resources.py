"""Bounded, offline resource recommendations for V5 candidates.

This module only describes what the controller may allocate.  It never starts
a crawl, changes a topic, invokes Sol, or applies a budget to a scheduler.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import math
from typing import Any

from .contracts import (
    PUBLICATION_AUTHORIZATION,
    new_artifact_envelope,
    payload_of,
    validate_v5_artifact_envelope,
)


_SCHEMA_VERSION = "v5-resource-plan-v1"
_ACTIONS = frozenset(
    {"full_capture", "evidence_recovery", "stop", "light_capture", "sol_review"}
)
_DEFAULT_COSTS = {
    "full_capture": 8.0,
    "evidence_recovery": 6.0,
    "stop": 0.0,
    "light_capture": 2.0,
    "sol_review": 4.0,
}
_HIGH_VALUE = 0.70
_HIGH_READINESS = 0.70
_LOW_VALUE = 0.40
_HIGH_RISK = 0.70
_HIGH_POTENTIAL = 0.70
_HIGH_CONTROVERSY = 0.70


def _is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _score(candidate: Mapping[str, Any], fields: Sequence[str]) -> float:
    for field in fields:
        value = candidate.get(field)
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if _is_number(value):
            return min(1.0, max(0.0, float(value)))
        if isinstance(value, str):
            normalized = value.strip().casefold()
            if normalized in {"high", "critical", "ready", "full", "yes", "true"}:
                return 1.0
            if normalized in {"medium", "partial", "normal"}:
                return 0.5
            if normalized in {"low", "unready", "none", "no", "false"}:
                return 0.0
    return 0.0


def _action_for(candidate: Mapping[str, Any]) -> tuple[str, str, bool]:
    value = _score(candidate, ("value_score", "value", "priority_score", "priority"))
    readiness = _score(
        candidate,
        ("evidence_readiness", "readiness", "evidence_ready"),
    )
    potential = _score(
        candidate,
        ("potential_score", "potential", "traffic_potential"),
    )
    controversy = _score(
        candidate,
        ("controversy_score", "controversy", "controversy_risk"),
    )
    risk = _score(candidate, ("risk_score", "risk", "risk_level"))

    # Safety and human review are explicit tiers.  A high-potential/high-
    # controversy item goes to Sol even when it is also valuable; a low-value
    # high-risk item is stopped before any capture recommendation.
    if potential >= _HIGH_POTENTIAL and controversy >= _HIGH_CONTROVERSY:
        return "sol_review", "高潜力且高争议，先交 Sol 做风险复核", True
    if value < _LOW_VALUE and risk >= _HIGH_RISK:
        return "stop", "价值不足且风险高，停止投入并交 controller 判断", True
    if value >= _HIGH_VALUE and readiness >= _HIGH_READINESS:
        return "full_capture", "价值和证据就绪度都高，建议完整补材", False
    if value >= _HIGH_VALUE:
        return "evidence_recovery", "价值高但证据未就绪，优先补证", True
    return "light_capture", "普通候选，采用轻量材料采集", False


def _owner(candidate: Mapping[str, Any], action: str) -> str:
    configured = _text(candidate.get("owner"))
    if configured:
        return configured
    return {
        "full_capture": "Luna",
        "evidence_recovery": "Luna",
        "stop": "controller",
        "light_capture": "Luna",
        "sol_review": "Sol",
    }[action]


def _estimated_cost(candidate: Mapping[str, Any], action: str) -> float:
    if action == "stop":
        return 0.0
    configured = candidate.get("estimated_cost")
    if _is_number(configured) and float(configured) >= 0:
        return round(float(configured), 6)
    return _DEFAULT_COSTS[action]


def plan_resource_allocation(
    candidates: Sequence[Mapping[str, Any]],
    *,
    budget: float,
    run_id: str,
    generated_at: str,
) -> dict[str, Any]:
    """Build a controller-only resource recommendation plan."""

    if isinstance(candidates, (str, bytes, bytearray)) or not isinstance(candidates, Sequence):
        raise ValueError("invalid_candidates")
    if not _is_number(budget) or float(budget) < 0:
        raise ValueError("invalid_budget")

    seen: set[str] = set()
    remaining = float(budget)
    allocations: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            raise ValueError(f"invalid_candidate:{index}")
        candidate_id = _text(candidate.get("candidate_id"))
        if not candidate_id:
            raise ValueError(f"missing_candidate_id:{index}")
        if candidate_id in seen:
            raise ValueError(f"duplicate_candidate_id:{candidate_id}")
        seen.add(candidate_id)
        action, reason, controller_review_required = _action_for(candidate)
        estimated_cost = _estimated_cost(candidate, action)
        allocated_cost = min(estimated_cost, max(0.0, remaining))
        if allocated_cost < estimated_cost and action != "stop":
            reason = f"{reason}；预算不足，实际分配受限"
        remaining -= allocated_cost
        allocations.append(
            {
                "candidate_id": candidate_id,
                "action": action,
                "owner": _owner(candidate, action),
                "estimated_cost": estimated_cost,
                "allocated_cost": round(allocated_cost, 6),
                "reason": reason,
                "controller_review_required": controller_review_required,
                "auto_apply": False,
                "signals": {
                    "value_score": _score(candidate, ("value_score", "value", "priority_score", "priority")),
                    "evidence_readiness": _score(candidate, ("evidence_readiness", "readiness", "evidence_ready")),
                    "potential_score": _score(candidate, ("potential_score", "potential", "traffic_potential")),
                    "controversy_score": _score(candidate, ("controversy_score", "controversy", "controversy_risk")),
                    "risk_score": _score(candidate, ("risk_score", "risk", "risk_level")),
                },
            }
        )

    total_estimated = round(sum(item["estimated_cost"] for item in allocations), 6)
    total_allocated = round(sum(item["allocated_cost"] for item in allocations), 6)
    payload = {
        "budget": round(float(budget), 6),
        "allocations": allocations,
        "allocation_count": len(allocations),
        "total_estimated_cost": total_estimated,
        "total_allocated_cost": total_allocated,
        "remaining_budget": round(max(0.0, remaining), 6),
        "budget_status": "within_budget" if total_estimated <= float(budget) else "budget_constrained",
        "controller_only": True,
        "auto_apply": False,
        "publication_authorization": PUBLICATION_AUTHORIZATION,
    }
    return new_artifact_envelope(
        _SCHEMA_VERSION,
        run_id,
        payload,
        generated_at=generated_at,
    )


def validate_resource_plan(plan: Mapping[str, Any]) -> list[str]:
    """Return stable validation errors for a resource-plan artifact."""

    if not isinstance(plan, Mapping):
        return ["invalid:artifact"]
    run_id = plan.get("run_id") if isinstance(plan.get("run_id"), str) else ""
    errors = validate_v5_artifact_envelope(
        plan,
        _SCHEMA_VERSION,
        run_id=run_id,
    )
    payload = payload_of(plan)
    if not isinstance(payload, Mapping):
        return list(dict.fromkeys(errors))
    required = (
        "budget",
        "allocations",
        "allocation_count",
        "total_estimated_cost",
        "total_allocated_cost",
        "remaining_budget",
        "budget_status",
        "controller_only",
        "auto_apply",
        "publication_authorization",
    )
    for field in required:
        if field not in payload:
            errors.append(f"missing:payload:{field}")
    budget = payload.get("budget")
    if not _is_number(budget) or float(budget) < 0:
        errors.append("invalid:payload:budget")
    allocations = payload.get("allocations")
    if not isinstance(allocations, list):
        errors.append("invalid:payload:allocations")
        allocations = []
    count = payload.get("allocation_count")
    if isinstance(count, bool) or not isinstance(count, int) or count != len(allocations):
        errors.append("mismatch:payload:allocation_count")
    if payload.get("budget_status") not in {"within_budget", "budget_constrained"}:
        errors.append("invalid:payload:budget_status")
    if payload.get("controller_only") is not True:
        errors.append("controller_only_must_be_true")
    if payload.get("auto_apply") is not False:
        errors.append("auto_apply_must_be_false")
    if payload.get("publication_authorization") != PUBLICATION_AUTHORIZATION:
        errors.append("publication_authorization_must_be_not_authorized")

    seen: set[str] = set()
    estimated_total = 0.0
    allocated_total = 0.0
    for index, allocation in enumerate(allocations):
        prefix = f"allocation:{index}"
        if not isinstance(allocation, Mapping):
            errors.append(f"invalid:{prefix}")
            continue
        candidate_id = allocation.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            errors.append(f"invalid:{prefix}:candidate_id")
        elif candidate_id in seen:
            errors.append(f"duplicate:{prefix}:candidate_id")
        else:
            seen.add(candidate_id)
        if allocation.get("action") not in _ACTIONS:
            errors.append(f"invalid:{prefix}:action")
        for field in ("owner", "reason"):
            if not isinstance(allocation.get(field), str) or not allocation[field].strip():
                errors.append(f"invalid:{prefix}:{field}")
        for field in ("estimated_cost", "allocated_cost"):
            value = allocation.get(field)
            if not _is_number(value) or float(value) < 0:
                errors.append(f"invalid:{prefix}:{field}")
        estimated = allocation.get("estimated_cost")
        allocated = allocation.get("allocated_cost")
        if _is_number(estimated) and _is_number(allocated):
            estimated_total += float(estimated)
            allocated_total += float(allocated)
            if float(allocated) > float(estimated) + 1e-9:
                errors.append(f"invalid:{prefix}:allocated_cost_exceeds_estimate")
        if not isinstance(allocation.get("controller_review_required"), bool):
            errors.append(f"invalid:{prefix}:controller_review_required")
        if allocation.get("auto_apply") is not False:
            errors.append("auto_apply_must_be_false")
        signals = allocation.get("signals")
        if not isinstance(signals, Mapping):
            errors.append(f"invalid:{prefix}:signals")
        else:
            for signal in ("value_score", "evidence_readiness", "potential_score", "controversy_score", "risk_score"):
                if not _is_number(signals.get(signal)) or not 0 <= float(signals[signal]) <= 1:
                    errors.append(f"invalid:{prefix}:signals:{signal}")

    for field, value, expected in (
        ("total_estimated_cost", payload.get("total_estimated_cost"), estimated_total),
        ("total_allocated_cost", payload.get("total_allocated_cost"), allocated_total),
    ):
        if not _is_number(value) or abs(float(value) - expected) > 1e-6:
            errors.append(f"mismatch:payload:{field}")
    remaining = payload.get("remaining_budget")
    if not _is_number(remaining) or float(remaining) < 0:
        errors.append("invalid:payload:remaining_budget")
    elif _is_number(budget) and abs(float(remaining) - max(0.0, float(budget) - allocated_total)) > 1e-6:
        errors.append("mismatch:payload:remaining_budget")
    if _is_number(budget) and allocated_total > float(budget) + 1e-6:
        errors.append("budget_exceeded")
    return list(dict.fromkeys(errors))


__all__ = ["plan_resource_allocation", "validate_resource_plan"]
