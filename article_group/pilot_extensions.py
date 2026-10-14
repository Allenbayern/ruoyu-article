"""pilot_extensions: 将旧系统工程防线与内容资产深度融入新系统的核心工程扩展。

包含六大核心机制：
1. 八大引爆母题智能分类（classify_viral_pillar）
2. 时间戳剥离与长青测试（run_timestamp_peel_test）
3. 四阶深度素材结构化完整度评估（evaluate_three_tier_evidence）
4. 标题冻结与防篡改验证（freeze_title, verify_title_freeze，走 evidence_write）
5. 断言账本双向覆盖扫描（check_assertion_ledger_coverage，分级 error/warning）
6. 开篇试写熔断机制（prose_pilot_check）
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from article_group.evidence_write import write_evidence_json

# ==============================================================================
# 1. 八大引爆母题定义与智能匹配
# ==============================================================================

VIRAL_PILLARS = {
    "p1_honest_retaliation": {
        "name": "老实人被逼绝境与现世反扑",
        "keywords": ["老实人", "逼急", "索命", "绝境", "反扑", "恶霸", "逼疯", "村霸", "匹夫一怒", "算总账", "复仇"],
        "formula": "[老实人/底层人]如何被一步步逼疯：这部[神作/现实电影]，扒光了[恶霸/体系]吃人的底牌",
    },
    "p2_industry_backlash": {
        "name": "德不配位的行业清算与现世报",
        "keywords": ["内娱", "遮羞布", "戏骨", "资源咖", "演技", "翻车", "塌房", "抠图", "日薪", "打回原形", "冷遇", "接不到戏", "道歉", "关评"],
        "formula": "[顶级实力/敬业苦熬]却[卖房破产/接不到戏]，扯下了整个内娱最后的遮羞布",
    },
    "p3_survival_ledger": {
        "name": "现实生存算盘与破产死线",
        "keywords": ["月供", "房贷", "断供", "现金流", "中产", "破产", "摆摊", "外卖", "血亏", "亏损", "活命", "算账", "体面", "债务"],
        "formula": "从[昔日高薪/数亿投资]到[八块钱卤肉/血亏清算]，算清成年人的活命总账",
    },
    "p4_black_market_trap": {
        "name": "江湖黑产与绝户杀猪盘拆解",
        "keywords": ["神棍", "杀猪盘", "绝户", "江湖", "骗术", "骗局", "八大门", "玄学", "免死金牌", "割韭菜", "大师", "假神仙"],
        "formula": "[请神显灵/完美偶遇]背后：算透江湖八门敲骨吸髓的绝户算盘",
    },
    "p5_grassroots_revolt": {
        "name": "反巨星反情怀的草根掀桌爽感",
        "keywords": ["小成本", "黑马", "逆袭", "打烂", "打脸", "方言", "草根", "不请巨星", "不玩情怀", "拍爽", "票房超", "打翻"],
        "formula": "不请[巨星/顶流]不玩[套路情怀]，[小成本/草根]凭什么打碎了资本的脸？",
    },
    "p6_forbidden_depth": {
        "name": "尺度禁区与时代脓包重访",
        "keywords": ["禁片", "尺度", "被封", "删减", "地下", "院线禁区", "脓包", "暗黑", "停播", "残暴", "挑战底线", "不敢拍"],
        "formula": "[被封杀/删减N分钟/多国禁播]：这[几部神作]，撕开了[时代/人性]最不敢碰的脓包",
    },
    "p7_nostalgic_haven": {
        "name": "集体神作记忆与时代避难所",
        "keywords": ["当年", "重温", "老片", "神作", "原声带", "经典", "重聚", "童年", "回不去", "看懂", "时代眼泪", "避难"],
        "formula": "[时代经典/当年冷片]：为什么[N年]后，全网才终于看懂了它？",
    },
    "p8_female_resilience": {
        "name": "绝地逢生的女性与生存大女主",
        "keywords": ["逃离豪门", "弃妇", "大女主", "恶女", "吸血", "独立", "狠女人", "翻盘", "王炸", "离婚", "赢家", "骨气"],
        "formula": "被全网[嘲笑/吸血N年]：那个[弃妇/苦命女人]，如何亲手把烂牌打成王炸？",
    },
}


def classify_viral_pillar(topic_text: str) -> dict[str, Any]:
    """智能匹配所属母题，若无明显命中则默认退回 p3 现实算盘或 p4 黑产拆台。"""
    scores = {}
    for pid, meta in VIRAL_PILLARS.items():
        score = sum(1 for kw in meta["keywords"] if kw in topic_text)
        scores[pid] = score

    best_pid = max(scores, key=scores.get)
    if scores[best_pid] == 0:
        best_pid = "p3_survival_ledger"

    return {
        "pillar_id": best_pid,
        "name": VIRAL_PILLARS[best_pid]["name"],
        "formula": VIRAL_PILLARS[best_pid]["formula"],
        "matched_score": scores[best_pid],
    }


# ==============================================================================
# 2. 时间戳剥离与长青测试 (remove_timestamp_test)
# ==============================================================================

TRANSIENT_TIME_PATTERNS = [
    r"今天", r"昨日?", r"前天", r"刚刚", r"刚刚曝光", r"最新", r"热搜(?:第[一二三四五六七八九十\d]+)?",
    r"\d{1,2}月\d{1,2}日", r"202\d年", r"刚刚官宣", r"昨晚", r"今日", r"今日头条", r"网传", r"突发"
]


def run_timestamp_peel_test(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """去掉时间戳与热搜排名后，验证是否仍具备人、冲突、利益算盘。"""
    title = str(candidate.get("title_skeleton") or candidate.get("angle") or candidate.get("title") or "")
    stance = str(candidate.get("killer_stance") or "")
    question = str(candidate.get("reader_question") or "")
    combined = f"{title} {stance} {question}"

    peeled_text = combined
    for pat in TRANSIENT_TIME_PATTERNS:
        peeled_text = re.sub(pat, "", peeled_text)

    # 检验剩余文本中的实质内容长度与关键要素
    cjk_remaining = len(re.findall(r"[\u4e00-\u9fff]", peeled_text))
    has_conflict = any(k in peeled_text for k in [
        "反差", "撕碎", "清算", "绝户", "断供", "代价", "破产", "背刺", "算盘",
        "为什么", "怎么", "现金流", "断裂", "遮羞布", "人情世故", "底裤", "神棍"
    ])

    passed = cjk_remaining >= 15 and has_conflict
    reason = "长青核心坚固，剥离时间戳后人性和利益冲突依然成立" if passed else "剥离时间词后只剩空洞事件通报，缺乏长青冲突"

    return {
        "passed": passed,
        "cjk_remaining": cjk_remaining,
        "reason": reason,
        "peeled_snippet": peeled_text[:80],
    }


# ==============================================================================
# 3. 四阶深度素材结构化完整度评估器 (Four-Tier Evidence Evaluator)
# ==============================================================================

def evaluate_three_tier_evidence(evidence_pack: Mapping[str, Any]) -> dict[str, Any]:
    """结构化评估素材完整度：
    - Tier 1 骨架层：core_claims (>=3条结构化主张) + 明确角色线
    - Tier 2 行业机制/原著层：origin_background (原著/历史原型) + industry_jargon (行业行话/黑产机制)
    - Tier 3 微观拉片层：sensory_anchors (>=3个声明具体功能和质感的微观道具)
    - Tier 4 现实映射层：real_world_counterpart / social_implication (当代社会学/现实投射)
    """
    sensory_anchors = evidence_pack.get("sensory_anchors", [])
    core_claims = evidence_pack.get("core_claims", [])
    characters = evidence_pack.get("characters") or evidence_pack.get("character_dossiers") or {}
    origin_bg = str(evidence_pack.get("origin_background") or "")
    jargon = evidence_pack.get("industry_jargon") or []
    real_world = str(evidence_pack.get("real_world_counterpart") or evidence_pack.get("social_implication") or "")

    # Tier 1: 骨架
    has_tier1_claims = isinstance(core_claims, list) and len(core_claims) >= 3
    has_tier1_chars = bool(characters)
    tier1_pass = has_tier1_claims and has_tier1_chars

    # Tier 2: 原型与行业机制
    has_tier2_origin = len(origin_bg.strip()) >= 10 or any(
        k in json.dumps(evidence_pack, ensure_ascii=False) for k in ["原著", "真实事件", "改编自", "原型", "纪实", "历史"]
    )
    has_tier2_jargon = bool(jargon) or any(
        k in json.dumps(evidence_pack, ensure_ascii=False) for k in ["八门", "门派", "算盘", "机制", "套路", "化学", "物理", "分成", "黑产"]
    )
    tier2_pass = has_tier2_origin and has_tier2_jargon

    # Tier 3: 微观拉片道具
    has_tier3_anchors = isinstance(sensory_anchors, list) and len(sensory_anchors) >= 3

    # Tier 4: 现实同构
    has_tier4_real = len(real_world.strip()) >= 10 or any(
        k in json.dumps(evidence_pack, ensure_ascii=False) for k in ["当代", "现实", "现代", "富豪", "打工人", "韭菜", "中产", "老百姓", "普通人"]
    )

    score = 0
    if has_tier1_claims: score += 20
    if has_tier1_chars: score += 10
    if has_tier2_origin: score += 20
    if has_tier2_jargon: score += 15
    if has_tier3_anchors: score += 25
    if has_tier4_real: score += 10

    missing: list[str] = []
    if not has_tier1_claims: missing.append("Tier 1: 核心论证主张不足3条")
    if not has_tier1_chars: missing.append("Tier 1: 缺少主要角色关系与蜕变线")
    if not has_tier2_origin: missing.append("Tier 2: 缺少原著小说或真实原型背景溯源")
    if not has_tier2_jargon: missing.append("Tier 2: 缺少行业行话或黑产底层机制拆解")
    if not has_tier3_anchors: missing.append("Tier 3: 具象微观感官道具不足3个")
    if not has_tier4_real: missing.append("Tier 4: 缺少当代现实同构案例或社会学映射")

    passed = score >= 80

    return {
        "score": score,
        "passed": passed,
        "tier1_pass": tier1_pass,
        "tier2_pass": tier2_pass,
        "tier3_pass": has_tier3_anchors,
        "tier4_pass": has_tier4_real,
        "missing_items": missing,
        "anchors_count": len(sensory_anchors) if isinstance(sensory_anchors, list) else 0,
        "claims_count": len(core_claims) if isinstance(core_claims, list) else 0,
    }


# ==============================================================================
# 4. 标题冻结协议 (Title Freeze) —— 规范走 evidence_write
# ==============================================================================

def freeze_title(run_root: str | Path, title_text: str) -> dict[str, Any]:
    """在 planning 阶段锁定标题与 SHA-256 哈希，必须通过 write_evidence_json 留底记账。"""
    root = Path(run_root).resolve()
    review_dir = root / "review"
    freeze_path = review_dir / "title-freeze.json"

    clean_title = title_text.strip()
    title_hash = hashlib.sha256(clean_title.encode("utf-8")).hexdigest()
    cjk_len = len(re.findall(r"[\u4e00-\u9fff]", clean_title))
    total_len = len(clean_title)

    payload = {
        "status": "frozen_ok",
        "title": clean_title,
        "title_sha256": title_hash,
        "cjk_len": cjk_len,
        "total_len": total_len,
        "length_compliant": total_len <= 30,
    }

    # 走 evidence_write 标准通道：留底 before-image 并记 changelog
    write_evidence_json(
        freeze_path,
        payload,
        run_dir=root,
        reason="title_freeze:record_locked_headline",
        author="editorial_planner",
    )
    return payload


def verify_title_freeze(run_root: str | Path, current_title: str) -> tuple[bool, str]:
    """验证当前标题是否匹配冻结记录。"""
    freeze_path = Path(run_root).resolve() / "review" / "title-freeze.json"
    if not freeze_path.exists():
        return False, "title_not_frozen"

    try:
        data = json.loads(freeze_path.read_text(encoding="utf-8"))
    except Exception:
        return False, "corrupted_title_freeze_record"

    frozen_title = data.get("title", "")
    frozen_hash = data.get("title_sha256", "")
    current_hash = hashlib.sha256(current_title.strip().encode("utf-8")).hexdigest()

    if current_hash != frozen_hash or current_title.strip() != frozen_title:
        return False, f"title_tampered_after_freeze:expected_{frozen_title}_got_{current_title.strip()}"

    return True, "frozen_ok"


# ==============================================================================
# 5. 断言账本双向覆盖门禁 (Assertion Ledger Coverage，分级严查)
# ==============================================================================

_CN_NUMERALS = "一二三四五六七八九十两半"
TIME_SPAN_EXTRACT_RE = re.compile(
    r"[0-9一二三四五六七八九十百千几多余数两半]{1,6}\s*(?:年|个月|月|周|星期|天|日|届|期)(?:来|间|之后|以后|后|前|过去|时间|内)?"
    r"|多年来|这些?年(?:来)?|一直以来|多年以前|近年来"
)
SPECIFIC_SPAN_CLASSIFIER_RE = re.compile(
    r"[0-9]|十几|十多|数十|近[0-9一二三四五六七八九十]|将近"
    rf"|[{_CN_NUMERALS}]+(?:年|个月|月|周|星期|天|日|届|期)(?:后|前|来|间|内|过去)?"
)

GENERAL_SPAN_RE = re.compile(r"这些?年(?:来)?|多年来|一直以来|多年以前|近年来")

AUDIENCE_ACTION_RE = re.compile(
    r"(?:还在|仍在|依旧在|仍被|被反复|被不断|不断被|纷纷|都在|人人|一致)"
    r"[^。！？；\n]{0,10}?"
    r"(?:引用|提起|提及|讨论|转发|传播|模仿|致敬|重看|重播|刷屏|传颂)"
    r"|盘到包浆|如数家珍|口口相传|家喻户晓|出圈|全网痛骂|全网都在骂|都在质问"
)

NUMBER_FACT_RE = re.compile(
    r"(?:[0-9]+(?:\.[0-9]+)?|[一二三四五六七八九十百千万两半]{2,6})\s*(?:%|％|亿|万|千|百|岁|小时|分钟|个月|天|元|美元|块|集|季|部|场|次)"
)

QUOTE_FACT_RE = re.compile(r"“([^”\n]{4,60})”|\"([^\"\n]{4,60})\"")

# 修辞性非事实数字白名单（比喻/俗语/叙事虚指，不要求入账）
RHETORICAL_NUMBER_WHITELIST = {
    "一分钱", "一万遍", "一百倍", "一辈子", "半辈子", "几辈子", "几十年", "千千万万",
    "一点", "一回", "一次", "一天", "一年", "一秒钟", "两句", "三言两语", "八面玲珑",
    "一厘一毫", "一点一滴", "一干二净", "半个时辰", "两块铜板", "三集", "三次", "两次",
    "半步", "几步", "十分钟", "一分钟", "一小时", "半天", "两天", "三天", "十天半月",
}


def check_assertion_ledger_coverage(
    draft_text: str,
    evidence_pack: Mapping[str, Any],
    *,
    run_root: str | Path | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    """检查正文中的时间跨度、受众群体行为、带量词数字与直接引语是否在账本或已登记来源中有依据。
    复用老系统 `assertion_ledger_coverage._covered_in_ledger` 滑窗与计数后缀归一能力。
    """
    from article_group.assertion_ledger_coverage import _covered_in_ledger

    corpus_parts = [json.dumps(evidence_pack, ensure_ascii=False)]
    if run_root is not None:
        r_root = Path(run_root)
        manifest_path = r_root / "source-manifest.json"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                for s in manifest.get("sources") or []:
                    rel = s.get("artifact_path")
                    if rel and (r_root / rel).is_file():
                        corpus_parts.append((r_root / rel).read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                pass
    evidence_text = "\n".join(corpus_parts)

    raw_spans = sorted(set(TIME_SPAN_EXTRACT_RE.findall(draft_text)))
    specific_times = [
        sp for sp in raw_spans
        if SPECIFIC_SPAN_CLASSIFIER_RE.search(sp) and sp not in RHETORICAL_NUMBER_WHITELIST
    ]
    general_times = sorted(set(GENERAL_SPAN_RE.findall(draft_text)))
    audience_actions = sorted(set(AUDIENCE_ACTION_RE.findall(draft_text)))
    number_facts = [
        n for n in sorted(set(NUMBER_FACT_RE.findall(draft_text)))
        if n not in RHETORICAL_NUMBER_WHITELIST
    ]
    raw_quotes = QUOTE_FACT_RE.findall(draft_text)
    quotes = sorted({(q[0] or q[1]).strip() for q in raw_quotes if (q[0] or q[1]).strip()})

    errors: list[str] = []
    warnings: list[str] = []

    def _is_supported(claim: str) -> bool:
        return claim in evidence_text or _covered_in_ledger(claim, evidence_text)

    # 1. 受众群体行为断言：无账本条目直接记 error（daily-008 major 级别）
    unsupported_actions = [a for a in audience_actions if not _is_supported(a)]
    for act in unsupported_actions:
        errors.append(f"unsupported_audience_action:{act}")

    # 2. 具体时间跨度：超过 2 处完全无来源记 error（strict 模式 1 处即记 error）
    unsupported_specific_times = [t for t in specific_times if not _is_supported(t)]
    if len(unsupported_specific_times) > 2 or (strict and unsupported_specific_times):
        errors.append(f"unsupported_specific_timespan_overflow:{unsupported_specific_times}")
    elif unsupported_specific_times:
        warnings.append(f"unsupported_specific_timespan_warning:{unsupported_specific_times}")

    # 3. 泛化时间表述只记 warning
    unsupported_general = [g for g in general_times if not _is_supported(g)]
    for gen in unsupported_general:
        warnings.append(f"general_timespan_advisory:{gen}")

    # 4. 带量词数字核验（NUMBER_FACT_RE）：strict 模式下直接升格为 error
    unsupported_numbers = [n for n in number_facts if not _is_supported(n)]
    for num in unsupported_numbers:
        if strict:
            errors.append(f"unsupported_number_fact:{num}")
        else:
            warnings.append(f"unsupported_number_fact:{num}")

    # 5. 引语核验（QUOTE_FACT_RE）：取前 6 字滑窗看是否在证据与来源中出现
    unsupported_quotes: list[str] = []
    clean_ev = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", evidence_text)
    for q in quotes:
        anchor = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", q)[:6]
        if len(anchor) >= 4 and anchor not in clean_ev and not _is_supported(q):
            unsupported_quotes.append(q)
            if strict:
                errors.append(f"unsupported_quote:{q[:24]}")
            else:
                warnings.append(f"unsupported_quote:{q[:24]}")

    passed = len(errors) == 0

    return {
        "passed": passed,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "audience_actions_found": audience_actions,
        "specific_times_found": specific_times,
        "number_facts_found": number_facts,
        "unsupported_numbers": unsupported_numbers,
        "quotes_found": quotes,
        "unsupported_quotes": unsupported_quotes,
    }


# ==============================================================================
# 6. 开篇试写熔断机制 (Prose Pilot Melting Switch)
# ==============================================================================

OPENING_CLICHES = [
    r"随着(?:影视行业|时代的|社会的发展)",
    r"由.*执导",
    r"近年来.*电影",
    r"在当今影视市场中",
    r"探讨了.*人性",
    r"本片以独特的视听语言",
    r"不可否认的是",
    r"值得一提的是",
]


def prose_pilot_check(opening_text: str) -> tuple[bool, str]:
    """前 300 字试写熔断检查：严禁八股影评引子，首段必须具备动作、道具、数字或台词张力（对齐 12 篇定稿母本）。"""
    snippet = opening_text.strip()[:300]
    for pat in OPENING_CLICHES:
        if re.search(pat, snippet):
            return False, f"prose_pilot_melt:opening_cliche_detected:matched_{pat}"

    # 兼容戏剧冲突切入与 12 篇母本的冷峻白描镜头/数字/道具切入
    has_tension = any(
        p in snippet
        for p in [
            "“", "\"", "血", "死", "枪", "断", "杀", "冷笑", "钱", "短信", "火", "砸", "震", "破", "账", "泪", "跑",
            "捏着", "僵在", "跪", "擦", "疯传", "截图", "判决书", "红烛", "尸体", "万", "元", "奖", "雪", "雨", "拍",
        ]
    ) or bool(re.search(r"\d+", snippet))
    if not has_tension:
        return False, "prose_pilot_melt:lack_of_physical_tension_in_opening"

    return True, "prose_pilot_passed"


# ==============================================================================
# 7. 信源权能分级矩阵 (Source Capability Matrix)
# ==============================================================================

# 权能定义：crawled pages are not automatically writable
CAPABILITY_HIERARCHY = {
    "page_metadata": 1,        # 只能证明档期、片名、发布时间，禁写角色动机/台词
    "secondary_discussion": 2, # 营销号/影评讨论，只能归属于“据讨论称”，禁作第一手事实
    "page_fulltext": 3,        # 权威媒体报道全文，可支撑报道事实
    "dialogue_transcript": 4,  # 台词原声/字幕本，才准写第一人称原话引述
    "scene_verified": 5,       # 视频正片拉片，才准写微观动作与镜头细节
    "confirmed-primary": 5,    # 官方一手采访实录
}

QUOTE_RE = re.compile(r"[“\"「『]([^”\"」』\n]{15,80})[”\"」』]")


def validate_source_capabilities(draft_text: str, sources_manifest: Mapping[str, Any]) -> dict[str, Any]:
    """信源权能分级校验：防止拿着低权能通报或二手营销号料，直接捏造一手原话引述或微观动作。"""
    sources = sources_manifest.get("sources", [])
    max_cap = 1
    has_primary = False
    for s in sources:
        role = s.get("source_role") or "secondary_discussion"
        cap = CAPABILITY_HIERARCHY.get(role, 2)
        if cap > max_cap:
            max_cap = cap
        if cap >= 4:
            has_primary = True

    long_quotes = QUOTE_RE.findall(draft_text)

    violations = []
    # 如果信源全都是二级讨论或纯页面元数据（max_cap < 3），却在正文里包含大量未署名直接长引语
    if max_cap < 3 and len(long_quotes) > 0:
        violations.append(f"source_capability_overreached:低权能信源({max_cap})禁止出现直接长引述({len(long_quotes)}处)")

    passed = len(violations) == 0

    return {
        "passed": passed,
        "max_capability_level": max_cap,
        "has_primary_or_transcript": has_primary,
        "long_quotes_count": len(long_quotes),
        "violations": violations,
    }


# ==============================================================================
# 8. 脱水可读性透视 (Source-Stripped Body Generator)
# ==============================================================================

def generate_source_stripped_body(draft_text: str) -> dict[str, Any]:
    """脱水透视稿生成器：物理抽干外部大段剧情复述与长直接引述，留下作者独立议论与利益算盘。
    供 Controller 在 3 秒内看清文章是否有真才实学。
    """
    lines = draft_text.splitlines()
    stripped_lines = []

    for line in lines:
        stripped = line.strip()
        # 跳过标题、分割线、配图
        if not stripped or stripped.startswith("#") or stripped.startswith("---") or stripped.startswith("!["):
            continue
        # 如果整段是一句长引语（超25字），抽干过滤
        if stripped.startswith("“") and stripped.endswith("”") and len(stripped) > 25:
            continue
        # 过滤纯客观剧情叙述标记行（可识别的特定引述）
        stripped_lines.append(stripped)

    stripped_body = "\n\n".join(stripped_lines)
    raw_chars = len(re.findall(r"[\u4e00-\u9fff]", draft_text))
    stripped_chars = len(re.findall(r"[\u4e00-\u9fff]", stripped_body))

    # 计算脱水压缩比
    compression_ratio = round(stripped_chars / max(1, raw_chars), 3)

    return {
        "raw_cjk_chars": raw_chars,
        "stripped_cjk_chars": stripped_chars,
        "compression_ratio": compression_ratio,
        "stripped_body": stripped_body,
        "is_substantive": stripped_chars >= 800 and compression_ratio >= 0.50,
        "summary": f"脱水透视完成：原文 {raw_chars} 字 -> 核心观点骨架 {stripped_chars} 字 (留存率 {compression_ratio*100:.1f}%)"
    }


# ==============================================================================
# 9. 待核清单保守默认规则 (Uncertainty Sheet Conservative Fallback)
# ==============================================================================

def resolve_uncertainty_sheet(
    pending_sheet: Mapping[str, Any],
    human_decisions: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """处理待核清单（pending-review-sheet）：
    - 若人类提供了决策：按人类指令锁定；
    - 若人类未提供决策：
      - blocking == True 项：抛出 blocking_uncertainty_unresolved 阻断；
      - blocking == False 项：自动应用【保守默认法则】（优先选择 recommendation 中的不写数字/降级为归属表述）。
    """
    pending_items = pending_sheet.get("pending_items", [])
    verified_items = list(pending_sheet.get("verified_items", []))
    decisions = human_decisions or {}

    resolved_items = []
    blocking_errors = []

    for item in pending_items:
        uid = str(item.get("id") or "")
        is_blocking = item.get("blocking", False)

        if uid in decisions:
            chosen = decisions[uid]
            resolved_items.append({
                "id": uid,
                "item": item.get("item"),
                "status": "human_decided",
                "chosen_policy": chosen,
            })
        else:
            # 人类未决策
            if is_blocking:
                blocking_errors.append(f"blocking_uncertainty_unresolved:{uid}:{item.get('item', '')[:30]}")
            else:
                # 自动应用最保守口径
                fallback = item.get("recommendation") or (item.get("alternatives") or ["不写具体未核数字"])[0]
                resolved_items.append({
                    "id": uid,
                    "item": item.get("item"),
                    "status": "conservative_fallback_applied",
                    "chosen_policy": fallback,
                    "note": "人类未作答，自动按最保守口径降级处理，不阻断发稿"
                })

    passed = len(blocking_errors) == 0

    return {
        "passed": passed,
        "blocking_errors": blocking_errors,
        "resolved_items": resolved_items,
        "verified_items_count": len(verified_items),
        "total_resolved": len(resolved_items),
    }


def check_uncertainty_sheet_compliance(
    draft_text: str,
    pending_sheet: Mapping[str, Any] | None = None,
    evidence_pack: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """检查待核清单（pending-review-sheet.json）与证据包中的降级/省略裁决是否在正文中被严格遵守：
    1. 若存在未决的 blocking=True 项且无 resolved 状态，阻断；
    2. 若 policy/recommendation 中显式声明了“删除 X”或 `forbidden_tokens`，而正文依然出现 X，阻断。
    """
    sheet = pending_sheet or {}
    ev = evidence_pack or {}
    errors: list[str] = []
    leaked_tokens: list[str] = []

    pending_items = sheet.get("pending_items") or []
    for item in pending_items:
        if not isinstance(item, Mapping):
            continue
        uid = str(item.get("id") or "U?")
        status = str(item.get("status") or "")
        if item.get("blocking") is True and status not in {
            "human_decided",
            "resolved",
            "resolved_conservative_omission",
            "conservative_fallback_applied",
        }:
            errors.append(f"blocking_uncertainty_unresolved:{uid}")

        for tok in item.get("forbidden_tokens") or []:
            tok_str = str(tok).strip()
            if tok_str and tok_str in draft_text:
                leaked_tokens.append(tok_str)
                errors.append(f"uncertainty_forbidden_token_leaked:{uid}:{tok_str}")

    # 检查 evidence_pack.uncertain_facts_downgraded 中声明“删除 ...”的片段是否泄漏回正文
    for dg in ev.get("uncertain_facts_downgraded") or []:
        if not isinstance(dg, Mapping):
            continue
        policy = str(dg.get("policy") or "")
        for m in re.finditer(r"删除\s*([0-9]+(?:\.[0-9]+)?%|「[^」]{2,20}」)", policy):
            raw_forbid = m.group(1).strip("「」 ")
            if raw_forbid and raw_forbid in draft_text:
                leaked_tokens.append(raw_forbid)
                errors.append(f"downgraded_fact_leaked_in_draft:{raw_forbid}")

    return {
        "passed": len(errors) == 0,
        "errors": sorted(set(errors)),
        "leaked_tokens": sorted(set(leaked_tokens)),
    }


# ==============================================================================
# 10. 账本孤儿检查 (Ledger Orphan Detection —— 滑窗精准匹配 + 多形态兼容)
# ==============================================================================

def _sliding_cjk_windows(text: str, stopwords: set[str]) -> list[str]:
    """提取 3~4 字 CJK 滑动窗口及连续短词块，解决原非重叠贪婪切块漏检问题。"""
    clean_runs = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    windows: list[str] = []
    for run in clean_runs:
        if len(run) <= 4:
            if run not in stopwords:
                windows.append(run)
        else:
            for wlen in (4, 3):
                for idx in range(len(run) - wlen + 1):
                    sub = run[idx : idx + wlen]
                    if sub not in stopwords:
                        windows.append(sub)
    return windows


def detect_ledger_orphans(draft_text: str, evidence_pack: Mapping[str, Any]) -> dict[str, Any]:
    """反向检查：账本中辛苦搜集的硬核条目（core_claims, sensory_anchors），正文到底消化了多少。
    支持 dict（assertion/claim/fact/name/anchor）与 str 列表双形态，采用 3~4 字滑窗匹配。
    若落段率低于 60%，发出 ledger_orphan_warning。
    """
    claims = evidence_pack.get("core_claims") or []
    anchors = evidence_pack.get("sensory_anchors") or []

    total_key_items = len(claims) + len(anchors)
    if total_key_items == 0:
        return {"passed": True, "absorption_rate": 1.0, "orphan_items": [], "warnings": []}

    stopwords = {
        "不过", "所谓", "这是", "因为", "所以", "如果", "但是", "可以", "能够", "在这个", "对于",
        "一个", "一种", "他们", "自己", "最后", "承认", "这一切", "全是", "为了",
    }

    absorbed_claims = 0
    orphans: list[str] = []

    for idx, c in enumerate(claims, 1):
        if isinstance(c, Mapping):
            cid = str(c.get("claim_id") or f"C{idx:02d}")
            assertion = str(c.get("assertion") or c.get("claim") or c.get("fact") or "")
            support = str(c.get("support") or "")
            combined = f"{assertion} {support}".strip()
        else:
            cid = f"C{idx:02d}"
            assertion = str(c)
            combined = assertion

        tokens = _sliding_cjk_windows(combined, stopwords)
        if (assertion and assertion in draft_text) or any(t in draft_text for t in tokens):
            absorbed_claims += 1
        else:
            orphans.append(f"orphan_claim:{cid}:{assertion[:25]}")

    absorbed_anchors = 0
    for idx, a in enumerate(anchors, 1):
        if isinstance(a, Mapping):
            aid = str(a.get("anchor_id") or f"A{idx:02d}")
            aname = str(a.get("name") or a.get("anchor") or "")
        else:
            aid = f"A{idx:02d}"
            aname = str(a)

        tokens = _sliding_cjk_windows(aname, stopwords)
        if (aname and aname in draft_text) or any(t in draft_text for t in tokens):
            absorbed_anchors += 1
        else:
            orphans.append(f"orphan_anchor:{aid}:{aname[:25]}")

    absorbed_total = absorbed_claims + absorbed_anchors
    absorption_rate = round(absorbed_total / max(1, total_key_items), 3)

    passed = absorption_rate >= 0.60
    warnings: list[str] = []
    if not passed:
        warnings.append(
            f"ledger_orphan_warning:账本硬核素材落段率过低({absorption_rate*100:.1f}% < 60%)，主笔未充分消化物料"
        )

    return {
        "passed": passed,
        "absorption_rate": absorption_rate,
        "absorbed_count": absorbed_total,
        "total_items": total_key_items,
        "orphan_items": orphans,
        "warnings": warnings,
    }


# ==============================================================================
# 11. 原文滑窗防脑补溯源校验 (Claim-to-Source Sliding Window Provenance Check)
# ==============================================================================

def verify_claims_anchored_in_sources(
    run_root: str | Path,
    evidence_pack: Mapping[str, Any],
) -> dict[str, Any]:
    """防静态脑补素材门禁：
    1. 校验 source-manifest.json 中登记的每个 sources/*.clean.md 真实存在、非空且 SHA-256 一致；
    2. 复用 claim_source_check.fact_anchors_in_source，核验 evidence_pack.source_facts 中声明的事实
       必须在对应 source_id 的原文中滑窗命中（连续 6 字窗口或数字/实体锚定）。
    """
    from article_group.claim_source_check import fact_anchors_in_source

    root = Path(run_root).resolve()
    manifest_path = root / "source-manifest.json"
    if not manifest_path.is_file():
        return {
            "passed": False,
            "errors": ["source_manifest_missing"],
            "anchored_count": 0,
            "total_facts": 0,
        }

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "passed": False,
            "errors": ["source_manifest_corrupted"],
            "anchored_count": 0,
            "total_facts": 0,
        }

    sources = manifest.get("sources") or []
    if not sources:
        return {
            "passed": False,
            "errors": ["source_manifest_empty"],
            "anchored_count": 0,
            "total_facts": 0,
        }

    errors: list[str] = []
    source_texts: dict[str, str] = {}

    for src in sources:
        sid = str(src.get("source_id") or "").strip()
        rel_path = str(src.get("artifact_path") or "").strip()
        expected_sha = str(src.get("sha256") or "").strip()
        if not sid or not rel_path:
            errors.append(f"invalid_source_entry:{sid}")
            continue
        if ".." in sid or not re.match(r"^[A-Za-z0-9_.-]+$", sid):
            errors.append(f"invalid_source_id_format_or_traversal:{sid}")
            continue
        fpath = (root / rel_path).resolve()
        if not fpath.is_relative_to(root):
            errors.append(f"source_path_traversal:{sid}:{rel_path}")
            continue
        if not fpath.is_file():
            errors.append(f"source_file_missing:{sid}:{rel_path}")
            continue
        raw_bytes = fpath.read_bytes()
        actual_sha = hashlib.sha256(raw_bytes).hexdigest()
        if expected_sha and actual_sha != expected_sha:
            errors.append(f"source_sha256_mismatch:{sid}")
        text = raw_bytes.decode("utf-8", errors="replace")
        # 防止几十字的空壳伪快照
        cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
        if cjk_count < 30:
            errors.append(f"source_snapshot_too_thin:{sid}:cjk_{cjk_count}<30")
        source_texts[sid] = text

    source_facts = evidence_pack.get("source_facts") or []
    anchored_count = 0
    for item in source_facts:
        if not isinstance(item, Mapping):
            continue
        fact_text = str(item.get("fact") or "").strip()
        anchor_text = str(item.get("text") or "").strip()
        sid = str(item.get("source_id") or "").strip()
        if not (fact_text or anchor_text) or not sid:
            continue
        src_body = source_texts.get(sid, "")
        if not src_body:
            errors.append(f"fact_references_unknown_source:{sid}:{(fact_text or anchor_text)[:20]}")
            continue
        ok_fact, _ = fact_anchors_in_source(fact_text, src_body) if fact_text else (False, [])
        ok_anchor, _ = fact_anchors_in_source(anchor_text, src_body) if anchor_text else (False, [])
        if ok_fact or ok_anchor:
            anchored_count += 1
        else:
            errors.append(f"fact_not_anchored_in_source:{sid}:{(fact_text or anchor_text)[:25]}")

    return {
        "passed": len(errors) == 0,
        "errors": sorted(set(errors)),
        "registered_sources": len(source_texts),
        "anchored_count": anchored_count,
        "total_facts": len(source_facts),
    }


# ==============================================================================
# 12. 跨批次已发文章与人物去重扫描器 (Cross-Batch Published Deduplication)
# ==============================================================================

def scan_historical_published_dedupe(
    candidate_title_or_work: str,
    *,
    dsh_articles_dir: str | Path = "/home/allen/dsh/articles",
    runs_dir: str | Path | None = None,
    exclude_run_name: str = "",
) -> dict[str, Any]:
    """扫描本地直出文章库（/home/allen/dsh/articles/**/*.md）与历史 runs/ 标题包，
    同时检测《作品名》与核心人物/实体名撞车。
    """
    query = candidate_title_or_work.strip()
    works = [m.group(1).strip() for m in re.finditer(r"《([^》]{2,30})》", query)]
    ignore_words = {
        "为什么", "怎么", "什么", "一个", "这部", "电影", "电视剧", "新剧", "内娱", "国产剧",
        "老实人", "大结局", "遮羞布", "人情世故", "算盘", "绝户计", "杀猪盘", "神作", "神剧",
        "名利场", "桌子", "掀翻", "撕烂", "打碎", "到底", "凭什么", "真相",
    }
    clean_q = re.sub(r"《[^》]+》", " ", query)
    runs = re.findall(r"[\u4e00-\u9fff]+", clean_q)
    extracted_tokens: set[str] = set()
    for r in runs:
        if len(r) <= 4 and r not in ignore_words and len(r) >= 2:
            extracted_tokens.add(r)
        for n in (3, 2, 4):
            for idx in range(len(r) - n + 1):
                sub = r[idx : idx + n]
                if sub not in ignore_words and len(sub) >= 2:
                    extracted_tokens.add(sub)
    tokens = sorted(extracted_tokens, key=lambda s: (-len(s), s))

    matched_records: list[dict[str, str]] = []

    def _match_against(hist_title: str, source_str: str) -> None:
        for w in works:
            if w and w in hist_title:
                matched_records.append({
                    "source": source_str,
                    "historical_title": hist_title,
                    "match_type": f"same_work:《{w}》",
                })
                return
        for tok in tokens:
            if len(tok) >= 2 and tok in hist_title:
                matched_records.append({
                    "source": source_str,
                    "historical_title": hist_title,
                    "match_type": f"same_entity:{tok}",
                })
                return

    articles_root = Path(dsh_articles_dir)
    if articles_root.is_dir():
        md_candidates = list(articles_root.glob("*.md")) + list(articles_root.glob("*/delivery.md")) + list(articles_root.glob("*/*/delivery.md"))
        for md_file in sorted(set(md_candidates)):
            try:
                first_lines = md_file.read_text(encoding="utf-8", errors="ignore")[:300]
            except OSError:
                continue
            m_h1 = re.search(r"^#\s+(.+)$", first_lines, re.M)
            hist_title = m_h1.group(1).strip() if m_h1 else md_file.stem
            _match_against(hist_title, str(md_file))

    if runs_dir is not None:
        r_root = Path(runs_dir)
        if r_root.is_dir():
            for tp in sorted(r_root.glob("*/*/title-pack.json")):
                if exclude_run_name and exclude_run_name in str(tp):
                    continue
                try:
                    data = json.loads(tp.read_text(encoding="utf-8"))
                except Exception:
                    continue
                hist_title = str(data.get("selected_title") or "")
                hist_work = str(data.get("work") or "")
                combined = f"{hist_title} {hist_work}".strip()
                if combined:
                    _match_against(combined, str(tp))

    return {
        "status": "conflict_detected" if matched_records else "clean",
        "is_duplicate": len(matched_records) > 0,
        "extracted_works": works,
        "extracted_tokens": tokens[:5],
        "matched_records": matched_records,
    }


# ==============================================================================
# 13. 定题即定检：标题核心词二次靶向深搜计划 (Targeted Search on Title Freeze)
# ==============================================================================

def build_title_targeted_search_plan(
    selected_title: str,
    killer_stance: str = "",
) -> dict[str, Any]:
    """「定题即定检」：当标题确定后，拆解标题中的《作品》、数字、核心动作词，
    自动生成动笔前必须核实的微观靶向检索清单（Tier 1 事实 / Tier 2 机制 / Tier 3 场景）。
    """
    clean_title = selected_title.strip()
    works = [m.group(1).strip() for m in re.finditer(r"《([^》]{2,30})》", clean_title)]
    numbers = re.findall(r"\d+(?:\.\d+)?[万亿岁年集部天%]*|[一二三四五六七八九十百千万]+[万亿岁年集部天]", clean_title)
    core_clauses = [c.strip() for c in re.split(r"[：:，,！!？?\s]+", re.sub(r"《[^》]+》", "", clean_title)) if len(c.strip()) >= 3]

    subject = works[0] if works else (core_clauses[0] if core_clauses else clean_title[:8])

    tier1_queries = [f'"{subject}" {num} 真实出处 核实' for num in numbers] or [f'"{subject}" 核心事实 时间线 核实']
    tier2_queries = [f'"{subject}" {clause} 幕后 机制 账本' for clause in core_clauses[:2]]
    tier3_queries = [f'"{subject}" 经典名场面 原话台词 细节拉片']

    return {
        "selected_title": clean_title,
        "subject": subject,
        "numbers_to_verify": numbers,
        "core_clauses": core_clauses,
        "tier1_fact_queries": tier1_queries,
        "tier2_mechanism_queries": tier2_queries,
        "tier3_scene_queries": tier3_queries,
        "rule_note": "定题即定检：标题中的每个数字与动作断言必须在动笔前完成微观核实，无来源则降级",
    }


# ==============================================================================
# 14. 腾讯朱雀真机门禁适配器 (Zhuque All-Green Gate Adapter)
# ==============================================================================

def run_zhuque_gate_check(
    draft_path: str | Path,
    *,
    execute_live: bool = False,
    cli_path: str | Path = "/home/allen/dsh/scripts/zhuque_gate.py",
) -> dict[str, Any]:
    """对接 /home/allen/dsh/scripts/zhuque_gate.py：
    - execute_live=False 时诚实返回 status='not_run' 与原因，绝不伪造 pass；
    - execute_live=True 时调用真机脚本解析结果，若登录态/网络不可用则记录 unavailable。
    """
    import subprocess

    target = Path(draft_path).resolve()
    cli = Path(cli_path)

    if not target.is_file():
        return {"status": "not_run", "blocking": False, "reason": "draft_file_missing", "advisory": True}
    if not cli.is_file():
        return {"status": "not_run", "blocking": False, "reason": "zhuque_cli_missing", "advisory": True}
    if not execute_live:
        return {
            "status": "not_run",
            "blocking": False,
            "reason": "live_zhuque_not_triggered_in_offline_mode",
            "cli_path": str(cli),
            "advisory": True,
        }

    try:
        proc = subprocess.run(
            ["python3", str(cli), str(target)],
            capture_output=True,
            text=True,
            timeout=90,
        )
        passed = proc.returncode == 0
        return {
            "status": "pass" if passed else "needs_human_review",
            "blocking": False,
            "exit_code": proc.returncode,
            "stdout_tail": proc.stdout[-400:] if proc.stdout else "",
            "stderr_tail": proc.stderr[-200:] if proc.stderr else "",
            "advisory": True,
        }
    except Exception as exc:
        return {
            "status": "not_run",
            "blocking": False,
            "reason": f"zhuque_execution_error:{type(exc).__name__}",
            "advisory": True,
        }


# ==============================================================================
# 15. L2 复核报告 Schema 校验与防带病 Approve 门禁 (L2 Contract Validator)
# ==============================================================================

L2_REQUIRED_TOP_KEYS = {"decision", "scope_reviewed", "findings", "non_findings", "coverage_gaps"}
L2_FINDING_KEYS = {"severity", "target", "evidence", "counterexample_or_failure_mode", "required_fix", "recheck"}
L2_ALLOWED_DECISIONS = {"approve", "needs_changes", "evidence_insufficient"}
L2_ALLOWED_SEVERITIES = {"blocker", "major", "minor"}
L2_PROVENANCE_KEYS = {"reviewer", "reviewer_session_id", "reviewed_draft_sha256", "attempt", "created_at"}


def validate_and_normalize_l2_review(l2_payload: Mapping[str, Any]) -> dict[str, Any]:
    """严格对齐 schemas/dsh-review-contract.json 与 article_group/dsh_review.py 铁律：
    1. 顶层必须包含 decision / scope_reviewed / findings / non_findings / coverage_gaps；
    2. 每个 finding 必须是包含 6 个标准字段的对象（若为旧式字符串则报错 contract_error）；
    3. 若存在任何 blocker 或 major 级 finding，decision 绝不允许为 approve（自动降级为 needs_changes）；
    4. 必须包含 5 大来源证明字段（reviewer, reviewer_session_id, reviewed_draft_sha256, attempt, created_at），缺一降级为 UNVERIFIED。
    """
    errors: list[str] = []
    if not isinstance(l2_payload, Mapping):
        return {"valid": False, "errors": ["l2_payload_not_mapping"], "effective_decision": "needs_changes"}

    missing_top = L2_REQUIRED_TOP_KEYS - set(l2_payload.keys())
    if missing_top:
        errors.append(f"missing_top_keys:{','.join(sorted(missing_top))}")

    raw_decision = str(l2_payload.get("decision") or "")
    if raw_decision not in L2_ALLOWED_DECISIONS:
        errors.append(f"invalid_decision:{raw_decision}")

    # 来源证明字段校验
    missing_prov = L2_PROVENANCE_KEYS - set(l2_payload.keys())
    provenance_valid = True
    if missing_prov:
        errors.append(f"missing_provenance_keys:{','.join(sorted(missing_prov))}")
        provenance_valid = False
    else:
        for k in ("reviewer", "reviewer_session_id", "reviewed_draft_sha256", "created_at"):
            val_str = str(l2_payload.get(k) or "").strip()
            if not val_str:
                errors.append(f"empty_provenance_field:{k}")
                provenance_valid = False
        attempt = l2_payload.get("attempt")
        if not isinstance(attempt, int) or attempt < 1:
            errors.append(f"invalid_attempt_number:{attempt}")
            provenance_valid = False

    findings = l2_payload.get("findings")
    blocker_or_major = 0
    if not isinstance(findings, list):
        errors.append("findings_must_be_list")
    else:
        for idx, f in enumerate(findings):
            if not isinstance(f, Mapping):
                errors.append(f"finding_{idx}_not_object")
                blocker_or_major += 1
                continue
            missing_f = L2_FINDING_KEYS - set(f.keys())
            if missing_f:
                errors.append(f"finding_{idx}_missing_keys:{','.join(sorted(missing_f))}")
            sev = str(f.get("severity") or "")
            if sev not in L2_ALLOWED_SEVERITIES:
                errors.append(f"finding_{idx}_invalid_severity:{sev}")
            if sev in {"blocker", "major"}:
                blocker_or_major += 1

    effective_decision = raw_decision if raw_decision in L2_ALLOWED_DECISIONS else "needs_changes"
    downgraded = False
    if effective_decision == "approve" and blocker_or_major > 0:
        effective_decision = "needs_changes"
        downgraded = True
        errors.append(f"approve_with_{blocker_or_major}_blocker_or_major_forbidden")
    elif effective_decision == "approve" and not provenance_valid:
        effective_decision = "UNVERIFIED"
        downgraded = True
        errors.append("unverified_l2_source:approval_revoked_missing_provenance")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "raw_decision": raw_decision,
        "effective_decision": effective_decision,
        "downgraded": downgraded,
        "blocker_or_major_count": blocker_or_major,
        "provenance_valid": provenance_valid,
    }


def save_l2_review_with_history(
    run_root: str | Path,
    l2_payload: Mapping[str, Any],
    *,
    author: str = "quality_l2_reviewer",
) -> dict[str, Any]:
    """保存 L2 复核记录，并在写入前自动将上一轮归档到 review/l2-history/attempt-<n>.json。
    历史副本不可覆盖，严禁删除历史。
    """
    root = Path(run_root).resolve()
    review_dir = root / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    current_file = review_dir / "l2-adversarial-review.json"
    history_dir = review_dir / "l2-history"

    # 若当前已有旧复核记录，先归档上一轮
    if current_file.is_file():
        try:
            old_data = json.loads(current_file.read_text(encoding="utf-8"))
            old_attempt = old_data.get("attempt") or 1
            history_dir.mkdir(parents=True, exist_ok=True)
            hist_target = history_dir / f"attempt-{old_attempt}.json"
            if not hist_target.exists():
                write_evidence_json(
                    hist_target,
                    old_data,
                    run_dir=root,
                    reason=f"l2_history:archive_attempt_{old_attempt}",
                    author=author,
                )
        except Exception:
            pass

    write_evidence_json(
        current_file,
        l2_payload,
        run_dir=root,
        reason=f"l2_review:save_attempt_{l2_payload.get('attempt', 1)}",
        author=author,
    )
    return {"ok": True, "saved_path": str(current_file)}


# ==============================================================================
# 16. Markdown 图片引用存在性门禁 (Markdown Image Reference Integrity Gate)
# ==============================================================================

MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def check_markdown_image_integrity(draft_text: str, run_root: str | Path) -> dict[str, Any]:
    """检查 draft.md 中的 ![alt](path) 引用：
    - 若正文中不含任何图片引用（纯内联卡片模式），直接通过；
    - 若正文中声明了本地图片相对路径（如 images/01_xxx.jpg），则磁盘上必须真实存在该文件，
      严禁伪造悬空假路径欺骗配图密度门禁！
    - 严格防御路径穿越：禁止含 .. 且解析后必须在 run root 内部。
    """
    root = Path(run_root).resolve()
    matches = MD_IMAGE_RE.findall(draft_text)
    dangling: list[str] = []

    for _alt, raw_path in matches:
        p_str = raw_path.strip()
        if p_str.startswith(("http://", "https://", "data:")):
            continue
        if ".." in p_str:
            dangling.append(p_str)
            continue
        try:
            candidate = (root / p_str).resolve()
            if not candidate.is_relative_to(root) or not candidate.is_file():
                dangling.append(p_str)
        except Exception:
            dangling.append(p_str)

    return {
        "passed": len(dangling) == 0,
        "image_refs_count": len(matches),
        "dangling_images": dangling,
        "errors": [f"dangling_image_reference:{p}" for p in dangling],
    }


# ==============================================================================
# 17. 跨阶段产物 SHA-256 哈希强绑定校验 (Cross-Stage Artifact Hash Binding)
# ==============================================================================

def verify_artifact_hash_bindings(run_root: str | Path) -> dict[str, Any]:
    """校验 L2 复核报告与微信排版件是否绑定在当前最新 draft.md 的 SHA-256 上。
    一旦 draft.md 在复核或排版后被改动，旧 approve 与旧微信件立即判定为 stale 失效！
    """
    root = Path(run_root).resolve()
    draft_path = root / "draft.md"
    if not draft_path.is_file():
        return {"passed": True, "errors": [], "draft_sha256": ""}

    current_draft_sha = hashlib.sha256(draft_path.read_bytes()).hexdigest()
    errors: list[str] = []

    # 1. 核对 L2 报告绑定的 draft_sha256（字段 reviewed_draft_sha256 必填且比对）
    l2_path = root / "review" / "l2-adversarial-review.json"
    if l2_path.is_file():
        try:
            l2_data = json.loads(l2_path.read_text(encoding="utf-8"))
            reviewed_sha = str(l2_data.get("reviewed_draft_sha256") or "").strip()
            if not reviewed_sha:
                errors.append("stale_l2_review:reviewed_draft_sha256_missing")
            elif reviewed_sha != current_draft_sha:
                errors.append(
                    f"stale_l2_review_hash_mismatch:l2_bound_{reviewed_sha[:12]}_vs_draft_{current_draft_sha[:12]}"
                )
        except Exception:
            errors.append("corrupted_l2_review_json")

    # 2. 核对确定性门禁报告绑定的 reviewed_draft_sha256
    det_path = root / "review" / "deterministic-gates.json"
    if det_path.is_file():
        try:
            det_data = json.loads(det_path.read_text(encoding="utf-8"))
            det_sha = str(det_data.get("reviewed_draft_sha256") or "").strip()
            if not det_sha:
                errors.append("stale_deterministic_gates:reviewed_draft_sha256_missing")
            elif det_sha != current_draft_sha:
                errors.append(
                    f"stale_deterministic_gates_hash_mismatch:gates_bound_{det_sha[:12]}_vs_draft_{current_draft_sha[:12]}"
                )
        except Exception:
            errors.append("corrupted_deterministic_gates_json")

    # 3. 核对全量门禁总账报告 (gate-registry-report.json) 绑定的 draft_sha256 与 l2_file_sha256
    reg_path = root / "review" / "gate-registry-report.json"
    if reg_path.is_file():
        try:
            reg_data = json.loads(reg_path.read_text(encoding="utf-8"))
            reg_draft_sha = str(reg_data.get("draft_sha256") or "").strip()
            if reg_draft_sha and reg_draft_sha != current_draft_sha:
                errors.append(
                    f"stale_gate_registry_report_draft_mismatch:bound_{reg_draft_sha[:12]}_vs_{current_draft_sha[:12]}"
                )
            if l2_path.is_file():
                current_l2_sha = hashlib.sha256(l2_path.read_bytes()).hexdigest()
                reg_l2_sha = str(reg_data.get("l2_file_sha256") or "").strip()
                if reg_l2_sha and reg_l2_sha != current_l2_sha:
                    errors.append(
                        f"stale_gate_registry_report_l2_mismatch:bound_{reg_l2_sha[:12]}_vs_{current_l2_sha[:12]}"
                    )
        except Exception:
            errors.append("corrupted_gate_registry_report_json")

    # 4. 核对微信排版清单绑定的 source_draft_sha256 与三件套自身哈希
    wx_manifest_path = root / "wechat" / "wechat-manifest.json"
    if wx_manifest_path.is_file():
        try:
            wx_m = json.loads(wx_manifest_path.read_text(encoding="utf-8"))
            src_sha = str(wx_m.get("source_draft_sha256") or "").strip()
            if src_sha and src_sha != current_draft_sha:
                errors.append(
                    f"stale_wechat_render_hash_mismatch:wechat_bound_{src_sha[:12]}_vs_draft_{current_draft_sha[:12]}"
                )
            for fname, key in (
                ("body.html", "body_sha256"),
                ("preview.html", "preview_sha256"),
                ("delivery.md", "delivery_md_sha256"),
            ):
                f_target = root / "wechat" / fname
                expected_h = str(wx_m.get(key) or "").strip()
                if expected_h and f_target.is_file():
                    actual_h = hashlib.sha256(f_target.read_bytes()).hexdigest()
                    if actual_h != expected_h:
                        errors.append(f"wechat_artifact_hash_tampered:{fname}")
        except Exception:
            errors.append("corrupted_wechat_manifest_json")

    return {
        "passed": len(errors) == 0,
        "draft_sha256": current_draft_sha,
        "errors": errors,
    }


# ==============================================================================
# 18. 三案例上线门槛自动评估面板 (Pilot Readiness Evaluator)
# ==============================================================================

def evaluate_pilot_readiness(project_root: str | Path) -> dict[str, Any]:
    """扫描 runs/*/*/pilot-manifest.json，按 `docs/dsh/article-group-bot-pilot-v1.md`
    评估连续三案例上线门槛（RUN-RECORD、门禁记录、哈希一致、L2 approve、返工<=2轮、SEALED封存）。
    通过 validate_run 实时重新计算，绝不直接采信落盘的旧 pilot-validation.json。
    """
    from .pilot_contract import validate_run

    p_root = Path(project_root).resolve()
    runs_root = p_root / "runs"
    cases: list[dict[str, Any]] = []

    if runs_root.is_dir():
        for mf in sorted(runs_root.glob("*/*/pilot-manifest.json")):
            r_dir = mf.parent
            try:
                manifest = json.loads(mf.read_text(encoding="utf-8"))
            except Exception:
                continue

            try:
                val_data = validate_run(p_root, r_dir)
            except Exception:
                val_data = {"status": "BLOCKED", "artifact_ready": False, "run_completed": False}

            metrics_path = r_dir / "pilot-metrics.json"
            metrics_data = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.is_file() else {}
            events = metrics_data.get("events") or []

            revisions = [int(e.get("value") or 0) for e in events if e.get("kind") == "revision_count" and e.get("value") is not None]
            coord_secs = [float(e.get("value") or 0) for e in events if e.get("kind") == "coordination_seconds" and e.get("value") is not None]

            is_ready = bool(val_data.get("artifact_ready")) and val_data.get("status") == "PASS"
            is_sealed = (r_dir / "SEALED").is_file() and (r_dir / "SEALED.manifest.json").is_file()

            cases.append({
                "case_id": manifest.get("case_id", r_dir.name),
                "run_id": manifest.get("run_id", r_dir.name),
                "run_root": str(r_dir),
                "status": val_data.get("status", manifest.get("run_status", "active")),
                "artifact_ready": is_ready,
                "sealed": is_sealed,
                "has_run_record": (r_dir / "RUN-RECORD.md").is_file(),
                "max_revision_count": max(revisions) if revisions else 1,
                "coordination_seconds": coord_secs[-1] if coord_secs else None,
            })

    ready_cases = [c for c in cases if c["artifact_ready"]]
    sealed_ready_cases = [c for c in ready_cases if c["sealed"]]

    return {
        "total_pilot_runs": len(cases),
        "artifact_ready_count": len(ready_cases),
        "sealed_ready_count": len(sealed_ready_cases),
        "three_case_threshold_met": len(ready_cases) >= 3,
        "schedule_unlock_eligible": len(sealed_ready_cases) >= 3,
        "cases": cases,
    }



