#!/usr/bin/env python3
"""Write the content-only handoff record for a Ruoyu article run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from article_group.content_delivery import CONTENT_READY, write_content_delivery_record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    path = write_content_delivery_record(args.run_dir, args.output)
    record = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0 if record.get("content_status") == CONTENT_READY else 1


if __name__ == "__main__":
    raise SystemExit(main())
