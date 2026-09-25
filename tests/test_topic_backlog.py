from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from topic_backlog import (  # noqa: E402
    BacklogError,
    _connect,
    adopt,
    counts_by_state,
    decide,
    export_jsonl,
    ingest,
    item_key_for,
    list_items,
    main,
    render,
    retract,
)

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
STAMP = NOW.isoformat()


def _row(**overrides: object) -> dict:
    row = {
        "candidate_id": "derived:abc123",
        "content_hash": "sha256:deadbeef",
        "canonical_url": "https://mp.weixin.qq.com/s/example",
        "account_name": "某影视号",
        "title": "《云雀叫天录》张一山演技如何？",
        "hook_draft": "这戏这角儿，换谁都不行。",
        "reader_question_draft": "张一山到底会不会演戏？",
        "published_at": "2026-09-22T02:00:00+00:00",
        "screening_status": "advisory_candidate",
        "scores": {"total": 90, "evidence_readiness": 40},
        "direction_bucket": "performance",
        "risk_assessment": {"level": "none", "method": "llm", "codes": []},
        "source_prior_label": "approved_head_account",
    }
    row.update(overrides)
    return row


@pytest.fixture()
def conn(tmp_path: Path):
    connection = _connect(tmp_path / "backlog.sqlite")
    yield connection
    connection.close()


# --- identity -------------------------------------------------------------------


def test_key_prefers_content_hash_then_url_then_candidate_id():
    assert item_key_for(_row()) == "sha256:deadbeef"
    assert item_key_for(_row(content_hash="")).startswith("url:")
    assert item_key_for(_row(content_hash="", canonical_url="")) == "cid:derived:abc123"


def test_key_is_stable_for_the_same_article_across_days():
    first = item_key_for(_row())
    second = item_key_for(_row(candidate_id="derived:DIFFERENT", title="换了标题"))

    assert first == second, "same content must collapse to one backlog entry"


def test_item_without_identity_is_refused():
    with pytest.raises(BacklogError, match="without_any_identity"):
        item_key_for({"content_hash": "", "canonical_url": "", "candidate_id": "",
                      "title": "   "})


# --- ingestion is automatic, disposition is not ---------------------------------


def test_only_advisory_candidates_are_ingested(conn):
    stats = ingest(conn, [
        _row(candidate_id="a", content_hash="sha256:a"),
        _row(candidate_id="b", content_hash="sha256:b", screening_status="rejected"),
    ], run_dir="runs/2026-09-23/x", now=STAMP)

    assert stats["added"] == 1
    assert stats["skipped_not_advisory"] == 1
    assert len(list_items(conn)) == 1


def test_new_items_arrive_undecided(conn):
    ingest(conn, [_row()], now=STAMP)

    item = list_items(conn)[0]
    assert item["state"] == "new"
    assert item["decided_by"] is None
    assert item["decided_at"] is None


def test_reingest_updates_sighting_without_duplicating(conn):
    ingest(conn, [_row()], run_dir="day1", now="2026-09-23T08:00:00+00:00")
    stats = ingest(conn, [_row()], run_dir="day2", now="2026-09-24T08:00:00+00:00")

    assert stats["added"] == 0
    assert stats["updated"] == 1
    item = list_items(conn)[0]
    assert item["seen_count"] == 2
    assert item["first_run_dir"] == "day1"
    assert item["last_run_dir"] == "day2"


def test_ingested_item_keeps_its_first_seen_timestamp(conn):
    ingest(conn, [_row()], now="2026-09-23T08:00:00+00:00")
    ingest(conn, [_row()], now="2026-09-25T08:00:00+00:00")

    item = list_items(conn)[0]
    assert item["first_seen_at"] == "2026-09-23T08:00:00+00:00"
    assert item["last_seen_at"] == "2026-09-25T08:00:00+00:00"


# --- a dropped item must not resurrect ------------------------------------------


