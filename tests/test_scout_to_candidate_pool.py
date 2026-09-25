from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from scout_to_candidate_pool import (  # noqa: E402
    ConvertError,
    EDITORIAL_FIELDS,
    build_pool,
    derive_cluster_id,
    derive_freshness,
    extract_work_tokens,
    main,
)

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def _row(**overrides: object) -> dict:
    row = {
        "candidate_id": "cand-1",
        "account_name": "某影视号",
        "title": "《云雀叫天录》张一山演技如何？",
        "canonical_url": "https://mp.weixin.qq.com/s/example",
        "published_at": "2026-09-23T02:00:00+00:00",
        "screening_status": "advisory_candidate",
        "scores": {"evidence_readiness": 40, "total": 90},
        "hook_draft": "这戏这角儿，换谁都不行。",
        "reader_question_draft": "张一山到底会不会演戏？",
        "source_prior_label": "approved_head_account",
    }
    row.update(overrides)
    return row


def _pool(rows: list[dict], selected: list[str] | None = None):
    return build_pool(
        rows,
        selected_ids=selected if selected is not None else [str(rows[0]["candidate_id"])],
        run_id="2026-09-23/daily-014",
        now=NOW,
    )


def _write_ledger(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "ledger.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8")
    return path


# --- the machine must not choose -------------------------------------------------


def test_empty_selection_is_refused():
    with pytest.raises(ConvertError, match="selection_required"):
        build_pool([_row()], selected_ids=[], run_id="r", now=NOW)


def test_unknown_selection_id_is_refused():
    with pytest.raises(ConvertError, match="unknown_candidate"):
        build_pool([_row()], selected_ids=["ghost"], run_id="r", now=NOW)


def test_selecting_a_rejected_candidate_is_refused():
    rows = [_row(candidate_id="ok"), _row(candidate_id="noise",
                                          screening_status="rejected")]

    with pytest.raises(ConvertError, match="not_an_advisory_candidate"):
        build_pool(rows, selected_ids=["noise"], run_id="r", now=NOW)


# --- editorial fields stay empty -------------------------------------------------


def test_every_editorial_field_is_left_empty():
    pool, _ = _pool([_row()])

    candidate = pool["candidates"][0]
    for field in EDITORIAL_FIELDS:
        assert candidate[field] == "", f"{field} must not be machine-filled"


def test_pool_declares_itself_incomplete_and_never_authorises_publication():
    pool, report = _pool([_row()])

    assert pool["draft_status"] == "incomplete_editorial_fields"
    assert pool["publication_authorization"] == "not_authorized"
    assert pool["editorial_todo"]["cand-1"] == list(EDITORIAL_FIELDS)
    assert report["pending_editorial_cells"] == len(EDITORIAL_FIELDS)


def test_selection_is_recorded_verbatim():
    rows = [_row(candidate_id="a"), _row(candidate_id="b")]

    pool, _ = _pool(rows, selected=["b"])

    assert pool["selected_slot_ids"] == ["b"]
    assert {c["candidate_id"] for c in pool["candidates"]} == {"a", "b"}


# --- machine fields must be valid for the real gate ------------------------------


@pytest.mark.parametrize(
    ("published", "expected"),
    [
        ("2026-09-23T02:00:00+00:00", "same-day"),
        ("2026-09-21T12:00:00+00:00", "fermenting-1-3d"),
        ("2026-09-01T12:00:00+00:00", "revival"),
        ("", ""),
        ("not-a-date", ""),
    ],
)
def test_freshness_uses_only_the_gates_window_vocabulary(published, expected):
    from article_group.portfolio_gate import WINDOWS

    value = derive_freshness(published, NOW)

    assert value == expected
    assert value == "" or value in WINDOWS, "inventing a window label is a real defect"


def test_readiness_is_always_a_gate_value():
    from article_group.portfolio_gate import READINESS

    for score in (0, 20, 30, 40):
        pool, _ = _pool([_row(scores={"evidence_readiness": score, "total": 50})])
        assert pool["candidates"][0]["evidence_readiness"] in READINESS


