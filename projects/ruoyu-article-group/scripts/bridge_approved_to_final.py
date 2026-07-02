#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[3]
PROJECT_DIR = WORKSPACE / "projects" / "ruoyu-article-group"
FEEDBACK_DIR = WORKSPACE / "handover-hotspot" / "04-QUALITY-FEEDBACK"
OUTPUT_BASE = PROJECT_DIR / "ruoyu-output"
HTML_RENDER = WORKSPACE / "scripts" / "ruoyu_md_to_html.py"


@dataclass
class ApprovedCandidate:
    source: str
    title: str
    score: int
    bucket: str
    reason: str
    serial: int
    angle: str | None = None


def parse_candidates(text: str) -> list[ApprovedCandidate]:
    candidates: list[ApprovedCandidate] = []
    current_bucket = "unknown"
    current_reason = ""
    current_angle = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            current_bucket = line[3:].strip()
            continue
        if line.startswith("- 推荐角度："):
            current_angle = line.split("：", 1)[1].strip()
            continue
        m = re.match(r"-\s*\d+\.\s*\[(?P<source>[^\]]+)\]\s*(?P<title>.+?)｜.*?分池=(?P<bucket>[^｜]+)｜进池依据=(?P<reason>[^｜]+)", line)
        if not m:
            continue
        score_match = re.search(r"基础分(?P<score>\d+)", line)
        serial_match = re.match(r"-\s*(\d+)\.", line)
        candidates.append(
            ApprovedCandidate(
                source=m.group("source").strip(),
                title=m.group("title").strip(),
                score=int(score_match.group("score")) if score_match else 0,
                bucket=m.group("bucket").strip(),
                reason=m.group("reason").strip(),
                serial=int(serial_match.group(1)) if serial_match else len(candidates) + 1,
                angle=current_angle,
            )
        )
        current_angle = None
    return candidates


def slugify(title: str) -> str:
    safe = re.sub(r"[\\/:*?\"<>|]", "-", title)
    safe = re.sub(r"\s+", "", safe)
    return safe[:64].strip("-") or "untitled"


def build_publish_title(candidate: ApprovedCandidate) -> str:
    title = candidate.title.strip()
    if "吴启华" in title and "AI电影" in title:
        return "吴启华卖20岁肖像权！AI电影先把演员推上赌桌"
    if "功夫女足" in title:
        return "周星驰《功夫女足》还没上映，观众为什么先唱衰"
    if "泰山景区" in title and "刀片刺绳" in title:
        return "泰山135公里刀片刺绳！争议为什么压不住"
    if "婚内单身" in title:
        return "婚内单身火了！36岁的人为什么不急着离婚"
    if any(token in title for token in ["《", "》", "为什么", "最", "冷场", "票房", "离世", "去世", "观众"]):
        return title
    if "婚姻" in title:
        return f"{title}，最该聊的不是道理，而是人为什么撑不下去"
    return title


def build_markdown(candidate: ApprovedCandidate, date_str: str) -> str:
    title = build_publish_title(candidate)
    alt_1 = title
    alt_2 = candidate.title
    alt_3 = f"{title}，争议背后谁最被动？"
    direction = candidate.angle or "结构性角度"
    return f"""# {title}

> bridge_generated｜来源：[本地镜像] {date_str} approved 草案。此稿为桥接成稿，用于验证 approved -> final -> HTML 贯通；进入正式发布前仍需人工补证据与改写。

## 备选标题

1. {alt_1}
2. {alt_2}
3. {alt_3}

## 正文

今天这条候选来自 {candidate.source}，当前分池为「{candidate.bucket}」，候选分数 {candidate.score}。

它之所以被保留，不是因为信息量已经完美，而是因为它至少提供了一个可以展开的切口：{candidate.reason}。

如果把它放进若雨随影文章组的工作流里，当前最有价值的是沿着「{direction}」往下深挖：这件事为什么会在今天成立，它击中了观众的哪一种判断差，它背后到底是人物、作品、平台，还是更深一层的行业变化。

从桥接验证的角度看，这篇稿子故意保持克制：不补未核验事实，不冒充独家信息，也不把候选草案直接包装成已经完全成熟的主稿。

但它至少证明一件事：只要 approved 草案里已经出现了可写标题、分池信息和进池依据，就可以被桥接成一篇结构完整、可继续编辑、可继续转 HTML 的成稿。

真正影响它能不能进入正式主稿池的，下一步反而不是文件写不出来，而是证据是否足够、角度是否够狠、锚点是否够具体。

如果后续要继续升级，这篇稿子最需要补的不是字数，而是三样东西：第一，明确的作品/人物/平台锚点；第二，今天为什么写它的触发理由；第三，足够支撑观点的评论区或二跳正文证据。

所以这份 final 不是终局，而是桥接层的产出验证：证明 approved 不必永远停留在草案，它可以被安全地落到 final，再由人工继续拔高。

## 核查摘要

- 主平台：微信公众号 / 今日头条双平台
- 最终标题：{title}
- 标题池/备选标题：{alt_1}｜{alt_2}｜{alt_3}
- 二审问题/结论：已从 approved 白名单桥接到 final；复核结论为可进入人工补证据编辑，不直接发布。
- 风险素材：未自动补二跳正文、评论原文和平台数据，禁止当正式事实稿外发。
- 来源：`handover-hotspot/04-QUALITY-FEEDBACK/article-approved-latest.md`
- approved 原题：{candidate.title}
- 今日热度证据：来自 {date_str} approved 草案分池、分数与进池依据；仍需补原平台排名、评论区高赞和二跳正文。
- 评论/舆论信号：当前仅使用 approved 草案的“信号/进池依据”摘要，正式稿必须补评论原文或可核验讨论样本。
- bridge 输入：标题 / 分池 / 分数 / 进池依据 / 推荐角度（如有）
- 当前限制：未自动补二跳正文、未自动补评论证据、未自动补 reference library。
- 用途：验证 `article-approved-latest -> ruoyu-output/final/YYYY-MM-DD/` 桥接可执行。
"""


