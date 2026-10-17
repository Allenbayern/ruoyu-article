"""dna_engine: 基于 12 篇定稿母本标定的若雨随影 Writing DNA 审计与母本匹配引擎。

历史沿革与演进：
1. 2026-10-13 核心设计纠偏：淘汰旧版外部营销号碎段阈值，以 12 篇定稿母本为黄金标尺。
2. 2026-10-14 阈值统一与双轨分层（用户裁决：放宽门禁下沿兼容母本，提示词保持最新目标）：
   - 解决 prompt_assembler 与 dna_engine 阈值割裂问题，定义唯一权威常量 `DNA_RHYTHM_STANDARD`；
   - 写作目标（写入提示词，审计偏离仅作 advisory 提醒）：
     - 段落中位数 `45.0 ~ 65.0` 字；
     - 段落呼吸律动标准差 `para_stdev >= 25.0`；
     - 沉浸叙事长段（80~170 字）`>= 4` 段；
     - 短段（<=35 字）占比 `20.0% ~ 45.0%`；
     - CJK 纯汉字数 `2000 ~ 2700` 字。
   - 门禁硬线（audit_draft_dna 判 FAIL 阻断）：
     - 段落中位数 `37.0 ~ 65.0` 字（兼容 mother-01 中位数 38 与 mother-12 中位数 37）；
     - 段落呼吸律动标准差 `para_stdev >= 25.0`；
     - 沉浸叙事长段（80~170 字）`>= 4` 段；
     - 短段（<=35 字）占比 `15.0% ~ 50.0%`（兼容 mother-05 短段 18.4% 与 mother-12 短段 48.3%）；
     - 超过 205 字的死墙段落 `== 0`；
     - 文章字数下限接入 `run_profile.MIN_CJK_CHARS` (1500 字硬阻断)，无硬上限。
   - 落在硬线内但偏离目标区间者，记入 `advisories`，不阻断发布。
   - 打通仓库权威 `style_gate`（禁来源自证、审稿腔、骑墙和稀泥）与 `anti_ai_gate`（< 45.0），
     并拦截廉价口头禅（“脊梁骨发凉/大白话拆开来看/抽了一记耳光”）高频堆砌。
"""

from __future__ import annotations

import glob
import json
import os
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from article_group.anti_ai_gate import analyze_anti_ai
from article_group.evidence_write import write_evidence_json
from article_group.run_profile import MIN_CJK_CHARS
from article_group.style_gate import scan_style

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DNA_ROOT = PROJECT_ROOT / "ruoyu-content" / "10-case-library" / "writing-dna"
RAW_CORPUS_DIR = DNA_ROOT / "raw-corpus"
META_DIR = DNA_ROOT / "_meta"
MOTHER_ARTICLES_DIR = Path("/home/allen/dsh/articles")


