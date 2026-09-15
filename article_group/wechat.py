"""Public, no-session extraction for single WeChat article URLs.

WeChat may return a HTTP 200 interstitial instead of an article.  The adapter
uses the public article surface with a normal mobile browser profile and the
public ``scene=25`` query parameter, then fails closed unless ``#js_content``
contains real text.  It never supplies cookies, tokens, proxy credentials,
captcha answers, or JavaScript-generated anti-bot signatures.
"""

from __future__ import annotations

from html.parser import HTMLParser
from collections.abc import Callable
import re
import time
from typing import Any, Final
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


_WECHAT_HOSTS: Final = frozenset({"mp.weixin.qq.com", "m.mp.weixin.qq.com"})
_SCENE: Final = "25"
_CHALLENGE_MARKERS: Final = (
    "环境异常",
    "当前环境异常",
    "完成验证后即可继续访问",
    "访问过于频繁",
    "secitptpage",
    "js_verify",
    "verifycode",
    "captcha",
)
_MOBILE_PROFILES: Final = (
    (
        "iphone_wechat",
        (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Mobile/15E148 MicroMessenger/8.0.50"
        ),
    ),
    (
        "android_wechat",
        (
            "Mozilla/5.0 (Linux; Android 14; Pixel 7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Mobile Safari/537.36 "
            "MicroMessenger/8.0.50"
        ),
    ),
    (
        "iphone_safari",
        (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.0 Mobile/15E148 Safari/604.1"
        ),
    ),
)
_BLOCK_TAGS: Final = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "div",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "tr",
        "ul",
    }
)
_VOID_TAGS: Final = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
class WechatExtractionError(ValueError):
    """Raised when a public WeChat page cannot provide a trustworthy body."""

    def __init__(self, code: str, *, attempts: list[str] | None = None) -> None:
        self.code = code
        self.attempts = list(attempts or [])
        super().__init__(code)


class _ContentParser(HTMLParser):
    """Collect text under the first element whose id is ``js_content``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._found = False
        self._done = False
        self._root_tag = ""
        self._depth = 0
        self._suppressed_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._done:
            return

        attr_map = {key.lower(): value for key, value in attrs if key}
        if not self._found:
            if attr_map.get("id", "").lower() == "js_content":
                self._found = True
                self._root_tag = tag
                self._depth = 1
            return

        if self._suppressed_depth:
            if tag in {"script", "style"}:
                self._suppressed_depth += 1
        else:
            if tag in _BLOCK_TAGS:
                self._parts.append("\n\n")
            elif tag == "br":
                self._parts.append("\n")
            if tag in {"script", "style"}:
                self._suppressed_depth = 1

        if tag not in _VOID_TAGS:
            self._depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._done:
            return
        attr_map = {key.lower(): value for key, value in attrs if key}
        if not self._found and attr_map.get("id", "").lower() == "js_content":
            self._found = True
            self._root_tag = tag
            self._depth = 0
            self._done = True
            return
        if self._found and not self._suppressed_depth:
            if tag == "br":
                self._parts.append("\n")
            elif tag in _BLOCK_TAGS:
                self._parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self._found or self._done:
            return

        if self._suppressed_depth:
            if tag in {"script", "style"}:
                self._suppressed_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n\n")

        if tag not in _VOID_TAGS:
            self._depth -= 1
        if self._depth <= 0 and tag == self._root_tag:
            self._done = True

    def handle_data(self, data: str) -> None:
        if self._found and not self._done and not self._suppressed_depth:
            self._parts.append(data)

    @property
    def found(self) -> bool:
        return self._found

    @property
    def text(self) -> str:
        raw = "".join(self._parts)
        raw = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
        raw = re.sub(r"[ \t\f\v]+", " ", raw)
        raw = re.sub(r" *\n *", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


class _MetadataParser(HTMLParser):
    """Read ordinary HTML metadata without executing page JavaScript."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.metadata: dict[str, str] = {}
        self._in_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr_map = {key.lower(): value or "" for key, value in attrs if key}
        if tag == "meta":
            key = attr_map.get("property") or attr_map.get("name")
            value = attr_map.get("content", "").strip()
            if key and value and key.lower() not in self.metadata:
                self.metadata[key.lower()] = value
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)

    @property
    def title(self) -> str:
        return re.sub(r"\s+", " ", "".join(self._title_parts)).strip()


