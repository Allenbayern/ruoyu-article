"""title_funnel: 标题漏斗与文案实验室（Title Funnel & Copywriting Lab）

将爆款标题 5 大套路与人类心理弱点工程化落地：
1. 套路A：打破认知与常识悬念（Curiosity Gap）
2. 套路B：情绪共鸣与扎心宣泄（Emotional Resonance）
3. 套路C：利益相关与现实账本（Self-Interest Ledger）
4. 套路D：极端反差与身份错位（Extreme Contrast）
5. 套路E：数字量化与具象事实（Concrete Numbers）

核心功能：
- 严格体检单条标题：微信手机端折行敏感度（≤28字）、违禁虚词过滤、现实利益/刺激关键词密度
- 生成或规范化 10 个候选标题包（覆盖 5 大套路，且提供 A/B 测情绪型 vs 悬念型备选）
"""
from __future__ import annotations

import re
from typing import Any, Mapping

# 微信订阅号列表页标题黄金长度（手机端 2 行不被截断）
TITLE_MAX_LEN = 28
TITLE_OPTIMAL_MIN = 16
TITLE_OPTIMAL_MAX = 26

# 严禁在自媒体长文标题中出现的公文、学术、假大空与伪深刻八股虚词
FORBIDDEN_EMPTY_WORDS = (
    "浅析",
    "浅谈",
    "探讨",
    "何去何从",
    "时代画卷",
    "深刻启示",
    "值得深思",
    "引人注目",
    "不可否认",
    "毋庸置疑",
    "赋能",
    "闭环",
    "破局",
    "维度",
    "视阈",
    "探微",
)

# 现实利益、账本与情绪刺激关键词表
LEDGER_AND_STIMULUS_WORDS = (
    "万", "亿", "元", "美元", "房贷", "月供", "账本", "算盘", "筹码", "代价",
    "遮羞布", "撕下", "底牌", "开销", "身价", "片酬", "票房", "崩塌", "翻车",
    "疯", "狠", "惨", "假", "骗局", "断供", "清算", "体面", "老实人", "坑",
    "谁", "不敢", "凭什么", "到底", "为何", "揭开", "扎心", "代价", "痛"
)

# 五大套路分类元数据
TITLE_PATTERNS = {
    "pattern_A": {
        "code": "A",
        "name": "打破认知与常识悬念",
        "trigger": "打破认知/求知欲",
        "desc": "打破大众既有常识认知或直指隐秘真相，引发'非看不可'的好奇悬念。",
        "formula": "【反常识事实】+【追问动机/真相】：到底为什么/扯下了谁的遮羞布？",
    },
    "pattern_B": {
        "code": "B",
        "name": "情绪共鸣与扎心宣泄",
        "trigger": "情绪共鸣/宣泄压抑",
        "desc": "直击普通人生活深处的委屈、不甘与焦虑，把读者心头憋着的闷气化为利刃。",
        "formula": "【痛点困境】+【扎心共鸣】：戳破了多少人不敢面对的体面",
    },
    "pattern_C": {
        "code": "C",
        "name": "利益相关与现实账本",
        "trigger": "利益相关/生存危机",
        "desc": "剥离虚浮光环，把明星或剧情事件投射到读者每天面对的柴米油盐房贷生存账本。",
        "formula": "【具体阶层/人群】+【生存账本/代价】：这笔血汗账普通人怎么算？",
    },
    "pattern_D": {
        "code": "D",
        "name": "极端反差与身份错位",
        "trigger": "极端反差/戏剧张力",
        "desc": "剧烈两极对撞：台前体面 vs 台后狼狈、昔日顶流 vs 现实落魄、慈眉善目 vs 机关算尽。",
        "formula": "【高光起点】到【荒诞结果】：从万人追捧到满盘皆输，全在算计中",
    },
    "pattern_E": {
        "code": "E",
        "name": "数字量化与具象事实",
        "trigger": "数字悬念/确凿证据",
        "desc": "利用冷酷、具象的真实数字与时间节点制造冲击力，杜绝模糊概括。",
        "formula": "【精确数字/时间】+【颠覆性结局】：上映X天腰斩Y万/整整赔了Z年",
    },
}


def audit_title_health(title: str) -> dict[str, Any]:
    """对单条标题进行严格体检（手机端折行敏感度、违禁虚词、现实利益关键词）。"""
    t = str(title or "").strip()
    errors: list[str] = []
    warnings: list[str] = []

    # 1. 字数长度体检（手机端折行敏感度 ≤ 28 字）
    length = len(t)
    if length == 0:
        return {
            "passed": False,
            "title": "",
            "length": 0,
            "errors": ["title_empty"],
            "warnings": [],
            "ledger_keywords": [],
        }

    if length > TITLE_MAX_LEN:
        errors.append(f"title_too_long_{length}_max_{TITLE_MAX_LEN}")
    elif length < TITLE_OPTIMAL_MIN:
        warnings.append(f"title_too_short_{length}_min_{TITLE_OPTIMAL_MIN}")

    # 2. 违禁虚词与八股过滤
    hit_empty_words = [w for w in FORBIDDEN_EMPTY_WORDS if w in t]
    if hit_empty_words:
        errors.append(f"forbidden_empty_words:{','.join(hit_empty_words)}")

    # 3. 现实利益与刺激度关键词密度
    matched_ledger = [w for w in LEDGER_AND_STIMULUS_WORDS if w in t]
    if not matched_ledger:
        warnings.append("lacks_ledger_or_stimulus_keywords")

    return {
        "passed": len(errors) == 0,
        "title": t,
        "length": length,
        "is_optimal_length": TITLE_OPTIMAL_MIN <= length <= TITLE_OPTIMAL_MAX,
        "errors": errors,
        "warnings": warnings,
        "hit_empty_words": hit_empty_words,
        "ledger_keywords": matched_ledger,
    }


