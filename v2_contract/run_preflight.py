"""Fail-closed V2 task-card and transition preflight for a proposed batch."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from yaml import YAMLError

from v2_contract.validate_task_card import validate_task_card
from v2_contract.validate_transition import validate_transition


MAPPED_ARTICLE_FIELDS = (
    "article_id",
    "candidate_id",
    "slot",
    "work",
    "primary_atom",
    "reader_intent",
    "angle",
    "state",
    "why_today",
    "content_map",
    "event_cluster_id",
    "reader_question",
    "source_refs",
    "gate_status",
    "publication_authorization",
    "delivery_state",
    "review_policy",
    "recovery_mode",
    "daily_output_policy",
)
CANDIDATE_FIELD_MAP = {
    "work": "work",
    "content_map": "content_map",
    "event_cluster_id": "event_cluster_id",
    "reader_question": "reader_question",
    "why_today": "why_now",
}
TASK_CARD_METADATA_FIELDS = ("article_id", "candidate_id", "batch_id", "state", "slot")
TASK_CARD_METADATA_PATTERN = re.compile(
    r"^- (?P<field>article_id|candidate_id|batch_id|state|slot): (?P<value>.+)$",
    re.MULTILINE,
)
TASK_CARD_NARRATIVE_PATTERNS = {
    "primary_atom": re.compile(r"^- Primary Atom: (?P<value>.+)$", re.MULTILINE),
    "reader_intent": re.compile(r"^- Reader Intent: (?P<value>.+)$", re.MULTILINE),
    "angle": re.compile(r"^1\. \*\*站队点/可转述句\*\*：(?P<value>.+)$", re.MULTILINE),
}


class PreflightInputError(ValueError):
    """Raised when a batch or supplied run context cannot be loaded."""


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PreflightInputError(f"JSON document must be an object: {path}")
    return payload


def _nonblank_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalized_candidate_id(value: object) -> str | None:
    """Match the canonical candidate-ID normalization without coercing input."""
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"\s+", " ", value).strip().lower()
    return normalized or None


def _missing_article_fields(article: dict[str, Any]) -> list[str]:
    return [field for field in MAPPED_ARTICLE_FIELDS if field not in article or article[field] is None]


def _article_label(article: object, index: int | None = None) -> str:
    if isinstance(article, dict) and _nonblank_string(article.get("article_id")):
        return article["article_id"].strip()
    return f"index-{index}" if index is not None else "unknown"


def _task_card_metadata(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    values = {
        match.group("field"): match.group("value").strip()
        for match in TASK_CARD_METADATA_PATTERN.finditer(text)
    }
    for field, pattern in TASK_CARD_NARRATIVE_PATTERNS.items():
        match = pattern.search(text)
        if match is not None:
            values[field] = match.group("value").strip()
    missing = [
        field
        for field in (*TASK_CARD_METADATA_FIELDS, *TASK_CARD_NARRATIVE_PATTERNS)
        if field not in values
    ]
    if missing:
        raise PreflightInputError(f"task-card metadata missing {','.join(missing)}: {path}")
    return values


def _load_run_context(run_dir: Path, run_id: str) -> dict[str, Any]:
    if not run_dir.is_dir():
        raise PreflightInputError(f"run directory does not exist: {run_dir}")

    candidates = _load_json_object(run_dir / "candidate-pool.json")
    source_manifest = _load_json_object(run_dir / "source-manifest.json")
    for name, payload in (("candidate-pool", candidates), ("source-manifest", source_manifest)):
        if payload.get("run_id") != run_id:
            raise PreflightInputError(f"{name} run_id mismatch: expected={run_id}:actual={payload.get('run_id')}")

    candidate_list = candidates.get("candidates")
    if not isinstance(candidate_list, list) or not all(isinstance(item, dict) for item in candidate_list):
        raise PreflightInputError(f"candidate-pool candidates must be an object list: {run_dir}")
    candidate_by_id: dict[str, dict[str, Any]] = {}
    seen_candidate_ids: set[str] = set()
    for index, candidate in enumerate(candidate_list):
        normalized_candidate_id = _normalized_candidate_id(candidate.get("candidate_id"))
        if normalized_candidate_id is None:
            continue
        if normalized_candidate_id in seen_candidate_ids:
            raise PreflightInputError(
                f"preflight.duplicate_candidate_id:{normalized_candidate_id}:record-{index}"
            )
        seen_candidate_ids.add(normalized_candidate_id)
        candidate_id = candidate["candidate_id"]
        candidate_by_id[candidate_id] = candidate

    sources = source_manifest.get("sources")
    if not isinstance(sources, list) or not all(isinstance(item, dict) for item in sources):
        raise PreflightInputError(f"source-manifest sources must be an object list: {run_dir}")
    source_paths = {
        source["relative_path"]
        for source in sources
        if _nonblank_string(source.get("relative_path"))
    }

    task_card_metadata: dict[str, dict[str, str]] = {}
    for task_card in sorted((run_dir / "task-cards").glob("task-card-*.md")):
        metadata = _task_card_metadata(task_card)
        article_id = metadata["article_id"]
        if article_id in task_card_metadata:
            raise PreflightInputError(f"duplicate task-card article_id:{article_id}: {run_dir}")
        task_card_metadata[article_id] = metadata

    if not task_card_metadata:
        raise PreflightInputError(f"no task cards found: {run_dir / 'task-cards'}")
    return {
        "candidate_by_id": candidate_by_id,
        "source_paths": source_paths,
        "task_card_metadata": task_card_metadata,
    }


def _context_errors(article: dict[str, Any], run_id: str, context: dict[str, Any] | None) -> list[str]:
    if context is None:
        return []

    article_id = _article_label(article)
    errors: list[str] = []
    candidate_id = article["candidate_id"]
    candidate = (
        context["candidate_by_id"].get(candidate_id)
        if _nonblank_string(candidate_id)
        else None
    )
    if not _nonblank_string(candidate_id):
        errors.append(f"preflight.candidate_id_invalid:{article_id}")
    elif not isinstance(candidate, dict):
        errors.append(f"preflight.candidate_not_in_pool:{article_id}:{candidate_id}")
    else:
        for article_field, candidate_field in CANDIDATE_FIELD_MAP.items():
            if article[article_field] != candidate.get(candidate_field):
                errors.append(f"preflight.candidate_mismatch:{article_id}:{article_field}")

    source_refs = article["source_refs"]
    if not isinstance(source_refs, list) or not all(_nonblank_string(value) for value in source_refs):
        errors.append(f"preflight.source_refs_invalid:{article_id}")
    else:
        for source_ref in source_refs:
            if source_ref not in context["source_paths"]:
                errors.append(f"preflight.source_not_in_manifest:{article_id}:{source_ref}")

    metadata = context["task_card_metadata"].get(article_id)
    if metadata is None:
        errors.append(f"preflight.task_card_missing:{article_id}")
    else:
        expected = {
            "article_id": article_id,
            "candidate_id": str(candidate_id),
            "batch_id": run_id.rsplit("/", 1)[-1],
            "state": str(article["state"]),
            "slot": str(article["slot"]),
            "primary_atom": str(article["primary_atom"]),
            "reader_intent": str(article["reader_intent"]),
            "angle": str(article["angle"]),
        }
        for field, value in expected.items():
            if metadata[field] != value:
                errors.append(f"preflight.task_card_mismatch:{article_id}:{field}")
    return errors


def _map_article(article: dict[str, Any], run_id: str) -> dict[str, Any]:
    task_card = {field: article[field] for field in MAPPED_ARTICLE_FIELDS}
    task_card["schema_version"] = "1.1"
    task_card["run_id"] = run_id
    if "artifacts" in article:
        task_card["artifacts"] = article["artifacts"]
    return task_card


def map_article_to_task_card(
    article: dict[str, Any],
    run_id: str,
    run_dir: Path | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Map one explicit batch article to v1.1, returning fail-closed errors."""
    if not isinstance(article, dict):
        return None, ["preflight.article_must_be_an_object:unknown"]
    article_id = _article_label(article)
    missing = _missing_article_fields(article)
    if missing:
        return None, [f"preflight.missing_mapping_fields:{article_id}:{','.join(missing)}"]
    context = _load_run_context(run_dir, run_id) if run_dir is not None else None
    task_card = _map_article(article, run_id)
    errors = _context_errors(article, run_id, context) + validate_task_card(task_card)
    return task_card, errors


