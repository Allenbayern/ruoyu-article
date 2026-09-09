from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json


def test_human_attestation_requires_explicit_human_identity_and_current_html(tmp_path):
    assert importlib.util.find_spec("article_group.human_attestation") is not None
    from article_group.human_attestation import validate_human_attestation

    html = tmp_path / "review" / "frozen" / "ruoyu-art-001.html"
    html.parent.mkdir(parents=True)
    html.write_text("<article>正文</article>", encoding="utf-8")
    attestation = {
        "schema_version": "human-attestation-v1",
        "article_id": "art-001",
        "reviewer_kind": "human",
        "reviewer_role": "human_editor",
        "reviewer_identity": "Allen",
        "reviewed_at": "2026-08-25T12:00:00+08:00",
        "decision": "accept",
        "html_path": "review/frozen/ruoyu-art-001.html",
        "html_sha256": hashlib.sha256(html.read_bytes()).hexdigest(),
        "attestation_ref": "manual-editor-review-001",
    }
    assert validate_human_attestation(attestation, tmp_path, "art-001", [html]) == []


def test_human_attestation_rejects_controller_or_model_provenance(tmp_path):
    from article_group.human_attestation import validate_human_attestation

    html = tmp_path / "ruoyu-art-001.html"
    html.write_text("正文", encoding="utf-8")
    attestation = {
        "schema_version": "human-attestation-v1",
        "article_id": "art-001",
        "reviewer_kind": "controller",
        "reviewer_role": "human_editor",
        "reviewer_identity": "controller-luna",
        "reviewed_at": "2026-08-25T12:00:00+08:00",
        "decision": "accept",
        "html_path": html.name,
        "html_sha256": hashlib.sha256(html.read_bytes()).hexdigest(),
        "attestation_ref": "fake",
    }
    errors = validate_human_attestation(attestation, tmp_path, "art-001", [html])
    assert "reviewer_kind_must_be_human" in errors
    assert "reviewer_identity_not_human" in errors


def test_markdown_human_attestation_v3_binds_current_markdown(tmp_path):
    from article_group.human_attestation import validate_human_attestation

    markdown = tmp_path / "drafts" / "art-001.md"
    markdown.parent.mkdir(parents=True)
    markdown.write_text("# 标题\n\n正文", encoding="utf-8")
    attestation = {
        "schema_version": "human-attestation-v3",
        "article_id": "art-001",
        "reviewer_kind": "human",
        "reviewer_role": "human_editor",
        "reviewer_identity": "Allen",
        "reviewed_at": "2026-08-26T12:00:00+08:00",
        "decision": "accept",
        "markdown_path": "drafts/art-001.md",
        "markdown_sha256": hashlib.sha256(markdown.read_bytes()).hexdigest(),
        "attestation_ref": "manual-editor-review-003",
    }

    assert validate_human_attestation(
        attestation,
        tmp_path,
        "art-001",
        [],
        review_surface="markdown_codex",
        markdown_paths=[markdown],
    ) == []


def test_markdown_human_attestation_rejects_html_binding_fields(tmp_path):
    from article_group.human_attestation import validate_human_attestation

    markdown = tmp_path / "art-001.md"
    markdown.write_text("# 标题\n\n正文", encoding="utf-8")
    attestation = {
        "schema_version": "human-attestation-v3",
        "article_id": "art-001",
        "reviewer_kind": "human",
        "reviewer_role": "human_editor",
        "reviewer_identity": "Allen",
        "reviewed_at": "2026-08-26T12:00:00+08:00",
        "decision": "accept",
        "markdown_path": markdown.name,
        "markdown_sha256": hashlib.sha256(markdown.read_bytes()).hexdigest(),
        "html_path": "old.html",
        "html_sha256": "0" * 64,
        "attestation_ref": "manual-editor-review-003",
    }

    errors = validate_human_attestation(
        attestation,
        tmp_path,
        "art-001",
        [],
        review_surface="markdown_codex",
        markdown_paths=[markdown],
    )

    assert "human_attestation_html_fields_forbidden" in errors
