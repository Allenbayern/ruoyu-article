#!/usr/bin/env python3
"""Ad-hoc F3 checker for the saved pages in the scoped repair artifact."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


EXPECTED = {
    "https://www.1905.com/news/20260425/1759020.shtml": {
        "institution": "1905电影网",
        "source_program": "中国电影报道",
        "author": None,
        "reporters": ["徐嘉", "徐玉凡", "肖金石", "邵小涛", "王建勋", "张君浩"],
        "editors": ["小赛"],
        "published_at": "2026-04-25",
    },
    "https://www.1905.com/mdb/film/2259123/": {
        "institution": "1905电影网",
        "source_program": None,
        "author": None,
        "reporters": [],
        "editors": [],
        "published_at": None,
    },
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads(args.audit.read_text(encoding="utf-8"))
    found = {row["canonical_url"]: row for row in rows}
    for url, expected in EXPECTED.items():
        row = found.get(url)
        if row is None:
            print("F3_PAGE_MISSING")
            return 1
        if any(row.get(field) != value for field, value in expected.items()):
            print("F3_VISIBLE_METADATA_MISMATCH")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
