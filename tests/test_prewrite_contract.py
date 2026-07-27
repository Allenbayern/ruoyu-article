"""RED tests for pre-write candidate pool and editorial selection gates."""

from __future__ import annotations

from pathlib import Path

import pytest


# --- valid fixtures ---


def valid_candidate_pool() -> dict:
    """A minimal pool of 10 candidates with all required fields."""
    candidates = []
    for index in range(1, 11):
        candidates.append(
            {
                "candidate_id": f"cand-{index:02d}",
                "work": f"作品{index}",
                "core_person_or_event": f"核心事件{index}",
                "primary_atom": f"原子{index}",
                "reader_intent": "好奇",
                "angle": f"切口{index}",
                "content_map": f"内容地图{index}",
                "event_cluster_id": f"event-{index:02d}",
                "reader_question": f"读者问题{index}",
                "title_skeleton": f"标题骨架{index}",
                "ending_destination": f"结尾{index}",
                "event_time": "2026-07-26T00:00:00+08:00",
                "observed_at": "2026-07-26T10:00:00+08:00",
                "freshness_window": "same-day",
                "current_trigger": "新上映",
                "content_value_scores": {"emotion": 2, "narrative": 2, "share": 2, "human": 2, "freshness": 2},
                "source_roles": ["confirmed-primary"],
                "evidence_atom_ids": ["e-1"],
                "concrete_anchor_ids": ["a-1"],
                "recommendation": "A" if index <= 3 else "Archive",
                "reject_or_wait_reason": "" if index <= 3 else "仅供候选池，非当日写",
            }
        )
    return {
        "run_id": "test-run",
        "observed_at": "2026-07-26T10:00:00+08:00",
        "timezone": "+08:00",
        "candidates": candidates,
    }


def valid_slot_decisions() -> dict:
    return {
        "run_id": "test-run",
        "slots": [
            {"slot": "A", "primary_candidate_id": "cand-01", "backup_candidate_id": "cand-04"},
            {"slot": "B", "primary_candidate_id": "cand-02", "backup_candidate_id": "cand-05"},
            {"slot": "C", "primary_candidate_id": "cand-03", "backup_candidate_id": "cand-06"},
        ],
    }


# --- RED tests for candidate pool contract ---


def test_candidate_pool_requires_at_least_ten_candidates():
    from article_group.prewrite import validate_candidate_pool

    pool = valid_candidate_pool()
    pool["candidates"] = pool["candidates"][:3]
    errors = validate_candidate_pool(pool)
    assert any("pool" in err.lower() or "10" in err for err in errors)


def test_candidate_requires_numeric_five_dimension_scores():
    from article_group.prewrite import validate_candidate_pool

    pool = valid_candidate_pool()
    pool["candidates"][0]["content_value_scores"] = {"emotion": "high", "narrative": "high"}
    errors = validate_candidate_pool(pool)
    assert any("score" in err.lower() or "dimension" in err.lower() or "scores" in err.lower() for err in errors)


def test_candidate_pool_rejects_future_observed_at():
    from article_group.prewrite import validate_candidate_pool

    pool = valid_candidate_pool()
    pool["observed_at"] = "2099-01-01T00:00:00+08:00"
    errors = validate_candidate_pool(pool)
    assert any("future" in err.lower() or "timestamp" in err.lower() or "time" in err.lower() for err in errors)


def test_candidate_pool_requires_timezone():
    from article_group.prewrite import validate_candidate_pool

    pool = valid_candidate_pool()
    del pool["timezone"]
    errors = validate_candidate_pool(pool)
    assert errors


# --- RED tests for editorial selection ---


def test_selected_slots_require_three_distinct_primary_and_backup_ids():
    from article_group.prewrite import validate_slot_decisions

    decisions = valid_slot_decisions()
    # Use same backup as another slot's primary
    decisions["slots"][1]["backup_candidate_id"] = "cand-01"
    errors = validate_slot_decisions(decisions)
    assert any("backup" in err.lower() or "overlap" in err.lower() or "duplicate" in err.lower() for err in errors)


def test_primary_cannot_be_another_slots_backup():
    from article_group.prewrite import validate_slot_decisions

    decisions = valid_slot_decisions()
    decisions["slots"][2]["primary_candidate_id"] = "cand-04"
    errors = validate_slot_decisions(decisions)
    assert any("backup" in err.lower() or "overlap" in err.lower() or "duplicate" in err.lower() for err in errors)


