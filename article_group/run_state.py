"""run_state: 判定一个 run 是否已收尾/已封存，用于保护封存证据。

判据优先级：
1. **`SEALED` 标记**（2026-09-17 新增，close_out 收尾时写入）：显式、可读、含
   收尾时间与验收人，比从 batch.json 推断更难误判；
2. batch.json 任一文章 `gate_status.controller_acceptance == accepted`；
3. 存在 `review/attestation/*.human.json` 签字。

为什么需要：
daily-008 收尾后（当时还没有 SEALED 标记），为演示扩展后的预检工具直接在已收尾
run 上重跑 `ledger_coverage_precheck.py`，覆盖了 `review/art-001/
ledger-coverage-precheck.json`（10:20 那版，无备份、不可还原）。
写证据的工具必须能一眼看出"这是封存证据"，默认拒绝写入。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SEALED_NAME = "SEALED"
SEALED_SCHEMA_VERSION = "run-sealed-v1"


def _load(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def sealed_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / SEALED_NAME


def sealed_record(run_dir: str | Path) -> Mapping[str, Any]:
    return _load(sealed_path(run_dir))


def seal(
    run_dir: str | Path,
    *,
    identity: str,
    ref: str = "",
    articles: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """写入 SEALED 标记（收尾的最后一步）；幂等：已封存则返回原记录。"""
    root = Path(run_dir)
    existing = sealed_record(root)
    if existing:
        return {**existing, "status": "already_sealed"}
    payload: dict[str, Any] = {
        "schema_version": SEALED_SCHEMA_VERSION,
        "sealed_at": _dt.datetime.now().astimezone().replace(microsecond=0).isoformat(),
        "sealed_by": identity,
        "seal_ref": ref or "controller 明确验收通过后收尾",
        "articles": [dict(item) for item in articles],
        "note": "封存证据：写证据的工具在未显式 force 时必须拒绝改动本 run。"
                "演示/复现请用副本（scripts/run_sandbox.py）。",
        "publication_authorization": "not_authorized",
    }
    path = sealed_path(root)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**payload, "status": "sealed"}


def sealed_reason(run_dir: str | Path) -> str:
    """已封存时返回原因（供报错信息用），未封存返回空串。"""
    record = sealed_record(run_dir)
    if not record:
        return ""
    return f"sealed_at={record.get('sealed_at', '?')},by={record.get('sealed_by', '?')}"


def is_sealed(run_dir: str | Path) -> bool:
    return bool(sealed_reason(run_dir))


def closed_reason(run_dir: str | Path) -> str:
    """已收尾/已封存时返回原因，否则返回空串。"""
    sealed = sealed_reason(run_dir)
    if sealed:
        return sealed
    root = Path(run_dir)
    batch = _load(root / "batch.json")
    accepted = [
        str(article.get("article_id"))
        for article in (batch.get("articles") or [])
        if isinstance(article, Mapping)
        and str((article.get("gate_status") or {}).get("controller_acceptance", "")).lower() == "accepted"
    ]
    if accepted:
        return "controller_acceptance=accepted:" + ",".join(accepted)
    attestation_dir = root / "review" / "attestation"
    if attestation_dir.is_dir() and any(attestation_dir.glob("*.human.json")):
        return "human_attestation_present"
    return ""


def run_is_closed(run_dir: str | Path) -> bool:
    return bool(closed_reason(run_dir))


def delivery_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def seal_articles(run_dir: str | Path) -> list[dict[str, Any]]:
    """收集要写进 SEALED 的文章与交付哈希。"""
    root = Path(run_dir)
    delivery = root / "delivery"
    if not delivery.is_dir():
        return []
    return [
        {"article_id": item.parent.name, "delivery_sha256": delivery_digest(item)}
        for item in sorted(delivery.glob("*/delivery.md"))
    ]


__all__ = [
    "SEALED_NAME",
    "SEALED_SCHEMA_VERSION",
    "sealed_path",
    "sealed_record",
    "sealed_reason",
    "seal",
    "seal_articles",
    "is_sealed",
    "closed_reason",
    "run_is_closed",
    "delivery_digest",
]

