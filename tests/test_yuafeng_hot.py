"""Tests for the Yuafeng hot-list discovery adapter.

All HTTP calls are mocked — no network access during tests.
API keys are never persisted, logged, or leaked into exceptions.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import build_opener

import pytest

from article_group.yuafeng_hot import (
    YuafengHotError,
    fetch_aggregate,
    fetch_tencent_news,
    fetch_uc_hot,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure ``YUAFENG_API_KEY`` is absent unless a test explicitly sets it."""
    monkeypatch.delenv("YUAFENG_API_KEY", raising=False)


@pytest.fixture
def set_api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Set a dummy API key in the environment."""
    key = "test-key-12345"
    monkeypatch.setenv("YUAFENG_API_KEY", key)
    return key


def _mock_opener(body: Any = None) -> MagicMock:
    """Return a mock ``build_opener()`` result whose ``.open()``
    returns a response with *body* serialised as JSON."""
    if body is None:
        body = {"data": [{"title": "热搜1", "url": "https://example.com/1"}]}
    data = json.dumps(body).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.read.return_value = data
    mock_resp.__enter__.return_value = mock_resp

    mock_opener = MagicMock()
    mock_opener.open.return_value = mock_resp
    return mock_opener


def _patch_opener(body: Any = None):
    """Context manager that patches ``build_opener`` to return a mock."""
    return patch(
        "article_group.yuafeng_hot.build_opener",
        return_value=_mock_opener(body),
    )


def _patch_opener_http_error(code: int = 403):
    """Context manager that patches ``build_opener`` to raise HTTPError."""
    mock_err = MagicMock()
    mock_err.side_effect = HTTPError(
        url="http://mock/",
        code=code,
        msg="Forbidden",
        hdrs={},
        fp=None,
    )

    mock_opener = MagicMock()
    mock_opener.open = mock_err

    return patch(
        "article_group.yuafeng_hot.build_opener",
        return_value=mock_opener,
    )


def _patch_opener_network_error():
    """Context manager that patches ``build_opener`` to raise URLError."""
    from urllib.error import URLError

    mock_err = MagicMock()
    mock_err.side_effect = URLError("Connection refused")

    mock_opener = MagicMock()
    mock_opener.open = mock_err

    return patch(
        "article_group.yuafeng_hot.build_opener",
        return_value=mock_opener,
    )


def _patch_opener_timeout_error():
    """Context manager that patches ``build_opener`` to raise TimeoutError."""
    mock_err = MagicMock()
    mock_err.side_effect = TimeoutError("timed out")

    mock_opener = MagicMock()
    mock_opener.open = mock_err

    return patch(
        "article_group.yuafeng_hot.build_opener",
        return_value=mock_opener,
    )


def _patch_opener_os_error():
    """Context manager that patches ``build_opener`` to raise OSError."""
    mock_err = MagicMock()
    mock_err.side_effect = OSError("connection reset by peer")

    mock_opener = MagicMock()
    mock_opener.open = mock_err

    return patch(
        "article_group.yuafeng_hot.build_opener",
        return_value=mock_opener,
    )


# ---------------------------------------------------------------------------
# Missing API key
# ---------------------------------------------------------------------------


def test_fetch_uc_hot_missing_key():
    """Raises error when env var is absent."""
    with pytest.raises(YuafengHotError, match="missing_api_key"):
        fetch_uc_hot()


def test_fetch_tencent_news_missing_key():
    with pytest.raises(YuafengHotError, match="missing_api_key"):
        fetch_tencent_news()


def test_fetch_aggregate_missing_key():
    with pytest.raises(YuafengHotError, match="missing_api_key"):
        fetch_aggregate("微博热榜")


# ---------------------------------------------------------------------------
# No secret in exceptions
# ---------------------------------------------------------------------------


def test_key_not_in_exception_on_missing_key(set_api_key):
    """When the key is present but another error occurs, exception message
    must not contain the key value."""
    with _patch_opener_http_error(500) as mock:
        try:
            fetch_uc_hot()
        except YuafengHotError as exc:
            msg = str(exc)
        else:
            pytest.fail("Expected YuafengHotError")

    assert "test-key-12345" not in msg
    # Also check: the URL built during the request isn't leaked
    # The mock opener's open() call receives the full URL; verify it was
    # not included in the exception message
    assert "apikey=" not in msg
    assert set_api_key not in msg


# ---------------------------------------------------------------------------
# Query parameter behaviour — UC
# ---------------------------------------------------------------------------


def test_fetch_uc_hot_url(monkeypatch: pytest.MonkeyPatch, set_api_key: str):
    """Verify the correct endpoint URL is constructed for UC."""
    captured_urls: list[str] = []

    def fake_fetch(url: str) -> dict[str, Any]:
        captured_urls.append(url)
        return {"source": "yuafeng-uc", "endpoint": "/API/xq_shenmahot.php", "fetched_at": "", "source_role": "discovery", "evidence_eligible": False, "raw_json": {}, "items": []}

    import article_group.yuafeng_hot
    original = article_group.yuafeng_hot._fetch_json
    article_group.yuafeng_hot._fetch_json = fake_fetch
    try:
        fetch_uc_hot()
    finally:
        article_group.yuafeng_hot._fetch_json = original

    assert len(captured_urls) == 1
    url = captured_urls[0]
    assert "api-v2.yuafeng.cn" in url
    assert "/API/xq_shenmahot.php" in url
    query = parse_qs(urlparse(url).query)
    assert query == {"type": ["json"], "apikey": [set_api_key]}


# ---------------------------------------------------------------------------
# Tencent News query parameters
# ---------------------------------------------------------------------------


class TestTencentQueryParams:
    """Verify page and type parameter inclusion/exclusion."""

    def _capture(self, set_api_key, **kwargs) -> str:
        captured_urls: list[str] = []

        def fake_fetch(url: str) -> dict[str, Any]:
            captured_urls.append(url)
            return {"raw_json": {}, "items": []}

        import article_group.yuafeng_hot
        original = article_group.yuafeng_hot._fetch_json
        article_group.yuafeng_hot._fetch_json = fake_fetch
        try:
            _ = fetch_tencent_news(**kwargs) if kwargs else fetch_tencent_news()
        finally:
            article_group.yuafeng_hot._fetch_json = original

        assert len(captured_urls) == 1
        return captured_urls[0]

    def test_default_no_optional_params(self, set_api_key):
        url = self._capture(set_api_key)
        query = parse_qs(urlparse(url).query)
        assert query == {"apikey": [set_api_key]}

    def test_with_page(self, set_api_key):
        url = self._capture(set_api_key, page=2)
        assert parse_qs(urlparse(url).query)["page"] == ["2"]

    def test_with_type(self, set_api_key):
        url = self._capture(set_api_key, type_="news")
        assert parse_qs(urlparse(url).query)["type"] == ["news"]

    def test_with_both_options(self, set_api_key):
        url = self._capture(set_api_key, page=1, type_="hot")
        assert parse_qs(urlparse(url).query) == {
            "apikey": [set_api_key],
            "page": ["1"],
            "type": ["hot"],
        }

    @pytest.mark.parametrize("invalid_type", ["", " hot", "hot ", 1, False])
    def test_invalid_type_rejected(self, set_api_key, invalid_type):
        with pytest.raises(YuafengHotError, match="invalid_type"):
            fetch_tencent_news(type_=invalid_type)

    def test_zero_page_rejected(self, set_api_key):
        with pytest.raises(YuafengHotError, match="invalid_page"):
            fetch_tencent_news(page=0)

    def test_negative_page_rejected(self, set_api_key):
        with pytest.raises(YuafengHotError, match="invalid_page"):
            fetch_tencent_news(page=-1)

    @pytest.mark.parametrize("bad_page", [True, False])
    def test_page_bool_rejected(self, set_api_key, bad_page):
        with pytest.raises(YuafengHotError, match="invalid_page"):
            fetch_tencent_news(page=bad_page)


# ---------------------------------------------------------------------------
# Aggregate action validation
# ---------------------------------------------------------------------------


class TestAggregateActionValidation:
    """Only the predefined Chinese actions are accepted."""

    VALID_ACTIONS = [
        "知乎热榜",
        "微博热榜",
        "微信热文榜",
        "澎湃热榜",
        "百度热点",
        "知乎日报",
        "今日头条热榜",
        "梨视频总榜",
    ]

    def test_all_valid_actions_pass(self, set_api_key):
        for action in self.VALID_ACTIONS:
            # Patch _fetch_json so we don't need real HTTP
            with _patch_opener({"data": [{"title": "ok"}]}):
                fetch_aggregate(action)  # should not raise

    def test_invalid_action_rejected(self, set_api_key):
        for action in ("", "知乎", "微薄热榜", "invalid_action", "baidu"):
            with pytest.raises(YuafengHotError, match="invalid_action"):
                fetch_aggregate(action)

    def _capture_url(self, set_api_key, action, page=None) -> str:
        captured: list[str] = []

        def fake_fetch(url: str) -> dict[str, Any]:
            captured.append(url)
            return {"raw_json": {}, "items": []}

        import article_group.yuafeng_hot
        original = article_group.yuafeng_hot._fetch_json
        article_group.yuafeng_hot._fetch_json = fake_fetch
        try:
            fetch_aggregate(action, page=page)
        finally:
            article_group.yuafeng_hot._fetch_json = original

        assert len(captured) == 1
        return captured[0]

    def test_url_contains_action_and_key(self, set_api_key):
        url = self._capture_url(set_api_key, "知乎热榜")
        assert parse_qs(urlparse(url).query) == {
            "apikey": [set_api_key],
            "action": ["知乎热榜"],
        }

    def test_url_with_page(self, set_api_key):
        url = self._capture_url(set_api_key, "微博热榜", page=3)
        assert parse_qs(urlparse(url).query)["page"] == ["3"]

    def test_zero_page_rejected_aggregate(self, set_api_key):
        with pytest.raises(YuafengHotError, match="invalid_page"):
            fetch_aggregate("微博热榜", page=0)

    @pytest.mark.parametrize("bad_page", [True, False])
    def test_page_bool_rejected_aggregate(self, set_api_key, bad_page):
        with pytest.raises(YuafengHotError, match="invalid_page"):
            fetch_aggregate("微博热榜", page=bad_page)

    def test_invalid_action_exception_has_no_key(self, set_api_key):
        try:
            fetch_aggregate("invalid")
        except YuafengHotError as exc:
            assert set_api_key not in str(exc)
        else:
            pytest.fail("Expected YuafengHotError")


# ---------------------------------------------------------------------------
# Error handling — HTTP / network / parse
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Verify fail-closed behaviour for network-level errors."""

    def test_http_403(self, set_api_key):
        with _patch_opener_http_error(403):
            with pytest.raises(YuafengHotError, match="http_error:403"):
                fetch_uc_hot()

    def test_http_500(self, set_api_key):
        with _patch_opener_http_error(500):
            with pytest.raises(YuafengHotError, match="http_error:500"):
                fetch_tencent_news()

    def test_network_error(self, set_api_key):
        with _patch_opener_network_error():
            with pytest.raises(YuafengHotError, match="network_error"):
                fetch_aggregate("微博热榜")

    def test_timeout_error(self, set_api_key):
        with _patch_opener_timeout_error():
            with pytest.raises(YuafengHotError, match="network_error"):
                fetch_tencent_news()

    def test_os_error(self, set_api_key):
        with _patch_opener_os_error():
            with pytest.raises(YuafengHotError, match="network_error"):
                fetch_tencent_news()

    def test_timeout_error_no_secret_in_exception(self, set_api_key):
        with _patch_opener_timeout_error():
            try:
                fetch_tencent_news()
            except YuafengHotError as exc:
                msg = str(exc)
            else:
                pytest.fail("Expected YuafengHotError")
        assert "test-key-12345" not in msg
        assert "timed out" not in msg

    def test_os_error_no_secret_in_exception(self, set_api_key):
        with _patch_opener_os_error():
            try:
                fetch_tencent_news()
            except YuafengHotError as exc:
                msg = str(exc)
            else:
                pytest.fail("Expected YuafengHotError")
        assert "test-key-12345" not in msg
        assert "connection reset" not in msg

    def test_non_json_response(self, set_api_key):
        """A response that is not valid JSON raises parse_error."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json at all"
        mock_resp.__enter__.return_value = mock_resp

        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_resp

        with patch("article_group.yuafeng_hot.build_opener", return_value=mock_opener):
            with pytest.raises(YuafengHotError, match="parse_error"):
                fetch_uc_hot()

    def test_response_with_nested_data_list(self, set_api_key):
        """A typical aggregate response with data wrapping."""
        body = {"data": [{"title": "热点1"}, {"title": "热点2"}]}
        with _patch_opener(body):
            result = fetch_aggregate("知乎热榜")
        assert len(result["items"]) == 2
        assert result["items"][0]["title"] == "热点1"

    def test_response_with_top_level_list(self, set_api_key):
        """Some endpoints return a bare JSON array."""
        body = [{"title": "A"}, {"title": "B"}]
        with _patch_opener(body):
            result = fetch_tencent_news()
        assert len(result["items"]) == 2

    def test_response_with_uc_top_mapping_is_numerically_sorted(self, set_api_key):
        """UC's verified live shape is data.Top_N -> item dictionaries."""
        body = {
            "data": {
                "Top_10": {"title": "第十"},
                "Top_2": {"title": "第二"},
                "Top_1": {"title": "第一"},
            }
        }
        with _patch_opener(body):
            result = fetch_uc_hot()
        assert [item["title"] for item in result["items"]] == ["第一", "第二", "第十"]

    def test_near_miss_top_mapping_is_not_normalized(self, set_api_key):
        """Only an all-Top_N mapping with dictionary values is accepted."""
        body = {"data": {"Top_1": {"title": "第一"}, "other": {"title": "非榜单"}}}
        with _patch_opener(body):
            result = fetch_uc_hot()
        assert result["items"] == []

    def test_normalizaton_empty_on_unkown_shape(self, set_api_key):
        """An unrecognised JSON structure produces an empty items list."""
        body = {"message": "success", "code": 0}
        with _patch_opener(body):
            result = fetch_uc_hot()
        assert result["items"] == []


