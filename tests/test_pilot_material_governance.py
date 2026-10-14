"""Unit tests for material governance: capability, stripped body, uncertainty fallback and orphan detection."""

from __future__ import annotations

from pathlib import Path
import pytest

from article_group.pilot_extensions import (
    validate_source_capabilities,
    generate_source_stripped_body,
    resolve_uncertainty_sheet,
    detect_ledger_orphans,
)


def test_validate_source_capabilities():
    # 1. 低权能信源 + 长直接引语 -> 违规拦截
    draft_with_quote = "某人公开声称：“这是一个非常漫长而且没有经过任何核实的长引述内容，必须被拦截。”"
    low_manifest = {
        "sources": [{"source_id": "s1", "source_role": "page_metadata"}]
    }
    res_low = validate_source_capabilities(draft_with_quote, low_manifest)
    assert res_low["passed"] is False
    assert len(res_low["violations"]) > 0

    # 2. 一手专访/原声信源 -> 正常放行
    high_manifest = {
        "sources": [{"source_id": "s2", "source_role": "confirmed-primary"}]
    }
    res_high = validate_source_capabilities(draft_with_quote, high_manifest)
    assert res_high["passed"] is True


def test_generate_source_stripped_body():
    raw_draft = """# 标题

![图片描述](images/01.jpg)

这是作者的核心观点段落，论证名利场的人情世故全是虚伪算盘。

“这是一句长达三十多个字符的直接引用台词或外部材料复述，应当在透视稿中被抽干处理。”

这是作者的冷面收刀总结，算清利益账本。
"""
    res = generate_source_stripped_body(raw_draft)
    assert res["raw_cjk_chars"] > res["stripped_cjk_chars"]
    assert "核心观点段落" in res["stripped_body"]
    assert "冷面收刀总结" in res["stripped_body"]
    assert res["compression_ratio"] > 0


def test_resolve_uncertainty_sheet_conservative_fallback():
    sheet = {
        "pending_items": [
            {
                "id": "U01",
                "item": "某人是否获得过某大奖",
                "recommendation": "不写具体大奖名称，按保守口径处理",
                "blocking": False,
            },
            {
                "id": "U02",
                "item": "涉及刑案的生死事实",
                "recommendation": "需人工确认",
                "blocking": True,
            },
        ]
    }

    # 1. 人类未作答 -> U02 blocking 阻断，U01 自动保守回退
    res_unresolved = resolve_uncertainty_sheet(sheet, human_decisions=None)
    assert res_unresolved["passed"] is False
    assert any("blocking_uncertainty_unresolved:U02" in e for e in res_unresolved["blocking_errors"])
    fallback_u01 = [item for item in res_unresolved["resolved_items"] if item["id"] == "U01"][0]
    assert fallback_u01["status"] == "conservative_fallback_applied"

    # 2. 人类回答了 U02 -> 顺利通过
    res_resolved = resolve_uncertainty_sheet(sheet, human_decisions={"U02": "人工核实无误"})
    assert res_resolved["passed"] is True
    assert len(res_resolved["blocking_errors"]) == 0


def test_detect_ledger_orphans():
    evidence_pack = {
        "core_claims": [
            {"claim_id": "C01", "assertion": "周星驰在片场极其苛求细节"},
            {"claim_id": "C02", "assertion": "完全未被正文引用的孤儿主张事实"},
        ],
        "sensory_anchors": [
            {"anchor_id": "A01", "name": "片场第八个真啤酒瓶"},
        ]
    }

    # 1. 充分消化 -> 放行
    absorbed_draft = "周星驰在片场极其苛求细节，黄一飞被片场第八个真啤酒瓶砸得头破血流。"
    res_absorbed = detect_ledger_orphans(absorbed_draft, evidence_pack)
    assert res_absorbed["passed"] is True
    assert res_absorbed["absorption_rate"] >= 0.60

    # 2. 严重未消化（只有一句话，其余全成孤儿） -> 警告
    poor_draft = "这是完全无关的正文内容，随便写写。"
    res_poor = detect_ledger_orphans(poor_draft, evidence_pack)
    assert res_poor["passed"] is False
    assert len(res_poor["warnings"]) > 0


