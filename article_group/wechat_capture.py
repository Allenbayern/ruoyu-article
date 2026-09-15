"""Capture a public WeChat article into a run-local evidence snapshot."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from article_group.wechat import WechatExtractionError, fetch_wechat_article


_SOURCE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


def _safe_source_id(source_id: str) -> bool:
    return isinstance(source_id, str) and bool(_SOURCE_ID_RE.fullmatch(source_id))


def _sha256_file(file_path: Path) -> str:
    return hashlib.sha256(file_path.read_bytes()).hexdigest()


def _validate_sources_dir(root: Path, sources_dir: Path) -> None:
    if sources_dir.exists() and sources_dir.is_symlink():
        raise ValueError(f"sources directory escapes run root: {sources_dir}")
    if sources_dir.resolve().parent != root:
        raise ValueError(f"sources directory escapes run root: {sources_dir}")


def capture_wechat_source(
    url: str,
    run_root: str | Path,
    source_id: str,
    role: str = "confirmed-primary",
    independence_group: str = "",
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Fetch and snapshot one public WeChat article for a controlled run.

    The raw HTML is deliberately not persisted.  The clean body, metadata,
    capture method, and SHA-256 are stored under ``run_root/sources`` so a
    later material manifest can bind claims to the exact captured text.
    """
    if not _safe_source_id(source_id):
        raise ValueError(f"source_id must be a safe filename component: {source_id!r}")

    root = Path(run_root).resolve()
    sources_dir = root / "sources"
    _validate_sources_dir(root, sources_dir)

    snapshot_path = sources_dir / f"{source_id}.clean.md"
    metadata_path = sources_dir / f"{source_id}.source.json"
    if snapshot_path.exists() or metadata_path.exists():
        raise ValueError(f"snapshot already exists: {snapshot_path}")

    article_data = fetch_wechat_article(url, timeout=timeout)
    body = article_data.get("body", "")
    if not isinstance(body, str) or not body.strip():
        raise WechatExtractionError("static_body_missing")
    body = body.rstrip() + "\n"

    # Re-check the boundary after the network operation in case the directory
    # was replaced while the request was in flight.
    _validate_sources_dir(root, sources_dir)
    sources_dir.mkdir(parents=True, exist_ok=True)
    _validate_sources_dir(root, sources_dir)

    try:
        with snapshot_path.open("x", encoding="utf-8", newline="\n") as snapshot_file:
            snapshot_file.write(body)
    except FileExistsError as error:
        raise ValueError(f"snapshot already exists: {snapshot_path}") from error

    digest = _sha256_file(snapshot_path)
    captured_at = datetime.now(timezone.utc).isoformat()
    relative_path = str(snapshot_path.relative_to(root))
    metadata = {
        "source_id": source_id,
        "source": "wechat",
        "requested_url": url,
        "fetch_url": article_data.get("fetch_url", article_data["canonical_url"]),
        "canonical_url": article_data["canonical_url"],
        "page_canonical_url": article_data.get("page_canonical_url", ""),
        "title": article_data.get("title", ""),
        "author": article_data.get("author", ""),
        "account_name": article_data.get("account_name", ""),
        "publish_time": article_data.get("publish_time", ""),
        "body_path": relative_path,
        "clean_sha256": digest,
        "capture_status": "full",
        "capture_method": article_data.get("fetch_method", "direct_html"),
        "capture_type": "page_fulltext",
        "declared_source_level": "fulltext",
        "role": role,
        "independence_group": independence_group,
        "captured_at": captured_at,
    }
    try:
        with metadata_path.open("x", encoding="utf-8", newline="\n") as metadata_file:
            json.dump(metadata, metadata_file, ensure_ascii=False, indent=2, sort_keys=True)
            metadata_file.write("\n")
    except FileExistsError as error:
        raise ValueError(f"snapshot already exists: {metadata_path}") from error

    return {
        "source_id": source_id,
        "relative_path": relative_path,
        "sha256": digest,
        "url": article_data["canonical_url"],
        "requested_url": url,
        "role": role,
        "independence_group": independence_group,
        "captured_at": captured_at,
        "source": "wechat",
        "title": article_data.get("title", ""),
        "author": article_data.get("author", ""),
        "account_name": article_data.get("account_name", ""),
        "publish_time": article_data.get("publish_time", ""),
        "capture_status": "full",
        "capture_method": article_data.get("fetch_method", "direct_html"),
        "capture_type": "page_fulltext",
        "declared_source_level": "fulltext",
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch a public WeChat article body.")
    parser.add_argument("url", help="Public mp.weixin.qq.com article URL")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--json", action="store_true", help="Print metadata and body as JSON")
    parser.add_argument("--run-root", type=Path, help="Capture under <run-root>/sources")
    parser.add_argument("--source-id", help="Source ID used for the evidence snapshot")
    parser.add_argument("--role", default="confirmed-primary")
    parser.add_argument("--independence-group", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if bool(args.run_root) != bool(args.source_id):
        parser.error("--run-root and --source-id must be supplied together")

    try:
        if args.run_root is not None:
            result: dict[str, Any] = capture_wechat_source(
                args.url,
                args.run_root,
                args.source_id,
                role=args.role,
                independence_group=args.independence_group,
                timeout=args.timeout,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0

        result = fetch_wechat_article(args.url, timeout=args.timeout)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"# {result['title']}\n\n{result['body']}")
        return 0
    except (WechatExtractionError, ValueError) as error:
        print(f"wechat_fetch_error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI
    raise SystemExit(main())


__all__ = ["capture_wechat_source", "main"]
