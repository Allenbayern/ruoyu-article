"""Manual command-line entry point for the Yuafeng R0 discovery radar.

Builds one local, caller-addressed R0 discovery-only JSON artifact from
explicitly named Yuafeng hot-list sources. Never reads or writes candidate
pool / prewrite / Toutiao files. The YUAFENG_API_KEY (if required by the
network adapter) is read at call-time by the adapter and never printed.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Sequence

from article_group.discovery_radar import (
    DiscoveryRadarError,
    build_yuafeng_discovery_radar,
)
from article_group.yuafeng_hot import YuafengHotError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build one Yuafeng R0 discovery-only radar JSON artifact."
    )
    parser.add_argument(
        "--output-path",
        required=True,
        help="Destination .json path whose parent directory already exists",
    )
    parser.add_argument(
        "--sources",
        required=True,
        help=(
            "JSON array of source descriptors, e.g. "
            '[{"name": "uc"}, {"name": "aggregate", "action": "微博热榜"}]'
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    try:
        sources = json.loads(args.sources)
    except json.JSONDecodeError as error:
        print(
            json.dumps(
                {"error": "invalid_sources_json", "detail": error.msg},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2

    try:
        artifact: dict[str, Any] = build_yuafeng_discovery_radar(
            args.output_path, sources
        )
    except (DiscoveryRadarError, YuafengHotError) as error:
        print(
            json.dumps(
                {"error": str(error), "type": "radar"}, ensure_ascii=False
            ),
            file=sys.stderr,
        )
        return 2
    except ValueError as error:
        print(
            json.dumps(
                {"error": str(error), "type": "input"}, ensure_ascii=False
            ),
            file=sys.stderr,
        )
        return 2

    print(json.dumps(artifact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
