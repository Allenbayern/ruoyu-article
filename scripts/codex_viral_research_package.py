#!/usr/bin/env python3
"""Build an immutable local viral-research package from a capture manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import NoReturn, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from article_group.viral_research_package import (  # noqa: E402
    ViralResearchPackageError,
    build_package,
    validate_package_root,
)


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, "argument_error\n")


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        description="Build a non-overwriting viral research package from local capture evidence."
    )
    parser.add_argument("--capture-manifest", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = build_package(
            args.capture_manifest,
            run_root=args.run_root,
            output_root=args.output_root,
        )
        validate_package_root(args.output_root)
    except ViralResearchPackageError as exc:
        print(exc.code)
        return 2
    except (OSError, TypeError, ValueError):
        print("package_failed")
        return 2

    status = manifest.get("status")
    if status != "evidence_checked":
        print("package_incomplete")
        return 2
    print(
        json.dumps(
            {
                "status": status,
                "output_root": str(args.output_root.expanduser().resolve()),
                "sample_count": len(manifest.get("samples", [])),
                "exclusion_count": sum(
                    1
                    for line in (args.output_root / "exclusions.jsonl").read_text(
                        encoding="utf-8"
                    ).splitlines()
                    if line.strip()
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