def test_backup_must_be_material_ready():
    from article_group.prewrite import validate_slot_decisions

    decisions = valid_slot_decisions()
    decisions["slots"][0]["backup_candidate_id"] = "cand-99"
    errors = validate_slot_decisions(decisions, candidate_ids={"cand-01", "cand-02", "cand-03", "cand-04", "cand-05", "cand-06"})
    assert any("unknown" in err.lower() or "missing" in err.lower() or "not in" in err.lower() for err in errors)


def test_reject_reason_is_required_for_unselected_candidates():
    from article_group.prewrite import validate_candidate_pool

    pool = valid_candidate_pool()
    # cand-07 is unselected (Archive) but has an empty reject reason
    pool["candidates"][6]["reject_or_wait_reason"] = ""
    pool["candidates"][6]["recommendation"] = "Archive"
    errors = validate_candidate_pool(pool)
    assert any("reject" in err.lower() or "reason" in err.lower() or "archive" in err.lower() for err in errors)


def test_valid_pool_and_decisions_pass():
    from article_group.prewrite import validate_candidate_pool, validate_slot_decisions

    pool = valid_candidate_pool()
    assert validate_candidate_pool(pool) == []

    decisions = valid_slot_decisions()
    candidate_ids = {card["candidate_id"] for card in pool["candidates"]}
    assert validate_slot_decisions(decisions, candidate_ids=candidate_ids) == []


# --- Slice 3: canonical slot contract and deterministic semantic deduplication ---


@pytest.mark.parametrize("field", ["content_map", "event_cluster_id", "reader_question"])
def test_candidate_requires_new_canonical_slot_fields(field: str):
    from article_group.prewrite import validate_candidate_pool

    pool = valid_candidate_pool()
    del pool["candidates"][0][field]

    assert f"candidate_cand-01_missing_{field}" in validate_candidate_pool(pool)


@pytest.mark.parametrize("field,bad_value", [
    ("content_map", []), ("event_cluster_id", {}), ("reader_question", 3),
])
def test_candidate_rejects_non_string_canonical_slot_fields(field: str, bad_value: object):
    from article_group.prewrite import validate_candidate_pool

    pool = valid_candidate_pool()
    pool["candidates"][0][field] = bad_value

    assert f"candidate_cand-01_invalid_{field}" in validate_candidate_pool(pool)


@pytest.mark.parametrize("field", ["content_map", "event_cluster_id", "reader_question"])
def test_candidate_requires_nonblank_canonical_slot_fields(field: str):
    from article_group.prewrite import validate_candidate_pool

    pool = valid_candidate_pool()
    pool["candidates"][0][field] = " \t "

    assert f"candidate_cand-01_missing_{field}" in validate_candidate_pool(pool)


def test_candidate_pool_rejects_non_dict_candidate_without_crashing():
    from article_group.prewrite import validate_candidate_pool

    pool = valid_candidate_pool()
    pool["candidates"][0] = ["not-a-record"]

    assert "candidate_record_0_must_be_a_dict" in validate_candidate_pool(pool)


def test_candidate_pool_rejects_duplicate_candidate_ids():
    from article_group.prewrite import validate_candidate_pool

    pool = valid_candidate_pool()
    pool["candidates"][1]["candidate_id"] = " cand-01 "

    assert "candidate_pool_duplicate_candidate_id_cand-01" in validate_candidate_pool(pool)


@pytest.mark.parametrize("bad_value", ["  ", "\t", 0, 1, True, False, ("cand-01",), b"cand-01", [], {}])
def test_candidate_pool_rejects_non_string_or_blank_candidate_id(bad_value: object):
    from article_group.prewrite import validate_candidate_pool

    pool = valid_candidate_pool()
    pool["candidates"][0]["candidate_id"] = bad_value
    errors = validate_candidate_pool(pool)

    assert (
        "candidate_record_0_missing_candidate_id" in errors
        or "candidate_record_0_invalid_candidate_id" in errors
    )


def test_candidate_pool_rejects_duplicate_non_string_candidate_ids_as_invalid_not_green():
    from article_group.prewrite import validate_candidate_pool

    pool = valid_candidate_pool()
    pool["candidates"][0]["candidate_id"] = 0
    pool["candidates"][1]["candidate_id"] = 0
    errors = validate_candidate_pool(pool)

    assert errors.count("candidate_record_0_invalid_candidate_id") == 1
    assert errors.count("candidate_record_1_invalid_candidate_id") == 1
    assert validate_candidate_pool(pool) != []


def test_build_slot_contract_copies_locked_primary_candidate_fields():
    from article_group.prewrite import build_slot_contract

    contract = build_slot_contract(valid_candidate_pool(), valid_slot_decisions())

    assert contract["slots"][0] == {
        "slot": "A", "candidate_id": "cand-01", "work": "作品1",
        "primary_atom": "原子1", "reader_intent": "好奇", "angle": "切口1",
        "content_map": "内容地图1", "event_cluster_id": "event-01",
        "reader_question": "读者问题1",
    }


