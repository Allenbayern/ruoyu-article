from __future__ import annotations

from datetime import datetime, timedelta
from numbers import Real
import re
from typing import Any


QUALIFICATION_STATUSES = frozenset(
    {"qualified_viral", "vendor_qualified", "observed_pending", "research_only"}
)
RESEARCH_DOMAIN = "competitive_research_evidence"
FACT_DOMAIN = "ruoyu_article_fact_evidence"
FEEDBACK_DOMAIN = "production_feedback_evidence"


class CaseContractError(ValueError):
    """Raised when a record violates the v1.1 research-evidence contract."""


def _require(condition: object, code: str) -> None:
    if not condition:
        raise CaseContractError(code)


def _mapping(value: object, code: str) -> dict[str, Any]:
    _require(isinstance(value, dict), code)
    return value


def _items(value: object, code: str) -> list[object]:
    _require(isinstance(value, list), code)
    return value


def _text(value: object, code: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()), code)
    return value.strip()


def _number(value: object, code: str) -> float:
    _require(isinstance(value, Real) and not isinstance(value, bool), code)
    return float(value)


def _timestamp(value: object, code: str) -> datetime:
    text = _text(value, code)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise CaseContractError(code) from error
    _require(parsed.tzinfo is not None, code)
    _require(parsed.utcoffset() == timedelta(hours=8), code)
    return parsed


def _sha256(value: object, code: str) -> str:
    digest = _text(value, code)
    _require(bool(re.fullmatch(r"[0-9a-fA-F]{64}", digest)), code)
    return digest.lower()


# --- 占位符检测（2026-09-17）：让"语义为空的凭证"可见 -------------------------
#
# 背景：爆款库 11 张 qualified_viral 卡的 client_evidence.sha256 全部是 64 个 0。
# 契约要求 client_confirmed 回链到截图/录屏并给出 SHA-256；全零不是哈希，是占位符。
# 而 _sha256() 只校验 [0-9a-fA-F]{64} 格式，全零照样通过——该格式校验形同虚设。
#
# 判据刻意只覆盖**明确定义、可枚举**的占位符家族，不做"熵很低"这类模糊启发式，
# 以免误伤真实哈希。严重度为 warning：可见、可上报、不阻断——收紧成硬失败会把
# 现有唯一一批合格语料清零。

_HEX64 = re.compile(r"[0-9a-fA-F]{64}")
_REPEATED_HEX64 = re.compile(r"([0-9a-fA-F])\1{63}")
_SEQUENTIAL_HEX64 = frozenset(
    {"0123456789abcdef" * 4, ("0123456789abcdef" * 4).upper()}
)

PLACEHOLDER_WARNING_CODE = "client_evidence_sha256_placeholder"
WARNING_SEVERITY = "warning"


def placeholder_sha256_kind(value: object) -> str | None:
    """是"格式合法但语义为空"的 SHA-256 占位符则返回种类，否则 None。

    只认明确定义的占位符家族，不做熵估计、不做模糊匹配。
    """
    if not isinstance(value, str):
        return None
    digest = value.strip()
    if not _HEX64.fullmatch(digest):
        return None
    repeated = _REPEATED_HEX64.fullmatch(digest)
    if repeated is not None:
        return f"repeated_hex_char:{repeated.group(1).lower()}"
    if digest in _SEQUENTIAL_HEX64:
        return "sequential_hex_cycle"
    return None


def client_evidence_sha256_is_placeholder(card: dict[str, Any]) -> bool:
    """``client_evidence.sha256`` 是否为明确定义的占位符（全零/全 f 等）。

    缺失或格式非法不在本判定范围内（那是 :func:`_sha256` 的 error 级职责），返回 False。
    """
    if not isinstance(card, dict):
        return False
    evidence = card.get("client_evidence")
    if not isinstance(evidence, dict):
        return False
    return placeholder_sha256_kind(evidence.get("sha256")) is not None


def case_card_warnings(card: dict[str, Any]) -> list[dict[str, Any]]:
    """一张卡的非阻断缺陷清单（warning 级）。

    与 :func:`assess_qualification` 的硬校验严格分离：这里的问题只上报，
    不改变资格判定，因此现有合格卡不会因为"凭证是占位符"而失效。
    """
    if not isinstance(card, dict):
        return []
    warnings: list[dict[str, Any]] = []
    evidence = card.get("client_evidence")
    if isinstance(evidence, dict):
        kind = placeholder_sha256_kind(evidence.get("sha256"))
        if kind is not None:
            warnings.append(
                {
                    "code": PLACEHOLDER_WARNING_CODE,
                    "severity": WARNING_SEVERITY,
                    "field": "client_evidence.sha256",
                    "kind": kind,
                    "detail": (
                        "client_evidence.sha256 是无信息熵的占位符，无法回链到截图/录屏；"
                        "契约要求 client_confirmed 附真实证据哈希，需重新取证后回填。"
                        "本轮只标注，不作废该卡。"
                    ),
                    "remediation": "re_attest_client_evidence",
                }
            )
    return warnings


