#!/usr/bin/env python3
"""增量打分与微信母体契合度评估 (scorer.py)
落实【补丁2】：
1. 处于冷却期（cooldown_until > now 或 status != 'pending'）的事件，坚决不调 LLM 打分！
2. 历史老事件（非首次入库）：仅当 cross_platform_count 相比上次新增 >= 2，或首次进入 S 级 Top 10 时才重新触发 LLM；
3. 否则复用原有评分，仅本地更新 lifecycle_stage 和排名轨迹。
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path("/home/allen/Projects/ruoyu-film-daily/scripts")
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import llm_client

# 影视/名利场/人物垂类加权关键词
RE_VERTICAL_BOOST = re.compile(
    r"(电影|电视剧|演员|导演|明星|艺人|老戏骨|名利场|富豪|大佬|对赌|商海|破产|塌房|豪门|票房|上映|角色|演艺|娱乐|手艺人|老艺术家|退市|巨亏|还债|剧组|影帝|影后|神作|烂片|戏骨|替身|配音|通稿|片酬)"
)

# 纯非垂直民生杂质/泛科技清谈（硬降权至 ≤ 35分，严禁进入公域推荐池）
RE_IRRELEVANT_CIVILIAN = re.compile(
    r"(弹窗.*(扣费|扣款|保费|扣钱)|保险.*(扣费|套路|退费|保单)|劳动纠纷|物业费|维权.*(退费|退款)|电信诈骗|AI.*(替代|颠覆|取代|发展|前景|是否会)|如何看待AI|大模型|手机发布|系统升级|固件更新|参数对比|架构升级)"
)

# 纯宣发/票房播报/定档通报（无深层人物命运账本时严禁加权）
RE_BOX_OFFICE_ANNOUNCEMENT = re.compile(
    r"(票房破(纪录|\d+亿|\d+万)|全球票房|首日票房|首周末票房|新片定档|预告片曝光|发布新剧照|主创亮相|电影节开幕|热映中)"
)

# 历史比对通用泛词（不计入专有名词匹配）
GENERIC_STOP_ENTITIES = {
    "电影", "电视剧", "内娱", "演员", "老戏骨", "导演", "明星", "新片", "票房", "老片", 
    "热搜", "短视频", "艺人", "角色", "演技", "大片", "剧组", "观众", "作品", "主角",
    "中国", "内地", "全球", "全国", "全网", "网友", "官方", "央视", "卫视", "社会", "时代"
}


def calculate_historical_topic_penalty(
    event_title: str,
    core_entities: list[str],
    published_topics: list[dict[str, Any]],
    now: int,
    cross_platform_count: int = 1,
    is_burst: bool = False,
) -> tuple[int, str]:
    """计算基于历史已发文章台账的【动态时间衰减负分算法】：
    1. 判定候选事件与历史发表长文的专有实体/主题重合度；
    2. 若命中，计算距离上次发表的距今天数 days_ago：
       - <= 7.0 天: 刚写过不久，基础负分 -45 分（极大概率不再打扰）
       - 7.0 ~ 14.0 天: 基础负分 -30 分
       - 14.0 ~ 30.0 天: 基础负分 -18 分
       - 30.0 ~ 60.0 天: 基础负分 -10 分
       - > 60.0 天: 基础负分 -5 分（接近完全释放）
    3. 重大突发新热度冲抵/补偿（老人物新爆点综合重估）：
       - 若 cross_platform_count >= 3: 补偿 +12 分
       - 若 cross_platform_count >= 5: 补偿 +20 分
       - 若 is_burst: 额外补偿 +8 分
       - 净惩罚 net_penalty = min(0, base_penalty + burst_bonus)（惩罚净值负分，最多冲抵到 0）
    """
    if not published_topics:
        return 0, ""

    matched_pubs = []
    # 提取事件有效专有实体
    event_valid_ents = [e for e in core_entities if e not in GENERIC_STOP_ENTITIES and len(e) >= 2]

    for pub in published_topics:
        pub_ents = pub.get("core_entities", [])
        pub_valid_ents = [e for e in pub_ents if e not in GENERIC_STOP_ENTITIES and len(e) >= 2]
        
        hit = False
        hit_entity = ""
        # 1. 实体交集
        common = set(event_valid_ents).intersection(set(pub_valid_ents))
        if common:
            hit = True
            hit_entity = list(common)[0]
        else:
            # 2. 实体在标题中出现
            for pe in pub_valid_ents:
                if pe in event_title:
                    hit = True
                    hit_entity = pe
                    break
            if not hit:
                for ee in event_valid_ents:
                    if ee in pub["title"]:
                        hit = True
                        hit_entity = ee
                        break

        if hit:
            pub_ts = pub.get("published_at", now)
            days_ago = max(0.0, (now - pub_ts) / 86400.0)
            matched_pubs.append({
                "pub": pub,
                "hit_entity": hit_entity,
                "days_ago": days_ago,
            })

    if not matched_pubs:
        return 0, ""

    # 取距今最近（days_ago 最小）的一篇作为主约束
    matched_pubs.sort(key=lambda x: x["days_ago"])
    closest = matched_pubs[0]
    days_ago = closest["days_ago"]
    pub_info = closest["pub"]
    hit_ent = closest["hit_entity"]

    # 计算基础时间衰减负分
    if days_ago <= 7.0:
        base_penalty = -45
    elif days_ago <= 14.0:
        base_penalty = -30
    elif days_ago <= 30.0:
        base_penalty = -18
    elif days_ago <= 60.0:
        base_penalty = -10
    else:
        base_penalty = -5

    # 计算重大突发新热度补偿
    burst_bonus = 0
    if cross_platform_count >= 5:
        burst_bonus += 20
    elif cross_platform_count >= 3:
        burst_bonus += 12

    if is_burst:
        burst_bonus += 8

    net_penalty = min(0, base_penalty + burst_bonus)
    reason = (
        f"命中{days_ago:.1f}天前已发长文《{pub_info['title'][:18]}...》({pub_info['published_date']})[关键词:{hit_ent}]，"
        f"衰减负分{base_penalty}分；新热度补偿+{burst_bonus}分；净调整{net_penalty}分"
    )
    return net_penalty, reason


def apply_vertical_affinity(event_title: str, item: dict[str, Any]) -> dict[str, Any]:
    """落实【微信公域推荐 4 大爆款母题与垂类加权收紧】：
    1. 纯非垂直民生杂质/泛科技清谈（如“误点弹窗扣保费”、“AI替代XX”），直接压制在 35 分以下，避免污染推荐池；
    2. 针对微信公域 5W+ 真实爆款 4 大母题给予梯队加权：
       - A_actor_integrity（戏骨风骨 vs 内娱遮羞布）：1.30x
       - B_talent_dilemma（明珠蒙尘 / 灵气演员困境）：1.25x
       - C_hardcore_masterpiece（硬核神作/老片重映打脸烂片）：1.20x
       - D_industry_deconstruction（内娱畸形生态解剖）：1.15x
    3. 纯票房宣发通报，封顶 75 分；
    """
    score = item.get("overall_score", 70)
    archetype = item.get("resonance_archetype", "NONE")
    tension = item.get("story_tension_score", 70)

    # 0. 隔夜冷饭防污染（时效失效保护）：若事件存续超48小时且进入衰退期(fading)，封顶55分一票降权防马后炮
    if item.get("lifecycle_stage") == "fading":
        score = min(55, score)
        item["overall_score"] = score
        return item

    # 1. 纯民生或纯科技噪音一票打入冷板凳
    if RE_IRRELEVANT_CIVILIAN.search(event_title):
        score = min(35, score)
        item["safety_tier"] = "YELLOW"
        item["safety_reason"] = "非影视文娱垂直领域（纯民生消费/科技清谈，微信公域推荐断流）"
        item["overall_score"] = score
        return item

    is_vertical = bool(RE_VERTICAL_BOOST.search(event_title)) or archetype in (
        "A_actor_integrity", "B_talent_dilemma", "C_hardcore_masterpiece", "D_industry_deconstruction",
        "A_celebrity_collapse", "D_era_tears"
    )
    is_pure_pr = bool(RE_BOX_OFFICE_ANNOUNCEMENT.search(event_title))

    if is_vertical and not is_pure_pr and tension >= 75:
        # 按四大核心母题分级加权 (名利场对赌与塌房/演员风骨享受 1.25x 加权)
        if archetype in ("A_actor_integrity", "D_era_tears", "A_celebrity_collapse", "B_talent_dilemma"):
            score = min(98, int(score * 1.25))
        elif archetype == "C_hardcore_masterpiece":
            score = min(95, int(score * 1.20))
        elif archetype in ("D_industry_deconstruction", "B_class_slip"):
            score = min(94, int(score * 1.15))
        else:
            score = min(92, int(score * 1.10))
    elif is_pure_pr and score > 78:
        score = min(78, score)

    item["overall_score"] = max(1, min(100, score))
    return item


def should_trigger_llm_scoring(
    event: dict[str, Any],
    existing_db_event: dict[str, Any] | None,
    items: list[dict[str, Any]],
    now: int,
) -> tuple[bool, str]:
    """判断是否需要调用 LLM 打分（补丁2核心控费节流）"""
    if existing_db_event is None:
        return True, "new_event_first_seen"

    status = existing_db_event.get("status", "pending")
    cooldown_until = existing_db_event.get("cooldown_until", 0)

    # 1. 处于冷却期或已被人工处置（selected/rejected）
    if cooldown_until > now or status != "pending":
        return False, "in_cooldown_or_handled"

    # 2. 检查是否有显著跃升
    old_cross = existing_db_event.get("cross_platform_count", 1)
    new_cross = len(set(it["platform"] for it in items))
    
    # 跨平台数新增 >= 2 个
    if new_cross - old_cross >= 2:
        return True, f"cross_platform_jump_{old_cross}_to_{new_cross}"

    # 首次进入 S 级平台 Top 10
    has_s_top10 = any(it["platform_tier"] == "S" and it["rank_position"] <= 10 for it in items)
    if has_s_top10 and existing_db_event.get("overall_score", 0) < 80:
        return True, "s_tier_top10_surge"

    # 默认复用历史已有评分
    return False, "reuse_cached_score"


def evaluate_chunk_with_llm(
    chunk_events: list[dict[str, Any]],
    env: dict[str, str],
) -> dict[str, dict[str, Any]]:
    eval_inputs = []
    for ev in chunk_events:
        platforms = [f"{it.get('platform', it.get('platform_name', 'unknown'))}(#{it.get('rank_position', 99)})" for it in ev["items"]]
        eval_inputs.append({
            "event_id": ev["event_id"],
            "canonical_title": ev["canonical_title"],
            "core_entities": ev["core_entities"],
            "platforms": platforms,
        })

    system_prompt = """你是一个顶级特稿主编，精通“若雨随影”文风（算透现实账本、大白话拆台、反差人物、冷峻深刻）。
