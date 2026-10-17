"""test_four_area_pipeline_upgrade: 全面测试若雨影视长文四大升级模块及选题库同步。

覆盖范围：
1. 《动笔前投射对焦卡》（projection_card.py）
2. 手机排版呼吸门禁（mobile_rhythm_gate.py）
3. 爆款标题漏斗与文案实验室（title_funnel.py）
4. 发布冷启动物料包与排版收口（moyu_green_renderer.py）
5. topics.db 工业化三件套落盘与读取（topic_pipeline_sync.py）
"""
import json
import sqlite3
import pytest
from pathlib import Path

from article_group.projection_card import (
    EXPECTED_ACTIONS,
    FORBIDDEN_OFFICIAL_JARGON,
    validate_projection_card,
    generate_projection_card_from_event,
    format_projection_card_markdown,
)
from article_group.mobile_rhythm_gate import (
    check_mobile_rhythm,
    H2_MAX_COUNT,
    H2_MIN_COUNT,
    MAX_ANCHOR_GAP_CHARS,
    MAX_PARA_CHARS,
    LONG_PARA_THRESHOLD,
)
from article_group.title_funnel import (
    audit_title_health,
    build_title_funnel_pack,
    generate_title_candidates_10,
    TITLE_MAX_LEN,
    TITLE_PATTERNS,
)
from article_group.moyu_green_renderer import (
    build_cold_start_kit,
    render_moyu_green_bundle,
    write_moyu_green_run_bundle,
    RECOMMENDATION_FIXED_COUNT,
)
from article_group.topic_pipeline_sync import (
    init_topic_projections_table,
    upsert_topic_projection,
    get_topic_projection,
    sync_classic_pilot_cases_to_db,
)


# =============================================================================
# 1. 动笔前投射对焦卡测试 (Projection Card)
# =============================================================================

def test_projection_card_validation_success():
    card = {
        "self_relevance": "剥离明星滤镜后，对应普通人盲目加杠杆与中产泡沫破灭的现实生存账本。",
        "emotional_outlet": "读完这篇，读者顺出那口看伪善者人设崩塌、体面碎了一地的解气爽感。",
        "one_liner_conflict": "台前全是为梦想买单，台后全是欠薪跑路的无情算盘",
        "expected_action": "去评论区骂/倒苦水",
    }
    res = validate_projection_card(card)
    assert res["passed"] is True
    assert len(res["errors"]) == 0
    assert res["card"]["expected_action"] == "去评论区骂/倒苦水"


def test_projection_card_forbidden_official_jargon():
    card = {
        "self_relevance": "普通人的房贷压力",
        "emotional_outlet": "骂出真实心声",
        "one_liner_conflict": "以扎实推进战略布局为抓手，全面提升核心竞争力",  # 命中公文八股
        "expected_action": "去评论区骂/倒苦水",
    }
    res = validate_projection_card(card)
    assert res["passed"] is False
    assert any("one_liner_conflict_contains_official_jargon" in err for err in res["errors"])


def test_projection_card_invalid_expected_action():
    card = {
        "self_relevance": "普通人的生存代价",
        "emotional_outlet": "看清体面崩塌",
        "one_liner_conflict": "台前温情脉脉，台后全是利益算计",
        "expected_action": "转发到微信群里点赞",  # 不在合规白名单
    }
    res = validate_projection_card(card)
    assert res["passed"] is False
    assert any("invalid_expected_action" in err for err in res["errors"])


def test_projection_card_conflict_too_long():
    card = {
        "self_relevance": "普通人的生存代价",
        "emotional_outlet": "看清体面崩塌",
        "one_liner_conflict": "这句话写得太长了已经远远超过了三十个字符的硬性限制读者在手机端一眼根本无法看懂其核心矛盾是什么",
        "expected_action": "截图某句人间清醒发朋友圈",
    }
    res = validate_projection_card(card)
    assert res["passed"] is False
    assert any("conflict_too_long" in err for err in res["errors"])


def test_generate_projection_card_from_event():
    event = {
        "canonical_title": "明星独角兽公司爆雷欠薪",
        "ledger_summary": "创始人转移资产海外置业，普通员工讨薪无门背负房贷车贷。",
        "proposed_angle": "台前大谈情怀梦想，台后暗中转移资产；名利场从来不信眼泪，只信合同账本。",
        "resonance_archetype": "B_class_slip",
    }
    card = generate_projection_card_from_event(event)
    assert "创始人转移资产" in card["self_relevance"]
    assert len(card["one_liner_conflict"]) <= 30
    assert card["expected_action"] in EXPECTED_ACTIONS
    val = validate_projection_card(card)
    assert val["passed"] is True


# =============================================================================
# 2. 手机排版呼吸门禁测试 (Mobile Rhythm Gate)
# =============================================================================

