"""Independent review timeout stays UNVERIFIED and can resume one article."""
from article_group.independent_review import (
    evaluate_independent_review,
    plan_resume,
    validate_independent_review_record,
)


def timeout_record(**overrides) -> dict:
    record = {
        "schema_version": "article-independent-review-v1",
        "article_task_id": "at-art-001",
        "article_id": "art-001",
        "draft_path": "articles/art-001.md",
        "draft_sha256": "a" * 64,
        "attempt": 1,
        "max_attempts": 3,
        "status": "UNVERIFIED",
        "decision": "timeout",
        "timeout_reason": "l2_exec_deadline_exceeded",
        "next_step": "resume_single_article",
        "scope": "single_article",
        "l2_required": True,
        "l2_risk_basis": "标题承诺涉及人物动机，需要独立核对材料边界",
        "publication_authorization": "not_authorized",
    }
    record.update(overrides)
    return record


def test_timeout_cannot_be_treated_as_pass():
    result = evaluate_independent_review(timeout_record())
    assert result["errors"] == []
    assert result["status"] == "UNVERIFIED"
    assert result["pass"] is False


def test_timeout_can_resume_current_article_version():
    plan = plan_resume(
        timeout_record(),
        current_draft_path="articles/art-001.md",
        current_draft_sha256="b" * 64,
    )
    assert plan["action"] == "resume_article"
    assert plan["article_task_id"] == "at-art-001"
    assert plan["attempt"] == 2
    assert plan["draft_sha256"] == "b" * 64
    assert plan["scope"] == "single_article"
    assert plan["rerun_batch"] is False


def test_retry_limit_blocks_further_resume():
    plan = plan_resume(
        timeout_record(attempt=3, max_attempts=3),
        current_draft_path="articles/art-001.md",
        current_draft_sha256="a" * 64,
    )
    assert plan["action"] == "blocked"
    assert plan["reason"] == "retry_limit"


def test_l2_requires_specific_risk_basis():
    errors = validate_independent_review_record(
        timeout_record(l2_required=True, l2_risk_basis="")
    )
    assert "l2_requires_risk_basis" in errors


def test_unverified_timeout_cannot_use_approve_decision():
    errors = validate_independent_review_record(
        timeout_record(decision="approve")
    )
    assert "timeout_cannot_pass" in errors


def test_resume_keeps_previous_timeout_evidence():
    plan = plan_resume(
        timeout_record(),
        current_draft_path="articles/art-001.md",
        current_draft_sha256="a" * 64,
    )
    assert plan["previous_status"] == "UNVERIFIED"
    assert plan["previous_timeout_reason"] == "l2_exec_deadline_exceeded"


def test_strict_review_binding_records_current_artifact_hashes(tmp_path):
    from article_group.independent_review import build_independent_review_binding

    (tmp_path / "articles").mkdir()
    (tmp_path / "review").mkdir()
    (tmp_path / "articles" / "art-001.md").write_text("正文版本一", encoding="utf-8")
    (tmp_path / "review" / "body.md").write_text("正文版本一", encoding="utf-8")
    (tmp_path / "review" / "title-pack.json").write_text('{"title":"标题"}', encoding="utf-8")

    binding = build_independent_review_binding(
        tmp_path,
        artifact_path="articles/art-001.md",
        body_path="review/body.md",
        title_pack_path="review/title-pack.json",
        created_from_run="run-001",
    )

    assert binding["artifact_sha256"]
    assert binding["body_sha256"]
    assert binding["title_pack_sha256"]
    assert binding["created_from_run"] == "run-001"


def test_strict_review_binding_defaults_to_the_full_manifest_run_id(tmp_path):
    from article_group.independent_review import build_independent_review_binding

    (tmp_path / "articles").mkdir()
    (tmp_path / "review").mkdir()
    (tmp_path / "articles" / "art-001.md").write_text("正文", encoding="utf-8")
    (tmp_path / "review" / "body.md").write_text("正文", encoding="utf-8")
    (tmp_path / "review" / "title-pack.json").write_text("{}", encoding="utf-8")
    (tmp_path / "batch.json").write_text(
        '{"run_id":"2026-09-13/daily-003"}', encoding="utf-8"
    )

    binding = build_independent_review_binding(
        tmp_path,
        artifact_path="articles/art-001.md",
        body_path="review/body.md",
        title_pack_path="review/title-pack.json",
    )

    assert binding["created_from_run"] == "2026-09-13/daily-003"


