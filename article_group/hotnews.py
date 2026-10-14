"""hotnews: Real-time multi-platform trending topics fetcher.

Ported from HelpWriting (hotnews.py) and hardened for Hermes/Article Group.
Fetches live hot topics across Weibo, Douyin, Bilibili, Zhihu, Toutiao, Baidu, etc.
Pure Python standard library implementation (urllib.request + json), zero external dependencies.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from typing import Any, Final
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_TIMEOUT: Final = 10.0
_USER_AGENT: Final = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

PLATFORMS = [
    {"name": "微博", "code": "weibo", "zhiwei_id": "weibo"},
    {"name": "抖音", "code": "douyin", "zhiwei_id": "douyin"},
    {"name": "哔哩哔哩", "code": "bilibili", "zhiwei_id": "bilibili"},
    {"name": "知乎热榜", "code": "zhihu", "zhiwei_id": "zhihu"},
    {"name": "今日头条", "code": "toutiao", "zhiwei_id": "toutiao"},
    {"name": "百度热点", "code": "baidu", "zhiwei_id": "baidu"},
    {"name": "小红书", "code": "xiaohongshu", "zhiwei_id": "little-red-book"},
    {"name": "快手", "code": "kuaishou", "zhiwei_id": "kuaishou"},
]

ZHIWEI_PLATFORMS = {p["zhiwei_id"] for p in PLATFORMS if p["zhiwei_id"]}


def _normalize_platform(name_or_code: str) -> dict[str, Any] | None:
    target = name_or_code.strip().lower()
    for p in PLATFORMS:
        if p["code"] == target or p["name"] == target or target in p["name"].lower():
            return p
    return None


def get_zhiwei_hotnews(platform_id: str, timeout: float = _TIMEOUT) -> list[dict[str, Any]] | None:
    """Fetch real-time trending list from Zhiwei Data API (pure urllib.request)."""
    api_url = (
        f"https://trends.zhiweidata.com/hotSearchTrend/search/longTimeInListSearch"
        f"?type={platform_id}&sortType=realTime"
    )
    headers = {
        "User-Agent": _USER_AGENT,
        "Referer": "https://trends.zhiweidata.com/",
    }
    req = Request(api_url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("state") and isinstance(data.get("data"), list):
            items = []
            for item in data["data"]:
                items.append(
                    {
                        "title": item.get("name", "").strip(),
                        "rank": int(item.get("rank", 0)),
                        "hot_value": str(item.get("lastCount", "0")),
                        "url": item.get("url", ""),
                        "source": "zhiwei",
                    }
                )
            return items
    except (HTTPError, URLError, json.JSONDecodeError, UnicodeDecodeError, TimeoutError) as e:
        logger.debug("Zhiwei API request failed for %s: %s", platform_id, e)
    return None


def get_vvhan_hotnews(platform_name: str, timeout: float = _TIMEOUT) -> list[dict[str, Any]] | None:
    """Fallback fetch from public aggregator (vvhan)."""
    api_url = "https://api.vvhan.com/api/hotlist/all"
    req = Request(api_url, headers={"User-Agent": _USER_AGENT})
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("success") and isinstance(data.get("data"), list):
            for block in data["data"]:
                if block.get("name") == platform_name and isinstance(block.get("data"), list):
                    items = []
                    for idx, row in enumerate(block["data"], start=1):
                        items.append(
                            {
                                "title": row.get("title", "").strip(),
                                "rank": idx,
                                "hot_value": str(row.get("hot", "0")),
                                "url": row.get("url", ""),
                                "source": "vvhan",
                            }
                        )
                    return items
    except Exception as e:
        logger.debug("Vvhan fallback failed for %s: %s", platform_name, e)
    return None


def get_platform_hotnews(
    platform: str,
    limit: int = 15,
) -> list[dict[str, Any]]:
    """Get structured hot news items for a given platform.

    Args:
        platform: Platform name ('微博') or code ('weibo').
        limit: Max items to return.
    """
    p_info = _normalize_platform(platform)
    if not p_info:
        logger.warning("Unknown platform: %s", platform)
        return []

    # 1. Primary: Zhiwei Data API
    if p_info["zhiwei_id"]:
        items = get_zhiwei_hotnews(p_info["zhiwei_id"])
        if items:
            return items[:limit]

    # 2. Fallback: vvhan API
    items = get_vvhan_hotnews(p_info["name"])
    if items:
        return items[:limit]

    return []


def get_all_platform_hotnews(limit_per_platform: int = 5) -> dict[str, list[dict[str, Any]]]:
    """Fetch top trending items across all supported platforms."""
    results: dict[str, list[dict[str, Any]]] = {}
    for p in PLATFORMS:
        items = get_platform_hotnews(p["code"], limit=limit_per_platform)
        if items:
            results[p["name"]] = items
    return results


def select_weighted_topic(platform: str, limit: int = 15) -> str:
    """Pick one trending topic weighted by rank position (rank 1 has highest weight)."""
    items = get_platform_hotnews(platform, limit=limit)
    if not items:
        return "院线新片与票房观察"

    titles = [x["title"] for x in items if x.get("title")]
    if not titles:
        return "院线新片与票房观察"

    weights = [1.0 / ((i + 1) ** 1.5) for i in range(len(titles))]
    chosen = random.choices(titles, weights=weights, k=1)[0]
    return chosen.replace("|", "——")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="全网多平台实时热点聚合探测器")
    parser.add_argument("-p", "--platform", default="weibo", help="平台名称或代码 (weibo/douyin/bilibili/zhihu/toutiao/baidu等)")
    parser.add_argument("-n", "--limit", type=int, default=10, help="返回条数 (默认 10)")
    parser.add_argument("-a", "--all", action="store_true", help="同时拉取所有平台热榜")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    parser.add_argument("--pick", action="store_true", help="按排名权重随机抽取一个话题")

    args = parser.parse_args(argv)

    if args.all:
        all_data = get_all_platform_hotnews(limit_per_platform=args.limit)
        if args.json:
            print(json.dumps(all_data, ensure_ascii=False, indent=2))
        else:
            print("=" * 60)
            print("🔥 全网多平台实时热点概览")
            print("=" * 60)
            for plat, items in all_data.items():
                print(f"\n【{plat}】")
                for it in items:
                    print(f"  {it['rank']:>2d}. {it['title']} ({it['hot_value']})")
        return 0

    if args.pick:
        topic = select_weighted_topic(args.platform, limit=args.limit)
        print(topic)
        return 0

    items = get_platform_hotnews(args.platform, limit=args.limit)
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        p_info = _normalize_platform(args.platform)
        p_name = p_info["name"] if p_info else args.platform
        print(f"🔥 [{p_name}] 实时热搜榜 (Top {len(items)})")
        print("-" * 50)
        for it in items:
            print(f"{it['rank']:>2d}. {it['title']}  [热度: {it['hot_value']}]")
        print("-" * 50)

    return 0


if __name__ == "__main__":
    sys.exit(main())
