from __future__ import annotations

import json
from pathlib import Path

import pytest

from article_group.toutiao_cli import main


URL = "https://www.toutiao.com/article/1234567890123456/"


def test_cli_success_prints_manifest(monkeypatch, capsys, tmp_path):
    def fake_capture(url, run_root, source_id, role, independence_group, timeout):
        assert url == URL
        assert run_root == str(tmp_path)
        assert source_id == "TT-1"
        assert role == "confirmed-primary"
        assert independence_group == "toutiao:1"
        assert timeout == 7.5
        return {
            "source_id": source_id,
            "relative_path": "sources/TT-1.txt",
            "sha256": "a" * 64,
            "url": "https://m.toutiao.com/article/1234567890123456/",
            "role": role,
            "independence_group": independence_group,
            "captured_at": "2026-08-01T00:00:00+00:00",
        }

    monkeypatch.setattr("article_group.toutiao_cli.capture_toutiao_source", fake_capture)
    result = main(
        [
            "--url",
            URL,
            "--run-root",
            str(tmp_path),
            "--source-id",
            "TT-1",
            "--independence-group",
            "toutiao:1",
            "--timeout",
            "7.5",
        ]
    )

    assert result == 0
    assert json.loads(capsys.readouterr().out)["source_id"] == "TT-1"
    assert capsys.readouterr().err == ""


def test_cli_extraction_error_is_machine_readable(monkeypatch, capsys, tmp_path):
    from article_group.toutiao import ToutiaoExtractionError

    def fail(*args, **kwargs):
        raise ToutiaoExtractionError("blocked_challenge")

    monkeypatch.setattr("article_group.toutiao_cli.capture_toutiao_source", fail)
    result = main(["--url", URL, "--run-root", str(tmp_path), "--source-id", "TT-1"])

    captured = capsys.readouterr()
    assert result == 2
    assert json.loads(captured.err) == {"error": "blocked_challenge", "type": "extraction"}
    assert captured.out == ""


def test_cli_requires_explicit_arguments():
    with pytest.raises(SystemExit) as raised:
        main([])
    assert raised.value.code == 2
