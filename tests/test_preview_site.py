"""预览页生成器：渲染保真、零外链、可发布、越界拒绝。

覆盖 2026-09-18 接入 daily_engine 的 `article_group.preview_site`：
controller 要的是"标题能点、点开能读"的链接，而 run 里的 Markdown / 公众号 HTML
本身没有被任何服务托管——本模块负责把 run 产物渲染成自包含静态站点。
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import time
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest

from article_group.preview_site import LOCK_TTL_SECONDS as LOCK_TTL
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


# ── 交付链接清单（preview/links.json，2026-09-24） ──────────────────────
#
# 为什么需要：controller 在无桌面主机上只能靠 DSH 侧边栏看文章，而侧边栏链接的语法与
# 限制此前只写在 AGENTS.md / README 里、靠人记住（绝对路径、链接目标不能带 `?`、
# HTML 页内相对跳转点不动）。本清单把"该给哪些链接、各自的绝对路径与哈希"变成 run 内
# 产物，交付时直接读它，不再手写路径——手写就一定会漂。


def _frontend_parse_file_link(value: str):
    """镜像 DSH 前端 ``parseFileLink``（packages/client/ui-primitives）的链接语法。

    只镜像与本清单相关的判定：先在第一个 ``#`` 处切分；destination 含 ``?`` 即拒绝；
    再 ``decodeURIComponent``；拒绝控制字符、``//`` 开头与协议前缀；``#L<n>`` /
    ``#L<n>-L<m>`` 解析为行号。返回 ``(path, line)`` 或 ``None``。

    真实实现是前端 JS（``dsh-client-ui-primitives``）；本镜像用来钉住"我们发出的
    markdown 链接一定能被前端识别为文件链接、且目标能还原成同一个绝对路径"。
    """
    hash_index = value.find("#")
    destination = value if hash_index < 0 else value[:hash_index]
    # 真实实现：含 `?` 的 destination 一律不是文件链接（查询串不支持）
    if "?" in destination:
        return None
    try:
        path = unquote(destination)
    except ValueError:  # 不完整的百分号转义
        return None
    if not path or re.search(r"[\u0000-\u001f\u007f]", path) or re.match(r"^[\\/]{2}", path):
        return None
    if re.match(r"^[a-z][a-z\d+.-]*:", path, flags=re.I) and not re.match(r"^[a-z]:[\\/]", path, flags=re.I):
        return None
    if hash_index < 0:
        return path, None
    match = re.fullmatch(r"L([1-9]\d*)(?:-L([1-9]\d*))?", value[hash_index + 1:])
    if match is None:
        return None
    line = int(match.group(1))
    end = line if match.group(2) is None else int(match.group(2))
    if end < line:
        return None
    return path, line


def _link_target(entry: dict) -> str:
    """取出 ``markdown_link`` 里的链接目标（``](`` 与结尾 ``)`` 之间）。"""
    _, _, rest = entry["markdown_link"].partition("](")
    assert rest.endswith(")"), entry["markdown_link"]
    return rest[:-1]


def test_build_writes_links_manifest_with_absolute_paths_and_hashes(tmp_path):
    run = _make_run(tmp_path)
    report = build(run)

    manifest_file = run / "preview/links.json"
    assert manifest_file.is_file()
    assert report["links_path"] == "preview/links.json"
    assert report["links_sha256"] == hashlib.sha256(manifest_file.read_bytes()).hexdigest()

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "preview-links-v1"
    assert manifest["state"] == "complete"
    assert manifest["run_id"] == "2026-09-17-daily-999"
    assert manifest["run_root"] == str(run.resolve())
    assert manifest["content_status"] == "CONTENT_READY"
    assert manifest["publication_authorization"] == "not_authorized"
    # 预览 ≠ 发布授权：清单里也要显式带上，别让链接被当成发布凭据
    assert manifest["index"]["path"] == "preview/index.html"
    assert [a["article_id"] for a in manifest["articles"]] == ["art-001", "art-002"]

    for article in manifest["articles"]:
        aid = article["article_id"]
        for slot, relative in (("body_md", f"delivery/{aid}/delivery.md"),
                               ("reading", f"preview/{aid}.html")):
            entry = article[slot]
            assert entry["path"] == relative
            target = Path(entry["abs_path"])
            assert target.is_absolute(), entry
            assert target == (run / relative).resolve()
            assert target.is_file(), relative
            assert entry["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest(), relative

    # 同一份事实只有一处权威：清单里的哈希必须与本次 build 报告、发布记录口径一致
    by_id = {a["article_id"]: a["sha256"] for a in report["articles"]}
    for article in manifest["articles"]:
        assert article["body_md"]["sha256"] == by_id[article["article_id"]]
    assert manifest["index"]["sha256"] == report["index_sha256"]


def test_links_manifest_markdown_links_survive_the_frontend_parser(tmp_path):
    """发出的链接必须是前端认得的文件链接，且目标能还原成同一个绝对路径。"""
    run = _make_run(tmp_path)
    build(run)
    manifest = json.loads((run / "preview/links.json").read_text(encoding="utf-8"))

    entries = [manifest["index"]]
    for article in manifest["articles"]:
        entries.extend(article[slot] for slot in ("body_md", "reading")
                       if slot in article)

    for entry in entries:
        link = entry["markdown_link"]
        target = _link_target(entry)
        assert "?" not in target, f"链接目标带裸 '?' 会退化成普通链接：{link}"
        parsed = _frontend_parse_file_link(target)
        assert parsed is not None, f"前端解析不出文件链接：{link}"
        assert parsed[0] == entry["abs_path"], link
        assert Path(parsed[0]).is_file(), entry["abs_path"]


def test_links_manifest_escapes_labels_and_encodes_hostile_paths(tmp_path):
    """标题里的 [] 与路径里的空格 / `?` / `#` / 括号都不能破坏链接语法。"""
    run = tmp_path / "2026-09-17" / "daily-998 a?b#c(d)"
    (run / "delivery/art-001").mkdir(parents=True)
    (run / "delivery/art-001/delivery.md").write_text(
        f"# 甲[标题] (含括号)\n\n{BODY_2}\n", encoding="utf-8")
    (run / "batch.json").write_text(json.dumps({
        "articles": [{"article_id": "art-001", "title": "甲[标题] (含括号)"}],
    }, ensure_ascii=False), encoding="utf-8")
    build(run)

    manifest = json.loads((run / "preview/links.json").read_text(encoding="utf-8"))
    body = manifest["articles"][0]["body_md"]
    link = body["markdown_link"]
    assert " " not in _link_target(body), link
    assert _frontend_parse_file_link(_link_target(body))[0] == body["abs_path"]
    # 标签里的 [] 必须转义，否则 markdown 结构被撑破
    assert "\\[标题\\]" in link, link


def test_links_manifest_degrades_when_wechat_missing(tmp_path):
    run = _make_run(tmp_path, with_wechat=False)
    build(run)
    manifest = json.loads((run / "preview/links.json").read_text(encoding="utf-8"))
    for article in manifest["articles"]:
        assert "wechat_copy" not in article and "wechat_fragment" not in article
    # 有公众号版时要在清单里给出来（复制到后台用）
    run2 = _make_run(tmp_path / "with-wechat")
    build(run2)
    manifest2 = json.loads((run2 / "preview/links.json").read_text(encoding="utf-8"))
    assert manifest2["articles"][0]["wechat_fragment"]["path"] == "preview/wechat/art-001.wx.html"


def test_links_manifest_is_deterministic_and_ledgered(tmp_path):
    """清单要可幂等（无时间戳），且写入必须走留底通道（有账）。"""
    run = _make_run(tmp_path)
    build(run)
    first = (run / "preview/links.json").read_bytes()
    build(run)
    assert (run / "preview/links.json").read_bytes() == first
    changelog = (run / "evidence-changelog.jsonl").read_text(encoding="utf-8")
    assert "preview_site:links" in changelog


def test_publish_carries_links_manifest_and_hashes_stay_true(tmp_path):
    """发布副本要与 run 内逐字节一致，清单才能当交付依据。"""
    run = _make_run(tmp_path)
    build(run)
    static = tmp_path / "outbox"
    static.mkdir()

    record = publish(run, static, base_url="http://192.168.100.168:8899")
    published = static / "2026-09-17-daily-999"
    assert "links.json" in record["files"]
    assert (published / "links.json").read_bytes() == (run / "preview/links.json").read_bytes()

    manifest = json.loads((published / "links.json").read_text(encoding="utf-8"))
    for article in manifest["articles"]:
        for slot in ("body_md", "reading"):
            relative = article[slot]["path"]
            assert article[slot]["sha256"] == hashlib.sha256((run / relative).read_bytes()).hexdigest()
    assert record["index_sha256"] == manifest["index"]["sha256"]


def test_preview_step_surfaces_links_path(tmp_path, monkeypatch):
    """引擎要把 links_path 写进 run-manifest 的 preview_site 块，交付期才有单一入口可读。"""
    from scripts import daily_engine as engine

    run = _make_run(tmp_path)
    monkeypatch.delenv("RUOYU_PREVIEW_PUBLISH_ROOT", raising=False)
    # ROOT 是模块全局：正常路径由 bind_spec() 从 spec 绑定，测试里直接装上去
    monkeypatch.setattr(engine, "ROOT", str(run), raising=False)

    status = engine.preview_site_step()

    assert status["status"] == "ok"
    assert status["links_path"] == "preview/links.json"
    assert (run / status["links_path"]).is_file()
    assert status["index_path"] == "preview/index.html"          # 既有字段不变
    assert status["published"]["status"] == "not_published"


# ── 独立 L2 对抗复核后的收口（2026-09-24） ──────────────────────────────
#
# 复核（独立只读子代理）判 needs_changes：1 处 major（中止的 build 会留下"看起来
# 完整"的旧清单，哈希指向已被覆盖的字节）、5 处 minor。下面每条测试都对应一条发现，
# 先红后绿；发现编号沿用复核报告。


def test_aborted_build_never_leaves_a_complete_manifest(tmp_path):
    """MAJOR：build 中途失败时，上一轮的清单必须已经失效，不能继续"看起来完整"。

    中止的 build 会先覆盖 index.html / 阅读页，失败点之后的文件保持旧样；若旧清单
    留着，交付期读到的哈希与磁盘不符，而且是静默的（AGENTS.md 让人直接读清单）。
    """
    run = _make_run(tmp_path)
    build(run)
    assert json.loads((run / "preview/links.json").read_text(encoding="utf-8"))["state"] == "complete"

    (run / "delivery/art-002/delivery.md").write_text(f"# 乙标题\n\n改了正文。\n", encoding="utf-8")
    victim = run / "preview/art-002.html"
    victim.unlink()
    victim.mkdir()                      # 让第 3 步写到一半失败

    with pytest.raises(OSError):
        build(run)

    manifest = json.loads((run / "preview/links.json").read_text(encoding="utf-8"))
    assert manifest["state"] != "complete", "中止的 build 留下了'完整'清单，交付会静默拿到假哈希"


def test_links_manifest_has_no_timestamp_and_pins_the_page_time_coupling(tmp_path, monkeypatch):
    """MINOR：清单自身无时间戳；但 index.sha256 是生成页面的哈希，页面内嵌分钟级时间。

    这是**已知耦合**：跨分钟重建时 index.sha256（进而 links_sha256）会变。把它钉住，
    免得再被当成"逐字节可复现"来用。
    """
    import article_group.preview_site as ps

    class _Stamp:
        def __init__(self, text): self.text = text
        def strftime(self, _fmt): return self.text

    class _Clock:
        def __init__(self, text): self._stamp = _Stamp(text)
        def now(self): return self
        def astimezone(self): return self._stamp

    run = _make_run(tmp_path)
    build(run)
    manifest = json.loads((run / "preview/links.json").read_text(encoding="utf-8"))
    assert "generated_at" not in manifest and "generated" not in manifest

    monkeypatch.setattr(ps, "datetime", _Clock("2026-09-24 10:00 CST"))
    build(run)
    first = json.loads((run / "preview/links.json").read_text(encoding="utf-8"))["index"]["sha256"]
    monkeypatch.setattr(ps, "datetime", _Clock("2026-09-24 11:00 CST"))
    build(run)
    second = json.loads((run / "preview/links.json").read_text(encoding="utf-8"))["index"]["sha256"]

    assert first != second, "页面生成时间变了，index.sha256 却不变——耦合假设已被推翻，请更新文档"
    assert any("index" in n for n in json.loads(
        (run / "preview/links.json").read_text(encoding="utf-8"))["notes"]), \
        "notes 应当写明 index.sha256 跟随页面内嵌生成时间"


def test_links_manifest_degrades_on_control_char_path(tmp_path):
    """MINOR：路径含控制字符时前端会拒绝该链接 → 给 null + 原因，不假装能点。"""
    run = tmp_path / "2026-09-24" / "daily-997\ttab"
    (run / "delivery/art-001").mkdir(parents=True)
    (run / "delivery/art-001/delivery.md").write_text(f"# 甲标题\n\n{BODY_2}\n", encoding="utf-8")
    (run / "batch.json").write_text(json.dumps({
        "articles": [{"article_id": "art-001", "title": "甲标题"}],
    }, ensure_ascii=False), encoding="utf-8")

    build(run)                              # 不能抛

    entry = json.loads((run / "preview/links.json").read_text(encoding="utf-8"))["articles"][0]["body_md"]
    assert entry["markdown_link"] is None
    assert entry["link_unavailable_reason"] == "path_contains_control_char"
    assert len(entry["sha256"]) == 64       # 哈希照给：路径给的出来，只是点不动


def test_links_manifest_degrades_on_non_utf8_path(tmp_path):
    """MINOR：路径里有非 UTF-8 字节时，build() 不能整个失败——降级 + 如实标注有损。"""
    parent = tmp_path / "2026-09-24"
    parent.mkdir()
    raw = os.fsencode(str(parent)) + b"/daily-\xffbad"
    os.mkdir(raw)
    run = Path(os.fsdecode(raw))            # 含 surrogateescape 字节
    (run / "delivery/art-001").mkdir(parents=True)
    (run / "delivery/art-001/delivery.md").write_text(f"# 甲标题\n\n{BODY_2}\n", encoding="utf-8")
    (run / "batch.json").write_text(json.dumps({
        "articles": [{"article_id": "art-001", "title": "甲标题"}],
    }, ensure_ascii=False), encoding="utf-8")

    build(run)                              # 不能抛 UnicodeEncodeError

    manifest = json.loads((run / "preview/links.json").read_text(encoding="utf-8"))
    entry = manifest["articles"][0]["body_md"]
    assert entry["markdown_link"] is None
    assert entry["link_unavailable_reason"] == "path_not_encodable"
    assert entry["abs_path_lossy"] is True


def test_links_manifest_does_not_advertise_stale_wechat_copies(tmp_path):
    """MINOR：run 里的 wechat 源没了以后，不能继续把陈旧副本当"公众号版"给出去。"""
    run = _make_run(tmp_path)
    build(run)
    assert "wechat_copy" in json.loads((run / "preview/links.json").read_text(encoding="utf-8"))["articles"][0]

    shutil.rmtree(run / "wechat")
    build(run)

    article = json.loads((run / "preview/links.json").read_text(encoding="utf-8"))["articles"][0]
    assert "wechat_copy" not in article and "wechat_fragment" not in article
    manifest = json.loads((run / "preview/links.json").read_text(encoding="utf-8"))
    assert "preview/wechat/art-001.html" in manifest["stale_preview_files"]


def test_subset_rebuild_declares_leftover_reading_pages(tmp_path):
    """子集重建后，磁盘上多出来的阅读页要出现在 stale_preview_files，不静默留着。"""
    run = _make_run(tmp_path)
    build(run)
    build(run, articles=["art-001"])

    manifest = json.loads((run / "preview/links.json").read_text(encoding="utf-8"))
    assert [a["article_id"] for a in manifest["articles"]] == ["art-001"]
    assert "preview/art-002.html" in manifest["stale_preview_files"]


@pytest.mark.parametrize(
    "marker",
    ['{"sealed_at": "2026-09-24T00:00:00+08:00", "sealed_by": "test"}\n', ""],
    ids=["json-marker", "empty-marker"],
)
def test_publish_on_sealed_run_records_refusal_without_raising(tmp_path, marker):
    """MINOR（既有缺陷，落在新产物的发布路径上）：封存 run 上发布要如实记账，不能抛。

    copytree 已经把站点（含 links.json）拷进静态根了；随后写 run 内 publish-record
    会撞上封存守门。**两道关的触发条件不同**：`evidence_write` 的 `sealed_reason`
    要能解析 SEALED 才判"已封存"，而 `runs_guard` 的审计钩子只看文件在不在——
    所以 `touch SEALED`（空标记）绕过前者、由后者抛出 SealedWriteBlocked。
    旧代码只捕 RunSealedError：空标记下异常逃出去，CLI 报失败且无 run 侧记录。
    """
    from article_group import runs_guard

    run = _make_run(tmp_path)
    build(run)
    static = tmp_path / "outbox"
    static.mkdir()
    (run / "SEALED").write_text(marker, encoding="utf-8")
    runs_guard.refresh()

    record = publish(run, static, base_url="http://192.168.100.168:8899")

    assert record["record_error"] == "run_sealed_publish_record_not_written"
    assert (static / "2026-09-17-daily-999/links.json").is_file()       # 站点确实发布了
    assert not (run / "preview/publish-record.json").exists()           # 但没有 run 侧记账


# ── 第二轮独立复核后的收口（2026-09-24） ────────────────────────────────
#
# 复核（同一个独立只读子代理，第二轮）判 needs_changes：1 处 major（失效 stub 写在第一
# 个可能失败的阶段之后）+ 4 处 minor。编号沿用报告：(a) 前置失败阶段、(a-2) 并发、
# (b) 半成品可发布、(c) 有损路径无标记、(d) 页面仍链向陈旧副本。


def test_stub_invalidates_manifest_before_the_first_fallible_step(tmp_path):
    """MAJOR（a）：`read_article` 之前就会失败，旧清单不能原样留在 complete。

    复核在冻结版上用五种方式复现过（删成稿 / 非 UTF-8 / chmod 000 / 成稿变目录 /
    batch.json 畸形）。这里取两种最有代表性的：
    """
    run = _make_run(tmp_path)
    build(run)
    assert json.loads((run / "preview/links.json").read_text(encoding="utf-8"))["state"] == "complete"

    # 1) 成稿被删：read_article 抛 FileNotFoundError
    (run / "delivery/art-002/delivery.md").unlink()
    with pytest.raises(FileNotFoundError):
        build(run)
    manifest = json.loads((run / "preview/links.json").read_text(encoding="utf-8"))
    assert manifest["state"] != "complete", "read_article 阶段失败后，旧清单仍是 complete"

    # 2) batch.json 变成列表：取 articles 时 AttributeError
    run2 = _make_run(tmp_path / "malformed")
    build(run2)
    (run2 / "batch.json").write_text("[1,2,3]", encoding="utf-8")
    with pytest.raises(AttributeError):
        build(run2)
    assert json.loads((run2 / "preview/links.json").read_text(encoding="utf-8"))["state"] != "complete"


def test_concurrent_build_is_refused_instead_of_interleaving(tmp_path):
    """MINOR（a-2）：并发 build 必须被拦住——单个 state 槽挡不住"B 完成后 A 才写页面"。"""
    run = _make_run(tmp_path)
    build(run)
    lock = run / ".preview-links.lock"
    lock.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")   # 持有者活着

    with pytest.raises(RuntimeError, match="并发|进行中"):
        build(run)


def test_lock_from_a_dead_process_is_taken_over(tmp_path):
    """MINOR（a-2）：硬崩留下的僵锁要能接管，不能把 run 永久锁死。"""
    run = _make_run(tmp_path)
    build(run)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (run / "preview/.links.lock").write_text(json.dumps({"pid": dead.pid}), encoding="utf-8")

    build(run)                                   # 应接管而不是报错
    assert json.loads((run / "preview/links.json").read_text(encoding="utf-8"))["state"] == "complete"
    assert not (run / ".preview-links.lock").exists(), "构建结束应释放锁"


def test_publish_refuses_a_building_manifest(tmp_path):
    """MINOR（b）：state=building 的半成品站点不许发布到静态根。"""
    run = _make_run(tmp_path)
    build(run)
    (run / "delivery/art-002/delivery.md").unlink()
    with pytest.raises(FileNotFoundError):
        build(run)                               # 清单降级为 building
    assert json.loads((run / "preview/links.json").read_text(encoding="utf-8"))["state"] == "building"

    static = tmp_path / "outbox"
    static.mkdir()
    with pytest.raises(ValueError, match="state"):
        publish(run, static, base_url="http://192.168.100.168:8899")
    assert not (static / "2026-09-17-daily-999").exists(), "半成品站点不该出现在静态根"


def test_publish_still_accepts_a_run_without_links_json(tmp_path):
    """兼容性：早于本产物的 run 没有 links.json，发布不能因此被拒。"""
    run = _make_run(tmp_path)
    build(run)
    (run / "preview/links.json").unlink()
    static = tmp_path / "outbox"
    static.mkdir()

    record = publish(run, static, base_url="http://192.168.100.168:8899")

    assert record["index_url"] == "http://192.168.100.168:8899/2026-09-17-daily-999/"
    assert "path_repr_lossy" not in record


# ── 2026-09-25 独立审计：publish 的两个活口子 ──────────────────────────────


def test_a_first_build_that_died_after_writing_pages_cannot_be_published(tmp_path):
    """首轮 build 死在写 links.json 之前，publish 不能因为"没有清单"就放行。

    写入顺序是 index.html →（阅读页）→ links.json，所以首轮死在最后一步时磁盘上是
    「有 index.html、没有 links.json」。而 `_invalidate_links_manifest` 对不存在的
    清单直接早退，publish 又把"没有清单"一律当早于本产物的旧 run 兼容——于是静态根
    上会出现一个链向不存在阅读页的半成品站点。这里要求构建一开始就留下 building 桩，
    使任何"写了第一页之后"的失败都必然带着一个可判定的非 complete 清单。
    """
    run = _make_run(tmp_path)
    (run / "preview").mkdir(exist_ok=True)
    (run / "preview" / "art-002.html").mkdir()          # 让第 3 步写阅读页时失败

    with pytest.raises(OSError):
        build(run)

    assert (run / "preview/index.html").is_file(), "前提不成立：失败点应在 index.html 之后"
    static = tmp_path / "outbox"
    static.mkdir()
    with pytest.raises(ValueError):
        publish(run, static, base_url="http://192.168.100.168:8899")
    assert not (static / "2026-09-17-daily-999").exists(), "半成品站点被发布到了静态根"


def test_publish_refuses_a_links_manifest_with_an_unknown_schema(tmp_path):
    """清单版本不认识时拒绝发布：版本是契约的一部分，不能"读得动就发"。"""
    run = _make_run(tmp_path)
    build(run)
    payload = json.loads((run / "preview/links.json").read_text(encoding="utf-8"))
    payload["schema_version"] = "preview-links-v9"
    (run / "preview/links.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    static = tmp_path / "outbox"
    static.mkdir()
    with pytest.raises(ValueError, match="schema"):
        publish(run, static, base_url="http://192.168.100.168:8899")
    assert not (static / "2026-09-17-daily-999").exists()


def test_publish_does_not_ship_its_own_publish_record(tmp_path):
    """发布内容里不能带上自己的发布记录：那是 run 内的账，不是交付物。

    第二次发布时 `preview/` 里已经有上一次写的 `publish-record.json`（含绝对宿主路径
    与文件清单），整目录 copytree 会把它一起推到静态根（8899 是内网可访问的）。
    """
    run = _make_run(tmp_path)
    build(run)
    static = tmp_path / "outbox"
    static.mkdir()
    publish(run, static, base_url="http://192.168.100.168:8899")
    assert (run / "preview/publish-record.json").is_file(), "前提：第一次发布写了 run 内记录"

    publish(run, static, base_url="http://192.168.100.168:8899")

    shipped = sorted(p.name for p in (static / "2026-09-17-daily-999").rglob("*") if p.is_file())
    assert "publish-record.json" not in shipped, f"发布内容里带着自己的发布记录：{shipped}"


def test_publish_record_and_links_flag_lossy_paths_for_non_utf8_run(tmp_path):
    """MINOR（c）：非 UTF-8 路径要有损时**标注**，且"返回的记录"与"落盘记录"必须一致。"""
    parent = tmp_path / "2026-09-24"
    parent.mkdir()
    os.mkdir(os.fsencode(str(parent)) + b"/daily-\xffbad")
    run = Path(os.fsdecode(os.fsencode(str(parent)) + b"/daily-\xffbad"))
    (run / "delivery/art-001").mkdir(parents=True)
    (run / "delivery/art-001/delivery.md").write_text(f"# 甲标题\n\n{BODY_2}\n", encoding="utf-8")
    (run / "batch.json").write_text(json.dumps({
        "articles": [{"article_id": "art-001", "title": "甲标题"}],
    }, ensure_ascii=False), encoding="utf-8")
    build(run)
    static = tmp_path / "outbox"
    static.mkdir()

    record = publish(run, static, base_url="http://192.168.100.168:8899")
    persisted = json.loads((run / "preview/publish-record.json").read_text(encoding="utf-8"))

    assert record["path_repr_lossy"] is True
    assert persisted["path_repr_lossy"] is True
    # 返回值和落盘值必须一致（复核 finding c：两者不一致时"以记录为准"就成了陷阱）
    assert persisted["target"] == record["target"]
    assert persisted["index_url"] == record["index_url"]
    # links.json 的 run_id 也是同一个有损路径，必须一并标注
    manifest = json.loads((run / "preview/links.json").read_text(encoding="utf-8"))
    assert manifest["run_id_lossy"] is True


def test_regenerated_pages_do_not_offer_stale_wechat_copies(tmp_path):
    """MINOR（d）：清单不广告还不够——重生成的页面里也不能留着指向陈旧副本的锚点。"""
    run = _make_run(tmp_path)
    build(run)
    assert 'href="wechat/art-001.html"' in (run / "preview/index.html").read_text(encoding="utf-8")

    shutil.rmtree(run / "wechat")
    build(run)

    index = (run / "preview/index.html").read_text(encoding="utf-8")
    page = (run / "preview/art-001.html").read_text(encoding="utf-8")
    assert 'href="wechat/art-001.html"' not in index, "目录页仍链向陈旧公众号副本"
    assert 'href="wechat/art-001.wx.html"' not in index
    assert 'href="wechat/art-001.html"' not in page, "阅读页仍链向陈旧公众号副本"
    assert 'href="art-001.html"' in index, "阅读页链接本身必须还在"


# ── 第三轮独立复核后的收口（2026-09-24） ────────────────────────────────
#
# 三轮复核判 needs_changes：6 处 minor（无 major），第二轮 5 项确认已修复。
# 编号沿用报告 1-6。


def test_publish_refuses_a_corrupt_manifest(tmp_path):
    """finding 1：坏清单不能当成"没有清单"放行。

    截断的 JSON 正是 SIGKILL / ENOSPC 写一半留下形态——而它恰好绕过这道门。
    """
    run = _make_run(tmp_path)
    build(run)
    static = tmp_path / "outbox"
    static.mkdir()

    (run / "preview/links.json").write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON|解析"):
        publish(run, static, base_url="http://192.168.100.168:8899")

    (run / "preview/links.json").write_text("[1,2,3]", encoding="utf-8")
    with pytest.raises(ValueError, match="对象"):
        publish(run, static, base_url="http://192.168.100.168:8899")

    assert not (static / "2026-09-17-daily-999").exists(), "坏清单的站点不该被发布"


def test_lock_is_not_stolen_while_the_holder_is_alive(tmp_path):
    """finding 2：锁刚创建、pid 还没落盘的窗口里，不能被第二个构建抢走。

    持有者活着时那条锁读不懂 → 必须判定"占用中"（fail-closed），而不是接管。
    """
    run = _make_run(tmp_path)
    build(run)
    lock = run / ".preview-links.lock"
    lock.write_text("", encoding="utf-8")          # 空：创建→写 pid 之间的形态

    with pytest.raises(RuntimeError, match="并发|进行中"):
        build(run)


def test_refused_build_does_not_downgrade_a_complete_manifest(tmp_path):
    """finding 3：加锁失败不能把一份好的 complete 清单打成 building。"""
    run = _make_run(tmp_path)
    build(run)
    assert json.loads((run / "preview/links.json").read_text(encoding="utf-8"))["state"] == "complete"

    (run / ".preview-links.lock").write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="并发|进行中"):
        build(run)

    manifest = json.loads((run / "preview/links.json").read_text(encoding="utf-8"))
    assert manifest["state"] == "complete", "被拒绝的构建不该动上一轮的清单"


def test_stale_lock_from_a_reused_pid_is_taken_over(tmp_path):
    """finding 3：锁很旧（超过 TTL）时即使 pid 还活着也要能接管，否则 run 被永久锁死。

    现实路径：构建被 SIGKILL / 断电留下锁，重启后那个 pid 属于无关的常驻进程。
    """
    run = _make_run(tmp_path)
    build(run)
    lock = run / ".preview-links.lock"
    lock.write_text(json.dumps({"pid": 1}), encoding="utf-8")   # pid 1 一般活着但无关
    old = time.time() - 3600
    os.utime(lock, (old, old))

    build(run)
    assert json.loads((run / "preview/links.json").read_text(encoding="utf-8"))["state"] == "complete"


def test_lock_release_tolerates_a_sealed_run(tmp_path):
    """finding 4：构建中途 run 被封存时，unlink 会被护栏抛 SealedWriteBlocked——
    那是一次**已成功**的构建，不能因为释放锁而报错。"""
    from article_group import preview_site as ps
    from article_group import runs_guard

    run = _make_run(tmp_path)
    # 锁要在封存**之前**建好：封存后连测试自己都写不进去（护栏按设计拦下）
    lock = run / ps.LOCK_PATH
    lock.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    handle = os.open(lock, os.O_RDONLY)
    (run / "SEALED").write_text('{"sealed_at": "2026-09-24T00:00:00+08:00", "sealed_by": "test"}\n', encoding="utf-8")
    runs_guard.refresh()

    ps._release_lock(lock, handle)      # 不该抛 SealedWriteBlocked


def test_lossy_index_url_is_withheld_instead_of_emitted(tmp_path):
    """finding 4（四轮）：字节正确的 `%FF` URL 在部署端仍是 404。

    `python -m http.server`（8899 就是这个栈）的 `SimpleHTTPRequestHandler.unquote()`
    把 `%FF` 解成 U+FFFD，于是路径对不上 → 404。既然这个 URL 没人能打开，就不要给：
    `index_url` 给 `None`，并保留 `path_repr_lossy` 说明原因。
    """
    parent = tmp_path / "2026-09-24"
    parent.mkdir()
    raw = os.fsencode(str(parent)) + b"/g-daily-\xffbad"
    os.mkdir(raw)
    run = Path(os.fsdecode(raw))
    (run / "delivery/art-001").mkdir(parents=True)
    (run / "delivery/art-001/delivery.md").write_text(f"# 甲标题\n\n{BODY_2}\n", encoding="utf-8")
    (run / "batch.json").write_text(json.dumps({
        "articles": [{"article_id": "art-001", "title": "甲标题"}],
    }, ensure_ascii=False), encoding="utf-8")
    build(run)
    static = tmp_path / "outbox"
    static.mkdir()

    record = publish(run, static, base_url="http://192.168.100.168:8899")

    assert record["index_url"] is None, "不可服务的 URL 不该发出去"
    assert record["path_repr_lossy"] is True
    assert (static / next(p.name for p in static.iterdir() if p.is_dir()) / "index.html").is_file()


def test_failed_first_build_leaves_no_preview_dir(tmp_path):
    """finding 6：首次构建失败不该留下空的 preview/——那会毁掉"无 preview/ ⇒ 本阶段没跑"的信号。"""
    run = _make_run(tmp_path)
    (run / "batch.json").write_text("[1,2,3]", encoding="utf-8")

    with pytest.raises(AttributeError):
        build(run)

    assert not (run / "preview").exists(), "失败的首轮构建留下了空的 preview/ 目录"


def test_leftover_lock_absence_is_authorized_without_hiding_it(tmp_path):
    """第四轮 finding 1 的正确收口（第五轮 major 1 修正了粒度）。

    第四轮我把它整条排除，结果造成"隐形写入通道"；正确契约是：
    **不进排除名单**（存在即入册、内容受钉），但**缺失属授权**（瞬时件被正常删除）。
    """
    from article_group import run_seal

    run = _make_run(tmp_path)
    build(run)
    (run / ".preview-links.lock").write_text(json.dumps({"pid": 999999}), encoding="utf-8")

    assert ".preview-links.lock" not in run_seal.EXCLUDED_REASONS, "不能整条排除（会形成隐形写入通道）"
    assert ".preview-links.lock" in run_seal.MAY_BE_ABSENT, "缺失要按授权瞬时件处理"
    entries = {relative for relative, _, _ in run_seal._scan_entries(run)[0]}
    assert ".preview-links.lock" in entries, "存在时必须进清单，否则封存后改写无人能发现"


def test_takeover_unlink_failure_is_refused_not_silently_unlocked(tmp_path):
    """finding 2（四轮）：接管失败（例如锁路径是目录且已超龄）绝不能悄悄降级成"不加锁"。"""
    run = _make_run(tmp_path)
    build(run)
    lock = run / ".preview-links.lock"             # build() 成功后会释放锁，这里直接占位即可
    lock.mkdir()                                   # 锁路径变成目录
    old = time.time() - (LOCK_TTL + 60)
    os.utime(lock, (old, old))

    with pytest.raises((RuntimeError, OSError)):
        build(run)


def test_lock_with_a_future_mtime_is_taken_over(tmp_path):
    """finding 3（四轮）：mtime 在未来（时钟回拨 / 拷贝带 -t）时 TTL 永远不触发 → 接管。"""
    run = _make_run(tmp_path)
    build(run)
    lock = run / ".preview-links.lock"
    lock.write_text("", encoding="utf-8")           # 读不懂
    future = time.time() + 10 * 365 * 24 * 3600
    os.utime(lock, (future, future))

    build(run)                                      # 不能永久锁死
    assert json.loads((run / "preview/links.json").read_text(encoding="utf-8"))["state"] == "complete"


# ── 2026-09-25 独立审计 P2：释放锁必须校验归属 ────────────────────────────


def test_release_lock_removes_only_its_own_lock(tmp_path):
    """正向：锁是自己的（pid 一致）就正常删掉，不许因为加归属校验而漏删。"""
    from article_group import preview_site as ps

    lock = tmp_path / ".preview-links.lock"
    lock.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    fd = os.open(lock, os.O_RDONLY)
    ps._release_lock(lock, fd)
    assert not lock.exists(), "自己的锁没被释放"


def test_release_lock_does_not_delete_a_preemptors_lock(tmp_path):
    """负向：A 被 B 合法接管（TTL 到期）后，A 结束时不能删掉 **B** 的锁。

    否则第三个构建就能立刻拿到锁，与 B 并行写同一个 run——正是锁要防的
    「清单说 complete、页面却是别人的字节」。
    """
    from article_group import preview_site as ps

    lock = tmp_path / ".preview-links.lock"
    lock.write_text(json.dumps({"pid": os.getpid() + 1}), encoding="utf-8")
    fd = os.open(lock, os.O_RDONLY)
    ps._release_lock(lock, fd)
    assert lock.exists(), "释放锁时删掉了不属于自己的锁——接管者的互斥被破坏"


def test_release_lock_leaves_an_unreadable_lock_alone(tmp_path):
    """读不懂归属时 fail-closed：不删（陈旧锁另有 TTL 接管路径，不靠这里清）。"""
    from article_group import preview_site as ps

    lock = tmp_path / ".preview-links.lock"
    lock.write_text("", encoding="utf-8")
    fd = os.open(lock, os.O_RDONLY)
    ps._release_lock(lock, fd)
    assert lock.exists(), "归属不明时删了锁"


def test_corrupt_manifest_message_offers_the_no_rebuild_remedy(tmp_path):
    """finding 6（四轮，low）：坏清单的报错也要给出"删掉清单 + --no-build"这条出路。"""
    run = _make_run(tmp_path)
    build(run)
    static = tmp_path / "outbox"
    static.mkdir()
    (run / "preview/links.json").write_text("{ broken", encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        publish(run, static, base_url="http://192.168.100.168:8899")
    assert "--no-build" in str(exc.value), "坏清单的报错漏了「删清单再 --no-build」这条出路"


# ── 第五轮独立复核后的收口（2026-09-24） ────────────────────────────────
# 五轮复核判 needs_changes：2 major + 2 minor，两个 major 都是第四轮修复**引入**的回归。


def test_lock_path_is_inventoried_so_tampering_is_caught(tmp_path):
    """MAJOR 1：锁不能是被排除的路径——那样往它写东西 verify 也永远看不见。

    正确粒度：**存在即入册**（内容/大小/符号链接照查），**缺失属授权**（瞬时件被正常删除）。
    """
    from article_group import run_seal

    run = _make_run(tmp_path)
    build(run)
    lock = run / ".preview-links.lock"
    lock.write_bytes(b"planted-before-seal" * 200)

    assert not run_seal._is_excluded(".preview-links.lock"), "锁被排除 → 形成隐形写入通道"
    entries = {relative for relative, _, _ in run_seal._scan_entries(run)[0]}
    assert ".preview-links.lock" in entries, "存在时必须进清单（否则封存后改写无人能发现）"
    assert ".preview-links.lock" in run_seal.MAY_BE_ABSENT, "缺失要按授权处理"


def test_verify_treats_the_lock_as_sealed_when_present_and_authorized_when_absent(tmp_path):
    """MAJOR 1（verify 行为）：在场受钉、缺失授权——篡改必须能被抓到。

    篡改走子进程（不 import article_group），正是护栏文档里承认覆盖不到的
    "进程外写手"那一类，也正是封存清单存在的意义。
    """
    from article_group import run_seal
    from article_group.run_state import seal

    run = _make_run(tmp_path)
    build(run)
    lock = run / ".preview-links.lock"
    subprocess.run([sys.executable, "-c", f"open({str(lock)!r},'wb').write(b'planted'*600)"], check=True)
    run_seal.write_manifest(run, run_seal.build_manifest(run, sealed_at="2026-09-24T00:00:00+08:00", sealed_by="test"))
    seal(run, identity="test")

    assert run_seal.verify(run)["status"] == "intact"

    subprocess.run([sys.executable, "-c", f"open({str(lock)!r},'wb').write(b'TAMPERED')"], check=True)
    assert any(c["path"] == ".preview-links.lock" for c in run_seal.verify(run)["changes"]), \
        "封存后改写该路径没被发现（隐形写入通道）"

    subprocess.run([sys.executable, "-c", f"open({str(lock)!r},'wb').write(b'planted'*600)"], check=True)
    subprocess.run([sys.executable, "-c", f"import os; os.unlink({str(lock)!r})"], check=True)
    assert all(c["path"] != ".preview-links.lock" for c in run_seal.verify(run)["changes"]), \
        "瞬时锁被正常删除却报成未授权漂移"


def test_live_holder_with_a_future_mtime_is_not_preempted(tmp_path):
    """MAJOR 2：pid 必须**先于** mtime 判定——活持有者不能被时钟偏斜抢锁。"""
    run = _make_run(tmp_path)
    build(run)
    lock = run / ".preview-links.lock"
    lock.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")   # 活持有者
    future = time.time() + LOCK_TTL           # mtime 在未来
    os.utime(lock, (future, future))

    with pytest.raises(RuntimeError, match="并发|进行中"):
        build(run)

    # 读不懂的锁 + 未来 mtime 仍要能接管（第四轮那条不得回退）
    lock.write_text("", encoding="utf-8")
    os.utime(lock, (future, future))
    build(run)
    assert json.loads((run / "preview/links.json").read_text(encoding="utf-8"))["state"] == "complete"


def test_uncreatable_lock_refuses_instead_of_running_unlocked(tmp_path):
    """MINOR 3：建锁失败（只读 run 根）必须拒绝，不能悄悄无锁继续。"""
    run = _make_run(tmp_path)
    build(run)
    os.chmod(run, 0o555)
    try:
        with pytest.raises(RuntimeError, match="无法建立构建锁|无锁"):
            build(run)
    finally:
        os.chmod(run, 0o755)


def test_publish_cli_survives_a_lossy_run(tmp_path):
    """MINOR 4：非 UTF-8 run 发布成功后，CLI 不能因为打印 run 名而崩。"""
    parent = tmp_path / "2026-09-24"
    parent.mkdir()
    raw = os.fsencode(str(parent)) + b"/c-daily-\xffbad"
    os.mkdir(raw)
    run = Path(os.fsdecode(raw))
    (run / "delivery/art-001").mkdir(parents=True)
    (run / "delivery/art-001/delivery.md").write_text(f"# 甲标题\n\n{BODY_2}\n", encoding="utf-8")
    (run / "batch.json").write_text(json.dumps({
        "articles": [{"article_id": "art-001", "title": "甲标题"}],
    }, ensure_ascii=False), encoding="utf-8")
    build(run)
    static = tmp_path / "outbox"
    static.mkdir()

    proc = subprocess.run(
        [sys.executable, "scripts/publish_preview.py", "--run-dir", str(run),
         "--root", str(static), "--base-url", "http://192.168.100.168:8899", "--no-build"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert proc.returncode == 0, f"CLI 崩了：{proc.stderr[-300:]}"


def test_malformed_lock_pid_does_not_crash_the_build(tmp_path):
    """第六轮 minor：畸形 pid（溢出值）按"已死"处理并接管，不能抛无信息崩溃。"""
    run = _make_run(tmp_path)
    build(run)
    (run / ".preview-links.lock").write_text(json.dumps({"pid": 10 ** 20}), encoding="utf-8")

    build(run)                                     # 不该抛 OverflowError
    assert json.loads((run / "preview/links.json").read_text(encoding="utf-8"))["state"] == "complete"


# ── 第六轮 major 的专项收口：封存清单对条目类型失明 + 静默跳过扫不动的子树 ──

def _seal_run(run: Path) -> dict:
    """按生产顺序封存：清单 → SEALED 标记。"""
    from article_group import run_seal
    from article_group.run_state import seal

    run_seal.write_manifest(
        run, run_seal.build_manifest(run, sealed_at="2026-09-24T00:00:00+08:00", sealed_by="test"))
    seal(run, identity="test")
    return json.loads((run / "SEALED.manifest.json").read_text(encoding="utf-8"))


def _sh(cmd: str) -> None:
    """在**不 import article_group** 的子进程里操作：这正是护栏承认覆盖不到的进程外写手。"""
    subprocess.run([sys.executable, "-c", cmd], check=True)


def test_seal_inventory_records_non_file_shapes(tmp_path):
    """非文件形状必须入册：目录 / FIFO / socket 都要有自己的类型记录。"""
    from article_group import run_seal

    run = _make_run(tmp_path)
    build(run)
    (run / "evidence-dir").mkdir()
    (run / "evidence-dir/inner.md").write_text("x", encoding="utf-8")
    os.mkfifo(run / "fifo-pipe")

    payload = run_seal.build_manifest(run, sealed_at="2026-09-24T00:00:00+08:00", sealed_by="test")

    assert payload["inventory"] == run_seal.INVENTORY_ALL_ENTRIES
    assert "evidence-dir" in {item["path"] for item in payload["dirs"]}
    assert "evidence-dir/inner.md" in {item["path"] for item in payload["files"]}
    others = {item["path"]: item for item in payload["others"]}
    assert others["fifo-pipe"]["stat_kind"] == "fifo"
    assert payload["scan_errors"] == []


def test_post_seal_empty_directory_is_detected(tmp_path):
    """封存后凭空多出一个**空目录**，也必须被发现（此前完全隐形）。"""
    from article_group import run_seal

    run = _make_run(tmp_path)
    build(run)
    _seal_run(run)
    assert run_seal.verify(run)["status"] == "intact"

    _sh(f"import os; os.mkdir({str(run / 'planted-dir')!r})")
    changes = run_seal.verify(run)["changes"]
    assert any(c["path"] == "planted-dir" and c["kind"] == "added" for c in changes), \
        f"封存后新增的空目录没被发现：{changes}"


def test_pinned_lock_replaced_by_empty_directory_is_detected(tmp_path):
    """复合盲点：被清单钉住的锁被换成空目录，不能报 intact。"""
    from article_group import run_seal

    run = _make_run(tmp_path)
    build(run)
    lock = run / ".preview-links.lock"
    lock.write_bytes(b"pinned-lock")
    _seal_run(run)

    _sh(f"import os; os.unlink({str(lock)!r}); os.mkdir({str(lock)!r})")
    changes = run_seal.verify(run)["changes"]
    assert any(c["path"] == ".preview-links.lock" for c in changes), \
        f"被钉住的锁换成目录后仍报 {run_seal.verify(run)['status']}：{changes}"


def test_unscannable_subtree_is_loud_not_intact(tmp_path):
    """扫不动的子树：封存要拒绝，校验要报 unverifiable——不许给假 PASS。"""
    from article_group import run_seal

    run = _make_run(tmp_path)
    build(run)
    hidden = run / "hidden"
    hidden.mkdir()
    (hidden / "payload.txt").write_text("predates the seal", encoding="utf-8")
    os.chmod(hidden, 0o000)
    try:
        payload = run_seal.build_manifest(run, sealed_at="2026-09-24T00:00:00+08:00", sealed_by="test")
        assert payload["scan_errors"], "扫不动的子树没有被记下来"
        with pytest.raises(ValueError, match="不完整|扫不动"):
            run_seal.write_manifest(run, payload)
    finally:
        os.chmod(hidden, 0o755)


def test_sealing_rewrites_the_manifest_so_a_hand_degraded_v1_does_not_survive(tmp_path):
    """为什么不能在这里测 v1 兼容：`seal()` 会**无条件重建**清单（run_state.py）。

    2026-09-25 独立审计发现：本函数位置此前那条 `test_v1_manifest_still_verifies_with_
    the_legacy_inventory` 是**空转的**——它先写一份 v1 清单、再调 `seal()`，而 seal()
    用 v2 覆盖了它，于是 `verify()` 校验的其实是 v2 清单。整套测试里 v1 那条生产路径
    （现存 daily-008/009/010 全走它）因此零覆盖。

    真正的 v1 覆盖在 `tests/test_run_seal.py`（`_v1_sealed_run` 造真 v1 run：
    手写清单 + 手写 SEALED，不经过 seal()）。这里把"为什么不能这么造"钉住，
    免得下一个人再写出一条假测试。
    """
    from article_group import run_seal

    from article_group.run_state import seal

    run = _make_run(tmp_path)
    build(run)
    payload = run_seal.build_manifest(run, sealed_at="2026-09-24T00:00:00+08:00", sealed_by="test")
    payload["schema_version"] = run_seal.SCHEMA_VERSION_V1
    payload.pop("inventory", None)
    run_seal.write_manifest(run, payload)
    assert run_seal.load_manifest(run)["schema_version"] == run_seal.SCHEMA_VERSION_V1

    seal(run, identity="test")

    on_disk = run_seal.load_manifest(run)
    assert on_disk["schema_version"] == run_seal.SCHEMA_VERSION, \
        "seal() 重建了清单：想测 v1 就必须绕过它（见 tests/test_run_seal.py::_v1_sealed_run）"


# ── 第七轮收口：清单自身的绑定（已知限制）+ 版本门控 + stat_kind ──

def test_anchor_catches_a_forged_manifest(tmp_path, monkeypatch):
    """方案 A：清单自身锚到 run 之外 → **伪造清单被查得出**。

    第七轮那条 major（"删掉记录就能掩盖删档"）此前只能文档化；现在锚点把"清单被改写"
    变成可检测：锚点里记着清单正文的摘要，改写清单就与锚点对不上。
    残余（如实记）：只改本机锚点仍能掩盖——那要靠把锚点复制到 mac-backup 才关得掉。
    """
    from article_group import run_seal
    from article_group.run_state import seal

    monkeypatch.setenv(run_seal.ANCHOR_DIR_ENV, str(tmp_path / "anchors"))
    run = _make_run(tmp_path)
    build(run)
    run_seal.write_manifest(run, run_seal.build_manifest(run, sealed_at="2026-09-24T00:00:00+08:00", sealed_by="t"))
    seal(run, identity="t")
    assert run_seal.verify(run)["status"] == "intact"
    assert run_seal.read_anchor(run) is not None, "封存时应当写下锚点"

    victim = run / "delivery/art-001/delivery.md"
    _sh(f"import os; os.unlink({str(victim)!r})")                 # 进程外删除
    assert any(c["path"] == "delivery/art-001/delivery.md" for c in run_seal.verify(run)["changes"])

    _sh(                                                          # 进程外抹掉记录以掩盖
        "import json;"
        f"p={str(run / 'SEALED.manifest.json')!r};"
        "d=json.load(open(p));"
        "d['files']=[f for f in d['files'] if f['path']!='delivery/art-001/delivery.md'];"
        "d['file_count']=len(d['files']);"
        "open(p,'w').write(json.dumps(d))"
    )
    result = run_seal.verify(run)
    assert result["status"] == "drifted", f"伪造清单没被发现：{result}"
    assert result["anchor"]["status"] == "anchor_mismatch"
    assert any(c["kind"] == "anchor_mismatch" for c in result["changes"])


def test_a_removed_local_anchor_is_loud_not_intact(tmp_path, monkeypatch):
    """残余如实记：只改本机锚点仍能掩盖 → 但这种情形必须**响亮**（报 missing），不报 intact。"""
    from article_group import run_seal
    from article_group.run_state import seal

    monkeypatch.setenv(run_seal.ANCHOR_DIR_ENV, str(tmp_path / "anchors"))
    run = _make_run(tmp_path)
    build(run)
    run_seal.write_manifest(run, run_seal.build_manifest(run, sealed_at="2026-09-24T00:00:00+08:00", sealed_by="t"))
    seal(run, identity="t")

    anchor = run_seal.anchor_file_for(run)
    _sh(f"import os; os.unlink({str(anchor)!r})")
    result = run_seal.verify(run)
    assert result["status"] == "drifted"
    assert result["anchor"]["status"] == "anchor_missing"
    assert any(c["kind"] == "anchor_missing" for c in result["changes"])


def test_anchor_push_failure_is_recorded_not_fatal(tmp_path, monkeypatch):
    """离机复制失败不阻断封存，但**机器可读层不许自相矛盾**（第二轮复核 major）。

    此前这里断言清单记 `anchor_unavailable`——可本机锚点其实**写成了**，而 `verify`
    走"锚点文件在"的分支报 `intact`/退出 0。于是同一份报告里清单说"锚点不可用"、
    verify 说"完好"，人读行还只说"离机复制状态：failed"，**没有**那句要命的
    「仅本机快照，只改本机锚点仍能掩盖」——F1 要关的安全假象在这个变体下原样存在。

    现在如实记：锚点**已锚到 run 之外**（本机），只是离机那一步失败。
    """
    from article_group import run_seal
    from article_group.run_state import seal

    monkeypatch.setenv(run_seal.ANCHOR_DIR_ENV, str(tmp_path / "anchors"))
    monkeypatch.setenv(run_seal.ANCHOR_PUSH_ENV, "ssh://mac-backup/Users/Allen/Backups/does-not-exist.git")
    monkeypatch.setattr(
        run_seal, "_replicate_anchor",
        lambda *_args, **_kwargs: ("failed", "simulated unreachable"),
    )
    run = _make_run(tmp_path)
    build(run)
    run_seal.write_manifest(run, run_seal.build_manifest(run, sealed_at="t", sealed_by="t"))
    seal(run, identity="t")
    payload = json.loads((run / "SEALED.manifest.json").read_text(encoding="utf-8"))
    assert payload["anchor"]["status"] == "anchored"
    assert payload["anchor"]["kind"] == "local-snapshot"
    assert payload["anchor"]["replication"] == "failed"
    assert "simulated unreachable" in payload["anchor"]["reason"]
    assert run_seal.read_anchor(run) is not None, "本机锚点仍应留下"


def test_a_failed_push_keeps_the_local_snapshot_warning_in_the_report(tmp_path, monkeypatch):
    """major（第二轮复核）：push 失败 = 没有离机副本，警告必须与 local-only 同等强烈。"""
    from article_group import run_seal
    from article_group.run_state import seal

    monkeypatch.setenv(run_seal.ANCHOR_DIR_ENV, str(tmp_path / "anchors"))
    monkeypatch.setenv(run_seal.ANCHOR_PUSH_ENV, "ssh://example/ledger.git")
    monkeypatch.setattr(run_seal, "_replicate_anchor",
                        lambda *_a, **_k: ("failed", "simulated unreachable"))
    run = _make_run(tmp_path)
    build(run)
    run_seal.write_manifest(run, run_seal.build_manifest(run, sealed_at="t", sealed_by="t"))
    seal(run, identity="t")

    report = run_seal.verify(run)
    manifest_block = run_seal.load_manifest(run)["anchor"]
    # 机器可读层两层必须一致（此前清单 anchor_unavailable、verify anchored）
    assert manifest_block["status"] == report["anchor"]["status"] == "anchored"
    assert report["anchor"]["replication"] == "failed"
    # 人读层必须有那句本机快照的警告（与 local-only 同等待遇）
    text = run_seal._describe(report)
    assert "仅本机快照" in text, text
    assert "只改本机锚点仍能掩盖" in text, text
    # 补救提示不能说"重跑封存"——seal() 幂等，重跑不会重试锚点
    assert "重跑封存" not in text, text


def test_check_remote_does_not_run_during_verify(tmp_path, monkeypatch):
    """verify 不得联网。离机对照只在显式 check_remote_anchor 时发生。"""
    from article_group import run_seal
    from article_group.run_state import seal

    monkeypatch.setenv(run_seal.ANCHOR_DIR_ENV, str(tmp_path / "anchors"))
    called: list[str] = []
    monkeypatch.setattr(run_seal, "check_remote_anchor", lambda *_a, **_k: called.append("hit") or {"status": "matches"})
    run = _make_run(tmp_path)
    build(run)
    run_seal.write_manifest(run, run_seal.build_manifest(run, sealed_at="t", sealed_by="t"))
    seal(run, identity="t")
    assert run_seal.verify(run)["status"] == "intact"
    assert called == []


def test_check_remote_reports_a_mismatch(tmp_path, monkeypatch):
    from article_group import run_seal

    monkeypatch.setenv(run_seal.ANCHOR_DIR_ENV, str(tmp_path / "anchors"))
    run = _make_run(tmp_path)
    build(run)
    run_seal.write_manifest(run, run_seal.build_manifest(run, sealed_at="t", sealed_by="t"))
    name = run_seal.anchor_file_for(run).name

    def fake_run(argv, *args, **kwargs):
        class _Done:
            returncode = 0
            stderr = b""
            stdout = b""
        if argv[:2] == ["git", "archive"]:
            done = _Done()
            done.stdout = _tar_bytes(f"anchors/{name}", b'{"manifest_digest":"other"}')
            return done
        if argv[:2] == ["tar", "-t"]:
            done = _Done()
            done.stdout = f"anchors/{name}\n".encode()
            return done
        if argv[:2] == ["tar", "-xO"]:
            done = _Done()
            done.stdout = b'{"manifest_digest":"other"}'
            return done
        raise AssertionError(argv)

    monkeypatch.setattr(run_seal.subprocess, "run", fake_run)
    report = run_seal.check_remote_anchor(run, remote="ssh://example/seal-ledger.git")
    assert report["status"] == "remote_mismatch"
    assert report["remote_digest"] == "other"


def _tar_bytes(member: str, payload: bytes) -> bytes:
    import io
    import tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(member)
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


def test_anchor_without_push_stays_local_only(tmp_path, monkeypatch):
    """没开推送时不得假装已复制到离机。"""
    from article_group import run_seal
    from article_group.run_state import seal

    monkeypatch.setenv(run_seal.ANCHOR_DIR_ENV, str(tmp_path / "anchors"))
    monkeypatch.delenv(run_seal.ANCHOR_PUSH_ENV, raising=False)
    run = _make_run(tmp_path)
    build(run)
    run_seal.write_manifest(run, run_seal.build_manifest(run, sealed_at="t", sealed_by="t"))
    seal(run, identity="t")
    payload = json.loads((run / "SEALED.manifest.json").read_text(encoding="utf-8"))
    assert payload["anchor"]["status"] == "anchored"
    assert payload["anchor"]["replication"] == "local-only"
    assert payload["anchor"]["remote"] == ""


def test_unwritable_anchor_store_records_anchor_unavailable(tmp_path, monkeypatch):
    """离线/不可写策略（controller 定）：照常封存，但在清单里**如实**记 anchor_unavailable。"""
    from article_group import run_seal
    from article_group.run_state import seal

    ro = tmp_path / "readonly"
    ro.mkdir()
    os.chmod(ro, 0o500)
    monkeypatch.setenv(run_seal.ANCHOR_DIR_ENV, str(ro / "anchors"))
    try:
        run = _make_run(tmp_path)
        build(run)
        run_seal.write_manifest(run, run_seal.build_manifest(run, sealed_at="t", sealed_by="t"))
        seal(run, identity="t")                      # 不因锚点写不进去而阻断封存
        payload = json.loads((run / "SEALED.manifest.json").read_text(encoding="utf-8"))
        assert payload["anchor"]["status"] == "anchor_unavailable", payload["anchor"]
        assert payload["anchor"]["reason"] and payload["anchor"]["remedy"]
        report = run_seal.verify(run)
        assert report["anchor"]["status"] == "anchor_unavailable"
        # 2026-09-25 语义修正：这里此前断言 `intact`——但"锚点不可用"意味着**清单有没被
        # 改写查不出来**，报 intact 就是在说一件没被证明的事。现在改报
        # unanchored（文件逐字节没变 ≠ 证明过没被改），且不算漂移。
        assert report["status"] == run_seal.STATUS_UNANCHORED, \
            "锚点不可用本身不算漂移，但它也**不是** intact——它证明不了清单没被改写"
        assert report["changes"] == []
    finally:
        os.chmod(ro, 0o755)


def test_v2_manifest_without_the_flag_is_refused_not_downgraded(tmp_path):
    """H2：门控键在版本上——v2 清单丢标志要**拒绝给结论**，不许安静降级或假 missing。"""
    from article_group import run_seal
    from article_group.run_state import seal

    run = _make_run(tmp_path)
    build(run)
    run_seal.write_manifest(run, run_seal.build_manifest(run, sealed_at="2026-09-24T00:00:00+08:00", sealed_by="t"))
    seal(run, identity="t")
    assert run_seal.verify(run)["status"] == "intact"
    # 注意：write_manifest 会把 inventory 规范化回来，所以"缺标志"只可能来自
    # **封存后的进程外改写**——这正是本门控要拦的篡改形态
    _sh(
        "import json;"
        f"p={str(run / 'SEALED.manifest.json')!r};"
        "d=json.load(open(p)); d.pop('inventory', None); open(p,'w').write(json.dumps(d))"
    )

    result = run_seal.verify(run)
    assert result["status"] == "unverifiable", f"竟然给了结论：{result}"
    # 精确断言（复核 F11）：弱断言会在门控被换成别的理由时静默放行
    assert result["reason"] == "清单声明 v2 却缺 inventory 标志：可能被改写，拒绝给结论", result


def test_a_v1_manifest_carrying_the_v2_flag_is_refused_not_silently_downgraded(tmp_path):
    """版本与标志矛盾时**拒绝给结论**（2026-09-25 政策变更）。

    此前这里断言 v1+标志走旧口径（"不冒假 added"）。但那条口径给了攻击者一条
    降低校验强度的路：把 v2 清单的 `schema_version` 改回 v1，就能让校验退回
    "只比文件"的旧语义。现在两个信号矛盾一律 unverifiable。

    真 v1 run 的覆盖见 `tests/test_run_seal.py::_v1_sealed_run`（本函数无法造出
    真 v1：`seal()` 会重建清单）。
    """
    from article_group import run_seal

    run = _make_run(tmp_path)
    build(run)
    payload = run_seal.build_manifest(run, sealed_at="2026-09-24T00:00:00+08:00", sealed_by="t")
    payload["schema_version"] = run_seal.SCHEMA_VERSION_V1
    payload["inventory"] = run_seal.INVENTORY_ALL_ENTRIES
    run_seal.write_manifest(run, payload)

    result = run_seal.verify(run)
    assert result["status"] == "unverifiable", f"矛盾的版本/标志被放行：{result}"
    # 精确断言（第二轮复核 minor）：同模式的弱断言原有三处，这里是最初漏掉的一处
    assert result["reason"] == "清单声明 v1 却带着 v2 的 inventory 标志：两个信号矛盾，拒绝给结论", result


def test_fifo_replaced_by_socket_is_detected(tmp_path):
    """minor 3：同为 other，具体类型（fifo↔socket）变化也要报。"""
    from article_group import run_seal
    from article_group.run_state import seal

    run = _make_run(tmp_path)
    build(run)
    os.mkfifo(run / "node")
    run_seal.write_manifest(run, run_seal.build_manifest(run, sealed_at="2026-09-24T00:00:00+08:00", sealed_by="t"))
    seal(run, identity="t")
    assert run_seal.verify(run)["status"] == "intact"

    _sh(
        "import os, socket;"
        f"p={str(run / 'node')!r};"
        "os.unlink(p);"
        "s=socket.socket(socket.AF_UNIX); s.bind(p)"
    )
    changes = run_seal.verify(run)["changes"]
    assert any(c["path"] == "node" for c in changes), f"fifo 换成 socket 没被发现：{changes}"


# ── 第七轮 minor 4 收口：拒绝路径要"早、干净、退出码合规" ──

def test_backfill_cli_reports_unscannable_tree_with_exit_code_3(tmp_path):
    """`--backfill` 在扫不动的树上要按文档退 3 并给人话，不要甩 traceback。"""
    run = _make_run(tmp_path)
    build(run)
    dead = run / "dead"
    dead.mkdir()
    (dead / "x.txt").write_text("x", encoding="utf-8")
    os.chmod(dead, 0o000)
    # 必须"已封存但缺清单"：没有 SEALED 时 backfill 会直接返回 not_sealed 短路，
    # 根本走不到扫描路径（我第一次就是这么写错的——测试没测到目标分支）
    (run / "SEALED").write_text('{"sealed_at": "2026-09-24T00:00:00+08:00", "sealed_by": "t"}', encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "article_group.run_seal", "--run-root", str(run), "--backfill"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
        )
    finally:
        os.chmod(dead, 0o755)

    assert proc.returncode == 3, f"退出码应 3，实为 {proc.returncode}\n{proc.stderr[-400:]}"
    assert "Traceback" not in proc.stderr, f"不该甩 traceback：{proc.stderr[-300:]}"
    assert "扫不动" in (proc.stdout + proc.stderr), "要给出人话原因"
    assert not (run / "SEALED.manifest.json").exists(), "扫不动的树不该被封存"


def test_close_out_preflights_the_scan_before_mutating(tmp_path):
    """`close_out` 必须在**动手之前**发现扫不动的树：留下未封存的半改 run 是不可接受的。"""
    from article_group import close_out as close_out_mod

    run = _make_run(tmp_path)
    build(run)
    before = sorted(p.name for p in run.iterdir())
    dead = run / "dead"
    dead.mkdir()
    (dead / "x.txt").write_text("x", encoding="utf-8")
    os.chmod(dead, 0o000)
    try:
        report = close_out_mod.close_out(run, identity="test", confirm=True)
        assert report["status"] == "unscannable_tree", report
        assert report["steps"] == [], f"预检失败却已经动了手：{report['steps']}"
        assert not (run / "SEALED").exists()
        assert sorted(p.name for p in run.iterdir()) == sorted(before + ["dead"]), \
            "预检失败却改动了 run"
    finally:
        os.chmod(dead, 0o755)


# ── 第八轮 minor 收口：坏 --run-root / 封存前复检（TOCTOU）/ 单份 JSON ──

def test_preflight_scan_rejects_a_bad_root(tmp_path):
    """minor 2：坏路径 ≠ 扫不动的树——前者要指向 --run-root，别给"修权限"的误导建议。"""
    from article_group.run_seal import preflight_scan

    missing = preflight_scan(tmp_path / "nope")
    assert missing["ok"] is False and missing["bad_root"] is True
    assert "run-root" in missing["remedy"] or "run 目录" in missing["reason"]
    assert not missing["scan_errors"]

    as_file = tmp_path / "afile.txt"
    as_file.write_text("x", encoding="utf-8")
    assert preflight_scan(as_file)["bad_root"] is True

    ok = preflight_scan(_make_run(tmp_path))
    assert ok["ok"] is True and ok["bad_root"] is False


def test_close_out_reports_a_bad_run_root_with_its_own_status(tmp_path):
    """minor 2：`close_out` 对坏 --run-root 给独立状态，不退 3（那是"无法验证的树"）。"""
    from article_group import close_out as close_out_mod

    report = close_out_mod.close_out(tmp_path / "typo-run-root", identity="test", confirm=True)
    assert report["status"] == "bad_run_root", report
    assert report["steps"] == []

    proc = subprocess.run(
        [sys.executable, "-m", "article_group.close_out", "--run-root", str(tmp_path / "typo"),
         "--identity", "test", "--confirm"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert proc.returncode == 2, f"坏 --run-root 应退 2，实为 {proc.returncode}\n{proc.stderr[-300:]}"


# 说明：TOCTOU（预检之后、封存之前树变得扫不动）的修复已在 close_out 里落地——
# 封存前**复检**+ 把失败转成干净的 unscannable_tree 报告（不再抛未捕获异常）。
# 但本测试没能稳定地搭出来（要打桩 _run_step 与惰性导入的 preflight_scan，耦合太紧），
# 因此**不留半可靠的测试**：该路径目前只有八轮复核的复现作证，缺口记在 RUN-RECORD §8。
# 复核者建议的搭法：用 close_out 的 `runner` 钩子在跑动中途注入 chmod。

def test_backfill_failure_emits_a_single_json_document(tmp_path):
    """minor 3：失败路径只发**一份** JSON（stderr），stdout 保持干净可解析。"""
    run = _make_run(tmp_path)
    build(run)
    dead = run / "dead"
    dead.mkdir()
    (dead / "x.txt").write_text("x", encoding="utf-8")
    os.chmod(dead, 0o000)
    (run / "SEALED").write_text('{"sealed_at": "2026-09-24T00:00:00+08:00", "sealed_by": "t"}', encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "article_group.run_seal", "--run-root", str(run), "--backfill"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
        )
    finally:
        os.chmod(dead, 0o755)

    assert proc.returncode == 3
    assert proc.stdout.strip() == "", f"stdout 不该再发第二份文档：{proc.stdout[:200]}"
    payload = json.loads(proc.stderr)          # 单份、可解析
    assert payload["status"] == "unverifiable"
    assert json.loads(proc.stdout + proc.stderr)  # 合并后仍是**一份**合法 JSON


# ── 第九轮加固：退出码文档化 / 词汇统一 / TOCTOU 可靠测试 ──

def test_close_out_documents_and_pins_its_exit_codes(tmp_path):
    """退出码既要**写进 argparse**，也要**钉住**（此前只有注释、只有一个码被测）。"""
    from article_group import close_out as close_out_mod

    parser = close_out_mod._build_parser()
    epilog = parser.epilog or ""
    for code in ("0", "1", "2", "3"):
        assert code in epilog, f"退出码 {code} 没写进 argparse"
    assert "无法验证" in epilog and "--run-root" in epilog

    def cli(*extra: str) -> int:
        return close_out_mod.main(["--run-root", str(tmp_path / "typo"), *extra])

    assert cli("--identity", "test", "--confirm") == 2, "坏 --run-root 应退 2"
    assert cli("--identity", "test") == 1, "缺 --confirm 应退 1（confirmation_required）"


def test_preflight_and_verify_share_one_scan_vocabulary(tmp_path):
    """两处都要给 ok / reason / remedy / scan_errors —— 调用方不必为两种形状各写一套。"""
    from article_group import run_seal
    from article_group.run_state import seal

    run = _make_run(tmp_path)
    build(run)
    dead = run / "dead"
    dead.mkdir()
    (dead / "x.txt").write_text("x", encoding="utf-8")
    # 顺序很重要：扫不动的树**不许封存**（round-7 的 fail-closed），所以先封存，
    # 再由**进程外**把它变成不可读（封存后进程内写入会被护栏拦下）
    run_seal.write_manifest(run, run_seal.build_manifest(run, sealed_at="t", sealed_by="t"))
    seal(run, identity="t")
    _sh(f"import os; os.chmod({str(dead)!r}, 0)")
    try:
        pre = run_seal.preflight_scan(run)
        assert pre["ok"] is False
        assert pre["reason"] and pre["remedy"] and pre["scan_errors"]
        assert set(pre["scan_errors"][0]) == {"path", "error"}

        rep = run_seal.verify(run)
        assert rep["status"] == "unverifiable"
        for key in ("ok", "reason", "remedy", "scan_errors"):
            assert key in rep, f"verify 缺少统一词汇 {key}"
        assert rep["ok"] is False
        assert set(rep["scan_errors"][0]) == {"path", "error"}
    finally:
        _sh(f"import os; os.chmod({str(dead)!r}, 0o755)")


def test_close_out_catches_a_tree_that_becomes_unscannable_mid_run(tmp_path, monkeypatch):
    """TOCTOU 的可靠测试（复核者建议的搭法）：用 `runner` 钩子在**跑动中途**注入 chmod。

    预检在 t0 通过；runner 在第一个子进程步骤被调用时把 victim 变成不可读；封存前的
    复检必须拦下，并给出干净报告（保留已完成 steps、不抛异常、不封存）。
    """
    from article_group import close_out as close_out_mod
    import article_group.wechat_render as wechat_mod

    run = _make_run(tmp_path)
    build(run)
    victim = run / "victim"
    victim.mkdir()
    (victim / "x.txt").write_text("x", encoding="utf-8")
    fired: list[int] = []

    class _Done:
        returncode = 0
        stdout = ""
        stderr = ""

    def runner(*_args, **_kwargs):
        if not fired:                       # 第一次子进程步骤：制造 TOCTOU
            os.chmod(victim, 0o000)
            fired.append(1)
        return _Done()

    monkeypatch.setattr(close_out_mod, "reconcile", lambda *a, **k: {"stale_records": []})
    monkeypatch.setattr(close_out_mod, "write_close_out_section", lambda *a, **k: None)
    monkeypatch.setattr(close_out_mod, "write_step_log_markdown", lambda *a, **k: None)
    monkeypatch.setattr(wechat_mod, "render_run", lambda *a, **k: {"index_path": ""})

    try:
        report = close_out_mod.close_out(run, identity="test", confirm=True, runner=runner)
        assert report["status"] == "unscannable_tree", report
        assert "封存前复检" in report["reason"] or "扫不动" in report["reason"]
        names = [s["name"] for s in report["steps"]]
        assert "seal" not in names, f"复检已拦下，不该走到封存：{names}"
        assert names, "已完成的步骤要如实保留"
        assert not (run / "SEALED").exists()
    finally:
        os.chmod(victim, 0o755)


def test_a_failed_rebuild_over_a_legacy_preview_cannot_be_published(tmp_path):
    """F7（2026-09-25 复核）：legacy 形态（有 index.html、没有 links.json）也要被桩覆盖。

    daily-009 / daily-010 实测都是这个形态。此前桩落在 `read_article` 之后，于是
    "在写第一页之前失败"的 rebuild 会留下没有清单的旧站点，而 publish 把它当
    "早于本产物的旧 run"放行——发布出去的是上一轮的站点。
    """
    run = _make_run(tmp_path)
    build(run)
    (run / "preview/links.json").unlink()               # 旧版产物形态
    (run / "delivery/art-002/delivery.md").unlink()      # 让 read_article 在写页面之前失败

    with pytest.raises(OSError):
        build(run)

    static = tmp_path / "outbox"
    static.mkdir()
    with pytest.raises(ValueError):
        publish(run, static, base_url="http://192.168.100.168:8899")
    assert not (static / "2026-09-17-daily-999").exists(), "陈旧站点被发布到了静态根"


def test_a_true_first_build_failure_still_leaves_no_preview_dir(tmp_path):
    """反向保证：真正的首轮失败**不该**产生 preview/（那是"本阶段没跑"的信号）。"""
    run = _make_run(tmp_path)
    (run / "delivery/art-002/delivery.md").unlink()

    with pytest.raises(OSError):
        build(run)

    assert not (run / "preview").exists(), "首轮失败不该留下 preview/ 目录"