@dataclass(frozen=True)
class DnaRhythmStandard:
    """若雨随影文风律动与篇幅黄金标尺（2026-10-14 区分写作目标与门禁硬线）。"""

    # --- 1. 写作目标（Target/Guideline: 写入提示词，审计偏离仅记为 advisory） ---
    target_para_median_min: float = 45.0
    target_para_median_max: float = 65.0
    target_para_stdev_min: float = 25.0
    target_immersive_len_min: int = 80
    target_immersive_len_max: int = 170
    target_immersive_paras_min: int = 4
    target_short_para_len_max: int = 35
    target_short_para_pct_min: float = 20.0
    target_short_para_pct_max: float = 45.0
    target_cjk_min: int = 2000
    target_cjk_max: int = 2700

    # --- 2. 门禁硬线（Hard Gate: audit_draft_dna 判 FAIL 阻断） ---
    gate_para_median_min: float = 37.0
    gate_para_median_max: float = 65.0
    gate_para_stdev_min: float = 25.0
    gate_immersive_len_min: int = 80
    gate_immersive_len_max: int = 170
    gate_immersive_paras_min: int = 4
    gate_short_para_len_max: int = 35
    gate_short_para_pct_min: float = 15.0
    gate_short_para_pct_max: float = 50.0
    gate_wall_para_len_max: int = 205
    gate_wall_paras_max: int = 0
    # 门禁硬下限从 run_profile.MIN_CJK_CHARS 读取（1500），不设硬上限
    gate_cjk_min: int = MIN_CJK_CHARS

    def to_rhythm_standard_dict(self) -> dict[str, Any]:
        """供 match_dna 消费的标准字典格式。"""
        return {
            "para_median_range": [self.gate_para_median_min, self.gate_para_median_max],
            "para_median_target_range": [self.target_para_median_min, self.target_para_median_max],
            "para_stdev_min": self.gate_para_stdev_min,
            "immersive_paras_80_170_min": self.gate_immersive_paras_min,
            "immersive_paras_75_200_min": self.gate_immersive_paras_min,  # 兼容历史 key
            "wall_paras_gt_205_max": self.gate_wall_paras_max,
            "short_paras_le_35_pct_range": [self.gate_short_para_pct_min, self.gate_short_para_pct_max],
            "short_paras_pct_target_range": [self.target_short_para_pct_min, self.target_short_para_pct_max],
            "cjk_hard_min": self.gate_cjk_min,
            "cjk_target_range": [self.target_cjk_min, self.target_cjk_max],
        }

    def to_prompt_assembler_dict(self) -> dict[str, Any]:
        """供 prompt_assembler.dna_rhythm_standard 消费的格式（使用写作目标）。"""
        return {
            "para_median_target": f"{int(self.target_para_median_min)}~{int(self.target_para_median_max)}字",
            "para_stdev_min": self.target_para_stdev_min,
            "immersive_paras_min": self.target_immersive_paras_min,
            "wall_paras_max": self.gate_wall_paras_max,
            "short_paras_pct_range": f"{int(self.target_short_para_pct_min)}%~{int(self.target_short_para_pct_max)}%",
            "cjk_chars_range": f"{self.target_cjk_min}~{self.target_cjk_max}字",
        }


# 全局唯一律动阈值常量（不可变）
DNA_RHYTHM_STANDARD: DnaRhythmStandard = DnaRhythmStandard()

