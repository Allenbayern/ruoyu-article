"""Editorial judgment is separate from four-stage record structure."""
from __future__ import annotations

from article_group.editorial_judgment import (
    evaluate_editorial_judgment,
    find_internal_review_language,
    validate_editorial_judgment,
)


def _increment(
    section_id: str,
    locator: str,
    added_material: str,
    advanced_judgment: str,
    difference_from_previous: str,
    increment_kind: str,
    supporting_material_ids: list[str] | None = None,
) -> dict:
    return {
        "section_id": section_id,
        "locator": locator,
        "added_material": added_material,
        "advanced_judgment": advanced_judgment,
        "difference_from_previous": difference_from_previous,
        "increment_kind": increment_kind,
        "supporting_material_ids": supporting_material_ids or [],
    }


def _finding(locator: str, defect: str, basis: str, action: str) -> dict:
    return {
        "locator": locator,
        "defect": defect,
        "basis": basis,
        "action": action,
    }


def judgment_record(**overrides) -> dict:
    record = {
        "schema_version": "article-editorial-judgment-v1",
        "article_task_id": "at-art-001",
        "article_id": "art-001",
        "draft_path": "articles/art-001.md",
        "draft_sha256": "a" * 64,
        "structure_result": "pass",
        "structure_record_ref": {
            "path": "review/editorial-review-record-art-001.json",
            "sha256": "b" * 64,
        },
        "judgment_result": "pass",
        "actor_layers": {
            "machine_check": {
                "by": "editorial-review-validator",
                "result": "pass",
                "checked_at": "2026-09-10T11:00:00+08:00",
            },
            "model_editorial_review": {
                "by": "grok-4.6",
                "result": "pass",
                "checked_at": "2026-09-10T11:05:00+08:00",
                "paragraph_notes": [
                    {
                        "locator": "第2段",
                        "note": "新增第6期书信标题，把等待落到具体预告。",
                    }
                ],
            },
            "human_confirmation": {
                "by": "allen",
                "result": "pass",
                "checked_at": "2026-09-10T12:00:00+08:00",
                "attestation_ref": "review/attestation/art-001.json",
            },
        },
        "section_increments": [
            _increment(
                "s1",
                "第1-2段",
                "第6期上书信标题",
                "预告把思念写成公开节点",
                "开篇",
                "new_fact",
                ["src-heart-ep6-letter"],
            ),
            _increment(
                "s2",
                "第3-4段",
                "告白后当场递水并留下",
                "可讨论的是有没有接住求助",
                "从预告节点转到当场动作",
                "new_judgment",
                ["src-episode-scene"],
            ),
        ],
        "findings": [],
        "scoring_evidence": {
            "total_score": 88,
            "why_worth_reading": [
                {
                    "locator": "第3段",
                    "argument": "读者能就“留下还是没留下”站队，而不是听等待的空判断。",
                }
            ],
        },
    }
    record.update(overrides)
    return record


def test_structure_pass_is_not_judgment_pass():
    result = evaluate_editorial_judgment(
        judgment_record(
            judgment_result="return_research",
            actor_layers={
                "machine_check": {
                    "by": "editorial-review-validator",
                    "result": "pass",
                    "checked_at": "2026-09-10T11:00:00+08:00",
                },
                "model_editorial_review": {
                    "by": "grok-4.6",
                    "result": "return_research",
                    "checked_at": "2026-09-10T11:05:00+08:00",
                    "paragraph_notes": [
                        {
                            "locator": "第4-6段",
                            "note": "同一书信标题反复解释等待，没有新场面。",
                        }
                    ],
                },
                "human_confirmation": {
                    "by": "allen",
                    "result": "pending",
                    "checked_at": None,
                    "attestation_ref": None,
                },
            },
            findings=[
                _finding(
                    "第4-6段",
                    "少量材料反复解释",
                    "added_material 与第1节相同，只换等待/照顾的说法",
                    "return_research",
                )
            ],
        )
    )
    assert result["structure_result"] == "pass"
    assert result["judgment_result"] == "return_research"
    assert result["combined_result"] != "pass"


