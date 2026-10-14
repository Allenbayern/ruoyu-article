"""comparison_card: Render structured film/literature comparison cards to HTML and PNG.

Designed for Ruoyu Film Daily (若雨随影) editorial workflow:
Enables deterministic, zero-hallucination visual comparison cards for:
- "Novel vs Adaptation" (原著 vs 剧版魔改)
- "Remake vs Classic" (翻拍 vs 经典)
- "Real History vs Screen Fiction" (史实原型 vs 荧幕演义)

Features:
- Pure-Python HTML generator with self-contained CSS (no external fonts required).
- Multiple visual themes:
  - `cinema-film`: Deep film aesthetic (slate dark background, warm amber accent).
  - `editorial-paper`: Classic print editorial (warm paper background, graphite & crimson).
- Output sizes:
  - `xiaohongshu`: 1080 x 1440 (standard 3:4 vertical card)
  - `square`: 1080 x 1080 (1:1 feed card)
  - `story`: 1080 x 1920 (9:16 mobile card)
- Graceful Playwright rendering to PNG with safe fallback.
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
# Themes and Dimensions
# ==============================================================================

CARD_SIZES: dict[str, tuple[int, int]] = {
    "xiaohongshu": (1080, 1440),
    "square": (1080, 1080),
    "story": (1080, 1920),
}

THEME_STYLES: dict[str, dict[str, str]] = {
    "cinema-film": {
        "bg": "linear-gradient(145deg, #0f172a 0%, #1e293b 100%)",
        "container_bg": "#1e293b",
        "header_color": "#f8fafc",
        "subtitle_color": "#94a3b8",
        "badge_bg": "#b45309",
        "badge_color": "#fef3c7",
        "item_a_bg": "rgba(30, 58, 138, 0.4)",
        "item_a_color": "#60a5fa",
        "item_b_bg": "rgba(180, 83, 9, 0.4)",
        "item_b_color": "#fbbf24",
        "table_bg": "#141e33",
        "table_border": "#334155",
        "td_border": "#1e293b",
        "dim_name_color": "#cbd5e1",
        "val_color": "#e2e8f0",
        "winner_color": "#f59e0b",
        "footer_color": "#64748b",
        "watermark_color": "#475569",
    },
    "editorial-paper": {
        "bg": "linear-gradient(145deg, #f8f9fa 0%, #edf0f5 100%)",
        "container_bg": "#ffffff",
        "header_color": "#0f172a",
        "subtitle_color": "#64748b",
        "badge_bg": "#1e293b",
        "badge_color": "#ffffff",
        "item_a_bg": "#f1f5f9",
        "item_a_color": "#2563eb",
        "item_b_bg": "#fef2f2",
        "item_b_color": "#dc2626",
        "table_bg": "#ffffff",
        "table_border": "#e2e8f0",
        "td_border": "#f1f5f9",
        "dim_name_color": "#475569",
        "val_color": "#1e293b",
        "winner_color": "#b45309",
        "footer_color": "#94a3b8",
        "watermark_color": "#cbd5e1",
    },
}

DEFAULT_THEME = "cinema-film"
DEFAULT_SIZE = "xiaohongshu"


# ==============================================================================
# HTML Template Builder
# ==============================================================================

def generate_comparison_card_html(
    *,
    title: str,
    subtitle: str = "",
    badge: str = "深度对照",
    item_a: str,
    item_b: str,
    dimensions: list[dict[str, Any]],
    theme: str = DEFAULT_THEME,
    size: str = DEFAULT_SIZE,
    source_note: str = "数据整理：若雨随影",
    watermark: str = "若雨随影 · 影视档案",
) -> str:
    """Generate self-contained HTML for a structured comparison card.

    Args:
        title: Main title of the comparison (e.g. "原著小说 vs 电视剧版")
        subtitle: Subtitle context (e.g. "核心人设与关键冲突深度对照")
        badge: Top badge label (e.g. "改编对照" / "经典对决")
        item_a: Subject A label (e.g. "刘慈欣原著")
        item_b: Subject B label (e.g. "网飞剧集版")
        dimensions: List of dicts with:
                    - "name": dimension name (e.g. "汪淼角色设定")
                    - "val_a": value/description for subject A
                    - "val_b": value/description for subject B
                    - "winner": optional "A" | "B" | "neutral"
        theme: "cinema-film" or "editorial-paper"
        size: "xiaohongshu" | "square" | "story"
        source_note: Bottom source disclaimer
        watermark: Bottom branding mark
    """
    width, height = CARD_SIZES.get(size, CARD_SIZES[DEFAULT_SIZE])
    th = THEME_STYLES.get(theme, THEME_STYLES[DEFAULT_THEME])

    # Build Table Rows
    rows_html = []
    for d in dimensions:
        dim_name = html.escape(str(d.get("name", "")))
        val_a = html.escape(str(d.get("val_a", "")))
        val_b = html.escape(str(d.get("val_b", "")))
        winner = str(d.get("winner", "")).upper()

        cls_a = ' class="winner"' if winner == "A" else ""
        cls_b = ' class="winner"' if winner == "B" else ""

        rows_html.append(f"""
        <tr>
          <td class="dim-col">{dim_name}</td>
          <td{cls_a}>{val_a}</td>
          <td{cls_b}>{val_b}</td>
        </tr>""")

    tbody_content = "\n".join(rows_html)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)} - 对比卡片</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: #000;
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  }}
  .card-container {{
    width: {width}px;
    height: {height}px;
    background: {th['bg']};
    padding: 64px 60px;
    display: flex;
    flex-direction: column;
    position: relative;
    overflow: hidden;
  }}
  .card-header {{
    text-align: center;
    margin-bottom: 36px;
    flex-shrink: 0;
  }}
  .badge {{
    display: inline-block;
    background: {th['badge_bg']};
    color: {th['badge_color']};
    font-size: 20px;
    font-weight: 700;
    padding: 6px 24px;
    border-radius: 20px;
    margin-bottom: 18px;
    letter-spacing: 2px;
  }}
  .card-header h1 {{
    font-size: 46px;
    font-weight: 800;
    color: {th['header_color']};
    letter-spacing: 2px;
    line-height: 1.3;
  }}
  .card-header .vs {{
    color: {th['winner_color']};
    font-style: italic;
    margin: 0 14px;
  }}
  .card-header .subtitle {{
    font-size: 22px;
    color: {th['subtitle_color']};
    margin-top: 12px;
    letter-spacing: 1px;
  }}
  .table-box {{
    flex: 1;
    display: flex;
    flex-direction: column;
    background: {th['table_bg']};
    border-radius: 20px;
    overflow: hidden;
    border: 1px solid {th['table_border']};
    box-shadow: 0 10px 30px rgba(0,0,0,0.25);
  }}
  table.comp-table {{
    width: 100%;
    height: 100%;
    border-collapse: collapse;
    table-layout: fixed;
  }}
  table.comp-table thead th {{
    padding: 22px 18px;
    font-size: 24px;
    font-weight: 700;
    text-align: center;
    border-bottom: 2px solid {th['table_border']};
  }}
  table.comp-table thead th.dim-header {{
    width: 24%;
    color: {th['subtitle_color']};
    text-align: left;
    padding-left: 24px;
  }}
  table.comp-table thead th.col-a {{
    width: 38%;
    background: {th['item_a_bg']};
    color: {th['item_a_color']};
  }}
  table.comp-table thead th.col-b {{
    width: 38%;
    background: {th['item_b_bg']};
    color: {th['item_b_color']};
  }}
  table.comp-table tbody tr {{
    border-bottom: 1px solid {th['td_border']};
  }}
  table.comp-table tbody tr:last-child {{
    border-bottom: none;
  }}
  table.comp-table tbody td {{
    padding: 16px 20px;
    font-size: 20px;
    color: {th['val_color']};
    text-align: center;
    line-height: 1.5;
    word-break: break-word;
  }}
  table.comp-table tbody td.dim-col {{
    text-align: left;
    font-weight: 700;
    color: {th['dim_name_color']};
    padding-left: 24px;
  }}
  table.comp-table tbody td.winner {{
    font-weight: 700;
    color: {th['winner_color']};
  }}
  .card-footer {{
    margin-top: 28px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 18px;
    color: {th['footer_color']};
    flex-shrink: 0;
  }}
  .card-footer .source {{
    letter-spacing: 0.5px;
  }}
  .card-footer .watermark {{
    font-weight: 700;
    color: {th['watermark_color']};
    letter-spacing: 1px;
  }}
</style>
</head>
<body>
<div class="card-container">
  <div class="card-header">
    <div class="badge">{html.escape(badge)}</div>
    <h1>{html.escape(item_a)} <span class="vs">vs</span> {html.escape(item_b)}</h1>
    <div class="subtitle">{html.escape(subtitle or title)}</div>
  </div>

  <div class="table-box">
    <table class="comp-table">
      <thead>
        <tr>
          <th class="dim-header">对比维度</th>
          <th class="col-a">{html.escape(item_a)}</th>
          <th class="col-b">{html.escape(item_b)}</th>
        </tr>
      </thead>
      <tbody>
{tbody_content}
      </tbody>
    </table>
  </div>

  <div class="card-footer">
    <span class="source">{html.escape(source_note)}</span>
    <span class="watermark">{html.escape(watermark)}</span>
  </div>
</div>
</body>
</html>
"""


