from pathlib import Path

import pytest

from article_group.workflow import (
    BatchValidationError,
    build_controlled_run,
    validate_claim_inventory,
    validate_batch,
    validate_transition,
)


def valid_batch():
    articles = []
    for slot, work, atom, intent, angle, title in (
        ("A", "作品甲", "主角选择", "好奇", "人物代价", "作品甲里主角终于做了选择"),
        ("B", "作品乙", "观众翻转", "共鸣", "误解被看见", "作品乙最委屈的人被看见"),
        ("C", "作品丙", "幕后取舍", "惊讶", "创作代价", "作品丙删掉的结尾改变了谁"),
    ):
        articles.append(
            {
                "article_id": f"demo-{slot.lower()}",
                "slot": slot,
                "work": work,
                "primary_atom": atom,
                "reader_intent": intent,
                "angle": angle,
                "state": "R7 editorial-ready",
                "markdown_path": f"slots/{slot}/draft.md",
                "evidence_pack_path": f"slots/{slot}/evidence-pack.md",
                "writing_brief_path": f"slots/{slot}/writing-brief.md",
                "title": title,
                "claim_coverage": "complete",
                "material_claim_ids": ["claim-1"],
                "claim_mappings": [{
                    "claim_id": "claim-1",
                    "claim_text": "正文中的可验证主张",
                    "draft_locator": "正文中的可验证主张",
                    "claim_type": "fact",
                    "source_id": "source-1",
                    "locator": "p.1",
                    "support_status": "direct",
                    "limitation": "",
                }],
                "concrete_support_types": ["character", "scene"],
                "html_delivery_state": "withheld",
                "publication_authorization": "not_authorized",
            }
        )
    return {
        "run_id": "synthetic-controlled-run",
        "publication_authorization": "not_authorized",
        "articles": articles,
    }


def materialize_artifacts(batch, root: Path):
    for article in batch["articles"]:
        for field in ("markdown_path", "evidence_pack_path", "writing_brief_path"):
            target = root / article[field]
            target.parent.mkdir(parents=True, exist_ok=True)
            if field == "markdown_path":
                target.write_text("正文中的可验证主张" + "文" * 1500, encoding="utf-8")
            else:
                target.write_text("synthetic-only\n", encoding="utf-8")


def test_valid_synthetic_batch_creates_mechanically_verified_manifest(tmp_path: Path):
    batch = valid_batch()
    materialize_artifacts(batch, tmp_path)
    target = build_controlled_run(batch, tmp_path)

    payload = target.read_text(encoding="utf-8")
    assert '"state": "R7 mechanically-verified"' in payload
    assert '"state": "R8 review-ready"' not in payload
    assert '"publication_authorization": "not_authorized"' in payload
    assert '"network_actions": "none"' in payload


def test_duplicate_primary_atom_blocks_batch():
    batch = valid_batch()
    batch["articles"][2]["primary_atom"] = batch["articles"][1]["primary_atom"]

    assert "duplicate_primary_atom:观众翻转" in validate_batch(batch)


def test_incomplete_evidence_blocks_batch():
    batch = valid_batch()
    batch["articles"][0]["claim_coverage"] = "partial"

    assert "claim_coverage_incomplete:demo-a" in validate_batch(batch)


def test_html_generation_is_out_of_scope_for_controlled_run():
    batch = valid_batch()
    batch["articles"][0]["html_delivery_state"] = "generated"

    assert "html_out_of_scope_for_controlled_run:demo-a" in validate_batch(batch)


def test_unauthorized_publication_blocks_batch():
    batch = valid_batch()
    batch["publication_authorization"] = "granted"

    assert "controlled_run_must_not_authorize_publication" in validate_batch(batch)


def test_missing_declared_artifact_blocks_manifest(tmp_path: Path):
    batch = valid_batch()
    materialize_artifacts(batch, tmp_path)
    (tmp_path / batch["articles"][0]["markdown_path"]).unlink()

    with pytest.raises(BatchValidationError, match="missing_artifact_file:demo-a:markdown_path"):
        build_controlled_run(batch, tmp_path)


def test_path_escape_blocks_manifest(tmp_path: Path):
    batch = valid_batch()
    materialize_artifacts(batch, tmp_path)
    batch["articles"][0]["markdown_path"] = "../outside.md"

    with pytest.raises(BatchValidationError, match="unsafe_artifact_path:demo-a:markdown_path"):
        build_controlled_run(batch, tmp_path)


def test_empty_declared_artifact_blocks_manifest(tmp_path: Path):
    batch = valid_batch()
    materialize_artifacts(batch, tmp_path)
    (tmp_path / batch["articles"][0]["evidence_pack_path"]).write_text("   \n", encoding="utf-8")

    with pytest.raises(BatchValidationError, match="empty_artifact_file:demo-a:evidence_pack_path"):
        build_controlled_run(batch, tmp_path)


