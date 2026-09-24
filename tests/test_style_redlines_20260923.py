"""RED tests for the 2026-09-23 landing batch (taboo-topics-001 lessons).

Every negative sample here is a verbatim or near-verbatim string that actually
shipped in that run and was caught by the controller or by L2:

- controller verdict on the 周也 draft: "不知所云" — the two early versions
  defended the drama's dubbing and the fan reading instead of taking a side;
- L2 blocker: 古装武侠角色被写成"中枪身亡";
- L2 major: a fabricated long netizen quote in double quotation marks;
- L2 minor: "试图通过咬牙切齿…拼命够到对方的气场" (mind-reading);
- controller verdict on both early drafts: 1000 字出头, 单薄, 缺阅读性.

These gate the *mechanism*, not the wording: each test names the rule it
protects so a future refactor cannot quietly drop it.
"""

from __future__ import annotations

import pytest

from article_group.style_gate import (
    DEPTH_FLOOR_CJK_CHARS,
    scan_style,
    sensory_anchor_check,
    depth_floor_check,
    validate_markdown_text,
)


def _rules(text: str) -> set[str]:
    return {hit["rule"] for hit in scan_style(text)}


def _errors(text: str) -> set[str]:
    return {
        hit["rule"]
        for hit in scan_style(text)
        if hit["severity"] == "error"
    }


# --- 1) 公关和稀泥腔：error -------------------------------------------------


@pytest.mark.parametrize(
    "sample",
    [
        "两种说法都有人认，谁也说服不了谁。",
        "替她说话的人理由也硬，她的处境其实情有可原。",
        "这件事两边都有道理，观众的眼睛是雪亮的。",
        "这部剧的问题是分散的，也不能全怪女主一个人。",
        "对这部剧的评价见仁见智，各有各的立场。",
        "这段表演其实并不差，是角色的特定处境需要。",
    ],
)
def test_equivocal_pr_tone_is_an_error(sample: str):
    hits = scan_style(sample)
    assert any(h["severity"] == "error" and h["rule"].startswith("stance:") for h in hits), sample


def test_a_clear_stance_is_not_flagged():
    """Taking a side — even about the same subject — must stay legal."""
    clean = (
        "这部剧最致命的问题不是尺度，而是把两小时的窒息感稀释成了八集的温吞水。"
        "孙艺珍的狠辣眼神救不了松散的剧本，五点五分的口碑就是观众给出的答案。"
    )
    assert _errors(clean) == set()


# --- 2) 代言心理：warning，L2 侧升级为阻断 ----------------------------------


@pytest.mark.parametrize(
    "sample",
    [
        "周也试图通过咬牙切齿、面部发力来拼命够到对方的气场。",
        "她最不想被人看到的那一面，恰好被镜头拍了下来。",
        "导演心里想表达的是礼教吃人的残酷。",
        "她自己心里明白的是，这场戏已经救不回来了。",
    ],
)
def test_mind_reading_is_flagged_as_warning(sample: str):
    hits = scan_style(sample)
    assert any(h["rule"].startswith("motive:") for h in hits), sample
    assert all(h["severity"] == "warning" for h in hits if h["rule"].startswith("motive:"))


def test_observable_description_is_not_mind_reading():
    clean = "紧绷咬牙与面部用力的外部肌肉反应，反而放大了这场独角戏里的失控感。"
    assert not any(r.startswith("motive:") for r in _rules(clean))


# --- 3) 引语真实性：长句网友引语 = warning --------------------------------


def test_long_quoted_netizen_speech_is_flagged():
    sample = (
        "不少观众直言不讳：“这哪里是痛彻心扉的复仇孤女，分明是憋笑憋到了极限，"
        "下一秒就要当场破功。”"
    )
    assert "quote:长引语需账本" in _rules(sample)


def test_short_attributed_phrase_is_not_flagged():
    """短评式引号（维权惯用短语）不属于一手长引语，不应误伤。"""
    clean = "不少观众直言其“表情管理失控”“五官乱飞”，甚至调侃画面看起来“像是在憋笑”。"
    assert "quote:长引语需账本" not in _rules(clean)


# --- 4) 时代道具穿越：仅在古装/年代语境下触发 ------------------------------


