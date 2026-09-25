#!/usr/bin/env python3
"""Cross-day topic backlog: accumulate advisory cards, record Controller calls.

The scout produces cards for one day.  Without somewhere to put the ones you
want to keep, "储备" is a checkbox with no destination and yesterday's good
idea is gone.  This store keeps them.

Two rules shape the design:

1. **Ingestion is automatic; disposition is not.**  Scanning a ledger only
   ever writes ``state='new'``.  Moving an item to ``backlog`` / ``selected``
   / ``dropped`` requires an explicit ``--by`` actor.  The machine never
   decides which topics matter.

2. **A dropped item stays dropped.**  If the same article resurfaces in a
   later scan, the sighting count and ``last_seen_at`` update but the state
   does not.  Otherwise the same noise returns every morning.

Scope: this store holds *advisory candidates* only (rows the scout marked
``advisory_candidate``).  Screened-out rows stay in the per-run ledger.

Usage::

    # after a scout run
    python scripts/topic_backlog.py ingest --scout-ledger <ledger.jsonl>
    python scripts/topic_backlog.py list --state new
    python scripts/topic_backlog.py decide --key <item_key> --state backlog \
        --reason "等有第二篇材料再写" --by controller
    python scripts/topic_backlog.py adopt --key <item_key> --run-id 2026-09-23/daily-014 \
        --by controller
    python scripts/topic_backlog.py render --out state/topic-backlog.md
    python scripts/topic_backlog.py export --out state/topic-backlog.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.topic_scout import _sealed_ancestor  # noqa: E402

DEFAULT_DB = Path(__file__).resolve().parents[1] / "state" / "topic-backlog.sqlite"

# States the Controller can set.  ``new`` is machine-set only.
CONTROLLER_STATES = ("backlog", "selected", "dropped")
ALL_STATES = ("new", *CONTROLLER_STATES, "adopted")
OPEN_STATES = ("new", "backlog", "selected")

SCHEMA = """
CREATE TABLE IF NOT EXISTS backlog_items (
    item_key TEXT PRIMARY KEY,
    candidate_id TEXT,
    content_hash TEXT,
    canonical_url TEXT,
    account_name TEXT,
    title TEXT NOT NULL,
    hook_draft TEXT,
    reader_question_draft TEXT,
    published_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    seen_count INTEGER NOT NULL DEFAULT 1,
    first_run_dir TEXT,
    last_run_dir TEXT,
    rank_score INTEGER,
    evidence_readiness TEXT,
    direction_bucket TEXT,
    risk_level TEXT,
    risk_method TEXT,
    risk_unverified INTEGER NOT NULL DEFAULT 0,
    source_prior_label TEXT,
    state TEXT NOT NULL DEFAULT 'new',
    decided_by TEXT,
    decided_at TEXT,
    decision_reason TEXT,
    adopted_run_id TEXT
);
CREATE TABLE IF NOT EXISTS backlog_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_key TEXT NOT NULL,
    event_type TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT,
    occurred_at TEXT NOT NULL,
    actor TEXT,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_backlog_state ON backlog_items(state);
CREATE INDEX IF NOT EXISTS idx_events_item ON backlog_events(item_key);
"""


class BacklogError(ValueError):
    """The requested operation cannot proceed safely."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def item_key_for(row: Mapping[str, Any]) -> str:
    """Stable identity across days: content first, then url, then candidate id."""

    content_hash = str(row.get("content_hash") or "").strip()
    if content_hash:
        return content_hash
    url = str(row.get("canonical_url") or "").strip()
    if url:
        return "url:" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    candidate_id = str(row.get("candidate_id") or "").strip()
    if candidate_id:
        return "cid:" + candidate_id
    title = str(row.get("title") or "").strip()
    if title:
        return "title:" + hashlib.sha256(title.encode("utf-8")).hexdigest()[:32]
    raise BacklogError("item_without_any_identity")


def _risk_fields(row: Mapping[str, Any]) -> tuple[str, str, int]:
    assessment = row.get("risk_assessment") or {}
    level = str(assessment.get("level") or "unknown")
    method = str(assessment.get("method") or "none")
    unverified = 1 if method == "heuristic_unverified" or level == "unknown" else 0
    return level, method, unverified


