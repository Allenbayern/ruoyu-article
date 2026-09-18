"""wechat_render：把已封存交付稿渲染成"打开即可复制"的公众号排版版。

测试不依赖 docker / 网络：渲染器用可注入的命令模板，测试里换成桩脚本。
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

from article_group.wechat_render import (
    DEFAULT_THEME,
    RendererFailed,
    RendererUnavailable,
    cjk_chars,
    copy_page,
    main,
    normalize_for_wechat,
    render_markdown,
    render_run,
)

ARTICLE = """# 标题：姜文为什么一部比一部拧巴

## 第一节

影片上映第一周，豆瓣评分稳定在6.7分，文汇报的评语既没有把它捧上神坛，也没有把它归入烂片。
"""


def _stub_renderer(tmp_path: Path) -> str:
    """A fake renderer: reads the md file, emits an inline-styled fragment."""
    script = tmp_path / "stub_render.py"
    script.write_text(
        textwrap.dedent(
            """
            import pathlib, sys
            theme = sys.argv[2] if len(sys.argv) > 2 else "default"
            text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
            lines = [l for l in text.splitlines() if l.strip() and not l.startswith("#")]
            body = "".join(f'<p style="margin:1em 0">{l}</p>' for l in lines)
            print(f'<section id="wenyan" style="font-size:16px" data-theme="{theme}">{body}</section>')
            """
        ),
        encoding="utf-8",
    )
    return f"{sys.executable} {script} {{md_file}} {{theme}}"


def _run_with_deliveries(tmp_path: Path, *articles: str) -> Path:
    root = tmp_path / "daily-900"
    for index, text in enumerate(articles, start=1):
        target = root / "delivery" / f"art-{index:03d}"
        target.mkdir(parents=True, exist_ok=True)
        (target / "delivery.md").write_text(text, encoding="utf-8")
    return root


def test_render_markdown_returns_fragment_and_command(tmp_path):
    fragment, used = render_markdown(ARTICLE, renderer_cmd=_stub_renderer(tmp_path))
    assert '<section id="wenyan"' in fragment
    assert "豆瓣评分稳定在6.7分" in fragment
    assert "stub_render.py" in used


def test_render_markdown_passes_theme(tmp_path):
    fragment, _ = render_markdown(ARTICLE, theme="pie", renderer_cmd=_stub_renderer(tmp_path))
    assert 'data-theme="pie"' in fragment


def test_render_markdown_missing_renderer_raises_unavailable():
    with pytest.raises(RendererUnavailable):
        render_markdown(ARTICLE, renderer_cmd="/nonexistent/renderer {md_file}")


def test_render_markdown_failing_renderer_raises_failed(tmp_path):
    with pytest.raises(RendererFailed):
        render_markdown(ARTICLE, renderer_cmd=f"{sys.executable} -c \"import sys; sys.exit(3)\"")


def test_render_run_writes_artifacts_and_hashes(tmp_path):
    root = _run_with_deliveries(tmp_path, ARTICLE)
    report = render_run(root, renderer_cmd=_stub_renderer(tmp_path))

    assert report["status"] == "ok"
    assert report["theme"] == DEFAULT_THEME
    assert report["publication_authorization"] == "not_authorized"
    assert len(report["articles"]) == 1

    item = report["articles"][0]
    assert item["article_id"] == "art-001"
    assert item["title"].startswith("标题：姜文")
    assert item["cjk_chars"] == cjk_chars(ARTICLE)
    assert item["inline_style_count"] >= 1

    wx_path = root / item["fragment_path"]
    page_path = root / item["copy_page_path"]
    assert wx_path.exists() and page_path.exists()
    assert (root / "wechat" / "index.html").exists()
    assert report["index_path"] == "wechat/index.html"

    page = page_path.read_text(encoding="utf-8")
    assert "copyArticle()" in page and "copySource()" in page
    # native 结构：渲染器主题被归一（去 id/H1，无文字阴影，p 换成后台原生段距）
    assert "<section" in page and 'id="wenyan"' not in page
    assert "text-shadow" not in page
    assert 'style="margin: 0 0 1.2em; line-height: 1.75; font-size: 16px; color: #333;"' in page
    assert "not_authorized" in (root / "wechat" / "manifest.json").read_text(encoding="utf-8")


def test_render_run_records_hashes_of_source_and_output(tmp_path):
    root = _run_with_deliveries(tmp_path, ARTICLE)
    report = render_run(root, renderer_cmd=_stub_renderer(tmp_path))
    item = report["articles"][0]

    import hashlib

    source = (root / "delivery" / "art-001" / "delivery.md").read_bytes()
    fragment = (root / item["fragment_path"]).read_bytes()
    assert item["source_sha256"] == hashlib.sha256(source).hexdigest()
    assert item["fragment_sha256"] == hashlib.sha256(fragment).hexdigest()


def test_render_run_handles_multiple_articles_and_index(tmp_path):
    root = _run_with_deliveries(tmp_path, ARTICLE, ARTICLE.replace("姜文", "还珠"))
    report = render_run(root, renderer_cmd=_stub_renderer(tmp_path))
    assert [item["article_id"] for item in report["articles"]] == ["art-001", "art-002"]
    index = (root / "wechat" / "index.html").read_text(encoding="utf-8")
    assert "art-001.html" in index and "art-002.html" in index


def test_render_run_without_deliveries_is_not_an_error(tmp_path):
    root = tmp_path / "daily-901"
    root.mkdir()
    report = render_run(root, renderer_cmd=_stub_renderer(tmp_path))
    assert report["status"] == "no_deliveries"
    assert report["articles"] == []
    assert (root / "wechat" / "manifest.json").exists()


def test_render_run_records_unavailable_without_failing(tmp_path):
    root = _run_with_deliveries(tmp_path, ARTICLE)
    report = render_run(root, renderer_cmd="/nonexistent/renderer {md_file}")
    assert report["status"] == "unavailable"
    assert report["reason"].startswith("renderer_not_found")
    manifest = json.loads((root / "wechat" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "unavailable"
    assert manifest["publication_authorization"] == "not_authorized"


def test_render_run_records_failed_renderer(tmp_path):
    root = _run_with_deliveries(tmp_path, ARTICLE)
    report = render_run(root, renderer_cmd=f"{sys.executable} -c \"import sys; sys.exit(2)\"")
    assert report["status"] == "failed"
    assert "art-001" in report["reason"]


def test_copy_page_editor_url_is_optional():
    plain = copy_page(title="T", note="n", body_html="<p style='x'>a</p>")
    with_editor = copy_page(title="T", note="n", body_html="<p style='x'>a</p>",
                            editor_url="http://192.168.100.168:8080/")
    assert "用编辑器改排版" not in plain
    assert "http://192.168.100.168:8080/" in with_editor


def test_normalize_drops_duplicated_title_and_restyles():
    rendered = (
        '<section id="wenyan" style="font-family: system-ui; caret-color: rgb(0,0,0);" '
        'data-provider="WenYan">'
        '<h1 style="margin:1em 0;text-align:center;text-shadow:2px 2px 4px rgba(0,0,0,.1)">'
        '<span>标题不能重复</span></h1>'
        '<h2 style="margin:1em 0;text-align:center;border-bottom:1px solid #f7f7f7;'
        'font-weight:bold"><span>第一节</span></h2>'
        '<p style="margin:1em 0"><span>正文一句话。</span></p>'
        '</section>'
    )
    text = normalize_for_wechat(rendered, drop_title=True)
    assert "<h1" not in text and "标题不能重复" not in text
    assert "id=\"wenyan\"" not in text and "data-provider" not in text
    assert "text-shadow" not in text and "text-align:center" not in text
    assert 'style="margin: 1.8em 0 .7em; font-size: 1.05em; font-weight: bold; ' \
           'text-align: left; line-height: 1.6; color: #222;"' in text
    assert "<span" not in text and "正文一句话。" in text


def test_normalize_keeps_title_when_requested():
    rendered = '<h1 style="text-align:center"><span>标题</span></h1><p style="margin:1em 0">正文。</p>'
    text = normalize_for_wechat(rendered, drop_title=False)
    assert "标题" in text and "<h1" in text


def test_render_run_theme_style_keeps_renderer_output(tmp_path):
    root = _run_with_deliveries(tmp_path, ARTICLE)
    report = render_run(root, renderer_cmd=_stub_renderer(tmp_path), style="theme")
    item = report["articles"][0]
    assert item["style"] == "theme" and item["dropped_title"] is False
    page = (root / item["copy_page_path"]).read_text(encoding="utf-8")
    assert 'id="wenyan"' in page  # 渲染器原样保留


def test_cli_renders_and_prints_report(tmp_path, capsys: pytest.CaptureFixture[str]):
    root = _run_with_deliveries(tmp_path, ARTICLE)
    code = main(["--run-root", str(root), "--renderer-cmd", _stub_renderer(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "status=ok" in out
    assert "wechat/art-001.html" in out


def test_cli_json_mode(tmp_path, capsys: pytest.CaptureFixture[str]):
    root = _run_with_deliveries(tmp_path, ARTICLE)
    assert main(["--run-root", str(root), "--renderer-cmd", _stub_renderer(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["articles"][0]["article_id"] == "art-001"


def test_cli_no_cache_forces_a_rerender(tmp_path, capsys: pytest.CaptureFixture[str]):
    root = _run_with_deliveries(tmp_path, ARTICLE)
    renderer, counter = _counting_renderer(tmp_path)

    assert main(["--run-root", str(root), "--renderer-cmd", renderer, "--json"]) == 0
    capsys.readouterr()
    assert main(["--run-root", str(root), "--renderer-cmd", renderer, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["cache"]["hits"] == 1

    assert main(
        ["--run-root", str(root), "--renderer-cmd", renderer, "--json", "--no-cache"]
    ) == 0
    forced = json.loads(capsys.readouterr().out)
    assert forced["cache"]["enabled"] is False and forced["cache"]["misses"] == 1
    assert _render_calls(counter) == 2


# --- 渲染缓存（2026-09-18，A1）：输入没变就不再跑 docker+npx -------------------


def _counting_renderer(tmp_path: Path) -> tuple[str, Path]:
    """桩渲染器：每次被调用就往 calls.txt 记一笔，用来证明缓存命中时没渲染。"""

    counter = tmp_path / "calls.txt"
    script = tmp_path / "counting_render.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import pathlib, sys
            counter = pathlib.Path({str(counter)!r})
            counter.write_text((counter.read_text() if counter.exists() else "") + "1")
            theme = sys.argv[2] if len(sys.argv) > 2 else "default"
            text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
            lines = [l for l in text.splitlines() if l.strip() and not l.startswith("#")]
            body = "".join(f'<p style="margin:1em 0">{{l}}</p>' for l in lines)
            print(f'<section id="wenyan" style="font-size:16px" data-theme="{{theme}}">{{body}}</section>')
            """
        ),
        encoding="utf-8",
    )
    return f"{sys.executable} {script} {{md_file}} {{theme}}", counter


