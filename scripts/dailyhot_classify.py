#!/usr/bin/env python3
"""DailyHot 谈资信号 LLM 分类层（第 2 步落地版）。

对每日快照做两件事：
1. 影视向判定 film（true/false）——是否与影视/综艺/动漫/明星娱乐话题直接相关；
2. 争议度 dispute（0 平静信息 / 1 有争议或立场分歧 / 2 激烈站队/翻车级）。

实现要点：
- LLM：shenwendp deepseek-v4.1-flash（reasoning_effort=low），每请求 30 条批量；
- 失败降级：单批请求失败 → 该批改走关键词启发式（复用 dailyhot_talk_filter 的
  同款规则）并标记 method=heuristic-fallback；LLM 整体不可用 → 全部启发式兜底，
  仍产出分类文件（退出码 0，摘要里如实标注降级比例）；
- 禁区词（死亡/病逝/自杀）先行过滤，不进 LLM；
- 边界：信号仅作 R0 选题发现，不作事实来源；分类判断不含事实承诺。

凭据：~/.config/ruoyu-llm/env（600 权限：RUOYU_LLM_API_KEY/BASE_URL/MODEL）。
密钥只经环境注入内存，不写日志、不回显、不入 runs/ 产物。

用法：
    python3 scripts/dailyhot_classify.py
    python3 scripts/dailyhot_classify.py --date 2026-09-16 --top 20
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.dailyhot_talk_filter import (  # noqa: E402
    dispute_score,
    is_excluded,
    is_film_relevant,
    load_snapshot,
)
from scripts.llm_client import LlmUnavailable, chat as llm_chat, load_env, parse_json_array  # noqa: E402

CHUNK_SIZE = 30

SYSTEM_PROMPT = (
    "你是影视内容选题助理。对每条候选信号判断两件事并只输出 JSON：\n"
    "1) film: 是否与影视剧/综艺/动漫/网文改编/明星艺人娱乐话题直接相关（true/false）；"
    "注意：电竞选手、游戏、体育赛事话题一律判 false（除非是影视改编）。\n"
    "2) dispute: 讨论烈度——0=平静信息或提问，1=有明显争议/立场分歧/吐槽，"
    "2=激烈争吵、站队、翻车级事件。\n"
    '输出格式（严格 JSON 数组，不要任何解释文字）：[{"i":序号,"film":true,"dispute":1,"why":"≤10字原因"}]'
)


def heuristic_judge(title: str, desc: str) -> tuple[bool, int, str]:
    text = f"{title} {desc}"
    return is_film_relevant(text), min(dispute_score(text), 2), "关键词启发式"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="快照日期（默认最新）")
    parser.add_argument("--top", type=int, default=20, help="摘要输出条数")
    parser.add_argument("--chunk", type=int, default=CHUNK_SIZE)
    args = parser.parse_args()

    path, snapshot = load_snapshot(args.date)
    items: list[dict] = []
    for board in snapshot["boards"]:
        if board.get("error"):
            continue
        for item in board["items"]:
            items.append(
                {
                    "source": board["route"],
                    "source_label": board["label"],
                    "rank": item["rank"],
                    "title": item["title"],
                    "desc": item["desc"],
                    "hot": item["hot"],
                    "url": item["url"],
                    "text": f"{item['title']} {item['desc']}",
                }
            )

    env = load_env()
    classified: dict[int, dict] = {}
    llm_count = fallback_count = excluded_count = 0
    for idx, item in enumerate(items):
        if is_excluded(item["text"]):
            classified[idx] = {"film": False, "dispute": 0, "why": "禁区词过滤", "method": "excluded"}
            excluded_count += 1

    pending = [i for i in range(len(items)) if i not in classified]
    for start in range(0, len(pending), args.chunk):
        chunk = pending[start : start + args.chunk]
        user = "候选信号（序号<TAB>标题<TAB>摘要）：\n" + "\n".join(
            f"{idx}\t{items[idx]['title'][:80]}\t{items[idx]['desc'][:80]}" for idx in chunk
        )
        try:
            raw = llm_chat(env, SYSTEM_PROMPT, user)
            parsed = parse_json_array(raw)
            if not parsed:
                # 一次更严格的重试：要求裸 JSON，禁止解释
                raw = llm_chat(
                    env,
                    SYSTEM_PROMPT + "最终回答必须是一个裸 JSON 数组，禁止任何其他文字或代码块。",
                    user,
                )
                parsed = parse_json_array(raw)
            if not parsed:
                raise LlmUnavailable("json_parse_failed")
            for entry in parsed:
                i = int(entry.get("i", -1))
                if i in chunk:
                    classified[i] = {
                        "film": bool(entry.get("film")),
                        "dispute": max(0, min(int(entry.get("dispute") or 0), 2)),
                        "why": str(entry.get("why", ""))[:20],
                        "method": "llm",
                    }
                    llm_count += 1
        except (LlmUnavailable, KeyError, ValueError, TypeError) as exc:
            for idx in chunk:
                film, dispute, why = heuristic_judge(items[idx]["title"], items[idx]["desc"])
                classified[idx] = {"film": film, "dispute": dispute, "why": why, "method": "heuristic-fallback"}
            fallback_count += len(chunk)
            print(f"[classify] chunk[{chunk[0]}:{chunk[-1]}] LLM 失败（{exc}）→ 该批已降级关键词", file=sys.stderr)

    for idx in pending:
        if idx not in classified:  # 极端兜底：任何遗漏都用启发式补齐
            film, dispute, why = heuristic_judge(items[idx]["title"], items[idx]["desc"])
            classified[idx] = {"film": film, "dispute": dispute, "why": why, "method": "heuristic-fallback"}
            fallback_count += 1

    rows = []
    for idx, item in enumerate(items):
        verdict = classified.get(idx, {"film": False, "dispute": 0, "why": "", "method": "missing"})
        rows.append({**item, **verdict})
    film_rows = [r for r in rows if r["film"]]
    hot_disputes = sorted(
        film_rows, key=lambda r: (-r["dispute"], -(r["hot"] or 0))
    )

    out = Path("runs/radar/dailyhot") / f"{path.stem}.classified.json"
    out.write_text(
        json.dumps(
            {
                "schema_version": "talk-classified-v1",
                "snapshot": str(path),
                "llm_model": env.get("RUOYU_LLM_MODEL"),
                "stats": {
                    "total": len(items),
                    "llm": llm_count,
                    "heuristic_fallback": fallback_count,
                    "excluded": excluded_count,
                },
                "film_hits": len(film_rows),
                "items": rows,
                "note": "信号仅作 R0 选题发现，不作事实来源；dispute 为讨论烈度代理。",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"快照: {path}")
    print(
        f"统计: 总 {len(items)} | LLM 分类 {llm_count} | 降级关键词 {fallback_count} | 禁区过滤 {excluded_count}"
    )
    print(f"影视向 {len(film_rows)} 条，按争议度降序前 {min(args.top, len(hot_disputes))} 条：")
    for i, r in enumerate(hot_disputes[: args.top], 1):
        flag = "🔥" if r["dispute"] >= 2 else ("⚡" if r["dispute"] == 1 else "  ")
        print(f"{i:>2}. {flag} [{r['source_label']}] {r['title'][:40]}  {r['why'][:12]}")
        print(f"      {r['url'][:70]}")
    print(f"\n分类结果: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
