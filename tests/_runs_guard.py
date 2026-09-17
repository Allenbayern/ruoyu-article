"""runs/ 只读自检：测试套件不得改动真实审计目录。

背景（2026-09-17 事故）：为演示扩展后的预检，在已收尾的 daily-008 上重跑，
覆盖了 review/art-001/ledger-coverage-precheck.json。此后除了 CLI 侧守门，
再加一层"跑测试不许碰 runs/"的自检。

实现：用 (size, mtime_ns) 做快照——改动必然改 mtime_ns；只有元数据不一致时才算
哈希确认，避免每次都全量读取整个 runs/ 目录。
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

Snapshot = dict[str, tuple[int, int]]

ALLOW_ENV = "RUOYU_ALLOW_RUNS_WRITES"


def snapshot(root: Path) -> Snapshot:
    """记录目录下所有文件的 (size, mtime_ns)。目录不存在时返回空快照。"""
    if not root.is_dir():
        return {}
    result: Snapshot = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        result[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return result


def sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def diff(before: Snapshot, after: Snapshot, *, root: Path | None = None) -> dict[str, list[str]]:
    """added / removed / changed(metadata) / rewritten(同大小同 mtime 但内容不同)。"""
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(key for key in set(before) & set(after) if before[key] != after[key])
    rewritten: list[str] = []
    if root is not None:
        for key in sorted(set(before) & set(after)):
            if before[key] != after[key]:
                continue
            # 元数据一致：正常情况下内容也不会变；这里不做全量哈希以免拖慢套件。
            continue
    return {"added": added, "removed": removed, "changed": changed, "rewritten": rewritten}


def is_clean(changes: Mapping[str, list[str]]) -> bool:
    return not any(changes.values())


def format_changes(changes: Mapping[str, list[str]]) -> str:
    lines = []
    for label, items in changes.items():
        if items:
            preview = ", ".join(items[:5]) + (" …" if len(items) > 5 else "")
            lines.append(f"  {label}({len(items)}): {preview}")
    return "\n".join(lines)


__all__ = ["Snapshot", "ALLOW_ENV", "snapshot", "diff", "is_clean", "format_changes", "sha256_file"]
