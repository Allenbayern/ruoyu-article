"""final_review — prepublication 总复核层（v1）。

汇总单批所有闸门产物为单一判定：PUBLISHABLE / BLOCKED / PENDING（需人工）。

判定顺序（fail-closed）：
1. 证据齐全性：batch.json / preflight-report.json / 交付 HTML / style-gate /
   prose-pilot / 每篇评分卡必须存在；editorial-record 若存在必须通过校验。
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
from article_group.provenance import validate_current_source_provenance
from article_group.revalidation import validate_revalidation_record
from article_group.run_profile import validate_batch_profile

PUBLISHABLE = "PUBLISHABLE"
BLOCKED = "BLOCKED"
PENDING = "PENDING"

CHAR_DIFF_TOLERANCE = 0.15  # style_gate 与 prose_pilot 字数口径差容限
MIN_CJK_CHARS = 1500
MAX_CJK_CHARS = 2200

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
        if html_state in {"withheld", "pending", "withheld_pending_review"}:
            items.append(f"{aid}: html_delivery_state={html_state}")

        attestation_path = root / "review" / "attestation" / f"{aid}.human.json"
        attestation = _load_json(attestation_path) if attestation_path.is_file() else None
        attestation_errors = validate_human_attestation(
            attestation, root, aid, delivery_htmls
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
    card: dict, root: Path, delivery_htmls: list[Path], article_id: str
) -> list[str]:
    """校验评分卡质量证据及其对当前交付 HTML 的绑定。"""
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

    hash_fields = [field for field in _HASH_FIELDS if field in card]
    if len(hash_fields) != 1:
        errors.append("hash_field_ambiguous" if hash_fields else "hash_missing")
        expected_hash = None
    else:
        expected_hash = card[hash_fields[0]]
        if not isinstance(expected_hash, str) or not _SHA256_RE.fullmatch(expected_hash):
            errors.append("hash_invalid")
            expected_hash = None

    article_delivery_htmls = _article_delivery_htmls(article_id, delivery_htmls)
    delivery_targets = [_resolve_inside(root, path) for path in article_delivery_htmls]
    if not article_delivery_htmls:
        errors.append("delivery_html_identity_missing")
    elif any(target is None or not target.is_file() for target in delivery_targets):
        errors.append("delivery_html_invalid")

    path_fields = [field for field in _PATH_FIELDS if field in card]
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
                    errors.append("path_not_delivery_html")
    elif len(article_delivery_htmls) == 1:
        target = delivery_targets[0]
    else:
        errors.append("path_required_for_article_delivery_html")

    if target is not None and expected_hash is not None:
        actual_hash = _sha256(target)
        if actual_hash is None:
            errors.append("delivery_html_unreadable")
        elif actual_hash != expected_hash.lower():
            errors.append("hash_mismatch")

    return errors


def _validate_style_artifact(
    report: dict, root: Path, delivery_htmls: list[Path]
) -> tuple[Path | None, list[str]]:
    """Validate the style report's byte/path binding to final delivery HTML."""
    errors: list[str] = []
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

    # 交付 HTML：根目录 bundle 或 review/ 下成品
    delivery_htmls = _delivery_htmls(root)
    if not delivery_htmls:
        return _blocked("evidence_missing:delivery-html")

    # ---- 2. 机械闸门：style_gate ---------------------------------------
    style_files = sorted(root.glob("review/style-gate-*.json"))
    if not style_files:
        return _blocked("evidence_missing:style-gate-*.json")
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
        scoring_errors = _validate_scoring_card(card, root, delivery_htmls, article_id)
        if scoring_errors:
            return _blocked(
                "gate:scoring_card",
                article=article_id,
                errors=scoring_errors,
            )

    # The scoring-card checks above deliberately run first when a delivery
    # file was changed: the caller gets the most specific stale-artifact
    # diagnosis.  A batch still cannot pass until every style report is bound
    # to exactly one current delivery HTML.
    style_artifacts: dict[Path, str] = {}
    for sf, data in style_reports:
        style_artifact, artifact_errors = _validate_style_artifact(
            data, root, delivery_htmls
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
        for path in delivery_htmls
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