def test_moyu_green_renderer_and_redlines():
    from article_group.moyu_green_renderer import render_moyu_green_bundle, validate_moyu_green_html

    sample_md = """# 测试主标题

开篇第一段。

## 一、小节标题

**独立金句卡片**

正文段落带**加粗词**。
"""
    bundle = render_moyu_green_bundle(
        sample_md,
        title="测试主标题",
        subtitle_points=["看点一", "看点二"],
        category_tag="深度解剖",
        work_badge="绝命毒师",
        interaction_question="你怎么选？",
        interaction_invite="欢迎在评论区聊聊。",
        recommendations=[
            {"title": "《推荐一》", "desc": "看点描述一"},
            {"title": "《推荐二》", "desc": "看点描述二"},
        ],
    )
    val = validate_moyu_green_html(bundle["body_html"])
    assert val["passed"] is True
    assert val["errors"] == []
    assert val["leaf_span_count"] > 10


def test_human_material_approval_gate_blocks_planning(tmp_path: Path):
    from article_group.pilot_contract import PilotContractError, init_run, record_handoff

    res = init_run(tmp_path, "case-mat-gate", "素材放行门测试")
    run_dir = Path(res["run_root"])

    for fname in ("c.json", "a.json", "e.json", "p.json"):
        (run_dir / fname).write_text("{}", encoding="utf-8")

    record_handoff(tmp_path, run_dir, "discovery", "complete", "scout", {"output_refs": ["c.json"], "artifact_refs": ["c.json"]})
    record_handoff(tmp_path, run_dir, "topic_gate", "approved", "human", {"output_refs": ["a.json"], "decision_ref": "a.json"})
    # evidence 阶段显式标记 human_material_approved=False（尚未经人工放行素材）
    record_handoff(
        tmp_path,
        run_dir,
        "evidence",
        "complete",
        "evidence_researcher",
        {"output_refs": ["e.json"], "artifact_refs": ["e.json"], "human_material_approved": False},
    )

    with pytest.raises(PilotContractError, match="human_material_approval_required_before_planning"):
        record_handoff(
            tmp_path,
            run_dir,
            "planning",
            "complete",
            "editorial_planner",
            {"selected_title": "合规标题", "output_refs": ["p.json"], "artifact_refs": ["p.json"]},
        )


def test_claim_source_provenance_blocks_unanchored_fabrication(tmp_path: Path):
    from article_group.pilot_adapters import evidence_sources_adapter
    from article_group.pilot_extensions import verify_claims_anchored_in_sources

    run_dir = tmp_path / "run_prov"
    run_dir.mkdir()

    evidence_sources_adapter(
        run_dir,
        [
            {
                "source_id": "src-real",
                "title": "权威来源快照",
                "url": "https://example.com/1",
                "text": "这是一份经过抓取落盘的真实长文记录，明确记载老白手算家庭活命预算合计737,000美元，房贷结清107,000美元。",
                "source_role": "confirmed-primary",
            }
        ],
    )

    # 1. 真实锚定的事实 -> 通过
    good_pack = {
        "source_facts": [
            {"source_id": "src-real", "fact": "老白手算家庭活命预算合计737,000美元"},
        ]
    }
    res_good = verify_claims_anchored_in_sources(run_dir, good_pack)
    assert res_good["passed"] is True

    # 2. 静态脑补、原文根本没有的事实 -> 拦截
    bad_pack = {
        "source_facts": [
            {"source_id": "src-real", "fact": "他拿过三次奥斯卡终身成就大奖"},
        ]
    }
    res_bad = verify_claims_anchored_in_sources(run_dir, bad_pack)
    assert res_bad["passed"] is False
    assert any("fact_not_anchored_in_source" in e for e in res_bad["errors"])


def test_historical_published_dedupe_scanner(tmp_path: Path):
    from article_group.pilot_extensions import scan_historical_published_dedupe

    hist_dir = tmp_path / "hist_articles"
    hist_dir.mkdir()
    (hist_dir / "old-1.md").write_text("# 大婚当夜惨遭灭门：李现《我不是大师》把绝户计拍绝了\n\n正文", encoding="utf-8")

    dup = scan_historical_published_dedupe("想再写一篇《我不是大师》的江湖骗局", dsh_articles_dir=hist_dir)
    assert dup["is_duplicate"] is True
    assert dup["status"] == "conflict_detected"

    clean = scan_historical_published_dedupe("全新选题《绝命毒师》老白账本", dsh_articles_dir=hist_dir)
    assert clean["is_duplicate"] is False
    assert clean["status"] == "clean"


