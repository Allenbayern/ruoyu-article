"""Run-level gate wiring shared by daily generators (2026-09-15).

Three institutional gates, no silent skips:

- **task-hierarchy 1.0 contract** (`article_task_v1.validate_task_hierarchy_run`)
  — blocking: a failing contract aborts the run with exit 1.
- **claim↔source provenance** (`claim_source_check.check_run_material_packs`)
  — blocking: every material-pack fact must be anchorable in its declared
  source's captured artifact.
- **四阶段复核协议** (`editorial_review.evaluate_editorial_record`)
  — blocking: BLOCKED/FAIL records enter evidence_intake; upstream stop
  requires downstream not_run (enforced inside the evaluator).
- **independent_review 内容阻塞检查** — a completed L2 decision that is not
  ``approve*`` blocks the run ("复核跑完了"≠通过)；pending 属治理栏不阻断。
- **git_hygiene infra readiness** — a recorded snapshot of `git ls-files`
  against the required infrastructure paths; commit-level ``daily_commit``
  mode stays a commit-time check.
- **compliance_gate（五道门）** — pool-aware: pools without ``social``
  candidates record explicit ``not_run`` + reason; pools with social
  candidates run the real five-gates enforcement (hard errors block,
  keyword cross-check warnings are aid only). Declaration shape:
  `templates/five-gates-declaration.md`.

Generators call :func:`run_all_gates` with their own ``write_json`` writer
(rooted at the run dir), e.g. ``run_real_daily_005.gates()``.
"""
from __future__ import annotations

from collections.abc import Mapping
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from .article_task_v1 import validate_task_hierarchy_run
from .claim_source_check import check_run_material_packs
from .compliance_gate import crosscheck_pool_five_gates, validate_pool_five_gates
from .editorial_gate import build_editorial_gate
from .editorial_review import evaluate_editorial_record
from .git_hygiene import validate_infra_ready

COMPLIANCE_GATE_REASON = (
    "社会话题五道门（five_gates）仅在 social_topic 题材启用；本期日更为影视制作"
    "题材（craft/relationship），五道门不适用。按 Vault 边界不做静默跳过："
    "显式记录 not_run 及原因。"
)

WriteFn = Callable[[str, object], None]


def build_task_hierarchy_report(run_root: str | Path) -> dict[str, Any]:
    """Run the real 1.0 parent/child contract gate over a run dir."""
    return validate_task_hierarchy_run(Path(run_root))


def build_git_hygiene_snapshot() -> dict[str, Any]:
    """Snapshot repo infrastructure readiness (module never runs git itself)."""
    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    missing = validate_infra_ready(tracked)
    return {
        "schema_version": "git-hygiene-v1",
        "mode": "infra_ready",
        "tracked_paths_count": len(tracked),
        "missing": missing,
        "pass": not missing,
        "note": "commit 级 daily_commit 模式由提交前检查执行；run 内只记录仓库基础设施就绪快照",
        "publication_authorization": "not_authorized",
    }


def build_compliance_not_run_record() -> dict[str, Any]:
    """Explicit not_run record for the social-topic five gates."""
    return {
        "schema_version": "compliance-gate-v1",
        "full_gate": "not_run",
        "full_gate_reason": COMPLIANCE_GATE_REASON,
        "publication_authorization": "not_authorized",
    }


