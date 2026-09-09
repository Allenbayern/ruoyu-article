#!/usr/bin/env python3
"""Collect NewRank discovery evidence for a Linux/Codex schedule.

The access token is supplied only by the runtime environment. This wrapper does
not accept credential arguments, persist the token, or print it. All actual
HTTP and response handling remains in ``article_group.newrank_hot_article``.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
import os
from pathlib import Path
import sys
from typing import NoReturn, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from article_group import newrank_hot_article  # noqa: E402


DEFAULT_OUTPUT_ROOT = ROOT / "runs" / "newrank-watch"


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, "argument_error\n")


def _today() -> date:
    return date.today()


def _date_range(days: int, today: date | None = None) -> list[str]:
    if days < 1:
        raise newrank_hot_article.NewrankError("days_invalid")
    anchor = today or _today()
    return [(anchor - timedelta(days=index)).isoformat() for index in range(days)]


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        description="Collect NewRank hot-article evidence without publication side effects."
    )
    parser.add_argument("--days", type=int, default=30, help="Number of Asia/Shanghai calendar dates to collect")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Root under which a YYYY-MM-DD evidence directory is created",
    )
    return parser


def _runtime_token() -> str | None:
    token = os.environ.get("NEWRANK_N_TOKEN", "")
    return token if token.strip() else None


def _summary(*, status: str, run_date: date, output: Path) -> str:
    manifest = output.with_name(output.name + ".manifest.json")
    return json.dumps(
        {
            "status": status,
            "date": run_date.isoformat(),
            "output": str(output),
            "manifest": str(manifest),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    token = _runtime_token()
    if token is None:
        print("source_unavailable")
        return 2

    run_date = _today()
    output_root = args.output_root.expanduser()
    output = output_root / run_date.isoformat() / "newrank-hot-articles.json"
    manifest = output.with_name(output.name + ".manifest.json")
    if output.exists() or manifest.exists():
        print("artifact_exists")
        return 2
    try:
        public_times = _date_range(args.days, run_date)
        collector = newrank_hot_article.NewrankCollector(n_token=token)
        result = collector.collect(public_times, output)
        if not output.is_file() or not manifest.is_file():
            raise newrank_hot_article.NewrankError("artifact_incomplete")
    except newrank_hot_article.NewrankError as error:
        # Only stable error codes leave the process. Never include exception
        # details because a future transport implementation could echo input.
        print(str(error.args[0]) if error.args else "source_failed")
        return 2
    except (OSError, TypeError, ValueError):
        print("source_failed")
        return 2

    status = str(result.get("status") or "source_failed")
    print(_summary(status=status, run_date=run_date, output=output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