def test_title_targeted_search_plan_on_freeze():
    from article_group.pilot_extensions import build_title_targeted_search_plan

    plan = build_title_targeted_search_plan("砸3个亿实景拍了118天！《敦煌英雄》撕碎了大导的遮羞布")
    assert plan["subject"] == "敦煌英雄"
    assert len(plan["numbers_to_verify"]) >= 2
    assert len(plan["tier1_fact_queries"]) >= 1
    assert len(plan["tier3_scene_queries"]) >= 1


def test_zhuque_gate_adapter_honest_not_run(tmp_path: Path):
    from article_group.pilot_extensions import run_zhuque_gate_check

    draft = tmp_path / "draft.md"
    draft.write_text("# 标题\n\n正文内容", encoding="utf-8")
    res = run_zhuque_gate_check(draft, execute_live=False)
    assert res["status"] == "not_run"
    assert res["advisory"] is True


def test_number_and_quote_coverage_in_assertion_ledger():
    from article_group.pilot_extensions import check_assertion_ledger_coverage

    ev = {"notes": "化疗自费部分九万美元，台词：我才是那个去敲门的人"}
    draft_bad = "五十岁的老头在二十四小时后收到九万美元账单，大喊：“这是我随口编造的一句假台词！”"
    res = check_assertion_ledger_coverage(draft_bad, ev)
    assert "五十岁" in res["unsupported_numbers"]
    assert "二十四小时" in res["unsupported_numbers"]
    assert "九万美元" not in res["unsupported_numbers"]
    assert len(res["unsupported_quotes"]) == 1


def test_l2_contract_validator_rejects_string_findings_and_downgrades_approve():
    from article_group.pilot_extensions import validate_and_normalize_l2_review

    # 1. findings 写成字符串数组 -> 报错
    bad_schema = {
        "decision": "approve",
        "scope_reviewed": ["draft.md"],
        "findings": ["这是一条未按对象格式写的finding"],
        "non_findings": [],
        "coverage_gaps": [],
    }
    res_bad = validate_and_normalize_l2_review(bad_schema)
    assert res_bad["valid"] is False
    assert res_bad["effective_decision"] == "needs_changes"

    # 2. 有 major finding 却声称 approve -> 自动降级并报错
    contradict = {
        "decision": "approve",
        "scope_reviewed": ["draft.md"],
        "findings": [
            {
                "severity": "major",
                "target": "draft.md:1",
                "evidence": "ev",
                "counterexample_or_failure_mode": "fail",
                "required_fix": "fix",
                "recheck": "recheck",
            }
        ],
        "non_findings": [],
        "coverage_gaps": [],
    }
    res_contra = validate_and_normalize_l2_review(contradict)
    assert res_contra["valid"] is False
    assert res_contra["downgraded"] is True
    assert res_contra["effective_decision"] == "needs_changes"


def test_dangling_markdown_image_reference_blocked(tmp_path: Path):
    from article_group.pilot_extensions import check_markdown_image_integrity

    draft = "# 标题\n\n![假图](images/non_existent_01.jpg)\n\n正文。"
    res = check_markdown_image_integrity(draft, tmp_path)
    assert res["passed"] is False
    assert "images/non_existent_01.jpg" in res["dangling_images"]


def test_cross_stage_artifact_hash_binding_catches_stale_wechat_or_l2(tmp_path: Path):
    import json
    from article_group.pilot_extensions import verify_artifact_hash_bindings

    run_dir = tmp_path / "run_bind"
    (run_dir / "review").mkdir(parents=True)
    (run_dir / "wechat").mkdir(parents=True)

    (run_dir / "draft.md").write_text("# 新稿\n\n改动后的正文", encoding="utf-8")
    (run_dir / "review" / "l2-adversarial-review.json").write_text(
        json.dumps({"decision": "approve", "reviewed_draft_sha256": "0" * 64}),
        encoding="utf-8",
    )
    (run_dir / "wechat" / "wechat-manifest.json").write_text(
        json.dumps({"source_draft_sha256": "f" * 64}),
        encoding="utf-8",
    )

    res = verify_artifact_hash_bindings(run_dir)
    assert res["passed"] is False
    assert any("stale_l2_review_hash_mismatch" in e for e in res["errors"])
    assert any("stale_wechat_render_hash_mismatch" in e for e in res["errors"])



