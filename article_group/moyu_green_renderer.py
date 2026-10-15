"""moyu_green_renderer: 若雨随影 2026-10-12 定稿「摸鱼绿杂志风」微信排版渲染与校验引擎。

严格实现 6 大标准组件（纯净首屏 Mode B）：
1. 【组件 1】双层封面大卡片（Breaking Cover · Mode B 纯净首屏默认不展示大封面，避免与微信系统文章标题机械重复）
2. 【组件 2】头部名片关注条（Top Follow Hook · Mode B 无封面，位于首段前）
3. 【组件 3】正文叙事与呼吸感（绿底白字徽章编号 + 17px H2 + 4px 墨绿竖线浅绿卡 + 三点呼吸分隔线）
4. 【组件 4】读者互动卡（Interaction）
5. 【组件 5】文末显眼关注大卡（Footer Follow CTA Card）
6. 【组件 6】往期推荐（精选 5 篇，不承诺点击跳转）

严格遵守微信编辑器技术红线：
- 所有文字节点包裹 <span leaf="">
- 纯内联样式，body.html 零 <style>/class=/position:fixed|sticky
- 全角中文标点
- 产出 body.html、preview.html 与 delivery.md
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from article_group.evidence_write import write_evidence, write_evidence_json


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def _esc_attr(text: str) -> str:
    """属性值专用转义。

    _esc 用 quote=False，不转义双引号——直接塞进 href="..."/src="..." 时，一个 `"`
    就能截断属性并注入任意属性或标签（2026-10-15 由新增超链接回归测试实测抓到）。
    """
    return html.escape(text, quote=True)


def _normalize_cjk_punct(text: str) -> str:
    """将半角直引号与英文逗号/感叹号/问号归一为全角中文标点。"""
    # 处理成对直引号 "..." -> “...”
    out: list[str] = []
    open_q = True
    for ch in text:
        if ch == '"':
            out.append("“" if open_q else "”")
            open_q = not open_q
        else:
            out.append(ch)
    res = "".join(out)
    # 替换中文语境下的半角标点
    res = re.sub(r"(?<=[\u4e00-\u9fff]),\s*", "，", res)
    res = re.sub(r"(?<=[\u4e00-\u9fff])!\s*", "！", res)
    res = re.sub(r"(?<=[\u4e00-\u9fff])\?\s*", "？", res)
    return res


def _render_inline_paragraph(line: str) -> str:
    """将包含 **加粗** 的行转换为全包裹 <span leaf=""> 的微信内联段落。"""
    normalized = _normalize_cjk_punct(line.strip())
    parts = re.split(r"(\*\*.*?\*\*)", normalized)
    spans: list[str] = []
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            inner = _esc(part[2:-2])
            spans.append(f'<strong style="color: #111827;"><span leaf="">{inner}</span></strong>')
        else:
            spans.append(f'<span leaf="">{_esc(part)}</span>')
    inner_html = "".join(spans)
    return f'  <p style="margin: 0 0 16px; color: #374151; line-height: 1.85; text-align: justify;">{inner_html}</p>'


def _render_quote_card(text: str) -> str:
    """单侧 4px 墨绿竖线浅绿卡。"""
    clean = _normalize_cjk_punct(text.strip())
    clean = re.sub(r"^\*\*|\*\*$", "", clean).strip()
    return f"""  <section style="margin: 20px 0; background: #F0FDF4; border-left: 4px solid #059669; padding: 14px 18px; border-radius: 0 8px 8px 0;">
    <p style="margin: 0; font-size: 15px; font-weight: 700; color: #065F46; line-height: 1.75;">
      <span leaf="">{_esc(clean)}</span>
    </p>
  </section>"""


def _render_divider() -> str:
    """三点呼吸分隔线。"""
    return """  <section style="margin: 28px 0; display: flex; align-items: center; justify-content: center; gap: 6px;">
    <span style="width: 4px; height: 4px; background: #059669; border-radius: 50%;"></span>
    <span style="width: 18px; height: 2px; background: rgba(5,150,105,0.3); border-radius: 1px;"></span>
    <span style="width: 4px; height: 4px; background: #059669; border-radius: 50%;"></span>
  </section>"""


def _render_section_heading(badge: str, title: str) -> str:
    """绿色徽章编号（一、/二、）+ 17px 粗体 H2。"""
    return f"""  <section style="margin: 36px 0 18px; display: flex; align-items: center; gap: 10px;">
    <span style="background: #059669; color: #ffffff; font-size: 12px; font-weight: 800; padding: 3px 8px; border-radius: 6px; letter-spacing: 1px;"><span leaf="">{_esc(badge)}</span></span>
    <h2 style="font-size: 17px; font-weight: 800; color: #111827; margin: 0; line-height: 1.4;"><span leaf="">{_esc(_normalize_cjk_punct(title))}</span></h2>
  </section>"""


def _render_bullet_item(text: str) -> str:
    """小绿圆点列表项。"""
    normalized = _normalize_cjk_punct(text.strip())
    parts = re.split(r"(\*\*.*?\*\*)", normalized)
    spans: list[str] = []
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            spans.append(f'<strong style="color: #111827;"><span leaf="">{_esc(part[2:-2])}</span></strong>')
        else:
            spans.append(f'<span leaf="">{_esc(part)}</span>')
    return f"""  <section style="margin: 0 0 10px 12px; display: flex; align-items: baseline; gap: 8px;">
    <span style="width: 6px; height: 6px; background: #059669; border-radius: 50%; display: inline-block; flex-shrink: 0; margin-top: 8px;"></span>
    <p style="margin: 0; color: #374151; line-height: 1.8; text-align: justify;">{"".join(spans)}</p>
  </section>"""


def _render_numbered_item(num_str: str, text: str) -> str:
    """墨绿数字徽章有序列表项。"""
    normalized = _normalize_cjk_punct(text.strip())
    parts = re.split(r"(\*\*.*?\*\*)", normalized)
    spans: list[str] = []
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            spans.append(f'<strong style="color: #111827;"><span leaf="">{_esc(part[2:-2])}</span></strong>')
        else:
            spans.append(f'<span leaf="">{_esc(part)}</span>')
    return f"""  <section style="margin: 0 0 10px 8px; display: flex; align-items: baseline; gap: 8px;">
    <span style="background: #ecfdf5; color: #059669; font-size: 12px; font-weight: 800; padding: 1px 6px; border-radius: 4px; flex-shrink: 0;"><span leaf="">{_esc(num_str)}</span></span>
    <p style="margin: 0; color: #374151; line-height: 1.8; text-align: justify;">{"".join(spans)}</p>
  </section>"""


_MD_TABLE_SENTINEL = "\x00MDTABLE\x00"


def _split_md_row(row: str) -> list[str]:
    text = row.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip() for cell in text.split("|")]


def _is_md_separator_row(cells: Sequence[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", (cell or "").strip()) for cell in cells)


def _render_md_cell(cell: str, *, header: bool, align: str) -> str:
    """单元格内联渲染：**加粗** 与 [文字](链接)，全部包裹 <span leaf="">。"""
    normalized = _normalize_cjk_punct(cell.strip())
    chunks: list[str] = []
    for part in re.split(r"(\*\*.*?\*\*|\[[^\]]+\]\([^)]+\))", normalized):
        if not part:
            continue
        m_link = re.fullmatch(r"\[([^\]]+)\]\(([^)]+)\)", part)
        if m_link:
            chunks.append(
                f'<a href="{_esc_attr(m_link.group(2))}" style="color: #059669; text-decoration: none; font-weight: 700;">'
                f'<span leaf="">{_esc(m_link.group(1))}</span></a>'
            )
        elif part.startswith("**") and part.endswith("**") and len(part) > 4:
            chunks.append(f'<strong style="color: #111827;"><span leaf="">{_esc(part[2:-2])}</span></strong>')
        else:
            chunks.append(f'<span leaf="">{_esc(part)}</span>')
    inner = "".join(chunks)
    if header:
        return (
            '<th style="padding: 9px 8px; text-align: center; font-weight: 800; color: #065f46; font-size: 12px; '
            'line-height: 1.5; border-bottom: 1.5px solid rgba(5,150,105,0.25);">' + inner + "</th>"
        )
    return (
        f'<td style="padding: 9px 8px; text-align: {align}; vertical-align: top; color: #374151; font-size: 12px; '
        'line-height: 1.6; border-bottom: 1px solid #f3f4f6;">' + inner + "</td>"
    )


def _render_md_table(rows: Sequence[Sequence[str]]) -> str:
    """把 Markdown 表格渲染为微信友好的内联样式 <table>，避免管道行被当成正文段落。"""
    if not rows:
        return ""
    header = list(rows[0])
    body = [list(r) for r in rows[1:]]
    aligns = ["center"] * len(header)
    if body and _is_md_separator_row(body[0]):
        aligns = [
            "center" if (c.startswith(":") and c.endswith(":")) else "right" if c.endswith(":") else "left"
            for c in body[0]
        ]
        body = body[1:]
    width = max([len(header)] + [len(r) for r in body]) if body else len(header)

    def _pad(cells: list[str]) -> list[str]:
        return (cells + [""] * width)[:width]

    head_html = "".join(_render_md_cell(c, header=True, align="center") for c in _pad(header))
    body_rows = ""
    for row in body:
        tds = "".join(
            _render_md_cell(c, header=False, align=aligns[i] if i < len(aligns) else "left")
            for i, c in enumerate(_pad(row))
        )
        body_rows += f"      <tr>{tds}</tr>\n"
    return f"""  <section style="margin: 0 0 26px;">
    <table style="width: 100%; border-collapse: collapse; background: #ffffff; border: 1.5px solid rgba(5,150,105,0.18); border-radius: 10px; overflow: hidden;">
      <thead>
      <tr style="background: #ECFDF5;">{head_html}</tr>
      </thead>
      <tbody>
{body_rows}      </tbody>
    </table>
  </section>"""


def _hoist_md_tables(markdown_text: str) -> str:
    """把「| ... |」Markdown 表格整块折叠为单行占位符，交由主循环整体渲染。"""
    hoisted: list[str] = []
    block: list[str] = []

    def _flush() -> None:
        if block:
            encoded = "\x02".join("\x01".join(_split_md_row(r)) for r in block)
            hoisted.append(_MD_TABLE_SENTINEL + encoded)
            block.clear()

    for raw in markdown_text.splitlines():
        if raw.strip().startswith("|"):
            block.append(raw)
            continue
        _flush()
        hoisted.append(raw)
    _flush()
    return "\n".join(hoisted)


# 2026-10-15 定稿红线（AGENTS.md §7 ② + docs/dsh/moyu-green-wechat-spec-2026-10-12.md）：
# 文末「往期推荐」固定 5 篇。此前只有渲染侧软兜底（len(recs) >= 5 即 break），run 级
# wechat-config.json 给 6 篇照样全绿出厂——case-008 实测渲染出 6 篇且校验器只查「往期推荐」
# 四个字是否存在，不查条数。这里把条数收敛成硬约束：渲染侧规范化 + 校验侧真门禁。
RECOMMENDATION_FIXED_COUNT = 5
RECOMMENDATION_PIN = "📌 "


def normalize_recommendations(
    recommendations: Sequence[Mapping[str, str]],
    *,
    title: str = "",
    work_badge: str = "",
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """把「往期推荐」规范化为恰好 RECOMMENDATION_FIXED_COUNT 篇，并返回可审计的处置记录。

    - 多于 5 篇：按输入顺序截断，被丢弃的标题进 audit["dropped"]（不静默丢弃）。
    - 少于 5 篇：用 CANONICAL_MOTHER_TEXTS 母本补齐，补入的标题进 audit["padded"]。
    - 标题重复/空标题：只保留第一条，同样进 audit["dropped"]。
    """
    recs: list[dict[str, str]] = []
    seen: set[str] = set()
    dropped: list[str] = []
    for raw in recommendations or []:
        item = {str(k): str(v) for k, v in dict(raw).items()}
        rec_title = (item.get("title") or "").strip()
        if not rec_title or rec_title in seen:
            if rec_title:
                dropped.append(rec_title)
            continue
        seen.add(rec_title)
        recs.append(item)

    padded: list[str] = []
    if len(recs) < RECOMMENDATION_FIXED_COUNT:
        from article_group.dna_engine import CANONICAL_MOTHER_TEXTS

        for mother in CANONICAL_MOTHER_TEXTS:
            if len(recs) >= RECOMMENDATION_FIXED_COUNT:
                break
            mother_title = f"《{mother['title']}》"
            if mother_title in seen or mother["title"] == title:
                continue
            if work_badge and work_badge[:4] in mother["title"]:
                continue
            seen.add(mother_title)
            recs.append({
                "title": mother_title,
                "desc": f"{mother['archetype']}标杆深文：剥开名利场温情脉脉的面纱，把每一分现实代价算到骨头里。",
            })
            padded.append(mother_title)

    if len(recs) > RECOMMENDATION_FIXED_COUNT:
        dropped.extend(r.get("title", "") for r in recs[RECOMMENDATION_FIXED_COUNT:])
        recs = recs[:RECOMMENDATION_FIXED_COUNT]

    audit = {
        "target": RECOMMENDATION_FIXED_COUNT,
        "action": "padded" if padded else ("truncated" if dropped else "ok"),
        "padded": padded,
        "dropped": [d for d in dropped if d],
        "count": len(recs),
    }
    return recs, audit


def render_moyu_green_bundle(
    markdown_text: str,
    *,
    title: str,
    subtitle_points: Sequence[str],
    category_tag: str,
    work_badge: str,
    year_month: str = "2026.10",
    interaction_question: str,
    interaction_invite: str,
    recommendations: Sequence[Mapping[str, str]],
    page_slug: str = "article",
    run_root: str | Path | None = None,
    include_cover_card: bool = False,
    include_top_follow: bool = False,
    embed_images: bool = False,
) -> dict[str, Any]:
    """将 Markdown 正文渲染为符合摸鱼绿杂志风规范的 body.html、preview.html 与 delivery.md。

    include_top_follow=False：去掉头部名片式关注条（正文直接从开篇切入）。
    embed_images=False：不在 body.html 里写本地 `<img>`（微信公众号编辑器无法抓取本地/
    相对路径图片，粘贴后必然碎图），只保留居中图注行作为「插图锚点」，正图由人工在编辑器
    内上传或粘贴（见 wechat/image-gallery.html）。
    """
    clean_title = _normalize_cjk_punct(title.strip())
    subtitle_str = " · ".join(_normalize_cjk_punct(p.strip()) for p in subtitle_points if p.strip())
    root_path = Path(run_root).resolve() if run_root else None

    # 红线：往期推荐固定 5 篇（不论调用方给几条，出厂恒为 5 条并留下处置记录）
    recommendations, recommendation_audit = normalize_recommendations(
        recommendations, title=title, work_badge=work_badge
    )

    out: list[str] = []
    out.append(
        "<section style=\"max-width: 677px; margin: 0 auto; background: #ffffff; font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif; color: #374151; font-size: 15px; line-height: 1.8; letter-spacing: 0.5px; padding: 12px 16px;\">"
    )

    # 【组件 1】双层封面大卡片（Breaking Cover · 可选模式 B 纯净首屏）
    if include_cover_card:
        out.append(f"""  <section style="margin: 0 0 28px; background: #ffffff; border: 1.5px solid rgba(5,150,105,0.18); border-radius: 16px; overflow: hidden; box-shadow: 0 4px 16px rgba(0,0,0,0.04);">
    <section style="padding: 24px 20px 20px;">
      <section style="display: flex; align-items: center; gap: 8px; margin-bottom: 16px;">
        <span style="width: 8px; height: 8px; background: #059669; border-radius: 50%; display: inline-block;"></span>
        <span style="font-size: 11px; font-weight: 700; letter-spacing: 2px; color: #059669;"><span leaf="">若雨随影 · 影视暗房</span></span>
        <section style="flex: 1; height: 1px; background: rgba(5,150,105,0.15);"></section>
        <span style="font-size: 11px; color: #9CA3AF; font-weight: 600;"><span leaf="">{_esc(year_month)}</span></span>
      </section>
      <h1 style="font-size: 20px; font-weight: 900; color: #111827; margin: 0 0 12px; line-height: 1.4; letter-spacing: -0.5px;">
        <span leaf="">{_esc(clean_title)}</span>
      </h1>
      <section style="width: 42px; height: 3px; background: #059669; border-radius: 2px; margin-bottom: 12px;"></section>
      <p style="font-size: 13px; color: #6B7280; margin: 0; line-height: 1.6;">
        <span leaf="">{_esc(subtitle_str)}</span>
      </p>
    </section>
    <section style="background: #059669; padding: 8px 20px; display: flex; align-items: center; justify-content: space-between;">
      <span style="font-size: 11px; color: rgba(255,255,255,0.95); font-weight: 600;"><span leaf="">{_esc(category_tag)}</span></span>
      <span style="background: rgba(255,255,255,0.22); padding: 2px 8px; border-radius: 4px; font-size: 9px; color: #ffffff; font-weight: 700;"><span leaf="">{_esc(work_badge)}</span></span>
    </section>
  </section>""")

    # 【组件 2】头部名片关注条（Top Follow Hook · 按 run 配置可关闭）
    if include_top_follow:
        out.append("""  <!-- 头部关注引导条 -->
  <table width="100%" border="0" cellpadding="0" cellspacing="0" style="border-collapse: collapse; margin: 0 0 24px; background: #f0fdf4; border: 1.5px solid #a7f3d0; border-radius: 12px; box-shadow: 0 2px 8px rgba(5,150,105,0.05);">
    <tr>
      <td style="padding: 12px 14px; vertical-align: middle;">
        <table border="0" cellpadding="0" cellspacing="0" style="border-collapse: collapse;">
          <tr>
            <td style="width: 38px; height: 38px; background: #059669; border-radius: 50%; text-align: center; vertical-align: middle; font-size: 18px; color: #ffffff;">
              <span leaf="">🍵</span>
            </td>
            <td style="padding-left: 10px; vertical-align: middle;">
              <p style="margin: 0; font-size: 14px; font-weight: 800; color: #065f46; line-height: 1.4; white-space: nowrap;">
                <span leaf="">关注【若雨随影】</span>
              </p>
              <p style="margin: 2px 0 0; font-size: 12px; color: #047857; line-height: 1.4; white-space: nowrap;">
                <span leaf="">扒光名利场算盘 · 算透人性账本</span>
              </p>
            </td>
          </tr>
        </table>
      </td>
      <td style="padding: 12px 14px; text-align: right; vertical-align: middle;">
        <span style="display: inline-block; background: #059669; border-radius: 20px; padding: 6px 14px; font-size: 11px; font-weight: 800; color: #ffffff; letter-spacing: 0.5px; white-space: nowrap;"><span leaf="">+ 关注</span></span>
      </td>
    </tr>
  </table>""")

    # 【组件 3】正文叙事与呼吸感
    seen_quote_cards: set[str] = set()
    delivery_md_lines: list[str] = [
        f"# {clean_title}",
        "",
        "> 🍵 **关注【若雨随影】**：只聊最真实的人性博弈，算透名利场现实账本。点击顶部蓝字关注，好文不错过。",
        "",
        "---",
        "",
    ]

    for raw_line in _hoist_md_tables(markdown_text).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Markdown 表格整块占位符 ➔ 渲染为内联样式 <table>
        if line.startswith(_MD_TABLE_SENTINEL):
            raw_table = line[len(_MD_TABLE_SENTINEL):]
            table_rows = [r.split("\x01") for r in raw_table.split("\x02")]
            out.append(_render_md_table(table_rows))
            delivery_md_lines.append("\n".join("| " + " | ".join(r) + " |" for r in table_rows) + "\n")
            continue
        # 跳过顶层 H1 标题和 Markdown 图片占位符（微信纯享内联正文不带本地断裂死图路径）
        if line.startswith("# "):
            continue
        m_img = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", line)
        if m_img:
            alt, src_rel = m_img.group(1).strip(), m_img.group(2).strip()
            # 校验图片是否在 run_root 下真实存在，存在则渲染标准微信内联图文卡片
            img_file = root_path / src_rel if root_path else None
            if img_file and img_file.is_file():
                if embed_images:
                    img_card = f"""  <section style="margin: 24px 0; text-align: center;">
    <img src="{_esc_attr(src_rel)}" alt="{_esc_attr(alt)}" style="max-width: 100%; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.06); display: block; margin: 0 auto;" />
    <p style="margin: 8px 0 0; font-size: 13px; color: #6b7280; text-align: center; line-height: 1.5;"><span leaf="">▲ {_esc(_normalize_cjk_punct(alt))}</span></p>
  </section>"""
                    out.append(img_card)
                else:
                    # 微信编辑器抓不到本地图片：正文只保留居中图注行作为「插图锚点」
                    out.append(
                        f"""  <p style="margin: 22px 0 18px; font-size: 13px; color: #6b7280; text-align: center; line-height: 1.5;"><span leaf="">▲ {_esc(_normalize_cjk_punct(alt))}</span></p>"""
                    )
                delivery_md_lines.append(f"![{_normalize_cjk_punct(alt)}]({src_rel})\n\n*▲ {_normalize_cjk_punct(alt)}*\n")
            continue
        if line == "---":
            out.append(_render_divider())
            delivery_md_lines.append("\n---\n")
            continue
        if line.startswith("## ") or line.startswith("### "):
            heading_text = re.sub(r"^#{2,3}\s+", "", line).strip()
            m_badge = re.match(r"^([一二三四五六七八九十]+、)\s*(.+)$", heading_text)
            if m_badge:
                badge, h_title = m_badge.group(1), m_badge.group(2)
            else:
                badge, h_title = "●", heading_text
            out.append(_render_section_heading(badge, h_title))
            delivery_md_lines.append(f"### {badge}{_normalize_cjk_punct(h_title)}\n")
            continue
        if line.startswith("* ") or line.startswith("- "):
            item_text = line[2:].strip()
            out.append(_render_bullet_item(item_text))
            delivery_md_lines.append(f"* {_normalize_cjk_punct(item_text)}")
            continue
        m_num_list = re.match(r"^(\d+\.)\s+(.+)$", line)
        if m_num_list:
            num_badge, item_text = m_num_list.group(1), m_num_list.group(2).strip()
            out.append(_render_numbered_item(num_badge, item_text))
            delivery_md_lines.append(f"{num_badge} {_normalize_cjk_punct(item_text)}")
            continue
        if line.startswith("> "):
            quote_body = re.sub(r"^>\s*", "", line).strip()
            clean_q = re.sub(r"^\*\*|\*\*$", "", _normalize_cjk_punct(quote_body)).strip()
            if clean_q and clean_q not in seen_quote_cards:
                seen_quote_cards.add(clean_q)
                out.append(_render_quote_card(clean_q))
                delivery_md_lines.append(f"> **{clean_q}**\n")
            continue
        # 独立整行加粗金句 ➔ 转换为单侧 4px 墨绿竖线浅绿卡（去重防堆叠）
        if line.startswith("**") and line.endswith("**") and line.count("**") == 2:
            core_sentence = _normalize_cjk_punct(line[2:-2].strip())
            if core_sentence not in seen_quote_cards:
                seen_quote_cards.add(core_sentence)
                out.append(_render_quote_card(core_sentence))
                delivery_md_lines.append(f"> **{core_sentence}**\n")
            else:
                out.append(_render_inline_paragraph(line))
                delivery_md_lines.append(f"{_normalize_cjk_punct(line)}\n")
            continue

        out.append(_render_inline_paragraph(line))
        delivery_md_lines.append(f"{_normalize_cjk_punct(line)}\n")

    # 正文结束后的三点呼吸分隔线
    out.append(_render_divider())

    # 【组件 4】读者互动卡（Interaction）
    q_norm = _normalize_cjk_punct(interaction_question.strip())
    inv_norm = _normalize_cjk_punct(interaction_invite.strip())
    out.append(f"""  <section style="margin: 36px 0 20px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px 18px;">
    <section style="display: flex; align-items: center; gap: 8px; margin-bottom: 10px;">
      <span style="font-size: 17px;"><span leaf="">💬</span></span>
      <h3 style="margin: 0; font-size: 16px; font-weight: 800; color: #1e293b;"><span leaf="">读者互动</span></h3>
    </section>
    <p style="margin: 0 0 10px; color: #374151; line-height: 1.8; text-align: left;"><span leaf="">{_esc(q_norm)}</span></p>
    <p style="margin: 0 0 10px; color: #374151; line-height: 1.8; text-align: left;"><strong style="color: #111827;"><span leaf="">{_esc(inv_norm)}</span></strong></p>
    <p style="margin: 0; font-size: 13px; color: #64748b; line-height: 1.7; text-align: left;"><span leaf="">觉得这篇现实拆解有用，欢迎收藏或转发给身边需要的人。</span></p>
  </section>""")

    # 【组件 5】文末显眼关注大卡（Footer Follow CTA Card · 核心转化）
    out.append("""  <!-- 显眼直接的文末关注卡片 -->
  <section style="margin: 32px 0 24px; background: #f0fdf4; border: 1.5px solid #059669; border-radius: 14px; padding: 22px 18px; box-shadow: 0 4px 16px rgba(5, 150, 105, 0.1);">
    <section style="display: flex; align-items: center; margin-bottom: 12px;">
      <span leaf="" style="display: inline-block; width: 4px; height: 18px; background-color: #059669; border-radius: 2px; margin-right: 8px;"></span>
      <span leaf="" style="font-size: 16px; font-weight: 800; color: #065f46; letter-spacing: 0.5px;">🍵 关注【若雨随影】</span>
    </section>
    <p style="margin: 0 0 10px; font-size: 14.5px; color: #1f2937; line-height: 1.75; text-align: left;">
      <span leaf="">这里没有浮夸的宣发吹捧，不吃资本的人情通稿。</span>
    </p>
    <p style="margin: 0 0 14px; font-size: 14.5px; color: #1f2937; line-height: 1.75; text-align: left;">
      <span leaf="">我们只做一件事：</span><strong style="color: #065f46;"><span leaf="">把影视剧里的人性博弈、权力交换与现实账本，算得明明白白。</span></strong>
    </p>
    <section style="background-color: #ffffff; border-radius: 8px; padding: 12px 14px; margin-bottom: 14px; border: 1px solid #d1fae5;">
      <p style="margin: 0 0 6px; font-size: 13px; color: #374151; line-height: 1.6; text-align: left;">
        <span leaf="" style="color: #059669; font-weight: bold;">📌 硬核拆台：</span><span leaf="">穿透影视宣发滤镜，看懂资本造星把戏</span>
      </p>
      <p style="margin: 0 0 6px; font-size: 13px; color: #374151; line-height: 1.6; text-align: left;">
        <span leaf="" style="color: #059669; font-weight: bold;">📌 算透现实：</span><span leaf="">透过银幕名利场，讲透普通人的生存算盘</span>
      </p>
      <p style="margin: 0; font-size: 13px; color: #374151; line-height: 1.6; text-align: left;">
        <span leaf="" style="color: #059669; font-weight: bold;">📌 每周精选：</span><span leaf="">输出高密度深度长文，绝无水话套话</span>
      </p>
    </section>
    <section style="text-align: center; padding: 12px 14px; background-color: #059669; border-radius: 8px; margin-bottom: 10px; box-shadow: 0 3px 10px rgba(5,150,105,0.2);">
      <p style="margin: 0; font-size: 14px; font-weight: 800; color: #ffffff; letter-spacing: 0.5px;">
        <span leaf="">👉 点击顶部蓝字关注「若雨随影」</span>
      </p>
    </section>
    <p style="margin: 0; font-size: 12px; color: #4b5563; text-align: center; line-height: 1.6;">
      <span leaf="">⭐️ 微信改版后极易被冲散，关注后顺手点击右上角「…」</span><strong style="color: #065f46;"><span leaf="">【设为星标】</span></strong><span leaf="">，好文不错过。</span>
    </p>
  </section>""")

    # 【组件 6】往期推荐（Recommendation · 严格兼容微信公众号原生图文超链接属性）
    rec_list = list(recommendations)
    total_recs = len(rec_list)
    rec_items_html: list[str] = []
    for idx, rec in enumerate(rec_list):
        rec_title = _normalize_cjk_punct(rec.get("title", "").strip())
        # 纯净标题（剥离《》与前缀emoji，供微信编辑器识别为图文文章真实标题）
        pure_title = re.sub(r"^[📌s]+|[《》「」]", "", rec_title).strip()
        rec_desc = _normalize_cjk_punct(rec.get("desc", "").strip())
        rec_url = str(rec.get("url") or rec.get("link") or "").strip()
        border_style = " border-bottom: 1px solid #ecfdf5;" if idx < total_recs - 1 else ""
        margin_b = "12px" if idx < total_recs - 1 else "8px"
        if rec_url:
            # 微信公众号官方规范：📌在<a>外，<a>带textvalue/data-itemshowtype/linktype/data-linktype
            title_node = f'<span leaf="">📌&nbsp;<a target="_blank" href="{_esc_attr(rec_url)}" textvalue="{_esc_attr(pure_title)}" data-itemshowtype="0" linktype="text" data-linktype="2" style="color: #065f46; text-decoration: none;"><span leaf="">{_esc(pure_title)}</span></a></span>'
        else:
            title_node = f'<span leaf="">📌&nbsp;{_esc(pure_title)}</span>'
        desc_node = f"""
      <p style="margin: 0; font-size: 12.5px; color: #4b5563; line-height: 1.6; text-align: left;"><span leaf="">{_esc(rec_desc)}</span></p>""" if rec_desc else ""
        rec_items_html.append(f"""    <section style="margin-bottom: {margin_b}; padding: 10px 0 12px;{border_style}">
      <p style="margin: 0 0 4px; font-size: 14px; color: #065f46; line-height: 1.6;">{title_node}</p>{desc_node}
    </section>""")

    num_words_map = {1: "这篇", 2: "两篇", 3: "三篇", 4: "四篇", 5: "五篇", 6: "六篇"}
    count_text = num_words_map.get(total_recs, f"{total_recs}篇") if total_recs > 0 else "这些"
    rec_intro_text = f"如果你喜欢这种“撕开体面、算透现实账本”的深度拆解，下面{count_text}也值得继续看："

    out.append(f"""  <section style="margin: 30px 0 18px; padding: 16px 0 4px; border-top: 1px solid #d1fae5; border-bottom: 1px solid #d1fae5;">
    <section style="display: flex; align-items: center; gap: 8px; margin-bottom: 10px;">
      <span style="font-size: 17px;"><span leaf="">🔥</span></span>
      <h3 style="margin: 0; font-size: 16px; font-weight: 800; color: #065f46;"><span leaf="">往期推荐</span></h3>
    </section>
    <p style="font-size: 13px; color: #047857; margin: 0 0 12px; line-height: 1.6; text-align: left;"><span leaf="">{rec_intro_text}</span></p>
{chr(10).join(rec_items_html)}
  </section>""")

    out.append("</section>")
    body_html = "\n".join(out) + "\n"

    preview_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(page_slug)} · 公众号排版预览</title>
<style>
  body{{margin:0;background:#eef0f2;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif;-webkit-text-size-adjust:100%;}}
  .gzh-toolbar{{position:fixed;top:0;left:0;right:0;height:54px;background:#ffffff;box-shadow:0 1px 10px rgba(0,0,0,.08);display:flex;align-items:center;justify-content:space-between;padding:0 16px;z-index:99;}}
  .gzh-hint{{font-size:13px;color:#6b7280;line-height:1.4;}}
  .gzh-hint b{{color:#111827;}}
  .gzh-copy{{background:#059669;color:#fff;border:0;border-radius:9px;padding:10px 20px;font-size:14px;font-weight:700;cursor:pointer;box-shadow:0 3px 10px rgba(5,150,105,.28);white-space:nowrap;transition:transform .08s,background .15s;}}
  .gzh-copy:hover{{background:#047857;}}
  .gzh-copy:active{{transform:translateY(1px);}}
  .gzh-toast{{position:fixed;top:66px;left:50%;transform:translateX(-50%);background:#111827;color:#fff;padding:11px 20px;border-radius:10px;font-size:14px;font-weight:600;opacity:0;pointer-events:none;transition:opacity .25s;z-index:100;box-shadow:0 6px 20px rgba(0,0,0,.25);max-width:88vw;text-align:center;}}
  .gzh-toast.show{{opacity:1;}}
  .gzh-stage{{max-width:700px;margin:78px auto 64px;padding:0 8px;}}
  @media(max-width:520px){{.gzh-hint{{max-width:150px;}}}}
</style>
</head>
<body>
<div class="gzh-toolbar">
  <span class="gzh-hint">预览效果 · <b>摸鱼绿杂志风定稿版</b></span>
  <button class="gzh-copy" id="gzhCopyBtn" onclick="gzhCopy()">📋 复制正文</button>
</div>
<div class="gzh-toast" id="gzhToast"></div>
<div class="gzh-stage">
  <div id="gzh-content">
{body_html.rstrip()}
  </div>
</div>
<script>
  function gzhShowToast(msg){{
    var t=document.getElementById('gzhToast');
    t.textContent=msg;t.classList.add('show');
    clearTimeout(t._timer);
    t._timer=setTimeout(function(){{t.classList.remove('show');}},2800);
  }}
  function gzhCopy(){{
    var el = document.getElementById('gzh-content');
    var btn = document.getElementById('gzhCopyBtn');
    
    // 方案一：优先使用浏览器原生 DOM Range 选择后执行标准 copy 命令
    // 这样浏览器会将完整的渲染图层和 HTML 样式原汁原味注入富文本剪贴板（微信公众平台最完美兼容方式）
    var range = document.createRange();
    range.selectNodeContents(el);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    
    var ok = false;
    try {{
      ok = document.execCommand('copy');
    }} catch(e) {{
      ok = false;
    }}
    sel.removeAllRanges();

    if (ok) {{
      gzhShowToast('✅ 已复制！去公众号编辑器按 Ctrl/⌘+V 粘贴即可');
      var old = btn.textContent;
      btn.textContent = '✅ 已复制';
      setTimeout(function(){{ btn.textContent = old; }}, 2200);
      return;
    }}

    // 方案二：备用方案，使用 ClipboardItem 直接写入原始 HTML
    if (navigator.clipboard && window.isSecureContext && typeof ClipboardItem !== 'undefined') {{
      var blob = new Blob([el.innerHTML], {{ type: 'text/html' }});
      var textBlob = new Blob([el.innerText], {{ type: 'text/plain' }});
      navigator.clipboard.write([
        new ClipboardItem({{ 'text/html': blob, 'text/plain': textBlob }})
      ]).then(function() {{
        gzhShowToast('✅ 已复制！去公众号编辑器按 Ctrl/⌘+V 粘贴即可');
        var old = btn.textContent;
        btn.textContent = '✅ 已复制';
        setTimeout(function(){{ btn.textContent = old; }}, 2200);
      }}).catch(function() {{
        gzhShowToast('⚠ 自动复制受阻，请直接在页面中 Ctrl+A 全选并 Ctrl+C 复制');
      }});
      return;
    }}

    gzhShowToast('⚠ 自动复制受阻，请直接在页面中手动全选复制');
  }}
</script>
</body>
</html>
"""

    delivery_md_lines.extend([
        "",
        "---",
        "",
        "### 💬 读者互动",
        "",
        q_norm,
        "",
        f"**{inv_norm}**",
        "",
        "---",
        "",
        "### 🍵 关注【若雨随影】",
        "",
        "这里没有浮夸的宣发吹捧，不吃资本的人情通稿。我们只做一件事：**把影视剧里的人性博弈、权力交换与现实账本，算得明明白白。**",
        "",
        "👉 **点击顶部蓝字关注「若雨随影」，顺手设为星标，好文不错过。**",
        "",
    ])
    if rec_list:
        delivery_md_lines.extend([
            "",
            "---",
            "",
            "### 🔥 往期推荐",
            "",
            rec_intro_text,
            "",
        ])
        for rec in rec_list:
            r_title = _normalize_cjk_punct(rec.get("title", "").strip())
            r_desc = _normalize_cjk_punct(rec.get("desc", "").strip())
            r_url = str(rec.get("url") or rec.get("link") or "").strip()
            if r_url:
                delivery_md_lines.append(f"* [📌 {r_title}]({r_url})")
            else:
                delivery_md_lines.append(f"* 📌 {r_title}")
            if r_desc:
                delivery_md_lines.append(f"  {r_desc}")
            delivery_md_lines.append("")
    delivery_md = "\n".join(delivery_md_lines)

    return {
        "body_html": body_html,
        "preview_html": preview_html,
        "delivery_md": delivery_md,
        "source_draft_sha256": hashlib.sha256(markdown_text.encode("utf-8")).hexdigest(),
        "body_sha256": hashlib.sha256(body_html.encode("utf-8")).hexdigest(),
        "preview_sha256": hashlib.sha256(preview_html.encode("utf-8")).hexdigest(),
        "delivery_md_sha256": hashlib.sha256(delivery_md.encode("utf-8")).hexdigest(),
        "recommendation_audit": recommendation_audit,
    }


