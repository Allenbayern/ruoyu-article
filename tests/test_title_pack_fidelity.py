from __future__ import annotations


def valid_title_pack(**overrides) -> dict:
    record = {
        "schema_version": "article-title-pack-v1",
        "article_id": "art-001",
        "body_path": "drafts/art-001/body_draft.md",
        "body_sha256": "0" * 64,
        "content_fidelity_ref": {
            "path": "review/art-001/content-fidelity.json",
            "sha256": "1" * 64,
        },
        "created_after_content_pass": True,
        "result": "selected",
        "selected_title_id": "t1",
        "directions": [
            {
                "title_id": "t1",
                "title": "门口那场争执，改变了谁的选择？",
                "distinct_angle": "动作如何改变关系",
                "body_locators": ["p1"],
                "source_locators": ["source-1#scene"],
                "selected": True,
            }
        ],
    }
    record.update(overrides)
    return record


def test_title_pack_is_allowed_to_have_zero_directions_only_when_returning():
    from article_group.title_pack_fidelity import evaluate_title_pack

    assert evaluate_title_pack(
        valid_title_pack(
            result="return_article", directions=[], return_reason="正文仍需补材料"
        )
    )["status"] == "return_article"
    assert evaluate_title_pack(
        valid_title_pack(result="selected", directions=[])
    )["status"] != "selected"


def test_title_core_fact_is_checked_only_in_title_packaging():
    from article_group.title_pack_fidelity import validate_title_pack

    record = valid_title_pack(result="selected")
    record["directions"][0]["body_locators"] = []
    assert "title_core_fact_missing_body_support" in validate_title_pack(record)


def test_title_pack_cannot_request_body_autofill():
    from article_group.title_pack_fidelity import validate_title_pack

    record = valid_title_pack(result="revise_body")
    assert "invalid:result" in validate_title_pack(record)


def test_title_pack_rejects_body_additions_and_revision_requests():
    from article_group.title_pack_fidelity import validate_title_pack

    record = valid_title_pack(
        body_additions=["标题不应要求正文新增事实"],
        body_revision_required=True,
    )

    errors = validate_title_pack(record)

    assert "forbidden_title_pack_field:body_additions" in errors
    assert "forbidden_title_pack_field:body_revision_required" in errors


def test_selected_title_requires_exactly_one_selected_direction():
    from article_group.title_pack_fidelity import validate_title_pack

    record = valid_title_pack(
        directions=[
            {**valid_title_pack()["directions"][0], "selected": True},
            {
                "title_id": "t2",
                "title": "另一条标题",
                "distinct_angle": "另一种角度",
                "body_locators": ["p2"],
                "source_locators": ["source-2#fact"],
                "selected": True,
            },
        ]
    )
    assert "selected_title_requires_exactly_one_direction" in validate_title_pack(record)


def test_title_pack_rejects_more_than_three_directions():
    from article_group.title_pack_fidelity import validate_title_pack

    direction = valid_title_pack()["directions"][0]
    record = valid_title_pack(
        directions=[
            {**direction, "title_id": f"t{index}", "selected": index == 1}
            for index in range(1, 5)
        ]
    )
    assert "title_directions_exceed_three" in validate_title_pack(record)


def test_changed_body_invalidates_title_package(tmp_path):
    import hashlib

    from article_group.title_pack_fidelity import evaluate_title_pack

    body = tmp_path / "body_draft.md"
    original = "## 关系转向\n\n正文。\n"
    body.write_text(original, encoding="utf-8")
    record = valid_title_pack(
        body_path="body_draft.md",
        body_sha256=hashlib.sha256(original.encode()).hexdigest(),
    )
    body.write_text(original + "新增事实。\n", encoding="utf-8")

    result = evaluate_title_pack(record, body_text=body.read_text(encoding="utf-8"))

    assert "title_pack_stale_body" in result["errors"]


def test_title_review_must_bind_the_selected_title_pack():
    from article_group.title_pack_fidelity import evaluate_title_review

    title_pack = valid_title_pack()
    review = {
        "schema_version": "article-title-review-v1",
        "article_id": "art-001",
        "title_pack_ref": {
            "path": "review/art-001/title-pack.json",
            "sha256": "1" * 64,
        },
        "created_after_title_packaging": True,
        "result": "pass",
        "selected_title_id": "t2",
    }

    result = evaluate_title_review(review, title_pack=title_pack)

    assert result["status"] != "pass"
    assert "title_review_selected_title_mismatch" in result["errors"]
