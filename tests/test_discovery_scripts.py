"""llm_client / discovery 脚本的无网络单测（2026-09-16）。"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from scripts.llm_client import parse_json_array


def test_parse_plain_array():
    assert parse_json_array('[{"i":1,"film":true}]') == [{"i": 1, "film": True}]


def test_parse_array_inside_noise():
    text = "好的，以下是结果：\n[{\"i\":1,\"film\":false,\"dispute\":1}]\n以上。"
    assert parse_json_array(text) == [{"i": 1, "film": False, "dispute": 1}]


def test_parse_fenced_json_array():
    text = "```json\n[{\"i\":2,\"why\":\"争议\"}]\n```"
    assert parse_json_array(text) == [{"i": 2, "why": "争议"}]


def test_parse_garbage_returns_none():
    assert parse_json_array("完全不是 JSON 的回复") is None


def test_parse_missing_brackets_returns_none():
    assert parse_json_array('{"i":1}') is None


def test_parse_broken_json_returns_none():
    assert parse_json_array("[{i:1,}]") is None


def test_parse_empty_array():
    assert parse_json_array("[]") == []


def test_classify_heuristic_judge_is_deterministic():
    from scripts.dailyhot_classify import heuristic_judge

    film, dispute, why = heuristic_judge("《让子弹飞》为什么更好看", "电影比较讨论")
    assert film is True
    assert dispute >= 1
    assert why

    film2, dispute2, _ = heuristic_judge("周末去哪玩", "旅游攻略")
    assert film2 is False
    assert dispute2 == 0


def test_radar_normalize_shape():
    from scripts.dailyhot_radar import normalize

    row = normalize(
        "douban-group",
        {"id": 1, "title": "标题", "desc": "摘要", "hot": 5, "url": "https://x", "mobileUrl": "https://m", "timestamp": 123},
        2,
        "2026-09-16T08:30:00+08:00",
    )
    assert row["source"] == "douban-group"
    assert row["rank"] == 2
    assert row["url"] == "https://x"
    assert row["mobile_url"] == "https://m"
    assert row["captured_at"] == "2026-09-16T08:30:00+08:00"


def test_radar_fetch_failure_is_recorded(tmp_path, monkeypatch):
    from scripts import dailyhot_radar

    def fake_fetch(api, route, timeout):
        return "timeout: boom", []

    monkeypatch.setattr(dailyhot_radar, "fetch", fake_fetch)
    monkeypatch.setattr(dailyhot_radar, "time", type("T", (), {"sleep": lambda s: None})())
    out = tmp_path / "snapshots"
    import argparse

    monkeypatch.setattr(
        argparse.ArgumentParser,
        "parse_args",
        lambda self: argparse.Namespace(
            api="http://127.0.0.1:6688", out=str(out), routes="douban-group", date="2026-09-16", timeout=5
        ),
    )
    code = dailyhot_radar.main()
    snapshot = json.loads((out / "2026-09-16.json").read_text(encoding="utf-8"))
    assert code == 1  # 单路由失败 → 非零
    assert snapshot["boards"][0]["error"] == "timeout: boom"


def test_classify_fallback_when_llm_down(tmp_path, monkeypatch):
    from scripts import dailyhot_classify

    snapshot_dir = tmp_path / "runs/radar/dailyhot"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "2026-09-16.json").write_text(
        json.dumps(
            {
                "schema_version": "dailyhot-radar-v1",
                "captured_at": "2026-09-16T08:30:00+08:00",
                "date": "2026-09-16",
                "boards": [
                    {
                        "route": "zhihu",
                        "label": "知乎热榜",
                        "items": [
                            {"rank": 1, "title": "为什么《一步之遥》达不到《让子弹飞》的高度？", "desc": "电影比较", "hot": 100, "url": "https://z/1", "timestamp": 1},
                            {"rank": 2, "title": "周末去哪玩", "desc": "旅游", "hot": 9, "url": "https://z/2", "timestamp": 1},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(dailyhot_classify, "load_env", lambda: {"RUOYU_LLM_API_KEY": "k", "RUOYU_LLM_MODEL": "m", "RUOYU_LLM_BASE_URL": "http://x/v1"})

    def boom(env, system, user):
        raise dailyhot_classify.LlmUnavailable("llm down")

    monkeypatch.setattr(dailyhot_classify, "llm_chat", boom)
    import argparse

    monkeypatch.setattr(
        argparse.ArgumentParser,
        "parse_args",
        lambda self: argparse.Namespace(date="2026-09-16", top=5, chunk=30),
    )
    code = dailyhot_classify.main()
    assert code == 0
    record = json.loads((snapshot_dir / "2026-09-16.classified.json").read_text(encoding="utf-8"))
    assert record["stats"]["heuristic_fallback"] == 2
    assert all(item["method"] == "heuristic-fallback" for item in record["items"])


def test_load_snapshot_default_requires_today(tmp_path, monkeypatch):
    """鲜度守卫：默认分支只有昨天的快照时必须拒绝，不能静默选中旧快照。"""
    from scripts import dailyhot_talk_filter

    snapshot_dir = tmp_path / "runs/radar/dailyhot"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "2026-09-15.json").write_text(
        json.dumps(
            {
                "schema_version": "dailyhot-radar-v1",
                "captured_at": "2026-09-15T08:30:00+08:00",
                "date": "2026-09-15",
                "boards": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(dailyhot_talk_filter, "SNAPSHOT_DIR", snapshot_dir)
    today = datetime.now().strftime("%Y-%m-%d")
    with pytest.raises(SystemExit) as exc:
        dailyhot_talk_filter.load_snapshot(None)
    assert "2026-09-15" not in str(exc.value)
    assert today in str(exc.value)
    assert "dailyhot_radar" in str(exc.value)


def test_load_snapshot_explicit_historical_date_still_works(tmp_path, monkeypatch):
    """鲜度守卫只作用于默认分支：--date 显式指定历史日期仍可回放。"""
    from scripts import dailyhot_talk_filter

    snapshot_dir = tmp_path / "runs/radar/dailyhot"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "2026-09-15.json").write_text(
        json.dumps(
            {
                "schema_version": "dailyhot-radar-v1",
                "captured_at": "2026-09-15T08:30:00+08:00",
                "date": "2026-09-15",
                "boards": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(dailyhot_talk_filter, "SNAPSHOT_DIR", snapshot_dir)
    path, snapshot = dailyhot_talk_filter.load_snapshot("2026-09-15")
    assert path.name == "2026-09-15.json"
    assert snapshot["date"] == "2026-09-15"
