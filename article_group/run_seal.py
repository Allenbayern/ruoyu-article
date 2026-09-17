"""run_seal: 封存不只是"写个 SEALED"，而是**全量清单 + 可事后验证**。

为什么需要（008 复盘后的最后一块）：
`SEALED` 只记了封存时间、署名和两篇交付的哈希。于是"封存之后有没有被改过"这个问题
此前无法回答——尤其 `runs/` 不进 git，连副本都没有。运行时护栏（`runs_guard`）挡得住
进程内的误写，挡不住进程外（编辑器 / rsync / git checkout），更挡不住"已经写进去了、
没人知道"。本模块补上事后可验：

- **seal 时**：把 run 内每个文件的 size + sha256（符号链接记目标）写进
  `SEALED.manifest.json`，并把即将写下的 `SEALED` 字节哈希一并记入
  （`sealed_marker_sha256`），这样标记自身也被覆盖；
- **verify 时**：逐项重算并分类——改动 / 新增 / 缺失 / 符号链接变化 / append-only 被重写，
  再与 `evidence-changelog.jsonl` 对照，区分"有账的 force 改动"与"无账的可疑改动"；
- **契约 append-only 文件**（`step-log.jsonl` / `evidence-changelog.jsonl`）按**前缀**校验：
  追加不算改动，重写/截断算。

排除项是显式的（见 `EXCLUDED_REASONS`）：封存生命周期标记、append-only 文件（另按前缀校验）、
清单自身、以及 `review/.before/**`（force 写入的留底快照，只会在封存后新增）。

退出码（CLI）：0 完好 / 2 有漂移 / 3 无法验证（缺清单，例如封存时还没有本模块的 run）。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "run-sealed-manifest-v1"
MANIFEST_NAME = "SEALED.manifest.json"
SEALED_NAME = "SEALED"
APPEND_ONLY_NAMES = ("step-log.jsonl", "evidence-changelog.jsonl")
BEFORE_DIR = "review/.before"

EXCLUDED_REASONS: dict[str, str] = {
    SEALED_NAME: "封存标记自身：用 sealed_marker_sha256 单独校验",
    MANIFEST_NAME: "清单自身（写清单时它还不存在）",
    "SEALED.*": "封存生命周期留下的标记（撤销封存 / 沙盘改名）",
    "evidence-changelog.jsonl": "契约 append-only：按前缀校验（追加放行、重写算改动）",
    "step-log.jsonl": "契约 append-only：同上（封存这一步自己的流水就在其后追加）",
    BEFORE_DIR + "/**": "force 写入的留底快照：只会在封存后新增",
}

EXIT_INTACT = 0
EXIT_DRIFTED = 2
EXIT_UNVERIFIABLE = 3


def manifest_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / MANIFEST_NAME


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_excluded(relative: str) -> bool:
    if relative in EXCLUDED_REASONS:
        return True
    if relative.startswith("SEALED."):
        return True
    if relative.startswith(BEFORE_DIR + "/"):
        return True
    return False


def _iter_entries(root: Path) -> Iterator[tuple[str, Path]]:
    """遍历 run 内应被清单覆盖的条目（跳过排除项），按路径排序。"""
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if _is_excluded(relative):
            continue
        if path.is_symlink() or path.is_file():
            yield relative, path


def build_manifest(
    run_dir: str | Path,
    *,
    sealed_at: str,
    sealed_by: str,
    seal_ref: str = "",
    sealed_marker_sha256: str = "",
) -> dict[str, Any]:
    """生成封存全量清单（不落盘）。"""
    root = Path(run_dir)
    files: list[dict[str, Any]] = []
    total_bytes = 0
    for relative, path in _iter_entries(root):
        if path.is_symlink():
            files.append({"path": relative, "symlink": os.readlink(path)})
            continue
        size = path.stat().st_size
        total_bytes += size
        files.append({"path": relative, "size": size, "sha256": _sha256_file(path)})

    append_only: list[dict[str, Any]] = []
    for name in APPEND_ONLY_NAMES:
        path = root / name
        if not path.is_file():
            continue
        data = path.read_bytes()
        append_only.append({"path": name, "size": len(data), "sha256": _sha256_bytes(data)})

    return {
        "schema_version": SCHEMA_VERSION,
        "run_dir": str(root),
        "sealed_at": sealed_at,
        "sealed_by": sealed_by,
        "seal_ref": seal_ref,
        "sealed_marker_sha256": sealed_marker_sha256,
        "file_count": len(files),
        "total_bytes": total_bytes,
        "files": files,
        "append_only": append_only,
        "excluded": dict(EXCLUDED_REASONS),
        "backfilled": False,
        "backfilled_at": "",
        "note": "封存全量清单：verify 逐项重算。force 改动合法但会被列出（有账可查）；"
                "无账改动一律视为可疑。",
        "publication_authorization": "not_authorized",
    }


def write_manifest(run_dir: str | Path, payload: dict[str, Any]) -> Path:
    path = manifest_path(run_dir)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_manifest(run_dir: str | Path) -> dict[str, Any] | None:
    path = manifest_path(run_dir)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _changelog_index(run_dir: Path) -> dict[str, dict[str, Any]]:
    """路径 → 最后一条记账（谁/何时/是否 forced）。verify 只读，绝不写。"""
    path = run_dir / "evidence-changelog.jsonl"
    index: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return index
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            index[entry["path"]] = entry
    return index


def verify(run_dir: str | Path) -> dict[str, Any]:
    """逐项重算清单，返回 {status, changes, …}（只读）。"""
    root = Path(run_dir)
    manifest = load_manifest(root)
    if manifest is None:
        return {
            "status": "unverifiable",
            "run_dir": str(root),
            "reason": "该 run 没有封存全量清单（封存时还没有 run_seal，或清单被删）",
            "remedy": "若确认要补录：python -m article_group.run_seal --run-root <run> --backfill"
                      "（补录只能证明补录之后未被改动，不能证明封存时刻的内容）",
            "changes": [],
        }
    if manifest.get("schema_version") != SCHEMA_VERSION:
        return {
            "status": "unverifiable",
            "run_dir": str(root),
            "reason": f"清单版本不认识：{manifest.get('schema_version')!r}",
            "changes": [],
        }

    listed = {str(item["path"]): item for item in manifest.get("files", []) if isinstance(item, dict)}
    present = {relative: path for relative, path in _iter_entries(root)}
    changes: list[dict[str, Any]] = []

    for relative, item in listed.items():
        path = present.get(relative)
        if path is None:
            changes.append({"path": relative, "kind": "missing", "detail": "清单里有、现在不在"})
            continue
        if path.is_symlink():
            if os.readlink(path) != item.get("symlink"):
                changes.append({"path": relative, "kind": "symlink_changed",
                                "detail": f"{item.get('symlink')!r} → {os.readlink(path)!r}"})
            continue
        if item.get("symlink") is not None:
            changes.append({"path": relative, "kind": "symlink_changed",
                            "detail": "清单记的是符号链接，现在是普通文件"})
            continue
        size = path.stat().st_size
        if size != item.get("size"):
            changes.append({"path": relative, "kind": "modified",
                            "detail": f"size {item.get('size')} → {size}"})
            continue
        digest = _sha256_file(path)
        if digest != item.get("sha256"):
            changes.append({"path": relative, "kind": "modified",
                            "detail": f"sha256 {str(item.get('sha256'))[:12]}… → {digest[:12]}…"})
    for relative in sorted(set(present) - set(listed)):
        changes.append({"path": relative, "kind": "added", "detail": "清单里没有、现在多出来"})

    for item in manifest.get("append_only", []):
        relative = str(item.get("path"))
        path = root / relative
        if not path.is_file():
            changes.append({"path": relative, "kind": "missing", "detail": "append-only 文件不见了"})
            continue
        data = path.read_bytes()
        frozen = int(item.get("size", 0))
        if len(data) < frozen:
            changes.append({"path": relative, "kind": "append_only_truncated",
                            "detail": f"封存时 {frozen} 字节，现在 {len(data)} 字节"})
        elif _sha256_bytes(data[:frozen]) != item.get("sha256"):
            changes.append({"path": relative, "kind": "append_only_rewritten",
                            "detail": "封存时的前 N 字节已被改写"})

    if manifest.get("sealed_marker_sha256"):
        marker = root / SEALED_NAME
        expected = str(manifest["sealed_marker_sha256"])
        if not marker.is_file():
            changes.append({"path": SEALED_NAME, "kind": "missing", "detail": "封存标记不见了"})
        elif _sha256_file(marker) != expected:
            changes.append({"path": SEALED_NAME, "kind": "modified",
                            "detail": "封存标记的字节与封存时不一致"})

    ledger = _changelog_index(root)
    for change in changes:
        entry = ledger.get(change["path"])
        change["authorized"] = entry is not None
        if entry is not None:
            change["ledger"] = {
                "at": entry.get("at"),
                "author": entry.get("author"),
                "reason": entry.get("reason"),
                "forced": entry.get("forced"),
            }

    return {
        "status": "intact" if not changes else "drifted",
        "run_dir": str(root),
        "sealed_at": manifest.get("sealed_at"),
        "sealed_by": manifest.get("sealed_by"),
        "backfilled": bool(manifest.get("backfilled")),
        "backfilled_at": manifest.get("backfilled_at", ""),
        "checked_files": len(listed),
        "append_only_checked": len(manifest.get("append_only", [])),
        "changes": changes,
        "unauthorized_changes": [item for item in changes if not item.get("authorized")],
        "publication_authorization": "not_authorized",
    }


def backfill(run_dir: str | Path, *, author: str = "agent", reason: str = "") -> dict[str, Any]:
    """给"封存时还没有清单"的老 run 事后补录清单（必须留痕、且不假装能证明历史）。"""
    from article_group import runs_guard
    from article_group.evidence_write import append_changelog
    from article_group.run_state import sealed_record

    root = Path(run_dir)
    record = sealed_record(root)
    if not record:
        return {"status": "not_sealed", "run_dir": str(root)}
    if load_manifest(root) is not None:
        return {"status": "already_present", "run_dir": str(root)}

    stamp = _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()
    payload = build_manifest(
        root,
        sealed_at=str(record.get("sealed_at", "")),
        sealed_by=str(record.get("sealed_by", "")),
        seal_ref=str(record.get("seal_ref", "")),
        sealed_marker_sha256=_sha256_file(root / SEALED_NAME) if (root / SEALED_NAME).is_file() else "",
    )
    payload.update({
        "backfilled": True,
        "backfilled_at": stamp,
        "backfilled_by": author,
        "backfill_note": "事后补录：只能证明补录之后未被改动，不能证明封存时刻的内容。",
    })
    with runs_guard.sealed_write_token(root, reason="run_seal:backfill", author=author):
        write_manifest(root, payload)
        append_changelog(
            root,
            path=MANIFEST_NAME,
            reason=f"run_seal:backfill:{reason}" if reason else "run_seal:backfill",
            author=author,
            existed=False,
            after_sha256=_sha256_bytes(manifest_path(root).read_bytes()),
            forced=True,  # 目标 run 已封存：这是经令牌的显式写入，照实记
        )
    return {"status": "backfilled", **{key: payload[key] for key in ("backfilled_at", "file_count")}}


def _describe(report: dict[str, Any]) -> str:
    status = report.get("status")
    if status == "unverifiable":
        return f"无法验证：{report.get('reason')}\n  {report.get('remedy', '')}"
    lines = [
        f"封存完整性：{status}（核对 {report.get('checked_files')} 个文件，"
        f"append-only {report.get('append_only_checked')} 个）",
        f"  sealed_at={report.get('sealed_at')} by={report.get('sealed_by')}"
        + ("（事后补录清单）" if report.get("backfilled") else ""),
    ]
    for change in report.get("changes", []):
        mark = "有账" if change.get("authorized") else "无账"
        detail = change.get("detail", "")
        lines.append(f"  [{mark}] {change.get('kind')}: {change.get('path')} — {detail}")
        if change.get("authorized"):
            entry = change["ledger"]
            lines.append(f"        记账：{entry.get('at')} by {entry.get('author')} "
                         f"reason={entry.get('reason')} forced={entry.get('forced')}")
    if not report.get("changes"):
        lines.append("  与封存时逐字节一致。")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m article_group.run_seal",
        description="校验（或事后补录）run 的封存全量清单：0 完好 / 2 有漂移 / 3 无法验证",
    )
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--backfill", action="store_true",
                        help="给封存时还没有清单的老 run 补录（留痕；不假装能证明历史）")
    parser.add_argument("--author", default="agent")
    parser.add_argument("--reason", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.backfill:
        result = backfill(args.run_root, author=args.author, reason=args.reason)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["status"] != "backfilled":
            return EXIT_UNVERIFIABLE

    report = verify(args.run_root)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else _describe(report))
    return {
        "intact": EXIT_INTACT,
        "drifted": EXIT_DRIFTED,
        "unverifiable": EXIT_UNVERIFIABLE,
    }.get(str(report.get("status")), EXIT_UNVERIFIABLE)


__all__ = [
    "APPEND_ONLY_NAMES",
    "EXCLUDED_REASONS",
    "EXIT_DRIFTED",
    "EXIT_INTACT",
    "EXIT_UNVERIFIABLE",
    "MANIFEST_NAME",
    "SCHEMA_VERSION",
    "backfill",
    "build_manifest",
    "load_manifest",
    "main",
    "manifest_path",
    "verify",
    "write_manifest",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
