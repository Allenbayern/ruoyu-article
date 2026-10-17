"""moyu_green_renderer: 若雨随影 2026-10-15 定稿「石墨冷灰大刊风 · 暗黑自适应」微信排版渲染与校验引擎（原摸鱼绿全面升级版）。

严格实现 6 大标准组件（纯净首屏 Mode B）：
1. 【组件 1】双层封面大卡片（Breaking Cover · Mode B 纯净首屏默认不展示大封面，避免与微信系统文章标题机械重复）
2. 【组件 2】头部名片关注条（Top Follow Hook · Mode B 无封面，位于首段前）
3. 【组件 3】正文叙事与呼吸感（16px字号 + 1.75行高 + 炭黑#2d3748 + 01数字浅灰微底胶囊H2 + 3.5px冷灰竖线透明微底卡 + 石墨呼吸分隔线）
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
    return f'  <p style="margin: 0 0 18px; color: #2d3748; font-size: 16px; line-height: 1.75; text-align: justify; letter-spacing: 0.5px;">{inner_html}</p>'


def _render_quote_card(text: str) -> str:
    """单侧 4px 墨绿竖线浅绿卡。"""
    clean = _normalize_cjk_punct(text.strip())
    clean = re.sub(r"^\*\*|\*\*$", "", clean).strip()
    return f"""  <section style="margin: 20px 0; background: rgba(0, 0, 0, 0.025); border-left: 3.5px solid #64748b; padding: 14px 18px; border-radius: 0 8px 8px 0;">
    <p style="margin: 0; font-size: 15.5px; font-weight: 700; color: #1e293b; line-height: 1.75;">
      <span leaf="">{_esc(clean)}</span>
    </p>
  </section>"""


def _render_divider() -> str:
    """三点呼吸分隔线。"""
    return """  <section style="margin: 28px 0; display: flex; align-items: center; justify-content: center; gap: 6px;">
    <span style="width: 4px; height: 4px; background: #94a3b8; border-radius: 50%;"></span>
    <span style="width: 20px; height: 1.5px; background: rgba(148,163,184,0.4); border-radius: 1px;"></span>
    <span style="width: 4px; height: 4px; background: #94a3b8; border-radius: 50%;"></span>
  </section>"""


_CN_NUM_MAP = {
    "一": "01", "二": "02", "三": "03", "四": "04", "五": "05",
    "六": "06", "七": "07", "八": "08", "九": "09", "十": "10",
    "1": "01", "2": "02", "3": "03", "4": "04", "5": "05",
    "6": "06", "7": "07", "8": "08", "9": "09",
}


def _format_badge(badge: str, default_idx: int = 1) -> str:
    cleaned = re.sub(r"[、.\s]", "", badge).strip()
    if cleaned in _CN_NUM_MAP:
        return _CN_NUM_MAP[cleaned]
    if cleaned.isdigit():
        return f"{int(cleaned):02d}"
    return f"{default_idx:02d}"


def _render_section_heading(badge: str, title: str) -> str:
    """方案 A（极简高级杂志风 · 浅底胶囊 + 01数字 + 底部细线）。"""
    num_str = _format_badge(badge)
    clean_title = _normalize_cjk_punct(title.strip())
    return f"""  <section style="margin: 38px 0 20px; padding-bottom: 12px; border-bottom: 1px solid #e2e8f0;">
    <section style="display: flex; align-items: baseline; gap: 10px;">
      <span style="display: inline-block; font-size: 11.5px; font-weight: 800; color: #475569; letter-spacing: 0.5px; background: rgba(0,0,0,0.04); border: 1px solid #cbd5e1; padding: 2px 7px; border-radius: 4px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; vertical-align: middle;"><span leaf="">{_esc(num_str)}</span></span>
      <h2 style="font-size: 18px; font-weight: 800; color: #0f172a; margin: 0; line-height: 1.5; letter-spacing: -0.2px;"><span leaf="">{_esc(clean_title)}</span></h2>
    </section>
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
    <span style="width: 5px; height: 5px; background: #64748b; border-radius: 50%; display: inline-block; flex-shrink: 0; margin-top: 8px;"></span>
    <p style="margin: 0; color: #2d3748; font-size: 16px; line-height: 1.75; text-align: justify;">{"".join(spans)}</p>
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
    <span style="background: rgba(0,0,0,0.04); color: #475569; border: 1px solid #cbd5e1; font-size: 12px; font-weight: 800; padding: 1px 6px; border-radius: 4px; flex-shrink: 0;"><span leaf="">{_esc(num_str)}</span></span>
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
RECOMMENDATION_PIN = "📌"


