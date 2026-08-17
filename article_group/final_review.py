"""final_review — prepublication 总复核层（v1）。

汇总单批所有闸门产物为单一判定：PUBLISHABLE / BLOCKED / PENDING（需人工）。

判定顺序（fail-closed）：
1. 证据齐全性：batch.json / preflight-report.json / 交付 HTML 必须存在；
   style-gate / prose-pilot / editorial-record 缺失记 evidence_gap（不阻断）。
2. 机械闸门：preflight status == PASS；style-gate error_count == 0。
3. 发布不变量：publication_authorization == "not_authorized" 且无 authorization_* 字段。
4. 跨批指纹：collect_history(exclude_run=本批) + check_cross_batch，error 级命中阻断。
5. 存疑判定：style-gate warning 或 prose-pilot 与 style_gate 字数口径差 > 15% → PENDING。
6. 全过 → PUBLISHABLE（质量判定，发布永远人工）。

用法：
    python -m article_group.final_review --batch runs/2026-08-15/controlled-020
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from article_group.editorial_review import evaluate_editorial_record
from article_group.portfolio_gate import check_cross_batch, collect_history

PUBLISHABLE = "PUBLISHABLE"
BLOCKED = "BLOCKED"
PENDING = "PENDING"

CHAR_DIFF_TOLERANCE = 0.15  # style_gate 与 prose_pilot 字数口径差容限

# style_gate 的结构化检查是 warning-level，除了 hook_declaration 的
# producer-specific failure statuses（missing/mismatch）。closing_interaction
# 的 info 状态是建议，不进入人工判定队列。
_STRUCTURED_WARNING_STATUSES = {
    "opening_hook": {"warning"},
    "title_gap": {"warning"},
    "fact_density": {"warning"},
    "hook_declaration": {"missing", "mismatch", "warning"},
    "closing_interaction": {"warning"},
}


def _load_json(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _evidence_gap(reason: str) -> dict:
    return {"type": "evidence_gap", "reason": reason}


def _blocked(reason: str, **extra: object) -> dict:
    return {"verdict": BLOCKED, "reason": reason, **extra}


def _pending(reason: str, items: list[str]) -> dict:
    return {"verdict": PENDING, "reason": reason, "human_judgment_items": items}


def _publishable() -> dict:
    return {"verdict": PUBLISHABLE, "reason": "全部闸门通过"}


def evaluate_batch(batch_dir: str | Path) -> dict:
    """对单个批次目录执行总复核，返回判定报告。"""
    root = Path(batch_dir)
    if not root.is_dir():
        return _blocked("batch_dir_missing", batch_dir=str(root))

    gaps: list[dict] = []
    human_items: list[str] = []

    # ---- 1. 证据齐全性 -------------------------------------------------
    batch_json = root / "batch.json"
    preflight = root / "preflight-report.json"
    if not batch_json.exists():
        return _blocked("evidence_missing:batch.json")
    batch = _load_json(batch_json)
    if batch is None:
        return _blocked("evidence_unreadable:batch.json")

    articles = batch.get("articles") or []
    if not isinstance(articles, list) or not articles:
        return _blocked("evidence_invalid:batch.json:no_articles")

    run_id = str(batch.get("run_id", ""))
    if not run_id:
        return _blocked("evidence_invalid:batch.json:no_run_id")

    if not preflight.exists():
        return _blocked("evidence_missing:preflight-report.json")
    preflight_data = _load_json(preflight)
    if preflight_data is None:
        return _blocked("evidence_unreadable:preflight-report.json")
    if str(preflight_data.get("status", "")).upper() != "PASS":
        return _blocked("gate:preflight", status=str(preflight_data.get("status")))

    # 交付 HTML：根目录 bundle 或 review/ 下成品
    delivery_htmls = sorted(root.glob("ruoyu-articles-*.html")) or sorted(
        (root / "review").glob("ruoyu-art-*.html")
    ) or sorted((root / "review" / "frozen").glob("*.html"))
    if not delivery_htmls:
        gaps.append(_evidence_gap("交付 HTML 缺失（root/review/frozen 均无）"))

    # ---- 2. 机械闸门：style_gate ---------------------------------------
    style_files = sorted(root.glob("review/style-gate-*.json"))
    if not style_files:
        return _blocked("evidence_missing:style-gate-*.json")
    for sf in style_files:
        data = _load_json(sf)
        if data is None:
            return _blocked("evidence_unreadable:style-gate", file=sf.name)
        for art in data.get("articles") or []:
            if not isinstance(art, dict):
                continue
            if int(art.get("error_count", 0) or 0) > 0:
                return _blocked("gate:style_gate", file=sf.name, article=art.get("index"))
            for hit in art.get("hits") or []:
                if isinstance(hit, dict) and hit.get("severity") == "warning":
                    human_items.append(f"{sf.name}: {hit.get('rule')}")
            for field, warning_statuses in _STRUCTURED_WARNING_STATUSES.items():
                structured_status = art.get(field)
                if (
                    isinstance(structured_status, dict)
                    and structured_status.get("status") in warning_statuses
                ):
                    human_items.append(
                        f"{sf.name}: {field}: {structured_status.get('reason', 'status=warning')}"
                    )

    # ---- 3. 发布不变量 ---------------------------------------------------
    auth_fields = ("authorization_by", "authorized_at", "authorization_ref", "authorized_publication_scope")
    for art in articles:
        if not isinstance(art, dict):
            continue
        aid = str(art.get("article_id", "?"))
        if str(art.get("publication_authorization", "not_authorized")) != "not_authorized":
            return _blocked("gate:publication_authorization", article=aid,
                            value=str(art.get("publication_authorization")))
        for field in auth_fields:
            if art.get(field) not in (None, ""):
                return _blocked("gate:publication_authorization", article=aid, field=field)

    # ---- 4. 跨批指纹 ------------------------------------------------------
    try:
        history = collect_history(exclude_run=root.name)
        issues = check_cross_batch(articles, history)
    except Exception as exc:  # noqa: BLE001 — 指纹检查失败不得放行
        return _blocked("gate:cross_batch_failed", error=str(exc))
    waivers: list[dict] = []
    for issue in issues:
        level = str(issue.get("level", ""))
        if level == "error":
            # 控制器豁免注记通道（人机一致）：portfolio-gate-report.json 中已有人工裁决
            # （confirmed_new_angle / 确认豁免）且 candidate 匹配时，error 降级为已裁决
            # 记录放行，不再 BLOCKED——机器只拦未裁决的重复。
            waiver = _match_adjudication_waiver(root, str(issue.get("candidate", "")))
            if waiver:
                waivers.append({
                    "candidate": issue.get("candidate"),
                    "gate": "gate:cross_batch",
                    "message": issue.get("message"),
                    "adjudicated_at": waiver.get("recorded_at"),
                    "adjudicator": waiver.get("adjudicator"),
                    "verdict": waiver.get("result") or waiver.get("verdict"),
                })
                continue
            return _blocked("gate:cross_batch", candidate=issue.get("candidate"),
                            message=issue.get("message"))
        if level == "warning":
            human_items.append(f"cross_batch: {issue.get('message')}")

    # ---- 5. 存疑判定：prose_pilot 字数口径 --------------------------------
    prose_files = sorted(root.glob("review/prose-pilot-report*.json"))
    if not prose_files:
        return _blocked("evidence_missing:prose-pilot-report.json")
    prose_latest = _load_json(prose_files[-1])  # 取最新一份（-v2 等）
    if prose_latest is None:
        return _blocked("evidence_unreadable:prose-pilot-report.json")

    # 字数口径差：style_gate char_count vs prose_pilot chars
    char_gaps: list[str] = []
    if style_files and prose_files:
        prose_latest = _load_json(prose_files[-1])
        for sf in style_files:
            data = _load_json(sf)
            if data is None:
                continue
            for art in data.get("articles") or []:
                if not isinstance(art, dict) or not art.get("title"):
                    continue
                sg_count = int(art.get("char_count", 0) or 0)
                pp_count = _find_prose_chars(prose_latest, str(art.get("title", "")))
                if sg_count and pp_count:
                    diff = abs(sg_count - pp_count) / max(sg_count, pp_count)
                    if diff > CHAR_DIFF_TOLERANCE:
                        char_gaps.append(
                            f"{sf.name}: style_gate={sg_count} prose_pilot={pp_count} 差{diff:.0%}"
                        )
    human_items.extend(char_gaps)

    # ---- editorial-record（协议 v1.0，M2 起为必需） ------------------------
    editorial_files = sorted(root.glob("review/*editorial*")) + sorted(root.glob("evidence/*editorial*"))
    if editorial_files:
        record = _load_json(editorial_files[0])
        if record is None:
            return _blocked("evidence_unreadable:editorial-record")
        try:
            report = evaluate_editorial_record(record, root)
        except Exception as exc:  # noqa: BLE001
            return _blocked("gate:editorial_review", error=str(exc))
        if report.get("verdict") != "PASS":
            return _blocked("gate:editorial_review", editorial_verdict=report.get("verdict"),
                            errors=report.get("errors"))
    else:
        gaps.append(_evidence_gap("editorial-record.json 缺失（协议 v1.0 落地前批次可忽略）"))

    # ---- 收敛 --------------------------------------------------------------
    result: dict = {
        "run_id": run_id,
        "batch_dir": root.name,
        "verdict": None,
        "reason": None,
        "evidence_gaps": gaps,
        "human_judgment_items": human_items,
        "adjudicated_waivers": waivers,
        "publication_authorization": "not_authorized",
    }
    if human_items:
        result.update(_pending("存在存疑项，需人工判定", human_items))
    else:
        result.update(_publishable())
    return result


def _match_adjudication_waiver(root: Path, candidate: str) -> dict | None:
    """读取本批 portfolio-gate-report.json 的控制器豁免注记，candidate 匹配即返回。

    豁免条件（安全限制）：adjudicated=True 且 result 含 confirmed_new_angle / 确认豁免；
    仅匹配同一 candidate。机器尊重人工裁决，但绝不自行创造豁免。
    """
    if not candidate:
        return None
    report_file = root / "portfolio-gate-report.json"
    if not report_file.exists():
        return None
    try:
        report = json.loads(report_file.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — 读不到注记当作无豁免，走原 BLOCKED 路径
        return None
    adj = report.get("controller_adjudication") or {}
    if not isinstance(adj, dict) or adj.get("adjudicated") is not True:
        return None
    result_text = str(adj.get("result", ""))
    if "confirmed_new_angle" not in result_text and "确认豁免" not in result_text:
        return None
    if candidate not in result_text:
        return None
    return adj


def _find_prose_chars(prose: dict | None, title: str) -> int:
    """在 prose-pilot 报告里按标题找字数；找不到返回 0。"""
    if prose is None:
        return 0
    norm = lambda s: re.sub(r"\s+", "", str(s))
    target = norm(title)
    for b in prose.get("batches") or []:
        for art in b.get("articles") or []:
            if isinstance(art, dict) and norm(art.get("title", "")) == target:
                return int(art.get("chars", 0) or 0)
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True, type=Path, help="批次目录 runs/<date>/controlled-NNN")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = evaluate_batch(args.batch)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["verdict"] == PUBLISHABLE else 1


if __name__ == "__main__":
    raise SystemExit(main())
