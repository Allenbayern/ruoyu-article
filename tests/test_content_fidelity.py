from __future__ import annotations


def info(
    information_id: str,
    text: str,
    kind: str,
    body_locator: str,
    source_locator: str,
    *,
    independence_key: str | None = None,
) -> dict:
    return {
        "information_id": information_id,
        "independence_key": independence_key or information_id,
        "text": text,
        "kind": kind,
        "body_locator": body_locator,
        "source_refs": [source_locator] if source_locator else [],
        "source_locators": [source_locator] if source_locator else [],
    }


def valid_content_record(**overrides) -> dict:
    record = {
        "schema_version": "article-content-fidelity-v1",
        "article_id": "art-001",
        "body_path": "drafts/art-001/body_draft.md",
        "body_sha256": "0" * 64,
        "core_object": "门口那场争执",
        "reader_question": "这段关系为什么会改变？",
        "explanation_mechanism": "动作顺序把关系中的权力变化显出来。",
        "mechanism_locator": "p3",
        "reader_takeaway": "先看动作如何改变关系，再判断人物选择。",
        "reader_takeaway_locator": "p3",
        "hard_information": [
            info("i1", "女主在门口拦住他", "action", "p1", "source-1"),
            info("i2", "两人在门口发生争执", "scene", "p2", "source-2"),
            info("i3", "他选择先离开而不是解释", "relationship", "p3", "source-3"),
        ],
        "section_increments": [
            {
                "section_id": "s1",
                "body_locator": "p1",
                "reader_gain": "先看到拦人的具体动作。",
                "gain_kind": "action",
                "material_refs": ["source-1"],
            },
            {
                "section_id": "s2",
                "body_locator": "p2",
                "reader_gain": "再看到争执发生的场面。",
                "gain_kind": "scene",
                "material_refs": ["source-2"],
            },
            {
                "section_id": "s3",
                "body_locator": "p3",
                "reader_gain": "最后解释离开如何改变关系。",
                "gain_kind": "mechanism",
                "material_refs": ["source-3"],
            },
        ],
        "standalone_check": {
            "status": "pass",
            "object_locator": "p1",
            "problem_locator": "p1",
            "explanation_locator": "p3",
            "judgment_locator": "p3",
        },
        "result": "pass",
    }
    record.update(overrides)
    return record


def test_content_fidelity_requires_three_independent_hard_information_items():
    from article_group.content_fidelity import evaluate_content_fidelity

    result = evaluate_content_fidelity(
        valid_content_record(
            hard_information=[
                info("i1", "同一事实", "fact", "p1", "e1", independence_key="same"),
                info("i2", "同一事实换词", "fact", "p2", "e1", independence_key="same"),
            ]
        )
    )
    assert result["status"] != "pass"
    assert "hard_information_requires_at_least_3" in result["errors"]
    assert "hard_information_not_independent" in result["errors"]


def test_content_fidelity_rejects_reader_paraphrase_without_body_and_source_locators():
    from article_group.content_fidelity import validate_content_fidelity

    record = valid_content_record(
        hard_information=[
            info("i1", "人物很孤独", "reader_paraphrase", "", ""),
            info("i2", "一场争执发生在门口", "scene", "p2", "e2"),
            info("i3", "他在关系中选择沉默", "relationship", "p3", "e3"),
        ]
    )
    errors = validate_content_fidelity(record)
    assert "invalid:hard_information_kind:i1" in errors
    assert "missing:hard_information_body_locator:i1" in errors
    assert "missing:hard_information_source_locator:i1" in errors


def test_content_fidelity_does_not_treat_source_ids_as_source_locators():
    from article_group.content_fidelity import validate_content_fidelity

    record = valid_content_record()
    for item in record["hard_information"]:
        item.pop("source_locators", None)

    errors = validate_content_fidelity(record)

    assert "missing:hard_information_source_locator:i1" in errors


def test_content_fidelity_rejects_restatement_section_increment():
    from article_group.content_fidelity import validate_content_fidelity

    record = valid_content_record()
    record["section_increments"][1]["gain_kind"] = "restatement"
    assert "section_increment_restatement" in validate_content_fidelity(record)


