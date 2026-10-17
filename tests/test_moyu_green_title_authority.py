
import pytest
from pathlib import Path
from article_group.moyu_green_renderer import render_moyu_green_from_run

def test_draft_h1_overrides_stale_config_title(tmp_path: Path):
    draft_file = tmp_path / "draft.md"
    draft_file.write_text("# 正确的正文定稿标题\n\n正文内容第一段。\n", encoding="utf-8")
    
    cfg_file = tmp_path / "wechat-config.json"
    cfg_file.write_text('{"title": "陈旧的配置标题"}', encoding="utf-8")
    
    res = render_moyu_green_from_run(tmp_path)
    preview_html = (tmp_path / "wechat" / "preview.html").read_text(encoding="utf-8")
    delivery_md = (tmp_path / "wechat" / "delivery.md").read_text(encoding="utf-8")
    
    assert "正确的正文定稿标题" in preview_html
    assert "陈旧的配置标题" not in preview_html
    assert delivery_md.startswith("# 正确的正文定稿标题")
