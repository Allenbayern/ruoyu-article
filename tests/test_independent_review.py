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


# --- 记录状态判据与 canonical 化（2026-09-18，daily-009 复盘）----------------


def placeholder_record(**overrides) -> dict:
    """引擎在"这篇还没复核"时写的占位记录（可以被安全刷新）。"""

    record = {
        "schema_version": "article-independent-review-v1",
        "article_task_id": "at-art-001",
        "article_id": "art-001",
        "run_id": "2026-09-17/daily-009",
        "created_from_run": "2026-09-17/daily-009",
        "artifact_path": "delivery/art-001/delivery.md",
        "artifact_sha256": "a" * 64,
        "draft_path": "drafts/art-001/body_draft.md",
        "draft_sha256": "b" * 64,
        "body_path": "drafts/art-001/body_draft.md",
        "body_sha256": "b" * 64,
        "title_pack_path": "review/art-001/title-pack.json",
        "title_pack_sha256": "c" * 64,
        "attempt": 1,
        "max_attempts": 3,
        "status": "PENDING",
        "decision": "human_review_required",
        "next_step": "independent_review_required",
        "scope": "single_article",
        "publication_authorization": "not_authorized",
    }
    record.update(overrides)
    return record


def test_only_the_unreviewed_stub_is_a_placeholder():
    from article_group.independent_review import is_placeholder_record

    assert is_placeholder_record(placeholder_record()) is True
    assert is_placeholder_record(placeholder_record(status="pending")) is True
    assert is_placeholder_record(None) is True  # 记录缺失 = 还没复核


def test_finished_review_records_are_never_placeholders():
    """PASS/complete/UNVERIFIED 都是结论；引擎不得用占位符覆盖它们。"""

    from article_group.independent_review import is_placeholder_record

    for overrides in (
        # codex_review 契约记录（daily-009 就是这样被覆盖掉的）
        {"status": "PASS", "decision": "approve", "structured_result": True},
        {"status": "FAIL", "decision": "needs_changes", "structured_result": True},
        # canonical 记录
        {"status": "complete", "decision": "approve", "next_step": "stop"},
        # 跑过但没跑出结论：超时记录也要留证据
        {"status": "UNVERIFIED", "decision": "timeout", "timeout_reason": "deadline"},
        # evidence_rebind 判失效后的记录带 stale 痕迹，同样不能静默覆盖
        {"status": "PENDING", "decision": "human_review_required", "stale": True,
         "stale_reason": "delivery_or_title_changed:artifact_sha256"},
    ):
        assert is_placeholder_record(placeholder_record(**overrides)) is False, overrides


def _bound_review_record(tmp_path, **overrides) -> dict:
    from article_group.independent_review import build_independent_review_binding

    (tmp_path / "delivery" / "art-001").mkdir(parents=True)
    (tmp_path / "drafts" / "art-001").mkdir(parents=True)
    (tmp_path / "review" / "art-001").mkdir(parents=True)
    (tmp_path / "delivery" / "art-001" / "delivery.md").write_text("# 标题\n\n正文\n", encoding="utf-8")
    (tmp_path / "drafts" / "art-001" / "body_draft.md").write_text("正文\n", encoding="utf-8")
    (tmp_path / "review" / "art-001" / "title-pack.json").write_text('{"title":"标题"}', encoding="utf-8")
    binding = build_independent_review_binding(
        tmp_path,
        artifact_path="delivery/art-001/delivery.md",
        body_path="drafts/art-001/body_draft.md",
        title_pack_path="review/art-001/title-pack.json",
        created_from_run="2026-09-17/daily-009",
    )
    record = {
        "schema_version": "codex-review-contract-1.0",
        "review_mode": "l2",
        "article_task_id": "at-art-001",
        "article_id": "art-001",
        "run_id": "daily-009",
        "decision": "approve",
        "findings": [],
        "coverage_gaps": [],
        "structured_result": True,
        "status": "PASS",
        "attempt": 4,
        "max_attempts": 3,
        "publication_authorization": "not_authorized",
        "draft_path": "drafts/art-001/body_draft.md",
        "draft_sha256": binding["body_sha256"],
        **binding,
    }
    record.update(overrides)
    return record


def test_canonicalize_makes_a_contract_record_the_gate_can_read(tmp_path):
    from article_group.independent_review import (
        canonicalize_independent_review_record,
        evaluate_independent_review,
    )

    canonical = canonicalize_independent_review_record(
        _bound_review_record(tmp_path), article_id="art-001", run_root=tmp_path
    )

    assert canonical["schema_version"] == "article-independent-review-v1"
    assert canonical["status"] == "complete"
    assert canonical["contract_status"] == "PASS"  # 契约判词不丢
    assert canonical["next_step"] == "stop"
    assert canonical["max_attempts"] == 3
    assert canonical["run_id"] == "2026-09-17/daily-009"
    assert canonical["publication_authorization"] == "not_authorized"
    assert canonical["canonical_validation_errors"] == []

    result = evaluate_independent_review(
        canonical,
        run_root=tmp_path,
        expected_artifact_path="delivery/art-001/delivery.md",
        expected_body_path="drafts/art-001/body_draft.md",
        expected_title_pack_path="review/art-001/title-pack.json",
        expected_run_id="2026-09-17/daily-009",
        strict=True,
    )
    assert result["errors"] == []
    assert result["pass"] is True


def test_canonicalize_keeps_a_failed_review_complete_but_not_passing(tmp_path):
    from article_group.independent_review import (
        canonicalize_independent_review_record,
        evaluate_independent_review,
    )

    canonical = canonicalize_independent_review_record(
        _bound_review_record(tmp_path, status="FAIL", decision="needs_changes"),
        article_id="art-001",
        run_root=tmp_path,
    )

    assert canonical["status"] == "complete"  # 跑完了
    assert canonical["contract_status"] == "FAIL"
    assert canonical["next_step"] == "needs_changes"
    assert evaluate_independent_review(canonical)["pass"] is False


def test_canonicalize_keeps_a_missing_result_unverified(tmp_path):
    from article_group.independent_review import canonicalize_independent_review_record

    record = _bound_review_record(tmp_path)
    record.pop("structured_result")
    record["status"] = "UNVERIFIED"
    record["decision"] = "evidence_insufficient"
    record["error"] = "l2_structured_result_missing"

    canonical = canonicalize_independent_review_record(
        record, article_id="art-001", run_root=tmp_path
    )

    assert canonical["status"] == "UNVERIFIED"
    assert canonical["next_step"] == "independent_review_required"


def test_canonicalize_reports_a_stale_binding_instead_of_hiding_it(tmp_path):
    from article_group.independent_review import canonicalize_independent_review_record

    record = _bound_review_record(tmp_path)
    (tmp_path / "delivery" / "art-001" / "delivery.md").write_text(
        "# 标题\n\n正文改过了\n", encoding="utf-8"
    )

    canonical = canonicalize_independent_review_record(
        record, article_id="art-001", run_root=tmp_path
    )

    assert "stale_review" in canonical["canonical_validation_errors"]
