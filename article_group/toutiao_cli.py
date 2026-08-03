"""Manual command-line entry point for Toutiao evidence capture."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from article_group.toutiao import ToutiaoExtractionError
from article_group.toutiao_capture import capture_toutiao_source


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture one public Toutiao article into a source evidence snapshot."
    )
    parser.add_argument("--url", required=True, help="Public Toutiao article URL")
    parser.add_argument("--run-root", required=True, help="Existing or new local run root")
    parser.add_argument("--source-id", required=True, help="Single safe source ID")
    parser.add_argument("--role", default="confirmed-primary")
    parser.add_argument("--independence-group", default="")
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest_entry = capture_toutiao_source(
            args.url,
            args.run_root,
            args.source_id,
            role=args.role,
            independence_group=args.independence_group,
            timeout=args.timeout,
        )
    except ToutiaoExtractionError as error:
        print(json.dumps({"error": str(error), "type": "extraction"}), file=sys.stderr)
        return 2
    except ValueError as error:
        print(json.dumps({"error": str(error), "type": "input_or_snapshot"}), file=sys.stderr)
        return 2

    print(json.dumps(manifest_entry, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
