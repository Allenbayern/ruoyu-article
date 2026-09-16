"""run_state: 判定一个 run 是否已收尾（人工验收已落），用于保护已封存的证据。

为什么需要（2026-09-17 事故）：
daily-008 收尾后，为演示扩展后的预检工具，直接在**已收尾的 run** 上重跑
`ledger_coverage_precheck.py`，把 `review/art-001/ledger-coverage-precheck.json`
（10:20 那版，记录的是修复前的缺口）覆盖掉了。工具本身没有"这是封存证据"的概念。

本模块给出统一判据 `run_is_closed()`：batch.json 里任一文章
`gate_status.controller_acceptance == accepted`，或存在 human-attestation 签字。
写证据的工具在已收尾 run 上必须显式 `--force` 才能继续，并把覆盖事实写进产物。
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def _load(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def closed_reason(run_dir: str | Path) -> str:
    """已收尾时返回原因（供报错信息用），未收尾返回空串。"""
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


__all__ = ["run_is_closed", "closed_reason"]
