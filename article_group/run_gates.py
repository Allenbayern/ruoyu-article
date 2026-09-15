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


def run_all_gates(
    run_root: str | Path,
    write_json: WriteFn,
    *,
    fail_on_error: bool = True,
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

    compliance_failed = compliance.get("full_gate") == "run" and not compliance.get("pass")
    if fail_on_error and (
        not hierarchy_report["pass"]
        or not claim_report["pass"]
        or not editorial_report["pass"]
        or not independent_report["pass"]
        or compliance_failed
    ):
        payload = {
            "task_hierarchy_gate": hierarchy_report,
            "claim_source_check": claim_report,
            "editorial_protocol": editorial_report,
            "independent_review_gate": independent_report,
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
    "build_compliance_gate_record",
    "build_compliance_not_run_record",
    "build_editorial_protocol_report",
    "build_git_hygiene_snapshot",
    "build_independent_review_gate",
    "build_task_hierarchy_report",
    "run_all_gates",
]
