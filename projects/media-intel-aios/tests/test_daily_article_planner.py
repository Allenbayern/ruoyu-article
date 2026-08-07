from datetime import datetime, timedelta, timezone

import pytest

from scripts.daily_article_planner import PlannerReasonCode, plan_daily_slots
from scripts.daily_article_workflow import Candidate


UTC = timezone.utc
NOW = datetime(2026, 7, 16, 12, tzinfo=UTC)


def candidate(candidate_id, *, topic, angle, group, role="confirmed_primary", age_hours=4, risk_tags=(), strength=None, **changes):
    published_at = NOW - timedelta(hours=age_hours)
    if strength is None:
        strength = "A_current" if age_hours <= 24 else "B_mature"
    values = {
        "id": candidate_id,
        "scan_hour": NOW,
        "topic_key": topic,
        "angle_key": angle,
        "headline": f"标题 {candidate_id}",
        "claim": f"可核验主张 {candidate_id}",
        "entity": "示例实体",
        "event_time": published_at,
        "first_seen_at": published_at,
        "source_url": f"https://example.test/{candidate_id}",
        "source_role": role,
        "publisher": f"机构 {group}",
        "author_or_org": f"记者 {candidate_id}",
        "published_at": published_at,
        "evidence_quote": f"可核验摘录 {candidate_id}",
        "locator": "article > p:nth-of-type(2)",
        "independence_group": group,
        "risk_tags": risk_tags,
        "denial_status": "none",
        "strength": strength,
        "state": "S2_VERIFICATION",
        "reason_codes": (),
    }
    values.update(changes)
    return Candidate(**values)


def strong_group(prefix, *, topic, angle, age_hours=4, strength=None):
    return (
        candidate(f"{prefix}-primary-a", topic=topic, angle=angle, group=f"{prefix}-a", age_hours=age_hours, strength=strength),
        candidate(f"{prefix}-primary-b", topic=topic, angle=angle, group=f"{prefix}-b", age_hours=age_hours, strength=strength),
    )


def complete_plan_candidates():
    return (
        *strong_group("a", topic="release:a", angle="release:a:current", age_hours=1),
        *strong_group("a-alt-1", topic="release:a-alt-1", angle="release:a-alt-1:current", age_hours=2),
        *strong_group("a-alt-2", topic="release:a-alt-2", angle="release:a-alt-2:current", age_hours=3),
        *strong_group("b", topic="catalog:b", angle="catalog:b:revival", age_hours=48),
        *strong_group("c", topic="catalog:c", angle="catalog:c:revival", age_hours=48),
        *strong_group("bc-alt-1", topic="catalog:alt-1", angle="catalog:alt-1:revival", age_hours=48),
        *strong_group("bc-alt-2", topic="catalog:alt-2", angle="catalog:alt-2:revival", age_hours=48),
        *strong_group("bc-alt-3", topic="catalog:alt-3", angle="catalog:alt-3:revival", age_hours=48),
        *strong_group("bc-alt-4", topic="catalog:alt-4", angle="catalog:alt-4:revival", age_hours=48),
    )


def test_planner_selects_one_current_strong_a_and_two_distinct_b_or_c_slots_with_alternates():
    candidates = complete_plan_candidates()

    plan = plan_daily_slots(candidates, now=NOW)

    assert plan.reason_codes == ()
    assert tuple(slot.slot_type for slot in plan.slots) == ("A", "B", "C")
    assert plan.slots[0].primary.published_at >= NOW - timedelta(hours=24)
    assert all(25 <= (NOW - slot.primary.published_at).total_seconds() / 3600 <= 72 for slot in plan.slots[1:])
    assert all(len(slot.alternates) == 2 for slot in plan.slots)
    assert len({alternate.id for slot in plan.slots for alternate in slot.alternates}) == 6
    assert all(alternate.topic_key != slot.primary.topic_key for slot in plan.slots for alternate in slot.alternates)
    assert all(alternate.published_at >= NOW - timedelta(hours=24) for alternate in plan.slots[0].alternates)
    assert all(25 <= (NOW - alternate.published_at).total_seconds() / 3600 <= 72 for slot in plan.slots[1:] for alternate in slot.alternates)


@pytest.mark.parametrize(
    ("age_hours", "expected_reason"),
    ((-1, "FUTURE_CANDIDATE"), (72.0001, PlannerReasonCode.STALE_CANDIDATE)),
)
def test_planner_rejects_future_and_over_72_hour_candidates(age_hours, expected_reason):
    plan = plan_daily_slots(
        (*complete_plan_candidates(), *strong_group("chronology", topic="chronology", angle="chronology", age_hours=age_hours)),
        now=NOW,
    )

    assert any(expected_reason in rejection.reason_codes for rejection in plan.rejections)