# ==============================================================================
# Markdown Table to Comparison JSON Parser
# ==============================================================================

def parse_markdown_comparison_table(md_table_text: str) -> list[dict[str, Any]]:
    """Parse a 3-column markdown table (| 维度 | A | B |) into dimensions list."""
    lines = [ln.strip() for ln in md_table_text.splitlines() if ln.strip()]
    dimensions: list[dict[str, Any]] = []
    data_lines = []

    for line in lines:
        if "|" in line:
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) >= 3:
                # Skip divider line
                if all(set(c) <= {"-", ":", " "} for c in cells):
                    continue
                data_lines.append(cells)

    if not data_lines:
        return dimensions

    # Skip header row if it contains '维度'
    start_idx = 1 if "维度" in data_lines[0][0] or "参数" in data_lines[0][0] else 0

    for row in data_lines[start_idx:]:
        dim_name = row[0]
        val_a = row[1]
        val_b = row[2]
        winner = "neutral"
        if "(胜)" in val_a or "✓" in val_a:
            winner = "A"
            val_a = val_a.replace("(胜)", "").replace("✓", "").strip()
        elif "(胜)" in val_b or "✓" in val_b:
            winner = "B"
            val_b = val_b.replace("(胜)", "").replace("✓", "").strip()

        dimensions.append({
            "name": dim_name,
            "val_a": val_a,
            "val_b": val_b,
            "winner": winner,
        })

    return dimensions


