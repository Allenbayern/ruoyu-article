"""Offline tests for the isolated R0 tgmeng discovery radar."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from article_group.tgmeng_hot import TgmengHotError, fetch_candy, fetch_board
from article_group.tgmeng_radar import (
    DiscoveryRadarError,
    build_tgmeng_discovery_radar,
    validate_discovery_radar,
)


def _result(
    *,
    source: str = "tgmeng-maoyan",
    endpoint: str = "/api/topsearch/maoyan/goupiaopingfenbang",
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "endpoint": endpoint,
        "fetched_at": "2026-08-11T12:00:00+00:00",
        "source_role": "discovery",
        "evidence_eligible": False,
        "items": (
            [{"title": "《欢迎来龙餐馆》周票房榜一", "score": "7809"}]
            if items is None
            else items
        ),
    }


def _fetchers() -> dict[str, Any]:
    return {
        "weibo": lambda: _result(source="tgmeng-weibo", endpoint="/api/topsearch/weibo"),
        "zhihu": lambda: _result(source="tgmeng-zhihu", endpoint="/api/topsearch/zhihu"),
        "bilibili": lambda: _result(source="tgmeng-bilibili", endpoint="/api/topsearch/bilibili"),
        "douyin": lambda: _result(source="tgmeng-douyin", endpoint="/api/topsearch/douyin"),
        "toutiao": lambda: _result(source="tgmeng-toutiao", endpoint="/api/topsearch/toutiao"),
        "baidu": lambda: _result(source="tgmeng-baidu", endpoint="/api/topsearch/baidu"),
        "maoyan": lambda: _result(source="tgmeng-maoyan", endpoint="/api/topsearch/maoyan/goupiaopingfenbang"),
        "tencent": lambda: _result(source="tgmeng-tencent", endpoint="/api/topsearch/tencent/dianshiju"),
        "aiqiyi": lambda: _result(source="tgmeng-aiqiyi", endpoint="/api/topsearch/aiqiyi/dianshiju"),
        "candy": lambda *a, **k: _result(
            source="tgmeng-candy-entertainment",
            endpoint="/api/cachesearch/tgmenghotsearch/entertainment",
            items=[{"title": "沈腾新片龙餐馆今日上映", "score": "950"}],
        ),
    }


def test_writes_atomic_r0_artifact(tmp_path: Path) -> None:
    target = tmp_path / "radar.json"
    artifact = build_tgmeng_discovery_radar(
        target,
        [{"name": "maoyan"}, {"name": "candy", "type": "entertainment"}],
        _fetchers=_fetchers(),
    )

    assert json.loads(target.read_text(encoding="utf-8")) == artifact
    assert not (tmp_path / ".radar.json.tmp").exists()
    assert artifact["artifact_type"] == "discovery_radar"
    assert artifact["state"] == "R0 radar"
    assert artifact["candidate_pool_eligible"] is False
    assert artifact["evidence_eligible"] is False
    assert artifact["next_action"] == "needs_editorial_research"
    assert artifact["summary"]["record_count"] == 2
    assert artifact["records"][0]["locator"] == "《欢迎来龙餐馆》周票房榜一"
    assert artifact["records"][0]["score"] == "7809"
    assert artifact["records"][1]["source"] == "tgmeng-candy-entertainment"
    assert validate_discovery_radar(artifact) == []


def test_cold_cache_window_surfaces_source_empty(tmp_path: Path) -> None:
    target = tmp_path / "radar.json"

    def empty_fetchers() -> dict[str, Any]:
        base = _fetchers()
        base["maoyan"] = lambda: _result(items=[])
        return base

    artifact = build_tgmeng_discovery_radar(
        target, [{"name": "maoyan"}], _fetchers=empty_fetchers()
    )
    assert artifact["summary"]["record_count"] == 0
    assert artifact["summary"]["error_count"] == 1
    assert artifact["errors"][0]["code"] == "source_empty"
    assert artifact["records"] == []


def test_fetch_error_is_recorded_not_fatal(tmp_path: Path) -> None:
    target = tmp_path / "radar.json"

    def broken_fetchers() -> dict[str, Any]:
        base = _fetchers()
        base["candy"] = lambda *a, **k: (_ for _ in ()).throw(
            TgmengHotError("network_error")
        )
        return base

    artifact = build_tgmeng_discovery_radar(
        target,
        [{"name": "maoyan"}, {"name": "candy", "type": "all"}],
        _fetchers=broken_fetchers(),
    )
    assert artifact["summary"]["record_count"] == 1
    assert artifact["summary"]["error_count"] == 1
    assert artifact["errors"][0]["code"] == "network_error"


def test_invalid_descriptors_rejected(tmp_path: Path) -> None:
    with pytest.raises(DiscoveryRadarError):
        build_tgmeng_discovery_radar(tmp_path / "r.json", [{"name": "not-a-source"}])
    with pytest.raises(DiscoveryRadarError):
        build_tgmeng_discovery_radar(
            tmp_path / "r.json", [{"name": "candy", "type": "unknown"}]
        )
    with pytest.raises(DiscoveryRadarError):
        build_tgmeng_discovery_radar(tmp_path / "r.json", [{"name": "candy"}])
    with pytest.raises(DiscoveryRadarError):
        build_tgmeng_discovery_radar(
            tmp_path / "r.json", [{"name": "weibo", "extra": 1}]
        )
    with pytest.raises(DiscoveryRadarError):
        build_tgmeng_discovery_radar(tmp_path / "r.txt", [{"name": "weibo"}])
    with pytest.raises(DiscoveryRadarError):
        build_tgmeng_discovery_radar(tmp_path / "r.json", [])


def test_validate_rejects_evidence_eligible_records() -> None:
    artifact = _result()
    artifact["items"] = []
    bad = {
        "schema_version": "1",
        "artifact_type": "discovery_radar",
        "state": "R0 radar",
        "candidate_pool_eligible": False,
        "evidence_eligible": False,
        "records": [
            {
                "source": "tgmeng-maoyan",
                "endpoint": "/x",
                "fetched_at": "2026-08-11T12:00:00+00:00",
                "locator": "标题",
                "evidence_eligible": True,
                "source_role": "discovery",
            }
        ],
    }
    problems = validate_discovery_radar(bad)
    assert "record_0_evidence_eligible" in problems


def test_fetch_board_invalid_source() -> None:
    with pytest.raises(TgmengHotError):
        fetch_board("not-a-board")


def test_fetch_candy_invalid_type() -> None:
    with pytest.raises(TgmengHotError):
        fetch_candy("not-a-type")