SAMPLE_WELL_RHYTHMED_TEXT = """# 深度拆解标题

开篇第一句夺魂钩子，直接切入核心矛盾事实。

这里是第二段短段落，控制在七八十个字符之内，给读者充足的呼吸感。

## 01 撕开温情脉脉的遮羞布

> **金句锚点：台前全是体面，台后全是算盘。**

紧接着一个分析段落。这里的行文紧凑利落，杜绝任何对仗机器腔。

▲ Walter 在洗车行低头擦车的特写镜头

这是又一段简练叙事，字数在一百字以内，节奏舒适。

## 02 算透现实利益的真实账本

这里展开第二节的细节拉片，层层推进人性的现实抉择。

> **读者带走的一句话：成年人所有的体面，背后早标好了代价。**

## 03 人性终局的冷酷收刀

第三节给出最后的冷酷裁决。没有虚伪的大团圆，只有现实的残酷沉淀。
"""

def test_mobile_rhythm_gate_pass():
    res = check_mobile_rhythm(SAMPLE_WELL_RHYTHMED_TEXT)
    assert res["passed"] is True
    assert res["metrics"]["h2_count"] == 3
    assert res["metrics"]["overlength_count"] == 0
    assert res["metrics"]["consecutive_long_spans_count"] == 0


def test_mobile_rhythm_gate_fails_overlength_paragraph():
    long_p = "这是一个极其漫长且冗长的段落" * 15  # > 180 字符
    bad_text = f"""# 标题\n\n## 01 第一节\n\n{long_p}\n\n## 02 第二节\n\n## 03 第三节\n"""
    res = check_mobile_rhythm(bad_text)
    assert res["passed"] is False
    assert any("overlength_paragraphs_count" in err for err in res["errors"])


def test_mobile_rhythm_gate_fails_too_many_h2():
    bad_text = """# 标题\n\n## 01 A\n\n## 02 B\n\n## 03 C\n\n## 04 D\n\n## 05 E\n\n## 06 F\n"""
    res = check_mobile_rhythm(bad_text)
    assert res["passed"] is False
    assert any("h2_count_too_many_ppt_trap" in err for err in res["errors"])


def test_mobile_rhythm_gate_fails_anchor_gap():
    # 连续超过 450 字没有引用/图注/金句锚点
    dense_block = ("这是一段没有任何视觉停顿与呼吸感的纯叙事文本内容。" * 10 + "\n\n") * 3
    bad_text = f"""# 标题\n\n## 01 第一节\n\n{dense_block}\n\n## 02 第二节\n\n## 03 第三节\n"""
    res = check_mobile_rhythm(bad_text, strict_anchor_gap=True)
    assert res["passed"] is False
    assert any("anchor_gap_exceeded" in err for err in res["errors"])


# =============================================================================
# 3. 爆款标题漏斗与文案实验室测试 (Title Funnel)
# =============================================================================

def test_audit_title_health():
    # 合规好标题
    good_title = "豆瓣至今不敢开分：繁花到底扯下了谁的遮羞布？"
    res = audit_title_health(good_title)
    assert res["passed"] is True
    assert res["length"] <= TITLE_MAX_LEN
    assert "遮羞布" in res["ledger_keywords"]

    # 超长标题
    too_long = "这部在国际电影节上获得无数赞誉却在国内引发广泛争议的电影到底扯下了谁的虚伪面具与遮羞布？"
    res_long = audit_title_health(too_long)
    assert res_long["passed"] is False
    assert any("title_too_long" in err for err in res_long["errors"])

    # 包含违禁虚词
    forbidden = "浅析影视剧中的人性博弈与时代画卷"
    res_forbid = audit_title_health(forbidden)
    assert res_forbid["passed"] is False
    assert any("forbidden_empty_words" in err for err in res_forbid["errors"])


def test_build_title_funnel_pack():
    pack = build_title_funnel_pack(
        "繁花",
        "算透名利场利益账本",
        case_id="case-test",
        facts=["豆瓣9.1分", "耗资数亿元制作", "和平饭店包房暴涨"],
    )
    assert pack["case_id"] == "case-test"
    assert pack["length_limit"] == TITLE_MAX_LEN
    assert pack["is_valid_length"] is True
    assert len(pack["title_candidates_10"]) == 10
    assert "variant_A_emotional" in pack["ab_test_recommendations"]
    assert "variant_B_suspense" in pack["ab_test_recommendations"]
    assert len(pack["cover_four_word_hooks"]) >= 3


# =============================================================================
# 4. 发布冷启动物料包与排版渲染测试 (Cold Start Kit & Delivery)
# =============================================================================

def test_build_cold_start_kit():
    card = {
        "self_relevance": "普通人职场打拼的切肤之痛",
        "emotional_outlet": "痛骂伪善老好人",
        "one_liner_conflict": "台前体面温情，台后全是利益机关",
        "expected_action": "去评论区骂/倒苦水",
    }
    tp = {
        "cover_four_word_hooks": ["撕破体面", "现实账本", "绝情算盘"],
    }
    kit = build_cold_start_kit(
        title="测试标题",
        work_name="繁花",
        killer_stance="算透名利场的残酷底牌",
        projection_card=card,
        title_pack=tp,
    )
    assert "【置顶讨论】" in kit["pinned_comment"]
    assert len(kit["pinned_comment"]) <= 50
    assert "欢迎留言" not in kit["pinned_comment"]
    assert "撕破体面" in kit["copy_1"] or "现实账本" in kit["copy_1"]
    assert "golden_slot" in kit
    assert "slot_reason" in kit
    assert "# 🚀 微信发布冷启动物料包" in kit["markdown"]