【硬性输出纪律】：直接输出标准 JSON 数组，严禁输出任何思考过程、推理推导或额外文字！

【账号核心定位与公域推荐铁律】：
本账号 90.2% 流量依赖微信公域推荐池，算法核心标签为【影视深度审美 + 撕开内娱遮羞布】。
凡是纯民生纠纷（保费扣款、物业纠纷、劳动维权、电信诈骗）或纯科技清谈（如AI替代XX），算法推荐流为 0，此类事件综合分严禁超过 35 分！

请对输入的现实热搜事件进行【四维深度打分与若雨文风切入点规划】：

1. 安全等级（safety_tier）：
   - GREEN：完全安全（影视、演艺世相、名利场、经典神作、实力派演员反差）；
   - YELLOW：谨慎合规（敏感劳资纠纷、非垂类民生、两性争议、社会公序良俗）；
   - RED：绝对不可碰（重大政治政策公文、外交、灾难公文、违法违纪涉密案）。

2. 若雨随影核心爆款母题原型（resonance_archetype）：
   - A_actor_integrity: 【母题A】戏骨风骨 vs 内娱遮羞布（一辈子龙套/实力派敬业代价，反衬当下流量明星娇气与通稿吹嘘）
   - B_talent_dilemma: 【母题B】明珠蒙尘 / 灵气演员困境（明明有影帝影后级灵气实力，却因不炒作、不迎合资本或烂剧本泛滥而接不到好戏）
   - C_hardcore_masterpiece: 【母题C】硬核神作/经典重温打脸工业烂片（不请流量巨星、靠扎实剧本与真刀真枪把观众看爽，打脸流水线烂片）
   - D_industry_deconstruction: 【母题D】内娱畸形生态解剖（天价片酬泡沫破裂、假吃假演买通稿、番位撕逼、资本强捧灰飞烟灭）
   - A_celebrity_collapse: 名利场人设崩塌与信誉破产
   - B_class_slip: 阶层滑落、资本对赌暴雷与商海风云
   - C_interest_game: 利益算计、合同霸王条款与现实账本博弈
   - D_era_tears: 时代眼泪、老艺人坚守与晚年清寒
   - NONE: 无共鸣原型（非影视文娱事件一律填 NONE）

