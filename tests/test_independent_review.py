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
