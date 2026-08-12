from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

from v2_contract.run_preflight import map_article_to_task_card, preflight_batch


ROOT = Path(__file__).parents[1]
RUN_DIR = ROOT / "runs/2026-08-08/controlled-016"


def _task_card_values(article_id: str) -> dict[str, str]:
    text = (RUN_DIR / "task-cards" / f"task-card-{article_id}.md").read_text(encoding="utf-8")
    patterns = {
        "primary_atom": r"^- Primary Atom: (?P<value>.+)$",
        "reader_intent": r"^- Reader Intent: (?P<value>.+)$",
        "angle": r"^1\. \*\*站队点/可转述句\*\*：(?P<value>.+)$",
    }
    values = {}
    for field, pattern in patterns.items():
        match = re.search(pattern, text, re.MULTILINE)
        if match is None:
            raise AssertionError(f"missing {field} in controlled task card {article_id}")
        values[field] = match["value"]
    return values


def _controlled_batch() -> dict:
    candidates = json.loads((RUN_DIR / "candidate-pool.json").read_text(encoding="utf-8"))["candidates"]
    source_refs_by_candidate = {
        "cand-001": [
            "sources/kungfu-bjsb-eastmoney-20260803.md",
            "sources/kungfu-gamersky-20260805.md",
            "sources/kungfu-sina-20260806.md",
            "sources/kungfu-sina-cj-20260803.md",
            "sources/kungfu-sina-cj-20260804.md",
        ],
        "cand-002": [
            "sources/odyssey-qq-20260721.md",
            "sources/odyssey-qq-xinhuanghe-20260626.md",
            "sources/odyssey-qq-xinhuanghe-20260803.md",
            "sources/odyssey-shangguan-baijiahao-20260803.md",
        ],
        "cand-003": [
            "sources/tianxiwei-lizhi-sina-20260806.md",
            "sources/tianxiwei-sina-20260806.md",
        ],
    }
    articles = []
    for article_number, (slot, candidate) in enumerate(zip(("A", "B", "C"), candidates, strict=True), start=1):
        article_id = f"art-{article_number:03d}"
        task_card = _task_card_values(article_id)
        articles.append(
            {
                "article_id": article_id,
                "candidate_id": candidate["candidate_id"],
                "slot": slot,
                "work": candidate["work"],
                "primary_atom": task_card["primary_atom"],
                "reader_intent": task_card["reader_intent"],
                "angle": task_card["angle"],
                "state": "R5 brief-ready",
                "why_today": candidate["why_now"],
                "content_map": candidate["content_map"],
                "event_cluster_id": candidate["event_cluster_id"],
                "reader_question": candidate["reader_question"],
                "source_refs": source_refs_by_candidate[candidate["candidate_id"]],
                "gate_status": {
                    "candidate_pool": "pass",
                    "slot_contract": "pass",
                    "source_manifest": "pass",
                    "claim_locators": "pass",
                    "material_sufficiency": "ready-for-brief",
                    "mechanical": "pending",
                    "independent_review": "pending",
                    "controller_acceptance": "pending",
                },
                "publication_authorization": "not_authorized",
                "delivery_state": "not_requested",
                "review_policy": {
                    "dr_02_variant": "B_risk_triggered_sol",
                    "review_required": True,
                    "rationale": "Controlled batch requires independent review before R8.",
                },
                "recovery_mode": {
                    "dr_07_variant": "A_scoped_recovery_override",
                    "active": None,
                    "manual_outline_ref": None,
                    "starts_at": None,
                    "ends_at": None,
                },
                "daily_output_policy": {
                    "dr_03_variant": "A_quantity_target_quality_floor",
                    "counts_as_delivery": True,
                    "rationale": "The controlled batch has met its quality floor.",
                },
            }
        )
    return {
        "run_id": "2026-08-08/controlled-016",
        "manifest_state": "R5 brief-ready",
        "target_state": "R6 drafting",
        "articles": articles,
    }


