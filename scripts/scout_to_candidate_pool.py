#!/usr/bin/env python3
"""Convert selected topic-scout cards into an Article Group candidate pool.

This is a **format mover, not an editor**.  It fills the fields a machine can
derive from a scout ledger and leaves every editorial judgement field empty,
listed explicitly as TODO.  It never invents ``landing`` / ``emotion`` /
``angle`` / ``core_question`` — those are the substance of a topic and belong
to the Controller.

Target shape is the *live* one: the same field set real batches use and that
``article_group.portfolio_gate`` consumes.  Note that
``article_group.prewrite.validate_candidate_pool`` describes a different,
test-only field set that no real run satisfies; this tool does not target it.

The Controller's selection is required.  Without it the tool refuses to run —
a machine must not decide which topics enter a batch.

Usage::

    python scripts/scout_to_candidate_pool.py \
        --scout-ledger runs/<date>/topic-scout-decision/candidate-ledger.jsonl \
        --select cand-1,cand-2 \
        --run-id 2026-09-23/daily-014 \
        --out runs/2026-09-23/daily-014/candidate-pool.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.topic_scout import _guard_output_dir, _sealed_ancestor  # noqa: E402

SCHEMA_VERSION = "candidate-pool-v2"
OUTPUT_FILENAMES = ("candidate-pool.json",)
SELECTION_RULE = (
    "topic-scout advisory cards -> Controller selection -> candidate pool. "
    "发现信号不得直接充当事实；编辑判断字段由 Controller 填写，机器不代填。"
)

# Filled by this tool from the scout ledger.
MACHINE_FIELDS = (
    "candidate_id",
    "work_title",
    "signal",
    "signal_source",
    "source_refs",
    "freshness_window",
    "evidence_readiness",
    "reader_question",
    "event_cluster_id",
)

# Editorial judgement. Always emitted empty, always reported as TODO.
EDITORIAL_FIELDS = (
    "work",
    "topic_mode",
    "article_mode",
    "content_map",
    "content_map_label",
    "remove_timestamp_test",
    "editorial_value_score",
    "reader",
    "landing",
    "emotion",
    "social_motive",
    "core_question",
    "angle",
    "prior_run_conflict",
    "selection_reason",
)

# Advisory, machine-derived, explicitly labelled as such.
ADVISORY_FIELDS = ("recommendation", "machine_rank_score", "machine_recommendation_basis")

FRESHNESS_WINDOWS = ("same-day", "fermenting-1-3d", "revival")
_WORK_RE = re.compile(r"《([^》]{1,40})》")


class ConvertError(ValueError):
    """The conversion cannot proceed safely."""


def load_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ConvertError(f"scout_ledger_missing:{path}")
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
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
        raise ConvertError("scout_ledger_empty")
    return rows


def extract_work_tokens(title: str) -> list[str]:
    """Pull 《...》 titles out of a headline — a mechanical same-work signal."""

    return [m.group(1).strip() for m in _WORK_RE.finditer(title or "") if m.group(1).strip()]


def derive_cluster_id(candidate: Mapping[str, Any]) -> str:
    """Tentative same-work cluster from the headline only.

    Deliberately narrow: it only groups cards that name the same work in
    《...》.  It is *not* editorial clustering and is labelled tentative so a
    human can override it.
    """

    tokens = extract_work_tokens(str(candidate.get("title") or ""))
    if tokens:
        return "scout-work-" + re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", tokens[0]).strip("-")
    account = str(candidate.get("account_name") or "").strip()
    if account:
        return "scout-account-" + re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", account).strip("-")
    return ""


def derive_freshness(published_at: str, now: datetime) -> str:
    """Map publish age onto the gate's window vocabulary.

    The gate accepts exactly three windows (``same-day`` /
    ``fermenting-1-3d`` / ``revival``); anything else is reported as invalid,
    so this must not invent new labels.
    """

    if not published_at:
        return ""
    try:
        parsed = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age_hours = (now - parsed).total_seconds() / 3600
    if age_hours <= 24:
        return "same-day"
    if age_hours <= 72:
        return "fermenting-1-3d"
    return "revival"


def derive_readiness(candidate: Mapping[str, Any]) -> str:
    """Map the scout's 0-40 evidence score onto the gate's vocabulary."""

    score = int((candidate.get("scores") or {}).get("evidence_readiness") or 0)
    if score >= 34:
        return "high"
    if score >= 22:
        return "medium"
    return "low"


def derive_recommendation(candidate: Mapping[str, Any]) -> tuple[str, str]:
    """Machine hint only. Returns (recommendation, basis note)."""

    total = int((candidate.get("scores") or {}).get("total") or 0)
    if total >= 75:
        rec = "A"
    elif total >= 55:
        rec = "B"
    else:
        rec = "C"
    return rec, (
        f"machine_rank_score={total}（非编辑判断）；"
        "该字段仅在缺少 selected_slot_ids 时才会被 portfolio_gate 当作选择依据，"
        "本工具始终写出显式选择，故它不驱动选批。"
    )


def build_pool(
    ledger: Sequence[Mapping[str, Any]],
    *,
    selected_ids: Sequence[str],
    run_id: str,
    now: datetime,
    timezone_name: str = "Asia/Shanghai",
    rejected_prior_works: Sequence[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (pool, report). The pool is deliberately incomplete on purpose."""

    if not selected_ids:
        raise ConvertError("selection_required:机器不决定哪几篇进批次")

    by_id = {str(r.get("candidate_id") or ""): r for r in ledger}
    unknown = [cid for cid in selected_ids if cid not in by_id]
    if unknown:
        raise ConvertError("selection_unknown_candidate:" + ",".join(unknown))

    eligible = [r for r in ledger if r.get("screening_status") == "advisory_candidate"]
    not_eligible = [cid for cid in selected_ids
                    if by_id[cid].get("screening_status") != "advisory_candidate"]
    if not_eligible:
        raise ConvertError("selection_not_an_advisory_candidate:" + ",".join(not_eligible))

    candidates: list[dict[str, Any]] = []
    todo_map: dict[str, list[str]] = {}
    for row in eligible:
        cid = str(row.get("candidate_id"))
        rec, basis = derive_recommendation(row)
        signal = str(row.get("title") or "")
        if row.get("hook_draft"):
            signal = f"{signal}｜强钩草案：{row['hook_draft']}"
        candidate = {
            "candidate_id": cid,
            "work_title": str(row.get("title") or ""),
            "signal": signal,
            "signal_source": "｜".join(
                part for part in (str(row.get("account_name") or ""),
                                  str(row.get("canonical_url") or "")) if part
            ),
            "source_refs": [str(row.get("canonical_url") or "")] if row.get("canonical_url") else [],
            "freshness_window": derive_freshness(str(row.get("published_at") or ""), now),
            "evidence_readiness": derive_readiness(row),
            "reader_question": str(row.get("reader_question_draft") or ""),
            "event_cluster_id": derive_cluster_id(row),
            "recommendation": rec,
            "machine_rank_score": int((row.get("scores") or {}).get("total") or 0),
            "machine_recommendation_basis": basis,
            "_cluster_basis": "由标题《...》机械推导，非编辑聚类，可覆盖",
            "_source_prior": row.get("source_prior_label"),
            "_source_prior_is_performance_proof": False,
        }
        for field in EDITORIAL_FIELDS:
            candidate.setdefault(field, "" if field != "editorial_value_score" else "")
        todo_map[cid] = list(EDITORIAL_FIELDS)
        candidates.append(candidate)

    pool = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "timezone": timezone_name,
        "observed_at": now.isoformat(),
        "selection_pass": 1,
        "selection_rule": SELECTION_RULE,
        "selected_slot_ids": [cid for cid in selected_ids],
        "candidates": candidates,
        "rejected_prior_works": list(rejected_prior_works),
        "decision": "selected_by_controller",
        "publication_authorization": "not_authorized",
        "draft_status": "incomplete_editorial_fields",
        "editorial_todo": todo_map,
    }
    report = {
        "candidates": len(candidates),
        "selected": len(selected_ids),
        "editorial_fields_per_candidate": len(EDITORIAL_FIELDS),
        "pending_editorial_cells": len(candidates) * len(EDITORIAL_FIELDS),
        "draft_status": pool["draft_status"],
    }
    return pool, report


