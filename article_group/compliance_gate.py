"""Three-state social-topic compliance gate with graded rules and angle library.

This module implements Allen's refined social-topic compliance boundary
(2026-08-02, after repeated Toutiao violations). Three-state judgment
(PASS/CONDITIONAL/FAIL) with graded rules per gate makes it easier to find
compliant angles instead of outright dropping topics.

Design principles:
- The S1 controller's structured declaration (`five_gates`) is AUTHORITATIVE.
  This module validates structure and consistency, and enforces hard rules.
- `grade_five_gates` is an automatic keyword-based cross-check (aid). It NEVER
  blocks a pool by itself; mismatches are surfaced as warnings so the
  controller double-checks borderline candidates.
- Enforcement rules (hard errors):
  * social candidate must declare a five-gates dict
  * each gate value must be PASS / CONDITIONAL / FAIL
  * `overall` must be consistent with the per-gate declaration
  * overall FAIL + recommendation A/B/C is rejected
  * overall CONDITIONAL + recommendation A/B/C requires a `compliant_angle`
- Mechanical text scan uses combination scoring to reduce noise.
"""

from __future__ import annotations

import re
from typing import Any

# Three-state values
GRADE_PASS = "PASS"
GRADE_CONDITIONAL = "CONDITIONAL"
GRADE_FAIL = "FAIL"
VALID_GRADES = {GRADE_PASS, GRADE_CONDITIONAL, GRADE_FAIL}
VALID_RECOMMENDATIONS = {"A", "B", "C", "Archive", "Reject", "Wait"}

GATE_KEYS = (
    "gate1_news_license",
    "gate2_privacy",
    "gate3_judicial",
    "gate4_copyright",
    "gate5_sensationalism",
)

SOCIAL_TOPIC_TYPE = "social"

# Mechanical redline scan (aid only): privacy-adjacent terms, judicial
# predetermination phrases, and sensational numeric patterns learned from the
# negative sample 《出生仅差55分钟被错抱…》, the 姚策 causal-language case, and
# the 343斤网红 (body-weight sensationalism) case.
_PRIVACY_TERMS = (
    "抱错", "亲子鉴定", "抑郁症", "抑郁", "离婚",
    "出轨", "破产", "病历", "重病", "绝症", "欠债",
    "自杀", "轻生", "家暴", "婚内", "私生子", "精神病",
    "确诊", "病情", "住院", "手术", "癌症", "化疗",
    "收入", "房贷", "彩礼", "失业", "贫困", "低保",
)
_JUDICIAL_PREDICT_TERMS = (
    "免责理由", "突破时效", "应当赔偿", "必须负责", "医院失职",
    "有罪", "犯罪", "错抱导致", "因错抱",
    "罪有应得", "死有余辜", "必须判", "应当判",
    "应负全责", "负有责任", "逃不掉", "等着赔偿",
)
_SENSATIONAL_PATTERNS = (
    (re.compile(r"\d{2,}分钟"), "minutes_gap"),
    (re.compile(r"仅差\d+"), "narrow_gap"),
    (re.compile(r"不到?\d+公里|\d+公里"), "distance_claim"),
    (re.compile(r"\d{2,}年后?发现|\d{2,}年才"), "years_later_found"),
    (re.compile(r"\d{3,}斤"), "body_weight"),
    (re.compile(r"惨不忍睹|触目惊心|太惨了|看哭|泪目|心碎"), "suffering_pileup"),
    (re.compile(r"反转|惊天|骇人听闻|匪夷所思"), "shock_bait"),
)

# Predefined compliant angles for CONDITIONAL candidates. 建议角度库：
# 当某一门为 CONDITIONAL 时优先推荐对应角度。
PREDEFINED_ANGLES = [
    "制度观察：从该事件看相关政策执行与公众反应",
    "消费/平台现象：用户行为变化背后的平台机制",
    "公开数据反常：数据异常波动所指向的社会结构变化",
    "文旅/影视跨界：事件中的文化IP或旅游资源联动视角",
    "生活评论：普通人日常经验中的共鸣与不易",
    "职场/教育/养老：特定人群生态中的共性问题与改善方向",
    "技术演进：新技术/新功能在社会场景中的实际影响",
    "环境可持续：事件背后的资源使用与生态影响评估",
]

