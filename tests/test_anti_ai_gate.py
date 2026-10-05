from article_group.anti_ai_gate import (
    analyze_anti_ai,
    check_anti_ai,
    check_opening_hook,
    score_burstiness,
    score_phrases,
    score_vocab,
    split_sentences,
    strip_markdown,
)


def test_split_and_strip():
    md = """# 标题
这里是一段**加粗**文字，还有[链接](https://example.com)和==黄色高亮==。
这是第二句！这是第三句？
"""
    plain = strip_markdown(md)
    assert "#" not in plain
    assert "加粗" in plain
    assert "黄色高亮" in plain
    sentences = split_sentences(plain)
    assert len(sentences) == 3


def test_opening_hook_cliche():
    # 宏观套话开篇 -> 失败
    bad_intro = "# 深度影评\n\n近年来，随着中国电影工业的飞速发展，越来越多的优秀作品涌现出来。"
    res = check_opening_hook(bad_intro)
    assert not res["passed"]
    assert "近年来" in res["matched"]

    bad_intro2 = "在流媒体蓬勃发展的背景下，传统院线正遭遇前所未有的危机。"
    res2 = check_opening_hook(bad_intro2)
    assert not res2["passed"]

    # 具体的场景/台词/数字开篇 -> 通过
    good_intro = "# 深度影评\n\n上映第四天，票房直接腰斩到了 1800 万。张艺谋在首映礼上叹了一口气。"
    res3 = check_opening_hook(good_intro)
    assert res3["passed"]


def test_ai_cliches_detection():
    bad_text = (
        "不可否认，这部电影具有里程碑的意义。值得一提的是，导演不仅展现了高超的技巧，"
        "而且深入探讨了人性。综上所述，毋庸置疑，它翻开了中国电影新的一页。"
    )
    score, det = score_phrases(bad_text)
    assert det["hit_count"] >= 4
    assert score >= 50.0


def test_ai_vocab_detection():
    jargon_text = (
        "该项目聚焦底层逻辑，打造内容生态闭环，全面赋能创作者，通过全链路降本增效实现破局出圈。"
    )
    score, det = score_vocab(jargon_text)
    assert det["total_hits"] >= 5
    assert score >= 50.0


def test_burstiness_evaluation():
    # 平滑 AI 句式（每句都在 20~25 字左右）
    flat_sentences = [
        "这是一部在视觉效果上非常精致的科幻冒险题材院线电影作品。",
        "导演在镜头的调度和光影的配合上展现出了极高的专业技术水准。",
        "主要演员在角色塑造和台词表达方面同样有着非常令人信服的发挥。",
        "整部作品在节奏把控和情节推进上保持了相当平稳克制的叙事基调。",
        "然而在核心主题的深度挖掘和人物动机的合理性上仍存在一定遗憾。",
    ]
    flat_score, flat_det = score_burstiness(flat_sentences)
    assert flat_det["cv"] < 0.25
    assert flat_score > 70.0  # 高 AI 味

    # 真人突发句式（长句穿插极短句，方差大）
    lively_sentences = [
        "我当时愣住了。",
        "整整一百二十分钟的所谓史诗巨制，最后竟然把所有矛盾全部归结为一场莫名其妙的醉酒误会，这简直荒唐透顶。",
        "确实。",
        "但凡编剧稍微去翻一下历史档案，都绝对写不出这种弱智的宫廷政变桥段。",
    ]
    lively_score, lively_det = score_burstiness(lively_sentences)
    assert lively_det["max_adjacent_delta"] > 15
    assert lively_score < 40.0  # 低 AI 味


def test_check_anti_ai_overall():
    # 典型 AI 垃圾稿
    ai_article = """# 影片分析

近年来，随着影视行业的高速发展，我们迎来了新时代。

首先，不可否认的是，该剧不仅在制作上精良，而且在主题上聚焦底层逻辑，成功打造了爆款闭环。
其次，毋庸置疑的是，演员的演技具有里程碑的意义。
最后，综上所述，由此可见，这是一部革命性的伟大作品。
"""
    passed, report = check_anti_ai(ai_article, threshold=45.0)
    assert not passed
    assert report["verdict"] in ("WARN", "FAIL")
    assert not report["opening_passed"]
    assert len(report["hit_phrases"]) >= 3

    # 真人深度影评
    human_article = """# 撕掉遮羞布

上映第四天，单日票房直接跌破两千万。

院线经理没再给面子，直接把黄金场次砍掉了七成。说白了，观众早就腻味了这种既要家国情怀又要流量明星的四不像配方——
你花三个亿做特效，转头却给女主角安排了一场在爆炸现场补口红的戏？离谱。

如果连最基础的物理常识都能在绿幕前被轻易抹平，所谓的工业化，不过是一场昂贵的自嗨。
"""
    passed_human, report_human = check_anti_ai(human_article, threshold=45.0)
    assert passed_human
    assert report_human["verdict"] == "PASS"
    assert report_human["opening_passed"]
