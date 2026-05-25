#!/usr/bin/env python3
"""
TrendAPI 热点雷达抓取脚本 v1.0
===============================
对接 TrendAPI (trendapi.tgmeng.com) 做全网热点发现。
输出50%影视文娱 + 50%社会热点的结构化URL列表，供后续正文抓取。

用法：
  python3 trendapi-fetch.py                     # 默认模式：影视+社会 各10条
  python3 trendapi-fetch.py --limit 30          # 各30条
  python3 trendapi-fetch.py --mode film         # 仅影视
  python3 trendapi-fetch.py --mode social       # 仅社会热点
  python3 trendapi-fetch.py --dry-run           # 只打印不保存
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
WORKSPACE = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR = os.path.join(WORKSPACE, "research-daily")

API_URL = "https://trendapi.tgmeng.com/api/skill/search"
LICENSE = "I32M-PKGF-UKAV-GQ21-KDWQ-U4F4"

# ─── 影视文娱分类 ─────────────────────────────────────
# ─── 影视文娱：优先「文章产出型」来源 ────────────
# 这些来源产出的是真正的影视资讯/评论文章（有正文可抓）
FILM_ARTICLE_SOURCES = [
    "时光网",          # 影视资讯文章
    "美漫百科",        # 影视剧流言汇总
    "游研社",          # 游戏影视评论
    "机核", "GCORES",  # 游戏影视文化
    "澎湃新闻",        # 影视深度报道
    "新京报",          # 影视娱乐版
    "豆瓣",            # 影视讨论
    "36氪", "钛媒体",  # 文娱产业分析
    "3DMGAME", "游侠网", "游民星空", "A9VG",  # 游戏含影视
    "IGN", "gamebase", "电玩帮", "17173",
]

# 这些主要是影视片单/视频（无正文可抓，仅做选题参考）
FILM_REFERENCE_SOURCES = [
    "猫眼", "腾讯视频", "爱奇艺视频", "优酷视频",
    "芒果视频", "B站", "百度文娱", "电视猫",
]

FILM_KEYWORDS = [
    "电影", "电视剧", "综艺", "纪录片", "动画", "动漫", "短剧",
    "导演", "演员", "演技", "剧本", "编剧", "票房", "院线", "上映",
    "定档", "撤档", "排片", "好莱坞", "国产片", "网飞", "Netflix",
    "漫威", "DC", "奥斯卡", "戛纳", "金鸡", "影帝", "影后",
    "影评", "预告片", "首映", "剧集", "网剧", "IP改编",
    "烂片", "黑马", "豆瓣评分", "口碑", "档期", "给阿嬷",
]

FILM_EXCLUDE_KEYWORDS = [
    "光伏", "储能", "期货", "股票", "基金", "涨停",
    "煤炭", "原油", "钢铁", "国考", "公务员", "考研",
    "GitHub", "Flutter", "API", "CUDA", "开源",
    "ADC治疗", "肿瘤", "癌症", "干细胞", "基因编辑",
]

# ─── 社会热点分类 ─────────────────────────────────────
SOCIAL_ROOT_CATEGORIES = ["新闻", "生活", "社区", "媒体"]
SOCIAL_CATEGORIES = [
    "新闻", "CCTV", "媒体", "社区",
    "百度", "百度民生", "百度新闻", "百度国际",
]

SOCIAL_EXCLUDE_KEYWORDS = [
    # 行业垂直（非大众关注）
    "光伏", "储能", "风电", "漂浮式", "地热能", "超临界",
    "煤炭", "焦煤", "螺纹钢", "有色金属", "电解铝",
    "期货", "快讯", "开盘", "收盘", "涨停", "跌停", "主力",
    "原油", "成品油", "油价", "沥青", "波罗的海",
    "钢铁", "钢管", "无缝管",
    "国家电网", "国家电投", "电投", "节能风电", "三峡能源",
    "能源局", "中俄联合声明",
    # 考试/教育（小众）
    "国考", "公务员", "教资", "教师资格", "四六级", "考研",
    "事业单位", "银行招聘", "公告",
    # 程序员/技术（非大众）
    "Flutter", "CUDA", "GitHub", "开源", "NPM", "Docker",
    "tRPC", "TensorFlow", "PyTorch",
    # 非新闻类
    "副业", "羊毛", "会计", "税务筹划",
    "快讯】", "期货】", "电报】",
    "半导体", "芯片", "NAND", "存储",
    # UGC娱乐（非新闻）
    "acfun", "AcFun", "ACFUN",
]
SOCIAL_PRIORITY_SOURCES = [
    "澎湃新闻", "新京报", "中国新闻网",
    "头条新闻", "腾讯新闻", "网易新闻",
    "微博", "抖音",
    "知乎", "虎扑体育", "步行街虎扑",
    "央视电视台",
    "第一财经", "每经网", "21经济网",
    "ZAKER", "BBC", "纽约时报", "法广", "星岛环球",
    "时代在线", "金十",
    "果壳", "丁香医生", "生命时报",
    "华尔街见闻", "财联社",
    "BBC", "法广", "纽约时报",
]
SOCIAL_NORMAL_SOURCES = [
    "新浪财经", "同花顺", "东方财富网",
    "中关村在线", "IT之家", "快科技",
    "虎嗅", "创业邦", "i黑马",
    "经济观察网",
]


def fetch_trendapi(timeout=30):
    """调用 TrendAPI REALTIME 接口"""
    body = json.dumps({
        "license": LICENSE,
        "mode": "REALTIME"
    }).encode("utf-8")

    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "OpenClaw-TrendFetcher/1.0"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            if data.get("code") == 200:
                return data.get("data", {}).get("items", [])
            else:
                print(f"❌ API错误: {data.get('message', 'unknown')}", file=sys.stderr)
                return []
    except Exception as e:
        print(f"❌ 请求失败: {e}", file=sys.stderr)
        return []


def is_film(item):
    """判断是否为影视文娱内容（优先文章产出型来源）"""
    title = item.get("title", "")
    source = item.get("source", "")
    text = title

    # 排除明确非影视的内容
    for kw in FILM_EXCLUDE_KEYWORDS:
        if kw in text:
            return False

    # 必须包含影视关键词（对非影视垂直源做强制要求）
    has_film_kw = any(kw in title for kw in FILM_KEYWORDS)

    # 优先：文章产出型来源（有正文可抓）
    if source in FILM_ARTICLE_SOURCES:
        if source in ["3DMGAME", "游侠网", "游民星空", "A9VG", "gamebase", "电玩帮", "4Gamer"]:
            # 游戏源：必须标题含电影/影视关键词
            return has_film_kw or any(kw in title for kw in ["预告", "预告片", "电影", "改编", "剧集", "IP"])
        return True

    # 片单/视频型来源：必须含影视关键词
    if source in FILM_REFERENCE_SOURCES:
        return has_film_kw

    # 其他来源：标题包含影视关键词
    return has_film_kw


def is_social(item):
    """判断是否为社会热点内容"""
    title = item.get("title", "")
    source = item.get("source", "")
    text = title

    # 排除行业垂直噪声
    for kw in SOCIAL_EXCLUDE_KEYWORDS:
        if kw in text:
            return False

    # 高价值社会源（新闻媒体、社交平台）
    high_value_social = [
        "澎湃新闻", "新京报", "中国新闻网",
        "头条新闻", "腾讯新闻", "网易新闻", "百度新闻",
        "微博", "抖音",
        "知乎", "虎扑体育", "步行街虎扑",
        "央视电视台",
        "ZAKER", "BBC", "纽约时报", "法广", "星岛环球",
        "时代在线", "金十",
        "果壳", "丁香医生", "生命时报",
    ]
    if source in high_value_social:
        return True

    # 财经媒体：需要标题有社会属性（不是纯金融分析）
    finance_social = [
        "华尔街见闻", "财联社", "第一财经", "每经网",
        "21经济网", "经济观察网",
        "新浪财经", "同花顺", "东方财富网",
    ]
    if source in finance_social:
        # 财经媒体只取有社会话题性的（排除纯市场分析）
        social_signals = [
            "事故", "爆炸", "矿难", "灾难", "地震", "洪水",
            "政策", "整治", "立案", "调查", "通报",
            "民生", "教育", "医疗", "养老", "住房", "户籍",
            "造假", "食品", "安全", "召回",
            "航天", "火箭", "卫星", "空间站", "登月",
            "反腐", "贪污", "违纪", "双开",
            "枪击", "恐袭", "战争", "冲突", "制裁",
            "疫情", "病毒", "疫苗", "药品",
            "新能源车", "自动驾驶", "FSD", "特斯拉",
            "裁员", "倒闭", "暴雷", "跑路",
            "高考", "中考", "招生",
        ]
        if any(sig in title for sig in social_signals):
            return True
        # 排除纯行情/市场分析
        return False

    # 根分类匹配
    if item.get("rootCategory") in SOCIAL_ROOT_CATEGORIES:
        return True

    # 分类匹配
    if item.get("category") in SOCIAL_CATEGORIES:
        return True

    return False


def filter_and_rank(items, limit_per_category=20):
    """分类过滤并去重排序"""
    films = []
    socials = []

    seen_urls = set()
    for item in items:
        url = item.get("url", "")
        # 去重 + 过滤无效URL
        if not url or url in seen_urls or url == "https://tgmeng.com":
            continue
        seen_urls.add(url)

        if is_film(item):
            films.append(item)
        elif is_social(item):
            socials.append(item)

    # 按时间排序（有publishedAt则用，无则保持原序）
    def sort_key(i):
        t = i.get("publishedAt", "")
        return t if t else ""

    films.sort(key=sort_key, reverse=True)
    socials.sort(key=sort_key, reverse=True)

    return films[:limit_per_category], socials[:limit_per_category]


def format_output(films, socials, limit):
    """格式化为可读输出"""
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    lines = []

    lines.append(f"🔭 TrendAPI 热点雷达 | {now.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"数据源：TrendAPI REALTIME（200+信源）")
    lines.append("=" * 60)
    lines.append("")

    # 影视部分
    lines.append(f"## 🎬 影视文娱热点（{len(films)}条）")
    lines.append("")
    for i, item in enumerate(films, 1):
        title = item.get("title", "无标题")[:60]
        source = item.get("source", "未知")
        category = item.get("category", "")
        url = item.get("url", "")
        pub = item.get("publishedAt", "")[:10]
        lines.append(f"{i}. [{source}] {title}")
        if pub:
            lines.append(f"   📅 {pub}")
        lines.append(f"   🔗 {url}")
        lines.append("")

    lines.append("")

    # 社会热点部分
    lines.append(f"## 📰 社会热点（{len(socials)}条）")
    lines.append("")
    for i, item in enumerate(socials, 1):
        title = item.get("title", "无标题")[:60]
        source = item.get("source", "未知")
        category = item.get("category", "")
        url = item.get("url", "")
        pub = item.get("publishedAt", "")[:10]
        lines.append(f"{i}. [{source}] {title}")
        if pub:
            lines.append(f"   📅 {pub}")
        lines.append(f"   🔗 {url}")
        lines.append("")

    lines.append("=" * 60)
    lines.append(f"📊 影视 {len(films)} 条 | 社会 {len(socials)} 条 | 合计 {len(films)+len(socials)} 条")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="TrendAPI 热点雷达抓取")
    parser.add_argument("--limit", type=int, default=20,
                        help="每类最多取几条（默认20）")
    parser.add_argument("--mode", default="both",
                        choices=["film", "social", "both"],
                        help="抓取模式")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印不保存")
    args = parser.parse_args()

    print("🌐 调用 TrendAPI REALTIME...", file=sys.stderr)
    items = fetch_trendapi(timeout=30)

    if not items:
        print("❌ 无数据返回", file=sys.stderr)
        sys.exit(1)

    print(f"📡 获取 {len(items)} 条原始数据", file=sys.stderr)

    films, socials = filter_and_rank(items, limit_per_category=args.limit)

    # 按模式过滤
    if args.mode == "film":
        socials = []
    elif args.mode == "social":
        films = []

    print(f"🎬 影视: {len(films)} 条 | 📰 社会: {len(socials)} 条", file=sys.stderr)

    report = format_output(films, socials, args.limit)

    if not args.dry_run:
        today = datetime.now().strftime("%Y-%m-%d")
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        # 保存雷达日报
        report_path = os.path.join(OUTPUT_DIR, f"{today}-trendapi-report.md")
        with open(report_path, "w") as f:
            f.write(report)
        print(f"\n📝 雷达日报: {report_path}", file=sys.stderr)

        # 保存结构化JSON（供后续抓取使用）
        json_path = os.path.join(OUTPUT_DIR, f"{today}-trendapi-urls.json")
        json_data = {
            "date": today,
            "fetch_time": datetime.now().isoformat(),
            "films": [
                {
                    "title": i.get("title", ""),
                    "url": i.get("url", ""),
                    "source": i.get("source", ""),
                    "category": i.get("category", ""),
                }
                for i in films
            ],
            "socials": [
                {
                    "title": i.get("title", ""),
                    "url": i.get("url", ""),
                    "source": i.get("source", ""),
                    "category": i.get("category", ""),
                }
                for i in socials
            ],
        }
        with open(json_path, "w") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        print(f"💾 URL数据: {json_path}", file=sys.stderr)

    # 输出到stdout
    print(report)


if __name__ == "__main__":
    main()