def ingest(
    conn: sqlite3.Connection,
    rows: Iterable[Mapping[str, Any]],
    *,
    run_dir: str = "",
    now: str | None = None,
) -> dict[str, int]:
    """Add or re-sight advisory candidates. Never changes a Controller state."""

    stamp = now or _now()
    added = updated = skipped = resent = 0
    for row in rows:
        if row.get("screening_status") != "advisory_candidate":
            skipped += 1
            continue
        key = item_key_for(row)
        scores = row.get("scores") or {}
        level, method, unverified = _risk_fields(row)
        fields = {
            "candidate_id": str(row.get("candidate_id") or ""),
            "content_hash": str(row.get("content_hash") or ""),
            "canonical_url": str(row.get("canonical_url") or ""),
            "account_name": str(row.get("account_name") or ""),
            "title": str(row.get("title") or ""),
            "hook_draft": str(row.get("hook_draft") or ""),
            "reader_question_draft": str(row.get("reader_question_draft") or ""),
            "published_at": str(row.get("published_at") or ""),
            "last_seen_at": stamp,
            "last_run_dir": run_dir,
            "rank_score": int(scores.get("total") or 0),
            "evidence_readiness": int(scores.get("evidence_readiness") or 0),
            "direction_bucket": str(row.get("direction_bucket") or ""),
            "risk_level": level,
            "risk_method": method,
            "risk_unverified": unverified,
            "source_prior_label": str(row.get("source_prior_label") or ""),
        }
        existing = conn.execute(
            "SELECT state, seen_count FROM backlog_items WHERE item_key = ?", (key,)
        ).fetchone()
        if existing is None:
            conn.execute(
                """INSERT INTO backlog_items
                   (item_key, first_seen_at, first_run_dir, seen_count, state,
                    candidate_id, content_hash, canonical_url, account_name, title,
                    hook_draft, reader_question_draft, published_at, last_seen_at,
                    last_run_dir, rank_score, evidence_readiness, direction_bucket,
                    risk_level, risk_method, risk_unverified, source_prior_label)
                   VALUES (:item_key, :first_seen_at, :run_dir, 1, 'new',
                    :candidate_id, :content_hash, :canonical_url, :account_name, :title,
                    :hook_draft, :reader_question_draft, :published_at, :last_seen_at,
                    :last_run_dir, :rank_score, :evidence_readiness, :direction_bucket,
                    :risk_level, :risk_method, :risk_unverified, :source_prior_label)""",
                {**fields, "item_key": key, "first_seen_at": stamp, "run_dir": run_dir},
            )
            conn.execute(
                """INSERT INTO backlog_events
                   (item_key, event_type, from_state, to_state, occurred_at, actor, detail)
                   VALUES (?, 'ingested', NULL, 'new', ?, 'system', ?)""",
                (key, stamp, run_dir),
            )
            added += 1
            continue

        conn.execute(
            """UPDATE backlog_items SET
                 last_seen_at = :last_seen_at, last_run_dir = :last_run_dir,
                 seen_count = seen_count + 1, rank_score = :rank_score,
                 evidence_readiness = :evidence_readiness,
                 direction_bucket = :direction_bucket,
                 risk_level = :risk_level, risk_method = :risk_method,
                 risk_unverified = :risk_unverified,
                 hook_draft = :hook_draft,
                 reader_question_draft = :reader_question_draft,
                 source_prior_label = :source_prior_label
               WHERE item_key = :item_key""",
            {**fields, "item_key": key},
        )
        # A previously dropped item must not silently come back to life.
        if existing["state"] == "dropped":
            resent += 1
            conn.execute(
                """INSERT INTO backlog_events
                   (item_key, event_type, from_state, to_state, occurred_at, actor, detail)
                   VALUES (?, 'resighted_after_drop', 'dropped', 'dropped', ?, 'system', ?)""",
                (key, stamp, f"seen_count={existing['seen_count'] + 1}"),
            )
        else:
            conn.execute(
                """INSERT INTO backlog_events
                   (item_key, event_type, from_state, to_state, occurred_at, actor, detail)
                   VALUES (?, 'resighted', ?, ?, ?, 'system', ?)""",
                (key, existing["state"], existing["state"], stamp,
                 f"seen_count={existing['seen_count'] + 1}"),
            )
        updated += 1
    conn.commit()
    return {"added": added, "updated": updated, "skipped_not_advisory": skipped,
            "resighted_after_drop": resent}


