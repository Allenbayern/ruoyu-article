"""Manual Toutiao source-capture utility for evidence snapshots."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any

from article_group.toutiao import (
    ToutiaoExtractionError,
    fetch_toutiao_article,
)


_SOURCE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


def _safe_source_id(source_id: str) -> bool:
    """Return True for a single safe filename component used as a source ID."""
    return bool(_SOURCE_ID_RE.fullmatch(source_id))


def _sha256_file(file_path: Path) -> str:
    """Return SHA-256 hex digest of file contents."""
    return hashlib.sha256(file_path.read_bytes()).hexdigest()


def capture_toutiao_source(
    url: str,
    run_root: str | Path,
    source_id: str,
    role: str = "confirmed-primary",
    independence_group: str = "",
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """
    Manually invoke Toutiao source capture for evidence snapshot.

    Fetches article via existing fetch_toutiao_article, writes body snapshot
    to run_root/sources/<source_id>.txt, returns manifest-compatible mapping.

    Args:
        url: Original Toutiao article URL
        run_root: Run root directory path
        source_id: Unique source identifier (used for snapshot filename)
        role: Source role in manifest (default: confirmed-primary)
        independence_group: Independence group for source
        timeout: HTTP request timeout in seconds (default: 30.0)

    Returns:
        Manifest-compatible dict with keys:
        source_id, relative_path, sha256, url, role, independence_group, captured_at

    Raises:
        ToutiaoExtractionError: If article fetch/extraction fails
        ValueError: If source_id is not safe for file path or snapshot exists
    """
    # Validate source_id for safe path usage
    if not isinstance(source_id, str) or not _safe_source_id(source_id):
        raise ValueError(f"source_id must be a safe filename component: {source_id!r}")

    snapshot_filename = f"{source_id}.txt"
    root = Path(run_root).resolve()
    sources_dir = root / "sources"
    snapshot_path = sources_dir / snapshot_filename
    if snapshot_path.exists():
        raise ValueError(f"snapshot already exists: {snapshot_path}")

    article_data = fetch_toutiao_article(url, timeout=timeout)

    body = article_data.get("body", "")
    if not isinstance(body, str) or not body:
        raise ToutiaoExtractionError("static_body_missing")

    sources_dir.mkdir(parents=True, exist_ok=True)
    if sources_dir.is_symlink() or sources_dir.resolve().parent != root:
        raise ValueError(f"sources directory escapes run root: {sources_dir}")
    try:
        with snapshot_path.open("x", encoding="utf-8") as snapshot_file:
            snapshot_file.write(body)
    except FileExistsError as error:
        raise ValueError(f"snapshot already exists: {snapshot_path}") from error

    # Compute SHA-256 of written snapshot
    snapshot_digest = _sha256_file(snapshot_path)

    # Build manifest-compatible mapping
    from datetime import datetime, timezone

    manifest_entry = {
        "source_id": source_id,
        "relative_path": str(snapshot_path.relative_to(root)),
        "sha256": snapshot_digest,
        "url": article_data["canonical_url"],  # canonical mobile URL
        "role": role,
        "independence_group": independence_group,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }

    return manifest_entry