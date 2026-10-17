from pathlib import Path

from article_group.anti_ai_gate import (
    analyze_anti_ai,
    check_anti_ai,
    check_opening_hook,
    score_burstiness,
    score_phrases,
    score_punctuation_flatness,
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


def test_punctuation_em_dash_penalized():
    # 破折号过多（DeepSeek AI 味体征，>=3/千字）
    dash_heavy_text = "答案其实很简单——专注。他找到了一条路——一条所有人都忽略的路。真正的结果——是所有人都没有想到的。"
    score, det = score_punctuation_flatness(dash_heavy_text)
    assert det["em_dash_count"] == 3
    assert det["em_dash_density_1k"] > 2.5
    # 高破折号不应享受人味加分，且应被施加惩罚
    assert score >= 50.0

    # 包含设问问号的人类风味文案
    question_text = "为什么票房会突然腰斩？所有人都在找答案。但真的只是宣发的问题吗？显然不是。"
    score_q, det_q = score_punctuation_flatness(question_text)
    assert det_q["flavor_points"] >= 4
    assert score_q <= 30.0


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
    assert report_human["paragraph_passed"]


def test_check_paragraph_length():
    from article_group.anti_ai_gate import check_paragraph_length

    # 短段落通过
    short_text = "第一段很短，正常阅读体验。\n\n第二段也不长，阅读节奏明快。"
    res_short = check_paragraph_length(short_text, max_chars=180)
    assert res_short["passed"] is True
    assert res_short["count"] == 0

    # 超长段落（>180字符）报警
    long_p = "这是一段非常冗长的正文内容，作者没有在任何合适的位置进行换行或者分段，导致整整大几百字全部堆叠在一起。" * 4
    long_text = f"# 标题\n\n{long_p}\n\n普通短段落。"
    res_long = check_paragraph_length(long_text, max_chars=180)
    assert res_long["passed"] is False
    assert res_long["count"] == 1
    assert res_long["long_paragraphs"][0]["length"] > 180


# ---------------------------------------------------------------------------
# 体裁加严分组的显式标注（2026-10-15，INTEGRATION-AND-FIXLIST.md §2）
# ---------------------------------------------------------------------------

SKILL_MD = Path("/home/allen/.agents/skills/lieflat-less-ai-tone/SKILL.md")


def test_genre_tightened_group_is_explicit_and_order_preserving():
    from article_group.anti_ai_gate import (
        AI_PHRASES,
        GENRE_TIGHTENED_PHRASES,
        GENRE_TIGHTENED_RATIONALE,
        GENRE_TIGHTENED_SCOPE,
        is_genre_tightened,
    )

    # 分组必须显式声明体裁与依据（此前只存在于代码里、无法审计）
    assert GENRE_TIGHTENED_SCOPE == "wechat-longform"
    assert "SKILL.md:103-104" in GENRE_TIGHTENED_RATIONALE
    assert len(GENRE_TIGHTENED_PHRASES) == 4
    # 顺序守恒：加严组仍是 AI_PHRASES 的前 4 条，计分行为不变
    assert AI_PHRASES[: len(GENRE_TIGHTENED_PHRASES)] == GENRE_TIGHTENED_PHRASES
    assert len(AI_PHRASES) == 31
    assert not (set(GENRE_TIGHTENED_PHRASES) & set(AI_PHRASES[len(GENRE_TIGHTENED_PHRASES):]))
    # 标注助手只认加严组
    assert all(is_genre_tightened(p) for p, _ in GENRE_TIGHTENED_PHRASES)
    assert not any(is_genre_tightened(p) for p, _ in AI_PHRASES[len(GENRE_TIGHTENED_PHRASES):])


def test_genre_tightened_rationale_is_verifiable_in_skill_source():
    """标注里引用的规则源必须真的这么写——不是自述式理由。"""
    lines = SKILL_MD.read_text(encoding="utf-8").splitlines()
    first_second = lines[102]  # 1-based :103
    parallelism = lines[103]   # 1-based :104
    assert "首先" in first_second and "其次" in first_second
    assert "无差别" in first_second or "人类" in first_second
    assert "排比" in parallelism and "人类" in parallelism


def test_phrases_scoring_unchanged_by_grouping():
    """分组是纯标注重构：固定输入下加严组条目仍在计分，且命中标签可被解析出来。"""
    from article_group.anti_ai_gate import GENRE_TIGHTENED_PHRASES, score_phrases

    text = "首先，要看清账本；其次，要算清成本；最后，再谈情怀。\n\n这不仅是一次翻拍，而且是一次清算。"
    score, detail = score_phrases(text)
    assert score > 0.0
    samples = detail["samples"]  # 形如 "命中片段 (标签)"
    assert any("枚举套话：首先…其次…最后" in s for s in samples)
    assert any("句式套话：不仅…而且" in s for s in samples)
    # 加严组条目确实参与计分（非死代码）：至少一个命中样本带加严组标签
    assert any(any(label in s for _, label in GENRE_TIGHTENED_PHRASES) for s in samples)
    # 通用组仍照常参与计分（对照组）
    score2, _ = score_phrases("值得一提的是，这里还有一处细节。")
    assert score2 > 0.0


def test_invisible_watermarks_detection_and_cleaning():
    """测试零宽隐形字符水印扫描、门禁阻断与清洗功能。"""
    from article_group.anti_ai_gate import (
        clean_invisible_watermarks,
        scan_invisible_watermarks,
    )

    clean_sample = "上映第四天，票房直接腰斩到了 1800 万。张艺谋在首映礼上叹了一口气。"
    # 注入零宽隐形字符 (U+200B, U+200C, U+2060)
    watermarked_sample = f"上映第四天\u200b，票房直接\u200c腰斩到了 1800 万\u2060。张艺谋在首映礼上叹了一口气。"

    # 1. 扫描检测
    scan_res = scan_invisible_watermarks(watermarked_sample)
    assert scan_res["detected"] is True
    assert scan_res["total_count"] == 3
    assert "ZERO WIDTH SPACE (U+200B)" in scan_res["breakdown"]
    assert "ZERO WIDTH NON-JOINER (U+200C)" in scan_res["breakdown"]
    assert "WORD JOINER (U+2060)" in scan_res["breakdown"]

    # 干净文本检测
    clean_scan = scan_invisible_watermarks(clean_sample)
    assert clean_scan["detected"] is False
    assert clean_scan["total_count"] == 0

    # 2. 门禁阻断验证
    passed, report = check_anti_ai(watermarked_sample)
    assert passed is False
    assert report["watermark_passed"] is False
    assert report["watermark_count"] == 3

    # 3. 清洗剥离验证
    cleaned_text, removed_count = clean_invisible_watermarks(watermarked_sample)
    assert removed_count == 3
    assert cleaned_text == clean_sample

    # 清洗后再过门禁应 PASS
    recheck_passed, recheck_report = check_anti_ai(cleaned_text)
    assert recheck_passed is True
    assert recheck_report["watermark_passed"] is True

