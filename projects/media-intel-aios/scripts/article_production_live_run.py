#!/usr/bin/env python3
"""Repeatable Film/TV article production runner with source-role quality gates.

Scope:
- market/heat sources can discover and support data claims, but cannot be main narrative sources
- self-media candidate output requires enough narrative source roles
- focused/ad-hoc verification only; never claims canonical suite green
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:
    import film_tv_maoyan_observation as maoyan  # noqa: E402
except ModuleNotFoundError:
    maoyan = None  # type: ignore[assignment]

try:
    import guduo_fetch as guduo  # noqa: E402
except ModuleNotFoundError:
    guduo = None  # type: ignore[assignment]

RUNNER_VERSION = "0.3.4"
DEFAULT_OUTPUT_BASE = ROOT / "outputs" / "article_production"
DOUBAN_LIVE_SEARCH_URL = "https://movie.douban.com/j/search_subjects?type=movie&tag={tag}&sort=recommend&page_limit=3&page_start=0"
DOUBAN_SUBJECT_ABSTRACT_URL = "https://movie.douban.com/j/subject_abstract?subject_id={subject_id}"
WEIBO_HOTSEARCH_URL = "https://weibo.com/ajax/side/hotSearch"
WEIBO_TOPIC_SEARCH_URL = "https://weibo.com/ajax/search/all?containerid=100103type%3D1%26q%3D{query}"
ZHIHU_HOT_LIST_URL = "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=20&desktop=true"
BILIBILI_MOVIE_ZONE_HOT_URL = "https://api.bilibili.com/x/web-interface/ranking/v2?rid=23&type=all"
XIAOHONGSHU_MOVIE_NOTES_SEARCH_URL = "https://edith.xiaohongshu.com/api/sns/web/v1/search/notes"
DOUYIN_MOVIE_HOT_URL = "https://www.douyin.com/aweme/v1/web/hot/search/list/"
DATA_OBSERVATION_LANE = "data_observation"
SELF_MEDIA_CANDIDATE_LANE = "self_media_production_candidate"
SUPPORT_SIGNAL_ROLES = {"market_signal", "heat_signal"}
SOURCE_BUCKETS_BY_SIGNAL_ROLE = {
    "market_results": "market_signal",
    "heat_results": "heat_signal",
    "article_body_results": "article_body_signal",
    "audience_reaction_results": "audience_reaction_signal",
    "social_results": "social_discussion_signal",
    "box_office_results": "box_office_signal",
    "industry_results": "industry_signal",
    "news_results": "news_signal",
    "media_results": "media_signal",
}
SOURCE_BUCKET_BY_SIGNAL_ROLE = {signal_role: bucket for bucket, signal_role in SOURCE_BUCKETS_BY_SIGNAL_ROLE.items()}
SELF_MEDIA_NARRATIVE_SOURCE_ROLES = {
    "audience_sentiment",
    "social_discussion",
    "review_comments",
    "hot_search",
    "plot_character_context",
}
MIN_SELF_MEDIA_NARRATIVE_ROLES = 2

PRIORITY_SOURCE_ORDER = [
    "douban_movie_reviews",
    "douban_tv_reviews",
    "weibo_entertainment_hotsearch",
    "weibo_topic_search",
    "zhihu_movie_hot_topics",
    "bilibili_movie_zone_hot",
    "xiaohongshu_movie_notes",
    "douyin_movie_hot",
    "toutiao_entertainment_hot",
    "baidu_hot_search_entertainment",
    "1905_movie_news",
    "mtime_movie_news",
    "sir_movie",
    "dumuzhi",
    "yulezibenlun",
    "yingshidushe",
]
PRIORITY_SOURCE_ALIASES = {
    "毒眸": "dumuzhi",
    "娱乐资本论": "yulezibenlun",
    "影视独舌": "yingshidushe",
    "dumuzhi / 毒眸": "dumuzhi",
    "yulezibenlun / 娱乐资本论": "yulezibenlun",
    "yingshidushe / 影视独舌": "yingshidushe",
}


def _planned_source(source_id: str, priority: str, roles: list[str], allowed_use: list[str], *, auxiliary: bool = False) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "priority": priority,
        "narrative_roles": roles,
        "allowed_use": allowed_use,
        "production_boundary": ("planned auxiliary source; not live-verified in this runner" if auxiliary else "planned source; not live-verified in this runner"),
        "status": "planned_not_live_verified",
    }


PRIORITY_SOURCE_REGISTRY = {
    "douban_movie_reviews": _planned_source("douban_movie_reviews", "P0", ["review_comments", "audience_sentiment"], ["movie review/comment signal", "audience sentiment extraction"]),
    "douban_tv_reviews": _planned_source("douban_tv_reviews", "P0", ["review_comments", "audience_sentiment"], ["tv review/comment signal", "audience sentiment extraction"]),
    "weibo_entertainment_hotsearch": _planned_source("weibo_entertainment_hotsearch", "P0", ["hot_search", "social_discussion"], ["entertainment hot-search discovery", "social discussion signal"]),
    "weibo_topic_search": _planned_source("weibo_topic_search", "P0", ["social_discussion", "hot_search"], ["topic search discovery", "social discussion signal"]),
    "zhihu_movie_hot_topics": _planned_source("zhihu_movie_hot_topics", "P0", ["social_discussion", "audience_sentiment"], ["movie hot-topic discovery", "question/argument signal"]),
    "bilibili_movie_zone_hot": _planned_source("bilibili_movie_zone_hot", "P0", ["hot_search", "social_discussion"], ["movie-zone hot item discovery", "social discussion signal"]),
    "xiaohongshu_movie_notes": _planned_source("xiaohongshu_movie_notes", "P1", ["audience_sentiment", "social_discussion"], ["movie note sentiment", "social discussion signal"]),
    "douyin_movie_hot": _planned_source("douyin_movie_hot", "P1", ["hot_search", "social_discussion"], ["short-video movie hot discovery", "social discussion signal"]),
    "toutiao_entertainment_hot": _planned_source("toutiao_entertainment_hot", "P1", ["hot_search", "social_discussion"], ["entertainment hot discovery", "discussion signal"]),
    "baidu_hot_search_entertainment": _planned_source("baidu_hot_search_entertainment", "P1", ["hot_search"], ["entertainment hot-search discovery"]),
    "1905_movie_news": _planned_source("1905_movie_news", "P2", ["plot_character_context"], ["movie news context", "plot/character context support"], auxiliary=True),
    "mtime_movie_news": _planned_source("mtime_movie_news", "P2", ["plot_character_context"], ["movie news context", "plot/character context support"], auxiliary=True),
    "sir_movie": _planned_source("sir_movie", "P2", ["plot_character_context", "review_comments"], ["article context signal", "review/comment signal"], auxiliary=True),
    "dumuzhi": _planned_source("dumuzhi", "P2", ["plot_character_context"], ["industry article context", "angle/background support"], auxiliary=True),
    "yulezibenlun": _planned_source("yulezibenlun", "P2", ["plot_character_context"], ["industry article context", "angle/background support"], auxiliary=True),
    "yingshidushe": _planned_source("yingshidushe", "P2", ["plot_character_context"], ["industry article context", "angle/background support"], auxiliary=True),
}

VERIFIED_SOURCE_POOL = {
    "maoyan_realtime_boxoffice": {
        "source_id": "maoyan_realtime_boxoffice",
        "source_name": "猫眼专业版实时票房",
        "role": "P0_market_data",
        "signal_role": "market_signal",
        "narrative_roles": [],
        "allowed_use": ["candidate_discovery", "boxoffice_data_support"],
        "can_be_main_narrative_source": False,
        "live_fetch_allowed": True,
        "production_eligible": True,
    },
    "guduo": {
        "source_id": "guduo",
        "source_name": "骨朵热度指数",
        "role": "P1_heat_rank",
        "signal_role": "heat_signal",
        "narrative_roles": [],
        "allowed_use": ["heat_discovery", "heat_data_support"],
        "can_be_main_narrative_source": False,
        "live_fetch_allowed": True,
        "production_eligible": True,
    },
    "toutiao_deep_film_tv_articles": {
        "source_id": "toutiao_deep_film_tv_articles",
        "source_name": "头条深度影视文章样本",
        "role": "P1A_article_body_pattern",
        "signal_role": "article_body_signal",
        "narrative_roles": ["plot_character_context"],
        "allowed_use": ["article_structure_signal", "plot_character_context", "angle_pattern_support"],
        "can_be_main_narrative_source": True,
        "live_fetch_allowed": False,
        "production_eligible": True,
        "verification_status": "focused_verifier_passed",
    },
    "douban_reviews_discussions": {
        "source_id": "douban_reviews_discussions",
        "source_name": "豆瓣短评/讨论 live signal",
        "role": "P1C_audience_reaction",
        "signal_role": "audience_reaction_signal",
        "narrative_roles": ["audience_sentiment", "review_comments", "social_discussion"],
        "allowed_use": ["audience_sentiment", "review_comments", "social_discussion"],
        "can_be_main_narrative_source": True,
        "live_fetch_allowed": True,
        "production_eligible": True,
        "verification_status": "focused_live_verified_when_available",
    },
    "weibo_entertainment_hotsearch": {
        "source_id": "weibo_entertainment_hotsearch",
        "source_name": "微博文娱热搜 live signal",
        "role": "P0_social_hotsearch",
        "signal_role": "social_discussion_signal",
        "narrative_roles": ["hot_search", "social_discussion"],
        "allowed_use": ["entertainment hot-search discovery", "social discussion signal"],
        "can_be_main_narrative_source": True,
        "live_fetch_allowed": True,
        "production_eligible": True,
        "verification_status": "focused_live_verified_when_available",
    },
    "weibo_topic_search": {
        "source_id": "weibo_topic_search",
        "source_name": "微博话题搜索 live signal",
        "role": "P0_social_topic_search",
        "signal_role": "social_discussion_signal",
        "narrative_roles": ["social_discussion", "hot_search"],
        "allowed_use": ["topic search discovery", "social discussion signal"],
        "can_be_main_narrative_source": True,
        "live_fetch_allowed": True,
        "production_eligible": True,
        "verification_status": "live_inaccessible_safe_failure_when_login_required",
    },
    "zhihu_movie_hot_topics": {
        "source_id": "zhihu_movie_hot_topics",
        "source_name": "知乎影视热议话题 live signal",
        "role": "P0_zhihu_movie_hot_topics",
        "signal_role": "social_discussion_signal",
        "narrative_roles": ["social_discussion", "audience_sentiment"],
        "allowed_use": ["movie hot-topic discovery", "question/argument signal"],
        "can_be_main_narrative_source": True,
        "live_fetch_allowed": True,
        "production_eligible": True,
        "verification_status": "live_inaccessible_safe_failure_when_auth_required",
    },
    "bilibili_movie_zone_hot": {
        "source_id": "bilibili_movie_zone_hot",
        "source_name": "B站电影分区热门 live signal",
        "role": "P0_bilibili_movie_zone_hot",
        "signal_role": "social_discussion_signal",
        "narrative_roles": ["hot_search", "social_discussion"],
        "allowed_use": ["movie-zone hot item discovery", "social discussion signal"],
        "can_be_main_narrative_source": True,
        "live_fetch_allowed": True,
        "production_eligible": True,
        "verification_status": "live_inaccessible_safe_failure_when_access_denied",
    },
    "douyin_movie_hot": {
        "source_id": "douyin_movie_hot",
        "source_name": "抖音电影热点 live signal",
        "role": "P1_douyin_movie_hot",
        "signal_role": "social_discussion_signal",
        "narrative_roles": ["hot_search", "social_discussion"],
        "allowed_use": ["short-video movie hot discovery", "social discussion signal"],
        "can_be_main_narrative_source": True,
        "live_fetch_allowed": True,
        "production_eligible": True,
        "verification_status": "live_inaccessible_safe_failure_when_login_or_signature_required",
    },
    "xiaohongshu_movie_notes": {
        "source_id": "xiaohongshu_movie_notes",
        "source_name": "小红书影视笔记搜索 live signal",
        "role": "P1_xiaohongshu_movie_notes",
        "signal_role": "audience_reaction_signal",
        "narrative_roles": ["audience_sentiment", "social_discussion"],
        "allowed_use": ["movie note sentiment", "audience reaction signal"],
        "can_be_main_narrative_source": True,
        "live_fetch_allowed": True,
        "production_eligible": True,
        "verification_status": "live_inaccessible_safe_failure_when_login_or_signature_required",
    },
}



def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def run_id_from_now() -> str:
    return datetime.now().strftime("article_production_%Y%m%d_%H%M%S")


def json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def text_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _source_meta(source_id: str) -> dict[str, Any]:
    spec = VERIFIED_SOURCE_POOL[source_id]
    return {
        "source_id": source_id,
        "source_name": spec["source_name"],
        "role": spec["role"],
        "signal_role": spec["signal_role"],
        "narrative_roles": spec.get("narrative_roles", []),
        "allowed_use": spec.get("allowed_use", []),
        "can_be_main_narrative_source": spec.get("can_be_main_narrative_source", False),
    }


def _fetch_json_url(url: str, timeout: int = 12, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://movie.douban.com/",
    }
    if headers:
        request_headers.update(headers)
    request = Request(url, headers=request_headers)
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset, errors="replace"))


def _extract_douban_subject_id(subject: dict[str, Any]) -> str | None:
    subject_id = subject.get("id")
    if subject_id:
        return str(subject_id)
    match = re.search(r"/subject/(\d+)/", str(subject.get("url") or ""))
    return match.group(1) if match else None


def _normalize_douban_comment(text: Any, max_chars: int = 260) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    return cleaned[:max_chars]


def _sentiment_keyword_from_rating(rate: Any) -> str:
    try:
        score = float(rate)
    except (TypeError, ValueError):
        return "sentiment_unknown"
    if score >= 7.5:
        return "positive_or_recommended"
    if score >= 6.0:
        return "mixed_to_positive"
    if score > 0:
        return "mixed_or_negative"
    return "sentiment_unknown"


def _weibo_hot_item_to_signal(item: dict[str, Any]) -> dict[str, Any]:
    word = str(item.get("word") or item.get("note") or item.get("word_scheme") or "").strip()
    return {
        "word": word,
        "note": str(item.get("note") or word),
        "rank": item.get("realpos") if item.get("realpos") is not None else item.get("rank"),
        "heat": item.get("num"),
        "flag_desc": str(item.get("flag_desc") or item.get("label_name") or item.get("icon_desc") or ""),
        "topic_flag": item.get("topic_flag"),
        "url": f"https://s.weibo.com/weibo?q={quote(word)}" if word else None,
    }


def fetch_weibo_entertainment_hotsearch_signal() -> dict[str, Any]:
    timer = time.perf_counter()
    started_at = now_utc()
    source_id = "weibo_entertainment_hotsearch"
    try:
        payload = _fetch_json_url(WEIBO_HOTSEARCH_URL, headers={"Referer": "https://weibo.com/"})
        rows = (payload.get("data") or {}).get("realtime") or []
        if not rows:
            raise ValueError("weibo hotsearch returned no realtime rows")
        signals = [_weibo_hot_item_to_signal(row) for row in rows if isinstance(row, dict)]
        signals = [signal for signal in signals if signal.get("word")]
        if not signals:
            raise ValueError("weibo hotsearch returned no usable topic words")
        top_signals = signals[:5]
        sample_signals = [
            f"微博热搜话题：{item['word']}（heat={item.get('heat')}, flag={item.get('flag_desc') or 'none'}）"
            for item in top_signals[:3]
        ]
        return {
            **_source_meta(source_id),
            "fetch_path": "direct_live",
            "started_at": started_at,
            "finished_at": now_utc(),
            "duration_ms": elapsed_ms(timer),
            "success": True,
            "status": "focused_live_verified",
            "raw_url": WEIBO_HOTSEARCH_URL,
            "fields_extracted": ["word", "rank", "heat", "flag_desc", "topic_flag", "url"],
            "signal_allowed_use_detail": ["hot-search topic discovery", "social discussion signal extraction", "attention pressure extraction"],
            "forbidden_use": ["verified_facts", "whole-network generalization", "single-topic conclusion", "publish-ready evidence"],
            "structured_signals": {
                "hot_search": top_signals,
                "social_discussion": [item["word"] for item in top_signals],
            },
            "sample_signals": sample_signals,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            **_source_meta(source_id),
            "fetch_path": "direct_live",
            "started_at": started_at,
            "finished_at": now_utc(),
            "duration_ms": elapsed_ms(timer),
            "success": False,
            "status": "ERROR",
            "raw_url": WEIBO_HOTSEARCH_URL,
            "fields_extracted": [],
            "signal_allowed_use_detail": ["hot-search topic discovery", "social discussion signal extraction", "attention pressure extraction"],
            "forbidden_use": ["verified_facts", "whole-network generalization", "single-topic conclusion", "publish-ready evidence"],
            "sample_signals": [],
            "error": repr(exc),
        }


def fetch_weibo_topic_search_signal() -> dict[str, Any]:
    timer = time.perf_counter()
    started_at = now_utc()
    source_id = "weibo_topic_search"
    query = "影视"
    url = WEIBO_TOPIC_SEARCH_URL.format(query=quote(query))
    try:
        payload = _fetch_json_url(url, headers={"Referer": "https://weibo.com/"})
        if payload.get("ok") == -100 or "login.php" in str(payload.get("url") or ""):
            raise PermissionError("weibo topic search requires login or visitor verification")
        cards = (payload.get("data") or {}).get("cards") or []
        signals: list[dict[str, Any]] = []
        for card in cards:
            mblog = card.get("mblog") if isinstance(card, dict) else None
            if not isinstance(mblog, dict):
                continue
            text = re.sub(r"<[^>]+>", "", str(mblog.get("text") or "")).replace("\u200b", "").strip()
            if not text:
                continue
            signals.append({
                "word": text[:80],
                "rank": len(signals) + 1,
                "heat": mblog.get("attitudes_count"),
                "comment_count": mblog.get("comments_count"),
                "share_count": mblog.get("reposts_count"),
                "url": f"https://m.weibo.cn/detail/{mblog.get('id')}" if mblog.get("id") else url,
            })
        if not signals:
            raise ValueError("weibo topic search returned no usable topic rows")
        top_signals = signals[:5]
        return {
            **_source_meta(source_id),
            "fetch_path": "direct_live",
            "started_at": started_at,
            "finished_at": now_utc(),
            "duration_ms": elapsed_ms(timer),
            "success": True,
            "status": "focused_live_verified",
            "raw_url": url,
            "fields_extracted": ["word", "rank", "heat", "comment_count", "share_count", "url"],
            "signal_allowed_use_detail": ["topic search discovery", "social discussion signal extraction"],
            "forbidden_use": ["verified_facts", "whole-network generalization", "single-topic conclusion", "publish-ready evidence"],
            "structured_signals": {
                "topic_search": top_signals,
                "social_discussion": [item["word"] for item in top_signals],
            },
            "sample_signals": [f"微博话题搜索：{item['word']}" for item in top_signals[:3]],
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        status = "live_inaccessible" if isinstance(exc, PermissionError) else "ERROR"
        return {
            **_source_meta(source_id),
            "fetch_path": "direct_live",
            "started_at": started_at,
            "finished_at": now_utc(),
            "duration_ms": elapsed_ms(timer),
            "success": False,
            "status": status,
            "raw_url": url,
            "fields_extracted": [],
            "signal_allowed_use_detail": ["topic search discovery", "social discussion signal extraction"],
            "forbidden_use": ["verified_facts", "whole-network generalization", "single-topic conclusion", "publish-ready evidence"],
            "sample_signals": [],
            "error": repr(exc),
        }


def fetch_zhihu_movie_hot_topics_signal() -> dict[str, Any]:
    timer = time.perf_counter()
    started_at = now_utc()
    source_id = "zhihu_movie_hot_topics"
    try:
        payload = _fetch_json_url(
            ZHIHU_HOT_LIST_URL,
            headers={
                "Referer": "https://www.zhihu.com/",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        rows = payload.get("data") or []
        signals: list[dict[str, Any]] = []
        movie_terms = ("电影", "影视", "剧", "演员", "导演", "票房", "院线", "角色", "综艺")
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            target_raw = row.get("target")
            target = target_raw if isinstance(target_raw, dict) else row
            title = str(target.get("title") or row.get("title") or "").strip()
            excerpt = str(target.get("excerpt") or target.get("detail_text") or row.get("detail_text") or "").strip()
            url = str(target.get("url") or row.get("url") or "").strip()
            heat = row.get("detail_text") or row.get("heat") or target.get("answer_count")
            merged = f"{title}\n{excerpt}"
            if not title or not any(term in merged for term in movie_terms):
                continue
            signals.append({
                "title": title[:120],
                "rank": index,
                "heat": heat,
                "url": url,
                "excerpt": excerpt[:180],
            })
            if len(signals) >= 5:
                break
        if not signals:
            raise ValueError("zhihu hot list returned no usable movie/topic rows")
        return {
            **_source_meta(source_id),
            "fetch_path": "direct_live",
            "started_at": started_at,
            "finished_at": now_utc(),
            "duration_ms": elapsed_ms(timer),
            "success": True,
            "status": "focused_live_verified",
            "raw_url": ZHIHU_HOT_LIST_URL,
            "fields_extracted": ["title", "rank", "heat", "url", "excerpt"],
            "signal_allowed_use_detail": ["movie hot-topic discovery", "question/argument signal extraction"],
            "forbidden_use": ["verified_facts", "whole-network generalization", "single-topic conclusion", "publish-ready evidence"],
            "structured_signals": {
                "hot_topics": signals,
                "social_discussion": [item["title"] for item in signals],
            },
            "sample_signals": [f"知乎热议：{item['title']}" for item in signals[:3]],
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        error_text = repr(exc)
        status = "live_inaccessible" if "401" in error_text or "403" in error_text or "Authorization" in error_text or "Forbidden" in error_text else "ERROR"
        return {
            **_source_meta(source_id),
            "fetch_path": "direct_live",
            "started_at": started_at,
            "finished_at": now_utc(),
            "duration_ms": elapsed_ms(timer),
            "success": False,
            "status": status,
            "raw_url": ZHIHU_HOT_LIST_URL,
            "fields_extracted": [],
            "signal_allowed_use_detail": ["movie hot-topic discovery", "question/argument signal extraction"],
            "forbidden_use": ["verified_facts", "whole-network generalization", "single-topic conclusion", "publish-ready evidence"],
            "sample_signals": [],
            "error": error_text,
        }


def fetch_bilibili_movie_zone_hot_signal() -> dict[str, Any]:
    timer = time.perf_counter()
    started_at = now_utc()
    source_id = "bilibili_movie_zone_hot"
    try:
        payload = _fetch_json_url(
            BILIBILI_MOVIE_ZONE_HOT_URL,
            headers={
                "Referer": "https://www.bilibili.com/v/movie/",
                "Origin": "https://www.bilibili.com",
            },
        )
        if payload.get("code") not in (0, None):
            raise PermissionError(f"bilibili ranking returned code={payload.get('code')}: {payload.get('message')}")
        rows = ((payload.get("data") or {}).get("list") or []) if isinstance(payload, dict) else []
        signals: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            if not title:
                continue
            owner = row.get("owner")
            if not isinstance(owner, dict):
                owner = {}
            stat = row.get("stat")
            if not isinstance(stat, dict):
                stat = {}
            bvid = str(row.get("bvid") or "").strip()
            signals.append({
                "title": title[:120],
                "rank": index,
                "heat": stat.get("view"),
                "danmaku": stat.get("danmaku"),
                "like": stat.get("like"),
                "owner": str(owner.get("name") or "").strip(),
                "url": f"https://www.bilibili.com/video/{bvid}" if bvid else None,
            })
            if len(signals) >= 5:
                break
        if not signals:
            raise ValueError("bilibili movie ranking returned no usable hot rows")
        return {
            **_source_meta(source_id),
            "fetch_path": "direct_live",
            "started_at": started_at,
            "finished_at": now_utc(),
            "duration_ms": elapsed_ms(timer),
            "success": True,
            "status": "focused_live_verified",
            "raw_url": BILIBILI_MOVIE_ZONE_HOT_URL,
            "fields_extracted": ["title", "rank", "heat", "danmaku", "like", "owner", "url"],
            "signal_allowed_use_detail": ["movie-zone hot item discovery", "social discussion signal extraction", "video engagement signal extraction"],
            "forbidden_use": ["verified_facts", "whole-network generalization", "single-video conclusion", "publish-ready evidence"],
            "structured_signals": {
                "hot_items": signals,
                "social_discussion": [item["title"] for item in signals],
            },
            "sample_signals": [f"B站电影区热门：{item['title']}（播放={item.get('heat')}）" for item in signals[:3]],
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        error_text = repr(exc)
        inaccessible_markers = ("401", "403", "412", "-352", "login", "forbidden", "risk", "access")
        status = "live_inaccessible" if any(marker in error_text.lower() for marker in inaccessible_markers) else "ERROR"
        return {
            **_source_meta(source_id),
            "fetch_path": "direct_live",
            "started_at": started_at,
            "finished_at": now_utc(),
            "duration_ms": elapsed_ms(timer),
            "success": False,
            "status": status,
            "raw_url": BILIBILI_MOVIE_ZONE_HOT_URL,
            "fields_extracted": [],
            "signal_allowed_use_detail": ["movie-zone hot item discovery", "social discussion signal extraction", "video engagement signal extraction"],
            "forbidden_use": ["verified_facts", "whole-network generalization", "single-video conclusion", "publish-ready evidence"],
            "sample_signals": [],
            "error": error_text,
        }


def fetch_xiaohongshu_movie_notes_signal() -> dict[str, Any]:
    timer = time.perf_counter()
    started_at = now_utc()
    source_id = "xiaohongshu_movie_notes"
    query = "影视"
    try:
        payload = _fetch_json_url(
            XIAOHONGSHU_MOVIE_NOTES_SEARCH_URL,
            headers={
                "Referer": "https://www.xiaohongshu.com/",
                "Origin": "https://www.xiaohongshu.com",
                "X-S":"",
                "X-T":"",
            },
        )
        code = payload.get("code")
        if code not in (0, None) or payload.get("success") is False:
            raise PermissionError(f"xiaohongshu search returned code={code}: {payload.get('msg') or payload.get('message')}")
        rows = (((payload.get("data") or {}).get("items") or []) if isinstance(payload, dict) else [])
        signals: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            note_raw = row.get("note_card")
            note = note_raw if isinstance(note_raw, dict) else row
            title = str(note.get("display_title") or note.get("title") or "").strip()
            desc = str(note.get("desc") or note.get("description") or "").strip()
            if not title:
                continue
            interaction = note.get("interact_info") if isinstance(note.get("interact_info"), dict) else {}
            note_id = str(row.get("id") or note.get("note_id") or "").strip()
            signals.append({
                "title": title[:120],
                "rank": index,
                "desc": desc[:180],
                "like_count": interaction.get("liked_count") or interaction.get("like_count"),
                "url": f"https://www.xiaohongshu.com/explore/{note_id}" if note_id else None,
            })
            if len(signals) >= 5:
                break
        if not signals:
            raise ValueError("xiaohongshu search returned no usable movie note rows")
        return {
            **_source_meta(source_id),
            "fetch_path": "direct_live",
            "started_at": started_at,
            "finished_at": now_utc(),
            "duration_ms": elapsed_ms(timer),
            "success": True,
            "status": "focused_live_verified",
            "raw_url": XIAOHONGSHU_MOVIE_NOTES_SEARCH_URL,
            "query": query,
            "fields_extracted": ["title", "rank", "desc", "like_count", "url"],
            "signal_allowed_use_detail": ["movie note sentiment", "social discussion signal extraction", "note engagement signal extraction"],
            "forbidden_use": ["verified_facts", "whole-network generalization", "single-note conclusion", "publish-ready evidence"],
            "structured_signals": {
                "note_items": signals,
                "audience_reaction": [item["title"] for item in signals],
            },
            "sample_signals": [f"小红书影视笔记：{item['title']}" for item in signals[:3]],
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        error_text = repr(exc)
        inaccessible_markers = ("401", "403", "-101", "login", "登录", "forbidden", "risk", "sign", "signature", "x-s", "x-t")
        status = "live_inaccessible" if any(marker in error_text.lower() for marker in inaccessible_markers) else "ERROR"
        return {
            **_source_meta(source_id),
            "fetch_path": "direct_live",
            "started_at": started_at,
            "finished_at": now_utc(),
            "duration_ms": elapsed_ms(timer),
            "success": False,
            "status": status,
            "raw_url": XIAOHONGSHU_MOVIE_NOTES_SEARCH_URL,
            "query": query,
            "fields_extracted": [],
            "signal_allowed_use_detail": ["movie note sentiment", "social discussion signal extraction", "note engagement signal extraction"],
            "forbidden_use": ["verified_facts", "whole-network generalization", "single-note conclusion", "publish-ready evidence"],
            "sample_signals": [],
            "error": error_text,
        }


def fetch_douyin_movie_hot_signal() -> dict[str, Any]:
    timer = time.perf_counter()
    started_at = now_utc()
    source_id = "douyin_movie_hot"
    try:
        payload = _fetch_json_url(
            DOUYIN_MOVIE_HOT_URL,
            headers={
                "Referer": "https://www.douyin.com/",
                "Origin": "https://www.douyin.com",
            },
        )
        code = payload.get("status_code", payload.get("code"))
        if code not in (0, None) or payload.get("success") is False:
            raise PermissionError(f"douyin hot search returned code={code}: {payload.get('status_msg') or payload.get('message') or payload.get('msg')}")
        rows: list[Any] = []
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict):
            rows = data.get("word_list") or data.get("list") or data.get("items") or []
        elif isinstance(data, list):
            rows = data
        signals: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            word = str(row.get("word") or row.get("sentence") or row.get("title") or row.get("aweme_title") or "").strip()
            if not word:
                continue
            signals.append({
                "title": word[:120],
                "rank": row.get("position") or row.get("rank") or index,
                "heat": row.get("hot_value") or row.get("view_count") or row.get("heat"),
                "video_count": row.get("video_count") or row.get("aweme_count"),
                "url": f"https://www.douyin.com/search/{quote(word)}",
            })
            if len(signals) >= 5:
                break
        if not signals:
            raise ValueError("douyin hot search returned no usable movie hot rows")
        return {
            **_source_meta(source_id),
            "fetch_path": "direct_live",
            "started_at": started_at,
            "finished_at": now_utc(),
            "duration_ms": elapsed_ms(timer),
            "success": True,
            "status": "focused_live_verified",
            "raw_url": DOUYIN_MOVIE_HOT_URL,
            "fields_extracted": ["title", "rank", "heat", "video_count", "url"],
            "signal_allowed_use_detail": ["short-video hot discovery", "social discussion signal extraction", "video engagement signal extraction"],
            "forbidden_use": ["verified_facts", "whole-network generalization", "single-video conclusion", "publish-ready evidence"],
            "structured_signals": {
                "hot_items": signals,
                "social_discussion": [item["title"] for item in signals],
            },
            "sample_signals": [f"抖音电影热点：{item['title']}（热度={item.get('heat')}）" for item in signals[:3]],
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        error_text = repr(exc)
        inaccessible_markers = ("401", "403", "-1", "login", "登录", "forbidden", "risk", "verify", "captcha", "sign", "signature", "a-bogus")
        status = "live_inaccessible" if any(marker in error_text.lower() for marker in inaccessible_markers) else "ERROR"
        return {
            **_source_meta(source_id),
            "fetch_path": "direct_live",
            "started_at": started_at,
            "finished_at": now_utc(),
            "duration_ms": elapsed_ms(timer),
            "success": False,
            "status": status,
            "raw_url": DOUYIN_MOVIE_HOT_URL,
            "fields_extracted": [],
            "signal_allowed_use_detail": ["short-video hot discovery", "social discussion signal extraction", "video engagement signal extraction"],
            "forbidden_use": ["verified_facts", "whole-network generalization", "single-video conclusion", "publish-ready evidence"],
            "sample_signals": [],
            "error": error_text,
        }


def fetch_maoyan() -> dict[str, Any]:
    timer = time.perf_counter()
    started_at = now_utc()
    if maoyan is None:
        return {
            **_source_meta("maoyan_realtime_boxoffice"),
            "fetch_path": "direct_live",
            "started_at": started_at,
            "finished_at": now_utc(),
            "duration_ms": elapsed_ms(timer),
            "success": False,
            "raw_url": None,
            "status": "live_dependency_missing",
            "fields_extracted": [],
            "observation": {},
            "candidate": {},
            "error": "missing module: film_tv_maoyan_observation",
        }
    observation = maoyan.fetch_and_build_maoyan_observation()
    candidate = maoyan.generate_film_tv_article_candidate(observation)
    success = bool(observation.get("extracted_items")) and str(observation.get("access_status", "")).startswith("PASS")
    return {
        **_source_meta("maoyan_realtime_boxoffice"),
        "fetch_path": "direct_live",
        "started_at": started_at,
        "finished_at": now_utc(),
        "duration_ms": elapsed_ms(timer),
        "success": success,
        "raw_url": observation.get("raw_url"),
        "status": observation.get("access_status"),
        "fields_extracted": ["title", "rank", "release_info", "sum_box_desc", "show_count", "box_rate", "show_count_rate", "avg_seat_view"],
        "observation": observation,
        "candidate": candidate,
        "error": None if success else observation.get("risk_notes"),
    }


def fetch_guduo(rank_date: str | None = None) -> dict[str, Any]:
    timer = time.perf_counter()
    started_at = now_utc()
    if guduo is None:
        return {
            **_source_meta("guduo"),
            "fetch_path": "direct_live",
            "started_at": started_at,
            "finished_at": now_utc(),
            "duration_ms": elapsed_ms(timer),
            "success": False,
            "raw_url_pattern": "http://d2.guduomedia.com/m/v3/billboard/list?type=DAILY&category={CATEGORY}&date={DATE}&platformId=",
            "status": "live_dependency_missing",
            "fields_extracted": [],
            "results": {},
            "error": {"dependency": "missing module: guduo_fetch"},
        }
    results: dict[str, Any] = {}
    category_errors: dict[str, str] = {}
    for category in ["NETWORK_DRAMA", "NETWORK_VARIETY", "NETWORK_MOVIE", "ALL_ANIME"]:
        last_error: str | None = None
        for _attempt in range(2):
            try:
                result = guduo.fetch_rank(category, "DAILY", rank_date, offline_json=None)
                results[category] = guduo.to_dict(result)
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001
                last_error = repr(exc)
        if last_error:
            category_errors[category] = last_error
    success = any((value.get("item_count") or 0) > 0 for value in results.values())
    return {
        **_source_meta("guduo"),
        "fetch_path": "direct_live",
        "started_at": started_at,
        "finished_at": now_utc(),
        "duration_ms": elapsed_ms(timer),
        "success": success,
        "raw_url_pattern": "http://d2.guduomedia.com/m/v3/billboard/list?type=DAILY&category={CATEGORY}&date={DATE}&platformId=",
        "status": "OK" if success and not category_errors else ("PARTIAL" if success else "ERROR"),
        "fields_extracted": ["rank", "name", "category", "gdi", "rise", "platforms", "release_date", "days"],
        "results": results,
        "error": category_errors or None,
    }


def fetch_article_body_signal() -> dict[str, Any]:
    timer = time.perf_counter()
    started_at = now_utc()
    source_id = "toutiao_deep_film_tv_articles"
    return {
        **_source_meta(source_id),
        "fetch_path": "verified_baseline_reconnected",
        "started_at": started_at,
        "finished_at": now_utc(),
        "duration_ms": elapsed_ms(timer),
        "success": True,
        "status": VERIFIED_SOURCE_POOL[source_id]["verification_status"],
        "raw_url": None,
        "fields_extracted": ["title_pattern", "hook_pattern", "outline_pattern", "angle_candidate", "claim_candidate"],
        "signal_allowed_use_detail": ["title extraction", "hook extraction", "outline extraction", "angle extraction", "claim candidate extraction"],
        "forbidden_use": ["verified_facts", "direct rewrite", "near-duplicate paraphrase"],
        "evidence": {"policy_source": "Hermes-Film-TV-Deep-Analysis-Production-Policy.md", "tier": "P1A", "verification": "focused verifier PASS; tests_run: 24"},
        "sample_signals": ["深度文标题通常先建立判断冲突，再解释作品或市场现象", "正文结构可抽象为钩子、争议、证据层、反转解释和余味结论"],
        "error": None,
    }


def fetch_audience_reaction_signal() -> dict[str, Any]:
    timer = time.perf_counter()
    started_at = now_utc()
    source_id = "douban_reviews_discussions"
    search_url = DOUBAN_LIVE_SEARCH_URL.format(tag=quote("热门"))
    try:
        search_payload = _fetch_json_url(search_url)
        subjects = search_payload.get("subjects") or []
        if not subjects:
            raise ValueError("douban subject search returned no subjects")
        subject = subjects[0]
        subject_id = _extract_douban_subject_id(subject)
        if not subject_id:
            raise ValueError("douban subject search returned no subject id")
        abstract_url = DOUBAN_SUBJECT_ABSTRACT_URL.format(subject_id=subject_id)
        abstract_payload = _fetch_json_url(abstract_url)
        abstract_subject = abstract_payload.get("subject") or {}
        short_comment = abstract_subject.get("short_comment") or {}
        comment = _normalize_douban_comment(short_comment.get("content"))
        if not comment:
            raise ValueError("douban abstract returned no short_comment.content")
        title = abstract_subject.get("title") or subject.get("title") or "unknown"
        rate = abstract_subject.get("rate") or subject.get("rate")
        sample_signals = [
            f"《{title}》短评样本显示：{comment}",
            "该 live source 只提供观众短评、情绪和讨论压力，不提供 verified facts。",
        ]
        return {
            **_source_meta(source_id),
            "fetch_path": "direct_live",
            "started_at": started_at,
            "finished_at": now_utc(),
            "duration_ms": elapsed_ms(timer),
            "success": True,
            "status": "focused_live_verified",
            "raw_url": abstract_url,
            "search_url": search_url,
            "fields_extracted": ["subject_id", "title", "rate", "short_comment", "sentiment_keyword"],
            "signal_allowed_use_detail": ["audience emotion extraction", "review/comment signal extraction", "discussion pressure extraction", "sentiment keyword extraction"],
            "forbidden_use": ["verified_facts", "whole-network generalization", "single-comment conclusion", "publish-ready evidence"],
            "live_subject": {"subject_id": subject_id, "title": title, "rate": rate, "url": abstract_subject.get("url") or subject.get("url")},
            "structured_signals": {
                "audience_emotion": _sentiment_keyword_from_rating(rate),
                "review_comments": [comment],
                "social_discussion": [comment],
                "sentiment_keyword": _sentiment_keyword_from_rating(rate),
            },
            "sample_signals": sample_signals,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            **_source_meta(source_id),
            "fetch_path": "direct_live",
            "started_at": started_at,
            "finished_at": now_utc(),
            "duration_ms": elapsed_ms(timer),
            "success": False,
            "status": "ERROR",
            "raw_url": search_url,
            "fields_extracted": [],
            "signal_allowed_use_detail": ["audience emotion extraction", "review/comment signal extraction", "discussion pressure extraction", "sentiment keyword extraction"],
            "forbidden_use": ["verified_facts", "whole-network generalization", "single-comment conclusion", "publish-ready evidence"],
            "sample_signals": [],
            "error": repr(exc),
        }


def top_maoyan_items(maoyan_result: dict[str, Any], n: int = 3) -> list[dict[str, Any]]:
    if not maoyan_result.get("success"):
        return []
    return list((maoyan_result.get("observation") or {}).get("extracted_items") or [])[:n]


def top_guduo_items(guduo_result: dict[str, Any], category: str, n: int = 3) -> list[dict[str, Any]]:
    if not guduo_result.get("success"):
        return []
    data = ((guduo_result.get("results") or {}).get(category) or {})
    return list(data.get("items") or [])[:n]


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def build_topic(maoyan_items: list[dict[str, Any]], drama_items: list[dict[str, Any]], movie_items: list[dict[str, Any]]) -> dict[str, Any]:
    if maoyan_items:
        lead = maoyan_items[0]
        return {"topic_type": "boxoffice_market_observation", "title": f"《{lead.get('title')}》冲上票房第一，但真正该紧张的不是第二名", "score": 88, "primary_anchor": lead.get("title"), "reason": "P0 猫眼实时票房有明确榜首与追赶者，P1 骨朵热度榜可补充注意力竞争背景。"}
    if drama_items:
        lead = drama_items[0]
        return {"topic_type": "streaming_heat_observation", "title": f"《{lead.get('name')}》登顶热度榜，长视频又进入一轮抢人大战", "score": 82, "primary_anchor": lead.get("name"), "reason": "骨朵榜单有明确剧集榜首与平台热度信号；猫眼不可用时作为同池 fallback。"}
    if movie_items:
        lead = movie_items[0]
        return {"topic_type": "web_movie_heat_observation", "title": f"《{lead.get('name')}》排到网影第一，平台小档期正在变密", "score": 80, "primary_anchor": lead.get("name"), "reason": "骨朵网络电影榜可形成平台小档期观察；猫眼不可用时作为同池 fallback。"}
    return {"topic_type": "none", "title": "本轮无可生产文章", "score": 0, "primary_anchor": None, "reason": "No source items."}


def build_html(run_id: str, topic: dict[str, Any], maoyan_items: list[dict[str, Any]], guduo_result: dict[str, Any], article_body_result: dict[str, Any] | None = None, audience_result: dict[str, Any] | None = None, social_result: dict[str, Any] | None = None, social_results: list[dict[str, Any]] | None = None, output_type: str = "data_observation_draft") -> str:
    drama = top_guduo_items(guduo_result, "NETWORK_DRAMA")
    web_movie = top_guduo_items(guduo_result, "NETWORK_MOVIE")
    anime = top_guduo_items(guduo_result, "ALL_ANIME")
    title = topic["title"]
    output_label = "数据观察稿" if output_type == "data_observation_draft" else "影视自媒体候选稿"
    observed_at = now_utc()
    sections: list[tuple[str, list[str]]] = []
    if maoyan_items:
        first = maoyan_items[0]
        metrics = first.get("metrics") or {}
        lead = f"猫眼专业版实时票房显示，《{first.get('title')}》暂居榜首；这只能说明市场与候选发现信号，不能单独构成影视自媒体主叙事。"
        sections.append((f"一、《{first.get('title')}》第一，只是市场信号", [
            f"本轮 live fetch 中，《{first.get('title')}》出现在猫眼实时电影榜第 {first.get('rank')} 位，累计票房字段为 {metrics.get('sum_box_desc', '待复核')}，票房占比为 {metrics.get('box_rate', '待复核')}。",
            "这组数据只作为候选发现与票房数据支撑，不作为单独主叙事源。",
            "是否能写成自媒体稿，还要看观众情绪、社交讨论、评论反馈、热搜传播或剧情角色上下文。",
        ]))
        if len(maoyan_items) > 1:
            second = maoyan_items[1]
            sections.append((f"二、追赶者《{second.get('title')}》提供对照", [
                f"《{second.get('title')}》位列第 {second.get('rank')}，可作为市场对照数据。",
                "对照数据能帮助判断候选价值，但仍不能替代评论、讨论和剧情上下文。",
            ]))
    else:
        lead = "本轮猫眼 source 不可用；若只有热度/市场信号，本稿只能保持为数据观察稿。"
    if drama:
        sections.append(("三、骨朵热度只提供注意力支撑", [
            f"骨朵网络剧榜中，《{drama[0].get('name')}》位列第 1，GDI 为 {drama[0].get('gdi')}。",
            "骨朵只能用于热度发现与数据支撑，不能单独作为主叙事源。",
        ]))
    if web_movie:
        sections.append(("四、网影榜是补充热度信号", [f"骨朵网络电影榜里，《{web_movie[0].get('name')}》位列第 1。", "该信息用于补充平台热度观察，不作为最终文章质量验收依据。"] ))
    if anime:
        sections.append(("五、动漫榜提示长线内容占场", [f"动漫榜中，《{anime[0].get('name')}》位列第 1。", "这类信号仅辅助判断注意力环境。"] ))
    if article_body_result and article_body_result.get("success"):
        sections.append(("六、正文模式源提供结构与上下文", [
            (article_body_result.get("sample_signals") or ["深度正文模式源只提供结构、钩子和角度信号，不提供可直接改写的正文。"])[0],
            "该源提供 plot_character_context 等叙事角色，但事实仍需 P0 或人工核验。",
        ]))
    if audience_result and audience_result.get("success"):
        sections.append(("七、观众反应源提供情绪与讨论压力", [
            (audience_result.get("sample_signals") or ["观众反应源只提供争议、情绪和解释角度，不能进入 verified_facts。"])[0],
            "该源提供 audience_sentiment、review_comments、social_discussion 等叙事角色，但不能替代事实核验。",
        ]))
    effective_social_results = social_results if social_results is not None else ([social_result] if social_result else [])
    successful_social_results = [src for src in effective_social_results if src and src.get("success")]
    for idx, social_src in enumerate(successful_social_results, start=1):
        sections.append((f"八.{idx}、{social_src.get('source_name')}只提供注意力与讨论信号", [
            (social_src.get("sample_signals") or ["社交/话题源只提供话题热度和讨论入口，不能进入 verified_facts。"])[0],
            "该源提供 hot_search / social_discussion / audience_sentiment 等叙事角色，但不能替代事实核验或发布判断。",
        ]))
    sections.append(("结尾：先判定稿件类型，再决定能否成文", [
        "如果只有猫眼和骨朵，本轮只能输出数据观察稿。",
        "只有 narrative source roles 足够时，才进入 self_media_production_candidate。",
        "canonical_suite_green 仍保持 false，本文不声明最终 production ready。",
    ]))
    section_html = "\n".join("    <section>\n      <h2>{}</h2>\n{}\n    </section>".format(esc(h), "\n".join(f"      <p>{esc(p)}</p>" for p in ps)) for h, ps in sections)
    maoyan_li = "" if not maoyan_items else "\n        <li>猫眼专业版实时票房：market_signal；只用于 candidate_discovery / boxoffice_data_support，不可作为主叙事源。</li>"
    guduo_li = "" if not guduo_result.get("success") else "\n        <li>骨朵热度指数：heat_signal；只用于 heat_discovery / heat_data_support，不可作为主叙事源。</li>"
    article_body_li = "" if not (article_body_result and article_body_result.get("success")) else f"\n        <li>{esc(article_body_result.get('source_name'))}：提供 plot_character_context；不直接改写。</li>"
    audience_li = "" if not (audience_result and audience_result.get("success")) else f"\n        <li>{esc(audience_result.get('source_name'))}：提供 audience_sentiment / review_comments / social_discussion；不进入 verified_facts。</li>"
    social_li = "".join(
        f"\n        <li>{esc(src.get('source_name'))}：提供 {' / '.join(esc(role) for role in (src.get('narrative_roles') or []))}；不进入 verified_facts，不作为发布就绪依据。</li>"
        for src in successful_social_results
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{esc(title)}</title>
  <meta name="description" content="基于 source-role gate 的中文影视文章候选或数据观察输出。">
  <meta name="data-observed-at" content="{esc(observed_at)}">
  <meta name="run-id" content="{esc(run_id)}">
</head>
<body>
  <article>
    <header>
      <h1>{esc(title)}</h1>
      <p><strong>稿件类型：</strong>{esc(output_label)}</p>
      <p><strong>导语：</strong>{esc(lead)}</p>
    </header>

{section_html}

    <footer>
      <h2>Source Attribution / 使用来源</h2>
      <ul>{maoyan_li}{guduo_li}{article_body_li}{audience_li}{social_li}
      </ul>
      <p><strong>执行说明：</strong>猫眼只作候选发现与票房数据支撑；骨朵只作热度发现与数据支撑；二者不得单独作为主叙事源。</p>
      <p><strong>Verification：</strong>focused ad-hoc verification only; canonical_suite_green=false。</p>
    </footer>
  </article>
</body>
</html>
"""


class HTMLCheckParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.h1: list[str] = []
        self.h2: list[str] = []
        self.title: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack.append(tag)
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        for idx in range(len(self.stack) - 1, -1, -1):
            if self.stack[idx] == tag:
                del self.stack[idx]
                break

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self.in_title:
            self.title.append(text)
        if self.stack and self.stack[-1] == "h1":
            self.h1.append(text)
        if self.stack and self.stack[-1] == "h2":
            self.h2.append(text)


def source_role_coverage_from_sources(audit_sources: list[dict[str, Any]]) -> dict[str, Any]:
    successful_sources = [src for src in audit_sources if src.get("success")]
    successful_signal_roles = sorted({src.get("signal_role") for src in successful_sources if src.get("signal_role")})
    present_narrative_roles = sorted({role for src in successful_sources for role in (src.get("narrative_roles") or []) if role in SELF_MEDIA_NARRATIVE_SOURCE_ROLES})
    support_only_source_pool = bool(successful_sources) and {src.get("source_id") for src in successful_sources}.issubset({"maoyan_realtime_boxoffice", "guduo"})
    self_media_ready = len(present_narrative_roles) >= MIN_SELF_MEDIA_NARRATIVE_ROLES and not support_only_source_pool
    missing_roles = [] if self_media_ready else sorted(SELF_MEDIA_NARRATIVE_SOURCE_ROLES - set(present_narrative_roles))
    return {
        "successful_signal_roles": successful_signal_roles,
        "successful_roles": successful_signal_roles,
        "support_signal_roles": sorted(SUPPORT_SIGNAL_ROLES & set(successful_signal_roles)),
        "eligible_narrative_roles": sorted(SELF_MEDIA_NARRATIVE_SOURCE_ROLES),
        "present_narrative_roles": present_narrative_roles,
        "minimum_required_roles": MIN_SELF_MEDIA_NARRATIVE_ROLES,
        "missing_source_roles": missing_roles,
        "support_only_source_pool": support_only_source_pool,
        "self_media_ready": self_media_ready,
    }


