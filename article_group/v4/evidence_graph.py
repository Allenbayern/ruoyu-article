"""Deterministic, offline evidence graph construction and impact tracing."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

from .contracts import (
    NODE_TYPES,
    new_artifact_envelope,
    safe_relative_path,
    sha256_file,
    validate_artifact_envelope,
)

_SCHEMA = "v4-evidence-graph-v1"
_ALLOWED = {
    ("topic", "supports", "claim"),
    ("claim", "supported_by", "source"),
    ("source", "captured_as", "material"),
    ("claim", "materialized_as", "title"),
    ("claim", "materialized_as", "opening"),
    ("claim", "materialized_as", "paragraph"),
    ("title", "reviewed_by", "review"),
    ("opening", "reviewed_by", "review"),
    ("paragraph", "reviewed_by", "review"),
}


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _read_json(root: Path, raw_path: object) -> dict[str, Any]:
    path = safe_relative_path(root, raw_path)
    if path is None or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _path_for(root: Path, raw: object, fallback: str) -> str:
    return _text(raw) or fallback


def _node(root: Path, node_id: str, node_type: str, artifact_path: str, **extra: Any) -> dict[str, Any]:
    resolved = safe_relative_path(root, artifact_path)
    exists = resolved is not None and resolved.is_file()
    digest = None
    if exists:
        try:
            digest = sha256_file(resolved)
        except OSError:
            exists = False
    result: dict[str, Any] = {
        "node_id": node_id,
        "node_type": node_type,
        "status": "present" if exists else "missing",
        "artifact_path": artifact_path,
        "artifact_sha256": digest,
    }
    result.update({key: value for key, value in extra.items() if value is not None})
    return result


def _add(nodes: dict[str, dict[str, Any]], item: dict[str, Any]) -> None:
    nodes[item["node_id"]] = item


def _edge(edges: list[dict[str, Any]], from_id: str, edge_type: str, to_id: str, *, locator: str = "", created_at: str) -> None:
    edges.append({"from": from_id, "to": to_id, "edge_type": edge_type, "locator": locator, "created_at": created_at})


def _source_records(root: Path, batch: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw_manifest = batch.get("source_manifest")
    manifest_path = batch.get("source_manifest_path", "source-manifest.json")
    if not isinstance(raw_manifest, Mapping) and not isinstance(raw_manifest, list):
        raw_manifest = _read_json(root, manifest_path).get("sources", [])
    if isinstance(raw_manifest, Mapping):
        raw_manifest = raw_manifest.get("sources", [])
    result: dict[str, Mapping[str, Any]] = {}
    if isinstance(raw_manifest, list):
        for record in raw_manifest:
            if isinstance(record, Mapping):
                source_id = _text(record.get("source_id") or record.get("id"))
                if source_id:
                    result[source_id] = record
    return result


def build_evidence_graph(run_root: Path, batch: Mapping[str, Any]) -> dict[str, Any]:
    """Build a closed V4 envelope from explicit batch records and local files."""
    root = Path(run_root)
    batch = batch if isinstance(batch, Mapping) else {}
    run_id = _text(batch.get("run_id")) or "controlled-002"
    generated_at = _text(batch.get("generated_at")) or "1970-01-01T00:00:00Z"
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    topic = batch.get("topic") if isinstance(batch.get("topic"), Mapping) else {}
    topic_id = _text(topic.get("topic_id") or topic.get("id")) or "topic-1"
    articles_hint = batch.get("articles")
    first_article = articles_hint[0] if isinstance(articles_hint, list) and articles_hint and isinstance(articles_hint[0], Mapping) else {}
    topic_path = _path_for(root, topic.get("path"), _text(first_article.get("topic_card_path")) or "topic.json")
    _add(nodes, _node(root, f"topic:{topic_id}", "topic", topic_path))

    articles = batch.get("articles", [])
    if not isinstance(articles, list):
        articles = []
    source_records = _source_records(root, batch)
    referenced_sources: set[str] = set(source_records)
    for article in articles:
        if not isinstance(article, Mapping):
            continue
        article_id = _text(article.get("article_id") or article.get("id"))
        if not article_id:
            continue
        fact_path = _path_for(root, article.get("fact_card_path"), f"review/{article_id}/fact-card.json")
        fact = _read_json(root, fact_path)
        claims = article.get("claims", fact.get("claims", fact.get("permitted_claims", [])))
        if not claims:
            ledger_path = _path_for(root, article.get("citation_ledger_path"), f"review/{article_id}/citations-ledger.json")
            claims = _read_json(root, ledger_path).get("claims", [])
        if not isinstance(claims, list):
            claims = []
        claim_ids: list[str] = []
        for index, claim in enumerate(claims, 1):
            if not isinstance(claim, Mapping):
                continue
            claim_id = _text(claim.get("claim_id") or claim.get("id")) or f"{article_id}-claim-{index}"
            claim_node = f"claim:{article_id}:{claim_id}"
            claim_ids.append(claim_id)
            source_ids = claim.get("source_ids", claim.get("sources", []))
            if isinstance(source_ids, str):
                source_ids = [source_ids]
            if not isinstance(source_ids, list):
                source_ids = []
            for source_id in source_ids:
                if isinstance(source_id, Mapping):
                    source_id = source_id.get("source_id") or source_id.get("id")
                source_id = _text(source_id)
                if source_id:
                    referenced_sources.add(source_id)
            _add(nodes, _node(root, claim_node, "claim", fact_path, claim_type=_text(claim.get("claim_type")) or "fact"))
            _edge(edges, f"topic:{topic_id}", "supports", claim_node, created_at=generated_at)
            for source_id in source_ids:
                source_id = _text(source_id.get("source_id") if isinstance(source_id, Mapping) else source_id)
                if source_id:
                    _edge(edges, claim_node, "supported_by", f"source:{source_id}", created_at=generated_at)

        manifest = source_records
        for source_id in sorted(referenced_sources):
            record = manifest.get(source_id, {})
            source_path = _path_for(root, (record.get("path") or record.get("relative_path")) if isinstance(record, Mapping) else None, f"sources/{source_id}.md")
            _add(nodes, _node(root, f"source:{source_id}", "source", source_path, source_role=_text(record.get("source_role") or record.get("role")) or "unknown"))
            material_path = _path_for(root, article.get("material_path"), f"materials/{source_id}.md")
            material_id = f"material:{source_id}"
            _add(nodes, _node(root, material_id, "material", material_path))
            _edge(edges, f"source:{source_id}", "captured_as", material_id, created_at=generated_at)

        draft_path = _path_for(root, article.get("draft_path") or article.get("markdown_path"), f"drafts/{article_id}.md")
        component_ids = [f"title:{article_id}", f"opening:{article_id}"]
        _add(nodes, _node(root, component_ids[0], "title", draft_path))
        _add(nodes, _node(root, component_ids[1], "opening", draft_path))
        paragraphs = article.get("paragraphs", [])
        if not isinstance(paragraphs, list):
            paragraphs = []
        for index, paragraph in enumerate(paragraphs, 1):
            paragraph = paragraph if isinstance(paragraph, Mapping) else {}
            paragraph_id = _text(paragraph.get("id") or paragraph.get("paragraph_id")) or f"p{index}"
            component_ids.append(f"paragraph:{article_id}:{paragraph_id}")
        for node_id in component_ids[2:]:
            _add(nodes, _node(root, node_id, "paragraph", draft_path))
        fallback_claims = claim_ids[:1]
        for component_id, component in zip(component_ids, [article.get("title"), article.get("opening"), *paragraphs]):
            claim_refs = component.get("claim_ids", []) if isinstance(component, Mapping) else fallback_claims
            if isinstance(claim_refs, str):
                claim_refs = [claim_refs]
            if not isinstance(claim_refs, list):
                claim_refs = fallback_claims
            for claim_id in claim_refs:
                claim_id = _text(claim_id)
                if claim_id:
                    _edge(edges, f"claim:{article_id}:{claim_id}", "materialized_as", component_id, created_at=generated_at)

        review_fallback = f"review/{article_id}/independent-review-result-v2.json"
        if (root / "review/independent-review-result-v2.json").is_file():
            review_fallback = "review/independent-review-result-v2.json"
        review_path = _path_for(root, article.get("review_path"), review_fallback)
        review_id = _text(article.get("review_id")) or f"{article_id}-review"
        review_node = f"review:{article_id}:{review_id}"
        _add(nodes, _node(root, review_node, "review", review_path))
        for component_id in component_ids:
            _edge(edges, component_id, "reviewed_by", review_node, created_at=generated_at)

    edges.sort(key=lambda item: (item["from"], item["edge_type"], item["to"], item["locator"]))
    payload = {"nodes": nodes, "edges": edges}
    return new_artifact_envelope(_SCHEMA, run_id, payload, generated_at=generated_at)


def _payload(graph: Mapping[str, Any]) -> Mapping[str, Any]:
    value = graph.get("payload") if isinstance(graph, Mapping) else None
    return value if isinstance(value, Mapping) else {}


def validate_evidence_graph(graph: Mapping[str, Any], run_root: Path) -> list[str]:
    if not isinstance(graph, Mapping):
        return ["invalid:graph"]
    run_id = _text(graph.get("run_id"))
    errors = validate_artifact_envelope(graph, _SCHEMA, run_id=run_id or "__missing__")
    payload = _payload(graph)
    nodes = payload.get("nodes")
    edges = payload.get("edges")
    if not isinstance(nodes, Mapping):
        return errors + ["invalid:nodes"]
    if not isinstance(edges, list):
        return errors + ["invalid:edges"]
    known: dict[str, Mapping[str, Any]] = {}
    for key, node in nodes.items():
        if not isinstance(key, str) or not isinstance(node, Mapping):
            errors.append("invalid:node")
            continue
        node_id = node.get("node_id")
        if node_id != key or node_id in known:
            errors.append(f"duplicate:node:{key}")
        known[key] = node
        if node.get("node_type") not in NODE_TYPES:
            errors.append(f"unknown:node_type:{key}")
        path = node.get("artifact_path")
        resolved = safe_relative_path(Path(run_root), path)
        if resolved is None:
            errors.append(f"invalid:path:{key}")
        elif resolved.is_file():
            try:
                if node.get("artifact_sha256") != sha256_file(resolved):
                    errors.append(f"mismatch:hash:{key}")
            except OSError:
                errors.append(f"missing:artifact:{key}")
        elif node.get("status") != "missing" or node.get("artifact_sha256") is not None:
            errors.append(f"missing:artifact:{key}")
        else:
            # Missing run-local evidence is represented in the graph, but it
            # still blocks a passing validation result.
            errors.append(f"missing:artifact:{key}")
    adjacency: dict[str, set[str]] = {key: set() for key in known}
    incoming: dict[str, set[str]] = {key: set() for key in known}
    for edge in edges:
        if not isinstance(edge, Mapping):
            errors.append("invalid:edge")
            continue
        left, right, kind = edge.get("from"), edge.get("to"), edge.get("edge_type")
        if left not in known or right not in known:
            errors.append("unknown:edge_node")
            continue
        if (known[left].get("node_type"), kind, known[right].get("node_type")) not in _ALLOWED:
            errors.append(f"illegal:edge:{kind}")
            continue
        adjacency[left].add(right)
        incoming[right].add(left)
    for key, node in known.items():
        if node.get("node_type") in {"title", "opening", "paragraph", "review"} and not incoming[key]:
            errors.append(f"isolated:{node.get('node_type')}:{key}")
        if node.get("node_type") == "claim":
            if not any(known[parent].get("node_type") == "topic" for parent in incoming[key]):
                errors.append(f"isolated:claim:{key}")
            if not any(known[child].get("node_type") == "source" for child in adjacency[key]):
                errors.append(f"unsupported:claim:{key}")
    return list(dict.fromkeys(errors))


def trace_impact(graph: Mapping[str, Any], node_id: str) -> list[str]:
    payload = _payload(graph)
    nodes = payload.get("nodes", {}) if isinstance(payload, Mapping) else {}
    edges = payload.get("edges", []) if isinstance(payload, Mapping) else []
    if not isinstance(nodes, Mapping) or node_id not in nodes or not isinstance(edges, list):
        return []
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        if isinstance(edge, Mapping) and edge.get("from") in nodes and edge.get("to") in nodes:
            adjacency.setdefault(edge["from"], []).append(edge["to"])
            # ``claim -supported_by-> source`` records evidence direction;
            # impact direction is dependency direction, so a source also
            # reaches the claims that depend on it.
            if edge.get("edge_type") == "supported_by":
                adjacency.setdefault(edge["to"], []).append(edge["from"])
    for values in adjacency.values():
        values.sort()
    result: list[str] = []
    seen = {node_id}
    queue = deque([node_id])
    while queue:
        current = queue.popleft()
        result.append(current)
        for child in adjacency.get(current, []):
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return result


def invalidate_source(graph: Mapping[str, Any], source_id: str, reason: str) -> dict[str, Any]:
    changed = deepcopy(dict(graph))
    payload = changed.get("payload")
    if not isinstance(payload, dict):
        return changed
    canonical = source_id if source_id.startswith("source:") else f"source:{source_id}"
    nodes = payload.get("nodes")
    if not isinstance(nodes, dict) or canonical not in nodes:
        return changed
    for impacted_id in trace_impact(changed, canonical):
        node = nodes.get(impacted_id)
        if isinstance(node, dict):
            node["status"] = "stale"
            reasons = node.setdefault("invalidation_reasons", [])
            if isinstance(reasons, list) and reason not in reasons:
                reasons.append(reason)
    return changed