# 12 篇定稿母本清单（作为最高优先级 Few-Shot 标尺）
CANONICAL_MOTHER_TEXTS: list[dict[str, str]] = [
    {
        "id": "mother-01",
        "path": "/home/allen/dsh/articles/delivery-20261012-wo-bu-shi-da-shi.md",
        "title": "大婚当夜惨遭灭门：李现新剧把江湖神棍的绝户计拍绝了",
        "archetype": "单片深度解剖",
        "pillar": "p4_black_market_trap",
    },
    {
        "id": "mother-02",
        "path": "/home/allen/dsh/articles/delivery-20261011-zhifou-8years.md",
        "title": "知否播完8年包揽视帝视后：盛家的算盘打碎了内娱流量泡沫",
        "archetype": "时代老片翻案重访",
        "pillar": "p2_industry_backlash",
    },
    {
        "id": "mother-03",
        "path": "/home/allen/dsh/articles/delivery-20261011-guoking-kaichu.md",
        "title": "国庆被排满7天班1天没去遭开除：打工人的法定假成了卖身契",
        "archetype": "现实生存算盘与破产死线",
        "pillar": "p3_survival_ledger",
    },
    {
        "id": "mother-04",
        "path": "/home/allen/dsh/articles/delivery-20261011-meiyanfang.md",
        "title": "梅艳芳冥诞63岁：被亲妈当摇钱树吸干一生，她死后设下最狠防线",
        "archetype": "行业争议与人物拆台",
        "pillar": "p8_female_resilience",
    },
    {
        "id": "mother-05",
        "path": "/home/allen/dsh/articles/delivery-20261011-byte-poisoning-tiankeyu.md",
        "title": "字节实习生投毒案反转：删光800万显卡代码的田柯宇到底冤不冤",
        "archetype": "行业争议与人物拆台",
        "pillar": "p3_survival_ledger",
    },
    {
        "id": "mother-06",
        "path": "/home/allen/dsh/articles/delivery-20261010-feitian-wangrenjun.md",
        "title": "击败于和伟胡歌拿视帝：演了5次毛主席的王仁君凭什么掀翻流量桌",
        "archetype": "行业争议与人物拆台",
        "pillar": "p2_industry_backlash",
    },
    {
        "id": "mother-07",
        "path": "/home/allen/dsh/articles/cctv6-truman-show-20261009.md",
        "title": "六公主临时撤片改播《楚门的世界》：全网都在猜它又在内涵谁",
        "archetype": "时代老片翻案重访",
        "pillar": "p7_nostalgic_haven",
    },
    {
        "id": "mother-08",
        "path": "/home/allen/dsh/articles/2026-10-08/wangxing-actor-scam/delivery.md",
        "title": "演员王星泰缅边境失联：横店底层演员的活命算盘有多绝望",
        "archetype": "江湖黑产与绝户杀猪盘拆解",
        "pillar": "p4_black_market_trap",
    },
    {
        "id": "mother-09",
        "path": "/home/allen/dsh/articles/2026-10-07-resident-evil-outbreak/delivery.md",
        "title": "《生化危机》重映：保护伞公司的裁员算盘比丧尸更吃人",
        "archetype": "单片深度解剖",
        "pillar": "p3_survival_ledger",
    },
    {
        "id": "mother-10",
        "path": "/home/allen/dsh/articles/2026-10-06-woju-xiaobei/delivery.md",
        "title": "重温《蜗居》小贝：老实人算清房价账本的那一夜彻底疯了",
        "archetype": "时代老片翻案重访",
        "pillar": "p1_honest_retaliation",
    },
    {
        "id": "mother-11",
        "path": "/home/allen/dsh/articles/2026-10-05-chenfeiyu/delivery.md",
        "title": "陈飞宇演反派翻盘：撕掉太子爷标签才算看懂名利场",
        "archetype": "行业争议与人物拆台",
        "pillar": "p2_industry_backlash",
    },
    {
        "id": "mother-12",
        "path": "/home/allen/dsh/articles/2026-10-04-gu-tianle/delivery.md",
        "title": "古天乐被追债8300万：香港电影最后的守夜人算不平这笔烂账",
        "archetype": "行业争议与人物拆台",
        "pillar": "p3_survival_ledger",
    },
]

FORBIDDEN_WORDS = [
    "然而，不得不说",
    "尽管如此",
    "不仅如此",
    "总而言之",
    "毋庸置疑",
    "不可否认",
    "本片以独特的视听语言",
    "探讨了人性",
    "深刻揭示了",
    "全员演技炸裂",
    "视觉奇观",
    "引爆全场",
    "希望对你有帮助",
    "你会如何看待",
    "你怎么看待",
    "值得一提的是",
    "综上所述",
]

# 廉价口号式口头禅：单篇最多允许出现 1 次，出现 >=2 次即判定为机械套话堆叠
SLOGAN_CATCHPHRASES = [
    "真叫人脊梁骨发凉",
    "可大白话拆开来看",
    "大白话拆穿",
    "拉倒吧",
    "抽了一记响亮的耳光",
    "抽了所有虚伪国产剧",
]


