from __future__ import annotations

from email.message import Message
from urllib.error import HTTPError

import pytest

from article_group.toutiao import (
    ToutiaoExtractionError,
    canonical_mobile_url,
    extract_toutiao_article,
    fetch_toutiao_article,
)


ARTICLE_HTML = """<!doctype html>
<html><head>
<meta property="og:title" content="样本标题 - 今日头条">
</head><body>
<article><h1>样本标题</h1><p>这是第一段真实正文，长度足够用于验证。</p>
<p>这是第二段真实正文，不能被挑战页面替代。</p></article>
</body></html>"""

CHALLENGE_HTML = """<!doctype html><html><body><script>
window.byted_acrawler={sign:function(){return 'challenge'}};
</script></body></html>"""


@pytest.mark.parametrize(
    ("input_url", "expected"),
    [
        (
            "https://www.toutiao.com/article/7667134749114925620/?log_from=tracking",
            "https://m.toutiao.com/article/7667134749114925620/",
        ),
        (
            "https://m.toutiao.com/article/7667134749114925620/",
            "https://m.toutiao.com/article/7667134749114925620/",
        ),
        (
            "https://www.toutiao.com/i7667134749114925620/",
            "https://m.toutiao.com/article/7667134749114925620/",
        ),
    ],
)
def test_canonical_mobile_url(input_url: str, expected: str):
    assert canonical_mobile_url(input_url) == expected


@pytest.mark.parametrize(
    "input_url",
    [
        "https://example.com/article/7667134749114925620/",
        "https://www.toutiao.com/article/not-an-id/",
        "https://www.toutiao.com/ch/news_hot/",
    ],
)
def test_canonical_mobile_url_rejects_unsupported_urls(input_url: str):
    with pytest.raises(ToutiaoExtractionError, match="unsupported_toutiao_url"):
        canonical_mobile_url(input_url)


def test_extract_rejects_challenge_page_before_parser_runs():
    with pytest.raises(ToutiaoExtractionError, match="blocked_challenge"):
        extract_toutiao_article(CHALLENGE_HTML, "https://m.toutiao.com/article/7667134749114925620/")


def test_extract_rejects_static_shell_without_article_root():
    with pytest.raises(ToutiaoExtractionError, match="static_body_missing"):
        extract_toutiao_article("<html><h1>标题</h1></html>", "https://m.toutiao.com/article/1/")


def test_extract_returns_title_body_and_canonical_url(monkeypatch):
    monkeypatch.setattr("article_group.toutiao._extract_text", lambda html: "第一段真实正文。\n\n第二段真实正文。")

    result = extract_toutiao_article(
        ARTICLE_HTML, "https://m.toutiao.com/article/7667134749114925620/"
    )

    assert result == {
        "source": "toutiao",
        "canonical_url": "https://m.toutiao.com/article/7667134749114925620/",
        "title": "样本标题",
        "body": "第一段真实正文。\n\n第二段真实正文。",
        "status": "success",
    }


def test_fetch_uses_mobile_canonical_url_and_reports_http_block(monkeypatch):
    requested: list[str] = []

    def fake_urlopen(request, timeout):
        requested.append(request.full_url)
        raise HTTPError(request.full_url, 403, "Forbidden", hdrs=Message(), fp=None)

    monkeypatch.setattr("article_group.toutiao._open_without_proxy", fake_urlopen)

    with pytest.raises(ToutiaoExtractionError, match="http_error:403"):
        fetch_toutiao_article("https://www.toutiao.com/article/7667134749114925620/")

    assert requested == ["https://m.toutiao.com/article/7667134749114925620/"]
