from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from v2_contract.validate_task_card import validate_task_card
from v2_contract.validate_transition import validate_transition


ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "docs/plans/ruoyu-production-v2/2026-08-11-contract-v1.0/task-card-v1.0.schema.json"
VOCABULARY = ROOT / "docs/plans/ruoyu-production-v2/2026-08-11-contract-v1.0/state-vocabulary-v1.0.yaml"


def valid_task_card() -> dict:
    return {
        "schema_version": "1.0",
        "run_id": "run-2026-08-11",
        "article_id": "article-a",
        "slot": "A",
        "candidate_id": "candidate-a",
        "work": "作品甲",
        "primary_atom": "主角的选择",
        "reader_intent": "理解人物代价",
        "why_today": "今天的新触发",
        "angle": "人物选择与代价",
        "content_map": "从事件到人物选择",
        "event_cluster_id": "event-a",
        "reader_question": "他为什么这样选择？",
        "source_refs": ["sources/a.json"],
        "gate_status": {
            "candidate_pool": "pass",
            "slot_contract": "pass",
            "source_manifest": "pass",
            "claim_locators": "pass",
            "material_sufficiency": "ready-for-brief",
            "mechanical": "pass",
            "independent_review": "pending",
            "controller_acceptance": "pending",
        },
        "state": "R7 mechanically-verified",
        "publication_authorization": "not_authorized",
        "delivery_state": "pending_independent_review",
        "review_policy": {
            "dr_02_variant": "B_risk_triggered_sol",
            "review_required": True,
            "rationale": "L2 implementation requires an independent review gate.",
        },
        "recovery_mode": {
            "dr_07_variant": "A_scoped_recovery_override",
            "active": False,
            "manual_outline_ref": None,
            "starts_at": None,
            "ends_at": None,
        },
        "daily_output_policy": {
            "dr_03_variant": "A_quantity_target_quality_floor",
            "counts_as_delivery": True,
            "rationale": "This card meets the quality floor.",
        },
    }


def test_valid_task_card_passes_schema_and_cross_checks():
    assert validate_task_card(valid_task_card(), SCHEMA, VOCABULARY) == []


def test_r8_requires_unauthorized_publication_and_approved_review():
    card = valid_task_card()
    card["state"] = "R8 review-ready"
    card["gate_status"].update(
        {
            "independent_review": "approve",
            "controller_acceptance": "accepted",
        }
    )
    assert validate_task_card(card, SCHEMA, VOCABULARY) == []

    granted = copy.deepcopy(card)
    granted["publication_authorization"] = "granted"
    assert any("r8_publication_authorization" in error for error in validate_task_card(granted, SCHEMA, VOCABULARY))

    pending_review = copy.deepcopy(card)
    pending_review["gate_status"]["independent_review"] = "pending"
    assert any("r8_independent_review" in error for error in validate_task_card(pending_review, SCHEMA, VOCABULARY))


def test_publication_authorized_requires_granted_and_published():
    card = valid_task_card()
    card["state"] = "publication-authorized"
    card["publication_authorization"] = "granted"
    card["delivery_state"] = "published"
    assert validate_task_card(card, SCHEMA, VOCABULARY) == []

    unpublished = copy.deepcopy(card)
    unpublished["delivery_state"] = "delivery-ready"
    assert any("publication_authorized_delivery_state" in error for error in validate_task_card(unpublished, SCHEMA, VOCABULARY))

    ungranted = copy.deepcopy(card)
    ungranted["publication_authorization"] = "not_authorized"
    assert any("publication_authorized_authorization" in error for error in validate_task_card(ungranted, SCHEMA, VOCABULARY))


def test_h4_requires_unauthorized_and_withheld_or_not_requested():
    card = valid_task_card()
    card["state"] = "H4 draft-only"
    card["delivery_state"] = "withheld"
    assert validate_task_card(card, SCHEMA, VOCABULARY) == []

    bad = copy.deepcopy(card)
    bad["publication_authorization"] = "granted"
    assert any("h4_publication_authorization" in error for error in validate_task_card(bad, SCHEMA, VOCABULARY))


def test_missing_primary_atom_is_rejected():
    card = valid_task_card()
    del card["primary_atom"]
    errors = validate_task_card(card, SCHEMA, VOCABULARY)
    assert any("schema.required" in error and "primary_atom" in error for error in errors)