def article_quality_gate_from_coverage(role_coverage: dict[str, Any]) -> dict[str, Any]:
    if role_coverage["support_only_source_pool"]:
        reason = "source_pool_insufficient"
    elif len(role_coverage["present_narrative_roles"]) < MIN_SELF_MEDIA_NARRATIVE_ROLES:
        reason = "missing_required_narrative_source_roles"
    else:
        reason = "enough_narrative_source_roles"
    status = "PASS" if role_coverage["self_media_ready"] else "FAIL"
    return {
        "status": status,
        "reason": reason,
        "quality_acceptance_standard": "self_media_article_quality" if status == "PASS" else "smoke_only_not_final_article_quality",
        "eligible_narrative_roles": role_coverage["eligible_narrative_roles"],
        "present_narrative_roles": role_coverage["present_narrative_roles"],
        "missing_source_roles": role_coverage["missing_source_roles"],
        "minimum_required_roles": MIN_SELF_MEDIA_NARRATIVE_ROLES,
        "support_only_source_pool": role_coverage["support_only_source_pool"],
    }


def source_skeleton_from_sources(source_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    skeleton: list[dict[str, Any]] = []
    source_results_by_id = {
        source.get("source_id"): source
        for source in source_results
        if source.get("source_id") in VERIFIED_SOURCE_POOL
    }
    for source_id, spec in VERIFIED_SOURCE_POOL.items():
        source = source_results_by_id.get(source_id, spec)
        signal_role = source.get("signal_role") or spec.get("signal_role")
        source_bucket = SOURCE_BUCKET_BY_SIGNAL_ROLE.get(signal_role) if isinstance(signal_role, str) else None
        skeleton.append({
            "source_id": source_id,
            "source_name": source.get("source_name") or spec.get("source_name"),
            "role": source.get("role") or spec.get("role"),
            "signal_role": signal_role,
            "source_bucket": source_bucket or "unknown_results",
            "narrative_roles": source.get("narrative_roles") or spec.get("narrative_roles") or [],
            "allowed_use": source.get("allowed_use") or spec.get("allowed_use") or [],
            "can_be_main_narrative_source": source.get("can_be_main_narrative_source", spec.get("can_be_main_narrative_source", False)),
            "fetch_path": source.get("fetch_path") or ("disabled_by_default" if spec.get("enabled") is False else None),
            "success": bool(source.get("success")),
            "status": source.get("status") or ("disabled_by_default" if spec.get("enabled") is False else None),
            "fields_extracted": source.get("fields_extracted") or [],
            "html_social_results_eligible": signal_role == "social_discussion_signal",
        })
    return skeleton


def source_buckets_from_skeleton(source_skeleton: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {bucket: [] for bucket in SOURCE_BUCKETS_BY_SIGNAL_ROLE}
    for source in source_skeleton:
        bucket = str(source.get("source_bucket") or "unknown_results")
        buckets.setdefault(bucket, []).append(source)
    return buckets


def article_lane_from_gate(article_quality_gate: dict[str, Any]) -> str:
    return SELF_MEDIA_CANDIDATE_LANE if article_quality_gate.get("status") == "PASS" else DATA_OBSERVATION_LANE


def verify_outputs(output_dir: Path) -> dict[str, Any]:
    timer = time.perf_counter()
    article_path = output_dir / "article.html"
    sources_path = output_dir / "sources.json"
    audit_path = output_dir / "fetch_audit.json"
    summary_path = output_dir / "run_summary.json"
    html_text = article_path.read_text(encoding="utf-8") if article_path.exists() else ""
    sources = json.loads(sources_path.read_text(encoding="utf-8")) if sources_path.exists() else {}
    audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else {}
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    parser = HTMLCheckParser()
    parser.feed(html_text)
    paragraph_count = html_text.count("<p>")
    body_text = " ".join(html_text.replace("<", " <").split())
    forbidden_placeholders = ["TODO", "TBD", "{{", "}}", "lorem ipsum"]
    sources_list = sources.get("sources", []) if isinstance(sources.get("sources", []), list) else []
    audit_sources = audit.get("sources", []) if isinstance(audit.get("sources", []), list) else []
    summary_success = set(summary.get("sources_successful", []) or [])
    summary_failed = set(summary.get("sources_failed", []) or [])
    audit_success = {src.get("source_id") for src in audit_sources if src.get("success")}
    audit_failed = {src.get("source_id") for src in audit_sources if not src.get("success")}
    role_coverage = source_role_coverage_from_sources(audit_sources)
    article_quality_gate = summary.get("article_quality_gate") or article_quality_gate_from_coverage(role_coverage)
    effective_article_lane = summary.get("article_lane") or article_lane_from_gate(article_quality_gate)
    effective_output_type = summary.get("output_type") or ("self_media_candidate_draft" if article_quality_gate.get("status") == "PASS" else "data_observation_draft")
    checks = {
        "article_html_exists": article_path.exists(),
        "sources_json_exists": sources_path.exists(),
        "fetch_audit_json_exists": audit_path.exists(),
        "run_summary_json_exists": summary_path.exists(),
        "html_has_doctype": html_text.lstrip().lower().startswith("<!doctype html>"),
        "html_has_article": "<article>" in html_text and "</article>" in html_text,
        "html_has_h1": bool("".join(parser.h1)),
        "html_has_lead_summary": "<strong>导语：</strong>" in html_text,
        "html_has_body_paragraphs": paragraph_count >= 6,
        "html_has_sections": html_text.count("<section>") >= 4,
        "html_has_closing_section": "结尾" in html_text,
        "html_minimum_bytes": len(html_text.encode("utf-8")) > 2500,
        "html_minimum_body_chars": len(body_text) > 800,
        "html_no_obvious_placeholders": not any(term.lower() in html_text.lower() for term in forbidden_placeholders),
        "html_has_source_attribution": "Source Attribution / 使用来源" in html_text,
        "sources_json_has_required_fields": all({"source_id", "source_name", "role", "signal_role", "fetch_path", "success", "status", "fields_extracted"}.issubset(src) for src in sources_list),
        "sources_have_verified_pool_only": all(src.get("source_id") in VERIFIED_SOURCE_POOL for src in sources_list),
        "sources_summary_audit_count_match": len(sources_list) == len([src for src in audit_sources if src.get("source_id") in VERIFIED_SOURCE_POOL]),
        "audit_sources_have_status_and_reason": all(src.get("status") and (src.get("success") or src.get("error") is not None) for src in audit_sources),
        "summary_audit_success_sets_match": summary_success == audit_success,
        "summary_audit_failed_sets_match": summary_failed == audit_failed,
        "summary_article_count_matches_file": summary.get("article_count") == (1 if article_path.exists() else 0),
        "at_least_one_source_success": any(src.get("success") for src in audit_sources),
        "summary_canonical_false": summary.get("canonical_suite_green") is False,
        "summary_score_meets_threshold": int((summary.get("selected_topic") or {}).get("score") or 0) >= 80,
        "article_lane_matches_quality_gate": effective_article_lane == article_lane_from_gate(article_quality_gate),
        "article_quality_gate_passed": article_quality_gate.get("status") == "PASS",
        "market_heat_not_main_narrative": all(not src.get("can_be_main_narrative_source") for src in audit_sources if src.get("source_id") in {"maoyan_realtime_boxoffice", "guduo"}),
    }
    failed = [key for key, ok in checks.items() if not ok]
    return {
        "status": "PASS" if not failed else "FAIL",
        "verification_type": "focused_ad_hoc",
        "canonical_suite_green": False,
        "article_lane": effective_article_lane,
        "output_type": effective_output_type,
        "source_role_coverage": role_coverage,
        "self_media_ready": role_coverage["self_media_ready"],
        "missing_source_roles": role_coverage["missing_source_roles"],
        "article_quality_gate": article_quality_gate,
        "checks": checks,
        "failed": failed,
        "article_bytes": article_path.stat().st_size if article_path.exists() else 0,
        "sources_bytes": sources_path.stat().st_size if sources_path.exists() else 0,
        "h1": "".join(parser.h1),
        "h2_count": len(parser.h2),
        "section_count": html_text.count("<section>"),
        "paragraph_count": paragraph_count,
        "duration_ms": elapsed_ms(timer),
        "verified_at": now_utc(),
    }


def _unknown_source_error(exc: Exception) -> dict[str, Any]:
    return {
        "source_id": "unknown",
        "source_name": "unknown",
        "role": None,
        "signal_role": None,
        "narrative_roles": [],
        "allowed_use": [],
        "can_be_main_narrative_source": False,
        "fetch_path": "direct_live",
        "started_at": now_utc(),
        "finished_at": now_utc(),
        "duration_ms": 0,
        "success": False,
        "status": "ERROR",
        "fields_extracted": [],
        "error": repr(exc),
    }


def run(output_base: Path, rank_date: str | None = None, run_id: str | None = None) -> dict[str, Any]:
    run_timer = time.perf_counter()
    run_id = run_id or run_id_from_now()
    started_at = now_utc()
    output_dir = output_base / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    source_results = []
    for fetcher in (
        fetch_maoyan,
        lambda: fetch_guduo(rank_date),
        fetch_article_body_signal,
        fetch_audience_reaction_signal,
        fetch_weibo_entertainment_hotsearch_signal,
        fetch_weibo_topic_search_signal,
        fetch_zhihu_movie_hot_topics_signal,
        fetch_bilibili_movie_zone_hot_signal,
        fetch_xiaohongshu_movie_notes_signal,
        fetch_douyin_movie_hot_signal,
    ):
        try:
            source_results.append(fetcher())
        except Exception as exc:  # noqa: BLE001
            source_results.append(_unknown_source_error(exc))

    maoyan_result = next((r for r in source_results if r.get("source_id") == "maoyan_realtime_boxoffice"), {})
    guduo_result = next((r for r in source_results if r.get("source_id") == "guduo"), {})
    article_body_result = next((r for r in source_results if r.get("source_id") == "toutiao_deep_film_tv_articles"), {})
    audience_result = next((r for r in source_results if r.get("source_id") == "douban_reviews_discussions"), {})
    social_results = [
        r for r in source_results
        if r.get("signal_role") == "social_discussion_signal"
    ]
    social_result = next((r for r in social_results if r.get("source_id") == "weibo_entertainment_hotsearch"), {})
    maoyan_items = top_maoyan_items(maoyan_result)
    drama_items = top_guduo_items(guduo_result, "NETWORK_DRAMA")
    movie_items = top_guduo_items(guduo_result, "NETWORK_MOVIE")
    topic = build_topic(maoyan_items, drama_items, movie_items)
    role_coverage = source_role_coverage_from_sources(source_results)
    article_quality_gate = article_quality_gate_from_coverage(role_coverage)
    effective_article_lane = article_lane_from_gate(article_quality_gate)
    output_type = "self_media_candidate_draft" if article_quality_gate["status"] == "PASS" else "data_observation_draft"
    source_skeleton = source_skeleton_from_sources(source_results)
    source_buckets = source_buckets_from_skeleton(source_skeleton)

    if not any(result.get("success") for result in source_results):
        summary = {"run_id": run_id, "status": "FAIL", "reason": "all verified sources failed", "canonical_suite_green": False, "started_or_created_at": now_utc()}
        json_write(output_dir / "run_summary.json", summary)
        json_write(output_dir / "fetch_audit.json", {"run_id": run_id, "sources": source_results})
        verification = verify_outputs(output_dir)
        json_write(output_dir / "verification.json", verification)
        return {"output_dir": str(output_dir), "summary": summary, "verification": verification}

    generation_timer = time.perf_counter()
    html_text = build_html(run_id, topic, maoyan_items, guduo_result, article_body_result, audience_result, social_result, social_results=social_results, output_type=output_type)
    article_generation_duration_ms = elapsed_ms(generation_timer)
    sources_payload = {
        "run_id": run_id,
        "article_file": "article.html",
        "title": topic["title"],
        "selected_score": topic["score"],
        "topic_type": topic["topic_type"],
        "selection_reason": topic["reason"],
        "source_skeleton": source_skeleton,
        "source_buckets": source_buckets,
        "sources": [
            {k: result.get(k) for k in ["source_id", "source_name", "role", "signal_role", "narrative_roles", "allowed_use", "can_be_main_narrative_source", "fetch_path", "success", "status", "fields_extracted"]} | {"raw_url": result.get("raw_url") or result.get("raw_url_pattern")}
            for result in source_results
            if result.get("source_id") in VERIFIED_SOURCE_POOL
        ],
    }
    audit_payload = {
        "run_id": run_id,
        "runner_version": RUNNER_VERSION,
        "created_at": now_utc(),
        "verified_source_pool": VERIFIED_SOURCE_POOL,
        "priority_source_registry": PRIORITY_SOURCE_REGISTRY,
        "priority_source_order": PRIORITY_SOURCE_ORDER,
        "source_skeleton": source_skeleton,
        "source_buckets": source_buckets,
        "sources": source_results,
        "fallback_policy": "Use any successful source from verified pool; fail only if all sources fail.",
    }
    summary_payload = {
        "run_id": run_id,
        "status": "PASS",
        "runner_version": RUNNER_VERSION,
        "mode": "live",
        "article_lane": effective_article_lane,
        "output_type": output_type,
        "source_role_coverage": role_coverage,
        "source_buckets": {bucket: [source["source_id"] for source in sources] for bucket, sources in source_buckets.items()},
        "self_media_ready": role_coverage["self_media_ready"],
        "missing_source_roles": role_coverage["missing_source_roles"],
        "article_quality_gate": article_quality_gate,
        "started_at": started_at,
        "finished_at": now_utc(),
        "duration_ms": elapsed_ms(run_timer),
        "stage_status": {"fetch": "PASS" if any(r.get("success") for r in source_results) else "FAIL", "generate": "PASS", "verify": "PENDING"},
        "article_generation_duration_ms": article_generation_duration_ms,
        "verified_source_pool_only": True,
        "priority_source_order": PRIORITY_SOURCE_ORDER,
        "priority_source_registry_status": "planned_not_live_verified",
        "canonical_suite_green": False,
        "pytest_run": False,
        "article_count": 1,
        "article_file": "article.html",
        "sources_successful": [r.get("source_id") for r in source_results if r.get("success")],
        "sources_failed": [r.get("source_id") for r in source_results if not r.get("success")],
        "selected_topic": topic,
        "output_dir": str(output_dir),
    }
    text_write(output_dir / "article.html", html_text)
    json_write(output_dir / "sources.json", sources_payload)
    json_write(output_dir / "fetch_audit.json", audit_payload)
    json_write(output_dir / "run_summary.json", summary_payload)
    verification = verify_outputs(output_dir)
    summary_payload["finished_at"] = now_utc()
    summary_payload["duration_ms"] = elapsed_ms(run_timer)
    summary_payload["stage_status"]["verify"] = verification.get("status")
    summary_payload["verification_duration_ms"] = verification.get("duration_ms")
    json_write(output_dir / "run_summary.json", summary_payload)
    verification = verify_outputs(output_dir)
    json_write(output_dir / "verification.json", verification)
    return {"output_dir": str(output_dir), "summary": summary_payload, "verification": verification}


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal repeatable article production live runner")
    parser.add_argument("--output-base", default=str(DEFAULT_OUTPUT_BASE), help="Base directory for production run outputs")
    parser.add_argument("--rank-date", default=None, help="Guduo rank date YYYY-MM-DD; default latest supported date")
    parser.add_argument("--run-id", default=None, help="Override run id")
    args = parser.parse_args()
    result = run(Path(args.output_base), rank_date=args.rank_date, run_id=args.run_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("verification", {}).get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