# 角度库按"哪一扇门为 CONDITIONAL"的推荐映射（用于 suggest_compliant_angles）。
_ANGLE_FOR_CONDITIONAL_GATE = {
    "gate1_news_license": [0, 1, 4],      # 制度观察 / 平台现象 / 生活评论
    "gate2_privacy": [0, 4, 5],           # 制度观察 / 生活评论 / 职场教育养老
    "gate3_judicial": [0, 2, 3],          # 制度观察 / 数据反常 / 文旅影视
    "gate4_copyright": [0, 1, 2],         # 制度观察 / 平台现象 / 数据反常
    "gate5_sensationalism": [0, 2, 4],    # 制度观察 / 数据反常 / 生活评论
}


def _gather_text(candidate: dict[str, Any]) -> str:
    """Collect free-text fields for keyword grading."""
    parts = [
        str(candidate.get("title", "")),
        str(candidate.get("angle", "")),
        str(candidate.get("work", "")),
    ]
    return " ".join(parts)


def _grade_gate_news_license(text: str) -> str:
    """gate1 新闻资质：
    PASS: 制度观察/生活评论/已公开事实评论（无独家、无调查、无未证实消息）
    CONDITIONAL: 有"调查/深度/追踪/突发"等字眼，但可改写角度
    FAIL: 个人号新闻式现场报道、独家爆料、未证实消息传播
    """
    fail_phrases = (
        "独家报道", "独家消息", "独家专访", "独家获悉", "独家爆料",
        "内部消息", "首次曝光", "现场直击", "第一时间",
    )
    if any(p in text for p in fail_phrases):
        return GRADE_FAIL

    conditional_phrases = ("调查", "深度", "追踪", "连续报道", "突发", "紧急", "实时更新", "进展")
    if any(p in text for p in conditional_phrases):
        return GRADE_CONDITIONAL

    return GRADE_PASS


def _grade_gate_privacy(text: str) -> str:
    """gate2 隐私：
    PASS: 已公开事实、公众人物公开行为、化名处理的敏感信息
    CONDITIONAL: 出现疾病/婚姻/家庭等敏感词但可最小化处理
    FAIL: 普通人未公开隐私细节（具体病历/离婚协议/收入/住址/身份证等）
    """
    fail_indicators = (
        "确诊", "病历", "手术记录", "精神病诊断",
        "离婚协议", "出轨证据", "财产分割", "债务明细",
        "工资收入", "房产信息", "存款数额", "贷款记录",
        "亲子鉴定报告", "家庭住址", "身份证号码", "电话号码",
    )
    if any(i in text for i in fail_indicators):
        return GRADE_FAIL

    conditional_terms = (
        "疾病", "病情", "症状", "治疗", "住院", "手术",
        "婚姻", "离婚", "出轨", "恋爱", "分手",
        "家庭", "子女", "怀孕", "流产",
        "收入", "工资", "奖金", "房贷", "租金",
    )
    if any(t in text for t in conditional_terms):
        return GRADE_CONDITIONAL

    return GRADE_PASS


def _grade_gate_judicial(text: str) -> str:
    """gate3 司法：
    PASS: 已有明确处理结果/已判决案件、仅描述程序进展不预判责任
    CONDITIONAL: 进行时案件但可写制度层面不涉及具体责任归属
    FAIL: 未决案件进行责任预判、突破时效说辞、暗示判决结果
    """
    hard_fail_phrases = (
        "应当赔偿", "必须负责", "应负全责", "逃不掉",
        "罪有应得", "死有余辜", "必须判", "应当判",
        "突破时效", "时效未过", "应担责任", "该赔",
        "责任在", "该负责", "应惩罚", "该处罚",
    )
    if any(p in text for p in hard_fail_phrases):
        return GRADE_FAIL

    conditional_phrases = (
        "开庭", "审理中", "一审", "二审", "再审",
        "上诉", "申诉", "调解", "和解",
        "警方立案", "检察院", "法院受理",
    )
    if any(p in text for p in conditional_phrases):
        return GRADE_CONDITIONAL

    return GRADE_PASS