def render_html_fallback(md_path: Path) -> Path:
    """Render a minimal standalone HTML file when the workspace renderer is absent."""
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    body: list[str] = []
    in_list = False

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            if in_list:
                body.append("</ul>")
                in_list = False
            continue
        if line.startswith("# "):
            if in_list:
                body.append("</ul>")
                in_list = False
            body.append(f"<h1>{html.escape(line[2:].strip())}</h1>")
        elif line.startswith("## "):
            if in_list:
                body.append("</ul>")
                in_list = False
            body.append(f"<h2>{html.escape(line[3:].strip())}</h2>")
        elif line.startswith("- "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{html.escape(line[2:].strip())}</li>")
        elif re.match(r"^\d+\.\s+", line):
            if not in_list:
                body.append("<ul>")
                in_list = True
            item = re.sub(r"^\d+\.\s+", "", line).strip()
            body.append(f"<li>{html.escape(item)}</li>")
        elif line.startswith(">"):
            if in_list:
                body.append("</ul>")
                in_list = False
            body.append(f"<blockquote>{html.escape(line.lstrip('>').strip())}</blockquote>")
        else:
            if in_list:
                body.append("</ul>")
                in_list = False
            body.append(f"<p>{html.escape(line)}</p>")

    if in_list:
        body.append("</ul>")

    html_path = md_path.with_suffix(".html")
    html_path.write_text(
        "<!doctype html>\n<html lang=\"zh-CN\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        f"<title>{html.escape(md_path.stem)}</title>\n"
        "<style>body{max-width:760px;margin:40px auto;padding:0 20px;line-height:1.75;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}blockquote{color:#555;border-left:4px solid #ddd;padding-left:1em;}li{margin:.35em 0;}</style>\n"
        "</head>\n<body>\n"
        + "\n".join(body)
        + "\n</body>\n</html>\n",
        encoding="utf-8",
    )
    return html_path


def render_html(md_path: Path) -> tuple[bool, str]:
    if HTML_RENDER.exists():
        html_cmd = [sys.executable, str(HTML_RENDER), str(md_path)]
        html_run = subprocess.run(html_cmd, capture_output=True, text=True)
        if html_run.returncode != 0:
            return False, f"HTML_RENDER_FAIL\n{html_run.stdout}\n{html_run.stderr}"
        return True, "HTML_RENDER_OK external"

    html_path = render_html_fallback(md_path)
    return True, f"HTML_RENDER_OK fallback={html_path}"


def main() -> int:
    parser = argparse.ArgumentParser(description="桥接：article-approved-latest -> ruoyu final")
    parser.add_argument("--date", required=True)
    parser.add_argument("--index", type=int, default=1, help="从 approved 里选择第几个候选（1-based）")
    parser.add_argument("--slot", type=int, default=None, help="输出文件序号，默认等于 --index")
    parser.add_argument("--allow-buckets", default="A池,B池,C池,今日钩子候选（可补写）", help="允许桥接的 bucket，逗号分隔")
    args = parser.parse_args()

    approved = FEEDBACK_DIR / "article-approved-latest.md"
    if not approved.exists():
        print("MISSING approved")
        return 2
    candidates = parse_candidates(approved.read_text(encoding="utf-8", errors="ignore"))
    allow = {x.strip() for x in args.allow_buckets.split(",") if x.strip()}
    filtered = [c for c in candidates if c.bucket in allow]
    if not filtered:
        print("NO_CANDIDATE")
        return 3
    idx = max(1, args.index) - 1
    if idx >= len(filtered):
        print("INDEX_OUT_OF_RANGE")
        return 4
    candidate = filtered[idx]

    final_dir = OUTPUT_BASE / "final" / args.date
    final_dir.mkdir(parents=True, exist_ok=True)
    slot = args.slot or args.index
    filename = f"{slot:02d}-{slugify(candidate.title)}.md"
    md_path = final_dir / filename
    md_path.write_text(build_markdown(candidate, args.date), encoding="utf-8")

    ok, html_message = render_html(md_path)
    if not ok:
        print(html_message)
        return 5

    print(f"BRIDGE_OK\nmd={md_path}\nhtml={md_path.with_suffix('.html')}\n{html_message}\ntitle={candidate.title}\nbucket={candidate.bucket}\nscore={candidate.score}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