def test_strict_review_rejects_a_changed_body_as_stale(tmp_path):
    from article_group.independent_review import build_independent_review_binding

    (tmp_path / "articles").mkdir()
    (tmp_path / "review").mkdir()
    artifact = tmp_path / "articles" / "art-001.md"
    body = tmp_path / "review" / "body.md"
    title_pack = tmp_path / "review" / "title-pack.json"
    artifact.write_text("正文版本一", encoding="utf-8")
    body.write_text("正文版本一", encoding="utf-8")
    title_pack.write_text('{"title":"标题"}', encoding="utf-8")
    binding = build_independent_review_binding(
        tmp_path,
        artifact_path="articles/art-001.md",
        body_path="review/body.md",
        title_pack_path="review/title-pack.json",
        created_from_run="run-001",
    )
    body.write_text("正文版本二", encoding="utf-8")
    record = timeout_record(
        production_contract="article-first-v1",
        brief_contract="writing-brief-v2",
        title_contract="title-pack-v1",
        legacy_compatibility=False,
        draft_path="articles/art-001.md",
        draft_sha256=binding["artifact_sha256"],
        **binding,
    )

    result = evaluate_independent_review(
        record,
        run_root=tmp_path,
        expected_run_id="run-001",
        expected_artifact_path="articles/art-001.md",
        expected_body_path="review/body.md",
        expected_title_pack_path="review/title-pack.json",
    )

    assert result["status"] == "stale_review"
    assert result["pass"] is False
    assert "stale_review" in result["errors"]


def test_strict_review_rejects_wrong_run_binding(tmp_path):
    from article_group.independent_review import build_independent_review_binding

    (tmp_path / "articles").mkdir()
    (tmp_path / "review").mkdir()
    (tmp_path / "articles" / "art-001.md").write_text("正文", encoding="utf-8")
    (tmp_path / "review" / "body.md").write_text("正文", encoding="utf-8")
    (tmp_path / "review" / "title-pack.json").write_text("{}", encoding="utf-8")
    binding = build_independent_review_binding(
        tmp_path,
        artifact_path="articles/art-001.md",
        body_path="review/body.md",
        title_pack_path="review/title-pack.json",
        created_from_run="run-old",
    )
    record = timeout_record(
        production_contract="article-first-v1",
        brief_contract="writing-brief-v2",
        title_contract="title-pack-v1",
        legacy_compatibility=False,
        draft_path="articles/art-001.md",
        draft_sha256=binding["artifact_sha256"],
        **binding,
    )

    errors = validate_independent_review_record(
        record, run_root=tmp_path, expected_run_id="run-new"
    )

    assert "stale_review" in errors


def test_resume_preserves_strict_artifact_binding(tmp_path):
    from article_group.independent_review import build_independent_review_binding, plan_resume

    (tmp_path / "article.md").write_text("正文", encoding="utf-8")
    (tmp_path / "body.md").write_text("正文", encoding="utf-8")
    (tmp_path / "title-pack.json").write_text("{}", encoding="utf-8")
    binding = build_independent_review_binding(
        tmp_path,
        artifact_path="article.md",
        body_path="body.md",
        title_pack_path="title-pack.json",
        created_from_run="run-001",
    )
    previous = timeout_record(
        draft_path="article.md",
        draft_sha256=binding["artifact_sha256"],
        **binding,
    )

    resumed = plan_resume(
        previous,
        current_draft_path="article.md",
        current_draft_sha256=binding["artifact_sha256"],
    )

    for field in (
        "artifact_path",
        "artifact_sha256",
        "body_path",
        "body_sha256",
        "title_pack_path",
        "title_pack_sha256",
        "created_from_run",
    ):
        assert resumed[field] == binding[field]
