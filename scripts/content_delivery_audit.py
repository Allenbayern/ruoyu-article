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
from article_group.evidence_write import RunSealedError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--force", action="store_true",
                        help="run 已封存时仍写入（controller 决定；走留底+记账）")
    args = parser.parse_args()
    try:
        path = write_content_delivery_record(args.run_dir, args.output, force=args.force)
    except RunSealedError as exc:  # 封存拒绝要给一句人话，不要 traceback
        print(f"content_delivery 拒绝写入：{exc}", file=sys.stderr)
        return 2
    record = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0 if record.get("content_status") == CONTENT_READY else 1


if __name__ == "__main__":
    raise SystemExit(main())
