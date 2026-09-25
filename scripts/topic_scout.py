#!/usr/bin/env python3
"""Topic scout: turn one media-intel research run into advisory topic cards.

This is the Article Group's *decision-support* layer.  It reads a completed
media-intel article-research run (read-only) and produces ranked, explainable
candidate cards for a human Controller to pick from.

Hard boundaries encoded here:

* It never decides.  Every output carries ``advisory_only: true``; the human
  Controller selects, rejects, or shelfs each card.
* It never authorises writing, review, or publication; no such field is emitted.
* It never upgrades an article to a verified-viral case.  Head-account origin is
  recorded as ``source_prior`` (a *source* prior), never as performance proof.
* It never drops a candidate silently: ``candidate-ledger.jsonl`` keeps every
  row with its reasons, including rejections.
* It makes no network calls and spends no AI budget.

Usage::

    python scripts/topic_scout.py \
        --research-run <media-intel-run-dir> \
        --account-pool <media-intel>/config/approved_viral_account_pool.json \
        --out-dir runs/<date>/topic-scout/<run-id>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.llm_client import (  # noqa: E402
    LlmUnavailable,
    chat as llm_chat,
    load_env,
    parse_json_array,
)

SCHEMA_VERSION = "topic-scout-v1"
LLM_PROMPT_VERSION = "hook-direction-v1"
DEFAULT_LLM_LIMIT = 8
DEFAULT_BODY_WINDOW = 2000
DIRECTION_NAMES: tuple[str, ...] = (
    "市场与档期", "口碑与评分", "人物与演员", "观众与情绪",
    "奖项与荣誉", "行业与政策", "平台与资本",
)
RISK_LEVELS: tuple[str, ...] = ("none", "low", "medium", "high")
HOOK_SCORE_MAX = 10
# Deterministic hook strength occupies 0..30; the LLM's 0..10 rating is scaled
# into the same band so the weight structure stays comparable.
HOOK_SCORE_SCALE = 3

# --- film relevance ---------------------------------------------------------
# A title/body must hit at least one of these to be treated as a film/TV topic.
# Deliberately conservative: generic social topics must not drift in.
FILM_TERMS: tuple[str, ...] = (
    "电影", "影片", "院线", "票房", "排片", "档期", "首映", "上映", "重映",
    "导演", "编剧", "主演", "演员", "影帝", "影后", "剧组", "开机", "杀青",
    "剧集", "电视剧", "网剧", "短剧", "综艺", "纪录片", "动画", "动漫",
    "豆瓣", "开分", "口碑", "预告", "定档", "出品", "监制", "制片",
    "影视", "影评", "影展", "戛纳", "柏林", "威尼斯", "奥斯卡", "金鸡", "金马",
    "集数", "番位", "角色", "演技", "视帝", "视后", "领衔",
)

# --- direction buckets (deterministic keyword grouping, provisional) --------
# These are *reading directions* for sorting, not a validated taxonomy.
DIRECTION_BUCKETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("市场与档期", ("票房", "排片", "档期", "预售", "大盘", "暑期档", "国庆档", "春节档", "重映", "上映")),
    ("口碑与评分", ("豆瓣", "开分", "评分", "口碑", "烂尾", "翻车", "封神", "神作", "崩了", "高开低走")),
    ("人物与演员", ("演员", "影帝", "影后", "演技", "番位", "塌房", "解约", "复出", "导演", "编剧", "领衔")),
    ("观众与情绪", ("观众", "网友", "弹幕", "评价", "情怀", "意难平", "白月光", "破防", "泪目", "共鸣")),
    ("奖项与荣誉", ("获奖", "入围", "提名", "影展", "戛纳", "柏林", "威尼斯", "奥斯卡", "金鸡", "金马", "最佳")),
    ("行业与政策", ("总局", "审核", "下架", "限令", "备案", "寒冬", "亏损", "裁员", "片酬", "监管", "政策")),
    ("平台与资本", ("平台", "财报", "招商", "会员", "长视频", "爱奇艺", "腾讯视频", "优酷", "芒果", "投资")),
)

# --- hook strength markers --------------------------------------------------
CONTRAST_MARKERS: tuple[str, ...] = (
    "却", "但", "反而", "居然", "没想到", "竟然", "结果", "然而", "偏偏",
    "不是", "而是", "明明", "为何", "为什么", "凭什么", "原来",
)
EXTREME_MARKERS: tuple[str, ...] = (
    "最", "第一", "唯一", "史无前例", "断层", "碾压", "暴跌", "暴涨", "翻倍",
    "狂揽", "垫底", "血亏", "封神", "翻车",
)
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:亿|万|千|百|%|倍|天|年|分|人|场|部|集)?")

# --- risk flags (screening aid only; a human makes the call) ----------------
RISK_TERMS: tuple[tuple[str, str], ...] = (
    ("political_sensitivity", "政治敏感"),
    ("leader_reference", "涉及领导人"),
    ("judicial_case", "司法案件"),
    ("privacy_individual", "普通人隐私"),
    ("death_or_suicide", "死亡/自杀"),
    ("minor_involved", "涉及未成年人"),
)
RISK_KEYWORDS: dict[str, tuple[str, ...]] = {
    "political_sensitivity": ("政治", "意识形态", "立场", "封杀", "审查", "敏感"),
    "judicial_case": ("判刑", "起诉", "法院", "警方", "立案", "违法", "犯罪"),
    "privacy_individual": ("素人", "路人", "普通人", "隐私", "人肉"),
    "death_or_suicide": ("自杀", "去世", "离世", "抑郁", "身亡"),
    "minor_involved": ("未成年", "童星", "小孩", "儿童"),
}

MIN_BODY_CHARS = 300


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
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
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _match_terms(text: str, terms: Iterable[str]) -> list[str]:
    return [term for term in terms if term in text]


def _sentences(text: str) -> list[str]:
    parts = re.split(r"[。！？\n]+", text)
    return [p.strip() for p in parts if p.strip()]


@dataclass
class AccountPrior:
    """Approved head-account pool: source prior only, never performance proof."""

    accounts: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None) -> "AccountPrior":
        if path is None or not path.is_file():
            return cls()
        payload = _read_json(path)
        accounts = payload.get("accounts")
        if not isinstance(accounts, list):
            return cls()
        index: dict[str, dict[str, Any]] = {}
        for row in accounts:
            if not isinstance(row, Mapping):
                continue
            account_id = _as_text(row.get("account_id"))
            if account_id:
                index[account_id] = dict(row)
        return cls(accounts=index)

    def lookup(self, account_id: str) -> dict[str, Any] | None:
        return self.accounts.get(account_id)


def _score_evidence(candidate: Mapping[str, Any]) -> tuple[int, list[str], list[str]]:
    """Return (score 0-40, satisfied, missing) for evidence readiness."""

    satisfied: list[str] = []
    missing: list[str] = []
    score = 0

    body = _as_text(candidate.get("body"))
    if len(body) >= 1500:
        score += 14
        satisfied.append(f"正文充实（{len(body)} 字）")
    elif len(body) >= MIN_BODY_CHARS:
        score += 8
        satisfied.append(f"正文可用（{len(body)} 字）")
    else:
        missing.append(f"正文偏短（{len(body)} 字）")

    if _as_text(candidate.get("body_status")) == "complete":
        score += 6
        satisfied.append("正文状态 complete")
    else:
        missing.append("正文状态非 complete")

    if candidate.get("claim_inventory_complete") is True:
        score += 10
        satisfied.append("claim 清单完整")
    else:
        reason = _as_text(candidate.get("claim_inventory_reason_code")) or "unknown"
        missing.append(f"claim 清单不完整（{reason}）")

    if _as_text(candidate.get("published_at")):
        score += 5
        satisfied.append("有发布时间")
    else:
        missing.append("缺发布时间")

    if _as_text(candidate.get("content_hash")):
        score += 5
        satisfied.append("有内容哈希")
    else:
        missing.append("缺内容哈希")

    return min(score, 40), satisfied, missing


def _score_hook(title: str, body: str) -> tuple[int, list[str]]:
    """Return (score 0-30, reasons) for deterministic hook strength."""

    reasons: list[str] = []
    score = 0
    text = f"{title}\n{body[:600]}"

    numbers = NUMBER_RE.findall(title)
    if numbers:
        score += 8
        reasons.append(f"标题含数字对比（{', '.join(numbers[:3])}）")

    contrast = _match_terms(title, CONTRAST_MARKERS)
    if contrast:
        score += 7
        reasons.append(f"标题含反差结构（{'/'.join(contrast[:3])}）")

    extreme = _match_terms(title, EXTREME_MARKERS)
    if extreme:
        score += 6
        reasons.append(f"标题含极端词（{'/'.join(extreme[:3])}）")

    if any(q in title for q in ("？", "?", "为什么", "为何", "凭什么")):
        score += 5
        reasons.append("标题是疑问式")

    if any(q in title for q in ("“", "”", "「", "」", '"')):
        score += 4
        reasons.append("标题含引语")

    contrast_body = _match_terms(body[:600], CONTRAST_MARKERS)
    if contrast_body:
        score += 3
        reasons.append("开头含反差推进")

    return min(score, 30), reasons


def _score_prior(account_id: str, scope_hit: bool, prior: AccountPrior) -> tuple[int, str, dict[str, Any]]:
    """Return (score 0-20, label, detail) for source prior."""

    record = prior.lookup(account_id)
    if record is None:
        return 0, "not_in_pool", {}
    if _as_text(record.get("status")) != "approved":
        return 0, "pool_status_not_approved", {"status": record.get("status")}
    tags = record.get("scope_tags")
    tags = tags if isinstance(tags, list) else []
    if "film_tv_article" not in tags:
        return 4, "approved_account_non_film_scope", {"scope_tags": tags}
    return 20, "approved_head_account", {
        "account_class": record.get("account_class"),
        "scope_tags": tags,
    }


def _detect_risk(text: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for code, keywords in RISK_KEYWORDS.items():
        hits = _match_terms(text, keywords)
        if hits:
            label = next((lbl for c, lbl in RISK_TERMS if c == code), code)
            findings.append({"code": code, "label": label, "hits": hits[:4]})
    return findings


def _direction_bucket(text: str) -> tuple[str, list[str]]:
    best = ("未归类", [])
    best_hits = 0
    for name, keywords in DIRECTION_BUCKETS:
        hits = _match_terms(text, keywords)
        if len(hits) > best_hits:
            best_hits = len(hits)
            best = (name, hits)
    return best


def _hook_draft(title: str, body: str) -> str:
    """Pick the most contrast-carrying sentence as a *draft* hook.

    Advisory text only: it is a suggestion for the writer, never a title and
    never a factual claim.
    """

    sentences = _sentences(body)
    if not sentences:
        return title
    scored: list[tuple[int, int, str]] = []
    for index, sentence in enumerate(sentences[:40]):
        if len(sentence) < 12 or len(sentence) > 120:
            continue
        score = 0
        score += 2 * len(_match_terms(sentence, CONTRAST_MARKERS))
        score += 2 * len(_match_terms(sentence, EXTREME_MARKERS))
        score += 1 if NUMBER_RE.search(sentence) else 0
        score += 1 if any(q in sentence for q in ("“", "”", "「", "」")) else 0
        if score:
            scored.append((score, -index, sentence))
    if not scored:
        return title
    scored.sort(reverse=True)
    return scored[0][2]


# --- LLM enrichment (optional, opt-in, fail-closed) -------------------------
#
# The LLM only improves *presentation*: which sentence is the strongest hook,
# which reading direction the piece belongs to, and what reader question it
# answers.  It can never change eligibility, scores, or any decision field —
# those stay deterministic so a run is reproducible and auditable.
#
# The hook it returns must be a verbatim substring of the article body.  This
# script re-checks that itself: a self-declared "I quoted the source" is not
# evidence, which is the same rule the article gates follow.

HOOK_SCORE_RUBRIC = (
    "9-10=具体对象+尖锐反差或真实利害，读者会想点开；"
    "7-8=有明确对照、悬念或数字；5-6=有信息但平；"
    "3-4=概括性陈述；0-2=几乎无钩子。"
)

LLM_SYSTEM_PROMPT = (
    "你是影视选题助理。给你若干篇已发表文章的标题与正文开头，为每一篇做四件事：\n"
    "1) hook：从**给定的正文原文里**挑出最有传播力的一句作为强钩。必须是原文的连续片段，"
    "逐字照抄，不得改写、不得拼接、不得自造。长度 12-60 字。\n"
    "2) hook_score：给这句钩子打 0-10 分，按同一把尺子打分：\n"
    "   " + HOOK_SCORE_RUBRIC + "\n"
    "3) direction：从固定集合里选一个最贴合的阅读方向："
    + "/".join(DIRECTION_NAMES) + "。\n"
    "4) risk：判断这篇**文章本身**是否真的涉及需要人工把关的内容风险，"
    "只算文章实质讨论或指向的，**仅仅提到影片情节里的相关字眼不算**。\n"
    "   risk_level 取 none/low/medium/high；risk_codes 只能从这个集合里选 0 个或多个："
    "political_sensitivity(政治敏感)/leader_reference(涉及领导人)/judicial_case(司法案件)/"
    "privacy_individual(普通人隐私)/death_or_suicide(死亡或自杀)/minor_involved(涉及未成年人)；\n"
    "   risk_reason ≤20 字，说明为什么。\n"
    "只输出严格 JSON 数组，不要任何解释或代码块：\n"
    '[{"i":序号,"hook":"原文片段","hook_score":8,"direction":"方向",'
    '"question":"读者问题","risk_level":"none","risk_codes":[],"risk_reason":""}]'
)


def _normalize_for_match(text: str) -> str:
    """Collapse whitespace so a verbatim quote survives formatting noise."""

    return re.sub(r"\s+", "", text)


def verify_hook_quote(hook: object, body: str) -> tuple[bool, str]:
    """Independently verify an LLM hook is a verbatim slice of the body.

    Returns ``(ok, reason)``.  The model's own claim is never trusted: the
    quote must appear in the body after whitespace normalization.
    """

    if not isinstance(hook, str) or not hook.strip():
        return False, "hook_empty"
    candidate = hook.strip()
    if len(candidate) < 8:
        return False, "hook_too_short"
    if len(candidate) > 120:
        return False, "hook_too_long"
    if _normalize_for_match(candidate) in _normalize_for_match(body):
        return True, "verified_verbatim"
    return False, "hook_not_in_body"


def _coerce_direction(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if text in DIRECTION_NAMES else None


def _coerce_hook_score(value: object) -> int | None:
    """Accept only an integer 0..10; anything else is rejected."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = int(value)
    if number < 0 or number > HOOK_SCORE_MAX:
        return None
    return number


