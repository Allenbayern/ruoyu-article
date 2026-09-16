"""薄小节检查（style_gate.thin_section）：把提纲式小节挡在门外。

背景（2026-09-16，daily-008 扩写实验）：该期原稿 1032 字，两个小节各仅 111 字
（"6.7分"节＝分数+票房+三个差评词；"姜文没变"节＝一句标题式判断）；同材料扩写版
最薄小节 210 字、补料版 215 字，均通过。判据：任一 H2+ 小节正文 <150 CJK 字。
"""
from __future__ import annotations

from article_group.style_gate import (
    THIN_SECTION_MIN_CJK,
    _markdown_sections,
    thin_section_check,
    validate_markdown_file,
    validate_markdown_text,
)

_PARA_A = (
    "影片上映第一周，豆瓣评分稳定在6.7分，文汇报的评语既没有把它捧上神坛，"
    "也没有把它归入烂片，这种撕裂感本身就是争议的来源。"
)
_PARA_B = (
    "观众的反应分成两拨，一拨觉得过瘾，一拨觉得被冒犯；打分的人越多这种分裂越清楚，"
    "连好还是坏都说不出口。"
)
_PARA_C = (
    "预算长期压在3亿上下的高位，票房却在第四部掉到不足一亿，"
    "于是拧巴从一个形容词变成了一组可以核对的数字。"
)
_PARA_D = (
    "同为姜文作品，太阳照常升起上映初期也饱受争议，如今豆瓣升到8.4；"
    "而一步之遥2014年是六字头，现在还是六字头。"
)
_PARA_E = (
    "放映结束后讨论并没有停止，有人把问题归到观众变了，有人把问题归到导演没变，"
    "两种说法都能在当天的评论里找到材料。"
)

_FAT_SECTION = "\n\n".join([_PARA_A, _PARA_B, _PARA_C, _PARA_D])
_FAT_SECTION_2 = "\n\n".join([_PARA_C, _PARA_E, _PARA_B, _PARA_A])

OUTLINE = f"""# 标题：姜文为什么一部比一部拧巴

## 第一节

{_FAT_SECTION}

## 第二节

太短了。

## 第三节

{_FAT_SECTION_2}
"""

EXPANDED = f"""# 标题：姜文为什么一部比一部拧巴

## 第一节

{_FAT_SECTION}

## 第二节

{_FAT_SECTION_2}
"""


def test_fixtures_are_above_the_threshold() -> None:
    """守卫测试：fixture 必须真的在阈值之上（且按 CJK 计），否则这条检查就白测了。"""
    import re

    cjk = lambda text: len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))  # noqa: E731
    assert cjk(_FAT_SECTION) > THIN_SECTION_MIN_CJK
    assert cjk(_FAT_SECTION_2) > THIN_SECTION_MIN_CJK


def test_markdown_sections_count_body_cjk_only():
    sections = _markdown_sections(OUTLINE)
    assert [name for name, _ in sections] == ["第一节", "第二节", "第三节"]
    assert sections[1][1] < THIN_SECTION_MIN_CJK
    assert sections[0][1] >= THIN_SECTION_MIN_CJK


def test_thin_section_check_flags_outline_section():
    result = thin_section_check(_markdown_sections(OUTLINE))
    assert result["status"] == "warning"
    assert result["thin_sections"] == [{"heading": "第二节", "cjk": 3}]
    assert "第二节" in result["reason"]


def test_thin_section_check_passes_expanded_sections():
    result = thin_section_check(_markdown_sections(EXPANDED))
    assert result["status"] == "ok"
    assert result["thin_sections"] == []
    assert result["sections"] == 2


def test_thin_section_check_without_headings_is_info():
    result = thin_section_check(_markdown_sections("只有一段正文，没有小标题。"))
    assert result["status"] == "info"


def test_validate_markdown_text_reports_thin_section_without_failing_the_gate():
    report = validate_markdown_text(OUTLINE)
    assert report["articles"][0]["thin_section"]["status"] == "warning"
    # 薄小节是 warning，不是 error：红线与既有 pass 语义不变。
    assert report["error_total"] == 0
    assert report["pass"] is True


def test_validate_markdown_file_includes_thin_section(tmp_path):
    path = tmp_path / "delivery.md"
    path.write_text(EXPANDED, encoding="utf-8")
    report = validate_markdown_file(path)
    assert report["articles"][0]["thin_section"]["status"] == "ok"
    assert report["artifact_sha256"]
