#!/usr/bin/env python3
"""Prepare and finalize the explicit viral-research semantic pass."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import NoReturn, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from article_group.viral_research_distill import (  # noqa: E402
    ViralResearchDistillError,
    finalize_distillation,
    prepare_distill_input,
)
from article_group.viral_research_selection import SelectionCriteria  # noqa: E402


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, "argument_error\n")


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        description="Prepare bounded input and finalize an explicitly triggered Codex semantic pass."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--package-root", type=Path, required=True)
    prepare.add_argument("--platform", required=True)
    prepare.add_argument("--medium", required=True)
    prepare.add_argument("--content-domain", required=True)
    prepare.add_argument("--narrative-purpose", required=True)
    prepare.add_argument("--output", type=Path, required=True)
    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--prepared", type=Path, required=True)
    finalize.add_argument("--package-root", type=Path, required=True)
    finalize.add_argument("--platform", required=True)
    finalize.add_argument("--medium", required=True)
    finalize.add_argument("--content-domain", required=True)
    finalize.add_argument("--narrative-purpose", required=True)
    finalize.add_argument("--cards-root", type=Path, required=True)
    finalize.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            criteria = SelectionCriteria(
                platform=args.platform,
                medium=args.medium,
                content_domain=args.content_domain,
                narrative_purpose=args.narrative_purpose,
            )
            result = prepare_distill_input(
                args.package_root, criteria=criteria, output_path=args.output
            )
            summary = {
                "status": "prepared",
                "output": str(args.output.expanduser().resolve()),
                "selected_sample_ids": result["selected_sample_ids"],
                "semantic_pass": result["semantic_pass"],
            }
        else:
            result = finalize_distillation(
                args.prepared,
                package_root=args.package_root,
                criteria=SelectionCriteria(
                    platform=args.platform,
                    medium=args.medium,
                    content_domain=args.content_domain,
                    narrative_purpose=args.narrative_purpose,
                ),
                cards_root=args.cards_root,
                output_path=args.output,
            )
            summary = {
                "status": "finalized",
                "output": str(args.output.expanduser().resolve()),
                "promotion_status": result["promotion_status"],
                "automatic_publication_authority": False,
            }
    except ViralResearchDistillError as exc:
        print(exc.code)
        return 2
    except (OSError, TypeError, ValueError):
        print("distill_failed")
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
