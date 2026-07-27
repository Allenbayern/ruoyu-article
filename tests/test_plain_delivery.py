"""Slice 5 RED: single markdown→plain renderer and stale-plain fail-closed gate."""

from __future__ import annotations

from pathlib import Path

import pytest


SAMPLE_MARKDOWN = """# 标题一行

第一段有**加粗**和*斜体*。

## 小标题

第二段有[链接](https://example.com)与`代码`。
"""

EXPECTED_PLAIN = """标题一行

第一段有加粗和斜体。

小标题

第二段有链接与代码。
"""


def test_render_plain_text_strips_markdown_keeps_blank_line_paragraphs():
    from article_group.delivery import render_plain_text

    assert render_plain_text(SAMPLE_MARKDOWN) == EXPECTED_PLAIN


def test_render_plain_text_rejects_non_string_without_coercion():
    from article_group.delivery import render_plain_text

    with pytest.raises(TypeError):
        render_plain_text(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        render_plain_text(["# x"])  # type: ignore[arg-type]


def test_write_plain_from_markdown_writes_derived_bytes(tmp_path: Path):
    from article_group.delivery import write_plain_from_markdown

    md = tmp_path / "article-draft.md"
    plain = tmp_path / "article-plain.txt"
    md.write_text(SAMPLE_MARKDOWN, encoding="utf-8")

    text = write_plain_from_markdown(md, plain)

    assert text == EXPECTED_PLAIN
    assert plain.read_text(encoding="utf-8") == EXPECTED_PLAIN


def test_validate_plain_delivery_passes_when_plain_matches_and_not_stale(tmp_path: Path):
    from article_group.delivery import validate_plain_delivery, write_plain_from_markdown

    md = tmp_path / "article-draft.md"
    plain = tmp_path / "article-plain.txt"
    md.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    write_plain_from_markdown(md, plain)

    assert validate_plain_delivery(md, plain) == []


def test_validate_plain_delivery_fails_when_plain_missing(tmp_path: Path):
    from article_group.delivery import validate_plain_delivery

    md = tmp_path / "article-draft.md"
    plain = tmp_path / "article-plain.txt"
    md.write_text(SAMPLE_MARKDOWN, encoding="utf-8")

    assert "plain_missing" in validate_plain_delivery(md, plain)


def test_validate_plain_delivery_fails_on_content_drift(tmp_path: Path):
    from article_group.delivery import validate_plain_delivery, write_plain_from_markdown

    md = tmp_path / "article-draft.md"
    plain = tmp_path / "article-plain.txt"
    md.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    write_plain_from_markdown(md, plain)
    plain.write_text(plain.read_text(encoding="utf-8") + "额外一行\n", encoding="utf-8")

    assert "plain_content_mismatch" in validate_plain_delivery(md, plain)


def test_validate_plain_delivery_fails_when_markdown_newer_than_plain(tmp_path: Path):
    from article_group.delivery import validate_plain_delivery, write_plain_from_markdown
    import os
    import time

    md = tmp_path / "article-draft.md"
    plain = tmp_path / "article-plain.txt"
    md.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    write_plain_from_markdown(md, plain)

    # Make markdown strictly newer than plain without changing rendered equality path:
    # first age the plain file, then rewrite markdown with identical bytes + newer mtime.
    older = time.time() - 10
    os.utime(plain, (older, older))
    md.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    newer = time.time()
    os.utime(md, (newer, newer))

    errors = validate_plain_delivery(md, plain)
    assert "plain_stale_markdown_newer" in errors


def test_validate_plain_delivery_fails_when_plain_retains_markdown_markers(tmp_path: Path):
    from article_group.delivery import validate_plain_delivery

    md = tmp_path / "article-draft.md"
    plain = tmp_path / "article-plain.txt"
    md.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    # Hand-written stale-looking plain that still has markdown markers and is newer.
    plain.write_text("# 标题一行\n\n第一段\n", encoding="utf-8")

    errors = validate_plain_delivery(md, plain)
    assert "plain_retains_markdown_markers" in errors or "plain_content_mismatch" in errors


def test_validate_run_plain_delivery_checks_all_slots(tmp_path: Path):
    from article_group.delivery import validate_run_plain_delivery, write_plain_from_markdown

    for slot in ("A", "B", "C"):
        slot_dir = tmp_path / "articles" / slot
        slot_dir.mkdir(parents=True)
        md = slot_dir / "article-draft.md"
        plain = slot_dir / "article-plain.txt"
        md.write_text(f"# 槽{slot}\n\n正文{slot}。\n", encoding="utf-8")
        write_plain_from_markdown(md, plain)

    assert validate_run_plain_delivery(tmp_path) == []

    # Break slot B
    (tmp_path / "articles" / "B" / "article-plain.txt").write_text("漂移\n", encoding="utf-8")
    errors = validate_run_plain_delivery(tmp_path)
    assert any(err.startswith("slot_B:") for err in errors)


def test_validate_run_plain_delivery_rejects_non_directory(tmp_path: Path):
    from article_group.delivery import validate_run_plain_delivery

    bogus = tmp_path / "not-a-dir.txt"
    bogus.write_text("x", encoding="utf-8")
    assert validate_run_plain_delivery(bogus) == ["run_dir_must_be_a_directory"]
    assert validate_run_plain_delivery(None) == ["run_dir_must_be_a_directory"]  # type: ignore[arg-type]


def test_render_plain_text_converts_parenthesized_url_links_to_label():
    from article_group.delivery import render_plain_text

    md = "见[标签](https://example.test/a_(b))。\n"
    assert render_plain_text(md) == "见标签。\n"


def test_render_plain_text_converts_reference_links_and_drops_definitions():
    from article_group.delivery import render_plain_text, validate_plain_delivery, write_plain_from_markdown
    from pathlib import Path

    md_text = "见[标签][r]。\n\n[r]: https://example.test\n"
    assert render_plain_text(md_text) == "见标签。\n"

    # write→validate must pass only when plain is label-only (no residual ref syntax)
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        md = root / "article-draft.md"
        plain = root / "article-plain.txt"
        md.write_text(md_text, encoding="utf-8")
        write_plain_from_markdown(md, plain)
        assert plain.read_text(encoding="utf-8") == "见标签。\n"
        assert validate_plain_delivery(md, plain) == []