# ==============================================================================
# Playwright PNG Exporter
# ==============================================================================

def render_html_to_png(
    html_path: Path | str,
    output_png_path: Path | str,
    *,
    width: int = 1080,
    height: int = 1440,
    scale: int = 2,
    timeout_ms: int = 20000,
) -> bool:
    """Render an HTML file to PNG using Playwright chromium.

    Returns True on success, False if Playwright is unavailable or fails.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("未安装 playwright，跳过图片自动渲染。可运行 pip install playwright && playwright install chromium 安装。", file=sys.stderr)
        return False

    html_file = Path(html_path).resolve()
    out_file = Path(output_png_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page(
                viewport={"width": width, "height": height},
                device_scale_factor=scale,
            )
            page.goto(f"file://{html_file}", wait_until="load", timeout=timeout_ms)
            card = page.query_selector(".card-container")
            if card:
                card.screenshot(path=str(out_file))
            else:
                page.screenshot(path=str(out_file), full_page=True)
            browser.close()
        return True
    except Exception as exc:
        print(f"Playwright 截图渲染失败: {exc}", file=sys.stderr)
        return False


# ==============================================================================
# CLI Entry Point
# ==============================================================================

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="影视结构化对比卡渲染器（一图流）")
    parser.add_argument("--json-input", help="包含对比数据的 JSON 文件路径")
    parser.add_argument("--md-input", help="包含 Markdown 对比表格的文件路径")
    parser.add_argument("--output-html", "-o", required=True, help="输出 HTML 文件路径")
    parser.add_argument("--output-png", help="输出 PNG 图片路径（需要 playwright）")
    parser.add_argument("--title", default="影视深度对照", help="卡片主标题")
    parser.add_argument("--subtitle", default="", help="卡片副标题")
    parser.add_argument("--badge", default="深度对照", help="顶部标牌")
    parser.add_argument("--item-a", default="对象 A", help="对比主体 A")
    parser.add_argument("--item-b", default="对象 B", help="对比主体 B")
    parser.add_argument("--theme", choices=list(THEME_STYLES.keys()), default=DEFAULT_THEME, help="主题风格")
    parser.add_argument("--size", choices=list(CARD_SIZES.keys()), default=DEFAULT_SIZE, help="卡片尺寸预设")

    args = parser.parse_args(argv)

    dimensions: list[dict[str, Any]] = []

    if args.json_input:
        data = json.loads(Path(args.json_input).read_text(encoding="utf-8"))
        if isinstance(data, list):
            dimensions = data
        elif isinstance(data, dict):
            dimensions = data.get("dimensions", [])
            args.title = data.get("title", args.title)
            args.subtitle = data.get("subtitle", args.subtitle)
            args.item_a = data.get("item_a", args.item_a)
            args.item_b = data.get("item_b", args.item_b)
            args.badge = data.get("badge", args.badge)
    elif args.md_input:
        md_text = Path(args.md_input).read_text(encoding="utf-8")
        dimensions = parse_markdown_comparison_table(md_text)
    else:
        # Default mock demo dimensions
        dimensions = [
            {"name": "主角核心动机", "val_a": "对科学真理的执着追问", "val_b": "拯救家庭与保护同伴", "winner": "neutral"},
            {"name": "危机爆发源起", "val_a": "物理学基础理论的崩溃", "val_b": "倒计时视网膜幻象与谋杀", "winner": "neutral"},
            {"name": "群戏视角切入", "val_a": "冷峻硬核的科学家群像", "val_b": "跨国多元的年轻团队组局", "winner": "A"},
            {"name": "视听叙事风格", "val_a": "史诗宏大与哲学冷漠", "val_b": "美剧快节奏悬疑与强冲突", "winner": "B"},
        ]

    card_html = generate_comparison_card_html(
        title=args.title,
        subtitle=args.subtitle,
        badge=args.badge,
        item_a=args.item_a,
        item_b=args.item_b,
        dimensions=dimensions,
        theme=args.theme,
        size=args.size,
    )

    out_html = Path(args.output_html)
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(card_html, encoding="utf-8")
    print(f"✅ HTML 对比卡已生成: {out_html}")

    if args.output_png:
        w, h = CARD_SIZES.get(args.size, CARD_SIZES[DEFAULT_SIZE])
        ok = render_html_to_png(out_html, args.output_png, width=w, height=h)
        if ok:
            print(f"✅ PNG 对比卡已生成: {args.output_png}")
        else:
            print("⚠️ 未能生成 PNG，请直接使用 HTML 或在浏览器打开后保存。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
