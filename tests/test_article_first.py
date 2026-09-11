from __future__ import annotations


def test_article_first_transition_requires_content_pass_before_title_packaging():
    from article_group.article_first import validate_article_first_transition

    assert validate_article_first_transition("content_review", "title_packaging") == [
        "content_pass_required_before_title_packaging"
    ]
    assert validate_article_first_transition("content_passed", "title_packaging") == []


def test_title_packaging_results_have_explicit_non_autofill_routes():
    from article_group.article_first import title_packaging_route, validate_article_first_transition

    assert title_packaging_route("selected") == "title_review"
    assert title_packaging_route("return_article") == "content_review"
    assert title_packaging_route("return_material") == "material_return"
    assert validate_article_first_transition(
        "title_packaging", "material_return", decision="return_material"
    ) == []
    assert validate_article_first_transition(
        "title_packaging", "material_return", decision="selected"
    ) == ["material_return_requires_title_packaging_decision"]
    assert validate_article_first_transition(
        "title_review", "material_return", decision="return_material"
    ) == []
    assert validate_article_first_transition(
        "title_review", "title_packaging", decision="return_material"
    ) == ["title_review_invalid_decision:return_material"]


def test_content_review_can_return_to_material_intake_without_packaging_a_title():
    from article_group.article_first import validate_article_first_transition

    assert validate_article_first_transition(
        "content_review", "material_return", decision="return_material"
    ) == []


def test_title_review_pass_can_enter_final_review():
    from article_group.article_first import validate_article_first_transition

    assert validate_article_first_transition(
        "title_review", "final_review", decision="pass"
    ) == []
    assert validate_article_first_transition(
        "title_review", "final_review", decision="selected"
    ) == ["title_review_invalid_decision:selected"]


def test_precontent_fields_are_rejected_but_reader_question_is_allowed():
    from article_group.article_first import validate_phase_field_boundary

    record = {
        "reader_question": "这段关系为什么会改变？",
        "title": "临时标题",
        "title_promise": "隐形标题",
    }
    errors = validate_phase_field_boundary(record, "content")
    assert "forbidden_precontent_field:title" in errors
    assert "forbidden_precontent_field:title_promise" in validate_phase_field_boundary(
        record, "content"
    )
    assert validate_phase_field_boundary({"reader_question": "问题"}, "content") == []


def test_title_skeleton_is_allowed_only_in_discovery_phase():
    from article_group.article_first import validate_phase_field_boundary

    assert validate_phase_field_boundary({"title_skeleton": "发现信号"}, "discovery") == []
    assert "forbidden_precontent_field:title_directions" in validate_phase_field_boundary(
        {"title_directions": [{"title": "不应进入发现层"}]}, "discovery"
    )
    assert "forbidden_content_field:title_skeleton" in validate_phase_field_boundary(
        {"title_skeleton": "发现信号"}, "content"
    )


def test_reader_takeaway_is_postdraft_evidence_not_a_writing_input():
    from article_group.article_first import validate_phase_field_boundary

    record = {"reader_takeaway": "读者最后能带走的判断", "reader_takeaway_locator": "p3"}
    errors = validate_phase_field_boundary(record, "writing")
    assert "forbidden_precontent_field:reader_takeaway" in errors
    assert "forbidden_precontent_field:reader_takeaway_locator" in errors
    assert validate_phase_field_boundary(record, "content_review") == []


def test_title_phase_rejects_legacy_title_contract_fields():
    from article_group.article_first import validate_phase_field_boundary

    errors = validate_phase_field_boundary(
        {"title_promise": "旧承诺", "title_skeleton": "发现信号"}, "title"
    )

    assert "forbidden_legacy_title_field:title_promise" in errors
    assert "forbidden_discovery_field:title_skeleton" in errors


def test_article_first_record_is_identified_by_explicit_contract_version():
    from article_group.article_first import is_article_first_record

    assert is_article_first_record({"article_first_contract_version": "article-first-v1"})
    assert not is_article_first_record({"title_promise": "历史字段"})


def test_body_draft_has_no_h1_but_delivery_has_one_formal_title():
    from article_group.delivery import compose_delivery_markdown, validate_delivery_markdown

    body = "## 关系转向\n\n正文内容。"
    delivery = compose_delivery_markdown(body, "正式标题")

    assert not body.startswith("# ")
    assert delivery.startswith("# 正式标题\n\n")
    assert validate_delivery_markdown(delivery, "正式标题") == []


def test_delivery_composition_rejects_a_body_h1():
    from article_group.delivery import compose_delivery_markdown

    try:
        compose_delivery_markdown("# 临时标题\n\n正文", "正式标题")
    except ValueError as exc:
        assert str(exc) == "body_draft_must_not_have_h1"
    else:
        raise AssertionError("body H1 must not enter delivery composition")


def test_new_templates_do_not_make_title_promise_a_writing_input():
    from pathlib import Path

    brief = Path("templates/writing-brief.md").read_text(encoding="utf-8")
    topic = Path("templates/topic-card.md").read_text(encoding="utf-8")
    assert "title_promise" not in brief
    assert '"title_promise"' not in topic
    assert "body_draft.md" in brief
    assert "title_pack.json" in brief
    assert "delivery.md" in brief
