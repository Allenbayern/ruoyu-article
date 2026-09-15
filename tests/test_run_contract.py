from __future__ import annotations

from article_group.run_contract import (
    REQUIRED_RUN_CONTRACT,
    is_explicit_legacy_compatibility,
    is_strict_run_contract,
    validate_phase_contract_fields,
    validate_referenced_contract_artifacts,
    validate_run_contract,
)


def strict_run(**overrides):
    record = dict(REQUIRED_RUN_CONTRACT)
    record.update(overrides)
    return record


def test_new_article_first_run_requires_the_exact_run_contract():
    assert validate_run_contract(strict_run()) == []
    assert is_strict_run_contract(strict_run()) is True


def test_explicit_new_run_missing_contract_is_a_contract_mismatch():
    errors = validate_run_contract(
        {"production_contract": "article-first-v1", "brief_contract": "writing-brief-v2"}
    )

    assert "contract_mismatch" in errors
    assert "missing:title_contract" in errors
    assert "missing:legacy_compatibility" in errors


def test_explicit_new_run_rejects_legacy_contract_values():
    errors = validate_run_contract(
        strict_run(
            brief_contract="writing-brief-v1",
            title_contract="title-first-v1",
            legacy_compatibility=True,
        )
    )

    assert "contract_mismatch" in errors
    assert "mismatch:brief_contract" in errors
    assert "mismatch:title_contract" in errors
    assert "legacy_compatibility_must_be_false" in errors


def test_strict_phase_rejects_legacy_title_field_even_when_capitalized():
    errors = validate_phase_contract_fields(
        {"Title": "旧标题", "title_promise": "旧承诺"}, "content"
    )

    assert "contract_mismatch" in errors
    assert "forbidden_precontent_field:title" in errors
    assert "forbidden_precontent_field:title_promise" in errors


def test_historical_unannotated_record_remains_compatibility_only():
    historical = {"article_first_contract_version": "article-first-v1"}

    assert is_strict_run_contract(historical) is False
    assert validate_run_contract(historical, require_explicit=False) == []


def test_explicit_legacy_compatibility_marker_is_a_declared_compatibility_lane():
    historical = {
        "article_first_contract_version": "article-first-v1",
        "legacy_compatibility": True,
    }

    assert is_explicit_legacy_compatibility(historical) is True
    assert is_strict_run_contract(historical) is False
    assert validate_run_contract(historical) == []


def test_strict_run_rejects_legacy_title_fields_at_run_boundary():
    errors = validate_run_contract(strict_run(Title="不应出现"))

    assert "contract_mismatch" in errors
    assert "forbidden_run_field:title" in errors


def test_strict_run_rejects_a_root_title_even_when_lowercase():
    errors = validate_run_contract(strict_run(title="不应出现在 run 根"))

    assert "forbidden_run_field:title" in errors


def test_strict_run_scans_referenced_brief_for_legacy_title_inputs(tmp_path):
    brief = tmp_path / "writing-brief.md"
    brief.write_text("Title: 旧标题\ntitle_promise: 旧承诺\n", encoding="utf-8")
    run = strict_run(articles=[{"writing_brief_path": "writing-brief.md"}])

    errors = validate_referenced_contract_artifacts(tmp_path, run)

    assert "contract_mismatch" in errors
    assert "forbidden_precontent_field:title" in errors
    assert "forbidden_precontent_field:title_promise" in errors


def test_strict_run_does_not_mistake_downstream_placeholders_for_legacy_brief_fields(tmp_path):
    brief = tmp_path / "writing-brief.md"
    brief.write_text(
        "title_pack_path: content_passed 后填写\n"
        "title_review_path: 标题复核后填写\n"
        "selected_title_id: 标题包选定后填写\n",
        encoding="utf-8",
    )
    run = strict_run(articles=[{"writing_brief_path": "writing-brief.md"}])

    assert validate_referenced_contract_artifacts(tmp_path, run) == []


def test_strict_run_rejects_legacy_fields_nested_in_article_records():
    errors = validate_run_contract(
        strict_run(
            articles=[
                {
                    "state": "content_review",
                    "Title": "旧标题",
                    "title_promise": "旧承诺",
                }
            ]
        )
    )

    assert "contract_mismatch" in errors
    assert any("articles" in error and "Title" in error for error in errors)
    assert any("title_promise" in error for error in errors)


def test_strict_material_phase_allows_source_metadata_title():
    errors = validate_phase_contract_fields(
        {"sources": [{"source_id": "s1", "title": "来源页面标题"}]},
        "material",
    )

    assert errors == []
