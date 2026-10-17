"""摸鱼绿红线回归：往期推荐固定 5 篇 + 新增 MD 表格/超链接两条渲染路径。

来历（2026-10-15）：case-008 出厂 body.html 实测 6 条往期推荐，而
AGENTS.md §7 ② 与 docs/dsh/moyu-green-wechat-spec-2026-10-12.md 都写「固定 5 篇」；
当时的校验器只查「往期推荐」四个字是否存在、不查条数，于是红线形同虚设。
同一份未提交改动里新增的 _render_md_table/_hoist_md_tables 与推荐超链接此前零断言覆盖。
"""
from __future__ import annotations

import re

import pytest

from article_group.moyu_green_renderer import (
    RECOMMENDATION_FIXED_COUNT,
    normalize_recommendations,
    render_moyu_green_bundle,
    validate_moyu_green_html,
)

SAMPLE_MD = """# 测试长文标题

开篇第一段正文，用来撑起 body_html 的第一个段落。

## 一、小节标题

| 项目 | 数额 | 备注 |
| --- | ---: | :--- |
| 月供 | 1.2万 | **断裂线** |
| 现金流 | 0 | 见 [参考](https://example.com/a) |

收尾段落。
"""


def _render(recommendations, *, md: str = SAMPLE_MD):
    return render_moyu_green_bundle(
        md,
        title="测试长文标题",
        subtitle_points=["看点一", "看点二"],
        category_tag="深度解剖",
        work_badge="测试剧名",
        interaction_question="你怎么选？",
        interaction_invite="欢迎在评论区聊聊。",
        recommendations=recommendations,
    )


def _recs(n: int):
    return [{"title": f"《推荐{i}》", "desc": f"看点描述{i}"} for i in range(1, n + 1)]


# ---------------------------------------------------------------- 红线：固定 5 篇


def test_recommendations_truncated_when_config_gives_six():
    """run 级 wechat-config.json 给 6 篇时，出厂必须是 5 篇且留痕（case-008 就是 6 篇）。"""
    bundle = _render(_recs(6))
    audit = bundle["recommendation_audit"]

    assert audit["target"] == RECOMMENDATION_FIXED_COUNT
    assert audit["action"] == "truncated"
    assert audit["count"] == RECOMMENDATION_FIXED_COUNT
    assert audit["dropped"] == ["《推荐6》"]

    val = validate_moyu_green_html(bundle["body_html"])
    assert val["passed"] is True, val["errors"]
    assert val["recommendation_count"] == RECOMMENDATION_FIXED_COUNT
    # delivery.md（人工复制用）也必须恰好 5 条
    assert bundle["delivery_md"].count("📌") == RECOMMENDATION_FIXED_COUNT


def test_recommendations_padded_when_config_gives_two():
    """给 2 篇时用母本补齐到 5 篇，红线对下界同样成立。"""
    bundle = _render(_recs(2))
    audit = bundle["recommendation_audit"]

    assert audit["action"] == "padded"
    assert audit["count"] == RECOMMENDATION_FIXED_COUNT
    assert len(audit["padded"]) == 3
    assert audit["dropped"] == []

    val = validate_moyu_green_html(bundle["body_html"])
    assert val["passed"] is True, val["errors"]
    assert val["recommendation_count"] == RECOMMENDATION_FIXED_COUNT


def test_normalize_dedupes_identical_titles():
    recs, audit = normalize_recommendations(_recs(3) + _recs(3))
    titles = [r["title"] for r in recs]
    assert len(titles) == len(set(titles)) == RECOMMENDATION_FIXED_COUNT
    assert audit["count"] == RECOMMENDATION_FIXED_COUNT


def test_validator_rejects_six_recommendations():
    """门禁必须能抓住「四字齐全但实际 6 篇」——这正是旧校验器放行的那一类。"""
    body = _render(_recs(RECOMMENDATION_FIXED_COUNT))["body_html"]
    assert validate_moyu_green_html(body)["passed"] is True

    tampered = body.replace(
        "往期推荐</span></h3>",
        '往期推荐</span></h3><p><span leaf="">📌 伪造第六条</span></p>',
        1,
    )
    val = validate_moyu_green_html(tampered)
    assert val["passed"] is False
    assert "recommendations_must_be_5:got_6" in val["errors"]
    assert val["recommendation_count"] == 6


