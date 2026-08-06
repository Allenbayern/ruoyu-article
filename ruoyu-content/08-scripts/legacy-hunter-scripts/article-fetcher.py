#!/usr/bin/env python3
"""
爆文素材抓取引擎 v1.0 — 进化小组学习资料采集
==============================================
每天从多个平台抓取 50+ 篇影视/热点类文章全文，
供进化小组研究爆款写作规律。

数据流：
  DailyHot/热榜API → 发现话题 → Google搜索/知乎 → 文章URL → 抓取全文 → 结构化存储

用法：
  python3 article-fetcher.py                    # 全量抓取（目标50+篇）
  python3 article-fetcher.py --limit 30         # 限量30篇
  python3 article-fetcher.py --source zhihu     # 仅知乎
  python3 article-fetcher.py --dry-run          # 试运行
"""

import json
import os
import re
import sys
import time
import hashlib
import argparse
import urllib.request
import urllib.error
import urllib.parse
import html as html_mod
from datetime import datetime, timezone, timedelta

# ─── 路径配置 ──────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(SCRIPT_DIR)
CORPUS_DIR = os.path.join(WORKSPACE, "article-corpus")
DAILY_DIR_TEMPLATE = os.path.join(CORPUS_DIR, "{date}")
INDEX_FILE = os.path.join(CORPUS_DIR, "index.json")

TZ = timezone(timedelta(hours=8))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# Jina Reader API — 穿透 JS 渲染和反爬，返回干净 Markdown
JINA_KEY = "jina_65c747397bed461e88f5541173bec6a0FKMmJ-4OvGpEIZYs4TE54R1uuBLo"
JINA_API = "https://r.jina.ai"

# ─── 影视关键词（用于过滤 + 搜索） ──────────────────────
FILM_SEARCH_QUERIES = [
    # 电影核心
    "电影 深度解读 2026",
    "票房 现象级 分析",
    "国产电影 口碑 逆袭",
    "冷门佳片 推荐 影评",
    "导演 专访 创作谈",
    # 剧集
    "国产剧 爆款 分析",
    "网剧 黑马 现象",
    "电视剧 改编 原著 对比",
    # 行业/趋势
    "短剧 行业 爆发 趋势",
    "院线 票房 市场 分析",
    "流媒体 Netflix Disney 竞争",
    "AI 电影 影像 技术",
    # 人物/现象
    "演员 演技 争议 评价",
    "电影节 获奖 盘点",
    "翻拍 经典 比较",
    # 类型
    "悬疑片 叙事 技巧",
    "动画 电影 国产 崛起",
    "纪录片 真实 力量",
    "科幻 电影 中国 突破",
    # 热点向
    "影视 热点 评论",
    "烂片 吐槽 为什么 失败",
    "豆瓣 高分 冷门",
]

# ─── 信息源定义 ────────────────────────────────────────
SOURCES = {
    "zhihu-hot": {
        "name": "知乎热榜(影视)",
        "type": "api",
        "url": "http://192.168.100.223:6688/zhihu",
        "note": "本地 DailyHot 知乎热榜，直接返回 JSON",
    },
    "douban-movie": {
        "name": "豆瓣电影",
        "type": "api",
        "url": "http://192.168.100.223:6688/douban-movie",
        "note": "本地 DailyHot 豆瓣新片榜",
    },
    "baidu-hot": {
        "name": "百度热搜(影视)",
        "type": "api",
        "url": "http://192.168.100.223:6688/baidu",
        "note": "本地 DailyHot 百度热搜",
    },
    "thepaper-ent": {
        "name": "澎湃新闻·有戏",
        "type": "api",
        "url": "https://www.thepaper.cn/list_2562",
        "note": "澎湃影视频道，文章可直接抓全文",
    },
    "toutiao-search": {
        "name": "头条搜索",
        "type": "search",
        "url_template": "https://so.toutiao.com/search?dvpf=pc&source=input&keyword={query}",
        "note": "搜索后提取文章URL再抓全文",
    },
    "google-news": {
        "name": "Google搜索(新闻)",
        "type": "search_api",
        "note": "使用已配置的 Google Custom Search API",
    },
}

