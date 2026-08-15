"""Executable contract tests for the four-stage editorial-review protocol."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys


def _write_json(root: Path, relative_path: str, payload: dict) -> dict[str, str]:
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "path": relative_path,
        "version": "1.0",
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }


def _write_text(root: Path, relative_path: str, text: str) -> dict[str, str]:
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return {
        "path": relative_path,
        "version": "1.0",
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }


def valid_record(root: Path) -> dict:
    topic_ref = _write_json(
        root,
        "editorial/art-001/topic-card.json",
        {
            "card_version": "1.0",
            "card_type": "topic_card",
            "run_id": "controlled-test",
            "article_id": "art-001",
            "core_question": "五天定档窗口会怎样影响一部160分钟电影的开画？",
            "target_reader": "关心院线新片但不熟悉排片机制的观众",
            "article_type": "发行策略观察",
            "one_sentence_scope": "只解释可观察的定档窗口与开画后果。",
            "out_of_scope": ["不推断片方动机", "不预测票房"],
            "decision": "proceed",
            "stop_reasons": [],
            "decided_by": "editor",
            "decided_at": "2026-08-15T10:00:00+08:00",
        },
    )
    fact_ref = _write_json(
        root,
        "editorial/art-001/fact-card.json",
        {
            "card_version": "1.0",
            "card_type": "fact_card",
            "run_id": "controlled-test",
            "article_id": "art-001",
            "sources": [
                {
                    "source_id": "src-001",
                    "url": "https://news.example.cn/article/001",
                    "locator": "官宣段第1段",
                    "source_level": "fulltext",
                    "accessed_at": "2026-08-15T10:10:00+08:00",
                }
            ],
            "permitted_claims": [
                {
                    "claim_id": "claim-001",
                    "claim": "影片于8月14日官宣，并计划于8月19日开画。",
                    "claim_type": "fact",
                    "source_ids": ["src-001"],
                    "limitation": "只证明正式定档窗口，不等于完整宣发期。",
                }
            ],
            "prohibited_claims": [
                {"claim": "片方为何选择周三开画", "reason": "现有来源未说明动机"}
            ],
            "coverage_gaps": [],
            "unresolved_conflicts": [],
            "data_as_of": "2026-08-15T10:20:00+08:00",
            "update_required_before_publication": "yes",
            "update_trigger": "冻结前重查票房、排片等动态数据。",
            "decision": "ready_for_draft",
            "stop_reasons": [],
            "decided_by": "fact_editor",
            "decided_at": "2026-08-15T10:20:00+08:00",
        },
    )
    draft_ref = _write_text(root, "drafts/art-001.md", "# 测试稿\n\n只写已核事实。\n")
    prepub_ref = _write_text(root, "review/art-001-prepublication.txt", "manual checklist evidence\n")

    stage_specs = [
        (
            "project_precheck",
            "立项前",
            "define_article_scope",
            "human",
            {"core_question": "pass", "target_reader": "pass", "article_type": "pass", "scope_exclusions": "pass"},
            [topic_ref],
            "prewrite",
        ),
        (
            "prewrite",
            "写作前",
            "bound_permitted_claims",
            "human_and_mechanical",
            {"claim_source_links": "pass", "prohibited_claims": "pass", "coverage_gaps": "pass", "conflicts": "pass"},
            [fact_ref],
            "postdraft",
        ),
        (
            "postdraft",
            "成稿后",
            "edit_human_writing",
            "human",
            {"structure": "pass", "viewpoint": "pass", "tone": "pass", "narrative": "pass"},
            [draft_ref],
            "prepublication",
        ),
        (
            "prepublication",
            "发布前",
            "verify_distribution_and_facts",
            "human_and_mechanical",
            {"title": "pass", "opening": "pass", "sources": "pass", "digits": "pass", "links": "pass", "page_cleanup": "pass"},
            [prepub_ref],
            "controller_review",
        ),
    ]
    scope_specs = {
        "project_precheck": {
            "scope_id": "topic_definition_only",
            "allowed_actions": [
                "define_core_question",
                "define_target_reader",
                "classify_article_type",
                "declare_scope_exclusions",
            ],
            "forbidden_actions": [
                "write_draft",
                "assert_unsourced_fact",
                "authorize_publication",
            ],
        },
        "prewrite": {
            "scope_id": "fact_boundary_only",
            "allowed_actions": [
                "map_claim_to_source",
                "declare_permitted_claim",
                "declare_prohibited_claim",
                "record_coverage_gap",
                "record_conflict",
            ],
            "forbidden_actions": [
                "change_topic_scope",
                "write_unsourced_claim",
                "authorize_publication",
            ],
        },
        "postdraft": {
            "scope_id": "human_writing_only",
            "allowed_actions": [
                "edit_structure",
                "edit_viewpoint",
                "edit_tone",
                "edit_narrative",
            ],
            "forbidden_actions": [
                "add_unsourced_fact",
                "rewrite_fact_boundary",
                "authorize_publication",
            ],
        },
        "prepublication": {
            "scope_id": "distribution_verification_only",
            "allowed_actions": [
                "review_title",
                "review_opening",
                "verify_sources",
                "verify_digits",
                "verify_links",
                "verify_page_cleanup",
            ],
            "forbidden_actions": [
                "change_editorial_thesis",
                "expand_fact_scope",
                "authorize_publication",
            ],
        },
    }
    stages = []
    for index, (stage_id, label, objective, mode, checks, evidence_refs, handoff_to) in enumerate(stage_specs):
        scope = scope_specs[stage_id]
        stages.append(
            {
                "stage_id": stage_id,
                "label": label,
                "round": 1,
                "objective": objective,
                "objectives": [objective],
                "scope": {
                    **scope,
                    "reader_facing": False,
                    "description": f"{label} only",
                },
                "status": "pass",
                "review_mode": mode,
                "checks": checks,
                "evidence_refs": evidence_refs,
                "completed_by": f"reviewer-{index + 1}",
                "completed_at": f"2026-08-15T1{index}:00:00+08:00",
                "handoff_to": handoff_to,
                "decision_note": "本轮仅完成该阶段唯一目标。",
            }
        )
    draft_passes = [
        {
            "pass_id": "facts_draft",
            "round": 1,
            "objective": "render_only_permitted_claims",
            "objectives": ["render_only_permitted_claims"],
            "stage_id": "prewrite",
            "status": "pass",
            "decision_note": "只按事实卡写入底稿。",
        },
        {
            "pass_id": "editorial_draft",
            "round": 1,
            "objective": "shape_structure_viewpoint_tone_narrative",
            "objectives": ["shape_structure_viewpoint_tone_narrative"],
            "stage_id": "postdraft",
            "status": "pass",
            "decision_note": "只编辑结构、观点、语气和叙事。",
        },
        {
            "pass_id": "recommender_optimization",
            "round": 1,
            "objective": "test_title_opening_and_distribution_fit",
            "objectives": ["test_title_opening_and_distribution_fit"],
            "stage_id": "prepublication",
            "status": "pass",
            "decision_note": "只核对标题、首屏和分发承诺。",
        },
        {
            "pass_id": "final_prepublication_review",
            "round": 1,
            "objective": "recheck_sources_digits_links_and_page_cleanup",
            "objectives": ["recheck_sources_digits_links_and_page_cleanup"],
            "stage_id": "prepublication",
            "status": "pass",
            "decision_note": "只复核来源、数字、链接和页面残留。",
        },
    ]
    return {
        "protocol_version": "1.0",
        "record_revision": 1,
        "supersedes_record_ref": None,
        "run_id": "controlled-test",
        "article_id": "art-001",
        "publication_authorization": "not_authorized",
        "card_refs": {"topic_card": topic_ref, "fact_card": fact_ref},
        "stages": stages,
        "draft_passes": draft_passes,
        "stop_draft": {
            "triggered": False,
            "stage_id": None,
            "reason_codes": [],
            "draft_disposition": "continue",
        },
        "handoff": {
            "status": "ready",
            "from_stage": "prepublication",
            "to": "controller_review",
            "handoff_at": "2026-08-15T14:00:00+08:00",
            "note": "结构与来源边界已核验，交由 controller 作最终采纳判断。",
            "evidence_refs": [prepub_ref],
        },
    }


def blocked_record(root: Path) -> dict:
    record = valid_record(root)
    record["stages"][1]["status"] = "fail"
    record["stages"][1]["decision_note"] = "事实卡存在需要补充的证据。"
    for stage in record["stages"][2:]:
        stage["status"] = "not_run"
        stage["checks"] = {name: "not_run" for name in stage["checks"]}
        stage["evidence_refs"] = []
    record["draft_passes"][0]["status"] = "blocked"
    for draft_pass in record["draft_passes"][1:]:
        draft_pass["status"] = "not_run"
    record["stop_draft"] = {
        "triggered": True,
        "stage_id": "prewrite",
        "reason_codes": ["stage_failed"],
        "draft_disposition": "revise",
        "evidence_refs": [record["card_refs"]["fact_card"]],
    }
    record["handoff"] = {
        "status": "blocked",
        "from_stage": "prewrite",
        "to": "evidence_intake",
        "handoff_at": "2026-08-15T14:00:00+08:00",
        "note": "事实卡阶段失败，后续阶段不得继续。",
        "evidence_refs": [record["card_refs"]["fact_card"]],
    }
    return record


def test_complete_record_passes_without_authorizing_publication(tmp_path: Path) -> None:
    from article_group.editorial_review import evaluate_editorial_record

    report = evaluate_editorial_record(valid_record(tmp_path), tmp_path)

    assert report == {
        "verdict": "PASS",
        "errors": [],
        "stop_reasons": [],
        "next_action": "controller_review",
        "publication_authorization": "not_authorized",
    }


def test_topic_and_fact_card_references_are_mandatory(tmp_path: Path) -> None:
    from article_group.editorial_review import evaluate_editorial_record

    record = valid_record(tmp_path)
    del record["card_refs"]["topic_card"]

    report = evaluate_editorial_record(record, tmp_path)

    assert report["verdict"] == "FAIL"
    assert "card_ref_missing:topic_card" in report["errors"]


def test_positive_later_round_is_valid_when_each_pass_has_one_objective(tmp_path: Path) -> None:
    from article_group.editorial_review import evaluate_editorial_record

    record = valid_record(tmp_path)
    record["stages"][2]["round"] = 2
    record["draft_passes"][1]["round"] = 2

    report = evaluate_editorial_record(record, tmp_path)

    assert report["verdict"] == "PASS"


def test_multiple_objectives_fail_closed(tmp_path: Path) -> None:
    from article_group.editorial_review import evaluate_editorial_record

    record = valid_record(tmp_path)
    record["stages"][0]["objectives"].append("write_draft")

    report = evaluate_editorial_record(record, tmp_path)

    assert report["verdict"] == "FAIL"
    assert "stage_single_objective_invalid:project_precheck" in report["errors"]


def test_tampered_card_digest_fails_closed(tmp_path: Path) -> None:
    from article_group.editorial_review import evaluate_editorial_record

    record = valid_record(tmp_path)
    topic_path = tmp_path / record["card_refs"]["topic_card"]["path"]
    topic_path.write_text("{}\n", encoding="utf-8")

    report = evaluate_editorial_record(record, tmp_path)

    assert report["verdict"] == "FAIL"
    assert "artifact_digest_mismatch:topic_card" in report["errors"]


def test_fact_card_requires_dynamic_data_boundary(tmp_path: Path) -> None:
    from article_group.editorial_review import evaluate_editorial_record

    record = valid_record(tmp_path)
    fact_ref = record["card_refs"]["fact_card"]
    fact_path = tmp_path / fact_ref["path"]
    fact_card = json.loads(fact_path.read_text(encoding="utf-8"))
    del fact_card["data_as_of"]
    updated_ref = _write_json(tmp_path, fact_ref["path"], fact_card)
    fact_ref.update(updated_ref)

    report = evaluate_editorial_record(record, tmp_path)

    assert report["verdict"] == "FAIL"
    assert "fact_card_data_as_of_missing:fact_card" in report["errors"]


def test_later_stages_cannot_continue_after_failed_stage(tmp_path: Path) -> None:
    from article_group.editorial_review import evaluate_editorial_record

    record = valid_record(tmp_path)
    record["stages"][1]["status"] = "fail"
    record["stop_draft"] = {
        "triggered": True,
        "stage_id": "prewrite",
        "reason_codes": ["stage_failed"],
        "draft_disposition": "revise",
        "evidence_refs": [record["card_refs"]["fact_card"]],
    }
    record["handoff"] = {
        "status": "blocked",
        "from_stage": "prewrite",
        "to": "evidence_intake",
        "handoff_at": "2026-08-15T14:00:00+08:00",
        "note": "事实卡阶段失败，后续阶段不得继续。",
        "evidence_refs": [record["card_refs"]["fact_card"]],
    }

    report = evaluate_editorial_record(record, tmp_path)

    assert report["verdict"] == "FAIL"
    assert "stage_after_failure_must_be_not_run:postdraft" in report["errors"]
    assert "stage_after_failure_must_be_not_run:prepublication" in report["errors"]


def test_draft_passes_are_not_run_after_project_precheck_failure(tmp_path: Path) -> None:
    from article_group.editorial_review import evaluate_editorial_record

    record = valid_record(tmp_path)
    record["stages"][0]["status"] = "fail"
    for stage in record["stages"][1:]:
        stage["status"] = "not_run"
        stage["checks"] = {name: "not_run" for name in stage["checks"]}
        stage["evidence_refs"] = []
    record["draft_passes"][0]["status"] = "blocked"
    for draft_pass in record["draft_passes"][1:]:
        draft_pass["status"] = "not_run"
    record["stop_draft"] = {
        "triggered": True,
        "stage_id": "project_precheck",
        "reason_codes": ["stage_failed"],
        "draft_disposition": "revise",
        "evidence_refs": [record["card_refs"]["topic_card"]],
    }
    record["handoff"] = {
        "status": "blocked",
        "from_stage": "project_precheck",
        "to": "evidence_intake",
        "handoff_at": "2026-08-15T14:00:00+08:00",
        "note": "立项前失败后不得进入任何写作 pass。",
        "evidence_refs": [record["card_refs"]["topic_card"]],
    }

    report = evaluate_editorial_record(record, tmp_path)

    assert report["verdict"] == "FAIL"
    assert "draft_pass_after_stage_failure_must_be_not_run:facts_draft" in report["errors"]


def test_structurally_valid_stop_is_blocked_not_pass(tmp_path: Path) -> None:
    from article_group.editorial_review import evaluate_editorial_record

    report = evaluate_editorial_record(blocked_record(tmp_path), tmp_path)

    assert report == {
        "verdict": "BLOCKED",
        "errors": [],
        "stop_reasons": ["stage_failed"],
        "next_action": "evidence_intake",
        "publication_authorization": "not_authorized",
    }


def test_stop_draft_must_name_a_failed_stage_not_an_unrun_downstream_stage(tmp_path: Path) -> None:
    from article_group.editorial_review import evaluate_editorial_record

    record = blocked_record(tmp_path)
    record["stop_draft"]["stage_id"] = "postdraft"

    report = evaluate_editorial_record(record, tmp_path)

    assert report["verdict"] == "FAIL"
    assert "stop_draft_stage_not_failed:postdraft" in report["errors"]


def test_not_run_stage_must_not_carry_pass_checks(tmp_path: Path) -> None:
    from article_group.editorial_review import evaluate_editorial_record

    record = blocked_record(tmp_path)
    record["stages"][2]["checks"]["structure"] = "pass"

    report = evaluate_editorial_record(record, tmp_path)

    assert report["verdict"] == "FAIL"
    assert "stage_check_not_not_run:postdraft:structure" in report["errors"]


def test_not_run_stage_must_not_carry_evidence_refs(tmp_path: Path) -> None:
    from article_group.editorial_review import evaluate_editorial_record

    record = blocked_record(tmp_path)
    record["stages"][2]["evidence_refs"] = [record["card_refs"]["fact_card"]]

    report = evaluate_editorial_record(record, tmp_path)

    assert report["verdict"] == "FAIL"
    assert "stage_evidence_refs_forbidden:postdraft" in report["errors"]


def test_revised_record_requires_hash_pinned_previous_revision(tmp_path: Path) -> None:
    from article_group.editorial_review import evaluate_editorial_record

    previous = valid_record(tmp_path)
    previous_ref = _write_json(tmp_path, "review/editorial-review-record-r1.json", previous)
    record = valid_record(tmp_path)
    record["record_revision"] = 2
    record["supersedes_record_ref"] = previous_ref

    report = evaluate_editorial_record(record, tmp_path)

    assert report["verdict"] == "PASS"
    record["supersedes_record_ref"]["sha256"] = "0" * 64
    report = evaluate_editorial_record(record, tmp_path)
    assert report["verdict"] == "FAIL"
    assert "artifact_digest_mismatch:supersedes_record" in report["errors"]


def test_cli_uses_explicit_record_and_run_root_and_blocks_nonpassing_record(tmp_path: Path) -> None:
    record_path = tmp_path / "review" / "editorial-review-record.json"
    record_path.parent.mkdir(parents=True)
    record_path.write_text(json.dumps(valid_record(tmp_path), ensure_ascii=False), encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        "article_group.editorial_review",
        "--record",
        str(record_path),
        "--run-root",
        str(tmp_path),
    ]
    repository_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(command, cwd=repository_root, capture_output=True, text=True, check=False)

    assert result.returncode == 0
    assert json.loads(result.stdout)["verdict"] == "PASS"

    record_path.write_text(json.dumps(blocked_record(tmp_path), ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(command, cwd=repository_root, capture_output=True, text=True, check=False)

    assert result.returncode == 1
    assert json.loads(result.stdout)["verdict"] == "BLOCKED"


def test_review_record_cannot_authorize_publication(tmp_path: Path) -> None:
    from article_group.editorial_review import evaluate_editorial_record

    record = valid_record(tmp_path)
    record["publication_authorization"] = "authorized"

    report = evaluate_editorial_record(record, tmp_path)

    assert report["verdict"] == "FAIL"
    assert "publication_authorization_must_be_not_authorized" in report["errors"]


def test_templates_and_runbook_document_the_validator_contract() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    topic_template = (repository_root / "templates/topic-card.md").read_text(encoding="utf-8")
    fact_template = (repository_root / "templates/fact-card.md").read_text(encoding="utf-8")
    record_template = (repository_root / "templates/editorial-review-record.md").read_text(encoding="utf-8")
    runbook = (
        repository_root / "docs/plans/ruoyu-production-v2/2026-08-14-daily-pipeline-runbook.md"
    ).read_text(encoding="utf-8")

    for template, reference_key in (
        (topic_template, "card_refs.topic_card"),
        (fact_template, "card_refs.fact_card"),
    ):
        assert reference_key in template
        assert "{path, version, sha256}" in template
        assert "必须等于该 JSON 的 `card_version`" in template

    for required_field in (
        '"card_refs"',
        '"topic_card"',
        '"fact_card"',
        '"review_mode"',
        '"stop_draft"',
        "--record",
        "--run-root",
    ):
        assert required_field in record_template

    assert "- publication_authorization: `not_authorized`" in record_template
    assert "仅 `PASS` 返回 exit `0`" in record_template
    assert "`BLOCKED`" in record_template
    assert "--record" in runbook
    assert "--run-root" in runbook
    assert "`BLOCKED`（结构合法但停稿）" in runbook
    assert "未接入/coverage gap" in runbook
