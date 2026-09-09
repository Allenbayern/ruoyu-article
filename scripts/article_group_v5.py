#!/usr/bin/env python3
"""Command-line entry point for the offline V5 verification lane."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from article_group.v5.verification import (
    VerificationError,
    _build_artifacts,
    _fixture,
    run_v5_verification,
    validate_v5_artifact,
    write_v5_artifact,
)


_COMMAND_FILES = {
    "experiment": "experiment-record.json",
    "lifecycle": "content-lifecycle.json",
    "dna": "article-dna.json",
    "failures": "failure-samples.json",
    "quotas": "dynamic-quotas.json",
    "strategy": "strategy-library.json",
    "resources": "resource-plan.json",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the offline, non-authorizing Ruoyu Article Group V5 lane."
    )
    parser.add_argument(
        "command",
        choices=(*_COMMAND_FILES, "verify"),
        help="artifact builder to run",
    )
    parser.add_argument("--run-dir", required=True, type=Path)
    outputs = parser.add_mutually_exclusive_group(required=True)
    outputs.add_argument("--output-dir", type=Path)
    outputs.add_argument("--output-path", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "verify":
            destination = args.output_path or args.output_dir
            assert destination is not None
            report = run_v5_verification(args.run_dir, output_path=destination)
            print(
                f"{report['payload'].get('status', 'PASS')} "
                f"v5-verification.json"
            )
            return 0

        fixture = _fixture(args.run_dir)
        artifacts = _build_artifacts(fixture)
        name = _COMMAND_FILES[args.command]
        artifact = artifacts[name]
        errors = validate_v5_artifact(name, artifact, fixture.run_dir)
        if errors:
            raise VerificationError("artifact_invalid:" + ";".join(errors))
        destination = (
            args.output_path
            if args.output_path is not None
            else args.output_dir / name
        )
        written = write_v5_artifact(name, artifact, output_path=destination)
        print(f"PASS {name} ({written})")
        return 0
    except (VerificationError, OSError, AssertionError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
