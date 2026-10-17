"""projection_card: 动笔前投射对焦卡（Projection Alignment Card）

将“读者三问”与“一行动”规范化为长文起草前的确定性门禁契约：
1. self_relevance（关读者屁事）：剥离明星/电影光环后，对应普通人身上的具体账本（≥10字）
2. emotional_outlet（情绪出口）：读完后读者心里的闷气是怎么顺出来的（≥10字）
3. one_liner_conflict（一句话矛盾）：≤30字大白话核心戏剧反差，严禁公文八股词汇
4. expected_action（预期读者动作）：严格属于三项之一：
   - 转给身边正在踩坑的朋友
   - 去评论区骂/倒苦水
   - 截图某句人间清醒发朋友圈
"""
from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping
from typing import Any

SCHEMA_VERSION = "projection-card-v1"

# 预期读者动作合规枚举（扩展支持家庭避坑群与职场吐槽）
EXPECTED_ACTIONS = (
    "转给身边正在踩坑的朋友",
    "转给家人/相亲相爱一家人群避坑",
    "转给同病相怜的同事/朋友吐槽",
    "去评论区骂/倒苦水",
    "截图某句人间清醒发朋友圈",
)

# 一句话矛盾绝对禁用的公文与伪深刻八股词汇
FORBIDDEN_OFFICIAL_JARGON = (
    "旨在",
    "深入贯彻",
    "扎实推进",
    "全面提升",
    "战略布局",
    "为抓手",
    "为契机",
    "有力保障",
    "顶层设计",
    "协同发力",
    "赋能",
    "闭环",
    "破局",
    "抓好",
    "切实增强",
    "为指导",
    "浅析",
    "何去何从",
    "时代的尘埃",
)


def validate_projection_card(card: Mapping[str, Any] | None) -> dict[str, Any]:
    """确定性校验《动笔前投射对焦卡》数据合规性。"""
    errors: list[str] = []

    if not isinstance(card, Mapping):
        return {
            "passed": False,
            "errors": ["projection_card_must_be_mapping"],
            "card": {},
        }

    # 1. self_relevance (关读者屁事)
    self_rel = str(card.get("self_relevance") or "").strip()
    if not self_rel:
        errors.append("missing_self_relevance")
    elif len(self_rel) < 10:
        errors.append(f"self_relevance_too_thin_{len(self_rel)}_min_10")

    # 2. emotional_outlet (情绪出口)
    outlet = str(card.get("emotional_outlet") or "").strip()
    if not outlet:
        errors.append("missing_emotional_outlet")
    elif len(outlet) < 10:
        errors.append(f"emotional_outlet_too_thin_{len(outlet)}_min_10")

    # 3. one_liner_conflict (一句话矛盾)
    conflict = str(card.get("one_liner_conflict") or "").strip()
    if not conflict:
        errors.append("missing_one_liner_conflict")
    else:
        # 长度上限 30 字
        conflict_clean = re.sub(r"\s+", "", conflict)
        if len(conflict_clean) > 30:
            errors.append(f"one_liner_conflict_too_long_{len(conflict_clean)}_max_30")

        # 公文/套话词拦截
        hit_jargon = [jg for jg in FORBIDDEN_OFFICIAL_JARGON if jg in conflict]
        if hit_jargon:
            errors.append(f"one_liner_conflict_contains_official_jargon:{','.join(hit_jargon)}")

    # 4. expected_action (预期动作)
    action = str(card.get("expected_action") or "").strip()
    if not action:
        errors.append("missing_expected_action")
    elif action not in EXPECTED_ACTIONS:
        errors.append(f"invalid_expected_action:{action}")

    clean_card = {
        "self_relevance": self_rel,
        "emotional_outlet": outlet,
        "one_liner_conflict": conflict,
        "expected_action": action,
    }
    
    # 可选字段：常青老题新写现实增量触点（若提供则保留并回显）
    anchor = str(card.get("fresh_reality_anchor") or "").strip()
    if anchor:
        clean_card["fresh_reality_anchor"] = anchor

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "card": clean_card,
    }


