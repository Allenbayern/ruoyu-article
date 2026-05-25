#!/usr/bin/env python3
"""
DailyHotApi 热榜聚合抓取脚本 v1.0
===================================
为「热点猎手」提供每日自动化热榜数据抓取。
数据源：DailyHotApi (imsyy/DailyHotApi)
公共 API：https://dailyhot.api.lolimi.cn/ 或 https://api-hot.imsyy.top/

用法：
  python3 dailyhot-fetch.py                          # 全部源
  python3 dailyhot-fetch.py --source douban-movie     # 单个源
  python3 dailyhot-fetch.py --source weibo,bilibili   # 多个源
  python3 dailyhot-fetch.py --limit 20                # 每源取几条
  python3 dailyhot-fetch.py --dry-run                 # 只打印不保存
  python3 dailyhot-fetch.py --format hotspot-report   # 输出热点猎手标准格式
"""

import json
import os
import sys
import time
import argparse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

# ─── 配置 ───────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(SCRIPT_DIR)  # employees/
OUTPUT_DIR = os.path.join(WORKSPACE, "research-daily")
CONFIG_FILE = os.path.join(SCRIPT_DIR, "dailyhot-config.json")

# API 端点（按优先级自动切换）
API_ENDPOINTS = [
    "http://192.168.100.223:6688",       # 🏠 本地部署（首选，最快）
    "https://dailyhot.api.lolimi.cn",     # 备用公共镜像
]

# 默认抓取的数据源（与影视公众号最相关）
DEFAULT_SOURCES = {
    "douban-movie":  {"name": "豆瓣电影",  "category": "🎬 影视核心", "priority": 1},
    "weibo":         {"name": "微博热搜",  "category": "📱 泛娱乐",   "priority": 1},
    "weixin":        {"name": "微信热榜",  "category": "📝 内容生态", "priority": 2},
    "bilibili":      {"name": "B站热门",   "category": "📱 泛娱乐",   "priority": 2},
    "douyin":        {"name": "抖音热点",  "category": "📱 泛娱乐",   "priority": 2},
    "hupu":          {"name": "虎扑热帖",  "category": "💬 社区讨论", "priority": 3},
    "zhihu":         {"name": "知乎热榜",  "category": "📝 深度讨论", "priority": 3},
    "baidu":         {"name": "百度热搜",  "category": "📱 泛娱乐",   "priority": 3},
    "toutiao":       {"name": "今日头条",  "category": "📱 泛娱乐",   "priority": 3},
    "douban-group":  {"name": "豆瓣小组",  "category": "🎬 影视核心", "priority": 2},
}

# 影视关键词过滤 — 只保留与影视文娱相关的条目
FILM_KEYWORDS = [
    # 核心影视词
    "电影", "电视剧", "综艺", "纪录片", "动画", "动漫", "短剧",
    "导演", "演员", "演技", "剧本", "编剧", "制片",
    "票房", "院线", "上映", "定档", "撤档", "排片",
    "好莱坞", "国产片", "进口片", "文艺片", "商业片", "纪录片",
    # 平台/IP
    "Netflix", "网飞", "Disney", "迪士尼", "HBO", "爱奇艺", "腾讯视频", "优酷", "B站",
    "漫威", "DC", "哈利波特", "指环王", "星球大战",
    # 活动/奖项
    "奥斯卡", "戛纳", "柏林电影节", "威尼斯电影节", "金鸡", "金马", "金像",
    "颁奖", "红毯", "首映", "路演", "点映",
    # 人物相关
    "影帝", "影后", "最佳男主", "最佳女主", "新人奖",
    # 内容形式
    "影评", "解说", "吐槽", "安利", "推荐", "片单",
    "预告片", "花絮", "幕后", "彩蛋", "删减",
    # 现象/趋势
    "爆款", "黑马", "逆袭", "翻车", "塌房",
    "IP改编", "真实事件改编", "游戏改编",
]

# 反过滤：这些词出现时不排除（防止误伤）
ANTI_EXCLUDE = []