def _grade_gate_copyright(text: str) -> str:
    """gate4 版权来源：
    PASS: 原创撰写、明显引用来源、改写不构成实质性相似
    CONDITIONAL: 需要加重引用或改写比例（出现"据报道/网传"等）
    FAIL: 直接复制、改写不足、未标明来源
    """
    fail_indicators = (
        "据不完全统计", "多方证实", "多位知情人士透露",
        "知情人士称", "内部人士透露", "可靠消息源", "知情人爆料",
    )
    if any(i in text for i in fail_indicators):
        return GRADE_FAIL

    conditional_indicators = ("据报道", "根据", "消息称", "传闻", "网传", "微博爆料", "朋友圈传播")
    if any(i in text for i in conditional_indicators):
        return GRADE_CONDITIONAL

    return GRADE_PASS


def _grade_gate_sensationalism(text: str) -> str:
    """gate5 猎奇风险：
    PASS: 理性评论、数据背后原因分析、生活化切入
    CONDITIONAL: 有标题党倾向但可改为中性表述
    FAIL: 纯苦难堆砌 + 数字堆砌、无原因分析的悲惨细节积累
    """
    suffer_terms = (
        "惨不忍睹", "触目惊心", "太惨了", "看哭", "泪目", "心碎",
        "家破人亡", "妻离子散", "一贫如洗", "举债度日",
    )
    number_patterns = [
        re.compile(r"\d{2,}分钟"),
        re.compile(r"仅差\d+"),
        re.compile(r"不到?\d+公里|\d+公里"),
        re.compile(r"\d{2,}年后?发现|\d{2,}年才"),
        re.compile(r"\d{3,}斤"),
    ]
    suffer_count = sum(1 for t in suffer_terms if t in text)
    number_count = sum(1 for p in number_patterns if p.search(text))

    if (suffer_count >= 2 and number_count >= 2) or suffer_count >= 3:
        return GRADE_FAIL

    conditional_phrases = (
        "震惊", "爆炸", "巨大反转", "意外转折", "没想到",
        "揭秘", "真相", "内幕", "不得不看",
        "血泪", "悲惨", "凄凉",
    )
    if any(p in text for p in conditional_phrases):
        return GRADE_CONDITIONAL

    return GRADE_PASS


_GATE_GRADERS = {
    "gate1_news_license": _grade_gate_news_license,
    "gate2_privacy": _grade_gate_privacy,
    "gate3_judicial": _grade_gate_judicial,
    "gate4_copyright": _grade_gate_copyright,
    "gate5_sensationalism": _grade_gate_sensationalism,
}


def grade_five_gates(candidate: dict[str, Any]) -> dict[str, str]:
    """Auto-grade a candidate's five gates from its free text (aid only).

    Returns a dict with gate1..gate5 and 'overall'. Non-social candidates
    return an empty dict.
    """
    topic_type = str(candidate.get("topic_type", "")).strip().lower()
    if topic_type != SOCIAL_TOPIC_TYPE:
        return {}

    text = _gather_text(candidate)
    grades: dict[str, str] = {}
    for key in GATE_KEYS:
        grader = _GATE_GRADERS.get(key)
        grades[key] = grader(text) if grader else GRADE_PASS

    if any(v == GRADE_FAIL for v in grades.values()):
        overall = GRADE_FAIL
    elif any(v == GRADE_CONDITIONAL for v in grades.values()):
        overall = GRADE_CONDITIONAL
    else:
        overall = GRADE_PASS
    grades["overall"] = overall
    return grades


