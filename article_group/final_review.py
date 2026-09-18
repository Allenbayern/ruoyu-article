"""final_review — prepublication 总复核层（v1）。

汇总单批所有闸门产物为单一判定：PUBLISHABLE / BLOCKED / PENDING（需人工）。

判定顺序（fail-closed）：
1. 证据齐全性：batch.json / preflight-report.json / 当前审阅面 artifact /
   style-gate / prose-pilot / 每篇评分卡必须存在；editorial-record 若存在必须通过校验。
2. 机械闸门：preflight status == PASS；style-gate error_count == 0。
3. 发布不变量：publication_authorization == "not_authorized" 且无 authorization_* 字段。
4. 跨批指纹：已加载历史或明确 empty_history 才能比对；未加载历史不能宣称去重通过。
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

from article_group.article_first import (
    ARTICLE_FIRST_CONTRACT_VERSION,
    validate_phase_field_boundary,
)
from article_group.content_fidelity import content_body_path, evaluate_content_fidelity
from article_group.delivery import compose_delivery_markdown, validate_body_draft, validate_delivery_markdown
from article_group.editorial_review import evaluate_editorial_record
from article_group.human_attestation import validate_human_attestation
from article_group.independent_review import evaluate_independent_review
from article_group.portfolio_gate import check_cross_batch, collect_history, interpret_history_input
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
from article_group.run_contract import (
    is_strict_run_contract,
    validate_article_first_run_lane,
    validate_phase_contract_fields,
    validate_referenced_contract_artifacts,
    validate_run_contract,
)
from article_group.rule_compliance import evaluate_batch_rule_compliance
from article_group.title_pack_fidelity import evaluate_title_pack, evaluate_title_review

PUBLISHABLE = "PUBLISHABLE"
BLOCKED = "BLOCKED"
PENDING = "PENDING"
FINAL_REVIEW_SCHEMA = "final-review-v1"

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
_MODERN_ENTRY_REVIEW_FIELDS = (
    "first_screen_value",
    "reader_takeaway",
    "reader_takeaway_locator",
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


def _dimensions_for_reason(reason: str) -> dict[str, str]:
    if reason.startswith("gate:content_contract"):
        return {
            "content_result": "FAIL",
            "evidence_result": "PASS",
            "governance_result": "PENDING",
        }
    if reason.startswith("gate:publication_authorization"):
        return {
            "content_result": "PASS",
            "evidence_result": "PASS",
            "governance_result": "FAIL",
        }
    if reason.startswith("gate:title_pack") or reason.startswith("gate:delivery_artifact"):
        return {
            "content_result": "PASS",
            "evidence_result": "FAIL",
            "governance_result": "PENDING",
        }
    if reason.startswith("gate:independent_review"):
        # 2026-09-18（N2 裁决）：content_result=PASS 的前提是 L2=approve。
        # L2 跑完但未通过（needs_changes / UNVERIFIED）是内容判定，内容栏不得写 PASS。
        return {
            "content_result": "FAIL",
            "evidence_result": "FAIL",
            "governance_result": "PENDING",
        }
    return {
        "content_result": "UNKNOWN",
        "evidence_result": "FAIL",
        "governance_result": "PENDING",
    }


def _blocked(reason: str, **extra: object) -> dict:
    return {
        "verdict": BLOCKED,
        "reason": reason,
        **_dimensions_for_reason(reason),
        "publication_authorization": "not_authorized",
        **extra,
    }


_CONTENT_PENDING_MARKERS = (
    "style-gate",
    "style_gate",
    "prose-pilot",
    "prose_pilot",
    "opening_hook",
    "title_gap",
    "fact_density",
    "hook_declaration",
    "closing_interaction",
    "char_count=",
    "rule_compliance=",
    "source_stripped_",
)
_EVIDENCE_PENDING_MARKERS = (
    "cross_batch",
    "revalidation",
    "fact_card",
    "evidence",
    "source_",
    "stale",
)
# 2026-09-18（N2 裁决）：content_result=PASS 的前提是 L2=approve。复核未完成
# （pending / missing）时内容栏不得显示 PASS——否则"没跑 L2"比"跑了没过"更容易拿到
# CONTENT_READY（daily-009 就是内容 READY + 治理 PENDING 并存）。人没签字仍不算内容
# 阻塞：这里记 PENDING，不记 FAIL；历史 run 不追溯重判。
_CONTENT_GATED_BY_L2_MARKERS = ("independent_review=",)
_GOVERNANCE_PENDING_MARKERS = (
    "independent_review=",
    "controller_acceptance=",
    "human_editor_attestation=",
    "human_attestation_",
    "human_readability_attestation=",
    "human_review_completed_by_nonhuman_provenance",
    "delivery_state=",
    "html_delivery_state=",
    "editorial-review-record",
)

# 只有"人还没签"才会产生这些原因码；它们属治理待办，不是内容缺陷（A1，2026-09-15）。
_HUMAN_ATTESTATION_CODES = (
    "source_stripped_readability_pending",
    "source_stripped_human_record_missing",
    "source_stripped_human_reviewer_missing",
)


def _pending_dimensions(items: list[str]) -> dict[str, str]:
    dimensions = {
        "content_result": "PASS",
        "evidence_result": "PASS",
        "governance_result": "PASS",
    }
    for item in items:
        normalized = item.lower()
        if any(marker in normalized for marker in _CONTENT_PENDING_MARKERS):
            dimensions["content_result"] = "PENDING"
        if any(marker in normalized for marker in _CONTENT_GATED_BY_L2_MARKERS):
            dimensions["content_result"] = "PENDING"
        if any(marker in normalized for marker in _EVIDENCE_PENDING_MARKERS):
            dimensions["evidence_result"] = "PENDING"
        if any(marker in normalized for marker in _GOVERNANCE_PENDING_MARKERS):
            dimensions["governance_result"] = "PENDING"
        elif not any(
            marker in normalized
            for marker in (*_CONTENT_PENDING_MARKERS, *_EVIDENCE_PENDING_MARKERS)
        ):
            # Unknown human judgment items are not silently treated as
            # content or governance passes.
            dimensions["evidence_result"] = "PENDING"
    return dimensions


def _pending(reason: str, items: list[str]) -> dict:
    return {
        "verdict": PENDING,
        "reason": reason,
        "human_judgment_items": items,
        **_pending_dimensions(items),
        "publication_authorization": "not_authorized",
    }


def _publishable() -> dict:
    return {
        "verdict": PUBLISHABLE,
        "reason": "全部闸门和评分卡通过；发布仍需真人授权",
        "content_result": "PASS",
        "evidence_result": "PASS",
        "governance_result": "PASS",
        "publication_authorization": "not_authorized",
    }


def _is_article_first_batch(batch: dict, articles: list[object] | None = None) -> bool:
    values = articles if articles is not None else batch.get("articles", [])
    return bool(
        batch.get("article_first_contract_version") == ARTICLE_FIRST_CONTRACT_VERSION
        or is_strict_run_contract(batch)
        or any(
            isinstance(article, dict)
            and (
                article.get("article_first_contract_version") == ARTICLE_FIRST_CONTRACT_VERSION
                or any(
                    field in article
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
            for article in values
        )
    )


def _modern_relative_path(root: Path, raw: object) -> Path | None:
    if not isinstance(raw, str) or not raw.strip() or Path(raw).is_absolute() or ".." in Path(raw).parts:
        return None
    return _resolve_inside(root, root / raw)


def _modern_article_contract(root: Path, article: dict, *, strict: bool = False) -> dict:
    """Validate the immutable body/title/delivery chain for one modern article."""

    aid = str(article.get("article_id", "?"))
    errors: list[str] = []
    errors.extend(
        validate_phase_contract_fields(article, "title")
        if strict
        else validate_phase_field_boundary(article, "title")
    )

    def path_for(fields: tuple[str, ...], label: str) -> tuple[str, Path | None]:
        for field in fields:
            raw = article.get(field)
            if isinstance(raw, str) and raw.strip():
                path = _modern_relative_path(root, raw)
                if path is None:
                    errors.append(f"{label}_path_invalid")
                return raw.strip(), path
        errors.append(f"{label}_path_missing")
        return "", None

    body_raw, body_path = path_for(("body_draft_path", "body_path"), "body_draft")
    content_raw, content_path = path_for(
        ("content_fidelity_path", "content_fidelity_record_path"),
        "content_fidelity",
    )
    title_raw, title_path = path_for(("title_pack_path",), "title_pack")
    title_review_raw, title_review_path = path_for(("title_review_path",), "title_review")
    delivery_raw, delivery_path = path_for(("delivery_path", "markdown_path"), "delivery")

    body_text = ""
    if body_path is None or not body_path.is_file():
        errors.append("body_draft_missing")
    else:
        try:
            body_text = body_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            errors.append("body_draft_unreadable")
    errors.extend(validate_body_draft(body_text)) if body_text else None

    content = _load_json(content_path) if content_path is not None and content_path.is_file() else None
    content_result = None
    if content is None:
        errors.append("content_fidelity_missing_or_unreadable")
    else:
        content_report = evaluate_content_fidelity(
            content,
            body_text=body_text,
            strict=strict or None,
        )
        content_result = content_report.get("status")
        if content_result != "pass":
            errors.extend(
                f"content_fidelity:{error}"
                for error in content_report.get("errors", [])
            )
            if not content_report.get("errors"):
                errors.append("content_fidelity_result_not_pass")
        if content_body_path(content) != body_raw:
            errors.append("content_fidelity_body_path_mismatch")

    title_pack = _load_json(title_path) if title_path is not None and title_path.is_file() else None
    title_result = None
    selected_title = ""
    if title_pack is None:
        errors.append("title_pack_missing_or_unreadable")
    else:
        title_report = evaluate_title_pack(title_pack, body_text=body_text)
        title_result = title_report.get("status")
        if title_result != "selected":
            errors.extend(
                f"title_pack:{error}"
                for error in title_report.get("errors", [])
            )
            if not title_report.get("errors"):
                errors.append("title_pack_result_not_selected")
        selected_id = title_report.get("selected_title_id")
        for direction in title_pack.get("directions", []):
            if isinstance(direction, dict) and direction.get("title_id") == selected_id:
                selected_title = str(direction.get("title", "")).strip()
                break
        if title_result == "selected" and not selected_title:
            errors.append("selected_title_missing")
        if title_pack.get("body_path") != body_raw:
            errors.append("title_pack_body_path_mismatch")
        reference = title_pack.get("content_fidelity_ref")
        if not isinstance(reference, dict) or reference.get("path") != content_raw:
            errors.append("title_pack_content_fidelity_path_mismatch")
        elif content_path is not None and _sha256(content_path) != str(reference.get("sha256", "")).lower():
            errors.append("title_pack_content_fidelity_hash_mismatch")

    title_review = (
        _load_json(title_review_path)
        if title_review_path is not None and title_review_path.is_file()
        else None
    )
    title_review_result = None
    if title_review is None:
        errors.append("title_review_missing_or_unreadable")
    else:
        title_review_report = evaluate_title_review(title_review, title_pack=title_pack)
        title_review_result = title_review_report.get("status")
        if title_review_result != "pass":
            errors.extend(
                f"title_review:{error}"
                for error in title_review_report.get("errors", [])
            )
            if not title_review_report.get("errors"):
                errors.append("title_review_result_not_pass")
        if title_review.get("article_id") != aid:
            errors.append("title_review_article_id_mismatch")
        reference = title_review.get("title_pack_ref")
        if not isinstance(reference, dict) or reference.get("path") != title_raw:
            errors.append("title_review_title_pack_path_mismatch")
        elif title_path is not None and _sha256(title_path) != str(reference.get("sha256", "")).lower():
            errors.append("title_review_title_pack_hash_mismatch")

    if delivery_path is None or not delivery_path.is_file():
        errors.append("delivery_missing")
        delivery_text = ""
    else:
        try:
            delivery_text = delivery_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            errors.append("delivery_unreadable")
            delivery_text = ""
    if selected_title and delivery_text:
        errors.extend(validate_delivery_markdown(delivery_text, selected_title))
        try:
            if compose_delivery_markdown(body_text, selected_title) != delivery_text:
                errors.append("delivery_body_mismatch")
        except ValueError:
            errors.append("delivery_body_mismatch")

    return {
        "article_id": aid,
        "errors": sorted(set(errors)),
        "body_path": body_path,
        "content_path": content_path,
        "title_path": title_path,
        "delivery_path": delivery_path,
        "delivery_raw": delivery_raw,
        "content_result": content_result,
        "title_result": title_result,
        "title_review_result": title_review_result,
        "selected_title": selected_title,
    }


def _strict_independent_review(
    root: Path,
    article: dict,
    binding: dict,
    *,
    run_id: str,
) -> tuple[str, list[str]]:
    """Check the independent review against the exact current article chain."""

    aid = str(article.get("article_id", "?"))
    raw_path = article.get("independent_review_path") or article.get(
        "independent_review_record_path"
    )
    if not isinstance(raw_path, str) or not raw_path.strip():
        raw_path = f"review/{aid}/independent-review.json"
    review_path = _modern_relative_path(root, raw_path)
    if review_path is None or not review_path.is_file():
        return "pending", [f"{aid}: independent_review=missing"]
    review = _load_json(review_path)
    if review is None:
        return "blocked", ["independent_review_unreadable"]

    body_raw = article.get("body_draft_path") or article.get("body_path")
    title_raw = article.get("title_pack_path")
    artifact_raw = (
        binding.get("delivery_raw")
        or article.get("delivery_path")
        or article.get("artifact_path")
        or body_raw
    )
    report = evaluate_independent_review(
        review,
        run_root=root,
        expected_artifact_path=artifact_raw if isinstance(artifact_raw, str) else None,
        expected_body_path=body_raw if isinstance(body_raw, str) else None,
        expected_title_pack_path=title_raw if isinstance(title_raw, str) else None,
        expected_run_id=run_id,
        strict=True,
    )
    errors = report.get("errors", [])
    if "stale_review" in errors:
        return "blocked", sorted(set(["stale_review", *errors]))
    if errors:
        return "blocked", sorted(set(errors))
    if not report.get("pass"):
        status = str(report.get("status", "pending"))
        normalized = status.strip().lower()
        if normalized not in {"pending", ""}:
            decision = str(report.get("decision") or "").strip() or "missing"
            # 复核已完成但没有通过（decision 非 approve*，或 status=UNVERIFIED）属内容问题，
            # 必须阻断；只有"尚未完成"才进治理待办。2026-09-15 修复：此前二者都被写成
            # independent_review=<status>，该标记移入治理栏后会把未通过的复核漏放。
            return "blocked", [f"{aid}: independent_review_decision={decision}"]
        return "pending", [f"{aid}: independent_review={normalized or 'missing'}"]
    return "pass", []


def _requires_independent_review(batch: dict) -> bool:
    """M2/R7.5 batches must not look publishable before human review is complete.

    Older fixture batches and pre-M2 historical runs may not carry the state
    fields.  Once a batch declares the M2 checkpoint/state contract, the
    quality result is fail-closed until independent review and human
    attestation are explicitly complete.
    """
    milestone = str(batch.get("milestone", ""))
    return bool(
        is_strict_run_contract(batch)
        or "M2" in milestone
        or batch.get("manifest_state")
        or batch.get("target_state")
    )


def _rule_compliance_pending_items(rule_report: Mapping[str, Any]) -> list[str]:
    """把未通过的 rule_compliance 逐篇转成人工待办项（A1，2026-09-15）。

    - 若某篇的失败原因**全部**是"人还没签"（可读性/人工记录），记为治理项
      ``human_readability_attestation=``：机器判内容，人判签字，各归各位。
    - 一旦混入任何机器可判的失败原因，仍按内容项 ``rule_compliance=`` 处理（fail-closed）。

    注意：治理项的文案刻意**不含** ``rule_compliance=`` 这个子串，否则会被
    ``_CONTENT_PENDING_MARKERS`` 重新归类成内容问题（同一类折叠会制造假阳性）。
    """

    items: list[str] = []
    for entry in rule_report.get("articles", []):
        if not isinstance(entry, dict) or entry.get("status") == "PASS":
            continue
        aid = str(entry.get("article_id", "?"))
        status = str(entry.get("status", "PENDING")).lower()
        errors = [str(code) for code in (entry.get("errors") or [])]
        human_only = bool(errors) and all(code in _HUMAN_ATTESTATION_CODES for code in errors)
        if human_only:
            items.append(f"{aid}: human_readability_attestation=pending ({status})")
        else:
            items.append(f"{aid}: rule_compliance={status}")
    return items


# 只有"编辑口径"类、且已由 controller 明确裁决的指标才可被豁免（2026-09-15，F5 选项 b）。
# 机器不会创建 review/controller-waivers.json，也不会替 controller 补字段。
_WAIVABLE_GATES = ("fact_density",)


def _style_record_article_id(file_name: str) -> str:
    """从 ``style-gate-markdown-art-001.json`` 取回 article_id；取不到返回空串。"""

    match = re.match(r"style-gate(?:-markdown)?-(?P<aid>.+)\.json$", file_name)
    return match.group("aid") if match else ""


def _load_controller_waivers(root: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """读取 controller 手写的豁免记录（fail-closed：任何异常都视为无豁免）。

    文件 ``review/controller-waivers.json``::

        {"schema_version": "controller-waivers-v1",
         "waivers": [{"gate": "fact_density", "article_id": "art-001",
                      "adjudicated": true, "adjudicator": "Allen",
                      "recorded_at": "2026-09-15",
                      "reason": "口径理由（必填）"}]}

    条目必须 gate 落在 ``_WAIVABLE_GATES``、字段齐全、``adjudicated`` 为 true；
    任何一条不满足就被忽略并继续阻断——机器只尊重显式裁决，不自行创造豁免。
    """

    path = root / "review" / "controller-waivers.json"
    if not path.is_file():
        return {}
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return {}
    entries = payload.get("waivers")
    if not isinstance(entries, list):
        return {}
    loaded: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        gate = str(entry.get("gate") or "").strip()
        aid = str(entry.get("article_id") or "").strip()
        reason = str(entry.get("reason") or "").strip()
        adjudicator = str(entry.get("adjudicator") or "").strip()
        if gate not in _WAIVABLE_GATES or not aid or not reason or not adjudicator:
            continue
        if entry.get("adjudicated") is not True:
            continue
        loaded[(gate, aid)] = {
            "article_id": aid,
            "gate": gate,
            "reason": reason,
            "adjudicator": adjudicator,
            "recorded_at": str(entry.get("recorded_at") or ""),
            "source": "review/controller-waivers.json",
        }
    return loaded


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


_FINAL_REVIEW_COMPARISON_FIELDS = (
    "run_id",
    "verdict",
    "reason",
    "content_result",
    "evidence_result",
    "governance_result",
    "article_rule_compliance",
    "publication_authorization",
    "human_judgment_items",
    "evidence_gaps",
    "adjudicated_waivers",
    "review_surface",
    "preview_mode",
    "final_review_schema",
    "batch_sha256",
    "reviewed_artifacts",
)


def _current_review_artifacts(root: Path, batch: dict) -> list[dict[str, str]]:
    """Return the current final review surface and its byte identities."""

    entries: list[dict[str, str]] = []
    surface = batch.get("review_surface")
    if surface == "markdown_codex":
        articles = batch.get("articles")
        if not isinstance(articles, list):
            return entries
        for article in articles:
            if not isinstance(article, dict):
                continue
            raw_path = article.get("delivery_path") or article.get("markdown_path")
            if not isinstance(raw_path, str):
                continue
            target = _resolve_inside(root, root / raw_path)
            digest = _sha256(target) if target is not None and target.is_file() else None
            if target is None or digest is None:
                continue
            entries.append(
                {
                    "article_id": str(article.get("article_id", "")),
                    "path": target.relative_to(root.resolve()).as_posix(),
                    "sha256": digest,
                }
            )
        return entries

    for target in _delivery_htmls(root):
        digest = _sha256(target)
        if digest is None:
            continue
        entries.append(
            {
                "path": target.relative_to(root.resolve()).as_posix(),
                "sha256": digest,
            }
        )
    return entries


def build_final_review_record(batch_dir: str | Path) -> dict:
    """Evaluate and bind a final-review record to the current run bytes."""

    root = Path(batch_dir)
    report = dict(evaluate_batch(root))
    batch = _load_json(root / "batch.json") or {}
    if batch.get("article_rule_compliance_required") is True:
        report["article_rule_compliance"] = evaluate_batch_rule_compliance(root, batch).get("status", "UNVERIFIED")
    else:
        report.setdefault("article_rule_compliance", "not_required")
    if not report.get("run_id") and batch.get("run_id"):
        report["run_id"] = batch["run_id"]
    report.update(
        {
            "final_review_schema": FINAL_REVIEW_SCHEMA,
            "final_review_path": "review/final-review.json",
            "batch_sha256": _sha256(root / "batch.json"),
            "reviewed_artifacts": _current_review_artifacts(root, batch),
        }
    )
    return report


def validate_final_review_record(
    record: object,
    batch_dir: str | Path,
    *,
    expected: dict | None = None,
) -> list[str]:
    """Fail closed unless a persisted final review is for this exact run."""

    if not isinstance(record, dict):
        return ["final_review_record_not_object"]
    root = Path(batch_dir)
    batch = _load_json(root / "batch.json")
    if batch is None:
        return ["batch_unreadable"]

    errors: list[str] = []
    if record.get("final_review_schema") != FINAL_REVIEW_SCHEMA:
        errors.append("final_review_schema_missing_or_invalid")
    expected_run_id = batch.get("run_id")
    if record.get("run_id") != expected_run_id:
        errors.extend(("stale_final_review", "final_review_run_id_mismatch"))
    batch_digest = _sha256(root / "batch.json")
    if not isinstance(record.get("batch_sha256"), str):
        errors.append("final_review_binding_missing:batch_sha256")
    if record.get("batch_sha256") != batch_digest:
        errors.extend(("stale_final_review", "final_review_batch_hash_mismatch"))
    current_artifacts = _current_review_artifacts(root, batch)
    if record.get("reviewed_artifacts") != current_artifacts:
        errors.extend(("stale_final_review", "final_review_artifacts_mismatch"))

    if expected is not None:
        for field in _FINAL_REVIEW_COMPARISON_FIELDS:
            if record.get(field) != expected.get(field):
                errors.extend(("stale_final_review", f"final_review_result_mismatch:{field}"))
    return list(dict.fromkeys(errors))


def _persist_final_review(root: Path, report: dict, *, force: bool = False) -> Path:
    """落盘 final-review.json——走留底通道（封存 run 上必须显式 force）。"""
    from article_group.evidence_write import write_evidence_json

    path = root / "review" / "final-review.json"
    write_evidence_json(path, report, run_dir=root, reason="final_review", force=force)
    return path


def write_final_review_report(
    batch_dir: str | Path,
    output: str | Path | None = None,
    *,
    force: bool = False,
) -> Path:
    """Persist a freshly evaluated and byte-bound final-review record."""

    root = Path(batch_dir)
    report = build_final_review_record(root)
    if output is not None:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return target
    return _persist_final_review(root, report, force=force)


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
    modern: bool = False,
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
    required_entry_fields = _MODERN_ENTRY_REVIEW_FIELDS if modern else _ENTRY_REVIEW_FIELDS
    if modern:
        errors.extend(validate_phase_field_boundary(card, "title"))
    if modern and any(
        isinstance(container, dict) and "title_promise" in container
        for container in review_objects
    ):
        errors.append("entry_field_forbidden:title_promise")
    for field in required_entry_fields:
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

    strict_run = is_strict_run_contract(batch)
    articles = batch.get("articles") or []
    if not isinstance(articles, list) or not articles:
        return _blocked("evidence_invalid:batch.json:no_articles")

    article_first_batch = _is_article_first_batch(batch, articles)
    lane_errors = validate_article_first_run_lane(batch, detected=article_first_batch)
    if lane_errors:
        return _blocked("gate:run_contract", errors=lane_errors)
    if strict_run:
        contract_errors = validate_run_contract(batch)
        contract_errors.extend(validate_referenced_contract_artifacts(root, batch))
        if contract_errors:
            return _blocked("gate:run_contract", errors=contract_errors)
        if batch.get("article_rule_compliance_required") is True:
            rule_report = evaluate_batch_rule_compliance(root, batch)
            if rule_report.get("status") in {"FAIL", "UNVERIFIED"}:
                return _blocked(
                    "gate:article_rule_compliance",
                    errors=rule_report.get("errors", []),
                    article_rule_compliance=rule_report.get("status"),
                )
            if rule_report.get("status") == "PENDING":
                human_items.extend(_rule_compliance_pending_items(rule_report))

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

    modern_bindings: dict[str, dict] = {}
    if article_first_batch:
        for index, article in enumerate(articles):
            if not isinstance(article, dict):
                return _blocked("gate:content_contract", article=index, errors=["article_not_object"])
            binding = _modern_article_contract(root, article, strict=strict_run)
            aid = str(article.get("article_id", index))
            modern_bindings[aid] = binding
            errors = binding["errors"]
            if errors:
                content_errors = [
                    error for error in errors
                    if error.startswith((
                        "body_draft_",
                        "missing:body_draft",
                        "content_fidelity",
                        "content_body_",
                    ))
                ]
                title_errors = [
                    error for error in errors
                    if error.startswith((
                        "title_pack",
                        "title_review",
                        "selected_title",
                    ))
                ]
                if content_errors:
                    return _blocked(
                        "gate:content_contract",
                        article=aid,
                        errors=errors,
                    )
                if title_errors:
                    return _blocked(
                        "gate:title_pack",
                        article=aid,
                        errors=errors,
                    )
                return _blocked(
                    "gate:delivery_artifact",
                    article=aid,
                    errors=errors,
                )
            if binding.get("selected_title"):
                article["title"] = binding["selected_title"]
        if strict_run:
            expected_run_id = str(batch.get("run_id") or root.name)
            for article in articles:
                if not isinstance(article, dict):
                    continue
                aid = str(article.get("article_id", "?"))
                review_status, review_items = _strict_independent_review(
                    root,
                    article,
                    modern_bindings.get(aid, {}),
                    run_id=expected_run_id,
                )
                if review_status == "blocked":
                    return _blocked(
                        "gate:independent_review",
                        article=aid,
                        errors=review_items,
                    )
                human_items.extend(review_items)
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
            raw_markdown_path = article.get("delivery_path") or article.get("markdown_path")
            target = _resolve_inside(root, root / str(raw_markdown_path or ""))
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
    controller_waivers = _load_controller_waivers(root)
    applied_waivers: list[dict[str, Any]] = []
    style_reports: list[tuple[Path, dict]] = []
    for sf in style_files:
        data = _load_json(sf)
        if data is None:
            return _blocked("evidence_unreadable:style-gate", file=sf.name)
        style_reports.append((sf, data))
        style_article_id = _style_record_article_id(sf.name)
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
                    waiver = controller_waivers.get((field, style_article_id))
                    if waiver:
                        applied_waivers.append(
                            {
                                **waiver,
                                "metric": field,
                                "status": structured_status.get("status"),
                                "detail": structured_status.get("reason", ""),
                            }
                        )
                        continue
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
        history_path = root / "portfolio-history.json"
        if history_path.is_file():
            interpreted = interpret_history_input(_load_json(history_path))
            history = interpreted["batches"]
            history_status = interpreted["history_status"]
        else:
            history = collect_history(exclude_run=root.name)
            history_status = "loaded" if history else "empty_history"
        issues = check_cross_batch(articles, history, history_status=history_status)
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
            modern=article_first_batch,
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
        "adjudicated_waivers": [*waivers, *applied_waivers],
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
    parser.add_argument("--force", action="store_true",
                        help="run 已封存时仍写入（controller 决定；走留底+记账）")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_final_review_record(args.batch)
    from article_group.evidence_write import RunSealedError

    try:
        _persist_final_review(args.batch, report, force=args.force)
    except RunSealedError as exc:  # 封存拒绝要给一句人话，不要 traceback
        print(f"final_review 拒绝写入：{exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["verdict"] == PUBLISHABLE else 1


if __name__ == "__main__":
    raise SystemExit(main())
