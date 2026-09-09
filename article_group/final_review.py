"""final_review — prepublication 总复核层（v1）。

汇总单批所有闸门产物为单一判定：PUBLISHABLE / BLOCKED / PENDING（需人工）。

判定顺序（fail-closed）：
1. 证据齐全性：batch.json / preflight-report.json / 当前审阅面 artifact /
   style-gate / prose-pilot / 每篇评分卡必须存在；editorial-record 若存在必须通过校验。
2. 机械闸门：preflight status == PASS；style-gate error_count == 0。
3. 发布不变量：publication_authorization == "not_authorized" 且无 authorization_* 字段。
4. 跨批指纹：collect_history(exclude_run=本批) + check_cross_batch，error 级命中阻断。
5. 存疑判定：style-gate warning 或 prose-pilot 与 style_gate 字数口径差 > 15% → PENDING。
6. 全过 → PUBLISHABLE（质量判定，发布永远人工）。

用法：
    python -m article_group.final_review --batch runs/2026-08-15/controlled-020
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

from article_group.editorial_review import evaluate_editorial_record
from article_group.human_attestation import validate_human_attestation
from article_group.portfolio_gate import check_cross_batch, collect_history
from article_group.preview_contract import (
    resolve_preview_mode,
    validate_batch_preview_mode,
    validate_preview_evidence,
)
from article_group.provenance import validate_current_source_provenance
from article_group.revalidation import validate_revalidation_record
from article_group.review_surface import (
    resolve_review_surface,
    validate_batch_review_surface,
    validate_markdown_review_evidence,
)
from article_group.run_profile import MAX_CJK_CHARS, MIN_CJK_CHARS, validate_batch_profile

PUBLISHABLE = "PUBLISHABLE"
BLOCKED = "BLOCKED"
PENDING = "PENDING"

CHAR_DIFF_TOLERANCE = 0.15  # style_gate 与 prose_pilot 字数口径差容限
_SCORING_LIMITS = {
    "total_score": (0, 100),
    "evidence_score": (0, 25),
    "original_judgment_score": (0, 20),
    "information_gain_score": (0, 20),
    "structure_score": (0, 15),
    "title_value_score": (0, 10),
    "readability_score": (0, 5),
    "compliance_score": (0, 5),
}
_SCORING_FLOORS = {
    "total_score": 75,
    "evidence_score": 15,
    "original_judgment_score": 15,
}
_ENTRY_REVIEW_FIELDS = (
    "title_promise",
    "first_screen_value",
    "reader_takeaway",
    "body_fulfillment",
)
_HASH_FIELDS = ("html_sha256", "artifact_sha256")
_PATH_FIELDS = ("html_path", "artifact_path")
_MARKDOWN_HASH_FIELDS = ("markdown_sha256", "artifact_sha256")
_MARKDOWN_PATH_FIELDS = ("markdown_path", "artifact_path")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")

# style_gate 的结构化检查是 warning-level，除了 hook_declaration 的
# producer-specific failure statuses（missing/mismatch）。closing_interaction
# 的 info 状态是建议，不进入人工判定队列。
_STRUCTURED_WARNING_STATUSES = {
    "opening_hook": {"warning"},
    "title_gap": {"warning"},
    "fact_density": {"warning"},
    "hook_declaration": {"missing", "mismatch", "warning"},
    "closing_interaction": {"warning"},
}


def _load_json(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _evidence_gap(reason: str) -> dict:
    return {"type": "evidence_gap", "reason": reason}


def _blocked(reason: str, **extra: object) -> dict:
    return {"verdict": BLOCKED, "reason": reason, **extra}


def _pending(reason: str, items: list[str]) -> dict:
    return {"verdict": PENDING, "reason": reason, "human_judgment_items": items}


def _publishable() -> dict:
    return {"verdict": PUBLISHABLE, "reason": "全部闸门和评分卡通过；发布仍需真人授权"}


def _requires_independent_review(batch: dict) -> bool:
    """M2/R7.5 batches must not look publishable before human review is complete.

    Older fixture batches and pre-M2 historical runs may not carry the state
    fields.  Once a batch declares the M2 checkpoint/state contract, the
    quality result is fail-closed until independent review and human
    attestation are explicitly complete.
    """
    milestone = str(batch.get("milestone", ""))
    return bool(
        "M2" in milestone
        or batch.get("manifest_state")
        or batch.get("target_state")
    )


def _review_completion_items(
    batch: dict,
    articles: list[dict],
    editorial_records: list[tuple[Path, dict]],
    root: Path,
    delivery_htmls: list[Path],
    *,
    review_surface: str = "html_delivery",
    markdown_by_article: dict[str, Path] | None = None,
) -> list[str]:
    """Return human-state blockers that mechanical gates cannot waive."""
    if not _requires_independent_review(batch):
        return []

    items: list[str] = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        aid = str(article.get("article_id", "?"))
        gate = article.get("gate_status")
        gate = gate if isinstance(gate, dict) else {}
        independent = str(gate.get("independent_review", "")).lower()
        if independent not in {"approve", "approved", "pass", "complete"}:
            items.append(f"{aid}: independent_review={independent or 'missing'}")

        controller = str(gate.get("controller_acceptance", "")).lower()
        if controller not in {"accepted", "approved", "pass", "complete"}:
            items.append(f"{aid}: controller_acceptance={controller or 'missing'}")

        delivery = str(article.get("delivery_state", "")).lower()
        html_state = str(article.get("html_delivery_state", "")).lower()
        if delivery in {"pending_independent_review", "pending_controller_acceptance", "pending"}:
            items.append(f"{aid}: delivery_state={delivery}")
        if review_surface != "markdown_codex" and html_state in {
            "withheld", "pending", "withheld_pending_review"
        }:
            items.append(f"{aid}: html_delivery_state={html_state}")

        attestation_path = root / "review" / "attestation" / f"{aid}.human.json"
        attestation = _load_json(attestation_path) if attestation_path.is_file() else None
        markdown_paths = []
        if markdown_by_article and aid in markdown_by_article:
            markdown_paths = [markdown_by_article[aid]]
        attestation_errors = validate_human_attestation(
            attestation,
            root,
            aid,
            delivery_htmls,
            review_surface=review_surface,
            markdown_paths=markdown_paths,
        )
        if attestation_errors:
            # Keep the legacy summary label for dashboards, but the independent
            # attestation file—not a scoring-card boolean—is authoritative.
            items.append(f"{aid}: human_editor_attestation=pending_or_missing")
            for error in attestation_errors:
                items.append(f"{aid}: {error}")

        fact_card_path = root / "review" / aid / "fact-card.json"
        if fact_card_path.is_file():
            fact_card = _load_json(fact_card_path)
            if fact_card is None:
                items.append(f"{aid}: fact_card_unreadable")
            elif fact_card.get("update_required_before_publication") == "yes":
                revalidation_path = root / "review" / aid / "revalidation.json"
                revalidation = (
                    _load_json(revalidation_path)
                    if revalidation_path.is_file()
                    else None
                )
                revalidation_errors = validate_revalidation_record(
                    fact_card, revalidation, root
                )
                for error in revalidation_errors:
                    items.append(f"{aid}: {error}")

    if not editorial_records:
        items.append("editorial-review-record: missing for M2 batch")
    for path, record in editorial_records:
        for stage in record.get("stages", []) or []:
            if not isinstance(stage, dict):
                continue
            mode = str(stage.get("review_mode", "")).lower()
            completed_by = str(stage.get("completed_by", "")).lower()
            if mode.startswith("human") and any(
                token in completed_by for token in ("controller", "codex", "luna", "agent")
            ):
                items.append(
                    f"{path.name}:{stage.get('stage_id', 'unknown')}:"
                    "human_review_completed_by_nonhuman_provenance"
                )
    return items


def _delivery_htmls(root: Path) -> list[Path]:
    """Select the final frozen HTML before any working-copy fallback."""
    frozen = sorted((root / "review" / "frozen").glob("*.html"))
    if frozen:
        return frozen
    return sorted(root.glob("ruoyu-articles-*.html")) or sorted(
        (root / "review").glob("ruoyu-art-*.html")
    )


def _resolve_inside(root: Path, path: Path) -> Path | None:
    """解析路径并拒绝越出批次目录的文件。"""
    try:
        root_resolved = root.resolve()
        resolved = path.resolve()
        resolved.relative_to(root_resolved)
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _article_delivery_htmls(
    article_id: str, delivery_htmls: list[Path]
) -> list[Path]:
    """Select delivery HTMLs whose identity matches one article."""
    token = re.compile(
        rf"(?<![A-Za-z0-9_]){re.escape(article_id)}(?![A-Za-z0-9_])"
    )
    return [path for path in delivery_htmls if token.search(path.name)]


def _validate_scoring_card(
    card: dict,
    root: Path,
    delivery_htmls: list[Path],
    article_id: str,
    *,
    review_surface: str = "html_delivery",
    markdown_artifact: Path | None = None,
) -> list[str]:
    """校验评分卡质量证据及其对当前审阅面的绑定。"""
    errors: list[str] = []

    for field, (lower, upper) in _SCORING_LIMITS.items():
        value = card.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"score_non_numeric:{field}" if field in card else f"score_missing:{field}")
            continue
        if not math.isfinite(value) or not lower <= value <= upper:
            errors.append(f"score_out_of_range:{field}")
            continue
        if field in _SCORING_FLOORS and value < _SCORING_FLOORS[field]:
            errors.append(f"score_below_floor:{field}")

    component_fields = tuple(field for field in _SCORING_LIMITS if field != "total_score")
    component_values = [card.get(field) for field in component_fields]
    numeric_components: list[float] = []
    components_valid = True
    for value in component_values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            components_valid = False
            break
        if not math.isfinite(value):
            components_valid = False
            break
        numeric_components.append(float(value))
    total_value = card.get("total_score")
    if (
        components_valid
        and isinstance(total_value, (int, float))
        and not isinstance(total_value, bool)
        and math.isfinite(total_value)
        and not math.isclose(
            float(total_value), sum(numeric_components), rel_tol=0, abs_tol=1e-9
        )
    ):
        errors.append("score_sum_mismatch")

    review_objects = [
        card,
        card.get("editorial_review"),
        card.get("editorial_review_fields"),
    ]
    for field in _ENTRY_REVIEW_FIELDS:
        if not any(
            isinstance(container, dict)
            and isinstance(container.get(field), str)
            and bool(container[field].strip())
            for container in review_objects
        ):
            errors.append(f"entry_field_missing:{field}")

    if review_surface == "markdown_codex":
        return errors + _validate_scoring_artifact_binding(
            card,
            root,
            article_id,
            review_surface=review_surface,
            delivery_artifacts=([markdown_artifact] if markdown_artifact else []),
        )

    return errors + _validate_scoring_artifact_binding(
        card,
        root,
        article_id,
        review_surface=review_surface,
        delivery_artifacts=delivery_htmls,
    )


def _validate_scoring_artifact_binding(
    card: dict,
    root: Path,
    article_id: str,
    *,
    review_surface: str,
    delivery_artifacts: list[Path],
) -> list[str]:
    """Bind one scoring card to exactly one current surface artifact."""
    if review_surface == "markdown_codex":
        hash_fields = [field for field in _MARKDOWN_HASH_FIELDS if field in card]
        path_fields = [field for field in _MARKDOWN_PATH_FIELDS if field in card]
        identity_missing = "markdown_identity_missing"
        invalid_artifact = "markdown_artifact_invalid"
        not_artifact = "path_not_review_markdown"
        unreadable = "markdown_unreadable"
        hash_mismatch = "markdown_hash_mismatch"
    else:
        hash_fields = [field for field in _HASH_FIELDS if field in card]
        path_fields = [field for field in _PATH_FIELDS if field in card]
        identity_missing = "delivery_html_identity_missing"
        invalid_artifact = "delivery_html_invalid"
        not_artifact = "path_not_delivery_html"
        unreadable = "delivery_html_unreadable"
        hash_mismatch = "hash_mismatch"

    errors: list[str] = []
    if len(hash_fields) != 1:
        errors.append("hash_field_ambiguous" if hash_fields else "hash_missing")
        expected_hash = None
    else:
        expected_hash = card[hash_fields[0]]
        if not isinstance(expected_hash, str) or not _SHA256_RE.fullmatch(expected_hash):
            errors.append("hash_invalid")
            expected_hash = None

    if review_surface == "markdown_codex":
        article_artifacts = delivery_artifacts
    else:
        article_artifacts = _article_delivery_htmls(article_id, delivery_artifacts)
    delivery_targets = [_resolve_inside(root, path) for path in article_artifacts]
    if not article_artifacts:
        errors.append(identity_missing)
    elif any(target is None or not target.is_file() for target in delivery_targets):
        errors.append(invalid_artifact)

    target: Path | None = None
    if len(path_fields) > 1:
        errors.append("path_field_ambiguous")
    elif path_fields:
        raw_path = card[path_fields[0]]
        if not isinstance(raw_path, str) or not raw_path.strip():
            errors.append("path_invalid")
        else:
            relative_path = Path(raw_path)
            if relative_path.is_absolute() or ".." in relative_path.parts or "\x00" in raw_path:
                errors.append("path_invalid")
            else:
                target = _resolve_inside(root, root / relative_path)
                if target is None or not target.is_file():
                    errors.append("path_missing")
                elif target not in delivery_targets:
                    errors.append(not_artifact)
    elif len(article_artifacts) == 1:
        target = delivery_targets[0]
    else:
        errors.append(
            "path_required_for_article_markdown"
            if review_surface == "markdown_codex"
            else "path_required_for_article_delivery_html"
        )

    if target is not None and expected_hash is not None:
        actual_hash = _sha256(target)
        if actual_hash is None:
            errors.append(unreadable)
        elif actual_hash != expected_hash.lower():
            errors.append(hash_mismatch)

    return errors


def _validate_style_artifact(
    report: dict,
    root: Path,
    delivery_htmls: list[Path],
    *,
    review_surface: str = "html_delivery",
) -> tuple[Path | None, list[str]]:
    """Validate a style report's byte/path binding to the current surface."""
    errors: list[str] = []
    if review_surface == "markdown_codex" and report.get("artifact_type") != "markdown":
        errors.append("artifact_binding_type_invalid:markdown")
    artifact_path = report.get("artifact_path")
    artifact_hash = report.get("artifact_sha256")

    if not isinstance(artifact_path, str) or not artifact_path.strip():
        errors.append("artifact_binding_missing:path")
        target = None
    else:
        declared = Path(artifact_path)
        target = _resolve_inside(
            root,
            declared if declared.is_absolute() else root / declared,
        )
        if target is None or not target.is_file():
            errors.append("artifact_binding_invalid:path")

    if not isinstance(artifact_hash, str) or not _SHA256_RE.fullmatch(artifact_hash):
        errors.append("artifact_binding_missing_or_invalid:sha256")

    delivery_targets = {
        resolved
        for path in delivery_htmls
        if (resolved := _resolve_inside(root, path)) is not None
    }
    if target is not None and target not in delivery_targets:
        errors.append("artifact_binding_not_final_delivery")

    if target is not None and target in delivery_targets and isinstance(artifact_hash, str):
        actual_hash = _sha256(target)
        if actual_hash is None:
            errors.append("artifact_binding_unreadable")
        elif actual_hash != artifact_hash.lower():
            errors.append("artifact_binding_hash_mismatch")

    return target, errors