WECHAT_RENDER_FLAGS_DEFAULT: dict[str, bool] = {
    "include_cover_card": False,
    # 2026-10-14 用户定稿标准：文首不配名片式关注条（正文直接从开篇切入；文末关注大卡保留）
    "include_top_follow": False,
    # 2026-10-14 用户定稿标准：正文不内嵌本地图片（微信编辑器抓不到本地/相对路径图片，粘贴必碎图），
    # 只保留居中图注行作锚点，配图由人工经 wechat/image-gallery.html 逐张复制/上传插入
    "embed_images": False,
}


def load_wechat_render_flags(run_root: str | Path) -> dict[str, bool]:
    """渲染用开关：run 级 wechat-config.json 覆盖 → 否则用定稿默认值。"""
    root = Path(run_root).resolve()
    cfg: dict[str, Any] = {}
    cfg_path = root / "wechat-config.json"
    if cfg_path.is_file():
        try:
            loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cfg = loaded
        except Exception:
            cfg = {}
    flags = dict(WECHAT_RENDER_FLAGS_DEFAULT)
    for key in flags:
        if key in cfg:
            flags[key] = bool(cfg[key])
    return flags


def load_rendered_wechat_flags(run_root: str | Path) -> dict[str, bool]:
    """校验用开关：以「该 run 实际渲染时用的开关」为准（wechat-manifest.render_flags）。

    渲染开关标准上线前产出的老 run（manifest 无 render_flags）按其历史标准校验，
    不做新标准回溯判定，避免历史交付件被追溯判错。
    """
    root = Path(run_root).resolve()
    manifest_path = root / "wechat" / "wechat-manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
        if isinstance(manifest, dict):
            rendered = manifest.get("render_flags")
            if isinstance(rendered, dict):
                flags = dict(WECHAT_RENDER_FLAGS_DEFAULT)
                for key in flags:
                    if key in rendered:
                        flags[key] = bool(rendered[key])
                return flags
            return {"include_cover_card": False, "include_top_follow": True, "embed_images": True}
    return load_wechat_render_flags(root)