def test_converted_pool_only_trips_editorial_gate_checks(tmp_path):
    """The real gate must complain about editorial gaps and nothing else."""

    ledger = _write_ledger(tmp_path, [_row(candidate_id="a"),
                                      _row(candidate_id="b", title="另一篇影评")])
    out = tmp_path / "pool" / "candidate-pool.json"
    assert main(["--scout-ledger", str(ledger), "--select", "a",
                 "--run-id", "r", "--out", str(out)]) == 0

    from article_group.portfolio_gate import run_checks

    result, _code = run_checks(str(out))
    blocking = {e["id"] for e in result.get("errors", [])}

    assert blocking <= {"portfolio.quadrant.missing"}, (
        "machine-filled fields must not cause any other blocking error, got " + str(blocking)
    )


# --- clustering is mechanical and labelled ---------------------------------------


def test_work_tokens_are_extracted_from_double_angle_brackets():
    assert extract_work_tokens("《交锋》与《云雀叫天录》对比") == ["交锋", "云雀叫天录"]
    assert extract_work_tokens("没有书名号的标题") == []


def test_cluster_groups_same_work_titles():
    a = derive_cluster_id({"title": "《交锋》第一集"})
    b = derive_cluster_id({"title": "莫要冤枉《交锋》"})

    assert a == b
    assert a.startswith("scout-work-")


def test_cluster_falls_back_to_account_when_no_work_named():
    cluster = derive_cluster_id({"title": "没有书名号", "account_name": "马庆云"})

    assert cluster == "scout-account-马庆云"


def test_cluster_is_labelled_tentative():
    pool, _ = _pool([_row()])

    assert "非编辑聚类" in pool["candidates"][0]["_cluster_basis"]


def test_source_prior_is_marked_as_not_performance_proof():
    pool, _ = _pool([_row()])

    candidate = pool["candidates"][0]
    assert candidate["_source_prior"] == "approved_head_account"
    assert candidate["_source_prior_is_performance_proof"] is False


# --- CLI -------------------------------------------------------------------------


def test_cli_writes_pool_and_checklist(tmp_path):
    ledger = _write_ledger(tmp_path, [_row(candidate_id="a")])
    out = tmp_path / "pool" / "candidate-pool.json"

    code = main(["--scout-ledger", str(ledger), "--select", "a",
                 "--run-id", "2026-09-23/daily-014", "--out", str(out)])

    assert code == 0
    pool = json.loads(out.read_text(encoding="utf-8"))
    assert pool["selected_slot_ids"] == ["a"]
    checklist = (out.parent / "candidate-pool-TODO.md").read_text(encoding="utf-8")
    assert "portfolio_gate 报 error" in checklist
    assert "不该由机器代笔" in checklist


def test_cli_requires_an_explicit_selection(tmp_path):
    ledger = _write_ledger(tmp_path, [_row()])
    out = tmp_path / "pool" / "candidate-pool.json"

    code = main(["--scout-ledger", str(ledger), "--run-id", "r", "--out", str(out)])

    assert code == 2
    assert not out.exists()


def test_cli_refuses_to_overwrite_an_existing_pool(tmp_path):
    ledger = _write_ledger(tmp_path, [_row(candidate_id="a")])
    out = tmp_path / "pool" / "candidate-pool.json"
    args = ["--scout-ledger", str(ledger), "--select", "a", "--run-id", "r", "--out", str(out)]

    assert main(args) == 0
    assert main(args) == 3
    assert main([*args, "--allow-overwrite"]) == 0


def test_cli_refuses_to_write_inside_a_sealed_run(tmp_path):
    ledger = _write_ledger(tmp_path, [_row(candidate_id="a")])
    sealed = tmp_path / "sealed"
    sealed.mkdir()
    (sealed / "SEALED").write_text("sealed\n", encoding="utf-8")

    code = main(["--scout-ledger", str(ledger), "--select", "a", "--run-id", "r",
                 "--out", str(sealed / "candidate-pool.json")])

    assert code == 3
    assert not (sealed / "candidate-pool.json").exists()


def test_cli_fails_closed_on_missing_ledger(tmp_path):
    code = main(["--scout-ledger", str(tmp_path / "nope.jsonl"), "--select", "a",
                 "--run-id", "r", "--out", str(tmp_path / "pool" / "candidate-pool.json")])

    assert code == 2