@pytest.mark.parametrize(
    ("parent", "field"),
    [
        ("review_policy", "dr_02_variant"),
        ("recovery_mode", "dr_07_variant"),
        ("daily_output_policy", "dr_03_variant"),
    ],
)
def test_pending_allen_variant_is_rejected_by_frozen_const(parent: str, field: str):
    card = valid_task_card()
    card[parent][field] = "pending_allen"
    errors = validate_task_card(card, SCHEMA, VOCABULARY)
    assert any(field in error for error in errors)


def test_unknown_state_is_rejected():
    card = valid_task_card()
    card["state"] = "R99 unknown"
    errors = validate_task_card(card, SCHEMA, VOCABULARY)
    assert any("state" in error for error in errors)


def test_schema_state_enum_must_match_frozen_vocabulary(tmp_path: Path):
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    schema["properties"]["state"]["enum"].remove("A archived")
    altered_schema = tmp_path / "task-card.schema.json"
    altered_schema.write_text(json.dumps(schema), encoding="utf-8")

    errors = validate_task_card(valid_task_card(), altered_schema, VOCABULARY)

    assert errors == ["state_enum_missing_from_schema:A archived"]


def test_schema_variant_const_must_match_frozen_vocabulary(tmp_path: Path):
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    schema["properties"]["review_policy"]["properties"]["dr_02_variant"]["const"] = "pending_allen"
    altered_schema = tmp_path / "task-card.schema.json"
    altered_schema.write_text(json.dumps(schema), encoding="utf-8")

    errors = validate_task_card(valid_task_card(), altered_schema, VOCABULARY)

    assert errors == [
        "schema.const:review_policy/dr_02_variant:'pending_allen' was expected",
        "variant_const_not_in_vocabulary:dr_02_variant:"
        "schema=pending_allen:vocabulary=B_risk_triggered_sol",
        "variant_const_mismatch:dr_02_variant:expected=pending_allen:actual=B_risk_triggered_sol",
    ]


def test_schema_must_retain_all_frozen_variant_consts(tmp_path: Path):
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    del schema["properties"]["daily_output_policy"]["properties"]["dr_03_variant"]["const"]
    altered_schema = tmp_path / "task-card.schema.json"
    altered_schema.write_text(json.dumps(schema), encoding="utf-8")

    errors = validate_task_card(valid_task_card(), altered_schema, VOCABULARY)

    assert errors == ["variant_const_missing_from_schema:dr_03_variant"]


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("R6 drafting", "R7 editorial-ready"),
        ("R7 editorial-ready", "R7 mechanically-verified"),
        ("R7 mechanically-verified", "R7.5 awaiting-independent-review"),
        ("R7.5 awaiting-independent-review", "R8 review-ready"),
        ("R8 review-ready", "H3 needs-revision"),
    ],
)
def test_frozen_transition_table_accepts_valid_transition(current: str, target: str):
    assert validate_transition(current, target, VOCABULARY) == []


def test_illegal_transition_is_rejected():
    errors = validate_transition("R3 slots-locked", "R6 drafting", VOCABULARY)
    assert errors == ["invalid_transition:R3 slots-locked->R6 drafting"]


def test_unknown_transition_state_is_rejected():
    errors = validate_transition("R99 unknown", "R6 drafting", VOCABULARY)
    assert "unknown_source_state:R99 unknown" in errors
    assert "invalid_transition:R99 unknown->R6 drafting" in errors


def test_cli_fixture_is_json_serializable():
    assert json.loads(json.dumps(valid_task_card()))["schema_version"] == "1.0"


def test_task_card_cli_reports_malformed_vocabulary_as_input_error(tmp_path: Path):
    task_card = tmp_path / "task-card.json"
    task_card.write_text("{}", encoding="utf-8")
    vocabulary = tmp_path / "broken-vocabulary.yaml"
    vocabulary.write_text("states: [\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "v2_contract.validate_task_card",
            str(task_card),
            "--vocabulary",
            str(vocabulary),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "INPUT_ERROR" in result.stderr
    assert "Traceback" not in result.stderr


def test_transition_cli_reports_malformed_vocabulary_as_input_error(tmp_path: Path):
    vocabulary = tmp_path / "broken-vocabulary.yaml"
    vocabulary.write_text("states: [\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "v2_contract.validate_transition",
            "R6 drafting",
            "R7 editorial-ready",
            "--vocabulary",
            str(vocabulary),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "INPUT_ERROR" in result.stderr
    assert "Traceback" not in result.stderr
