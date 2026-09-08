#!/usr/bin/env python3
"""Offline command-line entry point for the Article Group V4 lane.

The command only composes the pure V4 modules over one explicit run-local
directory.  It has no source discovery, network, Vault, HTML, credential, or
publication side effect.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from article_group.v4.verification import (  # noqa: E402
    ARTIFACT_FILES,
    V4VerificationError,
    build_effect_artifact,
    build_gap_artifact,
    build_graph_artifact,
    build_portfolio_artifact,
    build_recovery_artifact,
    build_template_artifact,
    run_v4_verification,
    validate_v4_artifact,
    write_v4_artifact,
)


COMMANDS = ("plan", "graph", "gaps", "templates", "effects", "recover", "verify")
_COMMAND_ARTIFACTS = {
    "plan": "portfolio",
    "graph": "graph",
    "gaps": "gaps",
    "templates": "templates",
    "effects": "effects",
    "recover": "recover",
}
_BUILDERS: dict[str, Callable[[Path], dict[str, Any]]] = {
    "plan": build_portfolio_artifact,
    "graph": build_graph_artifact,
    "templates": build_template_artifact,
    "effects": build_effect_artifact,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Article Group V4 offline evidence lane."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in COMMANDS:
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--run-dir", "--run", dest="run_dir", type=Path, required=True)
        outputs = subparser.add_mutually_exclusive_group(required=True)
        outputs.add_argument("--output-dir", type=Path)
        outputs.add_argument("--output-path", "--output", dest="output_path", type=Path)
    return parser


def _print_result(
    status: str,
    *,
    path: Path | None = None,
    errors: list[str] | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    result: dict[str, Any] = {
        "status": status,
        "path": str(path) if path is not None else None,
        "errors": errors or [],
    }
    if payload is not None:
        for field in (
            "decision",
            "PASS",
            "missing_source_roles",
            "retry_requirements",
            "manual_escalation",
            "content_status",
            "publication_authorization",
            "read_back",
        ):
            if field in payload:
                result[field] = payload[field]
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def _run_root(raw: Path) -> Path:
    run_dir = raw.resolve()
    if raw.is_symlink() or not run_dir.is_dir():
        raise V4VerificationError(f"run_dir_missing_or_unsafe:{run_dir}")
    return run_dir


def _target(args: argparse.Namespace, artifact_name: str) -> Path:
    if args.output_path is not None:
        return args.output_path
    if args.output_dir is not None:
        return args.output_dir / ARTIFACT_FILES[artifact_name]
    raise V4VerificationError("output_path_required")


def _single(command: str, run_dir: Path, output_path: Path) -> int:
    artifact_name = _COMMAND_ARTIFACTS[command]
    if command == "gaps":
        graph = build_graph_artifact(run_dir)
        artifact = build_gap_artifact(run_dir, graph)
    elif command == "recover":
        graph = build_graph_artifact(run_dir)
        artifact = build_recovery_artifact(run_dir, graph)
    else:
        artifact = _BUILDERS[command](run_dir)

    errors = validate_v4_artifact(artifact_name, artifact, run_dir)
    path = write_v4_artifact(
        artifact_name,
        artifact,
        output_path=output_path,
    )
    payload = artifact.get("payload") if isinstance(artifact.get("payload"), dict) else None
    _print_result(
        "PASS" if not errors else "BLOCKED",
        path=path,
        errors=errors,
        payload=payload,
    )
    return 0 if not errors else 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        run_dir = _run_root(args.run_dir)
        if args.command == "verify":
            verification_path = _target(args, "verify")
            artifact = run_v4_verification(
                run_dir,
                output_path=verification_path,
            )
            payload = artifact.get("payload")
            payload = payload if isinstance(payload, dict) else {}
            status = payload.get("status")
            errors = payload.get("errors")
            errors = errors if isinstance(errors, list) else []
            _print_result(
                "PASS" if status == "PASS" else "BLOCKED",
                path=verification_path.resolve(),
                errors=errors,
                payload=payload,
            )
            return 0 if status == "PASS" else 1
        return _single(args.command, run_dir, _target(args, _COMMAND_ARTIFACTS[args.command]))
    except (OSError, ValueError, TypeError, KeyError, V4VerificationError) as exc:
        _print_result("BLOCKED", errors=[str(exc)])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
