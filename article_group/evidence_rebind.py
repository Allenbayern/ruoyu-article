"""evidence_rebind: 交付内容一变，依赖它的 approve 必须失效（而不是被重绑保住）。

为什么需要（daily-008 复盘）：
引擎对"已完成的复核记录"有保护（不回写 PENDING 占位，防止覆盖 L2 权威产物），
于是内容改稿后，记录里的 artifact_sha256 / body_sha256 / title_pack_sha256 会
与磁盘不一致。daily-008 当时的处理是跑 `sync_independent_review_008.py` 把这些
哈希**改成当前文件的哈希**——approve 就这样被保住了，哈希绑定形同虚设。

本模块把方向反过来：检测到不一致就**判旧证据失效**（stale），保留原值供审计，
并把记录退回待复核状态，交由引擎重建 PENDING 记录、重新走 L2。它不做任何
"以新哈希续用旧结论"的操作。

边界：只改复核/签字记录的失效状态与原因；不写任何发布授权字段，也不动交付文件。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "evidence-rebind-v1"
REPORT_NAME = "evidence-rebind-report.json"

# 绑定字段 → 对应的当前文件
BINDINGS: tuple[tuple[str, str], ...] = (
    ("artifact_sha256", "delivery/{aid}/delivery.md"),
    ("markdown_sha256", "delivery/{aid}/delivery.md"),
    ("reviewed_artifact_sha256", "delivery/{aid}/delivery.md"),
    ("body_sha256", "drafts/{aid}/body_draft.md"),
    ("draft_sha256", "drafts/{aid}/body_draft.md"),
    ("title_pack_sha256", "review/{aid}/title-pack.json"),
)

# 已通过的结论字段：只有这些需要被失效
APPROVING_DECISIONS = {"approve", "approve-with-notes", "accept", "accepted"}


def _now() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _load(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def dependent_records(run_dir: Path, aid: str) -> list[Path]:
    """会被交付内容改写而失效的记录清单。"""
    return [
        run_dir / "review" / aid / "independent-review.json",
        run_dir / "review" / aid / "codex-l2-review.json",
        run_dir / "review" / aid / "source-stripped-readability.json",
        run_dir / "review" / "attestation" / f"{aid}.human.json",
    ]


def _is_approving(record: Mapping[str, Any]) -> bool:
    decision = str(record.get("decision") or "").lower()
    status = str(record.get("status") or "").lower()
    return decision in APPROVING_DECISIONS or status in {"complete", "pass"}


def _stale_patch(path: Path, record: Mapping[str, Any], mismatches: list[dict[str, str]]) -> dict[str, Any]:
    patched = dict(record)
    patched.setdefault("superseded", {})
    if isinstance(patched["superseded"], dict):
        patched["superseded"].update({
            "decision": record.get("decision"),
            "status": record.get("status"),
            "sha256": {item["field"]: item["recorded"] for item in mismatches},
            "superseded_at": _now(),
        })
    patched["status"] = "PENDING"
    if str(record.get("decision") or "").lower() in APPROVING_DECISIONS:
        patched["decision"] = "human_review_required"
    patched["stale"] = True
    patched["stale_reason"] = "delivery_or_title_changed:" + ",".join(
        f"{item['field']}" for item in mismatches
    )
    patched["stale_since"] = _now()
    patched["stale_fields"] = mismatches
    patched["next_step"] = "rereview_after_content_change"
    patched["publication_authorization"] = "not_authorized"
    return patched


def reconcile(run_dir: str | Path, *, apply: bool = False, force: bool = False) -> dict[str, Any]:
    """比对交付/草稿/标题包哈希与依赖记录；apply=True 时把 approve 判为失效。"""
    root = Path(run_dir)
    articles = sorted(
        path.parent.name for path in (root / "delivery").glob("*/delivery.md")
    ) if (root / "delivery").is_dir() else []
    changes: list[dict[str, Any]] = []
    stale_records: list[dict[str, Any]] = []
    for aid in articles:
        for record_path in dependent_records(root, aid):
            record = _load(record_path)
            if record is None:
                continue
            mismatches: list[dict[str, str]] = []
            for field, template in BINDINGS:
                recorded = record.get(field)
                if not isinstance(recorded, str) or not recorded:
                    continue
                current = sha256_file(root / template.format(aid=aid))
                if current and current != recorded:
                    mismatches.append({"field": field, "recorded": recorded, "current": current,
                                       "path": template.format(aid=aid)})
            if not mismatches:
                continue
            entry = {
                "aid": aid,
                "record": str(record_path.relative_to(root)),
                "approving": _is_approving(record),
                "mismatches": mismatches,
            }
            changes.append(entry)
            if _is_approving(record):
                patched = _stale_patch(record_path, record, mismatches)
                stale_records.append(entry)
                if apply:
                    from article_group.evidence_write import write_evidence_json

                    write_evidence_json(record_path, patched, run_dir=root,
                                        reason="evidence_rebind:stale_record", force=force)
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_dir": str(root),
        "applied": apply,
        "checked_at": _now(),
        "articles": articles,
        "changes": changes,
        "stale_records": [entry["record"] for entry in stale_records],
        "note": "检测到不一致时把 approve 判为失效并退回待复核；不会用新哈希续用旧结论。",
        "publication_authorization": "not_authorized",
    }
    if apply:
        from article_group.evidence_write import write_evidence_json

        write_evidence_json(root / "review" / REPORT_NAME, report, run_dir=root,
                            reason="evidence_rebind:report", force=force)
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m article_group.evidence_rebind",
        description="交付变更 → 依赖它的 approve 自动失效（默认 dry-run）",
    )
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="真正写入失效状态与报告")
    parser.add_argument("--force", action="store_true",
                        help="在已收尾的 run 上强制应用（默认拒绝改写封存证据）")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="存在失效记录时以非零码退出")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.apply and not getattr(args, "force", False):
        from article_group.run_state import closed_reason

        closed = closed_reason(args.run_root)
        if closed:
            print(f"拒绝执行：run 已收尾（{closed}）。加 --force 才会改写封存证据。", file=sys.stderr)
            return 2
    report = reconcile(args.run_root, apply=args.apply, force=getattr(args, "force", False))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        mode = "已应用" if report["applied"] else "dry-run"
        print(f"[{mode}] 文章 {len(report['articles'])} 篇 | 不一致记录 {len(report['changes'])} | "
              f"判为失效 {len(report['stale_records'])}")
        for entry in report["changes"]:
            fields = ",".join(item["field"] for item in entry["mismatches"])
            flag = "stale" if entry["approving"] else "info"
            print(f"  [{flag}] {entry['aid']} {entry['record']}: {fields}")
    if args.strict and report["stale_records"]:
        return 1
    return 0


__all__ = [
    "SCHEMA_VERSION",
    "REPORT_NAME",
    "BINDINGS",
    "APPROVING_DECISIONS",
    "dependent_records",
    "reconcile",
    "sha256_file",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
