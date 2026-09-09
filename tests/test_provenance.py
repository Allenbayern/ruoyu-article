from __future__ import annotations

import importlib.util


def _write_context(tmp_path):
    (tmp_path / "source-manifest.json").write_text(
        '{"sources":['
        '{"source_id":"src-good","role":"confirmed-primary","eligible_for_current_draft":true},'
        '{"source_id":"src-excluded","role":"context-only-excluded","eligible_for_current_draft":false}'
        ']}',
        encoding="utf-8",
    )


def test_provenance_rejects_excluded_source_in_current_claim_mapping(tmp_path):
    assert importlib.util.find_spec("article_group.provenance") is not None
    from article_group.provenance import validate_current_source_provenance

    _write_context(tmp_path)
    batch = {
        "articles": [
            {
                "article_id": "art-001",
                "source_refs": ["src-excluded"],
                "claim_mappings": [{"source_id": "src-excluded"}],
                "exclusion_evidence_refs": ["src-excluded"],
            }
        ]
    }
    errors = validate_current_source_provenance(batch, tmp_path)
    assert "excluded_source_in_current_ref:art-001:src-excluded" in errors


def test_provenance_allows_excluded_source_only_in_exclusion_evidence(tmp_path):
    from article_group.provenance import validate_current_source_provenance

    _write_context(tmp_path)
    batch = {
        "articles": [
            {
                "article_id": "art-001",
                "source_refs": ["src-good"],
                "claim_mappings": [{"source_id": "src-good"}],
                "exclusion_evidence_refs": ["src-excluded"],
            }
        ]
    }
    assert validate_current_source_provenance(batch, tmp_path) == []