def normalize_wechat_url(url: str) -> str:
    """Validate a public WeChat article URL and add the stable public scene."""
    if not isinstance(url, str) or not url.strip():
        raise WechatExtractionError("unsupported_wechat_url")

    parsed = urlsplit(url.strip())
    host = parsed.hostname.lower() if parsed.hostname else ""
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or host not in _WECHAT_HOSTS
        or parsed.username
        or parsed.password
        or not (parsed.path == "/s" or parsed.path.startswith("/s/"))
    ):
        raise WechatExtractionError("unsupported_wechat_url")

    try:
        port = parsed.port
    except ValueError as error:
        raise WechatExtractionError("unsupported_wechat_url") from error
    if port not in {None, 80, 443}:
        raise WechatExtractionError("unsupported_wechat_url")

    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    normalized_items: list[tuple[str, str]] = []
    scene_seen = False
    for key, value in query_items:
        if key.lower() == "scene":
            if not scene_seen:
                normalized_items.append((key, _SCENE))
                scene_seen = True
        else:
            normalized_items.append((key, value))
    if not scene_seen:
        normalized_items.append(("scene", _SCENE))

    netloc = host
    if port is not None and port not in {80, 443}:
        netloc = f"{host}:{port}"
    return urlunsplit(
        (
            "https",
            netloc,
            parsed.path,
            urlencode(normalized_items),
            "",
        )
    )


def _has_challenge_marker(html: str) -> bool:
    lowered = html.lower()
    return any(marker.lower() in lowered for marker in _CHALLENGE_MARKERS)


def _parse_content(html: str) -> tuple[bool, str]:
    parser = _ContentParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as error:  # HTMLParser should be forgiving, but fail closed.
        raise WechatExtractionError("html_parse_failed") from error
    return parser.found, parser.text


def _decode_js_string(value: str) -> str:
    """Decode the small JS string escapes used by WeChat metadata variables."""
    value = re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda match: chr(int(match.group(1), 16)),
        value,
    )
    value = re.sub(
        r"\\x([0-9a-fA-F]{2})",
        lambda match: chr(int(match.group(1), 16)),
        value,
    )
    replacements = {
        r"\\n": "\n",
        r"\\r": "\r",
        r"\\t": "\t",
        r"\\\\": "\\",
        r"\\\"": '"',
        r"\\'": "'",
        r"\\/": "/",
    }
    for escaped, decoded in replacements.items():
        value = value.replace(escaped, decoded)
    return value.strip()


