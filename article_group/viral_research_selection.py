from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class SelectionCriteria:
    platform: str
    medium: str
    content_domain: str
    narrative_purpose: str
    account_type: str | None = None
    topic: str | None = None
    work_relation: str | None = None

    def as_shape(self) -> dict[str, str]:
        values = {
            "platform": self.platform,
            "medium": self.medium,
            "content_domain": self.content_domain,
            "narrative_purpose": self.narrative_purpose,
            "account_type": self.account_type,
            "topic": self.topic,
            "work_relation": self.work_relation,
        }
        return {key: value for key, value in values.items() if value is not None}


def _criteria_mapping(criteria: Mapping[str, Any] | SelectionCriteria) -> Mapping[str, Any]:
    if isinstance(criteria, SelectionCriteria):
        return criteria.as_shape()
    return criteria


MIN_QUALIFIED_SAMPLES = 5
MIN_DISTINCT_ACCOUNTS = 2
QUALIFIED_LANES = frozenset({"wechat", "wechat_long_form", "wechat_qualified"})
SHAPE_FIELDS = (
    "platform",
    "medium",
    "content_domain",
    "account_type",
    "narrative_purpose",
    "topic",
    "work_relation",
)


class ViralResearchSelectionError(ValueError):
    """Raised when an explicit research selection request is invalid."""


@dataclass(frozen=True)
class SelectionResult:
    selected: tuple[dict[str, Any], ...]
    pending: tuple[dict[str, Any], ...]
    excluded: tuple[dict[str, Any], ...]
    reason: str | None
    min_samples: int
    min_accounts: int

    @property
    def ready(self) -> bool:
        accounts = {str(item.get("account_id")) for item in self.selected}
        return len(self.selected) >= self.min_samples and len(accounts) >= self.min_accounts

    def as_dict(self) -> dict[str, Any]:
        return {
            "selected": [dict(item) for item in self.selected],
            "pending": [dict(item) for item in self.pending],
            "excluded": [dict(item) for item in self.excluded],
            "reason": self.reason,
            "ready": self.ready,
            "min_samples": self.min_samples,
            "min_accounts": self.min_accounts,
        }


def _text(value: Any) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def _shape_value(sample: Mapping[str, Any], field: str) -> str:
    shape = sample.get("shape")
    if not isinstance(shape, Mapping):
        shape = {}
    if field == "platform":
        return _text(sample.get("platform"))
    return _text(shape.get(field))


def shape_matches(
    sample: Mapping[str, Any],
    target_shape: Mapping[str, Any] | SelectionCriteria,
) -> bool:
    """Return true when every specified shape dimension matches exactly."""
    target_shape = _criteria_mapping(target_shape)
    if not isinstance(target_shape, Mapping):
        raise ViralResearchSelectionError("target_shape_invalid")
    for field in SHAPE_FIELDS:
        target = _text(target_shape.get(field))
        if target and _shape_value(sample, field) != target:
            return False
    return True


def _qualified(sample: Mapping[str, Any]) -> bool:
    return (
        sample.get("qualification_status") == "qualified_viral"
        and _text(sample.get("platform")) in QUALIFIED_LANES
    )


def _sort_cross_account(samples: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(sample) for sample in samples]
    rows.sort(
        key=lambda sample: (
            _text(sample.get("account_id")),
            _text(sample.get("sample_id")),
        )
    )
    first_by_account: list[dict[str, Any]] = []
    remainder: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sample in rows:
        account = _text(sample.get("account_id"))
        if account not in seen:
            first_by_account.append(sample)
            seen.add(account)
        else:
            remainder.append(sample)
    return first_by_account + remainder


def _evidence_cluster_key(sample: Mapping[str, Any]) -> str:
    declared = sample.get("evidence_cluster")
    if isinstance(declared, str) and declared.strip():
        return declared.strip()
    digests: list[str] = []
    for field in ("raw_ref", "clean_ref", "metadata_ref"):
        reference = sample.get(field)
        if not isinstance(reference, str) or "#sha256=" not in reference:
            return ""
        digest = reference.rsplit("#sha256=", 1)[1].strip().lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            return ""
        digests.append(digest)
    return "|".join(digests)


