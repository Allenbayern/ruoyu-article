"""Tests for image_processor and moyu_green image card rendering."""

from __future__ import annotations

import base64
from pathlib import Path

from article_group.image_processor import ingest_user_image, insert_image_to_draft, parse_image_header
from article_group.moyu_green_renderer import build_image_gallery_html, render_moyu_green_bundle

# 1x1 transparent PNG in base64
TINY_PNG_B64 = b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="


def test_parse_image_header_and_ingest(tmp_path: Path):
    src_img = tmp_path / "sample_user.png"
    src_img.write_bytes(base64.b64decode(TINY_PNG_B64))

    meta = parse_image_header(src_img)
    assert meta["is_valid_image"] is True
    assert meta["format"] == "png"
    assert meta["width"] == 1
    assert meta["height"] == 1

    run_dir = tmp_path / "run_01"
    run_dir.mkdir()

    ingest_res = ingest_user_image(
        run_dir,
        src_img,
        target_slot="01_walter_wash",
        caption="洗车行里的老白",
    )
    assert ingest_res["slot"] == "01_walter_wash"
    assert ingest_res["relative_path"] == "images/01_walter_wash.png"
    assert (run_dir / "images" / "01_walter_wash.png").is_file()
    assert (run_dir / "images" / "image-manifest.json").is_file()

    # 测试插入到 draft.md
    draft_file = run_dir / "draft.md"
    draft_file.write_text("# 标题\n\n首段内容...\n\n## 一、小节1\n\n正文...\n", encoding="utf-8")

    ins_res = insert_image_to_draft(run_dir, ingest_res["markdown_tag"], position="after_title")
    assert ins_res["ok"] is True
    updated_draft = draft_file.read_text(encoding="utf-8")
    assert "![洗车行里的老白](images/01_walter_wash.png)" in updated_draft

    # 测试 moyu_green 渲染：2026-10-14 定稿标准=正文不内嵌本地图片，只留「▲ 图注」插入锚点
    bundle = render_moyu_green_bundle(
        updated_draft,
        title="测试标题",
        subtitle_points=["看点1", "看点2"],
        category_tag="剧评",
        work_badge="深度",
        interaction_question="问题",
        interaction_invite="邀请",
        recommendations=[],
        run_root=run_dir,
    )
    assert "<img" not in bundle["body_html"]
    assert "▲ 洗车行里的老白" in bundle["body_html"]
    assert "![洗车行里的老白](images/01_walter_wash.png)" in bundle["delivery_md"]

    # 显式开启归档预览开关时，才允许内嵌本地图片
    archive_bundle = render_moyu_green_bundle(
        updated_draft,
        title="测试标题",
        subtitle_points=["看点1", "看点2"],
        category_tag="剧评",
        work_badge="深度",
        interaction_question="问题",
        interaction_invite="邀请",
        recommendations=[],
        run_root=run_dir,
        embed_images=True,
    )
    assert '<img src="images/01_walter_wash.png"' in archive_bundle["body_html"]
    assert "▲ 洗车行里的老白" in archive_bundle["body_html"]

    # 配图插入画廊：按正文顺序编号、静态图内嵌 base64、静态图可剪贴板复制
    gallery = build_image_gallery_html(run_dir, title="测试标题", draft_text=updated_draft)
    assert gallery["count"] == 1
    assert gallery["items"][0]["name"] == "01_walter_wash.png"
    assert gallery["items"][0]["embedded"] is True
    assert "data:image/png;base64," in gallery["html"]
    assert "▲ 洗车行里的老白" in gallery["html"]
