"""Deterministic, offline construction and impact tracing for the V4 evidence graph."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any, Mapping

from ..article_first import ARTICLE_FIRST_CONTRACT_VERSION
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
_DISCOVERY_SOURCE_ROLES = frozenset(
    {
        "discovery_signal",
        "social_signal",
        "social",
        "trending",
        "hotlist",
        "hot_search",
        "heat_signal",
    }
)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _is_discovery_source_role(value: object) -> bool:
    role = _text(value).lower().replace("-", "_").replace(" ", "_")
    return role in _DISCOVERY_SOURCE_ROLES


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


def _put_node(
    nodes: dict[str, dict[str, Any]],
    node: dict[str, Any],
    errors: list[str],
) -> None:
    """Insert a node without allowing a later artifact to overwrite it."""

    node_id = node.get("node_id")
    if not isinstance(node_id, str) or not node_id:
        errors.append("invalid:node_id")
        return
    existing = nodes.get(node_id)
    if existing is None:
        nodes[node_id] = node
        return
    if existing != node:
        errors.append(f"duplicate:node:{node_id}")


def _claim_locator(
    fact_claim: Mapping[str, Any],
    ledger: Mapping[str, Any],
    claim_id: str,
    *,
    fact_card: Mapping[str, Any] | None = None,
) -> str:
    """Return an artifact locator, including the structured fact-card form."""

    for value in (
        fact_claim.get("locator"),
        fact_claim.get("claim_locator"),
        ledger.get("claim_locator"),
        ledger.get("locator"),
    ):
        locator = _text(value)
        if locator:
            return locator
    # The current fact-card format stores permitted claims without a per-claim
    # locator. This is a concrete JSON-field locator, not a node-id fallback.
    if isinstance(fact_card, Mapping) and isinstance(fact_card.get("permitted_claims"), list):
        return f"fact-card:permitted_claims[{claim_id}]"
    return ""


def _edge(edges: list[dict[str, Any]], left: str, kind: str, right: str, locator: str, created_at: str) -> None:
    edges.append({"from": left, "to": right, "edge_type": kind, "locator": locator, "created_at": created_at})


def _article_path_match(raw_path: str, article_id: str) -> bool:
    """Match an output to an article by a complete path component or stem."""

    try:
        path = Path(raw_path)
    except (TypeError, ValueError):
        return False
    return (
        article_id in path.parts
        or path.stem == article_id
        or re.search(
            rf"(?<![A-Za-z0-9]){re.escape(article_id)}(?![A-Za-z0-9])",
            raw_path,
        )
        is not None
    )


def _find_output(
    outputs: Mapping[str, Any],
    key: str,
    article_id: str,
    errors: list[str] | None = None,
) -> str:
    """Resolve exactly one output for an article, never by substring matching."""

    values = outputs.get(key)
    candidates: list[str] = []
    if isinstance(values, str):
        if _article_path_match(values, article_id):
            candidates = [values]
    elif isinstance(values, list):
        candidates = [
            value for value in values
            if isinstance(value, str) and _article_path_match(value, article_id)
        ]
    elif isinstance(values, Mapping):
        value = values.get(article_id)
        if isinstance(value, str) and value:
            candidates = [value]

    if len(candidates) == 1:
        return candidates[0]
    if errors is not None:
        if len(candidates) > 1:
            errors.append(f"ambiguous:output:{key}:{article_id}")
        elif values is not None:
            errors.append(f"missing:output:{key}:{article_id}")
    return ""


def _merge_article(
    manifest: Mapping[str, Any],
    article: Mapping[str, Any],
    errors: list[str] | None = None,
) -> dict[str, Any]:
    selected = next((x for x in manifest.get("selected_articles", []) if isinstance(x, Mapping) and x.get("article_id") == article.get("article_id")), {})
    merged = dict(selected) if isinstance(selected, Mapping) else {}; merged.update(article)
    outputs = manifest.get("outputs", {}) if isinstance(manifest.get("outputs"), Mapping) else {}
    inputs = manifest.get("inputs", {}) if isinstance(manifest.get("inputs"), Mapping) else {}
    aid = _text(merged.get("article_id"))
    if not merged.get("topic_card_path"):
        merged["topic_card_path"] = _find_output(outputs, "topic_cards", aid, errors)
    for field, output_key in (("fact_card_path", "fact_cards"), ("citation_ledger_path", "citation_ledgers"), ("draft_path", "drafts"), ("review_path", "review_records")):
        if not merged.get(field):
            merged[field] = _find_output(outputs, output_key, aid, errors)
    if not merged.get("material_pack_path"):
        packs = inputs.get("material_packs", []); task = _text(merged.get("crawl_task_id"))
        merged["material_pack_path"] = next((p for p in packs if isinstance(p, str) and (not task or task in p)), "")
    return merged


def _is_article_first_article(article: Mapping[str, Any]) -> bool:
    return bool(
        article.get("article_first_contract_version") == ARTICLE_FIRST_CONTRACT_VERSION
        or any(
            isinstance(article.get(field), str) and article.get(field).strip()
            for field in (
                "body_draft_path",
                "body_path",
                "content_fidelity_path",
                "content_fidelity_record_path",
                "title_pack_path",
                "title_review_path",
                "delivery_path",
            )
        )
    )


def _draft_locators(
    root: Path,
    draft_path: str,
    expected_title: str = "",
    errors: list[str] | None = None,
    *,
    require_h1: bool = True,
) -> tuple[str, str, list[tuple[str, list[str]]], dict[str, str]]:
    path = safe_relative_path(root, draft_path)
    if path is None or not path.is_file():
        if errors is not None:
            errors.append(f"missing:draft:{draft_path or 'path'}")
        return "", "", [], {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        if errors is not None:
            errors.append(f"malformed:draft:{draft_path}")
        return "", "", [], {}

    h1s: list[tuple[int, str]] = []
    in_fence = False
    for line_number, line in enumerate(lines, 1):
        if re.match(r"^[ \t]*```", line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"^[ \t]{0,3}#[ \t]+(.+?)[ \t]*#?[ \t]*$", line)
        if match:
            heading = match.group(1).strip()
            if heading:
                h1s.append((line_number, heading))
    title_locator = ""
    if require_h1:
        if len(h1s) != 1:
            if errors is not None:
                errors.append(f"invalid:h1:{draft_path}:count={len(h1s)}")
        else:
            heading = h1s[0][1]
            title_locator = f"h1:{heading}"
            if expected_title and heading != expected_title.strip():
                if errors is not None:
                    errors.append(f"mismatch:title:{draft_path}")
    elif h1s and errors is not None:
        errors.append(f"invalid:body_h1:{draft_path}:count={len(h1s)}")

    blocks: list[tuple[str, str]] = []; block: list[str] = []; section = ""; in_fence = False
    for line in lines:
        value = line.strip()
        if re.match(r"^```", value):
            if block:
                blocks.append((section, " ".join(block))); block = []
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if re.match(r"^#{1,6}(?:[ \t]+|$)", value):
            if block: blocks.append((section, " ".join(block))); block = []
            if value.startswith("## "):
                section = re.split(r"[，,：:。]", value[3:].strip(), maxsplit=1)[0]
                section = re.sub(r"\s+", "-", section)
        elif value: block.append(value)
        elif block: blocks.append((section, " ".join(block))); block = []
    if block: blocks.append((section, " ".join(block)))
    paragraph_data: list[tuple[str, list[str]]] = []; token_to_primary: dict[str, str] = {}; section_counts: dict[str, int] = {}
    boundary = re.compile(r"(?<=[。！？!?；;])")
    for index, (section_name, text) in enumerate(blocks, 1):
        sentences = [part.strip() for part in boundary.split(text) if part.strip()] or [text]
        aliases: list[str] = []
        primary = f"p{index}-s1"
        for sentence_index, _ in enumerate(sentences, 1):
            token = f"p{index}-s{sentence_index}"; aliases.append(token); token_to_primary[token] = primary
            if section_name:
                section_counts[section_name] = section_counts.get(section_name, 0) + 1
                section_token = f"§{section_name}-s{section_counts[section_name]}"
                aliases.append(section_token); token_to_primary[section_token] = primary
        paragraph_data.append((primary, aliases))
    opening = paragraph_data[0][0] if paragraph_data else ""
    return title_locator, opening, paragraph_data, token_to_primary


def _title_claim_ids(article: Mapping[str, Any], topic: Mapping[str, Any], claims: Mapping[str, Mapping[str, Any]], errors: list[str], article_id: str) -> list[str]:
    explicit = article.get("title_claim_ids", topic.get("title_claim_ids"))
    if explicit is not None:
        values = [explicit] if isinstance(explicit, str) else explicit
        if not isinstance(values, list): errors.append(f"invalid:title_claim_ids:{article_id}"); return []
        result = [_text(value) for value in values if _text(value)]
        for claim_id in result:
            if claim_id not in claims: errors.append(f"unknown:title_claim_id:{article_id}:{claim_id}")
        return result
    title = _text(article.get("title")); subject = _text(article.get("subject"))
    terms: set[str] = set()
    for value in (title, subject):
        for run in re.findall(r"[\u4e00-\u9fff]{2,}", value):
            terms.update(run[index:index + 2] for index in range(len(run) - 1))
        terms.update(re.findall(r"[A-Za-z0-9]{3,}", value))
    result = []
    for claim_id, claim in claims.items():
        claim_text = _text(claim.get("text") or claim.get("claim") or claim.get("claim_text"))
        if any(term in claim_text for term in terms): result.append(claim_id)
    if not result: errors.append(f"missing:title_binding:{article_id}")
    return result


def _input_hashes(
    root: Path,
    manifest_path: str,
    source_manifest_path: str,
) -> dict[str, str]:
    """Hash the manifests whose paths and source bindings define the graph."""

    result: dict[str, str] = {}
    for prefix, raw_path in (
        ("__run_manifest__:", manifest_path),
        ("__source_manifest__:", source_manifest_path),
    ):
        path = safe_relative_path(root, raw_path)
        if path is None or not path.is_file():
            continue
        try:
            result[f"{prefix}{raw_path}"] = sha256_file(path)
        except OSError:
            continue
    return result


def build_evidence_graph(run_root: Path, batch: Mapping[str, Any]) -> dict[str, Any]:
    root = Path(run_root); batch = batch if isinstance(batch, Mapping) else {}; build_errors: list[str] = []
    manifest_path = _text(batch.get("run_manifest_path")) or "run-manifest.json"
    manifest_file = safe_relative_path(root, manifest_path)
    use_manifest = (manifest_file is not None and manifest_file.is_file()) or not isinstance(batch.get("articles"), list)
    manifest = _read_required(root, manifest_path, "run_manifest", build_errors) if use_manifest else {}
    run_id = _text(batch.get("run_id") or manifest.get("run_id")) or "controlled-002"
    generated_at = _text(batch.get("generated_at") or manifest.get("created_at")) or "1970-01-01T00:00:00Z"
    outputs = manifest.get("outputs", {}) if isinstance(manifest.get("outputs"), Mapping) else {}
    source_manifest_path = _text(batch.get("source_manifest_path") or outputs.get("source_manifest")) or "source-manifest.json"
    source_manifest = _read_required(root, source_manifest_path, "source_manifest", build_errors)
    if "sources" not in source_manifest or not isinstance(source_manifest.get("sources"), list): build_errors.append("invalid:source_manifest:sources")
    source_records: dict[str, Mapping[str, Any]] = {}
    for source in source_manifest.get("sources", []):
        if not isinstance(source, Mapping) or not _text(source.get("source_id")):
            continue
        source_id = _text(source.get("source_id"))
        if source_id in source_records:
            build_errors.append(f"duplicate:source_id:{source_id}")
        else:
            source_records[source_id] = source
    if "articles" in batch and not isinstance(batch.get("articles"), list): build_errors.append("invalid:articles")
    if "articles" in batch and isinstance(batch.get("articles"), list) and not batch["articles"]: build_errors.append("missing:articles")
    selected = manifest.get("selected_articles", []) if isinstance(manifest.get("selected_articles"), list) else []
    explicit_articles = batch.get("articles") if isinstance(batch.get("articles"), list) else None
    for label, items in (("manifest_article_id", selected), ("article_id", explicit_articles or [])):
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, Mapping):
                continue
            article_id = _text(item.get("article_id"))
            if article_id and article_id in seen:
                build_errors.append(f"duplicate:{label}:{article_id}")
            elif article_id:
                seen.add(article_id)
    if manifest and explicit_articles is not None:
        selected_ids = {str(x.get("article_id")) for x in selected if isinstance(x, Mapping)}
        explicit_ids = {str(x.get("article_id")) for x in explicit_articles if isinstance(x, Mapping)}
        if selected_ids != explicit_ids: build_errors.append("mismatch:manifest_batch_article_ids")
        if len(selected) != 2: build_errors.append("invalid:article_count")
    raw_articles = explicit_articles if explicit_articles is not None else selected
    if not raw_articles: build_errors.append("missing:selected_articles")
    if len(raw_articles) != 2: build_errors.append("invalid:article_count")
    manifest = dict(manifest); manifest["_run_root"] = root
    nodes: dict[str, dict[str, Any]] = {}; edges: list[dict[str, Any]] = []
    for raw in raw_articles:
        if not isinstance(raw, Mapping): build_errors.append("invalid:article"); continue
        article = _merge_article(manifest, raw, build_errors); aid = _text(article.get("article_id")); topic_id = _text(article.get("topic_id"))
        if not aid: build_errors.append("missing:article_id"); continue
        if not topic_id: build_errors.append(f"missing:topic_id:{aid}"); topic_id = f"missing:{aid}"
        topic_node = f"topic:{topic_id}"; topic_path = _text(article.get("topic_card_path"))
        topic = _read_required(root, topic_path, f"topic:{aid}", build_errors)
        _put_node(nodes, _node(root, topic_node, "topic", topic_path, locator="topic-card"), build_errors)
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
        # A permitted fact that is not present in the current citation ledger
        # is not materialized in this draft; keeping it out avoids inventing a
        # draft/source locator for an unused claim.
        claim_ids = set(ledger_claims) | {
            _text(item.get("claim_id"))
            for item in inline_claims
            if isinstance(item, Mapping) and _text(item.get("claim_id"))
        }
        for claim_id in sorted(claim_ids):
            fc, lc = fact_by_id.get(claim_id, {}), ledger_claims.get(claim_id, {})
            fs = set(fc.get("source_ids", [])) if isinstance(fc.get("source_ids", []), list) else set(); ls = set(lc.get("source_ids", [])) if isinstance(lc.get("source_ids", []), list) else set()
            if claim_id in fact_by_id and claim_id in ledger_claims and fs != ls: build_errors.append(f"mismatch:source_ids:{aid}:{claim_id}")
            cid = f"claim:{aid}:{claim_id}"
            claim_locator = _claim_locator(fc, lc, claim_id, fact_card=fact)
            if not claim_locator:
                build_errors.append(f"missing:claim_locator:{aid}:{claim_id}")
            _put_node(
                nodes,
                _node(
                    root,
                    cid,
                    "claim",
                    fact_path,
                    claim_type=_text(fc.get("claim_type")) or "fact",
                    locator=claim_locator,
                ),
                build_errors,
            )
            support_locator = _text(lc.get("source_locator"))
            if not support_locator:
                build_errors.append(f"missing:source_locator:{aid}:{claim_id}")
            else:
                _edge(edges, topic_node, "supports", cid, support_locator, generated_at)
            for sid in sorted(fs | ls):
                source = source_records.get(sid, {})
                if not source: build_errors.append(f"missing:source_manifest:{sid}")
                source_path = _text(source.get("relative_path") or source.get("path")); role = _text(source.get("role") or source.get("source_role"))
                _put_node(nodes, _node(root, f"source:{sid}", "source", source_path, source_role=role), build_errors)
                if support_locator and _is_discovery_source_role(role):
                    build_errors.append(f"forbidden:discovery_source_support:{sid}")
                elif support_locator:
                    _edge(edges, cid, "supported_by", f"source:{sid}", support_locator, generated_at)
        pack_path = _text(article.get("material_pack_path")); pack = _read_required(root, pack_path, f"material_pack:{aid}", build_errors)
        if "materials" not in pack or not isinstance(pack.get("materials"), Mapping): build_errors.append(f"invalid:material_pack:materials:{aid}")
        materials = pack.get("materials", {}) if isinstance(pack.get("materials"), Mapping) else {}
        for category, values in materials.items():
            if not isinstance(values, list): build_errors.append(f"invalid:materials:{aid}:{category}"); continue
            for material in values:
                if not isinstance(material, Mapping) or not _text(material.get("material_id")): build_errors.append(f"invalid:material:{aid}"); continue
                mid = _text(material["material_id"]); mn = f"material:{mid}"; locator = _text(material.get("locator"))
                if not locator:
                    build_errors.append(f"missing:material_locator:{aid}:{mid}")
                _put_node(nodes, _node(root, mn, "material", pack_path, locator=locator, category=category), build_errors)
                source_ids = material.get("source_ids", material.get("source_id", [])); source_ids = [source_ids] if isinstance(source_ids, str) else source_ids
                if not isinstance(source_ids, list): build_errors.append(f"invalid:material_binding:{aid}:{mid}"); source_ids = []
                source_url = material.get("source_url")
                if not source_ids and source_url is not None and not isinstance(source_url, str): build_errors.append(f"invalid:material_binding:{aid}:{mid}")
                if not source_ids and _text(source_url):
                    source_ids = [sid for sid, source in source_records.items() if _text(source.get("url")) == source_url]
                if not source_ids: build_errors.append(f"missing:material_binding:{aid}:{mid}")
                for sid in source_ids:
                    sid = _text(sid)
                    if not sid or sid not in source_records: build_errors.append(f"unknown:material_binding:{aid}:{mid}:{sid}"); continue
                    source = source_records[sid]; spath = _text(source.get("relative_path") or source.get("path")); role = _text(source.get("role") or source.get("source_role"))
                    _put_node(nodes, _node(root, f"source:{sid}", "source", spath, source_role=role), build_errors)
                    if locator:
                        _edge(edges, f"source:{sid}", "captured_as", mn, locator, generated_at)
        modern = _is_article_first_article(article)
        body_path = _text(article.get("body_draft_path") or article.get("body_path") or article.get("draft_path"))
        delivery_path = _text(article.get("delivery_path") or article.get("markdown_path") or article.get("draft_path"))
        content_review_path = _text(
            article.get("content_review_path")
            or article.get("content_fidelity_path")
            or article.get("review_path")
        )
        title_pack_path = _text(article.get("title_pack_path"))
        title_review_path = _text(article.get("title_review_path"))
        title_pack = _read_json(root, title_pack_path) if modern and title_pack_path else {}
        if modern and title_pack_path and not title_pack:
            build_errors.append(f"malformed:title_pack:{title_pack_path}")

        selected_direction: Mapping[str, Any] | None = None
        if modern and title_pack.get("result") == "selected":
            selected_id = _text(title_pack.get("selected_title_id"))
            directions = title_pack.get("directions", [])
            if isinstance(directions, list):
                selected_direction = next(
                    (
                        item
                        for item in directions
                        if isinstance(item, Mapping)
                        and (
                            (selected_id and item.get("title_id") == selected_id)
                            or (not selected_id and item.get("selected") is True)
                        )
                    ),
                    None,
                )
        selected_title = _text(selected_direction.get("title")) if selected_direction else ""
        title_enabled = not modern or selected_direction is not None
        title_loc, opening_loc, paragraph_data, locator_map = _draft_locators(
            root,
            body_path,
            _text(article.get("title") or article.get("subject")),
            build_errors,
            require_h1=not modern,
        )
        title = f"title:{aid}"
        opening = f"opening:{aid}"
        if title_enabled and modern:
            title_loc, _, _, _ = _draft_locators(
                root,
                delivery_path,
                selected_title,
                build_errors,
                require_h1=True,
            )
        if title_enabled:
            _put_node(
                nodes,
                _node(
                    root,
                    title,
                    "title",
                    delivery_path if modern else body_path,
                    locator=title_loc,
                ),
                build_errors,
            )
        _put_node(nodes, _node(root, opening, "opening", body_path, locator=opening_loc), build_errors)
        for primary, aliases in paragraph_data:
            _put_node(nodes, _node(root, f"paragraph:{aid}:{primary}", "paragraph", body_path, locator=primary, locators=aliases), build_errors)
        current_claims = {claim_id: fact_by_id[claim_id] for claim_id in claim_ids if claim_id in fact_by_id}
        title_claim_ids: list[str] = []
        if title_enabled:
            title_article = dict(article)
            if modern and selected_title:
                title_article["title"] = selected_title
            if modern and selected_direction and selected_direction.get("claim_ids") is not None:
                title_article["title_claim_ids"] = selected_direction.get("claim_ids")
            title_claim_ids = _title_claim_ids(title_article, topic, current_claims, build_errors, aid)
            for claim_id in title_claim_ids:
                if claim_id in fact_by_id:
                    _edge(edges, f"claim:{aid}:{claim_id}", "materialized_as", title, "title", generated_at)
        for cid, lc in ledger_claims.items():
            for loc in [x.strip() for x in _text(lc.get("draft_locator")).split(";") if x.strip()]:
                primary = locator_map.get(loc)
                if primary is None: build_errors.append(f"unresolved:draft_locator:{aid}:{loc}"); continue
                paragraph_target = f"paragraph:{aid}:{primary}"
                _edge(edges, f"claim:{aid}:{cid}", "materialized_as", paragraph_target, loc, generated_at)
                if loc == opening_loc: _edge(edges, f"claim:{aid}:{cid}", "materialized_as", opening, loc, generated_at)
        review_path = content_review_path
        review = _read_required(root, review_path, f"review:{aid}", build_errors)
        rid = _text(review.get("review_id") or review.get("article_id")) or aid
        if modern:
            content_review = f"review:{aid}:content:{rid}"
            _put_node(
                nodes,
                _node(
                    root,
                    content_review,
                    "review",
                    review_path,
                    locator=review_path,
                    review_stage="content",
                ),
                build_errors,
            )
            for component in [opening, *[key for key in nodes if key.startswith(f"paragraph:{aid}:")]]:
                _edge(edges, component, "reviewed_by", content_review, review_path, generated_at)
            if title_enabled:
                title_review_artifact = title_review_path or title_pack_path or review_path
                title_review = f"review:{aid}:title:{title_review_artifact or rid}"
                _put_node(
                    nodes,
                    _node(
                        root,
                        title_review,
                        "review",
                        title_review_artifact,
                        locator=title_review_artifact,
                        review_stage="title",
                    ),
                    build_errors,
                )
                _edge(edges, title, "reviewed_by", title_review, title_review_artifact, generated_at)
        else:
            rn = f"review:{aid}:{rid}"
            _put_node(nodes, _node(root, rn, "review", review_path, locator=review_path), build_errors)
            for component in [title, opening, *[key for key in nodes if key.startswith(f"paragraph:{aid}:")]]: _edge(edges, component, "reviewed_by", rn, review_path, generated_at)
    edges.sort(key=lambda x: (x["from"], x["edge_type"], x["to"], x["locator"])); payload: dict[str, Any] = {"nodes": nodes, "edges": edges}
    if build_errors: payload["build_errors"] = sorted(set(build_errors))
    graph = new_artifact_envelope(_SCHEMA, run_id, payload, generated_at=generated_at)
    graph["input_hashes"] = _input_hashes(root, manifest_path, source_manifest_path)
    return graph


def _payload(graph: Mapping[str, Any]) -> Mapping[str, Any]:
    value = graph.get("payload") if isinstance(graph, Mapping) else None
    return value if isinstance(value, Mapping) else {}


def _validate_input_hashes(
    graph: Mapping[str, Any],
    run_root: Path,
    errors: list[str],
) -> dict[str, Mapping[str, Any]]:
    """Recheck graph-defining manifests and return the current source map."""

    hashes = graph.get("input_hashes")
    if not isinstance(hashes, Mapping):
        errors.append("invalid:input_hashes")
        return {}
    source_records: dict[str, Mapping[str, Any]] = {}
    for key, expected in hashes.items():
        if not isinstance(key, str) or not isinstance(expected, str):
            continue
        if key.startswith("__source_manifest__:"):
            raw_path = key.split(":", 1)[1]
            label = "source_manifest"
        elif key.startswith("__run_manifest__:"):
            raw_path = key.split(":", 1)[1]
            label = "run_manifest"
        else:
            continue
        path = safe_relative_path(Path(run_root), raw_path)
        if path is None or not path.is_file():
            errors.append(f"missing:input_hash:{label}:{raw_path}")
            continue
        try:
            actual = sha256_file(path)
        except OSError:
            errors.append(f"missing:input_hash:{label}:{raw_path}")
            continue
        if actual != expected:
            errors.append(f"mismatch:input_hash:{label}:{raw_path}")
        if label == "source_manifest":
            manifest = _read_json(Path(run_root), raw_path)
            records = manifest.get("sources")
            if isinstance(records, list):
                for record in records:
                    if not isinstance(record, Mapping):
                        continue
                    source_id = _text(record.get("source_id"))
                    if source_id and source_id not in source_records:
                        source_records[source_id] = record
    return source_records


def validate_evidence_graph_structure(graph: Mapping[str, Any]) -> list[str]:
    """Validate graph structure without touching the run filesystem.

    Gap and recovery derivation can be used with an in-memory graph in unit
    tests, while the full graph validator additionally verifies every file
    hash against a supplied run root.  This structural gate keeps the former
    fail-closed instead of accepting a barely-shaped envelope.
    """

    if not isinstance(graph, Mapping):
        return ["invalid:graph"]
    run_id = _text(graph.get("run_id")) or "__missing__"
    errors = validate_artifact_envelope(graph, _SCHEMA, run_id=run_id)
    if set(graph) != {"schema_version", "run_id", "generated_at", "input_hashes", "payload"}:
        errors.append("invalid:top_level")
    payload = _payload(graph)
    nodes = payload.get("nodes")
    edges = payload.get("edges")
    if not isinstance(nodes, Mapping):
        errors.append("invalid:nodes")
        return list(dict.fromkeys(errors))
    if not nodes:
        errors.append("invalid:empty_nodes")
    if not isinstance(edges, list):
        errors.append("invalid:edges")
        return list(dict.fromkeys(errors))
    if not edges:
        errors.append("invalid:empty_edges")
    if "publication_authorization" in payload:
        errors.append("publication_authorization_must_not_be_present")
    build_errors = payload.get("build_errors")
    if isinstance(build_errors, list):
        errors.extend(f"build:{item}" for item in build_errors if isinstance(item, str))
    elif build_errors is not None:
        errors.append("invalid:build_errors")

    known: dict[str, Mapping[str, Any]] = {}
    for key, node in nodes.items():
        if not isinstance(key, str) or not isinstance(node, Mapping):
            errors.append("invalid:node")
            continue
        for field in _REQUIRED_NODE:
            if field not in node:
                errors.append(f"missing:node:{field}:{key}")
        if node.get("node_id") != key:
            errors.append(f"mismatch:node_id:{key}")
        node_type = node.get("node_type")
        if node_type not in NODE_TYPES:
            errors.append(f"unknown:node_type:{key}")
        if node.get("status") not in _STATUSES:
            errors.append(f"invalid:status:{key}")
        path = node.get("artifact_path")
        if not isinstance(path, str) or not path.strip() or Path(path).is_absolute() or ".." in Path(path).parts:
            errors.append(f"invalid:artifact_path:{key}")
        digest = node.get("artifact_sha256")
        if digest is not None and (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in digest)
        ):
            errors.append(f"invalid:artifact_sha256:{key}")
        if node_type == "source" and not _text(node.get("source_role")):
            errors.append(f"missing:source_role:{key}")
        if node_type == "claim" and not _text(node.get("claim_type")):
            errors.append(f"missing:claim_type:{key}")
        if node_type in {"claim", "material", "title", "opening", "paragraph", "review"} and not _text(node.get("locator")):
            errors.append(f"missing:locator:{key}")
        if node_type == "title" and _text(node.get("locator")) and not node["locator"].startswith("h1:"):
            errors.append(f"invalid:title_locator:{key}")
        if isinstance(key, str) and isinstance(node_type, str):
            known[key] = node

    signatures: set[tuple[object, ...]] = set()
    for index, edge in enumerate(edges):
        if not isinstance(edge, Mapping):
            errors.append(f"invalid:edge:{index}")
            continue
        for field in _REQUIRED_EDGE:
            value = edge.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"invalid:edge:{field}:{index}")
        left, right, kind = edge.get("from"), edge.get("to"), edge.get("edge_type")
        if not all(isinstance(value, str) and value for value in (left, right, kind)):
            continue
        if left not in known or right not in known:
            errors.append(f"unknown:edge_node:{index}")
            continue
        pair = (known[left].get("node_type"), kind, known[right].get("node_type"))
        if pair not in _ALLOWED:
            errors.append(f"illegal:edge:{kind}:{index}")
        if kind == "supported_by" and _is_discovery_source_role(known[right].get("source_role")):
            errors.append(f"forbidden:discovery_source_support:{right}")
        signature = tuple(edge.get(field) for field in _REQUIRED_EDGE)
        if signature in signatures:
            errors.append(f"duplicate:edge:{index}")
        signatures.add(signature)
    return list(dict.fromkeys(errors))


def validate_evidence_graph(graph: Mapping[str, Any], run_root: Path) -> list[str]:
    if not isinstance(graph, Mapping): return ["invalid:graph"]
    errors = validate_artifact_envelope(graph, _SCHEMA, run_id=_text(graph.get("run_id")) or "__missing__"); payload = _payload(graph); nodes = payload.get("nodes"); edges = payload.get("edges")
    if set(graph) != {"schema_version", "run_id", "generated_at", "input_hashes", "payload"}:
        errors.append("invalid:top_level")
    source_records = _validate_input_hashes(graph, Path(run_root), errors)
    if not isinstance(nodes, Mapping): return errors + ["invalid:nodes"]
    if not nodes: errors.append("invalid:empty_nodes")
    if not isinstance(edges, list): return errors + ["invalid:edges"]
    if not edges: errors.append("invalid:empty_edges")
    build_errors = payload.get("build_errors", [])
    if not isinstance(build_errors, list):
        errors.append("invalid:build_errors")
        build_errors = []
    errors.extend(f"build:{x}" for x in build_errors if isinstance(x, str))
    if "publication_authorization" in payload:
        errors.append("publication_authorization_must_not_be_present")
    known: dict[str, Mapping[str, Any]] = {}
    node_ids: set[str] = set()
    for key, node in nodes.items():
        if not isinstance(key, str) or not isinstance(node, Mapping): errors.append("invalid:node"); continue
        for field in _REQUIRED_NODE:
            if field not in node: errors.append(f"missing:node:{field}:{key}")
        if node.get("node_id") != key: errors.append(f"mismatch:node_id:{key}")
        if not isinstance(node.get("node_id"), str) or not node.get("node_id"): errors.append(f"invalid:node_id:{key}")
        elif node["node_id"] in node_ids: errors.append(f"duplicate:node:{node['node_id']}")
        else: node_ids.add(node["node_id"])
        if not isinstance(node.get("node_type"), str) or node.get("node_type") not in NODE_TYPES: errors.append(f"unknown:node_type:{key}")
        if not isinstance(node.get("status"), str) or node.get("status") not in _STATUSES: errors.append(f"invalid:status:{key}")
        if not isinstance(node.get("artifact_path"), str) or not node.get("artifact_path"): errors.append(f"invalid:artifact_path:{key}")
        digest = node.get("artifact_sha256")
        if digest is not None and (not isinstance(digest, str) or len(digest) != 64): errors.append(f"invalid:artifact_sha256:{key}")
        node_type = node.get("node_type")
        if node_type == "source" and not _text(node.get("source_role")): errors.append(f"missing:source_role:{key}")
        if node_type == "claim" and not _text(node.get("claim_type")): errors.append(f"missing:claim_type:{key}")
        if isinstance(node_type, str) and node_type in {"claim", "material", "title", "opening", "paragraph", "review"} and not _text(node.get("locator")):
            errors.append(f"missing:locator:{key}")
        if node_type == "title" and _text(node.get("locator")) and not node["locator"].startswith("h1:"):
            errors.append(f"invalid:title_locator:{key}")
        known[key] = node; path = safe_relative_path(Path(run_root), node.get("artifact_path"))
        if path is None: errors.append(f"invalid:path:{key}")
        elif not path.is_file() or digest is None: errors.append(f"missing:artifact:{key}")
        else:
            try:
                if digest != sha256_file(path): errors.append(f"mismatch:hash:{key}")
            except OSError: errors.append(f"missing:artifact:{key}")
        if node_type == "source" and key.startswith("source:"):
            source_id = key.split(":", 1)[1]
            record = source_records.get(source_id)
            if record is not None:
                expected_path = _text(record.get("relative_path") or record.get("path"))
                if node.get("artifact_path") != expected_path:
                    errors.append(f"mismatch:source_mapping:{source_id}")
                expected_role = _text(record.get("role") or record.get("source_role"))
                if expected_role and node.get("source_role") != expected_role:
                    errors.append(f"mismatch:source_role:{source_id}")
    adjacency: dict[str, set[str]] = {key: set() for key in known}; incoming: dict[str, set[str]] = {key: set() for key in known}; incoming_edges: dict[str, list[tuple[str, str]]] = {key: [] for key in known}; signatures: set[tuple[Any, ...]] = set()
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
        if (
            kind == "supported_by"
            and right_type == "source"
            and _is_discovery_source_role(known[right].get("source_role"))
        ):
            errors.append(f"forbidden:discovery_source_support:{right}")
        sig = tuple(edge.get(x) for x in _REQUIRED_EDGE)
        if all(isinstance(value, str) for value in sig):
            if sig in signatures: errors.append("duplicate:edge")
            signatures.add(sig)
        adjacency[left].add(right); incoming[right].add(left); incoming_edges[right].append((left, kind))
    for key, node in known.items():
        kind = node.get("node_type")
        if isinstance(kind, str) and kind in {"title", "opening", "review"} and not incoming[key]: errors.append(f"isolated:{kind}:{key}")
        if kind == "claim":
            if not any(known[parent].get("node_type") == "topic" for parent in incoming[key]): errors.append(f"isolated:claim:{key}")
            if not any(known[child].get("node_type") == "source" for child in adjacency[key]): errors.append(f"unsupported:claim:{key}")
        if kind == "material" and not any(known[parent].get("node_type") == "source" and edge_kind == "captured_as" for parent, edge_kind in incoming_edges[key]): errors.append(f"unbound:material:{key}")
    return list(dict.fromkeys(errors))


def trace_impact(graph: Mapping[str, Any], node_id: str) -> list[str]:
    payload = _payload(graph); nodes = payload.get("nodes", {}); edges = payload.get("edges", [])
    if not isinstance(node_id, str) or not isinstance(nodes, Mapping) or node_id not in nodes or not isinstance(edges, list): return []
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        if not isinstance(edge, Mapping) or edge.get("from") not in nodes or edge.get("to") not in nodes: continue
        if edge.get("edge_type") == "supported_by":
            adjacency.setdefault(edge["to"], []).append(edge["from"])
        else:
            adjacency.setdefault(edge["from"], []).append(edge["to"])
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
