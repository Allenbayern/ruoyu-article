"""Tests for the public WeChat article fetch and evidence capture path."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from article_group.wechat import (
    WechatExtractionError,
    extract_wechat_article,
    fetch_wechat_article,
    normalize_wechat_url,
)
from article_group.wechat_capture import capture_wechat_source


ARTICLE_HTML = """
<!doctype html>
<html>
<head>
  <meta property="og:title" content="页面标题">
  <meta property="article:author" content="文章作者">
  <script>
    var msg_title = '脚本标题';
    var nickname = htmlDecode("测试公号");
    var publish_time = "2026-09-14 10:20";
  </script>
</head>
<body>
  <div id="js_content">
    <p>第一段是正文事实。</p>
    <section><strong>第二段</strong>继续提供场景。</section>
    <blockquote>这里是引用。</blockquote>
  </div>
</body>
</html>
"""

CHALLENGE_HTML = """
<html><head><title>环境异常</title></head>
<body><div id="secitptpage">完成验证后即可继续访问</div></body></html>
"""


class _FakeResponse:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._body


def test_normalize_wechat_url_adds_public_scene_parameter():
    assert normalize_wechat_url("https://mp.weixin.qq.com/s/abc?from=appmsg") == (
        "https://mp.weixin.qq.com/s/abc?from=appmsg&scene=25"
    )


def test_normalize_wechat_url_rejects_non_public_article_hosts():
    with pytest.raises(WechatExtractionError, match="unsupported_wechat_url"):
        normalize_wechat_url("https://example.com/s/abc")

    with pytest.raises(WechatExtractionError, match="unsupported_wechat_url"):
        normalize_wechat_url("https://mp.weixin.qq.com/cgi-bin/login")


def test_extract_wechat_article_reads_metadata_and_js_content():
    result = extract_wechat_article(
        ARTICLE_HTML,
        "https://mp.weixin.qq.com/s/abc?scene=25",
        fetch_method="test_profile",
    )

    assert result["title"] == "页面标题"
    assert result["author"] == "文章作者"
    assert result["account_name"] == "测试公号"
    assert result["publish_time"] == "2026-09-14 10:20"
    assert "第一段是正文事实。" in result["body"]
    assert "第二段继续提供场景。" in result["body"]
    assert "这里是引用。" in result["body"]
    assert result["fetch_method"] == "test_profile"


def test_fetch_uses_mobile_public_profiles_after_a_challenge_page():
    responses = [_FakeResponse(CHALLENGE_HTML), _FakeResponse(ARTICLE_HTML)]
    seen: list[tuple[str, str]] = []

    def open_url(request, timeout):
        seen.append((request.full_url, request.headers["User-agent"]))
        return responses.pop(0)

    result = fetch_wechat_article(
        "https://mp.weixin.qq.com/s/abc",
        timeout=7,
        open_url=open_url,
    )

    assert result["title"] == "页面标题"
    assert result["fetch_url"] == "https://mp.weixin.qq.com/s/abc?scene=25"
    assert result["fetch_method"] == "direct_html:android_wechat"
    assert len(seen) == 2
    assert all("scene=25" in url for url, _ua in seen)
    assert "MicroMessenger" in seen[0][1]
    assert "MicroMessenger" in seen[1][1]


def test_fetch_never_accepts_a_200_challenge_as_article_body():
    def open_url(_request, _timeout):
        return _FakeResponse(CHALLENGE_HTML)

    with pytest.raises(WechatExtractionError, match="captcha_or_access_blocked"):
        fetch_wechat_article("https://mp.weixin.qq.com/s/abc", open_url=open_url)


def test_fetch_distinguishes_a_plain_static_shell_from_network_failure():
    def open_url(_request, _timeout):
        return _FakeResponse("<html><head><title>登录</title></head><body>登录</body></html>")

    with pytest.raises(WechatExtractionError, match="static_body_missing"):
        fetch_wechat_article("https://mp.weixin.qq.com/s/abc", open_url=open_url)


def test_capture_writes_clean_body_sidecar_and_manifest(tmp_path: Path, monkeypatch):
    def fake_fetch(url: str, *, timeout: float = 30.0) -> dict[str, str]:
        assert url == "https://mp.weixin.qq.com/s/abc"
        assert timeout == 11
        return {
            "source": "wechat",
            "canonical_url": "https://mp.weixin.qq.com/s/abc?scene=25",
            "fetch_url": "https://mp.weixin.qq.com/s/abc?scene=25",
            "title": "测试文章",
            "author": "文章作者",
            "account_name": "测试公号",
            "publish_time": "2026-09-14 10:20",
            "body": "第一段。\n\n第二段。",
            "fetch_method": "direct_html:iphone_wechat",
            "status": "success",
        }

    monkeypatch.setattr("article_group.wechat_capture.fetch_wechat_article", fake_fetch)

    result = capture_wechat_source(
        "https://mp.weixin.qq.com/s/abc",
        tmp_path,
        "WX1",
        role="research-reference",
        independence_group="wechat-test",
        timeout=11,
    )

    snapshot = tmp_path / "sources" / "WX1.clean.md"
    sidecar = tmp_path / "sources" / "WX1.source.json"
    assert snapshot.read_text(encoding="utf-8") == "第一段。\n\n第二段。\n"
    assert result["relative_path"] == "sources/WX1.clean.md"
    assert result["sha256"] == hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert result["url"] == "https://mp.weixin.qq.com/s/abc?scene=25"
    assert result["title"] == "测试文章"
    assert result["account_name"] == "测试公号"
    assert result["capture_method"] == "direct_html:iphone_wechat"
    assert result["capture_type"] == "page_fulltext"
    assert result["declared_source_level"] == "fulltext"
    assert result["role"] == "research-reference"
    assert result["independence_group"] == "wechat-test"

    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    assert metadata["source_id"] == "WX1"
    assert metadata["clean_sha256"] == result["sha256"]
    assert metadata["capture_status"] == "full"
    assert metadata["capture_type"] == "page_fulltext"
    assert metadata["body_path"] == "sources/WX1.clean.md"


def test_capture_does_not_overwrite_existing_snapshot(tmp_path: Path, monkeypatch):
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "WX1.clean.md").write_text("existing", encoding="utf-8")

    monkeypatch.setattr(
        "article_group.wechat_capture.fetch_wechat_article",
        lambda *_args, **_kwargs: pytest.fail("must reject before fetching"),
    )

    with pytest.raises(ValueError, match="snapshot already exists"):
        capture_wechat_source("https://mp.weixin.qq.com/s/abc", tmp_path, "WX1")


def test_capture_propagates_extraction_error_without_creating_files(tmp_path: Path, monkeypatch):
    def bad_fetch(*_args, **_kwargs):
        raise WechatExtractionError("captcha_or_access_blocked")

    monkeypatch.setattr("article_group.wechat_capture.fetch_wechat_article", bad_fetch)

    with pytest.raises(WechatExtractionError, match="captcha_or_access_blocked"):
        capture_wechat_source("https://mp.weixin.qq.com/s/abc", tmp_path, "WX2")

    assert not (tmp_path / "sources").exists()
