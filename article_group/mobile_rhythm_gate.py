"""mobile_rhythm_gate: 手机端深度长文排版与节奏校验器

针对微信手机端（一行约 22~24 汉字）与 3500 字深度影视/人物长文的叙事沉浸感量化硬指标：
1. 【章节与视觉灯塔双层结构】：
   - 主章节小标题（H2 胶囊标题）：全文严格控制在 3 ~ 4 个（每 800 ~ 1000 字一个），防 PPT 碎片化陷阱。
   - 300 字视觉呼吸锚点：每个主章节内部，每 300 ~ 350 字必须出现独立成行的加粗金句或引用高亮短句（连续超 450 字无锚点即报警）。
2. 【手机屏 5 行换算律】：
   - 单自然段字数严格控制在 ≤ 115 字（超过 115 字必须按语义切段）。
   - 严禁连续 3 段都是长段（> 70 字），必须遵循“叙事段（70~110字）+ 扎心点评短段（15~35字）”的长短交错律动。
3. 【≥ 3 处可截图带走点】：
   - 全文必须埋设至少 3 处结合了具体数字/账本的透彻论断（高亮/引用/加粗金句含数字或账本关键词）。
"""
from __future__ import annotations

import re
from typing import Any

# 账本与数字关键词，用于识别“可截图带走”的透彻现实论断
LEDGER_KEYWORDS = (
    "万", "亿", "元", "美元", "日元", "年", "月", "天", "折", "房贷", "月供",
    "账本", "算盘", "筹码", "代价", "违约金", "合同", "清算", "利息", "现金流",
    "底牌", "开销", "分红", "赔偿", "存折", "身价", "片酬", "票房", "税", "本金"
)

# 允许的 H2 胶囊小标题范围（深度叙事长文 3~4 幕）
H2_MIN_COUNT = 3
H2_MAX_COUNT = 4

# 单段字数手机端 5 行上限（一行 23 字 * 5 = 115）
MAX_PARA_CHARS = 115

# 长段与短段判定界限
LONG_PARA_THRESHOLD = 70
SHORT_PUNCHY_MIN = 15
SHORT_PUNCHY_MAX = 35

# 视觉呼吸锚点最大允许间距（字数）
MAX_ANCHOR_GAP_CHARS = 450


def clean_cjk_count(text: str) -> int:
    """计算纯文字/汉字长度（去除空格与 Markdown 格式标记）。"""
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    t = re.sub(r"[*_~`>#|]", "", t)
    t = re.sub(r"\s+", "", t)
    return len(t)


def is_visual_anchor_line(line: str) -> bool:
    """判定单行是否为视觉抓手/呼吸锚点（加粗金句、引用框、表格、插图图注）。"""
    s = line.strip()
    if not s:
        return False
    # 引用块
    if s.startswith(">"):
        return True
    # 独立成行的加粗金句（例如 **...** 占据整行或核心主体）
    if re.match(r"^(\*\*|__)[^*_]{6,}(\*\*|__)$", s):
        return True
    # 含有显著加粗长短语的过渡行
    if "**" in s and len(re.findall(r"\*\*([^*]{8,})\*\*", s)) > 0:
        return True
    # 插图图注锚点
    if s.startswith("▲") or s.startswith("*▲"):
        return True
    # 分隔线
    if s in ("---", "***", "___"):
        return True
    return False


def is_screenshot_worthy(anchor_text: str) -> bool:
    """判定是否具备'截图带走'属性：包含加粗/引用 + 数字或现实账本关键词。"""
    has_digit = bool(re.search(r"\d+", anchor_text))
    has_ledger = any(kw in anchor_text for kw in LEDGER_KEYWORDS)
    return has_digit or has_ledger


