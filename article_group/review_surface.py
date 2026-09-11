"""Review-surface contracts for Markdown-first article production.

The normal review surface is the current Markdown draft.  The historical HTML
surface remains readable for explicitly legacy batches, but it is not part of
the Markdown path's evidence or acceptance contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path
import re
from typing import Any, Iterable

from article_group.run_profile import MAX_CJK_CHARS, MIN_CJK_CHARS

DEFAULT_REVIEW_SURFACE = "markdown_codex"
REVIEW_SURFACES = ("markdown_codex", "html_delivery")
MARKDOWN_REVIEW_EVIDENCE_SCHEMA = "markdown-review-evidence-v1"
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_CJK_RE = re.compile(r"[㐀-䶿一-鿿]")


def resolve_review_surface(value: object) -> str:
    """Resolve an optional surface, defaulting new callers to Markdown."""
    if value is None:
        return DEFAULT_REVIEW_SURFACE
    if not isinstance(value, str) or not value.strip():
        raise ValueError("review_surface_invalid")
    surface = value.strip()
    if surface not in REVIEW_SURFACES:
        raise ValueError(f"review_surface_invalid:{surface}")
    return surface


def validate_batch_review_surface(
    batch: dict[str, Any], *, require_explicit: bool = False
) -> list[str]:
    """Validate the batch-level review surface without inspecting artifacts."""
    if "review_surface" not in batch:
        return ["review_surface_missing"] if require_explicit else []

    raw = batch.get("review_surface")
    if not isinstance(raw, str) or not raw.strip():
        return ["review_surface_invalid"]

    surface = raw.strip()
    if surface not in REVIEW_SURFACES:
        return [f"review_surface_invalid:{surface}"]

    if surface == DEFAULT_REVIEW_SURFACE and "preview_mode" in batch:
        return ["preview_mode_forbidden_for_markdown_surface"]
    return []


def _resolve_inside(root: Path, raw: object) -> Path | None:
    if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    try:
        resolved = (root.resolve() / candidate).resolve()
        resolved.relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved


def _article_id(article: object) -> str | None:
    if not isinstance(article, dict):
        return None
    raw = article.get("article_id")
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip()
    if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        return None
    return value


def _cjk_count(text: str) -> int:
    return len(_CJK_RE.findall(text))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _review_markdown_path(article: dict[str, Any]) -> object:
    """Use final delivery.md for article-first records, legacy markdown otherwise."""

    return article.get("delivery_path") or article.get("markdown_path")


def build_markdown_review_evidence(
    root: Path, articles: Iterable[dict[str, Any]], *, run_id: str | None = None
) -> dict[str, Any]:
    """Build a byte-bound Markdown manifest for the supplied batch articles."""
    root = root.resolve()
    entries: dict[str, dict[str, Any]] = {}
    for article in articles:
        article_id = _article_id(article)
        if article_id is None:
            raise ValueError("markdown_evidence_article_id_invalid")
        if article_id in entries:
            raise ValueError(f"markdown_evidence_article_duplicate:{article_id}")
        raw_path = _review_markdown_path(article)
        target = _resolve_inside(root, raw_path)
        if target is None:
            raise ValueError(f"markdown_evidence_path_unsafe:{article_id}")
        try:
            data = target.read_bytes()
            text = data.decode("utf-8")
        except FileNotFoundError as exc:
            raise ValueError(f"markdown_evidence_file_missing:{article_id}") from exc
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"markdown_evidence_file_unreadable:{article_id}") from exc
        entries[article_id] = {
            "markdown_path": str(Path(raw_path)),
            "size": len(data),
            "markdown_sha256": _sha256(data),
            "cjk_chars": _cjk_count(text),
        }

    payload: dict[str, Any] = {
        "schema_version": MARKDOWN_REVIEW_EVIDENCE_SCHEMA,
        "review_surface": DEFAULT_REVIEW_SURFACE,
        "generated_at": datetime.now(UTC).isoformat(),
        "articles": entries,
    }
    if run_id:
        payload["run_id"] = run_id
    return payload


def validate_markdown_review_evidence(
    payload: dict[str, Any] | None,
    root: Path,
    articles: Iterable[dict[str, Any]],
) -> list[str]:
    """Fail closed when evidence no longer describes current Markdown bytes."""
    if not isinstance(payload, dict):
        return ["markdown_evidence_unreadable"]
    errors: list[str] = []
    if payload.get("schema_version") != MARKDOWN_REVIEW_EVIDENCE_SCHEMA:
        errors.append("markdown_evidence_schema_version_invalid")
    if payload.get("review_surface") != DEFAULT_REVIEW_SURFACE:
        errors.append("markdown_evidence_review_surface_invalid")

    expected: dict[str, dict[str, Any]] = {}
    for article in articles:
        article_id = _article_id(article)
        if article_id is None:
            errors.append("markdown_evidence_batch_article_invalid")
            continue
        if article_id in expected:
            errors.append(f"markdown_evidence_batch_article_duplicate:{article_id}")
            continue
        expected[article_id] = article

    manifest = payload.get("articles")
    if not isinstance(manifest, dict):
        return [*errors, "markdown_evidence_articles_invalid"]

    actual_ids = set(manifest)
    for article_id in sorted(set(expected) - actual_ids):
        errors.append(f"markdown_evidence_article_missing:{article_id}")
    for article_id in sorted(actual_ids - set(expected)):
        errors.append(f"markdown_evidence_article_extra:{article_id}")

    root = root.resolve()
    paths_seen: dict[str, str] = {}
    for article_id, article in expected.items():
        entry = manifest.get(article_id)
        if not isinstance(entry, dict):
            errors.append(f"markdown_evidence_entry_invalid:{article_id}")
            continue
        declared_path = entry.get("markdown_path")
        expected_path = _review_markdown_path(article)
        if declared_path != expected_path:
            errors.append(f"markdown_evidence_path_mismatch:{article_id}")
        target = _resolve_inside(root, declared_path)
        if target is None:
            errors.append(f"markdown_evidence_path_unsafe:{article_id}")
            continue
        path_key = str(target)
        previous_id = paths_seen.get(path_key)
        if previous_id is not None:
            errors.append(f"markdown_evidence_path_duplicate:{article_id}:{previous_id}")
        else:
            paths_seen[path_key] = article_id
        if not target.is_file():
            errors.append(f"markdown_evidence_file_missing:{article_id}")
            continue
        try:
            data = target.read_bytes()
            text = data.decode("utf-8")
        except (OSError, UnicodeError):
            errors.append(f"markdown_evidence_file_unreadable:{article_id}")
            continue

        declared_size = entry.get("size")
        if isinstance(declared_size, bool) or not isinstance(declared_size, int):
            errors.append(f"markdown_evidence_size_invalid:{article_id}")
        elif declared_size != len(data):
            errors.append(f"markdown_evidence_size_mismatch:{article_id}")

        declared_hash = entry.get("markdown_sha256")
        if not isinstance(declared_hash, str) or not _SHA256_RE.fullmatch(declared_hash):
            errors.append(f"markdown_evidence_hash_invalid:{article_id}")
        elif declared_hash.lower() != _sha256(data):
            errors.append(f"markdown_evidence_hash_mismatch:{article_id}")

        actual_cjk = _cjk_count(text)
        declared_cjk = entry.get("cjk_chars")
        if isinstance(declared_cjk, bool) or not isinstance(declared_cjk, int):
            errors.append(f"markdown_evidence_cjk_count_invalid:{article_id}")
        elif declared_cjk != actual_cjk:
            errors.append(f"markdown_evidence_cjk_count_mismatch:{article_id}")
        if not MIN_CJK_CHARS <= actual_cjk <= MAX_CJK_CHARS:
            errors.append(
                f"markdown_evidence_cjk_count_out_of_range:{article_id}:{actual_cjk}"
            )
    return errors