def _extract_js_assignment(html: str, name: str) -> str:
    for quote in ("'", '"'):
        escaped_quote = re.escape(quote)
        pattern = re.compile(
            rf"\b(?:var\s+)?{re.escape(name)}\s*=\s*"
            rf"(?:htmlDecode\s*\(\s*)?{escaped_quote}"
            rf"((?:\\.|(?!{escaped_quote}).)*){escaped_quote}",
            re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(html)
        if match:
            return _decode_js_string(match.group(1))
    return ""


def _extract_metadata(html: str) -> dict[str, str]:
    parser = _MetadataParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as error:  # pragma: no cover - defensive against malformed HTML
        raise WechatExtractionError("html_parse_failed") from error

    title = (
        parser.metadata.get("og:title")
        or _extract_js_assignment(html, "msg_title")
        or parser.title
    )
    author = (
        parser.metadata.get("article:author")
        or parser.metadata.get("author")
        or _extract_js_assignment(html, "author")
    )
    account_name = (
        _extract_js_assignment(html, "nickname")
        or parser.metadata.get("profile:username")
        or parser.metadata.get("og:site_name")
    )
    publish_time = (
        parser.metadata.get("article:published_time")
        or _extract_js_assignment(html, "publish_time")
        or _extract_js_assignment(html, "publishTime")
    )
    return {
        "title": title.strip(),
        "author": author.strip(),
        "account_name": account_name.strip(),
        "publish_time": publish_time.strip(),
        "page_canonical_url": parser.metadata.get("og:url", "").strip(),
    }


def extract_wechat_article(
    html: str,
    canonical_url: str,
    *,
    fetch_method: str = "direct_html",
) -> dict[str, str]:
    """Extract a full public article body, rejecting WeChat interstitial HTML."""
    if not isinstance(html, str) or not html:
        raise WechatExtractionError("static_body_missing")

    found, body = _parse_content(html)
    if not found:
        if _has_challenge_marker(html):
            raise WechatExtractionError("captcha_or_access_blocked")
        raise WechatExtractionError("static_body_missing")
    if not body:
        if _has_challenge_marker(html):
            raise WechatExtractionError("captcha_or_access_blocked")
        raise WechatExtractionError("static_body_missing")

    metadata = _extract_metadata(html)
    if not metadata["title"]:
        raise WechatExtractionError("article_title_missing")

    return {
        "source": "wechat",
        "canonical_url": canonical_url,
        "fetch_url": canonical_url,
        "page_canonical_url": metadata["page_canonical_url"],
        "title": metadata["title"],
        "author": metadata["author"],
        "account_name": metadata["account_name"],
        "publish_time": metadata["publish_time"],
        "body": body,
        "fetch_method": fetch_method,
        "status": "success",
    }


def _decode_response(raw: bytes, response: Any) -> str:
    charset = ""
    headers = getattr(response, "headers", None)
    if headers is not None:
        get_charset = getattr(headers, "get_content_charset", None)
        if callable(get_charset):
            charset = get_charset() or ""
    for encoding in (charset, "utf-8", "gb18030"):
        if not encoding:
            continue
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def _default_open_url(request: Request, timeout: float):
    return urlopen(request, timeout=timeout)


def _read_response(
    open_url: Callable[[Request, float], Any], request: Request, timeout: float
) -> str:
    response = open_url(request, timeout)
    try:
        raw = response.read()
        if isinstance(raw, str):
            return raw
        return _decode_response(raw, response)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def fetch_wechat_article(
    url: str,
    *,
    timeout: float = 30.0,
    open_url: Callable[[Request, float], Any] | None = None,
) -> dict[str, str]:
    """Fetch one public WeChat article without cookies, tokens, or JS execution.

    ``open_url`` is intentionally injectable for deterministic tests.  A
    production caller should leave it unset so the standard URL opener is used.
    Each request is independent and carries only ordinary browser headers.
    """
    if timeout <= 0:
        raise ValueError("timeout must be positive")

    fetch_url = normalize_wechat_url(url)
    opener = open_url or _default_open_url
    attempts: list[str] = []
    saw_challenge = False
    saw_static_body_missing = False
    network_failures = 0

    for profile_name, user_agent in _MOBILE_PROFILES:
        request = Request(
            fetch_url,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Upgrade-Insecure-Requests": "1",
            },
        )
        try:
            html = _read_response(opener, request, timeout)
            return extract_wechat_article(
                html,
                fetch_url,
                fetch_method=f"direct_html:{profile_name}",
            )
        except WechatExtractionError as error:
            attempts.append(f"{profile_name}:{error.code}")
            saw_challenge = saw_challenge or error.code == "captcha_or_access_blocked"
            saw_static_body_missing = saw_static_body_missing or error.code in {
                "static_body_missing",
                "article_title_missing",
                "html_parse_failed",
            }
        except HTTPError as error:
            attempts.append(f"{profile_name}:http_error:{error.code}")
        except (URLError, TimeoutError, OSError) as error:
            error_name = "timeout" if isinstance(error, TimeoutError) else "network_error"
            attempts.append(f"{profile_name}:{error_name}")
            network_failures += 1

    # A short, single retry helps with a transient connection reset without
    # turning a challenge into an unbounded scrape loop.  Do not retry after a
    # challenge or a valid HTML response that simply lacks an article root.
    if network_failures == len(_MOBILE_PROFILES):
        time.sleep(0.5)
        profile_name, user_agent = _MOBILE_PROFILES[0]
        request = Request(
            fetch_url,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Upgrade-Insecure-Requests": "1",
            },
        )
        try:
            html = _read_response(opener, request, timeout)
            return extract_wechat_article(
                html,
                fetch_url,
                fetch_method=f"direct_html:{profile_name}:retry",
            )
        except WechatExtractionError as error:
            attempts.append(f"{profile_name}:retry:{error.code}")
            saw_challenge = saw_challenge or error.code == "captcha_or_access_blocked"
            saw_static_body_missing = saw_static_body_missing or error.code in {
                "static_body_missing",
                "article_title_missing",
                "html_parse_failed",
            }
        except HTTPError as error:
            attempts.append(f"{profile_name}:retry:http_error:{error.code}")
        except (URLError, TimeoutError, OSError) as error:
            error_name = "timeout" if isinstance(error, TimeoutError) else "network_error"
            attempts.append(f"{profile_name}:retry:{error_name}")

    if saw_challenge:
        code = "captcha_or_access_blocked"
    elif saw_static_body_missing:
        code = "static_body_missing"
    else:
        code = "fetch_failed"
    raise WechatExtractionError(code, attempts=attempts)


__all__ = [
    "WechatExtractionError",
    "extract_wechat_article",
    "fetch_wechat_article",
    "normalize_wechat_url",
]
