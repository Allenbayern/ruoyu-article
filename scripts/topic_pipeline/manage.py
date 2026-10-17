#!/usr/bin/env python3
"""选题库状态管理 CLI (manage.py)
用于人工把关状态机流转：
- list: 查看当前 pending / selected / rejected 事件
- select <event_id>: 确认立项该选题，自动进入 7 天冷却防重复推荐
- reject <event_id>: 驳回该选题，记录不写并进入 7 天冷却
- stats: 统计事件库与快照总览
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

PIPELINE_DIR = Path(__file__).parent
PROJECT_ROOT = PIPELINE_DIR.parent.parent
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import db
import title_generator
import llm_client
from article_group.projection_card import (
    generate_projection_card_from_event,
    generate_projection_card_with_llm,
    format_projection_card_markdown,
    validate_projection_card,
)


def format_time(ts: int) -> str:
    if not ts:
        return "无"
    return dt.datetime.fromtimestamp(ts).astimezone().strftime("%Y-%m-%d %H:%M")


def main() -> int:
    parser = argparse.ArgumentParser(description="若雨随影选题池管理工具")
    subparsers = parser.add_subparsers(dest="cmd")

    # list
    p_list = subparsers.add_parser("list", help="列出选题")
    p_list.add_argument("--status", choices=["pending", "selected", "rejected", "all"], default="pending")
    p_list.add_argument("--limit", type=int, default=20)

    # select
    p_sel = subparsers.add_parser("select", help="选用某事件立项（自动进入冷却并生成投射对焦卡）")
    p_sel.add_argument("event_id", help="事件 ID")
    p_sel.add_argument("--days", type=int, default=7, help="冷却天数（默认7天）")
    p_sel.add_argument("--run-dir", help="可选的目标 run 目录（自动注入 article-brief.json）")

    # projection
    p_proj = subparsers.add_parser("projection", help="查看或导出某事件的《动笔前投射对焦卡》")
    p_proj.add_argument("event_id", help="事件 ID")
    p_proj.add_argument("--run-dir", help="可选的目标 run 目录（自动写入 article-brief.json）")
    p_proj.add_argument("--source-file", help="可选的新闻源正文/事实素材文件路径（如 article.md），用于精准推演与杜绝幻觉")

    # title
    p_title = subparsers.add_parser("title", help="为某事件生成 Top 5 爆款标题包 (title-pack.json)")
    p_title.add_argument("event_id", help="事件 ID")
    p_title.add_argument("--run-dir", help="可选的目标 run 目录（自动写入 title-pack.json）")
    p_title.add_argument("--source-file", help="可选的新闻源正文/事实素材文件路径（如 article.md），用于杜绝事实幻觉")

    # reject
    p_rej = subparsers.add_parser("reject", help="驳回某事件（自动进入冷却）")
    p_rej.add_argument("event_id", help="事件 ID")
    p_rej.add_argument("--days", type=int, default=7, help="冷却天数（默认7天）")

    # stats
    subparsers.add_parser("stats", help="查看数据总览")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return 0

    conn = db.get_db()

    if args.cmd in ("select", "projection"):
        event = db.get_event(conn, args.event_id)
        if not event:
            print(f"❌ 未在 events 或常青库中找到事件 ID: `{args.event_id}`")
            return 1

        if args.cmd == "select":
            ok = db.set_event_status(conn, args.event_id, "selected", days=args.days)
            if ok:
                print(f"✅ 成功将事件 `{args.event_id}` 标记为【selected（已选定立项）】，已设置 {args.days} 天冷却期！\n")
            else:
                print(f"❌ 状态更新失败：`{args.event_id}`")
                return 1

        source_content = ""
        source_file_arg = getattr(args, "source_file", None)
        if source_file_arg:
            sf_path = Path(source_file_arg).resolve()
            if sf_path.is_file():
                source_content = sf_path.read_text(encoding="utf-8")
                print(f"📖 已成功读取新闻源正文素材: {sf_path} ({len(source_content)} 字)")
        
        # 尝试从快照关联的素材或直接调用 LLM 推演对焦卡
        env = llm_client.load_env()
        card = generate_projection_card_with_llm(event, env, source_content=source_content)
        val = validate_projection_card(card)

        print("=" * 60)
        print(f"📌 事件: {event.get('canonical_title')}")
        print("=" * 60)
        print(format_projection_card_markdown(card))
        print("=" * 60)

        run_dir_arg = getattr(args, "run_dir", None)
        if run_dir_arg:
            r_path = Path(run_dir_arg).resolve()
            if r_path.is_dir():
                brief_file = r_path / "article-brief.json"
                brief_data = {}
                if brief_file.is_file():
                    try:
                        brief_data = json.loads(brief_file.read_text(encoding="utf-8"))
                    except Exception:
                        brief_data = {}
                brief_data.setdefault("work", event.get("canonical_title"))
                brief_data.setdefault("killer_stance", event.get("proposed_angle") or card["one_liner_conflict"])
                brief_data["projection_card"] = card
                brief_file.write_text(json.dumps(brief_data, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"💾 《动笔前投射对焦卡》已成功持久化写入: {brief_file}")
            else:
                print(f"⚠️ 指定的 run-dir 目录不存在: {r_path}")

        return 0

    if args.cmd == "title":
        event = db.get_event(conn, args.event_id)
        if not event:
            print(f"❌ 未在 events 或常青库中找到事件 ID: `{args.event_id}`")
            return 1

        source_content = ""
        source_file_arg = getattr(args, "source_file", None)
        if source_file_arg:
            sf_path = Path(source_file_arg).resolve()
            if sf_path.is_file():
                source_content = sf_path.read_text(encoding="utf-8")
                print(f"📖 已加载真实新闻正文/核验素材: {sf_path} ({len(source_content)} 字)")
            else:
                print(f"⚠️ 指定的 source-file 不存在: {sf_path}")

        # 检查是否已有 run-dir 内的草稿正文
        run_dir_arg = getattr(args, "run_dir", None)
        if not source_content and run_dir_arg:
            r_path = Path(run_dir_arg).resolve()
            draft_p = r_path / "draft.md"
            if draft_p.is_file():
                source_content = draft_p.read_text(encoding="utf-8")
                print(f"📖 自动关联到已有草稿正文: {draft_p} ({len(source_content)} 字)")

        print(f"⏳ 正在为事件 `{event.get('canonical_title')}` 召回事实并执行 Top 5 标题漏斗生成...")
        brief = (
            f"核心切入点: {event.get('proposed_angle') or '无'}\n"
            f"现实账本明细: {event.get('ledger_summary') or '无'}\n"
            f"核心实体: {event.get('core_entities') or '无'}\n"
            f"情绪共鸣母题: {event.get('resonance_archetype') or '无'}\n"
            f"【真实核验素材/正文输入（严禁编造素材外的事实）】:\n"
            f"{source_content if source_content else '警告：暂无长文正文输入，仅能依据上述现实账本事实，严禁自行脑补年限、官司与人物关系！'}"
        )
        env = llm_client.load_env()
        title_pack = title_generator.generate_title_pack(event.get("canonical_title"), brief, env)

        print("=" * 60)
        print(f"🎯 选定默认主标题: {title_pack.get('selected_title')}")
        print("=" * 60)
        print("📌 5 大事实锚点 (fact_anchors):")
        for i, a in enumerate(title_pack.get("fact_anchors", []), 1):
            print(f"  {i}. {a}")
        print("\n🏆 Top 5 决选包 (top_5_finalists):")
        for f in title_pack.get("top_5_finalists", []):
            print(f"  #{f.get('rank')} [{f.get('category')}] ({f.get('char_count')}字): {f.get('title')}")
            print(f"     👉 钩子: {f.get('hook_explanation')}")
            print(f"     🕒 建议时段: {f.get('best_for')}")
        print("=" * 60)

        run_dir_arg = getattr(args, "run_dir", None)
        if run_dir_arg:
            r_path = Path(run_dir_arg).resolve()
            if r_path.is_dir():
                tp_file = r_path / "title-pack.json"
                tp_file.write_text(json.dumps(title_pack, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"💾 标题包已成功持久化写入: {tp_file}")
            else:
                print(f"⚠️ 指定的 run-dir 目录不存在: {r_path}")
        return 0

    if args.cmd == "reject":
        ok = db.set_event_status(conn, args.event_id, "rejected", days=args.days)
        if ok:
            print(f"🚫 成功将事件 `{args.event_id}` 标记为【rejected（已驳回）】，进入 {args.days} 天冷却池不再打扰。")
        else:
            print(f"❌ 未找到事件 ID: `{args.event_id}`")
        return 0

    if args.cmd == "list":
        now = int(time.time())
        query = "SELECT * FROM events"
        params = []
        if args.status != "all":
            query += " WHERE status = ?"
            params.append(args.status)
        query += " ORDER BY overall_score DESC, last_seen_at DESC LIMIT ?"
        params.append(args.limit)

        cur = conn.execute(query, tuple(params))
        rows = cur.fetchall()
        print(f"\n📋 事件列表 [状态: {args.status}] 共 {len(rows)} 条:")
        print("-" * 80)
        for r in rows:
            cooldown_desc = "无"
            if r["cooldown_until"] > now:
                remain_h = int((r["cooldown_until"] - now) / 3600)
                cooldown_desc = f"冷却中(余{remain_h}小时)"
            print(f"[{r['overall_score']:2d}分] {r['event_id']} | {r['status']:8s} | {r['lifecycle_stage']:12s} | {cooldown_desc}")
            print(f"      📌 {r['canonical_title']}")
            if r["proposed_angle"]:
                print(f"      🎯 切入点: {r['proposed_angle']}")
            print("-" * 80)
        return 0

    if args.cmd == "stats":
        now = int(time.time())
        c_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        c_pending = conn.execute("SELECT COUNT(*) FROM events WHERE status = 'pending' AND cooldown_until <= ?", (now,)).fetchone()[0]
        c_selected = conn.execute("SELECT COUNT(*) FROM events WHERE status = 'selected'").fetchone()[0]
        c_rejected = conn.execute("SELECT COUNT(*) FROM events WHERE status = 'rejected'").fetchone()[0]
        c_cooldown = conn.execute("SELECT COUNT(*) FROM events WHERE cooldown_until > ?", (now,)).fetchone()[0]
        c_snapshots = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]

        print("\n📊 选题池数据总览:")
        print(f"  - 事件总数: {c_events}")
        print(f"  - 待把关 (pending 可选): {c_pending}")
        print(f"  - 已选定 (selected): {c_selected}")
        print(f"  - 已驳回 (rejected): {c_rejected}")
        print(f"  - 处于冷却期: {c_cooldown}")
        print(f"  - 排名快照轨迹总数: {c_snapshots}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
