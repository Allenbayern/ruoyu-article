#!/usr/bin/env python3
"""Collect platform signals and generate agent-ready article handover files.

This script is intentionally conservative:
- it can run with public URLs only;
- optional login cookies are read from environment variables;
- secret values are never written to generated Markdown outputs.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

QUALITY_REL = Path("handover-hotspot") / "04-QUALITY-FEEDBACK"
DEFAULT_CONFIG = Path("projects/ruoyu-article-group/config/platform-sources.example.json")


@dataclass
class SourceSignal:
    name: str
    platform: str
    mode: str
    url: str
    title: str
    summary: str
    cookie_env: str | None
    auth_state: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect platform signals for Ruoyu article group.")
    parser.add_argument("--workspace", default=".", help="Repository/workspace root. Default: current directory.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="JSON config describing platform sources.")
    parser.add_argument("--date", default=date.today().isoformat(), help="Run date, YYYY-MM-DD.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of source signals to keep.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and print summary without writing handover files.")
    return parser.parse_args(argv)


def load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Config root must be a JSON object.")
    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("Config must contain a non-empty sources list.")
    return data


def fetch_text(url: str, cookie_env: str | None = None, timeout: int = 20) -> tuple[str, str]:
    headers = {"User-Agent": "ruoyu-article-group/0.1 (+agent-ready-public-signal-collector)"}
    auth_state = "公开访问"
    if cookie_env:
        cookie_value = os.environ.get(cookie_env)
        if cookie_value:
            headers["Cookie"] = cookie_value
            auth_state = f"使用环境变量 {cookie_env} 提供登录态"
        else:
            auth_state = f"未提供 {cookie_env}，按公开访问尝试"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - user-configured sources
        raw = resp.read(512_000)
        charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace"), auth_state


def strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", text)
    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", text)
    title = clean_text(title_match.group(1)) if title_match else ""
    body = re.sub(r"(?is)<[^>]+>", " ", text)
    body = clean_text(body)
    if title and title not in body:
        return f"{title}\n{body}"
    return body


def clean_text(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def infer_title(text: str, fallback: str) -> str:
    lines = [line.strip(" #-｜|\t") for line in re.split(r"[\n。！？!?]", text) if line.strip()]
    for line in lines:
        if 6 <= len(line) <= 80:
            return line[:80]
    return fallback[:80]


def summarize(text: str, title: str) -> str:
    cleaned = clean_text(text.replace(title, " "))
    return cleaned[:160] if cleaned else "待 agent 结合平台上下文复核。"


def collect_signal(source: dict[str, Any]) -> SourceSignal:
    name = str(source.get("name") or source.get("platform") or "未命名来源")
    platform = str(source.get("platform") or "unknown")
    mode = str(source.get("mode") or "public_url")
    url = str(source.get("url") or "")
    cookie_env = source.get("cookie_env")
    cookie_env = str(cookie_env) if cookie_env else None
    if not url:
        raise ValueError(f"Source {name} missing url")
    if mode not in {"public_url", "optional_cookie"}:
        raise ValueError(f"Source {name} has unsupported mode: {mode}")
    text, auth_state = fetch_text(url, cookie_env=cookie_env)
    plain = strip_html(text)
    parsed = urlparse(url)
    fallback = f"{name} 平台信号 {parsed.netloc or parsed.path}"
    title = infer_title(plain, fallback)
    summary = summarize(plain, title)
    return SourceSignal(
        name=name,
        platform=platform,
        mode=mode,
        url=url,
        title=title,
        summary=summary,
        cookie_env=cookie_env,
        auth_state=auth_state,
    )


def render_directive(config: dict[str, Any], run_date: str, signals: list[SourceSignal]) -> str:
    platforms = config.get("publishing_platforms") or ["今日头条", "微信公众号"]
    platform_text = " / ".join(map(str, platforms))
    env_lines = []
    for sig in signals:
        if sig.cookie_env:
            env_lines.append(f"- {sig.platform}：可选环境变量 `{sig.cookie_env}`（只在本机设置，禁止写入仓库）")
    env_block = "\n".join(env_lines) if env_lines else "- 当前配置未声明登录态环境变量，按公开页面抓取。"
    return f"""# 文章组当日指令｜{run_date}

