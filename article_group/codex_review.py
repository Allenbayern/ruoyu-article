"""Codex review adapter for the Ruoyu controlled-production workflow.

This is an evidence-producing sidecar. It never edits artifacts, changes workflow
state, grants publication authority, or replaces deterministic local gates.

Modes:
    normal: Codex native ``review`` using the Luna route.
    l2:    read-only Codex ``exec`` using the Sol route and review schema.

``--review-json PATH`` records a structured review produced by any other agent
harness (for example a dsh subagent): the reviewer command is skipped, the JSON
is stored in the ordinary ``.log`` sidecar, and the same bindings, hashes and
completion checks apply.  This keeps the L2 gate available after the Codex CLI
is retired.  The module and file names are historical identifiers; they are not
a runtime dependency on the Codex CLI.

Canonical independent-review records (2026-09-18, daily-009 复盘): the gate and
the generator engine read ``review/<aid>/independent-review.json`` in the
``article-independent-review-v1`` shape, while this tool's own record is the
``codex-review-contract-1.0`` shape.  Pointing ``--output`` at
``independent-review.json`` (or passing ``--canonical-independent-review``)
makes the tool write the canonical shape directly — ``status=complete`` plus the
full artifact binding — so no reviewer has to hand-copy a record that the
engine would later overwrite with a PENDING placeholder.

Contract enforcement (2026-09-18, B5′): every structured L2 review is validated
against ``schemas/codex-review-contract.json`` (severity ∈ blocker/major/minor,
exact finding keys, no extra keys).  A review that does not satisfy it is
recorded as ``UNVERIFIED`` with ``contract_errors`` — never as a verdict.  And a
``blocker``/``major`` finding can never be recorded as an approve: such a
decision is downgraded to ``needs_changes`` and the change is recorded
(``decision_adjusted_from`` / ``severity_mapping``).

The normal record is explicitly repository code-review evidence.  Its successful
``review_completed`` decision is not an article-independent ``approve``.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from article_group.independent_review import build_independent_review_binding
from article_group.run_contract import REQUIRED_RUN_CONTRACT, is_strict_run_contract


SCHEMA_VERSION = "codex-review-contract-1.0"
DEFAULT_SCHEMA = Path(__file__).resolve().parent.parent / "schemas" / "codex-review-contract.json"
CANONICAL_RECORD_NAME = "independent-review.json"


def _binding_gaps(args: argparse.Namespace) -> list[str]:
    """写 canonical 记录还缺哪些文章链参数（缺了门禁只会把它读成 invalid）。"""

    return [
        flag
        for flag, value in (
            ("--article-id", getattr(args, "article_id", None)),
            ("--artifact-path", getattr(args, "artifact_path", None)),
            ("--body-path", getattr(args, "body_path", None)),
            ("--title-pack-path", getattr(args, "title_pack_path", None)),
        )
        if not (isinstance(value, str) and value.strip())
    ]


def _canonical_target(args: argparse.Namespace, gaps: list[str]) -> bool:
    """这份记录要不要按门禁读的 canonical 契约写。

    - 显式 ``--canonical-independent-review``：意图明确，缺文章链直接报错退出；
    - ``--output`` 文件名就是 canonical 约定名 ``independent-review.json``
      （``final_review`` 的默认路径）：链齐全时按 canonical 写。
    """

    if args.mode != "l2":
        return False
    explicit = bool(getattr(args, "canonical_independent_review", False))
    named = Path(args.output).name == CANONICAL_RECORD_NAME
    if not (explicit or named):
        return False
    if gaps:
        if explicit:
            raise SystemExit(
                "canonical independent-review 记录需要 "
                + "、".join(gaps)
                + "（门禁按文章链逐项核验绑定）"
            )
        return False
    return True


def _display_path(run_root: Path, target: Path) -> str:
    """run 内文件记相对路径，run 外记绝对路径（沿用 run 内其他产物的口径）。"""

    resolved = Path(target).expanduser().resolve()
    root = Path(run_root).expanduser().resolve()
    if resolved.is_relative_to(root):
        return resolved.relative_to(root).as_posix()
    return str(resolved)


def _canonical_record_state(run_root: Path, article_id: str) -> str:
    """门禁读的那份 canonical 记录现在是什么状态。

    ``missing`` / ``placeholder`` / ``finished`` 三态。契约记录里带上它，
    "结论只写在契约记录里、门禁那份还是占位符"就不再是隐形状态
    （2026-09-18，daily-009：正是这个隐形状态让一次 approve 在系统里消失）。
    """

    from article_group.independent_review import is_placeholder_record

    path = Path(run_root) / "review" / article_id / CANONICAL_RECORD_NAME
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "missing"
    return "placeholder" if is_placeholder_record(record) else "finished"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_id(run_root: Path) -> str:
    return run_root.name or "codex-review"


def _write_json(
    path: Path,
    payload: dict[str, Any],
    *,
    run_dir: Path | None = None,
    reason: str = "codex_review",
    force: bool = False,
) -> None:
    """写 JSON：目标在 run 内时走留底通道（留底+记账+封存守门），否则普通写入。"""
    if run_dir is not None:
        from article_group.evidence_write import write_evidence_json

        write_evidence_json(path, payload, run_dir=run_dir, reason=reason, force=force)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(
    path: Path,
    text: str,
    *,
    run_dir: Path | None = None,
    reason: str = "codex_review:log",
    force: bool = False,
) -> None:
    """写评审原文日志：同一口径（它在 run 内时同样是证据）。"""
    if run_dir is not None:
        from article_group.evidence_write import write_evidence

        write_evidence(path, text, run_dir=run_dir, reason=reason, force=force)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _evidence_run(run_root: Path, target: Path) -> Path | None:
    """目标落在 run 内才交给留底通道；写到 run 外的产物不该被封存守门挡。"""
    root = Path(run_root).expanduser().resolve()
    if Path(target).expanduser().resolve().is_relative_to(root):
        return Path(run_root)
    return None


def _build_prompt(args: argparse.Namespace) -> str:
    criteria = args.acceptance or "Review the changed files for correctness, regressions, negative paths, and test coverage."
    return (
        "You are an independent evidence reviewer. Do not modify files, do not publish, "
        "do not merge, and do not authorize any external action. Read the original request, "
        "the repository changes, and the acceptance criteria independently. Report only "
        "evidence-backed findings and coverage gaps.\n\n"
        f"Original request: {args.request}\n"
        f"Acceptance criteria: {criteria}\n"
        f"Run root / artifact context: {args.run_root}\n"
        f"Additional focus: {args.focus or 'none'}\n"
        "Use exact file paths, line numbers where possible, commands, and counterexamples."
    )


def _base_record(args: argparse.Namespace, mode: str, command: list[str]) -> dict[str, Any]:
    record = {
        "schema_version": SCHEMA_VERSION,
        "run_id": _run_id(args.run_root),
        "risk_tier": args.risk,
        "review_mode": mode,
        "original_request": args.request,
        "acceptance_criteria": args.acceptance or "",
        "artifact_context": str(args.run_root),
        "started_at": _utc_now(),
        "command": command,
        "decision": "evidence_insufficient",
        "findings": [],
        "coverage_gaps": ["review_not_completed"],
        "publication_authorization": "not_authorized",
    }
    if mode == "normal":
        record.update(
            {
                "review_kind": "repository_code_review",
                "review_purpose": "code_review_evidence",
                "independent_review_eligible": False,
            }
        )
    else:
        record.update(
            {
                "review_kind": "adversarial_code_review_evidence",
                "review_purpose": "code_review_evidence",
                "independent_review_eligible": False,
            }
        )
    if getattr(args, "base_review", None):
        # L2 增量复核协议（2026-09-16）：--base-review 指向上一轮已归档记录，
        # 本轮声明为 diff-only 复核（只验证改动清单 + 抽查），基线哈希入库留痕。
        base = Path(args.base_review)
        record["scope_mode"] = "diff_only"
        record["base_review"] = str(base)
        if base.exists():
            record["base_review_sha256"] = _sha256(base)
        else:
            record["base_review_missing"] = True
    manifest_path = args.run_root / "batch.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        manifest = None
    if isinstance(manifest, dict) and is_strict_run_contract(manifest):
        for field in REQUIRED_RUN_CONTRACT:
            if field in manifest:
                record[field] = manifest[field]
        if isinstance(manifest.get("run_id"), str) and manifest["run_id"].strip():
            record["created_from_run"] = manifest["run_id"].strip()
    return record


def _parse_l2_output(text: str) -> dict[str, Any] | None:
    for line in reversed(text.splitlines()):
        candidate = line.strip()
        if not candidate.startswith("{"):
            continue
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "decision" in value and "findings" in value:
            return value
    return None


def _load_review_json(text: str) -> dict[str, Any] | None:
    """Parse an externally produced review document.

    Accepts a bare review object, a JSON array whose last object is a review, or
    a CLI transcript that contains a structured review line, mirroring
    ``_parse_l2_output``'s tolerance for surrounding noise.
    """
    stripped = text.strip()
    if not stripped:
        return None
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return _parse_l2_output(text)
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in reversed(value):
            if isinstance(item, dict):
                return item
    return None


CONTRACT_REVIEW_KEYS = ("decision", "scope_reviewed", "findings", "non_findings", "coverage_gaps")
BLOCKING_SEVERITIES = frozenset({"blocker", "major"})
APPROVING_DECISIONS = frozenset({"approve", "approved", "approve-with-notes", "pass"})


def validate_review_contract(review: object, schema_path: str | Path) -> list[str]:
    """按 ``schemas/codex-review-contract.json`` 校验复核 JSON。

    2026-09-18（B5′）：契约里 severity 早就是 blocker/major/minor 三级，但
    ``--review-json`` 路径此前只挑 5 个 key 拷贝，复核员自造
    ``id/category/location/...`` 也无人拦——字段漂移就这样进了记录。现在按契约
    拒收：不合契约的复核只能记成 UNVERIFIED，不能记成结论。

    schema 读不到、jsonschema 不可用都 fail-closed（按"不合契约"处理）。
    """

    try:
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"schema_unavailable:{type(exc).__name__}"]
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as exc:  # pragma: no cover - runtime dependency guard
        return [f"jsonschema_unavailable:{type(exc).__name__}"]
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors: list[str] = []
    for error in sorted(validator.iter_errors(review), key=lambda item: list(item.absolute_path)):
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        errors.append(f"{location}:{error.validator}:{error.message}"[:300])
    return errors[:20]


def severity_decision_adjustment(decision: object, findings: object) -> dict[str, Any] | None:
    """severity → decision 的映射规则（2026-09-18，B5′）。

    有 blocker/major 就是阻断项：复核员即使写了 approve 也不能批准，按 fail-closed
    降级成 needs_changes。minor 不触发降级（daily-009 的 approve 只带 minor）。
    返回 ``None`` 表示不需要改判。
    """

    if not isinstance(findings, list):
        return None
    blocking = sorted(
        {
            str(finding.get("severity"))
            for finding in findings
            if isinstance(finding, Mapping) and str(finding.get("severity")) in BLOCKING_SEVERITIES
        }
    )
    if not blocking:
        return None
    if str(decision or "").strip().lower() not in APPROVING_DECISIONS:
        return None
    return {
        "from": decision,
        "to": "needs_changes",
        "blocking_severities": blocking,
    }


def _apply_l2_contract(
    record: dict[str, Any],
    structured: object,
    schema_path: str | Path,
) -> bool:
    """把一份结构化 L2 复核并入记录；不合契约就 fail-closed 记 UNVERIFIED。

    返回 True 表示复核满足契约并已并入（``exit_code`` 由调用方按各自语义处理）。
    """

    contract_errors = validate_review_contract(structured, schema_path)
    if contract_errors:
        record["error"] = "l2_review_contract_invalid"
        record["contract_errors"] = contract_errors
        record["decision"] = "evidence_insufficient"
        record["status"] = "UNVERIFIED"
        record["coverage_gaps"] = ["l2_review_contract_invalid"]
        return False
    assert isinstance(structured, Mapping)
    for key in CONTRACT_REVIEW_KEYS:
        if key in structured:
            record[key] = structured[key]
    record["coverage_gaps"] = structured.get("coverage_gaps", [])
    record["structured_result"] = True
    adjustment = severity_decision_adjustment(record.get("decision"), record.get("findings"))
    if adjustment:
        record["decision_adjusted_from"] = adjustment["from"]
        record["severity_mapping"] = adjustment
        record["decision"] = adjustment["to"]
        record["coverage_gaps"] = list(record.get("coverage_gaps") or []) + [
            "severity_mapping:blocking_finding_cannot_approve"
        ]
    record["status"] = "PASS" if record.get("decision") == "approve" else "FAIL"
    return True


def run_review(args: argparse.Namespace) -> int:
    external_review = getattr(args, "review_json", None)
    codex = None if external_review is not None else shutil.which("codex")
    if external_review is None and codex is None:
        raise SystemExit(
            "codex executable not found in PATH; pass --review-json to record a review "
            "produced by another agent harness"
        )
    if not args.run_root.exists():
        raise SystemExit(f"run root does not exist: {args.run_root}")
    canonical_gaps = _binding_gaps(args) if args.mode == "l2" else []
    canonical = _canonical_target(args, canonical_gaps)

    if external_review is not None:
        command = ["review-json", str(external_review)]
    elif args.mode == "normal":
        command = [
            codex,
            "review",
            "-c",
            'model="gpt-5.6-luna"',
            "-c",
            'model_reasoning_effort="max"',
            "--uncommitted",
        ]
        if args.base:
            command = [
                codex,
                "review",
                "-c",
                'model="gpt-5.6-luna"',
                "-c",
                'model_reasoning_effort="max"',
                "--base",
                args.base,
            ]
        if args.focus:
            command.append(args.focus)
    else:
        command = [
            codex,
            "exec",
            "-m",
            "gpt-5.6-sol",
            "-c",
            'model_reasoning_effort="high"',
            "-s",
            "read-only",
            "--output-schema",
            str(args.schema),
            _build_prompt(args),
        ]

    record = _base_record(args, args.mode, command)
    if getattr(args, "article_task_id", None):
        record["article_task_id"] = args.article_task_id
    if getattr(args, "article_id", None):
        record["article_id"] = args.article_id
    if getattr(args, "draft_path", None):
        record["draft_path"] = args.draft_path
    if getattr(args, "draft_sha256", None):
        record["draft_sha256"] = args.draft_sha256
    artifact_path = getattr(args, "artifact_path", None) or getattr(args, "draft_path", None)
    body_path = getattr(args, "body_path", None)
    title_pack_path = getattr(args, "title_pack_path", None)
    if artifact_path and body_path and title_pack_path:
        try:
            record.update(
                build_independent_review_binding(
                    args.run_root,
                    artifact_path=artifact_path,
                    body_path=body_path,
                    title_pack_path=title_pack_path,
                    created_from_run=getattr(args, "created_from_run", None)
                    or record.get("created_from_run")
                    or record.get("run_id"),
                )
            )
        except ValueError as exc:
            record["binding_error"] = str(exc)
    else:
        if artifact_path:
            record["artifact_path"] = artifact_path
        if body_path:
            record["body_path"] = body_path
        if title_pack_path:
            record["title_pack_path"] = title_pack_path
        if getattr(args, "created_from_run", None):
            record["created_from_run"] = args.created_from_run
    # The independent-review contract keeps the historical draft fields for
    # the body under review, while the strict binding separately records the
    # final delivery artifact.  Populate the draft identity from the same
    # bound files when the CLI caller supplied only the new fields.
    if artifact_path or body_path:
        record.setdefault("draft_path", body_path or artifact_path)
        if not record.get("draft_sha256"):
            if body_path and record.get("body_sha256"):
                record["draft_sha256"] = record["body_sha256"]
            elif artifact_path and record.get("artifact_sha256"):
                record["draft_sha256"] = record["artifact_sha256"]
    record["attempt"] = getattr(args, "attempt", 1) or 1
    if getattr(args, "l2_required", False):
        record["l2_required"] = True
        record["l2_risk_basis"] = args.l2_risk_basis or ""
    started = datetime.now(timezone.utc)
    run_kwargs = {
        "cwd": args.repo,
        "text": True,
        "capture_output": True,
        "check": False,
        "env": os.environ.copy(),
    }
    if getattr(args, "timeout_seconds", None):
        run_kwargs["timeout"] = args.timeout_seconds
    external_text: str | None = None
    if external_review is not None:
        completed = None
        try:
            external_text = external_review.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            record["error"] = f"review_json_unreadable:{exc}"
            external_text = ""
    else:
        try:
            completed = subprocess.run(command, **run_kwargs)
        except subprocess.TimeoutExpired as exc:
            record["error"] = f"codex_review_timeout:{exc}"
            record["status"] = "UNVERIFIED"
            record["decision"] = "timeout"
            record["coverage_gaps"] = ["review_timeout"]
            record["timeout_reason"] = "review_deadline_exceeded"
            record["next_step"] = "resume_single_article" if record.get("article_task_id") else "resume_review"
            record["scope"] = "single_article" if record.get("article_task_id") else "batch"
            completed = None
        except OSError as exc:
            record["error"] = f"codex_invocation_failed:{exc}"
            completed = None

    output = external_text if external_text is not None else ("" if completed is None else (completed.stdout + completed.stderr))
    output_path = args.output.with_suffix(".log")
    _write_text(
        output_path, output,
        run_dir=_evidence_run(args.run_root, output_path),
        reason="codex_review:log", force=bool(getattr(args, "force", False)),
    )
    record["output_path"] = str(output_path)
    record["output_sha256"] = _sha256(output_path)
    record["finished_at"] = _utc_now()
    record["duration_seconds"] = round((datetime.now(timezone.utc) - started).total_seconds(), 3)

    if completed is not None:
        record["exit_code"] = completed.returncode
        if args.mode == "l2":
            structured = _parse_l2_output(output)
            if structured is not None:
                if not _apply_l2_contract(record, structured, args.schema):
                    record["exit_code"] = 1
            else:
                record["error"] = "l2_structured_result_missing"
        else:
            record["decision"] = "review_completed" if completed.returncode == 0 else "review_failed"
            record["status"] = "PASS" if completed.returncode == 0 else "FAIL"
            record["coverage_gaps"] = [] if completed.returncode == 0 else ["codex_review_nonzero_exit"]
    elif external_review is not None:
        structured = _load_review_json(output)
        if args.mode == "l2":
            if structured is None or "decision" not in structured or "findings" not in structured:
                record["error"] = "l2_structured_result_missing"
                record["decision"] = "evidence_insufficient"
                record["status"] = "UNVERIFIED"
                record["coverage_gaps"] = ["l2_structured_result_missing"]
                record["exit_code"] = 1
            elif _apply_l2_contract(record, structured, args.schema):
                record["exit_code"] = 0
                record["review_source"] = "external_review_json"
                record["review_evidence_path"] = _display_path(args.run_root, external_review)
            else:
                record["exit_code"] = 1
                record["review_source"] = "external_review_json"
                record["review_evidence_path"] = _display_path(args.run_root, external_review)
        else:
            decision = structured.get("decision") if structured else None
            if not isinstance(decision, str) or not decision.strip():
                decision = "review_completed" if structured is not None else "review_input_unreadable"
            record["decision"] = decision
            record["status"] = "PASS" if decision == "review_completed" else "FAIL"
            if structured is not None:
                for key in ("findings", "non_findings", "coverage_gaps"):
                    if key in structured:
                        record[key] = structured[key]
                record["coverage_gaps"] = structured.get("coverage_gaps", [])
                record["review_source"] = "external_review_json"
                record["exit_code"] = 0 if record["status"] == "PASS" else 1
            else:
                record["coverage_gaps"] = ["review_json_invalid"]
                record["exit_code"] = 1

    # 2026-09-17：标题包冻结闸门。L2 只能绑定"已冻结且未被改动"的标题包；
    # 不满足时不得记 approve（daily-008 的旧 approve 正是被手工 rebind 保住的）。
    if args.mode == "l2":
        from article_group.title_freeze import BLOCKING_STATUSES, check as _title_freeze_check

        _aid = str(getattr(args, "article_id", "") or "").strip()
        if _aid:
            freeze_report = _title_freeze_check(args.run_root, _aid)
            record["title_freeze_status"] = freeze_report["status"]
            record["title_freeze_reason"] = freeze_report.get("reason", "")
            if freeze_report.get("title_pack_sha256"):
                record["title_pack_sha256"] = freeze_report["title_pack_sha256"]
            if freeze_report["status"] in BLOCKING_STATUSES and not getattr(
                args, "allow_unfrozen_title", False
            ):
                record["title_freeze_violation"] = freeze_report
                # 只拦"通过"：UNVERIFIED/未产出结果要保留原样，
                # 否则会掩盖"复核没跑成"与"复核判不通过"的区别（既有测试守这条）。
                if str(record.get("decision") or "") in {"approve", "approve-with-notes"}:
                    record["decision"] = "needs_changes"
                    record["status"] = "FAIL"
                    record["coverage_gaps"] = list(record.get("coverage_gaps") or []) + [
                        f"title_freeze:{freeze_report['status']}"
                    ]
    if canonical:
        from article_group.independent_review import canonicalize_independent_review_record

        record = canonicalize_independent_review_record(
            record,
            article_id=args.article_id,
            article_task_id=getattr(args, "article_task_id", None),
            run_root=args.run_root,
            status="complete" if record.get("structured_result") is True else "UNVERIFIED",
        )
    elif str(getattr(args, "article_id", "") or "").strip():
        # 只写契约记录时，如实标注门禁那份 canonical 记录的状态；这次结论若只落在
        # 契约记录里而 canonical 还是占位符，就在产物与 stderr 里同时可见。
        aid = str(args.article_id).strip()
        state = _canonical_record_state(Path(args.run_root), aid)
        record["canonical_record_state"] = state
        if state != "finished" and record.get("decision") in {
            "approve",
            "approved",
            "approve-with-notes",
        }:
            print(
                f"注意：门禁读的 review/{aid}/{CANONICAL_RECORD_NAME} 是 {state}；"
                f"本次 approve 只写在这份契约记录里。"
                f"加 --canonical-independent-review 或把 --output 指到 "
                f"review/{aid}/{CANONICAL_RECORD_NAME} 重录一次。",
                file=sys.stderr,
            )
    elif canonical_gaps and Path(args.output).name == CANONICAL_RECORD_NAME:
        # 输出名暗示 canonical，但没有文章链 —— 只能按契约形状写；不假装写成了
        # canonical 记录，把缺的参数记进产物并告知（门禁会把这份读成 invalid）。
        record["canonical_record_incomplete"] = canonical_gaps
        print(
            "注意：--output 是 canonical 约定名独立复核记录，但缺少 "
            + "、".join(canonical_gaps)
            + "；本份按契约形状写，门禁会读成 invalid。补齐文章链后重录。",
            file=sys.stderr,
        )
    _write_json(
        args.output, record,
        run_dir=_evidence_run(args.run_root, args.output),
        reason=f"codex_review:{args.mode}", force=bool(getattr(args, "force", False)),
    )
    print(json.dumps({"output": str(args.output), "exit_code": record.get("exit_code"), "decision": record["decision"]}, ensure_ascii=False))
    if record.get("contract_errors"):
        print(
            "复核 JSON 不合契约，已按 UNVERIFIED 记录（不构成结论）："
            + "；".join(str(error) for error in record["contract_errors"][:5]),
            file=sys.stderr,
        )
    return 0 if record.get("exit_code") == 0 and record["decision"] not in {"evidence_insufficient", "review_failed"} else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Codex as an evidence-producing review sidecar, or record a review produced by another agent harness."
    )
    parser.add_argument("--mode", choices=("normal", "l2"), required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--acceptance")
    parser.add_argument("--focus")
    parser.add_argument("--base")
    parser.add_argument("--risk", choices=("L0", "L1", "L2"), default="L1")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--timeout-seconds", type=float)
    parser.add_argument("--article-task-id")
    parser.add_argument("--article-id")
    parser.add_argument("--draft-path")
    parser.add_argument("--draft-sha256")
    parser.add_argument("--artifact-path")
    parser.add_argument("--body-path")
    parser.add_argument("--title-pack-path")
    parser.add_argument("--created-from-run")
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--l2-required", action="store_true")
    parser.add_argument("--l2-risk-basis", default="")
    parser.add_argument(
        "--base-review",
        type=Path,
        help="上一轮已归档的 L2 记录：声明本轮为 diff-only 增量复核并记录基线哈希。",
    )
    parser.add_argument(
        "--allow-unfrozen-title",
        action="store_true",
        help="显式放行未冻结的标题包（默认禁止；放行事实会写进 L2 记录）",
    )
    parser.add_argument(
        "--review-json",
        type=Path,
        help="Record a structured review JSON produced by another agent harness instead of invoking the Codex CLI.",
    )
    parser.add_argument(
        "--canonical-independent-review",
        action="store_true",
        help=(
            "按门禁读的 article-independent-review-v1 契约写这份记录"
            "（status=complete；输出名是 independent-review.json 时自动生效）"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="run 已封存时仍写入复核记录与日志（controller 决定；走留底+记账）",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    from article_group.evidence_write import RunSealedError

    try:
        return run_review(args)
    except RunSealedError as exc:  # 封存拒绝要给一句人话，不要 traceback
        print(f"codex_review 拒绝写入：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
