#!/usr/bin/env python3
"""run_sandbox: 一条命令把 run 复制成可自由写入的演练沙盘。

为什么需要（2026-09-17 事故）：
为演示扩展后的预检工具，直接在**已收尾的 daily-008** 上重跑，覆盖了
`review/art-001/ledger-coverage-precheck.json`（当时无备份、不可还原）。
正确做法是先在副本上演练——但"记得先 cp"太依赖记性，所以做成一条命令。

行为：
- 默认复制到 `/tmp/<run-id>-sandbox-<时间戳>`，拒绝覆盖已存在的目标（除非 --force）；
- 副本里的 `SEALED` 改名为 `SEALED.from-source`，并写 `SANDBOX.json` 记录来源与时间，
  这样副本可自由写入（封存守门不会误挡演练），同时保留"它来自封存 run"的事实；
- 打印副本路径与可直接粘贴的命令。

边界：沙盘是演练资料，不是审计证据；不要用它替换真实 run。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

SANDBOX_MARKER = "SANDBOX.json"
SEALED_NAME = "SEALED"
SEALED_AS_COPIED = "SEALED.from-source"


def _now() -> _dt.datetime:
    return _dt.datetime.now().astimezone()


def sandbox_path(run_dir: str | Path, dest: str | Path | None = None) -> Path:
    source = Path(run_dir).resolve()
    if dest is not None:
        return Path(dest).resolve()
    label = f"{source.parent.name}-{source.name}" if source.parent.name[:4].isdigit() else source.name
    stamp = _now().strftime("%Y%m%dT%H%M%S")
    return Path("/tmp") / f"{label}-sandbox-{stamp}"


def make_sandbox(
    run_dir: str | Path,
    *,
    dest: str | Path | None = None,
    label: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """复制 run 成沙盘；返回 {dest, marker, …}。"""
    source = Path(run_dir).resolve()
    if not (source / "batch.json").is_file() and not (source / "delivery").is_dir():
        raise FileNotFoundError(f"不像一个 run 目录：{source}")
    target = sandbox_path(source, dest)
    if target.exists():
        if not force:
            raise FileExistsError(f"目标已存在：{target}（加 --force 覆盖）")
        shutil.rmtree(target)
    shutil.copytree(source, target, symlinks=True)

    sealed_from = ""
    sealed_path = target / SEALED_NAME
    if sealed_path.is_file():
        sealed_path.rename(target / SEALED_AS_COPIED)
        sealed_from = SEALED_AS_COPIED

    marker: dict[str, Any] = {
        "schema_version": "run-sandbox-v1",
        "created_at": _now().replace(microsecond=0).isoformat(),
        "source_run": str(source),
        "label": label,
        "sealed_marker_renamed_to": sealed_from,
        "note": "演练副本：可自由写入，不是审计证据；不要用它替换真实 run。",
        "hint": f"python -m article_group.close_out --run-root {target} --confirm",
        "publication_authorization": "not_authorized",
    }
    (target / SANDBOX_MARKER).write_text(
        json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    marker["dest"] = str(target)
    return marker


def is_sandbox(path: str | Path) -> bool:
    return (Path(path) / SANDBOX_MARKER).is_file()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python scripts/run_sandbox.py",
        description="把 run 复制成演练沙盘（默认 /tmp，副本可自由写入，SEALED 改名留痕）",
    )
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--dest", type=Path, default=None)
    parser.add_argument("--label", default="", help="备注这次演练要做什么")
    parser.add_argument("--force", action="store_true", help="目标已存在时覆盖")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    marker = make_sandbox(args.run_dir, dest=args.dest, label=args.label, force=args.force)
    if args.json:
        print(json.dumps(marker, ensure_ascii=False, indent=2))
    else:
        print(f"沙盘已就绪：{marker['dest']}")
        if marker["sealed_marker_renamed_to"]:
            print(f"  （源 run 已封存，副本内 {SEALED_NAME} → {marker['sealed_marker_renamed_to']}，副本可写入）")
        print(f"  提示：{marker['hint']}")
    return 0


__all__ = ["SANDBOX_MARKER", "SEALED_AS_COPIED", "sandbox_path", "make_sandbox", "is_sandbox", "main"]


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