def test_repeated_material_cannot_pass_as_increment():
    errors = validate_editorial_judgment(
        judgment_record(
            section_increments=[
                _increment(
                    "s1",
                    "第1-2段",
                    "第6期上书信标题",
                    "等待开始",
                    "开篇",
                    "new_fact",
                    ["src-heart-ep6-letter"],
                ),
                _increment(
                    "s2",
                    "第3-4段",
                    "第6期上书信标题",
                    "等待仍在继续",
                    "换词复述",
                    "restatement",
                    ["src-heart-ep6-letter"],
                ),
            ]
        )
    )
    assert "section_increment_restatement" in errors


def test_protocol_record_is_not_human_confirmation():
    record = judgment_record()
    record["actor_layers"]["human_confirmation"] = {
        "by": "editorial-protocol-record",
        "result": "pass",
        "checked_at": "2026-09-10T11:00:00+08:00",
        "attestation_ref": "review/attestation/art-001.json",
    }
    errors = validate_editorial_judgment(record)
    assert "human_confirmation_not_human" in errors


def test_human_mode_without_human_pass_cannot_claim_judgment_pass():
    record = judgment_record(judgment_result="pass")
    record["actor_layers"]["human_confirmation"] = {
        "by": "allen",
        "result": "pending",
        "checked_at": None,
        "attestation_ref": None,
    }
    errors = validate_editorial_judgment(record)
    assert "human_confirmation_required_for_pass" in errors


def test_high_score_requires_paragraph_level_why_worth_reading():
    errors = validate_editorial_judgment(
        judgment_record(
            scoring_evidence={
                "total_score": 88,
                "why_worth_reading": [],
            }
        )
    )
    assert "scoring_missing_why_worth_reading" in errors


def test_motivation_or_audience_consensus_cannot_pass_without_material():
    errors = validate_editorial_judgment(
        judgment_record(
            section_increments=[
                _increment(
                    "s1",
                    "第1段",
                    "视频简介",
                    "问的其实是我有没有被看见",
                    "开篇",
                    "character_motivation",
                    [],
                )
            ]
        )
    )
    assert "unsupported_motivation_or_consensus:s1" in errors


def test_internal_review_language_is_a_judgment_defect():
    hits = find_internal_review_language("未知不是文章的缺口，读者可以留下自己的判断。")
    assert hits
    errors = validate_editorial_judgment(
        judgment_record(),
        draft_text="未知不是文章的缺口，读者可以留下自己的判断。",
    )
    assert "internal_review_language" in errors


def test_return_to_research_is_a_valid_editorial_outcome():
    result = evaluate_editorial_judgment(
        judgment_record(
            judgment_result="return_research",
            actor_layers={
                "machine_check": {
                    "by": "editorial-review-validator",
                    "result": "pass",
                    "checked_at": "2026-09-10T11:00:00+08:00",
                },
                "model_editorial_review": {
                    "by": "grok-4.6",
                    "result": "return_research",
                    "checked_at": "2026-09-10T11:05:00+08:00",
                    "paragraph_notes": [
                        {
                            "locator": "第5段",
                            "note": "材料只够写预告节点，不够写照顾意愿。",
                        }
                    ],
                },
                "human_confirmation": {
                    "by": "allen",
                    "result": "pending",
                    "checked_at": None,
                    "attestation_ref": None,
                },
            },
            findings=[
                _finding(
                    "第5段",
                    "核心问题缺少场面",
                    "材料包只有节目标题",
                    "return_research",
                )
            ],
            scoring_evidence={
                "total_score": 70,
                "why_worth_reading": [],
            },
        )
    )
    assert result["errors"] == []
    assert result["judgment_result"] == "return_research"
    assert result["combined_result"] == "return_research"


def test_article_first_postdraft_pass_requires_content_fidelity_binding():
    record = judgment_record(
        article_first_contract_version="article-first-v1",
        content_fidelity_ref={
            "path": "review/art-001/content-fidelity.json",
            "sha256": "c" * 64,
        },
        content_fidelity_result="pass",
    )
    assert validate_editorial_judgment(record) == []

    record.pop("content_fidelity_ref")
    errors = validate_editorial_judgment(record)
    assert "content_fidelity_ref_required" in errors


def test_article_first_editorial_judgment_allows_postdraft_reader_takeaway():
    record = judgment_record(
        article_first_contract_version="article-first-v1",
        content_fidelity_ref={
            "path": "review/art-001/content-fidelity.json",
            "sha256": "c" * 64,
        },
        content_fidelity_result="pass",
        reader_takeaway="读者最后能带走的判断",
        reader_takeaway_locator="p3",
    )

    assert validate_editorial_judgment(record) == []