def test_planner_downgrades_25_to_72_hour_evidence_before_classification():
    candidates = (
        *strong_group("current-a", topic="release:a", angle="release:a:current", age_hours=24),
        *strong_group("background", topic="catalog:background", angle="catalog:background:revival", age_hours=25),
    )

    plan = plan_daily_slots(candidates, now=NOW)

    assert plan.slots == ()
    assert plan.reason_codes == (PlannerReasonCode.INSUFFICIENT_BC_CANDIDATES,)
    assert not any(PlannerReasonCode.WEAK_EVIDENCE in rejection.reason_codes for rejection in plan.rejections)


def test_planner_fails_closed_when_any_slot_lacks_two_same_class_non_reused_alternates():
    plan = plan_daily_slots(complete_plan_candidates()[:-2], now=NOW)

    assert plan.slots == ()
    assert plan.reason_codes == ("INSUFFICIENT_CLASS_ALTERNATES",)


def test_planner_requires_explicit_semantic_slot_classes_not_age_for_b_or_c():
    candidates = (
        *strong_group("a", topic="release:a", angle="release:a:current", age_hours=1, strength="A_current"),
        *strong_group("a-alt-1", topic="release:a-alt-1", angle="release:a-alt-1:current", age_hours=2, strength="A_current"),
        *strong_group("a-alt-2", topic="release:a-alt-2", angle="release:a-alt-2:current", age_hours=3, strength="A_current"),
        *strong_group("breaking-48h", topic="breaking", angle="breaking:current", age_hours=48, strength="A_current"),
        *strong_group("mature", topic="catalog:mature", angle="catalog:mature", age_hours=48, strength="B_mature"),
        *strong_group("resurgent", topic="catalog:resurgent", angle="catalog:resurgent", age_hours=48, strength="C_resurgent"),
        *strong_group("bc-alt-1", topic="catalog:alt-1", angle="catalog:alt-1", age_hours=48, strength="B_mature"),
        *strong_group("bc-alt-2", topic="catalog:alt-2", angle="catalog:alt-2", age_hours=48, strength="C_resurgent"),
        *strong_group("bc-alt-3", topic="catalog:alt-3", angle="catalog:alt-3", age_hours=48, strength="B_mature"),
        *strong_group("bc-alt-4", topic="catalog:alt-4", angle="catalog:alt-4", age_hours=48, strength="C_resurgent"),
    )

    plan = plan_daily_slots(candidates, now=NOW)

    assert plan.reason_codes == ()
    assert plan.slots[1].primary.strength in {"B_mature", "C_resurgent"}
    assert plan.slots[2].primary.strength in {"B_mature", "C_resurgent"}
    assert all(slot.primary.id != "breaking-48h-primary-a" for slot in plan.slots[1:])
    alternate_ids = {alternate.id for slot in plan.slots for alternate in slot.alternates}
    assert len(alternate_ids) == 6
    assert alternate_ids.isdisjoint({slot.primary.id for slot in plan.slots})
    # B and C share a mature/resurgent pool: either semantic class may alternate either slot.
    assert all(alternate.strength in {"B_mature", "C_resurgent"} for slot in plan.slots[1:] for alternate in slot.alternates)


@pytest.mark.parametrize("strength", ("strong", "D_other"))
def test_planner_fails_closed_for_missing_or_invalid_semantic_slot_class(strength):
    invalid = candidate("invalid-class", topic="invalid", angle="invalid", group="invalid-a", strength=strength)

    plan = plan_daily_slots((*complete_plan_candidates(), invalid), now=NOW)

    assert any(
        rejection.candidate_id == "invalid-class"
        and PlannerReasonCode.INVALID_SEMANTIC_SLOT_CLASS in rejection.reason_codes
        for rejection in plan.rejections
    )


def test_planner_rejects_complete_unknown_source_role_with_precise_reason():
    unsupported = candidate("unsupported-role", topic="unsupported", angle="unsupported", group="unsupported-a", role="partner_wire")

    plan = plan_daily_slots((*complete_plan_candidates(), unsupported), now=NOW)

    rejection = next(rejection for rejection in plan.rejections if rejection.candidate_id == "unsupported-role")
    assert rejection.reason_codes == (PlannerReasonCode.UNSUPPORTED_SOURCE_ROLE,)


@pytest.mark.parametrize(
    "changes, expected_reason",
    (
        ({"risk_tags": ("rumor",), "source_role": "discovery"}, "RISK_REQUIRES_TWO_CONFIRMATION_GROUPS"),
        ({"risk_tags": ("privacy",), "denial_status": "denied"}, "DENIAL_OR_REBUTTAL_PRESENT"),
        ({"reason_codes": ("EVIDENCE_CONFLICT",)}, "UNRESOLVED_EVIDENCE_CONFLICT"),
    ),
)
def test_planner_rejects_risk_without_two_confirmation_groups_conflicts_and_denials(changes, expected_reason):
    risky = strong_group("risky", topic="risky", angle="risky", age_hours=48)
    replacements = tuple(
        candidate(
            item.id,
            topic=item.topic_key,
            angle=item.angle_key,
            group=item.independence_group,
            age_hours=48,
            **changes,
        )
        for item in risky
    )

    plan = plan_daily_slots((*complete_plan_candidates(), *replacements), now=NOW)

    assert any(expected_reason in rejection.reason_codes for rejection in plan.rejections)


