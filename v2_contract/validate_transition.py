"""Validate a proposed V2 state transition against the frozen vocabulary."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from yaml import YAMLError, safe_load


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VOCABULARY = ROOT / "docs/plans/ruoyu-production-v2/2026-08-11-contract-v1.0/state-vocabulary-v1.0.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML document must be a mapping: {path}")
    return payload


def _known_states(vocabulary: dict[str, Any]) -> set[str]:
    states = vocabulary.get("states")
    return set(states) if isinstance(states, dict) else set()


def _allowed_transitions(vocabulary: dict[str, Any]) -> set[tuple[str, str]]:
    states = vocabulary.get("states")
    if not isinstance(states, dict):
        return set()

    allowed: set[tuple[str, str]] = set()
    for current, state_definition in states.items():
        if not isinstance(current, str) or not isinstance(state_definition, dict):
            continue
        exits = state_definition.get("exits")
        if not isinstance(exits, list):
            continue
        for target in exits:
            if isinstance(target, str):
                allowed.add((current, target))
    return allowed


def validate_transition(
    current: object,
    target: object,
    vocabulary_path: Path = DEFAULT_VOCABULARY,
) -> list[str]:
    """Return deterministic errors when a direct transition is absent from the contract."""
    vocabulary = _load_yaml(vocabulary_path)
    errors: list[str] = []
    known_states = _known_states(vocabulary)

    if not isinstance(current, str) or current not in known_states:
        errors.append(f"unknown_source_state:{current}")
    if not isinstance(target, str) or target not in known_states:
        errors.append(f"unknown_target_state:{target}")
    if (current, target) not in _allowed_transitions(vocabulary):
        errors.append(f"invalid_transition:{current}->{target}")
    return errors


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("current", help="Current contract state")
    parser.add_argument("target", help="Requested direct target state")
    parser.add_argument("--vocabulary", type=Path, default=DEFAULT_VOCABULARY, help="Frozen state vocabulary YAML")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        errors = validate_transition(args.current, args.target, args.vocabulary)
    except (OSError, ValueError, YAMLError) as exc:
        print(f"INPUT_ERROR:{exc}", file=sys.stderr)
        return 2

    if errors:
        print("INVALID")
        print("\n".join(errors))
        return 1

    print("VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