def test_claim_mappings_are_required_for_complete_coverage():
    batch = valid_batch()
    batch["articles"][0]["claim_mappings"] = []

    assert "claim_mappings_invalid:demo-a" in validate_batch(batch)


def test_valid_claim_inventory_accepts_complete_fact_mapping():
    article = valid_batch()["articles"][0]

    assert validate_claim_inventory(article, "正文中的可验证主张") == []


def test_batch_accepts_bounded_inference_without_source_locator():
    batch = valid_batch()
    article = batch["articles"][0]
    article["claim_mappings"][0] = {
        "claim_id": "claim-1",
        "claim_text": "这可以读作一次克制的告别",
        "draft_locator": "克制的告别",
        "claim_type": "inference",
        "source_id": "",
        "locator": "",
        "support_status": "inference",
        "limitation": "这是作者基于已核事实的有限解读，不是来源直接结论",
    }

    assert validate_batch(batch) == []


def test_claim_inventory_rejects_duplicate_claim_id():
    article = valid_batch()["articles"][0]
    article["material_claim_ids"] = ["claim-1", "claim-2"]
    duplicate = article["claim_mappings"][0].copy()
    duplicate["draft_locator"] = "另一处正文主张"
    article["claim_mappings"].append(duplicate)

    assert "duplicate_claim_id:demo-a:claim-1" in validate_claim_inventory(
        article, "正文中的可验证主张 另一处正文主张"
    )


def test_claim_inventory_rejects_material_and_mapping_id_mismatch():
    article = valid_batch()["articles"][0]
    article["material_claim_ids"] = ["missing"]

    errors = validate_claim_inventory(article, "正文中的可验证主张")

    assert "material_claim_ids_missing_mappings:demo-a:missing" in errors
    assert "claim_mappings_undeclared_material_claims:demo-a:claim-1" in errors


@pytest.mark.parametrize("invalid_type", [["fact"], {"fact": 1}, 1, True, None])
def test_claim_inventory_rejects_non_string_claim_type_without_crashing(tmp_path: Path, invalid_type):
    batch = valid_batch()
    materialize_artifacts(batch, tmp_path)
    batch["articles"][0]["claim_mappings"][0]["claim_type"] = invalid_type

    errors = validate_batch(batch, tmp_path)
    assert any(error.startswith("claim_mapping_invalid_type:demo-a:claim-1") for error in errors)

    with pytest.raises(BatchValidationError, match="claim_mapping_invalid_type:demo-a:claim-1"):
        build_controlled_run(batch, tmp_path)


def test_claim_inventory_requires_schema_and_type_consistent_support():
    article = valid_batch()["articles"][0]
    mapping = article["claim_mappings"][0]
    mapping.update({
        "claim_text": " ", "draft_locator": "", "claim_type": "opinion",
        "support_status": "attributed", "source_id": "", "locator": "",
    })

    errors = validate_claim_inventory(article, "正文中的可验证主张")

    assert "claim_mapping_missing:demo-a:claim-1:claim_text" in errors
    assert "claim_mapping_missing:demo-a:claim-1:draft_locator" in errors
    assert "claim_mapping_invalid_type:demo-a:claim-1:opinion" in errors


def test_claim_inventory_requires_fact_source_and_inference_limitation():
    article = valid_batch()["articles"][0]
    mapping = article["claim_mappings"][0]
    mapping["source_id"] = ""
    mapping["locator"] = ""
    errors = validate_claim_inventory(article, "正文中的可验证主张")
    assert "claim_mapping_missing_source:demo-a:claim-1" in errors
    assert "claim_mapping_missing_locator:demo-a:claim-1" in errors

    mapping.update({"claim_type": "inference", "support_status": "inference", "limitation": ""})
    assert "claim_mapping_missing_limitation:demo-a:claim-1" in validate_claim_inventory(
        article, "正文中的可验证主张"
    )


def test_claim_inventory_requires_draft_locator_in_markdown_with_normalization():
    article = valid_batch()["articles"][0]
    article["claim_mappings"][0]["draft_locator"] = "正文  中的\n可验证主张"
    assert validate_claim_inventory(article, "正文 中的 可验证主张") == []

    article["claim_mappings"][0]["draft_locator"] = "未出现的主张"
    assert "claim_mapping_draft_locator_not_found:demo-a:claim-1" in validate_claim_inventory(
        article, "正文中的可验证主张"
    )