def test_dropped_item_stays_dropped_when_it_reappears(conn):
    ingest(conn, [_row()], now=STAMP)
    key = list_items(conn)[0]["item_key"]
    decide(conn, key, "dropped", by="controller", reason="没意思", now=STAMP)

    stats = ingest(conn, [_row()], now="2026-09-30T08:00:00+00:00")

    item = list_items(conn)[0]
    assert item["state"] == "dropped", "the same noise must not return every morning"
    assert item["seen_count"] == 2
    assert stats["resighted_after_drop"] == 1
    events = [r["event_type"] for r in conn.execute(
        "SELECT event_type FROM backlog_events WHERE item_key = ?", (key,)).fetchall()]
    assert "resighted_after_drop" in events


# --- controller authority -------------------------------------------------------


def test_decide_requires_a_named_actor(conn):
    ingest(conn, [_row()], now=STAMP)
    key = list_items(conn)[0]["item_key"]

    with pytest.raises(BacklogError, match="actor_required"):
        decide(conn, key, "backlog", by="   ", now=STAMP)


def test_decide_rejects_non_controller_states(conn):
    ingest(conn, [_row()], now=STAMP)
    key = list_items(conn)[0]["item_key"]

    for bad in ("new", "adopted"):
        with pytest.raises(BacklogError, match="invalid_state"):
            decide(conn, key, bad, by="controller", now=STAMP)


def test_decide_rejects_unknown_item(conn):
    with pytest.raises(BacklogError, match="unknown_item"):
        decide(conn, "sha256:nope", "backlog", by="controller", now=STAMP)


def test_decide_accepts_an_unambiguous_key_prefix(conn):
    ingest(conn, [_row(content_hash="sha256:aaaa1111")], now=STAMP)

    result = decide(conn, "sha256:aaaa", "backlog", by="controller", now=STAMP)

    assert result["item_key"] == "sha256:aaaa1111"


def test_ambiguous_key_prefix_is_refused_not_guessed(conn):
    ingest(conn, [_row(content_hash="sha256:aaaa1111"),
                  _row(content_hash="sha256:aaaa2222")], now=STAMP)

    with pytest.raises(BacklogError, match="ambiguous_item_key"):
        decide(conn, "sha256:aaaa", "backlog", by="controller", now=STAMP)


def test_adopt_accepts_a_key_prefix_too(conn):
    ingest(conn, [_row(content_hash="sha256:bbbb9999")], now=STAMP)
    decide(conn, "sha256:bbbb", "selected", by="controller", now=STAMP)

    adopt(conn, "sha256:bbbb", run_id="2026-09-23/daily-014", by="controller", now=STAMP)

    assert list_items(conn)[0]["adopted_run_id"] == "2026-09-23/daily-014"


# --- corrections stay auditable -------------------------------------------------


def test_retract_returns_an_item_to_new_and_clears_the_call(conn):
    ingest(conn, [_row()], now=STAMP)
    decide(conn, "sha256:deadbeef", "dropped", by="someone", reason="手滑", now=STAMP)

    result = retract(conn, "sha256:deadbeef", by="controller",
                     reason="误标，恢复", now=STAMP)

    assert result["from_state"] == "dropped"
    assert result["previous_actor"] == "someone"
    item = list_items(conn)[0]
    assert item["state"] == "new"
    assert item["decided_by"] is None
    assert item["decision_reason"] is None


def test_retract_keeps_the_original_decision_in_the_event_log(conn):
    ingest(conn, [_row()], now=STAMP)
    decide(conn, "sha256:deadbeef", "backlog", by="someone", reason="先存着", now=STAMP)
    retract(conn, "sha256:deadbeef", by="controller", reason="误标", now=STAMP)

    events = [dict(r) for r in conn.execute(
        "SELECT event_type, from_state, to_state, actor FROM backlog_events ORDER BY event_id"
    ).fetchall()]
    kinds = [e["event_type"] for e in events]

    assert kinds == ["ingested", "disposition", "retraction"], "history must not be erased"
    assert events[1]["actor"] == "someone"


