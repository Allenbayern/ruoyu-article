#!/usr/bin/env python3
"""跨批次聚类与实体提取模块 (cluster.py)
落实【补丁1】：
1. 优先查过去 72 小时活跃的 active_events (event_id, canonical_title, core_entities)；
2. 注入 LLM Prompt：相同现实事件严禁造新 ID，必须复用已有 event_id；
3. 本地增加 core_entities 交集兜底对齐逻辑；
4. 仅确认为全新事件时才生成新的 event_id (sha256(canonical_title)[:16])。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

# 引入项目共享 llm_client
SCRIPTS_DIR = Path("/home/allen/Projects/ruoyu-film-daily/scripts")
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import llm_client


def generate_new_event_id(canonical_title: str) -> str:
    """生成唯一事件 ID"""
    clean_title = re.sub(r"[^\w\u4e00-\u9fa5]", "", canonical_title.lower())
    h = hashlib.sha256(clean_title.encode("utf-8")).hexdigest()[:16]
    return f"ev_{h}"


def cluster_chunk_with_llm(
    candidates_chunk: list[dict[str, Any]],
    active_events: list[dict[str, Any]],
    env: dict[str, str],
) -> list[dict[str, Any]]:
    candidate_prompts = []
    for idx, c in enumerate(candidates_chunk):
        candidate_prompts.append({
            "idx": idx,
            "platform": c["platform"],
            "platform_tier": c["platform_tier"],
            "rank": c["rank_position"],
            "title": c["title"],
            "desc": c.get("desc", "")[:50],
        })

    existing_events_ctx = []
    for ev in active_events:
        existing_events_ctx.append({
            "event_id": ev["event_id"],
            "canonical_title": ev["canonical_title"],
            "core_entities": ev["core_entities"],
        })

    system_prompt = """你是一个全网舆情与爆款新闻聚合助手。
【硬性输出纪律】：直接输出标准 JSON 数组，严禁输出任何思考过程、推理推导或额外文字！

你的任务是将多平台的零散热搜条目，聚类归纳为具体的「独立现实新闻事件（Real-World Events）」。

【关键对齐纪律 - 补丁 1】
系统中已经存在「过去 72 小时活跃事件列表（active_events）」。
如果当前热搜报道的现实事件已经存在于 active_events 中（比如同一人物、同一案件、同一风波、后续进展）：
必须【100% 复用原有的 event_id】，绝对不许生成新的 event_id！
只有当确认该热搜属于从未出现过的全新事件时，才将 existing_event_id 设为 null。

输出格式要求（纯 JSON 数组）：
[
  {
    "canonical_title": "标准事件全称（客观准确，15字以内）",
    "existing_event_id": "若匹配到 active_events 则填入其 event_id，否则填 null",
    "core_entities": ["核心主体1", "核心主体2"],
    "item_indices": [0, 2]
  }
]
"""

    user_prompt = f"""【过去 72 小时已有活跃事件 (active_events)】:
{json.dumps(existing_events_ctx[:20], ensure_ascii=False, indent=2)}

【精选待聚类热搜候选列表 (共 {len(candidate_prompts)} 条)】:
{json.dumps(candidate_prompts, ensure_ascii=False, indent=2)}
"""

    for retry in range(2):
        try:
            content = llm_client.chat(env, system_prompt, user_prompt, max_tokens=6000)
            clusters = llm_client.parse_json_array(content)
            if clusters:
                return clusters
        except Exception as exc:
            print(f"[cluster] LLM 聚类重试 {retry+1}/2 异常: {exc}", file=sys.stderr)
            import time
            time.sleep(1)

    return []


def cluster_hotspots_with_llm(
    candidates: list[dict[str, Any]],
    active_events: list[dict[str, Any]],
    env: dict[str, str],
    chunk_size: int = 25,
) -> list[dict[str, Any]]:
    """分批调用 LLM 进行事件聚类（每批 25 条，稳定防截断），并严格对齐 72 小时内的 active_events"""
    grouped_events = []
    
    # 按 chunk_size 分块处理
    for i in range(0, len(candidates), chunk_size):
        chunk = candidates[i : i + chunk_size]
        clusters = cluster_chunk_with_llm(chunk, active_events, env)
        
        used_local_indices = set()
        if clusters:
            for cl in clusters:
                canonical_title = cl.get("canonical_title", "").strip()
                if not canonical_title:
                    continue
                core_entities = cl.get("core_entities", [])
                existing_event_id = cl.get("existing_event_id")
                local_indices = [idx for idx in cl.get("item_indices", []) if 0 <= idx < len(chunk)]
                if not local_indices:
                    continue
                
                # 补丁 1 的 Python 实体兜底对齐
                matched_id = existing_event_id
                if not matched_id:
                    for active in active_events:
                        overlap = set(core_entities) & set(active.get("core_entities", []))
                        if len(overlap) >= 2 or (len(overlap) == 1 and overlap.intersection({"博纳影业", "张艺谋", "王家卫", "周星驰", "贾玲"})):
                            matched_id = active["event_id"]
                            break

                event_id = matched_id if matched_id else generate_new_event_id(canonical_title)
                matched_items = [chunk[idx] for idx in local_indices]
                for idx in local_indices:
                    used_local_indices.add(idx)

                grouped_events.append({
                    "event_id": event_id,
                    "canonical_title": canonical_title,
                    "core_entities": core_entities,
                    "items": matched_items,
                    "is_new": (matched_id is None),
                })

        # 本批中未被聚类的孤立项兜底
        for idx, cand in enumerate(chunk):
            if idx not in used_local_indices:
                title = cand["title"]
                matched_id = None
                for active in active_events:
                    if any(ent in title for ent in active.get("core_entities", []) if len(ent) >= 2):
                        matched_id = active["event_id"]
                        break
                ev_id = matched_id if matched_id else generate_new_event_id(title)
                grouped_events.append({
                    "event_id": ev_id,
                    "canonical_title": title,
                    "core_entities": [cand.get("platform_name", ""), title[:6]],
                    "items": [cand],
                    "is_new": (matched_id is None),
                })

    return grouped_events


def fallback_local_cluster(candidates: list[dict[str, Any]], active_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """LLM 不可用时的本地启发式轻量聚类"""
    grouped_events = []
    for cand in candidates:
        title = cand["title"]
        matched_id = None
        # 简单比对历史实体
        for active in active_events:
            if any(ent in title for ent in active.get("core_entities", []) if len(ent) >= 2):
                matched_id = active["event_id"]
                break
        ev_id = matched_id if matched_id else generate_new_event_id(title)
        grouped_events.append({
            "event_id": ev_id,
            "canonical_title": title,
            "core_entities": [title[:4]],
            "items": [cand],
            "is_new": (matched_id is None),
        })
    return grouped_events