# ─── 文章内容抓取器 ────────────────────────────────────
class ArticleFetcher:
    def __init__(self, limit=50, dry_run=False):
        self.limit = limit
        self.dry_run = dry_run
        self.articles = []
        self.errors = []
        self.today = datetime.now(TZ).strftime("%Y-%m-%d")

    def fetch_url(self, url, timeout=15):
        """通用URL抓取，返回HTML文本"""
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            self.errors.append({"url": url, "error": str(e)})
            return None

    def fetch_json(self, url, timeout=15):
        """抓取JSON API"""
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            self.errors.append({"url": url, "error": str(e)})
            return None

    def extract_text(self, html, source):
        """从HTML中提取正文"""
        # 移除 script/style
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)

        # 按来源选择不同提取策略
        if "thepaper" in source or "澎湃" in source:
            # 澎湃新闻
            patterns = [
                r'<div[^>]*class="[^"]*news_txt[^"]*"[^>]*>(.*?)</div>',
                r'<article[^>]*>(.*?)</article>',
                r'<div[^>]*class="[^"]*article_content[^"]*"[^>]*>(.*?)</div>',
            ]
        elif "zhihu" in source:
            patterns = [
                r'<div[^>]*class="[^"]*RichText[^"]*"[^>]*>(.*?)</div>',
                r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
            ]
        elif "baidu" in source:
            patterns = [
                r'<article[^>]*>(.*?)</article>',
                r'<div[^>]*class="[^"]*article[^"]*"[^>]*>(.*?)</div>',
            ]
        else:
            # 通用提取
            patterns = [
                r'<article[^>]*>(.*?)</article>',
                r'<div[^>]*class="[^"]*(?:article|content|post|entry)[^"]*"[^>]*>(.*?)</div>',
                r'<div[^>]*id="[^"]*(?:article|content|post)[^"]*"[^>]*>(.*?)</div>',
            ]

        for pattern in patterns:
            match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
            if match:
                text = match.group(1)
                text = re.sub(r'<[^>]+>', '\n', text)
                text = html_mod.unescape(text)
                text = re.sub(r'\n{3,}', '\n\n', text)
                text = re.sub(r'[ \t]+', ' ', text)
                return text.strip()

        # 兜底：提取所有可见文本
        text = re.sub(r'<[^>]+>', ' ', html)
        text = html_mod.unescape(text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:10000]

    def extract_title(self, html):
        """从HTML提取标题"""
        match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE)
        if match:
            return html_mod.unescape(match.group(1).strip())
        match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.IGNORECASE)
        if match:
            return html_mod.unescape(re.sub(r'<[^>]+>', '', match.group(1)).strip())
        return ""

    def is_film_related(self, text):
        """判断文本是否影视相关"""
        keywords = [
            "电影", "影片", "导演", "演员", "票房", "院线", "上映",
            "电视剧", "剧集", "网剧", "综艺", "动画", "动漫", "纪录片",
            "短剧", "微短剧", "改编", "原著", "IP", "翻拍",
            "影评", "豆瓣", "IMDb", "烂番茄", "奥斯卡", "戛纳",
            "好莱坞", "国产片", "文艺片", "商业片", "类型片",
            "科幻片", "悬疑片", "喜剧片", "动作片", "恐怖片",
            "流媒体", "Netflix", "迪士尼", "HBO",
            "金鸡", "金马", "金像", "影帝", "影后",
        ]
        text_lower = text.lower()
        return any(kw.lower() in text_lower for kw in keywords)

    # ─── 数据源抓取方法 ───────────────────────────────

    def fetch_zhihu_hot(self):
        """通过本地 DailyHot API 抓取知乎热榜中的影视话题"""
        print("  📡 知乎热榜...", end=" ")
        data = self.fetch_json(SOURCES["zhihu-hot"]["url"])
        if not data:
            print("❌")
            return []

        items = data.get("data", [])
        film_items = []
        for item in items:
            title = item.get("title", "") or item.get("name", "")
            if not title:
                continue

            # 筛选影视相关
            if not self.is_film_related(title):
                continue

            url = item.get("url", "") or item.get("mobilUrl", "")
            hot_val = item.get("hot", "")

            film_items.append({
                "title": title.strip(),
                "url": url.strip(),
                "source": "zhihu-hot",
                "source_name": "知乎热榜",
                "hot": str(hot_val),
                "type": "question",
                "discovered_at": datetime.now(TZ).isoformat(),
            })

        print(f"✅ {len(film_items)}个影视话题")
        return film_items

    def fetch_baidu_hot(self):
        """通过本地 DailyHot API 抓取百度热搜中的影视条目"""
        print("  📡 百度热搜...", end=" ")
        data = self.fetch_json(SOURCES["baidu-hot"]["url"])
        if not data:
            print("❌")
            return []

        film_items = []
        for item in data.get("data", []):
            title = item.get("title", "") or item.get("name", "")
            if not title or not self.is_film_related(title):
                continue

            film_items.append({
                "title": title.strip(),
                "url": item.get("url", "") or item.get("mobilUrl", ""),
                "source": "baidu-hot",
                "source_name": "百度热搜",
                "hot": str(item.get("hot", "")),
                "type": "news",
                "discovered_at": datetime.now(TZ).isoformat(),
            })

        print(f"✅ {len(film_items)}条")
        return film_items

    def fetch_douban_movie(self):
        """抓取豆瓣新片榜"""
        print("  📡 豆瓣电影...", end=" ")
        data = self.fetch_json(SOURCES["douban-movie"]["url"])
        if not data:
            print("❌")
            return []

        film_items = []
        for item in data.get("data", []):
            title = item.get("title", "") or item.get("name", "")
            if not title:
                continue
            # 清理评分前缀 如 "【6.9】爱情抓马"
            clean_title = title.strip()

            film_items.append({
                "title": clean_title,
                "url": item.get("url", "") or item.get("mobilUrl", ""),
                "source": "douban-movie",
                "source_name": "豆瓣电影",
                "hot": str(item.get("hot", "")),
                "desc": item.get("desc", ""),
                "type": "movie",
                "discovered_at": datetime.now(TZ).isoformat(),
            })

        print(f"✅ {len(film_items)}部")
        return film_items

    def fetch_thepaper_ent(self):
        """抓取澎湃新闻影视频道文章"""
        print("  📡 澎湃·有戏...", end=" ")
        html = self.fetch_url(SOURCES["thepaper-ent"]["url"])
        if not html:
            print("❌")
            return []

        film_items = []
        # 澎湃列表页提取链接
        links = re.findall(r'<a[^>]*href="(/newsDetail_forward_\d+)"[^>]*>(.*?)</a>', html, re.DOTALL)

        for url_suffix, title_raw in links[:30]:
            title = re.sub(r'<[^>]+>', '', title_raw).strip()
            if not title or len(title) < 5:
                continue
            if not self.is_film_related(title):
                continue

            full_url = f"https://www.thepaper.cn{url_suffix}"
            film_items.append({
                "title": title,
                "url": full_url,
                "source": "thepaper",
                "source_name": "澎湃·有戏",
                "hot": "",
                "type": "article",
                "discovered_at": datetime.now(TZ).isoformat(),
            })

        print(f"✅ {len(film_items)}篇")
        return film_items

    def fetch_toutiao_search(self):
        """通过头条搜索发现影视文章"""
        print("  📡 头条搜索...", end=" ")
        import random
        queries = random.sample(FILM_SEARCH_QUERIES, min(5, len(FILM_SEARCH_QUERIES)))

        all_items = []
        for query in queries[:3]:  # 限制请求量
            url = SOURCES["toutiao-search"]["url_template"].format(query=urllib.parse.quote(query))
            html = self.fetch_url(url, timeout=15)
            if not html:
                continue

            # 提取头条搜索结果中的链接
            links = re.findall(r'href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL)
            for link, title_raw in links:
                title = re.sub(r'<[^>]+>', '', title_raw).strip()
                if not title or len(title) < 8:
                    continue
                if "toutiao.com" not in link and "/group/" not in link:
                    continue
                if not self.is_film_related(title):
                    continue

                all_items.append({
                    "title": title,
                    "url": link if link.startswith("http") else f"https:{link}",
                    "source": "toutiao-search",
                    "source_name": "头条搜索",
                    "hot": "",
                    "type": "article",
                    "discovered_at": datetime.now(TZ).isoformat(),
                })
            time.sleep(1)

        # 去重
        seen = set()
        unique = []
        for item in all_items:
            key = item["title"][:50]
            if key not in seen:
                seen.add(key)
                unique.append(item)

        print(f"✅ {len(unique)}篇")
        return unique

    def google_search_articles(self):
        """使用 Google Custom Search 查找影视文章"""
        print("  📡 Google搜索...", end=" ")

        api_key = "AIzaSyB3P_FIXi81KXQOeWKOV6KJd6w61ZSwu8c"
        cx = "418c686055e7342df"
        all_items = []

        import random
        queries = random.sample(FILM_SEARCH_QUERIES, min(6, len(FILM_SEARCH_QUERIES)))

        for query in queries[:4]:
            params = urllib.parse.urlencode({
                "key": api_key,
                "cx": cx,
                "q": query,
                "num": 10,
                "lr": "lang_zh-CN",
                "sort": "date",
            })
            url = f"https://www.googleapis.com/customsearch/v1?{params}"
            data = self.fetch_json(url)
            if not data or "items" not in data:
                continue

            for item in data["items"]:
                title = item.get("title", "")
                link = item.get("link", "")
                snippet = item.get("snippet", "")

                if not self.is_film_related(f"{title} {snippet}"):
                    continue

                all_items.append({
                    "title": html_mod.unescape(title),
                    "url": link,
                    "source": "google",
                    "source_name": "Google搜索",
                    "hot": "",
                    "snippet": snippet,
                    "type": "article",
                    "discovered_at": datetime.now(TZ).isoformat(),
                })

            time.sleep(0.5)

        # 去重
        seen = set()
        unique = []
        for item in all_items:
            uid = item["url"].split("?")[0].rstrip("/")
            if uid not in seen:
                seen.add(uid)
                unique.append(item)

        print(f"✅ {len(unique)}篇")
        return unique

    def fetch_via_jina(self, url, timeout=30):
        """通过 Jina Reader 抓取文章（穿透 JS 渲染和反爬）"""
        req = urllib.request.Request(
            f"{JINA_API}/{url}",
            headers={
                "Authorization": f"Bearer {JINA_KEY}",
                "X-Return-Format": "markdown",
                "User-Agent": UA,
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            self.errors.append({"url": url, "error": f"Jina: {e}"})
            return None

    def extract_jina_content(self, markdown_text):
        """从 Jina 返回的 Markdown 中提取正文（去掉网站导航等噪音）"""
        lines = markdown_text.split("\n")
        content_lines = []
        in_header = True
        nav_keywords = ["搜索", "登录", "关注", "推荐", "视频", "财经", "科技",
                        "消息", "发布", "首页", "无障碍", "下载客户端"]

        for line in lines:
            stripped = line.strip()

            # 跳过 Jina 元数据头部
            if stripped.startswith("Title:") or stripped.startswith("URL Source:") or stripped.startswith("Published Time:") or stripped.startswith("Markdown Content:"):
                in_header = True
                continue

            # 跳过导航类内容
            if in_header and any(kw in stripped for kw in nav_keywords) and len(stripped) < 30:
                continue

            # 遇到真正的标题或内容开始
            if stripped.startswith("# ") and not any(kw in stripped for kw in nav_keywords):
                in_header = False

            if not in_header and stripped:
                content_lines.append(stripped)

        text = "\n".join(content_lines)
        # 去掉开头的导航噪音
        text = re.sub(r'^\s*\*\s+.*?\n', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()

        # 去掉尾部噪音（举报/登录/评论等）
        text = re.sub(r'\n(举报|登录|评论 \d+|请先.*?登录).*$', '', text, flags=re.MULTILINE)
        text = re.sub(r'\[!\[Image.*?\n', '', text)
        text = re.sub(r'\!\[Image[^\]]*\]\([^)]+\)\n?', '', text)

        return text

    def fetch_article_content(self, item):
        """抓取单篇文章全文（优先 Jina，失败回退直接抓取）"""
        url = item.get("url", "")
        if not url:
            return None

        print(f"    抓取: {item['title'][:40]}...", end=" ", flush=True)

        content = None
        title = item["title"]

        # 策略1：Jina Reader（穿透 JS 渲染）
        jina_md = self.fetch_via_jina(url)
        if jina_md and len(jina_md) > 200:
            content = self.extract_jina_content(jina_md)
            if content and len(content) > 200:
                # 提取标题
                for line in jina_md.split("\n"):
                    if line.startswith("Title:") and "安全验证" not in line:
                        t = line[6:].strip()
                        if t and len(t) > 2:
                            title = t
                            break

                print(f"✅ Jina {len(content)}字")
                item["title"] = title
                item["content"] = content[:20000]  # 限制长度
                item["content_length"] = len(content)
                item["fetch_status"] = "full"
                return item

        # 策略2：直接抓取 HTML（回退）
        html = self.fetch_url(url, timeout=15)
        if html and len(html) > 500:
            content = self.extract_text(html, item.get("source", ""))
            extracted_title = self.extract_title(html)
            if extracted_title:
                title = extracted_title

            if content and len(content) > 200:
                print(f"✅ 直接 {len(content)}字")
                item["title"] = title
                item["content"] = content[:20000]
                item["content_length"] = len(content)
                item["fetch_status"] = "full"
                return item

        # 策略3：用 Jina 片段或 HTML 片段
        if jina_md:
            content = jina_md[:1000]
            print(f"⚠️ 片段({len(content)}字)")
        elif html:
            content = self.extract_text(html, item.get("source", ""))[:500]
            print(f"⚠️ 截断({len(content)}字)")
        else:
            print("❌ 失败")
            return None

        item["title"] = title
        item["content"] = content
        item["content_length"] = len(content)
        item["fetch_status"] = "partial"
        return item

    # ─── 主流程 ─────────────────────────────────────────

    def run(self):
        """主抓取流程"""
        print(f"\n{'='*60}")
        print(f"📰 爆文素材抓取引擎 v1.0")
        print(f"   日期：{self.today} | 目标：{self.limit}篇+")
        print(f"{'='*60}\n")

        # 阶段1：发现文章
        print("🔍 阶段1：多源发现影视相关文章...\n")
        discovered = []

        # 并行发现
        discovered += self.fetch_zhihu_hot()
        discovered += self.fetch_douban_movie()
        discovered += self.fetch_baidu_hot()
        discovered += self.fetch_thepaper_ent()
        discovered += self.fetch_toutiao_search()
        discovered += self.google_search_articles()

        print(f"\n   共发现 {len(discovered)} 个候选条目\n")

        if len(discovered) == 0:
            print("❌ 未发现任何影视相关文章，请检查网络或关键词配置")
            return

        # 阶段2：抓取全文
        print("📥 阶段2：逐篇抓取全文...\n")
        success_count = 0
        for item in discovered[:self.limit * 2]:  # 多取一些，因为有些会失败
            if success_count >= self.limit:
                break

            result = self.fetch_article_content(item)
            if result and result.get("content_length", 0) >= 200:
                self.articles.append(result)
                success_count += 1

            time.sleep(1.5)  # 礼貌间隔

        print(f"\n📊 抓取完成：{success_count} 篇成功 / {len(discovered)} 个候选")

        # 阶段3：保存
        if not self.dry_run and self.articles:
            self.save_articles()
            self.update_index()

        print(f"\n💡 进化小组可以开始分析今天的新素材了！")

    def save_articles(self):
        """保存文章到结构化存储"""
        daily_dir = DAILY_DIR_TEMPLATE.format(date=self.today)
        os.makedirs(daily_dir, exist_ok=True)

        # 1. 保存每篇文章为独立MD文件
        for i, article in enumerate(self.articles):
            safe_title = re.sub(r'[\\/:*?"<>|]', '_', article['title'][:50])
            filename = f"{i+1:03d}-{safe_title}.md"
            filepath = os.path.join(daily_dir, filename)

            md = self._format_article_md(article, i + 1)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(md)

        # 2. 保存JSON元数据
        json_path = os.path.join(daily_dir, "metadata.json")
        meta = {
            "date": self.today,
            "fetched_at": datetime.now(TZ).isoformat(),
            "total": len(self.articles),
            "sources": {},
        }
        for a in self.articles:
            source = a.get("source_name", "unknown")
            meta["sources"][source] = meta["sources"].get(source, 0) + 1

        # 去除正文后再存JSON（正文太大，在MD里）
        light_articles = []
        for a in self.articles:
            light = {k: v for k, v in a.items() if k != "content"}
            light["content_preview"] = a.get("content", "")[:200]
            light_articles.append(light)

        meta["articles"] = light_articles
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        print(f"\n💾 已保存 {len(self.articles)} 篇文章 → {daily_dir}/")

    def update_index(self):
        """更新总索引"""
        if os.path.exists(INDEX_FILE):
            with open(INDEX_FILE) as f:
                index = json.load(f)
        else:
            index = {"version": "1.0", "total_articles": 0, "daily": {}}

        daily_count = len(self.articles)
        index["daily"][self.today] = {
            "count": daily_count,
            "fetched_at": datetime.now(TZ).isoformat(),
            "dir": DAILY_DIR_TEMPLATE.format(date=self.today),
        }
        index["total_articles"] = sum(d["count"] for d in index["daily"].values())
        index["last_updated"] = datetime.now(TZ).isoformat()

        os.makedirs(CORPUS_DIR, exist_ok=True)
        with open(INDEX_FILE, "w") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

    def _format_article_md(self, article, num):
        """格式化单篇文章为Markdown"""
        lines = []
        lines.append(f"# [{num}] {article['title']}")
        lines.append("")
        lines.append(f"- **来源**：{article.get('source_name', '')}")
        lines.append(f"- **链接**：{article.get('url', '')}")
        lines.append(f"- **热度**：{article.get('hot', '')}")
        lines.append(f"- **抓取时间**：{article.get('discovered_at', '')}")
        lines.append(f"- **字数**：{article.get('content_length', 0)}")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## 正文")
        lines.append("")
        lines.append(article.get("content", "(无内容)"))

        # 进化小组分析区
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## 🧬 进化小组分析区")
        lines.append("")
        lines.append("### 🔥 热点猎手")
        lines.append("- 传播路径：")
        lines.append("- 情绪触发点：")
        lines.append("- 信息源追溯：")
        lines.append("")
        lines.append("### 📋 选题策划")
        lines.append("- 选题角度：")
        lines.append("- 标题公式：")
        lines.append("- 分享动机：")
        lines.append("- 差异化空间：")
        lines.append("")
        lines.append("### ✍️ 封不住")
        lines.append("- 开头钩子类型：")
        lines.append("- 叙事结构：")
        lines.append("- 金句摘录：")
        lines.append("- 可复用技巧：")
        lines.append("")

        return "\n".join(lines)


# ─── CLI入口 ────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="爆文素材抓取引擎")
    parser.add_argument("--limit", type=int, default=50, help="目标文章数（默认50）")
    parser.add_argument("--source", default="all",
                        help="数据源：zhihu,douban,baidu,thepaper,toutiao,google,all")
    parser.add_argument("--dry-run", action="store_true", help="只发现不抓取全文")
    args = parser.parse_args()

    fetcher = ArticleFetcher(limit=args.limit, dry_run=args.dry_run)

    # 如果指定了单个源，跑对应的
    if args.source != "all":
        source_map = {
            "zhihu": fetcher.fetch_zhihu_hot,
            "douban": fetcher.fetch_douban_movie,
            "baidu": fetcher.fetch_baidu_hot,
            "thepaper": fetcher.fetch_thepaper_ent,
            "toutiao": fetcher.fetch_toutiao_search,
            "google": fetcher.google_search_articles,
        }
        if args.source in source_map:
            discovered = source_map[args.source]()
            print(f"\n发现 {len(discovered)} 条")
            if not args.dry_run:
                for item in discovered[:args.limit]:
                    fetcher.fetch_article_content(item)
                    time.sleep(1.5)
                if fetcher.articles:
                    fetcher.save_articles()
                    fetcher.update_index()
        else:
            print(f"未知数据源: {args.source}")
            print(f"可用: {list(source_map.keys())}")
    else:
        fetcher.run()


if __name__ == "__main__":
    main()
