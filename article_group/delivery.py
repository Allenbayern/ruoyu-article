"""Plain-text delivery derive/validate for controlled article runs.

Markdown remains the canonical draft. ``article-plain.txt`` is the copy-paste
deliverable for platforms that do not parse Markdown. This module never
authorizes publication, fetches sources, or renders HTML.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .workflow import validate_delivery_authorization

__all__ = [
    "compose_delivery_markdown",
    "render_plain_text",
    "validate_body_draft",
    "validate_delivery_markdown",
    "write_plain_from_markdown",
    "validate_plain_delivery",
    "validate_run_plain_delivery",
    "validate_delivery_authorization",
]

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
_BOLD_ITALIC_RE = re.compile(r"(\*\*\*|\*\*|\*|___|__|_)(.+?)\1")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_FENCE_RE = re.compile(r"^\s*```.*$")
_H1_LINE_RE = re.compile(r"^[ \t]{0,3}#[ \t]+(?P<title>.+?)[ \t]*#?[ \t]*$")
_REF_DEFINITION_RE = re.compile(r"^\s{0,3}\[([^\]]+)\]:\s+\S+")
_REF_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\[([^\]]*)\]")
# Residual markers that must not appear in plain deliverables.
_MARKDOWN_MARKER_RE = re.compile(
    r"(^|\n)\s{0,3}#{1,6}\s"
    r"|(\*\*|__)"
    r"|^\s*>"
    r"|`"
    r"|^\s*[-*+]\s+\[[ xX]\]"
    r"|^\s{0,3}\[[^\]]+\]:\s+\S+"  # leftover reference definitions
    r"|\[([^\]]+)\]\[([^\]]*)\]"  # leftover reference links
    r"|\[([^\]]+)\]\("  # leftover inline link openers
)


def _markdown_h1s(markdown: str) -> list[str]:
    """Return real Markdown H1 headings, excluding fenced-code contents."""

    headings: list[str] = []
    in_fence = False
    for raw_line in markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if _FENCE_RE.match(raw_line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _H1_LINE_RE.match(raw_line)
        if match and match.group("title").strip():
            headings.append(match.group("title").strip())
    return headings


def validate_body_draft(body_text: str) -> list[str]:
    """Validate the title-free body artifact used by the content stage."""

    if not isinstance(body_text, str):
        return ["body_draft_must_be_a_string"]
    if not body_text.strip():
        return ["body_draft_empty"]
    if _markdown_h1s(body_text):
        return ["body_draft_must_not_have_h1"]
    return []


def compose_delivery_markdown(body_text: str, title: str) -> str:
    """Compose the final Markdown handoff from an already-reviewed body.

    This is intentionally a one-way packaging operation.  It refuses a body
    that already contains an H1 so a temporary title cannot silently become a
    title candidate or a second source of truth.
    """

    body_errors = validate_body_draft(body_text)
    if body_errors:
        raise ValueError(body_errors[0])
    if not isinstance(title, str) or not title.strip() or "\n" in title or "\r" in title:
        raise ValueError("delivery_title_invalid")
    body = body_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return f"# {title.strip()}\n\n{body}\n"


def validate_delivery_markdown(markdown: str, expected_title: str) -> list[str]:
    """Validate exactly one formal H1 and its binding to the selected title."""

    if not isinstance(markdown, str):
        return ["delivery_markdown_must_be_a_string"]
    if not isinstance(expected_title, str) or not expected_title.strip():
        return ["delivery_title_expected_invalid"]
    headings = _markdown_h1s(markdown)
    errors: list[str] = []
    if len(headings) != 1:
        errors.append("delivery_h1_count_invalid")
    elif headings[0] != expected_title.strip():
        errors.append("delivery_title_mismatch")
    body_lines = [
        line for line in markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if line.strip() and not _H1_LINE_RE.match(line)
    ]
    if not body_lines:
        errors.append("delivery_body_missing")
    return errors


def _replace_balanced_bracket_dest(text: str, *, image: bool) -> str:
    """Replace ``[label](dest)`` / ``![alt](dest)`` with label/alt using balanced parens."""
    prefix = "![" if image else "["
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        start = text.find(prefix, i)
        if start < 0:
            out.append(text[i:])
            break
        out.append(text[i:start])
        label_start = start + len(prefix)
        label_end = text.find("]", label_start)
        if label_end < 0 or label_end + 1 >= n or text[label_end + 1] != "(":
            out.append(text[start : start + len(prefix)])
            i = start + len(prefix)
            continue
        dest_start = label_end + 2
        depth = 1
        j = dest_start
        while j < n and depth:
            ch = text[j]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            j += 1
        if depth != 0:
            # Unbalanced destination: keep raw from here and stop rewriting this form.
            out.append(text[start:])
            break
        label = text[label_start:label_end]
        out.append(label)
        i = j
    return "".join(out)


def _strip_links_and_images(line: str) -> str:
    """Convert supported link/image forms to visible labels; drop reference definitions."""
    if _REF_DEFINITION_RE.match(line):
        return ""
    line = _replace_balanced_bracket_dest(line, image=True)
    line = _replace_balanced_bracket_dest(line, image=False)
    line = _REF_LINK_RE.sub(r"\1", line)
    return line


def render_plain_text(markdown: str) -> str:
    """Derive plain text from markdown: strip markers, keep blank-line paragraphs."""
    if not isinstance(markdown, str):
        raise TypeError("markdown_must_be_a_str")

    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    lines_out: list[str] = []
    in_fence = False
    for raw_line in text.split("\n"):
        line = raw_line
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            lines_out.append(line.rstrip())
            continue
        line = _HEADING_RE.sub("", line)
        line = _strip_links_and_images(line)
        # Repeat bold/italic stripping to handle nested simple forms.
        for _ in range(3):
            updated = _BOLD_ITALIC_RE.sub(r"\2", line)
            if updated == line:
                break
            line = updated
        line = _INLINE_CODE_RE.sub(r"\1", line)
        line = line.replace("**", "").replace("__", "")
        lines_out.append(line.rstrip())

    # Collapse runs of blank lines to a single blank line; trim file edges.
    collapsed: list[str] = []
    blank_pending = False
    for line in lines_out:
        if not line.strip():
            blank_pending = True
            continue
        if blank_pending and collapsed:
            collapsed.append("")
        blank_pending = False
        collapsed.append(line)
    return ("\n".join(collapsed) + "\n") if collapsed else ""

def write_plain_from_markdown(
    markdown_path: Path,
    plain_path: Path,
    *,
    run_dir: Path | None = None,
    force: bool = False,
) -> str:
    """Render markdown file to plain path; return derived plain text.

    ``run_dir`` 给出时走留底通道（留底 + 记账 + 封存守门）——交付纯文本副本也是证据。
    """
    if not isinstance(markdown_path, Path) or not isinstance(plain_path, Path):
        raise TypeError("paths_must_be_path_objects")
    markdown = markdown_path.read_text(encoding="utf-8")
    plain = render_plain_text(markdown)
    if run_dir is not None:
        from article_group.evidence_write import write_evidence

        write_evidence(
            plain_path, plain, run_dir=run_dir,
            reason="delivery:plain_from_markdown", force=force,
        )
        return plain
    plain_path.parent.mkdir(parents=True, exist_ok=True)
    plain_path.write_text(plain, encoding="utf-8")
    return plain


def _path_is_file(path: object) -> bool:
    return isinstance(path, Path) and path.is_file()


def validate_plain_delivery(markdown_path: Path, plain_path: Path) -> list[str]:
    """Return fail-closed errors when plain is missing, drifted, or stale vs markdown."""
    errors: list[str] = []
    if not isinstance(markdown_path, Path) or not isinstance(plain_path, Path):
        return ["plain_paths_must_be_path_objects"]
    if not markdown_path.is_file():
        return ["markdown_missing"]
    if not plain_path.is_file():
        return ["plain_missing"]

    markdown = markdown_path.read_text(encoding="utf-8")
    actual = plain_path.read_text(encoding="utf-8")
    expected = render_plain_text(markdown)

    if actual != expected:
        errors.append("plain_content_mismatch")
    if _MARKDOWN_MARKER_RE.search(actual):
        errors.append("plain_retains_markdown_markers")

    try:
        md_mtime = markdown_path.stat().st_mtime
        plain_mtime = plain_path.stat().st_mtime
    except OSError:
        errors.append("plain_stat_unavailable")
        return errors

    # Markdown newer than plain without regen is stale even if content still matches.
    if md_mtime > plain_mtime:
        errors.append("plain_stale_markdown_newer")
    return errors


def validate_run_plain_delivery(run_dir: Path | Any) -> list[str]:
    """Validate A/B/C ``article-draft.md`` ↔ ``article-plain.txt`` pairs under a run dir."""
    if not isinstance(run_dir, Path) or not run_dir.is_dir():
        return ["run_dir_must_be_a_directory"]

    errors: list[str] = []
    for slot in ("A", "B", "C"):
        slot_dir = run_dir / "articles" / slot
        md = slot_dir / "article-draft.md"
        plain = slot_dir / "article-plain.txt"
        if not slot_dir.is_dir():
            errors.append(f"slot_{slot}:slot_dir_missing")
            continue
        slot_errors = validate_plain_delivery(md, plain)
        errors.extend(f"slot_{slot}:{err}" for err in slot_errors)
    return errors