def generate_projection_card_with_llm(
    event: Mapping[str, Any],
    env: dict[str, str],
    source_content: str = "",
) -> dict[str, str]:
    """通过 LLM 深度推演真实的《动笔前投射对焦卡》，彻底杜绝机械模板与万能套话。"""
    try:
        import sys
        from pathlib import Path
        import importlib
        scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        llm_client = importlib.import_module("llm_client")
    except Exception:
        return generate_projection_card_from_event(event)

    title = str(event.get("canonical_title") or "热点事件").strip()
    ledger = str(event.get("ledger_summary") or "").strip()
    angle = str(event.get("proposed_angle") or "").strip()
    archetype = str(event.get("resonance_archetype") or "").strip()

    is_evergreen = archetype in ("A_actor_integrity", "D_era_tears", "C_hardcore_masterpiece") or any(
        kw in title for kw in ("李雪健", "游本昌", "老戏骨", "老艺术家", "张艺谋", "王家卫", "周星驰", "成龙", "经典老片", "抗癌", "老片")
    )
    evergreen_rule = ""
    json_anchor_field = ""
    if is_evergreen:
        evergreen_rule = """
5. fresh_reality_anchor（当下现实增量触点/由头，≥15字）：【常青人物/老题新写硬核红线】绝不能老调重弹发旧词！必须明确指出今天究竟是因为什么新事（例如：近期内娱哪部烂剧天价替身翻车、某场新访谈、或某部新片上映强烈对比），才把该经典人物重新激活带回公众热搜？"""
        json_anchor_field = ',\n  "fresh_reality_anchor": "..."'

    system_prompt = f"""你是一个顶级深度长文主编（若雨随影），在长文动笔前，必须完成《动笔前投射对焦卡（Projection Alignment Card）》。
核心使命：撕掉一切假大空套话，从真实新闻/事件素材中，精准提炼普通人的现实利益痛点、情绪解药与核心矛盾。

【严禁套话铁律】：
严禁使用任何机械模板句式（如'剥离事件光环后...'、'读完这篇，读者看清伪善温情背后的利益机关...'等万能套话一律严禁出现！）。
必须针对该事件的具体人、事、账本，量身定制：
1. self_relevance（关读者屁事，≥15字）：事件背后的哪一笔账或哪种风险，实际上随时可能降临在读者或其家人头上？用具体场景和代价写。
2. emotional_outlet（情绪出口，≥15字）：读完这篇，读者心里积压的哪口恶气、委屈或困惑被狠狠替他说出来了？
3. one_liner_conflict（一句话矛盾，8~30字）：核心对立矛盾大白话，严禁公文八股词（如旨在、赋能、闭环、顶层设计、何去何从）。
4. expected_action（预期读者动作）：必须根据事件类型精准严格选择以下 5 项之一（严禁自创）：
   - 转给家人/相亲相爱一家人群避坑（民生防坑/弹窗扣费/消费陷阱/老年人被套路）
   - 转给身边正在踩坑的朋友（商业对赌/买房踩雷/合同陷阱）
   - 转给同病相怜的同事/朋友吐槽（职场背刺/打工人委屈/行业黑幕）
   - 去评论区骂/倒苦水（名利场塌房/荒诞反转/公序良俗被践踏）
   - 截图某句人间清醒发朋友圈（深刻人生复盘/冷酷人间清醒/老戏骨风骨）{evergreen_rule}

请输出纯 JSON：
{{
  "self_relevance": "...",
  "emotional_outlet": "...",
  "one_liner_conflict": "...",
  "expected_action": "..."{json_anchor_field}
}}"""

    user_prompt = f"""【事件标题】: {title}
【现实账本摘要】: {ledger}
【拟定切入点】: {angle}
【共鸣原型】: {archetype}
【真实素材/正文内容】:
{source_content[:2500] if source_content else '暂无长正文，请基于上述具体事实与账本深度推演。'}

请输出纯 JSON。"""

    try:
        raw_text = llm_client.chat(env, system_prompt, user_prompt, max_tokens=4000)
        stripped = raw_text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            stripped = "\n".join(lines).strip()
        s_idx = stripped.find("{")
        e_idx = stripped.rfind("}")
        if s_idx != -1 and e_idx > s_idx:
            data = json.loads(stripped[s_idx : e_idx + 1])
            if isinstance(data, dict):
                # 预处理与宽容归一化
                conflict = str(data.get("one_liner_conflict") or "").strip()
                conflict_clean = re.sub(r"\s+", "", conflict)
                if len(conflict_clean) > 30:
                    parts = re.split(r"[，,；;。！!？?]", conflict)
                    candidate = parts[0].strip()
                    if 8 <= len(candidate) <= 30:
                        data["one_liner_conflict"] = candidate
                    else:
                        data["one_liner_conflict"] = conflict[:28]

                action = str(data.get("expected_action") or "").strip()
                if action not in EXPECTED_ACTIONS:
                    for valid_act in EXPECTED_ACTIONS:
                        if valid_act in action:
                            data["expected_action"] = valid_act
                            break
                    else:
                        if any(k in action for k in ("朋友圈", "人间清醒", "尊严", "敬仰")):
                            data["expected_action"] = "截图某句人间清醒发朋友圈"
                        elif any(k in action for k in ("家人", "避坑", "长辈")):
                            data["expected_action"] = "转给家人/相亲相爱一家人群避坑"
                        elif any(k in action for k in ("同事", "吐槽", "打工", "行业")):
                            data["expected_action"] = "转给同病相怜的同事/朋友吐槽"
                        elif any(k in action for k in ("骂", "评论", "倒苦水")):
                            data["expected_action"] = "去评论区骂/倒苦水"
                        elif any(k in action for k in ("踩坑", "买房", "对赌", "合同")):
                            data["expected_action"] = "转给身边正在踩坑的朋友"

            val = validate_projection_card(data)
            if val["passed"]:
                return val["card"]
    except Exception as exc:
        print(f"[projection_card] LLM 推演异常: {exc}，使用优化规则兜底", file=sys.stderr)

    return generate_projection_card_from_event(event)


