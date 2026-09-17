from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json


def _fact_card() -> dict:
    return {
        "article_id": "art-001",
        "data_as_of": "2026-08-25T08:00:00+08:00",
        "update_required_before_publication": "yes",
        "permitted_claims": [{"claim_id": "F1", "claim": "价格为218元"}],
    }


def test_revalidation_passes_only_with_fresh_snapshot_and_exact_claim_coverage(tmp_path):
    assert importlib.util.find_spec("article_group.revalidation") is not None
    from article_group.revalidation import validate_revalidation_record

    snapshot = tmp_path / "sources" / "current.html"
    snapshot.parent.mkdir()
    snapshot.write_text("当前价格为218元，发布前核验。", encoding="utf-8")
    record = {
        "schema_version": "revalidation-v1",
        "article_id": "art-001",
        "checked_at": "2026-08-25T10:00:00+08:00",
        "decision": "pass",
        "claims": [
            {
                "claim_id": "F1",
                "status": "confirmed",
                "max_age_hours": 24,
                "source_snapshot": {
                    "path": "sources/current.html",
                    "sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                    "locator": "价格为218元",
                },
            }
        ],
    }
    assert validate_revalidation_record(
        _fact_card(), record, tmp_path, now=datetime(2026, 8, 25, 11, tzinfo=timezone.utc)
    ) == []


def test_revalidation_blocks_stale_or_incomplete_dynamic_claims(tmp_path):
    from article_group.revalidation import validate_revalidation_record

    snapshot = tmp_path / "current.html"
    snapshot.write_text("当前价格为218元。", encoding="utf-8")
    record = {
        "schema_version": "revalidation-v1",
        "article_id": "art-001",
        "checked_at": "2026-08-25T08:30:00+08:00",
        "decision": "pass",
        "claims": [],
    }
    errors = validate_revalidation_record(
        _fact_card(), record, tmp_path, now=datetime(2026, 8, 25, 11, tzinfo=timezone.utc)
    )
    assert "revalidation_claim_coverage_mismatch" in errors
    assert "revalidation_claims_missing_snapshot:F1" in errors


def test_revalidation_is_not_required_for_static_fact_card(tmp_path):
    from article_group.revalidation import validate_revalidation_record

    fact = _fact_card()
    fact["update_required_before_publication"] = "no"
    assert validate_revalidation_record(fact, None, tmp_path) == []
