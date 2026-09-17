"""evidence_write: 写 run 证据的唯一入口——先留底，再写，并记账。

为什么需要（2026-09-17 事故）：
在已收尾的 daily-008 上重跑账本预检，覆盖了
`review/art-001/ledger-coverage-precheck.json`（10:20 那版记录的是修复前缺口）。
预检器当时是"无条件写"，没有 before-image，覆盖即不可逆——只能事后登记，无法还原。

本模块把写证据变成三件事：
1. **留底**：覆盖前把旧文件存到 `review/.before/<时间戳>/<相对路径>`；
2. **记账**：往 `evidence-changelog.jsonl` 追加一行（谁/何时/为什么/前后 SHA-256/快照路径）；
3. **守门**：run 已封存（SEALED）时默认拒绝写入，必须显式 force。

配套 `restore()` 能按快照把文件还原，让留底真正可用而不只是心理安慰。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import shutil
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "evidence-write-v1"
CHANGELOG_NAME = "evidence-changelog.jsonl"
BEFORE_DIR = "review/.before"

_THIS = Path(__file__).resolve()
if str(_THIS.parents[1]) not in sys.path:  # pragma: no cover - 源码树内运行
    sys.path.insert(0, str(_THIS.parents[1]))

from article_group.run_state import sealed_reason  # noqa: E402


class RunSealedError(RuntimeError):
    """目标 run 已封存，未显式 force 时拒绝写入。"""


def _now() -> _dt.datetime:
    return _dt.datetime.now().astimezone()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def changelog_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / CHANGELOG_NAME


def snapshot_dir(run_dir: str | Path, stamp: _dt.datetime | None = None) -> Path:
    moment = stamp or _now()
    return Path(run_dir) / BEFORE_DIR / moment.strftime("%Y%m%dT%H%M%S")


def write_evidence(
    path: str | Path,
    content: str | bytes,
    *,
    run_dir: str | Path,
    reason: str,
    author: str = "agent",
    force: bool = False,
) -> dict[str, Any]:
    """写一个 run 证据文件：留底 → 记账 → 写入。返回本次写入的账目条目。"""
    root = Path(run_dir)
    target = Path(path)
    if not target.is_absolute():
        target = root / target
    blocked = sealed_reason(root)
    if blocked and not force:
        raise RunSealedError(f"run 已封存（{blocked}）：加 force 才会改写封存证据")

    payload = content.encode("utf-8") if isinstance(content, str) else content
    existed = target.is_file()
    before_sha = sha256_bytes(target.read_bytes()) if existed else ""
    moment = _now()
    snapshot = ""
    if existed:
        relative = target.relative_to(root) if target.is_relative_to(root) else Path(target.name)
        backup = snapshot_dir(root, moment) / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
        snapshot = str(backup.relative_to(root))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)

    entry: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "at": moment.replace(microsecond=0).isoformat(),
        "author": author,
        "reason": reason,
        "path": str(target.relative_to(root)) if target.is_relative_to(root) else str(target),
        "existed": existed,
        "before_sha256": before_sha,
        "after_sha256": sha256_bytes(payload),
        "snapshot_path": snapshot,
        "forced": bool(force and blocked),
        "publication_authorization": "not_authorized",
    }
    log = changelog_path(root)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def write_evidence_json(
    path: str | Path,
    payload: Mapping[str, Any] | Sequence[Any],
    *,
    run_dir: str | Path,
    reason: str,
    author: str = "agent",
    force: bool = False,
) -> dict[str, Any]:
    return write_evidence(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        run_dir=run_dir, reason=reason, author=author, force=force,
    )


def read_changelog(run_dir: str | Path) -> list[dict[str, Any]]:
    path = changelog_path(run_dir)
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            entries.append(dict(payload))
    return entries


def latest_snapshot(run_dir: str | Path, relative_path: str) -> Path | None:
    """按时间倒序找某个证据文件最近一次留底。"""
    base = Path(run_dir) / BEFORE_DIR
    if not base.is_dir():
        return None
    for directory in sorted((item for item in base.iterdir() if item.is_dir()), reverse=True):
        candidate = directory / relative_path
        if candidate.is_file():
            return candidate
    return None


def restore(
    run_dir: str | Path,
    relative_path: str,
    *,
    reason: str = "restore_from_snapshot",
    author: str = "agent",
    force: bool = False,
) -> dict[str, Any]:
    """用最近一次快照还原某个证据文件（本身也留底、也记账）。"""
    root = Path(run_dir)
    snapshot = latest_snapshot(root, relative_path)
    if snapshot is None:
        raise FileNotFoundError(f"没有可用快照：{relative_path}")
    return write_evidence(
        root / relative_path,
        snapshot.read_bytes(),
        run_dir=root,
        reason=f"{reason}<-{snapshot.parent.name}",
        author=author,
        force=force,
    )


__all__ = [
    "SCHEMA_VERSION",
    "CHANGELOG_NAME",
    "BEFORE_DIR",
    "RunSealedError",
    "changelog_path",
    "snapshot_dir",
    "write_evidence",
    "write_evidence_json",
    "read_changelog",
    "latest_snapshot",
    "restore",
    "sha256_bytes",
]
