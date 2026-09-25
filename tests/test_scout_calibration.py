from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from scout_calibration import (  # noqa: E402
    GoldSetError,
    _auc,
    apply_risk_labels,
    build_report,
    extract_risk_review_queue,
    load_gold_set,
    main,
    measure_stability,
    score_risk_screens,
)

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
SEED = ROOT / "tests" / "fixtures" / "scout_calibration" / "hook_gold_seed.jsonl"
V2 = ROOT / "tests" / "fixtures" / "scout_calibration" / "hook_gold_v2.jsonl"


def _item(**overrides: object) -> dict:
    row = {
        "item_id": "i1",
        "stratum": "full_title",
        "label": "good",
        "text": "某标题",
        "basis": "documented_editorial_choice",
        "source_ref": "docs/x.md:1",
    }
    row.update(overrides)
    return row


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "gold.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return path


# --- gold set integrity -----------------------------------------------------


def test_seed_gold_set_loads_and_every_item_has_provenance():
    items = load_gold_set(SEED)

    # 8 user-attested + 2 preferred rewrites = 10 good; 2 rejected rewrites
    # + 3 anti-pattern fragments = 5 bad.
    assert len(items) == 15
    assert sum(1 for i in items if i["label"] == "good") == 10
    assert sum(1 for i in items if i["label"] == "bad") == 5
    assert all(item["source_ref"].strip() for item in items)
    assert {i["label"] for i in items} == {"good", "bad"}


def test_gold_set_refuses_item_without_independent_source_ref(tmp_path):
    path = _write(tmp_path, [_item(source_ref="")])

    with pytest.raises(GoldSetError, match="missing_source_ref"):
        load_gold_set(path)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("label", "maybe", "bad_label"),
        ("basis", "vibes", "bad_basis"),
        ("stratum", "whatever", "bad_stratum"),
        ("text", "   ", "empty_text"),
        ("item_id", "", "bad_item_id"),
    ],
)
def test_gold_set_rejects_invalid_fields(tmp_path, field, value, reason):
    path = _write(tmp_path, [_item(**{field: value})])

    with pytest.raises(GoldSetError, match=reason):
        load_gold_set(path)


def test_gold_set_rejects_duplicate_ids(tmp_path):
    path = _write(tmp_path, [_item(), _item()])

    with pytest.raises(GoldSetError, match="bad_item_id"):
        load_gold_set(path)


def test_gold_set_missing_file_fails_closed(tmp_path):
    with pytest.raises(GoldSetError, match="gold_set_missing"):
        load_gold_set(tmp_path / "nope.jsonl")


# --- expanded set (v2) ------------------------------------------------------


def test_v2_reaches_the_reporting_threshold():
    items = load_gold_set(V2)

    good = sum(1 for i in items if i["label"] == "good")
    bad = sum(1 for i in items if i["label"] == "bad")
    assert len(items) == 26
    assert (good, bad) == (21, 5)
    assert len(items) >= 20, "must cross the measurable-sample total"
    assert good >= 10 and bad >= 5


def test_v2_keeps_core_and_extended_provenance_separate():
    items = load_gold_set(V2)

    tiers = {i["provenance_tier"] for i in items}
    assert tiers == {"core", "extended"}
    extended = [i for i in items if i["provenance_tier"] == "extended"]
    assert len(extended) == 11
    assert all(i["basis"] == "contract_qualified_performance" for i in extended)
    # the weak tier must announce its weakness in the item itself
    assert all("占位符" in i["notes"] for i in extended)


def test_v1_seed_defaults_to_core_tier():
    items = load_gold_set(SEED)

    assert all(i["provenance_tier"] == "core" for i in items)


def test_gold_set_rejects_unknown_tier(tmp_path):
    path = _write(tmp_path, [_item(provenance_tier="vibes")])

    with pytest.raises(GoldSetError, match="bad_tier"):
        load_gold_set(path)


