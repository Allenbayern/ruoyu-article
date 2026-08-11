"""Read-only Tgmeng hot-board discovery adapter.

Supports the self-hosted 糖果梦热榜 (tgmeng) aggregator on the home LAN
(http://192.168.100.123:4399). Every result is discovery-only — never
treated as factual evidence (article-group double-source verification
still applies).

Endpoints used (all external-request cache paths, no AI spend):

- Top boards:   GET /api/topsearch/{source}/{board?}       (cache-backed)
- Candy index:  GET /api/cachesearch/tgmenghotsearch/{type} (5-min AI prewarm cache)

Caveats encoded in the adapter:

- External requests read a server-side cache; a cold-cache window yields
  ``data: null`` which surfaces as ``source_empty`` (a stable error code),
  never as a fabricated or partial list.
- The candy index is AI-aggregated and refreshed on a schedule — treat it
  as a topic signal only, never as a factual claim source.
- No credentials are required; the adapter never writes anything.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Final
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_BASE_URL: Final = "http://192.168.100.123:4399/api"
_TIMEOUT: Final = 20.0
_USER_AGENT: Final = "ruoyu-article-group-tgmeng/0.1 (discovery-only)"

# Restricted set of valid source names.
_BOARDS: Final[frozenset[str]] = frozenset({
    "weibo", "zhihu", "bilibili", "douyin", "toutiao", "baidu",
    "maoyan", "tencent", "aiqiyi",
})
# Candy-index categories (AI prewarmed on a 5-min schedule).
_CANDY_TYPES: Final[frozenset[str]] = frozenset({
    "all", "technology", "finance", "entertainment", "car", "sports",
    "game", "livelihood",
})
_BOARD_NAMES: Final[dict[str, str]] = {
    "maoyan": "goupiaopingfenbang",
    "tencent": "dianshiju",
    "aiqiyi": "dianshiju",
}
_MAX_ITEMS: Final = 60


class TgmengHotError(ValueError):
    """Raised when the tgmeng backend cannot be reached or returns an
    invalid response. The message is a stable error code."""


def _fetch_json(url: str) -> dict[str, Any]:
    """GET *url* and return the parsed JSON object (fail-closed)."""
    request = Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urlopen(request, timeout=_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as error:
        raise TgmengHotError(f"http_error:{error.code}") from error
    except URLError as error:
        raise TgmengHotError("network_error") from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise TgmengHotError("invalid_json") from error
    if not isinstance(payload, dict):
        raise TgmengHotError("invalid_payload")
    if payload.get("code") != 200:
        raise TgmengHotError(f"business_error:{payload.get('code')}")
    return payload


def _extract_items(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Normalize the tgmeng response into discovery items.

    Returns an empty list when the server cache has no data yet
    (``data: null``) — the caller maps that to ``source_empty``.
    """
    data = payload.get("data")
    if data is None:
        return []
    if not isinstance(data, dict):
        raise TgmengHotError("invalid_data_shape")
    rows = data.get("dataInfo")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise TgmengHotError("invalid_items_shape")
    items: list[dict[str, str]] = []
    for row in rows[: _MAX_ITEMS]:
        if not isinstance(row, dict):
            continue
        title = row.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        item: dict[str, str] = {"title": title.strip()}
        score = row.get("hotScore")
        if isinstance(score, (int, float)) or (
            isinstance(score, str) and score.strip().isdigit()
        ):
            item["score"] = str(score)
        elif isinstance(score, str) and score.strip():
            item["score"] = score.strip()
        url = row.get("url")
        if isinstance(url, str) and url.strip():
            item["url"] = url.strip()
        items.append(item)
    return items


def fetch_board(source: str, board: str | None = None) -> dict[str, Any]:
    """Fetch one top board from the tgmeng backend (discovery-only).

    *source* must be in ``_BOARDS``. Returns a discovery-shaped dict
    (``source_role="discovery"``, ``evidence_eligible=False``) or raises
    ``TgmengHotError``. An empty ``items`` list means the server-side
    cache has no data for this board yet (``source_empty`` semantics).
    """
    if source not in _BOARDS:
        raise TgmengHotError("invalid_source_name")
    board = board or _BOARD_NAMES.get(source, "")
    url = f"{_BASE_URL}/topsearch/{source}"
    if board:
        url += f"/{board}"
    payload = _fetch_json(url)
    items = _extract_items(payload)
    return {
        "source": f"tgmeng-{source}",
        "endpoint": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "items": items,
        "source_role": "discovery",
        "evidence_eligible": False,
    }


def fetch_candy(candy_type: str = "all") -> dict[str, Any]:
    """Fetch the candy index (AI-aggregated topic signal).

    *candy_type* must be in ``_CANDY_TYPES``. Same discovery-shaped return
    contract as :func:`fetch_board`; an empty ``items`` list means the
    AI prewarm cache is not populated yet for this category.
    """
    if candy_type not in _CANDY_TYPES:
        raise TgmengHotError("invalid_candy_type")
    url = f"{_BASE_URL}/cachesearch/tgmenghotsearch/{candy_type}"
    payload = _fetch_json(url)
    items = _extract_items(payload)
    return {
        "source": f"tgmeng-candy-{candy_type}",
        "endpoint": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "items": items,
        "source_role": "discovery",
        "evidence_eligible": False,
    }