def _validate_editorial_review_surface(
    record: dict,
    root: Path,
    review_surface: str,
    markdown_by_article: dict[str, Path],
) -> list[str]:
    """Keep editorial-record evidence on the same surface as final_review."""
    if review_surface != "markdown_codex":
        return []
    errors: list[str] = []
    if record.get("review_surface") != "markdown_codex":
        errors.append("editorial_review_surface_missing_or_invalid")

    article_id = str(record.get("article_id", ""))
    expected = markdown_by_article.get(article_id)
    if expected is None:
        errors.append(f"editorial_markdown_target_missing:{article_id}")

    final_ref = record.get("final_review_ref")
    if not isinstance(final_ref, dict):
        errors.append("editorial_final_review_ref_missing")
    else:
        raw_path = final_ref.get("path")
        target = _resolve_inside(root, root / str(raw_path)) if isinstance(raw_path, str) else None
        if target is None or expected is None or target != expected.resolve():
            errors.append("editorial_final_review_ref_not_current_markdown")
        declared_hash = final_ref.get("sha256")
        if not isinstance(declared_hash, str) or not _SHA256_RE.fullmatch(declared_hash):
            errors.append("editorial_final_review_hash_invalid")
        elif target is not None and target.is_file() and _sha256(target) != declared_hash.lower():
            errors.append("editorial_final_review_hash_mismatch")

    markdown_seen = False

    def walk(value: object) -> None:
        nonlocal markdown_seen
        if isinstance(value, dict):
            raw_path = value.get("path")
            if isinstance(raw_path, str):
                normalized = raw_path.replace("\\", "/")
                if (
                    normalized.endswith(".html")
                    or "/frozen/" in normalized
                    or normalized.startswith("review/preview-")
                    or normalized.endswith("/freeze-manifest.json")
                    or "/style-gate-art-" in normalized
                ):
                    errors.append(f"editorial_html_reference_forbidden:{raw_path}")
                if expected is not None:
                    target = _resolve_inside(root, root / raw_path)
                    digest = value.get("sha256")
                    if (
                        target == expected.resolve()
                        and isinstance(digest, str)
                        and _SHA256_RE.fullmatch(digest)
                        and _sha256(expected) == digest.lower()
                    ):
                        markdown_seen = True
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(record)
    if expected is not None and not markdown_seen:
        errors.append("editorial_markdown_evidence_reference_missing")
    return list(dict.fromkeys(errors))