def test_content_fidelity_requires_title_free_standalone_body():
    from article_group.content_fidelity import evaluate_content_fidelity

    result = evaluate_content_fidelity(
        valid_content_record(), body_text="# 临时标题\n\n正文"
    )
    assert "content_body_must_not_have_h1" in result["errors"]

    result = evaluate_content_fidelity(valid_content_record())
    assert result["status"] == "pass"


def test_content_fidelity_rejects_title_fields_even_when_nested():
    from article_group.content_fidelity import validate_content_fidelity

    record = valid_content_record(
        editorial_notes={"title_promise": "不应成为写作方向"}
    )
    assert "forbidden_precontent_field:title_promise" in validate_content_fidelity(record)


def test_content_fidelity_requires_two_hard_information_types():
    from article_group.content_fidelity import validate_content_fidelity

    record = valid_content_record(
        hard_information=[
            info("i1", "事实一", "fact", "p1", "e1"),
            info("i2", "事实二", "fact", "p2", "e2"),
            info("i3", "事实三", "fact", "p3", "e3"),
        ]
    )
    assert "hard_information_requires_two_types" in validate_content_fidelity(record)


def test_content_fidelity_requires_an_increment_for_each_major_body_paragraph():
    import hashlib

    from article_group.content_fidelity import validate_content_fidelity

    body = "第一段事实。\n\n第二段场面。\n\n第三段机制。\n\n第四段判断。\n"
    record = valid_content_record(body_sha256=hashlib.sha256(body.encode()).hexdigest())
    record["section_increments"] = record["section_increments"][:3]

    errors = validate_content_fidelity(record, body_text=body)

    assert "section_increment_missing_major_paragraph:p4" in errors


def _strict_content_record(**overrides):
    record = valid_content_record(
        production_contract="article-first-v1",
        brief_contract="writing-brief-v2",
        title_contract="title-pack-v1",
        legacy_compatibility=False,
        core_judgment="这段关系的变化来自一次具体选择，而不是一句表态。",
        judgment_basis=[
            {
                "locator": "p1",
                "fact_or_scene": "女主在门口拦住他",
                "explanation": "先出现主动拦截的动作。",
            },
            {
                "locator": "p3",
                "fact_or_scene": "他选择先离开而不是解释",
                "explanation": "后出现离开的选择，形成关系转向。",
            },
        ],
        judgment_strength="supported",
        reader_can_repeat=True,
        unsupported_scenario_boundary="材料不能支持两人之后是否和好，也不能推出所有观众的看法。",
    )
    record.update(overrides)
    return record


def test_strict_content_review_requires_the_repeatable_core_judgment_package():
    from article_group.content_fidelity import validate_content_fidelity

    errors = validate_content_fidelity(
        valid_content_record(
            production_contract="article-first-v1",
            brief_contract="writing-brief-v2",
            title_contract="title-pack-v1",
            legacy_compatibility=False,
        )
    )

    assert "missing:core_judgment" in errors
    assert "missing:judgment_basis" in errors
    assert "missing:judgment_strength" in errors
    assert "missing:reader_can_repeat" in errors
    assert "missing:unsupported_scenario_boundary" in errors


def test_strict_content_review_needs_two_bases_for_the_same_judgment():
    from article_group.content_fidelity import validate_content_fidelity

    record = _strict_content_record(
        judgment_basis=[
            {
                "locator": "p1",
                "fact_or_scene": "女主在门口拦住他",
                "explanation": "一个具体动作。",
            }
        ]
    )

    errors = validate_content_fidelity(record)

    assert "core_judgment_requires_two_bases" in errors


def test_strict_marker_cannot_be_downgraded_by_strict_false():
    from article_group.content_fidelity import validate_content_fidelity

    record = _strict_content_record(
        core_judgment=None,
        judgment_basis=None,
        judgment_strength=None,
        reader_can_repeat=None,
        unsupported_scenario_boundary=None,
    )

    errors = validate_content_fidelity(record, strict=False)

    assert "missing:core_judgment" in errors
    assert "missing:judgment_basis" in errors
    assert "missing:judgment_strength" in errors


def test_strict_content_review_accepts_supported_repeatable_judgment():
    from article_group.content_fidelity import evaluate_content_fidelity

    result = evaluate_content_fidelity(_strict_content_record())

    assert result["status"] == "pass"
    assert result["content_checks"]["core_judgment"]["status"] == "pass"
