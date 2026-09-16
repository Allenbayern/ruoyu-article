"""claim_source_check: mechanical provenance verification (2026-09-15).

Every fact a material pack attributes to a source must be anchorable in that
source's captured artifact: at least one contiguous 6-character window (or a
numeric token) of the normalized fact must appear in the normalized source
text.  This turns the hand-written fact→source mapping into a machine-checked
claim instead of a self-declared one.

Advisory by itself; ``run_gates`` treats an unanchored fact as a hard error
(the pack's provenance cannot be certified).
"""
from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

WINDOW_SIZE = 6
_TOKEN_SPLIT_RE = re.compile(r"[、，。：；·\s—\-《》()（）【】\[\]\"'“”‘’]+")

_TAG_RE = re.compile(r"<[^>]+>")
_NUMERIC_TOKEN_RE = re.compile(r"\d+(?:\.\d+)?[％%万亿年月日集部个次人]*")


def normalize_text(text: str) -> str:
    """Strip markup/whitespace/light punctuation to a comparable string."""
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"[\s\u3000]+", "", text)
    return text


def fact_anchors_in_source(fact: str, source_text: str) -> tuple[bool, list[str]]:
    """Return whether ``fact`` is anchorable in ``source_text`` and the windows.

    Anchoring rule (either is enough):
    - a contiguous 6-character window of the normalized fact appears in the
      normalized source, or a numeric token of the fact appears verbatim; or
    - entity-level coverage: at least half of the fact's punctuation-split
      tokens (>= 2 chars) appear in the source, with a minimum of two tokens.
    """
    fact_norm = normalize_text(fact)
    source_norm = normalize_text(source_text)
    if not fact_norm or not source_norm:
        return False, []
    if len(fact_norm) <= WINDOW_SIZE:
        # 短事实没有窗口可滑：必须整串逐字出现在来源里。
        return fact_norm in source_norm, [fact_norm] if fact_norm in source_norm else []
    matched: list[str] = []
    for i in range(0, max(1, len(fact_norm) - WINDOW_SIZE + 1)):
        window = fact_norm[i:i + WINDOW_SIZE]
        if len(window) == WINDOW_SIZE and window in source_norm:
            matched.append(window)
    if not matched:
        for token in _NUMERIC_TOKEN_RE.findall(fact_norm):
            if len(token) >= 2 and token in source_norm:
                matched.append(token)
    if not matched:
        tokens = [t for t in _TOKEN_SPLIT_RE.split(fact_norm) if len(t) >= 2]
        hit = [t for t in tokens if t in source_norm]
        if len(tokens) >= 2 and len(hit) >= max(1, len(tokens) // 2) and len(hit) >= 2:
            matched = [f"token:{t}" for t in hit]
    return bool(matched), matched


def _load_json_mapping(path: Path) -> Mapping[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, Mapping) else None


def _source_texts(run_root: Path, pack: Mapping[str, Any]) -> dict[str, str]:
    """Map source_id -> normalized captured artifact text for a pack."""
    texts: dict[str, str] = {}
    manifest = _load_json_mapping(run_root / "source-manifest.json")
    artifact_map: dict[str, str] = {}
    if manifest is not None:
        for source in manifest.get("sources", []):
            if isinstance(source, Mapping) and source.get("source_id"):
                artifact_map[str(source["source_id"])] = str(source.get("artifact_path") or "")
    for source in pack.get("sources", []):
        if not isinstance(source, Mapping):
            continue
        source_id = str(source.get("source_id") or "")
        if not source_id or source_id in texts:
            continue
        rel = artifact_map.get(source_id) or ""
        path = (run_root / rel) if rel else None
        text = ""
        if path is not None:
            try:
                text = normalize_text(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                text = ""
        texts[source_id] = text
    return texts


_TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


def source_titles(run_root: Path, source_ids: list[str]) -> dict[str, str]:
    """Normalized headline of each captured source (manifest title, else <title>)."""
    titles: dict[str, str] = {}
    manifest = _load_json_mapping(run_root / "source-manifest.json")
    declared: dict[str, str] = {}
    artifact_map: dict[str, str] = {}
    if manifest is not None:
        for source in manifest.get("sources", []):
            if not isinstance(source, Mapping) or not source.get("source_id"):
                continue
            key = str(source["source_id"])
            declared[key] = str(source.get("title") or "")
            artifact_map[key] = str(source.get("artifact_path") or "")
    for source_id in source_ids:
        raw_title = declared.get(source_id) or ""
        if not raw_title:
            rel = artifact_map.get(source_id) or ""
            if rel:
                try:
                    raw = (Path(run_root) / rel).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    raw = ""
                match = _TITLE_TAG_RE.search(raw)
                raw_title = match.group(1) if match else ""
        titles[source_id] = normalize_text(html.unescape(raw_title))
    return titles


def body_only_text(text: str, title: str) -> str:
    """Drop headline occurrences so a headline-only anchor becomes detectable.

    A claim that exists *only* in a source's headline is not body evidence:
    daily-008 shipped three "conclusions" taken verbatim from source titles
    ("姜文没变，观众和时代变了" 等) and no gate noticed.
    """
    if not title or not text:
        return text
    return text.replace(title, "")


def check_material_pack(run_root: str | Path, pack: Mapping[str, Any]) -> dict[str, Any]:
    """Verify every obtained fact and content_value_plan item of a pack.

    Two severities:
    - `errors`: a fact that cannot be anchored anywhere in its source artifact;
    - `warnings`: a fact anchored **only in the source headline** (title as
      evidence). Warnings never flip ``pass`` so historical runs stay green,
      but they surface in the gate report for the controller.
    """
    root = Path(run_root)
    texts = _source_texts(root, pack)
    titles = source_titles(root, sorted(texts))
    bodies = {source_id: body_only_text(text, titles.get(source_id, ""))
              for source_id, text in texts.items()}
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []

    by_source = pack.get("obtained_facts_by_source") or {}
    for source_id, facts in by_source.items():
        source_text = texts.get(str(source_id), "")
        body_text = bodies.get(str(source_id), "")
        for fact in facts if isinstance(facts, list) else []:
            if not isinstance(fact, str):
                continue
            anchored, windows = fact_anchors_in_source(fact, source_text)
            title_only = False
            if anchored and source_text != body_text:
                in_body, _ = fact_anchors_in_source(fact, body_text)
                title_only = not in_body
            results.append({
                "source_id": source_id,
                "fact": fact,
                "anchored": anchored,
                "title_only": title_only,
                "matched_windows": windows,
            })
            if not anchored:
                errors.append(f"fact_not_anchored:{source_id}:{fact[:32]}")
            elif title_only:
                warnings.append(f"title_only_anchor:{source_id}:{fact[:32]}")

    plan = pack.get("content_value_plan") or {}
    for item in (plan.get("hard_information_plan") or []) if isinstance(plan, Mapping) else []:
        if not isinstance(item, Mapping):
            continue
        gain = item.get("reader_gain")
        if not isinstance(gain, str):
            continue
        for ref in item.get("material_refs") or []:
            source_text = texts.get(str(ref), "")
            anchored, _ = fact_anchors_in_source(gain, source_text)
            if not anchored:
                errors.append(f"plan_not_anchored:{ref}:{item.get('plan_id', '?')}")
                continue
            in_body, _ = fact_anchors_in_source(gain, bodies.get(str(ref), ""))
            if not in_body:
                warnings.append(f"title_only_anchor:{ref}:{item.get('plan_id', '?')}")

    return {
        "schema_version": "claim-source-check-v1",
        "pass": not errors,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "results": results,
        "publication_authorization": "not_authorized",
    }


def check_content_fidelity(run_root: str | Path, fidelity: Mapping[str, Any]) -> dict[str, Any]:
    """Ledger-side title-as-evidence check for a delivery fidelity record.

    ``content-fidelity.json`` hard_information items carry ``source_refs`` and
    a ``text``; if that text anchors only in the referenced source's headline,
    it is a signal (heat-list title / editorial headline) masquerading as
    evidence.
    """
    root = Path(run_root)
    items = fidelity.get("hard_information")
    items = items if isinstance(items, list) else []
    refs = sorted({
        str(ref)
        for item in items if isinstance(item, Mapping)
        for ref in (item.get("source_refs") or [])
    })
    pack = {"sources": [{"source_id": ref} for ref in refs]}
    texts = _source_texts(root, pack)
    titles = source_titles(root, refs)
    bodies = {ref: body_only_text(texts.get(ref, ""), titles.get(ref, "")) for ref in refs}
    warnings: list[str] = []
    errors: list[str] = []
    results: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        item_id = str(item.get("information_id") or "?")
        anchored_anywhere = False
        title_only = False
        for ref in (item.get("source_refs") or []):
            ref = str(ref)
            in_full, _ = fact_anchors_in_source(text, texts.get(ref, ""))
            in_body, _ = fact_anchors_in_source(text, bodies.get(ref, ""))
            anchored_anywhere = anchored_anywhere or in_full
            if in_full and not in_body:
                title_only = True
        results.append({
            "information_id": item_id,
            "text": text,
            "anchored": anchored_anywhere,
            "title_only": title_only,
        })
        if not anchored_anywhere:
            errors.append(f"fidelity_not_anchored:{item_id}:{text[:32]}")
        elif title_only:
            warnings.append(f"title_only_anchor:{item_id}:{text[:32]}")
    return {
        "schema_version": "claim-source-check-v1",
        "scope": "content_fidelity",
        "pass": not errors,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "results": results,
        "publication_authorization": "not_authorized",
    }


def check_run_material_packs(run_root: str | Path) -> dict[str, Any]:
    """Verify every material pack under a run root; returns an aggregate report."""
    root = Path(run_root)
    pack_reports: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    packs_dir = root / "material-packs"
    paths = sorted(packs_dir.glob("*.json")) if packs_dir.is_dir() else []
    if not paths:
        errors.append("missing:material_packs")
    for path in paths:
        pack = _load_json_mapping(path)
        if pack is None:
            errors.append(f"invalid_material_pack:{path.name}")
            continue
        report = check_material_pack(root, pack)
        pack_reports.append({"pack": path.name, **report})
        errors.extend(f"{path.name}:{item}" for item in report["errors"])
        warnings.extend(f"{path.name}:{item}" for item in report.get("warnings", []))
    return {
        "schema_version": "claim-source-check-v1",
        "run_id": f"{root.parent.name}/{root.name}" if root.parent.name[:4].isdigit() else root.name,
        "pass": not errors,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "packs": pack_reports,
        "publication_authorization": "not_authorized",
    }


__all__ = [
    "WINDOW_SIZE",
    "normalize_text",
    "fact_anchors_in_source",
    "body_only_text",
    "source_titles",
    "check_material_pack",
    "check_run_material_packs",
    "check_content_fidelity",
]
