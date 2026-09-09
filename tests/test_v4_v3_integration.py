from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from article_group.editorial_pipeline_v3 import (
    validate_transition,
    validate_v4_transition_context,
)
from article_group.v4.evidence_graph import build_evidence_graph
from article_group.v4.portfolio import build_daily_portfolio


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "v4" / "controlled-002"


def _selected_plan() -> dict:
    pool = json.loads((FIXTURE / "candidate-pool.json").read_text(encoding="utf-8"))
    return build_daily_portfolio(
        pool["candidates"],
        [],
        run_id="v4-fixture-002",
        planned_at="2026-09-09T09:00:00+08:00",
    )


def _valid_graph() -> dict:
    batch = json.loads((FIXTURE / "batch.json").read_text(encoding="utf-8"))
    return build_evidence_graph(FIXTURE, batch)


def test_v4_blocks_research_without_a_selected_portfolio():
    errors = validate_v4_transition_context(
        "approved",
        "researching",
        portfolio_plan=None,
        evidence_graph=None,
        gap_report=None,
        recovery_actions=None,
    )

    assert "missing:v4_portfolio" in errors


def test_v4_accepts_a_valid_selected_portfolio_for_research():
    plan = _selected_plan()

    errors = validate_v4_transition_context(
        "approved",
        "researching",
        portfolio_plan=plan,
        evidence_graph=None,
        gap_report=None,
        recovery_actions=None,
    )

    assert errors == []


def test_v4_blocks_writing_when_gap_report_has_blocker():
    errors = validate_v4_transition_context(
        "material_ready",
        "writing",
        portfolio_plan=_selected_plan(),
        evidence_graph=_valid_graph(),
        gap_report={"blocking_gaps": ["gap-1"]},
        recovery_actions={"actions": []},
    )

    assert "blocking_gap:gap-1" in errors


def test_v4_surfaces_stale_evidence_as_a_recheck_error():
    graph = _valid_graph()
    graph["payload"]["nodes"]["source:src-001"]["status"] = "stale"

    errors = validate_v4_transition_context(
        "material_ready",
        "writing",
        portfolio_plan=_selected_plan(),
        evidence_graph=graph,
        gap_report={"blocking_gaps": []},
        recovery_actions={"actions": []},
    )

    assert "stale:evidence:source:src-001" in errors


def test_v4_does_not_replace_the_v3_review_to_closed_transition():
    errors = validate_v4_transition_context(
        "review",
        "closed",
        portfolio_plan=None,
        evidence_graph=None,
        gap_report=None,
        recovery_actions=None,
    )

    assert errors == []
    assert validate_transition("review", "closed") == []


def test_v4_rejects_authorization_injected_into_context():
    plan = deepcopy(_selected_plan())
    plan["payload"]["publication_authorization"] = "authorized"

    errors = validate_v4_transition_context(
        "approved",
        "researching",
        portfolio_plan=plan,
        evidence_graph=None,
        gap_report=None,
        recovery_actions=None,
    )

    assert "forbidden:portfolio:publication_authorization" in errors
