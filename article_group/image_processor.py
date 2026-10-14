"""image_processor: 用户供图安全处理、规格化落盘与排版接入模块。

遵循 AGENTS.md 规范与 Article Group 门禁：
1. 校验用户所提供图片的真实性与基础规格（JPEG / PNG / WebP / GIF，长宽比与分辨率）；
2. 规范化存入 `runs/<run-id>/images/<slot>.<ext>` 并登记 `image-manifest.json`（走 evidence_write）；
3. 杜绝虚假本地路径，保证通过 `check_markdown_image_integrity` 门禁；
4. 提供精准插入到 Markdown 正文指定章节位置的能力；
5. 配合 moyu_green_renderer 渲染微信标准图文卡片与中文字注。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import struct
from pathlib import Path
from typing import Any

from article_group.evidence_write import write_evidence, write_evidence_json


def parse_image_header(file_path: str | Path) -> dict[str, Any]:
    """使用标准库纯 Python 解析常见图片格式（JPEG, PNG, GIF, WebP）的尺寸与类型。"""
    p = Path(file_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"image_file_not_found:{p}")

    size_bytes = p.stat().st_size
    with open(p, "rb") as f:
        head = f.read(128)

    fmt = "unknown"
    width, height = 0, 0

    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        fmt = "png"
        if len(head) >= 24:
            width, height = struct.unpack(">II", head[16:24])
    elif head[:6] in (b"GIF87a", b"GIF89a"):
        fmt = "gif"
        if len(head) >= 10:
            width, height = struct.unpack("<HH", head[6:10])
    elif head.startswith(b"RIFF") and b"WEBP" in head[8:16]:
        fmt = "webp"
        with open(p, "rb") as f:
            full_head = f.read(32)
        if b"VP8 " in full_head:
            width, height = struct.unpack("<HH", full_head[26:30])
            width &= 0x3FFF
            height &= 0x3FFF
        elif b"VP8L" in full_head:
            b0, b1, b2, b3 = full_head[21:25]
            width = 1 + (((b1 & 0x3F) << 8) | b0)
            height = 1 + (((b3 & 0xF) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
        elif b"VP8X" in full_head:
            width = 1 + struct.unpack("<I", full_head[24:27] + b"\x00")[0]
            height = 1 + struct.unpack("<I", full_head[27:30] + b"\x00")[0]
    elif head.startswith(b"\xff\xd8"):
        fmt = "jpeg"
        # 逐段扫描 SOF 标记
        with open(p, "rb") as f:
            f.seek(2)
            b = f.read(2)
            while b and b[0] == 0xFF:
                marker = b[1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    f.seek(3, 1)
                    h, w = struct.unpack(">HH", f.read(4))
                    width, height = w, h
                    break
                elif marker in (0xD9, 0xDA):
                    break
                else:
                    seg_len = struct.unpack(">H", f.read(2))[0]
                    f.seek(seg_len - 2, 1)
                b = f.read(2)

    aspect_ratio = round(width / max(1, height), 2)
    ratio_label = "other"
    if 1.70 <= aspect_ratio <= 1.85:
        ratio_label = "16:9"
    elif 1.30 <= aspect_ratio <= 1.36:
        ratio_label = "4:3"
    elif 0.95 <= aspect_ratio <= 1.05:
        ratio_label = "1:1"
    elif 2.30 <= aspect_ratio <= 2.40:
        ratio_label = "2.35:1"

    return {
        "format": fmt,
        "width": width,
        "height": height,
        "size_bytes": size_bytes,
        "aspect_ratio": aspect_ratio,
        "ratio_label": ratio_label,
        "is_valid_image": fmt != "unknown" and width > 0 and height > 0,
    }


def ingest_user_image(
    run_root: str | Path,
    source_path: str | Path,
    *,
    target_slot: str = "01_cover",
    caption: str = "",
    author: str = "controller",
) -> dict[str, Any]:
    """接收用户提供的图片，安全校验、规范化重命名拷贝至 run_root/images/ 并记账。"""
    root = Path(run_root).resolve()
    src = Path(source_path).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"source_image_missing:{src}")

    meta = parse_image_header(src)
    if not meta["is_valid_image"]:
        raise ValueError(f"unsupported_or_corrupted_image:{src}")

    ext = "jpg" if meta["format"] == "jpeg" else meta["format"]
    slug = re.sub(r"[^\w\-]", "_", target_slot).strip("_") or "image"
    filename = f"{slug}.{ext}"

    images_dir = root / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    target_file = images_dir / filename

    raw_bytes = src.read_bytes()
    target_file.write_bytes(raw_bytes)
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    clean_caption = caption.strip() or f"插图 {slug}"
    rel_path = f"images/{filename}"
    markdown_tag = f"![{clean_caption}]({rel_path})"

    item_record = {
        "slot": slug,
        "filename": filename,
        "relative_path": rel_path,
        "absolute_path": str(target_file),
        "source_original_path": str(src),
        "caption": clean_caption,
        "markdown_tag": markdown_tag,
        "format": meta["format"],
        "width": meta["width"],
        "height": meta["height"],
        "aspect_ratio": meta["aspect_ratio"],
        "ratio_label": meta["ratio_label"],
        "size_bytes": meta["size_bytes"],
        "sha256": sha256,
    }

    manifest_file = images_dir / "image-manifest.json"
    manifest_data = {}
    if manifest_file.is_file():
        try:
            manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    items_list = manifest_data.get("images") or []
    items_list = [it for it in items_list if it.get("slot") != slug]
    items_list.append(item_record)
    manifest_data["schema_version"] = "run-image-manifest-v1"
    manifest_data["run_id"] = root.name
    manifest_data["total_images"] = len(items_list)
    manifest_data["images"] = items_list

    write_evidence_json(
        manifest_file,
        manifest_data,
        run_dir=root,
        reason=f"image_processor:ingest_image:{slug}",
        author=author,
    )

    return item_record


def insert_image_to_draft(
    run_root: str | Path,
    markdown_tag: str,
    *,
    position: str = "after_title",
    author: str = "writer",
) -> dict[str, Any]:
    """将配图 Markdown 标签安全插入到 draft.md 的指定章节位置。"""
    root = Path(run_root).resolve()
    draft_file = root / "draft.md"
    if not draft_file.is_file():
        raise FileNotFoundError(f"draft_md_missing:{draft_file}")

    text = draft_file.read_text(encoding="utf-8")
    lines = text.splitlines()

    tag_to_insert = markdown_tag.strip()
    # 如果已经存在该图片的相对路径，避免重复插入
    rel_match = re.search(r"\((images/[^)]+)\)", tag_to_insert)
    if rel_match and rel_match.group(1) in text:
        return {"ok": True, "already_inserted": True, "draft_path": str(draft_file)}

    new_lines = []
    inserted = False

    if position == "after_title":
        for idx, line in enumerate(lines):
            new_lines.append(line)
            if not inserted and line.startswith("# "):
                new_lines.append("")
                new_lines.append(tag_to_insert)
                new_lines.append("")
                inserted = True
    elif position.startswith("after_h2_"):
        try:
            target_h2_idx = int(position.replace("after_h2_", ""))
        except ValueError:
            target_h2_idx = 1
        h2_count = 0
        for line in lines:
            new_lines.append(line)
            if line.startswith("## "):
                h2_count += 1
                if h2_count == target_h2_idx and not inserted:
                    new_lines.append("")
                    new_lines.append(tag_to_insert)
                    new_lines.append("")
                    inserted = True
    else:  # 默认加在文末收尾前
        for line in lines:
            if not inserted and line.strip() == "---" and len(new_lines) > len(lines) * 0.7:
                new_lines.append(tag_to_insert)
                new_lines.append("")
                inserted = True
            new_lines.append(line)

    if not inserted:
        new_lines.insert(2 if len(new_lines) > 2 else len(new_lines), tag_to_insert)

    updated_text = "\n".join(new_lines) + "\n"
    write_evidence(
        draft_file,
        updated_text,
        run_dir=root,
        reason=f"image_processor:insert_image:{position}",
        author=author,
    )
    return {"ok": True, "already_inserted": False, "draft_path": str(draft_file)}
