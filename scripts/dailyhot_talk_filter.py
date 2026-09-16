#!/usr/bin/env python3
"""谈资信号筛选演示版：影视向过滤 + 争议度粗分类（第 2 步原型）。

输入：scripts/dailyhot_radar.py 生成的快照 runs/radar/dailyhot/<date>.json。
输出：影视向条目清单（按争议度降序），可选 --out 落盘过滤结果。

方法说明（诚实边界）：
- 本脚本是纯关键词启发式原型，不是 LLM 分类层；接口设计成 classifier 可替换，
  后续接 LLM（或混用）时替换 score/dispute 两个函数即可；
- 信号仅作 R0 选题发现，不作事实来源；
- 争议度是"讨论烈度"的粗代理（用词烈度 + 问句密度），不代表事实性争议成立。

用法：
    python3 scripts/dailyhot_talk_filter.py
    python3 scripts/dailyhot_talk_filter.py --date 2026-09-16 --top 30
    python3 scripts/dailyhot_talk_filter.py --out /tmp/filtered.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SNAPSHOT_DIR = Path("runs/radar/dailyhot")

FILM_KEYWORDS = (
    "剧", "电影", "影院", "院线", "票房", "综艺", "番剧", "国漫", "动画",
    "导演", "编剧", "主演", "演员", "演技", "剧情", "角色", "女主", "男主",
    "女配", "男配", "原著", "改编", "上映", "开播", "播出", "收官", "大结局",
    "预告", "服化道", "台词", "评分", "影评", "追剧", "嗑", "CP", "官宣",
    "杀青", "开机", "番位", "流量", "顶流", "塌房", "明星", "艺人", "偶像",
    "爱豆", "娱乐", "内娱", "磕", "夫妇", "剧组",
)

DISPUTE_KEYWORDS = (
    "吵", "撕", "骂", "吐槽", "翻车", "塌房", "道歉", "回应", "举报",
    "拉踩", "站队", "对峙", "撕逼", "打脸", "争议", "不服", "离谱",
    "无语", "破防", "抵制", "路转黑", "粉转黑", "拉黑", "阴阳",
)

QUESTION_MARKERS = (
    "为什么", "凭什么", "该不该", "谁对谁错", "谁更", "是不是", "你怎么看",
)

# 内容禁区（Vault 边界：死亡/病逝/自杀类不进选题，信号层直接过滤）
EXCLUDE_KEYWORDS = (
    "去世", "逝世", "自杀", "死亡", "离世", "讣告", "病逝", "遇难",
    "绝症", "葬礼", "遗照",
)


def is_film_relevant(text: str) -> bool:
    return any(keyword in text for keyword in FILM_KEYWORDS)


def dispute_score(text: str) -> int:
    score = sum(1 for keyword in DISPUTE_KEYWORDS if keyword in text)
    if any(marker in text for marker in QUESTION_MARKERS):
        score += 1
    return score


def is_excluded(text: str) -> bool:
    return any(keyword in text for keyword in EXCLUDE_KEYWORDS)


def load_snapshot(date: str | None) -> tuple[Path, dict]:
    if date:
        path = SNAPSHOT_DIR / f"{date}.json"
        if not path.exists():
            raise SystemExit(f"快照不存在: {path}")
    else:
        candidates = sorted(SNAPSHOT_DIR.glob("*.json"))
        if not candidates:
            raise SystemExit(f"{SNAPSHOT_DIR} 下没有快照，先跑 scripts/dailyhot_radar.py")
        path = candidates[-1]
    return path, json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="快照日期（默认最新）")
    parser.add_argument("--top", type=int, default=30, help="输出条数上限")
    parser.add_argument("--out", help="过滤结果落盘路径（可选）")
    args = parser.parse_args()

    path, snapshot = load_snapshot(args.date)
    rows: list[dict] = []
    board_stats: list[tuple[str, int, int, int]] = []
    excluded_total = 0
    for board in snapshot["boards"]:
        if board.get("error"):
            continue
        film_items = []
        for item in board["items"]:
            text = f"{item['title']} {item['desc']}"
            if is_excluded(text):
                excluded_total += 1
                continue
            if not is_film_relevant(text):
                continue
            score = dispute_score(text)
            film_items.append(
                {
                    "source": board["route"],
                    "source_label": board["label"],
                    "rank": item["rank"],
                    "title": item["title"],
                    "desc": item["desc"],
                    "hot": item["hot"],
                    "url": item["url"],
                    "dispute": score,
                }
            )
        board_stats.append((board["label"], len(film_items), len(board["items"]), 0))
        rows.extend(film_items)

    rows.sort(key=lambda r: (-r["dispute"], -(r["hot"] or 0)))

    print(f"快照: {path}（{snapshot['captured_at']}）")
    print(f"影视向命中 {len(rows)} 条 / 全量 {sum(b[2] for b in board_stats)} 条"
          f"（禁区过滤 {excluded_total} 条）\n")
    for label, hit, total, _excl in board_stats:
        print(f"  {label}: 影视向 {hit}/{total}")
    print(f"\n按争议度降序，前 {min(args.top, len(rows))} 条：")
    for i, row in enumerate(rows[: args.top], 1):
        flag = "🔥" if row["dispute"] >= 2 else ("⚡" if row["dispute"] == 1 else "  ")
        print(f"{i:>2}. {flag} [{row['source_label']}] {row['title'][:44]}")
        print(f"     争议{row['dispute']} 热度{row['hot']}  {row['url'][:66]}")

    if args.out:
        target = Path(args.out)
        target.write_text(
            json.dumps(
                {
                    "schema_version": "talk-filter-demo-v1",
                    "snapshot_date": snapshot["date"],
                    "snapshot_path": str(path),
                    "method": "keyword-heuristics (film/drama relevance + dispute intensity proxy)",
                    "film_hits": len(rows),
                    "items": rows,
                    "note": "信号仅作 R0 选题发现，不作事实来源；争议度为讨论烈度粗代理。",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"\n已落盘: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
