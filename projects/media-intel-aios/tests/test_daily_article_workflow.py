import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "scripts" / "daily_article_workflow.py"
UTC = timezone.utc


def load_module():
    spec = importlib.util.spec_from_file_location("daily_article_workflow", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def candidate_kwargs():
    return {
        "id": "cand-001",
        "scan_hour": datetime(2026, 7, 16, 10, tzinfo=UTC),
        "topic_key": "film:example:event",
        "angle_key": "film:example:market-angle",
        "headline": "示例标题",
        "claim": "可定位的示例主张",
        "entity": "示例影视作品",
        "event_time": datetime(2026, 7, 16, 9, tzinfo=UTC),
        "first_seen_at": datetime(2026, 7, 16, 10, tzinfo=UTC),
        "source_url": "https://example.test/source",
        "source_role": "confirmed_primary",
        "publisher": "示例机构",
        "author_or_org": "示例记者",
        "published_at": datetime(2026, 7, 16, 9, tzinfo=UTC),
        "evidence_quote": "可核验摘录",
        "locator": "article > p:nth-of-type(2)",
        "independence_group": "example-newsroom",
        "risk_tags": ("rumor",),
        "denial_status": "none",
        "strength": "strong",
        "state": "S2_VERIFICATION",
        "reason_codes": ("EVIDENCE_CONFLICT",),
    }


def make_candidate(module):
    return module.Candidate(**candidate_kwargs())


def make_alternate(module, candidate_id):
    values = candidate_kwargs()
    values.update({
        "id": candidate_id,
        "topic_key": f"topic:{candidate_id}",
        "angle_key": f"angle:{candidate_id}",
        "source_url": f"https://example.test/{candidate_id}",
    })
    return module.Candidate(**values)


def make_evidence(mod, candidate):
    return mod.EvidencePack(
        id="evidence-001",
        candidate_id=candidate.id,
        captured_at=datetime(2026, 7, 16, 10, tzinfo=UTC),
        source_snapshots=({"source_id": "source-001", "url": candidate.source_url, "quote": candidate.evidence_quote},),
        access_status="permitted",
        claim_mappings=({"claim_id": "claim-001", "source_id": "source-001", "locator": candidate.locator},),
    )


def valid_manifest():
    return {
        "status": "draft",
        "input_versions_or_hashes": {"candidates": "sha256:input"},
        "claim_mappings": [{"claim_id": "claim-001"}],
        "word_count": 2,
        "gates": {"evidence": "pass"},
        "template": {"path": "templates/graphite.html", "version": "1", "hash": "sha256:template"},
        "sanitization": {"status": "pass"},
        "compatibility": {"status": "pass"},
        "artifact_hashes": {"article.md": "sha256:article"},
        "failure_codes": [],
        "retries_or_replacements": [],
        "receipts": [],
        "alerts": [],
    }


def valid_audit():
    return ({"event": "created", "at": "2026-07-16T10:00:00+00:00"},)


def test_candidate_round_trip_preserves_required_contract_and_reason_codes():
    mod = load_module()
    candidate = make_candidate(mod)

    restored = mod.Candidate.from_dict(json.loads(json.dumps(candidate.to_dict())))

    assert restored == candidate
    assert restored.reason_codes == (mod.ReasonCode.EVIDENCE_CONFLICT.value,)
    assert restored.scan_hour.tzinfo is not None


def test_candidate_fails_closed_for_missing_required_or_naive_time():
    mod = load_module()
    missing_claim = candidate_kwargs()
    missing_claim.pop("claim")
    naive_time = candidate_kwargs()
    naive_time["published_at"] = datetime(2026, 7, 16, 9)

    with pytest.raises(TypeError):
        mod.Candidate(**missing_claim)
    with pytest.raises(ValueError, match="published_at.*timezone-aware"):
        mod.Candidate(**naive_time)


def test_evidence_slot_and_bundle_require_complete_references():
    mod = load_module()
    candidate = make_candidate(mod)
    evidence = make_evidence(mod, candidate)
    alternate_one = make_alternate(mod, "cand-002")
    alternate_two = make_alternate(mod, "cand-003")
    slot = mod.Slot(slot_type="A", primary=candidate, alternates=(alternate_one, alternate_two))
    bundle = mod.ArticleBundle(
        slot=slot,
        evidence_pack=evidence,
        body_markdown="# 示例\n正文",
        html=None,
        manifest=valid_manifest(),
        audit=valid_audit(),
    )

    assert bundle.to_dict()["evidence_pack_id"] == "evidence-001"
    with pytest.raises(ValueError, match="at least one source snapshot"):
        mod.EvidencePack(
            id="evidence-empty", candidate_id=candidate.id,
            captured_at=datetime(2026, 7, 16, 10, tzinfo=UTC), source_snapshots=(),
            access_status="permitted", claim_mappings=({"claim_id": "c", "source_id": "s", "locator": "p"},),
        )
    with pytest.raises(ValueError, match="exactly two distinct eligible alternates"):
        mod.Slot(slot_type="A", primary=candidate, alternates=(candidate, candidate, candidate))
    with pytest.raises(ValueError, match="slot primary"):
        mod.ArticleBundle(slot=slot, evidence_pack=mod.EvidencePack(
            id="wrong-evidence", candidate_id="other-candidate",
            captured_at=datetime(2026, 7, 16, 10, tzinfo=UTC),
            source_snapshots=({"source_id": "s", "url": "https://example.test", "quote": "q"},),
            access_status="permitted", claim_mappings=({"claim_id": "c", "source_id": "s", "locator": "p"},),
        ), body_markdown="# 示例", html=None, manifest=valid_manifest(), audit=valid_audit())


def test_slot_requires_two_distinct_eligible_alternates_or_an_explicit_unfilled_slot():
    mod = load_module()
    primary = make_candidate(mod)
    alternate = make_alternate(mod, "cand-002")

    with pytest.raises(ValueError, match="exactly two distinct eligible alternates"):
        mod.Slot(slot_type="A", primary=primary, alternates=(alternate,))
    with pytest.raises(ValueError, match="exactly two distinct eligible alternates"):
        mod.Slot(slot_type="A", primary=primary, alternates=(alternate, alternate))

    unfilled = mod.Slot(slot_type="B", primary=None, alternates=(), unfilled=True)

    assert unfilled.unfilled is True


def test_daily_clock_uses_explicit_timezone_and_deadline_transitions():
    mod = load_module()
    clock = mod.DailyClock("Asia/Shanghai", day="2026-07-16")

    assert clock.deadline("candidate_pool").isoformat() == "2026-07-16T10:30:00+08:00"
    assert clock.phase_at(datetime(2026, 7, 16, 3, 30, tzinfo=UTC)) == mod.WorkflowState.S2_VERIFICATION
    assert clock.phase_at(datetime(2026, 7, 16, 7, 31, tzinfo=UTC)) == mod.WorkflowState.S5_QUALITY_CHECK
    assert clock.event_at(datetime(2026, 7, 16, 7, 31, tzinfo=UTC)) == "freeze"
    with pytest.raises(ValueError, match="timezone-aware"):
        clock.phase_at(datetime(2026, 7, 16, 10, 30))
    with pytest.raises(ValueError, match="day must be an ISO date or date"):
        mod.DailyClock("Asia/Shanghai", day=20260716)


def test_fallback_transitions_require_source_and_trigger_reason_invariants():
    mod = load_module()
    with pytest.raises(ValueError, match="F1_ALTERNATE"):
        mod.WorkflowTransition(
            from_state=mod.WorkflowState.S2_VERIFICATION,
            to_state=mod.WorkflowState.F1_ALTERNATE,
            at=datetime(2026, 7, 16, 14, tzinfo=UTC),
            reason_codes=(mod.ReasonCode.MISSING_REQUIRED_FIELD,),
        )
    with pytest.raises(ValueError, match="INSUFFICIENT_EVIDENCE"):
        mod.WorkflowTransition(
            from_state=mod.WorkflowState.S2_VERIFICATION,
            to_state=mod.WorkflowState.F2_PARTIAL_DELIVERY,
            at=datetime(2026, 7, 16, 15, 30, tzinfo=UTC),
            reason_codes=(mod.ReasonCode.EVIDENCE_CONFLICT,),
        )
    with pytest.raises(ValueError, match="DEADLINE_MISSED"):
        mod.WorkflowTransition(
            from_state=mod.WorkflowState.S0_COLLECTION,
            to_state=mod.WorkflowState.F3_ALERT,
            at=datetime(2026, 7, 16, 16, tzinfo=UTC),
            reason_codes=(),
        )


def test_valid_fallback_transitions_retain_required_reason_codes():
    mod = load_module()

    f1 = mod.WorkflowTransition(
        mod.WorkflowState.S4_PRODUCTION,
        mod.WorkflowState.F1_ALTERNATE,
        datetime(2026, 7, 16, 14, tzinfo=UTC),
        (mod.ReasonCode.MISSING_REQUIRED_FIELD,),
    )
    f2 = mod.WorkflowTransition(
        mod.WorkflowState.F1_ALTERNATE,
        mod.WorkflowState.F2_PARTIAL_DELIVERY,
        datetime(2026, 7, 16, 15, 30, tzinfo=UTC),
        (mod.ReasonCode.INSUFFICIENT_EVIDENCE,),
    )
    f3 = mod.WorkflowTransition(
        mod.WorkflowState.S5_QUALITY_CHECK,
        mod.WorkflowState.F3_ALERT,
        datetime(2026, 7, 16, 16, tzinfo=UTC),
        (mod.ReasonCode.DEADLINE_MISSED,),
    )

    assert mod.WorkflowTransition.from_dict(f1.to_dict()) == f1
    assert mod.WorkflowTransition.from_dict(f2.to_dict()) == f2
    assert mod.WorkflowTransition.from_dict(f3.to_dict()) == f3


def test_done_requires_exactly_three_slot_receipts_but_placeholders_are_not_final():
    mod = load_module()
    receipts = (
        mod.SendReceipt("A", "message-a", is_final=True),
        mod.SendReceipt("B", "message-b", is_final=False),
        mod.SendReceipt("C", "message-c", is_final=True),
    )
    transition = mod.WorkflowTransition(
        from_state=mod.WorkflowState.S6_DELIVERY,
        to_state=mod.WorkflowState.DONE,
        at=datetime(2026, 7, 16, 16, tzinfo=UTC),
        reason_codes=(),
        send_receipts=receipts,
    )

    assert len(transition.send_receipts) == 3
    assert transition.send_receipts[1].is_final is False
    with pytest.raises(ValueError, match="exactly three send receipts"):
        mod.WorkflowTransition(
            from_state=mod.WorkflowState.S6_DELIVERY,
            to_state=mod.WorkflowState.DONE,
            at=datetime(2026, 7, 16, 16, tzinfo=UTC),
            reason_codes=(),
            send_receipts=receipts[:2],
        )


def test_article_bundle_requires_minimal_auditable_manifest_and_audit_fields():
    mod = load_module()
    primary = make_candidate(mod)
    slot = mod.Slot(
        slot_type="A",
        primary=primary,
        alternates=(make_alternate(mod, "cand-002"), make_alternate(mod, "cand-003")),
    )

    invalid_manifest = valid_manifest()
    invalid_manifest.pop("artifact_hashes")
    with pytest.raises(ValueError, match="manifest missing required field: artifact_hashes"):
        mod.ArticleBundle(slot, make_evidence(mod, primary), "# 示例", None, invalid_manifest, valid_audit())
    with pytest.raises(ValueError, match="audit event at is required"):
        mod.ArticleBundle(slot, make_evidence(mod, primary), "# 示例", None, valid_manifest(), ({"event": "created"},))
