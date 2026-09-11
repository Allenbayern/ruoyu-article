"""Deterministic gap derivation, prioritisation, and attempt recording for V4."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
import math
from typing import Any

from .contracts import GAP_TYPES
from .evidence_graph import (
    trace_impact,
    validate_evidence_graph,
    validate_evidence_graph_structure,
)


_GRAPH_SCHEMA = "v4-evidence-graph-v1"
_EPOCH = "1970-01-01T00:00:00Z"
_POSITIVE_STATUSES = {
    "available",
    "clear",
    "ok",
    "pass",
    "passed",
    "present",
    "resolved",
    "satisfied",
    "valid",
}
_NEGATIVE_STATUSES = {
    "blocked",
    "changed",
    "duplicate",
    "failed",
    "failure",
    "high_risk",
    "insufficient",
    "invalid",
    "missing",
    "needs_recheck",
    "stale",
    "unavailable",
    "unverified",
}
_ALIASES = {
    "audience": "audience_sample",
    "audience_evidence": "audience_sample",
    "audience_sample_gap": "audience_sample",
    "dedupe": "dedupe_context",
    "duplicate": "dedupe_context",
    "duplicate_topic": "dedupe_context",
    "fact_change": "dynamic_fact_revalidation",
    "fact_cross_check": "key_fact_cross_check",
    "cross_check": "key_fact_cross_check",
    "industry": "industry_relevance",
    "industry_evidence": "industry_relevance",
    "industry_relevance_gap": "industry_relevance",
    "key_fact": "key_fact_cross_check",
    "opening": "opening_support",
    "opening_fact": "opening_support",
    "opening_support_gap": "opening_support",
    "source": "source_failure",
    "source_unavailable": "source_failure",
    "title": "title_core_fact",
    "title_fact": "title_core_fact",
    "title_support": "title_core_fact",
    "title_core_claim": "title_core_fact",
    "title_core_fact_gap": "title_core_fact",
    "dynamic_fact": "dynamic_fact_revalidation",
    "dynamic_fact_recheck": "dynamic_fact_revalidation",
    "revalidation": "dynamic_fact_revalidation",
    "dedupe_context_gap": "dedupe_context",
}
_DEFAULTS: dict[str, tuple[bool, int, int, int, int, bool]] = {
    "title_core_fact": (True, 4, 3, 3, 2, True),
    "opening_support": (True, 4, 2, 3, 2, True),
    "key_fact_cross_check": (True, 4, 3, 2, 3, True),
    "audience_sample": (False, 2, 1, 2, 2, True),
    "industry_relevance": (False, 2, 2, 2, 3, True),
    "source_failure": (True, 5, 3, 3, 2, True),
    "dynamic_fact_revalidation": (True, 4, 3, 2, 3, True),
    "dedupe_context": (True, 5, 2, 3, 1, False),
}
_FAILURE_OUTCOMES = {"error", "failed", "failure"}
_SUCCESS_OUTCOMES = {"ok", "passed", "resolved", "success", "succeeded"}


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _canonical_gap_type(value: object) -> str:
    raw = _text(value).lower().replace("-", "_").replace(" ", "_")
    if raw in GAP_TYPES:
        return raw
    return _ALIASES.get(raw, "")


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def _unique_strings(value: object) -> tuple[list[str], bool]:
    if isinstance(value, str):
        values: object = [value]
    else:
        values = value
    if values is None:
        return [], True
    if not _is_sequence(values):
        return [], False
    result = sorted({_text(item) for item in values if _text(item)})
    return result, all(isinstance(item, str) for item in values)


def _number(value: object, default: float | int) -> tuple[float | int, bool]:
    if value is None:
        return default, True
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default, False
    if not math.isfinite(value):
        return default, False
    return value, True


def _nonnegative_int(value: object, default: int) -> tuple[int, bool]:
    if value is None:
        return default, True
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return default, False
    return value, True


def _timestamp(value: object, default: str) -> tuple[str, bool]:
    if value is None:
        return default, True
    if not isinstance(value, str) or not value.strip():
        return default, False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return default, False
    return value, True


def _graph_is_valid(graph: object, run_root: object = None) -> bool:
    if not isinstance(graph, Mapping):
        return False
    run_id = graph.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        return False
    structural_errors = validate_evidence_graph_structure(graph)
    if structural_errors:
        return False
    if run_root is not None:
        return not validate_evidence_graph(graph, run_root)
    return True


def _default_created_at(graph: Mapping[str, Any]) -> str:
    value = graph.get("generated_at")
    return value if isinstance(value, str) and value.strip() else _EPOCH


def _default_node_ids(
    graph: Mapping[str, Any], gap_type: str, article_id: str = ""
) -> list[str]:
    payload = graph.get("payload", {})
    nodes = payload.get("nodes", {}) if isinstance(payload, Mapping) else {}
    if not isinstance(nodes, Mapping):
        return []
    wanted = {
        "title_core_fact": {"title"},
        "opening_support": {"opening"},
        "key_fact_cross_check": {"claim"},
        "audience_sample": {"material"},
        "industry_relevance": {"material"},
        "source_failure": {"source"},
        "dynamic_fact_revalidation": {"claim", "source", "material"},
        "dedupe_context": {"topic"},
    }.get(gap_type, set())
    result = []
    for node_id, node in nodes.items():
        if not isinstance(node, Mapping) or node.get("node_type") not in wanted:
            continue
        if article_id and f":{article_id}" not in node_id:
            continue
        result.append(node_id)
    return sorted(result)


def _graph_has_title_stage(graph: Mapping[str, Any]) -> bool:
    """A title gap is meaningful only after a title node exists."""

    payload = graph.get("payload", {})
    nodes = payload.get("nodes", {}) if isinstance(payload, Mapping) else {}
    return isinstance(nodes, Mapping) and any(
        isinstance(node, Mapping) and node.get("node_type") == "title"
        for node in nodes.values()
    )


def _source_ids(record: Mapping[str, Any]) -> tuple[list[str], bool]:
    candidates: list[object] = []
    for key in ("failed_source_ids", "source_ids", "failed_source_id", "source_id"):
        if key in record:
            value = record[key]
            if isinstance(value, str):
                candidates.append(value)
            elif _is_sequence(value):
                candidates.extend(value)
            else:
                return [], False
    result = []
    for candidate in candidates:
        source_id = _text(candidate)
        if source_id.startswith("source:"):
            source_id = source_id[len("source:") :]
        if source_id:
            result.append(source_id)
    return sorted(set(result)), all(isinstance(item, str) for item in candidates)


def _record_is_gap(record: Mapping[str, Any], explicit_flag: object = None) -> bool:
    if isinstance(explicit_flag, bool):
        return not explicit_flag
    for key in ("is_gap", "gap"):
        if isinstance(record.get(key), bool):
            return record[key]
    if isinstance(record.get("passed"), bool):
        return not record["passed"]
    if isinstance(record.get("ok"), bool):
        return not record["ok"]
    status = record.get("status")
    if isinstance(status, bool):
        return not status
    if isinstance(status, str):
        lowered = status.strip().lower()
        if lowered in _POSITIVE_STATUSES:
            return False
        if lowered in _NEGATIVE_STATUSES:
            return True
    return True


def _flatten_audits(audits: object) -> tuple[list[dict[str, Any]], bool]:
    if not _is_sequence(audits):
        return [], False
    flattened: list[dict[str, Any]] = []
    for audit in audits:
        if not isinstance(audit, Mapping):
            return [], False
        parent = dict(audit)
        nested = parent.pop("gaps", None)
        if nested is None:
            nested = parent.pop("findings", None)
        if nested is not None:
            if not _is_sequence(nested):
                return [], False
            for item in nested:
                if not isinstance(item, Mapping):
                    return [], False
                merged = dict(parent)
                merged.update(item)
                flattened.append(merged)
            continue
        checks = parent.pop("checks", None)
        if isinstance(checks, Mapping):
            for check_name, check in checks.items():
                if isinstance(check, Mapping):
                    merged = dict(parent)
                    merged.update(check)
                    merged.setdefault("gap_type", check_name)
                    flattened.append(merged)
                elif isinstance(check, bool) or isinstance(check, str):
                    flattened.append({**parent, "gap_type": check_name, "status": check})
                else:
                    return [], False
            continue
        if checks is not None:
            return [], False
        found_key = False
        for key in GAP_TYPES:
            if key not in parent:
                continue
            found_key = True
            value = parent[key]
            if isinstance(value, Mapping):
                merged = dict(parent)
                merged.pop(key, None)
                merged.update(value)
                merged.setdefault("gap_type", key)
                flattened.append(merged)
            elif isinstance(value, bool) or isinstance(value, str):
                flattened.append({**parent, "gap_type": key, "status": value})
            else:
                return [], False
        if found_key:
            continue
        flattened.append(parent)
    return flattened, True


def _audit_records(audits: object) -> tuple[list[dict[str, Any]], bool]:
    flattened, valid = _flatten_audits(audits)
    if not valid:
        return [], False
    records: list[dict[str, Any]] = []
    for index, raw in enumerate(flattened):
        record = dict(raw)
        gap_type = _canonical_gap_type(
            record.get("gap_type") or record.get("check") or record.get("kind") or record.get("type")
        )
        if not gap_type:
            # A normal passing audit may have no gap type.  It contributes no task.
            if _record_is_gap(record) and any(
                key in record for key in ("status", "passed", "ok", "is_gap", "gap")
            ):
                return [], False
            continue
        if not _record_is_gap(record):
            continue
        record["gap_type"] = gap_type
        record["_audit_index"] = index
        records.append(record)
    return records, True


def _gap_id(record: Mapping[str, Any], gap_type: str, affected: list[str], index: int) -> str:
    explicit = _text(record.get("gap_id") or record.get("id"))
    if explicit:
        return explicit
    audit_id = _text(record.get("audit_id") or record.get("check_id"))
    if audit_id:
        return f"gap:{gap_type}:{audit_id}"
    scope = _text(record.get("article_id") or record.get("topic_id"))
    if scope:
        return f"gap:{gap_type}:{scope}"
    if affected:
        return f"gap:{gap_type}:{','.join(affected)}"
    return f"gap:{gap_type}:{index:04d}"


def _make_gap(
    graph: Mapping[str, Any], record: Mapping[str, Any], index: int
) -> dict[str, Any] | None:
    gap_type = _canonical_gap_type(record.get("gap_type"))
    if gap_type not in GAP_TYPES:
        return None
    if gap_type == "title_core_fact" and not _graph_has_title_stage(graph):
        # A title gap is a title-packaging concern.  Do not let an eager audit
        # turn a not-yet-created title into a content-stage blocker.
        return None
    defaults = _DEFAULTS[gap_type]
    article_id = _text(record.get("article_id"))
    raw_nodes = record.get(
        "affected_nodes",
        record.get("node_ids", record.get("affected_node", record.get("node_id"))),
    )
    nodes_were_provided = any(
        key in record for key in ("affected_nodes", "node_ids", "affected_node", "node_id")
    )
    affected, valid_nodes = _unique_strings(raw_nodes)
    if not valid_nodes:
        return None
    source_ids, valid_sources = _source_ids(record)
    if not valid_sources:
        return None
    if not affected and source_ids and gap_type == "source_failure":
        impacted: set[str] = set()
        for source_id in source_ids:
            impacted.update(trace_impact(graph, f"source:{source_id}"))
        affected = sorted(impacted)
    if not affected and not nodes_were_provided:
        affected = _default_node_ids(graph, gap_type, article_id)
    if gap_type == "source_failure" and not source_ids:
        source_ids = sorted(
            node_id[len("source:") :]
            for node_id in affected
            if node_id.startswith("source:")
        )
    if gap_type == "source_failure" and not source_ids:
        return None

    blocking, impact, risk, confidence, effort, retryable = defaults
    priority = record.get("priority")
    if isinstance(priority, Mapping):
        record = {**dict(priority), **dict(record)}
    for field, default in (
        ("blocking", blocking),
        ("impact", impact),
        ("risk", risk),
        ("confidence", confidence),
        ("effort", effort),
    ):
        if field not in record:
            continue
        if field == "blocking":
            if not isinstance(record[field], bool):
                return None
            blocking = record[field]
        else:
            value, valid = _number(record[field], default)
            if not valid:
                return None
            if value < 0:
                return None
            if field == "impact":
                impact = value
            elif field == "risk":
                risk = value
            elif field == "confidence":
                confidence = value
            else:
                effort = value
    if "retryable" in record:
        if not isinstance(record["retryable"], bool):
            return None
        retryable = record["retryable"]
    attempts, valid = _nonnegative_int(
        record.get("attempts", record.get("attempt_count")), 0
    )
    if not valid:
        return None
    consecutive, valid = _nonnegative_int(
        record.get("consecutive_failures", record.get("consecutive_failed_attempts")),
        0,
    )
    if not valid:
        return None
    created_at, valid = _timestamp(record.get("created_at"), _default_created_at(graph))
    if not valid:
        return None
    evidence_refs, valid = _unique_strings(
        record.get("evidence_refs", record.get("evidence_ref"))
    )
    if not valid:
        return None
    gap_id = _gap_id(record, gap_type, affected, index)
    if not gap_id:
        return None
    reason = _text(
        record.get("reason")
        or record.get("message")
        or record.get("detail")
        or record.get("description")
    ) or f"{gap_type} requires evidence recovery"
    disposition = _text(record.get("disposition"))
    if consecutive >= 2 and not disposition:
        disposition = "switch_topic_recommended"
    result: dict[str, Any] = {
        "gap_id": gap_id,
        "gap_type": gap_type,
        "blocking": blocking,
        "impact": impact,
        "risk": risk,
        "confidence": confidence,
        "effort": effort,
        "affected_nodes": affected,
        "failed_source_ids": source_ids,
        "retryable": retryable,
        "attempts": attempts,
        "consecutive_failures": consecutive,
        "created_at": created_at,
        "reason": reason,
        "evidence_refs": evidence_refs,
    }
    for field in ("article_id", "topic_id", "audit_id"):
        value = _text(record.get(field))
        if value:
            result[field] = value
    if len(source_ids) == 1:
        result["failed_source_id"] = source_ids[0]
    if disposition:
        result["disposition"] = disposition
    return result


def _graph_source_gaps(graph: Mapping[str, Any]) -> list[dict[str, Any]]:
    payload = graph.get("payload", {})
    nodes = payload.get("nodes", {}) if isinstance(payload, Mapping) else {}
    result = []
    for node_id, node in sorted(nodes.items()):
        if (
            not isinstance(node_id, str)
            or not isinstance(node, Mapping)
            or node.get("node_type") != "source"
            or node.get("status") not in {"missing", "stale"}
        ):
            continue
        source_id = node_id[len("source:") :] if node_id.startswith("source:") else node_id
        affected = trace_impact(graph, node_id)
        result.append(
            _make_gap(
                graph,
                {
                    "gap_type": "source_failure",
                    "gap_id": f"gap:source_failure:{source_id}",
                    "affected_nodes": affected,
                    "failed_source_ids": [source_id],
                    "reason": "source node is missing or stale",
                    "created_at": graph.get("generated_at", _EPOCH),
                },
                len(result),
            )
        )
    return [item for item in result if item is not None]


def _graph_structural_gaps(graph: Mapping[str, Any]) -> list[dict[str, Any]]:
    payload = graph.get("payload", {})
    nodes = payload.get("nodes", {}) if isinstance(payload, Mapping) else {}
    edges = payload.get("edges", []) if isinstance(payload, Mapping) else []
    incoming: dict[str, list[Mapping[str, Any]]] = {node_id: [] for node_id in nodes}
    for edge in edges:
        if isinstance(edge, Mapping) and edge.get("to") in incoming:
            incoming[edge["to"]].append(edge)
    result: list[dict[str, Any]] = []
    for node_id, node in sorted(nodes.items()):
        if not isinstance(node, Mapping) or node.get("status") not in {"missing", "stale"}:
            continue
        node_type = node.get("node_type")
        gap_type = {
            "title": "title_core_fact",
            "opening": "opening_support",
        }.get(node_type)
        if not gap_type:
            continue
        result.append(
            _make_gap(
                graph,
                {
                    "gap_type": gap_type,
                    "gap_id": f"gap:{gap_type}:{node_id}",
                    "affected_nodes": [node_id],
                    "reason": f"{node_type} node is missing or stale",
                    "created_at": graph.get("generated_at", _EPOCH),
                },
                len(result),
            )
        )
    for node_id, node in sorted(nodes.items()):
        if not isinstance(node, Mapping) or node.get("node_type") != "opening":
            continue
        if node.get("status") in {"missing", "stale"}:
            continue
        has_claim_support = any(
            edge.get("edge_type") == "materialized_as"
            and isinstance(edge.get("from"), str)
            and isinstance(known_parent := nodes.get(edge.get("from")), Mapping)
            and known_parent.get("node_type") == "claim"
            for edge in incoming.get(node_id, [])
            if isinstance(edge, Mapping)
        )
        if has_claim_support:
            continue
        result.append(
            _make_gap(
                graph,
                {
                    "gap_type": "opening_support",
                    "gap_id": f"gap:opening_support:{node_id}",
                    "affected_nodes": [node_id],
                    "reason": "opening has no supporting claim edge",
                    "created_at": graph.get("generated_at", _EPOCH),
                },
                len(result),
            )
        )
    for node_id, node in sorted(nodes.items()):
        if not isinstance(node, Mapping) or node.get("node_type") != "claim":
            continue
        supported = [
            edge
            for edge in edges
            if isinstance(edge, Mapping)
            and edge.get("from") == node_id
            and edge.get("edge_type") == "supported_by"
        ]
        if supported:
            continue
        result.append(
            _make_gap(
                graph,
                {
                    "gap_type": "key_fact_cross_check",
                    "gap_id": f"gap:key_fact_cross_check:{node_id}",
                    "affected_nodes": [node_id],
                    "reason": "claim has no supporting source edge",
                    "created_at": graph.get("generated_at", _EPOCH),
                },
                len(result),
            )
        )
    return [item for item in result if item is not None]


def _merge_duplicate_gaps(gaps: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, tuple[str, ...], tuple[str, ...]], dict[str, Any]] = {}
    for gap in gaps:
        key = (
            gap["gap_type"],
            tuple(gap.get("affected_nodes", [])),
            tuple(gap.get("failed_source_ids", [])),
        )
        if key not in merged:
            merged[key] = deepcopy(dict(gap))
            continue
        existing = merged[key]
        existing["affected_nodes"] = sorted(
            set(existing.get("affected_nodes", [])) | set(gap.get("affected_nodes", []))
        )
        existing["failed_source_ids"] = sorted(
            set(existing.get("failed_source_ids", []))
            | set(gap.get("failed_source_ids", []))
        )
        existing["evidence_refs"] = sorted(
            set(existing.get("evidence_refs", [])) | set(gap.get("evidence_refs", []))
        )
        existing["attempts"] = max(existing.get("attempts", 0), gap.get("attempts", 0))
        existing["consecutive_failures"] = max(
            existing.get("consecutive_failures", 0), gap.get("consecutive_failures", 0)
        )
    return list(merged.values())


def _prepare_gap(gap: object) -> tuple[dict[str, Any] | None, list[str]]:
    if not isinstance(gap, Mapping):
        return None, ["invalid:gap"]
    gap_type = _canonical_gap_type(gap.get("gap_type"))
    if gap_type not in GAP_TYPES:
        return None, ["invalid:gap_type"]
    gap_id = _text(gap.get("gap_id"))
    if not gap_id:
        return None, ["missing:gap_id"]
    defaults = _DEFAULTS[gap_type]
    result = deepcopy(dict(gap))
    result["gap_type"] = gap_type
    result["gap_id"] = gap_id
    if not isinstance(result.get("blocking", defaults[0]), bool):
        return None, ["invalid:blocking"]
    result.setdefault("blocking", defaults[0])
    for field, default in zip(("impact", "risk", "confidence", "effort"), defaults[1:5]):
        value, valid = _number(result.get(field), default)
        if not valid:
            return None, [f"invalid:{field}"]
        if value < 0:
            return None, [f"invalid:{field}"]
        result[field] = value
    nodes, valid = _unique_strings(result.get("affected_nodes"))
    if not valid:
        return None, ["invalid:affected_nodes"]
    sources, valid = _unique_strings(result.get("failed_source_ids"))
    if not valid:
        return None, ["invalid:failed_source_ids"]
    refs, valid = _unique_strings(result.get("evidence_refs"))
    if not valid:
        return None, ["invalid:evidence_refs"]
    result["affected_nodes"] = nodes
    result["failed_source_ids"] = sources
    result["evidence_refs"] = refs
    if not isinstance(result.get("retryable", defaults[5]), bool):
        return None, ["invalid:retryable"]
    result.setdefault("retryable", defaults[5])
    attempts, valid = _nonnegative_int(result.get("attempts"), 0)
    if not valid:
        return None, ["invalid:attempts"]
    consecutive, valid = _nonnegative_int(result.get("consecutive_failures"), 0)
    if not valid:
        return None, ["invalid:consecutive_failures"]
    result["attempts"] = attempts
    result["consecutive_failures"] = consecutive
    created_at, valid = _timestamp(result.get("created_at"), _EPOCH)
    if not valid:
        return None, ["invalid:created_at"]
    result["created_at"] = created_at
    return result, []


def derive_gap_tasks(
    graph: Mapping[str, Any],
    audits: Sequence[Mapping[str, Any]],
    *,
    run_root: object = None,
) -> list[dict[str, Any]]:
    """Derive only auditable V4 gap tasks from a closed evidence graph and audits."""

    if not _graph_is_valid(graph, run_root):
        return []
    records, valid = _audit_records(audits)
    if not valid:
        return []
    gaps: list[dict[str, Any]] = _graph_source_gaps(graph)
    gaps.extend(_graph_structural_gaps(graph))
    for index, record in enumerate(records):
        if record.get("gap_type") == "title_core_fact" and not _graph_has_title_stage(graph):
            continue
        item = _make_gap(graph, record, index)
        if item is None:
            return []
        gaps.append(item)
    return rank_gap_tasks(_merge_duplicate_gaps(gaps))


def rank_gap_tasks(gaps: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return stable copies sorted by the exact V4 priority tuple."""

    if not _is_sequence(gaps):
        return []
    prepared: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for gap in gaps:
        item, errors = _prepare_gap(gap)
        if errors or item is None or item["gap_id"] in seen_ids:
            return []
        seen_ids.add(item["gap_id"])
        prepared.append(item)
    return sorted(
        prepared,
        key=lambda item: (
            -int(item["blocking"]),
            -item["impact"],
            -item["risk"],
            -item["confidence"],
            item["effort"],
            item["created_at"],
            item["gap_id"],
        ),
    )


