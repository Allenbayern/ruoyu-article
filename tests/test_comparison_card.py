import json
from pathlib import Path

from article_group.comparison_card import (
    CARD_SIZES,
    THEME_STYLES,
    generate_comparison_card_html,
    main,
    parse_markdown_comparison_table,
    render_html_to_png,
)


def test_generate_comparison_card_html():
    dims = [
        {"name": "主角动机", "val_a": "求真", "val_b": "救人", "winner": "A"},
        {"name": "节奏把控", "val_a": "缓慢", "val_b": "紧凑", "winner": "B"},
    ]
    html_out = generate_comparison_card_html(
        title="原著 vs 剧版",
        item_a="原著小说",
        item_b="网飞版",
        dimensions=dims,
        theme="cinema-film",
        size="xiaohongshu",
    )
    assert "<!DOCTYPE html>" in html_out
    assert "原著小说" in html_out
    assert "网飞版" in html_out
    assert "主角动机" in html_out
    assert "class=\"winner\"" in html_out
    assert "1080px" in html_out
    assert "1440px" in html_out


def test_theme_and_size_switching():
    dims = [{"name": "视效", "val_a": "胶片", "val_b": "数字", "winner": "neutral"}]
    # editorial-paper
    html_paper = generate_comparison_card_html(
        title="测试",
        item_a="A",
        item_b="B",
        dimensions=dims,
        theme="editorial-paper",
        size="square",
    )
    assert "1080px" in html_paper
    assert THEME_STYLES["editorial-paper"]["badge_bg"] in html_paper


def test_parse_markdown_comparison_table():
    md = """
| 对比维度 | 原著版本 | 翻拍版本 |
|---|---|---|
| 核心结局 | 全员牺牲 (胜) | 阖家团圆 |
| 视听语言 | 长镜头为主 | 碎片化剪辑 (胜) |
| 主题深度 | 绝望中寻光 | 纯粹商业爽片 |
"""
    dims = parse_markdown_comparison_table(md)
    assert len(dims) == 3
    assert dims[0]["name"] == "核心结局"
    assert dims[0]["val_a"] == "全员牺牲"
    assert dims[0]["winner"] == "A"
    assert dims[1]["winner"] == "B"
    assert dims[2]["winner"] == "neutral"


def test_cli_execution_with_json_and_md(tmp_path: Path):
    out_html = tmp_path / "card.html"

    # 1. 默认参数执行
    rc = main(["-o", str(out_html), "--title", "年度对决", "--item-a", "作品甲", "--item-b", "作品乙"])
    assert rc == 0
    assert out_html.is_file()
    assert "作品甲" in out_html.read_text(encoding="utf-8")

    # 2. Markdown 表格输入
    md_file = tmp_path / "comp.md"
    md_file.write_text("| 维度 | A | B |\n|---|---|---|\n| 评分 | 9.0 (胜) | 6.5 |\n", encoding="utf-8")
    out_md_html = tmp_path / "card_from_md.html"
    rc_md = main(["-o", str(out_md_html), "--md-input", str(md_file), "--item-a", "老版", "--item-b", "新版"])
    assert rc_md == 0
    assert out_md_html.is_file()
    assert "老版" in out_md_html.read_text(encoding="utf-8")
    assert "9.0" in out_md_html.read_text(encoding="utf-8")


def test_render_png_fallback():
    # 测试在不崩溃的情况下调用 render_html_to_png
    # 如果系统里有 playwright，它能工作；如果无，它返回 False 并打印警告，不应 raise
    fake_path = Path("/nonexistent/file.html")
    res = render_html_to_png(fake_path, "/tmp/out.png")
    # 不存在的文件应该安全返回 False
    assert res is False