def build_compliance_gate_record(pool: Mapping[str, Any] | None) -> dict[str, Any]:
    """Compliance gate record for a candidate pool.

    - Pool missing or contains no ``topic_type: social`` candidate → explicit
      ``not_run`` + reason (film-daily lane; never silently skipped).
    - Pool contains social candidates → real five-gates enforcement via
      ``validate_pool_five_gates`` (hard errors block) plus keyword
      cross-check warnings (aid only, never blocking).
    """
    if pool is None:
        return {
            "schema_version": "compliance-gate-v1",
            "full_gate": "not_run",
            "full_gate_reason": (
                COMPLIANCE_GATE_REASON + "（候选池缺失，未做社会话题判定）"
            ),
            "publication_authorization": "not_authorized",
        }
    candidates = pool.get("candidates") if isinstance(pool, Mapping) else None
    social = [
        candidate
        for candidate in candidates
        if isinstance(candidate, Mapping)
        and str(candidate.get("topic_type", "")).strip().lower() == "social"
    ] if isinstance(candidates, list) else []
    if not social:
        return build_compliance_not_run_record()
    errors = validate_pool_five_gates(pool)
    warnings = crosscheck_pool_five_gates(pool)
    return {
        "schema_version": "compliance-gate-v1",
        "full_gate": "run",
        "mode": "social_topic",
        "social_candidates": len(social),
        "pass": not errors,
        "errors": errors,
        "warnings": warnings,
        "publication_authorization": "not_authorized",
    }


def _load_json_mapping(path: Path) -> Mapping[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, Mapping) else None


def build_editorial_protocol_report(run_root: str | Path) -> dict[str, Any]:
    """Evaluate every article's four-stage editorial record (protocol v1.0).

    BLOCKED/FAIL records (or missing records) are hard errors: the run may
    not claim editorial PASS from a self-declared record.  ``not_run``
    propagation after a stopping stage is enforced inside
    ``evaluate_editorial_record``.
    """
    root = Path(run_root)
    articles: list[dict[str, Any]] = []
    errors: list[str] = []
    paths = sorted((root / "task-hierarchy").glob("article-task-*.json"))
    if not paths:
        errors.append("missing:article_tasks")
    for path in paths:
        task = _load_json_mapping(path)
        if task is None:
            errors.append(f"invalid:article_task:{path.name}")
            continue
        aid = str(task.get("article_id") or path.stem)
        record = _load_json_mapping(root / f"review/{aid}/editorial-review-record.json")
        if record is None:
            errors.append(f"editorial_record_missing:{aid}")
            articles.append({"article_id": aid, "verdict": "FAIL", "errors": ["editorial_record_missing"]})
            continue
        report = evaluate_editorial_record(dict(record), root)
        articles.append({"article_id": aid, **report})
        if report.get("verdict") != "PASS":
            errors.append(f"{aid}:verdict:{report.get('verdict')}")
    return {
        "schema_version": "editorial-protocol-v1",
        "pass": not errors,
        "errors": sorted(set(errors)),
        "articles": articles,
        "publication_authorization": "not_authorized",
    }


def build_independent_review_gate(run_root: str | Path) -> dict[str, Any]:
    """Enforce the content-blocking rule for completed L2 reviews.

    A completed decision that is not ``approve*`` is a content blocker
    (gate:independent_review) — "复核跑完了但没通过"不能放行。Pending /
    human_review_required / unverified 属治理栏，不阻断（run 在 L2 前交付）。
    """
    root = Path(run_root)
    articles: list[dict[str, Any]] = []
    errors: list[str] = []
    paths = sorted((root / "task-hierarchy").glob("article-task-*.json"))
    if not paths:
        errors.append("missing:article_tasks")
    for path in paths:
        task = _load_json_mapping(path)
        if task is None:
            errors.append(f"invalid:article_task:{path.name}")
            continue
        aid = str(task.get("article_id") or path.stem)
        record = _load_json_mapping(root / f"review/{aid}/independent-review.json")
        if record is None:
            errors.append(f"independent_review_record_missing:{aid}")
            articles.append({"article_id": aid, "decision": None, "blocking": True})
            continue
        decision = str(record.get("decision") or record.get("status") or "pending")
        blocking = decision and not decision.lower().startswith(
            ("approve", "pending", "unverified", "timeout", "human_review")
        )
        if blocking:
            errors.append(f"gate:independent_review:{aid}:decision:{decision}")
        articles.append({"article_id": aid, "decision": decision, "blocking": blocking})
    return {
        "schema_version": "independent-review-gate-v1",
        "pass": not errors,
        "errors": sorted(set(errors)),
        "articles": articles,
        "publication_authorization": "not_authorized",
    }