def test_extended_tier_caveat_is_always_reported(tmp_path):
    report = build_report(load_gold_set(V2), {}, generated_at=NOW,
                          gold_set_path=V2, llm_used=False)

    joined = " ".join(report["caveats"])
    assert "extended 层证据弱" in joined
    assert "core 层 AUC 为准" in joined


# --- stability --------------------------------------------------------------


def test_stability_flags_items_that_move_and_reports_pairwise_holding():
    items = [
        {"item_id": "a", "label": "good", "text": "a"},
        {"item_id": "b", "label": "bad", "text": "b"},
        {"item_id": "p", "label": "good", "text": "p", "pair_id": "x", "pair_role": "preferred"},
        {"item_id": "r", "label": "bad", "text": "r", "pair_id": "x", "pair_role": "rejected"},
    ]
    runs = [
        {"a": {"score": 8}, "b": {"score": 8}, "p": {"score": 7}, "r": {"score": 3}},
        {"a": {"score": 8}, "b": {"score": 5}, "p": {"score": 7}, "r": {"score": 3}},
        {"a": {"score": 7}, "b": {"score": 6}, "p": {"score": 6}, "r": {"score": 4}},
    ]

    stability = measure_stability(items, runs)

    assert stability["repeats"] == 3
    assert stability["max_spread"] == 3
    assert stability["unstable_items"] == 1, "only b moves by >= 2"
    assert stability["pairwise_held"] == "3/3"
    assert stability["pairwise_verdicts"] == [True, True, True]


def test_stability_reports_a_flipped_pair():
    items = [
        {"item_id": "p", "label": "good", "text": "p", "pair_id": "x", "pair_role": "preferred"},
        {"item_id": "r", "label": "bad", "text": "r", "pair_id": "x", "pair_role": "rejected"},
    ]
    runs = [
        {"p": {"score": 7}, "r": {"score": 5}},
        {"p": {"score": 7}, "r": {"score": 7}},
    ]

    stability = measure_stability(items, runs)

    assert stability["pairwise_verdicts"] == [True, False]
    assert stability["pairwise_held"] == "1/2"


# --- metrics ----------------------------------------------------------------


def test_auc_is_one_for_perfect_separation():
    assert _auc([9, 8, 7], [2, 1, 0]) == 1.0


def test_auc_is_zero_for_reversed_separation():
    assert _auc([1, 2], [8, 9]) == 0.0


def test_auc_counts_ties_as_half():
    assert _auc([5], [5]) == 0.5


def test_auc_needs_both_groups():
    assert _auc([], [1]) is None
    assert _auc([1], []) is None


def test_pairwise_accuracy_tracks_documented_rewrites():
    items = [
        _item(item_id="a-after", pair_id="p1", pair_role="preferred", text="after"),
        _item(item_id="a-before", label="bad", pair_id="p1", pair_role="rejected", text="before"),
    ]
    scores = {"a-after": {"score": 7}, "a-before": {"score": 5}}

    report = build_report(items, scores, generated_at=NOW, gold_set_path=SEED, llm_used=True)

    assert report["metrics"]["pairwise_accuracy"] == "1/1"
    assert report["metrics"]["pairwise_details"][0]["correct"] is True


def test_small_sample_is_reported_as_insufficient_not_quietly_claimed():
    items = [_item(item_id=f"g{i}") for i in range(3)] + [
        _item(item_id="b0", label="bad")
    ]
    scores = {f"g{i}": {"score": 8} for i in range(3)}
    scores["b0"] = {"score": 2}

    report = build_report(items, scores, generated_at=NOW, gold_set_path=SEED, llm_used=True)

    assert report["calibration_status"] == "insufficient_sample"
    assert any("不足以拟合校准曲线" in c for c in report["caveats"])