def select_shape_matched_samples(
    samples: Iterable[Mapping[str, Any]],
    *,
    target_shape: Mapping[str, Any] | SelectionCriteria,
    min_samples: int = MIN_QUALIFIED_SAMPLES,
    min_accounts: int = MIN_DISTINCT_ACCOUNTS,
) -> SelectionResult:
    """Select an explicit, cross-account, shape-matched qualified batch."""
    if min_samples < 1 or min_accounts < 1:
        raise ViralResearchSelectionError("minimum_invalid")
    target_shape = _criteria_mapping(target_shape)
    selected_candidates: list[Mapping[str, Any]] = []
    pending: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for sample in samples:
        if not isinstance(sample, Mapping):
            excluded.append({"exclusion_reason": "sample_invalid"})
            continue
        if not _qualified(sample):
            status = sample.get("qualification_status")
            if status in {"observed_pending", "research_only"}:
                pending.append(dict(sample))
            else:
                excluded.append({**dict(sample), "exclusion_reason": "not_qualified"})
            continue
        if not shape_matches(sample, target_shape):
            excluded.append({**dict(sample), "exclusion_reason": "shape_mismatch"})
            continue
        selected_candidates.append(sample)
    ordered_candidates = _sort_cross_account(selected_candidates)
    selected_by_id: dict[str, dict[str, Any]] = {}
    selected_without_id: list[dict[str, Any]] = []

    def _revision_key(sample: Mapping[str, Any]) -> tuple[int, Decimal, str]:
        """Return a deterministic ordering for numeric and named revisions."""
        for field in ("revision", "capture_revision", "revision_id"):
            value = sample.get(field)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                try:
                    return (2, Decimal(str(value)), str(value))
                except InvalidOperation:
                    continue
            elif isinstance(value, str):
                marker = value.strip()
                if not marker:
                    continue
                try:
                    return (2, Decimal(marker), marker)
                except InvalidOperation:
                    return (1, Decimal(0), marker)
        return (0, Decimal(0), "")

    for sample in ordered_candidates:
        sample_id = sample.get("sample_id")
        if sample_id in (None, ""):
            selected_without_id.append(sample)
            continue
        key = str(sample_id)
        current = selected_by_id.get(key)
        if current is None:
            selected_by_id[key] = sample
            continue
        if _revision_key(sample) > _revision_key(current):
            selected_by_id[key] = sample

    ordered = _sort_cross_account([*selected_by_id.values(), *selected_without_id])
    unique: list[dict[str, Any]] = []
    seen_clusters: set[str] = set()
    for sample in ordered:
        cluster = _evidence_cluster_key(sample)
        if cluster and cluster in seen_clusters:
            excluded.append({**dict(sample), "exclusion_reason": "duplicate_evidence_cluster"})
            continue
        if cluster:
            seen_clusters.add(cluster)
        unique.append(sample)
    ordered = unique
    selected = tuple(ordered)
    account_count = len({_text(item.get("account_id")) for item in selected})
    if len(selected) < min_samples:
        reason = "insufficient_qualified_samples"
    elif account_count < min_accounts:
        reason = "insufficient_distinct_accounts"
    else:
        reason = None
    return SelectionResult(
        selected=selected,
        pending=tuple(pending),
        excluded=tuple(excluded),
        reason=reason,
        min_samples=min_samples,
        min_accounts=min_accounts,
    )


def select_samples(
    samples: Iterable[Mapping[str, Any]],
    *,
    target_shape: Mapping[str, Any],
    min_samples: int = MIN_QUALIFIED_SAMPLES,
    min_accounts: int = MIN_DISTINCT_ACCOUNTS,
) -> SelectionResult:
    """Compatibility alias for the explicit shape-matched selector."""
    return select_shape_matched_samples(
        samples,
        target_shape=target_shape,
        min_samples=min_samples,
        min_accounts=min_accounts,
    )
