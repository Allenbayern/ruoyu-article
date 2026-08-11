"""Capture and validate public Bilibili long-form research evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from article_group.case_contract import CaseContractError, validate_case_card

PLAN_NAME = "metric-plan.json"
RESULTS_NAME = "capture-results.json"
_API_STAT_KEY_BY_METRIC = {
    "view_count": "view",
    "like_count": "like",
    "comment_count": "reply",
    "share_count": "share",
    "favorite_count": "favorite",
}


class BilibiliCaptureError(ValueError):
    """Raised when a local Bilibili research packet is incomplete or altered."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BilibiliCaptureError(f"json_unreadable:{path.name}") from error
    if not isinstance(value, dict):
        raise BilibiliCaptureError(f"json_object_required:{path.name}")
    return value


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative_ref(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def _text(value: object, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BilibiliCaptureError(code)
    return value.strip()


def _metric_plan(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = plan.get("metric_plan")
    if not isinstance(raw, list) or not raw:
        raise BilibiliCaptureError("metric_plan_missing")
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise BilibiliCaptureError("metric_plan_item_invalid")
        name = _text(item.get("metric"), "metric_plan_name_missing")
        if not isinstance(item.get("visible"), bool) or not isinstance(
            item.get("required"), bool
        ):
            raise BilibiliCaptureError(f"metric_plan_flags_missing:{name}")
        result.append(item)
    return result


def _source_record(root: Path, body_ref: object) -> tuple[Path, dict[str, Any]]:
    body_path = root / _text(body_ref, "body_evidence_ref_missing")
    if not body_path.is_file():
        raise BilibiliCaptureError("body_snapshot_missing")
    if not body_path.name.endswith(".clean.md"):
        raise BilibiliCaptureError("body_snapshot_name_invalid")
    source_meta = body_path.with_name(
        body_path.name.removesuffix(".clean.md") + ".source.json"
    )
    if not source_meta.is_file():
        raise BilibiliCaptureError("body_metadata_missing")
    data = _load_json(source_meta)
    expected = _text(data.get("clean_sha256"), "body_clean_sha256_missing")
    if _digest(body_path) != expected:
        raise BilibiliCaptureError("body_snapshot_digest_mismatch")
    if data.get("capture_status") != "full":
        raise BilibiliCaptureError("body_snapshot_not_full")
    return body_path, data


def _metric_record(root: Path, api_ref: object) -> tuple[Path, dict[str, Any]]:
    api_path = root / _text(api_ref, "api_evidence_ref_missing")
    data = _load_json(api_path)
    payload = data.get("payload")
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise BilibiliCaptureError("metric_api_payload_invalid")
    article = payload.get("data")
    if not isinstance(article, dict) or not isinstance(article.get("stats"), dict):
        raise BilibiliCaptureError("metric_api_payload_missing_article_stats")
    return api_path, article


def _metrics_from_result(result: Mapping[str, Any]) -> dict[str, Any]:
    raw = result.get("metrics")
    if not isinstance(raw, dict):
        raise BilibiliCaptureError("result_metrics_missing")
    return raw


def _metric_cards(
    plan_items: list[dict[str, Any]],
    result: Mapping[str, Any],
    api_article: Mapping[str, Any],
    api_ref: str,
    observed_at: str,
) -> list[dict[str, Any]]:
    metrics = _metrics_from_result(result)
    api_stats = api_article.get("stats")
    if not isinstance(api_stats, dict):
        raise BilibiliCaptureError("metric_api_payload_missing_article_stats")
    cards: list[dict[str, Any]] = []
    for plan_item in plan_items:
        metric_name = _text(plan_item.get("metric"), "metric_plan_name_missing")
        value = metrics.get(metric_name)
        if not isinstance(value, int) or isinstance(value, bool):
            raise BilibiliCaptureError(f"result_metric_missing:{metric_name}")
        api_key = _API_STAT_KEY_BY_METRIC.get(metric_name)
        if api_key is None:
            raise BilibiliCaptureError(f"metric_api_key_unknown:{metric_name}")
        if api_stats.get(api_key) != value:
            raise BilibiliCaptureError(
                f"result_metric_disagrees_with_api:{metric_name}"
            )
        cards.append(
            {
                "metric": metric_name,
                "value": value,
                "status": "observed",
                "source": "official_public_article_viewinfo_api",
                "observed_at": observed_at,
                "evidence_ref": api_ref,
            }
        )
    return cards


def build_case_cards(root: str | Path) -> dict[str, Any]:
    """Validate a frozen local packet and write non-overwriting case cards."""
    packet_root = Path(root).resolve()
    plan = _load_json(packet_root / PLAN_NAME)
    plan_items = _metric_plan(plan)
    rule = plan.get("threshold_or_rank_rule")
    if not isinstance(rule, dict):
        raise BilibiliCaptureError("threshold_rule_missing")
    results_doc = _load_json(packet_root / RESULTS_NAME)
    raw_results = results_doc.get("results")
    if not isinstance(raw_results, list) or not raw_results:
        raise BilibiliCaptureError("capture_results_missing")

    cards_dir = packet_root / "cards"
    if cards_dir.exists():
        raise BilibiliCaptureError("cards_directory_already_exists")
    cards_dir.mkdir()
    manifest_rows: list[dict[str, Any]] = []
    try:
        for raw_result in raw_results:
            if not isinstance(raw_result, dict):
                raise BilibiliCaptureError("capture_result_invalid")
            sample_id = _text(raw_result.get("slug"), "sample_slug_missing")
            observed_at = _text(raw_result.get("observed_at"), "result_observed_at_missing")
            api_path, api_article = _metric_record(
                packet_root, raw_result.get("api_evidence_ref")
            )
            body_path, source_meta = _source_record(
                packet_root, raw_result.get("body_evidence_ref")
            )
            if raw_result.get("title") != api_article.get("title"):
                raise BilibiliCaptureError("result_title_disagrees_with_api")
            if raw_result.get("author") != api_article.get("author_name"):
                raise BilibiliCaptureError("result_author_disagrees_with_api")
            card = {
                "sample_id": sample_id,
                "evidence_domain": "competitive_research_evidence",
                "snapshot_ref": f"{_relative_ref(body_path, packet_root)}#sha256={source_meta['clean_sha256']}",
                "performance_evidence_ref": _relative_ref(api_path, packet_root),
                "metric_plan": plan_items,
                "metrics": _metric_cards(
                    plan_items,
                    raw_result,
                    api_article,
                    _relative_ref(api_path, packet_root),
                    observed_at,
                ),
                "threshold_or_rank_rule": rule,
                "qualification_reason": "Frozen Bilibili public-metric plan is closed by one official article response and one full-text snapshot.",
                "qualification_status": "qualified_viral",
                "article": {
                    "article_id": raw_result.get("article_id"),
                    "title": raw_result.get("title"),
                    "author": raw_result.get("author"),
                    "url": raw_result.get("url"),
                    "theme": raw_result.get("theme"),
                },
            }
            try:
                status = validate_case_card(card)
            except CaseContractError as error:
                raise BilibiliCaptureError(f"case_contract_failed:{sample_id}:{error}") from error
            card_path = cards_dir / f"{sample_id}.json"
            card_path.write_text(
                json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            manifest_rows.append(
                {
                    "sample_id": sample_id,
                    "qualification_status": status,
                    "card_ref": _relative_ref(card_path, packet_root),
                    "snapshot_ref": card["snapshot_ref"],
                    "performance_evidence_ref": card["performance_evidence_ref"],
                }
            )
        manifest = {
            "metric_plan_ref": PLAN_NAME,
            "sample_count": len(manifest_rows),
            "qualified_viral_count": sum(
                row["qualification_status"] == "qualified_viral" for row in manifest_rows
            ),
            "samples": manifest_rows,
        }
        (packet_root / "case-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return manifest
    except Exception:
        for path in cards_dir.glob("*"):
            path.unlink()
        cards_dir.rmdir()
        raise
