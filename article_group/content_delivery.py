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

from article_group.article_first import (
    ARTICLE_FIRST_CONTRACT_VERSION,
    is_article_first_record,
    validate_phase_field_boundary,
)
from article_group.content_fidelity import content_body_path, evaluate_content_fidelity
from article_group.delivery import compose_delivery_markdown, validate_body_draft, validate_delivery_markdown
from article_group.final_review import (
    BLOCKED,
    PUBLISHABLE,
    build_final_review_record,
    validate_final_review_record,
)
from article_group.run_contract import (
    is_strict_run_contract,
    validate_article_first_run_lane,
    validate_phase_contract_fields,
    validate_referenced_contract_artifacts,
    validate_run_contract,
)
from article_group.title_pack_fidelity import evaluate_title_pack, evaluate_title_review

CONTENT_READY = "CONTENT_READY"
CONTENT_BLOCKED = "CONTENT_BLOCKED"
CONTENT_DELIVERY_SCHEMA = "content-delivery-v1"

_GOVERNANCE_MARKERS = (
    "human_editor_attestation=",
    "human_attestation_",
    "human_readability_attestation=",
    "controller_acceptance=",
    "human_review_completed_by_nonhuman_provenance",
    "independent_review=",
    "delivery_state=",
    "html_delivery_state=",
    "editorial-review-record",
    "评分卡为历史模板常量",
)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_H1_RE = re.compile(r"^\s{0,3}#\s+(?P<title>.+?)\s*$", re.MULTILINE)