def _transition_values(batch: dict[str, Any]) -> tuple[object, object, list[str]]:
    current = batch.get("manifest_state")
    target = batch.get("target_state")
    missing = [
        field
        for field, value in (("manifest_state", current), ("target_state", target))
        if not _nonblank_string(value)
    ]
    errors = [f"preflight.missing_transition_fields:{','.join(missing)}"] if missing else []
    return current, target, errors


def preflight_batch(batch: dict[str, Any], run_dir: Path | None = None) -> dict[str, Any]:
    """Return a deterministic report without changing batch, manifest, or workflow state."""
    if not isinstance(batch, dict):
        raise PreflightInputError("batch JSON must be an object")
    raw_run_id = batch.get("run_id")
    if not _nonblank_string(raw_run_id):
        raise PreflightInputError("batch run_id must be a non-empty string")
    run_id = raw_run_id.strip() if isinstance(raw_run_id, str) else ""
    articles = batch.get("articles")
    if not isinstance(articles, list):
        raise PreflightInputError("batch articles must be a list")

    context = _load_run_context(run_dir, run_id) if run_dir is not None else None
    article_reports: list[dict[str, Any]] = []
    task_cards: list[dict[str, Any]] = []
    all_errors: list[str] = []
    for index, article in enumerate(articles):
        article_id = _article_label(article, index)
        if not isinstance(article, dict):
            errors = [f"preflight.article_must_be_an_object:{article_id}"]
            article_reports.append({"article_id": article_id, "errors": errors})
            all_errors.extend(errors)
            continue
        missing = _missing_article_fields(article)
        if missing:
            errors = [f"preflight.missing_mapping_fields:{article_id}:{','.join(missing)}"]
            article_reports.append({"article_id": article_id, "errors": errors})
            all_errors.extend(errors)
            continue

        task_card = _map_article(article, run_id)
        errors = _context_errors(article, run_id, context) + validate_task_card(task_card)
        article_reports.append({"article_id": article_id, "errors": errors})
        task_cards.append(task_card)
        all_errors.extend(errors)
    current, target, transition_errors = _transition_values(batch)
    if not transition_errors:
        transition_errors = validate_transition(current, target)
    all_errors.extend(transition_errors)
    if _nonblank_string(current):
        for article_report, article in zip(article_reports, articles, strict=True):
            if (
                isinstance(article, dict)
                and article.get("state") is not None
                and article.get("state") != current
            ):
                error = (
                    f"preflight.manifest_state_mismatch:{article_report['article_id']}"
                    f":article={article.get('state')}:manifest={current}"
                )
                article_report["errors"].append(error)
                all_errors.append(error)
    status = "PASS" if not all_errors else "FAIL"
    return {
        "status": status,
        "exit_code": 0 if status == "PASS" else 1,
        "run_id": run_id,
        "article_count": len(articles),
        "articles": article_reports,
        "task_cards": task_cards,
        "transition": {"current": current, "target": target, "errors": transition_errors},
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True, type=Path, help="Proposed batch JSON document")
    parser.add_argument("--run-dir", type=Path, help="Optional controlled run root for read-only consistency checks")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        report = preflight_batch(_load_json_object(args.batch), args.run_dir)
    except (OSError, ValueError, json.JSONDecodeError, YAMLError) as exc:
        print(f"INPUT_ERROR:{exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())