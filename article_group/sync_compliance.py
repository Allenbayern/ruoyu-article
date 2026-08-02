"""Synchronise five-gates declarations from candidate JSONs into a Markdown checklist.

Usage:
    python -m article_group.sync_compliance \\
        --input path/to/candidates.json \\
        --output path/to/sync-checklist.md

    python -m article_group.sync_compliance \\
        --input path/to/candidates_dir/ \\
        --output path/to/sync-checklist.md

The script reads one or more candidate JSON files (each either a single candidate
object or a pool with a "candidates" list), filters for social-topic
candidates, and renders a Markdown table summarising their five-gates
declaration. This can be used as a quick audit during S1 candidate discovery.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from article_group.compliance_gate import (
    GATE_KEYS,
    GRADE_CONDITIONAL,
    GRADE_FAIL,
    GRADE_PASS,
)


def _load_json_file(path: Path) -> list[dict[str, Any]]:
    """Load a JSON file and return a list of candidate dicts."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "candidates" in data:
        return data["candidates"]
    if isinstance(data, list):
        return data
    # Assume a single candidate object
    return [data]


def iter_candidate_files(input_path: Path):
    """Yield (source_path, candidate_dict) for all candidates under input_path."""
    if input_path.is_file():
        for cand in _load_json_file(input_path):
            yield input_path, cand
    elif input_path.is_dir():
        for root, _, files in os.walk(input_path):
            for name in files:
                if name.endswith(".json"):
                    p = Path(root) / name
                    for cand in _load_json_file(p):
                        yield p, cand
    else:
        raise ValueError(f"Input path does not exist: {input_path}")


def format_gate(value: str) -> str:
    if value == GRADE_PASS:
        return "✅ PASS"
    if value == GRADE_FAIL:
        return "❌ FAIL"
    if value == GRADE_CONDITIONAL:
        return "🟡 CONDITIONAL"
    return "⚪ N/A"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a five-gates checklist from candidate JSON files."
    )
    parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Path to a candidate JSON file or a directory containing such files.",
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Path to write the Markdown checklist.",
    )
    args = parser.parse_args(argv)

    in_path = Path(args.input)
    out_path = Path(args.output)

    rows: list[dict[str, str]] = []
    for src, cand in iter_candidate_files(in_path):
        cand_id = str(cand.get("candidate_id", "unknown"))
        topic_type = str(cand.get("topic_type", "")).strip().lower()
        if topic_type != "social":
            continue  # only social candidates go into the checklist

        gates = cand.get("five_gates", {})
        # Ensure we have entries for all five gates
        row = {
            "候选 ID": cand_id,
            "来源文件": str(src),
            "新闻资质": format_gate(gates.get("gate1_news_license", "")),
            "个人隐私": format_gate(gates.get("gate2_privacy", "")),
            "司法状态": format_gate(gates.get("gate3_judicial", "")),
            "版权来源": format_gate(gates.get("gate4_copyright", "")),
            "猎奇风险": format_gate(gates.get("gate5_sensationalism", "")),
            "总结果": format_gate(gates.get("overall", gates.get("result", ""))),
            "推荐": str(cand.get("recommendation", "")),
            "合规处理说明": str(cand.get("compliant_angle", ""))
            if gates.get("overall", gates.get("result")) == GRADE_CONDITIONAL
            else "",
        }
        rows.append(row)

    if not rows:
        out_path.write_text(
            "# 五 Gates 检查表（同步自候选 JSON）\n\n未发现任何社会热点候选（topic_type=social）。\n",
            encoding="utf-8",
        )
        return 0

    # Build markdown table
    headers = [
        "候选 ID",
        "来源文件",
        "新闻资质",
        "个人隐私",
        "司法状态",
        "版权来源",
        "猎奇风险",
        "总结果",
        "推荐",
        "合规处理说明",
    ]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(r[h] for h in headers) + " |")

    out_path.write_text(
        "# 五 Gates 检查表（同步自候选 JSON）\n\n"
        + "此表由 `python -m article_group.sync_compliance` 自動生成，用於 S1 階段快速審計。\n\n"
        + "\n".join(lines)
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] if len(sys.argv) > 1 else None))