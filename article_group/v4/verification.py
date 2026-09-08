"""Offline V4 orchestration and read-back verification.

This module deliberately has no crawler, network, Vault, or publication
integration.  It composes the pure V4 helpers around one explicit run
directory and writes versioned JSON artifacts into a caller-selected output
directory.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from .contracts import (
    new_artifact_envelope,
    parse_json_object,
    safe_relative_path,
    validate_artifact_envelope,
)
from .effect_feedback import aggregate_effects, advance_pattern_lifecycle
from .evidence_graph import build_evidence_graph, validate_evidence_graph
from .gap_priority import derive_gap_tasks
from .portfolio import build_daily_portfolio, validate_portfolio
from .recovery import derive_recovery_actions, validate_recovery_actions
from .template_guard import analyze_template_signals, validate_template_signals


ARTIFACT_FILES = {
    "portfolio": "portfolio-plan.json",
    "graph": "evidence-graph.json",
    "gaps": "gap-priority.json",
    "templates": "template-signals.json",
    "effects": "effect-feedback.json",
    "recover": "recovery-actions.json",
    "verify": "v4-verification.json",
}
ARTIFACT_SCHEMAS = {
    "portfolio": "v4-portfolio-plan-v1",
    "graph": "v4-evidence-graph-v1",
    "gaps": "v4-gap-priority-v1",
    "templates": "v4-template-signals-v1",
    "effects": "v4-effect-feedback-v1",
    "recover": "v4-recovery-actions-v1",
    "verify": "v4-verification-v1",
}
_VERIFICATION_SCHEMA = "v4-verification-v1"
_EPOCH = "1970-01-01T00:00:00Z"
_REQUIRED_SOURCE_ROLES = {
    "official_film_page",
    "industry_context",
    "audience_reaction",
}


class V4VerificationError(RuntimeError):
    """Raised when an offline V4 run cannot safely complete."""


def _stable_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ).encode("utf-8") + b"\n"


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_value(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_json(run_dir: Path, relative: str | Path) -> dict[str, Any] | list[Any] | None:
    path = safe_relative_path(run_dir, str(relative))
    if path is None or path.is_symlink() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None


def _load_object(run_dir: Path, relative: str) -> dict[str, Any]:
    value = _load_json(run_dir, relative)
    return value if isinstance(value, dict) else {}


def _write_once(path: Path, value: Mapping[str, Any]) -> None:
    data = _stable_bytes(value)
    if path.is_symlink():
        raise V4VerificationError(f"refuse_symlink:{path}")
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise V4VerificationError(f"cannot_read_existing:{path}") from exc
        if _hash_bytes(existing) != _hash_bytes(data):
            raise V4VerificationError(f"refuse_overwrite:{path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _preflight_writes(items: Sequence[tuple[Path, Mapping[str, Any]]]) -> None:
    """Check every destination before creating any missing output file."""

    destinations: set[Path] = set()
    for path, value in items:
        resolved = path.resolve()
        if resolved in destinations:
            raise V4VerificationError(f"output_path_collision:{resolved}")
        destinations.add(resolved)
        if path.is_symlink():
            raise V4VerificationError(f"refuse_symlink:{path}")
        if not path.exists():
            continue
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise V4VerificationError(f"cannot_read_existing:{path}") from exc
        if _hash_bytes(existing) != _hash_bytes(_stable_bytes(value)):
            raise V4VerificationError(f"refuse_overwrite:{path}")


def _run_metadata(run_dir: Path) -> tuple[str, str]:
    batch = _load_object(run_dir, "batch.json")
    manifest = _load_object(run_dir, "run-manifest.json")
    run_id = _text(batch.get("run_id")) or _text(manifest.get("run_id"))
    generated_at = (
        _text(batch.get("generated_at"))
        or _text(batch.get("created_at"))
        or _text(manifest.get("created_at"))
        or _EPOCH
    )
    return run_id or run_dir.name, generated_at


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _ensure_hashes(
    artifact: Mapping[str, Any],
    *,
    input_values: Mapping[str, object],
) -> dict[str, Any]:
    result = deepcopy(dict(artifact))
    hashes = result.get("input_hashes")
    result["input_hashes"] = dict(hashes) if isinstance(hashes, Mapping) else {}
    for key, value in input_values.items():
        result["input_hashes"][key] = _hash_value(value)
    return result


def _batch(run_dir: Path) -> dict[str, Any]:
    return _load_object(run_dir, "batch.json")


def build_portfolio_artifact(run_dir: Path) -> dict[str, Any]:
    run_id, generated_at = _run_metadata(run_dir)
    pool = _load_object(run_dir, "candidate-pool.json")
    history_value = _load_json(run_dir, "portfolio-history.json")
    candidates = pool.get("candidates", [])
    history = history_value if isinstance(history_value, list) else pool.get("history", [])
    artifact = build_daily_portfolio(
        candidates,
        history,
        run_id=run_id,
        planned_at=generated_at,
    )
    # The portfolio module hashes its normalized input snapshot.  Preserve
    # those names and values because its validator rechecks the binding.
    return artifact


def build_graph_artifact(run_dir: Path) -> dict[str, Any]:
    batch = _batch(run_dir)
    return build_evidence_graph(run_dir, batch)


def build_gap_artifact(
    run_dir: Path,
    graph: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    run_id, generated_at = _run_metadata(run_dir)
    graph_value = dict(graph) if isinstance(graph, Mapping) else build_graph_artifact(run_dir)
    audit = _load_json(run_dir, "source-audit.json")
    retry_state = _load_object(run_dir, "retry-state.json")
    retry_items = {
        (_text(item.get("article_id")), _text(item.get("source_id"))): item
        for item in retry_state.get("items", [])
        if isinstance(item, Mapping)
    }
    audits: list[Mapping[str, Any]] = []
    if isinstance(audit, Mapping):
        raw_articles = audit.get("articles", [])
        if isinstance(raw_articles, list):
            for article in raw_articles:
                if not isinstance(article, Mapping):
                    continue
                article_id = _text(article.get("article_id"))
                source_ref = _text(article.get("source_audit_ref"))
                failures = article.get("failed_sources", [])
                if not isinstance(failures, list):
                    continue
                for failure in failures:
                    if not isinstance(failure, Mapping):
                        continue
                    source_id = _text(failure.get("source_id"))
                    retry_item = retry_items.get((article_id, source_id), {})
                    required_now = bool(
                        failure.get("retry_required_now", False)
                        or retry_item.get("retry_required_now", False)
                    )
                    retryable = bool(
                        failure.get("retryable", retry_item.get("retryable", False))
                    )
                    audits.append(
                        {
                            "audit_id": f"{article_id}:{source_id}",
                            "gap_id": f"gap:source_failure:{article_id}:{source_id}",
                            "gap_type": "source_failure",
                            "article_id": article_id,
                            "source_id": source_id,
                            "status": "missing",
                            "blocking": required_now,
                            "retryable": retryable,
                            "attempts": retry_item.get("attempts", retry_state.get("attempts", 0)),
                            "consecutive_failures": retry_item.get(
                                "consecutive_failures", 0
                            ),
                            "reason": _text(failure.get("reason"))
                            or "source failure remains visible",
                            "evidence_refs": [
                                value
                                for value in ("source-audit.json", source_ref)
                                if value
                            ],
                        }
                    )
        raw_gaps = audit.get("gaps")
        if isinstance(raw_gaps, list):
            audits.extend(item for item in raw_gaps if isinstance(item, Mapping))
    graph_errors = validate_evidence_graph(graph_value, run_dir)
    gaps = (
        derive_gap_tasks(graph_value, audits, run_root=run_dir)
        if not graph_errors
        else []
    )
    blocking = [item["gap_id"] for item in gaps if item.get("blocking") is True]
    source_gaps = [item for item in gaps if item.get("gap_type") == "source_failure"]
    retry = [
        {
            "gap_id": item["gap_id"],
            "article_id": _text(item.get("article_id")),
            "source_id": _text(item.get("failed_source_id")),
            "retryable": item.get("retryable") is True,
            "attempts": item.get("attempts", 0),
            "required_now": item.get("blocking") is True,
            "reason": _text(item.get("reason")),
            "evidence_refs": list(item.get("evidence_refs", [])),
        }
        for item in gaps
        if (
            (item.get("retryable") is True or item.get("blocking") is True)
            and item.get("disposition") != "resolved"
        )
    ]
    payload = {
        "decision": "needs_controller" if blocking else "clear",
        "gaps": gaps,
        "source_gaps": source_gaps,
        "blocking_gaps": blocking,
        "retry_requirements": retry,
        "errors": [f"graph:{error}" for error in graph_errors],
        "publication_authorization": "not_authorized",
    }
    artifact = new_artifact_envelope(
        "v4-gap-priority-v1", run_id, payload, generated_at=generated_at
    )
    return _ensure_hashes(
        artifact,
        input_values={"evidence-graph": graph_value, "source-audit": audit},
    )


def _candidate_for_template(run_dir: Path) -> dict[str, Any]:
    batch = _batch(run_dir)
    articles = batch.get("articles")
    article = articles[0] if isinstance(articles, list) and articles and isinstance(articles[0], Mapping) else {}
    draft_path = _text(article.get("draft_path") or article.get("markdown_path"))
    body = ""
    if draft_path:
        path = safe_relative_path(run_dir, draft_path)
        try:
            if path is not None and not path.is_symlink() and path.is_file():
                body = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            body = ""
    return {
        "candidate_id": _text(article.get("article_id")) or "current",
        "run_id": _text(batch.get("run_id")),
        "generated_at": (
            _text(batch.get("generated_at"))
            or _text(batch.get("created_at"))
            or _EPOCH
        ),
        "title": _text(article.get("title")),
        "body": body,
    }


def build_template_artifact(run_dir: Path) -> dict[str, Any]:
    current = _load_object(run_dir, "template-current.json") or _candidate_for_template(run_dir)
    history_value = _load_json(run_dir, "template-history.json")
    history = history_value if isinstance(history_value, list) else []
    return analyze_template_signals(current, history)


def build_effect_artifact(run_dir: Path) -> dict[str, Any]:
    run_id, generated_at = _run_metadata(run_dir)
    pattern_path = next(
        (
            candidate
            for candidate in ("effect-pattern.json", "effects/pattern.json")
            if _load_json(run_dir, candidate) is not None
        ),
        "effect-pattern.json",
    )
    pattern = _load_object(run_dir, pattern_path)
    if not pattern:
        pattern = {
            "pattern_id": f"pattern:{run_id}",
            "state": "candidate",
        }
    events_path = next(
        (
            candidate
            for candidate in ("metric-events.json", "effects/metric-events.json")
            if _load_json(run_dir, candidate) is not None
        ),
        "metric-events.json",
    )
    raw_events = _load_json(run_dir, events_path)
    events = raw_events if isinstance(raw_events, list) else []
    pattern_for_module = dict(pattern)
    pattern_for_module.setdefault("run_id", run_id)
    pattern_for_module.setdefault("generated_at", generated_at)
    result = advance_pattern_lifecycle(pattern_for_module, events)
    if result.get("schema_version") == "v4-effect-feedback-v1" and isinstance(result.get("payload"), Mapping):
        artifact = result
    else:
        artifact = new_artifact_envelope(
            "v4-effect-feedback-v1", run_id, result, generated_at=generated_at
        )
    group_by_value = _load_json(run_dir, "effect-group-by.json")
    group_by = (
        tuple(group_by_value)
        if isinstance(group_by_value, list)
        and all(isinstance(item, str) for item in group_by_value)
        else ("platform",)
    )
    summaries = aggregate_effects(events, group_by=group_by) if events else []
    artifact = deepcopy(artifact)
    payload = artifact.get("payload")
    if isinstance(payload, dict):
        payload["aggregates"] = summaries
        payload["group_by"] = list(group_by)
        payload["publication_authorization"] = "not_authorized"
    return _ensure_hashes(
        artifact,
        input_values={
            "metric-events": events,
            "pattern": pattern_for_module,
            "group-by": list(group_by),
        },
    )


def build_recovery_artifact(
    run_dir: Path,
    graph: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    run_id, generated_at = _run_metadata(run_dir)
    graph_value = dict(graph) if isinstance(graph, Mapping) else build_graph_artifact(run_dir)
    raw_events = next(
        (
            value
            for candidate in ("recovery-events.json", "recovery/events.json")
            if (value := _load_json(run_dir, candidate)) is not None
        ),
        [],
    )
    events = raw_events if isinstance(raw_events, list) else []
    return derive_recovery_actions(
        graph_value,
        events,
        run_id=run_id,
        created_at=generated_at,
        run_root=run_dir,
    )


def _source_report(run_dir: Path) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    manifest = _load_object(run_dir, "source-manifest.json")
    roles = {
        _text(item.get("role") or item.get("source_role"))
        for item in manifest.get("sources", [])
        if isinstance(item, Mapping)
    }
    missing = {
        role for role in _REQUIRED_SOURCE_ROLES if role not in roles
    }
    audit = _load_object(run_dir, "source-audit.json")
    retry: dict[tuple[str, str], dict[str, Any]] = {}
    manual: list[str] = []

    def add_retry(record: Mapping[str, Any]) -> None:
        article_id = _text(record.get("article_id"))
        source_id = _text(record.get("source_id"))
        key = (article_id, source_id)
        if not article_id and not source_id:
            key = ("", _text(record.get("reason")) or "retry_required")
        current = retry.setdefault(
            key,
            {
                "article_id": article_id,
                "source_id": source_id,
                "reason": _text(record.get("reason")) or "retry_required",
                "retryable": False,
                "required_now": False,
            },
        )
        current["retryable"] = current["retryable"] or record.get("retryable") is True
        current["required_now"] = current["required_now"] or record.get(
            "required_now", record.get("retry_required_now", False)
        ) is True
        attempts = record.get("attempts")
        if isinstance(attempts, int) and not isinstance(attempts, bool):
            current["attempts"] = max(current.get("attempts", 0), attempts)
        trigger = _text(record.get("retry_trigger"))
        if trigger:
            current["retry_trigger"] = trigger
        evidence_ref = _text(record.get("evidence_ref"))
        if evidence_ref:
            current["evidence_ref"] = evidence_ref

    top_level_roles = audit.get("missing_roles") if isinstance(audit, Mapping) else []
    if isinstance(top_level_roles, list):
        missing.update(_text(role) for role in top_level_roles if _text(role))
    audit_articles = audit.get("articles") if isinstance(audit, Mapping) else []
    for article in audit_articles if isinstance(audit_articles, list) else []:
        if not isinstance(article, Mapping):
            continue
        article_roles = article.get("missing_roles", [])
        for role in article_roles if isinstance(article_roles, list) else []:
            role_text = _text(role)
            if role_text:
                missing.add(role_text)
        failures = article.get("failed_sources", [])
        for failure in failures if isinstance(failures, list) else []:
            if not isinstance(failure, Mapping):
                continue
            if failure.get("retryable") is True or failure.get("retry_required_now") is True:
                add_retry(
                    {
                        **dict(failure),
                        "article_id": article.get("article_id"),
                        "required_now": failure.get("retry_required_now", False),
                        "evidence_ref": _text(article.get("source_audit_ref"))
                        or "source-audit.json",
                    }
                )
    retry_state = _load_object(run_dir, "retry-state.json")
    retry_items = retry_state.get("items")
    if isinstance(retry_items, list):
        for item in retry_items:
            if not isinstance(item, Mapping):
                continue
            if item.get("retryable") is not True and item.get("retry_required_now") is not True:
                continue
            add_retry(item)
    if retry_state.get("retry_required") is True:
        add_retry(
            {
                "reason": _text(retry_state.get("next_action")) or "retry_required",
                "required_now": True,
                "retryable": True,
            }
        )
    raw_manual = audit.get("manual_escalations") if isinstance(audit, Mapping) else []
    if isinstance(raw_manual, list):
        for item in raw_manual:
            if isinstance(item, Mapping):
                value = _text(
                    item.get("id") or item.get("reason") or item.get("message")
                )
            else:
                value = _text(item)
            if value:
                manual.append(value)
    retry_values = sorted(
        retry.values(),
        key=lambda item: (
            _text(item.get("article_id")),
            _text(item.get("source_id")),
            _text(item.get("reason")),
        ),
    )
    return sorted(missing), retry_values, sorted(set(manual))


def _content_status(run_dir: Path) -> tuple[str, list[str]]:
    """Read content handoff state without deriving publication permission."""

    blockers: list[str] = []
    delivery = next(
        (
            value
            for candidate in ("review/content-delivery.json", "content-delivery.json")
            if (value := _load_json(run_dir, candidate)) is not None
        ),
        None,
    )
    batch = _batch(run_dir)
    manifest = _load_object(run_dir, "run-manifest.json")
    sources = [item for item in (delivery, batch, manifest) if isinstance(item, Mapping)]
    for source in sources:
        authorization = source.get("publication_authorization")
        if authorization is not None and authorization != "not_authorized":
            blockers.append("publication_authorization_must_remain_not_authorized")
    if isinstance(delivery, Mapping):
        status = _text(delivery.get("content_status"))
        if status in {"CONTENT_READY", "CONTENT_BLOCKED"}:
            raw_blockers = delivery.get("content_blockers")
            if isinstance(raw_blockers, list):
                blockers.extend(item for item in (_text(value) for value in raw_blockers) if item)
            return ("CONTENT_READY" if status == "CONTENT_READY" and not blockers else "CONTENT_BLOCKED", sorted(set(blockers)))
        blockers.append("content_status_missing_or_invalid")
        return "CONTENT_BLOCKED", sorted(set(blockers))

    status = _text(manifest.get("content_status")) or _text(batch.get("content_status"))
    if status != "CONTENT_READY":
        blockers.append("content_status_not_ready")
    if batch.get("review_surface") != "markdown_codex":
        blockers.append("content_delivery_requires_markdown_codex")
    articles = batch.get("articles")
    if not isinstance(articles, list) or not articles:
        blockers.append("batch_articles_invalid")
    else:
        for article in articles:
            if not isinstance(article, Mapping):
                blockers.append("batch_article_invalid")
                continue
            raw_path = article.get("markdown_path") or article.get("draft_path")
            path = safe_relative_path(run_dir, raw_path)
            if path is None or path.is_symlink() or not path.is_file():
                blockers.append(f"{_text(article.get('article_id')) or '?'}:markdown_missing_or_unsafe")
    return ("CONTENT_READY" if not blockers else "CONTENT_BLOCKED", sorted(set(blockers)))


def _validate_artifact(name: str, artifact: Mapping[str, Any], run_dir: Path) -> list[str]:
    run_id, _ = _run_metadata(run_dir)
    errors: list[str] = []
    if artifact.get("run_id") != run_id:
        errors.append("mismatch:run_id")
    if name == "portfolio":
        return list(dict.fromkeys(errors + validate_portfolio(artifact)))
    if name == "graph":
        return list(dict.fromkeys(errors + validate_evidence_graph(artifact, run_dir)))
    if name == "templates":
        return list(dict.fromkeys(errors + validate_template_signals(artifact)))
    if name == "recover":
        return list(dict.fromkeys(errors + validate_recovery_actions(artifact)))
    schema = ARTIFACT_SCHEMAS.get(name)
    if schema is None:
        return errors
    errors.extend(validate_artifact_envelope(artifact, schema, run_id=run_id))
    payload = artifact.get("payload")
    if not isinstance(payload, Mapping):
        errors.append("invalid:payload")
    else:
        if payload.get("publication_authorization") != "not_authorized":
            errors.append("publication_authorization_must_be_not_authorized")
        if name == "gaps":
            if not isinstance(payload.get("errors"), list):
                errors.append("invalid:gap_errors")
            else:
                errors.extend(
                    f"gap:{item}" for item in payload["errors"] if isinstance(item, str)
                )
            if not isinstance(payload.get("gaps"), list):
                errors.append("invalid:gaps")
            if not isinstance(payload.get("source_gaps"), list):
                errors.append("invalid:source_gaps")
            if not isinstance(payload.get("blocking_gaps"), list):
                errors.append("invalid:blocking_gaps")
            if not isinstance(payload.get("retry_requirements"), list):
                errors.append("invalid:retry_requirements")
        if name == "effects":
            if not isinstance(payload.get("errors"), list):
                errors.append("invalid:effects_errors")
            else:
                errors.extend(
                    f"effect:{item}" for item in payload["errors"] if isinstance(item, str)
                )
            if not isinstance(payload.get("aggregates"), list):
                errors.append("invalid:aggregates")
    return list(dict.fromkeys(errors))


def validate_v4_artifact(
    name: str,
    artifact: Mapping[str, Any],
    run_dir: Path,
) -> list[str]:
    """Validate one named V4 module artifact against the explicit run."""

    if name not in ARTIFACT_FILES or name == "verify":
        return [f"unknown_artifact:{name}"]
    return _validate_artifact(name, artifact, Path(run_dir).resolve())


def _write_named(output_dir: Path, name: str, artifact: Mapping[str, Any]) -> Path:
    path = output_dir / ARTIFACT_FILES[name]
    _write_once(path, artifact)
    return path


def write_v4_artifact(
    name: str,
    artifact: Mapping[str, Any],
    *,
    output_path: Path,
) -> Path:
    """Write one already-built artifact once and return its explicit path."""

    if name not in ARTIFACT_FILES:
        raise V4VerificationError(f"unknown_artifact:{name}")
    raw_path = Path(output_path)
    if raw_path.is_symlink():
        raise V4VerificationError(f"refuse_symlink:{raw_path}")
    path = raw_path.resolve()
    _write_once(path, artifact)
    if parse_json_object(path) is None:
        raise V4VerificationError(f"read_back_failed:{path}")
    return path


def validate_v4_verification(
    report: Mapping[str, Any],
    *,
    run_id: str,
) -> list[str]:
    """Validate the closed final V4 verification envelope."""

    if not isinstance(report, Mapping):
        return ["invalid:verification"]
    errors = validate_artifact_envelope(
        report, _VERIFICATION_SCHEMA, run_id=run_id
    )
    if set(report) != {
        "schema_version",
        "run_id",
        "generated_at",
        "input_hashes",
        "payload",
    }:
        errors.append("invalid:top_level")
    payload = report.get("payload")
    if not isinstance(payload, Mapping):
        return list(dict.fromkeys(errors + ["invalid:payload"]))
    if payload.get("status") not in {"PASS", "BLOCKED"}:
        errors.append("invalid:status")
    if payload.get("decision") != payload.get("status"):
        errors.append("mismatch:decision_status")
    checks = payload.get("checks")
    if not isinstance(checks, Mapping):
        errors.append("invalid:checks")
    else:
        for name in ARTIFACT_FILES:
            if name == "verify":
                continue
            check = checks.get(name)
            if not isinstance(check, Mapping):
                errors.append(f"missing:check:{name}")
                continue
            if check.get("status") not in {"PASS", "BLOCKED"}:
                errors.append(f"invalid:check_status:{name}")
            if not isinstance(check.get("errors"), list):
                errors.append(f"invalid:check_errors:{name}")
    expected_names = list(ARTIFACT_FILES.values())
    if payload.get("artifacts") != expected_names:
        errors.append("invalid:artifacts")
    module_names = [name for name in ARTIFACT_FILES if name != "verify"]
    expected_hash_names = [ARTIFACT_FILES[name] for name in module_names]
    artifact_hashes = payload.get("artifact_hashes")
    if not isinstance(artifact_hashes, Mapping):
        errors.append("invalid:artifact_hashes")
    elif set(artifact_hashes) != set(expected_hash_names):
        errors.append("invalid:artifact_hashes_keys")
    elif any(
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value.lower())
        for value in artifact_hashes.values()
    ):
        errors.append("invalid:artifact_hashes")
    input_hashes = report.get("input_hashes")
    if isinstance(input_hashes, Mapping) and artifact_hashes != input_hashes:
        errors.append("mismatch:artifact_hashes")
    for field in (
        "PASS",
        "pass",
        "blocked",
        "missing_source_roles",
        "retry_requirements",
        "manual_escalation",
        "manual_escalations",
        "errors",
    ):
        if not isinstance(payload.get(field), list):
            errors.append(f"invalid:{field}")
    if payload.get("PASS") != payload.get("pass"):
        errors.append("mismatch:PASS_pass")
    if payload.get("manual_escalation") != payload.get("manual_escalations"):
        errors.append("mismatch:manual_escalation")
    if payload.get("content_status") not in {"CONTENT_READY", "CONTENT_BLOCKED"}:
        errors.append("invalid:content_status")
    content_blockers = payload.get("content_blockers")
    if not isinstance(content_blockers, list):
        errors.append("invalid:content_blockers")
    if payload.get("publication_authorization") != "not_authorized":
        errors.append("publication_authorization_must_be_not_authorized")
    if payload.get("status") == "PASS" and (
        payload.get("blocked") or content_blockers
    ):
        errors.append("pass_contains_blockers")
    readback = payload.get("readback")
    if not isinstance(readback, Mapping) or readback.get("verified") is not True:
        errors.append("readback_must_be_verified")
    elif readback.get("artifact_count") != 7 or readback.get("files") != expected_names:
        errors.append("invalid:readback")
    if payload.get("read_back") is not True:
        errors.append("read_back_must_be_true")
    return list(dict.fromkeys(errors))


def run_v4_verification(run_dir: Path, *, output_path: Path) -> dict[str, Any]:
    """Run all offline V4 modules, write seven artifacts, and read them back."""

    raw_run_dir = Path(run_dir)
    raw_output_path = Path(output_path)
    if raw_run_dir.is_symlink() or not raw_run_dir.is_dir():
        raise V4VerificationError(f"run_dir_missing_or_unsafe:{raw_run_dir}")
    if raw_output_path.is_symlink():
        raise V4VerificationError(f"refuse_symlink:{raw_output_path}")
    run_dir = raw_run_dir.resolve()
    output_path = raw_output_path.resolve()
    if not run_dir.is_dir():
        raise V4VerificationError(f"run_dir_missing_or_unsafe:{run_dir}")
    if output_path == run_dir:
        raise V4VerificationError(f"output_path_invalid:{output_path}")
    output_dir = output_path.parent
    run_id, generated_at = _run_metadata(run_dir)

    graph = build_graph_artifact(run_dir)
    artifacts: dict[str, dict[str, Any]] = {
        "portfolio": build_portfolio_artifact(run_dir),
        "graph": graph,
        "gaps": build_gap_artifact(run_dir, graph),
        "templates": build_template_artifact(run_dir),
        "effects": build_effect_artifact(run_dir),
        "recover": build_recovery_artifact(run_dir, graph),
    }
    checks: dict[str, dict[str, Any]] = {}
    for name, artifact in artifacts.items():
        errors = _validate_artifact(name, artifact, run_dir)
        checks[name] = {
            "status": "PASS" if not errors else "BLOCKED",
            "errors": errors,
            "path": ARTIFACT_FILES[name],
        }

    missing_roles, retry_requirements, manual_escalations = _source_report(run_dir)
    template_payload = artifacts["templates"].get("payload", {})
    if isinstance(template_payload, Mapping) and template_payload.get("decision") == "manual_review":
        manual_escalations.append("template_signals_manual_review")
    if checks["portfolio"]["status"] == "BLOCKED":
        manual_escalations.append("portfolio_controller_review")
    gaps_payload = artifacts["gaps"].get("payload", {})
    if isinstance(gaps_payload, Mapping) and gaps_payload.get("blocking_gaps"):
        manual_escalations.append("gap_controller_review")
    recovery_payload = artifacts["recover"].get("payload", {})
    if isinstance(recovery_payload, Mapping):
        if any(
            isinstance(action, Mapping) and action.get("required_owner") == "controller"
            for action in recovery_payload.get("actions", [])
            if isinstance(recovery_payload.get("actions"), list)
        ):
            manual_escalations.append("recovery_controller_review")

    content_status, content_blockers = _content_status(run_dir)
    checks["content_handoff"] = {
        "status": "PASS" if not content_blockers else "BLOCKED",
        "errors": content_blockers,
        "path": "content-handoff",
    }
    module_names = tuple(artifacts)
    all_pass = all(
        checks[name]["status"] == "PASS" for name in module_names
    ) and not content_blockers
    pass_names = [name for name in module_names if checks[name]["status"] == "PASS"]
    blocked_names = [name for name in module_names if checks[name]["status"] != "PASS"]
    if content_blockers:
        blocked_names.append("content_handoff")
    all_errors = [
        f"{name}:{error}"
        for name in (*module_names, "content_handoff")
        for error in checks[name].get("errors", [])
        if isinstance(error, str)
    ]
    expected_names = list(ARTIFACT_FILES.values())
    six_bytes = {
        ARTIFACT_FILES[name]: _stable_bytes(artifacts[name])
        for name in module_names
    }
    six_hashes = {
        filename: _hash_bytes(data) for filename, data in six_bytes.items()
    }
    artifact_paths = {
        name: output_dir / ARTIFACT_FILES[name]
        for name in module_names
    }
    artifact_paths["verify"] = output_path
    output_items: list[tuple[Path, Mapping[str, Any]]] = [
        (artifact_paths[name], artifacts[name])
        for name in module_names
    ]
    verification_status = "PASS" if all_pass else "BLOCKED"
    pass_values = list(pass_names)
    manual_values = sorted(set(manual_escalations))
    verification_payload = {
        "status": verification_status,
        "decision": verification_status,
        "checks": checks,
        "artifacts": expected_names,
        "artifact_hashes": six_hashes,
        "PASS": pass_values,
        "pass": pass_values,
        "blocked": blocked_names,
        "missing_source_roles": sorted(set(missing_roles)),
        "retry_requirements": retry_requirements,
        "manual_escalation": manual_values,
        "manual_escalations": manual_values,
        "content_status": content_status,
        "content_blockers": content_blockers,
        "publication_authorization": "not_authorized",
        "errors": all_errors,
        "readback": {
            "verified": True,
            "artifact_count": 7,
            "files": expected_names,
        },
        "read_back": True,
    }
    verification = new_artifact_envelope(
        _VERIFICATION_SCHEMA,
        run_id,
        verification_payload,
        generated_at=generated_at,
    )
    verification["input_hashes"] = dict(six_hashes)
    output_items.append((output_path, verification))

    # Check every destination before writing any missing sibling artifact.
    _preflight_writes(output_items)
    for path, artifact in output_items:
        _write_once(path, artifact)

    expected_output_hashes = {
        **six_hashes,
        ARTIFACT_FILES["verify"]: _hash_bytes(_stable_bytes(verification)),
    }
    read_back_errors: list[str] = []
    for name, filename in ARTIFACT_FILES.items():
        path = artifact_paths[name]
        value = parse_json_object(path)
        if value is None:
            read_back_errors.append(f"read_back_failed:{filename}")
            continue
        try:
            actual_hash = _hash_bytes(path.read_bytes())
        except OSError:
            read_back_errors.append(f"read_back_failed:{filename}")
        else:
            if actual_hash != expected_output_hashes[filename]:
                read_back_errors.append(f"read_back_hash_mismatch:{filename}")
        if name == "verify":
            read_back_errors.extend(validate_v4_verification(value, run_id=run_id))
        else:
            read_back_errors.extend(_validate_artifact(name, value, run_dir))
    if read_back_errors:
        raise V4VerificationError(
            "read_back_failed:" + ",".join(sorted(set(read_back_errors)))
        )
    return parse_json_object(output_path) or verification


__all__ = [
    "ARTIFACT_FILES",
    "V4VerificationError",
    "build_effect_artifact",
    "build_gap_artifact",
    "build_graph_artifact",
    "build_portfolio_artifact",
    "build_recovery_artifact",
    "build_template_artifact",
    "run_v4_verification",
    "validate_v4_artifact",
    "validate_v4_verification",
    "write_v4_artifact",
]
