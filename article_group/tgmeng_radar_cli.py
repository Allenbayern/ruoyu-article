"""Manual command-line entry point for the tgmeng R0 discovery radar.

Builds one local, caller-addressed R0 discovery-only JSON artifact from
explicitly named tgmeng sources (boards and candy index). Never reads or
writes candidate pool / prewrite / Toutiao files.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Final, Sequence

from article_group.tgmeng_radar import (
    DiscoveryRadarError,
    build_tgmeng_discovery_radar,
    validate_discovery_radar,
)
from article_group.tgmeng_hot import TgmengHotError

_BOARD_NAMES: Final = "weibo zhihu bilibili douyin toutiao baidu maoyan tencent aiqiyi"
_CANDY_TYPES: Final = "all technology finance entertainment car sports game livelihood"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build one tgmeng R0 discovery-only radar JSON artifact."
    )
    parser.add_argument(
        "--output-path",
        required=True,
        help="Destination .json path whose parent directory already exists",
    )
    parser.add_argument(
        "--boards",
        default="",
        help=(
            f"Space-separated board names to fetch, e.g. "
            f"'maoyan tencent aiqiyi'. Allowed: {_BOARD_NAMES}"
        ),
    )
    parser.add_argument(
        "--candy",
        default="",
        help=(
            "Space-separated candy-index categories, e.g. 'entertainment all'. "
            f"Allowed: {_CANDY_TYPES}"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    sources: list[dict[str, Any]] = []
    for name in args.boards.split():
        sources.append({"name": name})
    for candy_type in args.candy.split():
        sources.append({"name": "candy", "type": candy_type})
    if not sources:
        print(
            json.dumps(
                {"error": "no_sources", "detail": "provide --boards and/or --candy"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2

    try:
        artifact: dict[str, Any] = build_tgmeng_discovery_radar(
            args.output_path, sources
        )
        problems = validate_discovery_radar(artifact)
    except (DiscoveryRadarError, TgmengHotError) as error:
        print(
            json.dumps({"error": str(error), "type": "radar"}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    except ValueError as error:
        print(
            json.dumps({"error": str(error), "type": "input"}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2

    if problems:
        print(
            json.dumps(
                {"error": "validation_failed", "problems": problems},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 3

    print(json.dumps(artifact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
