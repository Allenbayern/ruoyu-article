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

AI_PHRASES: list[tuple[str, str]] = [
    (r"首先[,，].{0,12}其次[,，].{0,12}最后", "枚举套话：首先…其次…最后"),
    (r"首先[,，].{0,12}其次[,，].{0,12}再次", "枚举套话：首先…其次…再次"),
    (r"不仅.{0,10}而且", "句式套话：不仅…而且"),
    (r"一方面.{0,15}另一方面", "句式套话：一方面…另一方面"),
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

    # Score mapping: CV <= 0.35 is very flat (AI味 85+); CV >= 0.75 is lively human writing (AI味 ~10)
    if cv <= 0.3:
        score = 90.0
    elif cv >= 0.8:
        score = 10.0
    else:
        score = 90.0 - (cv - 0.3) * (80.0 / 0.5)

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
    """Detect monotonous punctuation."""
    chars = len(text)
    flavor_points = 0
    flavor_points += text.count("——") * 3
    flavor_points += text.count("…") * 2
    flavor_points += text.count("?") + text.count("？")
    flavor_points += (text.count("!") + text.count("！")) // 2
    flavor_points += text.count("(") + text.count("（") + text.count(")") + text.count("）")

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

    return round(float(score), 1), {
        "flavor_points": flavor_points,
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

    total_ai_score = (
        b_score * WEIGHTS["burstiness"]
        + p_score * WEIGHTS["phrases"]
        + v_score * WEIGHTS["vocab"]
        + s_score * WEIGHTS["structural"]
        + pu_score * WEIGHTS["punctuation"]
    )

    if not opening_check["passed"]:
        total_ai_score = min(100.0, total_ai_score + 10.0)

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
    passed = full["total_ai_score"] < threshold and full["opening_hook"]["passed"]
    report = {
        "passed": passed,
        "total_score": full["total_ai_score"],
        "verdict": full["verdict"],
        "threshold": threshold,
        "opening_passed": full["opening_hook"]["passed"],
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