def evaluate_batch(batch_dir: str | Path) -> dict:
    """对单个批次目录执行总复核，返回判定报告。"""
    root = Path(batch_dir)
    if not root.is_dir():
        return _blocked("batch_dir_missing", batch_dir=str(root))

    gaps: list[dict] = []
    human_items: list[str] = []

    # ---- 1. 证据齐全性 -------------------------------------------------
    batch_json = root / "batch.json"
    preflight = root / "preflight-report.json"
    if not batch_json.exists():
        return _blocked("evidence_missing:batch.json")
    batch = _load_json(batch_json)
    if batch is None:
        return _blocked("evidence_unreadable:batch.json")

    articles = batch.get("articles") or []
    if not isinstance(articles, list) or not articles:
        return _blocked("evidence_invalid:batch.json:no_articles")

    modern_contract = (
        batch.get("run_profile_contract_version") == "run-profile-v1"
        or batch.get("run_profile_required") is True
    )
    surface_errors = validate_batch_review_surface(
        batch,
        require_explicit=modern_contract and "preview_mode" not in batch,
    )
    if surface_errors:
        return _blocked("gate:review_surface", errors=surface_errors)

    if "review_surface" in batch:
        review_surface = resolve_review_surface(batch.get("review_surface"))
    elif "preview_mode" in batch:
        review_surface = "html_delivery"
    else:
        # A batch without either new or legacy metadata is a historical HTML
        # fixture.  New run profiles must declare a surface above.
        review_surface = "html_delivery"

    preview_mode: str | None = None
    if review_surface == "html_delivery" and "preview_mode" in batch:
        preview_mode_errors = validate_batch_preview_mode(batch, require_explicit=False)
        if preview_mode_errors:
            return _blocked(
                "gate:preview_contract",
                errors=preview_mode_errors,
            )
        preview_mode = resolve_preview_mode(batch.get("preview_mode"))

    profile_errors = validate_batch_profile(
        batch,
        require_explicit=(
            batch.get("run_profile_contract_version") == "run-profile-v1"
            or batch.get("run_profile_required") is True
        ),
    )
    if profile_errors:
        return _blocked("gate:run_profile", errors=profile_errors)

    run_id = str(batch.get("run_id", ""))
    if not run_id:
        return _blocked("evidence_invalid:batch.json:no_run_id")

    if batch.get("provenance_contract_version") == "source-provenance-v1":
        provenance_errors = validate_current_source_provenance(batch, root)
        if provenance_errors:
            return _blocked(
                "gate:source_provenance",
                errors=provenance_errors,
            )

    if not preflight.exists():
        return _blocked("evidence_missing:preflight-report.json")
    preflight_data = _load_json(preflight)
    if preflight_data is None:
        return _blocked("evidence_unreadable:preflight-report.json")
    if str(preflight_data.get("status", "")).upper() != "PASS":
        return _blocked("gate:preflight", status=str(preflight_data.get("status")))

    delivery_htmls: list[Path] = []
    markdown_by_article: dict[str, Path] = {}
    review_artifacts: list[Path]
    if review_surface == "markdown_codex":
        evidence_path = root / "review" / "markdown-review-evidence.json"
        if not evidence_path.is_file():
            return _blocked("evidence_missing:markdown-review-evidence")
        evidence = _load_json(evidence_path)
        if evidence is None:
            return _blocked("evidence_unreadable:markdown-review-evidence")
        markdown_errors = validate_markdown_review_evidence(evidence, root, articles)
        if markdown_errors:
            return _blocked(
                "gate:markdown_review_evidence",
                errors=markdown_errors,
            )
        for article in articles:
            if not isinstance(article, dict):
                return _blocked("evidence_invalid:batch.json:article")
            aid = str(article.get("article_id", ""))
            target = _resolve_inside(root, root / str(article.get("markdown_path", "")))
            if target is None or not target.is_file():
                return _blocked("gate:markdown_review_evidence", article=aid,
                                errors=["markdown_artifact_missing"])
            markdown_by_article[aid] = target
        review_artifacts = [markdown_by_article[str(article["article_id"])] for article in articles]
    else:
        # Historical/explicit HTML batches retain the prior delivery contract.
        delivery_htmls = _delivery_htmls(root)
        if not delivery_htmls:
            return _blocked("evidence_missing:delivery-html")
        review_artifacts = delivery_htmls

    if preview_mode is not None:
        evidence_name = (
            "preview-local-evidence.json"
            if preview_mode == "local_codex"
            else "preview-http-evidence.json"
        )
        evidence_path = root / "review" / evidence_name
        if not evidence_path.is_file():
            return _blocked(
                "evidence_missing:preview-evidence",
                preview_mode=preview_mode,
                file=evidence_name,
            )
        evidence = _load_json(evidence_path)
        if evidence is None:
            return _blocked(
                "evidence_unreadable:preview-evidence",
                preview_mode=preview_mode,
                file=evidence_name,
            )
        preview_errors = validate_preview_evidence(
            evidence,
            mode=preview_mode,
            root=root,
            delivery_htmls=delivery_htmls,
        )
        if preview_errors:
            return _blocked(
                "gate:preview_contract",
                preview_mode=preview_mode,
                file=evidence_name,
                errors=preview_errors,
            )

    # ---- 2. 机械闸门：style_gate ---------------------------------------
    style_pattern = (
        "review/style-gate-markdown-*.json"
        if review_surface == "markdown_codex"
        else "review/style-gate-*.json"
    )
    style_files = sorted(root.glob(style_pattern))
    if not style_files:
        return _blocked(f"evidence_missing:{style_pattern}")
    style_reports: list[tuple[Path, dict]] = []
    for sf in style_files:
        data = _load_json(sf)
        if data is None:
            return _blocked("evidence_unreadable:style-gate", file=sf.name)
        style_reports.append((sf, data))
        for art in data.get("articles") or []:
            if not isinstance(art, dict):
                continue
            if int(art.get("error_count", 0) or 0) > 0:
                return _blocked("gate:style_gate", file=sf.name, article=art.get("index"))
            char_count = int(art.get("char_count", 0) or 0)
            if char_count and not MIN_CJK_CHARS <= char_count <= MAX_CJK_CHARS:
                human_items.append(
                    f"{sf.name}: char_count={char_count} outside "
                    f"{MIN_CJK_CHARS}-{MAX_CJK_CHARS}"
                )
            for hit in art.get("hits") or []:
                if isinstance(hit, dict) and hit.get("severity") == "warning":
                    human_items.append(f"{sf.name}: {hit.get('rule')}")
            for field, warning_statuses in _STRUCTURED_WARNING_STATUSES.items():
                structured_status = art.get(field)
                if (
                    isinstance(structured_status, dict)
                    and structured_status.get("status") in warning_statuses
                ):
                    human_items.append(
                        f"{sf.name}: {field}: {structured_status.get('reason', 'status=warning')}"
                    )

    # ---- 3. 发布不变量 ---------------------------------------------------
    auth_fields = ("authorization_by", "authorized_at", "authorization_ref", "authorized_publication_scope")
    for art in articles:
        if not isinstance(art, dict):
            continue
        aid = str(art.get("article_id", "?"))
        if str(art.get("publication_authorization", "not_authorized")) != "not_authorized":
            return _blocked("gate:publication_authorization", article=aid,
                            value=str(art.get("publication_authorization")))
        for field in auth_fields:
            if art.get(field) not in (None, ""):
                return _blocked("gate:publication_authorization", article=aid, field=field)

    # ---- 4. 跨批指纹 ------------------------------------------------------
    try:
        history = collect_history(exclude_run=root.name)
        issues = check_cross_batch(articles, history)
    except Exception as exc:  # noqa: BLE001 — 指纹检查失败不得放行
        return _blocked("gate:cross_batch_failed", error=str(exc))
    waivers: list[dict] = []
    for issue in issues:
        level = str(issue.get("level", ""))
        if level == "error":
            # 控制器豁免注记通道（人机一致）：portfolio-gate-report.json 中已有人工裁决
            # （confirmed_new_angle / 确认豁免）且 candidate 匹配时，error 降级为已裁决
            # 记录放行，不再 BLOCKED——机器只拦未裁决的重复。
            waiver = _match_adjudication_waiver(root, str(issue.get("candidate", "")))
            if waiver:
                waivers.append({
                    "candidate": issue.get("candidate"),
                    "gate": "gate:cross_batch",
                    "message": issue.get("message"),
                    "adjudicated_at": waiver.get("recorded_at"),
                    "adjudicator": waiver.get("adjudicator"),
                    "verdict": waiver.get("result") or waiver.get("verdict"),
                })
                continue
            return _blocked("gate:cross_batch", candidate=issue.get("candidate"),
                            message=issue.get("message"))
        if level == "warning":
            human_items.append(f"cross_batch: {issue.get('message')}")

    # ---- 5. 存疑判定：prose_pilot 字数口径 --------------------------------
    prose_files = sorted(root.glob("review/prose-pilot-report*.json"))
    if not prose_files:
        return _blocked("evidence_missing:prose-pilot-report.json")
    prose_latest = _load_json(prose_files[-1])  # 取最新一份（-v2 等）
    if prose_latest is None:
        return _blocked("evidence_unreadable:prose-pilot-report.json")

    # 字数口径差：style_gate char_count vs prose_pilot chars
    char_gaps: list[str] = []
    if style_files and prose_files:
        prose_latest = _load_json(prose_files[-1])
        for sf in style_files:
            data = _load_json(sf)
            if data is None:
                continue
            for art in data.get("articles") or []:
                if not isinstance(art, dict) or not art.get("title"):
                    continue
                sg_count = int(art.get("char_count", 0) or 0)
                pp_count = _find_prose_chars(prose_latest, str(art.get("title", "")))
                if sg_count and pp_count:
                    diff = abs(sg_count - pp_count) / max(sg_count, pp_count)
                    if diff > CHAR_DIFF_TOLERANCE:
                        char_gaps.append(
                            f"{sf.name}: style_gate={sg_count} prose_pilot={pp_count} 差{diff:.0%}"
                        )
    human_items.extend(char_gaps)

    # 评分卡是发布质量证据，不是发布授权；它不能改变 not_authorized 不变量。
    # 放在既有机械、授权和字数证据之后，保持旧门禁的错误优先级。
    scoring_dir = root / "review" / "scoring"
    scoring_cards: dict[str, dict] = {}
    for index, article in enumerate(articles):
        if not isinstance(article, dict):
            return _blocked("evidence_invalid:batch.json:article", article=index)
        article_id = article.get("article_id")
        if (
            not isinstance(article_id, str)
            or not article_id
            or article_id in {".", ".."}
            or "/" in article_id
            or "\\" in article_id
            or "\x00" in article_id
        ):
            return _blocked("evidence_invalid:batch.json:article_id", article=index)
        card_path = scoring_dir / f"{article_id}.json"
        card_resolved = _resolve_inside(root, card_path)
        if card_resolved is None or not card_path.is_file():
            return _blocked("evidence_missing:scoring-card", article=article_id)
        card = _load_json(card_path)
        if card is None:
            return _blocked("evidence_unreadable:scoring-card", article=article_id)
        scoring_cards[str(article_id)] = card
        scoring_errors = _validate_scoring_card(
            card,
            root,
            delivery_htmls,
            article_id,
            review_surface=review_surface,
            markdown_artifact=markdown_by_article.get(str(article_id)),
        )
        if scoring_errors:
            return _blocked(
                "gate:scoring_card",
                article=article_id,
                errors=scoring_errors,
            )

    # The scoring-card checks above deliberately run first when a review
    # artifact was changed: the caller gets the most specific stale-artifact
    # diagnosis. A batch still cannot pass until every style report is bound
    # to exactly one current surface artifact.
    style_artifacts: dict[Path, str] = {}
    for sf, data in style_reports:
        style_artifact, artifact_errors = _validate_style_artifact(
            data,
            root,
            review_artifacts,
            review_surface=review_surface,
        )
        if artifact_errors:
            return _blocked(
                "evidence_invalid:style-gate",
                file=sf.name,
                errors=artifact_errors,
            )
        assert style_artifact is not None  # guarded by artifact_errors above
        if style_artifact in style_artifacts:
            return _blocked(
                "evidence_invalid:style-gate",
                file=sf.name,
                errors=[
                    "artifact_binding_duplicate",
                    f"already_bound_by:{style_artifacts[style_artifact]}",
                ],
            )
        style_artifacts[style_artifact] = sf.name

    expected_style_artifacts = {
        resolved
        for path in review_artifacts
        if (resolved := _resolve_inside(root, path)) is not None
    }
    if set(style_artifacts) != expected_style_artifacts:
        missing = sorted(str(path) for path in expected_style_artifacts - set(style_artifacts))
        extra = sorted(str(path) for path in set(style_artifacts) - expected_style_artifacts)
        return _blocked(
            "evidence_invalid:style-gate",
            errors=[
                *([f"artifact_binding_missing_for:{path}" for path in missing]),
                *([f"artifact_binding_extra:{path}" for path in extra]),
            ],
        )

    # ---- editorial-record（协议 v1.0，M2 起为必需） ------------------------
    editorial_files = [
        path
        for pattern in ("review/*editorial*", "evidence/*editorial*")
        for path in sorted(root.glob(pattern))
        if path.suffix.lower() == ".json"
    ]
    editorial_records: list[tuple[Path, dict]] = []
    if editorial_files:
        for editorial_file in editorial_files:
            record = _load_json(editorial_file)
            if record is None:
                return _blocked("evidence_unreadable:editorial-record", file=editorial_file.name)
            editorial_records.append((editorial_file, record))
            try:
                report = evaluate_editorial_record(record, root)
            except Exception as exc:  # noqa: BLE001
                return _blocked("gate:editorial_review", file=editorial_file.name, error=str(exc))
            if report.get("verdict") != "PASS":
                return _blocked(
                    "gate:editorial_review",
                    file=editorial_file.name,
                    editorial_verdict=report.get("verdict"),
                    errors=report.get("errors"),
                )
            surface_errors = _validate_editorial_review_surface(
                record,
                root,
                review_surface,
                markdown_by_article,
            )
            if surface_errors:
                return _blocked(
                    "gate:editorial_review",
                    file=editorial_file.name,
                    errors=surface_errors,
                )
    else:
        gaps.append(_evidence_gap("editorial-record.json 缺失（协议 v1.0 落地前批次可忽略）"))

    # ---- 6. M2/R7.5 human-state contract ---------------------------------
    human_items.extend(
        _review_completion_items(
            batch,
            articles,
            editorial_records,
            root,
            delivery_htmls,
            review_surface=review_surface,
            markdown_by_article=markdown_by_article,
        )
    )

    # ---- 收敛 --------------------------------------------------------------
    result: dict = {
        "run_id": run_id,
        "batch_dir": root.name,
        "verdict": None,
        "reason": None,
        "evidence_gaps": gaps,
        "human_judgment_items": human_items,
        "adjudicated_waivers": waivers,
        "publication_authorization": "not_authorized",
    }
    if preview_mode is not None:
        result["preview_mode"] = preview_mode
    result["review_surface"] = review_surface
    if human_items:
        result.update(_pending("存在存疑项，需人工判定", human_items))
    else:
        result.update(_publishable())
    return result


