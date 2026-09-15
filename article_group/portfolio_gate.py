"""Batch portfolio diversity gate for the ruoyu article group.

Validates that a selected batch (3 articles) satisfies topic-diversity rules
established 2026-08-07 after controlled-015 produced three schedule-change
articles from the same event cluster:

- batch covers >= 2 content_map quadrants (A new-release event / B deep work /
  C cultural phenomenon / D person-controversy), same quadrant <= 2 articles
- same event_cluster_id at most 1 article per batch
- window mix preferred: same-day + fermenting-1-3d + revival; a missing
  evergreen slot is allowed when no qualified candidate exists
  (evergreen_gap: true) - never force a weak topic to satisfy diversity
- remove_timestamp_test recorded per article; "fail" items must not be the
  main slot in two consecutive batches
- topic_mode must not be release_event for all three articles
- editorial_value_score (1-5) and evidence_readiness (high/medium/low) are
  recorded separately: high readiness does not equal worth writing

Input: a candidate-pool JSON (same shape as runs/*/controlled-*/candidate-pool.json)
with a "candidates" list; the gate reads the selected batch from the
"selected_slot_ids" field if present, otherwise from candidates with
recommendation == "A" (up to 3). Output: JSON verdict with warnings/errors.

Exit code: 0 if no errors, 1 if errors. Run from project root:
    uv run python -m article_group.portfolio_gate <candidates.json>
"""
from __future__ import annotations

import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

QUADRANTS = {"A", "B", "C", "D"}
QUADRANT_LABELS = {
    "A": "新片事件",
    "B": "作品深度",
    "C": "文化现象",
    "D": "人物争议",
}
TOPIC_MODES = {
    "release_event",
    "character",
    "craft",
    "audience",
    "culture",
    "revisit",
    "market",
}
WINDOWS = {"same-day", "fermenting-1-3d", "revival"}
READINESS = {"high", "medium", "low"}


def _load(pool_path: str) -> tuple[dict, list[dict], list[str]]:
    data = json.loads(Path(pool_path).read_text(encoding="utf-8"))
    candidates = data.get("candidates", [])
    selected_ids = data.get("selected_slot_ids")
    if selected_ids:
        by_id = {c.get("candidate_id"): c for c in candidates}
        selected = [by_id[i] for i in selected_ids if i in by_id]
        missing = [i for i in selected_ids if i not in by_id]
        if missing:
            return data, [], [f"selected_slot_ids 引用不存在的候选: {missing}"]
    else:
        selected = [c for c in candidates if c.get("recommendation") == "A"][:3]
        if len(selected) < 3:
            return data, [], [f"批次不足 3 篇（推荐 A 仅 {len(selected)} 篇）"]
    return data, selected, []


def _field(cand: dict, *keys: str) -> str:
    for k in keys:
        if cand.get(k):
            return str(cand[k])
    return ""


def _normalize(value: str) -> str:
    """Map legacy/free-form values to canonical enums where possible."""
    v = str(value).strip()
    if v.upper() in QUADRANTS:
        return v.upper()
    # content_map may be stored as a label like "A 新片事件" or "新片事件"
    low = v.lower()
    for q, label in QUADRANT_LABELS.items():
        if q in v or label in low:
            return q
    return ""


def check_quadrants(selected: list[dict]) -> list[dict]:
    issues = []
    counts: dict[str, int] = {}
    for cand in selected:
        q = _normalize(_field(cand, "content_map", "content_map_label"))
        if not q:
            issues.append(
                {
                    "level": "error",
                    "id": "portfolio.quadrant.missing",
                    "candidate": cand.get("candidate_id"),
                    "message": "content_map 象限缺失或无法识别（应为 A/B/C/D）",
                }
            )
            continue
        counts[q] = counts.get(q, 0) + 1
    if counts and len(counts) < 2:
        issues.append(
            {
                "level": "error",
                "id": "portfolio.quadrant.concentrated",
                "candidate": None,
                "message": f"批次仅覆盖 1 个象限 {counts}，须 ≥2 个",
            }
        )
    for q, n in counts.items():
        if n > 2:
            issues.append(
                {
                    "level": "error",
                    "id": "portfolio.quadrant.overquota",
                    "candidate": None,
                    "message": f"象限 {q} 达 {n} 篇，同象限须 ≤2",
                }
            )
    return issues


