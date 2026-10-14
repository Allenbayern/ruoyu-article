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
) -> dict[str, str]:
    """将 Markdown 正文渲染为符合摸鱼绿杂志风规范的 body.html、preview.html 与 delivery.md。"""
    clean_title = _normalize_cjk_punct(title.strip())
    subtitle_str = " · ".join(_normalize_cjk_punct(p.strip()) for p in subtitle_points if p.strip())
    root_path = Path(run_root).resolve() if run_root else None

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

    # 【组件 2】头部名片关注条（Top Follow Hook · 开头必须有）
    out.append("""  <!-- 头部关注引导条 -->
  <section style="margin: 0 0 24px; background: #f0fdf4; border: 1.5px solid #a7f3d0; border-radius: 12px; padding: 12px 16px; box-shadow: 0 2px 8px rgba(5,150,105,0.05);">
    <section style="display: flex; align-items: center; justify-content: space-between; gap: 10px;">
      <section style="display: flex; align-items: center; gap: 10px;">
        <section style="width: 38px; height: 38px; background: #059669; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 18px; color: #ffffff; flex-shrink: 0;">
          <span leaf="">🍵</span>
        </section>
        <section>
          <p style="margin: 0; font-size: 14px; font-weight: 800; color: #065f46; line-height: 1.4;">
            <span leaf="">关注【若雨随影】</span>
          </p>
          <p style="margin: 2px 0 0; font-size: 12px; color: #047857; line-height: 1.4;">
            <span leaf="">扒光名利场算盘 · 算透人性账本</span>
          </p>
        </section>
      </section>
      <section style="background: #059669; border-radius: 20px; padding: 6px 14px; flex-shrink: 0; text-align: center;">
        <span style="font-size: 11px; font-weight: 800; color: #ffffff; letter-spacing: 0.5px;"><span leaf="">+ 关注</span></span>
      </section>
    </section>
  </section>""")

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

    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line:
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
                img_card = f"""  <section style="margin: 24px 0; text-align: center;">
    <img src="{_esc(src_rel)}" alt="{_esc(alt)}" style="max-width: 100%; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.06); display: block; margin: 0 auto;" />
    <p style="margin: 8px 0 0; font-size: 13px; color: #6b7280; text-align: center; line-height: 1.5;"><span leaf="">▲ {_esc(_normalize_cjk_punct(alt))}</span></p>
  </section>"""
                out.append(img_card)
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

    # 【组件 6】往期推荐（Recommendation · 支持自定义篇数，不承诺点击跳转）
    rec_list = list(recommendations)
    total_recs = len(rec_list)
    rec_items_html: list[str] = []
    for idx, rec in enumerate(rec_list):
        rec_title = _normalize_cjk_punct(rec.get("title", "").strip())
        rec_desc = _normalize_cjk_punct(rec.get("desc", "").strip())
        border_style = " border-bottom: 1px solid #ecfdf5;" if idx < total_recs - 1 else ""
        margin_b = "12px" if idx < total_recs - 1 else "8px"
        rec_items_html.append(f"""    <section style="margin-bottom: {margin_b}; padding: 10px 0 12px;{border_style}">
      <p style="margin: 0 0 4px; font-size: 14px; color: #065f46; line-height: 1.6;"><span leaf="">📌 {_esc(rec_title)}</span></p>
      <p style="margin: 0; font-size: 12.5px; color: #4b5563; line-height: 1.6; text-align: left;"><span leaf="">{_esc(rec_desc)}</span></p>
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
    var el=document.getElementById('gzh-content');
    var html=el.innerHTML;
    var text=el.innerText;
    var btn=document.getElementById('gzhCopyBtn');
    var ok=false;
    var handler=null;
    var ta=document.createElement('textarea');
    try{{
      handler=function(e){{
        if(!e.clipboardData)return;
        e.clipboardData.setData('text/html',html);
        e.clipboardData.setData('text/plain',text);
        e.preventDefault();
      }};
      document.addEventListener('copy',handler,{{once:true}});
      ta.value=text;
      ta.setAttribute('readonly','');
      ta.style.position='fixed';
      ta.style.left='-9999px';
      ta.style.top='0';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      ok=document.execCommand('copy');
    }}catch(e){{
      ok=false;
    }}finally{{
      if(ta.parentNode)ta.parentNode.removeChild(ta);
      if(handler)document.removeEventListener('copy',handler);
    }}
    if(ok){{
      gzhShowToast('✅ 已复制！去公众号编辑器按 Ctrl/⌘+V 粘贴即可');
      var old=btn.textContent;btn.textContent='✅ 已复制';
      setTimeout(function(){{btn.textContent=old;}},2200);
    }}else{{
      gzhShowToast('⚠ 浏览器阻止复制，请换 Edge/Chrome 后重试');
    }}
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
    delivery_md = "\n".join(delivery_md_lines)

    return {
        "body_html": body_html,
        "preview_html": preview_html,
        "delivery_md": delivery_md,
        "source_draft_sha256": hashlib.sha256(markdown_text.encode("utf-8")).hexdigest(),
        "body_sha256": hashlib.sha256(body_html.encode("utf-8")).hexdigest(),
        "preview_sha256": hashlib.sha256(preview_html.encode("utf-8")).hexdigest(),
        "delivery_md_sha256": hashlib.sha256(delivery_md.encode("utf-8")).hexdigest(),
    }


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
    )
    val = validate_moyu_green_html(bundle["body_html"])
    if not val["passed"]:
        raise ValueError(f"moyu_green_validation_failed:{val['errors']}")

    wechat_dir = root / "wechat"
    write_evidence(wechat_dir / "body.html", bundle["body_html"], run_dir=root, reason="moyu_green:body_html", author=author)
    write_evidence(wechat_dir / "preview.html", bundle["preview_html"], run_dir=root, reason="moyu_green:preview_html", author=author)
    write_evidence(wechat_dir / "delivery.md", bundle["delivery_md"], run_dir=root, reason="moyu_green:delivery_md", author=author)

    manifest = {
        "template": "ruoyu-moyu-green-2026-10-12",
        "validation": val,
        "source_draft_sha256": draft_sha256,
        "body_sha256": bundle["body_sha256"],
        "preview_sha256": bundle["preview_sha256"],
        "delivery_md_sha256": bundle["delivery_md_sha256"],
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

    include_cover_card = bool(wx_cfg.get("include_cover_card", False))

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
        include_cover_card=include_cover_card,
    )


def validate_moyu_green_html(body_html: str, *, allow_pure_reading_flow: bool = True) -> dict[str, Any]:
    """确定性校验「摸鱼绿杂志风」5 大技术红线与 6 大组件完整性。"""
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
    if "+ 关注" not in body_html or "扒光名利场算盘 · 算透人性账本" not in body_html:
        errors.append("missing_component_2_top_follow_hook")
    if "读者互动" not in body_html:
        errors.append("missing_component_4_interaction_card")
    if "👉 点击顶部蓝字关注「若雨随影」" not in body_html or "【设为星标】" not in body_html:
        errors.append("missing_component_5_footer_follow_cta")
    if "往期推荐" not in body_html:
        errors.append("missing_component_6_recommendations")
    if "点击直达" in body_html:
        errors.append("forbidden_fake_click_link_in_recommendations")
    if '<span leaf="">' not in body_html:
        errors.append("missing_leaf_spans")

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "leaf_span_count": body_html.count("<span leaf="),
    }
