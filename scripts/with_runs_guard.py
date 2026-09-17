#!/usr/bin/env python3
"""with_runs_guard: 包住任意命令，跑前跑后比对 `runs/`，有改动就报出来。

为什么需要：真实操作（预检重跑、渲染、收尾、补证）此前靠"跑之前算一次指纹、跑之后
再算一次"的人肉两步。人肉结论不能复用，也容易漏。这个包装器把它变成一句：

    python scripts/with_runs_guard.py -- python -m article_group.close_out --run-root runs/… --confirm

退出码：0 = 命令成功且 runs/ 未变；3 = runs/ 出现未放行的改动（无论命令成败）；
`--allow-changes` 时放行改动并回传命令自己的退出码。

注意：本包装器只观察，不阻止——真正拒绝写入的是 `article_group.runs_guard`
（进程内护栏）与封存 run 的 `SEALED` 标记。两者一起用：护栏挡住不该写的，
本包装器告诉你"这次操作到底动了什么"。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runs_fingerprint import (  # noqa: E402
    build_payload,
    compare,
    format_changes,
    is_clean,
)

EXIT_CLEAN = 0
EXIT_UNEXPECTED_CHANGES = 3


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/with_runs_guard.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default="runs", help="要盯的目录（默认 runs）")
    parser.add_argument("--hash", dest="with_hash", action="store_true",
                        help="连内容 sha256 一起比（能发现同尺寸同 mtime 的改写）")
    parser.add_argument("--allow-changes", action="store_true",
                        help="有改动也算通过（仍然打印改动清单）")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="-- 之后的命令")
    args = parser.parse_args(argv)

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("需要命令：python scripts/with_runs_guard.py -- <命令…>")

    before = build_payload(args.root, with_hash=args.with_hash)
    print(f"[with_runs_guard] 跑前：{before['file_count']} 个文件，指纹 {before['fingerprint'][:16]}…")
    completed = subprocess.run(command)
    after = build_payload(args.root, with_hash=args.with_hash)
    changes = compare(before, after)
    print(f"[with_runs_guard] 跑后：指纹 {after['fingerprint'][:16]}…（命令退出码 {completed.returncode}）")
    print(format_changes(changes, hashed=bool(after.get("hashed"))))

    if not is_clean(changes):
        if args.allow_changes:
            print("[with_runs_guard] 有改动，但 --allow-changes 已显式放行。")
            return EXIT_CLEAN if completed.returncode == 0 else completed.returncode
        print(f"[with_runs_guard] 改动 {args.root}/ 是不该发生的："
              "要么改用沙盘（python scripts/run_sandbox.py <run>），"
              "要么确认这是有意的封存/留底写入后再跑。")
        return EXIT_UNEXPECTED_CHANGES
    if completed.returncode != 0:
        print(f"[with_runs_guard] {args.root}/ 未变；命令自己失败（退出码 {completed.returncode}）。")
        return completed.returncode
    return EXIT_CLEAN


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
