import json

from article_group.rule_compliance import (
    build_source_stripped,
    evaluate_article_rule_evidence,
    validate_rule_compliance,
)


def record(**overrides):
    value = {
        "article_id": "art-001",
        "article_mode": "setting_observation",
        "required_source_roles": ["official_fact"],
        "sources": [{"source_id": "s1", "source_role": "official_fact", "supports_mode": ["setting_observation"], "cannot_support": ["scene_action", "dialogue", "audience_consensus", "ending"], "source_capability": "character_setup"}],
        "claims": [{"claim_id": "c1", "claim_level": "character_setup", "source_refs": ["s1"], "source_locators": ["p1"]}],
    }
    value.update(overrides)
    return value


def test_valid_setting_observation():
    assert validate_rule_compliance(record(), source_stripped_text="《作品》中的人物面对关系冲突，并作出一个选择。这个选择改变了两个人之后的相处方式，也让读者看见了代价。" ) == []


def test_rejects_non_enum_mode():
    assert "invalid:article_mode" in validate_rule_compliance(record(article_mode="craft_observation"), source_stripped_text="人物面对冲突并作出选择。")


def test_rejects_official_synopsis_as_viewing_commentary():
    errors = validate_rule_compliance(record(article_mode="viewing_commentary", required_source_roles=["scene"]), source_stripped_text="人物面对冲突并作出选择。")
    assert "material_roles_do_not_cover_mode" in errors


def test_reported_feature_accepts_media_report_role():
    # 2026-09-16 扩展：报道式特稿以媒体稿件为主证据是诚实角色。
    value = record(
        article_mode="reported_feature",
        required_source_roles=["media_report"],
        sources=[{
            "source_id": "s1",
            "source_role": "media_report",
            "supports_mode": ["reported_feature"],
            "cannot_support": ["scene_action", "dialogue", "audience_consensus", "ending"],
            "source_capability": "mechanism",
        }],
        claims=[{"claim_id": "c1", "claim_level": "mechanism", "source_refs": ["s1"], "source_locators": ["p1"]}],
    )
    assert "material_roles_do_not_cover_mode" not in validate_rule_compliance(value, source_stripped_text="人物面对冲突并作出选择。")


def test_reported_feature_accepts_commentary_role():
    # 2026-09-16 扩展：正规媒体评论/时评文章（事实部分可核查）可作报道式特稿主证据。
    value = record(
        article_mode="reported_feature",
        required_source_roles=["commentary"],
        sources=[{
            "source_id": "s1",
            "source_role": "commentary",
            "supports_mode": ["reported_feature"],
            "cannot_support": ["scene_action", "dialogue", "audience_consensus", "ending"],
            "source_capability": "mechanism",
        }],
        claims=[{"claim_id": "c1", "claim_level": "event_exists", "source_refs": ["s1"], "source_locators": ["p1"]}],
    )
    assert "material_roles_do_not_cover_mode" not in validate_rule_compliance(value, source_stripped_text="人物面对冲突并作出选择。")


def test_rejects_missing_cannot_support():
    source = dict(record()["sources"][0]); source.pop("cannot_support")
    assert any(error.startswith("missing:cannot_support") for error in validate_rule_compliance(record(sources=[source]), source_stripped_text="人物面对冲突并作出选择。"))


def test_rejects_forbidden_scene_claim():
    errors = validate_rule_compliance(record(claims=[{"claim_id": "c1", "claim_level": "scene_action", "source_refs": ["s1"], "source_locators": ["p1"]}]), source_stripped_text="人物面对冲突并作出选择。")
    assert "claim_level_forbidden:c1" in errors


def test_rejects_claim_above_source_capability():
    errors = validate_rule_compliance(
        record(claims=[{"claim_id": "c1", "claim_level": "scene_action", "source_refs": ["s1"], "source_locators": ["p1"]}]),
        source_stripped_text="人物面对冲突并作出选择，关系因此发生改变并留下长期影响。",
    )
    assert "claim_level_exceeds_source_capability:c1:s1" in errors


def test_stripped_copy_removes_meta_terms():
    assert "官方页面" not in build_source_stripped("官方页面写了人物面对冲突。")


def test_persisted_evidence_requires_current_artifacts(tmp_path):
    (tmp_path / "brief.md").write_text("article_mode: setting_observation\n", encoding="utf-8")
    (tmp_path / "task.md").write_text("article_mode: setting_observation\n", encoding="utf-8")
    (tmp_path / "material.json").write_text(json.dumps({"article_mode": "setting_observation", "required_source_roles": ["official_fact"]}), encoding="utf-8")
    (tmp_path / "source-manifest.json").write_text(json.dumps({"sources": [{"source_id": "s1", "source_role": "official_fact", "supports_mode": ["setting_observation"], "cannot_support": ["scene_action", "dialogue", "audience_consensus", "ending"], "source_capability": "character_setup"}]}), encoding="utf-8")
    (tmp_path / "delivery.md").write_text("# 标题\n\n《作品》中的人物面对冲突，并作出一个选择。这个选择改变了关系，也改变了他之后面对世界的方式。", encoding="utf-8")
    stripped = "# 标题\n\n《作品》中的人物面对冲突，并作出一个选择。这个选择改变了关系，也改变了他之后面对世界的方式。"
    (tmp_path / "stripped.md").write_text(stripped, encoding="utf-8")
    rule_record = record()
    rule_record.update({"source_stripped_path": "stripped.md", "source_stripped_readability_path": "human.json"})
    (tmp_path / "rule.json").write_text(json.dumps(rule_record), encoding="utf-8")
    import hashlib
    artifact = (tmp_path / "delivery.md").read_bytes()
    stripped_bytes = (tmp_path / "stripped.md").read_bytes()
    (tmp_path / "human.json").write_text(json.dumps({"schema_version": "article-rule-compliance-v1", "mode_check": "PASS", "material_layer_check": "PASS", "official_boundary_check": "PASS", "source_stripped_readability": "PENDING", "reviewed_artifact_sha256": hashlib.sha256(artifact).hexdigest(), "reviewed_source_stripped_sha256": hashlib.sha256(stripped_bytes).hexdigest(), "publication_authorization": "not_authorized"}), encoding="utf-8")
    article = {"article_id": "art-001", "article_mode": "setting_observation", "required_source_roles": ["official_fact"], "brief_path": "brief.md", "task_card_path": "task.md", "material_pack_path": "material.json", "rule_compliance_path": "rule.json", "delivery_path": "delivery.md", "source_stripped_path": "stripped.md", "source_stripped_readability_path": "human.json"}
    result = evaluate_article_rule_evidence(tmp_path, {"article_mode": "setting_observation", "required_source_roles": ["official_fact"], "source_manifest_path": "source-manifest.json"}, article)
    assert result["status"] == "PENDING"
    assert "source_stripped_readability_pending" in result["errors"]

    tampered = record()
    tampered["sources"] = [dict(tampered["sources"][0], source_capability="mechanism")]
    (tmp_path / "rule.json").write_text(json.dumps(tampered), encoding="utf-8")
    result = evaluate_article_rule_evidence(tmp_path, {"article_mode": "setting_observation", "required_source_roles": ["official_fact"], "source_manifest_path": "source-manifest.json"}, article)
    assert result["status"] == "FAIL"
    assert "source_manifest_source_capability_mismatch:s1" in result["errors"]
