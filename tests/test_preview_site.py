"""预览页生成器：渲染保真、零外链、可发布、越界拒绝。

覆盖 2026-09-18 接入 daily_engine 的 `article_group.preview_site`：
controller 要的是"标题能点、点开能读"的链接，而 run 里的 Markdown / 公众号 HTML
本身没有被任何服务托管——本模块负责把 run 产物渲染成自包含静态站点。
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

import pytest

from article_group.preview_site import build, delivery_status, md_to_html, publish, read_article, slug

BODY_1 = """## 第一节

第一段正文，含《书名号》与"引号"。

第二段正文，含 <尖括号> 与 & 符号，用于验证转义。

## 第二节

第三段正文。"""

BODY_2 = """## 只有一节

另一篇的第一段。"""


def _make_run(tmp_path: Path, *, with_wechat: bool = True, with_delivery_record: bool = True) -> Path:
    run = tmp_path / "2026-09-17" / "daily-999"
    (run / "delivery/art-001").mkdir(parents=True)
    (run / "delivery/art-002").mkdir(parents=True)
    (run / "delivery/art-001/delivery.md").write_text(f"# 甲标题\n\n{BODY_1}\n", encoding="utf-8")
    (run / "delivery/art-002/delivery.md").write_text(f"# 乙标题\n\n{BODY_2}\n", encoding="utf-8")
    (run / "batch.json").write_text(json.dumps({
        "schema_version": "article-group-run-v1",
        "articles": [
            {"article_id": "art-001", "title": "甲标题", "review_hook": "钩子甲"},
            {"article_id": "art-002", "title": "乙标题", "review_hook": "钩子乙"},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    (run / "review").mkdir()
    if with_delivery_record:
        (run / "review/content-delivery.json").write_text(json.dumps({
            "content_status": "CONTENT_READY", "publication_authorization": "not_authorized",
        }, ensure_ascii=False), encoding="utf-8")
    (run / "review/final-review.json").write_text(json.dumps({
        "verdict": "PENDING", "content_result": "PASS", "evidence_result": "PASS", "governance_result": "PENDING",
    }, ensure_ascii=False), encoding="utf-8")
    if with_wechat:
        (run / "wechat").mkdir()
        (run / "wechat/art-001.html").write_text("<html>公众号复制版甲</html>", encoding="utf-8")
        (run / "wechat/art-001.wx.html").write_text("<section>片段甲</section>", encoding="utf-8")
        (run / "wechat/index.html").write_text("<html>复制版目录</html>", encoding="utf-8")
    return run


# ── 渲染层 ──────────────────────────────────────────────────────────────

def test_md_to_html_maps_headings_and_paragraphs():
    out = md_to_html("## 小标题\n\n一段话。\n\n又一段。")
    assert out == "<h2>小标题</h2>\n<p>一段话。</p>\n<p>又一段。</p>"


def test_md_to_html_escapes_markup_and_drops_h1():
    out = md_to_html("# 标题\n\n正文含 <b> 与 & 号。")
    assert "<b>" not in out
    assert "&lt;b&gt;" in out and "&amp;" in out
    assert "标题" not in out.split("\n")[0]  # H1 由页面模板单独渲染，不重复


def test_md_to_html_keeps_unknown_lines_as_paragraphs():
    out = md_to_html("- 这不是列表语法，按段落处理")
    assert out.startswith("<p>") and "这不是列表语法" in out


def test_read_article_reports_cjk_and_hash(tmp_path):
    run = _make_run(tmp_path)
    art = read_article(run, "art-001")
    assert art["title"] == "甲标题"
    assert art["cjk_chars"] == len(re.findall(r"[\u4e00-\u9fff]", BODY_1))
    assert len(art["sha256"]) == 64


# ── 站点生成 ────────────────────────────────────────────────────────────

def test_build_writes_index_and_reading_pages(tmp_path):
    run = _make_run(tmp_path)
    report = build(run)

    assert report["status"] == "ok"
    assert report["content_status"] == "CONTENT_READY"
    assert report["index_path"] == "preview/index.html"
    for relative in ("preview/index.html", "preview/art-001.html", "preview/art-002.html",
                     "preview/wechat/art-001.html", "preview/wechat/art-001.wx.html"):
        assert (run / relative).is_file(), relative

    index = (run / "preview/index.html").read_text(encoding="utf-8")
    # 标题即链接
    assert '<a href="art-001.html">甲标题</a>' in index
    assert '<a href="art-002.html">乙标题</a>' in index
    assert "CONTENT_READY" in index and "not_authorized" in index
    assert "PASS" in index  # 终审三栏来自 final-review.json


def test_reading_page_matches_markdown_paragraph_by_paragraph(tmp_path):
    run = _make_run(tmp_path)
    build(run)

    for aid, body in (("art-001", BODY_1), ("art-002", BODY_2)):
        page = (run / f"preview/{aid}.html").read_text(encoding="utf-8")
        got = [html.unescape(x) for x in re.findall(r"<p>(.*?)</p>", page, flags=re.S)]
        want = [b.strip() for b in body.split("\n\n") if b.strip() and not b.startswith("#")]
        assert got == want, aid
        # H2 数量一致
        assert page.count("<h2>") == len(re.findall(r"^## ", body, flags=re.M))


def test_pages_have_no_external_resources(tmp_path):
    run = _make_run(tmp_path)
    build(run)
    for relative in ("preview/index.html", "preview/art-001.html", "preview/art-002.html"):
        page = (run / relative).read_text(encoding="utf-8")
        assert not re.search(r'(?:src|href)="https?://', page), relative
        assert "<link " not in page and "<script" not in page


def test_build_degrades_without_delivery_record_and_wechat(tmp_path):
    run = _make_run(tmp_path, with_wechat=False, with_delivery_record=False)
    report = build(run)

    assert report["status"] == "ok"
    assert report["content_status"] == "PENDING_L2"          # 退回 batch 口径，不假装通过
    assert report["copied"] == []
    assert (run / "preview/art-001.html").is_file()


def test_build_requires_batch_articles(tmp_path):
    run = _make_run(tmp_path)
    (run / "batch.json").write_text(json.dumps({"articles": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        build(run)


def test_build_is_idempotent_and_ledgered(tmp_path):
    run = _make_run(tmp_path)
    build(run)
    first = (run / "preview/index.html").read_bytes()
    build(run)
    assert (run / "preview/index.html").read_bytes() == first
    changelog = (run / "evidence-changelog.jsonl").read_text(encoding="utf-8")
    assert "preview_site:index" in changelog


def test_delivery_status_prefers_delivery_record(tmp_path):
    run = _make_run(tmp_path)
    batch = json.loads((run / "batch.json").read_text(encoding="utf-8"))
    assert delivery_status(run, batch) == "CONTENT_READY"
    (run / "review/content-delivery.json").unlink()
    assert delivery_status(run, batch) == "PENDING_L2"
    assert delivery_status(tmp_path / "nope", {}) == "UNKNOWN"


def test_slug_is_date_dash_run_name(tmp_path):
    run = _make_run(tmp_path)
    assert slug(run) == "2026-09-17-daily-999"


# ── 发布层 ──────────────────────────────────────────────────────────────

def test_publish_copies_site_and_records_where(tmp_path):
    run = _make_run(tmp_path)
    build(run)
    static = tmp_path / "outbox"
    static.mkdir()

    record = publish(run, static, base_url="http://192.168.100.168:8899")

    assert record["target"] == str((static / "2026-09-17-daily-999").resolve())
    assert record["index_url"] == "http://192.168.100.168:8899/2026-09-17-daily-999/"
    assert (static / "2026-09-17-daily-999/art-001.html").is_file()
    assert record["publication_authorization"] == "not_authorized"
    written = json.loads((run / "preview/publish-record.json").read_text(encoding="utf-8"))
    assert written["target"] == record["target"] and written["files"]


def test_publish_refuses_escape_and_missing_preview(tmp_path):
    run = _make_run(tmp_path)
    static = tmp_path / "outbox"
    static.mkdir()
    with pytest.raises(FileNotFoundError):
        publish(run, static)                      # 还没 build
    build(run)
    with pytest.raises(ValueError):
        publish(run, static, name="../../escape")  # 越界 fail-closed
    assert not (tmp_path / "escape").exists()


def test_publish_requires_existing_static_root(tmp_path):
    run = _make_run(tmp_path)
    build(run)
    with pytest.raises(NotADirectoryError):
        publish(run, tmp_path / "missing-root")