def test_retract_requires_actor_and_reason(conn):
    ingest(conn, [_row()], now=STAMP)
    decide(conn, "sha256:deadbeef", "backlog", by="controller", now=STAMP)

    with pytest.raises(BacklogError, match="actor_required"):
        retract(conn, "sha256:deadbeef", by="", reason="x", now=STAMP)
    with pytest.raises(BacklogError, match="reason_required"):
        retract(conn, "sha256:deadbeef", by="controller", reason="  ", now=STAMP)


def test_retract_refuses_when_there_is_nothing_to_undo(conn):
    ingest(conn, [_row()], now=STAMP)

    with pytest.raises(BacklogError, match="nothing_to_retract"):
        retract(conn, "sha256:deadbeef", by="controller", reason="x", now=STAMP)


def test_retract_also_clears_an_adoption_link(conn):
    ingest(conn, [_row()], now=STAMP)
    decide(conn, "sha256:deadbeef", "selected", by="controller", now=STAMP)
    adopt(conn, "sha256:deadbeef", run_id="2026-09-23/daily-014", by="controller", now=STAMP)

    retract(conn, "sha256:deadbeef", by="controller", reason="批次取消", now=STAMP)

    item = list_items(conn)[0]
    assert item["state"] == "new"
    assert item["adopted_run_id"] is None


def test_unverified_risk_cannot_be_selected(conn):
    ingest(conn, [_row(risk_assessment={"level": "unknown",
                                        "method": "heuristic_unverified",
                                        "codes": []})], now=STAMP)
    key = list_items(conn)[0]["item_key"]

    with pytest.raises(BacklogError, match="risk_unverified_cannot_be_selected"):
        decide(conn, key, "selected", by="controller", now=STAMP)


def test_unverified_risk_may_still_be_backlogged(conn):
    ingest(conn, [_row(risk_assessment={"level": "unknown",
                                        "method": "heuristic_unverified",
                                        "codes": []})], now=STAMP)
    key = list_items(conn)[0]["item_key"]

    result = decide(conn, key, "backlog", by="controller", reason="先存着", now=STAMP)

    assert result["to_state"] == "backlog"
    assert list_items(conn)[0]["risk_unverified"] == 1


def test_disposition_is_recorded_with_actor_and_reason(conn):
    ingest(conn, [_row()], now=STAMP)
    key = list_items(conn)[0]["item_key"]

    decide(conn, key, "backlog", by="controller", reason="等第二篇材料", now=STAMP)

    item = list_items(conn)[0]
    assert item["state"] == "backlog"
    assert item["decided_by"] == "controller"
    assert item["decision_reason"] == "等第二篇材料"
    event = conn.execute(
        "SELECT * FROM backlog_events WHERE event_type='disposition'").fetchone()
    assert (event["from_state"], event["to_state"], event["actor"]) == \
        ("new", "backlog", "controller")


# --- adoption -------------------------------------------------------------------


def test_adopt_links_an_item_to_the_batch_it_entered(conn):
    ingest(conn, [_row()], now=STAMP)
    key = list_items(conn)[0]["item_key"]
    decide(conn, key, "selected", by="controller", now=STAMP)

    adopt(conn, key, run_id="2026-09-23/daily-014", by="controller", now=STAMP)

    item = list_items(conn)[0]
    assert item["state"] == "adopted"
    assert item["adopted_run_id"] == "2026-09-23/daily-014"


def test_adopt_requires_actor_and_run_id(conn):
    ingest(conn, [_row()], now=STAMP)
    key = list_items(conn)[0]["item_key"]
    decide(conn, key, "selected", by="controller", now=STAMP)

    with pytest.raises(BacklogError, match="actor_required"):
        adopt(conn, key, run_id="r", by="", now=STAMP)
    with pytest.raises(BacklogError, match="run_id_required"):
        adopt(conn, key, run_id="  ", by="controller", now=STAMP)