def _delivery_error_record(
    reason: str,
    *,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    """Keep the four review dimensions present on every delivery outcome."""

    blockers = list(dict.fromkeys([reason, *(errors or [])]))
    return {
        "schema_version": CONTENT_DELIVERY_SCHEMA,
        "content_status": CONTENT_BLOCKED,
        "content_result": "UNKNOWN",
        "evidence_result": "FAIL",
        "governance_result": "PENDING",
        "article_rule_compliance": "UNVERIFIED",
        "publication_authorization": "not_authorized",
        "delivery_state": "withheld",
        "content_blockers": blockers,
        "governance_items": [],
    }


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


def _load_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _modern_article_errors(
    root: Path,
    article: Mapping[str, Any],
    delivery_text: str,
    *,
    strict: bool = False,
) -> tuple[list[str], str]:
    """Validate the body → title pack → delivery chain for one modern article."""

    errors: list[str] = []
    aid = str(article.get("article_id", "?"))
    errors.extend(
        validate_phase_contract_fields(article, "title")
        if strict
        else validate_phase_field_boundary(article, "title")
    )

    def required_path(*fields: str) -> tuple[str, Path | None]:
        for field in fields:
            raw = article.get(field)
            if isinstance(raw, str) and raw.strip():
                return raw, _safe_relative_path(root, raw)
        errors.append(f"{aid}:article_first_missing:{fields[0]}")
        return "", None

    body_raw, body_path = required_path("body_draft_path", "body_path")
    content_raw, content_path = required_path(
        "content_fidelity_path", "content_fidelity_record_path"
    )
    title_raw, title_path = required_path("title_pack_path")
    title_review_raw, title_review_path = required_path("title_review_path")
    delivery_raw, _ = required_path("delivery_path", "markdown_path")
    if body_path is None or not body_path.is_file():
        errors.append(f"{aid}:body_draft_missing_or_unsafe")
        body_text = ""
    else:
        try:
            body_text = body_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            errors.append(f"{aid}:body_draft_unreadable")
            body_text = ""
    if body_text:
        errors.extend(f"{aid}:{error}" for error in validate_body_draft(body_text))

    content = _load_object(content_path) if content_path is not None and content_path.is_file() else None
    if content is None:
        errors.append(f"{aid}:content_fidelity_missing_or_unreadable")
    else:
        content_result = evaluate_content_fidelity(
            content,
            body_text=body_text,
            strict=strict or None,
        )
        if content_result.get("status") != "pass":
            errors.extend(
                f"{aid}:content_fidelity:{error}"
                for error in content_result.get("errors", [])
            )
            if not content_result.get("errors"):
                errors.append(f"{aid}:content_fidelity_result_not_pass")
        if content_body_path(content) != body_raw:
            errors.append(f"{aid}:content_fidelity_body_path_mismatch")

    title_pack = _load_object(title_path) if title_path is not None and title_path.is_file() else None
    if title_pack is None:
        errors.append(f"{aid}:title_pack_missing_or_unreadable")
        selected_title = ""
    else:
        title_result = evaluate_title_pack(title_pack, body_text=body_text)
        if title_result.get("status") != "selected":
            errors.extend(
                f"{aid}:title_pack:{error}"
                for error in title_result.get("errors", [])
            )
            if not title_result.get("errors"):
                errors.append(f"{aid}:title_pack_result_not_selected")
        selected_title = ""
        selected_id = title_result.get("selected_title_id")
        for direction in title_pack.get("directions", []):
            if isinstance(direction, Mapping) and direction.get("title_id") == selected_id:
                selected_title = str(direction.get("title", "")).strip()
                break
        if not selected_title:
            errors.append(f"{aid}:selected_title_missing")
        if title_pack.get("body_path") != body_raw:
            errors.append(f"{aid}:title_pack_body_path_mismatch")
        content_ref = title_pack.get("content_fidelity_ref")
        if isinstance(content_ref, Mapping) and content_ref.get("path") != content_raw:
            errors.append(f"{aid}:title_pack_content_fidelity_path_mismatch")
        elif isinstance(content_ref, Mapping) and content_path is not None:
            actual_hash = _file_sha256(content_path)
            if actual_hash is None or str(content_ref.get("sha256", "")).lower() != actual_hash:
                errors.append(f"{aid}:title_pack_content_fidelity_hash_mismatch")

    title_review = (
        _load_object(title_review_path)
        if title_review_path is not None and title_review_path.is_file()
        else None
    )
    if title_review is None:
        errors.append(f"{aid}:title_review_missing_or_unreadable")
    else:
        title_review_result = evaluate_title_review(title_review, title_pack=title_pack)
        if title_review_result.get("status") != "pass":
            errors.extend(
                f"{aid}:title_review:{error}"
                for error in title_review_result.get("errors", [])
            )
            if not title_review_result.get("errors"):
                errors.append(f"{aid}:title_review_result_not_pass")
        if title_review.get("article_id") != aid:
            errors.append(f"{aid}:title_review_article_id_mismatch")
        review_ref = title_review.get("title_pack_ref")
        if not isinstance(review_ref, Mapping) or review_ref.get("path") != title_raw:
            errors.append(f"{aid}:title_review_title_pack_path_mismatch")
        elif title_path is not None:
            actual_hash = _file_sha256(title_path)
            if actual_hash is None or str(review_ref.get("sha256", "")).lower() != actual_hash:
                errors.append(f"{aid}:title_review_title_pack_hash_mismatch")

    if selected_title:
        errors.extend(f"{aid}:{error}" for error in validate_delivery_markdown(delivery_text, selected_title))
        try:
            if compose_delivery_markdown(body_text, selected_title) != delivery_text:
                errors.append(f"{aid}:delivery_body_mismatch")
        except ValueError:
            errors.append(f"{aid}:delivery_body_mismatch")
    if delivery_raw and article.get("delivery_path") and delivery_raw != article.get("delivery_path"):
        errors.append(f"{aid}:delivery_path_mismatch")
    return errors, selected_title


def _article_delivery_entry(
    root: Path,
    article: Mapping[str, Any],
    *,
    modern: bool = False,
    strict: bool = False,
) -> dict[str, Any]:
    article_id = str(article.get("article_id", ""))
    raw_path = article.get("delivery_path") if modern else article.get("markdown_path")
    if not raw_path:
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
    if modern:
        entry["body_draft_path"] = article.get("body_draft_path", article.get("body_path", ""))
        entry["content_fidelity_path"] = article.get(
            "content_fidelity_path", article.get("content_fidelity_record_path", "")
        )
        entry["title_pack_path"] = article.get("title_pack_path", "")
        entry["title_review_path"] = article.get("title_review_path", "")
        entry["delivery_path"] = raw_path
        modern_errors, selected_title = _modern_article_errors(
            root, article, text, strict=strict
        )
        if selected_title:
            entry["title"] = selected_title
        if modern_errors:
            entry["errors"] = modern_errors
            entry["error"] = modern_errors[0]
    entry["markdown_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    if modern:
        entry["delivery_sha256"] = entry["markdown_sha256"]
    entry["cjk_chars"] = len(_CJK_RE.findall(text))
    return entry


def _build_content_delivery_record_from_report(
    run_dir: Path,
    review_report: Mapping[str, Any],
    *,
    batch: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a handoff from an already evaluated report for unit tests."""
    if not isinstance(run_dir, Path) or not run_dir.is_dir():
        return _delivery_error_record("run_dir_missing")

    if batch is None:
        batch_path = run_dir / "batch.json"
        try:
            loaded_batch = json.loads(batch_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return _delivery_error_record("batch_unreadable")
        if not isinstance(loaded_batch, dict):
            return _delivery_error_record("batch_not_object")
        batch = loaded_batch
    if not isinstance(batch, Mapping):
        return _delivery_error_record("batch_not_object")
    if not isinstance(review_report, Mapping):
        return _delivery_error_record("review_report_not_object")

    report = dict(review_report)
    assessment = assess_content_readiness(report)
    blockers = list(assessment["content_blockers"])
    strict_batch = is_strict_run_contract(batch)
    if strict_batch:
        blockers.extend(validate_run_contract(batch))
        blockers.extend(validate_referenced_contract_artifacts(run_dir, batch))
    if batch.get("review_surface") != "markdown_codex":
        blockers.append("content_delivery_requires_markdown_codex")
    if batch.get("publication_authorization", "not_authorized") != "not_authorized":
        blockers.append("publication_authorization_must_remain_not_authorized")

    articles = batch.get("articles")
    if not isinstance(articles, list):
        articles = []
        blockers.append("batch_articles_invalid")
    modern_batch = strict_batch or batch.get("article_first_contract_version") == ARTICLE_FIRST_CONTRACT_VERSION or any(
        isinstance(article, Mapping)
        and (is_article_first_record(article) or any(field in article for field in (
            "body_draft_path", "body_path", "title_pack_path", "title_review_path",
            "delivery_path", "content_fidelity_path", "content_fidelity_record_path"
        )))
        for article in articles
    )
    blockers.extend(validate_article_first_run_lane(batch, detected=modern_batch))
    entries = [
        _article_delivery_entry(
            run_dir,
            article,
            modern=modern_batch,
            strict=strict_batch,
        )
        for article in articles
        if isinstance(article, Mapping)
    ]
    for entry in entries:
        if isinstance(entry.get("errors"), list):
            blockers.extend(error for error in entry["errors"] if isinstance(error, str))
        elif entry.get("error"):
            blockers.append(f"{entry.get('article_id', '?')}:{entry['error']}")

    return {
        "schema_version": CONTENT_DELIVERY_SCHEMA,
        "run_id": batch.get("run_id", ""),
        "content_status": CONTENT_READY if not blockers else CONTENT_BLOCKED,
        "review_surface": batch.get("review_surface"),
        "final_review_verdict": report.get("verdict"),
        "final_review_path": "review/final-review.json",
        "content_result": report.get("content_result", "UNKNOWN"),
        "evidence_result": report.get("evidence_result", "UNKNOWN"),
        "governance_result": report.get("governance_result", "UNKNOWN"),
        "article_rule_compliance": report.get("article_rule_compliance", "UNVERIFIED"),
        "publication_authorization": "not_authorized",
        "delivery_state": "content_ready_not_published" if not blockers else "withheld",
        "articles": entries,
        "content_blockers": blockers,
        "governance_items": assessment["governance_items"],
        "note": "CONTENT_READY 只表示文章可交给真人复制发布，不代表本系统已发布或授权发布。",
    }


def build_content_delivery_record(
    run_dir: Path,
    *,
    review_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a handoff from the persisted and freshly re-evaluated final review.

    ``review_report`` is retained as a consistency assertion for callers that
    already hold the record.  It can never supply the delivery verdict.
    """

    if not isinstance(run_dir, Path) or not run_dir.is_dir():
        return _delivery_error_record("run_dir_missing")

    batch_path = run_dir / "batch.json"
    try:
        batch = json.loads(batch_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _delivery_error_record("batch_unreadable")
    if not isinstance(batch, dict):
        return _delivery_error_record("batch_not_object")

    final_review_path = run_dir / "review" / "final-review.json"
    persisted = _load_object(final_review_path)
    if persisted is None:
        reason = (
            "final_review_record_missing"
            if not final_review_path.exists()
            else "final_review_record_unreadable"
        )
        return _delivery_error_record(reason)

    try:
        fresh = build_final_review_record(run_dir)
    except Exception:  # noqa: BLE001 — delivery must fail closed on re-evaluation errors
        return _delivery_error_record("final_review_evaluation_failed")

    persisted_errors = validate_final_review_record(
        persisted,
        run_dir,
        expected=fresh,
    )
    if persisted_errors:
        return _delivery_error_record(
            "stale_final_review" if "stale_final_review" in persisted_errors else "final_review_record_invalid",
            errors=persisted_errors,
        )

    if review_report is not None:
        supplied = dict(review_report) if isinstance(review_report, Mapping) else review_report
        supplied_errors = validate_final_review_record(
            supplied,
            run_dir,
            expected=fresh,
        )
        if supplied_errors:
            return _delivery_error_record(
                "review_report_not_current",
                errors=supplied_errors,
            )

    return _build_content_delivery_record_from_report(
        run_dir,
        fresh,
        batch=batch,
    )


def write_content_delivery_record(
    run_dir: Path,
    output: Path | None = None,
    *,
    force: bool = False,
) -> Path:
    """Evaluate a run and write its content-only handoff record（走留底通道 + 封存守门）。"""
    from article_group.evidence_write import write_evidence_json

    target = output or (run_dir / "review" / "content-delivery.json")
    record = build_content_delivery_record(run_dir)
    write_evidence_json(
        target, record, run_dir=run_dir,
        reason="content_delivery:record", force=force,
    )
    return target


__all__ = [
    "CONTENT_BLOCKED",
    "CONTENT_DELIVERY_SCHEMA",
    "CONTENT_READY",
    "assess_content_readiness",
    "build_content_delivery_record",
    "write_content_delivery_record",
]