def _render_calls(counter: Path) -> int:
    return len(counter.read_text(encoding="utf-8")) if counter.exists() else 0


def test_render_run_reuses_cached_output_when_nothing_changed(tmp_path):
    root = _run_with_deliveries(tmp_path, ARTICLE)
    renderer, counter = _counting_renderer(tmp_path)

    first = render_run(root, renderer_cmd=renderer)
    second = render_run(root, renderer_cmd=renderer)

    assert first["cache"]["hits"] == 0 and first["cache"]["misses"] == 1
    assert second["cache"]["hits"] == 1 and second["cache"]["misses"] == 0
    assert _render_calls(counter) == 1  # 第二次没有跑渲染器
    item = second["articles"][0]
    assert item["cached"] is True
    assert item["fragment_sha256"] == first["articles"][0]["fragment_sha256"]
    assert (root / "wechat" / "index.html").exists()
    assert second["publication_authorization"] == "not_authorized"


def test_cache_invalidates_when_the_delivery_changes(tmp_path):
    root = _run_with_deliveries(tmp_path, ARTICLE)
    renderer, counter = _counting_renderer(tmp_path)
    render_run(root, renderer_cmd=renderer)

    (root / "delivery" / "art-001" / "delivery.md").write_text(
        ARTICLE.replace("6.7分", "7.1分"), encoding="utf-8"
    )
    second = render_run(root, renderer_cmd=renderer)

    assert second["cache"] == {**second["cache"], "hits": 0, "misses": 1}
    assert _render_calls(counter) == 2
    fragment = (root / second["articles"][0]["fragment_path"]).read_text(encoding="utf-8")
    assert "7.1分" in fragment


