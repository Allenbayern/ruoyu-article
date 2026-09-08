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
    assert set(plan) == {"schema_version", "run_id", "generated_at", "input_hashes", "payload"}
    assert plan["payload"]["decision"] == "selected"
    assert plan["payload"]["selected_article_ids"] == ["flow-1", "depth-1"]
    assert plan["payload"]["publication_authorization"] == "not_authorized"
    assert validate_portfolio(plan) == []


def test_duplicate_event_cluster_blocks_portfolio():
    plan = build_daily_portfolio(
        _same_cluster_candidates(),
        [],
        run_id="r1",
        planned_at="2026-09-08T10:00:00+08:00",
    )
    assert plan["payload"]["decision"] == "needs_controller"
    assert "duplicate:event_cluster_id" in validate_portfolio(plan)
    assert plan["payload"]["selected_article_ids"] == []


def test_same_work_blocks_portfolio():
    candidates = _flow_and_depth_candidates()
    candidates[1]["work_or_person"] = candidates[0]["work_or_person"]
    plan = build_daily_portfolio(candidates, [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00")
    assert plan["payload"]["decision"] == "needs_controller"
    assert "duplicate:work_or_person" in validate_portfolio(plan)


def test_missing_evergreen_depth_candidate_is_explicit():
    candidates = [_candidate("flow-1", content_map="flow")]
    plan = build_daily_portfolio(candidates, [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00")
    assert plan["payload"]["decision"] == "needs_controller"
    errors = validate_portfolio(plan)
    assert "missing:depth_or_evergreen" in errors
    assert plan["payload"]["selected_article_ids"] == []


def test_no_valid_combination_does_not_fill_with_a_rejected_candidate():
    candidates = _flow_and_depth_candidates()
    candidates[1]["event_cluster_id"] = candidates[0]["event_cluster_id"]
    candidates.append({**candidates[1], "candidate_id": "depth-2", "work_or_person": "work-flow"})
    plan = build_daily_portfolio(candidates, [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00")
    assert plan["payload"]["decision"] == "needs_controller"
    assert plan["payload"]["selected_article_ids"] == []
    assert "no_valid_combination" in plan["payload"]["missing_constraints"]


def test_history_same_work_is_rejected_and_transition_gate_preserves_boundary():
    history = [{"selected_articles": [{"work_or_person": "work-flow"}]}]
    plan = build_daily_portfolio(_flow_and_depth_candidates(), history, run_id="r1", planned_at="2026-09-08T10:00:00+08:00")
    assert plan["payload"]["decision"] == "needs_controller"
    assert "history:work_or_person" in validate_portfolio(plan)
    assert portfolio_gate_for_transition(plan, ["flow-1", "depth-1"])
    assert plan["payload"]["publication_authorization"] == "not_authorized"


def test_same_content_map_blocks_even_when_roles_differ():
    candidates = _flow_and_depth_candidates()
    candidates[1]["content_map"] = candidates[0]["content_map"]
    plan = build_daily_portfolio(candidates, [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00")
    assert plan["payload"]["decision"] == "needs_controller"
    assert "duplicate:content_map" in validate_portfolio(plan)


def test_flow_and_evergreen_without_depth_is_selectable():
    candidates = _flow_and_depth_candidates()
    candidates[1]["content_map"] = "evergreen"
    plan = build_daily_portfolio(candidates, [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00")
    assert plan["payload"]["decision"] == "selected"
    assert "missing:depth_or_evergreen" not in validate_portfolio(plan)


def test_flow_and_depth_without_evergreen_is_selectable():
    candidates = _flow_and_depth_candidates()
    candidates[1]["traffic_class"] = "depth"
    plan = build_daily_portfolio(candidates, [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00")
    assert plan["payload"]["decision"] == "selected"
    assert "missing:depth_or_evergreen" not in validate_portfolio(plan)


def test_selected_candidate_requires_v4_quality_fields():
    candidates = _flow_and_depth_candidates()
    candidates[0]["selection_reason"] = ""
    candidates[1]["reader_gap"] = ""
    candidates[0]["content_value_score"] = "4"
    candidates[1]["evidence_readiness"] = "unknown"
    plan = build_daily_portfolio(candidates, [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00")
    assert plan["payload"]["decision"] == "needs_controller"
    errors = validate_portfolio(plan)
    assert "missing:selection_reason" in errors
    assert "missing:reader_gap" in errors
    assert "invalid:content_value_score" in errors
    assert "invalid:evidence_readiness" in errors


def test_controlled_candidate_aliases_normalize_to_v4_fields():
    candidates = [
        {
            **_candidate("flow-1", content_map="flow"),
            "selection_reason": None,
            "reason": "why selected",
            "reader_gap": None,
            "reader_intent": "current reader gap",
            "content_value_score": None,
            "editorial_value_score": 5,
        },
        {
            **_candidate("depth-1", content_map="depth", topic_mode="revisit", traffic_class="depth"),
            "reader_gap": None,
            "reader_question": "what readers need explained",
            "freshness_window": "evergreen",
        },
    ]
    plan = build_daily_portfolio(candidates, [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00")
    assert plan["payload"]["decision"] == "selected"
    selected = plan["payload"]["selected_articles"]
    assert selected[0]["selection_reason"] == "why selected"
    assert selected[0]["reader_gap"] == "current reader gap"
    assert selected[0]["content_value_score"] == 5
    assert selected[1]["evidence_readiness"] == "high"
