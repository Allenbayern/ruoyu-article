"""wechat_local_converter: Pure-Python Markdown to WeChat Official Account HTML converter.

Zero-dependency, zero-Docker, zero-Node implementation of Markdown to WeChat HTML.
Applies inline styles directly so that content pastes into the WeChat MP editor
without losing layout, fonts, colors, or quotes.

Features:
- Built-in cinematic & editorial themes (ruoyu-cinema, refined-blue, warm-amber, minimal-mono).
- Inline highlights & emphasis tags (==yellow==, ++blue++, %%pink%%, &&green&&, !!red!!, @@blue@@, ^^orange^^).
- Safe HTML escaping and dangerous protocol prevention (javascript:/data:).
- Single-page copy-ready preview generation.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any

# ==============================================================================
# Theme Definitions
# ==============================================================================

THEMES: dict[str, dict[str, Any]] = {
    "ruoyu-cinema": {
        "name": "若雨影视（暗青与金棕）",
        "styles": {
            "body": "font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif; font-size: 16px; color: #1e293b; line-height: 1.8; letter-spacing: 0.5px; padding: 12px 0;",
            "h1": "font-size: 22px; font-weight: 800; color: #0f172a; text-align: left; margin: 32px 0 20px; padding: 0 0 12px 0; border-bottom: 2px solid #0f172a; letter-spacing: 0.5px; line-height: 1.4;",
            "h2": "font-size: 18px; font-weight: 700; color: #0f172a; margin: 36px 0 16px; padding: 8px 0 8px 14px; border-left: 4px solid #b45309; background: linear-gradient(90deg, #fef3c7 0%, #ffffff 80%); border-radius: 0 6px 6px 0; line-height: 1.5; letter-spacing: 0.4px;",
            "h3": "font-size: 16px; font-weight: 700; color: #334155; margin: 26px 0 12px; padding: 0 0 6px 0; border-bottom: 1px dashed #cbd5e1; letter-spacing: 0.3px;",
            "p": "margin: 14px 0; text-align: justify; color: #1e293b; line-height: 1.85;",
            "blockquote": "margin: 22px 0; padding: 16px 20px; background: #f8fafc; border-left: 3px solid #b45309; color: #475569; font-size: 15px; border-radius: 0 8px 8px 0; line-height: 1.8;",
            "img": "max-width: 100%; height: auto; border-radius: 8px; margin: 20px auto; display: block; box-shadow: 0 4px 16px rgba(15,23,42,0.08);",
            "strong": "color: #0f172a; font-weight: 700; background: linear-gradient(180deg, transparent 65%, #fde68a 65%, #fde68a 95%, transparent 95%); padding: 0 2px;",
            "em": "font-style: italic; color: #64748b;",
            "code_inline": "background: #f1f5f9; color: #b45309; padding: 2px 6px; border-radius: 4px; font-size: 13.5px; font-family: Menlo, Consolas, Monaco, monospace; border: 1px solid #e2e8f0;",
            "code_block": "background: #0f172a; color: #f8fafc; padding: 18px 20px; border-radius: 8px; font-size: 13.5px; line-height: 1.7; font-family: Menlo, Consolas, Monaco, monospace; overflow-x: auto; white-space: pre-wrap; margin: 22px 0;",
            "ul": "margin: 16px 0; padding-left: 6px; list-style-type: none;",
            "ol": "margin: 16px 0 16px 6px; padding-left: 24px; list-style-type: decimal; color: #b45309; font-weight: 700;",
            "li": "margin: 8px 0; line-height: 1.8; color: #1e293b; font-weight: 400;",
            "hr": "border: none; height: 1px; background: linear-gradient(to right, transparent, #cbd5e1, transparent); margin: 34px 0;",
            "a": "color: #b45309; text-decoration: none; border-bottom: 1px solid rgba(180,83,9,0.4); padding-bottom: 1px;",
            "table": "width: 100%; border-collapse: collapse; margin: 22px 0; font-size: 14.5px; border-radius: 6px; overflow: hidden; border: 1px solid #e2e8f0;",
            "th": "background: #0f172a; color: #ffffff; padding: 11px 14px; text-align: left; font-weight: 600;",
            "td": "padding: 10px 14px; border-bottom: 1px solid #f1f5f9; color: #1e293b;",
            "caption": "font-size: 13px; color: #64748b; text-align: center; margin-top: 8px; font-style: italic;",
            "section_divider": "text-align: center; color: #cbd5e1; letter-spacing: 12px; font-size: 12px; margin: 36px 0 30px; user-select: none;",
        },
        "highlights": {
            "hl_yellow": "background: linear-gradient(180deg, transparent 55%, #fde68a 55%); color: #1e293b; padding: 0 3px; font-weight: 600;",
            "hl_blue": "background: #e0f2fe; color: #0369a1; padding: 1px 5px; border-radius: 3px; font-weight: 500;",
            "hl_pink": "background: #ffe4e6; color: #be123c; padding: 1px 5px; border-radius: 3px; font-weight: 500;",
            "hl_green": "background: #dcfce7; color: #15803d; padding: 1px 5px; border-radius: 3px; font-weight: 500;",
            "em_red": "color: #b91c1c; font-weight: 700;",
            "em_blue": "color: #0369a1; font-weight: 700;",
            "em_orange": "color: #c2410c; font-weight: 700;",
        },
        "divider_text": "◆ ◆ ◆",
    },
    "refined-blue": {
        "name": "商务精致蓝",
        "styles": {
            "body": "font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif; font-size: 15.5px; color: #242832; line-height: 1.75; letter-spacing: 0.4px; padding: 12px 0;",
            "h1": "font-size: 22px; font-weight: 800; color: #0b1530; text-align: left; margin: 32px 0 20px; padding: 0 0 12px 0; border-bottom: 2px solid #0b1530; letter-spacing: 0.5px; line-height: 1.4;",
            "h2": "font-size: 18px; font-weight: 700; color: #0b1530; margin: 36px 0 16px; padding: 10px 0 10px 14px; border-left: 4px solid #2e5bff; background: linear-gradient(90deg, #eef2ff 0%, #ffffff 70%); border-radius: 0 6px 6px 0; line-height: 1.5; letter-spacing: 0.3px;",
            "h3": "font-size: 16px; font-weight: 700; color: #1a2240; margin: 26px 0 12px; padding: 0 0 6px 0; border-bottom: 1px dashed #c7d2fe; letter-spacing: 0.3px;",
            "p": "margin: 14px 0; text-align: justify; color: #242832; line-height: 1.85;",
            "blockquote": "margin: 22px 0; padding: 18px 22px; background: #f4f6fc; border-left: 3px solid #2e5bff; color: #3a4463; font-size: 14.5px; border-radius: 0 10px 10px 0; line-height: 1.85;",
            "img": "max-width: 100%; height: auto; border-radius: 8px; margin: 22px auto; display: block; box-shadow: 0 6px 20px rgba(11,21,48,0.08);",
            "strong": "color: #0b1530; font-weight: 800; background: linear-gradient(180deg, transparent 62%, #fff18a 62%, #fff18a 95%, transparent 95%); padding: 0 2px;",
            "em": "font-style: italic; color: #5a6577;",
            "code_inline": "background: #eef2ff; color: #2e3a8a; padding: 2px 8px; border-radius: 4px; font-size: 13px; font-family: monospace; border: 1px solid #dbe4ff;",
            "code_block": "background: #0f1729; color: #e1e7ff; padding: 20px 22px; border-radius: 10px; font-size: 13px; line-height: 1.7; font-family: monospace; overflow-x: auto; white-space: pre-wrap; margin: 22px 0;",
            "ul": "margin: 16px 0; padding-left: 4px; list-style-type: none;",
            "ol": "margin: 18px 0 18px 8px; padding-left: 28px; list-style-type: decimal; color: #2e5bff; font-weight: 700;",
            "li": "margin: 10px 0; line-height: 1.8; color: #242832; font-weight: 400;",
            "hr": "border: none; height: 1px; background: linear-gradient(to right, transparent, #c7d2fe, transparent); margin: 36px 0;",
            "a": "color: #2e5bff; text-decoration: none; border-bottom: 1px solid rgba(46,91,255,0.35); padding-bottom: 1px;",
            "table": "width: 100%; border-collapse: collapse; margin: 22px 0; font-size: 14px; border-radius: 8px; overflow: hidden; border: 1px solid #e8ecf7;",
            "th": "background: #0b1530; color: #ffffff; padding: 12px 14px; text-align: left; font-weight: 600;",
            "td": "padding: 11px 14px; border-bottom: 1px solid #eef2ff; color: #242832;",
            "caption": "font-size: 12.5px; color: #8a93a8; text-align: center; margin-top: 10px; font-style: italic;",
            "section_divider": "text-align: center; color: #c7d2fe; letter-spacing: 14px; font-size: 11px; margin: 36px 0 30px; user-select: none;",
        },
        "highlights": {
            "hl_yellow": "background: linear-gradient(180deg, transparent 55%, #fff18a 55%); color: #242832; padding: 0 3px; font-weight: 600;",
            "hl_blue": "background: #dbe4ff; color: #1e2a8a; padding: 1px 5px; border-radius: 3px; font-weight: 500;",
            "hl_pink": "background: #ffe0ec; color: #a6115a; padding: 1px 5px; border-radius: 3px; font-weight: 500;",
            "hl_green": "background: #d7f5e2; color: #167a44; padding: 1px 5px; border-radius: 3px; font-weight: 500;",
            "em_red": "color: #c43a30; font-weight: 700;",
            "em_blue": "color: #2e5bff; font-weight: 700;",
            "em_orange": "color: #ea7c1c; font-weight: 700;",
        },
        "divider_text": "● ● ●",
    },
    "minimal-mono": {
        "name": "极简黑白灰",
        "styles": {
            "body": "font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif; font-size: 15.5px; color: #1f2937; line-height: 1.8; letter-spacing: 0.3px; padding: 12px 0;",
            "h1": "font-size: 21px; font-weight: 700; color: #111827; text-align: left; margin: 30px 0 18px; padding: 0 0 10px 0; border-bottom: 1px solid #111827;",
            "h2": "font-size: 17.5px; font-weight: 700; color: #111827; margin: 32px 0 14px; padding: 4px 0 4px 10px; border-left: 3px solid #111827;",
            "h3": "font-size: 16px; font-weight: 600; color: #374151; margin: 24px 0 10px;",
            "p": "margin: 14px 0; text-align: justify; color: #1f2937; line-height: 1.8;",
            "blockquote": "margin: 20px 0; padding: 14px 18px; background: #f9fafb; border-left: 3px solid #9ca3af; color: #4b5563; font-size: 14.5px;",
            "img": "max-width: 100%; height: auto; border-radius: 4px; margin: 20px auto; display: block;",
            "strong": "color: #111827; font-weight: 700;",
            "em": "font-style: italic; color: #6b7280;",
            "code_inline": "background: #f3f4f6; color: #111827; padding: 2px 6px; border-radius: 3px; font-size: 13px; font-family: monospace;",
            "code_block": "background: #111827; color: #f9fafb; padding: 16px 18px; border-radius: 6px; font-size: 13px; font-family: monospace; overflow-x: auto; white-space: pre-wrap; margin: 20px 0;",
            "ul": "margin: 14px 0; padding-left: 4px; list-style-type: none;",
            "ol": "margin: 14px 0 14px 6px; padding-left: 20px; list-style-type: decimal; color: #111827; font-weight: 700;",
            "li": "margin: 8px 0; line-height: 1.8; color: #1f2937; font-weight: 400;",
            "hr": "border: none; height: 1px; background: #e5e7eb; margin: 30px 0;",
            "a": "color: #111827; text-decoration: underline;",
            "table": "width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 14px; border: 1px solid #e5e7eb;",
            "th": "background: #f3f4f6; color: #111827; padding: 10px 12px; text-align: left; font-weight: 600; border-bottom: 1px solid #e5e7eb;",
            "td": "padding: 10px 12px; border-bottom: 1px solid #e5e7eb; color: #1f2937;",
            "caption": "font-size: 12.5px; color: #6b7280; text-align: center; margin-top: 8px;",
            "section_divider": "text-align: center; color: #9ca3af; letter-spacing: 10px; font-size: 11px; margin: 32px 0 26px; user-select: none;",
        },
        "highlights": {
            "hl_yellow": "background: #fef08a; color: #1f2937; padding: 0 3px;",
            "hl_blue": "background: #e5e7eb; color: #111827; padding: 1px 4px; border-radius: 2px;",
            "hl_pink": "background: #f3f4f6; color: #111827; padding: 1px 4px; border-radius: 2px;",
            "hl_green": "background: #e5e7eb; color: #111827; padding: 1px 4px; border-radius: 2px;",
            "em_red": "color: #111827; font-weight: 700; text-decoration: underline;",
            "em_blue": "color: #111827; font-weight: 700;",
            "em_orange": "color: #111827; font-weight: 700;",
        },
        "divider_text": "— — —",
    },
}

DEFAULT_THEME = "ruoyu-cinema"

INLINE_MARKS = [
    (r"==([^=\n]+)==", "hl_yellow"),
    (r"\+\+([^+\n]+)\+\+", "hl_blue"),
    (r"%%([^%\n]+)%%", "hl_pink"),
    (r"&&([^&\n]+)&&", "hl_green"),
    (r"!!([^!\n]+)!!", "em_red"),
    (r"@@([^@\n]+)@@", "em_blue"),
    (r"\^\^([^\^\n]+)\^\^", "em_orange"),
]


def list_available_themes() -> list[str]:
    """Return names of available built-in themes."""
    return sorted(THEMES.keys())


def load_theme(
    theme_name: str | None = None,
    style_path: str | Path | None = None,
) -> tuple[dict[str, str], dict[str, str], str]:
    """Load theme configuration (styles, highlights, divider_text)."""
    selected = theme_name if theme_name in THEMES else DEFAULT_THEME
    base = THEMES[selected]
    styles = dict(base["styles"])
    highlights = dict(base["highlights"])
    divider_text = base["divider_text"]

    if style_path:
        p = Path(style_path)
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                styles.update(data.get("styles", {}))
                highlights.update(data.get("highlights", {}))
                if data.get("divider_text"):
                    divider_text = data["divider_text"]
            except Exception:
                pass

    return styles, highlights, divider_text


# ==============================================================================
# Markdown to HTML Converter Core
# ==============================================================================

def convert_markdown_to_wechat_html(
    markdown_text: str,
    *,
    theme: str = DEFAULT_THEME,
    style_path: str | Path | None = None,
    drop_h1: bool = True,
) -> str:
    """Convert Markdown to inline-styled HTML compatible with WeChat Official Account.

    Args:
        markdown_text: The markdown text to convert.
        theme: Theme name (default: ruoyu-cinema).
        style_path: Path to custom JSON theme file.
        drop_h1: Whether to omit the first H1 title (as it duplicates the WeChat post title).
    """
    styles, highlights, divider_text = load_theme(theme, style_path)

    lines = markdown_text.splitlines()
    html_parts: list[str] = []

    in_code_block = False
    code_block_content: list[str] = []
    in_list = False
    list_type: str | None = None
    list_items: list[str] = []
    in_blockquote = False
    blockquote_lines: list[str] = []
    in_table = False
    table_rows: list[str] = []
    h1_seen = False
    prev_was_h2 = False

    def _flush_list() -> None:
        nonlocal in_list, list_items, list_type
        if in_list and list_items:
            tag = list_type or "ul"
            if tag == "ul":
                items_html = "\n".join(
                    f'<li style="{styles["li"]}"><span style="color: #b45309; margin-right: 6px;">●</span>{item}</li>'
                    for item in list_items
                )
            else:
                items_html = "\n".join(
                    f'<li style="{styles["li"]}">{item}</li>'
                    for item in list_items
                )
            html_parts.append(f'<{tag} style="{styles[tag]}">{items_html}</{tag}>')
            list_items = []
            in_list = False
            list_type = None

    def _flush_blockquote() -> None:
        nonlocal in_blockquote, blockquote_lines
        if in_blockquote and blockquote_lines:
            content = "<br>".join(blockquote_lines)
            html_parts.append(f'<blockquote style="{styles["blockquote"]}">{content}</blockquote>')
            blockquote_lines = []
            in_blockquote = False

    def _flush_table() -> None:
        nonlocal in_table, table_rows
        if in_table and table_rows:
            rows_html = []
            for i, row in enumerate(table_rows):
                cells = [c.strip() for c in row.split("|")[1:-1]]
                if i == 0:
                    cells_html = "".join(f'<th style="{styles["th"]}">{c}</th>' for c in cells)
                    rows_html.append(f"<tr>{cells_html}</tr>")
                elif all(set(c.strip()) <= {"-", ":"} for c in cells):
                    continue
                else:
                    cells_html = "".join(f'<td style="{styles["td"]}">{c}</td>' for c in cells)
                    rows_html.append(f"<tr>{cells_html}</tr>")
            html_parts.append(f'<table style="{styles["table"]}">{"".join(rows_html)}</table>')
            table_rows = []
            in_table = False

    def _escape_code(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    _DANGEROUS_URL = re.compile(r"^\s*(javascript|data|vbscript)\s*:", re.IGNORECASE)

    def _process_inline(text: str) -> str:
        # 1. Escape < and > to prevent raw script injections
        text = text.replace("<", "&lt;").replace(">", "&gt;")

        # 2. Image ![alt](src)
        def _img_sub(m: re.Match) -> str:
            alt = html.escape(m.group(1), quote=True)
            src = html.escape(m.group(2), quote=True)
            return f'<img src="{src}" alt="{alt}" style="{styles["img"]}"/>'

        text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _img_sub, text)

        # 3. Links [text](url) - guard dangerous protocols
        def _link_sub(m: re.Match) -> str:
            link_text = m.group(1)
            url = m.group(2).strip()
            if _DANGEROUS_URL.match(url):
                return link_text
            safe_url = html.escape(url, quote=True)
            return f'<a href="{safe_url}" style="{styles["a"]}">{link_text}</a>'

        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link_sub, text)

        # 4. Inline code `code`
        text = re.sub(
            r"`([^`]+)`",
            lambda m: f'<code style="{styles["code_inline"]}">{_escape_code(m.group(1))}</code>',
            text,
        )

        # 5. Extended highlights (==, ++, %%, &&, !!, @@, ^^)
        for pattern, key in INLINE_MARKS:
            st = highlights.get(key, "")
            if st:
                text = re.sub(
                    pattern,
                    lambda m, s=st: f'<span style="{s}">{m.group(1)}</span>',
                    text,
                )

        # 6. Bold **text**
        text = re.sub(
            r"\*\*([^*\n]+)\*\*",
            lambda m: f'<strong style="{styles["strong"]}">{m.group(1)}</strong>',
            text,
        )

        # 7. Italic *text*
        text = re.sub(
            r"(?<!\*)\*([^*\n]+)\*(?!\*)",
            lambda m: f'<em style="{styles["em"]}">{m.group(1)}</em>',
            text,
        )

        # 8. Clean up orphan ampersands
        text = re.sub(
            r"&(?!(?:[a-zA-Z][a-zA-Z0-9]{1,31}|#[0-9]{1,7}|#x[0-9a-fA-F]{1,6});)",
            "&amp;",
            text,
        )
        return text

    for line in lines:
        stripped = line.strip()

        # Code block
        if stripped.startswith("```"):
            if in_code_block:
                code_html = "\n".join(code_block_content)
                html_parts.append(f'<pre style="{styles["code_block"]}">{code_html}</pre>')
                code_block_content = []
                in_code_block = False
            else:
                _flush_list()
                _flush_blockquote()
                _flush_table()
                in_code_block = True
            prev_was_h2 = False
            continue

        if in_code_block:
            code_block_content.append(_escape_code(line))
            continue

        # Table
        if "|" in stripped and stripped.startswith("|"):
            _flush_list()
            _flush_blockquote()
            in_table = True
            table_rows.append(stripped)
            prev_was_h2 = False
            continue
        else:
            _flush_table()

        # Blockquote
        if stripped.startswith(">"):
            _flush_list()
            in_blockquote = True
            content = stripped.lstrip(">").strip()
            blockquote_lines.append(_process_inline(content))
            prev_was_h2 = False
            continue
        else:
            _flush_blockquote()

        # Section divider
        if re.match(r"^(={3,}|~{3,})$", stripped) or stripped == "[SEC]":
            _flush_list()
            html_parts.append(
                f'<p style="{styles.get("section_divider", "")}">{divider_text}</p>'
            )
            prev_was_h2 = False
            continue

        # Headings
        h_match = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if h_match:
            _flush_list()
            level = len(h_match.group(1))
            heading_text = _process_inline(h_match.group(2))
            tag = f"h{level}"
            if level == 1 and drop_h1 and not h1_seen:
                h1_seen = True
                prev_was_h2 = False
                continue
            if level == 2 and html_parts and not prev_was_h2:
                html_parts.append(
                    f'<p style="{styles.get("section_divider", "")}">{divider_text}</p>'
                )
            html_parts.append(f'<{tag} style="{styles[tag]}">{heading_text}</{tag}>')
            prev_was_h2 = (level == 2)
            continue

        # Horizontal rule
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            _flush_list()
            html_parts.append(f'<hr style="{styles["hr"]}"/>')
            prev_was_h2 = False
            continue

        # Unordered list
        ul_match = re.match(r"^[-*+]\s+(.+)$", stripped)
        if ul_match:
            if not in_list or list_type != "ul":
                _flush_list()
                in_list = True
                list_type = "ul"
            list_items.append(_process_inline(ul_match.group(1)))
            prev_was_h2 = False
            continue

        # Ordered list
        ol_match = re.match(r"^\d+\.\s+(.+)$", stripped)
        if ol_match:
            if not in_list or list_type != "ol":
                _flush_list()
                in_list = True
                list_type = "ol"
            list_items.append(_process_inline(ol_match.group(1)))
            prev_was_h2 = False
            continue

        _flush_list()

        if not stripped:
            continue

        # Standalone Image
        img_match = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", stripped)
        if img_match:
            alt_raw = img_match.group(1)
            src_raw = img_match.group(2)
            alt = html.escape(alt_raw, quote=True)
            src = html.escape(src_raw, quote=True)
            html_parts.append(
                f'<p style="text-align:center;margin:18px 0;"><img src="{src}" alt="{alt}" style="{styles["img"]}"/></p>'
            )
            if alt_raw:
                html_parts.append(f'<p style="{styles["caption"]}">{alt}</p>')
            prev_was_h2 = False
            continue

        # Regular paragraph
        text = _process_inline(stripped)
        html_parts.append(f'<p style="{styles["p"]}">{text}</p>')
        prev_was_h2 = False

    _flush_list()
    _flush_blockquote()
    _flush_table()

    if in_code_block and code_block_content:
        code_html = "\n".join(code_block_content)
        html_parts.append(f'<pre style="{styles["code_block"]}">{code_html}</pre>')

    body = "\n".join(html_parts)
    return f'<section style="{styles["body"]}">\n{body}\n</section>'


# ==============================================================================
# One-Click Copy Page Generator
# ==============================================================================

def build_copy_page(*, title: str, body_html: str, theme: str = DEFAULT_THEME) -> str:
    """Wrap rendered article HTML into a copy-to-clipboard web page."""
    escaped_title = html.escape(title)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escaped_title} - 微信公众号排版预览</title>
<style>
  body {{ margin: 0; background: #f4f4f2; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Noto Sans CJK SC", sans-serif; }}
  .bar {{ position: sticky; top: 0; z-index: 99; display: flex; gap: 0.8em; align-items: center; flex-wrap: wrap; padding: 0.8em 1.2em; background: #18181b; color: #fff; font-size: 14px; box-shadow: 0 2px 8px rgba(0,0,0,0.15); }}
  .bar b {{ font-weight: 600; font-size: 15px; color: #f4f4f5; }}
  .bar span {{ color: #a1a1aa; font-size: 13px; }}
  button {{ font: inherit; font-size: 14px; font-weight: 500; padding: 0.45em 1.2em; border-radius: 6px; border: 0; cursor: pointer; background: #07c160; color: #fff; transition: opacity 0.2s; }}
  button:hover {{ opacity: 0.9; }}
  button.ghost {{ background: #27272a; color: #e4e4e7; }}
  button.ghost:hover {{ background: #3f3f46; }}
  .sheet {{ max-width: 720px; margin: 2em auto 5em; background: #fff; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.06); padding: 2.5em 2em; }}
  .toast {{ position: fixed; left: 50%; bottom: 2.5em; transform: translateX(-50%); background: #18181b; color: #fff; padding: 0.7em 1.4em; border-radius: 20px; font-size: 14px; opacity: 0; transition: opacity 0.25s; pointer-events: none; z-index: 100; }}
  .toast.on {{ opacity: 0.95; }}
  @media (max-width: 600px) {{ .sheet {{ margin: 0; border-radius: 0; padding: 1.5em 1em; }} }}
</style>
<script>
function toast(msg) {{
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('on');
  setTimeout(() => t.classList.remove('on'), 1800);
}}
function copyArticle() {{
  const node = document.getElementById('wx-article');
  const range = document.createRange();
  range.selectNodeContents(node);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  let ok = false;
  try {{ ok = document.execCommand('copy'); }} catch(e) {{ ok = false; }}
  sel.removeAllRanges();
  if (ok) {{
    toast('✅ 已复制！直接到微信公众号后台粘贴即可');
  }} else if (navigator.clipboard && window.isSecureContext) {{
    const blob = new Blob([node.innerHTML], {{type: 'text/html'}});
    navigator.clipboard.write([new ClipboardItem({{'text/html': blob}})]).then(
      () => toast('✅ 已复制！直接到微信公众号后台粘贴即可'),
      () => toast('浏览器拦截了自动复制，请手动全选复制')
    );
  }} else {{
    toast('浏览器拦截了自动复制，请手动全选复制');
  }}
}}
function copySource() {{
  const node = document.getElementById('wx-article');
  const textarea = document.createElement('textarea');
  textarea.value = node.innerHTML;
  document.body.appendChild(textarea);
  textarea.select();
  let ok = false;
  try {{ ok = document.execCommand('copy'); }} catch(e) {{ ok = false; }}
  document.body.removeChild(textarea);
  if (ok) toast('已复制 HTML 源码');
  else toast('复制失败，请手动选择');
}}
</script>
</head>
<body>
<div class="bar">
  <b>{escaped_title}</b>
  <span>(主题: {theme})</span>
  <button onclick="copyArticle()">一键复制（粘贴到公众号）</button>
  <button class="ghost" onclick="copySource()">复制 HTML 源码</button>
</div>
<div class="sheet">
  <div id="wx-article">
{body_html}
  </div>
</div>
<div id="toast" class="toast"></div>
</body>
</html>
"""