# ---------------------------------------------------------------------------
# Result envelope structure
# ---------------------------------------------------------------------------


class TestResultEnvelope:
    """Verify the standard discovery envelope fields."""

    def test_complete_envelope(self, set_api_key):
        body = {"data": [{"title": "t1"}]}
        with _patch_opener(body):
            result = fetch_uc_hot()

        assert result["source"] == "yuafeng-uc"
        assert result["endpoint"] == "/API/xq_shenmahot.php"
        assert "fetched_at" in result
        assert result["fetched_at"].endswith("+00:00") or "+00:00" in result["fetched_at"]
        assert result["source_role"] == "discovery"
        assert result["evidence_eligible"] is False
        assert result["raw_json"] == body
        assert result["items"] == [{"title": "t1"}]

    def test_tencent_envelope(self, set_api_key):
        body = {"data": [{"news_id": 1}]}
        with _patch_opener(body):
            result = fetch_tencent_news(type_="hot")

        assert result["source"] == "yuafeng-tencent"
        assert result["endpoint"] == "/API/txxw.php"

    def test_aggregate_envelope(self, set_api_key):
        body = [{"rank": 1}]
        with _patch_opener(body):
            result = fetch_aggregate("澎湃热榜")

        assert result["source"] == "yuafeng-aggregate"
        assert result["endpoint"] == "/API/jinri_hot.php"
        assert result["evidence_eligible"] is False
        assert result["source_role"] == "discovery"

    def test_fetched_at_is_utc(self, set_api_key):
        """Verify fetched_at is a UTC ISO-8601 timestamp."""
        from datetime import timezone
        import uuid
        body = {"data": [str(uuid.uuid4())]}
        with _patch_opener(body):
            result = fetch_uc_hot()
        ts = result["fetched_at"]
        assert "t" in ts.lower() or "T" in ts
        assert ts.endswith("+00:00") or ts.endswith("Z")


# ---------------------------------------------------------------------------
# Module-level guarantees (contract)
# ---------------------------------------------------------------------------


def test_no_automatic_calls_on_import():
    """Importing the module must not trigger any HTTP calls."""
    import importlib
    import sys

    # Remove from cache if loaded
    if "article_group.yuafeng_hot" in sys.modules:
        del sys.modules["article_group.yuafeng_hot"]

    # Track import-time side-effects
    with patch("article_group.yuafeng_hot.build_opener") as mock:
        importlib.import_module("article_group.yuafeng_hot")

    mock.assert_not_called()


def test_empty_env_default(set_api_key):
    """Sanity: default empty env fixture is set up correctly."""
    assert os.environ.get("YUAFENG_API_KEY") == "test-key-12345"