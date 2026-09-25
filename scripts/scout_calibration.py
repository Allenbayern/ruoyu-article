#!/usr/bin/env python3
"""Calibrate the scout's LLM hook score against a labelled gold set.

Why this exists
---------------
``topic_scout --llm`` asks the model to rate a hook 0-10.  Without a labelled
reference that rating is only an opinion.  This script measures it against
labels that do **not** come from the model:

* ``user_attested_performance`` -- real published articles the user confirmed
  reached 50k+/100k+ reads;
* ``documented_editorial_choice`` -- before/after title rewrites the writing
  playbook explicitly judged;
* ``documented_anti_pattern`` -- hype phrases the playbook names as bad.

Circularity guard: a gold set built from the model's own output measures
nothing.  Every item therefore carries a ``source_ref`` pointing at an
independent artefact, and the loader refuses items without one.

Honesty guard: a seed set this small cannot establish a calibration curve.
When the sample is below the reporting threshold the report says so and marks
``calibration_status=insufficient_sample`` instead of quoting a coefficient as
if it meant something.

Usage::

    python scripts/scout_calibration.py \
        --gold-set tests/fixtures/scout_calibration/hook_gold_seed.jsonl \
        --out-dir runs/<date>/scout-calibration/<run-id>

    # offline: validate the gold set without spending tokens
    python scripts/scout_calibration.py --gold-set <...> --out-dir <...> --no-llm
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.llm_client import (  # noqa: E402
    LlmUnavailable,
    chat as llm_chat,
    load_env,
    parse_json_array,
)
from scripts.topic_scout import (  # noqa: E402
    HOOK_SCORE_RUBRIC,
    RISK_LEVELS,
    _coerce_hook_score,
    _guard_output_dir,
    _sealed_ancestor,
)

SCHEMA_VERSION = "scout-calibration-v1"
PROMPT_VERSION = "hook-score-calibration-v1"
REPORT_FILENAMES = ("calibration-report.json", "calibration-report.md")

VALID_LABELS = ("good", "bad")
VALID_BASIS = (
    "user_attested_performance",
    "documented_editorial_choice",
    "documented_anti_pattern",
    "contract_qualified_performance",
)
VALID_STRATA = ("full_title", "anti_pattern_fragment")
VALID_TIERS = ("core", "extended")

# Below these counts the numbers are indicative only, and the report says so.
MIN_GOOD_FOR_CLAIM = 10
MIN_BAD_FOR_CLAIM = 5
MIN_TOTAL_FOR_CLAIM = 20

CALIBRATION_SYSTEM_PROMPT = (
    "你是影视标题评分员。给你若干条中文标题或钩子，逐条按同一把尺子打 0-10 分。\n"
    "评分尺子：" + HOOK_SCORE_RUBRIC + "\n"
    "只输出严格 JSON 数组，不要任何解释或代码块："
    '[{"i":序号,"score":8,"why":"≤10字"}]'
)


class GoldSetError(ValueError):
    """The gold set is malformed or lacks independent provenance."""


def load_gold_set(path: Path) -> list[dict[str, Any]]:
    """Load and validate a gold set; refuse items without independent provenance."""

    if not path.is_file():
        raise GoldSetError(f"gold_set_missing:{path}")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GoldSetError(f"gold_set_bad_json:line{lineno}") from exc
        if not isinstance(row, dict):
            raise GoldSetError(f"gold_set_not_object:line{lineno}")
        item_id = str(row.get("item_id") or "").strip()
        if not item_id or item_id in seen:
            raise GoldSetError(f"gold_set_bad_item_id:line{lineno}")
        seen.add(item_id)
        if row.get("label") not in VALID_LABELS:
            raise GoldSetError(f"gold_set_bad_label:{item_id}")
        if row.get("basis") not in VALID_BASIS:
            raise GoldSetError(f"gold_set_bad_basis:{item_id}")
        if row.get("stratum") not in VALID_STRATA:
            raise GoldSetError(f"gold_set_bad_stratum:{item_id}")
        tier = row.get("provenance_tier", "core")
        if tier not in VALID_TIERS:
            raise GoldSetError(f"gold_set_bad_tier:{item_id}")
        row["provenance_tier"] = tier
        text = row.get("text")
        if not isinstance(text, str) or not text.strip():
            raise GoldSetError(f"gold_set_empty_text:{item_id}")
        # Circularity guard: labels must trace to an independent artefact.
        if not str(row.get("source_ref") or "").strip():
            raise GoldSetError(f"gold_set_missing_source_ref:{item_id}")
        items.append(row)
    if not items:
        raise GoldSetError("gold_set_empty")
    return items


def score_items(
    items: Sequence[Mapping[str, Any]],
    *,
    env: Mapping[str, str],
    chat_fn: Callable[..., str] = llm_chat,
) -> dict[str, dict[str, Any]]:
    """Score every item in one batched call. Returns {item_id: {score, why}}."""

    user_prompt = "待评分条目（序号<TAB>文本）：\n" + "\n".join(
        f"{index}\t{str(item.get('text'))[:120]}" for index, item in enumerate(items)
    )
    raw = chat_fn(dict(env), CALIBRATION_SYSTEM_PROMPT, user_prompt)
    parsed = parse_json_array(raw)
    if not parsed:
        raw = chat_fn(
            dict(env),
            CALIBRATION_SYSTEM_PROMPT + "最终回答必须是一个裸 JSON 数组。",
            user_prompt,
        )
        parsed = parse_json_array(raw)
    if not parsed:
        raise LlmUnavailable("json_parse_failed")

    results: dict[str, dict[str, Any]] = {}
    for entry in parsed:
        if not isinstance(entry, Mapping):
            continue
        try:
            index = int(entry.get("i", -1))
        except (TypeError, ValueError):
            continue
        if not 0 <= index < len(items):
            continue
        score = _coerce_hook_score(entry.get("score"))
        if score is None:
            continue
        results[str(items[index]["item_id"])] = {
            "score": score,
            "why": str(entry.get("why") or "")[:20],
        }
    return results


def _auc(good: Sequence[float], bad: Sequence[float]) -> float | None:
    """Probability a random good item outranks a random bad item (ties = 0.5)."""

    if not good or not bad:
        return None
    wins = 0.0
    for g in good:
        for b in bad:
            if g > b:
                wins += 1.0
            elif g == b:
                wins += 0.5
    return wins / (len(good) * len(bad))


def build_report(
    items: Sequence[Mapping[str, Any]],
    scores: Mapping[str, Mapping[str, Any]],
    *,
    generated_at: datetime,
    gold_set_path: Path,
    llm_used: bool,
) -> dict[str, Any]:
    """Compute separation metrics plus an explicit honesty block."""

    rows: list[dict[str, Any]] = []
    for item in items:
        item_id = str(item["item_id"])
        scored = scores.get(item_id)
        rows.append(
            {
                "item_id": item_id,
                "text": item.get("text"),
                "label": item.get("label"),
                "basis": item.get("basis"),
                "stratum": item.get("stratum"),
                "pair_id": item.get("pair_id"),
                "pair_role": item.get("pair_role"),
                "provenance_tier": item.get("provenance_tier", "core"),
                "score": scored.get("score") if scored else None,
                "why": scored.get("why") if scored else None,
                "source_ref": item.get("source_ref"),
            }
        )

    scored_rows = [r for r in rows if r["score"] is not None]
    good = [float(r["score"]) for r in scored_rows if r["label"] == "good"]
    bad = [float(r["score"]) for r in scored_rows if r["label"] == "bad"]
    full_good = [float(r["score"]) for r in scored_rows if r["label"] == "good" and r["stratum"] == "full_title"]
    full_bad = [float(r["score"]) for r in scored_rows if r["label"] == "bad" and r["stratum"] == "full_title"]
    core_good = [float(r["score"]) for r in scored_rows
                 if r["label"] == "good" and r["provenance_tier"] == "core"]
    core_bad = [float(r["score"]) for r in scored_rows
                if r["label"] == "bad" and r["provenance_tier"] == "core"]
    extended_rows = [r for r in scored_rows if r["provenance_tier"] == "extended"]
    extended_good = [float(r["score"]) for r in extended_rows if r["label"] == "good"]

    pairs: dict[str, dict[str, Any]] = {}
    for row in scored_rows:
        pair_id = row.get("pair_id")
        if not pair_id:
            continue
        pairs.setdefault(str(pair_id), {})[str(row.get("pair_role"))] = row["score"]
    pair_results: list[dict[str, Any]] = []
    for pair_id, sides in sorted(pairs.items()):
        if "preferred" in sides and "rejected" in sides:
            pair_results.append(
                {
                    "pair_id": pair_id,
                    "preferred": sides["preferred"],
                    "rejected": sides["rejected"],
                    "correct": sides["preferred"] > sides["rejected"],
                }
            )
    pair_correct = sum(1 for p in pair_results if p["correct"])

    enough = (
        len(good) >= MIN_GOOD_FOR_CLAIM
        and len(bad) >= MIN_BAD_FOR_CLAIM
        and len(scored_rows) >= MIN_TOTAL_FOR_CLAIM
    )

    metrics: dict[str, Any] = {
        "n_total": len(rows),
        "n_scored": len(scored_rows),
        "n_good": len(good),
        "n_bad": len(bad),
        "mean_good": round(statistics.fmean(good), 2) if good else None,
        "mean_bad": round(statistics.fmean(bad), 2) if bad else None,
        "mean_all": round(statistics.fmean(good + bad), 2) if (good or bad) else None,
        "separation_gap": round(statistics.fmean(good) - statistics.fmean(bad), 2)
        if good and bad
        else None,
        "auc_good_over_bad": (lambda a: round(a, 3) if a is not None else None)(_auc(good, bad)),
        "auc_full_title_only": (lambda a: round(a, 3) if a is not None else None)(_auc(full_good, full_bad)),
        "auc_core_tier_only": (lambda a: round(a, 3) if a is not None else None)(_auc(core_good, core_bad)),
        "n_core": sum(1 for r in scored_rows if r["provenance_tier"] == "core"),
        "n_extended": len(extended_rows),
        "mean_extended_good": round(statistics.fmean(extended_good), 2) if extended_good else None,
        "pairwise_accuracy": (
            f"{pair_correct}/{len(pair_results)}" if pair_results else None
        ),
        "pairwise_details": pair_results,
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.isoformat(),
        "gold_set": str(gold_set_path),
        "llm_used": llm_used,
        "prompt_version": PROMPT_VERSION,
        "rubric": HOOK_SCORE_RUBRIC,
        "metrics": metrics,
        "calibration_status": "measurable_sample" if enough else "insufficient_sample",
        "caveats": [
            "样本量小：本 gold set 是种子集，不足以拟合校准曲线，只能看方向性信号。",
            "分组标签含义不同：user_attested_performance 是「这篇表现好」，不是「这个标题钩子强」；"
            "documented_editorial_choice 才是关于钩子质量的直接判断。",
            "anti_pattern_fragment 是短语不是完整标题，已单独分层，不混入 full_title 的 AUC。",
            "已排除 ref-003：《早春晴朗》对标矩阵中该条标题被截断（带 …），评分不公平。",
            "**extended 层证据弱**：contract_qualified_performance 的 11 条，其 client_evidence.sha256 是占位符"
            "（全零），「表现达标」无法从留存证据回链。它们只用来增加样本量，结论以 core 层 AUC 为准。",
            "绝对分系统性偏移未被修正：LLM 打分整体偏高时，mean_all 会显示出来，但这不等于排序失效。",
            "本报告只能说明「LLM 打分是否与独立标签同向」，不能推出点击率或爆款概率。",
        ],
        "rows": rows,
    }


def render_report_markdown(report: Mapping[str, Any]) -> str:
    m = report["metrics"]
    lines: list[str] = []
    lines.append("# 钩子评分校准报告（对照独立标签）")
    lines.append("")
    lines.append(f"> 生成时间：{report['generated_at']}")
    lines.append(f"> gold set：`{report['gold_set']}`")
    lines.append(f"> 是否调用 LLM：{'是' if report['llm_used'] else '否（仅校验 gold set）'}")
    lines.append(f"> 评分尺子：{report['rubric']}")
    lines.append("")
    status = report["calibration_status"]
    if status == "insufficient_sample":
        lines.append("## ⚠️ 样本不足，结论仅供参考")
        lines.append("")
        lines.append(
            f"只有 {m['n_scored']} 条已评分（good {m['n_good']} / bad {m['n_bad']}）。"
            f"达到可量化门槛需要 good≥{MIN_GOOD_FOR_CLAIM}、bad≥{MIN_BAD_FOR_CLAIM}、"
            f"总数≥{MIN_TOTAL_FOR_CLAIM}。**下面的数字只能看方向，不能当作校准结果。**"
        )
        lines.append("")
    else:
        lines.append("## 样本量已达标")
        lines.append("")

    lines.append("## 分离度指标")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("| --- | --- |")
    lines.append(f"| 已评分条数 | {m['n_scored']}（good {m['n_good']} / bad {m['n_bad']}） |")
    lines.append(f"| good 均分 | {m['mean_good']} |")
    lines.append(f"| bad 均分 | {m['mean_bad']} |")
    lines.append(f"| 分离差距 | {m['separation_gap']} |")
    lines.append(f"| AUC（good > bad） | {m['auc_good_over_bad']} |")
    lines.append(f"| AUC（仅完整标题层） | {m['auc_full_title_only']} |")
    lines.append(f"| **AUC（仅 core 层，结论以此为准）** | **{m['auc_core_tier_only']}** |")
    lines.append(f"| 分层条数 | core {m['n_core']} / extended {m['n_extended']} |")
    lines.append(f"| extended 层 good 均分 | {m['mean_extended_good']} |")
    lines.append(f"| 成对准确率（改后 > 改前） | {m['pairwise_accuracy']} |")
    lines.append(f"| 全体均分（看是否整体偏高） | {m['mean_all']} |")
    lines.append("")
    lines.append("AUC 解读：0.5 = 与随机无异；1.0 = 完全分开。")
    lines.append("")

    if m["pairwise_details"]:
        lines.append("## 成对检验（手册记录的改前/改后）")
        lines.append("")
        lines.append("| 对 | 改后 | 改前 | 判定 |")
        lines.append("| --- | ---: | ---: | --- |")
        for p in m["pairwise_details"]:
            lines.append(
                f"| {p['pair_id']} | {p['preferred']} | {p['rejected']} | "
                + ("✅ 正确" if p["correct"] else "❌ 反向") + " |"
            )
        lines.append("")

    stability = report.get("stability")
    if stability:
        lines.append("## 稳定性（同批重发，只变批次组成）")
        lines.append("")
        lines.append(
            f"重发 {stability['repeats']} 次；**{stability['unstable_items']} / "
            f"{stability['n_compared']} 条分数波动 ≥2 分**，最大波动 {stability['max_spread']} 分；"
            f"成对判定保持 {stability['pairwise_held']}。"
        )
        lines.append("")
        lines.append("| 条目 | 标签 | 各次分数 | 波动 | 文本 |")
        lines.append("| --- | --- | --- | ---: | --- |")
        for row in stability["items"][:8]:
            lines.append(
                f"| {row['item_id']} | {row['label']} | {row['scores']} | {row['spread']} | "
                f"{str(row['text'])[:28]} |"
            )
        lines.append("")
        lines.append("**解读**：分数若随批次组成漂移，就说明它是「这一批里的相对判断」，"
                     "不是钩子的绝对属性。单次分数不可当作稳定测量值使用。")
        lines.append("")

    lines.append("## 逐条明细")
    lines.append("")
    lines.append("| 条目 | 标签 | 依据 | 层 | 分数 | 文本 |")
    lines.append("| --- | --- | --- | --- | ---: | --- |")
    for row in report["rows"]:
        score = row["score"] if row["score"] is not None else "—"
        lines.append(
            f"| {row['item_id']} | {row['label']} | {row['basis']} | {row['provenance_tier']} | {score} | "
            f"{str(row['text'])[:34]} |"
        )
    lines.append("")

    lines.append("## 必须知道的局限")
    lines.append("")
    for caveat in report["caveats"]:
        lines.append(f"- {caveat}")
    lines.append("")
    lines.append("## 边界")
    lines.append("")
    lines.append("- 本报告只衡量「LLM 打分是否与独立标签同向」，**不构成爆款预测能力**。")
    lines.append("- 校准结果不改变任何资格判定；它只是让评分这件事变得可衡量。")
    lines.append("- 标签与打分都可复核：每条都带 `source_ref`，可回到原始出处。")
    lines.append("")
    return "\n".join(lines)


def extract_risk_review_queue(ledger_path: Path, out_path: Path) -> dict[str, Any]:
    """Turn keyword-vs-LLM risk disagreements into a labelling queue.

    Label the *disagreements*, not the whole corpus: they carry the most
    information per human minute.  Nothing here is a verdict — every row is
    written with ``human_label`` empty for the Controller to fill in.
    """

    if not ledger_path.is_file():
        raise GoldSetError(f"ledger_missing:{ledger_path}")
    rows: list[dict[str, Any]] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        assessment = row.get("risk_assessment") or {}
        keyword_codes = [f.get("code") for f in (row.get("risk_flags") or []) if isinstance(f, dict)]
        llm_codes = list(assessment.get("codes") or [])
        method = assessment.get("method")
        if method not in {"llm", "heuristic_unverified"}:
            continue
        keyword_set, llm_set = set(keyword_codes), set(llm_codes)
        if method == "heuristic_unverified":
            disagreement = "unverified"
        elif keyword_set - llm_set:
            disagreement = "keyword_only"      # candidate false positive
        elif llm_set - keyword_set:
            disagreement = "llm_only"          # candidate false negative
        else:
            continue
        rows.append(
            {
                "item_id": f"risk-{row.get('candidate_id') or len(rows)}",
                "candidate_id": row.get("candidate_id"),
                "title": row.get("title"),
                "account_name": row.get("account_name"),
                "canonical_url": row.get("canonical_url"),
                "content_hash": row.get("content_hash"),
                "disagreement": disagreement,
                "keyword_codes": sorted(keyword_codes),
                "llm_level": assessment.get("level"),
                "llm_codes": sorted(llm_codes),
                "llm_reason": assessment.get("reason"),
                "human_label": "",
                "human_codes": [],
                "labeler": "",
                "labeled_at": "",
                "notes": "",
            }
        )
    payload = {
        "schema_version": "risk-review-queue-v1",
        "source_ledger": str(ledger_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "instruction": (
            "对每条判断文章本身是否真的构成内容风险，填 human_label（none/low/medium/high）"
            "与 human_codes，并署名。只标不一致项，因为它们每条的标注信息量最大。"
        ),
        "counts": {
            "total": len(rows),
            "keyword_only": sum(1 for r in rows if r["disagreement"] == "keyword_only"),
            "llm_only": sum(1 for r in rows if r["disagreement"] == "llm_only"),
            "unverified": sum(1 for r in rows if r["disagreement"] == "unverified"),
        },
        "rows": rows,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def measure_stability(
    items: Sequence[Mapping[str, Any]],
    runs: Sequence[Mapping[str, Mapping[str, Any]]],
) -> dict[str, Any]:
    """Report how much a score moves when the batch is re-sent unchanged.

    A score that depends on what else was in the batch is not an absolute
    property of the hook, so a single-run number must not be read as one.
    """

    per_item: list[dict[str, Any]] = []
    unstable = 0
    for item in items:
        item_id = str(item["item_id"])
        values = [run[item_id]["score"] for run in runs if item_id in run]
        if not values:
            continue
        spread = max(values) - min(values)
        if spread >= 2:
            unstable += 1
        per_item.append(
            {
                "item_id": item_id,
                "label": item.get("label"),
                "text": item.get("text"),
                "scores": values,
                "min": min(values),
                "max": max(values),
                "spread": spread,
            }
        )

    pair_verdicts: list[bool] = []
    by_pair: dict[str, dict[str, str]] = {}
    for item in items:
        pair_id = item.get("pair_id")
        if not pair_id:
            continue
        by_pair.setdefault(str(pair_id), {})[str(item.get("pair_role"))] = str(item["item_id"])
    for run in runs:
        for sides in by_pair.values():
            p_id, r_id = sides.get("preferred"), sides.get("rejected")
            if not p_id or not r_id:
                continue
            p = run.get(p_id, {}).get("score")
            r = run.get(r_id, {}).get("score")
            if p is None or r is None:
                continue
            pair_verdicts.append(p > r)

    return {
        "repeats": len(runs),
        "unstable_items": unstable,
        "n_compared": len(per_item),
        "max_spread": max((row["spread"] for row in per_item), default=0),
        "pairwise_verdicts": pair_verdicts,
        "pairwise_held": f"{sum(pair_verdicts)}/{len(pair_verdicts)}" if pair_verdicts else None,
        "items": sorted(per_item, key=lambda r: -r["spread"]),
    }


def render_risk_queue_markdown(payload: Mapping[str, Any]) -> str:
    """Human-fillable form so the Controller can label without reading JSON."""

    lines: list[str] = []
    lines.append("# 风险判定标注表（待 Controller 填写）")
    lines.append("")
    lines.append(f"> 来源 ledger：`{payload.get('source_ledger')}`")
    lines.append(f"> 生成时间：{payload.get('generated_at')}")
    lines.append("")
    lines.append(f"**{payload['counts']['total']} 条**，只列关键词与 LLM 判断**不一致**的："
                 f"keyword_only {payload['counts']['keyword_only']} ／ "
                 f"llm_only {payload['counts']['llm_only']} ／ "
                 f"unverified {payload['counts']['unverified']}。")
    lines.append("")
    lines.append("一致的条目没有标注价值，已跳过。**这些格里没有预填判定**——"
                 "你的标注才是真值，模型与关键词都只是待检验的猜测。")
    lines.append("")
    lines.append("填法：每条勾一个 `human_label`，写下 `human_codes`、署名与日期。")
    lines.append("")
    lines.append("| 可选值 | 含义 |")
    lines.append("| --- | --- |")
    lines.append("| `none` | 文章本身不构成内容风险（可能只是提及） |")
    lines.append("| `low` | 需要留意，但不阻碍选题 |")
    lines.append("| `medium` | 需要人工把关后再决定 |")
    lines.append("| `high` | 不建议做，或必须升级处理 |")
    lines.append("")
    lines.append("可用 `human_codes`：`political_sensitivity` / `leader_reference` / "
                 "`judicial_case` / `privacy_individual` / `death_or_suicide` / `minor_involved`")
    lines.append("")

    for index, row in enumerate(payload["rows"], start=1):
        lines.append(f"## {index}. {row.get('title')}")
        lines.append("")
        lines.append(f"- **账号**：{row.get('account_name')}")
        lines.append(f"- **不一致类型**：`{row.get('disagreement')}`")
        lines.append(f"- **关键词命中**：{row.get('keyword_codes') or '无'}")
        lines.append(f"- **LLM 判定**：{row.get('llm_level')} / {row.get('llm_codes') or '无'}"
                     + (f"　理由：{row.get('llm_reason')}" if row.get("llm_reason") else ""))
        lines.append(f"- **链接**：{row.get('canonical_url') or '—'}")
        lines.append("")
        lines.append(f"- [ ] `none`　- [ ] `low`　- [ ] `medium`　- [ ] `high`")
        lines.append(f"- human_codes：")
        lines.append(f"- 标注人 / 日期：")
        lines.append(f"- 备注：")
        lines.append("")

    lines.append("## 标完之后")
    lines.append("")
    lines.append("把结果填回 `risk-review-queue.json` 的对应行（`human_label` / `human_codes` / "
                 "`labeler` / `labeled_at`），才能用来算风险判定的准确率与召回率。")
    lines.append("")
    lines.append("**在此之前，`heuristic_unverified` 的条目不得当作已排除风险。**")
    lines.append("")
    return "\n".join(lines)


def apply_risk_labels(
    payload: dict[str, Any],
    labels: Mapping[str, str],
    *,
    labeler: str,
    labeled_at: str | None = None,
) -> dict[str, Any]:
    """Write human labels onto queue rows, keyed by ``item_id``.

    Unknown ids and unknown label values are refused rather than ignored: a
    silently dropped label would quietly shrink the ground truth.
    """

    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise GoldSetError("risk_queue_rows_missing")
    by_id = {str(row.get("item_id")): row for row in rows if isinstance(row, dict)}
    unknown = sorted(set(labels) - set(by_id))
    if unknown:
        raise GoldSetError("risk_label_unknown_item:" + ",".join(unknown))
    for item_id, label in labels.items():
        if label not in RISK_LEVELS:
            raise GoldSetError(f"risk_label_invalid:{item_id}:{label}")
    for item_id, label in labels.items():
        row = by_id[item_id]
        row["human_label"] = label
        row["human_codes"] = [] if label == "none" else list(row.get("llm_codes") or [])
        row["labeler"] = labeler
        row["labeled_at"] = labeled_at or datetime.now(timezone.utc).isoformat()
    payload["labeled_count"] = sum(1 for r in rows if r.get("human_label"))
    return payload


def score_risk_screens(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Compare the keyword screen and the LLM screen against human labels.

    Recall is only reported when at least one human positive exists; with no
    positives it is *not computable* and says so instead of printing 0.
    """

    rows = [r for r in payload.get("rows", []) if isinstance(r, dict) and r.get("human_label")]
    if not rows:
        return {"labeled": 0, "status": "unlabeled",
                "note": "没有任何人工标注，无法计算任何指标"}

    def _tally(flagged) -> dict[str, Any]:
        tp = fp = fn = tn = 0
        for row in rows:
            human_risk = row["human_label"] != "none"
            screen = bool(flagged(row))
            if screen and human_risk:
                tp += 1
            elif screen and not human_risk:
                fp += 1
            elif not screen and human_risk:
                fn += 1
            else:
                tn += 1
        return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
                "precision": round(tp / (tp + fp), 3) if (tp + fp) else None,
                "recall": round(tp / (tp + fn), 3) if (tp + fn) else None}

    keyword = _tally(lambda r: bool(r.get("keyword_codes")))
    llm = _tally(lambda r: (r.get("llm_level") or "none") != "none"
                 and r.get("disagreement") != "unverified")

    return {
        "labeled": len(rows),
        "status": "measurable" if any(r["human_label"] != "none" for r in rows)
        else "no_positive_labels",
        "human_positive_count": sum(1 for r in rows if r["human_label"] != "none"),
        "keyword_screen": keyword,
        "llm_screen": llm,
        "notes": [
            "recall 为 null 表示样本里没有人工正例，**不是 0**，无法计算。",
            "样本只有不一致项（一致项没有标注价值），因此这里的精确率不代表全量表现。",
            "在补齐正例样本、并明确风险尺子之前，本表**既不证明筛查器有效，也不证明其无效**；"
            "低精确率只说明当前尺子偏严，**不构成移除筛查器的依据**。",
        ],
    }


