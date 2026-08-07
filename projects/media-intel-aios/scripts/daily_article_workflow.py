#!/usr/bin/env python3
"""Opt-in data contracts and deadlines for the daily article workflow.

This module deliberately performs no fetching, generation, rendering, scheduling,
delivery, or publication. Callers opt in by importing and constructing its objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from typing import Any, ClassVar, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class WorkflowState(StrEnum):
    S0_COLLECTION = "S0_COLLECTION"
    S1_CANDIDATE_POOL = "S1_CANDIDATE_POOL"
    S2_VERIFICATION = "S2_VERIFICATION"
    S3_PROGRAMMING = "S3_PROGRAMMING"
    S4_PRODUCTION = "S4_PRODUCTION"
    S5_QUALITY_CHECK = "S5_QUALITY_CHECK"
    S6_DELIVERY = "S6_DELIVERY"
    F1_ALTERNATE = "F1_ALTERNATE"
    F2_PARTIAL_DELIVERY = "F2_PARTIAL_DELIVERY"
    F3_ALERT = "F3_ALERT"
    DONE = "DONE"


class ReasonCode(StrEnum):
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    SOURCE_PERMISSION_DENIED = "SOURCE_PERMISSION_DENIED"
    DEADLINE_MISSED = "DEADLINE_MISSED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    TEMPLATE_BLOCKED = "TEMPLATE_BLOCKED"


_STATE_SEQUENCE = (
    WorkflowState.S0_COLLECTION,
    WorkflowState.S1_CANDIDATE_POOL,
    WorkflowState.S2_VERIFICATION,
    WorkflowState.S3_PROGRAMMING,
    WorkflowState.S4_PRODUCTION,
    WorkflowState.S5_QUALITY_CHECK,
    WorkflowState.S6_DELIVERY,
    WorkflowState.DONE,
)
_ALLOWED_TRANSITIONS = {
    current: {_STATE_SEQUENCE[index + 1], WorkflowState.F1_ALTERNATE, WorkflowState.F2_PARTIAL_DELIVERY, WorkflowState.F3_ALERT}
    for index, current in enumerate(_STATE_SEQUENCE[:-1])
}
_ALLOWED_TRANSITIONS[WorkflowState.F1_ALTERNATE] = {WorkflowState.S3_PROGRAMMING, WorkflowState.F2_PARTIAL_DELIVERY, WorkflowState.F3_ALERT}
_ALLOWED_TRANSITIONS[WorkflowState.F2_PARTIAL_DELIVERY] = {WorkflowState.S6_DELIVERY, WorkflowState.F3_ALERT}
_ALLOWED_TRANSITIONS[WorkflowState.F3_ALERT] = {WorkflowState.S6_DELIVERY, WorkflowState.F2_PARTIAL_DELIVERY}
_ALLOWED_TRANSITIONS[WorkflowState.S6_DELIVERY].add(WorkflowState.DONE)
_F1_SOURCES = {WorkflowState.S3_PROGRAMMING, WorkflowState.S4_PRODUCTION, WorkflowState.S5_QUALITY_CHECK}
_F2_SOURCES = {WorkflowState.S2_VERIFICATION, WorkflowState.S4_PRODUCTION, WorkflowState.S5_QUALITY_CHECK, WorkflowState.F1_ALTERNATE}
_F3_SOURCES = set(_ALLOWED_TRANSITIONS) - {WorkflowState.S6_DELIVERY}
_FALLBACK_REASONS = frozenset({
    ReasonCode.EVIDENCE_CONFLICT,
    ReasonCode.MISSING_REQUIRED_FIELD,
    ReasonCode.SOURCE_PERMISSION_DENIED,
    ReasonCode.INSUFFICIENT_EVIDENCE,
    ReasonCode.TEMPLATE_BLOCKED,
})


def _require_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")


def _require_aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _datetime_from_value(name: str, value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    _require_aware(name, parsed)
    return parsed


def _frozen_dict(value: Mapping[str, Any], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    return dict(value)


@dataclass(frozen=True)
class Candidate:
    id: str
    scan_hour: datetime
    topic_key: str
    angle_key: str
    headline: str
    claim: str
    entity: str
    event_time: datetime
    first_seen_at: datetime
    source_url: str
    source_role: str
    publisher: str
    author_or_org: str
    published_at: datetime
    evidence_quote: str
    locator: str
    independence_group: str
    risk_tags: tuple[str, ...]
    denial_status: str
    strength: str
    state: str
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("id", "topic_key", "angle_key", "headline", "claim", "entity", "source_url", "source_role", "publisher", "author_or_org", "evidence_quote", "locator", "independence_group", "denial_status", "strength", "state"):
            _require_text(name, getattr(self, name))
        for name in ("scan_hour", "event_time", "first_seen_at", "published_at"):
            _require_aware(name, getattr(self, name))
        if not isinstance(self.risk_tags, tuple) or any(not isinstance(tag, str) or not tag.strip() for tag in self.risk_tags):
            raise ValueError("risk_tags must be a tuple of non-empty strings")
        if not isinstance(self.reason_codes, tuple) or any(not isinstance(code, str) or not code.strip() for code in self.reason_codes):
            raise ValueError("reason_codes must be a tuple of non-empty strings")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "scan_hour": self.scan_hour.isoformat(), "topic_key": self.topic_key, "angle_key": self.angle_key,
            "headline": self.headline, "claim": self.claim, "entity": self.entity, "event_time": self.event_time.isoformat(),
            "first_seen_at": self.first_seen_at.isoformat(), "source_url": self.source_url, "source_role": self.source_role,
            "publisher": self.publisher, "author_or_org": self.author_or_org, "published_at": self.published_at.isoformat(),
            "evidence_quote": self.evidence_quote, "locator": self.locator, "independence_group": self.independence_group,
            "risk_tags": list(self.risk_tags), "denial_status": self.denial_status, "strength": self.strength,
            "state": self.state, "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Candidate":
        raw = _frozen_dict(value, "candidate")
        for name in ("scan_hour", "event_time", "first_seen_at", "published_at"):
            raw[name] = _datetime_from_value(name, raw[name])
        raw["risk_tags"] = tuple(raw["risk_tags"])
        raw["reason_codes"] = tuple(raw["reason_codes"])
        return cls(**raw)


@dataclass(frozen=True)
class EvidencePack:
    id: str
    candidate_id: str
    captured_at: datetime
    source_snapshots: tuple[dict[str, Any], ...]
    access_status: str
    claim_mappings: tuple[dict[str, Any], ...]

    def __post_init__(self) -> None:
        _require_text("id", self.id)
        _require_text("candidate_id", self.candidate_id)
        _require_aware("captured_at", self.captured_at)
        _require_text("access_status", self.access_status)
        if not self.source_snapshots:
            raise ValueError("EvidencePack requires at least one source snapshot")
        if not self.claim_mappings:
            raise ValueError("EvidencePack requires at least one claim mapping")
        for snapshot in self.source_snapshots:
            for key in ("source_id", "url", "quote"):
                _require_text(f"source snapshot {key}", snapshot.get(key, ""))
        for mapping in self.claim_mappings:
            for key in ("claim_id", "source_id", "locator"):
                _require_text(f"claim mapping {key}", mapping.get(key, ""))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "candidate_id": self.candidate_id, "captured_at": self.captured_at.isoformat(), "source_snapshots": list(self.source_snapshots), "access_status": self.access_status, "claim_mappings": list(self.claim_mappings)}


@dataclass(frozen=True)
class Slot:
    slot_type: str
    primary: Candidate | None
    alternates: tuple[Candidate, ...]
    unfilled: bool = False

    def __post_init__(self) -> None:
        if self.slot_type not in {"A", "B", "C"}:
            raise ValueError("slot_type must be A, B, or C")
        if self.unfilled:
            if self.primary is not None or self.alternates:
                raise ValueError("unfilled Slot must not contain a primary or alternates")
            return
        if not isinstance(self.primary, Candidate):
            raise ValueError("filled Slot requires a Candidate primary")
        if len(self.alternates) != 2 or len({alternate.id for alternate in self.alternates}) != 2:
            raise ValueError("filled Slot requires exactly two distinct eligible alternates")
        if any(not isinstance(alternate, Candidate) or alternate.id == self.primary.id for alternate in self.alternates):
            raise ValueError("filled Slot requires exactly two distinct eligible alternates")
        eligible_roles = {"confirmed_primary", "confirmed_named_secondary", "confirmed_secondary"}
        if self.primary.source_role not in eligible_roles or any(alternate.source_role not in eligible_roles for alternate in self.alternates):
            raise ValueError("Slot primary and alternates must have eligible confirmed roles")

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_type": self.slot_type,
            "primary_id": self.primary.id if self.primary else None,
            "alternate_ids": [candidate.id for candidate in self.alternates],
            "unfilled": self.unfilled,
        }


@dataclass(frozen=True)
class ArticleBundle:
    slot: Slot
    evidence_pack: EvidencePack
    body_markdown: str
    html: str | None
    manifest: dict[str, Any]
    audit: tuple[dict[str, Any], ...]

    def __post_init__(self) -> None:
        if self.slot.primary is None:
            raise ValueError("ArticleBundle requires a filled Slot")
        if self.evidence_pack.candidate_id != self.slot.primary.id:
            raise ValueError("EvidencePack candidate_id must match slot primary")
        _require_text("body_markdown", self.body_markdown)
        if self.html is not None and not isinstance(self.html, str):
            raise ValueError("html must be a string or None")
        manifest = _frozen_dict(self.manifest, "manifest")
        for field in (
            "status", "input_versions_or_hashes", "claim_mappings", "word_count", "gates",
            "template", "sanitization", "compatibility", "artifact_hashes", "failure_codes",
            "retries_or_replacements", "receipts", "alerts",
        ):
            if field not in manifest:
                raise ValueError(f"manifest missing required field: {field}")
        if not isinstance(self.audit, tuple) or any(not isinstance(event, dict) for event in self.audit):
            raise ValueError("audit must be a tuple of mappings")
        for event in self.audit:
            _require_text("audit event", event.get("event", ""))
            _require_text("audit event at", event.get("at", ""))

    def to_dict(self) -> dict[str, Any]:
        return {"slot": self.slot.to_dict(), "evidence_pack_id": self.evidence_pack.id, "body_markdown": self.body_markdown, "html": self.html, "manifest": dict(self.manifest), "audit": list(self.audit)}


@dataclass(frozen=True)
class SendReceipt:
    slot_type: str
    message_id: str
    is_final: bool

    def __post_init__(self) -> None:
        if self.slot_type not in {"A", "B", "C"}:
            raise ValueError("send receipt slot_type must be A, B, or C")
        _require_text("send receipt message_id", self.message_id)
        if not isinstance(self.is_final, bool):
            raise ValueError("send receipt is_final must be a bool")


@dataclass(frozen=True)
class WorkflowTransition:
    from_state: WorkflowState
    to_state: WorkflowState
    at: datetime
    reason_codes: tuple[str, ...]
    send_receipts: tuple[SendReceipt, ...] = ()

    def __post_init__(self) -> None:
        _require_aware("at", self.at)
        if self.to_state not in _ALLOWED_TRANSITIONS.get(self.from_state, set()):
            raise ValueError(f"transition from {self.from_state} to {self.to_state} is not allowed")
        if not isinstance(self.reason_codes, tuple) or any(not isinstance(code, str) or not code.strip() for code in self.reason_codes):
            raise ValueError("reason_codes must be a tuple of non-empty strings")
        reasons = frozenset(self.reason_codes)
        if self.to_state == WorkflowState.F1_ALTERNATE:
            if self.from_state not in _F1_SOURCES or not reasons.intersection(_FALLBACK_REASONS):
                raise ValueError("F1_ALTERNATE requires a production-or-quality source and failure reason")
        if self.to_state == WorkflowState.F2_PARTIAL_DELIVERY:
            f2_reasons = {
                ReasonCode.INSUFFICIENT_EVIDENCE,
                ReasonCode.MISSING_REQUIRED_FIELD,
                ReasonCode.SOURCE_PERMISSION_DENIED,
                ReasonCode.TEMPLATE_BLOCKED,
            }
            if self.from_state not in _F2_SOURCES or not reasons.intersection(f2_reasons):
                raise ValueError("F2_PARTIAL_DELIVERY requires an explicit failed or INSUFFICIENT_EVIDENCE outcome")
        if self.to_state == WorkflowState.F3_ALERT:
            if self.from_state not in _F3_SOURCES or ReasonCode.DEADLINE_MISSED not in reasons:
                raise ValueError("F3_ALERT requires an eligible source and DEADLINE_MISSED")
        if self.to_state == WorkflowState.DONE:
            if (
                not isinstance(self.send_receipts, tuple)
                or any(not isinstance(receipt, SendReceipt) for receipt in self.send_receipts)
                or len(self.send_receipts) != 3
                or {receipt.slot_type for receipt in self.send_receipts} != {"A", "B", "C"}
            ):
                raise ValueError("DONE requires exactly three send receipts for slots A, B, and C")
        elif self.send_receipts:
            raise ValueError("send receipts are only permitted on DONE transitions")

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "at": self.at.isoformat(),
            "reason_codes": list(self.reason_codes),
            "send_receipts": [
                {"slot_type": receipt.slot_type, "message_id": receipt.message_id, "is_final": receipt.is_final}
                for receipt in self.send_receipts
            ],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkflowTransition":
        raw = _frozen_dict(value, "transition")
        raw["from_state"] = WorkflowState(raw["from_state"])
        raw["to_state"] = WorkflowState(raw["to_state"])
        raw["at"] = _datetime_from_value("at", raw["at"])
        raw["reason_codes"] = tuple(raw["reason_codes"])
        raw["send_receipts"] = tuple(SendReceipt(**receipt) for receipt in raw.get("send_receipts", ()))
        return cls(**raw)


@dataclass(frozen=True)
class DailyClock:
    timezone_name: str
    day: str | date

    DEADLINES: ClassVar[dict[str, tuple[int, int, WorkflowState]]] = {
        "candidate_pool": (10, 30, WorkflowState.S1_CANDIDATE_POOL),
        "verification": (11, 30, WorkflowState.S2_VERIFICATION),
        "programming": (12, 0, WorkflowState.S3_PROGRAMMING),
        "drafts": (14, 0, WorkflowState.S4_PRODUCTION),
        "quality_check": (15, 0, WorkflowState.S5_QUALITY_CHECK),
        "freeze": (15, 30, WorkflowState.S5_QUALITY_CHECK),
        "delivery": (16, 0, WorkflowState.S6_DELIVERY),
    }

    def __post_init__(self) -> None:
        _require_text("timezone_name", self.timezone_name)
        try:
            ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"unknown timezone: {self.timezone_name}") from error
        if isinstance(self.day, str):
            try:
                date.fromisoformat(self.day)
            except ValueError as error:
                raise ValueError("day must be an ISO date") from error
        elif type(self.day) is not date:
            raise ValueError("day must be an ISO date or date")

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    @property
    def local_day(self) -> date:
        return date.fromisoformat(self.day) if isinstance(self.day, str) else self.day

    def deadline(self, name: str) -> datetime:
        try:
            hour, minute, _ = self.DEADLINES[name]
        except KeyError as error:
            raise ValueError(f"unknown deadline: {name}") from error
        return datetime.combine(self.local_day, time(hour, minute), tzinfo=self.timezone)

    def phase_at(self, moment: datetime) -> WorkflowState:
        _require_aware("moment", moment)
        local_moment = moment.astimezone(self.timezone)
        if local_moment.date() != self.local_day:
            raise ValueError("moment must fall on DailyClock day in its explicit timezone")
        phase = WorkflowState.S0_COLLECTION
        for name in self.DEADLINES:
            deadline = self.deadline(name)
            if local_moment >= deadline:
                phase = self.DEADLINES[name][2]
            else:
                break
        return phase

    def event_at(self, moment: datetime) -> str | None:
        """Return the most recent deadline event; freeze remains an event, not F2."""
        _require_aware("moment", moment)
        local_moment = moment.astimezone(self.timezone)
        if local_moment.date() != self.local_day:
            raise ValueError("moment must fall on DailyClock day in its explicit timezone")
        events = [name for name in self.DEADLINES if local_moment >= self.deadline(name)]
        return events[-1] if events else None
