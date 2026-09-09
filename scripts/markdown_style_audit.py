#!/usr/bin/env python3
"""Generate byte-bound style reports for a Markdown review surface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from article_group.review_surface import validate_batch_review_surface  # noqa: E402
from article_group.style_gate import validate_markdown_file  # noqa: E402


def _safe_path(root: Path, raw: object) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts or "\x00" in raw:
        return None
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)

    root = args.run_dir.resolve()
    try:
        batch = json.loads((root / "batch.json").read_text(encoding="utf-8"))
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
        print("INPUT_ERROR:markdown_style_audit_requires_markdown_codex", file=sys.stderr)
        return 2

    output_dir = (args.output_dir or root / "review").resolve()
    try:
        output_dir.relative_to(root)
        output_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"OUTPUT_ERROR:{exc}", file=sys.stderr)
        return 2

    failed = False
    for article in batch.get("articles", []):
        if not isinstance(article, dict):
            print("INPUT_ERROR:article_must_be_an_object", file=sys.stderr)
            return 2
        article_id = article.get("article_id")
        if (
            not isinstance(article_id, str)
            or not article_id.strip()
            or "/" in article_id
            or "\\" in article_id
            or "\x00" in article_id
        ):
            print("INPUT_ERROR:article_id_invalid", file=sys.stderr)
            return 2
        markdown = _safe_path(root, article.get("markdown_path"))
        if markdown is None or not markdown.is_file():
            print(f"INPUT_ERROR:markdown_missing:{article_id}", file=sys.stderr)
            return 2
        try:
            report = validate_markdown_file(
                markdown,
                hook=str(
                    article.get("review_hook")
                    or article.get("work")
                    or article.get("primary_atom")
                    or article.get("reader_question")
                    or ""
                ),
            )
            target = output_dir / f"style-gate-markdown-{article_id}.json"
            target.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except (OSError, UnicodeError) as exc:
            print(f"OUTPUT_ERROR:{article_id}:{exc}", file=sys.stderr)
            return 2
        failed = failed or not bool(report.get("pass"))
        print(target)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
