"""prose_pilot 后台检查器测试（advisory only，不碰 style_gate）。

v2 精简（2026-08-10 盲测后）：仅「材料清单 + 判断词密度」两个已采纳通道；
段落推进（thin/pause/开场重复）与同构排比/句长过齐/抒情词/长前置成分已弃用。
"""

from article_group.prose_pilot import (
    _syntax_warnings,
    analyze_html,
    analyze_text,
)


# --- 判断词密度（候选 B，盲测 100% 验证）-------------------------------
def test_judgment_marker_high_count():
    t = "真正重要的是选择，真正重要的是坚持，真正重要的是不放弃，真正重要的是方向。"
    assert any("洞察路标" in w["signal"] for w in _syntax_warnings(t))


def test_no_false_warning_on_clean_text():
    t = "《八仙！》今日宣布定档8月19日，全国上映。导演郑润奇表示，影片筹备三年。"
    assert _syntax_warnings(t) == []


# --- 材料清单 + ledger 匹配（候选 A，零误报）---------------------------
def test_material_anchors_counted():
    r = analyze_text(
        "《八仙！》2026年8月19日上映，由郑润奇导演，共8个角色，定档消息来自官方。",
        "测试稿", [])
    assert r["material"]["anchor_total"] >= 4


def test_ledger_quote_matched():
    ledger = [{
        "source_id": 3,
        "title": "电影《不想失去你》定档8月19日",
        "url": "http://ent.ynet.com/",
        "text": "由蓝鸿春监制，郑润奇导演及编剧，黄曦彦、张祎曈、郑润奇主演的青春爱情电影《不想失去你》于今日发布定档海报，正式官宣将于2026年8月19日全国上映。",
    }]
    text = "电影《不想失去你》由蓝鸿春监制、郑润奇导演，正式官宣将于2026年8月19日全国上映。"
    r = analyze_text(text, "测试稿", ledger)
    assert r["material"]["ledger_matched_quotes"] == 1
    assert r["material"]["matched_sources"]


# --- HTML 提取 ----------------------------------------------------------
def test_html_analysis_extracts_articles():
    html = (
        "<article><h2>第一篇</h2><p>《八仙！》今日宣布定档8月19日，全国上映，导演郑润奇表示影片筹备多年，正式官宣。</p>"
        "<p>这种温柔让人久久不能平静，看完之后心里很暖，很多情绪堵在胸口说不出来，只能反复回味。</p></article>"
        "<article><h2>第二篇</h2><p>《不想失去你》由蓝鸿春监制，郑润奇导演，正式官宣将于8月19日全国上映。</p></article>"
    )
    results = analyze_html(html, [])
    assert len(results) == 2
    assert results[0]["title"] == "第一篇"
    assert results[0]["material"]["anchor_total"] >= 2


# --- 弃用通道验证 --------------------------------------------------------
def test_paragraph_progression_channel_removed():
    # v2 弃用：报告不再输出 progression 通道；advisory 性质不变
    r = analyze_text("《八仙！》今日宣布定档8月19日，全国上映。", "测试稿", [])
    assert "progression" not in r
    assert r["advisory"] is True
