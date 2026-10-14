from article_group.article_skeleton import (
    STRUCTURES,
    build_skeleton,
    format_skeleton_markdown,
)
from article_group.article_skeleton import main as skeleton_main
from article_group.hook_generator import format_hook_pair, lint_hook
from article_group.hook_generator import main as hook_main
from article_group.topic_evaluator import evaluate_topic, format_markdown_report
from article_group.topic_evaluator import main as evaluator_main


def test_hook_generator_valid_and_invalid():
    # 正常合格 hook
    res = format_hook_pair(
        "number_led",
        "上映四天票房腰斩到1800万。",
        "耗资三个亿的工业巨制沦为院线弃儿。",
    )
    assert res["valid"] is True
    assert res["opening_len"] <= 40
    assert res["reversal_len"] <= 40

    # 开场带问号 -> 拦截
    err_q = lint_hook("为什么这部大片三天就扑街了？", "因为剧情根本无法自圆其说。")
    assert any("问句" in e for e in err_q)

    # 包含填充词 -> 拦截
    err_filler = lint_hook("其实导演想要表达的很多。", "然后观众根本不买账。")
    assert any("其实" in e for e in err_filler)
    assert any("然后" in e for e in err_filler)

    # 包含破折号 -> 拦截
    err_dash = lint_hook("一部史诗——彻底崩塌。", "只留下一声叹息。")
    assert any("破折号" in e for e in err_dash)


def test_hook_generator_cli():
    rc = hook_main(["--opening", "成本三个亿票房两千万。", "--reversal", "资本用最贵的方式交了一次学费。"])
    assert rc == 0


def test_topic_evaluator_verdicts():
    # 高分选题 -> GO
    high_scores = {
        "traffic_potential": 9.0,
        "persona_fit": 9.0,
        "differentiation": 8.5,
        "evergreen_value": 8.0,
        "penetration": 8.5,
        "evidence_feasibility": 8.0,
        "compliance_safety": 9.0,
    }
    rep_high = evaluate_topic(title="拆解某大片扑街机制", scores=high_scores)
    assert rep_high["verdict"] == "GO"
    assert rep_high["total_score"] >= 75.0

    # 中分选题 -> PIVOT (需带建议)
    mid_scores = {
        "traffic_potential": 6.0,
        "persona_fit": 6.0,
        "differentiation": 5.0,  # 差异化低
        "evergreen_value": 6.0,
        "penetration": 6.0,
        "evidence_feasibility": 5.0,
        "compliance_safety": 8.0,
    }
    rep_mid = evaluate_topic(title="普通娱乐八卦", scores=mid_scores)
    assert rep_mid["verdict"] == "PIVOT"
    assert len(rep_mid["recommendations"]) > 0

    # 低分选题 -> DROP
    low_scores = {
        "traffic_potential": 4.0,
        "persona_fit": 3.0,
        "differentiation": 4.0,
        "evergreen_value": 3.0,
        "penetration": 4.0,
        "evidence_feasibility": 4.0,
        "compliance_safety": 5.0,
    }
    rep_low = evaluate_topic(title="纯八卦无聊通稿", scores=low_scores)
    assert rep_low["verdict"] == "DROP"
    assert rep_low["total_score"] < 55.0

    # 空分数不能虚假 GO，必须为 UNVERIFIED
    rep_empty = evaluate_topic(title="未打分选题", scores={})
    assert rep_empty["verdict"] == "UNVERIFIED"
    assert rep_empty["total_score"] == 0.0


def test_topic_evaluator_markdown_format():
    scores = {"traffic_potential": 8.0, "persona_fit": 8.0}
    rep = evaluate_topic(title="测试选题", scores=scores)
    md = format_markdown_report(rep)
    assert "# 选题可行性评估报告" in md
    assert "综合得分" in md


def test_article_skeleton_builder():
    skel = build_skeleton(
        topic="封神第一部魔改争议",
        structure_type="contrarian",
        killer_stance="它不是商业烂片，而是中国神话电影工业第一次真正拥有骨骼的成人礼",
        sensory_anchors=["雷震子啃桃核", "殷寿脱下染血战袍", "城墙碎裂的瓦砾声"],
        target_words=2400,
    )
    assert skel["structure_name"] == STRUCTURES["contrarian"]["name"]
    assert skel["stance_valid"] is True
    assert skel["anchors_count"] == 3
    assert len(skel["sections"]) == 5
    assert skel["sections"][0]["target_cjk_words"] > 0

    # 端水立场检测
    skel_weak = build_skeleton(
        topic="争议电影",
        structure_type="contrarian",
        killer_stance="这事两边都有道理，见仁见智吧",
    )
    assert skel_weak["stance_valid"] is False

    # Markdown 输出
    md = format_skeleton_markdown(skel)
    assert "开篇破冰契约" in md
    assert "雷震子啃桃核" in md


def test_article_skeleton_cli():
    rc = skeleton_main([
        "影评测试",
        "--stance", "这是一场虚伪的资本自嗨而观众早已识破",
        "--anchors", "染血衣带,雨夜破庙,折断的长剑",
    ])
    assert rc == 0
