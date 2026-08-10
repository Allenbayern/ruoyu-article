"""prose_pilot 试点检查器的单元测试（advisory only，不碰 style_gate）。"""

import json

from article_group.prose_pilot import (
    _para_advance_status,
    _syntax_warnings,
    analyze_html,
    analyze_text,
)


# --- 段落推进 -----------------------------------------------------------
def test_advance_has_new_with_fact():
    p = "《八仙！》今日宣布定档8月19日，全国上映。"
    assert _para_advance_status(p)["verdict"] == "has_new"


def test_advance_thin_pure_feeling():
    p = "这种温柔让人久久不能平静，看完之后心里很暖。"
    assert _para_advance_status(p)["verdict"] == "thin"


def test_advance_pause_reference_echo():
    # 纯回指复述（还是那句话 + 上文），无事实/论证推进 → pause
    p = "还是那句话，上文已经交代过了，这里就不再展开重复了。"
    assert _para_advance_status(p)["verdict"] == "pause"


# --- 句法软警告 ---------------------------------------------------------
def test_anaphora_window_detected():
    t = "他要找的是真相，他要找的是答案，他要找的是出口。"
    assert any(w["signal"] == "同构排比" for w in _syntax_warnings(t))


def test_sentence_length_evenness_warned():
    # 8 句以上、句长高度一致 → 句长过齐
    t = "今天天气不错。我出门走了走。街上人不太多。风吹过来很凉。树影落在地上。有人牵狗路过。我把手插兜里。慢慢往家走。"
    assert any(w["signal"] == "句长过齐" for w in _syntax_warnings(t))


def test_judgment_marker_high_count():
    t = "真正重要的是选择，真正重要的是坚持，真正重要的是不放弃，真正重要的是方向。"
    assert any("洞察路标" in w["signal"] for w in _syntax_warnings(t))


def test_no_false_warning_on_clean_text():
    t = "《八仙！》今日宣布定档8月19日，全国上映。导演郑润奇表示，影片筹备三年。"
    assert _syntax_warnings(t) == []


# --- 材料清单 + ledger 匹配 ---------------------------------------------
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


def test_html_analysis_extracts_articles():
    html = (
        "<article><h2>第一篇</h2><p>《八仙！》今日宣布定档8月19日，全国上映，导演郑润奇表示影片筹备多年，正式官宣。</p>"
        "<p>这种温柔让人久久不能平静，看完之后心里很暖，很多情绪堵在胸口说不出来，只能反复回味。</p></article>"
        "<article><h2>第二篇</h2><p>《不想失去你》由蓝鸿春监制，郑润奇导演，正式官宣将于8月19日全国上映。</p></article>"
    )
    results = analyze_html(html, [])
    assert len(results) == 2
    assert results[0]["title"] == "第一篇"
    assert results[0]["progression"]["thin_paragraphs"] == [2]


def test_result_is_advisory_only():
    r = analyze_text("《八仙！》今日宣布定档8月19日，全国上映。", "测试稿", [])
    assert r["advisory"] is True