def test_report_always_carries_caveats_and_scope_limits():
    report = build_report([_item()], {"i1": {"score": 8}},
                          generated_at=NOW, gold_set_path=SEED, llm_used=True)

    joined = " ".join(report["caveats"])
    assert "不构成爆款预测能力" in joined or "点击率" in joined
    assert "user_attested_performance" in joined, "must warn that performance != hook quality"
    assert "ref-003" in joined, "must record the excluded truncated title"


def test_out_of_range_scores_are_dropped_not_clamped():
    from topic_scout import _coerce_hook_score

    assert _coerce_hook_score(10) == 10
    assert _coerce_hook_score(0) == 0
    assert _coerce_hook_score(11) is None
    assert _coerce_hook_score(-1) is None
    assert _coerce_hook_score("7") is None
    assert _coerce_hook_score(True) is None


# --- CLI --------------------------------------------------------------------


def test_no_llm_mode_validates_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("RUOYU_LLM_API_KEY", "")
    out = tmp_path / "out"

    code = main(["--gold-set", str(SEED), "--out-dir", str(out), "--no-llm"])

    assert code == 0
    report = json.loads((out / "calibration-report.json").read_text(encoding="utf-8"))
    assert report["llm_used"] is False
    assert report["metrics"]["n_scored"] == 0
    assert (out / "calibration-report.md").is_file()


def test_cli_requires_gold_set_and_out_dir(tmp_path):
    with pytest.raises(SystemExit):
        main([])


def test_calibration_refuses_to_overwrite_an_earlier_report(tmp_path):
    out = tmp_path / "out"
    args = ["--gold-set", str(SEED), "--out-dir", str(out), "--no-llm"]

    assert main(args) == 0
    assert main(args) == 3, "a second run must refuse rather than overwrite"


def test_calibration_refuses_to_write_inside_a_sealed_run(tmp_path):
    sealed = tmp_path / "sealed-run"
    sealed.mkdir()
    (sealed / "SEALED").write_text("sealed\n", encoding="utf-8")

    code = main(["--gold-set", str(SEED), "--out-dir", str(sealed / "calib"), "--no-llm"])

    assert code == 3
    assert not (sealed / "calib").exists()


def test_risk_queue_refuses_to_write_inside_a_sealed_run(tmp_path):
    ledger = _ledger(tmp_path, [
        _ledger_row("x", [], {"method": "llm", "level": "low", "codes": ["judicial_case"]}),
    ])
    sealed = tmp_path / "sealed"
    sealed.mkdir()
    (sealed / "SEALED").write_text("sealed\n", encoding="utf-8")

    code = main(["--risk-queue-from", str(ledger),
                 "--risk-queue-out", str(sealed / "queue.json")])

    assert code == 3
    assert not (sealed / "queue.json").exists()


# --- risk labelling queue ---------------------------------------------------


