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
    freshness_window="same-day",
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
        "freshness_window": freshness_window,
        "status": "approved",
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
    candidates[1]["content_map"] = "culture"
    candidates[1]["topic_mode"] = "culture"
    candidates[1]["traffic_class"] = "evergreen"
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
            "freshness_window": "revival",
        },
    ]
    plan = build_daily_portfolio(candidates, [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00")
    assert plan["payload"]["decision"] == "selected"
    selected = plan["payload"]["selected_articles"]
    assert selected[0]["selection_reason"] == "why selected"
    assert selected[0]["reader_gap"] == "current reader gap"
    assert selected[0]["content_value_score"] == 5
    assert selected[1]["evidence_readiness"] == "high"


def test_validate_portfolio_rejects_invalid_task1_envelope():
    plan = build_daily_portfolio(
        _flow_and_depth_candidates(), [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00"
    )
    invalid = {**plan, "schema_version": "wrong-version"}
    assert "unknown:schema_version" in validate_portfolio(invalid)


def test_selected_article_ids_must_match_selected_articles():
    plan = build_daily_portfolio(
        _flow_and_depth_candidates(), [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00"
    )
    plan["payload"]["selected_article_ids"] = ["forged-id", "depth-1"]
    assert "selected:article_ids_mismatch" in validate_portfolio(plan)


def test_selected_candidates_require_identity_and_quality_fields():
    for field, expected in (
        ("candidate_id", "missing:candidate_id"),
        ("content_map", "missing:content_map"),
        ("event_cluster_id", "missing:event_cluster_id"),
        ("work_or_person", "missing:work_or_person"),
    ):
        candidates = _flow_and_depth_candidates()
        candidates[0][field] = ""
        plan = build_daily_portfolio(candidates, [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00")
        assert plan["payload"]["decision"] == "needs_controller"
        assert expected in validate_portfolio(plan)


def test_freshness_only_inputs_supply_flow_and_evergreen_roles():
    for freshness_window, expected_role in (
        ("same-day", "flow"),
        ("fermenting-1-3d", "flow"),
        ("revival", "evergreen"),
    ):
        candidates = [
            _candidate(
                "current",
                content_map="C 文化现象",
                traffic_class="",
                topic_mode="culture",
                freshness_window=freshness_window,
            ),
            _candidate(
                "other",
                content_map="B 作品深度",
                traffic_class="depth",
                topic_mode="culture",
            ),
        ]
        if expected_role == "evergreen":
            candidates[0]["content_map"] = "C 文化现象"
            candidates[1]["content_map"] = "flow"
        plan = build_daily_portfolio(
            candidates, [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00"
        )
        assert plan["payload"]["decision"] == "selected"
        assert plan["payload"]["selected_articles"][0]["freshness_window"]


def test_malformed_selected_articles_and_ids_are_stable_errors():
    plan = build_daily_portfolio(
        _flow_and_depth_candidates(), [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00"
    )
    for malformed in (None, [None, {}], [1, "x"], "articles"):
        candidate = {**plan, "payload": {**plan["payload"], "selected_articles": malformed}}
        first = validate_portfolio(candidate)
        assert first == validate_portfolio(candidate)
        assert first and all(isinstance(item, str) for item in first)
    for malformed in (None, "flow-1", ["flow-1"], ["flow-1", "flow-1"]):
        candidate = {**plan, "payload": {**plan["payload"], "selected_article_ids": malformed}}
        assert validate_portfolio(candidate)
        assert portfolio_gate_for_transition(candidate, malformed)


def test_payload_boundary_and_missing_constraints_items_fail_closed():
    plan = build_daily_portfolio(
        _flow_and_depth_candidates(), [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00"
    )
    for payload_change, expected in (
        ({"profile": "unknown"}, "invalid:profile"),
        ({"profile": None}, "invalid:profile"),
        ({"publication_authorization": None}, "publication_authorization_must_be_not_authorized"),
        ({"publication_authorization": "granted"}, "publication_authorization_must_be_not_authorized"),
        ({"missing_constraints": [{}]}, "invalid:missing_constraints_item"),
        ({"missing_constraints": [[]]}, "invalid:missing_constraints_item"),
        ({"missing_constraints": [None]}, "invalid:missing_constraints_item"),
    ):
        payload = {**plan["payload"], **payload_change}
        errors = validate_portfolio({**plan, "payload": payload})
        assert expected in errors


def test_sequence_inputs_and_invalid_items_are_explicit():
    candidates = tuple(_flow_and_depth_candidates())
    plan = build_daily_portfolio(
        candidates, tuple(), run_id="r1", planned_at="2026-09-08T10:00:00+08:00"
    )
    assert plan["payload"]["decision"] == "selected"
    for bad in ("not candidates", b"bytes", {"candidate": "mapping"}):
        rejected = build_daily_portfolio(
            bad, [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00"
        )
        assert rejected["payload"]["decision"] == "needs_controller"
        assert "invalid:candidates" in rejected["payload"]["missing_constraints"]
    rejected = build_daily_portfolio(
        [*candidates, None], [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00"
    )
    assert rejected["payload"]["decision"] == "needs_controller"
    assert "invalid:candidate" in rejected["payload"]["missing_constraints"]


def test_content_map_aliases_and_unknown_maps_fail_closed():
    for left_map, right_map in (("A", "A 新片事件"), ("b", "B 作品深度"), (" C 文化现象 ", "C") , ("D 人物争议", "d")):
        candidates = _flow_and_depth_candidates()
        candidates[0]["content_map"] = left_map
        candidates[1]["content_map"] = right_map
        plan = build_daily_portfolio(candidates, [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00")
        assert plan["payload"]["decision"] == "needs_controller"
        assert "duplicate:content_map" in validate_portfolio(plan)
    candidates = _flow_and_depth_candidates()
    candidates[0]["content_map"] = "unknown-map"
    plan = build_daily_portfolio(candidates, [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00")
    assert plan["payload"]["decision"] == "needs_controller"
    assert "missing:content_map" in validate_portfolio(plan)


def test_score_must_be_finite_and_between_one_and_five():
    for value in (True, "4", 0, 6, float("nan"), float("inf"), float("-inf")):
        candidates = _flow_and_depth_candidates()
        candidates[0]["content_value_score"] = value
        plan = build_daily_portfolio(candidates, [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00")
        assert plan["payload"]["decision"] == "needs_controller"
        assert "invalid:content_value_score" in validate_portfolio(plan)
    for value in (1, 5):
        candidates = _flow_and_depth_candidates()
        candidates[0]["content_value_score"] = value
        plan = build_daily_portfolio(candidates, [], run_id="r1", planned_at="2026-09-08T10:00:00+08:00")
        assert plan["payload"]["decision"] == "selected"


def test_only_precheck_or_approved_candidates_can_enter_the_portfolio():
    for status in ("idea", "returned", "closed", "unknown"):
        candidates = _flow_and_depth_candidates()
        candidates[0]["status"] = status
        plan = build_daily_portfolio(
            candidates,
            [],
            run_id="r1",
            planned_at="2026-09-08T10:00:00+08:00",
        )
        assert plan["payload"]["decision"] == "needs_controller"
        assert any("candidate_not_eligible" in error for error in validate_portfolio(plan))


def test_portfolio_input_snapshot_and_hashes_detect_tampering():
    candidates = _flow_and_depth_candidates()
    plan = build_daily_portfolio(
        candidates,
        [],
        run_id="r1",
        planned_at="2026-09-08T10:00:00+08:00",
    )
    assert set(plan["input_hashes"]) == {"candidates", "history"}
    assert validate_portfolio(plan, candidates=candidates, history=[]) == []

    plan["payload"]["input_snapshot"]["candidates"][0]["candidate_id"] = "tampered"
    assert "mismatch:input_hash:candidates" in validate_portfolio(plan)

    clean = build_daily_portfolio(
        candidates,
        [],
        run_id="r1",
        planned_at="2026-09-08T10:00:00+08:00",
    )
    changed_candidates = _flow_and_depth_candidates()
    changed_candidates[0]["selection_reason"] = "changed"
    assert "mismatch:external_candidates" in validate_portfolio(
        clean, candidates=changed_candidates, history=[]
    )
