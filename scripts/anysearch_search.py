#!/usr/bin/env python3
"""AnySearch 轻量客户端（选题调研用，不进证据链）。

密钥：~/.config/anysearch/env（ANYSEARCH_API_KEY=as_sk_...，600 权限，不入仓库），
或环境变量 ANYSEARCH_API_KEY。
用法：
    python3 scripts/anysearch_search.py search "查询" --max 5
    python3 scripts/anysearch_search.py extract URL --out /tmp/page.md

边界（不可逾越）：
- search 结果与 extract 输出只用于找角度、找候选来源页面；
- 任何事实仍须回原始页面抓取入 sources/ 并走 claim↔账本锚定；
- extract 的 Markdown 不得替代 sources/ 下的 HTML 捕获物。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

API = "https://api.anysearch.com"
ENV_FILE = Path.home() / ".config" / "anysearch" / "env"

# 额度/限流类错误关键词：命中即按"降级"处理，不重试（重试只会烧额度）。
QUOTA_MARKERS = ("rate limit", "quota", "额度", "次数", "limit exceeded", "too many")


class QuotaError(RuntimeError):
    """额度耗尽/限流：调用方应降级到 web_search/web_fetch，而非重试。"""


def load_key() -> str:
    key = os.environ.get("ANYSEARCH_API_KEY", "")
    if key:
        return key
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("ANYSEARCH_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("未找到 ANYSEARCH_API_KEY（~/.config/anysearch/env 或环境变量）")


def call(path: str, payload: dict | None, key: str, timeout: int = 60) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if body.get("code") != 0:
        message = str(body.get("message") or "")
        if any(marker in message.lower() for marker in QUOTA_MARKERS):
            raise QuotaError(message)
        raise SystemExit(f"AnySearch error: code={body.get('code')} message={body.get('message')}")
    return body


def cmd_search(args: argparse.Namespace, key: str) -> int:
    body = call(
        "/v1/search",
        {
            "query": args.query,
            "max_results": args.max,
            **({"language": args.language} if args.language else {}),
            **({"zone": args.zone} if args.zone else {}),
        },
        key,
    )
    results = body.get("data", {}).get("results", [])
    print(f"query: {args.query}（{len(results)} 条）\n")
    for i, r in enumerate(results, 1):
        print(f"{i}. {r.get('title', '')}")
        print(f"   {r.get('url', '')}")
        snippet = (r.get("snippet") or "").strip()
        if snippet:
            print(f"   {snippet[:160]}")
        print()
    if args.out:
        Path(args.out).write_text(
            json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"原始响应已落盘: {args.out}")
    return 0


def cmd_extract(args: argparse.Namespace, key: str) -> int:
    body = call("/v1/extract", {"url": args.url}, key, timeout=90)
    content = body.get("data", {}).get("content", "")
    if not content:
        raise SystemExit("extract 返回空内容")
    target = Path(args.out) if args.out else None
    if target:
        target.write_text(content, encoding="utf-8")
        print(f"已落盘: {target}（{len(content)} 字符）")
    else:
        print(content)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_search = sub.add_parser("search", help="单查询搜索（结果仅作调研参考）")
    p_search.add_argument("query")
    p_search.add_argument("--max", type=int, default=5)
    p_search.add_argument("--language", default="zh-CN")
    p_search.add_argument("--zone", choices=("cn", "intl"))
    p_search.add_argument("--out")
    p_search.set_defaults(func=cmd_search)

    p_extract = sub.add_parser("extract", help="整页提取为 Markdown（不进证据链）")
    p_extract.add_argument("url")
    p_extract.add_argument("--out")
    p_extract.set_defaults(func=cmd_extract)

    args = parser.parse_args()
    try:
        return args.func(args, load_key())
    except QuotaError as exc:
        print(
            f"[anysearch] 额度/限流：{exc}。不重试——本次调研降级改用 web_search/web_fetch。",
            file=sys.stderr,
        )
        return 3  # 退出码 3 = 额度耗尽，与一般错误(1)区分，便于调用方识别降级


if __name__ == "__main__":
    raise SystemExit(main())
