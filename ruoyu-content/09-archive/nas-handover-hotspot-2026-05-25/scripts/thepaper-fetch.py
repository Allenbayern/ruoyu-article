#!/usr/bin/env python3
"""
澎湃新闻直连抓取器 v1.0
========================
直接解析澎湃首页 __NEXT_DATA__ JSON，提取文章URL列表。
含影视+社会热点双重筛选，输出结构化URL供后续 web_fetch 抓取正文。

用法：
  python3 thepaper-fetch.py                    # 默认：提取所有文章URL
  python3 thepaper-fetch.py --limit 20         # 最多20条
  python3 thepaper-fetch.py --dry-run          # 只打印不保存
"""

import json
import os
import sys
import re
import argparse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

# ─── 配置 ───────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR = os.path.join(WORKSPACE, "research-daily")

HOMEPAGE_URL = "https://www.thepaper.cn/"
SEARCH_TEMPLATE = "https://www.thepaper.cn/search?searchKeyword={keyword}&page=1"

FILM_TOPICS = [
    "电影", "票房", "院线", "上映", "导演", "演员", "影评",
    "电视剧", "综艺", "动画", "纪录片", "短剧",
    "豆瓣", "IMDb", "戛纳", "奥斯卡", "金鸡",
    "Netflix", "网飞", "HBO", "迪士尼", "漫威", "DC",
    "好莱坞", "国产片", "文艺片", "大片",
    "给阿嬷", "乘风", "奔跑吧", "跑男",
    "阿凡达", "复联", "蜘蛛侠", "蝙蝠侠", "超人",
    "剧集", "网剧", "爱奇艺", "腾讯视频", "优酷",
    "烂片", "黑马", "口碑", "评分", "口碑炸",
    "庆余年", "三体", "诡秘", "流浪地球",
    "谍战", "悬疑", "科幻片", "喜剧", "恐怖片",
    "电影节", "首映礼", "路演", "预告",
    "影后", "影帝", "视帝", "视后",
    "原著", "改编", "翻拍", "续集", "前传",
    "作死", "\u6d6e\u8e81", "封神",
]

SOCIAL_TOPICS = [
    "事故", "爆炸", "安全", "煤矿", "调查",
    "政策", "民生", "教育", "医疗", "住房",
    "社会", "争议", "通报", "刑拘", "问责",
    "反腐", "贪污", "违纪",
    "航天", "科技", "创新", "突破",
    "国际", "外交", "贸易", "制裁",
]

# 排除的后缀/域名（非文章页）
SKIP_PATTERNS = [
    r"live\.thepaper\.cn",
    r"/video",
    r"m\.thepaper\.cn",
    r"app\.thepaper\.cn",
    r"/user/",
    r"/comment",
    r"\.pdf$", r"\.mp4$", r"\.jpg$",
]

# 文章页URL模式
ARTICLE_PATTERN = re.compile(r"/newsDetail_forward_\d+")


def fetch_homepage_data(timeout=20):
    """获取澎湃首页的 __NEXT_DATA__ JSON"""
    req = urllib.request.Request(
        HOMEPAGE_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; PaperFetcher/1.0)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"❌ 首页请求失败: {e}", file=sys.stderr)
        return None

    # 提取 __NEXT_DATA__
    marker = '__NEXT_DATA__" type="application/json">'
    idx = html.find(marker)
    if idx == -1:
        # 尝试旧格式
        marker = '"__NEXT_DATA__","props":'
        idx = html.find(marker)
        if idx == -1:
            print("❌ 未找到 __NEXT_DATA__", file=sys.stderr)
            return None

    start = html.index(">", idx) + 1
    end = html.index("</script>", start)
    json_str = html[start:end].strip()

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"❌ JSON解析失败: {e}", file=sys.stderr)
        return None


def extract_articles_from_data(data):
    """从 __NEXT_DATA__ 中提取所有文章信息"""
    articles = []
    seen_urls = set()

    pp = data.get("props", {}).get("pageProps", {}).get("data", {})
    if not pp:
        return articles

    def walk(obj, depth=0):
        if depth > 6:
            return
        if isinstance(obj, dict):
            # 检查是否为文章对象
            cont_id = obj.get("contId") or obj.get("contid")
            name = obj.get("name") or obj.get("title")
            url = obj.get("link") or obj.get("url", "")

            if cont_id and name and not url:
                # 构造URL
                url = f"https://www.thepaper.cn/newsDetail_forward_{cont_id}"

            if cont_id and name and url and url not in seen_urls:
                if not ARTICLE_PATTERN.search(url):
                    return  # 不是文章页

                for pat in SKIP_PATTERNS:
                    if re.search(pat, url):
                        return

                seen_urls.add(url)
                articles.append({
                    "id": str(cont_id),
                    "title": name,
                    "url": url,
                    "source": "澎湃新闻",
                    "source_detail": obj.get("nodeInfo", {}).get("name", ""),
                    "node_id": obj.get("nodeId") or obj.get("node_id", ""),
                    "pub_time": obj.get("pubTime") or obj.get("pubTimeNew", ""),
                    "praise": obj.get("praiseTimes", ""),
                    "tags": [t.get("tag", "") for t in obj.get("tagList", [])],
                })

            for v in obj.values():
                walk(v, depth + 1)

        elif isinstance(obj, list):
            for item in obj:
                walk(item, depth + 1)

    walk(pp)
    return articles