def crosscheck_five_gates(candidate: dict[str, Any]) -> list[str]:
    """Return WARNINGS when the declared grades differ from auto-grading.

    These are advisory only — they never block a pool. They prompt the
    controller to double-check a borderline candidate.
    """
    warnings: list[str] = []
    cid = candidate.get("candidate_id", "unknown")
    topic_type = str(candidate.get("topic_type", "")).strip().lower()
    if topic_type != SOCIAL_TOPIC_TYPE:
        return warnings

    declared = candidate.get("five_gates")
    if not isinstance(declared, dict):
        return warnings  # missing declaration is a hard error elsewhere

    expected = grade_five_gates(candidate)
    for key in GATE_KEYS:
        if key in declared and key in expected:
            if declared[key] != expected[key]:
                warnings.append(
                    f"candidate_{cid}_crosscheck_gate_{key}_declared_{declared[key]}_autograde_{expected[key]}"
                )
    if "overall" in declared and "overall" in expected:
        if declared["overall"] != expected["overall"]:
            warnings.append(
                f"candidate_{cid}_crosscheck_overall_declared_{declared['overall']}_autograde_{expected['overall']}"
            )
    return warnings


def suggest_compliant_angles(candidate: dict[str, Any]) -> list[str]:
    """Return suggested compliant angles for a CONDITIONAL candidate.

    Prefers angles mapped to the gates that are currently CONDITIONAL.
    Returns an empty list for PASS / FAIL / non-social candidates.
    """
    topic_type = str(candidate.get("topic_type", "")).strip().lower()
    if topic_type != SOCIAL_TOPIC_TYPE:
        return []

    expected = grade_five_gates(candidate)
    if expected.get("overall") != GRADE_CONDITIONAL:
        return []

    conditional_gates = [k for k in GATE_KEYS if expected.get(k) == GRADE_CONDITIONAL]
    suggested_indices: list[int] = []
    for gate in conditional_gates:
        for idx in _ANGLE_FOR_CONDITIONAL_GATE.get(gate, []):
            if idx not in suggested_indices:
                suggested_indices.append(idx)

    # Fill with the general library if fewer than 3 suggestions
    for idx in range(len(PREDEFINED_ANGLES)):
        if len(suggested_indices) >= 3:
            break
        if idx not in suggested_indices:
            suggested_indices.append(idx)

    return [PREDEFINED_ANGLES[i] for i in suggested_indices]


def validate_five_gates(candidate: dict[str, Any]) -> list[str]:
    """Return deterministic ERRORS for a candidate's five-gates declaration.

    Only social-topic candidates are enforced. Hard rules:
    - declaration required
    - each gate value in {PASS, CONDITIONAL, FAIL}
    - `overall` (or legacy `result`) consistent with per-gate declaration
    - recommendation must be a declared string value
    - overall FAIL cannot recommend A/B/C
    - overall CONDITIONAL + A/B/C requires a compliant_angle
    """
    errors: list[str] = []
    cid = candidate.get("candidate_id", "unknown")
    topic_type = str(candidate.get("topic_type", "")).strip().lower()
    if topic_type != SOCIAL_TOPIC_TYPE:
        return errors

    gates = candidate.get("five_gates")
    if not isinstance(gates, dict) or not gates:
        return [f"candidate_{cid}_social_topic_requires_five_gates"]

    for key in GATE_KEYS:
        declared = gates.get(key)
        if declared not in VALID_GRADES:
            errors.append(f"candidate_{cid}_invalid_gate_{key}")

    if errors:
        return errors  # skip consistency checks on malformed declarations

    failed = [key for key in GATE_KEYS if gates.get(key) == GRADE_FAIL]
    conditional = [key for key in GATE_KEYS if gates.get(key) == GRADE_CONDITIONAL]

    if failed:
        expected_overall = GRADE_FAIL
    elif conditional:
        expected_overall = GRADE_CONDITIONAL
    else:
        expected_overall = GRADE_PASS

    declared_overall = gates.get("overall")
    legacy_result = gates.get("result")
    if declared_overall is None:
        declared_overall = legacy_result
    elif legacy_result is not None and legacy_result != declared_overall:
        errors.append(
            f"candidate_{cid}_overall_conflicts_with_result_"
            f"overall_{declared_overall}_result_{legacy_result}"
        )

    if declared_overall not in VALID_GRADES:
        errors.append(f"candidate_{cid}_invalid_overall_{declared_overall}")
        return errors

    if declared_overall != expected_overall:
        errors.append(
            f"candidate_{cid}_overall_inconsistent_declared_{declared_overall}_expected_{expected_overall}"
        )

    recommendation = candidate.get("recommendation")
    if not isinstance(recommendation, str) or recommendation not in VALID_RECOMMENDATIONS:
        errors.append(f"candidate_{cid}_invalid_recommendation")
        return errors

    if expected_overall == GRADE_FAIL and recommendation in ("A", "B", "C"):
        errors.append(f"candidate_{cid}_failed_gate_cannot_recommend_{recommendation}")

    if expected_overall == GRADE_CONDITIONAL and recommendation in ("A", "B", "C"):
        angle = candidate.get("compliant_angle")
        if not isinstance(angle, str) or not angle.strip():
            errors.append(f"candidate_{cid}_conditional_requires_compliant_angle")

    return errors


