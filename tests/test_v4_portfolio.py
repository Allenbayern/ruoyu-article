from article_group.v4.portfolio import (
    build_daily_portfolio,
    portfolio_gate_for_transition,
    validate_portfolio,
)


def _candidate(
    candidate_id,
    *,
    content_map,
    topic_mode="release_event",
    event_cluster_id=None,
    work_or_person=None,
    traffic_class="flow",
    value=4,
    readiness="high",
):
    return {
        "candidate_id": candidate_id,
        "content_map": content_map,
        "topic_mode": topic_mode,
        "event_cluster_id": event_cluster_id or candidate_id,
        "work_or_person": work_or_person or candidate_id,
        "traffic_class": traffic_class,
        "selection_reason": f"reason-{candidate_id}",
        "reader_gap": f"gap-{candidate_id}",
        "content_value_score": value,
        "evidence_readiness": readiness,
    }


def _flow_and_depth_candidates():
    return [
        _candidate("flow-1", content_map="flow", work_or_person="work-flow"),
        _candidate(
            "depth-1",
            content_map="depth",
            topic_mode="revisit",
            traffic_class="evergreen",
            work_or_person="work-depth",
        ),
    ]


def _same_cluster_candidates():
    candidates = _flow_and_depth_candidates()
    candidates[1]["event_cluster_id"] = candidates[0]["event_cluster_id"]
    return candidates


def test_two_article_daily_requires_flow_and_depth_pair():
    plan = build_daily_portfolio(
        _flow_and_depth_candidates(),
        [],
        run_id="r1",
        planned_at="2026-09-08T10:00:00+08:00",
    )
    assert plan["decision"] == "selected"
    assert plan["selected_article_ids"] == ["flow-1", "depth-1"]
    assert plan["publication_authorization"] == "not_authorized"
    assert validate_portfolio(plan) == []


def test_duplicate_event_cluster_blocks_portfolio():
    plan = build_daily_portfolio(
        _same_cluster_candidates(),
        [],
        run_id="r1",
        planned_at="2026-09-08T10:00:00+08:00",
    )
    assert plan["decision"] == "needs_controller"
    assert "duplicate:event_cluster_id" in validate_portfolio(plan)
    assert plan["selected_article_ids"] == []


def test_same_work_blocks_portfolio():
    candidates = _flow_and_depth_candidates()
    candidates[1]["work_or_person"] = candidates[0]["work_or_person"]
    plan = build_daily_portfolio(candidates, [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00")
    assert plan["decision"] == "needs_controller"
    assert "duplicate:work_or_person" in validate_portfolio(plan)


def test_missing_evergreen_depth_candidate_is_explicit():
    candidates = [_candidate("flow-1", content_map="flow")]
    plan = build_daily_portfolio(candidates, [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00")
    assert plan["decision"] == "needs_controller"
    errors = validate_portfolio(plan)
    assert "missing:depth" in errors
    assert "missing:evergreen" in errors
    assert plan["selected_article_ids"] == []


def test_no_valid_combination_does_not_fill_with_a_rejected_candidate():
    candidates = _flow_and_depth_candidates()
    candidates[1]["event_cluster_id"] = candidates[0]["event_cluster_id"]
    candidates.append({**candidates[1], "candidate_id": "depth-2", "work_or_person": "work-flow"})
    plan = build_daily_portfolio(candidates, [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00")
    assert plan["decision"] == "needs_controller"
    assert plan["selected_article_ids"] == []
    assert "no_valid_combination" in plan["missing_constraints"]


def test_history_same_work_is_rejected_and_transition_gate_preserves_boundary():
    history = [{"selected_articles": [{"work_or_person": "work-flow"}]}]
    plan = build_daily_portfolio(_flow_and_depth_candidates(), history, run_id="r1", planned_at="2026-09-08T10:00:00+08:00")
    assert plan["decision"] == "needs_controller"
    assert "history:work_or_person" in validate_portfolio(plan)
    assert portfolio_gate_for_transition(plan, ["flow-1", "depth-1"])
    assert plan["publication_authorization"] == "not_authorized"
