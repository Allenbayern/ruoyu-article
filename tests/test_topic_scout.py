from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from topic_scout import (  # noqa: E402
    AccountPrior,
    build_cards,
    build_ledger,
    enrich_ledger_with_llm,
    main,
    verify_hook_quote,
)

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def _candidate(**overrides: object) -> dict:
    row = {
        "candidate_id": "cand-1",
        "account_id": "MP_WXS_1",
        "account_name": "某影视号",
        "title": "上映3天票房破2亿，豆瓣开分8.5，这部片子却被骂惨了",
        "body": "电影上映三天票房破2亿。" * 60,
        "body_status": "complete",
        "claim_inventory_complete": True,
        "published_at": "2026-09-23T02:00:00+00:00",
        "captured_at": "2026-09-23T04:00:00+00:00",
        "content_hash": "sha256:" + "a" * 64,
        "canonical_url": "https://mp.weixin.qq.com/s/example",
        "projection_id": "derived:1",
    }
    row.update(overrides)
    return row


def _write_run(tmp_path: Path, rows: list[dict]) -> Path:
    run = tmp_path / "run"
    run.mkdir(parents=True, exist_ok=True)
    (run / "article-candidates.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    return run


def _write_pool(tmp_path: Path, *, tags: list[str], status: str = "approved") -> Path:
    pool = tmp_path / "pool.json"
    pool.write_text(
        json.dumps(
            {
                "schema": "approved-viral-account-pool/v1",
                "accounts": [
                    {
                        "account_id": "MP_WXS_1",
                        "account_name": "某影视号",
                        "platform": "wechat",
                        "status": status,
                        "account_class": "film_self_media",
                        "scope_tags": tags,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return pool


def test_film_candidate_from_approved_head_account_becomes_advisory_candidate(tmp_path):
    run = _write_run(tmp_path, [_candidate()])
    pool = _write_pool(tmp_path, tags=["film_tv_article"])

    ledger = build_ledger(run, AccountPrior.load(pool), now=NOW)

    assert len(ledger) == 1
    row = ledger[0]
    assert row["film_relevant"] is True
    assert row["screening_status"] == "advisory_candidate"
    assert row["source_prior_label"] == "approved_head_account"
    # A source prior must never be presented as performance proof.
    assert row["source_prior_is_performance_proof"] is False
    assert row["advisory_only"] is True
    assert row["human_decision"] == "pending"
    assert row["scores"]["source_prior"] == 20


def test_non_film_candidate_is_rejected_not_silently_dropped(tmp_path):
    run = _write_run(
        tmp_path,
        [_candidate(title="2天内6省份省委书记调整", body="社会新闻正文。" * 80)],
    )
    pool = _write_pool(tmp_path, tags=["film_tv_article"])

    ledger = build_ledger(run, AccountPrior.load(pool), now=NOW)

    assert len(ledger) == 1, "rejected rows must stay in the ledger"
    assert ledger[0]["screening_status"] == "rejected"
    assert "非影视题材" in ledger[0]["reject_reasons"]


def test_approved_pool_without_film_scope_gets_weak_prior(tmp_path):
    run = _write_run(tmp_path, [_candidate()])
    pool = _write_pool(tmp_path, tags=["general_content"])

    row = build_ledger(run, AccountPrior.load(pool), now=NOW)[0]

    assert row["source_prior_label"] == "approved_account_non_film_scope"
    assert row["scores"]["source_prior"] == 4


def test_unapproved_pool_account_gets_no_prior(tmp_path):
    run = _write_run(tmp_path, [_candidate()])
    pool = _write_pool(tmp_path, tags=["film_tv_article"], status="paused")

    row = build_ledger(run, AccountPrior.load(pool), now=NOW)[0]

    assert row["source_prior_label"] == "pool_status_not_approved"
    assert row["scores"]["source_prior"] == 0


def test_incomplete_body_is_rejected(tmp_path):
    run = _write_run(
        tmp_path,
        [_candidate(body_status="incomplete", body="太短")],
    )
    pool = _write_pool(tmp_path, tags=["film_tv_article"])

    row = build_ledger(run, AccountPrior.load(pool), now=NOW)[0]

    assert row["screening_status"] == "rejected"
    assert "正文不可用" in row["reject_reasons"]


def test_cards_are_capped_and_never_padded(tmp_path):
    rows = [_candidate(candidate_id=f"cand-{i}", title=f"电影{i}票房破亿，却被骂惨") for i in range(3)]
    run = _write_run(tmp_path, rows)
    pool = _write_pool(tmp_path, tags=["film_tv_article"])
    ledger = build_ledger(run, AccountPrior.load(pool), now=NOW)

    assert len(build_cards(ledger, 5)) == 3, "must not pad up to the cap"
    assert len(build_cards(ledger, 2)) == 2, "must respect a lower cap"


def test_no_eligible_candidate_yields_empty_cards(tmp_path):
    run = _write_run(tmp_path, [_candidate(title="今天吃什么", body="生活内容。" * 80)])
    pool = _write_pool(tmp_path, tags=["film_tv_article"])
    ledger = build_ledger(run, AccountPrior.load(pool), now=NOW)

    assert build_cards(ledger, 5) == []


def test_cli_writes_ledger_cards_and_summary_without_authorising_anything(tmp_path):
    run = _write_run(tmp_path, [_candidate()])
    pool = _write_pool(tmp_path, tags=["film_tv_article"])
    out = tmp_path / "out"

    code = main(
        [
            "--research-run", str(run),
            "--account-pool", str(pool),
            "--out-dir", str(out),
            "--max-cards", "5",
        ]
    )

    assert code == 0
    summary = json.loads((out / "scout-summary.json").read_text(encoding="utf-8"))
    assert summary["advisory_only"] is True
    boundaries = summary["boundaries"]
    assert boundaries["decides_topic"] is False
    assert boundaries["authorises_writing"] is False
    assert boundaries["authorises_publication"] is False
    assert boundaries["upgrades_to_verified_viral"] is False
    assert (out / "candidate-ledger.jsonl").is_file()
    assert "advisory only" in (out / "candidate-cards.md").read_text(encoding="utf-8")


def test_missing_research_run_fails_closed(tmp_path):
    code = main(
        [
            "--research-run", str(tmp_path / "nope"),
            "--out-dir", str(tmp_path / "out"),
        ]
    )

    assert code == 2


def test_refuses_to_overwrite_a_previous_scout_output(tmp_path):
    run = _write_run(tmp_path, [_candidate()])
    pool = _write_pool(tmp_path, tags=["film_tv_article"])
    out = tmp_path / "out"
    args = [
        "--research-run", str(run),
        "--account-pool", str(pool),
        "--out-dir", str(out),
    ]

    assert main(args) == 0
    assert main(args) == 3, "a second run must refuse rather than overwrite"
    assert main([*args, "--allow-overwrite"]) == 0


def test_refuses_to_write_inside_a_sealed_run(tmp_path):
    run = _write_run(tmp_path, [_candidate()])
    pool = _write_pool(tmp_path, tags=["film_tv_article"])
    sealed = tmp_path / "sealed-run"
    sealed.mkdir()
    (sealed / "SEALED").write_text("sealed\n", encoding="utf-8")

    code = main(
        [
            "--research-run", str(run),
            "--account-pool", str(pool),
            "--out-dir", str(sealed / "scout"),
        ]
    )

    assert code == 3
    assert not (sealed / "scout").exists()


def test_missing_account_pool_degrades_gracefully(tmp_path):
    run = _write_run(tmp_path, [_candidate()])

    ledger = build_ledger(run, AccountPrior.load(None), now=NOW)

    assert ledger[0]["source_prior_label"] == "not_in_pool"
    assert ledger[0]["film_relevant"] is True


# --- LLM enrichment ---------------------------------------------------------

BODY = "电影上映三天票房破2亿。" * 60
FAKE_ENV = {"RUOYU_LLM_MODEL": "test-model", "RUOYU_LLM_API_KEY": "x", "RUOYU_LLM_BASE_URL": "http://x"}


def _eligible_ledger(tmp_path: Path) -> list[dict]:
    run = _write_run(tmp_path, [_candidate(body=BODY)])
    pool = _write_pool(tmp_path, tags=["film_tv_article"])
    return build_ledger(run, AccountPrior.load(pool), now=NOW)


def _fake_chat(payload: list[dict]):
    def _chat(env, system, user, **kwargs):
        return json.dumps(payload, ensure_ascii=False)

    return _chat


def test_llm_hook_must_be_verbatim_in_body(tmp_path):
    assert verify_hook_quote("电影上映三天票房破2亿", BODY)[0] is True
    ok, reason = verify_hook_quote("这句是模型自己编的，正文里没有", BODY)
    assert ok is False
    assert reason == "hook_not_in_body"


def test_llm_hook_that_is_fabricated_falls_back_to_heuristic(tmp_path):
    ledger = _eligible_ledger(tmp_path)
    before = ledger[0]["hook_draft"]

    stats = enrich_ledger_with_llm(
        ledger,
        env=FAKE_ENV,
        chat_fn=_fake_chat([{"i": 0, "hook": "完全编造的一句钩子", "direction": "口碑与评分", "question": "?"}]),
    )

    row = ledger[0]
    assert row["hook_method"] == "heuristic", "fabricated hook must not be used"
    assert row["hook_draft"] == before
    assert row["llm_hook_rejected_reason"] == "hook_not_in_body"
    assert stats["hook_rejected"] == 1


def test_llm_verbatim_hook_is_applied(tmp_path):
    ledger = _eligible_ledger(tmp_path)
    real_slice = BODY[:30]

    enrich_ledger_with_llm(
        ledger,
        env=FAKE_ENV,
        chat_fn=_fake_chat([{"i": 0, "hook": real_slice, "direction": "市场与档期", "question": "这片为什么被骂"}]),
    )

    row = ledger[0]
    assert row["hook_draft"] == real_slice
    assert row["hook_method"] == "llm_verified_verbatim"
    assert row["direction_bucket"] == "市场与档期"
    assert row["direction_method"] == "llm"
    assert row["reader_question_draft"] == "这片为什么被骂"
    assert row["llm_status"] == "applied"
    assert row["llm_model"] == "test-model"


def test_llm_direction_outside_closed_set_is_rejected(tmp_path):
    ledger = _eligible_ledger(tmp_path)

    stats = enrich_ledger_with_llm(
        ledger,
        env=FAKE_ENV,
        chat_fn=_fake_chat([{"i": 0, "hook": BODY[:30], "direction": "我自己发明的新方向"}]),
    )

    assert ledger[0]["direction_method"] == "heuristic"
    assert ledger[0]["direction_bucket"] in {
        "市场与档期", "口碑与评分", "人物与演员", "观众与情绪",
        "奖项与荣誉", "行业与政策", "平台与资本", "未归类",
    }
    assert stats["direction_rejected"] == 1


def test_llm_unavailable_degrades_and_run_still_succeeds(tmp_path):
    from scripts.llm_client import LlmUnavailable

    ledger = _eligible_ledger(tmp_path)
    before = ledger[0]["hook_draft"]

    def _boom(env, system, user, **kwargs):
        raise LlmUnavailable("network_error")

    stats = enrich_ledger_with_llm(ledger, env=FAKE_ENV, chat_fn=_boom)

    assert ledger[0]["llm_status"] == "unavailable"
    assert ledger[0]["hook_draft"] == before
    assert stats["unavailable"] == 1


def test_llm_cannot_change_eligibility_or_scores(tmp_path):
    ledger = _eligible_ledger(tmp_path)
    scores_before = dict(ledger[0]["scores"])
    status_before = ledger[0]["screening_status"]

    enrich_ledger_with_llm(
        ledger,
        env=FAKE_ENV,
        chat_fn=_fake_chat([{"i": 0, "hook": BODY[:30], "direction": "口碑与评分",
                             "question": "q", "screening_status": "rejected", "scores": {"total": 999}}]),
    )

    assert ledger[0]["screening_status"] == status_before
    assert ledger[0]["scores"] == scores_before


def test_llm_only_enriches_screened_candidates(tmp_path):
    run = _write_run(
        tmp_path,
        [
            _candidate(candidate_id="ok", body=BODY),
            _candidate(candidate_id="noise", title="今天吃什么", body="生活内容。" * 80),
        ],
    )
    pool = _write_pool(tmp_path, tags=["film_tv_article"])
    ledger = build_ledger(run, AccountPrior.load(pool), now=NOW)

    stats = enrich_ledger_with_llm(
        ledger,
        env=FAKE_ENV,
        chat_fn=_fake_chat([{"i": 0, "hook": BODY[:30], "direction": "口碑与评分", "question": "q"}]),
    )

    assert stats["requested"] == 1, "rejected rows must not be sent to the LLM"
    noise = next(r for r in ledger if r["candidate_id"] == "noise")
    assert noise["llm_status"] == "not_requested"


def test_llm_limit_caps_requests(tmp_path):
    run = _write_run(
        tmp_path,
        [_candidate(candidate_id=f"c{i}", title=f"电影{i}票房破亿却被骂") for i in range(4)],
    )
    pool = _write_pool(tmp_path, tags=["film_tv_article"])
    ledger = build_ledger(run, AccountPrior.load(pool), now=NOW)

    stats = enrich_ledger_with_llm(
        ledger,
        env=FAKE_ENV,
        chat_fn=_fake_chat([{"i": 0, "hook": BODY[:30], "direction": "口碑与评分", "question": "q"}]),
        limit=2,
    )

    assert stats["requested"] == 2


def test_llm_body_carrier_is_not_persisted(tmp_path):
    run = _write_run(tmp_path, [_candidate(body=BODY)])
    pool = _write_pool(tmp_path, tags=["film_tv_article"])
    out = tmp_path / "out"

    code = main(
        [
            "--research-run", str(run),
            "--account-pool", str(pool),
            "--out-dir", str(out),
        ]
    )

    assert code == 0
    for line in (out / "candidate-ledger.jsonl").read_text(encoding="utf-8").splitlines():
        assert "_body" not in json.loads(line)


def test_llm_flag_is_off_by_default(tmp_path):
    run = _write_run(tmp_path, [_candidate(body=BODY)])
    pool = _write_pool(tmp_path, tags=["film_tv_article"])
    out = tmp_path / "out"

    assert main(["--research-run", str(run), "--account-pool", str(pool), "--out-dir", str(out)]) == 0
    summary = json.loads((out / "scout-summary.json").read_text(encoding="utf-8"))

    assert summary["llm"]["enabled"] is False
    assert summary["llm"]["note"] == "not_requested"


# --- LLM hook score re-ranks ------------------------------------------------


def test_llm_hook_score_reranks_without_changing_eligibility(tmp_path):
    # "a" scores high on the deterministic hook heuristic, "b" scores 0; the
    # LLM then inverts them, so the final order proves re-ranking happened.
    strong_title = '上映3天狂揽2亿，豆瓣却被骂惨了？"最"烂'
    weak_title = "电影B的一点观后感"
    rows = [
        _candidate(candidate_id="a", title=strong_title, body=BODY),
        _candidate(candidate_id="b", title=weak_title, body=BODY),
    ]
    run = _write_run(tmp_path, rows)
    pool = _write_pool(tmp_path, tags=["film_tv_article"])
    ledger = build_ledger(run, AccountPrior.load(pool), now=NOW)

    # deterministic baseline: "a" leads
    assert ledger[0]["candidate_id"] == "a"
    assert ledger[0]["scores"]["hook_strength"] > ledger[1]["scores"]["hook_strength"]
    statuses_before = {r["candidate_id"]: r["screening_status"] for r in ledger}

    enrich_ledger_with_llm(
        ledger,
        env=FAKE_ENV,
        chat_fn=_fake_chat([
            {"i": 0, "hook": BODY[:30], "hook_score": 1, "direction": "口碑与评分", "question": "q"},
            {"i": 1, "hook": BODY[30:60], "hook_score": 10, "direction": "口碑与评分", "question": "q"},
        ]),
    )
    by_id = {r["candidate_id"]: r for r in ledger}

    # the LLM verdict flipped the order
    assert ledger[0]["candidate_id"] == "b", "LLM hook scores must re-rank"
    assert by_id["a"]["scores"]["hook_strength"] == 3
    assert by_id["b"]["scores"]["hook_strength"] == 30
    assert by_id["a"]["hook_score_basis"] == "llm"
    # eligibility did not move
    assert {r["candidate_id"]: r["screening_status"] for r in ledger} == statuses_before


def test_invalid_hook_score_keeps_deterministic_ranking(tmp_path):
    ledger = _eligible_ledger(tmp_path)
    before = ledger[0]["scores"]["hook_strength"]

    stats = enrich_ledger_with_llm(
        ledger,
        env=FAKE_ENV,
        chat_fn=_fake_chat([{"i": 0, "hook": BODY[:30], "hook_score": 99, "direction": "口碑与评分"}]),
    )

    assert ledger[0]["scores"]["hook_strength"] == before
    assert ledger[0]["hook_score_basis"] == "heuristic"
    assert stats["hook_score_rejected"] == 1


def test_rejected_hook_cannot_carry_its_score(tmp_path):
    ledger = _eligible_ledger(tmp_path)
    before = ledger[0]["scores"]["hook_strength"]

    enrich_ledger_with_llm(
        ledger,
        env=FAKE_ENV,
        chat_fn=_fake_chat([{"i": 0, "hook": "编造的钩子不在正文", "hook_score": 10, "direction": "口碑与评分"}]),
    )

    assert ledger[0]["hook_method"] == "heuristic"
    assert ledger[0]["scores"]["hook_strength"] == before, "a rejected quote must not raise the score"


# --- LLM risk assessment ----------------------------------------------------


def _risk_candidate(tmp_path: Path) -> list[dict]:
    """Body deliberately mentions a death term so keyword screening fires."""

    body = "这部影片里主角经历了离世与告别。" + BODY
    run = _write_run(tmp_path, [_candidate(body=body)])
    pool = _write_pool(tmp_path, tags=["film_tv_article"])
    return build_ledger(run, AccountPrior.load(pool), now=NOW)


def test_llm_clears_keyword_false_positive_but_keeps_it_visible(tmp_path):
    ledger = _risk_candidate(tmp_path)
    assert ledger[0]["risk_flags"], "keyword screen should have fired on this body"

    stats = enrich_ledger_with_llm(
        ledger,
        env=FAKE_ENV,
        chat_fn=_fake_chat([{
            "i": 0, "hook": "这部影片里主角经历了离世与告别。", "hook_score": 6,
            "direction": "观众与情绪", "question": "q",
            "risk_level": "none", "risk_codes": [], "risk_reason": "仅影片情节提及",
        }]),
    )

    row = ledger[0]
    assert row["risk_assessment"]["level"] == "none"
    assert row["risk_assessment"]["method"] == "llm"
    assert row["risk_assessment"]["overrode_keyword_flags"] is True
    assert row["risk_flags"], "keyword hits stay on the row for audit"
    assert stats["risk_cleared"] == 1


def test_risk_failure_is_fail_safe_never_reports_clear(tmp_path):
    from scripts.llm_client import LlmUnavailable

    ledger = _risk_candidate(tmp_path)

    def _boom(env, system, user, **kwargs):
        raise LlmUnavailable("timeout")

    stats = enrich_ledger_with_llm(ledger, env=FAKE_ENV, chat_fn=_boom)

    row = ledger[0]
    assert row["risk_assessment"]["method"] == "heuristic_unverified"
    assert row["risk_assessment"]["level"] != "none", "failure must never read as cleared"
    assert row["risk_assessment"]["level"] == "unknown"
    assert row["risk_assessment"]["codes"], "keyword codes are retained"
    assert stats["unavailable"] == 1


def test_invalid_risk_level_is_unverified_not_cleared(tmp_path):
    ledger = _risk_candidate(tmp_path)

    stats = enrich_ledger_with_llm(
        ledger,
        env=FAKE_ENV,
        chat_fn=_fake_chat([{
            "i": 0, "hook": BODY[:30], "hook_score": 5, "direction": "观众与情绪",
            "risk_level": "肯定没问题", "risk_codes": [],
        }]),
    )

    row = ledger[0]
    assert row["risk_assessment"]["method"] == "heuristic_unverified"
    assert row["risk_assessment"]["level"] == "unknown"
    assert stats["risk_level_rejected"] == 1


def test_risk_codes_are_filtered_to_closed_set(tmp_path):
    ledger = _risk_candidate(tmp_path)

    enrich_ledger_with_llm(
        ledger,
        env=FAKE_ENV,
        chat_fn=_fake_chat([{
            "i": 0, "hook": BODY[:30], "hook_score": 5, "direction": "观众与情绪",
            "risk_level": "medium",
            "risk_codes": ["privacy_individual", "invented_code", "death_or_suicide"],
        }]),
    )

    assert ledger[0]["risk_assessment"]["codes"] == ["privacy_individual", "death_or_suicide"]


def test_card_renders_unverified_risk_warning(tmp_path):
    run = _write_run(tmp_path, [_candidate(body=BODY)])
    pool = _write_pool(tmp_path, tags=["film_tv_article"])
    out = tmp_path / "out"

    # no --llm: risk never assessed, so the card must not imply it was cleared
    assert main(["--research-run", str(run), "--account-pool", str(pool), "--out-dir", str(out)]) == 0
    cards = (out / "candidate-cards.md").read_text(encoding="utf-8")

    assert "未复核" in cards
    assert "不得**视为已排除风险" in cards or "不得" in cards
