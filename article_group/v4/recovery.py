"""Offline, auditable recovery and manual-escalation actions for V4."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from typing import Any

from .contracts import EDGE_TYPES, NODE_TYPES, new_artifact_envelope, validate_artifact_envelope
from .evidence_graph import invalidate_source, trace_impact


_SCHEMA = "v4-recovery-actions-v1"
_GRAPH_SCHEMA = "v4-evidence-graph-v1"
_EPOCH = "1970-01-01T00:00:00Z"
_EVENT_ALIASES = {
    "duplicate": "duplicate_topic",
    "duplicate_topic_detected": "duplicate_topic",
    "fact_change": "fact_changed",
    "gap_failed_two_times": "gap_failed_twice",
    "gap_failure_twice": "gap_failed_twice",
    "material_insufficient": "material_insufficient",
    "material_shortage": "material_insufficient",
    "risk_high": "high_risk",
    "source_unavailable": "source_failure",
    "source_invalidated": "source_failure",
    "title_change": "title_changed",
}
_EVENT_TYPES = {
    "source_failure",
    "title_changed",
    "fact_changed",
    "duplicate_topic",
    "material_insufficient",
    "high_risk",
    "gap_failed_twice",
}
_ACTION_MAP: dict[str, tuple[str, str, str]] = {
    "source_failure": ("invalidate_source", "source_owner", "stale"),
    "title_changed": ("recheck_title_commitment", "editor", "recheck"),
    "fact_changed": ("revalidate_fact_bindings", "editor", "recheck"),
    "duplicate_topic": ("return_to_precheck", "controller", "precheck"),
    "material_insufficient": ("block_writing", "researcher", "blocked"),
    "high_risk": ("manual_l2_review", "controller", "manual_review"),
    "gap_failed_twice": ("switch_topic_recommended", "controller", "recommendation"),
}
_FORBIDDEN_STATES = {
    "authorized",
    "closed",
    "publish",
    "published",
    "publication_authorized",
    "r8",
}
_REQUIRED_ACTION_FIELDS = (
    "action_type",
    "affected_nodes",
    "required_owner",
    "next_state",
    "reason",
    "evidence_refs",
    "publication_authorization",
)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def _strings(value: object) -> tuple[list[str], bool]:
    if isinstance(value, str):
        value = [value]
    if value is None:
        return [], True
    if not _is_sequence(value):
        return [], False
    if any(not isinstance(item, str) or not item.strip() for item in value):
        return [], False
    return sorted(set(item.strip() for item in value)), True


def _canonical_event(value: object) -> str:
    raw = _text(value).lower().replace("-", "_").replace(" ", "_")
    if raw in _EVENT_TYPES:
        return raw
    return _EVENT_ALIASES.get(raw, "")


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _valid_graph(graph: object) -> bool:
    if not isinstance(graph, Mapping):
        return False
    run_id = graph.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        return False
    if validate_artifact_envelope(graph, _GRAPH_SCHEMA, run_id=run_id):
        return False
    payload = graph.get("payload")
    if not isinstance(payload, Mapping):
        return False
    nodes = payload.get("nodes")
    edges = payload.get("edges")
    if not isinstance(nodes, Mapping) or not isinstance(edges, list) or not nodes:
        return False
    for node_id, node in nodes.items():
        if (
            not isinstance(node_id, str)
            or not isinstance(node, Mapping)
            or node.get("node_id") != node_id
            or node.get("node_type") not in NODE_TYPES
            or node.get("status") not in {"present", "missing", "stale"}
        ):
            return False
    for edge in edges:
        if not isinstance(edge, Mapping):
            return False
        if not all(isinstance(edge.get(key), str) and edge[key] for key in ("from", "to", "edge_type")):
            return False
        if edge["edge_type"] not in EDGE_TYPES:
            return False
        if edge["from"] not in nodes or edge["to"] not in nodes:
            return False
    return True


def _event_nodes(graph: Mapping[str, Any], event: Mapping[str, Any], event_type: str) -> tuple[list[str], bool]:
    raw = event.get(
        "affected_nodes",
        event.get("node_ids", event.get("affected_node", event.get("node_id"))),
    )
    nodes, valid = _strings(raw)
    if not valid:
        return [], False
    if nodes:
        return nodes, True
    article_id = _text(event.get("article_id"))
    wanted = {
        "title_changed": {"title", "opening"},
        "fact_changed": {"claim", "source", "material", "paragraph"},
        "duplicate_topic": {"topic"},
        "material_insufficient": {"material"},
        "high_risk": {"claim", "paragraph", "review"},
        "gap_failed_twice": {"claim", "material", "source", "title", "opening", "paragraph"},
    }.get(event_type, set())
    graph_nodes = graph["payload"]["nodes"]
    selected = [
        node_id
        for node_id, node in graph_nodes.items()
        if isinstance(node, Mapping)
        and node.get("node_type") in wanted
        and (not article_id or f":{article_id}" in node_id)
    ]
    return sorted(selected), True


def _event_refs(event: Mapping[str, Any]) -> tuple[list[str], bool]:
    raw = event.get("evidence_refs", event.get("evidence_ref"))
    return _strings(raw)


def _source_id(event: Mapping[str, Any]) -> str:
    value = event.get("source_id", event.get("failed_source_id"))
    source_id = _text(value)
    return source_id[len("source:") :] if source_id.startswith("source:") else source_id


def _action_id(event: Mapping[str, Any], event_type: str, affected: list[str], refs: list[str]) -> str:
    event_id = _text(event.get("event_id") or event.get("id"))
    if event_id:
        return f"recovery:{event_type}:{event_id}"
    serial = json.dumps(
        {
            "event_type": event_type,
            "affected_nodes": affected,
            "evidence_refs": refs,
            "source_id": _source_id(event),
            "gap_id": _text(event.get("gap_id")),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"recovery:{event_type}:{hashlib.sha256(serial.encode()).hexdigest()[:16]}"


def _safe_event_action(
    graph: Mapping[str, Any], event: Mapping[str, Any], event_type: str
) -> tuple[dict[str, Any] | None, str | None]:
    action_type, owner, next_state = _ACTION_MAP[event_type]
    refs, valid = _event_refs(event)
    if not valid:
        return None, "invalid:evidence_refs"
    affected, valid = _event_nodes(graph, event, event_type)
    if not valid:
        return None, "invalid:affected_nodes"
    reason = _text(
        event.get("reason")
        or event.get("message")
        or event.get("detail")
        or event.get("description")
    ) or f"{event_type} requires controlled recovery"
    action: dict[str, Any] = {
        "action_id": _action_id(event, event_type, affected, refs),
        "event_type": event_type,
        "action_type": action_type,
        "affected_nodes": affected,
        "required_owner": owner,
        "next_state": next_state,
        "reason": reason,
        "evidence_refs": refs,
        "publication_authorization": "not_authorized",
    }
    if event_type == "source_failure":
        source_id = _source_id(event)
        if not source_id:
            return None, "missing:source_id"
        source_node = f"source:{source_id}"
        if source_node not in graph["payload"]["nodes"]:
            return None, f"unknown:source_id:{source_id}"
        changed = invalidate_source(graph, source_id, reason)
        stale_nodes = trace_impact(changed, source_node)
        action["source_id"] = source_id
        action["affected_nodes"] = stale_nodes
        action["stale_nodes"] = stale_nodes
        action["status_updates"] = [
            {"node_id": node_id, "status": "stale"} for node_id in stale_nodes
        ]
    elif event_type == "gap_failed_twice":
        gap_id = _text(event.get("gap_id"))
        if not gap_id:
            return None, "missing:gap_id"
        action["gap_id"] = gap_id
        action["recommendation_only"] = True
    return action, None


def _invalid_output(run_id: object, created_at: object, errors: list[str]) -> dict[str, Any]:
    safe_run_id = run_id if isinstance(run_id, str) and run_id.strip() else "__invalid__"
    safe_created_at = created_at if isinstance(created_at, str) else _EPOCH
    return new_artifact_envelope(
        _SCHEMA,
        safe_run_id,
        {
            "actions": [],
            "errors": sorted(set(errors)),
            "publication_authorization": "not_authorized",
        },
        generated_at=safe_created_at,
    )


def derive_recovery_actions(
    graph: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    created_at: str,
) -> dict[str, Any]:
    """Derive stable, non-authorising recovery actions from graph events."""

    errors: list[str] = []
    if not isinstance(run_id, str) or not run_id.strip():
        errors.append("missing:run_id")
    if not _valid_timestamp(created_at):
        errors.append("invalid:created_at")
    if not _valid_graph(graph):
        errors.append("invalid:graph")
    elif graph.get("run_id") != run_id:
        errors.append("mismatch:graph_run_id")
    if not _is_sequence(events):
        errors.append("invalid:events")
    if errors:
        return _invalid_output(run_id, created_at, errors)

    actions: list[dict[str, Any]] = []
    for index, raw_event in enumerate(events):
        if not isinstance(raw_event, Mapping):
            errors.append(f"invalid:event:{index}")
            continue
        if "created_at" in raw_event and not _valid_timestamp(raw_event["created_at"]):
            errors.append(f"invalid:event_created_at:{index}")
            continue
        if "run_id" in raw_event and raw_event.get("run_id") != run_id:
            errors.append(f"mismatch:event_run_id:{index}")
            continue
        if (
            "publication_authorization" in raw_event
            and raw_event.get("publication_authorization") != "not_authorized"
        ):
            errors.append(f"forbidden:event_authorization:{index}")
            continue
        event_type = _canonical_event(
            raw_event.get("event_type") or raw_event.get("type") or raw_event.get("event")
        )
        if not event_type:
            errors.append(f"invalid:event_type:{index}")
            continue
        action, error = _safe_event_action(graph, raw_event, event_type)
        if error:
            errors.append(f"event:{index}:{error}")
            continue
        if action is not None:
            actions.append(action)
    if errors:
        return _invalid_output(run_id, created_at, errors)
    actions.sort(
        key=lambda action: (
            action["event_type"],
            action["action_type"],
            tuple(action["affected_nodes"]),
            tuple(action["evidence_refs"]),
            action["action_id"],
        )
    )
    return new_artifact_envelope(
        _SCHEMA,
        run_id,
        {
            "actions": actions,
            "publication_authorization": "not_authorized",
        },
        generated_at=created_at,
    )


def validate_recovery_actions(actions: Mapping[str, Any]) -> list[str]:
    """Validate the closed recovery envelope and reject terminal/authorising actions."""

    if not isinstance(actions, Mapping):
        return ["invalid:recovery_actions"]
    run_id = actions.get("run_id")
    expected_run_id = run_id if isinstance(run_id, str) and run_id.strip() else "__missing__"
    errors = validate_artifact_envelope(
        actions, _SCHEMA, run_id=expected_run_id
    )
    payload = actions.get("payload")
    if not isinstance(payload, Mapping):
        return list(dict.fromkeys(errors + ["invalid:payload"]))
    if payload.get("publication_authorization") != "not_authorized":
        errors.append("publication_authorization_must_be_not_authorized")
    input_errors = payload.get("errors", [])
    if not isinstance(input_errors, list):
        errors.append("invalid:errors")
    elif input_errors:
        errors.extend(
            f"input:{item}" if isinstance(item, str) else "invalid:errors_item"
            for item in input_errors
        )
    raw_actions = payload.get("actions")
    if not isinstance(raw_actions, list):
        errors.append("invalid:actions")
        return list(dict.fromkeys(errors))
    action_ids: set[str] = set()
    for index, action in enumerate(raw_actions):
        if not isinstance(action, Mapping):
            errors.append(f"invalid:action:{index}")
            continue
        for key in _REQUIRED_ACTION_FIELDS:
            if key not in action:
                errors.append(f"missing:action:{key}:{index}")
        if any(key.startswith("authorization_") for key in action):
            errors.append(f"forbidden:action_authorization:{index}")
        action_id = _text(action.get("action_id"))
        if action_id:
            if action_id in action_ids:
                errors.append(f"duplicate:action_id:{action_id}")
            action_ids.add(action_id)
        for key in ("action_type", "required_owner", "next_state", "reason"):
            if key in action and (not isinstance(action[key], str) or not action[key].strip()):
                errors.append(f"invalid:action:{key}:{index}")
        next_state = _text(action.get("next_state")).lower()
        action_type = _text(action.get("action_type")).lower()
        if (
            next_state in _FORBIDDEN_STATES
            or action_type in _FORBIDDEN_STATES
            or any(token in next_state for token in ("closed", "publish", "r8", "authoriz"))
            or any(token in action_type for token in ("closed", "publish", "r8", "authoriz"))
        ):
            errors.append(f"forbidden:terminal_or_authorization:{index}")
        if "publication_authorization" in action and action["publication_authorization"] != "not_authorized":
            errors.append(f"publication_authorization_must_be_not_authorized:{index}")
        if "event_type" in action and not _canonical_event(action.get("event_type")):
            errors.append(f"invalid:action:event_type:{index}")
        affected, valid = _strings(action.get("affected_nodes"))
        if not valid:
            errors.append(f"invalid:action:affected_nodes:{index}")
        elif not isinstance(action.get("affected_nodes"), list) or len(affected) != len(action["affected_nodes"]):
            errors.append(f"invalid:action:affected_nodes:{index}")
        refs, valid = _strings(action.get("evidence_refs"))
        if not valid:
            errors.append(f"invalid:action:evidence_refs:{index}")
        elif refs != action.get("evidence_refs"):
            errors.append(f"unstable:action:evidence_refs:{index}")
        updates = action.get("status_updates")
        if updates is not None:
            if not isinstance(updates, list) or any(
                not isinstance(item, Mapping)
                or not isinstance(item.get("node_id"), str)
                or item.get("status") != "stale"
                for item in updates
            ):
                errors.append(f"invalid:action:status_updates:{index}")
    return list(dict.fromkeys(errors))
