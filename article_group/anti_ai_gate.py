"""anti_ai_gate: Machine-enforced heuristic anti-AI writing quality gate.

Ported and hardened from ZJU-REAL/Easel & Hermes Article Group rules.
Evaluates Markdown/plain text on 5 physical quantitative dimensions:
1. burstiness (sentence length variance & delta): real writing varies, AI is flat;
2. phrases (AI clichés / transitional filler formulas);
3. vocab (hollow buzzwords & abstract internet corporate jargon);
4. structural_perfection (rigid first/second/third textbook enumeration);
5. punctuation_flatness (monotonous punctuation lacking dashes/questions/parentheses).
Also enforces the Opening Hook rule: no macroscopic cliches ("近年来", "随着...发展") in paragraph 1.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any

DEFAULT_THRESHOLD: float = 45.0

# -----------------------------------------------------------------------------
# Cliché and Jargon Patterns
# -----------------------------------------------------------------------------
#
# 分两组，**计分行为完全不变**（顺序与内容逐字保持原样），区别只在可审计性：
#
#   A. GENRE_TIGHTENED_PHRASES —— 「体裁加严」组：比通用去 AI 规则**有意更严**的条目。
#   B. 其余条目 —— 通用组：与 lieflat-less-ai-tone 等通用去 AI 规则同向。
#
# 为什么需要显式标注（2026-10-15，L2 finding §2）：通用规则源 lieflat-less-ai-tone
# `SKILL.md:103-104` 明确判定「正文里的『首先……其次』」与「句内同构排比」**不是 AI 痕迹**
# （人类用得不比 AI 少），而本门禁对它们计分。这是**有意的体裁加严**（生效体裁：若雨随影
# 公众号影视长文），不是实现与规则源漂移；此前它只存在于代码里、无任何标注，无法审计，
# 故在此显式成组并写明依据。
#
# 决策证据（2026-10-15，量测脚本与结果见同目录）：
#   runs/2026-10-15/baimiao-vs-lieflat-rule-matrix/INTEGRATION-AND-FIXLIST.md §2
#   runs/2026-10-15/baimiao-vs-lieflat-rule-matrix/phrase-weight-measurement.json
# 量测结论：154 篇人类已发表稿件 + 7 篇本院定稿上，phrases/structural 两维中位分均为 0.0，
# 仅 3/154 命中本组条目；反事实把 phrases 权重 0.30→0.20 会翻转的判定为 **0 篇**。
# → 该加严在真实人类语料上是**惰性**的，问题只在「未标注」；因此**保留评分口径**（改权重
#   会破坏历史分数可比性而收益为零），只做标签化。
GENRE_TIGHTENED_SCOPE = "wechat-longform"
GENRE_TIGHTENED_RATIONALE = (
    "lieflat-less-ai-tone/SKILL.md:103-104 判『正文序数路标』与『句内同构排比』为非 AI 痕迹；"
    "本门禁的生效体裁是公众号影视长文，故按体裁加严计分——这是有意的口径差，非实现漂移。"
)
GENRE_TIGHTENED_PHRASES: list[tuple[str, str]] = [
    (r"首先[,，].{0,12}其次[,，].{0,12}最后", "枚举套话：首先…其次…最后"),
    (r"首先[,，].{0,12}其次[,，].{0,12}再次", "枚举套话：首先…其次…再次"),
    (r"不仅.{0,10}而且", "句式套话：不仅…而且"),
    (r"一方面.{0,15}另一方面", "句式套话：一方面…另一方面"),
]

AI_PHRASES: list[tuple[str, str]] = [
    # —— A. 体裁加严组（显式标注；内容与顺序与历史版本逐字一致）——
    *GENRE_TIGHTENED_PHRASES,
    # —— B. 通用组（与通用去 AI 规则同向）——
    (r"值得一提的是", "AI过渡词：值得一提的是"),
    (r"不可否认", "AI过渡词：不可否认"),
    (r"毋庸置疑", "AI过渡词：毋庸置疑"),
    (r"综上所述", "AI总结套话：综上所述"),
    (r"总而言之", "AI总结套话：总而言之"),
    (r"总的来说", "AI总结套话：总的来说"),
    (r"由此可见", "AI过渡词：由此可见"),
    (r"众所周知", "AI大词：众所周知"),
    (r"不难发现", "AI引导词：不难发现"),
    (r"显而易见", "AI过渡词：显而易见"),
    (r"在.{1,15}的背景下", "背景套话：在…的背景下"),
    (r"随着.{1,20}的发展", "宏观套话：随着…的发展"),
    (r"随着.{1,20}的不断", "宏观套话：随着…的不断"),
    (r"让我们一起来", "客服式互动：让我们一起来"),
    (r"让我们共同", "口号套话：让我们共同"),
    (r"归根结底", "AI套话：归根结底"),
    (r"无论如何", "AI过渡词：无论如何"),
    (r"从某种意义上(说|讲)", "端水套话：从某种意义上说"),
    (r"在当今社会", "宏观套话：在当今社会"),
    (r"进入新时代", "空洞套话：进入新时代"),
    (r"在.{1,10}时代", "空洞套话：在…时代"),
    (r"站在.{1,10}的角度", "说教套话：站在…的角度"),
    (r"打开了.{1,10}的大门", "浮夸套话：打开了…的大门"),
    (r"开启了.{1,10}的篇章", "浮夸套话：开启了…的篇章"),
    (r"翻开了.{1,10}新的一页", "浮夸套话：翻开了…新的一页"),
    (r"具有(重要|深远|里程碑)的意义", "空洞评价：具有…意义"),
    (r"产生了(深远|重大|巨大)的影响", "空洞评价：产生了…影响"),
]


def is_genre_tightened(pattern: str) -> bool:
    """该 pattern 是否属于「体裁加严」组（供审计/报告使用，不参与计分）。"""
    return any(pat == pattern for pat, _ in GENRE_TIGHTENED_PHRASES)

AI_VOCAB: list[str] = [
    "赋能", "打造", "聚焦", "深度融合", "生态", "闭环", "链路", "抓手",
    "价值链", "护城河", "方法论", "底层逻辑", "生态位", "结构化思维",
    "提升效率", "助力", "全链路", "一站式", "端到端", "量变到质变",
    "引领", "颠覆", "革命性", "前所未有", "核心竞争力", "范式", "新范式",
    "降本增效", "数字化转型", "智能化", "生态体系", "产业升级",
    "破局", "出圈", "破圈", "沉淀", "赋予", "深耕", "蓝图", "新篇章",
]

OPENING_CLICHE_PATTERN = re.compile(
    r"^(近年来|随着.{1,20}的(发展|深入|推进|不断)|在.{1,20}的背景下|在当今|回顾.{1,10})"
)

# -----------------------------------------------------------------------------
# Zero-width & Invisible Watermark Characters (AIGC Steganography & Trace)
# -----------------------------------------------------------------------------
# 常见于 AI 生成内容在字间夹带的隐形指纹/零宽字符（如 watermarks-remover 等工具审计重点）：
# U+200B: ZERO WIDTH SPACE (零宽空格)
# U+200C: ZERO WIDTH NON-JOINER (零宽非连接符)
# U+200D: ZERO WIDTH JOINER (零宽连接符)
# U+2060: WORD JOINER (词连接符)
# U+FEFF: ZERO WIDTH NO-BREAK SPACE / BOM (零宽无间断空格)
ZERO_WIDTH_CHARS = {
    "\u200b": "ZERO WIDTH SPACE (U+200B)",
    "\u200c": "ZERO WIDTH NON-JOINER (U+200C)",
    "\u200d": "ZERO WIDTH JOINER (U+200D)",
    "\u2060": "WORD JOINER (U+2060)",
    "\ufeff": "ZERO WIDTH NO-BREAK SPACE (U+FEFF)",
}
ZERO_WIDTH_PATTERN = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")


def scan_invisible_watermarks(text: str) -> dict[str, Any]:
    """Scan for invisible zero-width watermark characters in text.

    Returns detection summary including positions, counts, and character types.
    """
    findings: list[dict[str, Any]] = []
    char_counts: dict[str, int] = {}
    for idx, ch in enumerate(text):
        if ch in ZERO_WIDTH_CHARS:
            name = ZERO_WIDTH_CHARS[ch]
            char_counts[name] = char_counts.get(name, 0) + 1
            if len(findings) < 20:  # Sample up to 20 locations
                findings.append({
                    "char": name,
                    "index": idx,
                    "context": text[max(0, idx - 5): min(len(text), idx + 6)].replace(ch, "[HIDDEN]"),
                })
    total_count = sum(char_counts.values())
    return {
        "detected": total_count > 0,
        "total_count": total_count,
        "breakdown": char_counts,
        "samples": findings,
    }


def clean_invisible_watermarks(text: str) -> tuple[str, int]:
    """Strip all invisible zero-width watermark characters from text.

    Returns (cleaned_text, removed_count).
    """
    cleaned, count = ZERO_WIDTH_PATTERN.subn("", text)
    return cleaned, count


# -----------------------------------------------------------------------------
# Text Preprocessing & Helpers
# -----------------------------------------------------------------------------

def strip_markdown(text: str) -> str:
    """Strip markdown formatting, retaining raw text for prose analysis."""
    # Code blocks
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    # Inline code
    text = re.sub(r"`[^`]+`", " ", text)
    # Images & Links
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Custom highlight marks
    text = re.sub(r"(?:==|\+\+|%%|&&|!!|@@|\^\^)([^=\+\%&!@\^\n]+)(?:==|\+\+|%%|&&|!!|@@|\^\^)", r"\1", text)
    # Bold / Italic
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*\n]+)\*", r"\1", text)
    # Headings / Blockquotes / Lists
    text = re.sub(r"^\s*#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*>\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    # Tables
    text = re.sub(r"^\|.*\|$", " ", text, flags=re.MULTILINE)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    """Split text into sentences by Chinese and English punctuation."""
    parts = re.split(r"(?<=[。！？!?；;])", text)
    return [p.strip() for p in parts if p.strip()]


# -----------------------------------------------------------------------------
# Metric Computations
# -----------------------------------------------------------------------------

def score_burstiness(sentences: list[str]) -> tuple[float, dict[str, Any]]:
    """Burstiness score (0-100, higher = more AI/less variance)."""
    if len(sentences) < 3:
        return 40.0, {"cv": None, "reason": "too_few_sentences"}
    lengths = [len(s) for s in sentences]
    mean_val = statistics.mean(lengths)
    stdev_val = statistics.stdev(lengths) if len(lengths) > 1 else 0.0
    cv = (stdev_val / mean_val) if mean_val > 0 else 0.0

    # Max delta between adjacent sentences
    max_adjacent_delta = 0
    for i in range(len(lengths) - 1):
        delta = abs(lengths[i] - lengths[i + 1])
        if delta > max_adjacent_delta:
            max_adjacent_delta = delta

    # Short sentence presence (5-12 chars)
    short_sentence_count = sum(1 for ln in lengths if 5 <= ln <= 12)

    # Score mapping calibrated with 2.83M corpus data:
    # CV <= 0.25 is truly robotic/flat (AI score 85+);
    # CV in 0.45-0.70 is standard human prose range (AI score ~25-45);
    # CV >= 0.70 is lively human writing (AI score ~10).
    if cv <= 0.25:
        score = 85.0
    elif cv >= 0.70:
        score = 10.0
    else:
        score = 85.0 - (cv - 0.25) * (75.0 / 0.45)

    # Penalty if no adjacent sentence jump > 12 chars
    if max_adjacent_delta < 12:
        score = min(100.0, score + 15.0)

    # Bonus if there are rhythmic punchy short sentences
    if short_sentence_count >= 2:
        score = max(0.0, score - 10.0)

    return round(score, 1), {
        "sentence_count": len(sentences),
        "mean_length": round(mean_val, 1),
        "stdev": round(stdev_val, 1),
        "cv": round(cv, 3),
        "max_adjacent_delta": max_adjacent_delta,
        "short_sentence_count": short_sentence_count,
    }


def score_phrases(text: str) -> tuple[float, dict[str, Any]]:
    """AI cliché hit score with span de-duplication."""
    seen_spans: dict[tuple[int, int], tuple[str, str]] = {}
    for pat, label in AI_PHRASES:
        for m in re.finditer(pat, text):
            span = (m.start(), m.end())
            if span not in seen_spans:
                seen_spans[span] = (m.group(0), label)

    # Filter nested spans
    spans = sorted(seen_spans.keys(), key=lambda s: (s[0], -s[1]))
    kept: list[tuple[str, str]] = []
    for span in spans:
        contained = any(
            other != span and other[0] <= span[0] and other[1] >= span[1]
            for other in seen_spans.keys()
        )
        if not contained:
            kept.append(seen_spans[span])

    hit_count = len(kept)
    score = min(100.0, hit_count * 18.0)
    samples = [f"{text_snippet} ({desc})" for text_snippet, desc in kept[:10]]

    return round(score, 1), {
        "hit_count": hit_count,
        "samples": samples,
    }


def score_vocab(text: str) -> tuple[float, dict[str, Any]]:
    """Internet buzzword / corporate jargon density score."""
    hits: dict[str, int] = {}
    for word in AI_VOCAB:
        c = text.count(word)
        if c > 0:
            hits[word] = c
    total_hits = sum(hits.values())
    char_count = max(1, len(text))
    density_per_1k = total_hits / (char_count / 1000.0)

    if density_per_1k <= 1.5:
        score = density_per_1k * 15.0  # 0 - 22.5
    elif density_per_1k <= 4.0:
        score = 22.5 + (density_per_1k - 1.5) * 20.0  # 22.5 - 72.5
    else:
        score = min(100.0, 72.5 + (density_per_1k - 4.0) * 8.0)

    top_hits = sorted(hits.items(), key=lambda x: -x[1])[:10]
    return round(score, 1), {
        "total_hits": total_hits,
        "density_per_1k": round(density_per_1k, 2),
        "top": top_hits,
    }


def score_structural_perfection(text: str) -> tuple[float, dict[str, Any]]:
    """Detect mechanical enumeration structures (第一...第二...第三...)."""
    bad_patterns = [
        r"第一[,，、].{0,80}第二[,，、].{0,80}第三",
        r"一[是、][^。]{0,60}二[是、][^。]{0,60}三[是、]",
    ]
    hits = 0
    for pat in bad_patterns:
        hits += len(re.findall(pat, text))
    score = min(100.0, hits * 35.0)
    return round(float(score), 1), {"hit_count": hits}


def score_punctuation_flatness(text: str) -> tuple[float, dict[str, Any]]:
    """Detect monotonous punctuation.
    Calibrated with 2.83M corpus data:
    - Questions (?/？) are 17x more frequent in human writing (strong human beat).
    - Em-dashes (——) are 3-6x MORE frequent in AI (esp. DeepSeek 5.16/1k vs Human 0.80/1k),
      so dashes MUST NOT be rewarded as human flavor, and excessive density is penalized.
    """
    chars = len(text)
    flavor_points = 0
    # Questions are strong human indicators
    flavor_points += (text.count("?") + text.count("？")) * 2
    flavor_points += text.count("…") * 2
    flavor_points += (text.count("!") + text.count("！")) // 2
    flavor_points += text.count("(") + text.count("（") + text.count(")") + text.count("）")

    # Em-dash check: AI (especially DeepSeek) abuses dashes
    em_dash_count = text.count("——")
    em_dash_density_1k = (em_dash_count / (chars / 1000.0)) if chars > 0 else 0.0

    expected = max(chars, 200) / 1000.0 * 5.0
    ratio = (flavor_points / expected) if expected > 0 else 0.0

    if ratio >= 1.0:
        score = 10.0
    elif ratio >= 0.5:
        score = 30.0
    elif ratio >= 0.2:
        score = 60.0
    else:
        score = 85.0

    # Penalty if em-dash density exceeds human normal ceiling (> 2.5 per 1k chars)
    if em_dash_density_1k > 2.5 and em_dash_count >= 3:
        score = min(100.0, score + 20.0)

    return round(float(score), 1), {
        "flavor_points": flavor_points,
        "em_dash_count": em_dash_count,
        "em_dash_density_1k": round(em_dash_density_1k, 2),
        "expected": round(expected, 1),
        "ratio": round(ratio, 2),
    }


def check_opening_hook(raw_text: str) -> dict[str, Any]:
    """Check paragraph 1 for macroscopic cliché openings."""
    paragraphs = [p.strip() for p in raw_text.splitlines() if p.strip() and not p.strip().startswith("#")]
    if not paragraphs:
        return {"passed": True, "detail": "empty_content"}
    first_p = paragraphs[0]
    m = OPENING_CLICHE_PATTERN.search(first_p)
    if m:
        return {
            "passed": False,
            "matched": m.group(0),
            "paragraph_snippet": first_p[:60],
            "advice": "第一段禁止以'近年来/随着...发展/在...背景下'切入，应换成具体场景、台词、数字或冲突事实。",
        }
    return {"passed": True, "paragraph_snippet": first_p[:60]}


def check_paragraph_length(raw_text: str, max_chars: int = 180) -> dict[str, Any]:
    """Check for excessively long paragraphs (> max_chars) that hurt mobile WeChat readability."""
    paragraphs = [p.strip() for p in raw_text.splitlines() if p.strip() and not p.strip().startswith(("#", "```", "|", ">", "-"))]
    long_paras = []
    for idx, p in enumerate(paragraphs, start=1):
        clean_p = re.sub(r"\s+", "", p)
        if len(clean_p) > max_chars:
            long_paras.append({
                "index": idx,
                "length": len(clean_p),
                "snippet": p[:40] + "...",
            })
    return {
        "passed": len(long_paras) == 0,
        "count": len(long_paras),
        "long_paragraphs": long_paras,
        "advice": f"检测到 {len(long_paras)} 个过长段落（超 {max_chars} 字符），建议按手机端 3~4 行屏宽进行拆解" if long_paras else "段落长度符合手机阅读体验",
    }


# -----------------------------------------------------------------------------
# Overall Analysis & Gate Contract
# -----------------------------------------------------------------------------

WEIGHTS = {
    "burstiness": 0.30,
    "phrases": 0.30,
    "vocab": 0.20,
    "structural": 0.10,
    "punctuation": 0.10,
}


def analyze_anti_ai(raw_text: str) -> dict[str, Any]:
    """Perform a comprehensive heuristic anti-AI audit on the text."""
    plain = strip_markdown(raw_text)
    sentences = split_sentences(plain)

    b_score, b_det = score_burstiness(sentences)
    p_score, p_det = score_phrases(plain)
    v_score, v_det = score_vocab(plain)
    s_score, s_det = score_structural_perfection(plain)
    pu_score, pu_det = score_punctuation_flatness(plain)

    opening_check = check_opening_hook(raw_text)
    paragraph_check = check_paragraph_length(raw_text, max_chars=180)
    watermark_check = scan_invisible_watermarks(raw_text)

    total_ai_score = (
        b_score * WEIGHTS["burstiness"]
        + p_score * WEIGHTS["phrases"]
        + v_score * WEIGHTS["vocab"]
        + s_score * WEIGHTS["structural"]
        + pu_score * WEIGHTS["punctuation"]
    )

    if not opening_check["passed"]:
        total_ai_score = min(100.0, total_ai_score + 10.0)

    # Moderate penalty if mobile WeChat readability is impaired by >= 3 long paragraphs (> 180 chars)
    if paragraph_check["count"] >= 3:
        total_ai_score = min(100.0, total_ai_score + 5.0)

    # Invisible watermark characters (U+200B etc.) indicate explicit machine steganography
    if watermark_check["detected"]:
        # Direct significant AI penalty if invisible zero-width chars are detected
        total_ai_score = min(100.0, total_ai_score + min(30.0, watermark_check["total_count"] * 10.0))

    if total_ai_score < 35.0:
        verdict = "PASS"
    elif total_ai_score < 50.0:
        verdict = "WARN"
    else:
        verdict = "FAIL"

    return {
        "total_ai_score": round(total_ai_score, 1),
        "verdict": verdict,
        "char_count": len(plain),
        "sentence_count": len(sentences),
        "opening_hook": opening_check,
        "paragraph_length": paragraph_check,
        "invisible_watermarks": watermark_check,
        "dimensions": {
            "burstiness": {"score": b_score, "detail": b_det},
            "phrases": {"score": p_score, "detail": p_det},
            "vocab": {"score": v_score, "detail": v_det},
            "structural": {"score": s_score, "detail": s_det},
            "punctuation": {"score": pu_score, "detail": pu_det},
        },
        "weights": WEIGHTS,
    }


def check_anti_ai(
    text: str,
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[bool, dict[str, Any]]:
    """Main gate API: returns (passed, report)."""
    full = analyze_anti_ai(text)
    # Zero-width watermarks strictly fail the gate
    passed = (
        full["total_ai_score"] < threshold
        and full["opening_hook"]["passed"]
        and not full["invisible_watermarks"]["detected"]
    )
    report = {
        "passed": passed,
        "total_score": full["total_ai_score"],
        "verdict": full["verdict"],
        "threshold": threshold,
        "opening_passed": full["opening_hook"]["passed"],
        "paragraph_passed": full["paragraph_length"]["passed"],
        "watermark_passed": not full["invisible_watermarks"]["detected"],
        "watermark_count": full["invisible_watermarks"]["total_count"],
        "hit_phrases": full["dimensions"]["phrases"]["detail"].get("samples", []),
        "hit_vocab": [f"{w}×{c}" for w, c in full["dimensions"]["vocab"]["detail"].get("top", [])],
        "full_report": full,
    }
    return passed, report


# -----------------------------------------------------------------------------
# CLI Entry Point
# -----------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="反 AI 感写作量化门禁")
    parser.add_argument("input", help="要检查的 Markdown 文件路径")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出完整报告")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help=f"失败阈值（默认 {DEFAULT_THRESHOLD}）")

    args = parser.parse_args(argv)

    path = Path(args.input)
    if not path.is_file():
        print(f"错误: 文件不存在 {path}", file=sys.stderr)
        return 2

    text = path.read_text(encoding="utf-8")
    passed, report = check_anti_ai(text, threshold=args.threshold)

    if args.json:
        print(json.dumps(report["full_report"], ensure_ascii=False, indent=2))
    else:
        full = report["full_report"]
        print("=" * 60)
        print(f"反 AI 感检测报告 —— [{full['verdict']}]")
        print("=" * 60)
        print(f"综合 AI 味评分: {full['total_ai_score']} / 100 (阈值: {args.threshold})")
        print(f"字数: {full['char_count']}  句数: {full['sentence_count']}")
        print(f"开头破冰检查: {'✅ PASS' if full['opening_hook']['passed'] else '❌ FAIL: ' + full['opening_hook'].get('advice', '')}")
        wm = full.get("invisible_watermarks", {})
        wm_status = "✅ PASS" if not wm.get("detected") else f"❌ FAIL: 检出 {wm.get('total_count')} 处隐形零宽字符水印"
        print(f"隐形水印检查: {wm_status}")
        para_status = "✅ PASS" if full["paragraph_length"]["passed"] else f"⚠️ WARN: 存在 {full['paragraph_length']['count']} 个超长段落(>180字)"
        print(f"段落屏宽检查: {para_status}")
        print("-" * 60)
        for name, dim in full["dimensions"].items():
            print(f"  [{name:12s}] 得分: {dim['score']:>5} (权重: {int(WEIGHTS[name]*100)}%)")
        if report["hit_phrases"]:
            print("\n命中套话样本:")
            for p in report["hit_phrases"]:
                print(f"  - {p}")
        if report["hit_vocab"]:
            print(f"\n高频黑话词汇: {', '.join(report['hit_vocab'])}")
        print("=" * 60)

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