def normalize_recommendations(
    recommendations: Sequence[Mapping[str, str]] | None = None,
    *,
    title: str = "",
    work_badge: str = "",
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """把「往期推荐」规范化为恰好 RECOMMENDATION_FIXED_COUNT 篇，并返回可审计的处置记录。

    - 允许空白占位条目（用户 2026-10-17 定稿：往期推荐内容默认留空，供公众号后台人工选填）。
    - 若输入为空（None 或 []）：默认填充 5 个空白 📌 占位条目。
    - 若输入为部分非空推荐（1~4 篇）：用 CANONICAL_MOTHER_TEXTS 母本补齐到 5 篇。
    - 多于 5 篇：按输入顺序截断，被丢弃的标题进 audit["dropped"]（不静默丢弃）。
    - 标题重复：只保留第一条，同样进 audit["dropped"]。
    """
    if not recommendations:
        recs = [{"title": "", "desc": ""}] * RECOMMENDATION_FIXED_COUNT
        audit = {
            "target": RECOMMENDATION_FIXED_COUNT,
            "action": "blank_placeholders",
            "padded": [],
            "dropped": [],
            "count": RECOMMENDATION_FIXED_COUNT,
        }
        return recs, audit

    recs: list[dict[str, str]] = []
    seen: set[str] = set()
    dropped: list[str] = []
    for raw in recommendations:
        item = {str(k): str(v) for k, v in dict(raw).items()}
        rec_title = (item.get("title") or "").strip()
        if not rec_title:
            # 允许留空占位项（用户 2026-10-17 定稿：往期推荐内容留空，供公众号后台人工选填）
            recs.append(item)
            continue
        if rec_title in seen:
            dropped.append(rec_title)
            continue
        seen.add(rec_title)
        recs.append(item)

    padded: list[str] = []
    if len(recs) < RECOMMENDATION_FIXED_COUNT:
        if not seen:
            while len(recs) < RECOMMENDATION_FIXED_COUNT:
                recs.append({"title": "", "desc": ""})
        else:
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


def build_cold_start_kit(
    *,
    title: str,
    work_name: str,
    killer_stance: str = "",
    projection_card: Mapping[str, Any] | None = None,
    title_pack: Mapping[str, Any] | None = None,
    category_tag: str = "",
) -> dict[str, Any]:
    """生成微信公众号发布冷启动三件套物料包：
    1. 【置顶引战首评】（50字内，带刺、站队鲜明的大白话追问，严禁写“欢迎留言”与客套话）；
    2. 【朋友圈/社群破冰转发语 × 2条】（模拟读者看完后背发凉或拍案叫绝的第一人称分享语）；
    3. 【黄金推送时间建议】（结合选题属性明确建议午间、晚高峰或深夜档）。
    """
    w = str(work_name or "").strip()
    t = str(title or "").strip()
    s = str(killer_stance or "").strip()
    card = dict(projection_card) if isinstance(projection_card, Mapping) else {}
    tp = dict(title_pack) if isinstance(title_pack, Mapping) else {}

    # 4字封面钩子
    hooks = tp.get("cover_four_word_hooks") or []
    hook1 = hooks[0] if len(hooks) > 0 else "现实账本"
    hook2 = hooks[1] if len(hooks) > 1 else "撕破体面"

    self_rel = str(card.get("self_relevance") or "每一个在生活和职场中被所谓体面所绑架、暗自咽下生存代价的普通人。")
    emo_outlet = str(card.get("emotional_outlet") or "把浮华遮羞布扯碎，替大家骂出那句不敢说出口的现实真相。")
    action_one = str(card.get("expected_reader_action") or "成年人世界所有的体面，背后都暗中标好了现实代价。")

    # a) 首条置顶引战首评（50字内，带刺、站队鲜明的大白话追问，严禁写“欢迎留言”）
    conflict_hint = str(card.get("one_liner_conflict") or "").strip()
    if conflict_hint:
        # 提炼最核心矛盾短语（截取前22字以内）
        short_conflict = conflict_hint[:22].rstrip("，。；！")
        pinned_comment = f"【置顶讨论】{short_conflict}。你觉得这是合理规则还是吃相难看？站哪边？"
    elif w:
        pinned_comment = f"【置顶讨论】台前全是体面交情，台后全在算计利益。你觉得《{w}》里到底谁最虚伪？站哪边？"
    else:
        pinned_comment = "【置顶讨论】台前全是温情脉脉，台后全在算计利益。你觉得这是合理风控还是吃相难看？站哪边？"

    # 剔除一切八股客套话与无力废话
    for polite in ("欢迎留言", "欢迎在评论区聊聊", "欢迎讨论", "请在评论区", "留下一句大实话"):
        pinned_comment = pinned_comment.replace(polite, "")
    pinned_comment = pinned_comment.strip()

    # 严格锁死在 50 汉字以内
    if len(pinned_comment) > 50:
        pinned_comment = pinned_comment[:49] + "？"

    # b) 朋友圈/社群破冰转发语 × 2条（模拟读者看完后背发凉或拍案叫绝的第一人称分享语）
    stance_snippet = s[:30].rstrip("，。；！") if s else "所有的体面崩塌，背后全在按算盘算计利益"
    copy_1 = (
        f"【{hook1}】刚看完全文后背直发凉。成年人世界所有的体面，背后原来全在按这个算法算账。"
        f"《{w}》这部作品拆得太透了，强烈建议身边的朋友都看看。"
        if w else
        f"【{hook1}】刚看完全文后背直发凉。平时根本没注意过这种隐形扣款机关，背后全在按算盘算计老百姓。强烈建议身边的朋友都看看。"
    )
    copy_2 = (
        f"【{hook2}】把浮华遮羞布全扯烂了！“{stance_snippet}”，"
        f"每一句都戳在肺管子上。成年人生活里不敢挑明的那点账，全在这篇里了。"
    )

    # c) 黄金推送时间建议（结合选题属性明确建议午间、晚高峰或深夜档）
    cat_str = f"{category_tag} {t} {w}"
    is_hot_social = any(kw in cat_str for kw in ("保费", "扣费", "避坑", "维权", "打工", "职场", "社会", "民生", "骗局", "弹窗", "套路"))
    is_late_night = any(kw in cat_str for kw in ("老白", "绝命毒师", "老戏骨", "影帝", "周星驰", "岁月", "落幕", "封神", "时代眼泪", "游本昌"))

    if is_hot_social:
        golden_slot = "午间摸鱼黄金档（12:00 ~ 13:00）"
        slot_reason = "此类社会现实/民生算盘/避坑警醒选题，正是打工人午休摸鱼、微信社群与朋友圈最高频转发扩散的黄金窗口，极易引爆群聊二次传播。"
    elif is_late_night:
        golden_slot = "深夜沉浸共鸣档（21:30 ~ 22:30）"
        slot_reason = "经典人物沉浮、名利场清算与时代眼泪选题适合读者睡前独处精读，3500字长文完读率最高，最易激发走心长评与私域收藏。"
    else:
        golden_slot = "晚间下班通勤档（18:30 ~ 19:30）"
        slot_reason = "影视爆款与现实账本大稿兼具吃瓜消遣与深度剖析，契合读者下班通勤、晚饭前后的信息消费高峰。"

    md_lines = [
        "# 🚀 微信发布冷启动物料包（Cold Start Kit）",
        "",
        "> 本物料包用于文章审核通过后的发布运营：通过首条置顶评论引战/逼人表态，激活微信算法热启动；同时提供朋友圈与社群二度分发文案及黄金排期策略。",
        "",
        "---",
        "",
        "## 一、📌 首条置顶引战首评（First Pinned Comment）",
        "*发布后 1 分钟内由作者号发出并设为置顶，50字内带刺追问，严禁写客套话*",
        "",
        f"> **【置顶首评内容】**",
        f"> {pinned_comment}",
        "",
        "- **对立面切口**：逼读者在「面子与里子 / 利益与道德 / 算计与被算计」中站队表态。",
        "- **回复策略**：不论读者站正方还是反方，前 10 条评论在 30 分钟内逐一互动，激发信息流权重。",
        "",
        "---",
        "",
        "## 二、📲 朋友圈 / 社群破冰转发语 × 2条（Distribution Copy）",
        "",
        f"### 方案 1（后背发凉 · 现实账本 · 警醒避坑）",
        f"> {copy_1}",
        "",
        f"*配图建议：使用封面图（带 4 字视觉钩子「{hook1}」）*",
        "",
        f"### 方案 2（拍案叫绝 · 扎心共鸣 · 情绪宣泄）",
        f"> {copy_2}",
        "",
        f"*配图建议：使用封面图（带 4 字视觉钩子「{hook2}」）*",
        "",
        "---",
        "",
        "## 三、⏰ 黄金推送时间建议（Publishing Schedule）",
        f"- **推荐档位**：{golden_slot}",
        f"- **排期策略**：{slot_reason}",
        "",
        "---",
        "",
        "## 四、🎯 读者投射与对焦卡复核",
        f"- **关我什么事**：{self_rel}",
        f"- **情绪出口**：{emo_outlet}",
        f"- **读者看完最想带走并转发的一句话**：{action_one}",
        "",
    ]
    md_text = "\n".join(md_lines)

    return {
        "pinned_comment": pinned_comment,
        "copy_1": copy_1,
        "copy_2": copy_2,
        "hook_1": hook1,
        "hook_2": hook2,
        "golden_slot": golden_slot,
        "slot_reason": slot_reason,
        "self_relevance": self_rel,
        "emotional_outlet": emo_outlet,
        "expected_reader_action": action_one,
        "markdown": md_text,
    }


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
    recommendations: Sequence[Mapping[str, str]] | None = None,
    page_slug: str = "article",
    run_root: str | Path | None = None,
    include_cover_card: bool = False,
    include_top_follow: bool = False,
    embed_images: bool = False,
    cold_start_kit: Mapping[str, Any] | None = None,
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
        "<section style=\"max-width: 677px; margin: 0 auto; background: #ffffff; font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif; color: #2d3748; font-size: 16px; line-height: 1.75; letter-spacing: 0.5px; padding: 12px 16px;\">"
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
    heading_counter = 0
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
            heading_counter += 1
            heading_text = re.sub(r"^#{2,3}\s+", "", line).strip()
            m_badge = re.match(r"^([一二三四五六七八九十]+、|\d+[\.、\s]+)\s*(.+)$", heading_text)
            if m_badge:
                raw_badge, h_title = m_badge.group(1), m_badge.group(2)
                badge = _format_badge(raw_badge, default_idx=heading_counter)
            else:
                badge = f"{heading_counter:02d}"
                h_title = heading_text
            out.append(_render_section_heading(badge, h_title))
            delivery_md_lines.append(f"### {badge} {_normalize_cjk_punct(h_title)}\n")
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
    out.append(f"""  <section style="margin: 36px 0 20px; background: rgba(0,0,0,0.02); border: 1px solid #e2e8f0; border-radius: 12px; padding: 18px 20px;">
    <section style="display: flex; align-items: center; gap: 8px; margin-bottom: 10px;">
      <span style="font-size: 17px;"><span leaf="">💬</span></span>
      <h3 style="margin: 0; font-size: 16px; font-weight: 800; color: #1e293b;"><span leaf="">读者互动</span></h3>
    </section>
    <p style="margin: 0 0 10px; color: #374151; line-height: 1.8; text-align: left;"><span leaf="">{_esc(q_norm)}</span></p>
    <p style="margin: 0 0 10px; color: #374151; line-height: 1.8; text-align: left;"><strong style="color: #111827;"><span leaf="">{_esc(inv_norm)}</span></strong></p>
    <p style="margin: 0; font-size: 13px; color: #64748b; line-height: 1.7; text-align: left;"><span leaf="">觉得这篇现实拆解有用，欢迎收藏或转发给身边需要的人。</span></p>
  </section>""")

    # 【组件 5】文末显眼关注大卡（Footer Follow CTA Card · 核心转化）
    out.append("""  <!-- 显眼直接的文末关注卡片（石墨冷灰高级大刊风 · 暗黑模式0浑浊） -->
  <section style="margin: 34px 0 24px; background: rgba(0,0,0,0.025); border: 1.5px solid #94a3b8; border-radius: 14px; padding: 22px 18px; box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);">
    <section style="display: flex; align-items: center; margin-bottom: 12px;">
      <span leaf="" style="display: inline-block; width: 4px; height: 18px; background-color: #334155; border-radius: 2px; margin-right: 8px;"></span>
      <span leaf="" style="font-size: 16px; font-weight: 800; color: #0f172a; letter-spacing: 0.5px;">🍵 关注【若雨随影】</span>
    </section>
    <p style="margin: 0 0 10px; font-size: 14.5px; color: #334155; line-height: 1.75; text-align: left;">
      <span leaf="">这里没有浮夸的宣发吹捧，不吃资本的人情通稿。</span>
    </p>
    <p style="margin: 0 0 14px; font-size: 14.5px; color: #334155; line-height: 1.75; text-align: left;">
      <span leaf="">我们只做一件事：</span><strong style="color: #0f172a;"><span leaf="">把影视剧里的人性博弈、权力交换与现实账本，算得明明白白。</span></strong>
    </p>
    <section style="background-color: rgba(255,255,255,0.7); border-radius: 8px; padding: 12px 14px; margin-bottom: 14px; border: 1px solid #e2e8f0;">
      <p style="margin: 0 0 6px; font-size: 13px; color: #475569; line-height: 1.6; text-align: left;">
        <span leaf="" style="color: #1e293b; font-weight: bold;">📌 硬核拆台：</span><span leaf="">穿透影视宣发滤镜，看懂资本造星把戏</span>
      </p>
      <p style="margin: 0 0 6px; font-size: 13px; color: #475569; line-height: 1.6; text-align: left;">
        <span leaf="" style="color: #1e293b; font-weight: bold;">📌 算透现实：</span><span leaf="">透过银幕名利场，讲透普通人的生存算盘</span>
      </p>
      <p style="margin: 0; font-size: 13px; color: #475569; line-height: 1.6; text-align: left;">
        <span leaf="" style="color: #1e293b; font-weight: bold;">📌 每周精选：</span><span leaf="">输出高密度深度长文，绝无水话套话</span>
      </p>
    </section>
    <section style="text-align: center; padding: 12px 14px; background-color: #1e293b; border-radius: 8px; margin-bottom: 10px; box-shadow: 0 3px 10px rgba(0,0,0,0.15);">
      <p style="margin: 0; font-size: 14px; font-weight: 800; color: #ffffff; letter-spacing: 0.5px;">
        <span leaf="">👉 点击顶部蓝字关注「若雨随影」</span>
      </p>
    </section>
    <p style="margin: 0; font-size: 12px; color: #64748b; text-align: center; line-height: 1.6;">
      <span leaf="">⭐️ 微信改版后极易被冲散，关注后顺手点击右上角「…」</span><strong style="color: #0f172a;"><span leaf="">【设为星标】</span></strong><span leaf="">，好文不错过。</span>
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
        border_style = " border-bottom: 1px solid #f1f5f9;" if idx < total_recs - 1 else ""
        margin_b = "12px" if idx < total_recs - 1 else "8px"
        if rec_url:
            # 微信公众号官方规范：📌在<a>外，<a>带textvalue/data-itemshowtype/linktype/data-linktype
            title_node = f'<span leaf="">📌&nbsp;<a target="_blank" href="{_esc_attr(rec_url)}" textvalue="{_esc_attr(pure_title)}" data-itemshowtype="0" linktype="text" data-linktype="2" style="color: #1e293b; text-decoration: none; font-weight: 600;"><span leaf="">{_esc(pure_title)}</span></a></span>'
        elif pure_title:
            title_node = f'<span leaf="">📌&nbsp;{_esc(pure_title)}</span>'
        else:
            title_node = '<span leaf="">📌</span>'
        desc_node = f"""
      <p style="margin: 0; font-size: 12.5px; color: #4b5563; line-height: 1.6; text-align: left;"><span leaf="">{_esc(rec_desc)}</span></p>""" if rec_desc else ""
        rec_items_html.append(f"""    <section style="margin-bottom: {margin_b}; padding: 10px 0 12px;{border_style}">
      <p style="margin: 0 0 4px; font-size: 14.5px; color: #1e293b; line-height: 1.6;">{title_node}</p>{desc_node}
    </section>""")

    num_words_map = {1: "这篇", 2: "两篇", 3: "三篇", 4: "四篇", 5: "五篇", 6: "六篇"}
    count_text = num_words_map.get(total_recs, f"{total_recs}篇") if total_recs > 0 else "这些"
    rec_intro_text = f"如果你喜欢这种“撕开体面、算透现实账本”的深度拆解，下面{count_text}也值得继续看："

    out.append(f"""  <section style="margin: 30px 0 18px; padding: 16px 0 4px; border-top: 1px solid #e2e8f0; border-bottom: 1px solid #e2e8f0;">
    <section style="display: flex; align-items: center; gap: 8px; margin-bottom: 10px;">
      <span style="font-size: 17px;"><span leaf="">🔥</span></span>
      <h3 style="margin: 0; font-size: 16px; font-weight: 800; color: #0f172a;"><span leaf="">往期推荐</span></h3>
    </section>
    <p style="font-size: 13px; color: #64748b; margin: 0 0 12px; line-height: 1.6; text-align: left;"><span leaf="">{rec_intro_text}</span></p>
{chr(10).join(rec_items_html)}
  </section>""")

    out.append("</section>")
    body_html = "\n".join(out) + "\n"

    preview_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(clean_title)} · 公众号排版预览</title>
<style>
  body{{margin:0;background:#eef0f2;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif;-webkit-text-size-adjust:100%;}}
  .gzh-toolbar{{position:fixed;top:0;left:0;right:0;height:54px;background:#ffffff;box-shadow:0 1px 10px rgba(0,0,0,.08);display:flex;align-items:center;justify-content:space-between;padding:0 16px;z-index:99;}}
  .gzh-hint{{font-size:13px;color:#6b7280;line-height:1.4;}}
  .gzh-hint b{{color:#111827;}}
  .gzh-actions{{display:flex;align-items:center;gap:8px;}}
  .gzh-copy-title{{background:#f0fdf4;color:#065f46;border:1px solid #a7f3d0;border-radius:9px;padding:9px 14px;font-size:13px;font-weight:700;cursor:pointer;white-space:nowrap;transition:background .15s;}}
  .gzh-copy-title:hover{{background:#dcfce7;}}
  .gzh-copy{{background:#059669;color:#fff;border:0;border-radius:9px;padding:9px 18px;font-size:13px;font-weight:700;cursor:pointer;box-shadow:0 3px 10px rgba(5,150,105,.28);white-space:nowrap;transition:transform .08s,background .15s;}}
  .gzh-copy:hover{{background:#047857;}}
  .gzh-copy:active{{transform:translateY(1px);}}
  .gzh-toast{{position:fixed;top:66px;left:50%;transform:translateX(-50%);background:#111827;color:#fff;padding:11px 20px;border-radius:10px;font-size:14px;font-weight:600;opacity:0;pointer-events:none;transition:opacity .25s;z-index:100;box-shadow:0 6px 20px rgba(0,0,0,.25);max-width:88vw;text-align:center;}}
  .gzh-toast.show{{opacity:1;}}
  .gzh-stage{{max-width:700px;margin:74px auto 64px;padding:0 8px;}}
  .gzh-title-card{{background:#ffffff;border:1.5px solid #d1fae5;border-radius:14px;padding:20px 22px;margin-bottom:20px;box-shadow:0 4px 16px rgba(5,150,105,0.06);}}
  .gzh-title-badge{{display:inline-block;font-size:11px;font-weight:800;color:#059669;letter-spacing:1px;background:#ecfdf5;padding:3px 10px;border-radius:16px;border:1px solid #a7f3d0;margin-bottom:10px;}}
  .gzh-title-text{{margin:0 0 10px;font-size:20px;font-weight:900;color:#111827;line-height:1.45;letter-spacing:-0.5px;}}
  .gzh-title-sub{{display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:12.5px;color:#6b7280;line-height:1.6;}}
  @media(max-width:520px){{.gzh-hint{{display:none;}}.gzh-title-text{{font-size:17px;}}}}
</style>
</head>
<body>
<div class="gzh-toolbar">
  <span class="gzh-hint">预览效果 · <b>石墨冷灰大刊风（暗黑模式自适应）</b></span>
  <div class="gzh-actions">
    <button class="gzh-copy-title" id="gzhCopyTitleBtn" onclick="gzhCopyTitle()">📋 复制标题</button>
    <button class="gzh-copy" id="gzhCopyBtn" onclick="gzhCopy()">📋 复制正文</button>
  </div>
</div>
<div class="gzh-toast" id="gzhToast"></div>
<div class="gzh-stage">
  <!-- 定稿标题展示卡（位于复制正文区外部：保证用户在预览界面一眼可见定稿标题，同时复制正文时完全不会误带标题） -->
  <div class="gzh-title-card">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
      <span class="gzh-title-badge">📌 文章定稿标题</span>
      <span style="font-size:12px;color:#9ca3af;font-weight:600;">若雨随影 · {_esc(year_month)}</span>
    </div>
    <h1 class="gzh-title-text" id="gzhDisplayTitle">{_esc(clean_title)}</h1>
    <div class="gzh-title-sub">
      <span style="color:#334155;font-weight:700;background:#f1f5f9;padding:2px 8px;border-radius:6px;border:1px solid #cbd5e1;">{_esc(category_tag)}</span>
      <span style="color:#4b5563;background:#f3f4f6;padding:2px 8px;border-radius:6px;">{_esc(work_badge)}</span>
      <span>•</span>
      <span>看点提要：<strong style="color:#374151;">{_esc(subtitle_str)}</strong></span>
    </div>
  </div>

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
  function gzhCopyTitle(){{
    var t = document.getElementById('gzhDisplayTitle').innerText.trim();
    if (navigator.clipboard) {{
      navigator.clipboard.writeText(t).then(function(){{
        gzhShowToast('✅ 标题已复制到剪贴板！');
      }}).catch(function(){{
        gzhShowToast('⚠ 请手动选中标题文字复制');
      }});
    }} else {{
      gzhShowToast('⚠ 请手动选中标题文字复制');
    }}
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
            elif r_title:
                delivery_md_lines.append(f"* 📌 {r_title}")
            else:
                delivery_md_lines.append("* 📌 ")
            if r_desc:
                delivery_md_lines.append(f"  {r_desc}")
            delivery_md_lines.append("")

    if cold_start_kit:
        c_pinned = str(cold_start_kit.get("pinned_comment") or "").strip()
        c_copy1 = str(cold_start_kit.get("copy_1") or "").strip()
        c_copy2 = str(cold_start_kit.get("copy_2") or "").strip()
        c_slot = str(cold_start_kit.get("golden_slot") or "晚间下班通勤档（18:30 ~ 19:30）").strip()
        c_slot_reason = str(cold_start_kit.get("slot_reason") or "契合读者下班通勤与晚间休闲的高峰窗口。").strip()
        delivery_md_lines.extend([
            "",
            "---",
            "",
            "### 🚀 发布冷启动物料包（Cold Start Kit）",
            "",
            "#### 1. 【置顶引战首评】（50字内 · 带刺追问 · 禁客套）",
            f"> {c_pinned}",
            "",
            "#### 2. 【朋友圈 / 社群破冰转发语 × 2条】（第一人称分享）",
            f"- **文案 1（后背发凉 · 警醒避坑）**：{c_copy1}",
            f"- **文案 2（拍案叫绝 · 扎心共鸣）**：{c_copy2}",
            "",
            "#### 3. 【黄金推送时间建议】",
            f"- **推荐档位**：{c_slot}",
            f"- **排期策略**：{c_slot_reason}",
            "",
            "*详细冷启动引战与分发策略见同目录下 cold-start-kit.md。*",
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
    recommendations: Sequence[Mapping[str, str]] | None = None,
    page_slug: str = "article",
    author: str = "controller",
    include_cover_card: bool = False,
    include_top_follow: bool = False,
    embed_images: bool = False,
    killer_stance: str = "",
    projection_card: Mapping[str, Any] | None = None,
    title_pack: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """从 run_root/draft.md 渲染摸鱼绿三件套并落盘至 run_root/wechat/，绑定 source_draft_sha256。"""
    root = Path(run_root).resolve()
    draft_path = root / "draft.md"
    raw_bytes = draft_path.read_bytes()
    draft_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    md_text = raw_bytes.decode("utf-8")

    brief_data: dict[str, Any] = {}
    brief_file = root / "article-brief.json"
    if brief_file.is_file():
        try:
            brief_data = json.loads(brief_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    tp_data: dict[str, Any] = {}
    tp_file = root / "title-pack.json"
    if tp_file.is_file():
        try:
            tp_data = json.loads(tp_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    effective_proj = projection_card if projection_card is not None else brief_data.get("projection_card")
    effective_tp = title_pack if title_pack is not None else tp_data
    effective_stance = killer_stance or str(brief_data.get("killer_stance") or "")
    w_name = str(effective_tp.get("work") or brief_data.get("work") or work_badge.replace("《", "").replace("》", "").replace("深度拆解", "").strip())

    cold_start = build_cold_start_kit(
        title=title,
        work_name=w_name,
        killer_stance=effective_stance,
        projection_card=effective_proj,
        title_pack=effective_tp,
        category_tag=category_tag,
    )

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
        cold_start_kit=cold_start,
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
    write_evidence(wechat_dir / "cold-start-kit.md", cold_start["markdown"], run_dir=root, reason="moyu_green:cold_start_kit", author=author)

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
        "cold_start_kit": {
            "path": "wechat/cold-start-kit.md",
            "pinned_comment": cold_start["pinned_comment"],
            "distribution_copy_1": cold_start["copy_1"],
            "distribution_copy_2": cold_start["copy_2"],
        },
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
    自动提取分类标签、互动问题与 5 篇往期推荐（默认 5 个空白 📌 占位条目），一键生成摸鱼绿三件套（纯净首屏 Mode B 无封面大卡）。
    """
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
    # 标题判定优先级：正文 H1 权威优先（draft.md 是主笔与用户定稿的唯一事实真源）
    # 避免历史遗留或中间测试态的 wechat-config.json / title-pack.json 幽灵覆盖正文标题
    title = str(
        (m_h1.group(1).strip() if m_h1 else "")
        or wx_cfg.get("title")
        or tp.get("selected_title")
        or brief.get("selected_title")
        or root.name
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
        # 2026-10-17 用户定稿：往期推荐内容默认留空（5 个空白 📌 占位条目），供公众号后台人工选填
        recommendations = [{"title": "", "desc": ""}] * RECOMMENDATION_FIXED_COUNT

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
        killer_stance=str(brief.get("killer_stance") or ""),
        projection_card=brief.get("projection_card"),
        title_pack=tp,
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
