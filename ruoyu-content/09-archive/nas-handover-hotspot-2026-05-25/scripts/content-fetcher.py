#!/usr/bin/env python3
"""
内容抓取器 v1.0 — 零Token文章采集
====================================
读取雷达脚本产出的URL JSON → trafilatura抓正文 → 分类存档。
所有工作在Python内完成，不消耗OpenClaw token。

用法：
  python3 content-fetcher.py                              # 处理今天的所有URL
  python3 content-fetcher.py --date 2026-05-25            # 指定日期
  python3 content-fetcher.py --dry-run                    # 只预览不抓取
  python3 content-fetcher.py --limit 12                   # 每类最多12篇
"""

import json
import os
import sys
import re
import time
import hashlib
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ─── 动态设置 venv ───────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE = SCRIPT_DIR.parent
VENV_SITE = WORKSPACE / ".venv" / "lib" / "python3.11" / "site-packages"
if VENV_SITE.exists():
    sys.path.insert(0, str(VENV_SITE))

from trafilatura import extract
import urllib.request
import urllib.error
import urllib.parse

# ─── 配置 ───────────────────────────────────────────────
CORPUS_DIR = WORKSPACE / "article-corpus"
RESEARCH_DIR = WORKSPACE / "research-daily"

REQUEST_TIMEOUT = 20
MIN_WORD_COUNT = 200
MAX_ARTICLES = 12  # 每类最多抓取

# 域名可抓性判断
FETCHABLE_DOMAINS = [
    "thepaper.cn", "new.qq.com", "news.163.com", "3dmgame.com",
    "ali213.net", "gamersky.com", "qbitai.com", "jiqizhixin.com",
    "wallstreetcn.com", "cls.cn", "yicai.com", "eeo.com.cn",
    "chinastarmarket.cn", "sohu.com", "ifeng.com",
    "time-weekly.com", "lifetimes.cn", "bjnews.com.cn",
    "chinanews.com.cn", "bbc.com", "rfi.fr", "nytimes.com",
    "stnn.cc", "myzaker.com", "ithome.com",
    "leiphone.com", "tmtpost.com", "36kr.com",
    "guokr.com", "dxy.com", "familydoctor.cn",
]

BLOCKED_DOMAINS = [
    "zhihu.com", "douban.com", "toutiao.com",
    "baidu.com", "tieba.baidu.com", "juejin.cn",
    "weixin.qq.com", "mp.weixin.qq.com",
    "douyin.com", "bilibili.com", "acfun.cn",
    "maoyan.com", "iqiyi.com", "v.qq.com", "youku.com", "mgtv.com",
    "music.163.com", "github.com", "huggingface.co",
    "middlefun.com", "2libra.com", "v2ex.com",
    "kuaijitoutiao.com", "bbs.pinggu.org",
]

# 彭博/财经快讯类（无正文）
NEWS_TICKER_DOMAINS = [
    "jin10.com", "smm.cn", "fx678.com", "10jqka.com.cn",
    "laohucaijing.com", "theblockbeats.info", "chaincatcher.com",
]


def is_fetchable(url):
    """判断URL是否值得尝试抓取"""
    domain = urllib.parse.urlparse(url).netloc.lower()
    for bd in BLOCKED_DOMAINS:
        if bd in domain:
            return False
    for bd in NEWS_TICKER_DOMAINS:
        if bd in domain:
            return False
    return True


def is_known_good(url):
    """已知可抓域名"""
    domain = urllib.parse.urlparse(url).netloc.lower()
    for gd in FETCHABLE_DOMAINS:
        if gd in domain:
            return True
    return False


def fetch_article_content(url, timeout=REQUEST_TIMEOUT):
    """下载 + trafilatura extract 提取文章正文（返回markdown）"""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; ContentFetcher/1.0)",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read()

        # trafilatura extract — 直接返回 markdown 文本
        text = extract(html, output_format="markdown",
                       deduplicate=True, favor_precision=True,
                       include_links=False, include_images=False,
                       include_tables=False, include_formatting=False)

        if not text or len(text.strip()) < 20:
            return None, "extraction_failed"

        text = text.strip()
        word_count = len(text)

        # 尝试从文本首行提取标题
        title = ""
        lines = text.split("\n")
        if lines and lines[0].strip().startswith("#"):
            title = lines[0].strip("# ").strip()

        return {
            "text": text,
            "word_count": word_count,
            "title": title,
        }, "ok"

    except urllib.error.HTTPError as e:
        return None, f"http_{e.code}"
    except urllib.error.URLError as e:
        return None, "url_error"
    except Exception as e:
        return None, f"error:{str(e)[:40]}"


def safe_filename(title):
    """生成安全的文件名"""
    name = re.sub(r'[<>:"/\\|?*#\[\]]', '', title)
    name = name.strip()[:60]
    if not name:
        name = "untitled"
    return name


