"""Tests for WeChat low-creativity editorial redlines (2026-09-29 landing batch).

Real negative samples caught by WeChat official platform recommendation system:
- 2026-09-24 游本昌篇: "扯下了整个内娱的遮羞布", "撕开内娱最荒诞的遮羞布",
  "把现代流量明星的演技底裤扒得干干净净", "### 【引子】";
- 2026-09-25 片酬爆料篇: "内娱“假大女主”们，终于被打回原形！",
  "撕扯掉行业的最后一块遮羞布", "【热榜上的“一百万”】";
- 2026-09-23 孙艺珍篇: "全网狂搜的“19禁床戏”！".

These gate the *anti-low-creativity mechanism*, preventing clickbait,
sensational polarization phrases, vulgar lures, and rigid AIGC scaffolding.
"""

from __future__ import annotations

import pytest

from article_group.style_gate import scan_style


def _errors(text: str) -> set[str]:
    return {
        hit["rule"]
        for hit in scan_style(text)
        if hit["severity"] == "error"
    }


# --- 1) 狗血对立与拉踩套话拦截（error）---------------------------------------


@pytest.mark.parametrize(
    ("sample", "expected_rule"),
    [
        ("93岁游本昌走了，扯下了整个内娱的遮羞布", "clickbait:遮羞布套话"),
        ("九十三岁的老人悄悄交了卷，撕开内娱最荒诞的遮羞布", "clickbait:遮羞布套话"),
        ("每一项扎实的数据都在撕扯掉行业的最后一块遮羞布", "clickbait:遮羞布套话"),
        ("内娱“假大女主”们，终于被打回原形！", "clickbait:打回原形"),
        ("他用一个含泪回眸，把现代流量明星的演技底裤扒得干干净净", "clickbait:扒底裤套话"),
        ("这一出戏，直接打脸了半个娱乐圈。", "clickbait:打脸娱乐圈"),
    ],
)
def test_clickbait_polarization_phrases_are_errors(sample: str, expected_rule: str):
    hits = scan_style(sample)
    assert any(h["severity"] == "error" and h["rule"] == expected_rule for h in hits), sample


# --- 2) 低俗噱头引流词拦截（error）-----------------------------------------


@pytest.mark.parametrize(
    "sample",
    [
        "全网狂搜的“19禁床戏”！孙艺珍首演恶女，却将一手王炸拍砸了",
        "这部剧未播先火，全是靠大尺度床戏当噱头。",
    ],
)
def test_vulgar_clickbait_is_an_error(sample: str):
    hits = scan_style(sample)
    assert any(h["severity"] == "error" and h["rule"] == "clickbait:低俗引流" for h in hits), sample


# --- 3) 僵化 AI 章节脚手架拦截（error）--------------------------------------


@pytest.mark.parametrize(
    ("sample", "expected_rule"),
    [
        ("### 【引子】九十三岁的老人悄悄交了卷", "aigc:刻板章节标牌"),
        ("### 【冷板凳】三十年无名龙套", "aigc:刻板章节标牌"),
        ("【热榜上的“一百万”】", "aigc:刻板标签标牌"),
        ("【政策铁笼与长剧腰斩】", "aigc:刻板标签标牌"),
    ],
)
def test_rigid_aigc_scaffolding_is_an_error(sample: str, expected_rule: str):
    hits = scan_style(sample)
    assert any(h["severity"] == "error" and h["rule"] == expected_rule for h in hits), sample


# --- 4) 高信息增量与专业白描正例：不报错 -------------------------------------


def test_high_information_gain_clean_prose_is_not_flagged():
    """9-28 跑通的高质标杆（如崔道植、梁洛施篇）必须 100% 保持 clean。"""
    cui_clean = (
        "在显微镜下，两个相隔三千公里的弹壳底面上，几道微不可察、呈现微小弧度的特定击针痕迹，"
        "以及抽壳钩特有的细微崩口凹槽，在镜筒里严丝合缝地重叠在了一起。"
    )
    assert _errors(cui_clean) == set()

    liang_clean = (
        "二十三岁带着三个儿子离开豪门，她没有在豪门恩怨里消耗青春，"
        "而是在泥泞的现实里一步一步把自己的演员骨架重新立了起来。"
    )
    assert _errors(liang_clean) == set()