# ==============================================================================
# CLI Entry Point
# ==============================================================================

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Markdown → 微信公众号 HTML 转换器（纯本地）")
    parser.add_argument("input", nargs="?", help="Markdown 文件路径")
    parser.add_argument("-o", "--output", help="输出 HTML 文件路径（默认 stdout）")
    parser.add_argument("--theme", default=DEFAULT_THEME, help=f"主题名: {', '.join(list_available_themes())}")
    parser.add_argument("--style", help="自定义样式 JSON 文件路径")
    parser.add_argument("--keep-h1", action="store_true", help="保留正文第一处 H1（默认丢弃以防与标题重复）")
    parser.add_argument("--copy-page", action="store_true", help="输出带一键复制按钮的完整 HTML 预览页")
    parser.add_argument("--title", default="文章预览", help="预览页标题")
    parser.add_argument("--list-themes", action="store_true", help="列出所有内置主题")

    args = parser.parse_args(argv)

    if args.list_themes:
        for t in list_available_themes():
            print(f"- {t}: {THEMES[t]['name']}")
        return 0

    if not args.input:
        parser.error("需要提供输入 Markdown 文件路径")

    in_path = Path(args.input)
    if not in_path.is_file():
        print(f"错误: 文件不存在 {in_path}", file=sys.stderr)
        return 2

    md_text = in_path.read_text(encoding="utf-8")
    converted_html = convert_markdown_to_wechat_html(
        md_text,
        theme=args.theme,
        style_path=args.style,
        drop_h1=not args.keep_h1,
    )

    if args.copy_page:
        result = build_copy_page(
            title=args.title or in_path.stem,
            body_html=converted_html,
            theme=args.theme,
        )
    else:
        result = converted_html

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(result, encoding="utf-8")
        print(f"转换完成: {out_path}")
    else:
        print(result)

    return 0


if __name__ == "__main__":
    sys.exit(main())
