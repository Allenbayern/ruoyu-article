"""Unit tests for pilot_extensions and contract integration."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from article_group.pilot_contract import (
    PilotContractError,
    init_run,
    record_handoff,
)
from article_group.pilot_extensions import (
    check_assertion_ledger_coverage,
    classify_viral_pillar,
    evaluate_three_tier_evidence,
    freeze_title,
    prose_pilot_check,
    run_timestamp_peel_test,
    verify_title_freeze,
)


def test_classify_all_viral_pillars():
    sample_topics = [
        ("全员恶霸老实人被逼成索命鬼", "p1_honest_retaliation"),
        ("93岁老戏骨卖房破产内娱日薪208万打回原形", "p2_industry_backlash"),
        ("凡人歌中产断供房贷现金流断裂总账", "p3_survival_ledger"),
        ("李现新剧江湖神棍绝户计与杀猪盘", "p4_black_market_trap"),
        ("1400万小成本黑马逆袭打脸资本大片", "p5_grassroots_revolt"),
        ("华语地下禁片5部院线禁区尺度大到吓人", "p6_forbidden_depth"),
        ("当年冷片重温神作甄嬛传原声带时代眼泪", "p7_nostalgic_haven"),
        ("被全网笑了15年的弃妇38岁成了赢家大女主", "p8_female_resilience"),
    ]
    for topic, expected_id in sample_topics:
        res = classify_viral_pillar(topic)
        assert res["pillar_id"] == expected_id, f"Failed on {topic}"


def test_timestamp_peel_test_behavior():
    # 含有速朽时间词，但剥离后人与冲突依然坚固
    valid_candidate = {
        "title_skeleton": "今天最新热搜第一！凡人歌三十五岁现金流断裂破产总账",
        "killer_stance": "靶子是伪中产自嗨式悬浮职场，反差是顶配中产断供，结论是体面不过是现金流撑起的假象",
    }
    res_valid = run_timestamp_peel_test(valid_candidate)
    assert res_valid["passed"] is True

    # 只有单纯的时间通报，缺乏实质冲突
    invalid_candidate = {
        "title_skeleton": "今日热搜最新发布会召开",
        "killer_stance": "报道最新事件",
    }
    res_invalid = run_timestamp_peel_test(invalid_candidate)
    assert res_invalid["passed"] is False


def test_three_tier_evidence_evaluation():
    # 满血证据包
    full_pack = {
        "sensory_anchors": ["A1", "A2", "A3"],
        "core_claims": ["C1", "C2", "C3"],
        "characters": {"protagonist": "李现饰演王家贤到上官诚明"},
        "notes": "改编自天涯纪实文学原著，揭示民国江相派八大门黑产算盘机制，对照当代富豪心虚买免死金牌",
    }
    res = evaluate_three_tier_evidence(full_pack)
    assert res["passed"] is True
    assert res["score"] == 100

    # 缺损证据包（无道具、无原著）
    thin_pack = {
        "sensory_anchors": ["A1"],
        "core_claims": ["C1"],
        "notes": "普通影视简介",
    }
    res_thin = evaluate_three_tier_evidence(thin_pack)
    assert res_thin["passed"] is False
    assert len(res_thin["missing_items"]) > 0


def test_title_freeze_and_anti_tamper(tmp_path: Path):
    run_dir = tmp_path / "run_freeze"
    run_dir.mkdir()

    title = "《凡人歌》撕下的不是遮羞布，是中年人月供断裂后的命"
    frozen = freeze_title(run_dir, title)
    assert frozen["status"] == "frozen_ok"

    # 原标题验证通过
    ok, msg = verify_title_freeze(run_dir, title)
    assert ok is True

    # 篡改后验证拦截
    tampered_title = "《凡人歌》撕下的不是遮羞布，是中年人月供断裂后的命！"  # 多了个感叹号
    ok_bad, msg_bad = verify_title_freeze(run_dir, tampered_title)
    assert ok_bad is False
    assert "title_tampered_after_freeze" in msg_bad


def test_prose_pilot_melting_switch():
    bad_opening = "随着影视行业的发展，这部电影深刻探讨了复杂的人性。"
    ok_bad, msg_bad = prose_pilot_check(bad_opening)
    assert ok_bad is False
    assert "prose_pilot_melt:opening_cliche_detected" in msg_bad

    good_opening = "“那总，王总出家前留下的八十万窟窿，您看怎么平？”财务总监把审计报表往红木茶几上一拍。"
    ok_good, msg_good = prose_pilot_check(good_opening)
    assert ok_good is True


def test_assertion_ledger_coverage_levels():
    evidence_pack = {
        "core_claims": [{"claim": "李现饰演男主王家贤"}],
        "notes": "全网都在骂、十几年过去这一事实在当年通报中有记录"
    }

    # 1. 账本中有记录的时间与行为 -> 绿灯
    clean_draft = "当年全网都在骂那个角色，十几年过去，大家才看清。"
    res_clean = check_assertion_ledger_coverage(clean_draft, evidence_pack)
    assert res_clean["passed"] is True
    assert len(res_clean["errors"]) == 0

    # 2. 账本中完全没有记录的受众群体口嗨 -> 红灯 error 拦截
    wild_draft = "电视剧一开播，网友纷纷表示台词被反复引用，引发全网痛骂。"
    res_wild = check_assertion_ledger_coverage(wild_draft, {"core_claims": []})
    assert res_wild["passed"] is False
    assert any("unsupported_audience_action" in e for e in res_wild["errors"])


def test_contract_enforces_prose_pilot_on_draft(tmp_path: Path):
    init_res = init_run(tmp_path, "case-ext-01", "测试扩展")
    run_dir = Path(init_res["run_root"])

    # 前置 discovery -> topic_gate -> evidence -> planning
    for fname in ("c.json", "a.json", "e.json", "p.json"):
        (run_dir / fname).write_text("{}", encoding="utf-8")
    record_handoff(tmp_path, run_dir, "discovery", "complete", "scout", {"output_refs": ["c.json"], "artifact_refs": ["c.json"]})
    record_handoff(tmp_path, run_dir, "topic_gate", "approved", "human", {"output_refs": ["a.json"], "decision_ref": "a.json"})
    record_handoff(tmp_path, run_dir, "evidence", "complete", "evidence_researcher", {"output_refs": ["e.json"], "artifact_refs": ["e.json"]})
    record_handoff(tmp_path, run_dir, "planning", "complete", "editorial_planner", {
        "selected_title": "合规标题",
        "output_refs": ["p.json"],
        "artifact_refs": ["p.json"]
    })

    # 此时在 draft 写入含有套话八股的开篇
    draft_file = run_dir / "draft.md"
    draft_file.write_text("随着影视行业的发展，这部电影探讨了深刻的人性。\n\n后文展开...", encoding="utf-8")

    # 提交 draft 交接，期望被 prose_pilot_rejected 拦截
    with pytest.raises(PilotContractError, match="prose_pilot_rejected"):
        record_handoff(tmp_path, run_dir, "draft", "complete", "writer", {
            "output_refs": ["draft.md"],
            "artifact_refs": ["draft.md"]
        })


def test_dna_engine_mother_calibration(tmp_path: Path):
    from article_group.dna_engine import audit_draft_dna, match_dna

    # 1. 匹配 12 篇母本与母题
    match_res = match_dna("周星驰不懂人情世故底裤")
    assert match_res["detected_archetype"] == "行业争议与人物拆台"
    assert len(match_res["canonical_mother_articles"]) > 0

    # 2. 机械切碎段测试稿（一句话一行）应被拦截
    choppy_text = "# 测试标题\n\n" + "\n\n".join([f"第{i}句话短行。" for i in range(120)])
    choppy_file = tmp_path / "choppy.md"
    choppy_file.write_text(choppy_text, encoding="utf-8")
    audit_res = audit_draft_dna(choppy_file)
    assert audit_res["passed"] is False
    assert any("过度碎片化" in v or "短碎段" in v for v in audit_res["violations"])


def test_sliding_window_ledger_orphan_detection():
    from article_group.pilot_extensions import detect_ledger_orphans

    draft_text = "兼职洗车行里沾满泥水的抹布与学生讥讽的手机闪光灯成了最后的尊严。老实人被数学逼上绝路。"
    evidence_pack = {
        "core_claims": [
            {"claim_id": "C01", "assertion": "老实人被数学逼上绝路"}
        ],
        "sensory_anchors": [
            {"anchor_id": "A01", "name": "兼职洗车行里沾满泥水的抹布与学生讥讽的手机闪光灯"}
        ]
    }
    res = detect_ledger_orphans(draft_text, evidence_pack)
    assert res["passed"] is True
    assert res["absorption_rate"] == 1.0


def test_cross_batch_dedupe_entity_matching(tmp_path: Path):
    from article_group.pilot_extensions import scan_historical_published_dedupe

    articles_dir = tmp_path / "articles"
    articles_dir.mkdir()
    (articles_dir / "stephen-chow.md").write_text("# 不懂人情世故的周星驰\n\n正文...", encoding="utf-8")

    # 同作品匹配
    match_work = scan_historical_published_dedupe("《不懂人情世故的周星驰》", dsh_articles_dir=articles_dir)
    assert match_work["is_duplicate"] is True

    # 核心实体匹配
    match_entity = scan_historical_published_dedupe("周星驰掀翻名利场桌子", dsh_articles_dir=articles_dir)
    assert match_entity["is_duplicate"] is True
    assert any("周星驰" in r["historical_title"] for r in match_entity["matched_records"])


def test_moyu_green_from_run_auto_rendering(tmp_path: Path):
    from article_group.moyu_green_renderer import render_moyu_green_from_run

    run_dir = tmp_path / "run_wx"
    run_dir.mkdir()
    (run_dir / "draft.md").write_text(
        "# 测试长文标题\n\n"
        "这是第一段正文叙述。\n\n"
        "## 一、第一小节标题\n\n"
        "> **这是一句带卡片的关键金句**\n\n"
        "1. 带有数字徽章的列表项\n\n"
        "正文收尾。\n",
        encoding="utf-8",
    )
    (run_dir / "title-pack.json").write_text(json.dumps({"selected_title": "测试长文标题"}), encoding="utf-8")
    (run_dir / "article-brief.json").write_text(json.dumps({"work": "绝命毒师"}), encoding="utf-8")

    manifest = render_moyu_green_from_run(run_dir)
    assert manifest["validation"]["passed"] is True
    assert (run_dir / "wechat" / "body.html").is_file()
    assert (run_dir / "wechat" / "preview.html").is_file()
    assert (run_dir / "wechat" / "delivery.md").is_file()