def _invalid_attempt(gap: object, reason: str) -> dict[str, Any]:
    result: dict[str, Any] = {"disposition": "invalid_input", "errors": [reason]}
    if isinstance(gap, Mapping):
        for field in ("gap_id", "gap_type"):
            value = _text(gap.get(field))
            if value:
                result[field] = value
    return result


def record_gap_attempt(
    gap: Mapping[str, Any], *, outcome: str, evidence_ref: str | None
) -> dict[str, Any]:
    """Record one attempt without changing topic or silently granting a state."""

    prepared, errors = _prepare_gap(gap)
    if errors or prepared is None:
        return _invalid_attempt(gap, errors[0] if errors else "invalid:gap")
    normalized_outcome = _text(outcome).lower()
    if normalized_outcome not in _FAILURE_OUTCOMES | _SUCCESS_OUTCOMES:
        return _invalid_attempt(gap, "invalid:outcome")
    if evidence_ref is not None and (not isinstance(evidence_ref, str) or not evidence_ref.strip()):
        return _invalid_attempt(gap, "invalid:evidence_ref")
    refs = list(prepared["evidence_refs"])
    if isinstance(evidence_ref, str) and evidence_ref.strip() and evidence_ref not in refs:
        refs.append(evidence_ref)
        refs.sort()
    attempts = prepared["attempts"] + 1
    previous_consecutive = prepared["consecutive_failures"]
    if "consecutive_failures" not in gap:
        last_outcome = _text(gap.get("last_outcome")).lower()
        if last_outcome in _FAILURE_OUTCOMES:
            previous_consecutive = max(previous_consecutive, prepared["attempts"])
        elif last_outcome in _SUCCESS_OUTCOMES:
            previous_consecutive = 0
        elif attempts > 1:
            previous_consecutive = max(previous_consecutive, prepared["attempts"])
    if normalized_outcome in _FAILURE_OUTCOMES:
        consecutive = previous_consecutive + 1
        disposition = (
            "switch_topic_recommended"
            if consecutive >= 2
            else ("retry_required" if prepared["retryable"] else "not_retryable")
        )
    else:
        consecutive = 0
        disposition = "resolved"
    result = deepcopy(prepared)
    result.update(
        {
            "attempts": attempts,
            "consecutive_failures": consecutive,
            "last_outcome": normalized_outcome,
            "evidence_refs": refs,
            "disposition": disposition,
        }
    )
    history = result.get("attempt_history", [])
    if not _is_sequence(history) or any(not isinstance(item, Mapping) for item in history):
        return _invalid_attempt(gap, "invalid:attempt_history")
    history = deepcopy(list(history))
    history.append(
        {
            "attempt": attempts,
            "outcome": normalized_outcome,
            "evidence_ref": evidence_ref,
        }
    )
    result["attempt_history"] = history
    return result
