#!/usr/bin/env python3
"""生命周期计算模块 (lifecycle.py)
根据现实时间轴、跨平台跃升度、以及人物/实体特征，自动推导生命周期阶段：
- burst: 首次爆发期（<=6小时，>=2个平台，S级前15）
- fermenting: 发酵蓄势期（12~36小时，跨多平台持续有讨论）
- evergreen_hook: 常青人物/名利场母题钩子（老戏骨、老富豪、资本沉浮、阶层跌落）
- fading: 衰退期（>48小时，排名跌出前30）
- cold: 单平台偶发或热度不足
"""
from __future__ import annotations

import re
import time
from typing import Any

# 常青母题识别关键词：老戏骨、老牌明星、资本巨鳄、豪门破产
RE_EVERGREEN_FIGURES = re.compile(
    r"(游本昌|张艺谋|王家卫|周星驰|成龙|李连杰|陈凯歌|田华|李雪健|老戏骨|老艺术家|"
    r"博纳|万达|华谊|王健林|许家印|对赌|破产清算|退市|巨亏|豪门|晚年|重病|名利场)"
)

# 媒体评论/二轮发酵特征词（冷启动防爆发失真保护）
RE_SECOND_STAGE_COMMENTARY = re.compile(
    r"(漫评|社论|评论|评论员|复盘|如何看待|为什么说|全过程|热议|专访|起底|深扒|透视|反思|后续|调查报告)"
)


def compute_lifecycle_stage(
    event: dict[str, Any],
    items: list[dict[str, Any]],
    first_seen_at: int,
    now: int | None = None,
) -> str:
    if now is None:
        now = int(time.time())

    duration_hours = max(0.1, (now - first_seen_at) / 3600.0)
    
    platforms = set(it["platform"] for it in items)
    cross_count = len(platforms)
    
    # 查找是否有 S 级平台进入 Top 15
    has_s_top15 = any(it["platform_tier"] == "S" and it["rank_position"] <= 15 for it in items)
    # 查找是否有 A 级平台进入 Top 5
    has_a_top5 = any(it["platform_tier"] == "A" and it["rank_position"] <= 5 for it in items)

    title_and_entities = event["canonical_title"] + " " + " ".join(event.get("core_entities", []))
    is_evergreen_match = bool(RE_EVERGREEN_FIGURES.search(title_and_entities))

    # 1. 优先判定常青母题钩子 (若人物或事件天然契合常青母题，且有讨论度)
    if is_evergreen_match:
        return "evergreen_hook"

    # 检查是否命中二轮发酵/媒体评论特征（冷启动保护：防把媒体深度反思误判为现场首发）
    all_titles_text = event["canonical_title"] + " " + " ".join(it.get("raw_title", "") for it in items)
    is_commentary_or_followup = bool(RE_SECOND_STAGE_COMMENTARY.search(all_titles_text))

    # 2. 判定发酵蓄势期 (fermenting)
    # 包含：存续 8 ~ 48 小时跨平台扩散；或者虽然时间短但已经进入媒体评论/二次反思阶段
    if is_commentary_or_followup:
        return "fermenting"
    if 8 < duration_hours <= 48 and cross_count >= 2:
        return "fermenting"

    # 3. 判定爆发首发期 (burst)
    # 6~8 小时内纯第一现场突发事件，且至少上了 2 个平台或登上 S 级 Top 15，且未进入二轮评论
    if duration_hours <= 8 and (cross_count >= 2 or has_s_top15 or has_a_top5):
        return "burst"

    # 4. 判定衰退期 (fading)
    if duration_hours > 48:
        return "fading"

    return "cold"