def test_claim_inventory_preserves_word_and_paragraph_boundaries():
    article = valid_batch()["articles"][0]

    article["claim_mappings"][0]["draft_locator"] = "ab"
    assert "claim_mapping_draft_locator_not_found:demo-a:claim-1" in validate_claim_inventory(
        article, "a b"
    )

    article["claim_mappings"][0]["draft_locator"] = "甲乙"
    assert "claim_mapping_draft_locator_not_found:demo-a:claim-1" in validate_claim_inventory(
        article, "甲\n\n乙"
    )


def test_support_types_must_be_distinct_nonempty_list_values():
    batch = valid_batch()
    batch["articles"][0]["concrete_support_types"] = ["character", "character"]
    assert "insufficient_concrete_support:demo-a" in validate_batch(batch)
    batch["articles"][0]["concrete_support_types"] = "ab"
    assert "insufficient_concrete_support:demo-a" in validate_batch(batch)


def test_claim_mappings_reject_blank_fields():
    batch = valid_batch()
    batch["articles"][0]["claim_mappings"] = [{"claim_id": "  ", "source_id": "\t", "locator": "\n"}]

    errors = validate_batch(batch)

    assert "claim_mapping_missing:demo-a:0:claim_id" in errors
    assert "claim_mapping_missing:demo-a:0:claim_text" in errors
    assert "claim_mapping_missing:demo-a:0:draft_locator" in errors


def test_support_types_normalize_whitespace_before_deduplication():
    batch = valid_batch()
    batch["articles"][0]["concrete_support_types"] = ["character", " character "]

    assert "insufficient_concrete_support:demo-a" in validate_batch(batch)


def test_article_authorization_metadata_blocks_not_authorized_batch():
    batch = valid_batch()
    batch["articles"][0]["authorization_by"] = "controller"

    assert "authorization_metadata_must_be_blank_when_not_authorized" in validate_batch(batch)


def test_article_falsy_or_whitespace_authorization_metadata_blocks_not_authorized_batch():
    for value in (" ", 0, False, [], {}):
        batch = valid_batch()
        batch["articles"][0]["authorization_ref"] = value

        assert "authorization_metadata_must_be_blank_when_not_authorized" in validate_batch(batch)


def test_markdown_character_count_is_read_from_artifact(tmp_path: Path):
    batch = valid_batch()
    materialize_artifacts(batch, tmp_path)
    markdown = tmp_path / batch["articles"][0]["markdown_path"]
    markdown.write_text("短", encoding="utf-8")

    with pytest.raises(BatchValidationError, match="markdown_character_count_out_of_range:demo-a:1"):
        build_controlled_run(batch, tmp_path)


def test_review_ready_can_return_for_scoped_repair():
    validate_transition("R8 review-ready", "H3 needs-revision")


def test_terminal_draft_cannot_advance():
    with pytest.raises(BatchValidationError, match="terminal_state_cannot_advance"):
        validate_transition("H4 draft-only", "R6 drafting")


def test_invalid_transition_is_rejected():
    with pytest.raises(BatchValidationError, match="invalid_transition"):
        validate_transition("R3 slots-locked", "R6 drafting")


# --- Slice 4: mechanical green ≠ R8; promote only after Sol + controller ---


def test_validate_batch_rejects_self_declared_r8_without_review_evidence():
    batch = valid_batch()
    batch["articles"][0]["state"] = "R8 review-ready"

    assert "article_not_mechanically_eligible:demo-a:R8 review-ready" in validate_batch(batch)


def test_build_controlled_run_never_emits_r8_from_mechanical_gates_alone(tmp_path: Path):
    import json

    batch = valid_batch()
    materialize_artifacts(batch, tmp_path)
    # Even if a caller tries to pre-label R8, mechanical build must fail closed
    # rather than mint review-ready.
    batch["articles"][0]["state"] = "R8 review-ready"
    with pytest.raises(BatchValidationError, match="article_not_mechanically_eligible:demo-a"):
        build_controlled_run(batch, tmp_path)

    batch = valid_batch()
    materialize_artifacts(batch, tmp_path)
    target = build_controlled_run(batch, tmp_path)
    manifest = json.loads(target.read_text(encoding="utf-8"))
    assert manifest["state"] == "R7 mechanically-verified"
    assert all(article["state"] == "R7 mechanically-verified" for article in manifest["articles"])


@pytest.mark.parametrize(
    "sol_decision",
    ["needs_changes", "evidence_insufficient", "timeout", "review-incomplete", ""],
)
def test_promote_to_review_ready_rejects_non_approve_sol(sol_decision: str):
    from article_group.workflow import promote_to_review_ready

    manifest = {
        "state": "R7.5 awaiting-independent-review",
        "publication_authorization": "not_authorized",
        "articles": [{"article_id": "demo-a", "state": "R7.5 awaiting-independent-review"}],
    }
    with pytest.raises(BatchValidationError, match="sol_decision_not_approve"):
        promote_to_review_ready(
            manifest,
            sol_decision=sol_decision,
            controller_acceptance="accepted",
        )