def check_event_clusters(selected: list[dict]) -> list[dict]:
    issues = []
    clusters: dict[str, list[str]] = {}
    for cand in selected:
        cluster = _field(cand, "event_cluster_id")
        if not cluster:
            issues.append(
                {
                    "level": "warning",
                    "id": "portfolio.cluster.missing",
                    "candidate": cand.get("candidate_id"),
                    "message": "event_cluster_id 缺失：无法做跨篇事件簇去重（015 教训：三篇同簇被当作独立选题）",
                }
            )
            continue
        clusters.setdefault(cluster, []).append(str(cand.get("candidate_id")))
    for cluster, cids in clusters.items():
        if len(cids) > 1:
            issues.append(
                {
                    "level": "error",
                    "id": "portfolio.cluster.duplicate",
                    "candidate": None,
                    "message": f"事件簇 {cluster} 占 {len(cids)} 篇（{cids}），每批同簇须 ≤1——同簇不同作品不算独立选题",
                }
            )
    return issues


def check_windows(selected: list[dict]) -> list[dict]:
    issues = []
    windows = [_field(c, "freshness_window") for c in selected]
    for w in windows:
        if w and w not in WINDOWS:
            issues.append(
                {
                    "level": "warning",
                    "id": "portfolio.window.invalid",
                    "candidate": None,
                    "message": f"freshness_window 非法值 {w!r}（应为 same-day/fermenting-1-3d/revival）",
                }
            )
    missing_evergreen = "revival" not in windows
    if missing_evergreen:
        issues.append(
            {
                "level": "info",
                "id": "portfolio.window.evergreen_gap",
                "candidate": None,
                "message": "无 revival（常青/翻红）候选：允许空缺，须在批记录中记 evergreen_gap: true，不强行凑数",
            }
        )
    return issues


def check_topic_modes(selected: list[dict]) -> list[dict]:
    issues = []
    modes = [_field(c, "topic_mode") for c in selected]
    for m in modes:
        if m and m not in TOPIC_MODES:
            issues.append(
                {
                    "level": "warning",
                    "id": "portfolio.topic_mode.invalid",
                    "candidate": None,
                    "message": f"topic_mode 非法值 {m!r}（应为 {sorted(TOPIC_MODES)}）",
                }
            )
    if modes and all(m == "release_event" for m in modes):
        issues.append(
            {
                "level": "error",
                "id": "portfolio.topic_mode.all_release_event",
                "candidate": None,
                "message": "三篇叙事入口全为 release_event——允许新片，但新片也可走 character/craft/audience 入口",
            }
        )
    return issues


def check_timestamp_tests(selected: list[dict]) -> list[dict]:
    issues = []
    for cand in selected:
        result = _field(cand, "remove_timestamp_test", "timestamp_removal_test")
        if not result:
            issues.append(
                {
                    "level": "warning",
                    "id": "portfolio.timestamp.missing",
                    "candidate": cand.get("candidate_id"),
                    "message": "remove_timestamp_test 缺失（pass/risk/fail）",
                }
            )
    return issues


def check_value_readiness(selected: list[dict]) -> list[dict]:
    issues = []
    for cand in selected:
        value = cand.get("editorial_value_score")
        readiness = _field(cand, "evidence_readiness")
        if value is None:
            issues.append(
                {
                    "level": "warning",
                    "id": "portfolio.value.missing",
                    "candidate": cand.get("candidate_id"),
                    "message": "editorial_value_score 缺失（1-5，内容价值独立于时效）",
                }
            )
        if readiness and readiness not in READINESS:
            issues.append(
                {
                    "level": "warning",
                    "id": "portfolio.readiness.invalid",
                    "candidate": cand.get("candidate_id"),
                    "message": f"evidence_readiness 非法值 {readiness!r}（应为 high/medium/low）",
                }
            )
    return issues


# ---------------------------------------------------------------------------
# Cross-batch homogeneity check (平台规范：与近 10 篇同质化对比)
# 依据《头条与微信公众号优质文章及 AI 写稿作业规范》(2026-08-07 调研版)：
#  - 同作品/同题材在窗口内重复 = 黄灯（warning，须确认新角度/新数据）
#  - 近 3 批内同作品重复或标题高度相似 = 红灯（error，连续翻炒）
# ---------------------------------------------------------------------------

TITLE_SIM_WARN = 0.60
TITLE_SIM_ERROR = 0.85
CROSS_BATCH_WINDOW = 10
RECENT3 = 3


