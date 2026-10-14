"""Acceptance tests for article_group.hotnews."""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from article_group.hotnews import (
    _normalize_platform,
    get_platform_hotnews,
    get_zhiwei_hotnews,
    select_weighted_topic,
)


def test_normalize_platform():
    assert _normalize_platform("weibo")["name"] == "微博"
    assert _normalize_platform("微博")["code"] == "weibo"
    assert _normalize_platform("ZhiHu")["code"] == "zhihu"
    assert _normalize_platform("知乎热榜")["code"] == "zhihu"
    assert _normalize_platform("douyin")["name"] == "抖音"
    assert _normalize_platform("unknown_platform_123") is None


def test_get_zhiwei_hotnews_mock():
    mock_payload = {
        "state": True,
        "data": [
            {"name": "热搜话题A", "rank": 1, "lastCount": 100000, "url": "https://example.com/a"},
            {"name": "热搜话题B", "rank": 2, "lastCount": 80000, "url": "https://example.com/b"},
        ],
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("article_group.hotnews.urlopen", return_value=mock_resp):
        items = get_zhiwei_hotnews("weibo")
        assert items is not None
        assert len(items) == 2
        assert items[0]["title"] == "热搜话题A"
        assert items[0]["rank"] == 1
        assert items[0]["source"] == "zhiwei"


def test_get_platform_hotnews_fallback_and_limit():
    mock_items = [
        {"title": f"话题_{i}", "rank": i, "hot_value": "1000", "url": "", "source": "zhiwei"}
        for i in range(1, 10)
    ]

    with patch("article_group.hotnews.get_zhiwei_hotnews", return_value=mock_items):
        results = get_platform_hotnews("weibo", limit=3)
        assert len(results) == 3
        assert results[0]["title"] == "话题_1"
        assert results[2]["title"] == "话题_3"


def test_select_weighted_topic():
    mock_items = [
        {"title": "第一热点", "rank": 1},
        {"title": "第二热点|带竖线", "rank": 2},
    ]

    with patch("article_group.hotnews.get_platform_hotnews", return_value=mock_items):
        topic = select_weighted_topic("weibo")
        assert topic in ("第一热点", "第二热点——带竖线")
        assert "|" not in topic