def build_image_gallery_html(
    run_root: str | Path,
    *,
    title: str,
    draft_text: str | None = None,
    embed_static_max_bytes: int = 1_200_000,
) -> dict[str, Any]:
    """构建「公众号配图插入指引」画廊页（wechat/image-gallery.html）。

    微信公众号编辑器无法抓取本地／相对路径图片，粘贴含本地 `<img>` 的 HTML 必然碎图。
    本页把正文里出现的图片按顺序列出：静态图内嵌 base64（file:// 下 canvas 不被污染，
    可一键把图片本体复制进剪贴板，再粘到编辑器里由微信自行上传）；超大的动态 GIF 保留
    相对路径并明确标注「必须用编辑器图片按钮上传」，因为走剪贴板只会丢动画帧。
    """
    import base64

    from article_group.image_processor import parse_image_header

    root = Path(run_root).resolve()
    md = draft_text if draft_text is not None else (root / "draft.md").read_text(encoding="utf-8")

    # 图片登记底账：用于给「需人工上传」的动图回指用户原始文件名
    manifest_map: dict[str, str] = {}
    mf = root / "images" / "image-manifest.json"
    if mf.is_file():
        try:
            for it in (json.loads(mf.read_text(encoding="utf-8")).get("images") or []):
                src_orig = str(it.get("source_original_path") or "")
                if it.get("relative_path") and src_orig:
                    manifest_map[str(it["relative_path"])] = Path(src_orig).name
        except Exception:
            manifest_map = {}

    items: list[dict[str, Any]] = []
    order = 0
    for m in re.finditer(r"!\[([^\]]*)\]\(([^)]+)\)", md):
        rel = m.group(2).strip()
        if rel.startswith(("http://", "https://", "data:")):
            continue
        fp = root / rel
        if not fp.is_file():
            continue
        order += 1
        alt = _normalize_cjk_punct(m.group(1).strip())
        try:
            meta = parse_image_header(fp)
        except Exception:
            meta = {"format": "unknown", "width": 0, "height": 0}
        fmt = str(meta.get("format") or "unknown")
        size_bytes = fp.stat().st_size
        embed = fmt != "gif" and size_bytes <= embed_static_max_bytes
        src = f"data:image/{fmt};base64," + base64.b64encode(fp.read_bytes()).decode("ascii") if embed else rel
        items.append({
            "order": order,
            "rel": rel,
            "name": fp.name,
            "alt": alt,
            "src": src,
            "embedded": embed,
            "format": fmt,
            "width": int(meta.get("width") or 0),
            "height": int(meta.get("height") or 0),
            "size_mb": round(size_bytes / 1048576, 2),
            "is_gif": fmt == "gif",
            "source_name": manifest_map.get(rel, ""),
        })

    rows: list[str] = []
    for it in items:
        idx = it["order"]
        gif_note = (
            '<p class="gifnote">🎞️ 动态 GIF：请用公众号编辑器「图片 → 上传」选择该文件（走剪贴板只会保留一帧、丢失动画）。'
            + (f'<br>原始文件：{_esc(it["source_name"])}（就在你放插图的文件夹里）' if it.get("source_name") else "")
            + '</p>'
            if it["is_gif"]
            else ""
        )
        btn = (
            f'<button class="copybtn" onclick="copyShot(\'shot{idx}\', true)">🎞️ 动图不可剪贴板复制</button>'
            if it["is_gif"]
            else f'<button class="copybtn" onclick="copyShot(\'shot{idx}\', false)">📋 复制这张图</button>'
        )
        rows.append(f"""  <section class="card">
    <section class="head">
      <span class="badge">{idx:02d}</span>
      <span class="fname">{_esc(it['name'])}</span>
      <span class="meta">{_esc(it['format'].upper())} · {it['width']}×{it['height']} · {it['size_mb']}MB</span>
    </section>
    <img id="shot{idx}" class="shot" src="{it['src']}" alt="{_esc(it['alt'])}" />
    <p class="anchor">正文里的插入锚点（把图片粘在这一行上方）：</p>
    <p class="anchortext">▲ {_esc(it['alt'])}</p>
    <p class="path">文件位置：{_esc(it['rel'])}</p>
    {gif_note}
    {btn}
  </section>""")

    body = "\n".join(rows) if rows else '<p class="empty">正文里没有检测到本地配图。</p>'
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)} · 公众号配图插入指引</title>
<style>
  body{{margin:0;background:#eef0f2;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif;color:#111827;-webkit-text-size-adjust:100%;}}
  .wrap{{max-width:860px;margin:0 auto;padding:24px 14px 60px;}}
  h1{{font-size:20px;font-weight:800;margin:0 0 6px;}}
  .sub{{font-size:13px;color:#6b7280;margin:0 0 18px;line-height:1.7;}}
  .steps{{background:#f0fdf4;border:1.5px solid #a7f3d0;border-radius:12px;padding:14px 18px;margin:0 0 22px;}}
  .steps li{{font-size:13.5px;color:#065f46;line-height:1.9;}}
  .card{{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:16px 18px 18px;margin:0 0 18px;box-shadow:0 3px 14px rgba(0,0,0,.05);}}
  .head{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px;}}
  .badge{{background:#059669;color:#fff;font-size:12px;font-weight:800;padding:3px 9px;border-radius:6px;}}
  .fname{{font-size:13.5px;font-weight:700;color:#065f46;font-family:Consolas,Monaco,monospace;}}
  .meta{{font-size:12px;color:#9ca3af;}}
  .shot{{max-width:100%;height:auto;display:block;margin:0 auto;border-radius:8px;box-shadow:0 4px 14px rgba(0,0,0,.08);}}
  .anchor{{font-size:12.5px;color:#6b7280;margin:14px 0 4px;}}
  .anchortext{{font-size:13.5px;color:#374151;margin:0 0 4px;background:#f9fafb;border-left:3px solid #059669;padding:7px 10px;border-radius:0 6px 6px 0;}}
  .path{{font-size:12px;color:#9ca3af;margin:6px 0 0;font-family:Consolas,Monaco,monospace;}}
  .gifnote{{font-size:12.5px;color:#92400e;background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:8px 10px;margin:10px 0 0;line-height:1.7;}}
  .copybtn{{margin-top:12px;background:#059669;color:#fff;border:0;border-radius:9px;padding:9px 18px;font-size:13.5px;font-weight:700;cursor:pointer;}}
  .copybtn:hover{{background:#047857;}}
  .empty{{font-size:14px;color:#6b7280;}}
  .toast{{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);background:#111827;color:#fff;padding:11px 20px;border-radius:10px;font-size:13.5px;font-weight:600;opacity:0;pointer-events:none;transition:opacity .25s;max-width:88vw;text-align:center;z-index:99;}}
  .toast.show{{opacity:1;}}
</style>
</head>
<body>
<div class="wrap">
  <h1>{_esc(title)}</h1>
  <p class="sub">共 {len(items)} 张配图 · 按正文出现顺序排列</p>
  <section class="steps">
    <ol>
      <li>先在公众号编辑器里粘贴<strong>纯文字排版稿</strong>（body.html），此时每处插图只剩一行灰色「▲ 图注」。</li>
      <li>回到本页，对每张图点<strong>「📋 复制这张图」</strong>（或右键图片 →「复制图像」）。</li>
      <li>在编辑器里把光标点到对应那条<strong>「▲ 图注」上方</strong>，按 Ctrl/⌘+V —— 微信会自动把图片上传到自己的图库。</li>
    </ol>
    <p style="font-size:12.5px;color:#047857;margin:8px 0 0;line-height:1.7;">也可以直接把 <code>images/</code> 里的文件拖进编辑器，或用编辑器工具栏的「图片 → 上传」——效果与粘贴完全一致。</p>
  </section>
{body}
</div>
<div class="toast" id="toast"></div>
<script>
  function gzhToast(msg){{
    var t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(t._timer);
    t._timer = setTimeout(function(){{ t.classList.remove('show'); }}, 3000);
  }}
  function copyShot(id, isGif){{
    if (isGif) {{
      gzhToast('动图请用编辑器「图片 → 上传」选择文件，剪贴板复制会丢动画');
      return;
    }}
    var img = document.getElementById(id);
    if (!img || !img.complete || !img.naturalWidth) {{
      gzhToast('图片还没加载完，稍等一下再点');
      return;
    }}
    try {{
      var c = document.createElement('canvas');
      c.width = img.naturalWidth;
      c.height = img.naturalHeight;
      c.getContext('2d').drawImage(img, 0, 0);
      c.toBlob(function(blob){{
        if (!blob) {{ gzhToast('转换失败，请右键图片 →「复制图像」'); return; }}
        if (navigator.clipboard && typeof ClipboardItem !== 'undefined') {{
          navigator.clipboard.write([new ClipboardItem({{ 'image/png': blob }})]).then(
            function(){{ gzhToast('✅ 图片已复制！去编辑器锚点处 Ctrl/⌘+V'); }},
            function(){{ gzhToast('⚠ 浏览器拦截了自动复制，请右键图片 →「复制图像」'); }}
          );
        }} else {{
          gzhToast('⚠ 请右键图片 →「复制图像」');
        }}
      }}, 'image/png');
    }} catch (e) {{
      gzhToast('⚠ 请右键图片 →「复制图像」');
    }}
  }}
</script>
</body>
</html>
"""
    return {"html": html, "items": items, "count": len(items)}


def write_moyu_green_run_bundle(
    run_root: str | Path,
    *,
    title: str,
    subtitle_points: Sequence[str],
    category_tag: str,
    work_badge: str,
    year_month: str = "2026.10",
    interaction_question: str,
    interaction_invite: str,
    recommendations: Sequence[Mapping[str, str]],
    page_slug: str = "article",
    author: str = "controller",
    include_cover_card: bool = False,
    include_top_follow: bool = False,
    embed_images: bool = False,
) -> dict[str, Any]:
    """从 run_root/draft.md 渲染摸鱼绿三件套并落盘至 run_root/wechat/，绑定 source_draft_sha256。"""
    root = Path(run_root).resolve()
    draft_path = root / "draft.md"
    raw_bytes = draft_path.read_bytes()
    draft_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    md_text = raw_bytes.decode("utf-8")

    bundle = render_moyu_green_bundle(
        md_text,
        title=title,
        subtitle_points=subtitle_points,
        category_tag=category_tag,
        work_badge=work_badge,
        year_month=year_month,
        interaction_question=interaction_question,
        interaction_invite=interaction_invite,
        recommendations=recommendations,
        page_slug=page_slug,
        run_root=root,
        include_cover_card=include_cover_card,
        include_top_follow=include_top_follow,
        embed_images=embed_images,
    )
    val = validate_moyu_green_html(
        bundle["body_html"],
        allow_no_top_follow=not include_top_follow,
        allow_local_images=embed_images,
    )
    if not val["passed"]:
        raise ValueError(f"moyu_green_validation_failed:{val['errors']}")

    wechat_dir = root / "wechat"
    write_evidence(wechat_dir / "body.html", bundle["body_html"], run_dir=root, reason="moyu_green:body_html", author=author)
    write_evidence(wechat_dir / "preview.html", bundle["preview_html"], run_dir=root, reason="moyu_green:preview_html", author=author)
    write_evidence(wechat_dir / "delivery.md", bundle["delivery_md"], run_dir=root, reason="moyu_green:delivery_md", author=author)

    gallery = build_image_gallery_html(root, title=title, draft_text=md_text)
    write_evidence(wechat_dir / "image-gallery.html", gallery["html"], run_dir=root, reason="moyu_green:image_gallery", author=author)

    manifest = {
        "template": "ruoyu-moyu-green-2026-10-12",
        "validation": val,
        "recommendations": {
            "fixed_count": RECOMMENDATION_FIXED_COUNT,
            "rendered_count": val.get("recommendation_count"),
            "normalization": bundle.get("recommendation_audit", {}),
        },
        "source_draft_sha256": draft_sha256,
        "body_sha256": bundle["body_sha256"],
        "preview_sha256": bundle["preview_sha256"],
        "delivery_md_sha256": bundle["delivery_md_sha256"],
        "render_flags": {
            "include_cover_card": include_cover_card,
            "include_top_follow": include_top_follow,
            "embed_images": embed_images,
        },
        "image_gallery": {
            "path": "wechat/image-gallery.html",
            "image_count": gallery["count"],
            "body_html_embeds_local_images": embed_images,
        },
        "publication_authorization": "not_authorized",
    }
    write_evidence_json(wechat_dir / "wechat-manifest.json", manifest, run_dir=root, reason="moyu_green:manifest", author=author)
    return manifest


def render_moyu_green_from_run(
    run_root: str | Path,
    *,
    author: str = "controller",
) -> dict[str, Any]:
    """从 run 目录的 title-pack.json、article-brief.json、evidence-pack.json（及可选的 wechat-config.json）
    自动提取分类标签、互动问题与 5 篇真实母本往期推荐，一键生成摸鱼绿三件套（纯净首屏 Mode B 无封面大卡）。
    """
    from article_group.dna_engine import CANONICAL_MOTHER_TEXTS

    root = Path(run_root).resolve()
    draft_path = root / "draft.md"
    if not draft_path.is_file():
        raise ValueError(f"draft_missing:{draft_path}")

    def _load(rel: str) -> dict[str, Any]:
        p = root / rel
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    tp = _load("title-pack.json")
    brief = _load("article-brief.json")
    ev = _load("evidence-pack.json")
    wx_cfg = _load("wechat-config.json")

    md_text = draft_path.read_text(encoding="utf-8")
    m_h1 = re.search(r"^#\s+(.+)$", md_text, re.M)
    title = str(
        wx_cfg.get("title")
        or tp.get("selected_title")
        or brief.get("selected_title")
        or (m_h1.group(1).strip() if m_h1 else root.name)
    )

    subtitle_points = wx_cfg.get("subtitle_points") or brief.get("subtitle_points")
    if not subtitle_points:
        # 从正文 H2 小标题自动提炼 3 个精炼看点
        h2s = [
            re.sub(r"^[一二三四五六七八九十]+、\s*", "", m.group(1)).split("，")[0].split("：")[0][:12]
            for m in re.finditer(r"^##\s+(.+)$", md_text, re.M)
        ]
        subtitle_points = h2s[:3] or ["真实细节拉片", "现实利益算盘", "人性冷酷底牌"]

    work_name = str(ev.get("work") or tp.get("work") or brief.get("work") or "深度拆解")
    category_tag = str(
        wx_cfg.get("category_tag")
        or brief.get("category_tag")
        or f"深度剧评 · {work_name[:12]}"
    )
    work_badge = str(
        wx_cfg.get("work_badge")
        or brief.get("work_badge")
        or f"《{work_name[:8].strip('《》')}》深度拆解"
    )
    year_month = str(wx_cfg.get("year_month") or datetime.now().strftime("%Y.%m"))

    interaction_question = str(
        wx_cfg.get("interaction_question")
        or brief.get("interaction_question")
        or brief.get("reader_question")
        or "看完这场把体面撕碎的现实算盘，哪一个细节最让你心里一紧？"
    )
    interaction_invite = str(
        wx_cfg.get("interaction_invite")
        or brief.get("interaction_invite")
        or "欢迎在评论区聊聊你见过的真实人情与利益账本。"
    )

    recommendations = wx_cfg.get("recommendations") or brief.get("recommendations")
    if not recommendations:
        recs: list[dict[str, str]] = []
        for m in CANONICAL_MOTHER_TEXTS:
            if m["title"] != title and work_name[:4] not in m["title"]:
                recs.append({
                    "title": f"《{m['title']}》",
                    "desc": f"{m['archetype']}标杆深文：剥开名利场温情脉脉的面纱，把每一分现实代价算到骨头里。",
                })
            if len(recs) >= 5:
                break
        recommendations = recs

    flags = load_wechat_render_flags(root)

    return write_moyu_green_run_bundle(
        root,
        title=title,
        subtitle_points=subtitle_points,
        category_tag=category_tag,
        work_badge=work_badge,
        year_month=year_month,
        interaction_question=interaction_question,
        interaction_invite=interaction_invite,
        recommendations=recommendations,
        page_slug=root.name,
        author=author,
        include_cover_card=flags["include_cover_card"],
        include_top_follow=flags["include_top_follow"],
        embed_images=flags["embed_images"],
    )


def validate_moyu_green_html(
    body_html: str,
    *,
    allow_pure_reading_flow: bool = True,
    allow_no_top_follow: bool = True,
    allow_local_images: bool = False,
) -> dict[str, Any]:
    """确定性校验「摸鱼绿杂志风」技术红线与组件完整性。

    2026-10-14 用户定稿标准：文首名片式关注条默认不做（需要时由 run 显式开启，
    那时 allow_no_top_follow=False 才会强制要求它存在）。
    2026-10-15 新增红线：往期推荐固定 RECOMMENDATION_FIXED_COUNT（5）篇，按条目锚点实数。
    allow_local_images=True：允许 body.html 内含本地图片路径（仅用于留档预览）；默认禁止，
    因为微信公众号编辑器抓不到本地/相对路径图片，粘贴后必然碎图。
    """
    errors: list[str] = []

    if not body_html.strip().startswith("<section") or not body_html.strip().endswith("</section>"):
        errors.append("outer_container_must_be_section")
    if "max-width: 677px" not in body_html:
        errors.append("missing_max_width_677px")
    if re.search(r"<(?:style|html|body|head)\b", body_html, re.I):
        errors.append("forbidden_outer_or_style_tags_in_body_html")
    if re.search(r"\bclass\s*=", body_html, re.I):
        errors.append("forbidden_class_attribute_in_body_html")
    if re.search(r"position\s*:\s*(?:fixed|sticky)", body_html, re.I):
        errors.append("forbidden_fixed_or_sticky_in_body_html")
    if "若雨随影 · 影视暗房" not in body_html and not allow_pure_reading_flow:
        errors.append("missing_component_1_breaking_cover")
    if not allow_no_top_follow:
        if "+ 关注" not in body_html or "扒光名利场算盘 · 算透人性账本" not in body_html:
            errors.append("missing_component_2_top_follow_hook")
    if "读者互动" not in body_html:
        errors.append("missing_component_4_interaction_card")
    if "👉 点击顶部蓝字关注「若雨随影」" not in body_html or "【设为星标】" not in body_html:
        errors.append("missing_component_5_footer_follow_cta")
    # 【组件 6 红线】往期推荐固定 5 篇：只查「往期推荐」四个字存在是不够的——
    # case-008 就是四字齐全但实际 6 篇、门禁全绿出厂。这里按条目锚点 📌 实数。
    rec_section = body_html[body_html.index("往期推荐"):] if "往期推荐" in body_html else ""
    recommendation_count = rec_section.count(RECOMMENDATION_PIN)
    if not rec_section:
        errors.append("missing_component_6_recommendations")
    elif recommendation_count != RECOMMENDATION_FIXED_COUNT:
        errors.append(
            f"recommendations_must_be_{RECOMMENDATION_FIXED_COUNT}:got_{recommendation_count}"
        )
    if "点击直达" in body_html:
        errors.append("forbidden_fake_click_link_in_recommendations")
    if '<span leaf="">' not in body_html:
        errors.append("missing_leaf_spans")
    if not allow_local_images:
        for src in re.findall(r'<img[^>]*\ssrc="([^"]*)"', body_html, re.I):
            cleaned = src.strip()
            if cleaned and not cleaned.startswith(("http://", "https://", "data:")):
                errors.append(f"local_image_src_forbidden_in_wechat_copy:{cleaned}")

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "leaf_span_count": body_html.count("<span leaf="),
        "recommendation_count": recommendation_count,
    }
