"""Manual CLI: five-gates compliance declaration check for social candidates.

Reads a candidate pool (or a single candidate) JSON and prints a deterministic
three-state declaration report. Exit code 0 means each declaration passes the
validator; it does not mean every candidate's declared overall grade is PASS.
Exit code 2 means the input is invalid or at least one declaration is invalid.

Usage:
    python -m article_group.compliance_cli --pool pool.json
    python -m article_group.compliance_cli --candidate candidate.json
    cat pool.json | python -m article_group.compliance_cli
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from article_group.compliance_gate import (
    SOCIAL_TOPIC_TYPE,
    scan_social_redlines,
    validate_five_gates,
    validate_pool_five_gates,
)


def _load_input(path: str | None) -> dict[str, Any]:
    if path:
        raw = Path(path).read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid_json:{error}") from error
    if not isinstance(data, dict):
        raise ValueError("input_must_be_a_json_object")
    return data


def _single_candidate_report(candidate: dict[str, Any]) -> dict[str, Any]:
    errors = validate_five_gates(candidate)
    cid = candidate.get("candidate_id", "unknown")
    topic_type = str(candidate.get("topic_type", "")).strip().lower()
    gates = candidate.get("five_gates")
    overall = "N/A"
    if topic_type == SOCIAL_TOPIC_TYPE and isinstance(gates, dict):
        overall = gates.get("overall", gates.get("result", "N/A"))

    report: dict[str, Any] = {
        "candidate_id": cid,
        "topic_type": topic_type,
        "compliant": not errors,
        "declaration_valid": not errors,
        "errors": errors,
        "overall": overall,
        "recommendation": candidate.get("recommendation"),
    }
    if "compliant_angle" in candidate:
        report["compliant_angle"] = candidate["compliant_angle"]
    if topic_type == SOCIAL_TOPIC_TYPE:
        text = " ".join(
            str(candidate.get(field) or "")
            for field in ("work", "core_person_or_event", "primary_atom", "angle", "title_skeleton")
        )
        report["redline_scan"] = scan_social_redlines(text)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Five-gates compliance check for social hot-topic candidates."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--pool", help="Path to a candidate pool JSON (has 'candidates' list)")
    group.add_argument("--candidate", help="Path to a single candidate JSON")
    parser.add_argument("--json", action="store_true", help="Print full JSON report to stdout")
    args = parser.parse_args(argv)

    try:
        data = _load_input(args.pool or args.candidate)
    except ValueError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2

    if args.candidate:
        reports = [_single_candidate_report(data)]
        errors = reports[0]["errors"]
    else:
        errors = validate_pool_five_gates(data)
        candidates = data.get("candidates", []) if isinstance(data.get("candidates"), list) else []
        reports = [_single_candidate_report(candidate) for candidate in candidates]

    declaration_valid = not errors
    grade_counts = {
        grade: sum(1 for report in reports if report["overall"] == grade)
        for grade in ("PASS", "CONDITIONAL", "FAIL")
    }
    summary = {
        "compliant": declaration_valid,
        "declaration_valid": declaration_valid,
        "candidate_count": len(reports),
        "invalid_declaration_count": sum(
            1 for report in reports if not report["declaration_valid"]
        ),
        "grade_counts": grade_counts,
        "errors": errors,
        "reports": reports,
        "summary": (
            "All declarations are validator-valid; declared grades may include "
            "PASS, CONDITIONAL, or FAIL."
            if declaration_valid
            else "One or more declarations are validator-invalid."
        ),
    }
    if args.candidate:
        summary["overall"] = reports[0]["overall"]
        summary["recommendation"] = reports[0]["recommendation"]
        if "compliant_angle" in reports[0]:
            summary["compliant_angle"] = reports[0]["compliant_angle"]
    if args.json or not declaration_valid:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    else:
        print(
            "VALID: "
            f"{len(reports)} candidate(s) checked; "
            f"PASS={grade_counts['PASS']}, "
            f"CONDITIONAL={grade_counts['CONDITIONAL']}, "
            f"FAIL={grade_counts['FAIL']}."
        )
    return 0 if declaration_valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
