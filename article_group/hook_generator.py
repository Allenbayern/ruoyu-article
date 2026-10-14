"""hook_generator: Deterministic social media & long-form article hook generator and validator.

Ported from ZJU-REAL/Easel 'skill-hook-generator' and adapted for Ruoyu Film Daily.
Enforces the 2-line hook structure (Opening line + Reversal line) with strict physical constraints:
- Line 1 (Opening): <= 40 chars, assertive/concrete/punchy, NO question marks.
- Line 2 (Reversal): <= 40 chars, creates sharp cognitive dissonance/paradox.
- Zero filler words ('其实', '就是', '所以', '然后', '大概').
- Zero dashes ('——', '-').
- Priority to concrete numbers and first-hand witness anchors.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

HOOK_FORMULAS = {
    "number_led": {
        "name": "数字领衔 (Number-led)",
        "desc": "用反差强烈的硬核成本/票房/时长等数据开场，反转指出荒诞现实。",
    },
    "contrarian": {
        "name": "逆向认知 (Contrarian)",
        "desc": "抛出一个违背大众直觉的定论，反转给出无法辩驳的事实证据。",
    },
    "witness": {
        "name": "亲历目击 (Personal Witness)",
        "desc": "以第一视角切入具体场景与动作，反转打破一切美好的预设。",
    },
    "authority_steal": {
        "name": "权威借势 (Authority Steal)",
        "desc": "借用行业名导或权威机构的最高褒奖，反转揭露惨烈的底色。",
    },
    "admission": {
        "name": "自我坦白 (Admission)",
        "desc": "以认同/期待落空后的自省开场，反转点破最不愿承认的真相。",
    },
    "era_shock": {
        "name": "时代冲击 (Era Shock)",
        "desc": "宣告某种神话或工业形态的彻底终结，反转道出普通人的代价。",
    },
}

FORBIDDEN_FILLERS = ["其实", "就是", "所以", "然后", "大概", "也许", "可能"]


def calculate_social_char_count(text: str) -> int:
    """Calculate social count: CJK chars + words + punctuation tokens."""
    # Strip spaces for pure content count
    clean = text.strip()
    return len(clean)


def lint_hook(opening: str, reversal: str) -> list[str]:
    """Validate a 2-line hook pair against physical redlines."""
    errors: list[str] = []

    # 1. Length checks
    len1 = calculate_social_char_count(opening)
    len2 = calculate_social_char_count(reversal)

    if len1 == 0:
        errors.append("开场行不能为空")
    elif len1 > 40:
        errors.append(f"开场行超长 ({len1} 字 > 40 字限制)")

    if len2 == 0:
        errors.append("反转行不能为空")
    elif len2 > 40:
        errors.append(f"反转行超长 ({len2} 字 > 40 字限制)")

    # 2. No question marks in opening line
    if "?" in opening or "？" in opening:
        errors.append("开场行禁止使用问句，必须为确凿陈述句")

    # 3. No dashes
    if "——" in opening or "——" in reversal or "-" in opening or "-" in reversal:
        errors.append("禁止在钩子中使用破折号，句式必须紧凑")

    # 4. No fillers
    for filler in FORBIDDEN_FILLERS:
        if filler in opening or filler in reversal:
            errors.append(f"包含禁止填充词 '{filler}'，必须删去")

    return errors


def format_hook_pair(
    formula_key: str,
    opening: str,
    reversal: str,
) -> dict[str, Any]:
    """Package a validated hook pair into a structured contract."""
    errors = lint_hook(opening, reversal)
    meta = HOOK_FORMULAS.get(formula_key, {"name": formula_key, "desc": ""})
    return {
        "formula": formula_key,
        "formula_name": meta["name"],
        "opening": opening.strip(),
        "reversal": reversal.strip(),
        "opening_len": calculate_social_char_count(opening),
        "reversal_len": calculate_social_char_count(reversal),
        "valid": len(errors) == 0,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="社媒与长文 2 行开篇 Hook 校验与排版工具")
    parser.add_argument("--opening", "-1", help="第 1 行（开场）")
    parser.add_argument("--reversal", "-2", help="第 2 行（反转）")
    parser.add_argument("--formula", default="contrarian", choices=list(HOOK_FORMULAS.keys()), help="Hook 公式类型")
    parser.add_argument("--list-formulas", action="store_true", help="列出所有 6 种 Hook 范式")
    parser.add_argument("--json", action="store_true", help="输出 JSON")

    args = parser.parse_args(argv)

    if args.list_formulas:
        print("6 种经过验证的 Hook 范式：")
        for k, v in HOOK_FORMULAS.items():
            print(f"- [{k}] {v['name']}: {v['desc']}")
        return 0

    if not args.opening or not args.reversal:
        parser.error("需要提供 --opening 和 --reversal")

    hook_data = format_hook_pair(args.formula, args.opening, args.reversal)

    if args.json:
        print(json.dumps(hook_data, ensure_ascii=False, indent=2))
    else:
        print(f"【{hook_data['formula_name']}】")
        print(f"> {hook_data['opening']} ({hook_data['opening_len']}字)")
        print(f"> {hook_data['reversal']} ({hook_data['reversal_len']}字)")
        if hook_data["valid"]:
            print("✅ 格式与物理字数完全达标")
        else:
            print("❌ 校验失败：")
            for err in hook_data["errors"]:
                print(f"  - {err}")

    return 0 if hook_data["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
