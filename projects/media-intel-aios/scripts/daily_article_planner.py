"""Opt-in, pure candidate planning for the daily article workflow.

This module only evaluates supplied ``Candidate`` objects. It performs no I/O,
fetching, writing, scheduling, delivery, rendering, or publishing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Iterable

from scripts.daily_article_workflow import Candidate


class PlannerReasonCode(StrEnum):
    INVALID_CANDIDATE = "INVALID_CANDIDATE"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    UNSUPPORTED_SOURCE_ROLE = "UNSUPPORTED_SOURCE_ROLE"
    INVALID_SEMANTIC_SLOT_CLASS = "INVALID_SEMANTIC_SLOT_CLASS"
    NON_INDEPENDENT_EVIDENCE = "NON_INDEPENDENT_EVIDENCE"
    STALE_CANDIDATE = "STALE_CANDIDATE"
    FUTURE_CANDIDATE = "FUTURE_CANDIDATE"
    WEAK_EVIDENCE = "WEAK_EVIDENCE"
    RISK_REQUIRES_INDEPENDENT_CONFIRMATION = "RISK_REQUIRES_INDEPENDENT_CONFIRMATION"
    RISK_REQUIRES_TWO_CONFIRMATION_GROUPS = "RISK_REQUIRES_TWO_CONFIRMATION_GROUPS"
    UNRESOLVED_EVIDENCE_CONFLICT = "UNRESOLVED_EVIDENCE_CONFLICT"
    DENIAL_OR_REBUTTAL_PRESENT = "DENIAL_OR_REBUTTAL_PRESENT"
    DUPLICATE_TOPIC_OR_ANGLE = "DUPLICATE_TOPIC_OR_ANGLE"
    MISSING_CURRENT_STRONG_A = "MISSING_CURRENT_STRONG_A"
    INSUFFICIENT_BC_CANDIDATES = "INSUFFICIENT_BC_CANDIDATES"
    INSUFFICIENT_CLASS_ALTERNATES = "INSUFFICIENT_CLASS_ALTERNATES"


class FreshnessBand(StrEnum):
    CURRENT = "CURRENT"
    BACKGROUND = "BACKGROUND"
    STALE = "STALE"


class EligibilityBand(StrEnum):
    STRONG = "STRONG"
    MEDIUM = "MEDIUM"
    WEAK = "WEAK"


@dataclass(frozen=True)
class CandidateRejection:
    candidate_id: str | None
    reason_codes: tuple[PlannerReasonCode, ...]


@dataclass(frozen=True)
class PlannedSlot:
    slot_type: str
    primary: Candidate
    alternates: tuple[Candidate, ...]


@dataclass(frozen=True)
class DailySlotPlan:
    slots: tuple[PlannedSlot, ...]
    rejections: tuple[CandidateRejection, ...]
    reason_codes: tuple[PlannerReasonCode, ...]


_ROLE_SCORES = {
    "confirmed_primary": 2,
    "confirmed_named_secondary": 1,
    "confirmed_secondary": 1,
    "discovery": 0,
}
_SEMANTIC_SLOT_CLASSES = frozenset({"A_current", "B_mature", "C_resurgent"})
_BC_SEMANTIC_SLOT_CLASSES = frozenset({"B_mature", "C_resurgent"})
_REQUIRED_TEXT_FIELDS = (
    "id", "topic_key", "angle_key", "headline", "claim", "entity", "source_url",
    "source_role", "publisher", "author_or_org", "evidence_quote", "locator",
    "independence_group", "denial_status", "strength", "state",
)
_BAND_RANK = {EligibilityBand.WEAK: 0, EligibilityBand.MEDIUM: 1, EligibilityBand.STRONG: 2}


def _require_aware_now(now: datetime) -> None:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")


def _freshness(candidate: Candidate, now: datetime) -> FreshnessBand:
    age_seconds = (now - candidate.published_at).total_seconds()
    if age_seconds <= 24 * 60 * 60:
        return FreshnessBand.CURRENT
    if age_seconds <= 72 * 60 * 60:
        return FreshnessBand.BACKGROUND
    return FreshnessBand.STALE


def _candidate_is_complete(candidate: Candidate) -> bool:
    return all(isinstance(getattr(candidate, field, None), str) and getattr(candidate, field).strip() for field in _REQUIRED_TEXT_FIELDS)


def _source_score(candidate: Candidate) -> int | None:
    return _ROLE_SCORES.get(candidate.source_role)


def _semantic_slot_class(candidate: Candidate) -> str | None:
    """Return the explicit bounded semantic class carried in ``strength``.

    B and C are interchangeable for alternates: either may use B_mature or
    C_resurgent. Freshness enforces recency only; it never assigns a class.
    """
    return candidate.strength if candidate.strength in _SEMANTIC_SLOT_CLASSES else None


def _representative(candidates: tuple[Candidate, ...], now: datetime) -> Candidate:
    """Prefer score, then freshness, then recency and stable locator ordering."""
    return min(
        candidates,
        key=lambda candidate: (
            -(_source_score(candidate) or 0),
            _freshness(candidate, now) != FreshnessBand.CURRENT,
            -candidate.published_at.timestamp(),
            candidate.locator,
            candidate.id,
        ),
    )


def _eligibility(candidates: tuple[Candidate, ...], now: datetime) -> tuple[EligibilityBand, tuple[PlannerReasonCode, ...]]:
    groups: dict[str, Candidate] = {}
    for candidate in candidates:
        prior = groups.get(candidate.independence_group)
        if prior is None or _representative((candidate, prior), now) == candidate:
            groups[candidate.independence_group] = candidate
    sources = tuple(groups.values())
    score = sum(_source_score(candidate) or 0 for candidate in sources)
    group_count = len(sources)
    has_primary = any((_source_score(candidate) or 0) == 2 for candidate in sources)
    if score >= 4 and group_count >= 2 and has_primary:
        band = EligibilityBand.STRONG
    elif score >= 2 and group_count >= 2:
        band = EligibilityBand.MEDIUM
    else:
        band = EligibilityBand.WEAK

    reasons: list[PlannerReasonCode] = []
    if group_count < 2:
        reasons.append(PlannerReasonCode.NON_INDEPENDENT_EVIDENCE)
    if any(candidate.risk_tags for candidate in candidates):
        confirmation_groups = {candidate.independence_group for candidate in sources if (_source_score(candidate) or 0) > 0}
        if len(confirmation_groups) < 2:
            reasons.extend((PlannerReasonCode.RISK_REQUIRES_INDEPENDENT_CONFIRMATION, PlannerReasonCode.RISK_REQUIRES_TWO_CONFIRMATION_GROUPS))
    if any(candidate.denial_status != "none" for candidate in candidates):
        reasons.append(PlannerReasonCode.DENIAL_OR_REBUTTAL_PRESENT)
    if any("EVIDENCE_CONFLICT" in candidate.reason_codes for candidate in candidates):
        reasons.append(PlannerReasonCode.UNRESOLVED_EVIDENCE_CONFLICT)
    representative = _representative(candidates, now)
    if _freshness(representative, now) == FreshnessBand.BACKGROUND:
        band = (EligibilityBand.WEAK, EligibilityBand.MEDIUM, EligibilityBand.STRONG)[max(0, _BAND_RANK[band] - 1)]
    if band == EligibilityBand.WEAK:
        reasons.append(PlannerReasonCode.WEAK_EVIDENCE)
    return band, tuple(dict.fromkeys(reasons))


def _validated_groups(candidates: Iterable[object], now: datetime) -> tuple[dict[tuple[str, str], tuple[Candidate, ...]], list[CandidateRejection]]:
    grouped: dict[tuple[str, str], list[Candidate]] = {}
    rejections: list[CandidateRejection] = []
    for raw in candidates:
        if not isinstance(raw, Candidate):
            rejections.append(CandidateRejection(None, (PlannerReasonCode.INVALID_CANDIDATE,)))
        elif not _candidate_is_complete(raw):
            rejections.append(CandidateRejection(raw.id, (PlannerReasonCode.MISSING_REQUIRED_FIELD,)))
        elif _source_score(raw) is None:
            rejections.append(CandidateRejection(raw.id, (PlannerReasonCode.UNSUPPORTED_SOURCE_ROLE,)))
        elif _semantic_slot_class(raw) is None:
            rejections.append(CandidateRejection(raw.id, (PlannerReasonCode.INVALID_SEMANTIC_SLOT_CLASS,)))
        elif (now - raw.published_at).total_seconds() < 0:
            rejections.append(CandidateRejection(raw.id, (PlannerReasonCode.FUTURE_CANDIDATE,)))
        elif _freshness(raw, now) == FreshnessBand.STALE:
            rejections.append(CandidateRejection(raw.id, (PlannerReasonCode.STALE_CANDIDATE,)))
        else:
            grouped.setdefault((raw.topic_key, raw.angle_key), []).append(raw)
    return {key: tuple(values) for key, values in grouped.items()}, rejections


def _eligible_deduped(groups: dict[tuple[str, str], tuple[Candidate, ...]], now: datetime) -> tuple[list[tuple[Candidate, EligibilityBand, FreshnessBand]], list[CandidateRejection]]:
    evaluated: list[tuple[Candidate, EligibilityBand, FreshnessBand, tuple[Candidate, ...]]] = []
    rejections: list[CandidateRejection] = []
    for values in groups.values():
        band, reasons = _eligibility(values, now)
        representative = _representative(values, now)
        if reasons:
            rejections.append(CandidateRejection(representative.id, reasons))
        else:
            evaluated.append((representative, band, _freshness(representative, now), values))

    normalized: list[tuple[Candidate, EligibilityBand, FreshnessBand]] = []
    used_topics: set[str] = set()
    used_angles: set[str] = set()
    for representative, band, freshness, values in sorted(
        evaluated,
        key=lambda item: (-_BAND_RANK[item[1]], item[2] != FreshnessBand.CURRENT, -(_source_score(item[0]) or 0), item[0].locator, item[0].id),
    ):
        if representative.topic_key in used_topics or representative.angle_key in used_angles:
            rejections.extend(CandidateRejection(candidate.id, (PlannerReasonCode.DUPLICATE_TOPIC_OR_ANGLE,)) for candidate in values)
            continue
        normalized.append((representative, band, freshness))
        used_topics.add(representative.topic_key)
        used_angles.add(representative.angle_key)
        rejections.extend(
            CandidateRejection(candidate.id, (PlannerReasonCode.DUPLICATE_TOPIC_OR_ANGLE,))
            for candidate in values if candidate.id != representative.id
        )
    return normalized, rejections


def plan_daily_slots(candidates: Iterable[object], *, now: datetime) -> DailySlotPlan:
    """Build an all-or-nothing 1A + 2B/C plan with semantic-class alternates.

    ``Candidate.strength`` must be A_current, B_mature, or C_resurgent. A uses
    A_current; B/C use the shared B↔C mature/resurgent pool.
    """
    _require_aware_now(now)
    groups, rejections = _validated_groups(candidates, now)
    eligible, dedupe_rejections = _eligible_deduped(groups, now)
    rejections.extend(dedupe_rejections)

    a_options = [
        item[0] for item in eligible
        if item[1] == EligibilityBand.STRONG
        and item[2] == FreshnessBand.CURRENT
        and _semantic_slot_class(item[0]) == "A_current"
    ]
    if not a_options:
        return DailySlotPlan((), tuple(rejections), (PlannerReasonCode.MISSING_CURRENT_STRONG_A,))
    primary_a = a_options[0]
    bc_options = [
        item[0] for item in eligible
        if item[2] == FreshnessBand.BACKGROUND
        and _semantic_slot_class(item[0]) in _BC_SEMANTIC_SLOT_CLASSES
        and item[0].id != primary_a.id
    ]
    if len(bc_options) < 2:
        return DailySlotPlan((), tuple(rejections), (PlannerReasonCode.INSUFFICIENT_BC_CANDIDATES,))

    primaries = (primary_a, bc_options[0], bc_options[1])
    a_alternates = [candidate for candidate in a_options if candidate.id != primary_a.id]
    bc_alternates = bc_options[2:]
    if len(a_alternates) < 2 or len(bc_alternates) < 4:
        return DailySlotPlan((), tuple(rejections), (PlannerReasonCode.INSUFFICIENT_CLASS_ALTERNATES,))
    slots = (
        PlannedSlot("A", primary_a, tuple(a_alternates[:2])),
        PlannedSlot("B", primaries[1], tuple(bc_alternates[:2])),
        PlannedSlot("C", primaries[2], tuple(bc_alternates[2:4])),
    )
    return DailySlotPlan(slots, tuple(rejections), ())