def load_urls(date_str):
    """读取当天的URL JSON文件"""
    urls = {"film": [], "social": []}

    for prefix in ["trendapi", "thepaper"]:
        json_path = RESEARCH_DIR / f"{date_str}-{prefix}-urls.json"
        if not json_path.exists():
            continue

        try:
            with open(json_path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        for cat in ["film", "social"]:
            items = data.get(f"{cat}s", [])  # films/socials
            for item in items:
                url = item.get("url", "")
                if url and url not in {u["url"] for u in urls[cat]}:
                    urls[cat].append({
                        "title": item.get("title", ""),
                        "url": url,
                        "source": item.get("source", ""),
                    })

    return urls


def is_film_article(url_dict):
    """判断文章是否为影视/文娱类"""
    title = url_dict.get("title", "")
    source = url_dict.get("source", "")
    film_kw = [
        "电影", "电视剧", "综艺", "纪录片", "动画", "动漫", "短剧",
        "导演", "演员", "演技", "剧本", "编剧", "票房", "院线", "上映",
        "定档", "撤档", "好莱坞", "网飞", "Netflix", "漫威", "DC",
        "戛纳", "奥斯卡", "影帝", "影后", "影评", "预告片", "剧集",
        "改编", "翻拍", "续集", "烂片", "黑马", "口碑", "豆瓣评分",
        "给阿嬷",
    ]
    return any(kw in title or kw in source for kw in film_kw)


def process(date_str, limit=MAX_ARTICLES, dry_run=False):
    """主抓取流程"""
    tz = timezone(timedelta(hours=8))
    start_time = datetime.now(tz)

    print(f"📥 内容抓取器启动 | {start_time.strftime('%Y-%m-%d %H:%M')}", file=sys.stderr)

    # 1. 加载URL
    urls = load_urls(date_str)
    total_urls = len(urls["film"]) + len(urls["social"])
    if total_urls == 0:
        print("⚠️ 没有发现URL数据，请先运行雷达脚本", file=sys.stderr)
        return None

    print(f"📡 加载URL: 影视{len(urls['film'])}条 + 社会{len(urls['social'])}条", file=sys.stderr)

    # 2. 逐篇抓取
    results = {"film": [], "social": []}
    stats = {"fetched": 0, "failed": 0, "partial": 0, "skipped": 0, "blocked": 0}

    for category in ["film", "social"]:
        for item in urls[category]:
            # 限流
            if len(results[category]) >= limit:
                break

            url = item["url"]
            title_hint = item["title"][:50]

            # 跳过已知反爬域名
            if not is_fetchable(url):
                print(f"  🚫 [{category[:4]}] {title_hint} → 反爬域名", file=sys.stderr)
                stats["blocked"] += 1
                continue

            # 抓取
            print(f"  ⏳ [{category[:4]}] {title_hint}", file=sys.stderr, end="")
            content, status = fetch_article_content(url)

            if not content:
                print(f" → ❌ {status}", file=sys.stderr)
                stats["failed"] += 1
                continue

            wc = content["word_count"]
            final_title = content["title"] or item["title"]

            if wc < MIN_WORD_COUNT:
                print(f" → ⚠️ {wc}字(partial)", file=sys.stderr)
                status = "partial"
                stats["partial"] += 1
            else:
                print(f" → ✅ {wc}字", file=sys.stderr)
                status = "full"
                stats["fetched"] += 1

            article = {
                "title": final_title,
                "url": url,
                "source": item["source"],
                "text": content["text"],
                "word_count": wc,
                "status": status,
            }
            results[category].append(article)

            # 反爬延迟
            time.sleep(0.5)

    # 3. 存档
    if dry_run:
        print("\n🧪 DRY RUN — 不保存文件", file=sys.stderr)
        _print_summary(results, stats, date_str)
        return results

    # 创建目录
    for cat in ["film", "social"]:
        (CORPUS_DIR / date_str / cat).mkdir(parents=True, exist_ok=True)

    # 写入文章
    metadata_articles = []
    for category in ["film", "social"]:
        for i, article in enumerate(results[category], 1):
            fname = f"{i:03d}-{safe_filename(article['title'])}.md"
            fpath = CORPUS_DIR / date_str / category / fname

            # Markdown格式
            md = f"# {article['title']}\n\n"
            md += f"**来源**: {article['source']}\n"
            md += f"**原文链接**: {article['url']}\n"
            md += f"**字数**: {article['word_count']} | **状态**: {article['status']}\n"
            md += f"\n---\n\n{article['text']}\n"

            with open(fpath, "w", encoding="utf-8") as f:
                f.write(md)

            metadata_articles.append({
                "file": f"{category}/{fname}",
                "title": article["title"],
                "source": article["source"],
                "url": article["url"],
                "word_count": article["word_count"],
                "status": article["status"],
                "category": category,
            })

    # 写入 metadata.json
    metadata = {
        "date": date_str,
        "fetch_time": start_time.isoformat(),
        "pipeline": "hotspot-v2",
        "total": len(results["film"]) + len(results["social"]),
        "film_count": len(results["film"]),
        "social_count": len(results["social"]),
        "stats": stats,
        "articles": metadata_articles,
    }

    meta_path = CORPUS_DIR / date_str / "metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    _print_summary(results, stats, date_str)
    print(f"\n📁 语料库: {CORPUS_DIR / date_str}", file=sys.stderr)

    return results


def _print_summary(results, stats, date_str):
    """打印摘要"""
    print(f"\n{'='*50}", file=sys.stderr)
    print(f"📊 {date_str} 抓取报告", file=sys.stderr)
    print(f"  影视: {len(results['film'])}篇 | 社会: {len(results['social'])}篇", file=sys.stderr)
    print(f"  ✅ full={stats['fetched']} ⚠️ partial={stats['partial']} "
          f"❌ failed={stats['failed']} 🚫 blocked={stats['blocked']}", file=sys.stderr)

    for cat in ["film", "social"]:
        for a in results[cat]:
            icon = "✅" if a["status"] == "full" else "⚠️"
            print(f"  {icon} [{cat[:4]}] {a['title'][:50]} ({a['word_count']}字)", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="内容抓取器 — trafilatura 零token采集")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                        help="日期（默认今天）")
    parser.add_argument("--limit", type=int, default=MAX_ARTICLES,
                        help=f"每类最多抓取（默认{MAX_ARTICLES}）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只预览不保存")
    args = parser.parse_args()

    process(args.date, limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
