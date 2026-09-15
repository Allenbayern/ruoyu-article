"""Tests for the public WeChat body-reading CLI."""

from __future__ import annotations

import json

from article_group.wechat_capture import main


def test_cli_can_print_clean_article_json(monkeypatch, capsys):
    monkeypatch.setattr(
        "article_group.wechat_capture.fetch_wechat_article",
        lambda url, *, timeout: {
            "source": "wechat",
            "canonical_url": url,
            "fetch_url": url,
            "title": "测试标题",
            "author": "作者",
            "account_name": "公众号",
            "publish_time": "",
            "body": "这是正文。",
            "fetch_method": "test",
            "status": "success",
        },
    )

    assert main(["https://mp.weixin.qq.com/s/abc", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"] == "测试标题"
    assert payload["body"] == "这是正文。"