def test_anachronistic_weapon_in_a_period_drama_is_flagged():
    sample = "从二〇二一年《山河令》里顾湘中枪身亡时的哭戏争议，到今天的古装大剧。"
    assert "era:火器穿越" in _rules(sample)


def test_modern_setting_firearm_talk_is_not_flagged():
    clean = "这部警匪片的第三幕里，主角在码头中枪倒下，镜头没有给任何慢动作。"
    assert "era:火器穿越" not in _rules(clean)


# --- 5) 抽象腔 vs 具象锚点 --------------------------------------------------


def test_abstract_only_treatment_is_a_warning():
    paragraphs = [
        "这部剧讨论的是婚姻契约的让渡与名分界定，礼教秩序对主体性的规制构成了结构性困境。",
        "创作者把伦理命题的维度压缩进了话语的机制里，语义的内核因此发生了位移。",
    ]
    result = sensory_anchor_check(paragraphs)
    assert result["status"] == "warning"
    assert result["sensory_anchors"] == []


def test_physical_detail_satisfies_the_sensory_check():
    paragraphs = [
        "她握着剪刀撕碎了满墙的画卷，血从指尖渗出来，雨水打湿了和服的下摆。",
        "回到房里她才哭出来，跪在灵位前，牙齿咬住嘴唇不肯出声。",
    ]
    result = sensory_anchor_check(paragraphs)
    assert result["status"] == "ok"
    assert len(result["sensory_anchors"]) >= 3


# --- 6) 字数深度底线 --------------------------------------------------------


def test_depth_floor_flags_thin_articles():
    assert DEPTH_FLOOR_CJK_CHARS == 1500
    thin = depth_floor_check(1017)
    assert thin["status"] == "warning"
    assert "1500" in thin["reason"]
    deep = depth_floor_check(1675)
    assert deep["status"] == "ok"


def test_markdown_validation_exposes_depth_and_sensory_signals():
    markdown = (
        "# 标题为什么这样写？\n\n"
        + "这是一段事实锚点，导演与主演都在，2026年9月18日上线。" * 6
    )
    result = validate_markdown_text(markdown)
    article = result["articles"][0]
    assert "depth_floor" in article
    assert "sensory_anchor" in article
    assert article["depth_floor"]["status"] == "warning"


# --- 7) 归因豁免（实测修正：成稿被误判的反例） ------------------------------
#
# 2026-09-23 实测：已成稿的周也重写篇里，"辩护的核心逻辑是……这是角色的特定
# 处境"是报道对立面、随后立刻反驳，却被"角色需要辩护"规则误判为 error。
# 归因豁免只对"免责/辩护"一组生效，且必须真的出现替他人说话的标记。


def test_attributed_defence_is_not_a_stance_error():
    attributed = (
        "面对铺天盖地的恶评，剧粉和辩护者急忙搬出剧情前情，辩护的核心逻辑是"
        "“人在极度压抑时本就会哭得难看，这是角色的特定处境”。但这套辩词完全"
        "无法平息普通观众的不满。"
    )
    assert not any(
        h["rule"] == "stance:角色需要辩护" and h["severity"] == "error"
        for h in scan_style(attributed)
    )


def test_the_writers_own_excuse_is_still_an_error():
    self_excusing = "这部剧其实并不差，是角色的特定处境，观众不该苛责。"
    assert any(
        h["rule"] == "stance:角色需要辩护" and h["severity"] == "error"
        for h in scan_style(self_excusing)
    )


def test_hard_equivocation_is_never_excused_by_attribution():
    """作者自己的框架句不豁免：'谁也说服不了谁'点名了谁都不行。"""
    sample = "剧粉说的理由也硬，网友认为各有各的道理，谁也说服不了谁。"
    assert "stance:谁也说服不了谁" in _errors(sample)


def test_modern_media_terms_do_not_fire_the_anachronism_rule():
    """古装剧文章谈戏外的热搜与切片是正常的，不该报火器/时代道具风险。"""
    clean = "这部古装剧上线后，短视频平台上的切片播放量迅速攀升，微博热搜也是接连上榜。"
    assert not any(r.startswith("era:") for r in _rules(clean))
