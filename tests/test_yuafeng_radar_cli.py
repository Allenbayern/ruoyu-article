"""Offline tests for the Yuafeng R0 discovery-radar CLI.

No network or credentials involved — the builder function is always
monkeypatched. No candidate pool, prewrite, or Toutiao files touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from article_group.discovery_radar import DiscoveryRadarError
from article_group.yuafeng_radar_cli import main
from article_group.yuafeng_hot import YuafengHotError


def _fake_artifact() -> dict[str, Any]:
    return {
        "schema_version": "1",
        "artifact_type": "discovery_radar",
        "state": "R0 radar",
        "observed_at": "2026-08-01T12:00:00+00:00",
        "source_layer": "discovery-only",
        "candidate_pool_eligible": False,
        "evidence_eligible": False,
        "next_action": "needs_editorial_research",
        "records": [
            {
                "source": "yuafeng-uc",
                "endpoint": "/API/xq_shenmahot.php",
                "fetched_at": "2026-08-01T12:00:00+00:00",
                "locator": "热搜标题",
                "item_index": 0,
                "flags": "needs_editorial_research",
                "source_role": "discovery",
                "evidence_eligible": False,
            }
        ],
    }


def test_cli_success_prints_artifact(monkeypatch, capsys, tmp_path):
    target = tmp_path / "radar.json"

    def fake_builder(output_path, sources, **kwargs):
        assert str(output_path) == str(target)
        assert sources == [{"name": "uc"}]
        return _fake_artifact()

    monkeypatch.setattr(
        "article_group.yuafeng_radar_cli.build_yuafeng_discovery_radar",
        fake_builder,
    )

    result = main(
        [
            "--output-path",
            str(target),
            "--sources",
            '[{"name": "uc"}]',
        ]
    )

    assert result == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["artifact_type"] == "discovery_radar"
    assert parsed["state"] == "R0 radar"
    assert capsys.readouterr().err == ""


def test_cli_invalid_sources_json(capsys):
    result = main(
        [
            "--output-path",
            "/tmp/radar.json",
            "--sources",
            "not-json",
        ]
    )
    assert result == 2
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {
        "error": "invalid_sources_json",
        "detail": "Expecting value",
    }
    assert captured.out == ""


def test_cli_sources_not_a_list(capsys):
    result = main(
        [
            "--output-path",
            "/tmp/radar.json",
            "--sources",
            '{"name": "uc"}',
        ]
    )
    assert result == 2
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {
        "error": "sources_must_be_a_bounded_list",
        "type": "radar",
    }
    assert captured.out == ""


def test_cli_validates_sources_list_is_bounded(capsys):
    """11 sources exceeds the builder's max of 10 — validation fires pre-fetch."""
    many_sources = [{"name": "uc"}] * 11

    result = main(
        [
            "--output-path",
            "/tmp/radar.json",
            "--sources",
            json.dumps(many_sources),
        ]
    )
    assert result == 2
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {
        "error": "sources_must_be_a_bounded_list",
        "type": "radar",
    }
    assert captured.out == ""


def test_cli_discovery_radar_error(monkeypatch, capsys, tmp_path):
    def fail(*args, **kwargs):
        raise DiscoveryRadarError("invalid_source_name")

    monkeypatch.setattr(
        "article_group.yuafeng_radar_cli.build_yuafeng_discovery_radar",
        fail,
    )

    result = main(
        [
            "--output-path",
            str(tmp_path / "radar.json"),
            "--sources",
            '[{"name": "unknown"}]',
        ]
    )
    captured = capsys.readouterr()
    assert result == 2
    assert json.loads(captured.err) == {
        "error": "invalid_source_name",
        "type": "radar",
    }
    assert captured.out == ""


def test_cli_yuafeng_hot_error(monkeypatch, capsys, tmp_path):
    def fail(*args, **kwargs):
        raise YuafengHotError("missing_api_key")

    monkeypatch.setattr(
        "article_group.yuafeng_radar_cli.build_yuafeng_discovery_radar",
        fail,
    )

    result = main(
        [
            "--output-path",
            str(tmp_path / "radar.json"),
            "--sources",
            '[{"name": "uc"}]',
        ]
    )
    captured = capsys.readouterr()
    assert result == 2
    assert json.loads(captured.err) == {
        "error": "missing_api_key",
        "type": "radar",
    }
    assert captured.out == ""


def test_cli_value_error(monkeypatch, capsys, tmp_path):
    def fail(*args, **kwargs):
        raise ValueError("bad_arg")

    monkeypatch.setattr(
        "article_group.yuafeng_radar_cli.build_yuafeng_discovery_radar",
        fail,
    )

    result = main(
        [
            "--output-path",
            str(tmp_path / "radar.json"),
            "--sources",
            '[{"name": "uc"}]',
        ]
    )
    captured = capsys.readouterr()
    assert result == 2
    assert json.loads(captured.err) == {
        "error": "bad_arg",
        "type": "input",
    }
    assert captured.out == ""


def test_cli_requires_explicit_arguments():
    with pytest.raises(SystemExit) as raised:
        main([])
    assert raised.value.code == 2


def test_cli_requires_output_path():
    with pytest.raises(SystemExit) as raised:
        main(["--sources", '[{"name": "uc"}]'])
    assert raised.value.code == 2


def test_cli_requires_sources():
    with pytest.raises(SystemExit) as raised:
        main(["--output-path", "/tmp/radar.json"])
    assert raised.value.code == 2