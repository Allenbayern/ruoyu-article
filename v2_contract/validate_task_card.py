"""Validate a V2 task card against the frozen schema and state vocabulary."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker
from yaml import YAMLError, safe_load


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "docs/plans/ruoyu-production-v2/2026-08-11-contract-v1.0/task-card-v1.0.schema.json"
DEFAULT_VOCABULARY = ROOT / "docs/plans/ruoyu-production-v2/2026-08-11-contract-v1.0/state-vocabulary-v1.0.yaml"
VARIANT_PATHS = {
    "dr_02_variant": ("review_policy", "dr_02_variant"),
    "dr_07_variant": ("recovery_mode", "dr_07_variant"),
    "dr_03_variant": ("daily_output_policy", "dr_03_variant"),
}
VARIANT_DECISIONS = {
    "dr_02_variant": "DR-02",
    "dr_07_variant": "DR-07",
    "dr_03_variant": "DR-03",
}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return payload


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML document must be a mapping: {path}")
    return payload


def _path_label(parts: Iterable[object]) -> str:
    values = list(parts)  # jsonschema's deque is intentionally sequence-like.
    return "/".join(str(value) for value in values) or "$"


def _schema_errors(document: Any, schema: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(document),
        key=lambda error: (list(error.absolute_path), list(error.absolute_schema_path), error.message),
    )
    return [f"schema.{error.validator}:{_path_label(error.absolute_path)}:{error.message}" for error in errors]


def _nested_mapping(document: object, key: str) -> dict[str, Any]:
    if not isinstance(document, dict):
        return {}
    value = document.get(key)
    return value if isinstance(value, dict) else {}


def _schema_variant_consts(schema: dict[str, Any]) -> dict[str, object]:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return {}

    expected: dict[str, object] = {}
    for field, (parent, child) in VARIANT_PATHS.items():
        parent_schema = properties.get(parent)
        if not isinstance(parent_schema, dict):
            continue
        nested_properties = parent_schema.get("properties")
        if not isinstance(nested_properties, dict):
            continue
        child_schema = nested_properties.get(child)
        if isinstance(child_schema, dict) and "const" in child_schema:
            expected[field] = child_schema["const"]
    return expected


def _state_enum_errors(schema: dict[str, Any], vocabulary: dict[str, Any]) -> list[str]:
    properties = schema.get("properties")
    states = vocabulary.get("states")
    if not isinstance(properties, dict) or not isinstance(states, dict):
        return ["state_enum_cross_check_unavailable"]

    state_schema = properties.get("state")
    enum = state_schema.get("enum") if isinstance(state_schema, dict) else None
    if not isinstance(enum, list) or not all(isinstance(value, str) for value in enum):
        return ["state_enum_missing_or_invalid"]

    schema_states = set(enum)
    vocabulary_states = set(states)
    errors: list[str] = []
    missing = sorted(vocabulary_states - schema_states)
    extra = sorted(schema_states - vocabulary_states)
    if missing:
        errors.append(f"state_enum_missing_from_schema:{','.join(missing)}")
    if extra:
        errors.append(f"state_enum_not_in_vocabulary:{','.join(extra)}")
    return errors


def _variant_const_errors(schema: dict[str, Any], vocabulary: dict[str, Any]) -> list[str]:
    decision_points = vocabulary.get("variant_decision_points")
    if not isinstance(decision_points, dict):
        return ["variant_decision_cross_check_unavailable"]

    errors: list[str] = []
    schema_consts = _schema_variant_consts(schema)
    errors.extend(
        f"variant_const_missing_from_schema:{field}"
        for field in VARIANT_PATHS
        if field not in schema_consts
    )
    for field, schema_value in schema_consts.items():
        decision = decision_points.get(VARIANT_DECISIONS[field])
        vocabulary_value = decision.get("status") if isinstance(decision, dict) else None
        if schema_value != vocabulary_value:
            errors.append(
                f"variant_const_not_in_vocabulary:{field}:"
                f"schema={schema_value}:vocabulary={vocabulary_value}"
            )
    return errors


def _cross_check_errors(document: object, schema: dict[str, Any], vocabulary: dict[str, Any]) -> list[str]:
    errors = _state_enum_errors(schema, vocabulary) + _variant_const_errors(schema, vocabulary)
    if not isinstance(document, dict):
        return errors

    state = document.get("state")
    states = vocabulary.get("states")
    known_states = set(states) if isinstance(states, dict) else set()
    if isinstance(state, str) and state not in known_states:
        errors.append(f"state_not_in_vocabulary:{state}")

    gate_status = _nested_mapping(document, "gate_status")
    authorization = document.get("publication_authorization")
    delivery_state = document.get("delivery_state")
    if state == "R8 review-ready":
        if authorization != "not_authorized":
            errors.append("r8_publication_authorization_must_be_not_authorized")
        if gate_status.get("independent_review") != "approve":
            errors.append("r8_independent_review_must_be_approve")
    elif state == "publication-authorized":
        if authorization != "granted":
            errors.append("publication_authorized_authorization_must_be_granted")
        if delivery_state != "published":
            errors.append("publication_authorized_delivery_state_must_be_published")
    elif state == "H4 draft-only" and authorization != "not_authorized":
        errors.append("h4_publication_authorization_must_be_not_authorized")

    for field, expected in _schema_variant_consts(schema).items():
        parent, child = VARIANT_PATHS[field]
        actual = _nested_mapping(document, parent).get(child)
        if actual != expected:
            errors.append(f"variant_const_mismatch:{field}:expected={expected}:actual={actual}")

    return errors


def validate_task_card(
    document: Any,
    schema_path: Path = DEFAULT_SCHEMA,
    vocabulary_path: Path = DEFAULT_VOCABULARY,
) -> list[str]:
    """Return deterministic schema and contract-cross-check errors for one task card."""
    schema = _load_json(schema_path)
    vocabulary = _load_yaml(vocabulary_path)
    return _schema_errors(document, schema) + _cross_check_errors(document, schema, vocabulary)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_card", type=Path, help="JSON task-card document to validate")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA, help="Frozen task-card JSON Schema")
    parser.add_argument("--vocabulary", type=Path, default=DEFAULT_VOCABULARY, help="Frozen state vocabulary YAML")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        errors = validate_task_card(_load_json(args.task_card), args.schema, args.vocabulary)
    except (OSError, ValueError, json.JSONDecodeError, YAMLError) as exc:
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