def check_mobile_rhythm(
    raw_text: str,
    *,
    max_para_chars: int = MAX_PARA_CHARS,
    strict_h2: bool = True,
    strict_anchor_gap: bool = False,
) -> dict[str, Any]:
    """对长文执行手机端排版与叙事呼吸节奏综合校验。"""
    errors: list[str] = []
    warnings: list[str] = []
    advice: list[str] = []

    lines = raw_text.splitlines()

    # 1. 章节切分与 H2 胶囊标题检验
    sections: list[dict[str, Any]] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in lines:
        m = re.match(r"^##\s+(.+)$", line)
        if m:
            if current_heading is not None or current_lines:
                sections.append({
                    "heading": current_heading or "引子/开篇",
                    "lines": current_lines,
                })
            current_heading = m.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_heading is not None or current_lines:
        sections.append({
            "heading": current_heading or "引子/开篇",
            "lines": current_lines,
        })

    # H2 数量统计（排除引子）
    h2_sections = [s for s in sections if s["heading"] != "引子/开篇"]
    h2_count = len(h2_sections)

    if h2_count < H2_MIN_COUNT:
        msg = f"H2 胶囊小标题过少 (当前 {h2_count} 个 < 最小 {H2_MIN_COUNT} 个)，长文缺乏宏观叙事幕次"
        if strict_h2:
            errors.append(f"h2_count_too_few_{h2_count}")
        else:
            warnings.append(f"h2_count_too_few_{h2_count}")
        advice.append(msg)
    elif h2_count > H2_MAX_COUNT:
        msg = f"H2 胶囊小标题过多 (当前 {h2_count} 个 > 最大 {H2_MAX_COUNT} 个)，触发'300字一小标题'的PPT碎片化陷阱，打碎故事沉浸感"
        errors.append(f"h2_count_too_many_ppt_trap_{h2_count}")
        advice.append(msg)

    # 2. 章节内部呼吸锚点检验（每 300~350 字视觉抓手）
    anchor_gaps: list[dict[str, Any]] = []
    screenshot_anchors: list[str] = []

    for s_idx, sec in enumerate(sections):
        sec_name = sec["heading"]
        char_accumulator = 0
        gap_start_p = 1
        para_idx = 0

        for line in sec["lines"]:
            s_line = line.strip()
            if not s_line or s_line.startswith(("#", "```")):
                continue

            # 检查是否是截图锚点
            if is_visual_anchor_line(s_line):
                # 检查是否含账本/数字
                clean_anchor = re.sub(r"[*_>`#]", "", s_line).strip()
                if is_screenshot_worthy(clean_anchor) and len(clean_anchor) >= 8:
                    screenshot_anchors.append(clean_anchor)

                # 重置间距累加器
                char_accumulator = 0
                gap_start_p = para_idx + 1
            else:
                para_idx += 1
                c_len = clean_cjk_count(s_line)
                char_accumulator += c_len

                if char_accumulator > MAX_ANCHOR_GAP_CHARS:
                    anchor_gaps.append({
                        "section": sec_name,
                        "span_chars": char_accumulator,
                        "start_para": gap_start_p,
                        "end_para": para_idx,
                    })
                    # 避免反复同区域重复报警，记录后适度步进
                    char_accumulator = 0
                    gap_start_p = para_idx + 1

    if anchor_gaps:
        advice.append(
            f"检测到 {len(anchor_gaps)} 处超过 {MAX_ANCHOR_GAP_CHARS} 字无加粗金句或视觉锚点的密集区域，"
            "建议在每 300~350 字处插入独立成行的加粗金句充当滑屏抓手"
        )
        for g in anchor_gaps:
            tag = f"anchor_gap_exceeded_{g['section']}_{g['span_chars']}chars"
            warnings.append(tag)
            if strict_anchor_gap:
                errors.append(tag)

    # 3. 手机屏 5 行换算律 (≤ 115 字) 与连续长段检验
    all_paragraphs: list[dict[str, Any]] = []
    overlength_paragraphs: list[dict[str, Any]] = []

    # 提取所有正文自然段
    p_global_idx = 0
    for line in lines:
        s_line = line.strip()
        if not s_line or s_line.startswith(("#", "```", "|", ">", "-")):
            continue
        # 排除纯图注行
        if s_line.startswith("▲") or s_line.startswith("*▲"):
            continue

        p_global_idx += 1
        c_len = clean_cjk_count(s_line)
        p_info = {
            "index": p_global_idx,
            "length": c_len,
            "is_long": c_len > LONG_PARA_THRESHOLD,
            "is_punchy": SHORT_PUNCHY_MIN <= c_len <= SHORT_PUNCHY_MAX,
            "snippet": s_line[:35] + ("..." if len(s_line) > 35 else ""),
        }
        all_paragraphs.append(p_info)

        if c_len > max_para_chars:
            overlength_paragraphs.append(p_info)

    if overlength_paragraphs:
        errors.append(f"overlength_paragraphs_count_{len(overlength_paragraphs)}")
        advice.append(
            f"检测到 {len(overlength_paragraphs)} 个超长段落（超过手机屏 5 行/ {max_para_chars} 字硬线），"
            "手机端满屏无换行会极大消耗阅读耐心，必须按语义拆段"
        )

    # 4. 连续长段检验（严禁连续 3 段 > 70 字）
    consecutive_long_spans: list[list[int]] = []
    current_run: list[int] = []

    for p in all_paragraphs:
        if p["is_long"]:
            current_run.append(p["index"])
        else:
            if len(current_run) >= 3:
                consecutive_long_spans.append(list(current_run))
            current_run = []
    if len(current_run) >= 3:
        consecutive_long_spans.append(list(current_run))

    if consecutive_long_spans:
        for span in consecutive_long_spans:
            errors.append(f"consecutive_long_paras_{span[0]}_to_{span[-1]}")
        advice.append(
            f"检测到 {len(consecutive_long_spans)} 处连续 ≥3 段大长段（>70字），"
            "破坏了呼吸感！必须遵循'叙事长段（70~110字）+ 扎心点评短段（15~35字）'交错结构"
        )

    # 5. ≥ 3 处可截图带走点
    unique_screenshot_anchors = list(dict.fromkeys(screenshot_anchors))
    if len(unique_screenshot_anchors) < 3:
        warnings.append(f"insufficient_screenshot_anchors_{len(unique_screenshot_anchors)}_min_3")
        advice.append(
            f"全文仅识别出 {len(unique_screenshot_anchors)} 处结合了数字/账本的透彻论断（建议 ≥ 3 处），"
            "难以激发读者'截图发朋友圈'的自发传播冲动"
        )

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "h2_count": h2_count,
            "paragraphs_total": len(all_paragraphs),
            "overlength_count": len(overlength_paragraphs),
            "consecutive_long_spans_count": len(consecutive_long_spans),
            "anchor_gaps_count": len(anchor_gaps),
            "screenshot_anchors_count": len(unique_screenshot_anchors),
            "overlength_paragraphs": overlength_paragraphs,
            "consecutive_long_spans": consecutive_long_spans,
            "anchor_gaps": anchor_gaps,
            "screenshot_anchors": unique_screenshot_anchors,
        },
        "advice": advice,
    }
