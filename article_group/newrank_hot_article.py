#!/usr/bin/env python3
"""Offline-testable Newrank evidence collector.

The collector accepts a runtime-only access value through its Python API for
unit tests or a caller-controlled process channel. The CLI intentionally has
no credential arguments and fails closed when that value is not supplied by
its caller. It never persists or prints the access value.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Final, NamedTuple, NoReturn
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

GW: Final = "https://gw.newrank.cn"
API: Final = "/api/nr-trade-platform-common/xdnphb/ade/v1/platformCommon/HotArticle/getHotArticleList"
PARSER_VERSION: Final = "newrank-parser-v1"
USER_AGENT: Final = "ruoyu-film-daily-newrank/1.0 (evidence-only)"


class NewrankError(ValueError):
    """Stable fail-closed collector error code."""


class TransportResponse(NamedTuple):
    status: int
    body: bytes


Transport = Callable[[str, dict[str, str]], object]
Clock = Callable[[], datetime]


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, "argument_error\n")


def _default_transport(url: str, headers: dict[str, str]) -> TransportResponse:
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            return TransportResponse(response.status, response.read())
    except HTTPError as error:
        return TransportResponse(error.code, error.read())
    except (URLError, OSError, TimeoutError) as error:
        raise NewrankError("source_failed") from error


def _sign_get(params: dict[str, str]) -> dict[str, str]:
    # Signature construction is deterministic except for the caller-provided
    # request nonce; no credential is included in the persisted evidence.
    import secrets

    nonce = secrets.token_hex(5)[:9]
    parts = [f"{API}?AppKey=joker"]
    signed = dict(params)
    for key in sorted(params):
        parts.append(f"{key}={params[key]}")
    parts.append(f"nonce={nonce}")
    signed["nonce"] = nonce
    signed["xyz"] = hashlib.md5("&".join(parts).encode()).hexdigest()
    return signed


def _url(public_time: str) -> str:
    return f"{GW}{API}?{urlencode(_sign_get({'publicTime': public_time}))}"


def _parse_items(body: bytes) -> tuple[str, list[dict[str, Any]]]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NewrankError("json_failed") from error
    if not isinstance(payload, dict):
        raise NewrankError("schema_changed")
    value = payload.get("value")
    if not isinstance(value, dict) or "data" not in value:
        raise NewrankError("schema_changed")
    raw_items = value["data"]
    if not isinstance(raw_items, list):
        raise NewrankError("schema_changed")
    if any(not isinstance(item, dict) for item in raw_items):
        raise NewrankError("schema_changed")
    items = [dict(item) for item in raw_items]
    return ("source_empty" if not items else "ok", items)


def _normalize_response(response: object) -> TransportResponse:
    try:
        status = response.status  # type: ignore[attr-defined]
        body = response.body  # type: ignore[attr-defined]
    except (AttributeError, TypeError) as error:
        raise NewrankError("source_failed") from error
    if (
        not isinstance(status, int)
        or isinstance(status, bool)
        or not isinstance(body, bytes)
    ):
        raise NewrankError("source_failed")
    return TransportResponse(status, body)


def _write_json_once(path: Path, payload: object) -> None:
    if path.exists():
        raise NewrankError("artifact_exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class NewrankCollector:
    def __init__(
        self,
        *,
        n_token: str,
        transport: Transport = _default_transport,
        clock: Clock | None = None,
    ) -> None:
        if not isinstance(n_token, str) or not n_token.strip():
            raise NewrankError("source_unavailable")
        self._n_token = n_token
        self._transport = transport
        self._clock = clock or (lambda: datetime.now().astimezone())

    def collect(self, public_times: Sequence[str], output: str | Path) -> dict[str, Any]:
        output_path = Path(output)
        manifest_path = output_path.with_name(output_path.name + ".manifest.json")
        if output_path.exists() or manifest_path.exists():
            raise NewrankError("artifact_exists")
        requested = list(public_times)
        if not requested:
            raise NewrankError("public_time_missing")

        request_time = self._clock()
        if (
            not isinstance(request_time, datetime)
            or request_time.utcoffset() != timedelta(hours=8)
        ):
            raise NewrankError("clock_must_be_asia_shanghai")
        status = "ok"
        items: list[dict[str, Any]] = []
        try:
            for public_time in requested:
                response = _normalize_response(self._transport(
                    _url(public_time),
                    {"User-Agent": USER_AGENT, "N-Token": self._n_token},
                ))
                if response.status < 200 or response.status >= 300:
                    raise NewrankError("source_failed")
                day_status, day_items = _parse_items(response.body)
                items.extend(day_items)
                if day_status == "ok":
                    status = "ok"
            if not items:
                status = "source_empty"
        except NewrankError as error:
            status = error.args[0]
            items = []
        except (OSError, TimeoutError):
            status = "source_failed"
            items = []
        except Exception:
            status = "source_failed"
            items = []

        result: dict[str, Any] = {"status": status, "public_times": requested}
        if status in {"ok", "source_empty"}:
            result["items"] = items
        output_payload: dict[str, Any] = {
            "parser_version": PARSER_VERSION,
            "status": status,
            "public_times": requested,
        }
        if status in {"ok", "source_empty"}:
            output_payload["items"] = items
        raw_bytes = (json.dumps(output_payload, ensure_ascii=False, indent=2) + "\n").encode()
        manifest = {
            "request_timestamp": request_time.isoformat(),
            "parser_version": PARSER_VERSION,
            "sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "output_path": str(output_path),
            "status": status,
        }
        _write_json_once(output_path, output_payload)
        _write_json_once(manifest_path, manifest)
        return result


def _date_range(days: int) -> list[str]:
    if days < 1:
        raise NewrankError("days_invalid")
    today = date.today()
    return [(today - timedelta(days=index)).isoformat() for index in range(days)]


def main(argv: Sequence[str] | None = None, *, runtime_token: str | None = None) -> int:
    parser = _SafeArgumentParser(description="Collect Newrank batches into immutable local evidence.")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--out", default="newrank-hot-articles.json")
    parser.add_argument("--publictime")
    args = parser.parse_args(argv)
    token = runtime_token
    if not token:
        print("source_unavailable")
        return 2
    try:
        days = [args.publictime] if args.publictime else _date_range(args.days)
        result = NewrankCollector(n_token=token).collect(days, args.out)
    except NewrankError as error:
        print(error.args[0])
        return 2
    print(json.dumps({"status": result["status"], "output": args.out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(runtime_token=None))