def validate_pool_five_gates(pool: dict[str, Any]) -> list[str]:
    """Validate the five-gates declaration of every candidate in a pool."""
    errors: list[str] = []
    candidates = pool.get("candidates", []) if isinstance(pool, dict) else []
    if not isinstance(candidates, list):
        return ["candidates_must_be_a_list"]
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            errors.append(f"candidate_record_{index}_must_be_a_dict")
            continue
        errors.extend(validate_five_gates(candidate))
    return errors


def crosscheck_pool_five_gates(pool: dict[str, Any]) -> list[str]:
    """Return cross-check warnings for every candidate in a pool."""
    warnings: list[str] = []
    candidates = pool.get("candidates", []) if isinstance(pool, dict) else []
    if not isinstance(candidates, list):
        return warnings
    for candidate in candidates:
        if isinstance(candidate, dict):
            warnings.extend(crosscheck_five_gates(candidate))
    return warnings


def scan_social_redlines(text: str) -> list[str]:
    """Return redline signals found in free text (mechanical aid only).

    Noise-reduced: high-confidence hits require signals from TWO different
    categories (privacy + judicial / privacy + sensational / judicial +
    sensational). Single-category signals are reported as low-confidence
    hints only.
    """
    if not text:
        return []

    privacy_hits = [t for t in _PRIVACY_TERMS if t in text]
    judicial_hits = [t for t in _JUDICIAL_PREDICT_TERMS if t in text]
    sensational_hits = [tag for pattern, tag in _SENSATIONAL_PATTERNS if pattern.search(text)]

    hits: list[str] = []

    if privacy_hits and judicial_hits:
        for p in privacy_hits[:2]:
            for j in judicial_hits[:2]:
                hits.append(f"combo:privacy+judicial:{p}+{j}")
    if privacy_hits and sensational_hits:
        for p in privacy_hits[:2]:
            for s in sensational_hits[:2]:
                hits.append(f"combo:privacy+sensational:{p}+{s}")
    if judicial_hits and sensational_hits:
        for j in judicial_hits[:2]:
            for s in sensational_hits[:2]:
                hits.append(f"combo:judicial+sensational:{j}+{s}")

    if privacy_hits and not (privacy_hits and judicial_hits) and not (privacy_hits and sensational_hits):
        hits.extend(f"hint:privacy_term:{t}" for t in privacy_hits[:3])
    if judicial_hits and not (judicial_hits and privacy_hits) and not (judicial_hits and sensational_hits):
        hits.extend(f"hint:judicial_predict:{t}" for t in judicial_hits[:3])
    if sensational_hits and not (sensational_hits and privacy_hits) and not (sensational_hits and judicial_hits):
        hits.extend(f"hint:sensational:{tag}" for tag in sensational_hits[:3])

    return hits


__all__ = [
    "GRADE_PASS",
    "GRADE_CONDITIONAL",
    "GRADE_FAIL",
    "VALID_GRADES",
    "GATE_KEYS",
    "PREDEFINED_ANGLES",
    "grade_five_gates",
    "crosscheck_five_gates",
    "suggest_compliant_angles",
    "validate_five_gates",
    "validate_pool_five_gates",
    "crosscheck_pool_five_gates",
    "scan_social_redlines",
]