def test_planner_dedupes_topic_and_angle_and_rejects_weak_stale_risky_and_invalid_candidates():
    candidates = (
        *strong_group("a", topic="release:a", angle="release:a:current"),
        *strong_group("a-alt-1", topic="release:a-alt-1", angle="release:a-alt-1:current"),
        *strong_group("a-alt-2", topic="release:a-alt-2", angle="release:a-alt-2:current"),
        *strong_group("duplicate", topic="release:a", angle="release:a:current"),
        *strong_group("b", topic="catalog:b", angle="catalog:b:revival", age_hours=48),
        *strong_group("c", topic="catalog:c", angle="catalog:c:revival", age_hours=48),
        *strong_group("bc-alt-1", topic="catalog:alt-1", angle="catalog:alt-1:revival", age_hours=48),
        *strong_group("bc-alt-2", topic="catalog:alt-2", angle="catalog:alt-2:revival", age_hours=48),
        *strong_group("bc-alt-3", topic="catalog:alt-3", angle="catalog:alt-3:revival", age_hours=48),
        *strong_group("bc-alt-4", topic="catalog:alt-4", angle="catalog:alt-4:revival", age_hours=48),
        candidate("weak", topic="weak", angle="weak", group="one-group"),
        *strong_group("stale", topic="stale", angle="stale", age_hours=73),
        candidate("rumor", topic="rumor", angle="rumor", group="rumor-only", risk_tags=("rumor",)),
        "not-a-candidate",
    )

    plan = plan_daily_slots(candidates, now=NOW)

    assert tuple(slot.slot_type for slot in plan.slots) == ("A", "B", "C")
    rejection_codes = {code for rejection in plan.rejections for code in rejection.reason_codes}
    assert PlannerReasonCode.DUPLICATE_TOPIC_OR_ANGLE in rejection_codes
    assert PlannerReasonCode.WEAK_EVIDENCE in rejection_codes
    assert PlannerReasonCode.STALE_CANDIDATE in rejection_codes
    assert PlannerReasonCode.RISK_REQUIRES_INDEPENDENT_CONFIRMATION in rejection_codes
    assert PlannerReasonCode.INVALID_CANDIDATE in rejection_codes


def test_planner_treats_a_repeated_topic_or_angle_as_a_duplicate_even_when_the_other_key_differs():
    candidates = (
        *strong_group("a", topic="release:a", angle="release:a:current"),
        *strong_group("a-alt-1", topic="release:a-alt-1", angle="release:a-alt-1:current"),
        *strong_group("a-alt-2", topic="release:a-alt-2", angle="release:a-alt-2:current"),
        *strong_group("b", topic="catalog:b", angle="catalog:b:first", age_hours=48),
        *strong_group("aa-topic-duplicate", topic="catalog:b", angle="catalog:b:second", age_hours=48),
        *strong_group("c", topic="catalog:c", angle="catalog:c:revival", age_hours=48),
        *strong_group("ab-angle-duplicate", topic="catalog:d", angle="catalog:c:revival", age_hours=48),
        *strong_group("bc-alt-1", topic="catalog:alt-1", angle="catalog:alt-1:revival", age_hours=48),
        *strong_group("bc-alt-2", topic="catalog:alt-2", angle="catalog:alt-2:revival", age_hours=48),
        *strong_group("bc-alt-3", topic="catalog:alt-3", angle="catalog:alt-3:revival", age_hours=48),
        *strong_group("bc-alt-4", topic="catalog:alt-4", angle="catalog:alt-4:revival", age_hours=48),
    )

    plan = plan_daily_slots(candidates, now=NOW)

    assert plan.slots[0].primary.published_at >= NOW - timedelta(hours=24)
    assert len(plan.slots) == 3
    assert all(
        first.primary.topic_key != second.primary.topic_key
        and first.primary.angle_key != second.primary.angle_key
        for index, first in enumerate(plan.slots)
        for second in plan.slots[index + 1:]
    )
    assert any(PlannerReasonCode.DUPLICATE_TOPIC_OR_ANGLE in rejection.reason_codes for rejection in plan.rejections)


def test_planner_fails_closed_when_no_current_strong_a_is_available():
    candidates = (
        *strong_group("background-b", topic="catalog:b", angle="catalog:b:revival", age_hours=48),
        *strong_group("background-c", topic="catalog:c", angle="catalog:c:revival", age_hours=48),
    )

    plan = plan_daily_slots(candidates, now=NOW)

    assert plan.slots == ()
    assert plan.reason_codes == (PlannerReasonCode.MISSING_CURRENT_STRONG_A,)


def test_planner_requires_an_aware_reference_time():
    with pytest.raises(ValueError, match="now must be timezone-aware"):
        plan_daily_slots((), now=datetime(2026, 7, 16, 12))