def _run_cli(batch_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "v2_contract.run_preflight",
            "--batch",
            str(batch_path),
            *arguments,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_preflight_maps_controlled_016_articles_and_validates_transition(tmp_path: Path):
    batch = _controlled_batch()

    report = preflight_batch(batch, RUN_DIR)

    assert report["status"] == "PASS"
    assert report["exit_code"] == 0
    assert [card["article_id"] for card in report["task_cards"]] == ["art-001", "art-002", "art-003"]
    assert report["task_cards"][0]["schema_version"] == "1.1"
    assert report["task_cards"][0]["primary_atom"] == _task_card_values("art-001")["primary_atom"]
    assert report["task_cards"][0]["angle"] == _task_card_values("art-001")["angle"]
    assert report["task_cards"][0]["source_refs"] == [
        "sources/kungfu-bjsb-eastmoney-20260803.md",
        "sources/kungfu-gamersky-20260805.md",
        "sources/kungfu-sina-20260806.md",
        "sources/kungfu-sina-cj-20260803.md",
        "sources/kungfu-sina-cj-20260804.md",
    ]
    assert report["transition"]["errors"] == []

    batch_path = tmp_path / "controlled-016-batch.json"
    batch_path.write_text(json.dumps(batch), encoding="utf-8")
    result = _run_cli(batch_path, "--run-dir", str(RUN_DIR))

    assert result.returncode == 0
    cli_report = json.loads(result.stdout)
    assert cli_report["status"] == "PASS"
    assert [card["article_id"] for card in cli_report["task_cards"]] == ["art-001", "art-002", "art-003"]


def test_preflight_rejects_article_state_that_disagrees_with_manifest_state(tmp_path: Path):
    batch = _controlled_batch()
    batch["manifest_state"] = "R6 drafting"
    batch["target_state"] = "R7 editorial-ready"

    report = preflight_batch(batch, RUN_DIR)

    assert report["status"] == "FAIL"
    assert report["exit_code"] == 1
    assert [article["errors"] for article in report["articles"]] == [
        [
            "preflight.manifest_state_mismatch:art-001:article=R5 brief-ready:manifest=R6 drafting"
        ],
        [
            "preflight.manifest_state_mismatch:art-002:article=R5 brief-ready:manifest=R6 drafting"
        ],
        [
            "preflight.manifest_state_mismatch:art-003:article=R5 brief-ready:manifest=R6 drafting"
        ],
    ]

    batch_path = tmp_path / "manifest-state-mismatch.json"
    batch_path.write_text(json.dumps(batch), encoding="utf-8")
    result = _run_cli(batch_path, "--run-dir", str(RUN_DIR))

    assert result.returncode == 1
    cli_report = json.loads(result.stdout)
    assert cli_report["status"] == "FAIL"
    assert [article["errors"] for article in cli_report["articles"]] == [
        article["errors"] for article in report["articles"]
    ]


@pytest.mark.parametrize(
    ("duplicate_id", "duplicate_first"),
    [
        ("cand-001", True),
        ("cand-001", False),
        (" CAND-001 ", True),
        (" CAND-001 ", False),
    ],
    ids=("exact-first", "exact-last", "normalized-first", "normalized-last"),
)
def test_preflight_rejects_normalized_duplicate_candidate_ids_as_input_error(
    tmp_path: Path,
    duplicate_id: str,
    duplicate_first: bool,
):
    run_dir = tmp_path / "controlled-016"
    shutil.copytree(RUN_DIR, run_dir)

    candidate_pool_path = run_dir / "candidate-pool.json"
    candidate_pool = json.loads(candidate_pool_path.read_text(encoding="utf-8"))
    original = candidate_pool["candidates"][0]
    duplicate = {**original, "candidate_id": duplicate_id, "work": "conflicting duplicate"}
    if duplicate_first:
        candidate_pool["candidates"] = [duplicate, original, *candidate_pool["candidates"][1:]]
    else:
        candidate_pool["candidates"] = [original, duplicate, *candidate_pool["candidates"][1:]]
    candidate_pool_path.write_text(json.dumps(candidate_pool), encoding="utf-8")

    batch_path = tmp_path / "duplicate-candidate-id.json"
    batch_path.write_text(json.dumps(_controlled_batch()), encoding="utf-8")
    result = _run_cli(batch_path, "--run-dir", str(run_dir))

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("INPUT_ERROR:")
    assert "preflight.duplicate_candidate_id:cand-001" in result.stderr


def test_preflight_rejects_batch_field_that_disagrees_with_run_task_card():
    batch = _controlled_batch()
    batch["articles"][1]["primary_atom"] = "different primary atom"

    report = preflight_batch(batch, RUN_DIR)

    assert report["status"] == "FAIL"
    assert report["articles"][1]["errors"] == ["preflight.task_card_mismatch:art-002:primary_atom"]


def test_preflight_fails_closed_for_non_string_candidate_id_with_run_context():
    batch = _controlled_batch()
    batch["articles"][0]["candidate_id"] = []

    report = preflight_batch(batch, RUN_DIR)

    assert report["status"] == "FAIL"
    assert "preflight.candidate_id_invalid:art-001" in report["articles"][0]["errors"]
    assert any(error.startswith("schema.type:candidate_id:") for error in report["articles"][0]["errors"])


def test_mapping_fails_closed_when_daily_output_policy_is_missing(tmp_path: Path):
    batch = _controlled_batch()
    article = batch["articles"][0]
    del article["daily_output_policy"]

    task_card, errors = map_article_to_task_card(article, "2026-08-08/controlled-016", RUN_DIR)

    assert task_card is None
    assert errors == ["preflight.missing_mapping_fields:art-001:daily_output_policy"]

    batch_path = tmp_path / "missing-daily-output-policy.json"
    batch_path.write_text(json.dumps(batch), encoding="utf-8")
    result = _run_cli(batch_path, "--run-dir", str(RUN_DIR))

    assert result.returncode == 1
    assert json.loads(result.stdout)["articles"][0]["errors"] == errors


def test_preflight_rejects_transition_missing_from_frozen_exits(tmp_path: Path):
    batch = _controlled_batch()
    batch["target_state"] = "R8 review-ready"

    report = preflight_batch(batch, RUN_DIR)

    assert report["status"] == "FAIL"
    assert report["exit_code"] == 1
    assert report["transition"]["errors"] == ["invalid_transition:R5 brief-ready->R8 review-ready"]

    batch_path = tmp_path / "invalid-transition.json"
    batch_path.write_text(json.dumps(batch), encoding="utf-8")
    result = _run_cli(batch_path, "--run-dir", str(RUN_DIR))

    assert result.returncode == 1
    assert json.loads(result.stdout)["transition"]["errors"] == report["transition"]["errors"]


def test_preflight_fails_closed_when_manifest_state_is_missing():
    batch = _controlled_batch()
    del batch["manifest_state"]

    report = preflight_batch(batch, RUN_DIR)

    assert report["status"] == "FAIL"
    assert report["transition"]["errors"] == ["preflight.missing_transition_fields:manifest_state"]


def test_cli_reports_malformed_batch_json_as_input_error(tmp_path: Path):
    batch_path = tmp_path / "broken-batch.json"
    batch_path.write_text("{", encoding="utf-8")

    result = _run_cli(batch_path)

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("INPUT_ERROR:")
    assert "Traceback" not in result.stderr