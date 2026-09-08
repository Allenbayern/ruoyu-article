"""Deterministic, offline construction and impact tracing for the V4 evidence graph."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .contracts import NODE_TYPES, new_artifact_envelope, safe_relative_path, sha256_file, validate_artifact_envelope

_SCHEMA = "v4-evidence-graph-v1"
_STATUSES = {"present", "missing", "stale"}
_REQUIRED_NODE = ("node_id", "node_type", "status", "artifact_path", "artifact_sha256")
_REQUIRED_EDGE = ("from", "to", "edge_type", "locator", "created_at")
_ALLOWED = {
    ("topic", "supports", "claim"), ("claim", "supported_by", "source"),
    ("source", "captured_as", "material"),
    ("claim", "materialized_as", "title"), ("claim", "materialized_as", "opening"),
    ("claim", "materialized_as", "paragraph"), ("title", "reviewed_by", "review"),
    ("opening", "reviewed_by", "review"), ("paragraph", "reviewed_by", "review"),
}


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _read_json(root: Path, raw_path: object) -> dict[str, Any]:
    path = safe_relative_path(root, raw_path)
    if path is None or not path.is_file(): return {}
    try: value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError): return {}
    return value if isinstance(value, dict) else {}


def _read_required(root: Path, raw_path: object, label: str, errors: list[str]) -> dict[str, Any]:
    path = safe_relative_path(root, raw_path)
    if path is None: errors.append(f"missing:{label}:path"); return {}
    if not path.is_file(): errors.append(f"missing:{label}:{raw_path}"); return {}
    try: value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError): errors.append(f"malformed:{label}:{raw_path}"); return {}
    if not isinstance(value, dict): errors.append(f"invalid:{label}:object"); return {}
    return value


def _node(root: Path, node_id: str, node_type: str, artifact_path: str, **extra: Any) -> dict[str, Any]:
    resolved = safe_relative_path(root, artifact_path)
    present = resolved is not None and resolved.is_file()
    digest = None
    if present:
        try: digest = sha256_file(resolved)
        except OSError: present = False
    node = {"node_id": node_id, "node_type": node_type, "status": "present" if present else "missing", "artifact_path": artifact_path, "artifact_sha256": digest}
    node.update({key: value for key, value in extra.items() if value is not None})
    return node


def _edge(edges: list[dict[str, Any]], left: str, kind: str, right: str, locator: str, created_at: str) -> None:
    edges.append({"from": left, "to": right, "edge_type": kind, "locator": locator, "created_at": created_at})


def _find_output(outputs: Mapping[str, Any], key: str, article_id: str) -> str:
    values = outputs.get(key)
    if isinstance(values, str): return values
    if isinstance(values, list):
        return next((v for v in values if isinstance(v, str) and article_id in Path(v).name), "")
    return ""


def _merge_article(manifest: Mapping[str, Any], article: Mapping[str, Any]) -> dict[str, Any]:
    selected = next((x for x in manifest.get("selected_articles", []) if isinstance(x, Mapping) and x.get("article_id") == article.get("article_id")), {})
    merged = dict(selected) if isinstance(selected, Mapping) else {}; merged.update(article)
    outputs = manifest.get("outputs", {}) if isinstance(manifest.get("outputs"), Mapping) else {}
    inputs = manifest.get("inputs", {}) if isinstance(manifest.get("inputs"), Mapping) else {}
    aid = _text(merged.get("article_id"))
    merged.setdefault("topic_card_path", f"review/{aid}/topic-card.json")
    merged.setdefault("fact_card_path", f"review/{aid}/fact-card.json")
    merged.setdefault("citation_ledger_path", f"review/{aid}/citations-ledger.json")
    merged.setdefault("draft_path", _find_output(outputs, "drafts", aid) or f"drafts/{aid}.md")
    merged.setdefault("review_path", _find_output(outputs, "review_records", aid) or f"review/editorial-review-record-{aid}-v2.json")
    if not merged.get("material_pack_path"):
        packs = inputs.get("material_packs", []); task = _text(merged.get("crawl_task_id"))
        merged["material_pack_path"] = next((p for p in packs if isinstance(p, str) and (not task or task in p)), "")
    return merged


def _draft_locators(root: Path, draft_path: str) -> tuple[str, str, list[str]]:
    path = safe_relative_path(root, draft_path)
    if path is None or not path.is_file(): return "h1", "p1-s1", []
    try: lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError): return "h1", "p1-s1", []
    blocks: list[str] = []; block: list[str] = []
    for line in lines:
        value = line.strip()
        if value.startswith("#"):
            if block: blocks.append(" ".join(block)); block = []
        elif value: block.append(value)
        elif block: blocks.append(" ".join(block)); block = []
    if block: blocks.append(" ".join(block))
    locators = [f"p{i}-s1" for i in range(1, len(blocks) + 1)]
    return "h1", (locators[0] if locators else "p1-s1"), locators


def build_evidence_graph(run_root: Path, batch: Mapping[str, Any]) -> dict[str, Any]:
    root = Path(run_root); batch = batch if isinstance(batch, Mapping) else {}; build_errors: list[str] = []
    manifest_path = _text(batch.get("run_manifest_path")) or "run-manifest.json"
    use_manifest = (root / manifest_path).is_file() or not isinstance(batch.get("articles"), list)
    manifest = _read_required(root, manifest_path, "run_manifest", build_errors) if use_manifest else {}
    run_id = _text(batch.get("run_id") or manifest.get("run_id")) or "controlled-002"
    generated_at = _text(batch.get("generated_at") or manifest.get("created_at")) or "1970-01-01T00:00:00Z"
    outputs = manifest.get("outputs", {}) if isinstance(manifest.get("outputs"), Mapping) else {}
    source_manifest_path = _text(batch.get("source_manifest_path") or outputs.get("source_manifest")) or "source-manifest.json"
    source_manifest = _read_required(root, source_manifest_path, "source_manifest", build_errors)
    if "sources" not in source_manifest or not isinstance(source_manifest.get("sources"), list): build_errors.append("invalid:source_manifest:sources")
    source_records = {str(x.get("source_id")): x for x in source_manifest.get("sources", []) if isinstance(x, Mapping) and _text(x.get("source_id"))}
    raw_articles = batch.get("articles") if isinstance(batch.get("articles"), list) else manifest.get("selected_articles", [])
    nodes: dict[str, dict[str, Any]] = {}; edges: list[dict[str, Any]] = []
    for raw in raw_articles:
        if not isinstance(raw, Mapping): build_errors.append("invalid:article"); continue
        article = _merge_article(manifest, raw); aid = _text(article.get("article_id")); topic_id = _text(article.get("topic_id"))
        if not aid: build_errors.append("missing:article_id"); continue
        if not topic_id: build_errors.append(f"missing:topic_id:{aid}"); topic_id = f"missing:{aid}"
        topic_node = f"topic:{topic_id}"; topic_path = _text(article.get("topic_card_path"))
        _topic = _read_required(root, topic_path, f"topic:{aid}", build_errors)
        nodes[topic_node] = _node(root, topic_node, "topic", topic_path, locator="topic-card")
        fact_path = _text(article.get("fact_card_path")); ledger_path = _text(article.get("citation_ledger_path"))
        fact = _read_required(root, fact_path, f"fact:{aid}", build_errors); ledger = _read_required(root, ledger_path, f"ledger:{aid}", build_errors)
        if "permitted_claims" not in fact and "claims" not in fact: build_errors.append(f"invalid:fact:claims:{aid}")
        if "claims" not in ledger or not isinstance(ledger.get("claims"), list): build_errors.append(f"invalid:ledger:claims:{aid}")
        fact_claims = [x for x in fact.get("permitted_claims", fact.get("claims", [])) if isinstance(x, Mapping)]
        ledger_claims = {str(x.get("claim_id")): x for x in ledger.get("claims", []) if isinstance(x, Mapping) and _text(x.get("claim_id"))}
        fact_by_id = {str(x.get("claim_id")): x for x in fact_claims if _text(x.get("claim_id"))}
        inline_claims = article.get("claims", []) if isinstance(article.get("claims"), list) else []
        for inline in inline_claims:
            if not isinstance(inline, Mapping) or not _text(inline.get("claim_id")): continue
            claim_id = str(inline["claim_id"])
            if claim_id in fact_by_id:
                merged_claim = dict(fact_by_id[claim_id]); merged_sources = list(merged_claim.get("source_ids", []))
                for sid in inline.get("source_ids", []):
                    if sid not in merged_sources: merged_sources.append(sid)
                merged_claim["source_ids"] = merged_sources; fact_by_id[claim_id] = merged_claim
            else:
                fact_by_id[claim_id] = inline
        if not set(ledger_claims) <= set(fact_by_id): build_errors.append(f"mismatch:claim_ids:{aid}")
        for claim_id in sorted(set(fact_by_id) | set(ledger_claims)):
            fc, lc = fact_by_id.get(claim_id, {}), ledger_claims.get(claim_id, {})
            fs = set(fc.get("source_ids", [])) if isinstance(fc.get("source_ids", []), list) else set(); ls = set(lc.get("source_ids", [])) if isinstance(lc.get("source_ids", []), list) else set()
            if claim_id in fact_by_id and claim_id in ledger_claims and fs != ls: build_errors.append(f"mismatch:source_ids:{aid}:{claim_id}")
            cid = f"claim:{aid}:{claim_id}"; nodes[cid] = _node(root, cid, "claim", fact_path, claim_type=_text(fc.get("claim_type")) or "fact", locator=f"claim:{claim_id}")
            _edge(edges, topic_node, "supports", cid, _text(lc.get("source_locator") or fc.get("locator")) or f"claim:{claim_id}", generated_at)
            for sid in sorted(fs | ls):
                source = source_records.get(sid, {})
                if not source: build_errors.append(f"missing:source_manifest:{sid}")
                source_path = _text(source.get("relative_path") or source.get("path")); role = _text(source.get("role") or source.get("source_role"))
                nodes[f"source:{sid}"] = _node(root, f"source:{sid}", "source", source_path, source_role=role)
                _edge(edges, cid, "supported_by", f"source:{sid}", _text(lc.get("source_locator")) or f"source:{sid}", generated_at)
        pack_path = _text(article.get("material_pack_path")); pack = _read_required(root, pack_path, f"material_pack:{aid}", build_errors)
        if "materials" not in pack or not isinstance(pack.get("materials"), Mapping): build_errors.append(f"invalid:material_pack:materials:{aid}")
        materials = pack.get("materials", {}) if isinstance(pack.get("materials"), Mapping) else {}
        for category, values in materials.items():
            if not isinstance(values, list): build_errors.append(f"invalid:materials:{aid}:{category}"); continue
            for material in values:
                if not isinstance(material, Mapping) or not _text(material.get("material_id")): build_errors.append(f"invalid:material:{aid}"); continue
                mid = _text(material["material_id"]); mn = f"material:{mid}"; locator = _text(material.get("locator"))
                nodes[mn] = _node(root, mn, "material", pack_path, locator=locator, category=category)
                source_ids = material.get("source_ids", material.get("source_id", [])); source_ids = [source_ids] if isinstance(source_ids, str) else source_ids
                if not isinstance(source_ids, list): source_ids = []
                if not source_ids and _text(material.get("source_url")):
                    source_ids = [sid for sid, source in source_records.items() if _text(source.get("url")) == material.get("source_url")]
                for sid in source_ids:
                    sid = _text(sid)
                    if not sid: continue
                    source = source_records.get(sid, {}); spath = _text(source.get("relative_path") or source.get("path")); role = _text(source.get("role") or source.get("source_role"))
                    nodes[f"source:{sid}"] = _node(root, f"source:{sid}", "source", spath, source_role=role)
                    _edge(edges, f"source:{sid}", "captured_as", mn, locator or f"material:{mid}", generated_at)
        draft_path = _text(article.get("draft_path")); title_loc, opening_loc, paragraph_locs = _draft_locators(root, draft_path)
        title, opening = f"title:{aid}", f"opening:{aid}"; nodes[title] = _node(root, title, "title", draft_path, locator=title_loc); nodes[opening] = _node(root, opening, "opening", draft_path, locator=opening_loc)
        for loc in paragraph_locs: nodes[f"paragraph:{aid}:{loc}"] = _node(root, f"paragraph:{aid}:{loc}", "paragraph", draft_path, locator=loc)
        for cid, lc in ledger_claims.items():
            for loc in [x.strip() for x in _text(lc.get("draft_locator")).split(";") if x.strip()]:
                target = opening if loc == opening_loc else f"paragraph:{aid}:{loc}"
                if target in nodes: _edge(edges, f"claim:{aid}:{cid}", "materialized_as", target, loc, generated_at)
                paragraph_target = f"paragraph:{aid}:{loc}"
                if paragraph_target in nodes and paragraph_target != target: _edge(edges, f"claim:{aid}:{cid}", "materialized_as", paragraph_target, loc, generated_at)
            if opening_loc in _text(lc.get("draft_locator")): _edge(edges, f"claim:{aid}:{cid}", "materialized_as", title, opening_loc, generated_at)
        review_path = _text(article.get("review_path")); review = _read_required(root, review_path, f"review:{aid}", build_errors); rid = _text(review.get("article_id")) or aid; rn = f"review:{aid}:{rid}"; nodes[rn] = _node(root, rn, "review", review_path, locator=review_path)
        for component in [title, opening, *[key for key in nodes if key.startswith(f"paragraph:{aid}:")]]: _edge(edges, component, "reviewed_by", rn, review_path, generated_at)
    edges.sort(key=lambda x: (x["from"], x["edge_type"], x["to"], x["locator"])); payload: dict[str, Any] = {"nodes": nodes, "edges": edges}
    if build_errors: payload["build_errors"] = sorted(set(build_errors))
    return new_artifact_envelope(_SCHEMA, run_id, payload, generated_at=generated_at)


def _payload(graph: Mapping[str, Any]) -> Mapping[str, Any]:
    value = graph.get("payload") if isinstance(graph, Mapping) else None
    return value if isinstance(value, Mapping) else {}


def validate_evidence_graph(graph: Mapping[str, Any], run_root: Path) -> list[str]:
    if not isinstance(graph, Mapping): return ["invalid:graph"]
    errors = validate_artifact_envelope(graph, _SCHEMA, run_id=_text(graph.get("run_id")) or "__missing__"); payload = _payload(graph); nodes = payload.get("nodes"); edges = payload.get("edges")
    if not isinstance(nodes, Mapping): return errors + ["invalid:nodes"]
    if not isinstance(edges, list): return errors + ["invalid:edges"]
    errors.extend(f"build:{x}" for x in payload.get("build_errors", []) if isinstance(x, str))
    known: dict[str, Mapping[str, Any]] = {}
    for key, node in nodes.items():
        if not isinstance(key, str) or not isinstance(node, Mapping): errors.append("invalid:node"); continue
        for field in _REQUIRED_NODE:
            if field not in node: errors.append(f"missing:node:{field}:{key}")
        if node.get("node_id") != key: errors.append(f"mismatch:node_id:{key}")
        if not isinstance(node.get("node_id"), str) or not node.get("node_id"): errors.append(f"invalid:node_id:{key}")
        if not isinstance(node.get("node_type"), str) or node.get("node_type") not in NODE_TYPES: errors.append(f"unknown:node_type:{key}")
        if not isinstance(node.get("status"), str) or node.get("status") not in _STATUSES: errors.append(f"invalid:status:{key}")
        if not isinstance(node.get("artifact_path"), str) or not node.get("artifact_path"): errors.append(f"invalid:artifact_path:{key}")
        digest = node.get("artifact_sha256")
        if digest is not None and (not isinstance(digest, str) or len(digest) != 64): errors.append(f"invalid:artifact_sha256:{key}")
        if node.get("node_type") == "source" and not _text(node.get("source_role")): errors.append(f"missing:source_role:{key}")
        if node.get("node_type") == "claim" and not _text(node.get("claim_type")): errors.append(f"missing:claim_type:{key}")
        known[key] = node; path = safe_relative_path(Path(run_root), node.get("artifact_path"))
        if path is None: errors.append(f"invalid:path:{key}")
        elif not path.is_file() or digest is None: errors.append(f"missing:artifact:{key}")
        else:
            try:
                if digest != sha256_file(path): errors.append(f"mismatch:hash:{key}")
            except OSError: errors.append(f"missing:artifact:{key}")
    adjacency: dict[str, set[str]] = {key: set() for key in known}; incoming: dict[str, set[str]] = {key: set() for key in known}; signatures: set[tuple[Any, ...]] = set()
    for edge in edges:
        if not isinstance(edge, Mapping): errors.append("invalid:edge"); continue
        for field in _REQUIRED_EDGE:
            if field not in edge: errors.append(f"missing:edge:{field}")
            elif not isinstance(edge[field], str) or not edge[field]: errors.append(f"invalid:edge:{field}")
        left, right, kind = edge.get("from"), edge.get("to"), edge.get("edge_type")
        if not all(isinstance(value, str) for value in (left, right, kind)): continue
        if left not in known or right not in known: errors.append("unknown:edge_node"); continue
        left_type, right_type = known[left].get("node_type"), known[right].get("node_type")
        if not isinstance(left_type, str) or not isinstance(right_type, str) or (left_type, kind, right_type) not in _ALLOWED: errors.append(f"illegal:edge:{kind}"); continue
        sig = tuple(edge.get(x) for x in _REQUIRED_EDGE)
        if all(isinstance(value, str) for value in sig):
            if sig in signatures: errors.append("duplicate:edge")
            signatures.add(sig)
        adjacency[left].add(right); incoming[right].add(left)
    for key, node in known.items():
        kind = node.get("node_type")
        if isinstance(kind, str) and kind in {"title", "opening", "review"} and not incoming[key]: errors.append(f"isolated:{kind}:{key}")
        if kind == "claim":
            if not any(known[parent].get("node_type") == "topic" for parent in incoming[key]): errors.append(f"isolated:claim:{key}")
            if not any(known[child].get("node_type") == "source" for child in adjacency[key]): errors.append(f"unsupported:claim:{key}")
    return list(dict.fromkeys(errors))


def trace_impact(graph: Mapping[str, Any], node_id: str) -> list[str]:
    payload = _payload(graph); nodes = payload.get("nodes", {}); edges = payload.get("edges", [])
    if not isinstance(node_id, str) or not isinstance(nodes, Mapping) or node_id not in nodes or not isinstance(edges, list): return []
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        if not isinstance(edge, Mapping) or edge.get("from") not in nodes or edge.get("to") not in nodes: continue
        adjacency.setdefault(edge["from"], []).append(edge["to"])
        if edge.get("edge_type") == "supported_by": adjacency.setdefault(edge["to"], []).append(edge["from"])
    for values in adjacency.values(): values.sort()
    result: list[str] = []; seen = {node_id}; queue = deque([node_id])
    while queue:
        current = queue.popleft(); result.append(current)
        for child in adjacency.get(current, []):
            if child not in seen: seen.add(child); queue.append(child)
    return result


def invalidate_source(graph: Mapping[str, Any], source_id: str, reason: str) -> dict[str, Any]:
    changed = deepcopy(dict(graph)); payload = changed.get("payload")
    if not isinstance(payload, dict): return changed
    if not isinstance(source_id, str): return changed
    canonical = source_id if source_id.startswith("source:") else f"source:{source_id}"; nodes = payload.get("nodes")
    if not isinstance(nodes, dict) or canonical not in nodes: return changed
    affected = trace_impact(changed, canonical)
    for node_id in affected:
        if isinstance(nodes.get(node_id), dict):
            nodes[node_id]["status"] = "stale"
            reasons = nodes[node_id].setdefault("invalidation_reasons", [])
            if isinstance(reasons, list) and reason not in reasons: reasons.append(reason)
    records = payload.setdefault("invalidations", [])
    if isinstance(records, list): records.append({"source_id": canonical, "reason": reason, "affected_nodes": affected})
    return changed