def generate_title_candidates_10(
    work: str,
    killer_stance: str,
    *,
    facts: list[str] | None = None,
    projection_card: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """依据 5 大套路矩阵，为指定作品与立场生成 10 个结构化候选标题（每套路 2 个）。"""
    w = work.strip()
    s = killer_stance.strip()
    f_list = facts or []

    # 提取一些数字或特定事实词
    digits_found = []
    for f in f_list:
        found = re.findall(r"\d+[\w\u4e00-\u9fa5]*", str(f))
        digits_found.extend(found)
    primary_num = digits_found[0] if digits_found else "数千万"

    raw_candidates = [
        # 套路A：打破认知与常识悬念 (2个)
        {
            "pattern_type": "pattern_A",
            "title": f"豆瓣至今不敢开分：{w}到底扯下了谁的遮羞布？",
        },
        {
            "pattern_type": "pattern_A",
            "title": f"为什么所有人都看走眼了？{w}藏着最狠的人性算盘",
        },
        # 套路B：情绪共鸣与扎心宣泄 (2个)
        {
            "pattern_type": "pattern_B",
            "title": f"看哭无数老实人：{w}戳破了多少人不敢面对的伪善",
        },
        {
            "pattern_type": "pattern_B",
            "title": f"看完心里那口气终于顺了：{w}把虚伪体面踩得粉碎",
        },
        # 套路C：利益相关与现实账本 (2个)
        {
            "pattern_type": "pattern_C",
            "title": f"月薪两万也撑不起这体面：{w}算透了普通人的生存代价",
        },
        {
            "pattern_type": "pattern_C",
            "title": f"台前全是温情脉脉，台后全在算计利益：这笔血汗账怎么算？",
        },
        # 套路D：极端反差与身份错位 (2个)
        {
            "pattern_type": "pattern_D",
            "title": f"从风光无限到满盘皆输：{w}撕开名利场最残酷底牌",
        },
        {
            "pattern_type": "pattern_D",
            "title": f"慈眉善目却机关算尽：{w}把恶人账本算到了骨子里",
        },
        # 套路E：数字量化与具象事实 (2个)
        {
            "pattern_type": "pattern_E",
            "title": f"豪掷{primary_num}换来一声叹息：{w}这笔现实账本谁来买单？",
        },
        {
            "pattern_type": "pattern_E",
            "title": f"上映3天口碑两极反转：{w}到底动了谁的奶酪？",
        },
    ]

    candidates = []
    for item in raw_candidates:
        p_info = TITLE_PATTERNS[item["pattern_type"]]
        exam = audit_title_health(item["title"])
        # 如果超长，进行智能剪裁至 28 字内
        if exam["length"] > TITLE_MAX_LEN:
            t_short = item["title"][:TITLE_MAX_LEN]
            exam = audit_title_health(t_short)
            item["title"] = t_short

        candidates.append({
            "title": item["title"],
            "pattern_type": item["pattern_type"],
            "pattern_name": p_info["name"],
            "psychological_trigger": p_info["trigger"],
            "length": exam["length"],
            "passed_health_check": exam["passed"],
            "health_exam": exam,
        })

    return candidates


def build_title_funnel_pack(
    work: str,
    killer_stance: str,
    *,
    case_id: str = "case-unknown",
    facts: list[str] | None = None,
    projection_card: Mapping[str, Any] | None = None,
    selected_index: int = 0,
) -> dict[str, Any]:
    """完整组装标题漏斗文案实验室包（title-pack.json 兼容升级版）。"""
    candidates = generate_title_candidates_10(
        work,
        killer_stance,
        facts=facts,
        projection_card=projection_card,
    )

    # 选定主标题
    idx = max(0, min(selected_index, len(candidates) - 1))
    selected = candidates[idx]

    # 挑选 A/B 测备选（偏情绪型 vs 偏悬念型）
    emotional_candidates = [c for c in candidates if c["pattern_type"] in ("pattern_B", "pattern_C")]
    suspense_candidates = [c for c in candidates if c["pattern_type"] in ("pattern_A", "pattern_E")]

    variant_a = emotional_candidates[0]["title"] if emotional_candidates else candidates[2]["title"]
    variant_b = suspense_candidates[0]["title"] if suspense_candidates else candidates[0]["title"]

    # 4字封面视觉钩子
    cover_hooks = ["不敢开分", "算透底牌", "体面崩塌", "现实账本"]

    return {
        "case_id": case_id,
        "work": work,
        "killer_stance": killer_stance,
        "selected_title": selected["title"],
        "selected_title_length": selected["length"],
        "length_limit": TITLE_MAX_LEN,
        "is_valid_length": selected["length"] <= TITLE_MAX_LEN,
        "selected_pattern": {
            "type": selected["pattern_type"],
            "name": selected["pattern_name"],
            "trigger": selected["psychological_trigger"],
        },
        "ab_test_recommendations": {
            "variant_A_emotional": {
                "title": variant_a,
                "strategy": "偏情绪痛点型，适合朋友圈私域扩散与评论区倒苦水",
            },
            "variant_B_suspense": {
                "title": variant_b,
                "strategy": "偏悬念反常识型，适合公域信息流滑屏拦截与即刻点击",
            },
        },
        "title_candidates_10": candidates,
        "cover_four_word_hooks": cover_hooks,
        "patterns_catalog": TITLE_PATTERNS,
    }
