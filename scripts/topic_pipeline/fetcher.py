#!/usr/bin/env python3
"""数据源采集模块：从 dailyhot-api (127.0.0.1:6688) 并发或低频采集 15 个核心源。
支持单源失败容错、统一归一化与平台分级。
"""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

API_BASE = "http://127.0.0.1:6688"

# 15 个核心源配置与分级
TARGET_ROUTES = [
    # S 级：国民情绪与深度讨论
    {"route": "zhihu", "tier": "S", "name": "知乎热榜", "weight": 1.8},
    {"route": "toutiao", "tier": "S", "name": "今日头条", "weight": 1.8},
    {"route": "baidu", "tier": "S", "name": "百度热搜", "weight": 1.5},
    {"route": "weibo", "tier": "S", "name": "微博热搜", "weight": 1.5},
    {"route": "qq-news", "tier": "S", "name": "腾讯新闻", "weight": 1.5},
    {"route": "thepaper", "tier": "S", "name": "澎湃新闻", "weight": 1.6},
    # A 级：草根世相与文艺母题
    {"route": "douyin", "tier": "A", "name": "抖音热点", "weight": 1.0},
    {"route": "kuaishou", "tier": "A", "name": "快手热榜", "weight": 1.0},
    {"route": "douban-group", "tier": "A", "name": "豆瓣讨论精选", "weight": 1.0},
    {"route": "douban-movie", "tier": "A", "name": "豆瓣电影热榜", "weight": 1.0},
    {"route": "hupu", "tier": "A", "name": "虎扑步行街", "weight": 1.0},
    {"route": "tieba", "tier": "A", "name": "贴吧热议", "weight": 1.0},
    # B 级：财经与名利场沉浮
    {"route": "36kr", "tier": "B", "name": "36氪", "weight": 0.8},
    {"route": "sina-news", "tier": "B", "name": "新浪新闻", "weight": 0.8},
    {"route": "huxiu", "tier": "B", "name": "虎嗅", "weight": 0.8},
]


def fetch_route(route: str, timeout: int = 10) -> tuple[str | None, list[dict[str, Any]]]:
    url = f"{API_BASE}/{route}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 RuoyuTopicPipeline/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                return None, data["data"]
            return f"unexpected_shape: {type(data)}", []
    except Exception as exc:  # 容忍单路由报错
        return f"{type(exc).__name__}: {exc}", []


def fetch_all_core_routes(batch_time: int | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """采集全部 15 个源，返回 (原始条目列表, 状态摘要)"""
    if batch_time is None:
        batch_time = int(time.time())
    
    all_raw_items: list[dict[str, Any]] = []
    status_summary: dict[str, Any] = {
        "batch_time": batch_time,
        "total_sources": len(TARGET_ROUTES),
        "success_count": 0,
        "failed_count": 0,
        "sources_stat": {},
    }

    for cfg in TARGET_ROUTES:
        route = cfg["route"]
        tier = cfg["tier"]
        name = cfg["name"]
        err, items = fetch_route(route)
        if err:
            status_summary["failed_count"] += 1
            status_summary["sources_stat"][route] = {"status": "FAIL", "error": err, "count": 0}
            continue

        status_summary["success_count"] += 1
        status_summary["sources_stat"][route] = {"status": "OK", "count": len(items)}
        
        for rank, item in enumerate(items, start=1):
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            url = item.get("url") or item.get("mobileUrl") or ""
            desc = str(item.get("desc", "")).strip()
            hot = str(item.get("hot", "")).strip()
            
            all_raw_items.append({
                "platform": route,
                "platform_tier": tier,
                "platform_name": name,
                "weight": cfg["weight"],
                "rank_position": rank,
                "title": title,
                "desc": desc,
                "url": url,
                "raw_hot_label": hot,
                "batch_time": batch_time,
            })
            
    return all_raw_items, status_summary


if __name__ == "__main__":
    items, summary = fetch_all_core_routes()
    print(f"采集完成！成功源: {summary['success_count']}/{summary['total_sources']}，累计抓取: {len(items)} 条")
    for r, st in summary["sources_stat"].items():
        print(f"  - {r:14s}: {st['status']} ({st.get('count', 0)} 条)")