def build_topic_five_questions_gate(run_root: str | Path) -> dict[str, Any]:
    """Enforce the five-question topic preflight (2026-09-16 user-approved).

    Structural failures (missing/invalid five-question fields on a selected
    candidate) block the run; quality warnings are reported but never block.
    Reads the artifact written by the generator's candidates() stage.
    """
    root = Path(run_root)
    report = _load_json_mapping(root / "review" / "topic-five-questions.json")
    if report is None:
        return {
            "schema_version": "topic-five-questions-gate-v1",
            "pass": False,
            "errors": ["missing:topic_five_questions"],
            "warnings": [],
            "publication_authorization": "not_authorized",
        }
    errors = [str(e) for e in report.get("errors", [])]
    return {
        "schema_version": "topic-five-questions-gate-v1",
        "pass": not errors,
        "errors": sorted(set(errors)),
        "warnings": sorted({str(w) for w in report.get("warnings", [])}),
        "publication_authorization": "not_authorized",
    }


def build_assertion_coverage_gate(
    run_root: str | Path,
    *,
    write_article_reports: WriteFn | None = None,
) -> dict[str, Any]:
    """读者面断言 ↔ 账本覆盖的确定性门禁（2026-09-18，B1）。

    为什么需要（daily-008 复盘 → daily-009 复核）：008 的账本 46 条事实全部锚定、
    机器门禁全绿，L2 第一轮仍判两条 major——读者面写了「十几年过去」与
    「《让子弹飞》的台词还在被引用」，账本里没有对应条目；这两类断言正好从
    逐字引号比对与 LLM 抽查之间漏过去。确定性检查（
    :mod:`article_group.assertion_ledger_coverage`）当时就写好了，但只挂在手工脚本
    ``scripts/ledger_coverage_precheck.py`` 上、**不阻断**，于是复核时谁也拦不住。

    现在它进门禁：error 级缺口（时间跨度/受众行为）阻断，warning 级（数字/引号）
    只记录。``write_article_reports`` 给了写入器时，逐篇报告落到
    ``review/<aid>/assertion-coverage.json`` 作为证据。
    """

    from article_group.assertion_ledger_coverage import check_coverage

    root = Path(run_root)
    articles: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    for path in sorted((root / "task-hierarchy").glob("article-task-*.json")):
        task = _load_json_mapping(path) or {}
        aid = str(task.get("article_id") or path.stem.removeprefix("article-task-"))
        report = check_coverage(root, aid)
        article_errors = [str(error) for error in report.get("errors", [])]
        if report.get("status") == "no_delivery":
            article_errors.append("delivery_missing")
        articles.append(
            {
                "article_id": aid,
                "status": report.get("status"),
                "ledger_entries": report.get("ledger_entries", 0),
                "assertions": report.get("assertions", 0),
                "errors": article_errors,
                "warnings": [str(w) for w in report.get("warnings", [])],
            }
        )
        errors.extend(f"{aid}:{error}" for error in article_errors)
        warnings.extend(f"{aid}:{warning}" for warning in report.get("warnings", []))
        if write_article_reports is not None:
            write_article_reports(f"review/{aid}/assertion-coverage.json", dict(report))
    return {
        "schema_version": "assertion-coverage-gate-v1",
        "pass": not errors,
        "checked_articles": len(articles),
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "articles": articles,
        "note": "确定性检查：时间跨度/受众行为缺口阻断（L2 判 major 的两类），数字/引号记录不阻断。",
        "publication_authorization": "not_authorized",
    }