def _ledger(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "ledger.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return path


def _ledger_row(candidate_id: str, keyword_codes: list[str], assessment: dict) -> dict:
    return {
        "candidate_id": candidate_id,
        "title": f"标题{candidate_id}",
        "account_name": "某号",
        "risk_flags": [{"code": c, "label": c, "hits": ["x"]} for c in keyword_codes],
        "risk_assessment": assessment,
    }


def test_risk_queue_captures_only_disagreements(tmp_path):
    ledger = _ledger(tmp_path, [
        _ledger_row("fp", ["judicial_case"], {"method": "llm", "level": "none", "codes": []}),
        _ledger_row("fn", [], {"method": "llm", "level": "medium", "codes": ["political_sensitivity"]}),
        _ledger_row("unv", ["privacy_individual"], {"method": "heuristic_unverified",
                                                    "level": "unknown", "codes": ["privacy_individual"]}),
        _ledger_row("agree", ["privacy_individual"], {"method": "llm", "level": "high",
                                                      "codes": ["privacy_individual"]}),
    ])

    payload = extract_risk_review_queue(ledger, tmp_path / "queue.json")

    kinds = {r["candidate_id"]: r["disagreement"] for r in payload["rows"]}
    assert kinds == {"fp": "keyword_only", "fn": "llm_only", "unv": "unverified"}
    assert "agree" not in kinds, "agreements carry no labelling information"
    assert payload["counts"] == {"total": 3, "keyword_only": 1, "llm_only": 1, "unverified": 1}


def test_risk_queue_rows_are_unlabelled_by_construction(tmp_path):
    ledger = _ledger(tmp_path, [
        _ledger_row("x", [], {"method": "llm", "level": "low", "codes": ["judicial_case"]}),
    ])

    payload = extract_risk_review_queue(ledger, tmp_path / "queue.json")

    row = payload["rows"][0]
    assert row["human_label"] == "", "the queue must not pre-fill a verdict"
    assert row["human_codes"] == []
    assert row["labeler"] == ""
    assert "只标不一致项" in payload["instruction"]


def test_risk_queue_cli_mode_writes_queue(tmp_path):
    ledger = _ledger(tmp_path, [
        _ledger_row("x", ["judicial_case"], {"method": "llm", "level": "none", "codes": []}),
    ])
    out = tmp_path / "queue.json"

    code = main(["--risk-queue-from", str(ledger), "--risk-queue-out", str(out)])

    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["counts"]["total"] == 1


def test_risk_queue_also_writes_a_fillable_markdown_form(tmp_path):
    ledger = _ledger(tmp_path, [
        _ledger_row("x", ["judicial_case"], {"method": "llm", "level": "none", "codes": [],
                                            "reason": "讲的是刑侦剧"}),
    ])
    out = tmp_path / "queue.json"

    assert main(["--risk-queue-from", str(ledger), "--risk-queue-out", str(out)]) == 0
    form = out.with_suffix(".md").read_text(encoding="utf-8")

    assert "待 Controller 填写" in form
    assert "- [ ] `none`" in form
    assert "没有预填判定" in form
    assert "不得当作已排除风险" in form


def test_risk_queue_missing_ledger_fails_closed(tmp_path):
    code = main(["--risk-queue-from", str(tmp_path / "nope.jsonl"),
                 "--risk-queue-out", str(tmp_path / "q.json")])

    assert code == 2


# --- risk labels and screen metrics ----------------------------------------


def _queue(rows: list[dict]) -> dict:
    return {"schema_version": "risk-review-queue-v1", "rows": rows}


def _qrow(item_id: str, keyword_codes: list[str], level: str, disagreement: str) -> dict:
    return {
        "item_id": item_id,
        "title": f"标题{item_id}",
        "keyword_codes": keyword_codes,
        "llm_level": level,
        "llm_codes": [] if level == "none" else ["judicial_case"],
        "disagreement": disagreement,
        "human_label": "",
        "human_codes": [],
        "labeler": "",
        "labeled_at": "",
    }


def test_apply_risk_labels_writes_human_fields():
    payload = _queue([_qrow("a", ["judicial_case"], "none", "keyword_only")])

    updated = apply_risk_labels(payload, {"a": "none"}, labeler="controller",
                                labeled_at="2026-09-23T12:00:00+00:00")

    row = updated["rows"][0]
    assert row["human_label"] == "none"
    assert row["human_codes"] == []
    assert row["labeler"] == "controller"
    assert row["labeled_at"] == "2026-09-23T12:00:00+00:00"
    assert updated["labeled_count"] == 1


def test_apply_risk_labels_refuses_unknown_item():
    payload = _queue([_qrow("a", [], "low", "llm_only")])

    with pytest.raises(GoldSetError, match="unknown_item"):
        apply_risk_labels(payload, {"nope": "none"}, labeler="controller")


def test_apply_risk_labels_refuses_invalid_value():
    payload = _queue([_qrow("a", [], "low", "llm_only")])

    with pytest.raises(GoldSetError, match="invalid"):
        apply_risk_labels(payload, {"a": "probably_fine"}, labeler="controller")


def test_metrics_are_unlabeled_before_any_human_label():
    metrics = score_risk_screens(_queue([_qrow("a", [], "low", "llm_only")]))

    assert metrics["status"] == "unlabeled"
    assert metrics["labeled"] == 0


def test_recall_is_none_not_zero_when_there_are_no_human_positives():
    payload = _queue([
        _qrow("a", ["judicial_case"], "none", "keyword_only"),
        _qrow("b", [], "medium", "llm_only"),
    ])
    apply_risk_labels(payload, {"a": "none", "b": "none"}, labeler="controller")

    metrics = score_risk_screens(payload)

    assert metrics["status"] == "no_positive_labels"
    assert metrics["human_positive_count"] == 0
    assert metrics["keyword_screen"]["fp"] == 1
    assert metrics["keyword_screen"]["precision"] == 0.0
    assert metrics["llm_screen"]["fp"] == 1
    # the crucial distinction: no positives means recall is unknown, not zero
    assert metrics["keyword_screen"]["recall"] is None
    assert metrics["llm_screen"]["recall"] is None
    assert any("不是 0" in n for n in metrics["notes"])


def test_low_precision_is_not_framed_as_a_reason_to_remove_the_screen():
    """A 0.0 precision on a biased sample must not read as 'the screen is broken'."""

    payload = _queue([_qrow("a", ["judicial_case"], "none", "keyword_only")])
    apply_risk_labels(payload, {"a": "none"}, labeler="controller")
    metrics = score_risk_screens(payload)

    joined = " ".join(metrics["notes"])
    assert "既不证明筛查器有效，也不证明其无效" in joined
    assert "不构成移除筛查器的依据" in joined


def test_precision_and_recall_computed_when_a_positive_exists():
    payload = _queue([
        _qrow("hit", ["judicial_case"], "none", "keyword_only"),
        _qrow("miss", [], "medium", "llm_only"),
        _qrow("clean", [], "low", "llm_only"),
    ])
    # human says: "hit" really is a risk; "miss" is a keyword false negative
    apply_risk_labels(payload, {"hit": "high", "miss": "high", "clean": "none"},
                      labeler="controller")

    metrics = score_risk_screens(payload)

    assert metrics["status"] == "measurable"
    assert metrics["human_positive_count"] == 2
    # keyword flagged only "hit"
    assert metrics["keyword_screen"]["precision"] == 1.0
    assert metrics["keyword_screen"]["recall"] == 0.5
    # llm flagged "miss" and "clean", missing "hit"
    assert metrics["llm_screen"]["tp"] == 1
    assert metrics["llm_screen"]["fp"] == 1
    assert metrics["llm_screen"]["fn"] == 1
    assert metrics["llm_screen"]["precision"] == 0.5
    assert metrics["llm_screen"]["recall"] == 0.5


def test_cli_applies_labels_and_writes_metrics_report(tmp_path):
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps(_queue([
        _qrow("a", ["judicial_case"], "none", "keyword_only"),
    ]), ensure_ascii=False), encoding="utf-8")
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"a": "none"}), encoding="utf-8")

    code = main(["--risk-queue-from", str(queue),
                 "--apply-risk-labels", str(labels),
                 "--labeler", "controller"])

    assert code == 0
    saved = json.loads(queue.read_text(encoding="utf-8"))
    assert saved["rows"][0]["human_label"] == "none"
    assert saved["screen_metrics"]["keyword_screen"]["fp"] == 1
    report = (tmp_path / "risk-metrics.md").read_text(encoding="utf-8")
    assert "不可计算" in report
    assert "不得填 0 充当结果" in report


def test_cli_refuses_labels_for_unknown_items(tmp_path):
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps(_queue([_qrow("a", [], "low", "llm_only")])), encoding="utf-8")
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"ghost": "none"}), encoding="utf-8")

    code = main(["--risk-queue-from", str(queue), "--apply-risk-labels", str(labels)])

    assert code == 2
