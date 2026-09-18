#!/usr/bin/env python3
"""把某个 run 的预览页发布到主机静态根（`article_group.preview_site` 的 CLI）。

产物生成与主机交付分开：`daily_engine` 每批在 run 内生成 `preview/`（不含主机路径），
本脚本负责把它复制到静态根并打印可点开的 URL。run 内会留一条
`preview/publish-record.json`（走留底通道）记录"谁在何时发布到了哪里"。

用法：
    python scripts/publish_preview.py \
        --run-dir runs/2026-09-17/daily-009 \
        --root /home/allen/image-outbox \
        --base-url http://192.168.100.168:8899

    # 只发布、不重新生成（预览页必须已存在）
    python scripts/publish_preview.py --run-dir <run> --root <静态根> --no-build

退出码：0 成功；2 参数/环境问题（静态根不存在、预览页缺失且 --no-build）；1 其它失败。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from article_group.preview_site import build, publish  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="发布 run 的静态预览页到主机静态根")
    parser.add_argument("--run-dir", required=True, type=Path, help="run 根目录，如 runs/2026-09-17/daily-009")
    parser.add_argument("--root", required=True, type=Path, help="主机静态根（HTTP 服务的目录）")
    parser.add_argument("--name", help="静态根下的目录名；默认 <日期>-<run 名>")
    parser.add_argument("--base-url", help="静态根对应的 URL 前缀，如 http://192.168.100.168:8899")
    parser.add_argument("--no-build", action="store_true", help="不重新生成预览页（要求已存在）")
    args = parser.parse_args(argv)

    run_root = args.run_dir.resolve()
    if not (run_root / "delivery").is_dir():
        print(json.dumps({"error": "not_a_run_dir", "run_dir": str(run_root)}, ensure_ascii=False))
        return 2
    if not args.root.expanduser().is_dir():
        print(json.dumps({"error": "static_root_missing", "root": str(args.root)}, ensure_ascii=False))
        return 2

    built = None
    if not args.no_build:
        try:
            built = build(run_root)
        except Exception as exc:  # noqa: BLE001 - CLI 报错要一句人话
            print(json.dumps({"error": "build_failed", "reason": f"{type(exc).__name__}:{exc}"}, ensure_ascii=False))
            return 1
    elif not (run_root / "preview/index.html").is_file():
        print(json.dumps({"error": "preview_missing", "hint": "先运行 build_preview 或去掉 --no-build"}, ensure_ascii=False))
        return 2

    try:
        record = publish(run_root, args.root, name=args.name, base_url=args.base_url)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": "publish_failed", "reason": f"{type(exc).__name__}:{exc}"}, ensure_ascii=False))
        return 1

    print(json.dumps({
        "run_id": record["run_id"] if "run_id" in record else run_root.name,
        "built": built is not None,
        "content_status": (built or {}).get("content_status"),
        "index_url": record["index_url"],
        "target": record["target"],
        "files": len(record["files"]),
        "index_sha256": record["index_sha256"],
        "publication_authorization": "not_authorized",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
