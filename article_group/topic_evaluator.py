"""topic_evaluator: 7-dimension feasibility & viral potential evaluator for article topics.

Ported and refined from ZJU-REAL/Easel 'skill-topic-evaluator' for Ruoyu Film Daily.
Evaluates film/cultural topics across seven standardized dimensions:
1. traffic_potential (25%): audience pain point, viral controversy, discussion volume
2. persona_fit (20%): alignment with Ruoyu's sharp editorial stance & deep film analysis
3. differentiation (20%): low saturation, unique killer stance, anti-cliché angle
4. evergreen_value (10%): longevity beyond transient gossip, long-term archival value
5. penetration (10%): shareability, strong reader resonance, quotable takeaways
6. evidence_feasibility (10%): first-hand speeches, box office data, ledger backing
7. compliance_safety (5%): safe from platform bans, toxic fandom wars, redlines

Verdicts:
- score >= 75: GO (立即推进入候选池)
- 55 <= score < 75: PIVOT (调整切入角度后再评，附具体优化建议)
- score < 55: DROP (果断放弃，提供替代视角)
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

DIMENSION_WEIGHTS: dict[str, float] = {
    "traffic_potential": 0.25,
    "persona_fit": 0.20,
    "differentiation": 0.20,
    "evergreen_value": 0.10,
    "penetration": 0.10,
    "evidence_feasibility": 0.10,
    "compliance_safety": 0.05,
}

DIMENSION_NAMES: dict[str, str] = {
    "traffic_potential": "流量潜力 (热度与情绪共鸣)",
    "persona_fit": "定位契合 (若雨锋芒与深度)",
    "differentiation": "竞争差异 (独家靶子与反直觉)",
    "evergreen_value": "长青价值 (耐读度与行业留存)",
    "penetration": "传播穿透 (转发冲动与金句点)",
    "evidence_feasibility": "证据可行 (一手资料与账本支持)",
    "compliance_safety": "合规安全 (避开劣质低俗与非理智撕扯)",
}


def evaluate_topic(
    *,
    title: str,
    scores: dict[str, float] | None = None,
    notes: dict[str, str] | None = None,
    custom_advice: list[str] | None = None,
) -> dict[str, Any]:
    """Calculate weighted score and formulate decision verdict."""
    notes = notes or {}
    custom_advice = custom_advice or []

    if not scores:
        return {
            "title": title,
            "total_score": 0.0,
            "verdict": "UNVERIFIED",
            "summary": "未提供各维度评分证据，无法给出决策判定。",
            "dimensions": {},
            "recommendations": ["必须传入至少一项量化维度评分（或完整的7维打分），不可使用默认分数虚假通过。"],
        }

    total_score = 0.0
    dim_details: dict[str, Any] = {}

    for key, weight in DIMENSION_WEIGHTS.items():
        raw_score = float(scores.get(key, 5.0))
        # Clamp to 1.0 - 10.0
        raw_score = max(1.0, min(10.0, raw_score))
        weighted_score = raw_score * 10.0 * weight
        total_score += weighted_score

        dim_details[key] = {
            "name": DIMENSION_NAMES[key],
            "raw_score": raw_score,
            "weight": weight,
            "weighted_score": round(weighted_score, 1),
            "note": notes.get(key, ""),
        }

    total_score = round(total_score, 1)

    if total_score >= 75.0:
        verdict = "GO"
        summary = "高潜力选题：事实靶子明确，高度契合若雨锋芒，建议立即排期推进。"
    elif total_score >= 55.0:
        verdict = "PIVOT"
        summary = "有价值但切口需重构：需调整切入靶子，强化一手证据或拔高行业机制。"
    else:
        verdict = "DROP"
        summary = "不建议推进：受众共鸣不足或同质化严重，投入产出比过低。"

    recommendations: list[str] = list(custom_advice)
    if verdict == "PIVOT" and not recommendations:
        if scores.get("differentiation", 5.0) < 6.0:
            recommendations.append("避开全网已被说烂的大众槽点，转向深挖背后的产业机制或利益分账逻辑。")
        if scores.get("evidence_feasibility", 5.0) < 6.0:
            recommendations.append("当前缺乏一手原声或可靠主创访谈，先建立不确定性核查表，补齐事实账本。")
        if scores.get("traffic_potential", 5.0) < 6.0:
            recommendations.append("将冷门专业术语包装为普通观众可感知的真实困境（如'观众为啥觉得被骗了'）。")

    return {
        "title": title,
        "total_score": total_score,
        "verdict": verdict,
        "summary": summary,
        "dimensions": dim_details,
        "recommendations": recommendations,
    }


def format_markdown_report(report: dict[str, Any]) -> str:
    """Format evaluation dictionary into standard editorial Markdown."""
    lines = [
        f"# 选题可行性评估报告：{report['title']}",
        f"\n**综合得分**：`{report['total_score']} / 100`  |  **决策判定**：**【{report['verdict']}】**",
        f"**评审结论**：{report['summary']}\n",
        "## 七维量化评分明细\n",
        "| 评估维度 | 原始分 (1-10) | 权重 | 加权分 | 评审依据 |",
        "|---|---|---|---|---|",
    ]
    for key, d in report["dimensions"].items():
        lines.append(f"| {d['name']} | {d['raw_score']} | {int(d['weight']*100)}% | {d['weighted_score']} | {d['note']} |")

    if report["recommendations"]:
        lines.append("\n## 优化与行动建议\n")
        for i, rec in enumerate(report["recommendations"], 1):
            lines.append(f"{i}. {rec}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="若雨随影 选题七维可行性与爆款潜力评估工具")
    parser.add_argument("title", help="选题名称或核心主题")
    parser.add_argument("--scores", help="JSON 格式传入 7 维打分字典，如 '{\"traffic_potential\": 8}'")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")

    args = parser.parse_args(argv)

    raw_scores = {}
    if args.scores:
        try:
            raw_scores = json.loads(args.scores)
        except Exception as e:
            print(f"解析 scores JSON 失败: {e}", file=sys.stderr)
            return 2

    if not raw_scores:
        print("错误: 必须通过 --scores 传入评分字典（如 --scores '{\"traffic_potential\": 8}'），不可无证据评估。", file=sys.stderr)
        return 1

    report = evaluate_topic(title=args.title, scores=raw_scores)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_markdown_report(report))

    return 0


if __name__ == "__main__":
    sys.exit(main())
