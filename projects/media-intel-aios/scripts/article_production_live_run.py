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
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:
    import film_tv_maoyan_observation as maoyan  # type: ignore[import-not-found]  # noqa: E402
except ModuleNotFoundError:
    maoyan = None  # type: ignore[assignment]

try:
    import guduo_fetch as guduo  # type: ignore[import-not-found]  # noqa: E402
except ModuleNotFoundError:
    guduo = None  # type: ignore[assignment]

RUNNER_VERSION = "0.3.4"
DEFAULT_OUTPUT_BASE = ROOT / "outputs" / "article_production"
DOUBAN_LIVE_SUBJECT_LIMIT = 9
# Bounded, direct raw samples only. This never becomes a crawler or a generic gate.
DOUBAN_DISCUSSION_SAMPLE_LIMIT = 10
DOUBAN_REPEATED_CLUE_MIN_SAMPLES = 3
DOUBAN_REPEATED_CLUE_MIN_OCCURRENCES = 2
DOUBAN_LIVE_SEARCH_URL = "https://movie.douban.com/j/search_subjects?type=movie&tag={tag}&sort=recommend&page_limit={page_limit}&page_start=0"
DOUBAN_SUBJECT_ABSTRACT_URL = "https://movie.douban.com/j/subject_abstract?subject_id={subject_id}"
WEIBO_HOTSEARCH_URL = "https://weibo.com/ajax/side/hotSearch"
WEIBO_TOPIC_SEARCH_URL = "https://weibo.com/ajax/search/all?containerid=100103type%3D1%26q%3D{query}"
ZHIHU_HOT_LIST_URL = "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=20&desktop=true"
BILIBILI_MOVIE_ZONE_HOT_URL = "https://api.bilibili.com/x/web-interface/ranking/v2?rid=23&type=all"
BILIBILI_VIDEO_SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/type?{query}"
BILIBILI_VIDEO_DETAIL_URL = "https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
# Explicit identity bridges only.  Never use this registry to search or infer a 1905 page.
SAME_WORK_1905_REGISTRY = {
    "36372941": {
        "url": "https://www.1905.com/mdb/film/2258502/",
        "chinese_title": "森中有林",
        "english_title": "All The Good Eyes",
        "year": "2026",
        "actors": ["于和伟", "韩庚", "高圆圆"],
        # Acceptance contract for this finite, explicit editorial-page bridge.
        # These values are verified from page text only, never synthesized here.
        "expected_release_dates": ["2026-05-01", "2026-05-23"],
        "tmdb_id": "1443374",
        "imdb_id": "tt36598159",
        # Direct editorial evidence is intentionally finite. This bridge must never become search/discovery input.
        "editorial_pages": [
            {"url": "https://www.1905.com/mdb/film/2258502/info/", "page_type": "info"},
            {"url": "https://www.1905.com/news/20260413/1758006.shtml", "page_type": "news"},
            {"url": "https://www.1905.com/news/20260506/1759260.shtml", "page_type": "news"},
            {"url": "https://www.1905.com/news/20260325/1756861.shtml", "page_type": "news"},
        ],
    },
    "37379599": {
        "url": "https://www.1905.com/mdb/film/2259045/",
        "chinese_title": "10间敢死队",
        "english_title": "Being Toward Death",
        "year": "2026",
        "actors": ["陈思诚", "蒋龙", "杨超越"],
        "expected_release_dates": ["2026-05-01"],
        # Three direct news bodies are used because this packet extractor requires
        # every allowlisted page to yield classified article-body claims. The MDB
        # page above remains the explicit work-identity bridge.
        "editorial_pages": [
            {"url": "https://www.1905.com/news/20260426/1758826.shtml", "page_type": "news"},
            {"url": "https://www.1905.com/news/20260428/1758914.shtml", "page_type": "news"},
            {"url": "https://www.1905.com/news/20260508/1759383.shtml", "page_type": "news"},
        ],
    },
    "37242440": {
        "url": "https://www.1905.com/mdb/film/2258463/",
        "chinese_title": "惊蛰无声",
        "english_title": "Silent Alarm",
        "year": "2026",
        "actors": ["张艺谋", "易烊千玺", "朱一龙"],
        "editorial_pages": [
            {"url": "https://www.1905.com/news/20260219/1755042.shtml", "page_type": "news"},
            {"url": "https://www.1905.com/news/20260220/1755058.shtml", "page_type": "news"},
            {"url": "https://www.1905.com/news/20260220/1755067.shtml", "page_type": "news"},
        ],
    },
}
# Direct-body packet registry: finite, fixed editorial pages only. It is not a
# crawler seed and is reachable solely through its separate explicit request.
FAR_EAST_FILMS_DIRECT_BODY_REGISTRY = {
    "36372941": {
        "douban_url": "https://movie.douban.com/subject/36372941/",
        "chinese_title": "森中有林",
        "title_alias": "All the Good Eyes",
        "year": "2026",
        "url": "https://fareastfilms.com/fef-news/trailer-all-the-good-eyes/",
        "published_at": "2026-04-08",
        "page_title": "Trailer: ‘All the Good Eyes’",
        "byline": "Phil Mills",
        "synopsis_anchor": "After losing an eye in a violent incident",
        "root_locator": "main#main.site-main > .page-content > .entry-content",
    },
}
# Exact official-page identity bridges only; never search or infer from these.
OFFICIAL_SAME_WORK_REGISTRY = {
    "36877245": {
        "url": "https://www.youtube.com/watch?v=J6nia3eu5RY", "parser": "youtube",
        "chinese_titles": ["火遮眼"], "english_title": "The Furious", "subject_year": "2025", "official_year": "2026",
        "directors": ["谷垣健治"], "actors": ["謝苗", "谢苗"],
        "context_anchors": ["王偉", "王伟", "雨晴", "納文", "纳文", "兒童", "儿童"],
    },
    "36916000": {
        "url": "https://www.focusfeatures.com/pressure", "parser": "focus",
        "chinese_titles": ["诺曼底72小时", "諾曼第72小時"], "english_title": "Pressure", "subject_year": "2026", "official_year": "2026",
        "directors": ["Anthony Maras"], "actors": ["Andrew Scott", "Brendan Fraser"],
        "context_anchors": ["D-Day", "Eisenhower", "James Stagg", "72 hours"],
    },
    "37042683": {
        "url": "https://www.youtube.com/watch?v=-x_4XLUE1qc", "parser": "youtube",
        "chinese_titles": ["卡罗来纳的卡罗琳", "卡羅萊納的卡羅琳"], "english_title": "Carolina Caroline", "subject_year": "2025", "official_year": "2026",
        "directors": ["Adam Carter Rehmeier"], "actors": ["Samara Weaving", "Kyle Gallner"],
        "context_anchors": ["Caroline Daniels", "Texas", "con man", "crime"],
    },
}
XIAOHONGSHU_MOVIE_NOTES_SEARCH_URL = "https://edith.xiaohongshu.com/api/sns/web/v1/search/notes"
DOUYIN_MOVIE_HOT_URL = "https://www.douyin.com/aweme/v1/web/hot/search/list/"
MAOYAN_REALTIME_BOXOFFICE_URL = "https://piaofang.maoyan.com/dashboard-ajax/movie"
GUDUO_RANK_URL = "http://d2.guduomedia.com/m/v3/billboard/list"
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


def _fetch_html_url(url: str, timeout: int = 12, headers: dict[str, str] | None = None) -> dict[str, str]:
    """Fetch a public HTML document and expose only its final URL plus decoded body."""
    request_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
    }
    if headers:
        request_headers.update(headers)
    request = Request(url, headers=request_headers)
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return {"url": response.geturl(), "html": response.read().decode(charset, errors="replace")}


def _extract_letterboxd_work_anchor(live_subject: dict[str, Any] | None) -> tuple[str, str] | None:
    anchor = live_subject if isinstance(live_subject, dict) else {}
    title = re.sub(r"[\u200e\u200f\u202a-\u202e]", "", re.sub(r"\s+", " ", str(anchor.get("title") or ""))).strip()
    if not anchor.get("subject_id") or not anchor.get("url") or not title:
        return None
    year_match = re.search(r"\((\d{4})\)\s*$", title)
    if not year_match:
        return None
    english_before_year = re.search(r"([A-Za-z][A-Za-z0-9 .,'’:\-]*?)\s*\(\d{4}\)\s*$", title)
    if not english_before_year:
        return None
    work_title = re.sub(r"\s+", " ", english_before_year.group(1)).strip(" .")
    return (work_title, year_match.group(1)) if work_title else None