def test_scorer_vertical_affinity_rules():
    import sys
    sys.path.insert(0, "/home/allen/Projects/ruoyu-film-daily/scripts/topic_pipeline")
    import scorer

    # 1. 纯票房宣发通报：不予加权，且压低至 78 以下
    pr_item = {
        "overall_score": 85,
        "story_tension_score": 60,
        "resonance_archetype": "NONE",
    }
    res_pr = scorer.apply_vertical_affinity("生化危机爆发夜票房破纪录", pr_item)
    assert res_pr["overall_score"] <= 78

    # 3. 隔夜冷饭防污染（时效失效保护）：若事件存续超48小时进入 fading 衰退期，封顶 55 分一票降权防马后炮
    fading_item = {
        "overall_score": 92,
        "story_tension_score": 85,
        "resonance_archetype": "A_actor_integrity",
        "lifecycle_stage": "fading",
    }
    res_fading = scorer.apply_vertical_affinity("某老戏骨两年前金句热议", fading_item)
    assert res_fading["overall_score"] <= 55


def test_projection_card_evergreen_anchor():
    from article_group.projection_card import validate_projection_card, format_projection_card_markdown

    card_data = {
        "self_relevance": "普通人认真干活反被劝别较真，老实人被边缘化的切肤痛点。",
        "emotional_outlet": "替那些认真干活反被穿小鞋的打工人出恶气。",
        "one_liner_conflict": "老戏骨失声也要真说，流量明星拿几千万却只露脸。",
        "expected_action": "去评论区骂/倒苦水",
        "fresh_reality_anchor": "近期内娱古装剧接连被扒出主角靠替身和后期配音撑场，李雪健在《封神》含水真声拍戏的幕后片段被重新顶上热搜对照。",
    }
    val = validate_projection_card(card_data)
    assert val["passed"] is True
    assert val["card"]["fresh_reality_anchor"] == card_data["fresh_reality_anchor"]

    md = format_projection_card_markdown(val["card"])
    assert "当下现实增量触点" in md
    assert "封神" in md


def test_moyu_green_bundle_with_cold_start(tmp_path: Path):
    run_dir = tmp_path / "run_test"
    run_dir.mkdir()
    (run_dir / "draft.md").write_text(SAMPLE_WELL_RHYTHMED_TEXT, encoding="utf-8")

    manifest = write_moyu_green_run_bundle(
        run_dir,
        title="豆瓣至今不敢开分：繁花到底扯下了谁的遮羞布？",
        subtitle_points=["真实细节拉片", "现实利益算盘", "人性冷酷底牌"],
        category_tag="深度剧评 · 繁花",
        work_badge="《繁花》深度拆解",
        interaction_question="哪一个细节最让你心里一惊？",
        interaction_invite="欢迎在评论区聊聊。",
        recommendations=[{"title": "往期1", "desc": "描述1"}] * 5,
    )
    assert (run_dir / "wechat" / "body.html").is_file()
    assert (run_dir / "wechat" / "preview.html").is_file()
    assert (run_dir / "wechat" / "delivery.md").is_file()
    assert (run_dir / "wechat" / "cold-start-kit.md").is_file()
    assert "cold_start_kit" in manifest

    # 验证往期推荐 5 条红线与 delivery.md 格式
    deliv_text = (run_dir / "wechat" / "delivery.md").read_text(encoding="utf-8")
    assert deliv_text.count("📌") == RECOMMENDATION_FIXED_COUNT
    assert "### 🚀 发布冷启动物料包（Cold Start Kit）" in deliv_text


# =============================================================================
# 5. topics.db 工业化三件套落盘与读取测试 (Topic Pipeline Sync)
# =============================================================================

def test_topic_pipeline_sync_db(tmp_path: Path):
    db_file = tmp_path / "test_topics.db"
    results = sync_classic_pilot_cases_to_db(db_file)
    assert len(results) == 2
    assert results[0]["topic_id"] == "case-001"
    assert results[1]["topic_id"] == "case-008"

    conn = sqlite3.connect(db_file)
    c1 = get_topic_projection(conn, "case-001")
    assert c1 is not None
    assert c1["work_name"] == "疯癫老人日记"
    assert c1["selected_title"] == "豆瓣至今不敢开分：疯癫老人日记到底扯下了谁的遮羞布？"
    assert c1["projection_card"]["expected_action"] == "截图某句人间清醒发朋友圈"
    assert len(c1["title_funnel"]["title_candidates_10"]) == 10
    assert "【置顶讨论】" in c1["cold_start_kit"]["pinned_comment"]

    c8 = get_topic_projection(conn, "case-008")
    assert c8 is not None
    assert c8["work_name"] == "说话之道"
    assert c8["projection_card"]["expected_action"] == "去评论区骂/倒苦水"
    conn.close()
