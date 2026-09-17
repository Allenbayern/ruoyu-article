#!/usr/bin/env python3
"""runs_fingerprint: 给 `runs/` 拍可复现指纹，并在真实操作前后比对。

为什么需要：2026-09-17 之后，"跑之前/跑之后 runs/ 一字未动"一直靠手工两步算指纹。
人肉结论不能复用也不能审计；这个脚本把它变成命令。

用法：
    python scripts/runs_fingerprint.py print                     # 打印指纹
    python scripts/runs_fingerprint.py print --hash              # 连内容也哈希（更严、更慢）
    python scripts/runs_fingerprint.py save --out /tmp/before.json
    python scripts/runs_fingerprint.py compare --snapshot /tmp/before.json

判据：默认用 (size, mtime_ns) 做快照——改动必然改 mtime_ns，快且够用；
`--hash` 额外记 sha256，能发现"尺寸与 mtime 都被还原"的改写（`rewritten`）。
比对发现变更时退出码 2（干净为 0），好让它在门禁/脚本里直接用。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "runs-fingerprint-v1"
DEFAULT_ROOT = "runs"
EXIT_CLEAN = 0
EXIT_CHANGED = 2


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(root: str | Path, *, with_hash: bool = False) -> dict[str, list[Any]]:
    """目录下每个文件的 [size, mtime_ns]（`--hash` 时追加 sha256）。"""
    base = Path(root)
    entries: dict[str, list[Any]] = {}
    if not base.is_dir():
        return entries
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        key = path.relative_to(base).as_posix()
        row: list[Any] = [stat.st_size, stat.st_mtime_ns]
        if with_hash:
            try:
                row.append(_sha256_file(path))
            except OSError:
                row.append("")
        entries[key] = row
    return entries


def fingerprint(entries: Mapping[str, list[Any]]) -> str:
    lines = [f"{key}\t" + "\t".join(str(part) for part in entries[key]) for key in sorted(entries)]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def build_payload(root: str | Path, *, with_hash: bool = False) -> dict[str, Any]:
    entries = snapshot(root, with_hash=with_hash)
    return {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "hashed": with_hash,
        "file_count": len(entries),
        "fingerprint": fingerprint(entries),
        "entries": entries,
    }


def compare(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, list[str]]:
    """added / removed / changed（元数据变）/ rewritten（同尺寸同 mtime 但内容变）。"""
    old: Mapping[str, list[Any]] = before.get("entries", {})
    new: Mapping[str, list[Any]] = after.get("entries", {})
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed, rewritten = [], []
    for key in sorted(set(old) & set(new)):
        old_row, new_row = list(old[key]), list(new[key])
        if old_row[:2] != new_row[:2]:
            changed.append(key)
        elif len(old_row) > 2 and len(new_row) > 2 and old_row[2] != new_row[2]:
            rewritten.append(key)
    return {"added": added, "removed": removed, "changed": changed, "rewritten": rewritten}


def is_clean(changes: Mapping[str, list[str]]) -> bool:
    return not any(changes.values())


def format_changes(changes: Mapping[str, list[str]], *, hashed: bool) -> str:
    lines = []
    for label, items in changes.items():
        if label == "rewritten" and items:
            lines.append(f"  rewritten({len(items)}): 尺寸与 mtime 未变但内容不同 — {', '.join(items[:5])}")
            continue
        if items:
            preview = ", ".join(items[:5]) + (" …" if len(items) > 5 else "")
            lines.append(f"  {label}({len(items)}): {preview}")
    if not lines:
        lines.append("  runs/ 与快照逐项一致（size + mtime_ns" + (" + sha256" if hashed else "") + "）。")
    elif not hashed:
        lines.append("  提示：未做内容哈希，同尺寸且 mtime 被还原的改写不会被发现（加 --hash）。")
    return "\n".join(lines)


def _load_snapshot(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit(f"快照格式不认识：{path}")
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python scripts/runs_fingerprint.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("print", "save", "compare"))
    parser.add_argument("--root", default=DEFAULT_ROOT, help=f"要拍指纹的目录（默认 {DEFAULT_ROOT}）")
    parser.add_argument("--hash", dest="with_hash", action="store_true", help="连内容 sha256 一起记")
    parser.add_argument("--out", type=Path, help="save：快照写到哪")
    parser.add_argument("--snapshot", type=Path, help="compare：拿哪份快照比")
    parser.add_argument("--json", action="store_true", help="打印完整 JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "print":
        payload = build_payload(args.root, with_hash=args.with_hash)
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json
              else f"文件 {payload['file_count']} 个\n指纹 {payload['fingerprint']}")
        return EXIT_CLEAN

    if args.command == "save":
        if args.out is None:
            raise SystemExit("save 需要 --out <路径>")
        payload = build_payload(args.root, with_hash=args.with_hash)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"快照已保存：{args.out}（{payload['file_count']} 个文件，指纹 {payload['fingerprint'][:16]}…）")
        return EXIT_CLEAN

    if args.snapshot is None:
        raise SystemExit("compare 需要 --snapshot <快照路径>")
    before = _load_snapshot(args.snapshot)
    after = build_payload(args.root, with_hash=bool(before.get("hashed")) or args.with_hash)
    changes = compare(before, after)
    print(f"指纹 之前 {str(before.get('fingerprint'))[:16]}… → 现在 {after['fingerprint'][:16]}…")
    print(format_changes(changes, hashed=bool(after.get("hashed"))))
    return EXIT_CLEAN if is_clean(changes) else EXIT_CHANGED


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