主平台：{platform_text}
内容领域：{config.get('topic_domain', '影视娱乐')}

## agent 执行目标

1. 先使用 `scripts/collect_platform_signals.py` 抓取平台公开信号或本机登录态信号。
2. 再运行 `scripts/validate_article_pipeline.py --date {run_date}` 验证四层状态。
3. 只允许从 `article-approved-latest.md` 的 approved 白名单桥接正式稿。

## 本项目抓取的平台信号

{render_source_bullets(signals)}

## 使用者需要填写的信息

- 必填：`config/platform-sources.local.json` 里的平台名称、URL、内容领域、目标发布平台。
- 可选：下列环境变量用于访问登录态页面；不填时按公开页面尝试：
{env_block}

## 安全要求

- 不要把 cookie、token、账号密码、手机号、邮箱、微信号写入 Markdown、JSON 样例或 Git 仓库。
- 真实登录态只能放在本机环境变量或未入库的 `.env` 中。
"""


def render_source_bullets(signals: list[SourceSignal]) -> str:
    return "\n".join(
        f"- {sig.name}（{sig.platform}）：{sig.auth_state}；URL：{sig.url}" for sig in signals
    )


def render_feedback(config: dict[str, Any], run_date: str, signals: list[SourceSignal]) -> str:
    lines = [
        f"# 平台采集反馈｜{run_date}",
        "",
        "## 文章组采集状态",
        "",
        f"- 状态：已采集 {len(signals)} 条平台信号",
        "- 来源：公开页面 / 本机可选登录态环境变量",
        "- 注意：本文件不包含 cookie/token/账号密码",
        "",
        "## 候选 / 评分",
        "",
    ]
    for idx, sig in enumerate(signals, start=1):
        score = score_signal(sig)
        lines.extend(
            [
                f"### {idx}. {sig.title}",
                "",
                f"- 来源平台：{sig.platform}",
                f"- 来源名称：{sig.name}",
                f"- 采集模式：{sig.auth_state}",
                f"- 母本分：{score}",
                f"- 摘要：{sig.summary}",
                f"- 原始链接：{sig.url}",
                "- 初判：待总监复评；影视娱乐相关性、时效、事实硬度需二次核查。",
                "",
            ]
        )
    lines.extend([
        "## 正式成稿状态",
        "",
        "- 正式成稿：尚未桥接；需从 `article-approved-latest.md` 选择 approved 候选后运行 `bridge_approved_to_final.py`。",
        "- final：未生成时不得声称已正式交付。",
        "",
    ])
    return "\n".join(lines).rstrip() + "\n"


def score_signal(sig: SourceSignal) -> int:
    score = 70
    hot_words = ["热搜", "争议", "回应", "票房", "口碑", "官宣", "定档", "演员", "综艺", "电影", "剧"]
    score += min(20, sum(4 for word in hot_words if word in sig.title or word in sig.summary))
    return min(score, 95)


def render_director_review(run_date: str, signals: list[SourceSignal]) -> str:
    lines = [f"# NAS 总监复评｜{run_date}", "", "## 复评说明", "", "以下复评由平台信号自动生成初稿，agent/人工总监必须核查事实后再拍板。", ""]
    for idx, sig in enumerate(signals, start=1):
        conclusion = "主稿" if idx == 1 else "备稿"
        lines.extend(
            [
                f"## 候选 {idx}｜{sig.title}",
                "",
                f"1. 题目：{sig.title}",
                "2. 发布时间：以原平台页面为准，需二次核查",
                f"3. 为什么今天值得写：来自 {sig.name} 的平台信号，具备讨论热度或选题母本价值。",
                "4. 最适合的写作角度：从观众争议、行业变化、角色/演员处境或平台情绪切入。",
                "5. 风险点：标题事实、人物关系、数据口径、平台传言均需核验；未核事实不得写成确定判断。",
                f"6. 结论：{conclusion}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_approved(run_date: str, signals: list[SourceSignal]) -> str:
    lines = [f"# 文章组 approved 白名单｜{run_date}", "", "## approved 白名单", ""]
    for idx, sig in enumerate(signals, start=1):
        if idx > 3:
            break
        pool = "主稿" if idx == 1 else "备稿"
        lines.extend(
            [
                f"### {idx}. {sig.title}",
                "",
                f"- 来源：{sig.name} / {sig.platform}",
                f"- 标题：{sig.title}",
                f"- 分池：{pool}",
                f"- 基础分：{score_signal(sig)}",
                f"- 进池依据：平台信号摘要为“{sig.summary[:80]}”，具备影视娱乐自媒体文章母本价值。",
                "- 推荐角度：围绕争议、反差、人物利益和观众情绪写，不写未核传言。",
                "- 核查要求：正式写作前必须核查发布时间、人物、作品、数据与原始来源。",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_workflow_spec(config: dict[str, Any]) -> str:
    platforms = " / ".join(map(str, config.get("publishing_platforms") or ["今日头条", "微信公众号"]))
    return f"""# WORKFLOW-RECAST-CONTENT-AND-VIDEO-2026-06-10