def collect_history(
    limit: int = CROSS_BATCH_WINDOW,
    exclude_run: str = "",
    runs_root: Path | None = None,
) -> list[dict]:
    """从 runs/*/controlled-*/ 与 runs/*/daily-*/ 收集历史交付标题指纹（近 limit 批，时间倒序）。

    每批优先取根目录交付副本（ruoyu-articles-*.html，016 及以前命名），
    否则取 review/frozen 下所有交付 HTML：兼容两种命名——
      - ruoyu-articles-*.html（旧：整批合并包，016 及以前）
      - ruoyu-art-00*.html（新：单篇 frozen，021 起）
    修复 026 发现的命名契约断裂：021 起批次因只收 ruoyu-articles-* 整段漏窗。
    修复 2026-09-15 复核发现的漏窗：`daily-*` 日更批次此前完全不在历史内，
    导致跨批查重对日更永久失效（见《接手总纲》A-B3）。
    """
    if runs_root is None:
        runs_root = Path(__file__).resolve().parent.parent / "runs"
    batches: list[dict] = []
    batch_dirs = list(runs_root.glob("*/controlled-*")) + list(runs_root.glob("*/daily-*"))
    for batch_dir in sorted(batch_dirs, key=lambda path: str(path), reverse=True):
        if exclude_run and batch_dir.name == exclude_run:
            continue
        htmls = sorted(batch_dir.glob("ruoyu-articles-*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not htmls:
            frozen_dir = batch_dir / "review" / "frozen"
            if frozen_dir.exists():
                htmls = sorted(
                    list(frozen_dir.glob("ruoyu-articles-*.html"))
                    + list(frozen_dir.glob("ruoyu-art-00*.html")),
                    key=lambda p: p.stat().st_mtime, reverse=True,
                )
        titles: list[str] = []
        works: list[str] = []
        for h in htmls:  # 单篇命名（021+）下需聚合整批全部文章指纹
            t, w = _extract_titles(h)
            titles.extend(t)
            works.extend(w)
        reader_questions: list[str] = []
        content_fingerprints: list[str] = []
        batch_path = batch_dir / "batch.json"
        try:
            batch = json.loads(batch_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            batch = {}
        batch_articles = batch.get("articles") if isinstance(batch, dict) else None
        if isinstance(batch_articles, list):
            for article in batch_articles:
                if not isinstance(article, dict):
                    continue
                question = _field(article, "reader_question").strip()
                core_object = _field(article, "core_object").strip() or _field(article, "work").strip()
                primary_atom = _field(article, "primary_atom").strip()
                article_work_names = re.findall(r"《([^》]{1,20})》", core_object)
                works.extend(article_work_names or ([core_object] if core_object else []))
                article_title = _field(article, "title").strip()
                if article_title:
                    titles.append(article_title)
                if question:
                    reader_questions.append(question)
                    content_fingerprints.append(question)
                for value in (core_object, primary_atom):
                    if value and value not in content_fingerprints:
                        content_fingerprints.append(value)
        if not titles and not content_fingerprints and not works:
            continue
        batches.append(
            {
                "batch_dir": batch_dir.name,
                "path": str(htmls[0] if htmls else batch_path),
                "titles": titles,
                "works": works,
                "reader_questions": reader_questions,
                "content_fingerprints": content_fingerprints,
            }
        )
        if len(batches) >= limit:
            break
    for i, b in enumerate(batches):
        b["recent3"] = i < RECENT3
    return batches


def _extract_titles(path: str | Path) -> tuple[list[str], list[str]]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    raw = re.findall(r"<h2[^>]*>(.*?)</h2>", text, re.S)
    titles: list[str] = []
    works: list[str] = []
    for t in raw:
        t = re.sub(r"<[^>]+>", "", t).strip()
        t = re.sub(r"\s+", "", t)
        if not t or "目录" in t:
            continue
        titles.append(t)
        # 反衬提及排除：标题中「撞上/碰上/空降/同期/对比」等反衬句式里的《X》
        # 只是被提及的作品（025/026 实证：015「撞上了空降的《欢迎来龙餐馆》」非专文），
        # 不计入 works，避免跨批误报。仅保留主语位置的作品名。
        for seg in _split_title_segments(t):
            for w in re.findall(r"《([^》]{1,20})》", seg):
                works.append(w)
    return titles, works


def _split_title_segments(t: str) -> list[str]:
    """把 h2 标题按反衬连接词切开，只保留主语段。

    反衬句式示例：『上映前三天改档的《大唐妖探》，撞上了空降的《欢迎来龙餐馆》』
    → 主语段『上映前三天改档的《大唐妖探》』保留，《欢迎来龙餐馆》被排除。
    """
    contrast_markers = ("撞上", "碰上", "遇上", "空降", "同期", "对比", "让位", "让路", "看好戏", "等来", "迎来")
    for seg in re.split(r"[，,、；;：:——\-｜|·]", t):
        if not seg:
            continue
        if any(m in seg for m in contrast_markers):
            continue  # 反衬段整体排除（提及非专文）
        yield seg


def interpret_history_input(value: object) -> dict:
    """Distinguish unloaded history from a loaded window that happens to be empty.

    A bare empty list is not proof that history was checked. Callers must record
    an attempted load before claiming ``empty_history``.
    """
    if isinstance(value, list):
        if value:
            return {"history_status": "loaded", "batches": value, "attempted": True}
        return {"history_status": "not_loaded", "batches": [], "attempted": False}
    if isinstance(value, dict):
        status = value.get("history_status")
        batches = value.get("batches", [])
        attempted = value.get("attempted") is True
        if status == "empty_history" and attempted and batches == []:
            return {"history_status": "empty_history", "batches": [], "attempted": True}
        if status == "loaded" and isinstance(batches, list) and batches:
            return {"history_status": "loaded", "batches": batches, "attempted": True}
        if status == "not_loaded":
            return {"history_status": "not_loaded", "batches": [], "attempted": attempted}
    return {"history_status": "not_loaded", "batches": [], "attempted": False}


def validate_cross_batch_report(report: object) -> list[str]:
    if not isinstance(report, dict):
        return ["cross_batch_report_invalid"]
    errors: list[str] = []
    status = report.get("history_status")
    if report.get("checked") is True and status not in {"loaded", "empty_history"}:
        errors.append("cross_batch_checked_without_loaded_history")
    return sorted(set(errors))


def check_cross_batch(
    selected: list[dict],
    history: list[dict],
    *,
    history_status: str | None = None,
) -> list[dict]:
    issues: list[dict] = []
    if history_status is None:
        history_status = "loaded" if history else "not_loaded"
    if history_status == "not_loaded" or (history_status == "loaded" and not history):
        issues.append(
            {
                "level": "error",
                "id": "portfolio.cross_batch.history_not_loaded",
                "candidate": None,
                "message": "跨批历史未加载，不能宣称去重通过",
            }
        )
        return issues
    if history_status == "empty_history":
        issues.append(
            {
                "level": "info",
                "id": "portfolio.cross_batch.no_history",
                "candidate": None,
                "message": "已加载跨批历史，近窗内没有可比对批次",
            }
        )
        return issues
    if history_status != "loaded":
        issues.append(
            {
                "level": "error",
                "id": "portfolio.cross_batch.history_status_invalid",
                "candidate": None,
                "message": f"跨批历史状态无效：{history_status}",
            }
        )
        return issues
    for cand in selected:
        cid = cand.get("candidate_id")
        work = _field(cand, "work").strip()
        question = _field(cand, "reader_question").strip()
        content_fingerprints = [
            value
            for value in (
                question,
                _field(cand, "core_object").strip(),
                _field(cand, "primary_atom").strip(),
            )
            if value
        ]
        work_names = re.findall(r"《([^》]{1,20})》", work) or ([work] if work else [])
        if not work_names and not content_fingerprints:
            issues.append(
                {
                    "level": "info",
                    "id": "portfolio.cross_batch.no_fingerprint",
                    "candidate": cid,
                    "message": "无 work/reader_question 字段，无法做跨批同质化比对",
                }
            )
            continue
        for h in history:
            matched_works = [w for w in h.get("works", []) if any(wn == w for wn in work_names)]
            best_sim = 0.0
            best_fingerprint = ""
            history_fingerprints = h.get("content_fingerprints", [])
            if isinstance(history_fingerprints, list):
                for current in content_fingerprints:
                    for previous in history_fingerprints:
                        if not isinstance(previous, str) or not previous.strip():
                            continue
                        sim = SequenceMatcher(None, current, previous).ratio()
                        if sim > best_sim:
                            best_sim, best_fingerprint = sim, previous
            if matched_works:
                historical_title = (h.get("titles") or ["历史交付"])[0]
                level = "error" if h["recent3"] else "warning"
                issues.append(
                    {
                        "level": level,
                        "id": "portfolio.cross_batch.same_work.recent" if level == "error" else "portfolio.cross_batch.same_work",
                        "candidate": cid,
                        "message": (
                            f"《{matched_works[0]}》批次 {h['batch_dir']} 已写（{historical_title[:38]}…）；"
                            "须确认实质新角度/新数据"
                            + ("；近 3 批内重复，视为连续翻炒（红灯）" if level == "error" else "（黄灯）")
                        ),
                        "batch": h["batch_dir"],
                    }
                )
            if best_sim >= TITLE_SIM_ERROR:
                issues.append(
                    {
                        "level": "error",
                        "id": "portfolio.cross_batch.title_near_duplicate",
                        "candidate": cid,
                        "message": f"正文问题/对象与批次 {h['batch_dir']} 内容指纹高度相似（sim={best_sim:.2f}）：{best_fingerprint[:38]}…",
                        "batch": h["batch_dir"],
                    }
                )
            elif best_sim >= TITLE_SIM_WARN:
                issues.append(
                    {
                        "level": "warning",
                        "id": "portfolio.cross_batch.title_similar",
                        "candidate": cid,
                        "message": f"正文问题/对象与批次 {h['batch_dir']} 内容指纹相似（sim={best_sim:.2f}）：{best_fingerprint[:38]}…",
                        "batch": h["batch_dir"],
                    }
                )
    return issues


def _run_dir_name(pool_path: str) -> str:
    """Return the batch directory name that owns ``pool_path``.

    A pool may live at the run root (``runs/<date>/<batch>/pool.json``) or under
    ``review/`` (``runs/<date>/<batch>/review/pool.json``); walking up until the
    parent of a dated directory yields the same identifier ``collect_history``
    compares against, so a run never sees itself in its own cross-batch window.
    """
    path = Path(pool_path).resolve()
    for candidate in path.parents:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate.parent.name):
            return candidate.name
    return path.parent.name


def run_checks(pool_path: str, cross_batch_window: int = 0) -> tuple[dict, int]:
    data, selected, fatal = _load(pool_path)
    issues: list[dict] = []
    if fatal:
        issues.extend(
            {"level": "error", "id": "portfolio.input", "candidate": None, "message": m}
            for m in fatal
        )
    else:
        for checker in (
            check_quadrants,
            check_event_clusters,
            check_windows,
            check_topic_modes,
            check_timestamp_tests,
            check_value_readiness,
        ):
            issues.extend(checker(selected))

    cross_batch: dict | None = None
    if cross_batch_window > 0 and not fatal:
        # ``collect_history`` matches ``exclude_run`` against the batch directory
        # *name*; derive it from the pool location so a run cannot appear in its
        # own cross-batch window (self-comparison).
        current_run = _run_dir_name(pool_path)
        history = collect_history(limit=cross_batch_window, exclude_run=current_run)
        history_status = "loaded" if history else "empty_history"
        cross_issues = check_cross_batch(selected, history, history_status=history_status)
        issues.extend(cross_issues)
        cross_batch = {
            "checked": True,
            "history_status": history_status,
            "window_batches": len(history),
            "batches": [h["batch_dir"] for h in history],
            "matches": cross_issues,
        }

    errors = [i for i in issues if i["level"] == "error"]
    warnings = [i for i in issues if i["level"] == "warning"]
    infos = [i for i in issues if i["level"] == "info"]
    verdict = {
        "pass": not errors,
        "errors": errors,
        "warnings": warnings,
        "infos": infos,
        "batch_size": len(selected),
        "quadrant_counts": _quadrant_counts(selected),
        "cluster_counts": _cluster_counts(selected),
        "windows": sorted({_field(c, "freshness_window") for c in selected}),
        "topic_modes": sorted({_field(c, "topic_mode") for c in selected}),
        "cross_batch": cross_batch,
    }
    return verdict, 0 if verdict["pass"] else 1


def _quadrant_counts(selected: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for cand in selected:
        q = _normalize(_field(cand, "content_map"))
        if q:
            counts[q] = counts.get(q, 0) + 1
    return counts


def _cluster_counts(selected: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for cand in selected:
        cluster = _field(cand, "event_cluster_id")
        if cluster:
            counts[cluster] = counts.get(cluster, 0) + 1
    return counts


def main() -> int:
    if len(sys.argv) < 2:
        print(
            json.dumps(
                {
                    "error": "用法: uv run python -m article_group.portfolio_gate <candidates.json> [--cross-batch [N]]  # N=近 N 批窗口，默认 10"
                },
                ensure_ascii=False,
            )
        )
        return 2
    pool = sys.argv[1]
    cross_batch_window = 0
    if "--cross-batch" in sys.argv:
        i = sys.argv.index("--cross-batch")
        cross_batch_window = CROSS_BATCH_WINDOW
        if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit():
            cross_batch_window = int(sys.argv[i + 1])
    verdict, code = run_checks(pool, cross_batch_window)
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
