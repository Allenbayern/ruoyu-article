"""Article Rule Compliance v1 checks.

This is a fail-closed, side-effect-free validator for article mode, material
roles, claim permissions, and source-stripped readability evidence.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from article_group.source_capability import validate_claim_capabilities

ARTICLE_MODES = frozenset({
    "setting_observation", "viewing_commentary", "reported_feature", "fact_explainer"
})
MODE_REQUIRED_ROLES = {
    "setting_observation": (frozenset({"official_fact", "mechanism"}),),
    "viewing_commentary": (frozenset({"scene", "review"}),),
    # reported_feature 的合法证据角色（2026-09-16 扩展）：专访/现场之外，
    # 报道式特稿以媒体/新闻稿件为主证据同样是诚实角色（capability 层
    # 早已收录 media_report）。
    "reported_feature": (frozenset({"interview", "现场", "media_report"}),),
    "fact_explainer": (frozenset({"official_fact"}), frozenset({"cross_check"})),
}
MODE_ALLOWED_LEVELS = {
    "setting_observation": frozenset({"event_exists", "character_setup", "mechanism"}),
    "viewing_commentary": frozenset({"event_exists", "character_setup", "scene_action", "dialogue", "mechanism", "outcome"}),
    "reported_feature": frozenset({"event_exists", "character_setup", "scene_action", "dialogue", "mechanism", "outcome"}),
    "fact_explainer": frozenset({"event_exists", "character_setup", "mechanism"}),
}
META_TERMS = ("官方页面", "官方简介", "来源", "材料", "目前能确认", "当前资料", "证据边界")


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _sources(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = record.get("sources")
    return [item for item in raw if isinstance(item, Mapping)] if isinstance(raw, list) else []


def _claims(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = record.get("claims")
    return [item for item in raw if isinstance(item, Mapping)] if isinstance(raw, list) else []


def _mode(record: Mapping[str, Any]) -> str:
    return _text(record.get("article_mode"))


def _role_coverage(mode: str, roles: set[str]) -> bool:
    requirements = MODE_REQUIRED_ROLES.get(mode, ())
    return bool(requirements) and all(bool(options & roles) for options in requirements)


def validate_rule_compliance(record: Mapping[str, Any] | object, *, source_stripped_text: str | None = None, check_readability: bool = True) -> list[str]:
    if not isinstance(record, Mapping):
        return ["record_must_be_an_object"]
    errors: list[str] = []
    mode = _mode(record)
    if mode not in ARTICLE_MODES:
        errors.append("invalid:article_mode")
    required_roles = record.get("required_source_roles")
    if not isinstance(required_roles, list) or not required_roles or not all(_text(x) for x in required_roles):
        errors.append("missing:required_source_roles")
    sources = _sources(record)
    roles: set[str] = set()
    source_ids: set[str] = set()
    for index, source in enumerate(sources):
        sid = _text(source.get("source_id"))
        if not sid or sid in source_ids:
            errors.append(f"invalid:source_id:{index}")
        source_ids.add(sid)
        role = _text(source.get("source_role"))
        roles.add(role)
        if not role:
            errors.append(f"missing:source_role:{index}")
        if not isinstance(source.get("supports_mode"), list) or mode not in source.get("supports_mode", []):
            errors.append(f"source_mode_unsupported:{sid or index}")
        if not isinstance(source.get("cannot_support"), list) or not source.get("cannot_support"):
            errors.append(f"missing:cannot_support:{sid or index}")
        if not _text(source.get("source_capability")):
            errors.append(f"missing:source_capability:{sid or index}")
    if mode in ARTICLE_MODES and not _role_coverage(mode, roles):
        errors.append("material_roles_do_not_cover_mode")
    allowed = MODE_ALLOWED_LEVELS.get(mode, frozenset())
    for index, claim in enumerate(_claims(record)):
        cid = _text(claim.get("claim_id")) or str(index)
        level = _text(claim.get("claim_level"))
        refs = claim.get("source_refs") or claim.get("source_ids")
        locators = claim.get("source_locators")
        if level not in allowed:
            errors.append(f"claim_level_forbidden:{cid}")
        if not isinstance(refs, list) or not refs or not set(refs).issubset(source_ids):
            errors.append(f"claim_source_invalid:{cid}")
        if not isinstance(locators, list) or not locators or not all(_text(x) for x in locators):
            errors.append(f"claim_locator_missing:{cid}")
    errors.extend(validate_claim_capabilities(sources, _claims(record), strict=True))
    if not check_readability:
        return sorted(set(errors))
    if source_stripped_text is None:
        errors.append("source_stripped_readability_missing")
    else:
        lowered = source_stripped_text.replace(" ", "")
        if any(term in lowered for term in META_TERMS):
            errors.append("source_stripped_contains_meta_language")
        if len(lowered) < 40:
            errors.append("source_stripped_too_short")
    return sorted(set(errors))


def build_source_stripped(text: str) -> str:
    """Create a review copy without source-process language; never mutates input."""
    result = text
    for term in META_TERMS:
        result = result.replace(term, "")
    return result


def build_readability_record(article_id: str, mode: str, artifact: bytes, stripped: bytes, *, reviewer: str = "") -> dict[str, Any]:
    return {
        "schema_version": "article-rule-compliance-v1",
        "article_id": article_id,
        "article_mode": mode,
        "mode_check": "PASS",
        "material_layer_check": "PASS",
        "official_boundary_check": "PASS",
        "source_stripped_readability": "PENDING",
        "reviewer_id": reviewer,
        "reviewer_role": "human_editor",
        "reviewed_artifact_sha256": hashlib.sha256(artifact).hexdigest(),
        "reviewed_source_stripped_sha256": hashlib.sha256(stripped).hexdigest(),
        "publication_authorization": "not_authorized",
    }


def _load_json(path: Path) -> Mapping[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _safe_path(root: Path, raw: object) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts or "\x00" in raw:
        return None
    target = (root / candidate).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


def _declared_mode_from_markdown(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""
    match = re.search(r"^article_mode\s*:\s*([^\s]+)", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _human_readability_status(record: Mapping[str, Any] | None, artifact: bytes, stripped: bytes) -> tuple[str, list[str]]:
    if record is None:
        return "UNVERIFIED", ["source_stripped_human_record_missing"]
    errors: list[str] = []
    if record.get("schema_version") != "article-rule-compliance-v1":
        errors.append("source_stripped_human_schema_invalid")
    if record.get("mode_check") != "PASS":
        errors.append("source_stripped_mode_check_not_pass")
    if record.get("material_layer_check") != "PASS":
        errors.append("source_stripped_material_layer_check_not_pass")
    if record.get("official_boundary_check") != "PASS":
        errors.append("source_stripped_boundary_check_not_pass")
    if record.get("publication_authorization") != "not_authorized":
        errors.append("source_stripped_publication_authorization_invalid")
    if record.get("reviewed_artifact_sha256") != hashlib.sha256(artifact).hexdigest():
        errors.append("source_stripped_artifact_hash_mismatch")
    if record.get("reviewed_source_stripped_sha256") != hashlib.sha256(stripped).hexdigest():
        errors.append("source_stripped_hash_mismatch")
    if errors:
        return "FAIL", sorted(set(errors))
    if record.get("source_stripped_readability") != "PASS":
        return "PENDING", ["source_stripped_readability_pending"]
    if not _text(record.get("reviewer_id")) or record.get("reviewer_role") != "human_editor":
        return "UNVERIFIED", ["source_stripped_human_reviewer_missing"]
    return "PASS", []


def evaluate_article_rule_evidence(root: str | Path, batch: Mapping[str, Any], article: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one article's persisted rule-compliance evidence chain."""
    root_path = Path(root)
    aid = _text(article.get("article_id")) or "?"
    errors: list[str] = []
    mode = _mode(article)
    if mode not in ARTICLE_MODES:
        errors.append("invalid:article_mode")
    batch_mode = _text(batch.get("article_mode"))
    if batch_mode and batch_mode != mode:
        errors.append("batch_article_mode_mismatch")
    required_roles = article.get("required_source_roles")
    if not isinstance(required_roles, list) or not required_roles:
        errors.append("missing:required_source_roles")
    batch_roles = batch.get("required_source_roles")
    if isinstance(batch_roles, list) and batch_roles != required_roles:
        errors.append("batch_required_source_roles_mismatch")

    for field in ("brief_path", "task_card_path"):
        path = _safe_path(root_path, article.get(field))
        if path is None or not path.is_file():
            errors.append(f"{field}_missing")
        elif _declared_mode_from_markdown(path) != mode:
            errors.append(f"{field}_article_mode_mismatch")

    material_path = _safe_path(root_path, article.get("material_pack_path"))
    material = _load_json(material_path) if material_path and material_path.is_file() else None
    if material is None:
        errors.append("material_pack_missing")
    else:
        if _text(material.get("article_mode")) != mode:
            errors.append("material_pack_article_mode_mismatch")
        if material.get("required_source_roles") != required_roles:
            errors.append("material_pack_required_source_roles_mismatch")

    manifest_path = _safe_path(root_path, batch.get("source_manifest_path"))
    source_manifest = _load_json(manifest_path) if manifest_path and manifest_path.is_file() else None
    if source_manifest is None:
        errors.append("source_manifest_missing")
    manifest_sources = {
        _text(item.get("source_id")): item
        for item in (source_manifest.get("sources", []) if source_manifest else [])
        if isinstance(item, Mapping) and _text(item.get("source_id"))
    }

    compliance_path = _safe_path(root_path, article.get("rule_compliance_path"))
    compliance = _load_json(compliance_path) if compliance_path and compliance_path.is_file() else None
    if compliance is None:
        return {"status": "UNVERIFIED", "errors": sorted(set(errors + ["rule_compliance_record_missing"])), "article_id": aid}
    if compliance.get("article_id") != aid:
        errors.append("rule_compliance_article_id_mismatch")
    if compliance.get("article_mode") != mode:
        errors.append("rule_compliance_article_mode_mismatch")
    if compliance.get("required_source_roles") != required_roles:
        errors.append("rule_compliance_required_source_roles_mismatch")
    source_errors = validate_rule_compliance(compliance, check_readability=False)
    errors.extend(source_errors)
    for source in _sources(compliance):
        sid = _text(source.get("source_id"))
        declared = manifest_sources.get(sid)
        if declared is None:
            errors.append(f"source_manifest_reference_missing:{sid or '?'}")
            continue
        for field in ("source_role", "supports_mode", "cannot_support", "source_capability"):
            if source.get(field) != declared.get(field):
                errors.append(f"source_manifest_{field}_mismatch:{sid}")

    delivery_path = _safe_path(root_path, article.get("delivery_path") or article.get("markdown_path"))
    stripped_path = _safe_path(root_path, article.get("source_stripped_path"))
    human_path = _safe_path(root_path, article.get("source_stripped_readability_path"))
    if delivery_path is None or not delivery_path.is_file():
        errors.append("delivery_artifact_missing")
        artifact = b""
    else:
        artifact = delivery_path.read_bytes()
    if stripped_path is None or not stripped_path.is_file():
        errors.append("source_stripped_artifact_missing")
        stripped = b""
    else:
        stripped = stripped_path.read_bytes()
        stripped_errors = validate_rule_compliance(compliance, source_stripped_text=stripped.decode("utf-8"))
        errors.extend(stripped_errors)
    human = _load_json(human_path) if human_path and human_path.is_file() else None
    human_status, human_errors = _human_readability_status(human, artifact, stripped)
    if errors:
        return {"status": "FAIL", "errors": sorted(set(errors)), "article_id": aid, "human_status": human_status}
    if human_status == "FAIL":
        return {"status": "FAIL", "errors": human_errors, "article_id": aid, "human_status": human_status}
    if human_status != "PASS":
        return {"status": human_status, "errors": human_errors, "article_id": aid, "human_status": human_status}
    return {"status": "PASS", "errors": [], "article_id": aid, "human_status": human_status}


def evaluate_batch_rule_compliance(root: str | Path, batch: Mapping[str, Any]) -> dict[str, Any]:
    articles = batch.get("articles") if isinstance(batch, Mapping) else None
    if not isinstance(articles, list) or not articles:
        return {"status": "UNVERIFIED", "errors": ["articles_missing"], "articles": []}
    results = [evaluate_article_rule_evidence(root, batch, article) for article in articles if isinstance(article, Mapping)]
    statuses = {str(item.get("status")) for item in results}
    status = "FAIL" if "FAIL" in statuses else "UNVERIFIED" if "UNVERIFIED" in statuses else "PENDING" if "PENDING" in statuses else "PASS"
    return {"status": status, "errors": [error for item in results for error in item.get("errors", [])], "articles": results}


__all__ = ["ARTICLE_MODES", "MODE_ALLOWED_LEVELS", "build_readability_record", "build_source_stripped", "evaluate_article_rule_evidence", "evaluate_batch_rule_compliance", "validate_rule_compliance"]