def _resolve_key(conn: sqlite3.Connection, key_or_prefix: str) -> str:
    """Accept a unique key prefix — the full sha256 is unusable to type.

    Ambiguity is an error, never a guess.
    """

    token = (key_or_prefix or "").strip()
    if not token:
        raise BacklogError("empty_item_key")
    exact = conn.execute("SELECT item_key FROM backlog_items WHERE item_key = ?",
                         (token,)).fetchone()
    if exact is not None:
        return str(exact["item_key"])
    matches = [str(r["item_key"]) for r in conn.execute(
        "SELECT item_key FROM backlog_items WHERE item_key LIKE ?", (token + "%",)).fetchall()]
    if not matches:
        raise BacklogError(f"unknown_item:{token}")
    if len(matches) > 1:
        raise BacklogError(
            f"ambiguous_item_key:{token} 命中 {len(matches)} 条，请多给几位字符"
        )
    return matches[0]


def decide(
    conn: sqlite3.Connection,
    item_key: str,
    state: str,
    *,
    by: str,
    reason: str = "",
    now: str | None = None,
) -> dict[str, Any]:
    """Record a Controller disposition. ``by`` is mandatory on purpose."""

    if not by or not by.strip():
        raise BacklogError("actor_required:决定必须有人署名")
    if state not in CONTROLLER_STATES:
        raise BacklogError(f"invalid_state:{state}，只能是 {'/'.join(CONTROLLER_STATES)}")
    item_key = _resolve_key(conn, item_key)
    row = conn.execute("SELECT * FROM backlog_items WHERE item_key = ?", (item_key,)).fetchone()
    if state == "selected" and row["risk_unverified"]:
        raise BacklogError(
            "risk_unverified_cannot_be_selected:该条未取得风险判定，不得直接圈题；"
            "请先人工确认风险，或改标 backlog"
        )
    stamp = now or _now()
    conn.execute(
        """UPDATE backlog_items SET state = ?, decided_by = ?, decided_at = ?,
             decision_reason = ? WHERE item_key = ?""",
        (state, by.strip(), stamp, reason, item_key),
    )
    conn.execute(
        """INSERT INTO backlog_events
           (item_key, event_type, from_state, to_state, occurred_at, actor, detail)
           VALUES (?, 'disposition', ?, ?, ?, ?, ?)""",
        (item_key, row["state"], state, stamp, by.strip(), reason),
    )
    conn.commit()
    return {"item_key": item_key, "from_state": row["state"], "to_state": state,
            "by": by.strip(), "reason": reason}


def adopt(
    conn: sqlite3.Connection,
    item_key: str,
    *,
    run_id: str,
    by: str,
    now: str | None = None,
) -> dict[str, Any]:
    """Link an item to the batch it actually entered."""

    if not by or not by.strip():
        raise BacklogError("actor_required:采用必须有人署名")
    if not run_id or not run_id.strip():
        raise BacklogError("run_id_required")
    item_key = _resolve_key(conn, item_key)
    row = conn.execute("SELECT * FROM backlog_items WHERE item_key = ?", (item_key,)).fetchone()
    if row["state"] not in ("selected", "backlog"):
        raise BacklogError(f"cannot_adopt_from_state:{row['state']}")
    stamp = now or _now()
    conn.execute(
        """UPDATE backlog_items SET state = 'adopted', adopted_run_id = ?,
             decided_by = ?, decided_at = ? WHERE item_key = ?""",
        (run_id.strip(), by.strip(), stamp, item_key),
    )
    conn.execute(
        """INSERT INTO backlog_events
           (item_key, event_type, from_state, to_state, occurred_at, actor, detail)
           VALUES (?, 'adopted', ?, 'adopted', ?, ?, ?)""",
        (item_key, row["state"], stamp, by.strip(), run_id.strip()),
    )
    conn.commit()
    return {"item_key": item_key, "run_id": run_id.strip(), "by": by.strip()}


def retract(
    conn: sqlite3.Connection,
    item_key: str,
    *,
    by: str,
    reason: str,
    now: str | None = None,
) -> dict[str, Any]:
    """Undo a disposition, returning the item to ``new``.

    Corrections must be auditable: the retraction is logged rather than the
    earlier decision being erased, so a wrong call stays visible.
    """

    if not by or not by.strip():
        raise BacklogError("actor_required:撤销必须有人署名")
    if not reason or not reason.strip():
        raise BacklogError("reason_required:撤销必须写明原因")
    item_key = _resolve_key(conn, item_key)
    row = conn.execute("SELECT * FROM backlog_items WHERE item_key = ?", (item_key,)).fetchone()
    if row["state"] == "new":
        raise BacklogError("nothing_to_retract:该条目本来就没有表态")
    stamp = now or _now()
    conn.execute(
        """UPDATE backlog_items SET state = 'new', decided_by = NULL, decided_at = NULL,
             decision_reason = NULL, adopted_run_id = NULL WHERE item_key = ?""",
        (item_key,),
    )
    conn.execute(
        """INSERT INTO backlog_events
           (item_key, event_type, from_state, to_state, occurred_at, actor, detail)
           VALUES (?, 'retraction', ?, 'new', ?, ?, ?)""",
        (item_key, row["state"], stamp, by.strip(), reason.strip()),
    )
    conn.commit()
    return {"item_key": item_key, "from_state": row["state"], "to_state": "new",
            "by": by.strip(), "reason": reason.strip(),
            "previous_actor": row["decided_by"]}