def classify_article(article):
    """分类：film / social / other"""
    title = article.get("title", "")
    tags = " ".join(article.get("tags", []))
    source_detail = article.get("source_detail", "")
    text = title + " " + tags + " " + source_detail

    for kw in FILM_TOPICS:
        if kw in text:
            return "film"

    for kw in SOCIAL_TOPICS:
        if kw in text:
            return "social"

    return "other"


def format_report(film_articles, social_articles):
    """格式化输出"""
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    lines = []

    lines.append(f"📰 澎湃新闻直连 | {now.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"数据源：thepaper.cn 首页 SSR 数据")
    lines.append("=" * 60)
    lines.append("")

    lines.append(f"## 🎬 影视相关（{len(film_articles)}篇）")
    lines.append("")
    for i, a in enumerate(film_articles, 1):
        lines.append(f"{i}. {a['title'][:60]}")
        lines.append(f"   📂 {a['source_detail']} | {a['pub_time']} | ❤️{a.get('praise','')}")
        lines.append(f"   🔗 {a['url']}")
        lines.append("")

    lines.append("")
    lines.append(f"## 📰 社会热点（{len(social_articles)}篇）")
    lines.append("")
    for i, a in enumerate(social_articles, 1):
        lines.append(f"{i}. {a['title'][:60]}")
        lines.append(f"   📂 {a['source_detail']} | {a['pub_time']} | ❤️{a.get('praise','')}")
        lines.append(f"   🔗 {a['url']}")
        lines.append("")

    lines.append("=" * 60)
    lines.append(f"📊 影视 {len(film_articles)} 篇 | 社会 {len(social_articles)} 篇 | "
                 f"合计 {len(film_articles)+len(social_articles)} 篇")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="澎湃新闻直连抓取器")
    parser.add_argument("--limit", type=int, default=0,
                        help="每类最多取几条（0=不限）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印不保存")
    args = parser.parse_args()

    print("🌐 获取澎湃首页数据...", file=sys.stderr)
    data = fetch_homepage_data(timeout=20)

    if not data:
        print("❌ 获取首页数据失败", file=sys.stderr)
        sys.exit(1)

    articles = extract_articles_from_data(data)
    print(f"📡 提取到 {len(articles)} 篇文章", file=sys.stderr)

    if not articles:
        print("⚠️ 未提取到文章（可能页面结构已变更）", file=sys.stderr)
        sys.exit(0)

    # 分类
    film_articles = []
    social_articles = []
    other_articles = []

    for a in articles:
        cat = classify_article(a)
        if cat == "film":
            film_articles.append(a)
        elif cat == "social":
            social_articles.append(a)
        else:
            other_articles.append(a)

    # 应用limit
    if args.limit > 0:
        film_articles = film_articles[:args.limit]
        social_articles = social_articles[:args.limit]

    print(f"🎬 影视: {len(film_articles)} | 📰 社会: {len(social_articles)} | "
          f"🔖 其他: {len(other_articles)}", file=sys.stderr)

    report = format_report(film_articles, social_articles)

    if not args.dry_run:
        today = datetime.now().strftime("%Y-%m-%d")
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        # 保存报告
        report_path = os.path.join(OUTPUT_DIR, f"{today}-thepaper-report.md")
        with open(report_path, "w") as f:
            f.write(report)
        print(f"📝 报告: {report_path}", file=sys.stderr)

        # 保存结构化JSON
        json_path = os.path.join(OUTPUT_DIR, f"{today}-thepaper-urls.json")
        json_data = {
            "date": today,
            "fetch_time": datetime.now().isoformat(),
            "source": "thepaper.cn",
            "films": [
                {"title": a["title"], "url": a["url"], "source": a["source_detail"]}
                for a in film_articles
            ],
            "socials": [
                {"title": a["title"], "url": a["url"], "source": a["source_detail"]}
                for a in social_articles
            ],
        }
        with open(json_path, "w") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        print(f"💾 URL数据: {json_path}", file=sys.stderr)

    print(report)


if __name__ == "__main__":
    main()