def load_config():
    """加载配置文件，不存在则用默认值"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def find_working_api(timeout=10):
    """自动检测可用的 API 端点"""
    for base_url in API_ENDPOINTS:
        try:
            req = urllib.request.Request(
                f"{base_url}/douban-movie?limit=1",
                headers={"User-Agent": "OpenClaw-DailyHotFetcher/1.0"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
                if "data" in data or "code" in data:
                    return base_url
        except Exception:
            continue
    return None


def fetch_source(base_url, source_name, limit=15):
    """抓取单个热榜源"""
    url = f"{base_url}/{source_name}?limit={limit}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "OpenClaw-DailyHotFetcher/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read().decode())
            return parse_response(source_name, raw)
    except urllib.error.HTTPError as e:
        return {"source": source_name, "error": f"HTTP {e.code}", "items": []}
    except urllib.error.URLError as e:
        return {"source": source_name, "error": str(e.reason), "items": []}
    except json.JSONDecodeError:
        return {"source": source_name, "error": "JSON parse failed", "items": []}
    except Exception as e:
        return {"source": source_name, "error": str(e), "items": []}


def parse_response(source_name, raw):
    """解析 DailyHotApi 响应，统一为内部格式"""
    items = []
    meta = {
        "source": source_name,
        "name": raw.get("name", source_name),
        "updateTime": raw.get("updateTime", ""),
        "total": 0,
    }

    # DailyHotApi 标准响应格式：{"code": 200, "data": [...]}
    data = raw.get("data", raw) if isinstance(raw, dict) else []
    if not isinstance(data, list):
        data = []

    for item in data:
        if not isinstance(item, dict):
            continue
        title = item.get("title", "") or item.get("name", "") or item.get("keyword", "")
        desc = item.get("desc", "") or item.get("description", "") or ""
        hot = item.get("hot", "") or item.get("heat", "") or item.get("index", "") or ""
        url = item.get("url", "") or item.get("mobilUrl", "") or ""

        items.append({
            "title": str(title).strip(),
            "desc": str(desc).strip(),
            "hot": str(hot).strip(),
            "url": str(url).strip(),
            "is_film_related": is_film_related(str(title) + " " + str(desc)),
        })

    meta["total"] = len(items)
    return {"meta": meta, "items": items}


def is_film_related(text):
    """判断文本是否与影视文娱相关"""
    text_lower = text.lower()
    for kw in FILM_KEYWORDS:
        if kw.lower() in text_lower:
            return True
    return False


def filter_film_items(items):
    """只保留影视相关的条目"""
    return [item for item in items if item.get("is_film_related")]


def format_hotspot_report(all_results, tz_offset=8):
    """格式化为热点猎手的标准日报格式"""
    now = datetime.now(timezone(timedelta(hours=tz_offset)))
    lines = []
    lines.append(f"🔥 每日热榜速报 | {now.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"数据来源：DailyHotApi 聚合热榜")
    lines.append("=" * 60)
    lines.append("")

    total_film_items = 0

    for result in all_results:
        meta = result.get("meta", {})
        items = result.get("items", [])
        error = result.get("error")

        source_name = meta.get("name", result.get("source", "unknown"))
        update_time = meta.get("updateTime", "")

        if error:
            lines.append(f"⚠️ {source_name}：抓取失败 ({error})")
            lines.append("")
            continue

        film_items = filter_film_items(items)
        total_film_items += len(film_items)

        category_info = DEFAULT_SOURCES.get(result.get("source", ""), {})
        category = category_info.get("category", "📊 其他")

        lines.append(f"## {category} → {source_name}")
        lines.append(f"   更新时间：{update_time} | 共 {len(items)} 条 | 影视相关 {len(film_items)} 条")
        lines.append("")

        # 影视相关的排在前面，最多展示10条
        display_items = film_items[:10]
        for i, item in enumerate(display_items, 1):
            hot_str = f"🔥{item['hot']}" if item['hot'] else ""
            lines.append(f"  {i}. {item['title']}")
            if item['desc']:
                lines.append(f"     {item['desc'][:80]}")
            if hot_str:
                lines.append(f"     热度：{hot_str}")
            if item['url']:
                lines.append(f"     链接：{item['url']}")
            lines.append("")

        # 非影视但也可能有价值的
        other_items = [it for it in items if not it.get("is_film_related")]
        if other_items and len(film_items) < 5:
            lines.append(f"  📌 其他高热度条目（可能可开发影视角度）：")
            for item in other_items[:3]:
                hot_str = f"🔥{item['hot']}" if item['hot'] else ""
                lines.append(f"     · {item['title']} {hot_str}")
            lines.append("")

        lines.append("")

    lines.append("=" * 60)
    lines.append(f"📊 统计：共抓取 {len(all_results)} 个平台 | 影视相关条目 {total_film_items} 条")
    lines.append("")
    lines.append("📋 下一步：")
    lines.append("  1. 选题策划师：从上述热点中选出 3-5 个可做选题")
    lines.append("  2. 封不住（写手）：根据选定方向搜索素材、准备初稿")
    lines.append("  3. 关注时效性：S级热点建议 4 小时内出稿")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="DailyHotApi 热榜聚合抓取")
    parser.add_argument("--source", default="all",
                        help="数据源名称，多个用逗号分隔 (douban-movie,weibo,bilibili,douyin,zhihu,baidu,toutiao,douban-group)")
    parser.add_argument("--limit", type=int, default=20,
                        help="每个源取几条 (默认20)")
    parser.add_argument("--format", default="both",
                        choices=["json", "report", "both", "hotspot-report"],
                        help="输出格式")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印不保存文件")
    parser.add_argument("--api", default=None,
                        help="手动指定 API 端点 (覆盖自动检测)")
    parser.add_argument("--no-filter", action="store_true",
                        help="不过滤影视相关，展示全部")
    parser.add_argument("--timeout", type=int, default=15,
                        help="请求超时秒数")
    args = parser.parse_args()

    # 确定数据源
    if args.source == "all":
        sources = list(DEFAULT_SOURCES.keys())
    else:
        sources = [s.strip() for s in args.source.split(",")]
        for s in sources:
            if s not in DEFAULT_SOURCES:
                print(f"⚠️ 未知数据源：{s}，跳过", file=sys.stderr)

    sources = [s for s in sources if s in DEFAULT_SOURCES]

    # 按优先级排序
    sources.sort(key=lambda s: DEFAULT_SOURCES[s]["priority"])

    # 找可用的 API
    base_url = args.api or find_working_api(timeout=args.timeout)
    if not base_url:
        print("❌ 所有 API 端点均不可达，请检查网络或手动指定 --api", file=sys.stderr)
        sys.exit(1)

    print(f"🌐 使用 API：{base_url}", file=sys.stderr)
    print(f"📡 抓取 {len(sources)} 个数据源...", file=sys.stderr)

    # 抓取所有源
    all_results = []
    for source_name in sources:
        print(f"   ⏳ {DEFAULT_SOURCES[source_name]['name']}...", file=sys.stderr, end=" ")
        result = fetch_source(base_url, source_name, limit=args.limit)
        result["source"] = source_name  # 确保有 source 字段
        all_results.append(result)

        error = result.get("error") or result.get("meta", {}).get("error")
        if error:
            print(f"❌ {error}", file=sys.stderr)
        else:
            meta = result.get("meta", {})
            n = meta.get("total", len(result.get("items", [])))
            n_film = len(filter_film_items(result.get("items", [])))
            print(f"✅ {n}条 (影视{n_film})", file=sys.stderr)

        time.sleep(0.5)  # 礼貌间隔

    # 生成报表
    report = format_hotspot_report(all_results)

    # 保存
    today = datetime.now().strftime("%Y-%m-%d")
    if not args.dry_run:
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        # 保存 JSON 原始数据
        json_path = os.path.join(OUTPUT_DIR, f"{today}-dailyhot-raw.json")
        json_output = {
            "date": today,
            "fetch_time": datetime.now().isoformat(),
            "api": base_url,
            "sources": all_results,
        }
        with open(json_path, "w") as f:
            json.dump(json_output, f, ensure_ascii=False, indent=2)
        print(f"\n💾 原始数据已保存：{json_path}", file=sys.stderr)

        # 保存可读报表
        report_path = os.path.join(OUTPUT_DIR, f"{today}-dailyhot-report.md")
        with open(report_path, "w") as f:
            f.write(report)
        print(f"📝 热榜日报已保存：{report_path}", file=sys.stderr)

    # 输出
    if args.format in ("json", "both"):
        print(json.dumps(all_results, ensure_ascii=False, indent=2))
    if args.format in ("report", "hotspot-report", "both"):
        print(report)


if __name__ == "__main__":
    main()
