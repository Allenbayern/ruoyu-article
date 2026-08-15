from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

from article_group.newrank_hot_article import (
    PARSER_VERSION,
    NewrankCollector,
    NewrankError,
    main,
)


@dataclass
class FakeResponse:
    status: int
    body: bytes


def _payload(*items: dict[str, object]) -> bytes:
    return json.dumps({"value": {"data": list(items)}}).encode("utf-8")


def _collector(response: FakeResponse, now: datetime | None = None) -> NewrankCollector:
    return NewrankCollector(
        n_token="unit-test-runtime-value",
        transport=lambda _url, _headers: response,
        clock=lambda: now or datetime.fromisoformat("2026-08-13T12:00:00+08:00"),
    )


def _manifest_for(output: Path) -> Path:
    return output.with_name(output.name + ".manifest.json")


def test_collector_records_source_empty_without_conflating_failure(tmp_path: Path) -> None:
    output = tmp_path / "batch.json"
    result = _collector(FakeResponse(200, _payload())).collect(["2026-08-13"], output)

    assert result["status"] == "source_empty"
    assert result["items"] == []
    manifest = json.loads(_manifest_for(output).read_text(encoding="utf-8"))
    assert manifest["status"] == "source_empty"
    assert manifest["parser_version"] == PARSER_VERSION
    assert manifest["request_timestamp"] == "2026-08-13T12:00:00+08:00"
    assert manifest["output_path"] == str(output)
    assert len(manifest["sha256"]) == 64
    assert manifest["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()


def test_transport_and_http_failures_are_source_failed_not_empty(tmp_path: Path) -> None:
    def broken(_url: str, _headers: dict[str, str]) -> FakeResponse:
        raise OSError("transport details are not part of the public error")

    output = tmp_path / "transport.json"
    result = NewrankCollector(
        n_token="unit-test-runtime-value",
        transport=broken,
        clock=lambda: datetime.fromisoformat("2026-08-13T12:00:00+08:00"),
    ).collect(["2026-08-13"], output)
    assert result["status"] == "source_failed"
    assert "items" not in result
    assert json.loads(_manifest_for(output).read_text())["status"] == "source_failed"

    output = tmp_path / "http.json"
    result = _collector(FakeResponse(403, b"not retained" )).collect(["2026-08-13"], output)
    assert result["status"] == "source_failed"
    assert "items" not in result


def test_malformed_transport_response_is_source_failed_not_empty(tmp_path: Path) -> None:
    output = tmp_path / "malformed-response.json"
    result = NewrankCollector(
        n_token="unit-test-runtime-value",
        transport=lambda _url, _headers: object(),  # type: ignore[return-value]
        clock=lambda: datetime.fromisoformat("2026-08-13T12:00:00+08:00"),
    ).collect(["2026-08-13"], output)
    assert result["status"] == "source_failed"
    assert "items" not in result


def test_unexpected_transport_exception_is_source_failed_not_empty(tmp_path: Path) -> None:
    def broken(_url: str, _headers: dict[str, str]) -> FakeResponse:
        raise RuntimeError("transport implementation failure")

    output = tmp_path / "unexpected-transport.json"
    result = NewrankCollector(
        n_token="unit-test-runtime-value",
        transport=broken,
        clock=lambda: datetime.fromisoformat("2026-08-13T12:00:00+08:00"),
    ).collect(["2026-08-13"], output)
    assert result["status"] == "source_failed"
    assert "items" not in result


def test_json_and_schema_failures_are_distinct(tmp_path: Path) -> None:
    output = tmp_path / "json.json"
    result = _collector(FakeResponse(200, b"not-json")).collect(["2026-08-13"], output)
    assert result["status"] == "json_failed"
    assert "items" not in result

    output = tmp_path / "schema.json"
    result = _collector(FakeResponse(200, b'{"value": {"unexpected": []}}')).collect(
        ["2026-08-13"], output
    )
    assert result["status"] == "schema_changed"
    assert "items" not in result


def test_success_preserves_items_and_manifest_is_non_overwriting(tmp_path: Path) -> None:
    output = tmp_path / "success.json"
    result = _collector(
        FakeResponse(200, _payload({"rank": 1, "readNum": 100001}))
    ).collect(["2026-08-13"], output)
    assert result["status"] == "ok"
    assert result["items"] == [{"rank": 1, "readNum": 100001}]

    with pytest.raises(NewrankError, match="artifact_exists"):
        _collector(FakeResponse(200, _payload())).collect(["2026-08-13"], output)


def test_empty_day_followed_by_success_is_not_reported_as_source_empty(tmp_path: Path) -> None:
    responses = iter(
        [
            FakeResponse(200, _payload()),
            FakeResponse(200, _payload({"rank": 1})),
        ]
    )
    output = tmp_path / "mixed-days.json"
    result = NewrankCollector(
        n_token="unit-test-runtime-value",
        transport=lambda _url, _headers: next(responses),
        clock=lambda: datetime.fromisoformat("2026-08-13T12:00:00+08:00"),
    ).collect(["2026-08-12", "2026-08-13"], output)
    assert result["status"] == "ok"
    assert result["items"] == [{"rank": 1}]


def test_missing_cli_runtime_channel_fails_closed_without_source_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = main(["--publictime", "2026-08-13", "--out", str(tmp_path / "cli.json")])
    assert result == 2
    assert capsys.readouterr().out.strip() == "source_unavailable"
    assert not (tmp_path / "cli.json").exists()


@pytest.mark.parametrize("option", ["--cookie", "--n-token"])
def test_cli_rejects_unsupported_value_arguments_without_echo_or_artifact(
    option: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    synthetic_value = "synthetic-cli-value-001"
    output = tmp_path / "unsupported.json"
    with pytest.raises(SystemExit):
        main(["--publictime", "2026-08-13", "--out", str(output), option, synthetic_value])
    captured = capsys.readouterr()
    assert synthetic_value not in captured.out
    assert synthetic_value not in captured.err
    assert not output.exists()
