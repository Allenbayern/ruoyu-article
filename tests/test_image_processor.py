"""Tests for image_processor and moyu_green image card rendering."""

from __future__ import annotations

import base64
from pathlib import Path

from article_group.image_processor import ingest_user_image, insert_image_to_draft, parse_image_header
from article_group.moyu_green_renderer import render_moyu_green_bundle

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

    # 测试 moyu_green 渲染包含真实图片时的表现
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
    assert '<img src="images/01_walter_wash.png"' in bundle["body_html"]
    assert "▲ 洗车行里的老白" in bundle["body_html"]
    assert "![洗车行里的老白](images/01_walter_wash.png)" in bundle["delivery_md"]