3. 评分（0-100）：
   - resonance_score: 读者共鸣度（能否刺痛普通人对真实演技、好戏好片、不公内娱的强烈情绪）
   - story_tension_score: 戏剧反差与故事张力（真实付出 vs 荒诞收益）
   - overall_score: 综合推荐分（非影视垂直民生/科技 ≤ 35分；RED ≤ 30分；YELLOW ≤ 65分；契合4大母题的优质 GREEN 可 85-98分）

4. 核心输出字段：
   - ledger_summary: 一句话算透现实账本与利害关系（≤40字，用具体数字/代价/合同/片酬/年限说话）
   - proposed_angle: 若雨随影风格的爆款切入点（≤60字，开篇三秒夺魂，禁八股影评引子，用大白话撕开遮羞布）

请返回纯 JSON 数组，每个对象结构：
[
  {
    "event_id": "...",
    "safety_tier": "GREEN" | "YELLOW" | "RED",
    "safety_reason": "简要原因",
    "resonance_archetype": "A_actor_integrity" | "B_talent_dilemma" | "C_hardcore_masterpiece" | "D_industry_deconstruction" | "A_celebrity_collapse" | "B_class_slip" | "C_interest_game" | "D_era_tears" | "NONE",
    "resonance_score": 85,
    "story_tension_score": 88,
    "overall_score": 87,
    "ledger_summary": "...",
    "proposed_angle": "..."
  }
]
"""
    user_prompt = f"请打分以下事件（共 {len(eval_inputs)} 个）：\n" + json.dumps(eval_inputs, ensure_ascii=False, indent=2)

    title_map = {ev["event_id"]: ev["canonical_title"] for ev in chunk_events}

    for retry in range(2):
        try:
            content = llm_client.chat(env, system_prompt, user_prompt, max_tokens=6000)
            parsed = llm_client.parse_json_array(content)
            if parsed:
                res = {}
                for item in parsed:
                    eid = item.get("event_id")
                    if eid:
                        ev_title = title_map.get(eid, "")
                        res[eid] = apply_vertical_affinity(ev_title, item)
                return res
        except Exception as exc:
            print(f"[scorer] LLM 打分重试 {retry+1}/2 异常: {exc}", file=sys.stderr)
            time.sleep(1)

    return fallback_scoring(chunk_events)


def evaluate_events_with_llm(
    events_to_score: list[dict[str, Any]],
    env: dict[str, str],
    chunk_size: int = 8,
) -> dict[str, dict[str, Any]]:
    """分批调用 LLM 进行母体打分（每批 8 个，轻量化防止单批 token 超限与超时）"""
    if not events_to_score:
        return {}

    all_results: dict[str, dict[str, Any]] = {}
    for i in range(0, len(events_to_score), chunk_size):
        chunk = events_to_score[i : i + chunk_size]
        chunk_res = evaluate_chunk_with_llm(chunk, env)
        all_results.update(chunk_res)

    return all_results


def fallback_scoring(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """备用打分逻辑"""
    results = {}
    for ev in events:
        eid = ev["event_id"]
        raw_res = {
            "event_id": eid,
            "safety_tier": "GREEN",
            "safety_reason": "自动启发式默认安全",
            "resonance_archetype": "B_class_slip",
            "resonance_score": 75,
            "story_tension_score": 75,
            "overall_score": 75,
            "ledger_summary": "涉及现实利益与名利场沉浮，需深挖账本与代价。",
            "proposed_angle": f"从{ev['canonical_title']}切入，算透背后不为人知的现实博弈与人情冷暖。",
        }
        results[eid] = apply_vertical_affinity(ev["canonical_title"], raw_res)
    return results
