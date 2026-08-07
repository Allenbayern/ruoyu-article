"""tests.test_sources_parsers — 吸收自 media-intel-aios 的离线解析器单元测试。

全部使用自包含合成样本（tmp_path 内构造），不依赖仓库样本文件。
验证 8 个 article_group.sources 模块的 CLI 契约与输出形状。
"""

from __future__ import annotations

import importlib
import json
import sys

import pytest

SOURCES = "article_group.sources"


def run_module(monkeypatch, tmp_path, module_name, argv, expected_rc=0):
    """注入 sys.argv 并运行模块 main()，返回 (rc, 输出路径)。"""
    argv_full = [f"{SOURCES}.{module_name}"] + argv
    monkeypatch.setattr(sys, "argv", argv_full)
    mod = importlib.import_module(f"{SOURCES}.{module_name}")
    rc = mod.main()
    assert rc == expected_rc
    return rc


def write_text(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ---------- douban_fetch: HTML og:* 元数据提取 ----------

def test_douban_fetch_extracts_og_meta(monkeypatch, tmp_path):
    html = write_text(
        tmp_path, "review.html",
        '<html><head>'
        '<meta property="og:title" content="流浪地球2影评" />'
        '<meta property="og:description" content="这是一段影评摘要" />'
        '<meta property="og:url" content="https://movie.douban.com/review/123/" />'
        "</head><body>正文</body></html>",
    )
    out = tmp_path / "out.json"
    run_module(monkeypatch, tmp_path, "douban_fetch",
               ["--sample-html", str(html), "--output", str(out)])
    row = json.loads(out.read_text(encoding="utf-8"))
    assert row["source"] == "douban"
    assert row["title"] == "流浪地球2影评"
    assert row["summary"] == "这是一段影评摘要"
    assert row["url"] == "https://movie.douban.com/review/123/"


def test_douban_fetch_falls_back_to_title_tag(monkeypatch, tmp_path):
    html = write_text(
        tmp_path, "review2.html",
        "<html><head><title>没有 og 的页面</title></head><body>正文</body></html>",
    )
    out = tmp_path / "out.json"
    run_module(monkeypatch, tmp_path, "douban_fetch",
               ["--sample-html", str(html), "--output", str(out)])
    row = json.loads(out.read_text(encoding="utf-8"))
    assert row["title"] == "没有 og 的页面"


# ---------- douban_collect: fetch 结果 → article_vault JSONL ----------

def test_douban_collect_routes_to_article_vault(monkeypatch, tmp_path):
    src = write_text(
        tmp_path, "fetch.json",
        json.dumps({"source": "douban", "title": "T", "summary": "S",
                    "url": "https://movie.douban.com/review/1/"}),
    )
    art = tmp_path / "article.jsonl"
    story = tmp_path / "story.jsonl"
    run_module(monkeypatch, tmp_path, "douban_collect",
               ["--input", str(src), "--article-output", str(art),
                "--story-output", str(story)])
    line = json.loads(art.read_text(encoding="utf-8"))
    assert line["vault"] == "article_vault"
    assert line["content_type"] == "article"
    assert line["raw_score"] == 68
    assert line["title"] == "T"
    assert story.read_text(encoding="utf-8") == ""  # story 输出为空


# ---------- vocus_fetch: JSON 规范化透传 ----------

def test_vocus_fetch_passthrough(monkeypatch, tmp_path):
    payload = {"source": "vocus", "title": "V标题", "content": "正文",
               "url": "https://vocus.cc/a/1", "author": "作者"}
    src = write_text(tmp_path, "v.json", json.dumps(payload))
    out = tmp_path / "out.json"
    run_module(monkeypatch, tmp_path, "vocus_fetch",
               ["--sample-json", str(src), "--output", str(out)])
    assert json.loads(out.read_text(encoding="utf-8")) == payload


# ---------- vocus_collect: → article_vault JSONL（作者/时间/标签） ----------

def test_vocus_collect_keeps_author_and_tags(monkeypatch, tmp_path):
    src = write_text(
        tmp_path, "v.json",
        json.dumps({"source": "vocus", "title": "T", "content": "C",
                    "url": "u", "author": "a", "publish_time": "2026-07-01",
                    "tags": ["电影"]}),
    )
    art = tmp_path / "article.jsonl"
    story = tmp_path / "story.jsonl"
    run_module(monkeypatch, tmp_path, "vocus_collect",
               ["--input", str(src), "--article-output", str(art),
                "--story-output", str(story)])
    line = json.loads(art.read_text(encoding="utf-8"))
    assert line["vault"] == "article_vault"
    assert line["author"] == "a"
    assert line["publish_time"] == "2026-07-01"
    assert line["tags"] == ["电影"]
    assert line["raw_score"] == 70


# ---------- xiniu_collect: HTML title 抽取 ----------

def test_xiniu_collect_extracts_title(monkeypatch, tmp_path):
    html = write_text(
        tmp_path, "x.html",
        "<html><head><title>  春节档数据观察  </title></head><body>正文</body></html>",
    )
    out = tmp_path / "out.jsonl"
    run_module(monkeypatch, tmp_path, "xiniu_collect",
               ["--sample-html", str(html), "--output", str(out)])
    line = json.loads(out.read_text(encoding="utf-8"))
    assert line["source"] == "xiniu-yule"
    assert line["title"] == "春节档数据观察"
    assert line["content_type"] == "article"


# ---------- hotboard_collect: 热榜 JSON → dispatch 行 ----------

def test_hotboard_collect_items_dict_shape(monkeypatch, tmp_path):
    payload = {"items": [
        {"rank": 1, "title": "第一条", "hot": 100, "url": "http://a"},
        {"rank": 2, "name": "第二条", "hot_score": 50},
    ]}
    src = write_text(tmp_path, "hot.json", json.dumps(payload))
    out = tmp_path / "out.jsonl"
    run_module(monkeypatch, tmp_path, "hotboard_collect",
               ["--sample-json", str(src), "--output", str(out)])
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["content_type"] == "dispatch"
    assert rows[0]["rank"] == 1 and rows[0]["hot_score"] == 100
    assert rows[1]["title"] == "第二条" and rows[1]["hot_score"] == 50


def test_hotboard_collect_list_shape(monkeypatch, tmp_path):
    src = write_text(tmp_path, "hot2.json", json.dumps([{"title": "x"}]))
    out = tmp_path / "out.jsonl"
    run_module(monkeypatch, tmp_path, "hotboard_collect",
               ["--sample-json", str(src), "--output", str(out)])
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1 and rows[0]["title"] == "x"


# ---------- zhihu_question_backfill: 只收 zhihu question URL ----------

def test_zhihu_backfill_filters_question_urls(monkeypatch, tmp_path):
    dispatch = write_text(
        tmp_path, "d.jsonl",
        json.dumps({"url": "https://www.zhihu.com/question/123", "title": "Q1"}) + "\n"
        + json.dumps({"url": "https://example.com/other", "title": "X"}) + "\n"
        + json.dumps({"url": "https://www.zhihu.com/question/456"}) + "\n",
    )
    out = tmp_path / "queued.jsonl"
    run_module(monkeypatch, tmp_path, "zhihu_question_backfill",
               ["--dispatch", str(dispatch), "--output", str(out)])
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert all(r["status"] == "queued" for r in rows)
    assert rows[0]["title"] == "Q1"


def test_zhihu_backfill_tolerates_bad_lines(monkeypatch, tmp_path):
    dispatch = write_text(tmp_path, "bad.jsonl", "not-json\n\n")
    out = tmp_path / "queued.jsonl"
    run_module(monkeypatch, tmp_path, "zhihu_question_backfill",
               ["--dispatch", str(dispatch), "--output", str(out)])
    assert out.read_text(encoding="utf-8") == ""


# ---------- route_xiniu_leads: 默认字段补齐 ----------

def test_route_xiniu_leads_defaults(monkeypatch, tmp_path):
    leads = write_text(
        tmp_path, "leads.jsonl",
        json.dumps({"title": "线索1", "url": "u1"}) + "\n"
        + json.dumps({"title": "线索2", "source": "custom", "vault": "story_vault"}) + "\n",
    )
    out = tmp_path / "article.jsonl"
    run_module(monkeypatch, tmp_path, "route_xiniu_leads",
               ["--input", str(leads), "--article-output", str(out)])
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["source"] == "xiniu-yule"          # 默认补齐
    assert rows[0]["vault"] == "article_vault"
    assert rows[0]["raw_score"] == 60
    assert rows[1]["source"] == "custom"              # 已有值不被覆盖
    assert rows[1]["vault"] == "story_vault"


# ---------- 注册表契约 ----------

def test_parsers_registry_matches_modules():
    from article_group.sources import PARSERS

    for name in PARSERS:
        importlib.import_module(f"{SOURCES}.{name}")  # 全部可导入
    assert len(PARSERS) == 8
