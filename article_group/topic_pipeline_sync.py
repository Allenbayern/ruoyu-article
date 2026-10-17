"""topic_pipeline_sync: 将投射对焦卡、标题漏斗与冷启动物料包同步至 topics.db。

为选题库提供从热点/母本到工业化工业三件套（对焦卡、标题漏斗、冷启动包）的落盘存储与检索能力。
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Mapping

from article_group.projection_card import (
    EXPECTED_ACTIONS,
    validate_projection_card,
)
from article_group.title_funnel import (
    build_title_funnel_pack,
    audit_title_health,
)
from article_group.moyu_green_renderer import (
    build_cold_start_kit,
)

DEFAULT_DB_PATH = Path("/home/allen/Projects/ruoyu-film-daily/topic_pool/topics.db")


def init_topic_projections_table(conn: sqlite3.Connection) -> None:
    """确保 topics.db 中存在 topic_projections 工业化流水线物料表。"""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS topic_projections (
            topic_id TEXT PRIMARY KEY,
            work_name TEXT NOT NULL,
            killer_stance TEXT NOT NULL,
            projection_card_json TEXT NOT NULL,
            title_funnel_json TEXT NOT NULL,
            cold_start_kit_json TEXT NOT NULL,
            status TEXT DEFAULT 'ready',
            updated_at INTEGER NOT NULL
        );
    """)
    conn.commit()


def upsert_topic_projection(
    conn: sqlite3.Connection,
    *,
    topic_id: str,
    work_name: str,
    killer_stance: str,
    projection_card: Mapping[str, Any],
    title_funnel_pack: Mapping[str, Any],
    cold_start_kit: Mapping[str, Any],
    status: str = "ready",
) -> dict[str, Any]:
    """校验并将一个选题的工业化流水线物料（对焦卡、标题漏斗、冷启动包）持久化到数据库。"""
    init_topic_projections_table(conn)

    # 1. 强门禁：动笔前投射对焦卡必须 PASS
    pval = validate_projection_card(projection_card)
    if not pval["passed"]:
        raise ValueError(f"projection_card_validation_failed: {','.join(pval['errors'])}")

    # 2. 强门禁：标题包主选标题必须 PASS 健康度体检
    sel_title = str(title_funnel_pack.get("selected_title") or "")
    th_audit = audit_title_health(sel_title)
    if not th_audit["passed"]:
        raise ValueError(f"selected_title_health_failed: {','.join(th_audit['errors'])}")

    now_ts = int(time.time())
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO topic_projections (
            topic_id, work_name, killer_stance,
            projection_card_json, title_funnel_json, cold_start_kit_json,
            status, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
    """, (
        topic_id,
        work_name,
        killer_stance,
        json.dumps(dict(projection_card), ensure_ascii=False),
        json.dumps(dict(title_funnel_pack), ensure_ascii=False),
        json.dumps(dict(cold_start_kit), ensure_ascii=False),
        status,
        now_ts,
    ))
    conn.commit()

    return {
        "topic_id": topic_id,
        "work_name": work_name,
        "killer_stance": killer_stance,
        "selected_title": sel_title,
        "status": status,
        "updated_at": now_ts,
    }


def get_topic_projection(conn: sqlite3.Connection, topic_id: str) -> dict[str, Any] | None:
    """根据 topic_id 读取选题的工业化流水线物料。"""
    init_topic_projections_table(conn)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT topic_id, work_name, killer_stance,
               projection_card_json, title_funnel_json, cold_start_kit_json,
               status, updated_at
        FROM topic_projections WHERE topic_id = ?;
    """, (topic_id,))
    row = cursor.fetchone()
    if not row:
        return None

    tf = json.loads(row[4])
    return {
        "topic_id": row[0],
        "work_name": row[1],
        "killer_stance": row[2],
        "selected_title": tf.get("selected_title"),
        "projection_card": json.loads(row[3]),
        "title_funnel": tf,
        "cold_start_kit": json.loads(row[5]),
        "status": row[6],
        "updated_at": row[7],
    }


def sync_classic_pilot_cases_to_db(db_path: str | Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    """将范冰冰《绿夜》/《疯癫老人日记》（case-001）与蔡康永《说话之道》（case-008）两套标准工程化样本跑通并落盘。"""
    p = Path(db_path)
    conn = sqlite3.connect(p)
    results = []

    # -------------------------------------------------------------
    # Case 001: 范冰冰《疯癫老人日记》/《绿夜》海外复出豪赌
    # -------------------------------------------------------------
    c1_work = "疯癫老人日记"
    c1_stance = "算透顶流跌落神坛后的沉没成本，撕下所有名利场翻盘的虚妄体面"
    c1_card = {
        "self_relevance": "剥离顶流光环后，对应职场与中年人背负沉重沉没成本、企图孤注一掷逆风翻盘的切肤代价。",
        "emotional_outlet": "读完这篇，读者顺出看透名利浮华、接受现实代价后的释怀与人间清醒。",
        "one_liner_conflict": "台前全是为艺术献身，台后全是复出回血的孤注一掷",
        "expected_action": "截图某句人间清醒发朋友圈",
    }
    c1_tp = build_title_funnel_pack(
        c1_work,
        c1_stance,
        case_id="case-001",
        facts=["豆瓣至今不敢开分", "海外首映爆满恶评两极", "豪赌文艺片投资超数千万"],
        projection_card=c1_card,
        selected_index=0,
    )
    c1_cold = build_cold_start_kit(
        title=c1_tp["selected_title"],
        work_name=c1_work,
        killer_stance=c1_stance,
        projection_card=c1_card,
        title_pack=c1_tp,
    )
    res_1 = upsert_topic_projection(
        conn,
        topic_id="case-001",
        work_name=c1_work,
        killer_stance=c1_stance,
        projection_card=c1_card,
        title_funnel_pack=c1_tp,
        cold_start_kit=c1_cold,
    )
    results.append(res_1)

    # -------------------------------------------------------------
    # Case 008: 蔡康永《说话之道》高情商课走下神坛
    # -------------------------------------------------------------
    c8_work = "说话之道"
    c8_stance = "戳破东亚社会用高情商粉饰委曲求全的谎言，算清老好人被无限消耗的真实账本"
    c8_card = {
        "self_relevance": "剥离畅销书光环后，直戳普通人在职场与人际交往中过度讨好、咽下委屈的内耗账本。",
        "emotional_outlet": "读完这篇，读者顺出那口不再惯着伪善者、拒绝做讨好型老好人的解气爽感。",
        "one_liner_conflict": "台前教你体面说话，台后全是老实人默默咽下的生存委屈",
        "expected_action": "去评论区骂/倒苦水",
    }
    c8_tp = build_title_funnel_pack(
        c8_work,
        c8_stance,
        case_id="case-008",
        facts=["畅销500万册跌落神坛", "买课年轻人直呼上当", "高情商沦为职场软弱代名词"],
        projection_card=c8_card,
        selected_index=2,  # 选用套路B：看哭无数老实人
    )
    c8_cold = build_cold_start_kit(
        title=c8_tp["selected_title"],
        work_name=c8_work,
        killer_stance=c8_stance,
        projection_card=c8_card,
        title_pack=c8_tp,
    )
    res_8 = upsert_topic_projection(
        conn,
        topic_id="case-008",
        work_name=c8_work,
        killer_stance=c8_stance,
        projection_card=c8_card,
        title_funnel_pack=c8_tp,
        cold_start_kit=c8_cold,
    )
    results.append(res_8)

    conn.close()
    return results