本文件由 `projects/ruoyu-article-group/scripts/collect_platform_signals.py` 在干净环境中自动生成，用于让 agent 下载仓库后能识别文章组最小工作流。

## 项目

- 项目名：{config.get('project', '若雨随影文章组')}
- 内容领域：{config.get('topic_domain', '影视娱乐')}
- 发布平台：{platforms}

## 四层状态

1. 采集：从配置的平台源抓取公开页面或本机可选登录态页面。
2. 候选/评分：把平台信号整理为文章组候选和母本分。
3. NAS 总监复评：按题目、发布时间、为什么今天值得写、角度、风险点、结论六字段复评。
4. 正式成稿：只允许从 approved 白名单桥接到 final；未桥接前状态为“尚未正式成稿”。

## 安全边界

- 仓库只保存平台源配置样例和生成后的非敏感 Markdown。
- 真实 cookie、token、session、账号密码只能放在本机环境变量或未入库 `.env`。
- 任何 agent 不得把真实登录态写入 Git、Markdown、JSON 样例或日志。
"""


def write_handover(workspace: Path, run_date: str, config: dict[str, Any], signals: list[SourceSignal]) -> None:
    quality_dir = workspace / QUALITY_REL
    quality_dir.mkdir(parents=True, exist_ok=True)
    spec_path = workspace / "handover-hotspot" / "WORKFLOW-RECAST-CONTENT-AND-VIDEO-2026-06-10.md"
    if not spec_path.exists() or spec_path.stat().st_size == 0:
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(render_workflow_spec(config), encoding="utf-8")
    outputs = {
        "directive-latest.md": render_directive(config, run_date, signals),
        "latest-feedback.md": render_feedback(config, run_date, signals),
        "director-review-latest.md": render_director_review(run_date, signals),
        "article-approved-latest.md": render_approved(run_date, signals),
    }
    for name, content in outputs.items():
        (quality_dir / name).write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    workspace = Path(args.workspace).resolve()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = workspace / config_path
    config = load_config(config_path)
    signals = [collect_signal(source) for source in config["sources"]]
    signals = signals[: max(1, args.limit)]
    if args.dry_run:
        print(f"collected={len(signals)}")
        for sig in signals:
            print(f"- {sig.platform}: {sig.title} ({sig.auth_state})")
        return 0
    write_handover(workspace, args.date, config, signals)
    print(f"wrote {len(signals)} signals to {workspace / QUALITY_REL}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - CLI should print clean error
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
