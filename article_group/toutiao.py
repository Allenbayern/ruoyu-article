"""Public, no-session extraction for single 今日头条 article URLs.

The adapter only performs a normal GET against the official mobile article surface.
It never executes JavaScript, produces anti-bot signatures, injects cookies, or uses
proxies. Challenge pages and non-article shells fail closed with stable error codes.
"""

from __future__ import annotations

from html.parser import HTMLParser
import re
from typing import Final
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener


_MOBILE_URL_TEMPLATE: Final = "https://m.toutiao.com/article/{article_id}/"
_MOBILE_USER_AGENT: Final = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
)
_CHALLENGE_MARKERS: Final = ("byted_acrawler", "__acrawler", "captcha", "verify")
_ARTICLE_ID_RE: Final = re.compile(r"/(?:article/(\d+)|i(\d+))(?:/|$)")


class ToutiaoExtractionError(ValueError):
    """Raised when a URL is unsupported or its public static body is unavailable."""


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_h1 = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "h1" and not self._parts:
            self._in_h1 = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "h1":
            self._in_h1 = False

    def handle_data(self, data: str) -> None:
        if self._in_h1:
            self._parts.append(data)

    @property
    def title(self) -> str:
        return re.sub(r"\s+", " ", "".join(self._parts)).strip()


def canonical_mobile_url(url: str) -> str:
    """Convert a supported Toutiao PC/mobile permanent link to its mobile article URL."""
    parsed = urlparse(url)
    host = parsed.hostname.lower() if parsed.hostname else ""
    if parsed.scheme not in {"http", "https"} or not host.endswith("toutiao.com"):
        raise ToutiaoExtractionError("unsupported_toutiao_url")
    match = _ARTICLE_ID_RE.search(parsed.path)
    if not match:
        raise ToutiaoExtractionError("unsupported_toutiao_url")
    return _MOBILE_URL_TEMPLATE.format(article_id=match.group(1) or match.group(2))


def _has_article_root(html: str) -> bool:
    return bool(re.search(r"<article(?:\s|>)", html, re.IGNORECASE))


def _has_challenge_marker(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in _CHALLENGE_MARKERS)


def _extract_title(html: str) -> str:
    parser = _TitleParser()
    parser.feed(html)
    parser.close()
    return parser.title


def _extract_text(html: str) -> str:
    try:
        import trafilatura
    except ImportError as error:  # pragma: no cover - dependency installation is packaging-owned
        raise ToutiaoExtractionError("parser_unavailable:trafilatura") from error
    return trafilatura.extract(html, include_comments=False, include_tables=False) or ""


def _open_without_proxy(request: Request, timeout: float):
    """Open only through the direct connection, ignoring ambient proxy variables."""
    return build_opener(ProxyHandler({})).open(request, timeout=timeout)


def extract_toutiao_article(html: str, canonical_url: str) -> dict[str, str]:
    """Validate public mobile HTML and extract a non-script article body fail-closed."""
    if _has_challenge_marker(html):
        raise ToutiaoExtractionError("blocked_challenge")
    if not _has_article_root(html):
        raise ToutiaoExtractionError("static_body_missing")
    title = _extract_title(html)
    body = _extract_text(html).strip()
    if not title or not body or _has_challenge_marker(body):
        raise ToutiaoExtractionError("static_body_missing")
    return {
        "source": "toutiao",
        "canonical_url": canonical_url,
        "title": title,
        "body": body,
        "status": "success",
    }


def fetch_toutiao_article(url: str, *, timeout: float = 30.0) -> dict[str, str]:
    """Fetch one public Toutiao article without cookies, proxies, or JS execution."""
    canonical_url = canonical_mobile_url(url)
    request = Request(
        canonical_url,
        headers={"User-Agent": _MOBILE_USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    try:
        with _open_without_proxy(request, timeout) as response:
            html = response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        raise ToutiaoExtractionError(f"http_error:{error.code}") from error
    except URLError as error:
        raise ToutiaoExtractionError("network_error") from error
    return extract_toutiao_article(html, canonical_url)
