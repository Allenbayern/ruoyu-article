#!/usr/bin/env python3
"""Create and validate the Markdown review-surface evidence manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from article_group.review_surface import (  # noqa: E402
    build_markdown_review_evidence,
    validate_batch_review_surface,
    validate_markdown_review_evidence,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    root = args.run_dir.resolve()
    batch_path = root / "batch.json"
    try:
        batch = json.loads(batch_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"INPUT_ERROR:{exc}", file=sys.stderr)
        return 2
    if not isinstance(batch, dict):
        print("INPUT_ERROR:batch_must_be_an_object", file=sys.stderr)
        return 2
    surface_errors = validate_batch_review_surface(batch, require_explicit=True)
    if surface_errors:
        print("INPUT_ERROR:" + ";".join(surface_errors), file=sys.stderr)
        return 2
    if batch.get("review_surface") != "markdown_codex":
        print("INPUT_ERROR:markdown_review_audit_requires_markdown_codex", file=sys.stderr)
        return 2

    try:
        payload = build_markdown_review_evidence(
            root,
            batch.get("articles", []),
            run_id=batch.get("run_id"),
        )
    except (TypeError, ValueError) as exc:
        print(f"INPUT_ERROR:{exc}", file=sys.stderr)
        return 2

    errors = validate_markdown_review_evidence(payload, root, batch.get("articles", []))
    if errors:
        print("VALIDATION_ERROR:" + ";".join(errors), file=sys.stderr)
        return 1

    output = (args.output or root / "review" / "markdown-review-evidence.json").resolve()
    try:
        output.relative_to(root)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"OUTPUT_ERROR:{exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