def test_cannot_adopt_an_undecided_or_dropped_item(conn):
    ingest(conn, [_row()], now=STAMP)
    key = list_items(conn)[0]["item_key"]

    with pytest.raises(BacklogError, match="cannot_adopt_from_state:new"):
        adopt(conn, key, run_id="r", by="controller", now=STAMP)

    decide(conn, key, "dropped", by="controller", now=STAMP)
    with pytest.raises(BacklogError, match="cannot_adopt_from_state:dropped"):
        adopt(conn, key, run_id="r", by="controller", now=STAMP)


# --- rendering ------------------------------------------------------------------


def test_render_shows_counts_boundaries_and_never_hides_new_items(conn):
    ingest(conn, [_row(content_hash="sha256:a", title="甲"),
                  _row(content_hash="sha256:b", title="乙")], now=STAMP)
    key_a = [i for i in list_items(conn) if i["title"] == "甲"][0]["item_key"]
    decide(conn, key_a, "backlog", by="controller", reason="等时机", now=STAMP)

    text = render(conn, now=NOW)

    assert "入库是自动的，表态不是" in text
    assert "待你表态" in text and "储备中" in text
    assert "乙" in text or "甲" in text
    assert "不会自动复活" in text
    assert "不授权任何写作或发布" in text


def test_render_flags_unverified_risk(conn):
    ingest(conn, [_row(risk_assessment={"level": "unknown",
                                        "method": "heuristic_unverified",
                                        "codes": []})], now=STAMP)

    assert "风险未经复核" in render(conn, now=NOW)


# --- CLI ------------------------------------------------------------------------


def _ledger(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "ledger.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8")
    return path