def render_risk_metrics(metrics: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    """Report the two screens' precision/recall against human labels."""

    lines: list[str] = []
    lines.append("# 风险判定筛查指标（对照人工标注）")
    lines.append("")
    lines.append(f"> 已标注：{metrics.get('labeled')} 条；人工判为有风险的正例："
                 f"**{metrics.get('human_positive_count')}** 条")
    lines.append(f"> 状态：`{metrics.get('status')}`")
    lines.append("")

    if metrics.get("status") == "unlabeled":
        lines.append(f"{metrics.get('note')}")
        lines.append("")
        return "\n".join(lines)

    lines.append("| 筛查器 | 命中 | TP | FP | FN | TN | 精确率 | 召回率 |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for name, key in (("关键词筛查", "keyword_screen"), ("LLM 判定", "llm_screen")):
        s = metrics.get(key) or {}
        prec = s.get("precision")
        rec = s.get("recall")
        lines.append(
            f"| {name} | {s.get('tp', 0) + s.get('fp', 0)} | {s.get('tp')} | {s.get('fp')} | "
            f"{s.get('fn')} | {s.get('tn')} | {'—' if prec is None else prec} | "
            f"{'不可计算' if rec is None else rec} |"
        )
    lines.append("")
    for note in metrics.get("notes", []):
        lines.append(f"- {note}")
    lines.append("")

    lines.append("## 逐条")
    lines.append("")
    lines.append("| 条目 | 关键词 | LLM | 人工 | 不一致类型 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for row in payload.get("rows", []):
        if not isinstance(row, dict):
            continue
        lines.append(
            f"| {str(row.get('title'))[:30]} | {row.get('keyword_codes') or '无'} | "
            f"{row.get('llm_level')} | **{row.get('human_label')}** | {row.get('disagreement')} |"
        )
    lines.append("")
    lines.append("## 边界")
    lines.append("")
    lines.append("- 本表只统计**不一致项**；一致项未标注，所以精确率不代表全量表现。")
    lines.append("- 召回率在没有人工正例时**不可计算**，不得填 0 充当结果。")
    lines.append("- 这些数字不改变任何资格判定，只说明两个筛查器当前的可靠性。")
    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-set", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--no-llm", action="store_true",
                        help="validate the gold set and report structure without calling the LLM")
    parser.add_argument("--repeats", type=int, default=1,
                        help="re-send the same batch N times to measure score stability")
    parser.add_argument("--risk-queue-from", type=Path,
                        help="build a risk labelling queue from a topic_scout ledger")
    parser.add_argument("--risk-queue-out", type=Path,
                        help="where to write the risk labelling queue")
    parser.add_argument("--apply-risk-labels", type=Path,
                        help="JSON file mapping item_id -> none|low|medium|high")
    parser.add_argument("--labeler", default="controller",
                        help="who labelled the risk queue")
    args = parser.parse_args(argv)

    if args.risk_queue_from is not None and args.apply_risk_labels is not None:
        # Label an existing queue and report the screens' precision/recall.
        target = args.risk_queue_out or args.risk_queue_from
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
            labels = json.loads(args.apply_risk_labels.read_text(encoding="utf-8"))
            if not isinstance(labels, dict):
                raise GoldSetError("risk_labels_not_object")
            payload = apply_risk_labels(payload, labels, labeler=args.labeler)
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"status": "FAIL", "reason": f"risk_labels_unreadable:{exc}"},
                             ensure_ascii=False))
            return 2
        except GoldSetError as exc:
            print(json.dumps({"status": "FAIL", "reason": str(exc)}, ensure_ascii=False))
            return 2
        metrics = score_risk_screens(payload)
        payload["screen_metrics"] = metrics
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        metrics_path = target.with_name("risk-metrics.md")
        metrics_path.write_text(render_risk_metrics(metrics, payload), encoding="utf-8")
        print(json.dumps({"status": "PASS", "mode": "risk_metrics",
                          "labeled": metrics.get("labeled"),
                          "human_positive_count": metrics.get("human_positive_count"),
                          "keyword": metrics.get("keyword_screen"),
                          "llm": metrics.get("llm_screen"),
                          "out": str(metrics_path)}, ensure_ascii=False))
        return 0

    if args.risk_queue_from is not None:
        target = args.risk_queue_out or (args.out_dir / "risk-review-queue.json" if args.out_dir
                                         else Path("risk-review-queue.json"))
        sealed = _sealed_ancestor(target)
        if sealed is not None:
            print(json.dumps({"status": "BLOCKED", "reason": f"refuse_sealed_run:{sealed}",
                              "out": str(target)}, ensure_ascii=False))
            return 3
        try:
            payload = extract_risk_review_queue(args.risk_queue_from, target)
            md_target = target.with_suffix(".md")
            md_target.write_text(render_risk_queue_markdown(payload), encoding="utf-8")
        except GoldSetError as exc:
            print(json.dumps({"status": "FAIL", "reason": str(exc)}, ensure_ascii=False))
            return 2
        print(json.dumps({"status": "PASS", "mode": "risk_queue",
                          **payload["counts"], "out": str(target)}, ensure_ascii=False))
        return 0

    if args.gold_set is None or args.out_dir is None:
        parser.error("--gold-set and --out-dir are required unless --risk-queue-from is used")

    # Same output guard as topic_scout: never overwrite an earlier report, never
    # write inside a sealed run.
    refusal = _guard_output_dir(
        args.out_dir, allow_overwrite=False, filenames=REPORT_FILENAMES
    )
    if refusal is not None:
        print(json.dumps({"status": "BLOCKED", "reason": refusal,
                          "out_dir": str(args.out_dir)}, ensure_ascii=False))
        return 3

    try:
        items = load_gold_set(args.gold_set)
    except GoldSetError as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, ensure_ascii=False))
        return 2

    now = datetime.now(timezone.utc)
    scores: dict[str, dict[str, Any]] = {}
    stability: dict[str, Any] | None = None
    llm_used = False
    note = "not_requested"
    if not args.no_llm:
        try:
            env = load_env()
        except SystemExit as exc:
            print(json.dumps({"status": "BLOCKED", "reason": f"credentials_unavailable:{exc}"},
                             ensure_ascii=False))
            return 3
        repeats = max(1, args.repeats)
        try:
            all_runs: list[dict[str, dict[str, Any]]] = []
            for _ in range(repeats):
                all_runs.append(score_items(items, env=env))
            scores = all_runs[0]
            llm_used = True
            note = "applied"
            if repeats > 1:
                stability = measure_stability(items, all_runs)
                note = f"applied_repeats={repeats}"
        except (LlmUnavailable, KeyError, ValueError, TypeError) as exc:
            print(json.dumps({"status": "FAIL", "reason": f"llm_failed:{exc}"}, ensure_ascii=False))
            return 4

    report = build_report(items, scores, generated_at=now,
                          gold_set_path=args.gold_set, llm_used=llm_used)
    report["llm_note"] = note
    if stability is not None:
        report["stability"] = stability

    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "calibration-report.json"
    md_path = args.out_dir / "calibration-report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_report_markdown(report), encoding="utf-8")

    print(json.dumps({
        "status": "PASS",
        "calibration_status": report["calibration_status"],
        **{k: report["metrics"][k] for k in
           ("n_scored", "n_good", "n_bad", "mean_good", "mean_bad",
            "separation_gap", "auc_good_over_bad", "auc_core_tier_only",
            "pairwise_accuracy")},
        "stability": ({"repeats": stability["repeats"],
                       "unstable_items": stability["unstable_items"],
                       "max_spread": stability["max_spread"],
                       "pairwise_held": stability["pairwise_held"]}
                      if stability else None),
        "out_dir": str(args.out_dir),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