def run_all_gates(
    run_root: str | Path,
    write_json: WriteFn,
    *,
    fail_on_error: bool = True,
    editorial_declarations: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write the three gate artifacts into the run and return a summary.

    ``write_json(relative_path, value)`` is the generator's own writer,
    rooted at the run directory.  When ``fail_on_error`` is true, a failing
    task-hierarchy contract prints the report to stderr and exits 1.
    """
    hierarchy_report = build_task_hierarchy_report(run_root)
    write_json("task-hierarchy-validation-report.json", hierarchy_report)

    claim_report = check_run_material_packs(run_root)
    write_json("review/gates/claim-source-check.json", claim_report)

    editorial_report = build_editorial_protocol_report(run_root)
    write_json("review/gates/editorial-protocol.json", editorial_report)

    independent_report = build_independent_review_gate(run_root)
    write_json("review/gates/independent-review.json", independent_report)

    hygiene = build_git_hygiene_snapshot()
    write_json("review/gates/git-hygiene.json", hygiene)

    pool = _load_json_mapping(Path(run_root) / "candidate-pool.json")
    compliance = build_compliance_gate_record(pool)
    write_json("review/gates/compliance-gate.json", compliance)

    five_questions = build_topic_five_questions_gate(run_root)
    write_json("review/gates/topic-five-questions.json", five_questions)

    # B1（2026-09-18）：正文断言 ↔ 账本覆盖进门前置成门禁（逐篇报告一并留底）。
    assertion_report = build_assertion_coverage_gate(run_root, write_article_reports=write_json)
    write_json("review/gates/assertion-coverage.json", assertion_report)

    # 编辑质量门禁（2026-09-21，daily-010 编读复盘）：读者面结构与承诺兑现的机械判定。
    # 默认只报警；spec 用 EDITORIAL_DECLARATIONS 逐篇声明才硬拦（fail-closed）。
    editorial_quality = build_editorial_gate(run_root, editorial_declarations)
    write_json("review/gates/editorial-gate.json", editorial_quality)

    compliance_failed = compliance.get("full_gate") == "run" and not compliance.get("pass")
    if fail_on_error and (
        not hierarchy_report["pass"]
        or not claim_report["pass"]
        or not editorial_report["pass"]
        or not independent_report["pass"]
        or not five_questions["pass"]
        or not assertion_report["pass"]
        or not editorial_quality["pass"]
        or compliance_failed
    ):
        payload = {
            "task_hierarchy_gate": hierarchy_report,
            "claim_source_check": claim_report,
            "editorial_protocol": editorial_report,
            "independent_review_gate": independent_report,
            "topic_five_questions": five_questions,
            "assertion_coverage_gate": assertion_report,
            "compliance_gate": compliance,
        }
        print(
            "RUN GATES FAILED:\n"
            + json.dumps(payload, ensure_ascii=False, indent=2),
            file=sys.stderr,
        )
        sys.exit(1)
    return {
        "task_hierarchy_contract": "pass" if hierarchy_report["pass"] else "fail",
        "claim_source_provenance": "pass" if claim_report["pass"] else "fail",
        "editorial_protocol": "pass" if editorial_report["pass"] else "fail",
        "independent_review": "pass" if independent_report["pass"] else "fail",
        "topic_five_questions": "pass" if five_questions["pass"] else "fail",
        "assertion_coverage": "pass" if assertion_report["pass"] else "fail",
        "git_hygiene_infra": "pass" if hygiene["pass"] else "fail",
        "compliance_gate": (
            "not_run"
            if compliance.get("full_gate") == "not_run"
            else ("pass" if compliance.get("pass") else "fail")
        ),
        "compliance_gate_reason": COMPLIANCE_GATE_REASON,
    }


__all__ = [
    "COMPLIANCE_GATE_REASON",
    "build_assertion_coverage_gate",
    "build_compliance_gate_record",
    "build_compliance_not_run_record",
    "build_editorial_protocol_report",
    "build_git_hygiene_snapshot",
    "build_independent_review_gate",
    "build_task_hierarchy_report",
    "build_topic_five_questions_gate",
    "run_all_gates",
]
