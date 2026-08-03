"""Read-only Yuafeng hot-list discovery adapter.

Supports three API endpoints from api-v2.yuafeng.cn. Every result is
discovery-only — never treated as factual evidence.

API key is read at call-time from the ``YUAFENG_API_KEY`` environment
variable and is never persisted, logged, or leaked into exceptions.
Connections bypass ambient proxy settings (direct-only).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Final
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

_BASE_URL: Final = "https://api-v2.yuafeng.cn"

# Restricted set of valid actions for the aggregate endpoint.
_VALID_AGGREGATE_ACTIONS: Final[frozenset[str]] = frozenset({
    "知乎热榜",
    "微博热榜",
    "微信热文榜",
    "澎湃热榜",
    "百度热点",
    "知乎日报",
    "今日头条热榜",
    "梨视频总榜",
})
_UC_TOP_KEY_RE: Final[re.Pattern[str]] = re.compile(r"Top_([1-9]\d*)\Z")

_USER_AGENT: Final = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
)


class YuafengHotError(ValueError):
    """Raised when the Yuafeng hot-list API cannot be reached or returns
    an invalid response. The message is a stable error code — it never
    contains the API key or raw secrets."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_opener():
    """Return an opener that bypasses ambient proxy settings."""
    return build_opener(ProxyHandler({}))


def _get_api_key() -> str:
    """Read the API key from the environment at call-time."""
    key = os.environ.get("YUAFENG_API_KEY")
    if not key:
        raise YuafengHotError("missing_api_key")
    return key


def _validate_page(page: int | None) -> None:
    """Ensure *page* is either None or a positive integer."""
    if page is not None and (isinstance(page, bool) or not isinstance(page, int) or page < 1):
        raise YuafengHotError("invalid_page")


def _fetch_json(url: str) -> Any:
    """GET *url* and return the parsed JSON response.

    The URL already includes the API key as a query parameter.  Never
    echo the URL back in the exception message (it may contain the key).
    """
    request = Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with _build_opener().open(request, timeout=30.0) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise YuafengHotError(f"http_error:{exc.code}") from None
    except URLError:
        raise YuafengHotError("network_error") from None
    except (TimeoutError, OSError):
        raise YuafengHotError("network_error") from None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise YuafengHotError("parse_error") from None


def _normalize_items(parsed: Any) -> list[dict[str, Any]]:
    """Best-effort extraction of a list of items from the parsed response.

    Returns an empty list when the shape is unexpected.
    """
    # Direct top-level list
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    # Nested under data / data.data
    if isinstance(parsed, dict):
        data = parsed.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            inner = data.get("data") or data.get("list") or data.get("items")
            if isinstance(inner, list):
                return [item for item in inner if isinstance(item, dict)]
            ranked_items: list[tuple[int, dict[str, Any]]] = []
            for key, item in data.items():
                match = _UC_TOP_KEY_RE.fullmatch(key)
                if match is None or not isinstance(item, dict):
                    ranked_items = []
                    break
                ranked_items.append((int(match.group(1)), item))
            if ranked_items:
                return [item for _, item in sorted(ranked_items)]
        # Some APIs wrap in result / list
        for key in ("result", "list", "items", "hotList", "newsList"):
            val = parsed.get(key)
            if isinstance(val, list):
                return [item for item in val if isinstance(item, dict)]
    return []


def _build_result(
    source: str,
    endpoint: str,
    parsed: Any,
) -> dict[str, Any]:
    """Wrap a parsed response into the standard discovery result envelope."""
    return {
        "source": source,
        "endpoint": endpoint,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source_role": "discovery",
        "evidence_eligible": False,
        "raw_json": parsed,
        "items": _normalize_items(parsed),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_uc_hot() -> dict[str, Any]:
    """Fetch the UC hot list (type=json).

    Endpoint: ``/API/xq_shenmahot.php?type=json&apikey=...``
    """
    key = _get_api_key()
    params = urlencode({"type": "json", "apikey": key})
    url = f"{_BASE_URL}/API/xq_shenmahot.php?{params}"
    parsed = _fetch_json(url)
    return _build_result(
        source="yuafeng-uc",
        endpoint="/API/xq_shenmahot.php",
        parsed=parsed,
    )


def fetch_tencent_news(
    page: int | None = None,
    type_: str | None = None,
) -> dict[str, Any]:
    """Fetch Tencent news hot list.

    Endpoint: ``/API/txxw.php?apikey=...``

    *page* — optional 1-based page number (must be a positive int if set).
    *type_* — optional category string; if non-None, must be a non-empty str
              without leading/trailing whitespace.
    """
    key = _get_api_key()
    _validate_page(page)

    if type_ is not None:
        if not isinstance(type_, str) or not type_ or type_ != type_.strip():
            raise YuafengHotError("invalid_type")

    params = {"apikey": key}
    if page is not None:
        params["page"] = str(page)
    if type_ is not None:
        params["type"] = type_

    url = f"{_BASE_URL}/API/txxw.php?{urlencode(params)}"
    parsed = _fetch_json(url)
    return _build_result(
        source="yuafeng-tencent",
        endpoint="/API/txxw.php",
        parsed=parsed,
    )


def fetch_aggregate(
    action: str,
    page: int | None = None,
) -> dict[str, Any]:
    """Fetch an aggregate hot-list by named *action*.

    Endpoint: ``/API/jinri_hot.php?apikey=...&action=...``

    *action* — one of the predefined Chinese-named hot-list categories
               (知乎热榜, 微博热榜, 微信热文榜, 澎湃热榜, 百度热点,
                知乎日报, 今日头条热榜, 梨视频总榜).
    *page*   — optional 1-based page number (must be a positive int if set).

    Raises ``YuafengHotError("invalid_action")`` for unrecognised actions.
    """
    key = _get_api_key()
    if action not in _VALID_AGGREGATE_ACTIONS:
        raise YuafengHotError("invalid_action")
    _validate_page(page)

    params = {"apikey": key, "action": action}
    if page is not None:
        params["page"] = str(page)

    url = f"{_BASE_URL}/API/jinri_hot.php?{urlencode(params)}"
    parsed = _fetch_json(url)
    return _build_result(
        source="yuafeng-aggregate",
        endpoint="/API/jinri_hot.php",
        parsed=parsed,
    )