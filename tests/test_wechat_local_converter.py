import tempfile
from pathlib import Path

from article_group.wechat_local_converter import (
    DEFAULT_THEME,
    build_copy_page,
    convert_markdown_to_wechat_html,
    list_available_themes,
    load_theme,
    main,
)


def test_list_themes():
    themes = list_available_themes()
    assert "ruoyu-cinema" in themes
    assert "refined-blue" in themes
    assert "minimal-mono" in themes


def test_convert_headings_and_drop_h1():
    md = "# 文章大标题\n\n正文第一段。\n\n## 第一小节\n\n正文第二段。"
    # drop_h1=True
    html_out = convert_markdown_to_wechat_html(md, drop_h1=True)
    assert "<h1" not in html_out
    assert "<h2" in html_out
    assert "第一小节" in html_out
    assert "正文第一段" in html_out

    # keep_h1
    html_with_h1 = convert_markdown_to_wechat_html(md, drop_h1=False)
    assert "<h1" in html_with_h1
    assert "文章大标题" in html_with_h1


def test_inline_marks_and_highlights():
    md = "这是**加粗重点**，这是==黄色马克==，这是++蓝色马克++，这是!!红色警示!!。"
    html_out = convert_markdown_to_wechat_html(md)
    assert "<strong" in html_out
    assert "加粗重点" in html_out
    assert "黄色马克" in html_out
    assert "蓝色马克" in html_out
    assert "红色警示" in html_out
    assert "span style=" in html_out


def test_dangerous_links_sanitized():
    md = "正常链接：[Google](https://google.com)，恶意链接：[点击](javascript:alert(1))"
    html_out = convert_markdown_to_wechat_html(md)
    assert 'href="https://google.com"' in html_out
    assert "javascript:" not in html_out
    assert "点击" in html_out


def test_blockquote_and_table_and_code():
    md = """
> 这是一段台词引用

| 电影 | 评分 |
|---|---|
| 霸王别姬 | 9.6 |
| 活着 | 9.4 |

```python
print("film review")
```
"""
    html_out = convert_markdown_to_wechat_html(md)
    assert "<blockquote" in html_out
    assert "这是一段台词引用" in html_out
    assert "<table" in html_out
    assert "霸王别姬" in html_out
    assert "<pre" in html_out
    assert 'print("film review")' in html_out


def test_build_copy_page():
    body = "<p>正文内容</p>"
    page = build_copy_page(title="测试影评", body_html=body, theme="ruoyu-cinema")
    assert "<!DOCTYPE html>" in page
    assert "测试影评" in page
    assert "copyArticle()" in page
    assert "正文内容" in page


def test_cli_execution(tmp_path):
    md_file = tmp_path / "article.md"
    md_file.write_text("# 影评标题\n\n一段深刻的分析。\n\n## 视听语言\n\n镜头极具张力。", encoding="utf-8")
    out_file = tmp_path / "out.html"

    # 运行 CLI 转换纯 HTML
    rc = main([str(md_file), "-o", str(out_file), "--theme", "ruoyu-cinema"])
    assert rc == 0
    assert out_file.is_file()
    content = out_file.read_text(encoding="utf-8")
    assert "视听语言" in content
    assert "<h1" not in content  # 默认 drop_h1

    # 运行 CLI 转换带 copy-page 的完整预览页
    page_file = tmp_path / "page.html"
    rc_page = main([str(md_file), "-o", str(page_file), "--copy-page", "--title", "年度十佳"])
    assert rc_page == 0
    page_content = page_file.read_text(encoding="utf-8")
    assert "年度十佳" in page_content
    assert "一键复制" in page_content