def generate_projection_card_from_event(event: Mapping[str, Any]) -> dict[str, str]:
    """从 topics.db 事件数据智能生成《动笔前投射对焦卡》建议草案（优化非套话兜底）。"""
    title = str(event.get("canonical_title") or "热点事件").strip()
    ledger = str(event.get("ledger_summary") or "").strip()
    angle = str(event.get("proposed_angle") or "").strip()
    archetype = str(event.get("resonance_archetype") or "").strip()

    # 1. 对应普通人身上的具体账本
    if ledger:
        self_rel = f"你以为只是别人的倒霉事，其实同款扣费与合同陷阱随时埋在每个人的手机和账单里：{ledger}"
    elif "中产" in title or "断供" in title or "降薪" in title:
        self_rel = "普通人盲目加杠杆与高估赚钱周期后的必然反噬，每一笔月供都在清算当年的侥幸。"
    elif "背叛" in title or "职场" in title or "老好人" in title:
        self_rel = "职场老黄牛被卸磨杀驴、老实人被无情背刺，算透没有底牌的退让一文不值。"
    else:
        self_rel = f"撕开体面表象后，对应普通人在现实利益博弈与生活重压下最切肤的生存代价。"

    # 2. 情绪出口
    if "弹窗" in title or "扣费" in title or "保险" in title or "套路" in title:
        outlet = "替读者狠狠骂出对平台隐蔽免密扣费、把老百姓当肥羊薅的憋屈与愤怒。"
    elif "翻车" in title or "塌房" in title or "老赖" in title:
        outlet = "撕掉伪善者的画皮，让读者长出一口恶气：出来混总要还，体面被扒了个精光。"
    elif "老戏骨" in title or "游本昌" in title or "田华" in title:
        outlet = "在浮躁喧嚣中给读者一味定心丸：守住底线的人或许清贫，但活得比谁都硬气。"
    else:
        outlet = "戳破世俗温情谎言，让读者在冷峻现实中看清自保底线，获得清醒力量。"

    # 3. 一句话矛盾（≤30字大白话，严禁公文词汇）
    conflict = ""
    if angle:
        clauses = [c.strip() for c in re.split(r"[；。\n]", angle) if c.strip()]
        for cl in clauses:
            clean_cl = re.sub(r"\s+", "", cl)
            if 8 <= len(clean_cl) <= 30:
                conflict = cl
                break
        if not conflict:
            parts = [p.strip() for p in re.split(r"[，,]", angle) if p.strip()]
            combined = ""
            for p in parts:
                candidate = (combined + "，" + p).strip("，")
                if len(re.sub(r"\s+", "", candidate)) <= 30:
                    combined = candidate
                else:
                    break
            if 8 <= len(re.sub(r"\s+", "", combined)) <= 30:
                conflict = combined
            else:
                conflict = angle[:30].strip()
    if not conflict or len(conflict) < 8:
        conflict = "不小心点一下，大半积蓄没了"

    # 4. 预期动作（根据事件属性精准匹配）
    if any(k in title for k in ("弹窗", "扣费", "保费", "骗局", "套路", "老年", "爸妈", "买菜", "避雷")):
        action = "转给家人/相亲相爱一家人群避坑"
    elif any(k in title for k in ("中产", "对赌", "房贷", "破产", "加盟", "合同")):
        action = "转给身边正在踩坑的朋友"
    elif any(k in title for k in ("职场", "降薪", "裁员", "加班", "领导", "背刺", "辞职")):
        action = "转给同病相怜的同事/朋友吐槽"
    elif any(k in title for k in ("塌房", "老赖", "翻车", "手撕", "偷漏税", "劈腿")):
        action = "去评论区骂/倒苦水"
    else:
        action = "截图某句人间清醒发朋友圈"

    return {
        "self_relevance": self_rel,
        "emotional_outlet": outlet,
        "one_liner_conflict": conflict,
        "expected_action": action,
    }


def format_projection_card_markdown(card: Mapping[str, Any]) -> str:
    """渲染为供人类审阅或注入 Prompt 的 Markdown 文本。"""
    c = card or {}
    lines = [
        "### 🎯 【动笔前投射对焦卡 (Projection Alignment Card)】",
        f"- **1. 关读者屁事 (Self-Relevance)**：{c.get('self_relevance', '未填写')}",
        f"- **2. 情绪出口 (Emotional Outlet)**：{c.get('emotional_outlet', '未填写')}",
        f"- **3. 一句话矛盾 (One-Liner Conflict)**：{c.get('one_liner_conflict', '未填写')}",
        f"- **4. 预期读者动作 (Expected Action)**：【{c.get('expected_action', '未指定')}】",
    ]
    if c.get("fresh_reality_anchor"):
        lines.append(f"- **5. 当下现实增量触点 (Reality Anchor)**：{c['fresh_reality_anchor']}")
    return "\n".join(lines) + "\n"