def list_items(
    conn: sqlite3.Connection,
    *,
    state: str | None = None,
    states: Sequence[str] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if state:
        clauses.append("state = ?")
        params.append(state)
    if states:
        clauses.append("state IN (" + ",".join("?" for _ in states) + ")")
        params.extend(states)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM backlog_items{where} ORDER BY rank_score DESC, last_seen_at DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def counts_by_state(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT state, COUNT(*) n FROM backlog_items GROUP BY state").fetchall()
    return {str(r["state"]): int(r["n"]) for r in rows}


def render(conn: sqlite3.Connection, *, now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    counts = counts_by_state(conn)
    lines: list[str] = []
    lines.append("# 跨天选题储备池")
    lines.append("")
    lines.append(f"> 生成时间：{moment.isoformat()}")
    lines.append("")
    lines.append("| 状态 | 条数 | 含义 |")
    lines.append("| --- | ---: | --- |")
    lines.append(f"| `new` | {counts.get('new', 0)} | 已入库，**你还没表态** |")
    lines.append(f"| `backlog` | {counts.get('backlog', 0)} | 你标了储备，等时机 |")
    lines.append(f"| `selected` | {counts.get('selected', 0)} | 你圈了题，待进批次 |")
    lines.append(f"| `adopted` | {counts.get('adopted', 0)} | 已进入某批次 |")
    lines.append(f"| `dropped` | {counts.get('dropped', 0)} | 你放弃了；**再出现也不会自动复活** |")
    lines.append("")
    lines.append("**入库是自动的，表态不是。** 机器只把候选放进 `new`，")
    lines.append("储备 / 圈题 / 放弃都必须由你署名决定。")
    lines.append("")

    def section(title: str, state: str) -> None:
        items = list_items(conn, state=state, limit=60)
        if not items:
            return
        lines.append(f"## {title}（{len(items)}）")
        lines.append("")
        for item in items:
            age_days = ""
            if item.get("published_at"):
                try:
                    published = datetime.fromisoformat(str(item["published_at"]).replace("Z", "+00:00"))
                    if published.tzinfo is None:
                        published = published.replace(tzinfo=timezone.utc)
                    age_days = f"{int((moment - published).total_seconds() // 86400)}天前"
                except ValueError:
                    age_days = ""
            flags: list[str] = []
            if item.get("risk_unverified"):
                flags.append("⚠️ 风险未经复核")
            if int(item.get("seen_count") or 1) > 1:
                flags.append(f"第{item['seen_count']}次出现")
            lines.append(
                f"- **{int(item.get('rank_score') or 0)}**｜{str(item.get('title'))[:46]}"
                f"　`{item.get('account_name')}`"
                + (f"　{age_days}" if age_days else "")
                + (f"　{'／'.join(flags)}" if flags else "")
            )
            lines.append(f"  - key：`{item.get('item_key')}`")
            if item.get("decision_reason"):
                lines.append(f"  - 你的备注：{item['decision_reason']}"
                             f"（{item.get('decided_by')}）")
            if item.get("adopted_run_id"):
                lines.append(f"  - 已进入：`{item['adopted_run_id']}`")
            if item.get("hook_draft"):
                lines.append(f"  - 强钩草案：{str(item['hook_draft'])[:60]}")
            lines.append("")
        lines.append("")

    section("待你表态", "new")
    section("储备中", "backlog")
    section("已圈题待进批次", "selected")
    section("已进入批次", "adopted")
    lines.append("## 操作")
    lines.append("")
    lines.append("```bash")
    lines.append("python scripts/topic_backlog.py decide --key <key> --state backlog \\")
    lines.append('    --reason "等第二篇材料" --by controller')
    lines.append("python scripts/topic_backlog.py adopt --key <key> --run-id <批次> --by controller")
    lines.append("python scripts/topic_backlog.py render --out state/topic-backlog.md")
    lines.append("```")
    lines.append("")
    lines.append("## 边界")
    lines.append("")
    lines.append("- 入库不等于选上；`new` 只表示「机器觉得可能值得看」。")
    lines.append("- 风险未复核的条目**不得直接圈题**（工具会拒绝）。")
    lines.append("- 被放弃的条目再次出现时**不会自动复活**，只累加出现次数。")
    lines.append("- 本池不授权任何写作或发布。")
    lines.append("")
    return "\n".join(lines)


def _latest_moment(stamps: Iterable[str]) -> str:
    """取最新的时间戳——按**解析后的时刻**比，不是按字符串。

    字符串 `max` 是字典序：`2026-09-25T16:00:00+00:00` 其实比
    `2026-09-25T23:00:00+08:00` 更晚（16:00Z = 次日 00:00+08），字典序却判后者更大，
    于是快照的 `data_as_of` 会报成更早的那个（2026-09-25 第二轮复核 minor）。
    生产 `_now()` 恒为 UTC，所以 CLI 走不到；`now=` 参数与手改库走得到。

    **约定（第三轮复核 F10 要求写明）**：**无时区的时间戳按 UTC 解释**。生产写出的都带
    `+00:00`，naive 只可能来自手改库或别处的 `now=`；把 naive 当本地时间会算错新旧，
    当 UTC 是这里明确的约定，不是巧合。

    返回**原始文本**（不是归一化后的形式）：全 UTC 的正常数据结果与改动前逐字节相同，
    快照的确定性不受影响。解析不出来的值被忽略（宁可少给信息，不猜）。
    """
    best_moment: datetime | None = None
    best_text = ""
    for raw in stamps:
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        if best_moment is None or moment > best_moment:
            best_moment, best_text = moment, text
    return best_text


def export_jsonl(conn: sqlite3.Connection, out_path: Path) -> dict[str, int]:
    """把储备池导出为 JSONL 文本快照（`items` 与 `events` 各一行一条）。

    为什么要这个（2026-09-25）：库是**单副本的二进制状态**——坏了就没了，也没法 diff，
    而里面存的是 controller 的署名表态（含「放弃不复活」的历史）。文本快照可人读、
    可 diff、可另存，也让"这份状态变了什么"在库之外可核。

    每行形如 `{"record": "item"|"event", ...}`；行内键按字母序，保证同一状态导出逐字节稳定
    （除非内容真的变了）。
    """
    items = [dict(row) for row in conn.execute("SELECT * FROM backlog_items ORDER BY item_key")]
    events = [dict(row) for row in conn.execute("SELECT * FROM backlog_events ORDER BY event_id")]
    # 头一条是 meta：回答"这份快照相对库有多旧"（复核 F9）。用**从库里推导**的
    # `data_as_of` 而不是导出墙钟时间，这样同一份库重复导出仍然逐字节相同——
    # 快照要进版本库，抖动会让 diff 变成噪声。
    stamps = [str(item.get("last_seen_at") or "") for item in items]
    stamps += [str(event.get("occurred_at") or "") for event in events]
    meta = {
        "record": "meta",
        "schema_version": "backlog-export-v1",
        "data_as_of": _latest_moment(stamps),
        "items": len(items),
        "events": len(events),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(meta, ensure_ascii=False, sort_keys=True) + "\n")
        for item in items:
            handle.write(json.dumps({"record": "item", **item}, ensure_ascii=False, sort_keys=True) + "\n")
        for event in events:
            handle.write(json.dumps({"record": "event", **event}, ensure_ascii=False, sort_keys=True) + "\n")
    return {"items": len(items), "events": len(events), "data_as_of": meta["data_as_of"]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="command", required=True)

    p_ing = sub.add_parser("ingest", help="从一个 scout ledger 入库")
    p_ing.add_argument("--scout-ledger", required=True, type=Path)
    p_ing.add_argument("--run-dir", default="")

    p_list = sub.add_parser("list", help="列出条目")
    p_list.add_argument("--state", choices=ALL_STATES)
    p_list.add_argument("--limit", type=int, default=50)
    p_list.add_argument("--json", action="store_true")

    p_dec = sub.add_parser("decide", help="记录你的表态")
    p_dec.add_argument("--key", required=True)
    p_dec.add_argument("--state", required=True, choices=CONTROLLER_STATES)
    p_dec.add_argument("--reason", default="")
    p_dec.add_argument("--by", default="")

    p_adopt = sub.add_parser("adopt", help="标记已进入某批次")
    p_adopt.add_argument("--key", required=True)
    p_adopt.add_argument("--run-id", required=True)
    p_adopt.add_argument("--by", default="")

    p_retract = sub.add_parser("retract", help="撤销一次表态（留痕，不删历史）")
    p_retract.add_argument("--key", required=True)
    p_retract.add_argument("--reason", required=True)
    p_retract.add_argument("--by", default="")

    p_render = sub.add_parser("render", help="输出人类可读视图")
    p_render.add_argument("--out", type=Path)

    p_export = sub.add_parser("export", help="导出 JSONL 文本快照（库是单副本，坏了就没了）")
    p_export.add_argument("--out", type=Path, required=True)

    args = parser.parse_args(argv)

    # This store is rolling project state under state/ (formerly run/), never run
    # evidence. Refuse to be created inside a sealed run, and refuse to write a view
    # or a snapshot into one either.
    sealed_db = _sealed_ancestor(args.db)
    if sealed_db is not None:
        print(json.dumps({"status": "BLOCKED", "reason": f"refuse_sealed_run:{sealed_db}",
                          "db": str(args.db)}, ensure_ascii=False))
        return 3
    if getattr(args, "out", None):
        # 按"是否要写文件"判断，而不是按命令名白名单（复核 F8）：白名单漏登记一个
        # 将来新增的写文件子命令，就静默绕过封存护栏——本仓库刚因为"靠记得"栽过。
        sealed_out = _sealed_ancestor(args.out)
        if sealed_out is not None:
            print(json.dumps({"status": "BLOCKED",
                              "reason": f"refuse_sealed_run:{sealed_out}"}, ensure_ascii=False))
            return 3

    try:
        conn = _connect(args.db)
    except (OSError, sqlite3.Error) as exc:
        print(json.dumps({"status": "FAIL", "reason": f"db_unavailable:{exc}"},
                         ensure_ascii=False))
        return 2

    try:
        if args.command == "ingest":
            if not args.scout_ledger.is_file():
                raise BacklogError(f"scout_ledger_missing:{args.scout_ledger}")
            rows: list[dict[str, Any]] = []
            for line in args.scout_ledger.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    rows.append(parsed)
            if not rows:
                raise BacklogError("scout_ledger_empty")
            stats = ingest(conn, rows, run_dir=args.run_dir or str(args.scout_ledger.parent))
            print(json.dumps({"status": "PASS", **stats,
                              "totals": counts_by_state(conn)}, ensure_ascii=False))
            return 0

        if args.command == "list":
            items = list_items(conn, state=args.state, limit=args.limit)
            if args.json:
                print(json.dumps(items, ensure_ascii=False, indent=2))
            else:
                for item in items:
                    flag = " ⚠️风险未复核" if item.get("risk_unverified") else ""
                    print(f"[{item['state']:>9}] {int(item.get('rank_score') or 0):>3} "
                          f"{str(item.get('title'))[:44]} ({item.get('account_name')}){flag}")
                    print(f"            key={item['item_key']}")
            return 0

        if args.command == "decide":
            result = decide(conn, args.key, args.state, by=args.by, reason=args.reason)
            print(json.dumps({"status": "PASS", **result}, ensure_ascii=False))
            return 0

        if args.command == "adopt":
            result = adopt(conn, args.key, run_id=args.run_id, by=args.by)
            print(json.dumps({"status": "PASS", **result}, ensure_ascii=False))
            return 0

        if args.command == "retract":
            result = retract(conn, args.key, by=args.by, reason=args.reason)
            print(json.dumps({"status": "PASS", **result}, ensure_ascii=False))
            return 0

        if args.command == "render":
            text = render(conn)
            if args.out:
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(text, encoding="utf-8")
                print(json.dumps({"status": "PASS", "out": str(args.out),
                                  "totals": counts_by_state(conn)}, ensure_ascii=False))
            else:
                print(text)
            return 0

        if args.command == "export":
            stats = export_jsonl(conn, args.out)
            print(json.dumps({"status": "PASS", "out": str(args.out), **stats,
                              "totals": counts_by_state(conn)}, ensure_ascii=False))
            return 0
    except BacklogError as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, ensure_ascii=False))
        return 2
    except sqlite3.Error as exc:
        print(json.dumps({"status": "FAIL", "reason": f"db_error:{exc}"}, ensure_ascii=False))
        return 2
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