def _letterboxd_slug(work_title: str, year: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", work_title.lower()).strip("-")
    return f"{normalized}-{year}" if normalized else ""


def _html_tag_value(page_html: str, tag: str, attr: str, expected: str, value_attr: str) -> str:
    for match in re.finditer(rf"<{tag}\b([^>]*)>", page_html, flags=re.IGNORECASE):
        attrs = {
            key.lower(): html.unescape(value).strip()
            for key, _quote, value in re.findall(r"([\w:-]+)\s*=\s*(['\"])(.*?)\2", match.group(1), flags=re.DOTALL)
        }
        if attrs.get(attr.lower(), "").lower() == expected.lower() and attrs.get(value_attr.lower()):
            return attrs[value_attr.lower()]
    return ""


def fetch_letterboxd_same_work_context(live_subject: dict[str, Any] | None) -> dict[str, Any]:
    """Conservatively use one public Letterboxd film page as plot context, never as review evidence."""
    timer = time.perf_counter()
    started_at = now_utc()
    source_id = "letterboxd_work_context"
    source_meta = {
        "source_id": source_id,
        "source_name": "Letterboxd同作品页面剧情上下文",
        "role": "P1C_letterboxd_same_work_context",
        "signal_role": "article_body_signal",
        "narrative_roles": ["plot_character_context"],
        "allowed_use": ["same-work public plot and character context only"],
        "can_be_main_narrative_source": True,
    }
    page_url = ""
    try:
        parsed_anchor = _extract_letterboxd_work_anchor(live_subject)
        if not parsed_anchor:
            raise ValueError("douban live_subject lacks an English work title and terminal year")
        work_title, year = parsed_anchor
        slug = _letterboxd_slug(work_title, year)
        if not slug:
            raise ValueError("could not construct a Letterboxd film slug")
        page_url = f"https://letterboxd.com/film/{slug}/"
        fetched = _fetch_html_url(page_url, headers={"Referer": "https://letterboxd.com/"})
        final_url = str(fetched.get("url") or "").strip()
        page_html = str(fetched.get("html") or "")
        canonical_url = _html_tag_value(page_html, "link", "rel", "canonical", "href") or _html_tag_value(page_html, "meta", "property", "og:url", "content")
        description = _html_tag_value(page_html, "meta", "name", "description", "content") or _html_tag_value(page_html, "meta", "property", "og:description", "content")
        title_match = re.search(r"<title[^>]*>(.*?)</title>", page_html, flags=re.IGNORECASE | re.DOTALL)
        document_title = re.sub(r"\s+", " ", html.unescape(title_match.group(1))).strip() if title_match else ""
        final_parts = urlsplit(final_url)
        canonical_parts = urlsplit(canonical_url)
        expected_path = f"/film/{slug}/"
        title_pattern = re.compile(rf"\b{re.escape(work_title)}\b.*\b{re.escape(year)}\b", re.IGNORECASE)
        if (
            final_parts.scheme != "https" or final_parts.netloc.lower() != "letterboxd.com" or final_parts.path != expected_path
            or canonical_parts.scheme != "https" or canonical_parts.netloc.lower() != "letterboxd.com" or canonical_parts.path != expected_path
            or not title_pattern.search(document_title) or len(description) < 20
        ):
            raise ValueError("Letterboxd page failed exact film URL, canonical, title/year, or minimum-description evidence checks")
        anchor = live_subject if isinstance(live_subject, dict) else {}
        signal = {"title": document_title[:160], "description": re.sub(r"\s+", " ", description)[:600], "url": final_url}
        return {
            **source_meta, "fetch_path": "direct_live_same_work_public_page", "started_at": started_at, "finished_at": now_utc(), "duration_ms": elapsed_ms(timer),
            "success": True, "status": "focused_live_verified", "raw_url": final_url, "fields_extracted": ["subject_id", "title", "year", "canonical_url", "meta_description", "url"],
            "signal_allowed_use_detail": ["same-work plot and character context only; not audience review or social discussion evidence"],
            "forbidden_use": ["audience_review_claims", "social_discussion_claims", "verified_facts", "whole-platform generalization", "publish-ready evidence"],
            "live_subject": {"subject_id": str(anchor["subject_id"]), "title": str(anchor["title"]), "url": str(anchor["url"])},
            "top_signals": [signal], "structured_signals": {"plot_character_context": [signal]},
            "sample_signals": [f"Letterboxd同作品页面剧情上下文《{work_title}》：{signal['description']}"], "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            **source_meta, "fetch_path": "direct_live_same_work_public_page", "started_at": started_at, "finished_at": now_utc(), "duration_ms": elapsed_ms(timer),
            "success": False, "status": "ERROR", "raw_url": page_url or None, "fields_extracted": [],
            "signal_allowed_use_detail": ["same-work plot and character context only; not audience review or social discussion evidence"],
            "forbidden_use": ["audience_review_claims", "social_discussion_claims", "verified_facts", "whole-platform generalization", "publish-ready evidence"],
            "sample_signals": [], "error": repr(exc),
        }



def _1905_page_text(page_html: str) -> str:
    """Remove markup before identity/context checks; preserves visible public-page text only."""
    without_noncontent = re.sub(r"<(?:script|style|noscript)\b[^>]*>.*?</(?:script|style|noscript)>", " ", page_html, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", without_noncontent))).strip()


def _1905_editorial_root(page_html: str, page_type: str) -> str:
    """Return exactly one validated editorial root; never fall back to full-page text."""
    if page_type == "news":
        start_pattern = r'<div\b(?=[^>]*\bid=["\']contentNews["\'])[^>]*>'
    elif page_type == "info":
        start_pattern = r'<div\b(?=[^>]*\bclass=["\'][^"\']*\bsecondary-wrapper-w1200\b[^"\']*["\'])[^>]*>'
    else:
        raise ValueError("unsupported 1905 editorial page type")
    starts = list(re.finditer(start_pattern, page_html, flags=re.IGNORECASE | re.DOTALL))
    if len(starts) != 1:
        raise ValueError("1905 editorial root missing or ambiguous")
    start, depth = starts[0].end(), 1
    tag_pattern = re.compile(r'</?div\b[^>]*>', re.IGNORECASE)
    for match in tag_pattern.finditer(page_html, start):
        depth += -1 if match.group(0).startswith('</') else 1
        if depth == 0:
            root = page_html[start:match.start()]
            break
    else:
        raise ValueError("1905 editorial root is unclosed")
    root = re.sub(r'<(?:script|style|noscript)\b[^>]*>.*?</(?:script|style|noscript)>', ' ', root, flags=re.IGNORECASE | re.DOTALL)
    root = re.sub(r'<(?:footer|nav|aside)\b[^>]*>.*?</(?:footer|nav|aside)>', ' ', root, flags=re.IGNORECASE | re.DOTALL)
    root = re.sub(r'<(?:div|section|ul)\b[^>]*(?:\bshare\b|\btag\b|\brelNews\b|\brelated\b|\bfooter\b|\bnav\b)[^>]*>.*?</(?:div|section|ul)>', ' ', root, flags=re.IGNORECASE | re.DOTALL)
    return root


def _1905_editorial_fact_class(claim: str) -> str:
    """Fail closed: only explicitly attributable factual classes are writable."""
    if re.search(r"(?:上映时间|上映|公映|定档|档期|正式上映)", claim) and _1905_release_dates(claim):
        return "release"
    if re.search(r"演员|主演|饰演|领衔主演|特别出演", claim):
        return "cast"
    if re.search(r"(?:导演|编剧|主创|张艺谋).{0,30}(?:表示|称|说|谈及|认为|指出|解释)|(?:表示|称|说|谈及|认为|指出|解释).{0,30}[“\"]", claim) and re.search(r"森林|主题|意象|表达|情感|家国情怀", claim):
        return "theme"
    if re.search(r"导演|编剧|拍摄|创作|制作|镜头|剧组", claim):
        return "production"
    if re.search(r"剧情|角色|人物|故事|关系|叙事|命案", claim):
        return "plot_character"
    return ""


def _1905_release_dates(text: str, *, default_year: str = "") -> set[str]:
    """Normalize dates only when their own clause/field establishes release semantics."""
    release_pattern = r"上映时间|上映|公映|定档|档期|正式上映"
    dates = set()
    date_pattern = re.compile(r"(?:(20\d{2})[年./-]\s*)?(\d{1,2})[月./-]\s*(\d{1,2})(?:日)?")
    for match in date_pattern.finditer(text):
        # A publication date can share a sentence with a release date. Restrict the
        # semantic check to this comma/semicolon-delimited clause, while retaining
        # labels such as "上映时间：2026年5月1日" in the same clause.
        clause_start = max(text.rfind(mark, 0, match.start()) for mark in "，,；;。！？!?") + 1
        clause_end_candidates = [text.find(mark, match.end()) for mark in "，,；;。！？!?" if text.find(mark, match.end()) != -1]
        clause_end = min(clause_end_candidates) if clause_end_candidates else len(text)
        if not re.search(release_pattern, text[clause_start:clause_end]):
            continue
        year, month, day = match.groups()
        if year or default_year:
            dates.add(f"{year or default_year}-{int(month):02d}-{int(day):02d}")
    return dates


def _1905_root_release_dates(root_html: str, page_type: str, *, default_year: str = "") -> set[str]:
    """Read release dates from a single release sentence or the explicit info field only."""
    dates: set[str] = set()
    if page_type == "info":
        for block in re.findall(r"<dd\b[^>]*>.*?</dd>", root_html, flags=re.IGNORECASE | re.DOTALL):
            field = _1905_page_text(block)
            if "上映时间" in field:
                dates.update(_1905_release_dates(field, default_year=default_year))
    for fragment in re.findall(r"<(?:p|h[2-4])\b[^>]*>(.*?)</(?:p|h[2-4])>", root_html, flags=re.IGNORECASE | re.DOTALL):
        for sentence in re.split(r"(?<=[。！？!?])\s*", _1905_page_text(fragment)):
            dates.update(_1905_release_dates(sentence, default_year=default_year))
    return dates


def _1905_published_at(page_html: str) -> str:
    value = (_html_tag_value(page_html, "meta", "property", "article:published_time", "content")
             or _html_tag_value(page_html, "meta", "name", "publishdate", "content"))
    if value:
        return value[:40]
    match = re.search(r"\b20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}", _1905_page_text(page_html))
    return match.group(0) if match else ""


def _1905_editorial_claims(page_html: str, page_type: str) -> list[str]:
    root = _1905_editorial_root(page_html, page_type)
    fragments = re.findall(r"<(?:p|dd|h[2-4])\b[^>]*>(.*?)</(?:p|dd|h[2-4])>", root, flags=re.IGNORECASE | re.DOTALL)
    claims: list[str] = []
    for fragment in fragments:
        for sentence in re.split(r"(?<=[。！？!?])\s*", _1905_page_text(fragment)):
            sentence = re.sub(r"\s+", " ", sentence).strip()
            if len(sentence) < 20 or re.search(r"https?://|\bfr=|ICP备案|返回顶部|相关阅读|分享|免责声明", sentence, re.IGNORECASE):
                continue
            if _1905_editorial_fact_class(sentence):
                claims.append(sentence[:600])
    return claims


def _far_east_films_article_root(page_html: str) -> str:
    """Return the sole observed Far East Films article body, never a page-wide fallback."""
    def nested(tag: str, text: str, starts: list[re.Match[str]]) -> str:
        if len(starts) != 1:
            raise ValueError(f"Far East Films {tag} root missing or ambiguous")
        start, depth = starts[0].end(), 1
        for match in re.finditer(rf"</?{tag}\b[^>]*>", text[start:], flags=re.IGNORECASE):
            depth += -1 if match.group(0).startswith("</") else 1
            if depth == 0:
                return text[start:start + match.start()]
        raise ValueError(f"Far East Films {tag} root is unclosed")

    main_html = nested("main", page_html, list(re.finditer(r"<main\b(?=[^>]*\bid=['\"]main['\"])[^>]*>", page_html, flags=re.IGNORECASE)))
    return nested("div", main_html, list(re.finditer(r"<div\b(?=[^>]*\bclass=['\"][^'\"]*\bentry-content\b[^'\"]*['\"])[^>]*>", main_html, flags=re.IGNORECASE)))


def _far_east_films_published_date(page_html: str) -> str:
    """Read the fixed page's visible byline date from its unique entry header."""
    headers = re.findall(r"<header\b[^>]*\bclass=['\"][^'\"]*\bentry-header\b[^'\"]*['\"][^>]*>(.*?)</header>", page_html, flags=re.IGNORECASE | re.DOTALL)
    if len(headers) != 1:
        return ""
    candidates = re.findall(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s+20\d{2}\b", _1905_page_text(headers[0]))
    if len(candidates) != 1:
        return ""
    try:
        return datetime.strptime(candidates[0].replace(".", ""), "%b %d, %Y").strftime("%F")
    except ValueError:
        return ""


def fetch_far_east_films_direct_body_packet(live_subject: dict[str, Any] | None) -> dict[str, Any]:
    """Fetch one explicitly registered Far East Films editorial synopsis, fail closed."""
    timer, started_at = time.perf_counter(), now_utc()
    source_meta = {
        "source_id": "independent_direct_source_packet",
        "source_name": "Far East Films fixed editorial synopsis packet",
        "generic_eligibility_credit": False,
        "requires_attribution_in_output": True,
    }
    try:
        anchor = live_subject if isinstance(live_subject, dict) else {}
        subject_id = str(anchor.get("subject_id") or "").strip()
        mapping = FAR_EAST_FILMS_DIRECT_BODY_REGISTRY.get(subject_id)
        title = re.sub(r"\s+", " ", str(anchor.get("title") or "")).strip()
        if (not mapping or str(anchor.get("url") or "").strip() != mapping["douban_url"]
                or mapping["chinese_title"] not in title or mapping["title_alias"] not in title
                or _title_year(title) != mapping["year"]):
            raise ValueError("no matching explicit Far East Films direct-body identity bridge")
        fetched = _fetch_html_url(mapping["url"], headers={"Referer": mapping["url"]})
        final_url, page_html = str(fetched.get("url") or "").strip(), str(fetched.get("html") or "")
        canonical_url = _html_tag_value(page_html, "link", "rel", "canonical", "href")
        og_url = _html_tag_value(page_html, "meta", "property", "og:url", "content")
        article_published_at = _html_tag_value(page_html, "meta", "property", "article:published_time", "content")
        if (final_url != mapping["url"] or canonical_url != mapping["url"]
                or og_url != mapping["url"]):
            raise ValueError("Far East Films final URL or canonical/og URL did not exactly match registry")
        if (_far_east_films_published_date(page_html) != mapping["published_at"]
                or (article_published_at and article_published_at[:10] != mapping["published_at"])):
            raise ValueError("Far East Films publication date did not exactly match registry")
        root_html = _far_east_films_article_root(page_html)
        header_html = re.search(r"<header\b[^>]*\bclass=['\"][^'\"]*\bentry-header\b[^'\"]*['\"][^>]*>(.*?)</header>", page_html, flags=re.IGNORECASE | re.DOTALL)
        header_text = _1905_page_text(header_html.group(1)) if header_html else ""
        root_text = _1905_page_text(root_html)
        if mapping["page_title"] not in header_text or mapping["byline"] not in header_text:
            raise ValueError("Far East Films title or byline identity did not match registry")
        if mapping["title_alias"] not in root_text or mapping["chinese_title"] not in root_text or mapping["year"] not in root_text:
            raise ValueError("Far East Films article body lacks exact work identity")
        synopsis_match = re.search(r'<p\b[^>]*>\s*<strong>\s*Synopsis:\s*</strong>\s*(.*?)</p>', root_html, flags=re.IGNORECASE | re.DOTALL)
        synopsis = re.sub(r"\s+", " ", _1905_page_text(synopsis_match.group(1))).strip() if synopsis_match else ""
        if len(synopsis) < 120 or not synopsis.startswith(mapping["synopsis_anchor"]):
            raise ValueError("Far East Films synopsis/body validation failed")
        atom = {
            "claim": synopsis,
            "source_text": synopsis,
            "source_id": "independent_direct_source_packet",
            "source_role": "far_east_films_editorial_synopsis",
            "epistemic_status": "attributed_editorial_synopsis",
            "attribution": "Far East Films editorial synopsis",
            "url": mapping["url"],
            "canonical_url": canonical_url or og_url,
            "published_at": mapping["published_at"],
            "root_locator": mapping["root_locator"],
            "source_locator": mapping["root_locator"] + " > p:has(strong Synopsis)",
            "work_key": f"douban:{subject_id}",
            "work_title": title,
        }
        return {**source_meta, "fetch_path": "direct_live_explicit_registered_page", "started_at": started_at, "finished_at": now_utc(), "duration_ms": elapsed_ms(timer), "success": True, "status": "focused_live_verified", "raw_url": mapping["url"], "live_subject": anchor, "work_key": atom["work_key"], "supplementary_attributed_evidence": [atom], "page_audit": [{"url": mapping["url"], "canonical_url": atom["canonical_url"], "published_at": mapping["published_at"], "root_locator": mapping["root_locator"], "byline": mapping["byline"]}], "error": None}
    except Exception as exc:  # noqa: BLE001
        return {**source_meta, "fetch_path": "direct_live_explicit_registered_page", "started_at": started_at, "finished_at": now_utc(), "duration_ms": elapsed_ms(timer), "success": False, "status": "ERROR", "supplementary_attributed_evidence": [], "error": repr(exc)}


def fetch_1905_same_work_editorial_packet(live_subject: dict[str, Any] | None) -> dict[str, Any]:
    """Fail closed: only an explicit mapping may yield individual 1905 fact atoms."""
    timer = time.perf_counter()
    started_at = now_utc()
    source_meta = {"source_id": "1905_same_work_editorial_packet", "source_name": "1905同作品直接编辑报道证据包", "role": "P1A_1905_same_work_direct_editorial", "signal_role": "article_body_signal", "narrative_roles": ["plot_character_context"], "allowed_use": ["explicitly mapped direct 1905 editorial atoms with per-atom provenance"], "can_be_main_narrative_source": True}
    try:
        anchor = live_subject if isinstance(live_subject, dict) else {}
        subject_id = str(anchor.get("subject_id") or "").strip()
        subject_title = re.sub(r"\s+", " ", str(anchor.get("title") or "")).strip()
        subject_url = str(anchor.get("url") or "").strip()
        mapping = SAME_WORK_1905_REGISTRY.get(subject_id)
        pages = mapping.get("editorial_pages") if isinstance(mapping, dict) else None
        if (not mapping or not isinstance(pages, list) or not pages or subject_url != f"https://movie.douban.com/subject/{subject_id}/" or mapping["chinese_title"] not in subject_title or _title_year(subject_title) != mapping["year"]):
            raise ValueError("no matching explicit 1905 direct-editorial identity bridge")
        atoms: list[dict[str, Any]] = []
        time_sensitive: dict[str, set[str]] = {}
        page_audit: list[dict[str, Any]] = []
        for page in pages:
            page_url, page_type = str(page.get("url") or ""), str(page.get("page_type") or "")
            expected = urlsplit(page_url)
            fetched = _fetch_html_url(page_url, headers={"Referer": "https://www.1905.com/"})
            final_url, page_html = str(fetched.get("url") or "").strip(), str(fetched.get("html") or "")
            canonical_url = _html_tag_value(page_html, "link", "rel", "canonical", "href") or _html_tag_value(page_html, "meta", "property", "og:url", "content")
            final, canonical = urlsplit(final_url), urlsplit(canonical_url)
            root_html = _1905_editorial_root(page_html, page_type)
            visible, claims = _1905_page_text(root_html), _1905_editorial_claims(page_html, page_type)
            actor = next((item for item in mapping["actors"] if item in visible), "")
            work_link = urlsplit(mapping["url"]).path in page_html
            exact_urls = all(part.scheme == "https" and part.netloc.lower() == expected.netloc.lower() and part.path == expected.path for part in (final, canonical))
            if not exact_urls or not ((mapping["chinese_title"] in visible and mapping["year"] in visible) or work_link) or not actor or len(visible) < 180 or not claims:
                raise ValueError("1905 editorial page failed allowlisted URL/canonical, identity/person anchor, body length, or claim checks")
            published_at = _1905_published_at(page_html)
            published_year_match = re.search(r"\b(20\d{2})\b", published_at)
            published_year = published_year_match.group(1) if published_year_match else ""
            page_release_dates = _1905_root_release_dates(root_html, page_type, default_year=published_year)
            if page_release_dates:
                time_sensitive.setdefault("release_date", set()).update(page_release_dates)
            page_audit.append({"url": page_url, "page_type": page_type, "published_at": published_at, "identity_actor_anchor": actor, "body_characters": len(visible)})
            for claim in claims:
                fact_class = _1905_editorial_fact_class(claim)
                if fact_class == "release":
                    time_sensitive.setdefault("release_date", set()).update(_1905_release_dates(claim, default_year=published_year))
                    continue
                atoms.append({"claim": claim, "source_text": claim, "source_locator": "validated_editorial_root", "url": page_url, "page_type": page_type, "published_at": published_at, "fact_class": fact_class, "characters": len(claim)})
        conflicts = {kind: sorted(values) for kind, values in time_sensitive.items() if len(values) > 1}
        expected_release_dates = mapping.get("expected_release_dates")
        if isinstance(expected_release_dates, list):
            observed_release_dates = sorted(time_sensitive.get("release_date", set()))
            if observed_release_dates != sorted(str(value) for value in expected_release_dates):
                raise ValueError("1905 direct editorial packet failed release-date acceptance contract")
        deduped, seen = [], set()
        for atom in atoms:
            # The same statement on a separately validated direct page remains a
            # distinct provenance-bearing atom; only duplicate extraction from the
            # same page is collapsed.
            normalized_claim = re.sub(r"\W+", "", atom["claim"]).lower()
            key = f"{atom['url']}::{normalized_claim}"
            if key in seen or (conflicts and re.search(r"上映|公映|定档|档期", atom["claim"])):
                continue
            seen.add(key)
            deduped.append(atom)
        urls, news_urls, classes = {a["url"] for a in deduped}, {a["url"] for a in deduped if a["page_type"] == "news"}, {a["fact_class"] for a in deduped}
        contract = {"direct_url_count": len(urls), "news_body_count": len(news_urls), "deduped_fact_count": len(deduped), "fact_character_count": sum(int(a["characters"]) for a in deduped), "fact_class_count": len(classes)}
        contract["qualifies_long_form"] = contract["direct_url_count"] >= 3 and contract["news_body_count"] >= 2 and contract["deduped_fact_count"] >= 12 and contract["fact_character_count"] >= 1200 and contract["fact_class_count"] >= 4
        if not contract["qualifies_long_form"]:
            raise ValueError("1905 direct editorial packet did not meet high-coverage contract")
        return {**source_meta, "fetch_path": "direct_live_explicit_mapped_1905_editorial_packet", "started_at": started_at, "finished_at": now_utc(), "duration_ms": elapsed_ms(timer), "success": True, "status": "focused_live_verified", "raw_url": pages[0]["url"], "fields_extracted": ["evidence_atoms", "packet_contract", "page_audit"], "live_subject": {"subject_id": subject_id, "title": subject_title, "url": subject_url}, "evidence_atoms": deduped, "packet_contract": contract, "page_audit": page_audit, "conflicting_time_sensitive_fact": conflicts, "top_signals": [], "sample_signals": [], "error": None}
    except Exception as exc:  # noqa: BLE001
        return {**source_meta, "fetch_path": "direct_live_explicit_mapped_1905_editorial_packet", "started_at": started_at, "finished_at": now_utc(), "duration_ms": elapsed_ms(timer), "success": False, "status": "ERROR", "fields_extracted": [], "evidence_atoms": [], "sample_signals": [], "error": repr(exc)}


def fetch_1905_same_work_context(live_subject: dict[str, Any] | None) -> dict[str, Any]:
    """Fail-closed 1905 plot context for one explicitly bridged Douban work only."""
    timer = time.perf_counter()
    started_at = now_utc()
    source_id = "1905_same_work_context"
    source_meta = {
        "source_id": source_id,
        "source_name": "1905同作品页面剧情上下文",
        "role": "P1C_1905_same_work_context",
        "signal_role": "article_body_signal",
        "narrative_roles": ["plot_character_context"],
        "allowed_use": ["explicitly mapped same-work public plot and character context only"],
        "can_be_main_narrative_source": True,
    }
    page_url = ""
    try:
        anchor = live_subject if isinstance(live_subject, dict) else {}
        subject_id = str(anchor.get("subject_id") or "").strip()
        subject_title = re.sub(r"\s+", " ", str(anchor.get("title") or "")).strip()
        subject_url = str(anchor.get("url") or "").strip()
        mapping = SAME_WORK_1905_REGISTRY.get(subject_id)
        if not mapping:
            raise ValueError("no explicit 1905 same-work mapping for Douban subject")
        if not subject_title or not subject_url or mapping["chinese_title"] not in subject_title or _title_year(subject_title) != mapping["year"]:
            raise ValueError("Douban live_subject does not match the explicit 1905 identity bridge")
        page_url = str(mapping["url"])
        fetched = _fetch_html_url(page_url, headers={"Referer": "https://www.1905.com/"})
        final_url = str(fetched.get("url") or "").strip()
        page_html = str(fetched.get("html") or "")
        canonical_url = _html_tag_value(page_html, "link", "rel", "canonical", "href") or _html_tag_value(page_html, "meta", "property", "og:url", "content")
        final_parts = urlsplit(final_url)
        canonical_parts = urlsplit(canonical_url)
        expected_parts = urlsplit(page_url)
        page_text = _1905_page_text(page_html)
        actor_found = next((actor for actor in mapping["actors"] if actor in page_text), "")
        context_candidates = [
            re.sub(r"\s+", " ", html.unescape(value)).strip()
            for value in re.findall(r"<(?:p|div|article|section)[^>]*>(.*?)</(?:p|div|article|section)>", page_html, flags=re.IGNORECASE | re.DOTALL)
        ]
        plot_match = re.search(r"剧\s*情\s+(.{20,600})", page_text)
        context = plot_match.group(1).strip() if plot_match else next(
            (item for item in context_candidates if len(_1905_page_text(item)) >= 20 and re.search(r"剧情|人物|角色|饰演|改编|导演|主演|作品", _1905_page_text(item))),
            "",
        )
        context = _1905_page_text(context)
        has_context_semantics = bool(re.search(r"剧情|人物|角色|饰演|改编|导演|主演|作品", context))
        if (
            final_parts.scheme != "https" or final_parts.netloc.lower() != expected_parts.netloc.lower() or final_parts.path != expected_parts.path
            or canonical_parts.scheme != "https" or canonical_parts.netloc.lower() != expected_parts.netloc.lower() or canonical_parts.path != expected_parts.path
            or mapping["chinese_title"] not in page_text or mapping["english_title"].lower() not in page_text.lower()
            or mapping["year"] not in page_text or not actor_found or len(context) < 20 or not has_context_semantics
        ):
            raise ValueError("1905 page failed exact URL/canonical, Chinese+English+year+actor identity, or minimum context checks")
        live_subject_out = {"subject_id": subject_id, "title": subject_title, "url": subject_url}
        signal = {"title": f"{mapping['chinese_title']} {mapping['english_title']} ({mapping['year']})", "description": context[:600], "url": page_url, "identity_actor_anchor": actor_found}
        return {
            **source_meta, "fetch_path": "direct_live_explicit_mapped_same_work_public_page", "started_at": started_at, "finished_at": now_utc(), "duration_ms": elapsed_ms(timer),
            "success": True, "status": "focused_live_verified", "raw_url": page_url,
            "fields_extracted": ["subject_id", "chinese_title", "english_title", "year", "actor_anchor", "canonical_url", "context", "url"],
            "signal_allowed_use_detail": ["explicitly mapped same-work plot and character context only; not audience review or social discussion evidence"],
            "forbidden_use": ["audience_review_claims", "social_discussion_claims", "verified_facts", "whole-platform generalization", "publish-ready evidence"],
            "live_subject": live_subject_out, "top_signals": [signal], "structured_signals": {"plot_character_context": [signal]},
            "sample_signals": [f"1905同作品页面剧情上下文《{mapping['chinese_title']}》：{context[:500]}"], "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            **source_meta, "fetch_path": "direct_live_explicit_mapped_same_work_public_page", "started_at": started_at, "finished_at": now_utc(), "duration_ms": elapsed_ms(timer),
            "success": False, "status": "ERROR", "raw_url": page_url or None, "fields_extracted": [],
            "signal_allowed_use_detail": ["explicitly mapped same-work plot and character context only; not audience review or social discussion evidence"],
            "forbidden_use": ["audience_review_claims", "social_discussion_claims", "verified_facts", "whole-platform generalization", "publish-ready evidence"],
            "sample_signals": [], "error": repr(exc),
        }


def _youtube_player_response(page_html: str) -> dict[str, Any]:
    """Decode YouTube's embedded player JSON without using search metadata."""
    marker = "ytInitialPlayerResponse"
    start = page_html.find(marker)
    if start < 0:
        raise ValueError("YouTube embedded player JSON is missing")
    object_start = page_html.find("{", start + len(marker))
    if object_start < 0:
        raise ValueError("YouTube embedded player JSON has no object")
    payload, _end = json.JSONDecoder().raw_decode(page_html[object_start:])
    if not isinstance(payload, dict):
        raise ValueError("YouTube embedded player JSON is not an object")
    return payload


def _official_page_fields(page_html: str, parser: str) -> tuple[str, str, str, str]:
    if parser == "youtube":
        payload = _youtube_player_response(page_html)
        details = payload.get("videoDetails") if isinstance(payload.get("videoDetails"), dict) else {}
        microformat = payload.get("microformat") if isinstance(payload.get("microformat"), dict) else {}
        renderer = microformat.get("playerMicroformatRenderer") if isinstance(microformat.get("playerMicroformatRenderer"), dict) else {}
        title = re.sub(r"\s+", " ", str(details.get("title") or "")).strip()
        description = re.sub(r"\s+", " ", str(details.get("shortDescription") or "")).strip()
        upload_date = str(renderer.get("uploadDate") or renderer.get("publishDate") or "").strip()
        return title, description, upload_date, description
    if parser == "focus":
        title_match = re.search(r"<title[^>]*>(.*?)</title>", page_html, flags=re.IGNORECASE | re.DOTALL)
        title = _1905_page_text(title_match.group(1)) if title_match else ""
        description = _html_tag_value(page_html, "meta", "property", "og:description", "content") or _html_tag_value(page_html, "meta", "name", "description", "content")
        visible_text = _1905_page_text(page_html)
        date_match = re.search(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+(\d{4})\b", visible_text)
        return title, re.sub(r"\s+", " ", description).strip(), date_match.group(0) if date_match else "", visible_text
    raise ValueError("unsupported official same-work parser")


def fetch_official_same_work_context(live_subject: dict[str, Any] | None) -> dict[str, Any]:
    """Fail closed on one exact official page for each explicitly mapped Douban id."""
    timer = time.perf_counter()
    started_at = now_utc()
    source_meta = {
        "source_id": "official_same_work_context", "source_name": "官方同作品页面剧情上下文",
        "role": "P1C_official_same_work_context", "signal_role": "article_body_signal",
        "narrative_roles": ["plot_character_context"],
        "allowed_use": ["explicitly mapped official same-work plot and character context only"],
        "can_be_main_narrative_source": True,
    }
    page_url = ""
    try:
        anchor = live_subject if isinstance(live_subject, dict) else {}
        subject_id = str(anchor.get("subject_id") or "").strip()
        subject_title = re.sub(r"\s+", " ", str(anchor.get("title") or "")).strip()
        subject_url = str(anchor.get("url") or "").strip()
        mapping = OFFICIAL_SAME_WORK_REGISTRY.get(subject_id)
        if not mapping:
            raise ValueError("no explicit official same-work mapping for Douban subject")
        expected_subject_url = f"https://movie.douban.com/subject/{subject_id}/"
        if (subject_url != expected_subject_url or _title_year(subject_title) != mapping["subject_year"]
                or not any(title in subject_title for title in mapping["chinese_titles"])):
            raise ValueError("Douban live_subject does not match the explicit official identity bridge")
        page_url = str(mapping["url"])
        fetched = _fetch_html_url(page_url, headers={"Referer": page_url})
        final_url = str(fetched.get("url") or "").strip()
        if final_url != page_url:
            raise ValueError("official page final URL differs from exact mapped URL")
        page_html = str(fetched.get("html") or "")
        document_title, context, page_date, identity_text = _official_page_fields(page_html, str(mapping["parser"]))
        identity_haystack = f"{document_title} {identity_text}"
        director = next((item for item in mapping["directors"] if item.lower() in identity_haystack.lower()), "")
        actor = next((item for item in mapping["actors"] if item.lower() in identity_haystack.lower()), "")
        context_anchor_count = sum(1 for item in mapping["context_anchors"] if item.lower() in context.lower())
        if (mapping["english_title"].lower() not in document_title.lower()
                or mapping["official_year"] not in page_date or not director or not actor
                or len(context) < 20 or context_anchor_count < 2):
            raise ValueError("official page failed English title/year/director/actor identity or concrete-context checks")
        live_subject_out = {"subject_id": subject_id, "title": subject_title, "url": subject_url}
        signal = {"title": document_title[:160], "description": context[:600], "url": page_url,
                  "identity_director_anchor": director, "identity_actor_anchor": actor}
        return {
            **source_meta, "fetch_path": "direct_live_explicit_mapped_official_page", "started_at": started_at,
            "finished_at": now_utc(), "duration_ms": elapsed_ms(timer), "success": True,
            "status": "focused_live_verified", "raw_url": page_url,
            "fields_extracted": ["subject_id", "english_title", "subject_year", "official_year", "director_anchor", "actor_anchor", "context", "url"],
            "signal_allowed_use_detail": ["official same-work plot and character context only; not search, review, or social evidence"],
            "forbidden_use": ["audience_review_claims", "social_discussion_claims", "whole-platform generalization", "publish-ready evidence"],
            "live_subject": live_subject_out, "top_signals": [signal],
            "structured_signals": {"plot_character_context": [signal]},
            "sample_signals": [f"官方同作品页面剧情上下文《{mapping['english_title']}》：{context[:500]}"], "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            **source_meta, "fetch_path": "direct_live_explicit_mapped_official_page", "started_at": started_at,
            "finished_at": now_utc(), "duration_ms": elapsed_ms(timer), "success": False, "status": "ERROR",
            "raw_url": page_url or None, "fields_extracted": [],
            "signal_allowed_use_detail": ["official same-work plot and character context only; not search, review, or social evidence"],
            "forbidden_use": ["audience_review_claims", "social_discussion_claims", "whole-platform generalization", "publish-ready evidence"],
            "sample_signals": [], "error": repr(exc),
        }


def _extract_douban_subject_id(subject: dict[str, Any]) -> str | None:
    subject_id = subject.get("id")
    if subject_id:
        return str(subject_id)
    match = re.search(r"/subject/(\d+)/", str(subject.get("url") or ""))
    return match.group(1) if match else None


def _normalize_douban_comment(text: Any, max_chars: int = 260) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    return cleaned[:max_chars]


def _is_valid_source_url(value: Any) -> bool:
    parsed = urlsplit(str(value or ""))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _douban_discussion_signal_error(live_subject: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a deliberately non-actionable normalized record after a bad fetch."""
    live_subject = live_subject or {}
    subject_id = str(live_subject.get("subject_id") or "")
    result: dict[str, Any] = {
        "platform": "douban",
        "comment_samples": [],
        "status": "ERROR",
    }
    if re.fullmatch(r"\d+", subject_id):
        result["work_key"] = f"douban:{subject_id}"
    return result


_DOUBAN_REPEATED_CLUE_STOPWORDS = frozenset({
    "这部", "电影", "影片", "作品", "剧情", "故事", "角色", "人物", "观众", "短评", "评论",
    "感觉", "觉得", "真的", "还是", "这个", "那个", "一个", "一些", "可以", "不是", "没有",
    "什么", "因为", "所以", "如果", "以及", "但是", "而且", "就是", "很好", "不错", "普通",
})


def _normalize_douban_raw_comment_samples(
    raw_comment_samples: Any,
    *,
    subject_id: str,
) -> list[dict[str, str]]:
    """Validate a bounded, individually attributable direct Douban sample set."""
    if raw_comment_samples is None:
        return []
    if not isinstance(raw_comment_samples, list) or len(raw_comment_samples) > DOUBAN_DISCUSSION_SAMPLE_LIMIT:
        raise ValueError("douban raw comment samples must be a bounded list")
    normalized: list[dict[str, str]] = []
    sample_ids: set[str] = set()
    for raw_sample in raw_comment_samples:
        if not isinstance(raw_sample, dict):
            raise ValueError("douban raw comment samples require objects")
        sample_id = str(raw_sample.get("id") or "").strip()
        sample_url = str(raw_sample.get("url") or "").strip()
        text = raw_sample.get("content")
        if not sample_id or not isinstance(text, str) or not text.strip() or not _is_valid_source_url(sample_url):
            raise ValueError("douban raw comment samples require id, URL, and text")
        parsed = urlsplit(sample_url)
        if parsed.netloc != "movie.douban.com" or not re.search(rf"/subject/{re.escape(subject_id)}(?:/|$)", parsed.path):
            raise ValueError("douban raw comment samples must match the work identity")
        if sample_id in sample_ids:
            raise ValueError("douban raw comment samples require unique sample ids")
        sample_ids.add(sample_id)
        # Preserve every raw direct field verbatim for audit; matching is normalized separately.
        normalized.append(dict(raw_sample))
    return normalized


def _douban_raw_samples_from_abstract(abstract_subject: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Use an explicit direct API sample list when present; never synthesize one."""
    # The probed endpoint currently exposes only ``short_comment``.  Keep this
    # bounded capability adapter-local so a documented direct list can be used
    # without HTML scraping, search results, or a second source.
    for key in ("short_comments", "comment_samples"):
        if key in abstract_subject:
            value = abstract_subject[key]
            if not isinstance(value, list):
                raise ValueError(f"douban abstract {key} must be a list")
            return value[:DOUBAN_DISCUSSION_SAMPLE_LIMIT]
    return None


def _douban_clue_keywords(text: str) -> set[str]:
    """Use mechanical exact matching only; no themes, sentiment, or LLM inference."""
    normalized = re.sub(r"\s+", " ", text).strip().casefold()
    candidates = {
        word for word in re.findall(r"[a-z0-9][a-z0-9_-]{1,}", normalized)
        if word not in _DOUBAN_REPEATED_CLUE_STOPWORDS
    }
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
        for width in range(2, min(4, len(run)) + 1):
            for start in range(len(run) - width + 1):
                keyword = run[start:start + width]
                if keyword not in _DOUBAN_REPEATED_CLUE_STOPWORDS and "人物" not in keyword and "角色" not in keyword:
                    candidates.add(keyword)
    return candidates


def _douban_repeated_clues(samples: list[dict[str, str]]) -> list[dict[str, Any]]:
    sample_ids_by_keyword: dict[str, list[str]] = {}
    for sample in samples:
        for keyword in _douban_clue_keywords(str(sample["content"])):
            sample_ids_by_keyword.setdefault(keyword, []).append(sample["id"])
    clues = [
        {"keyword": keyword, "count": len(sample_ids), "sample_ids": sample_ids}
        for keyword, sample_ids in sample_ids_by_keyword.items()
        if len(sample_ids) >= DOUBAN_REPEATED_CLUE_MIN_OCCURRENCES
    ]
    return sorted(clues, key=lambda clue: (-int(clue["count"]), str(clue["keyword"])))


def _normalize_douban_discussion_signal(
    *,
    subject_id: Any,
    title: Any,
    source_url: Any,
    short_comment: Any,
    rating: Any,
    fetched_at: str,
    raw_comment_samples: Any = None,
) -> dict[str, Any]:
    """Normalize one verified Douban short comment without interpreting its meaning."""
    normalized_subject_id = str(subject_id or "")
    work_title = re.sub(r"\s+", " ", str(title or "")).strip()
    if not re.fullmatch(r"\d+", normalized_subject_id):
        raise ValueError("douban discussion signal requires a numeric subject id")
    if not work_title:
        raise ValueError("douban discussion signal requires a work title")
    if not _is_valid_source_url(source_url):
        raise ValueError("douban discussion signal requires a valid source URL")
    if not isinstance(short_comment, dict):
        raise ValueError("douban discussion signal requires a short comment object")
    raw_text = short_comment.get("content")
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValueError("douban discussion signal requires comment source text")

    raw_samples = _normalize_douban_raw_comment_samples(raw_comment_samples, subject_id=normalized_subject_id)
    sample: dict[str, Any] = {"text": raw_text, "rating": rating}
    for key in ("id", "url"):
        value = short_comment.get(key)
        if value not in (None, ""):
            sample[key] = value
    result = {
        "platform": "douban",
        "work_key": f"douban:{normalized_subject_id}",
        "work_title": work_title,
        "source_url": str(source_url),
        "fetched_at": fetched_at,
        "comment_samples": [sample],
        "rating": rating,
        "sentiment_hint": _sentiment_keyword_from_rating(rating),
        "status": "focused_live_verified",
    }
    result["sample_window"] = {
        "count": len(raw_samples),
        "source": "douban_subject_abstract.short_comments",
        "collected_at": fetched_at,
        "min_samples": DOUBAN_REPEATED_CLUE_MIN_SAMPLES,
        "status": "complete" if len(raw_samples) >= DOUBAN_REPEATED_CLUE_MIN_SAMPLES else "insufficient_samples",
    }
    if raw_samples:
        result["raw_comment_samples"] = raw_samples
    if len(raw_samples) >= DOUBAN_REPEATED_CLUE_MIN_SAMPLES:
        result["repeated_clues"] = _douban_repeated_clues(raw_samples)
        # Explicitly isolated metadata: discovery help only, never a consensus or generic gate.
        result["repeated_clues_allowed_use"] = "writer_discovery_only"
        result["repeated_clues_forbidden_use"] = [
            "consensus_claim", "controversy_claim", "public_opinion_claim",
            "eligibility", "publishing", "score", "tier", "ready_review_rendering", "cron",
        ]
    return result


def _signal_text(signal: Any) -> str:
    if isinstance(signal, str):
        return re.sub(r"\s+", " ", signal).strip()
    if not isinstance(signal, dict):
        return ""
    parts = [
        signal.get("title"),
        signal.get("summary"),
        signal.get("content"),
        signal.get("description"),
        signal.get("note"),
        signal.get("word"),
        signal.get("topic"),
        signal.get("reason"),
        signal.get("claim"),
    ]
    text = " ".join(str(part or "") for part in parts)
    return re.sub(r"\s+", " ", text).strip()


def _source_signal_items(source: dict[str, Any]) -> list[Any]:
    explicit = source.get("top_signals") or source.get("signals") or source.get("items") or source.get("extracted_items")
    if isinstance(explicit, list) and explicit:
        return explicit
    sample_signals = source.get("sample_signals")
    if isinstance(sample_signals, list) and sample_signals:
        return sample_signals
    structured = source.get("structured_signals")
    items: list[Any] = []
    if isinstance(structured, dict):
        for value in structured.values():
            if isinstance(value, list):
                items.extend(value)
            elif isinstance(value, dict):
                items.append(value)
            elif isinstance(value, str):
                items.append(value)
    return items


def export_backfill_article_rows(source_results: list[dict[str, Any]], query: str = "") -> list[dict[str, Any]]:
    query_text = re.sub(r"\s+", " ", str(query or "")).strip()
    matched_rows: list[dict[str, Any]] = []
    fallback_rows: list[dict[str, Any]] = []
    for source in source_results:
        if not source.get("success"):
            continue
        source_id = str(source.get("source_id") or "")
        # This finite direct-body packet is writer-only supplementary evidence.
        # Preserve its atoms intact for the batch adapter and bypass every generic
        # signal/source/role route below.
        if source_id == "independent_direct_source_packet":
            live_subject = source.get("live_subject") if isinstance(source.get("live_subject"), dict) else {}
            subject_id = str(live_subject.get("subject_id") or "").strip()
            atoms = source.get("supplementary_attributed_evidence")
            if not subject_id or not isinstance(atoms, list) or not all(isinstance(atom, dict) for atom in atoms):
                continue
            fallback_rows.append({
                "source": source_id,
                "source_id": source_id,
                "source_name": str(source.get("source_name") or source_id),
                "requires_attribution_in_output": source.get("requires_attribution_in_output") is True,
                "supplementary_attributed_evidence": atoms,
                "work_key": f"douban:{subject_id}",
                "work_identity": f"douban:{subject_id}",
                "work_title": str(live_subject.get("title") or "").strip() or None,
                "live_subject": live_subject,
            })
            continue
        signal_role = str(source.get("signal_role") or "")
        if signal_role not in {"social_discussion_signal", "audience_reaction_signal", "article_body_signal"}:
            continue
        source_name = str(source.get("source_name") or source_id or "unknown")
        live_subject = source.get("live_subject") if isinstance(source.get("live_subject"), dict) else {}
        subject_id = str(live_subject.get("subject_id") or "").strip()
        work_key = f"douban:{subject_id}" if subject_id else ""
        work_title = str(live_subject.get("title") or "").strip()
        source_type = "article"
        if signal_role == "social_discussion_signal":
            source_type = "topic"
        elif signal_role == "audience_reaction_signal":
            source_type = "commentary"
        signals = _source_signal_items(source)
        # A direct editorial packet is deliberately exported atom-by-atom. Never
        # flatten it into a synthetic marketing summary that loses provenance.
        if source_id == "1905_same_work_editorial_packet":
            contract = source.get("packet_contract") if isinstance(source.get("packet_contract"), dict) else {}
            if not contract.get("qualifies_long_form"):
                continue
            signals = source.get("evidence_atoms") if isinstance(source.get("evidence_atoms"), list) else []
        for index, signal in enumerate(signals[:50], start=1):
            text = _signal_text(signal)
            if not text:
                continue
            if isinstance(signal, dict):
                title = str(signal.get("title") or signal.get("topic") or signal.get("word") or signal.get("note") or text[:80]).strip()
                url = str(signal.get("url") or signal.get("link") or source.get("raw_url") or "").strip()
                rank = signal.get("rank") or index
                hot_score = signal.get("hot_score") or signal.get("score") or signal.get("heat") or signal.get("gdi")
                summary = str(signal.get("summary") or signal.get("description") or signal.get("note") or text[:140]).strip()
            else:
                title = text[:80]
                url = str(source.get("raw_url") or "").strip()
                rank = index
                hot_score = None
                summary = text[:140]
            if not title:
                continue
            content = text or summary or title
            row = {
                "source": source_id,
                "source_name": source_name,
                "signal_role": signal_role,
                "narrative_roles": list(source.get("narrative_roles") or []),
                "source_type": source_type,
                "content_type": source_type,
                "title": title[:120],
                "summary": summary[:240],
                "content": content[:1200],
                "url": url,
                "rank_date": datetime.now().strftime("%F"),
                "rank": rank,
                "hot_score": hot_score,
                "sample_evidence": f"live_backfill:{source_id}",
                "article_route_reason": f"live backfill from {source_name}" + (f" for {query_text}" if query_text else ""),
                "body_fetch_status": "live_signal_backfill",
                "next_fetch_hint": source_name,
                # A Douban subject id is the stable cross-platform identity.  Keep
                # it on every exported row, including Letterboxd plot context.
                "work_key": work_key or None,
                "work_identity": work_key or None,
                "work_title": work_title or None,
                "live_subject": live_subject or None,
                "evidence_atom": signal if source_id == "1905_same_work_editorial_packet" and isinstance(signal, dict) else None,
                "direct_editorial_packet_contract": source.get("packet_contract") if source_id == "1905_same_work_editorial_packet" else None,
            }
            if query_text and (query_text in text or query_text in title):
                matched_rows.append(row)
            else:
                fallback_rows.append(row)
    same_work_context_rows = [
        row for row in fallback_rows
        if row.get("source") in {"letterboxd_work_context", "1905_same_work_editorial_packet"}
    ]
    return (matched_rows + same_work_context_rows) if matched_rows else fallback_rows


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


def _first_list(value: Any, keys: tuple[str, ...]) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return []
    for key in keys:
        nested = value.get(key)
        if isinstance(nested, list):
            return nested
        if isinstance(nested, dict):
            child = _first_list(nested, keys)
            if child:
                return child
    for nested in value.values():
        if isinstance(nested, dict):
            child = _first_list(nested, keys)
            if child:
                return child
    return []


def _first_present(source: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in source and source[key] not in (None, ""):
            return source[key]
    return None


def _normalize_maoyan_row(row: dict[str, Any], index: int) -> dict[str, Any] | None:
    title = _first_present(row, ("movieName", "name", "nm", "title"))
    if not title:
        return None
    metrics = {
        "sum_box_desc": _first_present(row, ("sumBoxDesc", "boxSplitUnit", "boxInfo", "boxDesc")),
        "show_count": _first_present(row, ("showCount", "showCnt", "showCountDesc")),
        "box_rate": _first_present(row, ("boxRate", "boxRatio", "boxRateDesc")),
        "show_count_rate": _first_present(row, ("showCountRate", "showRate", "showCountRateDesc")),
        "avg_seat_view": _first_present(row, ("avgSeatView", "avgSeatViewDesc", "avgShowView")),
    }
    return {"rank": _first_present(row, ("rank", "rankNum")) or index, "title": str(title).strip()[:120], "release_info": _first_present(row, ("releaseInfo", "releaseInfoDesc", "movieInfo")), "metrics": metrics, "url": row.get("url") or "https://piaofang.maoyan.com/dashboard/movie"}


def _fallback_maoyan_observation() -> dict[str, Any]:
    payload = _fetch_json_url(MAOYAN_REALTIME_BOXOFFICE_URL, headers={"Referer": "https://piaofang.maoyan.com/dashboard/movie"})
    rows = _first_list(payload, ("list", "movieList", "items", "data"))
    items = [item for idx, row in enumerate(rows, start=1) if isinstance(row, dict) for item in [_normalize_maoyan_row(row, idx)] if item]
    if not items:
        raise ValueError("maoyan realtime boxoffice returned no usable movie rows")
    return {"raw_url": MAOYAN_REALTIME_BOXOFFICE_URL, "access_status": "PASS_fallback_live_json", "extracted_items": items[:5], "risk_notes": None}


def _fallback_maoyan_candidate(observation: dict[str, Any]) -> dict[str, Any]:
    items = observation.get("extracted_items") or []
    lead = items[0] if items else {}
    return {"title": f"《{lead.get('title', '未知影片')}》实时票房信号观察", "primary_anchor": lead.get("title"), "source_boundary": "fallback live JSON; market signal only"}


def _normalize_guduo_row(row: dict[str, Any], category: str, index: int) -> dict[str, Any] | None:
    name = _first_present(row, ("name", "title", "dramaName", "movieName", "showName"))
    if not name:
        return None
    return {"rank": _first_present(row, ("rank", "ranking", "rankNum")) or index, "name": str(name).strip()[:120], "category": category, "gdi": _first_present(row, ("gdi", "hot", "heat", "index", "value")), "rise": _first_present(row, ("rise", "trend", "change")), "platforms": _first_present(row, ("platforms", "platform", "playPlatform")), "release_date": _first_present(row, ("releaseDate", "release_date", "date")), "days": _first_present(row, ("days", "onlineDays"))}


def _fallback_guduo_rank(category: str, rank_date: str | None = None) -> dict[str, Any]:
    params = {"type": "DAILY", "category": category, "platformId": ""}
    if rank_date:
        params["date"] = rank_date
    url = f"{GUDUO_RANK_URL}?{urlencode(params)}"
    payload = _fetch_json_url(url, headers={"Referer": "http://d2.guduomedia.com/"})
    rows = _first_list(payload, ("list", "items", "rankList", "data"))
    items = [item for idx, row in enumerate(rows, start=1) if isinstance(row, dict) for item in [_normalize_guduo_row(row, category, idx)] if item]
    return {"category": category, "rank_date": rank_date, "item_count": len(items), "items": items[:10], "raw_url": url}


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


def _terminal_year(value: Any) -> str | None:
    normalized = re.sub(r"[\u200e\u200f\u202a-\u202e]", "", re.sub(r"\s+", " ", str(value or ""))).strip()
    match = re.search(r"\((\d{4})\)\s*$", normalized)
    return match.group(1) if match else None


def _title_year(value: Any) -> str | None:
    normalized = re.sub(r"[\u200e\u200f\u202a-\u202e]", "", re.sub(r"\s+", " ", str(value or ""))).strip()
    years = re.findall(r"\((\d{4})\)", normalized)
    return years[-1] if len(set(years)) == 1 else None


def _bilibili_anchor_identity(title: str) -> tuple[str, str, str | None]:
    """Return Chinese search title, optional English original title, and terminal release year."""
    normalized = re.sub(r"[\u200e\u200f\u202a-\u202e]", "", re.sub(r"\s+", " ", title)).strip()
    year = _terminal_year(normalized)
    title_without_year = re.sub(r"\s*\(\d{4}\)\s*$", "", normalized).strip()
    work_title = title_without_year.split(" ", 1)[0].strip("《》 ")
    english_match = re.search(r"([A-Za-z][A-Za-z0-9 .,'’:\-]*?)\s*$", title_without_year)
    english_title = re.sub(r"\s+", " ", english_match.group(1)).strip(" .") if english_match else ""
    return work_title, english_title, year


def fetch_bilibili_same_work_enrichment(live_subject: dict[str, Any] | None) -> dict[str, Any]:
    """Fetch bounded Bilibili candidates only after strict title/year identity checks."""
    timer = time.perf_counter()
    started_at = now_utc()
    source_id = "bilibili_work_detail"
    source_meta = {
        "source_id": source_id,
        "source_name": "B站同作品视频详情 live signal",
        "role": "P1C_bilibili_same_work_discussion",
        "signal_role": "social_discussion_signal",
        "narrative_roles": ["social_discussion"],
        "allowed_use": ["same-work social discussion signal"],
        "can_be_main_narrative_source": True,
    }
    anchor = live_subject if isinstance(live_subject, dict) else {}
    title = re.sub(r"[\u200e\u200f\u202a-\u202e]", "", re.sub(r"\s+", " ", str(anchor.get("title") or ""))).strip()
    work_title, english_title, anchor_year = _bilibili_anchor_identity(title)
    search_url = ""
    detail_url = ""
    failure_reason: str | None = None
    try:
        if not anchor.get("subject_id") or not title or not anchor.get("url") or not work_title:
            raise ValueError("douban live_subject is missing subject_id, title, or url")
        keyword = " ".join(part for part in (work_title, english_title, anchor_year or "") if part)
        search_url = BILIBILI_VIDEO_SEARCH_URL.format(query=urlencode({"search_type": "video", "keyword": keyword, "page": 1}))
        payload = _fetch_json_url(search_url, headers={"Referer": "https://www.bilibili.com/", "Origin": "https://www.bilibili.com"})
        if payload.get("code") not in (0, None):
            raise PermissionError(f"bilibili video search returned code={payload.get('code')}: {payload.get('message')}")
        candidates = ((payload.get("data") or {}).get("result") or []) if isinstance(payload, dict) else []
        checked_candidate = False
        for candidate in [row for row in candidates[:5] if isinstance(row, dict)]:
            bvid = str(candidate.get("bvid") or "").strip()
            candidate_title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(candidate.get("title") or ""))).strip()
            if not bvid or work_title not in candidate_title:
                continue
            checked_candidate = True
            if anchor_year and _title_year(candidate_title) != anchor_year:
                failure_reason = "same_work_year_mismatch"
                continue
            detail_url = BILIBILI_VIDEO_DETAIL_URL.format(bvid=quote(bvid))
            detail_payload = _fetch_json_url(detail_url, headers={"Referer": f"https://www.bilibili.com/video/{bvid}", "Origin": "https://www.bilibili.com"})
            if detail_payload.get("code") not in (0, None):
                raise PermissionError(f"bilibili video detail returned code={detail_payload.get('code')}: {detail_payload.get('message')}")
            detail = detail_payload.get("data") if isinstance(detail_payload, dict) else None
            if not isinstance(detail, dict) or str(detail.get("bvid") or "").strip() != bvid:
                continue
            detail_title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(detail.get("title") or ""))).strip()
            description = re.sub(r"\s+", " ", str(detail.get("desc") or "")).strip()
            video_url = f"https://www.bilibili.com/video/{bvid}"
            if anchor_year and _title_year(detail_title) != anchor_year:
                failure_reason = "same_work_year_mismatch"
                continue
            if work_title not in detail_title or len(description) < 20:
                continue
            stat = detail.get("stat") if isinstance(detail.get("stat"), dict) else {}
            signal = {"title": detail_title[:120], "description": description[:500], "url": video_url, "bvid": bvid, "view": stat.get("view"), "danmaku": stat.get("danmaku"), "like": stat.get("like")}
            return {
                **source_meta, "fetch_path": "direct_live_same_work", "started_at": started_at, "finished_at": now_utc(), "duration_ms": elapsed_ms(timer),
                "success": True, "status": "focused_live_verified", "raw_url": detail_url, "search_url": search_url,
                "fields_extracted": ["subject_id", "bvid", "title", "desc", "url", "view", "danmaku", "like"],
                "signal_allowed_use_detail": ["same-work social discussion signal extraction"],
                "forbidden_use": ["verified_facts", "whole-network generalization", "single-video conclusion", "publish-ready evidence"],
                "live_subject": {"subject_id": str(anchor["subject_id"]), "title": title, "url": str(anchor["url"])},
                "top_signals": [signal], "structured_signals": {"social_discussion": [signal]},
                "sample_signals": [f"B站同作品讨论《{work_title}》：{description}"], "error": None,
            }
        if anchor_year and (checked_candidate or candidates):
            failure_reason = "same_work_year_mismatch"
            raise ValueError("bilibili candidates failed exact same-work terminal-year identity checks")
        raise ValueError("bilibili video search returned no exact same-work BV candidate")
    except Exception as exc:  # noqa: BLE001
        error_text = repr(exc)
        inaccessible_markers = ("401", "403", "412", "-352", "login", "forbidden", "risk", "access")
        result = {
            **source_meta, "fetch_path": "direct_live_same_work", "started_at": started_at, "finished_at": now_utc(), "duration_ms": elapsed_ms(timer),
            "success": False, "status": "live_inaccessible" if any(marker in error_text.lower() for marker in inaccessible_markers) else "ERROR",
            "raw_url": detail_url or search_url or None, "search_url": search_url or None, "fields_extracted": [],
            "signal_allowed_use_detail": ["same-work social discussion signal extraction"],
            "forbidden_use": ["verified_facts", "whole-network generalization", "single-video conclusion", "publish-ready evidence"],
            "sample_signals": [], "error": error_text,
        }
        if failure_reason:
            result["failure_reason"] = failure_reason
        return result




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
    if maoyan is not None:
        observation = maoyan.fetch_and_build_maoyan_observation()
        candidate = maoyan.generate_film_tv_article_candidate(observation)
    else:
        observation = _fallback_maoyan_observation()
        candidate = _fallback_maoyan_candidate(observation)
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
    results: dict[str, Any] = {}
    category_errors: dict[str, str] = {}
    for category in ["NETWORK_DRAMA", "NETWORK_VARIETY", "NETWORK_MOVIE", "ALL_ANIME"]:
        last_error: str | None = None
        for _attempt in range(2):
            try:
                if guduo is not None:
                    result = guduo.fetch_rank(category, "DAILY", rank_date, offline_json=None)
                    results[category] = guduo.to_dict(result)
                else:
                    results[category] = _fallback_guduo_rank(category, rank_date)
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


def _audience_reaction_error(search_url: str, started_at: str, timer: float, exc: Exception, live_subject: dict[str, Any] | None = None) -> dict[str, Any]:
    result = {
        **_source_meta("douban_reviews_discussions"),
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
        "discussion_signal": _douban_discussion_signal_error(live_subject),
    }
    if live_subject:
        result["live_subject"] = live_subject
    return result


def _fetch_audience_reaction_for_subject(subject: dict[str, Any], search_url: str) -> dict[str, Any]:
    timer = time.perf_counter()
    started_at = now_utc()
    subject_id = _extract_douban_subject_id(subject)
    subject_title = str(subject.get("title") or "unknown")
    subject_url = str(subject.get("url") or "")
    live_subject = {"subject_id": subject_id or "", "title": subject_title, "url": subject_url}
    try:
        if not subject_id:
            raise ValueError("douban subject search returned no subject id")
        abstract_url = DOUBAN_SUBJECT_ABSTRACT_URL.format(subject_id=subject_id)
        abstract_payload = _fetch_json_url(abstract_url)
        abstract_subject = abstract_payload.get("subject") or {}
        short_comment = abstract_subject.get("short_comment") or {}
        comment = _normalize_douban_comment(short_comment.get("content"))
        if not comment:
            raise ValueError("douban abstract returned no short_comment.content")
        title = abstract_subject.get("title")
        rate = abstract_subject.get("rate") or subject.get("rate")
        source_url = abstract_subject.get("url")
        live_subject = {"subject_id": subject_id, "title": title or "", "rate": rate, "url": source_url or ""}
        finished_at = now_utc()
        raw_comment_samples = _douban_raw_samples_from_abstract(abstract_subject)
        discussion_signal = _normalize_douban_discussion_signal(
            subject_id=subject_id,
            title=title,
            source_url=source_url,
            short_comment=short_comment,
            rating=rate,
            fetched_at=finished_at,
            raw_comment_samples=raw_comment_samples,
        )
        return {
            **_source_meta("douban_reviews_discussions"),
            "fetch_path": "direct_live",
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": elapsed_ms(timer),
            "success": True,
            "status": "focused_live_verified",
            "raw_url": abstract_url,
            "search_url": search_url,
            "fields_extracted": ["subject_id", "title", "rate", "short_comment", "sentiment_keyword"],
            "signal_allowed_use_detail": ["audience emotion extraction", "review/comment signal extraction", "discussion pressure extraction", "sentiment keyword extraction"],
            "forbidden_use": ["verified_facts", "whole-network generalization", "single-comment conclusion", "publish-ready evidence"],
            "live_subject": live_subject,
            "structured_signals": {"audience_emotion": _sentiment_keyword_from_rating(rate), "review_comments": [comment], "social_discussion": [comment], "sentiment_keyword": _sentiment_keyword_from_rating(rate)},
            "sample_signals": [f"《{title}》短评样本显示：{comment}", "该 live source 只提供观众短评、情绪和讨论压力，不提供 verified facts。"],
            "discussion_signal": discussion_signal,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return _audience_reaction_error(search_url, started_at, timer, exc, live_subject)


def fetch_audience_reaction_signals(subject_limit: int = DOUBAN_LIVE_SUBJECT_LIMIT) -> list[dict[str, Any]]:
    """Fetch isolated Douban audience evidence for up to N distinct ranked subjects."""
    search_url = DOUBAN_LIVE_SEARCH_URL.format(tag=quote("热门"), page_limit=max(1, subject_limit))
    try:
        search_payload = _fetch_json_url(search_url)
        subjects = search_payload.get("subjects") or []
        if not subjects:
            raise ValueError("douban subject search returned no subjects")
    except Exception as exc:  # noqa: BLE001
        return [_audience_reaction_error(search_url, now_utc(), time.perf_counter(), exc)]

    results: list[dict[str, Any]] = []
    seen_subject_ids: set[str] = set()
    for subject in subjects:
        if not isinstance(subject, dict):
            continue
        subject_id = _extract_douban_subject_id(subject)
        if not subject_id or subject_id in seen_subject_ids:
            continue
        seen_subject_ids.add(subject_id)
        results.append(_fetch_audience_reaction_for_subject(subject, search_url))
        if len(results) >= subject_limit:
            break
    return results or [_audience_reaction_error(search_url, now_utc(), time.perf_counter(), ValueError("douban subject search returned no usable subject ids"))]


def fetch_audience_reaction_signal() -> dict[str, Any]:
    """Backward-compatible single-subject view of the conservative multi-work fetch."""
    return fetch_audience_reaction_signals(subject_limit=1)[0]


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


def build_topic(
    maoyan_items: list[dict[str, Any]],
    drama_items: list[dict[str, Any]],
    movie_items: list[dict[str, Any]],
    article_body_result: dict[str, Any] | None = None,
    audience_result: dict[str, Any] | None = None,
    social_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if maoyan_items:
        lead = maoyan_items[0]
        return {"topic_type": "boxoffice_market_observation", "title": f"《{lead.get('title')}》冲上票房第一，但真正该紧张的不是第二名", "score": 88, "primary_anchor": lead.get("title"), "reason": "P0 猫眼实时票房有明确榜首与追赶者，P1 骨朵热度榜可补充注意力竞争背景。"}
    if drama_items:
        lead = drama_items[0]
        return {"topic_type": "streaming_heat_observation", "title": f"《{lead.get('name')}》登顶热度榜，长视频又进入一轮抢人大战", "score": 82, "primary_anchor": lead.get("name"), "reason": "骨朵榜单有明确剧集榜首与平台热度信号；猫眼不可用时作为同池 fallback。"}
    if movie_items:
        lead = movie_items[0]
        return {"topic_type": "web_movie_heat_observation", "title": f"《{lead.get('name')}》排到网影第一，平台小档期正在变密", "score": 80, "primary_anchor": lead.get("name"), "reason": "骨朵网络电影榜可形成平台小档期观察；猫眼不可用时作为同池 fallback。"}
    if audience_result and audience_result.get("success"):
        signal = ((audience_result.get("sample_signals") or [""])[0] or "观众反应源出现可写的争议与情绪样本")
        title = signal.split("：", 1)[-1].strip("《》 ")[:28] or "观众反应里出现新的影视讨论切口"
        return {"topic_type": "audience_reaction_candidate", "title": title, "score": 84, "primary_anchor": title, "reason": "观众反应源提供 audience_sentiment / review_comments / social_discussion，可与其他叙事源组成候选稿。"}
    successful_social = [src for src in (social_results or []) if src and src.get("success")]
    if successful_social:
        signal = ((successful_social[0].get("sample_signals") or [""])[0] or "社交平台出现可跟进的影视讨论信号")
        title = signal.split("：", 1)[-1].strip()[:28] or "社交平台出现可跟进的影视讨论信号"
        return {"topic_type": "social_discussion_candidate", "title": title, "score": 82, "primary_anchor": title, "reason": "社交讨论源提供 hot_search / social_discussion 信号，可作为候选稿发现入口。"}
    if article_body_result and article_body_result.get("success"):
        signal = ((article_body_result.get("sample_signals") or [""])[0] or "正文模式源提供可参考的结构与上下文")
        title = signal[:28] or "正文模式源提供可参考的结构与上下文"
        return {"topic_type": "article_body_pattern_candidate", "title": title, "score": 80, "primary_anchor": title, "reason": "正文模式源提供 plot_character_context，可在叙事角色足够时组成候选稿。"}
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
    topic = build_topic(maoyan_items, drama_items, movie_items, article_body_result, audience_result, social_results)
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


def collect_live_backfill_rows(
    query: str = "",
    rank_date: str | None = None,
    subject_limit: int = DOUBAN_LIVE_SUBJECT_LIMIT,
    requested_editorial_packet_subject_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    requested_far_east_films_direct_body_subject_ids: set[str] | list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    # Explicit packet lanes are narrow preparation paths; neither is
    # inferred from ordinary-source failure or candidate scarcity.
    requested_packet_subject_ids = {
        str(subject_id).strip()
        for subject_id in (requested_editorial_packet_subject_ids or ())
        if str(subject_id).strip()
    }

    requested_far_east_films_direct_body_ids = {
        str(subject_id).strip()
        for subject_id in (requested_far_east_films_direct_body_subject_ids or ())
        if str(subject_id).strip()
    }
    source_results: list[dict[str, Any]] = []
    for fetcher in (
        fetch_article_body_signal,
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

    # Keep the legacy single-result fetcher usable for existing monkeypatch callers.
    multi_fetcher = fetch_audience_reaction_signals
    if getattr(multi_fetcher, "__module__", None) == __name__ and getattr(fetch_audience_reaction_signal, "__module__", None) != __name__:
        audience_results = [fetch_audience_reaction_signal()]
    else:
        try:
            audience_results = list(multi_fetcher(subject_limit=subject_limit))
        except Exception as exc:  # noqa: BLE001
            audience_results = [_unknown_source_error(exc)]
    source_results.extend(audience_results)

    seen_subject_ids: set[str] = set()
    for audience_result in audience_results:
        live_subject = audience_result.get("live_subject") if isinstance(audience_result.get("live_subject"), dict) else {}
        subject_id = str(live_subject.get("subject_id") or "").strip()
        if not audience_result.get("success") or not subject_id or subject_id in seen_subject_ids:
            continue
        seen_subject_ids.add(subject_id)
        try:
            same_work_result = fetch_bilibili_same_work_enrichment(live_subject)
        except Exception as exc:  # noqa: BLE001
            same_work_result = _unknown_source_error(exc)
        source_results.append(same_work_result)
        if subject_id in requested_packet_subject_ids:
            # Explicit packet request is independent of ordinary context
            # success.  A packet failure is additive and never blocks the
            # legacy Bilibili/1905/official/Letterboxd fallback sequence.
            try:
                source_results.append(fetch_1905_same_work_editorial_packet(live_subject))
            except Exception as exc:  # noqa: BLE001
                source_results.append(_unknown_source_error(exc))

        if subject_id in requested_far_east_films_direct_body_ids:
            try:
                source_results.append(fetch_far_east_films_direct_body_packet(live_subject))
            except Exception as exc:  # noqa: BLE001
                source_results.append(_unknown_source_error(exc))
        if not same_work_result.get("success"):
            # The narrow mapped-context adapter remains the ordinary enrichment
            # path.  Only an explicit failure there opens the independent,
            # non-publishing editorial-packet lane; do not fetch packet pages
            # merely because Bilibili enrichment was unavailable.
            try:
                same_work_1905_result = fetch_1905_same_work_context(live_subject)
            except Exception as exc:  # noqa: BLE001
                same_work_1905_result = _unknown_source_error(exc)
            source_results.append(same_work_1905_result)
            if not same_work_1905_result.get("success"):
                # Packet fetching is handled exclusively above by the explicit
                # subject request; ordinary failure never opens that lane.
                # Official pages are exact-registry-only and fail closed.
                try:
                    same_work_official_result = fetch_official_same_work_context(live_subject)
                except Exception as exc:  # noqa: BLE001
                    same_work_official_result = _unknown_source_error(exc)
                source_results.append(same_work_official_result)
            else:
                same_work_official_result = {"success": False}
            # Letterboxd remains an English-title-only final fallback.
            if (not same_work_1905_result.get("success") and not same_work_official_result.get("success")
                    and _extract_letterboxd_work_anchor(live_subject)):
                try:
                    source_results.append(fetch_letterboxd_same_work_context(live_subject))
                except Exception as exc:  # noqa: BLE001
                    source_results.append(_unknown_source_error(exc))
    return export_backfill_article_rows(source_results, query=query)


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