def _match_adjudication_waiver(root: Path, candidate: str) -> dict | None:
    """读取本批 portfolio-gate-report.json 的控制器豁免注记，candidate 匹配即返回。

    豁免条件（安全限制）：adjudicated=True 且 result 含 confirmed_new_angle / 确认豁免；
    仅匹配同一 candidate。机器尊重人工裁决，但绝不自行创造豁免。
    """
    if not candidate:
        return None
    report_file = root / "portfolio-gate-report.json"
    if not report_file.exists():
        return None
    try:
        report = json.loads(report_file.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — 读不到注记当作无豁免，走原 BLOCKED 路径
        return None
    adj = report.get("controller_adjudication") or {}
    if not isinstance(adj, dict) or adj.get("adjudicated") is not True:
        return None
    result_text = str(adj.get("result", ""))
    if "confirmed_new_angle" not in result_text and "确认豁免" not in result_text:
        return None
    if candidate not in result_text:
        return None
    return adj


def _find_prose_chars(prose: dict | None, title: str) -> int:
    """在 prose-pilot 报告里按标题找字数；找不到返回 0。"""
    if prose is None:
        return 0
    norm = lambda s: re.sub(r"\s+", "", str(s))
    target = norm(title)
    for b in prose.get("batches") or []:
        for art in b.get("articles") or []:
            if isinstance(art, dict) and norm(art.get("title", "")) == target:
                return int(art.get("chars", 0) or 0)
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True, type=Path, help="批次目录 runs/<date>/controlled-NNN")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = evaluate_batch(args.batch)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["verdict"] == PUBLISHABLE else 1


if __name__ == "__main__":
    raise SystemExit(main())
