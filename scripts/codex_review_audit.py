#!/usr/bin/env python3
"""Backward-compatibility shim for scripts.dsh_review_audit."""
from __future__ import annotations

import sys
from scripts import dsh_review_audit

for _key, _val in dsh_review_audit.__dict__.items():
    if not _key.startswith("__"):
        globals()[_key] = _val

if __name__ == "__main__":
    sys.exit(dsh_review_audit.main())