def test_cli_ingest_then_list_then_decide(tmp_path, capsys):
    db = tmp_path / "backlog.sqlite"
    ledger = _ledger(tmp_path, [_row()])

    assert main(["--db", str(db), "ingest", "--scout-ledger", str(ledger),
                 "--run-dir", "runs/2026-09-23/x"]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["added"] == 1 and stats["totals"] == {"new": 1}

    assert main(["--db", str(db), "list", "--state", "new", "--json"]) == 0
    items = json.loads(capsys.readouterr().out)
    assert len(items) == 1
    key = items[0]["item_key"]

    assert main(["--db", str(db), "decide", "--key", key, "--state", "backlog",
                 "--reason", "存着", "--by", "controller"]) == 0
    assert json.loads(capsys.readouterr().out)["to_state"] == "backlog"


def test_cli_decide_without_actor_fails_closed(tmp_path, capsys):
    db = tmp_path / "backlog.sqlite"
    ledger = _ledger(tmp_path, [_row()])
    main(["--db", str(db), "ingest", "--scout-ledger", str(ledger)])
    capsys.readouterr()

    code = main(["--db", str(db), "decide", "--key", "sha256:deadbeef",
                 "--state", "backlog"])

    assert code == 2
    assert "actor_required" in capsys.readouterr().out


def test_cli_render_writes_markdown(tmp_path):
    db = tmp_path / "backlog.sqlite"
    ledger = _ledger(tmp_path, [_row()])
    main(["--db", str(db), "ingest", "--scout-ledger", str(ledger)])
    out = tmp_path / "backlog.md"

    assert main(["--db", str(db), "render", "--out", str(out)]) == 0

    assert "跨天选题储备池" in out.read_text(encoding="utf-8")


def test_cli_ingest_missing_ledger_fails_closed(tmp_path):
    code = main(["--db", str(tmp_path / "b.sqlite"), "ingest",
                 "--scout-ledger", str(tmp_path / "nope.jsonl")])

    assert code == 2


# --- 导出：储备池是单副本生产状态，必须有可 diff 的文本快照 --------------------
#
# 2026-09-25：`run/topic-backlog.sqlite` 曾是全机唯一一份，里面的 controller 表态
# （含「放弃不复活」的历史）没有任何备份。JSONL 导出让这份状态可人读、可 diff、可另存。


def test_export_jsonl_writes_items_and_events(conn, tmp_path):
    ingest(conn, [_row()], run_dir="runs/2026-09-23/topic-scout-llm-001")
    key = item_key_for(_row())
    decide(conn, key, "backlog", by="controller", reason="等第二篇材料")

    out = tmp_path / "backlog.jsonl"
    stats = export_jsonl(conn, out)

    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
    kinds = [line["record"] for line in lines]
    # 头一条是 meta：回答"这份快照相对库有多旧"（复核 F9）
    assert kinds[0] == "meta" and kinds.count("item") == 1 and kinds.count("event") >= 2
    meta = lines[0]
    assert meta["schema_version"] == "backlog-export-v1"
    assert meta["items"] == 1 and meta["data_as_of"], meta
    item = next(line for line in lines if line["record"] == "item")
    assert item["item_key"] == key and item["state"] == "backlog"
    events = [line for line in lines if line["record"] == "event"]
    assert any(e.get("to_state") == "backlog" and e.get("actor") == "controller" for e in events), events
    assert stats["items"] == 1
    # 文本可复读：每一行都是独立合法 JSON（不是一个大 JSON 的片段）
    assert all(isinstance(line, dict) for line in lines)


def test_export_jsonl_is_byte_stable_across_runs(conn, tmp_path):
    """快照要进版本库：同一份库重复导出必须逐字节相同（否则 diff 全是噪声）。"""
    ingest(conn, [_row()], run_dir="runs/2026-09-23/topic-scout-llm-001")

    first = tmp_path / "a.jsonl"
    second = tmp_path / "b.jsonl"
    export_jsonl(conn, first)
    export_jsonl(conn, second)

    assert first.read_bytes() == second.read_bytes()


def test_cli_export_refuses_to_write_into_a_sealed_run(tmp_path, capsys):
    """导出是**写文件**：不能写进封存 run（与 render 同一条护栏）。"""
    sealed = tmp_path / "runs" / "2026-09-23" / "daily-999"
    sealed.mkdir(parents=True)
    (sealed / "SEALED").write_text("{}", encoding="utf-8")
    db = tmp_path / "backlog.sqlite"
    connection = _connect(db)
    try:
        ingest(connection, [_row()], run_dir="x")
    finally:
        connection.close()

    code = main(["--db", str(db), "export", "--out", str(sealed / "backlog.jsonl")])

    assert code == 3
    assert "refuse_sealed_run" in capsys.readouterr().out
    assert not (sealed / "backlog.jsonl").exists()


def test_cli_export_writes_a_text_snapshot(tmp_path):
    db = tmp_path / "backlog.sqlite"
    ledger = _ledger(tmp_path, [_row()])
    main(["--db", str(db), "ingest", "--scout-ledger", str(ledger)])
    out = tmp_path / "backlog.jsonl"

    assert main(["--db", str(db), "export", "--out", str(out)]) == 0

    assert out.is_file() and out.read_text(encoding="utf-8").strip()


def test_export_meta_uses_true_time_order_across_timezones(conn, tmp_path):
    """F4（第二轮复核）：`data_as_of` 此前用**字符串 max**，混时区会取错。

    16:00Z 其实比 23:00+08:00（=15:00Z）更晚，字典序却判后者更大。
    """
    ingest(conn, [_row()], run_dir="x")
    key = item_key_for(_row())
    decide(conn, key, "backlog", by="controller", reason="r", now="2026-09-25T23:00:00+08:00")
    conn.execute("UPDATE backlog_items SET last_seen_at = ? WHERE item_key = ?",
                 ("2026-09-25T16:00:00+00:00", key))
    conn.commit()

    stats = export_jsonl(conn, tmp_path / "s.jsonl")

    assert stats["data_as_of"] == "2026-09-25T16:00:00+00:00", stats


def test_latest_moment_ignores_unparseable_values():
    """解析不出来的值被忽略（宁可少给信息，不猜），全空则给空串。"""
    from topic_backlog import _latest_moment

    assert _latest_moment(["", "  ", "nonsense", "2026-09-25T00:00:00+00:00"]) \
        == "2026-09-25T00:00:00+00:00"
    assert _latest_moment(["", "nonsense"]) == ""
