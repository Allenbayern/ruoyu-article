"""Backward-compatibility shim for article_group.dsh_review.

This module is retained as a compatibility layer. New code should use
`article_group.dsh_review` instead.
"""
from __future__ import annotations

import sys
import shutil
import subprocess
from article_group import dsh_review

# Forward all public and internal attributes for full test compatibility
for _key, _val in dsh_review.__dict__.items():
    if not _key.startswith("__"):
        globals()[_key] = _val

# Keep historical reason for compatibility with existing ledger checks
REASON_PREFIX = "codex_review"


def main() -> int:
    args = build_parser().parse_args()
    from article_group.evidence_write import RunSealedError

    try:
        orig_prefix = dsh_review.REASON_PREFIX
        dsh_review.REASON_PREFIX = "codex_review"
        try:
            return run_review(args)
        finally:
            dsh_review.REASON_PREFIX = orig_prefix
    except RunSealedError as exc:
        print(f"codex_review 拒绝写入：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
