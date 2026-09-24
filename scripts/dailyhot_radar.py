#!/usr/bin/env python3
"""DailyHotApi 薄适配器：谈资型热帖信号 → 雷达快照 JSON。

部署：Linux 主机 docker 容器 imsyy/dailyhot-api（127.0.0.1:6688，内网只读），
见 docs/codex/talk-material-discovery-plan-2026-09.md 第 1 步。
用途边界：信号仅作 R0 选题发现，不作事实来源；每条可经 url 回溯原帖核验。
采集纪律：每日低频只读一次（cron），路由间加间隔，不并发。

用法：
    python3 scripts/dailyhot_radar.py --out runs/radar/dailyhot
    python3 scripts/dailyhot_radar.py --out /tmp/dh --routes douban-group,tieba
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.request
from pathlib import Path

DEFAULT_ROUTES = ("douban-group", "tieba", "hupu", "ngabbs", "zhihu", "toutiao", "bilibili", "douyin")

ROUTE_LABELS = {
    "douban-group": "豆瓣小组讨论精选",
    "tieba": "百度贴吧热议榜",
    "hupu": "虎扑步行街热帖",
    "ngabbs": "NGA热帖",
    "zhihu": "知乎热榜",
    "toutiao": "今日头条热榜",
    "bilibili": "B站热搜",
    "douyin": "抖音热搜",
}


def fetch(api: str, route: str, timeout: int) -> tuple[str | None, list[dict]]:
    url = f"{api.rstrip('/')}/{route}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — 适配器必须容忍单路由失败并如实记录
        return f"{type(exc).__name__}: {exc}", []
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        keys = list(payload)[:5] if isinstance(payload, dict) else type(payload).__name__
        return f"unexpected_payload:{keys}", []
    return None, items


def normalize(route: str, item: dict, rank: int, captured_at: str) -> dict:
    return {
        "rank": rank,
        "source": route,
        "source_label": ROUTE_LABELS.get(route, route),
        "id": str(item.get("id", "")),
        "title": str(item.get("title", "")),
        "desc": str(item.get("desc", "")),
        "hot": item.get("hot"),
        "url": item.get("url") or item.get("mobileUrl") or "",
        "mobile_url": item.get("mobileUrl", ""),
        "timestamp": item.get("timestamp"),
        "captured_at": captured_at,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:6688")
    parser.add_argument("--out", required=True)
    parser.add_argument("--routes", default=",".join(DEFAULT_ROUTES))
    parser.add_argument("--date", help="快照日期（默认今天）")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    routes = [r.strip() for r in args.routes.split(",") if r.strip()]
    captured_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    date = args.date or dt.date.today().isoformat()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    boards: list[dict] = []
    for route in routes:
        error, items = fetch(args.api, route, args.timeout)
        if error:
            boards.append(
                {"route": route, "label": ROUTE_LABELS.get(route, route), "error": error, "items": []}
            )
            print(f"[dailyhot-radar] {route}: FAIL {error}", file=sys.stderr)
            continue
        entries = [normalize(route, item, i + 1, captured_at) for i, item in enumerate(items)]
        boards.append({"route": route, "label": ROUTE_LABELS.get(route, route), "items": entries})
        print(f"[dailyhot-radar] {route}: {len(entries)} items")
        time.sleep(2)  # 低频只读：路由间间隔，不连发

    snapshot = {
        "schema_version": "dailyhot-radar-v1",
        "captured_at": captured_at,
        "date": date,
        "api": args.api,
        "routes_requested": routes,
        "boards": boards,
        "note": "信号仅作 R0 选题发现，不作事实来源；条目可经 url 回溯原帖核验。",
    }
    target = out_dir / f"{date}.json"
    target.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    total = sum(len(b["items"]) for b in boards)
    failed = sum(1 for b in boards if b.get("error"))
    print(f"[dailyhot-radar] snapshot: {target} boards={len(boards)} items={total} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