@pytest.mark.parametrize(
    "controller_acceptance",
    ["", "pending", "not_accepted", "accepted with known gap", None],
)
def test_promote_to_review_ready_rejects_without_controller_accept(controller_acceptance: object):
    from article_group.workflow import promote_to_review_ready

    manifest = {
        "state": "R7.5 awaiting-independent-review",
        "publication_authorization": "not_authorized",
        "articles": [{"article_id": "demo-a", "state": "R7.5 awaiting-independent-review"}],
    }
    with pytest.raises(BatchValidationError, match="controller_acceptance_required"):
        promote_to_review_ready(
            manifest,
            sol_decision="approve",
            controller_acceptance=controller_acceptance,  # type: ignore[arg-type]
        )


def test_promote_to_review_ready_requires_mechanical_or_awaiting_source_state():
    from article_group.workflow import promote_to_review_ready

    manifest = {
        "state": "R6 drafting",
        "publication_authorization": "not_authorized",
        "articles": [{"article_id": "demo-a", "state": "R6 drafting"}],
    }
    with pytest.raises(BatchValidationError, match="manifest_not_ready_for_r8_promotion"):
        promote_to_review_ready(
            manifest,
            sol_decision="approve",
            controller_acceptance="accepted",
        )


def test_promote_to_review_ready_sets_r8_only_with_sol_approve_and_controller_accept():
    from article_group.workflow import promote_to_review_ready

    manifest = {
        "run_id": "synthetic-controlled-run",
        "state": "R7 mechanically-verified",
        "publication_authorization": "not_authorized",
        "articles": [
            {"article_id": "demo-a", "state": "R7 mechanically-verified"},
            {"article_id": "demo-b", "state": "R7 mechanically-verified"},
        ],
    }
    promoted = promote_to_review_ready(
        manifest,
        sol_decision="approve",
        controller_acceptance="approved_after_re-review",
        sol_review_ref="reviews/sol-rereview.md",
        controller_acceptance_ref="reviews/controller-acceptance.md",
    )
    assert promoted["state"] == "R8 review-ready"
    assert promoted["publication_authorization"] == "not_authorized"
    assert promoted["sol_decision"] == "approve"
    assert promoted["controller_acceptance"] == "approved_after_re-review"
    assert all(article["state"] == "R8 review-ready" for article in promoted["articles"])


def test_mechanized_state_machine_path_to_r8():
    validate_transition("R6 drafting", "R7 editorial-ready")
    validate_transition("R7 editorial-ready", "R7 mechanically-verified")
    validate_transition("R7 mechanically-verified", "R7.5 awaiting-independent-review")
    validate_transition("R7.5 awaiting-independent-review", "R8 review-ready")
    with pytest.raises(BatchValidationError, match="invalid_transition"):
        validate_transition("R7 editorial-ready", "R8 review-ready")
    with pytest.raises(BatchValidationError, match="invalid_transition"):
        validate_transition("R7 mechanically-verified", "R8 review-ready")


@pytest.mark.parametrize("bad_batch", [None, [], "batch", 0, False, (), {}])
def test_validate_batch_rejects_non_dict_batch_without_crashing(bad_batch: object):
    # {} is a dict but empty; still must not AttributeError — empty dict is valid type.
    if bad_batch == {}:
        assert isinstance(validate_batch(bad_batch), list)  # type: ignore[arg-type]
        return
    assert validate_batch(bad_batch) == ["batch_must_be_a_dict"]  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_state", [None, 1, True, False, [], {}, (), set(), "  "])
def test_promote_rejects_unhashable_or_non_string_source_state(bad_state: object):
    from article_group.workflow import promote_to_review_ready

    manifest = {
        "state": bad_state,
        "publication_authorization": "not_authorized",
        "articles": [],
    }
    with pytest.raises(BatchValidationError, match="manifest_not_ready_for_r8_promotion"):
        promote_to_review_ready(
            manifest,
            sol_decision="approve",
            controller_acceptance="accepted",
        )


@pytest.mark.parametrize(
    "sol_decision,controller_acceptance",
    [
        (" approve ", "accepted"),
        ("approve", " accepted "),
        ("Approve", "accepted"),
        ("approve\n", "accepted"),
    ],
)
def test_promote_requires_exact_sol_and_controller_labels(
    sol_decision: object, controller_acceptance: object
):
    from article_group.workflow import promote_to_review_ready

    manifest = {
        "state": "R7 mechanically-verified",
        "publication_authorization": "not_authorized",
        "articles": [],
    }
    with pytest.raises(BatchValidationError):
        promote_to_review_ready(
            manifest,
            sol_decision=sol_decision,
            controller_acceptance=controller_acceptance,
        )