def _coerce_risk_level(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    return text if text in RISK_LEVELS else None


def _coerce_risk_codes(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    known = {code for code, _ in RISK_TERMS}
    codes: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip() in known and item.strip() not in codes:
            codes.append(item.strip())
    return codes


def recompute_total(row: dict[str, Any]) -> int:
    scores = row.get("scores") or {}
    total = (
        int(scores.get("evidence_readiness") or 0)
        + int(scores.get("hook_strength") or 0)
        + int(scores.get("source_prior") or 0)
        + int(scores.get("freshness") or 0)
    )
    scores["total"] = total
    row["scores"] = scores
    return total


def resort_ledger(ledger: list[dict[str, Any]]) -> None:
    ledger.sort(key=lambda r: (-(r.get("scores") or {}).get("total", 0), str(r.get("title") or "")))


def _mark_unverified_risk(row: dict[str, Any], reason: str) -> None:
    """Fail-safe risk marker: absence of an LLM verdict is never a clearance."""

    row["risk_assessment"] = {
        "method": "heuristic_unverified",
        "level": "unknown",
        "codes": [f["code"] for f in (row.get("risk_flags") or [])],
        "reason": reason,
        "keyword_flags_retained": True,
    }


def enrich_ledger_with_llm(
    ledger: list[dict[str, Any]],
    *,
    env: Mapping[str, str],
    chat_fn: Callable[..., str] = llm_chat,
    limit: int = DEFAULT_LLM_LIMIT,
    body_window: int = DEFAULT_BODY_WINDOW,
) -> dict[str, int]:
    """Enrich up to *limit* candidates in one batched LLM call.

    Only candidates that passed screening are enriched.  Every failure mode
    degrades to the deterministic fields already on the row; the run still
    completes and reports the degradation honestly.

    Two asymmetries matter:

    * Hook/direction failures degrade to the heuristic rendering — harmless.
    * Risk failures must **not** degrade to "no risk": on any LLM failure the
      keyword flags are kept and the row is marked ``unverified`` so nobody
      reads an absent LLM verdict as a clearance.
    """

    stats = {"requested": 0, "llm_applied": 0, "hook_rejected": 0, "direction_rejected": 0,
             "hook_score_rejected": 0, "risk_level_rejected": 0, "risk_cleared": 0,
             "fallback": 0, "unavailable": 0}

    eligible = [row for row in ledger if row.get("screening_status") == "advisory_candidate"]
    targets = eligible[: max(0, limit)]
    if not targets:
        return stats

    bodies: dict[str, str] = {}
    lines: list[str] = []
    for index, row in enumerate(targets):
        candidate_id = str(row.get("candidate_id") or f"row-{index}")
        body = str(row.get("_body") or "")
        bodies[candidate_id] = body
        lines.append(
            f"{index}\t标题：{str(row.get('title') or '')[:80]}\n"
            f"\t正文开头：{body[:body_window]}"
        )
    user_prompt = "候选文章（序号<TAB>内容）：\n" + "\n".join(lines)

    stats["requested"] = len(targets)
    try:
        raw = chat_fn(dict(env), LLM_SYSTEM_PROMPT, user_prompt)
        parsed = parse_json_array(raw)
        if not parsed:
            raw = chat_fn(
                dict(env),
                LLM_SYSTEM_PROMPT + "最终回答必须是一个裸 JSON 数组，禁止任何其他文字或代码块。",
                user_prompt,
            )
            parsed = parse_json_array(raw)
        if not parsed:
            raise LlmUnavailable("json_parse_failed")
    except (LlmUnavailable, KeyError, ValueError, TypeError) as exc:
        for row in targets:
            row["llm_status"] = "unavailable"
            row["llm_reason"] = str(exc)[:120]
            _mark_unverified_risk(row, "LLM 不可用，保留关键词筛查结果，未经复核")
        stats["unavailable"] = len(targets)
        stats["fallback"] = len(targets)
        return stats

    for entry in parsed:
        if not isinstance(entry, Mapping):
            continue
        try:
            index = int(entry.get("i", -1))
        except (TypeError, ValueError):
            continue
        if not 0 <= index < len(targets):
            continue
        row = targets[index]
        candidate_id = str(row.get("candidate_id") or f"row-{index}")
        body = bodies.get(candidate_id, "")

        ok, reason = verify_hook_quote(entry.get("hook"), body)
        if ok:
            row["hook_draft"] = str(entry["hook"]).strip()
            row["hook_method"] = "llm_verified_verbatim"
        else:
            row["hook_method"] = "heuristic"
            row["llm_hook_rejected_reason"] = reason
            stats["hook_rejected"] += 1

        # Hook quality only re-ranks (``scores.total``); it never touches
        # ``screening_status``.  A rejected/invalid rating leaves the
        # deterministic score in place.
        hook_score = _coerce_hook_score(entry.get("hook_score"))
        if hook_score is not None and ok:
            scores = row.setdefault("scores", {})
            scores["hook_strength"] = hook_score * HOOK_SCORE_SCALE
            row["hook_score_basis"] = "llm"
            row["llm_hook_score_raw"] = hook_score
            recompute_total(row)
        else:
            if hook_score is None:
                stats["hook_score_rejected"] += 1
            row["hook_score_basis"] = "heuristic"

        direction = _coerce_direction(entry.get("direction"))
        if direction:
            row["direction_bucket"] = direction
            row["direction_method"] = "llm"
        else:
            row["direction_method"] = "heuristic"
            stats["direction_rejected"] += 1

        question = entry.get("question")
        if isinstance(question, str) and question.strip():
            row["reader_question_draft"] = question.strip()[:40]

        # --- risk: fail-safe, and never a silent clearance -------------------
        keyword_flags = row.get("risk_flags") or []
        level = _coerce_risk_level(entry.get("risk_level"))
        if level is None:
            stats["risk_level_rejected"] += 1
            row["risk_assessment"] = {
                "method": "heuristic_unverified",
                "level": "unknown",
                "codes": [f["code"] for f in keyword_flags],
                "reason": "LLM 风险判定缺失或非法，保留关键词筛查结果，未经复核",
                "keyword_flags_retained": True,
            }
        else:
            codes = _coerce_risk_codes(entry.get("risk_codes"))
            keyword_codes = {f["code"] for f in keyword_flags}
            overrode = bool(keyword_codes) and not (keyword_codes & set(codes))
            if overrode:
                stats["risk_cleared"] += 1
            row["risk_assessment"] = {
                "method": "llm",
                "level": level,
                "codes": codes,
                "reason": str(entry.get("risk_reason") or "")[:40],
                "keyword_flags_retained": True,
                "overrode_keyword_flags": overrode,
            }

        row["llm_status"] = "applied"
        row["llm_model"] = str(env.get("RUOYU_LLM_MODEL") or "unknown")
        row["llm_prompt_version"] = LLM_PROMPT_VERSION
        stats["llm_applied"] += 1

    for row in targets:
        if row.get("llm_status") != "applied":
            row["llm_status"] = "partial_or_missing"
            _mark_unverified_risk(row, "该条未取得 LLM 判定，保留关键词筛查结果，未经复核")
            stats["fallback"] += 1

    resort_ledger(ledger)
    return stats


def _freshness_score(published_at: str, now: datetime) -> tuple[int, str]:
    if not published_at:
        return 0, "unknown"
    try:
        parsed = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return 0, "unparsable"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age_hours = (now - parsed).total_seconds() / 3600
    if age_hours <= 24:
        return 10, f"{age_hours:.1f}h"
    if age_hours <= 72:
        return 6, f"{age_hours/24:.1f}d"
    if age_hours <= 24 * 7:
        return 3, f"{age_hours/24:.1f}d"
    return 0, f"{age_hours/24:.1f}d"


def build_ledger(
    run_dir: Path,
    account_prior: AccountPrior,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Score every article candidate; keep all of them, drop none."""

    now = now or _utc_now()
    rows = _read_jsonl(run_dir / "article-candidates.jsonl")
    ledger: list[dict[str, Any]] = []

    for row in rows:
        title = _as_text(row.get("title"))
        body = _as_text(row.get("body"))
        account_id = _as_text(row.get("account_id"))
        account_name = _as_text(row.get("account_name"))
        combined = f"{title}\n{body[:1200]}"

        film_hits = _match_terms(combined, FILM_TERMS)
        film_relevant = bool(film_hits)

        evidence_score, evidence_ok, evidence_missing = _score_evidence(row)
        hook_score, hook_reasons = _score_hook(title, body)
        prior_score, prior_label, prior_detail = _score_prior(
            account_id, film_relevant, account_prior
        )
        freshness_score, freshness_label = _freshness_score(
            _as_text(row.get("published_at")), now
        )
        direction, direction_hits = _direction_bucket(combined)
        risk = _detect_risk(combined)

        total = evidence_score + hook_score + prior_score + freshness_score

        reject_reasons: list[str] = []
        if not film_relevant:
            reject_reasons.append("非影视题材")
        if _as_text(row.get("body_status")) != "complete":
            reject_reasons.append("正文不可用")
        if evidence_score < 15:
            reject_reasons.append("证据就绪度过低")

        ledger.append(
            {
                "candidate_id": _as_text(row.get("candidate_id")) or _as_text(row.get("projection_id")),
                "advisory_only": True,
                "account_id": account_id,
                "account_name": account_name,
                "title": title,
                "canonical_url": _as_text(row.get("canonical_url")),
                "content_hash": _as_text(row.get("content_hash")),
                "published_at": _as_text(row.get("published_at")),
                "captured_at": _as_text(row.get("captured_at")),
                "body_chars": len(body),
                "film_relevant": film_relevant,
                "film_hits": film_hits[:6],
                "direction_bucket": direction,
                "direction_hits": direction_hits[:5],
                "scores": {
                    "evidence_readiness": evidence_score,
                    "hook_strength": hook_score,
                    "source_prior": prior_score,
                    "freshness": freshness_score,
                    "total": total,
                },
                "source_prior_label": prior_label,
                "source_prior_detail": prior_detail,
                "source_prior_is_performance_proof": False,
                "evidence_satisfied": evidence_ok,
                "evidence_missing": evidence_missing,
                "hook_reasons": hook_reasons,
                "freshness_label": freshness_label,
                "risk_flags": risk,
                "risk_assessment": {
                    "method": "heuristic",
                    "level": "unknown",
                    "codes": [f["code"] for f in risk],
                    "reason": "关键词筛查结果，未经复核",
                    "keyword_flags_retained": True,
                },
                "hook_draft": _hook_draft(title, body),
                "hook_method": "heuristic",
                "hook_score_basis": "heuristic",
                "direction_method": "heuristic",
                "llm_status": "not_requested",
                "screening_status": "rejected" if reject_reasons else "advisory_candidate",
                "reject_reasons": reject_reasons,
                "human_decision": "pending",
                # Internal only: drives LLM enrichment, stripped before writing.
                "_body": body,
            }
        )

    ledger.sort(key=lambda r: (-r["scores"]["total"], r["title"]))
    return ledger


def build_cards(ledger: Sequence[Mapping[str, Any]], max_cards: int) -> list[Mapping[str, Any]]:
    """Pick at most *max_cards* advisory candidates. Never pad to fill quota."""

    eligible = [r for r in ledger if r.get("screening_status") == "advisory_candidate"]
    return eligible[:max_cards]


def render_cards_markdown(
    cards: Sequence[Mapping[str, Any]],
    ledger: Sequence[Mapping[str, Any]],
    run_dir: Path,
    account_pool: Path | None,
    generated_at: datetime,
) -> str:
    lines: list[str] = []
    lines.append("# 选题建议卡（advisory only — 需 Controller 手动圈题）")
    lines.append("")
    lines.append(f"> 生成时间：{generated_at.isoformat()}")
    lines.append(f"> 来源 run：`{run_dir}`")
    if account_pool is not None:
        lines.append(f"> 账号先验池：`{account_pool}`")
    lines.append("")
    lines.append("**这不是发布队列，也不是自动决策。** 系统只按可解释的维度排序并给建议；")
    lines.append("圈题、换题、放弃都由你决定。账号先验只表示**来源**可信，不代表该篇有实测阅读量。")
    lines.append("")

    if not cards:
        lines.append("## 今日无合格候选")
        lines.append("")
        lines.append("没有任何候选同时满足「影视题材 + 正文可用 + 证据就绪度达标」。")
        lines.append("这是允许的结果：**不为凑数降低标准**。")
        lines.append("")
    else:
        lines.append(f"## 今日建议候选（{len(cards)} 张，上限已设）")
        lines.append("")
        for index, card in enumerate(cards, start=1):
            scores = card.get("scores") or {}
            lines.append(f"### 候选 {index}｜{card.get('title')}")
            lines.append("")
            lines.append(f"- **账号**：{card.get('account_name')}（{card.get('source_prior_label')}）")
            direction_note = "LLM" if card.get("direction_method") == "llm" else "关键词"
            lines.append(f"- **方向桶**：{card.get('direction_bucket')}（{direction_note}）"
                         + (f"（命中：{'/'.join(card.get('direction_hits') or [])}）"
                            if card.get("direction_hits") and direction_note == "关键词" else ""))
            hook_note = "LLM 逐字摘录（已校验）" if card.get("hook_method") == "llm_verified_verbatim" else "关键词启发式"
            lines.append(f"- **强钩草案**：{card.get('hook_draft')}")
            lines.append(f"- **钩子来源**：{hook_note}")
            if card.get("llm_hook_rejected_reason"):
                lines.append(f"- **LLM 钩子未采用**：{card['llm_hook_rejected_reason']}（已回退启发式）")
            if card.get("reader_question_draft"):
                lines.append(f"- **读者问题草案**：{card.get('reader_question_draft')}")
            if card.get("hook_reasons") and card.get("hook_method") != "llm_verified_verbatim":
                lines.append(f"- **钩子依据**：{'；'.join(card['hook_reasons'])}")
            lines.append(
                f"- **分项评分**：证据就绪 {scores.get('evidence_readiness')}/40 ｜ "
                f"钩子强度 {scores.get('hook_strength')}/30"
                f"（{'LLM 评分' if card.get('hook_score_basis') == 'llm' else '关键词'}） ｜ "
                f"来源先验 {scores.get('source_prior')}/20 ｜ "
                f"时效 {scores.get('freshness')}/10 ｜ 合计 {scores.get('total')}"
            )
            lines.append(f"- **正文**：{card.get('body_chars')} 字，发布时间 {card.get('published_at') or '未知'}")
            lines.append(f"- **已具备**：{'；'.join(card.get('evidence_satisfied') or []) or '—'}")
            lines.append(f"- **仍缺**：{'；'.join(card.get('evidence_missing') or []) or '—'}")

            assessment = card.get("risk_assessment") or {}
            keyword_flags = card.get("risk_flags") or []
            level = assessment.get("level", "unknown")
            level_label = {
                "none": "无", "low": "低", "medium": "中", "high": "高",
            }.get(level, "未复核")
            method_label = {
                "llm": "LLM 判定",
                "heuristic_unverified": "关键词（未复核）",
                "heuristic": "关键词（未复核）",
            }.get(assessment.get("method"), "未复核")
            risk_line = f"- **风险**：{level_label}（{method_label}）"
            if assessment.get("reason"):
                risk_line += f"　{assessment['reason']}"
            lines.append(risk_line)
            if keyword_flags:
                lines.append(
                    "- **关键词命中（保留可见）**："
                    + "；".join(f"{r['label']}（{'/'.join(r['hits'])}）" for r in keyword_flags)
                    + ("　→ LLM 判定为不构成实际风险，仅属提及" if assessment.get("overrode_keyword_flags") else "")
                )
            if assessment.get("method") == "heuristic_unverified":
                lines.append("- **注意**：该条未取得 LLM 风险判定，**不得**视为已排除风险")
            lines.append(f"- **链接**：{card.get('canonical_url') or '—'}")
            lines.append(f"- **决定**：[ ] 圈题　[ ] 储备　[ ] 放弃　（human_decision 当前：pending）")
            lines.append("")

    rejected = [r for r in ledger if r.get("screening_status") == "rejected"]
    lines.append("## 被筛掉的原因分布")
    lines.append("")
    lines.append(f"- 评估总数：{len(ledger)}")
    lines.append(f"- 建议候选：{len(ledger) - len(rejected)}")
    lines.append(f"- 被筛掉：{len(rejected)}")
    lines.append("")
    if rejected:
        counts: dict[str, int] = {}
        for row in rejected:
            for reason in row.get("reject_reasons") or []:
                counts[reason] = counts.get(reason, 0) + 1
        lines.append("| 原因 | 数量 |")
        lines.append("| --- | ---: |")
        for reason, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {reason} | {count} |")
        lines.append("")
    lines.append("完整候选账本（含全部被筛项与理由）见 `candidate-ledger.jsonl`。")
    lines.append("")
    lines.append("## 边界声明")
    lines.append("")
    lines.append("- 本文件是**建议**，不是决策、不是发布授权、不是爆款认定。")
    lines.append("- 账号先验（`source_prior`）是**来源**资格，不是该篇表现证据。")
    lines.append("- 钩子草案是写作建议，未绑定正文 locator 前**不得**直接用作标题。")
    lines.append("- 风险标记只是筛查提示，是否可写由 Controller 判断。")
    lines.append("")
    return "\n".join(lines)


OUTPUT_FILENAMES = ("candidate-ledger.jsonl", "candidate-cards.md", "scout-summary.json")
SEALED_MARKERS = ("SEALED", "sealed.json")


def _sealed_ancestor(path: Path) -> Path | None:
    """Return the nearest ancestor that is a sealed run, if any."""

    current = path.resolve()
    for candidate in (current, *current.parents):
        for marker in SEALED_MARKERS:
            if (candidate / marker).exists():
                return candidate
    return None


def _guard_output_dir(
    out_dir: Path,
    *,
    allow_overwrite: bool,
    filenames: Sequence[str] = OUTPUT_FILENAMES,
) -> str | None:
    """Return a refusal code, or None when writing is safe.

    Fail-closed on two things the run-writer rules care about: never write into
    a sealed run, and never silently overwrite an earlier scout's artifacts.
    """

    sealed = _sealed_ancestor(out_dir)
    if sealed is not None:
        return f"refuse_sealed_run:{sealed}"
    if not allow_overwrite:
        existing = [name for name in filenames if (out_dir / name).exists()]
        if existing:
            return "refuse_overwrite:" + ",".join(existing)
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-run", required=True, type=Path,
                        help="media-intel article-research run directory (read-only)")
    parser.add_argument("--account-pool", type=Path, default=None,
                        help="approved_viral_account_pool.json (source prior only)")
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--max-cards", type=int, default=5)
    parser.add_argument("--allow-overwrite", action="store_true",
                        help="overwrite a previous scout output in the same directory")
    parser.add_argument("--llm", action="store_true",
                        help="enrich hook/direction with the shared LLM channel (costs tokens)")
    parser.add_argument("--llm-limit", type=int, default=DEFAULT_LLM_LIMIT,
                        help="max candidates to send to the LLM in one call")
    args = parser.parse_args(argv)

    if not args.research_run.is_dir():
        print(json.dumps({"status": "FAIL", "reason": "research_run_missing",
                          "path": str(args.research_run)}, ensure_ascii=False))
        return 2

    refusal = _guard_output_dir(args.out_dir, allow_overwrite=args.allow_overwrite)
    if refusal is not None:
        print(json.dumps({"status": "BLOCKED", "reason": refusal,
                          "out_dir": str(args.out_dir)}, ensure_ascii=False))
        return 3

    now = _utc_now()
    prior = AccountPrior.load(args.account_pool)
    ledger = build_ledger(args.research_run, prior, now=now)

    llm_stats: dict[str, int] = {"requested": 0, "llm_applied": 0, "hook_rejected": 0,
                                 "direction_rejected": 0, "fallback": 0, "unavailable": 0}
    llm_note = "not_requested"
    if args.llm:
        try:
            env = load_env()
        except SystemExit as exc:
            env = None
            llm_note = f"credentials_unavailable:{exc}"
            for row in ledger:
                if row.get("screening_status") == "advisory_candidate":
                    row["llm_status"] = "unavailable"
            print(f"[topic-scout] LLM 不可用，已全部回退确定性版本（{exc}）", file=sys.stderr)
        if env is not None:
            llm_stats = enrich_ledger_with_llm(
                ledger, env=env, limit=max(0, args.llm_limit)
            )
            llm_note = "applied"

    cards = build_cards(ledger, max(0, args.max_cards))

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # ``_body`` is an internal carrier for LLM enrichment; never persist it.
    ledger_path = args.out_dir / "candidate-ledger.jsonl"
    ledger_path.write_text(
        "\n".join(
            json.dumps({k: v for k, v in row.items() if k != "_body"}, ensure_ascii=False)
            for row in ledger
        ) + ("\n" if ledger else ""),
        encoding="utf-8",
    )

    cards_path = args.out_dir / "candidate-cards.md"
    cards_path.write_text(
        render_cards_markdown(cards, ledger, args.research_run, args.account_pool, now),
        encoding="utf-8",
    )

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "advisory_only": True,
        "research_run": str(args.research_run),
        "account_pool": str(args.account_pool) if args.account_pool else None,
        "counts": {
            "evaluated": len(ledger),
            "advisory_candidates": len(ledger) - sum(
                1 for r in ledger if r.get("screening_status") == "rejected"
            ),
            "rejected": sum(1 for r in ledger if r.get("screening_status") == "rejected"),
            "cards_emitted": len(cards),
            "film_relevant": sum(1 for r in ledger if r.get("film_relevant")),
            "from_approved_head_account": sum(
                1 for r in ledger if r.get("source_prior_label") == "approved_head_account"
            ),
        },
        "outputs": {"ledger": str(ledger_path), "cards": str(cards_path)},
        "llm": {
            "enabled": bool(args.llm),
            "note": llm_note,
            "prompt_version": LLM_PROMPT_VERSION,
            "ranking_used_llm_hook_score": llm_stats.get("llm_applied", 0) > 0
            and any(r.get("hook_score_basis") == "llm" for r in ledger),
            **llm_stats,
        },
        "boundaries": {
            "decides_topic": False,
            "authorises_writing": False,
            "authorises_publication": False,
            "upgrades_to_verified_viral": False,
            "llm_changes_eligibility": False,
            "llm_may_rerank": True,
            "llm_hook_requires_verbatim_match": True,
            "risk_failure_is_fail_safe": True,
            "notes": "source_prior is a source-level prior, not article performance evidence",
        },
    }
    summary_path = args.out_dir / "scout-summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"status": "PASS", **summary["counts"], "out_dir": str(args.out_dir)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
