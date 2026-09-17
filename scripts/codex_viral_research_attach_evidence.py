#!/usr/bin/env python3
"""Attach sanitized client evidence as a non-overwriting package revision."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import NoReturn, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from article_group.runs_guard import SealedWriteBlocked, cli_refusal
from article_group.viral_research_cards import (  # noqa: E402
    ViralResearchCardError,
    attach_client_evidence,
)


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, "argument_error\n")


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        description="Attach already-sanitized client evidence as a new immutable revision."
    )
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--evidence-file", type=Path, required=True)
    parser.add_argument("--output-revision", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = attach_client_evidence(
            package_root=args.package_root,
            sample_id=args.sample_id,
            evidence_file=args.evidence_file,
            output_revision=args.output_revision,
        )
    except ViralResearchCardError as exc:
        print(str(exc).split(":", 1)[0])
        return 2
    except SealedWriteBlocked as exc:  # 封存 run：一句人话 + 退出码 2，不给 traceback
        return cli_refusal(exc)
    except (OSError, TypeError, ValueError):
        print("attachment_failed")
        return 2
    print(
        json.dumps(
            {
                "status": "revision_written",
                "revision": str(args.output_revision.expanduser().resolve()),
                "sample_id": result["sample_id"],
                "derived_qualification_status": result["derived_qualification_status"],
                "automatic_publication_authority": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