def match_dna(topic: str, genre_hint: str = "") -> dict[str, Any]:
    """优先匹配 12 篇定稿母本作为 Few-Shot 标杆，其次补充爆款案例库。"""
    archetype = "单片深度解剖"
    if any(k in topic for k in ["盘点", "部", "榜", "十佳", "推荐", "必看"]):
        archetype = "梯度高分神作盘点"
    elif any(k in topic for k in ["塌房", "争议", "内幕", "骂", "道歉", "撤档", "翻车", "视帝", "视后", "人情世故", "底裤", "拆台", "潜规则"]):
        archetype = "行业争议与人物拆台"
    elif any(k in topic for k in ["老片", "当年", "翻案", "重温", "冷片", "禁片", "回归", "播完", "神剧"]):
        archetype = "时代老片翻案重访"
    elif any(k in topic for k in ["逆袭", "黑马", "首日", "票房", "破亿", "反超", "奇迹"]):
        archetype = "票房黑马与突发热点解密"
    elif genre_hint:
        archetype = genre_hint

    keywords = [w for w in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", topic) if len(w) >= 2]

    # 1. 从 12 篇定稿母本中匹配最契合的 2 篇
    scored_mothers: list[tuple[int, dict[str, str]]] = []
    for m in CANONICAL_MOTHER_TEXTS:
        if not os.path.exists(m["path"]):
            continue
        score = 10  # 母本基础高优权重
        if m["archetype"] == archetype:
            score += 8
        for kw in keywords:
            if kw in m["title"]:
                score += 12
        scored_mothers.append((score, m))
    scored_mothers.sort(key=lambda x: x[0], reverse=True)
    top_mothers = [m for _, m in scored_mothers[:2]]

    # 2. 从案例库补充 Top 3 结构参考
    top_cases: list[dict[str, Any]] = []
    case_bank_path = META_DIR / "case_bank.json"
    if case_bank_path.is_file():
        try:
            cases = json.loads(case_bank_path.read_text(encoding="utf-8"))
            matched_cases = []
            for c in cases:
                score = 0
                genre_val = c.get("genre", "")
                if genre_val and (archetype[:2] in genre_val or genre_val[:2] in archetype):
                    score += 6
                if "S级" in c.get("grade", ""):
                    score += 3
                for kw in keywords:
                    if kw in c.get("title", ""):
                        score += 10
                matched_cases.append((score, c))
            matched_cases.sort(key=lambda x: x[0], reverse=True)
            top_cases = [c for _, c in matched_cases[:3]]
        except Exception:
            top_cases = []

    return {
        "topic": topic,
        "detected_archetype": archetype,
        "canonical_mother_articles": top_mothers,
        "few_shot_paths": [m["path"] for m in top_mothers],
        "matched_cases": top_cases,
        "dna_ruleset_path": str(DNA_ROOT / "Writing-DNA.md"),
        "rhythm_standard": DNA_RHYTHM_STANDARD.to_rhythm_standard_dict(),
    }


def audit_draft_dna(
    file_path: str | Path,
    *,
    run_root: str | Path | None = None,
    write_report: bool = False,
) -> dict[str, Any]:
    """按 12 篇定稿母本黄金分布 + 仓库权威 style_gate / anti_ai_gate 审计文稿。"""
    target = Path(file_path).resolve()
    if not target.is_file():
        return {"ok": False, "passed": False, "error": f"File not found: {target}"}

    raw_text = target.read_text(encoding="utf-8")
    # 剥离文末标准卡片收口三件套（读者互动 / 关注卡片 / 往期推荐），只审计正文主体
    body_only = re.split(
        r"^#{2,3}\s*(?:💬\s*读者互动|🍵\s*关注|🔥\s*往期推荐)",
        raw_text,
        maxsplit=1,
        flags=re.MULTILINE,
    )[0]
    text = body_only
    imgs = re.findall(r"!\[.*?\]\(([^)]+)\)", text)
    bolds = re.findall(r"\*\*[^*\n]+\*\*", text)

    # 剥离标题、分隔线、列表符号、引用块标记与图片后统计纯叙事段落
    clean_text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    clean_text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean_text)
    clean_text = re.sub(r"^#+.*$", "", clean_text, flags=re.MULTILINE)
    clean_text = re.sub(r"^---\s*$", "", clean_text, flags=re.MULTILINE)
    clean_text = re.sub(r"^\s*[-*]\s+", "", clean_text, flags=re.MULTILINE)
    clean_text = re.sub(r"^\s*>\s*", "", clean_text, flags=re.MULTILINE)
    clean_text = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", clean_text)
    clean_text = clean_text.strip()

    total_chars = len(clean_text)
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", clean_text))

    paras = [p.strip() for p in clean_text.split("\n") if p.strip()]
    para_lens = [len(p) for p in paras] or [0]
    p_median = statistics.median(para_lens)
    p_stdev = statistics.stdev(para_lens) if len(para_lens) > 1 else 0.0

    immersive_para_count = len([
        p for p in para_lens
        if DNA_RHYTHM_STANDARD.gate_immersive_len_min <= p <= DNA_RHYTHM_STANDARD.gate_immersive_len_max
    ])
    wall_para_count = len([p for p in para_lens if p > DNA_RHYTHM_STANDARD.gate_wall_para_len_max])
    short_para_count = len([p for p in para_lens if p <= DNA_RHYTHM_STANDARD.gate_short_para_len_max])
    short_para_pct = (short_para_count / max(1, len(para_lens))) * 100.0

    sents = [s.strip() for s in re.split(r"[。！？!?；;\n]+", clean_text) if s.strip()]
    sent_lens = [len(s) for s in sents] or [0]
    short_sent_pct = len([s for s in sent_lens if s <= 15]) / len(sent_lens) * 100.0
    mid_sent_pct = len([s for s in sent_lens if 15 < s <= 35]) / len(sent_lens) * 100.0
    long_sent_pct = len([s for s in sent_lens if s > 35]) / len(sent_lens) * 100.0

    # 禁用词扫描
    forbidden_hits: list[dict[str, Any]] = []
    for fw in FORBIDDEN_WORDS:
        count = len(re.findall(re.escape(fw), clean_text))
        if count > 0:
            forbidden_hits.append({"word": fw, "count": count})

    # 口头禅套话堆叠扫描
    slogan_hits: list[dict[str, Any]] = []
    total_slogan_count = 0
    for sc in SLOGAN_CATCHPHRASES:
        c = clean_text.count(sc)
        if c > 0:
            slogan_hits.append({"phrase": sc, "count": c})
            total_slogan_count += c

    # 联动仓库权威 style_gate 与 anti_ai_gate（排除已由 title_freeze 锁定的 H1 主标题，避免标题问句误触正文低创词）
    style_scan_text = re.sub(r"^#\s+[^\n]*\n?", "", text, flags=re.MULTILINE)
    style_issues = scan_style(style_scan_text)
    style_errors = [
        {"rule": issue.get("rule"), "reason": issue.get("reason"), "snippet": issue.get("match")}
        for issue in style_issues
        if isinstance(issue, dict) and issue.get("severity") == "error"
    ]
    anti_ai_res = analyze_anti_ai(text)
    anti_ai_score = float(anti_ai_res.get("total_ai_score", 0.0))

    # 校验图片路径真实性（若有配图）
    base_dir = Path(run_root).resolve() if run_root else target.parent
    dangling_imgs = [
        p.strip()
        for p in imgs
        if not p.strip().startswith(("http://", "https://", "data:"))
        and not (base_dir / p.strip()).is_file()
    ]

    violations: list[str] = []
    advisories: list[str] = []

    # 1. 字数硬门禁（从 run_profile 读取硬下限，无硬上限）与目标区间 advisory
    if cjk_chars < DNA_RHYTHM_STANDARD.gate_cjk_min:
        violations.append(
            f"正文字数不足深水区底线: {cjk_chars} CJK 字 (底线 >= {DNA_RHYTHM_STANDARD.gate_cjk_min} 字)"
        )
    elif cjk_chars < DNA_RHYTHM_STANDARD.target_cjk_min or cjk_chars > DNA_RHYTHM_STANDARD.target_cjk_max:
        advisories.append(
            f"字数偏离写作目标区间 ({DNA_RHYTHM_STANDARD.target_cjk_min}~{DNA_RHYTHM_STANDARD.target_cjk_max}字): "
            f"当前为 {cjk_chars} CJK 字 (仅作提醒，不阻断发布)"
        )

    # 2. 段落中位数（硬线 37~65，目标 45~65；37<=p_median<45 记入 advisory）
    if p_median < DNA_RHYTHM_STANDARD.gate_para_median_min:
        violations.append(
            f"段落过度碎片化（一句话一行营销号体）: 中位数仅 {p_median:.1f} 字 "
            f"(门禁硬线: >= {DNA_RHYTHM_STANDARD.gate_para_median_min:.0f} 字)"
        )
    elif p_median > DNA_RHYTHM_STANDARD.gate_para_median_max:
        violations.append(
            f"段落中位数过长（缺乏呼吸留白）: {p_median:.1f} 字 "
            f"(门禁硬线: <= {DNA_RHYTHM_STANDARD.gate_para_median_max:.0f} 字)"
        )
    elif p_median < DNA_RHYTHM_STANDARD.target_para_median_min or p_median > DNA_RHYTHM_STANDARD.target_para_median_max:
        advisories.append(
            f"段落中位数偏离最佳写作区间 ({DNA_RHYTHM_STANDARD.target_para_median_min:.0f}~{DNA_RHYTHM_STANDARD.target_para_median_max:.0f}字): "
            f"当前为 {p_median:.1f} 字 (已过门禁硬线，建议优化)"
        )

    # 3. 段落标准差
    if p_stdev < DNA_RHYTHM_STANDARD.gate_para_stdev_min:
        violations.append(
            f"段落节奏死板（缺少长短交错呼吸感）: 标准差仅 {p_stdev:.1f} (要求 >= {DNA_RHYTHM_STANDARD.gate_para_stdev_min:.1f})"
        )

    # 4. 沉浸式拉片长段
    if immersive_para_count < DNA_RHYTHM_STANDARD.gate_immersive_paras_min:
        violations.append(
            f"缺少沉浸式拉片/算账长段({DNA_RHYTHM_STANDARD.gate_immersive_len_min}~{DNA_RHYTHM_STANDARD.gate_immersive_len_max}字): "
            f"当前仅 {immersive_para_count} 段 (要求 >= {DNA_RHYTHM_STANDARD.gate_immersive_paras_min} 段以建立叙事纵深)"
        )

    # 5. 死墙段落
    if wall_para_count > DNA_RHYTHM_STANDARD.gate_wall_paras_max:
        violations.append(
            f"存在 {wall_para_count} 个超过 {DNA_RHYTHM_STANDARD.gate_wall_para_len_max} 字的死墙段落 "
            f"(硬红线: {DNA_RHYTHM_STANDARD.gate_wall_paras_max})"
        )

    # 6. 短碎段占比（硬线 15%~50%，目标 20%~45%；落在 15%~20% 或 45%~50% 记入 advisory）
    if short_para_pct < DNA_RHYTHM_STANDARD.gate_short_para_pct_min:
        violations.append(
            f"短段(<={DNA_RHYTHM_STANDARD.gate_short_para_len_max}字)占比过低: {short_para_pct:.1f}% "
            f"(下限 >= {DNA_RHYTHM_STANDARD.gate_short_para_pct_min:.1f}%)"
        )
    elif short_para_pct > DNA_RHYTHM_STANDARD.gate_short_para_pct_max:
        violations.append(
            f"短碎段(<={DNA_RHYTHM_STANDARD.gate_short_para_len_max}字)占比过高: {short_para_pct:.1f}% "
            f"(上限 <= {DNA_RHYTHM_STANDARD.gate_short_para_pct_max:.1f}%，请将连续碎句合并为沉浸叙事段)"
        )
    elif short_para_pct < DNA_RHYTHM_STANDARD.target_short_para_pct_min or short_para_pct > DNA_RHYTHM_STANDARD.target_short_para_pct_max:
        advisories.append(
            f"短段占比偏离最佳写作区间 ({DNA_RHYTHM_STANDARD.target_short_para_pct_min:.0f}%~{DNA_RHYTHM_STANDARD.target_short_para_pct_max:.0f}%): "
            f"当前为 {short_para_pct:.1f}% (已过门禁硬线，建议优化)"
        )

    if forbidden_hits:
        violations.append(f"发现 AI 禁用套话: {forbidden_hits}")
    if total_slogan_count > 2:
        violations.append(
            f"廉价口号式口头禅堆砌 ({total_slogan_count} 处 > 2): {slogan_hits}，请改用冷峻动作与事实说话"
        )
    if style_errors:
        violations.append(f"触发 style_gate 红线 ({len(style_errors)} 处): {style_errors[:3]}")
    if anti_ai_res.get("invisible_watermarks", {}).get("detected"):
        violations.append(
            f"检出隐形零宽字符水印 ({anti_ai_res['invisible_watermarks']['total_count']} 处): "
            f"{anti_ai_res['invisible_watermarks'].get('breakdown')}"
        )
    if anti_ai_score >= 45.0:
        violations.append(f"anti_ai_gate 综合分超标: {anti_ai_score:.1f} (阈值 < 45.0)")
    if dangling_imgs:
        violations.append(f"存在悬空假图片路径: {dangling_imgs}")

    chars_per_img = round(total_chars / len(imgs), 1) if imgs else 0.0
    bolds_per_1k = round(len(bolds) / max(1, total_chars) * 1000, 2)

    report = {
        "ok": True,
        "schema_version": "dna-audit-v2-mother-calibrated",
        "passed": len(violations) == 0,
        "total_chars": total_chars,
        "cjk_chars": cjk_chars,
        "para_count": len(paras),
        "para_median": round(p_median, 1),
        "para_stdev": round(p_stdev, 1),
        "immersive_para_count": immersive_para_count,
        "wall_para_count": wall_para_count,
        "long_para_count": wall_para_count,  # 兼容旧字段名（指代违规超长死墙段）
        "short_para_pct": round(short_para_pct, 1),
        "sentence_dist": {
            "short_pct": round(short_sent_pct, 1),
            "mid_pct": round(mid_sent_pct, 1),
            "long_pct": round(long_sent_pct, 1),
        },
        "image_count": len(imgs),
        "dangling_images": dangling_imgs,
        "chars_per_img": chars_per_img,
        "bold_count": len(bolds),
        "bolds_per_1k": bolds_per_1k,
        "forbidden_hits": forbidden_hits,
        "slogan_hits": slogan_hits,
        "style_gate_errors": style_errors,
        "anti_ai_score": anti_ai_score,
        "violations": violations,
        "advisories": advisories,
    }

    if write_report and run_root is not None:
        r_root = Path(run_root).resolve()
        write_evidence_json(
            r_root / "review" / "dna-audit-report.json",
            report,
            run_dir=r_root,
            reason="dna_engine:audit_draft_dna",
            author="quality_l2_reviewer",
        )

    return report


def refresh_corpus() -> dict[str, Any]:
    """扫描语料库并更新统计基准。"""
    all_files = [
        f for f in glob.glob(str(RAW_CORPUS_DIR / "*.md")) if not f.endswith("MANIFEST.md")
    ]
    all_paras: list[int] = []
    all_sents: list[int] = []
    total_clean = 0
    total_imgs = 0
    total_bolds = 0

    for fpath in sorted(all_files):
        text = Path(fpath).read_text(encoding="utf-8")
        total_imgs += len(re.findall(r"!\[.*?\]\(.*?\)", text))
        total_bolds += len(re.findall(r"\*\*.*?\*\*", text))
        clean_text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
        clean_text = re.sub(r"^#+.*$", "", clean_text, flags=re.MULTILINE).strip()
        total_clean += len(clean_text)
        for p in [p.strip() for p in clean_text.split("\n") if p.strip()]:
            all_paras.append(len(p))
        for s in [s.strip() for s in re.split(r"[。！？!?；;\n]+", clean_text) if s.strip()]:
            all_sents.append(len(s))

    return {
        "ok": True,
        "scanned_articles": len(all_files),
        "mother_articles_registered": len(CANONICAL_MOTHER_TEXTS),
        "total_clean_chars": total_clean,
    }