def render_checklist(pool: Mapping[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# 候选池待填清单（编辑判断字段）")
    lines.append("")
    lines.append(f"> run_id：{pool.get('run_id')}")
    lines.append(f"> 状态：`{pool.get('draft_status')}`")
    lines.append(f"> 发布授权：`{pool.get('publication_authorization')}`")
    lines.append("")
    lines.append("**机器只填了能从建议卡机械推导的字段。下面这些是编辑判断，")
    lines.append("工具一律留空——它们是一篇选题的实质，不该由机器代笔。**")
    lines.append("")
    lines.append("## 填之前先知道闸门认可的取值")
    lines.append("")
    lines.append("| 字段 | 合法取值 | 缺失后果 |")
    lines.append("| --- | --- | --- |")
    lines.append("| `content_map` | `A` 新片事件 / `B` 作品深度 / `C` 文化现象 / `D` 人物争议 | **阻断**（portfolio_gate 报 error） |")
    lines.append("| `topic_mode` | `release_event` / `character` / `craft` / `audience` / `culture` / `revisit` / `market` | 提示 |")
    lines.append("| `remove_timestamp_test` | `pass` / `risk` / `fail` | 警告 |")
    lines.append("| `editorial_value_score` | 1–5 | 警告 |")
    lines.append("")
    lines.append("`freshness_window` 与 `evidence_readiness` 已由机器填入合法值"
                 "（窗口只有 `same-day` / `fermenting-1-3d` / `revival` 三种）。")
    lines.append("")
    selected = set(pool.get("selected_slot_ids") or [])
    for candidate in pool.get("candidates", []):
        cid = candidate.get("candidate_id")
        mark = "【已选】" if cid in selected else "【未选】"
        lines.append(f"## {mark} {cid}｜{str(candidate.get('work_title'))[:40]}")
        lines.append("")
        lines.append(f"- 机器已填：recommendation={candidate.get('recommendation')}"
                     f"（score {candidate.get('machine_rank_score')}）"
                     f"｜evidence_readiness={candidate.get('evidence_readiness')}"
                     f"｜freshness={candidate.get('freshness_window')}")
        lines.append(f"- 事件簇（机械推导，可覆盖）：`{candidate.get('event_cluster_id')}`")
        lines.append("- 待填：")
        for field in EDITORIAL_FIELDS:
            lines.append(f"  - [ ] `{field}`")
        lines.append("")
    lines.append("## 填完之后")
    lines.append("")
    lines.append("1. 跑 `python -m article_group.portfolio_gate <pool.json>` 检查跨批与象限约束。")
    lines.append("2. 再把 `draft_status` 改成你确认的状态——**不要**在字段还空着时当它已完成。")
    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scout-ledger", required=True, type=Path)
    parser.add_argument("--select", default="",
                        help="逗号分隔的 candidate_id；必须由 Controller 指定")
    parser.add_argument("--select-file", type=Path,
                        help="JSON 数组文件，替代 --select")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--allow-overwrite", action="store_true")
    args = parser.parse_args(argv)

    if args.select_file is not None:
        try:
            raw = json.loads(args.select_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"status": "FAIL", "reason": f"select_file_unreadable:{exc}"},
                             ensure_ascii=False))
            return 2
        if not isinstance(raw, list):
            print(json.dumps({"status": "FAIL", "reason": "select_file_must_be_a_list"},
                             ensure_ascii=False))
            return 2
        selected = [str(x) for x in raw]
    else:
        selected = [part.strip() for part in args.select.split(",") if part.strip()]

    refusal = _guard_output_dir(args.out.parent, allow_overwrite=args.allow_overwrite,
                                filenames=OUTPUT_FILENAMES)
    if refusal is not None:
        print(json.dumps({"status": "BLOCKED", "reason": refusal}, ensure_ascii=False))
        return 3
    sealed = _sealed_ancestor(args.out)
    if sealed is not None:
        print(json.dumps({"status": "BLOCKED", "reason": f"refuse_sealed_run:{sealed}"},
                         ensure_ascii=False))
        return 3

    try:
        ledger = load_ledger(args.scout_ledger)
        pool, report = build_pool(
            ledger,
            selected_ids=selected,
            run_id=args.run_id,
            now=datetime.now(timezone.utc),
            timezone_name=args.timezone,
        )
    except ConvertError as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, ensure_ascii=False))
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(pool, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    checklist = args.out.with_name("candidate-pool-TODO.md")
    checklist.write_text(render_checklist(pool), encoding="utf-8")

    print(json.dumps({"status": "PASS", **report,
                      "pool": str(args.out), "checklist": str(checklist)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