def test_cache_invalidates_when_theme_or_style_changes(tmp_path):
    root = _run_with_deliveries(tmp_path, ARTICLE)
    renderer, counter = _counting_renderer(tmp_path)
    render_run(root, theme="default", renderer_cmd=renderer)

    other_theme = render_run(root, theme="pie", renderer_cmd=renderer)
    other_style = render_run(root, theme="pie", style="theme", renderer_cmd=renderer)

    assert other_theme["cache"]["misses"] == 1
    assert other_style["cache"]["misses"] == 1
    assert _render_calls(counter) == 3


def test_cache_invalidates_when_the_rendered_files_were_tampered_with(tmp_path):
    root = _run_with_deliveries(tmp_path, ARTICLE)
    renderer, counter = _counting_renderer(tmp_path)
    first = render_run(root, renderer_cmd=renderer)
    (root / first["articles"][0]["fragment_path"]).write_text("<p>被手改过</p>\n", encoding="utf-8")

    second = render_run(root, renderer_cmd=renderer)

    assert second["cache"]["misses"] == 1
    assert _render_calls(counter) == 2
    assert "被手改过" not in (root / first["articles"][0]["fragment_path"]).read_text(encoding="utf-8")


def test_cache_is_ignored_for_records_without_a_pipeline_fingerprint(tmp_path):
    root = _run_with_deliveries(tmp_path, ARTICLE)
    renderer, counter = _counting_renderer(tmp_path)
    render_run(root, renderer_cmd=renderer)

    manifest_path = root / "wechat" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["articles"]:
        entry.pop("pipeline_fingerprint", None)
        entry.pop("copy_page_sha256", None)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    second = render_run(root, renderer_cmd=renderer)

    assert second["cache"]["misses"] == 1
    assert _render_calls(counter) == 2


def test_no_cache_forces_a_rerender(tmp_path):
    root = _run_with_deliveries(tmp_path, ARTICLE)
    renderer, counter = _counting_renderer(tmp_path)
    render_run(root, renderer_cmd=renderer)

    forced = render_run(root, renderer_cmd=renderer, use_cache=False)

    assert forced["cache"]["enabled"] is False
    assert forced["cache"]["misses"] == 1
    assert _render_calls(counter) == 2
