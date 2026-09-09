"""Content-ready delivery, kept separate from publication governance.

The article team needs a clear answer to a practical question: are the current
Markdown files finished enough to hand to a human publisher?  That answer is
different from whether a batch has a human attestation, an R8 manifest, or
publication authorization.  This module makes that distinction explicit.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from article_group.final_review import BLOCKED, PUBLISHABLE, evaluate_batch

CONTENT_READY = "CONTENT_READY"
CONTENT_BLOCKED = "CONTENT_BLOCKED"
CONTENT_DELIVERY_SCHEMA = "content-delivery-v1"

_GOVERNANCE_MARKERS = (
    "human_editor_attestation=",
    "human_attestation_",
    "controller_acceptance=",
    "human_review_completed_by_nonhuman_provenance",
)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_H1_RE = re.compile(r"^\s{0,3}#\s+(?P<title>.+?)\s*$", re.MULTILINE)


def _is_governance_item(item: object) -> bool:
    if not isinstance(item, str):
        return False
    return any(marker in item for marker in _GOVERNANCE_MARKERS)


def assess_content_readiness(review_report: Mapping[str, Any]) -> dict[str, Any]:
    """Classify a final-review report for content handoff.

    ``PENDING`` is content-ready only when every remaining item is explicitly
    governance-only.  Missing independent review, stale facts, style warnings,
    evidence drift, and other quality findings remain blockers.
    """
    verdict = str(review_report.get("verdict", ""))
    raw_items = review_report.get("human_judgment_items", [])
    items = [item for item in raw_items if isinstance(item, str)] if isinstance(raw_items, list) else []

    if verdict == BLOCKED:
        blockers = list(items) or [str(review_report.get("reason", "final_review_blocked"))]
        return {
            "content_status": CONTENT_BLOCKED,
            "content_blockers": blockers,
            "governance_items": [],
        }
    if verdict == PUBLISHABLE:
        return {
            "content_status": CONTENT_READY,
            "content_blockers": [],
            "governance_items": [],
        }

    governance_items = [item for item in items if _is_governance_item(item)]
    content_blockers = [item for item in items if not _is_governance_item(item)]
    if verdict != "PENDING" and not content_blockers:
        content_blockers.append(f"unexpected_final_review_verdict:{verdict or 'missing'}")
    return {
        "content_status": CONTENT_READY if not content_blockers else CONTENT_BLOCKED,
        "content_blockers": content_blockers,
        "governance_items": governance_items,
    }


def _safe_relative_path(root: Path, raw: object) -> Path | None:
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


def _article_delivery_entry(root: Path, article: Mapping[str, Any]) -> dict[str, Any]:
    article_id = str(article.get("article_id", ""))
    raw_path = article.get("markdown_path")
    path = _safe_relative_path(root, raw_path)
    entry: dict[str, Any] = {
        "article_id": article_id,
        "title": article.get("title", ""),
        "markdown_path": raw_path,
    }
    if path is None or not path.is_file():
        entry["error"] = "markdown_missing_or_unsafe"
        return entry
    text = path.read_text(encoding="utf-8")
    title_match = _H1_RE.search(text)
    if not entry["title"] and title_match:
        entry["title"] = title_match.group("title").strip()
    entry["markdown_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    entry["cjk_chars"] = len(_CJK_RE.findall(text))
    return entry


def build_content_delivery_record(
    run_dir: Path,
    *,
    review_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a compact, user-facing content handoff record for one run."""
    if not isinstance(run_dir, Path) or not run_dir.is_dir():
        return {
            "schema_version": CONTENT_DELIVERY_SCHEMA,
            "content_status": CONTENT_BLOCKED,
            "content_blockers": ["run_dir_missing"],
            "governance_items": [],
        }

    batch_path = run_dir / "batch.json"
    try:
        batch = json.loads(batch_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {
            "schema_version": CONTENT_DELIVERY_SCHEMA,
            "content_status": CONTENT_BLOCKED,
            "content_blockers": ["batch_unreadable"],
            "governance_items": [],
        }
    if not isinstance(batch, dict):
        return {
            "schema_version": CONTENT_DELIVERY_SCHEMA,
            "content_status": CONTENT_BLOCKED,
            "content_blockers": ["batch_not_object"],
            "governance_items": [],
        }

    report = dict(review_report) if isinstance(review_report, Mapping) else evaluate_batch(run_dir)
    assessment = assess_content_readiness(report)
    blockers = list(assessment["content_blockers"])
    if batch.get("review_surface") != "markdown_codex":
        blockers.append("content_delivery_requires_markdown_codex")
    if batch.get("publication_authorization", "not_authorized") != "not_authorized":
        blockers.append("publication_authorization_must_remain_not_authorized")

    articles = batch.get("articles")
    if not isinstance(articles, list):
        articles = []
        blockers.append("batch_articles_invalid")
    entries = [_article_delivery_entry(run_dir, article) for article in articles if isinstance(article, Mapping)]
    blockers.extend(
        f"{entry.get('article_id', '?')}:{entry['error']}"
        for entry in entries
        if entry.get("error")
    )

    return {
        "schema_version": CONTENT_DELIVERY_SCHEMA,
        "run_id": batch.get("run_id", ""),
        "content_status": CONTENT_READY if not blockers else CONTENT_BLOCKED,
        "review_surface": batch.get("review_surface"),
        "final_review_verdict": report.get("verdict"),
        "final_review_path": "review/final-review.json",
        "publication_authorization": "not_authorized",
        "delivery_state": "content_ready_not_published" if not blockers else "withheld",
        "articles": entries,
        "content_blockers": blockers,
        "governance_items": assessment["governance_items"],
        "note": "CONTENT_READY 只表示文章可交给真人复制发布，不代表本系统已发布或授权发布。",
    }


def write_content_delivery_record(run_dir: Path, output: Path | None = None) -> Path:
    """Evaluate a run and write its content-only handoff record."""
    target = output or (run_dir / "review" / "content-delivery.json")
    record = build_content_delivery_record(run_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


__all__ = [
    "CONTENT_BLOCKED",
    "CONTENT_DELIVERY_SCHEMA",
    "CONTENT_READY",
    "assess_content_readiness",
    "build_content_delivery_record",
    "write_content_delivery_record",
]