def test_validator_rejects_missing_recommendation_section():
    val = validate_moyu_green_html("<section></section>")
    assert val["passed"] is False
    assert "missing_component_6_recommendations" in val["errors"]
    assert val["recommendation_count"] == 0


# ------------------------------------------------- 新增渲染路径：MD 表格 / 超链接


def test_markdown_table_rendered_as_inline_table():
    """管道表格必须变内联 <table>，不能再以裸管道行落进正文。"""
    body = _render(_recs(5))["body_html"]

    assert "<table" in body
    assert "<thead>" in body and "<tbody>" in body
    assert "月供" in body and "1.2万" in body
    # 单元格内联渲染：**加粗** 与 [文字](链接)
    assert "<strong" in body
    assert '<a href="https://example.com/a"' in body
    # 不能残留裸管道行
    assert not any(line.strip().startswith("|") for line in body.splitlines())


def test_recommendation_url_becomes_real_anchor_and_absent_url_stays_plain():
    recs = [{"title": "《带链接》", "desc": "d", "url": "https://example.com/rec"}]
    recs += [{"title": f"《无链接{i}》", "desc": "d"} for i in range(2, 6)]
    body = _render(recs)["body_html"]

    # 带 url 的条目必须是真 <a> 且 href 指向该 url。
    # 不写死属性顺序：渲染器按微信规范输出 <a target="_blank" href="...">，
    # 而 textvalue 承载去《》后的纯净标题（2026-10-15 修正：原断言写成 '<a href=' 恒不成立）。
    assert re.search(r'<a\b[^>]*href="https://example\.com/rec"', body), "带 url 的推荐未被渲染成真链接"
    assert 'textvalue="带链接"' in body
    assert ">带链接</span></a>" in body
    # 标题在正文里会剥掉《》（微信编辑器识别真实文章标题所需），故不能断言带书名号的原串
    assert "《带链接》" not in body
    # 没有 url 的条目不得被包成假链接
    for i in range(2, 6):
        assert f"无链接{i}</span>" in body
        assert f"无链接{i}</a>" not in body
    # 规范禁止的虚假「点击直达」
    assert "点击直达" not in body
    assert validate_moyu_green_html(body)["passed"] is True


def test_recommendation_url_is_html_escaped():
    body = _render([{"title": "《注入》", "desc": "d", "url": 'https://e.com/?a=1&b="2"'}])["body_html"]
    assert "&amp;" in body
    assert 'b="2"' not in body


@pytest.mark.parametrize("count", [1, 3, 5, 7])
def test_fixed_count_holds_for_any_input(count: int):
    bundle = _render(_recs(count))
    val = validate_moyu_green_html(bundle["body_html"])
    assert val["passed"] is True, val["errors"]
    assert val["recommendation_count"] == RECOMMENDATION_FIXED_COUNT


def test_blank_recommendations_rendered_and_validated():
    """用户 2026-10-17 定稿：往期推荐内容默认留空（5 个空白 📌 占位条目），供公众号后台人工选填。"""
    blank_recs = [{"title": "", "desc": ""}] * RECOMMENDATION_FIXED_COUNT
    bundle = _render(blank_recs)
    val = validate_moyu_green_html(bundle["body_html"])
    assert val["passed"] is True, val["errors"]
    assert val["recommendation_count"] == RECOMMENDATION_FIXED_COUNT
    assert bundle["recommendation_audit"]["count"] == RECOMMENDATION_FIXED_COUNT
    assert bundle["recommendation_audit"]["action"] == "ok"
    assert '<span leaf="">📌</span>' in bundle["body_html"]
    assert bundle["delivery_md"].count("📌") == RECOMMENDATION_FIXED_COUNT


def test_none_recommendations_defaults_to_blank():
    bundle = render_moyu_green_bundle(
        SAMPLE_MD,
        title="测试长文标题",
        subtitle_points=["看点一", "看点二"],
        category_tag="深度解剖",
        work_badge="测试剧名",
        interaction_question="你怎么选？",
        interaction_invite="欢迎在评论区聊聊。",
        recommendations=None,
    )
    val = validate_moyu_green_html(bundle["body_html"])
    assert val["passed"] is True, val["errors"]
    assert val["recommendation_count"] == RECOMMENDATION_FIXED_COUNT
    assert bundle["recommendation_audit"]["count"] == RECOMMENDATION_FIXED_COUNT
    assert bundle["recommendation_audit"]["action"] == "blank_placeholders"
    assert '<span leaf="">📌</span>' in bundle["body_html"]