@pytest.mark.parametrize(
    "field",
    [
        "candidate_id",
        "work",
        "primary_atom",
        "reader_intent",
        "angle",
        "content_map",
        "event_cluster_id",
        "reader_question",
    ],
)
def test_slot_contract_rejects_drift_from_locked_primary_candidate(field: str):
    from article_group.prewrite import build_slot_contract, validate_slot_contract

    pool = valid_candidate_pool()
    decisions = valid_slot_decisions()
    contract = build_slot_contract(pool, decisions)
    contract["slots"][0][field] = "漂移值"

    errors = validate_slot_contract(contract, pool, decisions)
    assert f"slot_A_candidate_mismatch_{field}" in errors


def test_slot_contract_duplicate_label_still_reports_earlier_lock_drift():
    from article_group.prewrite import build_slot_contract, validate_slot_contract

    pool = valid_candidate_pool()
    decisions = valid_slot_decisions()
    contract = build_slot_contract(pool, decisions)
    drifted_a = {**contract["slots"][0], "work": "漂移值"}
    matching_a = dict(contract["slots"][0])
    # len==3 with duplicate A masks C; must still surface earlier A drift
    malicious = {"slots": [drifted_a, matching_a, dict(contract["slots"][1])]}

    errors = validate_slot_contract(malicious, pool, decisions)
    assert "slot_A_duplicate_slot_label" in errors
    assert "slot_A_candidate_mismatch_work" in errors


@pytest.mark.parametrize("field", ["candidate_id", "work", "primary_atom", "reader_intent", "angle", "content_map", "event_cluster_id", "reader_question"])
def test_slot_contract_rejects_artifact_record_drift(field: str):
    from article_group.prewrite import build_slot_contract, validate_slot_contract

    contract = build_slot_contract(valid_candidate_pool(), valid_slot_decisions())
    record = {**contract["slots"][0], "artifact_type": "brief", "path": "briefs/A.json"}
    record[field] = "错误值"

    errors = validate_slot_contract(contract, artifact_records=[record])
    assert f"artifact_brief_briefs/A.json_slot_A_mismatch_{field}" in errors


def test_slot_contract_rejects_duplicate_work_after_whitespace_and_case_normalization():
    from article_group.prewrite import build_slot_contract, validate_slot_contract

    pool = valid_candidate_pool()
    pool["candidates"][1]["work"] = "  作品1\t"
    contract = build_slot_contract(pool, valid_slot_decisions())

    assert "slot_contract_duplicate_normalized_work_A_B" in validate_slot_contract(contract)


def test_slot_contract_rejects_duplicate_event_cluster_across_different_works():
    from article_group.prewrite import build_slot_contract, validate_slot_contract

    pool = valid_candidate_pool()
    pool["candidates"][1]["event_cluster_id"] = pool["candidates"][0]["event_cluster_id"]
    contract = build_slot_contract(pool, valid_slot_decisions())

    assert "slot_contract_duplicate_event_cluster_id_A_B" in validate_slot_contract(contract)


def test_slot_contract_rejects_duplicate_reader_question_after_whitespace_and_case_normalization():
    from article_group.prewrite import build_slot_contract, validate_slot_contract

    pool = valid_candidate_pool()
    pool["candidates"][1]["reader_question"] = "  READER\tQUESTION "
    pool["candidates"][0]["reader_question"] = "reader question"
    contract = build_slot_contract(pool, valid_slot_decisions())

    assert "slot_contract_duplicate_normalized_reader_question_A_B" in validate_slot_contract(contract)


def test_three_independent_canonical_slots_pass_validation():
    from article_group.prewrite import build_slot_contract, validate_slot_contract

    pool = valid_candidate_pool()
    decisions = valid_slot_decisions()
    contract = build_slot_contract(pool, decisions)

    assert validate_slot_contract(contract, pool, decisions, artifact_records=contract["slots"]) == []


@pytest.mark.parametrize("field,bad_value", [
    ("content_map", []), ("event_cluster_id", {}), ("reader_question", 3),
])
def test_canonical_slot_validation_handles_non_string_fields_deterministically(field: str, bad_value: object):
    from article_group.prewrite import build_slot_contract, validate_slot_contract

    pool = valid_candidate_pool()
    pool["candidates"][0][field] = bad_value

    errors = validate_slot_contract(build_slot_contract(pool, valid_slot_decisions()))
    assert f"slot_A_invalid_{field}" in errors
