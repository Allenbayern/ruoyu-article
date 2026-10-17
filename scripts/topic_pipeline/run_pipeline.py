#!/usr/bin/env python3
"""选题流水线编排主脚本 (run_pipeline.py)
整合采集、零 Token 粗筛、带 72h 历史对齐的聚类、增量 LLM 打分、SQLite 双表持久化，
并产出符合黄金阵型（1爆发首发 + 1发酵蓄势 + 1常青母题）的《今日高潜选题推荐报告》。
落实【补丁 1、2、3】全部工程要求。
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

PIPELINE_DIR = Path(__file__).parent
SCRIPTS_DIR = PIPELINE_DIR.parent
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import cluster
import db
import fetcher
import filter as f_filter
import lifecycle
import llm_client
import scorer


def load_existing_event(conn: sqlite3.Connection, event_id: str) -> dict[str, Any] | None:
    cur = conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
    row = cur.fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("core_entities"):
        d["core_entities"] = json.loads(d["core_entities"])
    if d.get("platforms_involved"):
        d["platforms_involved"] = json.loads(d["platforms_involved"])
    return d


def get_snapshots_for_event(conn: sqlite3.Connection, event_id: str, limit: int = 3) -> list[dict[str, Any]]:
    cur = conn.execute(
        """
        SELECT platform, platform_tier, rank_position, raw_title, url 
        FROM snapshots 
        WHERE event_id = ? 
        ORDER BY batch_time DESC, rank_position ASC 
        LIMIT ?
        """,
        (event_id, limit),
    )
    return [dict(r) for r in cur.fetchall()]


def generate_top3_report(conn: sqlite3.Connection, now: int) -> tuple[str, dict[str, Any]]:
    """生成黄金阵型 Top 3 推荐报告（落实补丁3）
    - 推荐 1：爆发首发（burst 阶段最高分）
    - 推荐 2：蓄势深度（fermenting 阶段最高分）
    - 推荐 3：常青母题（evergreen_hook 阶段最高分，若无则从 evergreen_seeds / 历史池兜底）
    每个推荐附带代表性平台的原始 url。
    """
    # 查所有 pending 且未在冷却期的事件
    cur = conn.execute(
        """
        SELECT * FROM events 
        WHERE status = 'pending' AND cooldown_until <= ? AND safety_tier != 'RED'
        ORDER BY overall_score DESC, last_seen_at DESC
        """,
        (now,),
    )
    all_pending = [dict(r) for r in cur.fetchall()]

    burst_cand = None
    ferment_cand = None
    evergreen_cand = None

    # 1. 寻找推荐 1 (burst)
    for ev in all_pending:
        if ev["lifecycle_stage"] == "burst":
            burst_cand = ev
            break
    # 若无严格 burst，取最新出现的最高分且非衰退/冷饭(非 fading/cold)事件
    if not burst_cand:
        for ev in all_pending:
            if ev["lifecycle_stage"] not in ("fading", "cold"):
                burst_cand = ev
                break

    # 2. 寻找推荐 2 (fermenting)
    for ev in all_pending:
        if ev["event_id"] != (burst_cand["event_id"] if burst_cand else None):
            if ev["lifecycle_stage"] == "fermenting":
                ferment_cand = ev
                break
    # 若无严格 fermenting，取第二高分的非 burst 且非衰退/冷饭(非 fading/cold)事件
    if not ferment_cand:
        for ev in all_pending:
            if burst_cand and ev["event_id"] == burst_cand["event_id"]:
                continue
            if ev["lifecycle_stage"] not in ("fading", "cold"):
                ferment_cand = ev
                break

    # 3. 寻找推荐 3 (evergreen_hook / 常青母题，补丁3核心兜底)
    for ev in all_pending:
        used_ids = {burst_cand["event_id"] if burst_cand else None, ferment_cand["event_id"] if ferment_cand else None}
        if ev["event_id"] not in used_ids and ev["lifecycle_stage"] == "evergreen_hook":
            evergreen_cand = ev
            break

    is_seed_fallback = False
    # 若当日没有触发常青热搜，从 evergreen_seeds 兜底捞取最高分种子
    if not evergreen_cand:
        cur = conn.execute(
            """
            SELECT * FROM evergreen_seeds 
            WHERE status = 'pending' AND cooldown_until <= ? 
            ORDER BY score DESC LIMIT 1
            """,
            (now,),
        )
        seed_row = cur.fetchone()
        if seed_row:
            s_dict = dict(seed_row)
            evergreen_cand = {
                "event_id": s_dict["seed_id"],
                "canonical_title": s_dict["title"],
                "lifecycle_stage": "evergreen_hook (种子池兜底)",
                "overall_score": s_dict["score"],
                "resonance_score": s_dict["score"],
                "story_tension_score": s_dict["score"],
                "safety_tier": "GREEN",
                "proposed_angle": s_dict["proposed_angle"],
                "ledger_summary": s_dict["ledger_summary"],
                "platforms_involved": json.dumps(["常青人物库"]),
                "reference_url": s_dict.get("reference_url", ""),
            }
            is_seed_fallback = True

    # 组装 Markdown 报告
    date_str = dt.datetime.fromtimestamp(now).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    report_lines = [
        f"# 🎬 若雨随影 · 今日高潜选题推荐报告",
        f"> **生成时间**：{date_str} | **数据源**：15个核心源实时聚类 | **把关机制**：人工挂起等待决策",
        "",
        "---",
        "",
        "## 📌 今日 Top 3 选题黄金阵型推荐",
        "",
    ]

    recommendations = [
        ("【推荐 1 · 爆发首发】", burst_cand, "抢占全网注意力第一波峰值，兼顾时效与社会反思"),
        ("【推荐 2 · 发酵蓄势】", ferment_cand, "讨论跨多平台发酵 12~36h，各方观点已充分撕扯，最适合若雨冷酷拆台与算透账本"),
        ("【推荐 3 · 常青母题】", evergreen_cand, "经典老戏骨/名利场沉浮/时代眼泪，无时效压力但长尾传播力极强（常青池保障）"),
    ]

    for label, ev, desc in recommendations:
        if not ev:
            report_lines.append(f"### {label} （今日暂无合适候选）\n")
            continue

        eid = ev["event_id"]
        # 获取信源 URL（补丁3）
        urls = []
        if is_seed_fallback and ev.get("reference_url"):
            ref_val = ev["reference_url"]
            if ref_val.startswith("http"):
                urls.append(f"[{ev['canonical_title']}]({ref_val}) (经典文献/权威报道)")
            else:
                urls.append(ref_val)
        else:
            snaps = get_snapshots_for_event(conn, eid, limit=2)
            for sn in snaps:
                u = sn.get("url")
                if u:
                    urls.append(f"[{sn['platform']} #{sn['rank_position']} - {sn['raw_title'][:20]}]({u})")

        platforms_list = json.loads(ev["platforms_involved"]) if isinstance(ev["platforms_involved"], str) else ev["platforms_involved"]
        platforms_str = "、".join(platforms_list) if platforms_list else "全网"

        report_lines.extend([
            f"### {label} {ev['canonical_title']}",
            f"- **事件 ID**：`{eid}`",
            f"- **生命周期**：`{ev['lifecycle_stage']}` | **安全评级**：`{ev['safety_tier']}`",
            f"- **综合推荐分**：**{ev['overall_score']} 分** (共鸣度: {ev.get('resonance_score', 0)} / 戏剧张力: {ev.get('story_tension_score', 0)})",
            f"- **跨平台覆盖**：{platforms_str}",
            f"- **定位说明**：{desc}",
            f"- **现实账本 (Ledger)**：{ev.get('ledger_summary', '算透背后利益得失与阶层现实。')}",
            f"- **若雨文风切入点 (Angle)**：**{ev.get('proposed_angle', '从该事件切入，以冷峻白话撕开温情遮羞布。')}**",
        ])

        if ev.get("published_decay_penalty") and ev["published_decay_penalty"] < 0:
            report_lines.append(f"- **历史衰减负分**：⚠️ `{ev['published_decay_penalty']} 分` ({ev.get('penalty_reason', '')})")

        if urls:
            report_lines.append(f"- **信源回溯核验**：")
            for u_item in urls:
                report_lines.append(f"  * 🔗 {u_item}")
        else:
            report_lines.append(f"- **信源回溯核验**：平台未透传直链，可凭事件关键词在各平台回溯")

        report_lines.append("")

    report_lines.extend([
        "---",
        "## 🧭 决策表态指南（人工把关挂起协议）",
        "您可以直接回复如下指令完成决策，系统将自动记录并进入 7 天冷却期：",
        "1. **选用某题立项**：`python scripts/topic_pipeline/manage.py select <event_id>`（或直接回复我：`选定 1/2/3`）",
        "2. **驳回不写**：`python scripts/topic_pipeline/manage.py reject <event_id>`（自动计入 7 天冷却，不再打扰）",
        "3. **全部跳过/换一批**：保持 pending 或等待下次整点更新。",
    ])

    report_content = "\n".join(report_lines)
    return report_content, {
        "burst_id": burst_cand["event_id"] if burst_cand else None,
        "ferment_id": ferment_cand["event_id"] if ferment_cand else None,
        "evergreen_id": evergreen_cand["event_id"] if evergreen_cand else None,
    }


def run_pipeline() -> str:
    now = int(time.time())
    db.init_db()
    conn = db.get_db()
    env = llm_client.load_env()

    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] 1. 开始采集 15 个核心源...", flush=True)
    raw_items, fetch_summary = fetcher.fetch_all_core_routes(batch_time=now)
    print(f"   采集完成：成功源 {fetch_summary['success_count']}/{fetch_summary['total_sources']}，累计抓取 {len(raw_items)} 条", flush=True)

    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] 2. 执行零 Token 本地规则粗筛...", flush=True)
    selected_candidates, filter_stats = f_filter.filter_candidates(raw_items, target_min=40, target_max=60)
    print(f"   粗筛完成：剔除噪音 {filter_stats['filtered_out_count']} 条，保留精选 {len(selected_candidates)} 条送入聚类", flush=True)

    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] 3. 执行事件聚类（注入 72h 活跃事件，落实补丁 1）...", flush=True)
    active_events_72h = db.get_active_events_72h(conn)
    print(f"   已加载历史 72h 活跃事件: {len(active_events_72h)} 个", flush=True)
    clustered_events = cluster.cluster_hotspots_with_llm(selected_candidates, active_events_72h, env)
    print(f"   聚类完成：归纳出 {len(clustered_events)} 个独立现实事件", flush=True)

    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] 4. 判定生命周期与增量打分筛选（落实补丁 2）...", flush=True)
    events_to_score = []
    events_final_data = []

    for ev in clustered_events:
        eid = ev["event_id"]
        existing = load_existing_event(conn, eid)
        first_seen = existing["first_seen_at"] if existing else now
        
        # 本地计算生命周期
        l_stage = lifecycle.compute_lifecycle_stage(ev, ev["items"], first_seen, now=now)
        ev["lifecycle_stage"] = l_stage
        ev["first_seen_at"] = first_seen
        ev["seen_count"] = (existing["seen_count"] + 1) if existing else 1
        
        platforms = list(set(it["platform"] for it in ev["items"]))
        ev["platforms_involved"] = platforms
        ev["cross_platform_count"] = len(platforms)

        # 检查是否需要调用 LLM 增量打分（补丁2）
        need_score, reason = scorer.should_trigger_llm_scoring(ev, existing, ev["items"], now)
        if need_score:
            events_to_score.append(ev)
        else:
            # 复用历史评分，但必须经过最新的垂类约束（防旧历史脏数据残留）
            ev["safety_tier"] = existing.get("safety_tier", "GREEN")
            ev["safety_reason"] = existing.get("safety_reason", "")
            ev["resonance_archetype"] = existing.get("resonance_archetype", "")
            ev["resonance_score"] = existing.get("resonance_score", 0)
            ev["story_tension_score"] = existing.get("story_tension_score", 0)
            ev["overall_score"] = existing.get("overall_score", 0)
            ev["proposed_angle"] = existing.get("proposed_angle", "")
            ev["ledger_summary"] = existing.get("ledger_summary", "")
            # 重新过一次垂类亲和与民生噪音约束
            scorer.apply_vertical_affinity(ev["canonical_title"], ev)
        
        events_final_data.append(ev)

    print(f"   增量打分判定：需调用 LLM 打分事件 {len(events_to_score)} 个，复用历史/跳过 {len(clustered_events) - len(events_to_score)} 个")
    
    if events_to_score:
        score_results = scorer.evaluate_events_with_llm(events_to_score, env)
        for ev in events_final_data:
            eid = ev["event_id"]
            if eid in score_results:
                sc = score_results[eid]
                ev["safety_tier"] = sc.get("safety_tier", "GREEN")
                ev["safety_reason"] = sc.get("safety_reason", "")
                ev["resonance_archetype"] = sc.get("resonance_archetype", "")
                ev["resonance_score"] = sc.get("resonance_score", 0)
                ev["story_tension_score"] = sc.get("story_tension_score", 0)
                ev["overall_score"] = sc.get("overall_score", 0)
                ev["proposed_angle"] = sc.get("proposed_angle", "")
                ev["ledger_summary"] = sc.get("ledger_summary", "")

    # 4.1 加载历史已发文章台账，计算动态时间衰减负分算法
    published_topics = db.get_published_topics(conn)
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] 4.1 结合历史已发长文 ({len(published_topics)} 篇) 执行动态时间衰减负分...")
    for ev in events_final_data:
        penalty, reason = scorer.calculate_historical_topic_penalty(
            event_title=ev["canonical_title"],
            core_entities=ev.get("core_entities", []),
            published_topics=published_topics,
            now=now,
            cross_platform_count=ev.get("cross_platform_count", 1),
            is_burst=(ev.get("lifecycle_stage") == "burst"),
        )
        ev["published_decay_penalty"] = penalty
        ev["penalty_reason"] = reason
        if penalty != 0:
            original_score = ev.get("overall_score", 70)
            adjusted_score = max(1, min(100, original_score + penalty))
            ev["overall_score"] = adjusted_score
            print(f"   [历史降权] 事件 '{ev['canonical_title'][:20]}' 原得分 {original_score} ➔ 惩罚 {penalty} 分 ➔ 最终得分 {adjusted_score} ({reason})")

    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] 5. 写入 SQLite (events & snapshots)...")
    for ev in events_final_data:
        db.upsert_event(conn, ev)
        for item in ev["items"]:
            db.insert_snapshot(conn, {
                "event_id": ev["event_id"],
                "batch_time": now,
                "platform": item["platform"],
                "platform_tier": item["platform_tier"],
                "rank_position": item["rank_position"],
                "raw_title": item["title"],
                "url": item.get("url", ""),
                "raw_hot_label": item.get("raw_hot_label", ""),
            })

    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] 6. 生成《今日高潜选题推荐报告》（落实补丁 3）...")
    report_md, rec_meta = generate_top3_report(conn, now)

    # 保存报告到 runs/radar 供归档与追溯
    out_dir = Path("/home/allen/Projects/ruoyu-film-daily/runs/radar")
    out_dir.mkdir(parents=True, exist_ok=True)
    report_file = out_dir / f"radar_report_{dt.datetime.fromtimestamp(now).strftime('%Y%m%d_%H%M%S')}.md"
    report_file.write_text(report_md, encoding="utf-8")
    print(f"   报告已持久化保存至: {report_file}")

    # 自动覆写/同步至 topic_pool/latest_report.md（实现秒级开工读取）
    topic_pool_dir = Path("/home/allen/Projects/ruoyu-film-daily/topic_pool")
    topic_pool_dir.mkdir(parents=True, exist_ok=True)
    latest_report_file = topic_pool_dir / "latest_report.md"
    latest_report_file.write_text(report_md, encoding="utf-8")
    print(f"   最新报告已秒级同步更新至: {latest_report_file}")

    conn.close()
    return report_md


if __name__ == "__main__":
    rep = run_pipeline()
    print("\n" + "=" * 40 + " 报告内容 " + "=" * 40)
    print(rep)