def _metric_map(card: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw_metric in _items(card.get("metrics"), "metrics_must_be_a_list"):
        metric = _mapping(raw_metric, "metric_must_be_an_object")
        name = _text(metric.get("metric"), "metric_name_missing")
        _require(name not in result, f"duplicate_metric:{name}")
        result[name] = metric
    return result


def _validate_metric_plan(
    card: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    planned: dict[str, dict[str, Any]] = {}
    plan_items = _items(card.get("metric_plan"), "metric_plan_must_be_a_list")
    _require(plan_items, "metric_plan_missing")
    for raw_item in plan_items:
        item = _mapping(raw_item, "metric_plan_item_must_be_an_object")
        name = _text(item.get("metric"), "metric_plan_name_missing")
        _require(name not in planned, f"duplicate_metric_plan:{name}")
        _require(isinstance(item.get("visible"), bool), f"metric_visibility_missing:{name}")
        _require(isinstance(item.get("required"), bool), f"metric_required_missing:{name}")
        _require(
            not (item["required"] and not item["visible"]),
            f"metric_required_but_not_visible:{name}",
        )
        planned[name] = item

    metrics = _metric_map(card)
    _require(
        not (set(metrics) - set(planned)),
        "metric_not_declared_in_plan",
    )
    for name, metric in metrics.items():
        _text(metric.get("source"), "metric_source_missing")
        _text(metric.get("observed_at"), "metric_observed_at_missing")
        _text(metric.get("evidence_ref"), "metric_evidence_ref_missing")
        status = metric.get("status")
        _require(
            status in {"observed", "not_verifiable_offsite"},
            f"invalid_metric_status:{name}",
        )
        if status == "observed":
            _require(metric.get("value") is not None, f"observed_metric_value_missing:{name}")
        else:
            _require(metric.get("value") is None, f"unverifiable_metric_has_value:{name}")
    return planned, metrics


def _thresholds(
    rule: dict[str, Any],
    key: str,
    code: str,
) -> dict[str, float]:
    raw_thresholds = rule.get(key, {})
    _require(isinstance(raw_thresholds, dict), code)
    thresholds: dict[str, float] = {}
    for metric, value in raw_thresholds.items():
        thresholds[_text(metric, f"{code}_metric_missing")] = _number(
            value, f"{code}_value_invalid"
        )
    return thresholds


def _validate_rule(
    card: dict[str, Any], planned: dict[str, dict[str, Any]]
) -> tuple[dict[str, float], dict[str, float]]:
    rule = _mapping(card.get("threshold_or_rank_rule"), "threshold_or_rank_rule_missing")
    for key in ("platform", "baseline", "window", "rule"):
        _text(rule.get(key), f"threshold_rule_{key}_missing")
    minimums = _thresholds(rule, "minimums", "threshold_rule_minimums_invalid")
    rank_maximums = _thresholds(
        rule, "rank_maximums", "threshold_rule_rank_maximums_invalid"
    )
    _require(minimums or rank_maximums, "threshold_rule_criteria_missing")
    _require(
        not ((set(minimums) | set(rank_maximums)) - set(planned)),
        "threshold_rule_metric_not_in_plan",
    )
    _text(card.get("qualification_reason"), "qualification_reason_missing")
    return minimums, rank_maximums


def _validate_client_origin(card: dict[str, Any]) -> None:
    _require(card.get("evidence_origin") == "client", "client_origin_evidence_required")
    _text(card.get("metric_plan_version"), "client_metric_plan_version_missing")
    metric_plan_frozen_at = _timestamp(
        card.get("metric_plan_frozen_at"), "client_metric_plan_not_prefrozen"
    )
    rule = _mapping(card.get("threshold_or_rank_rule"), "threshold_or_rank_rule_missing")
    _text(rule.get("version"), "client_rule_version_missing")
    rule_frozen_at = _timestamp(rule.get("frozen_at"), "client_rule_not_prefrozen")
    evidence = _mapping(card.get("client_evidence"), "client_evidence_missing")
    _text(evidence.get("evidence_ref"), "client_evidence_ref_missing")
    _text(evidence.get("original_display"), "client_original_display_missing")
    evidence_observed_at = _timestamp(
        evidence.get("observed_at"), "client_evidence_observed_at_missing"
    )
    _require(
        metric_plan_frozen_at <= evidence_observed_at,
        "client_metric_plan_not_prefrozen",
    )
    _require(
        rule_frozen_at <= evidence_observed_at,
        "client_rule_not_prefrozen",
    )
    _text(evidence.get("confirmer"), "client_evidence_confirmer_missing")
    _sha256(evidence.get("sha256"), "client_evidence_sha256_missing")
    _require(evidence.get("sanitized") is True, "client_evidence_not_sanitized")
    for raw_metric in _items(card.get("metrics"), "metrics_must_be_a_list"):
        metric = _mapping(raw_metric, "metric_must_be_an_object")
        metric_observed_at = _timestamp(
            metric.get("observed_at"), "metric_observed_at_missing"
        )
        _require(
            metric_plan_frozen_at <= metric_observed_at,
            "client_metric_plan_not_prefrozen",
        )
        _require(
            rule_frozen_at <= metric_observed_at,
            "client_rule_not_prefrozen",
        )
        _require(
            "vendor" not in str(metric.get("source", "")).lower(),
            "qualified_viral_requires_client_metrics",
        )


def _vendor_observations(card: dict[str, Any]) -> list[dict[str, Any]]:
    _require(card.get("evidence_origin") == "vendor", "vendor_origin_required")
    _require("client_evidence" not in card, "vendor_cannot_carry_client_evidence")
    _require("metrics" not in card, "vendor_cannot_carry_client_metrics")
    rule = _mapping(card.get("vendor_rule"), "vendor_rule_missing")
    _require(rule.get("version") == "v0", "vendor_rule_version_invalid")
    _require(
        isinstance(rule.get("source_batch_rank_max"), int)
        and not isinstance(rule.get("source_batch_rank_max"), bool)
        and 1 <= rule["source_batch_rank_max"] <= 5,
        "vendor_rank_rule_invalid",
    )
    publication = _timestamp(card.get("publication_time"), "vendor_publication_time_missing")
    raw_observations = _items(
        card.get("vendor_observations"), "vendor_observations_must_be_a_list"
    )
    observations: list[dict[str, Any]] = []
    batch_refs: set[str] = set()
    batch_digests: set[str] = set()
    for raw_observation in raw_observations:
        observation = _mapping(raw_observation, "vendor_observation_must_be_an_object")
        observed_at = _timestamp(
            observation.get("observed_at"), "vendor_observed_at_missing"
        )
        _require(observed_at >= publication, "vendor_observation_before_publication")
        rank = observation.get("source_batch_rank")
        _require(
            isinstance(rank, int) and not isinstance(rank, bool) and 1 <= rank <= 5,
            "vendor_source_batch_rank_invalid",
        )
        _require(
            rank <= rule["source_batch_rank_max"],
            "vendor_source_batch_rank_exceeds_rule",
        )
        metrics = _mapping(observation.get("metrics"), "vendor_metrics_missing")
        _require(metrics.get("readNum") is not None, "vendor_read_num_missing")
        _number(metrics.get("readNum"), "vendor_read_num_invalid")
        _require(
            metrics.get("likeNum") is not None or metrics.get("judgeIndex") is not None,
            "vendor_engagement_metric_missing",
        )
        if metrics.get("likeNum") is not None:
            _number(metrics.get("likeNum"), "vendor_like_num_invalid")
        if metrics.get("judgeIndex") is not None:
            _number(metrics.get("judgeIndex"), "vendor_judge_index_invalid")
        source = observation.get("source")
        if source is not None:
            _require(
                "client" not in str(source).lower(),
                "vendor_client_value_mislabelled",
            )
        batch_ref = _text(observation.get("raw_batch_ref"), "vendor_raw_batch_ref_missing")
        batch_digest = _sha256(
            observation.get("raw_batch_sha256"), "vendor_raw_batch_sha256_missing"
        )
        _require(batch_ref not in batch_refs, "vendor_raw_batch_ref_reused")
        _require(batch_digest not in batch_digests, "vendor_raw_batch_sha256_reused")
        batch_refs.add(batch_ref)
        batch_digests.add(batch_digest)
        _require(observation.get("immutable") is True, "vendor_observation_not_immutable")
        _require(observed_at <= publication + timedelta(days=7), "vendor_observation_after_window")
        observations.append(observation)
    observations.sort(key=lambda item: _timestamp(item["observed_at"], "vendor_observed_at_missing"))
    return observations


def _vendor_status(card: dict[str, Any]) -> str:
    try:
        observations = _vendor_observations(card)
    except CaseContractError:
        return "observed_pending"
    publication = _timestamp(card["publication_time"], "vendor_publication_time_missing")
    for index, first_item in enumerate(observations):
        first = _timestamp(first_item["observed_at"], "vendor_observed_at_missing")
        for second_item in observations[index + 1 :]:
            second = _timestamp(second_item["observed_at"], "vendor_observed_at_missing")
            if second - first >= timedelta(hours=24) and second <= publication + timedelta(days=7):
                return "vendor_qualified"
    return "observed_pending"


def _thresholds_met(
    metrics: dict[str, dict[str, Any]],
    minimums: dict[str, float],
    rank_maximums: dict[str, float],
) -> bool:
    for name, minimum in minimums.items():
        metric = metrics.get(name)
        if metric is None or metric.get("status") != "observed":
            return False
        value = metric.get("value")
        if not isinstance(value, Real) or isinstance(value, bool) or value < minimum:
            return False
    for name, maximum in rank_maximums.items():
        metric = metrics.get(name)
        if metric is None or metric.get("status") != "observed":
            return False
        value = metric.get("value")
        if not isinstance(value, Real) or isinstance(value, bool) or value > maximum:
            return False
    return True


def assess_qualification(card: dict[str, Any]) -> str:
    """Return the highest defensible status without inventing missing metrics."""
    _require(card.get("evidence_domain") == RESEARCH_DOMAIN, RESEARCH_DOMAIN)
    _text(card.get("qualification_reason"), "qualification_reason_missing")
    if card.get("evidence_origin") == "vendor":
        return _vendor_status(card)
    planned, metrics = _validate_metric_plan(card)
    minimums, rank_maximums = _validate_rule(card, planned)
    required_visible = {
        name
        for name, item in planned.items()
        if item["visible"] and item["required"]
    }
    observed_required = {
        name
        for name in required_visible
        if name in metrics and metrics[name].get("status") == "observed"
    }
    if not observed_required:
        return "research_only"
    if observed_required != required_visible:
        return "observed_pending"
    if not _thresholds_met(metrics, minimums, rank_maximums):
        return "observed_pending"
    _validate_client_origin(card)
    return "qualified_viral"


def validate_fact_evidence_pack(pack: dict[str, Any]) -> None:
    _require(pack.get("evidence_domain") == FACT_DOMAIN, FACT_DOMAIN)
    _text(pack.get("article_id"), "fact_article_id_missing")
    _require(
        not pack.get("competitive_sample_refs"),
        "fact_evidence_cannot_reference_competitive_samples",
    )
    _require(
        pack.get("qualification_status") is None,
        "fact_evidence_cannot_carry_qualification",
    )
    claims = _items(pack.get("claims"), "fact_claims_must_be_a_list")
    _require(claims, "fact_claims_missing")
    for raw_claim in claims:
        claim = _mapping(raw_claim, "fact_claim_must_be_an_object")
        _text(claim.get("claim_id"), "fact_claim_id_missing")
        _text(claim.get("source_snapshot_ref"), "fact_source_snapshot_ref_missing")
        _text(claim.get("claim_locator"), "fact_claim_locator_missing")


def validate_feedback_record(
    feedback: dict[str, Any],
    *,
    techniques: dict[str, dict[str, Any]] | None = None,
) -> None:
    _require(feedback.get("evidence_domain") == FEEDBACK_DOMAIN, FEEDBACK_DOMAIN)
    _text(feedback.get("article_id"), "feedback_article_id_missing")
    technique_ids = _items(feedback.get("technique_ids"), "feedback_technique_ids_must_be_a_list")
    _require(technique_ids, "feedback_technique_ids_missing")
    _require(
        "qualification_status" not in feedback
        and "proposed_qualification_status" not in feedback,
        "feedback_cannot_change_qualification",
    )
    _require("claims" not in feedback, "feedback_cannot_carry_claims")
    if techniques is not None:
        _require(isinstance(techniques, dict), "feedback_techniques_registry_invalid")
        for raw_technique_id in technique_ids:
            technique_id = _text(raw_technique_id, "feedback_technique_id_invalid")
            technique = techniques.get(technique_id)
            _require(
                technique is not None,
                f"feedback_technique_unresolvable:{technique_id}",
            )
            _require(
                isinstance(technique, dict)
                and bool(
                    _items(
                        technique.get("qualified_sample_refs"),
                        "feedback_technique_refs_invalid",
                    )
                ),
                f"feedback_technique_not_formal:{technique_id}",
            )
    observations = _items(feedback.get("observations"), "feedback_observations_must_be_a_list")
    _require(observations, "feedback_observations_missing")
    for raw_observation in observations:
        observation = _mapping(raw_observation, "feedback_observation_must_be_an_object")
        _text(observation.get("metric"), "feedback_metric_missing")
        _require(observation.get("value") is not None, "feedback_metric_value_missing")
        _text(observation.get("source"), "feedback_metric_source_missing")
        _text(observation.get("observed_at"), "feedback_metric_observed_at_missing")
        _text(observation.get("evidence_ref"), "feedback_metric_evidence_ref_missing")


def validate_case_card(
    card: dict[str, Any],
    *,
    feedback: dict[str, Any] | None = None,
    techniques: dict[str, dict[str, Any]] | None = None,
    warnings: list[dict[str, Any]] | None = None,
) -> str:
    """校验一张卡，返回资格状态。

    warning 级缺陷经 ``warnings`` 收集器上报（可选，默认不上报），
    **不影响返回值、不阻断**：既有调用方的返回类型与语义保持不变。
    """
    if warnings is not None:
        warnings.extend(case_card_warnings(card))
    _text(card.get("sample_id"), "sample_id_missing")
    _text(card.get("snapshot_ref"), "snapshot_ref_missing")
    _text(card.get("performance_evidence_ref"), "performance_evidence_ref_missing")
    status = assess_qualification(card)
    if card.get("evidence_origin") == "vendor":
        _vendor_observations(card)
    declared_status = card.get("qualification_status")
    if declared_status is not None:
        _require(declared_status in QUALIFICATION_STATUSES, "invalid_qualification_status")
        _require(declared_status == status, "qualification_status_mismatch")
    if feedback is not None:
        validate_feedback_record(feedback, techniques=techniques)
    return status


def validate_technique_candidate(
    technique: dict[str, Any], cases: dict[str, dict[str, Any]]
) -> None:
    _require(isinstance(technique, dict), "technique_must_be_an_object")
    _require(isinstance(cases, dict), "cases_must_be_a_mapping")
    _text(technique.get("technique_id"), "technique_id_missing")
    _require(
        technique.get("kind") in {"title", "opening", "structure", "interaction"},
        "invalid_technique_kind",
    )
    refs = _items(technique.get("qualified_sample_refs"), "qualified_sample_refs_must_be_a_list")
    _require(refs, "qualified_sample_refs_missing")
    normalized_refs = [_text(raw_ref, "qualified_sample_ref_invalid") for raw_ref in refs]
    _require(len(normalized_refs) == len(set(normalized_refs)), "duplicate_qualified_sample_ref")
    statuses: list[str] = []
    supports: list[dict[str, Any]] = []
    for ref in normalized_refs:
        _require(ref in cases, f"sample_ref_unresolvable:{ref}")
        status = validate_case_card(cases[ref])
        _require(status in {"qualified_viral", "vendor_qualified"}, "technique_support_not_qualified")
        statuses.append(status)
        supports.append(cases[ref])

    vendor_count = statuses.count("vendor_qualified")
    client_count = statuses.count("qualified_viral")
    if vendor_count or technique.get("evidence_basis") == "mixed_client_vendor":
        _require(
            technique.get("evidence_basis") == "mixed_client_vendor",
            "mixed_evidence_basis_required",
        )
        _require(client_count >= 1, "mixed_requires_qualified_viral")
        _require(vendor_count >= 2, "mixed_requires_two_vendor_qualified")
        _require(
            len({_text(item.get("account_id"), "technique_account_id_missing") for item in supports})
            >= 3,
            "mixed_needs_three_distinct_accounts",
        )
        _require(
            len({_text(item.get("subject_category"), "technique_subject_category_missing") for item in supports})
            >= 3,
            "mixed_needs_three_distinct_subject_categories",
        )
        _require(
            technique.get("verification_state") == "verified",
            "mixed_verification_state_must_be_verified",
        )
        _require(
            technique.get("automatic_publication_authority") is False,
            "mixed_publication_authority_missing",
        )
    else:
        _require(
            technique.get("automatic_publication_authority") is False,
            "client_only_publication_authority_must_be_false",
        )