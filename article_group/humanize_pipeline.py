"""humanize_pipeline: Deterministic Polish, Dual Local Gates, and Zhuque Targeted Self-Healing.

Implements the end-to-end humanization architecture:
1. Deterministic Polish: Strips AI clichés, flattens PR jargon, cuts conversational ending questions,
   and injects opening hook & rhythm breaks.
2. Local Dual Gates: anti_ai_gate (< 45.0) + prewrite evidence checks (anchors, hooks, stakes).
3. Zhuque Targeted Self-Healing: Calls Zhuque detector, extracts dangerous sentences (Label 1/2),
   performs surgical rewrites, with max 2 retry rounds and safe human review sheet fallback.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from article_group.anti_ai_gate import check_anti_ai, strip_markdown
from article_group.prewrite import (
    validate_opening_hook,
    validate_realistic_stakes,
    validate_sensory_anchors,
)
from article_group.prompts.human_fingerprints import (
    get_human_fingerprints_instruction,
)

# Common conversational residue to cut completely from endings
CONVERSATIONAL_ENDINGS = [
    r"对此[，,]你怎么看[？?].*$",
    r"欢迎在评论区(留言|讨论|分享).*$",
    r"你有什么看法[？?].*$",
    r"让我们一起(期待|探讨|见证).*$",
    r"希望本文(能|对你).*$",
    r"如果你也喜欢(这篇文章)?.*$",
]

# High-risk clichés and deterministic replacements
CLICHE_REPLACEMENTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"值得一提的是[，,]?"), ""),
    (re.compile(r"不可否认的是[，,]?"), ""),
    (re.compile(r"不可否认[，,]?"), ""),
    (re.compile(r"毋庸置疑[，,]?"), ""),
    (re.compile(r"综上所述[，,]?"), "说到底，"),
    (re.compile(r"总而言之[，,]?"), "说到底，"),
    (re.compile(r"总的来说[，,]?"), "归齐来看，"),
    (re.compile(r"由此可见[，,]?"), "这么一看，"),
    (re.compile(r"众所周知[，,]?"), ""),
    (re.compile(r"不难发现[，,]?"), "明眼人都能看出来，"),
    (re.compile(r"显而易见[，,]?"), "很明显，"),
    (re.compile(r"归根结底[，,]?"), "说到底，"),
    (re.compile(r"从某种意义上(说|讲)[，,]?"), "往深了看，"),
    (re.compile(r"在当今社会[，,]?"), "如今这年月，"),
    (re.compile(r"不仅如此[，,]?"), "更要命的是，"),
    (re.compile(r"毫无疑问[，,]?"), "不用怀疑，"),
]

# PR corporate buzzwords to simplify
BUZZWORD_REPLACEMENTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"赋能"), "撑腰"),
    (re.compile(r"打造"), "做出"),
    (re.compile(r"闭环"), "收尾"),
    (re.compile(r"链路"), "环节"),
    (re.compile(r"底层逻辑"), "根本原因"),
    (re.compile(r"降本增效"), "压缩开支"),
    (re.compile(r"深度融合"), "彻底搅在一块"),
    (re.compile(r"核心竞争力"), "真正看家本领"),
    (re.compile(r"颠覆性"), "翻天覆地"),
]


def deterministic_polish(
    text: str,
    evidence_pack: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    """Perform deterministic rule-based polish to eliminate AI residue and inject human beats."""
    fixes: list[str] = []
    lines = text.splitlines()

    # 1. Strip conversational endings from tail paragraphs
    new_lines = []
    for line in lines:
        cleaned_line = line
        for pat in CONVERSATIONAL_ENDINGS:
            if re.search(pat, cleaned_line):
                cleaned_line = re.sub(pat, "", cleaned_line).rstrip()
                fixes.append(f"切除文末互动套话: {pat}")
        new_lines.append(cleaned_line)
    lines = new_lines

    # 2. Check and fix Opening Hook in first non-empty body paragraph
    if evidence_pack and evidence_pack.get("opening_hook"):
        declared_hook = str(evidence_pack["opening_hook"]).strip()
        in_frontmatter = False
        first_para_idx = -1
        for i, line in enumerate(lines):
            st = line.strip()
            if st == "---":
                in_frontmatter = not in_frontmatter
                continue
            if in_frontmatter:
                continue
            if st.startswith("#") or not st:
                continue
            first_para_idx = i
            break

        if first_para_idx != -1:
            first_para = lines[first_para_idx]
            # If starts with macroscopic cliché, replace opening
            cliche_match = re.match(r"^(近年来|随着.{1,20}的(发展|深入|推进|不断)|在.{1,20}的背景下|在当今|回顾.{1,10})[,，]?", first_para)
            if cliche_match:
                stripped_para = first_para[cliche_match.end():].lstrip()
                lines[first_para_idx] = f"{declared_hook}——{stripped_para}"
                fixes.append("替换首段宏观背景套话为极端动作破题钩子")
            elif declared_hook not in first_para and not any(t in first_para for t in re.findall(r"[\u4e00-\u9fff]{2,4}", declared_hook)):
                lines[first_para_idx] = f"{declared_hook}\n\n{first_para}"
                fixes.append("在首段前置注入动作破题钩子")

    # 3. Apply cliché and buzzword replacements in body
    polished_text = "\n".join(lines)
    for pat, rep in CLICHE_REPLACEMENTS:
        matches = pat.findall(polished_text)
        if matches:
            polished_text = pat.sub(rep, polished_text)
            fixes.append(f"清理AI套话 [{pat.pattern}] -> '{rep}' ({len(matches)}处)")

    for pat, rep in BUZZWORD_REPLACEMENTS:
        matches = pat.findall(polished_text)
        if matches:
            polished_text = pat.sub(rep, polished_text)
            fixes.append(f"平替公关黑话 [{pat.pattern}] -> '{rep}' ({len(matches)}处)")

    # 4. Break symmetric parallelisms: '不是...而是...'
    # When found, split into two punchy sentences
    parallel_match = re.findall(r"不是([^，。；]+)[，,]而是([^，。；]+)", polished_text)
    if parallel_match:
        polished_text = re.sub(
            r"不是([^，。；]+)[，,]而是([^，。；]+)",
            r"这绝非\1。真正的刀刃，恰恰卡在\2。",
            polished_text,
        )
        fixes.append(f"打破对仗排比 (不是...而是...) ({len(parallel_match)}处)")

    return polished_text, fixes


def check_local_gates(
    text: str,
    evidence_pack: dict[str, Any] | None = None,
    article_id: str = "art-001",
) -> dict[str, Any]:
    """Run dual local gates: anti_ai_gate (< 45.0) and prewrite evidence checks."""
    ai_passed, ai_report = check_anti_ai(text)

    evidence_errors: list[str] = []
    if evidence_pack:
        evidence_errors.extend(
            validate_sensory_anchors(evidence_pack, text, article_id=article_id)
        )
        evidence_errors.extend(
            validate_opening_hook(evidence_pack, text, article_id=article_id)
        )
        evidence_errors.extend(
            validate_realistic_stakes(evidence_pack, text, article_id=article_id)
        )

    all_passed = ai_passed and len(evidence_errors) == 0

    return {
        "passed": all_passed,
        "anti_ai_passed": ai_passed,
        "anti_ai_score": ai_report.get("total_score", 0.0),
        "hit_phrases": ai_report.get("hit_phrases", []),
        "hit_vocab": ai_report.get("hit_vocab", []),
        "evidence_passed": len(evidence_errors) == 0,
        "evidence_errors": evidence_errors,
        "full_ai_report": ai_report,
    }


def call_zhuque_check(text: str, split: bool = False, force: bool = True) -> dict[str, Any]:
    """Call Zhuque API via local script, fallback to Playwright Web matrix CLI if API exhausted."""
    cli_path = "/home/allen/dsh/scripts/zhuque_check.py"
    if os.path.exists(cli_path):
        cmd = [cli_path, text]
        if split:
            cmd.append("--split")
        if force:
            cmd.append("--force")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if proc.returncode == 0:
                res = json.loads(proc.stdout)
                if "error" not in res and not res.get("error"):
                    return res
        except Exception:
            pass

    # Fallback to local Playwright matrix CLI
    web_cli = "/home/allen/.agents/skills/zhuque-detector/scripts/zhuque_cli.py"
    python_env = "/home/allen/Projects/ruoyu-film-daily/.venv-tools/bin/python"
    if os.path.exists(web_cli) and os.path.exists(python_env):
        try:
            cmd = [python_env, web_cli, "detect", "--text", text]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            out = proc.stdout
            conf_match = re.search(r"AI 生成综合置信度[：:]\s*`?([\d.]+)%`?", out)
            conf = float(conf_match.group(1)) / 100.0 if conf_match else 0.10

            danger_cnt = 0
            dang_match = re.search(r"🔴 高危疑似 AI.*?\|\s*(\d+)\s*段", out)
            if dang_match:
                danger_cnt = int(dang_match.group(1))

            suspect_cnt = 0
            susp_match = re.search(r"🟡 中度可疑.*?\|\s*(\d+)\s*段", out)
            if susp_match:
                suspect_cnt = int(susp_match.group(1))

            human_cnt = 0
            hum_match = re.search(r"🟢 人工自然.*?\|\s*(\d+)\s*段", out)
            if hum_match:
                human_cnt = int(hum_match.group(1))

            tot = max(1, danger_cnt + suspect_cnt + human_cnt)
            ai_ratio = danger_cnt / tot
            human_ratio = human_cnt / tot
            suspect_ratio = suspect_cnt / tot

            danger_sentences: list[dict[str, Any]] = []
            if "中度可疑片段清单" in out:
                sections = out.split("中度可疑片段清单")[-1].split("=")[0]
                quotes = re.findall(r">\s*(.+)", sections)
                for q in quotes:
                    danger_sentences.append({"label": "2", "text": q.strip()})

            return {
                "softmax_confidence": conf,
                "labels_ratio": {
                    "0": human_ratio,
                    "1": ai_ratio,
                    "2": suspect_ratio,
                },
                "splits": danger_sentences,
            }
        except Exception as e:
            return {"error": f"web_cli_fallback_failed: {e}"}

    return {"error": "all_zhuque_methods_failed"}


def evaluate_zhuque_result(result: dict[str, Any]) -> dict[str, Any]:
    """Evaluate whether Zhuque result satisfies All-Green criteria."""
    if "error" in result:
        return {
            "is_all_green": False,
            "error": result["error"],
            "softmax_confidence": 1.0,
            "human_ratio": 0.0,
            "ai_ratio": 1.0,
            "suspect_ratio": 0.0,
            "danger_sentences": [],
        }

    conf = result.get("softmax_confidence", 1.0)
    labels = result.get("labels_ratio", {})
    human_ratio = labels.get("0", 0.0)
    ai_ratio = labels.get("1", 0.0)
    suspect_ratio = labels.get("2", 0.0)

    # Extract sentences flagged as danger (1) or suspect (2) if split data exists
    danger_sentences: list[dict[str, Any]] = []
    splits = result.get("splits", []) or result.get("data", {}).get("splits", [])
    for item in splits:
        lbl = str(item.get("label", ""))
        txt = item.get("text", "")
        if lbl in ("1", "2") and txt:
            danger_sentences.append({
                "label": lbl,
                "label_name": "AI" if lbl == "1" else "疑似AI",
                "text": txt,
            })

    is_all_green = (ai_ratio == 0.0 and conf < 0.50 and human_ratio >= 0.70)

    return {
        "is_all_green": is_all_green,
        "softmax_confidence": conf,
        "human_ratio": human_ratio,
        "ai_ratio": ai_ratio,
        "suspect_ratio": suspect_ratio,
        "danger_sentences": danger_sentences,
    }


def perform_surgical_repair(
    text: str,
    danger_sentences: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    """Surgically repair sentences identified as AI/suspect by Zhuque."""
    repaired_text = text
    repair_logs: list[str] = []

    for d in danger_sentences:
        target_s = d["text"].strip()
        if not target_s or len(target_s) < 6:
            continue

        # If sentence exists in text, perform targeted breaking and colloquial tone injection
        if target_s in repaired_text:
            replacement = target_s
            # Break compound punctuation
            if "，" in replacement:
                parts = replacement.split("，", 1)
                replacement = f"{parts[0]}。说白了，{parts[1]}"
            elif "、" in replacement:
                replacement = replacement.replace("、", "还有")

            # Remove generic linking markers
            for w in ("因此", "从而", "进而", "展现出", "体现了"):
                if w in replacement:
                    replacement = replacement.replace(w, "")

            if replacement != target_s:
                repaired_text = repaired_text.replace(target_s, replacement, 1)
                repair_logs.append(f"靶向拆解高危句: '{target_s[:15]}...' -> '{replacement[:15]}...'")

    return repaired_text, repair_logs


def run_humanize_pipeline(
    markdown_path: str | Path,
    evidence_pack_path: str | Path | None = None,
    output_path: str | Path | None = None,
    run_zhuque: bool = False,
    max_zhuque_rounds: int = 2,
) -> dict[str, Any]:
    """Execute end-to-end humanization pipeline with local dual gates & Zhuque self-healing."""
    md_file = Path(markdown_path)
    if not md_file.is_file():
        return {"error": f"file_not_found: {markdown_path}"}

    text = md_file.read_text(encoding="utf-8")
    evidence_pack = None
    if evidence_pack_path:
        ev_file = Path(evidence_pack_path)
        if ev_file.is_file():
            try:
                evidence_pack = json.loads(ev_file.read_text(encoding="utf-8"))
            except Exception:
                pass

    audit_trail: list[dict[str, Any]] = []

    # Step 1: Deterministic rule-based polish
    polished_text, initial_fixes = deterministic_polish(text, evidence_pack)
    audit_trail.append({
        "step": "deterministic_polish",
        "fixes_applied": len(initial_fixes),
        "details": initial_fixes,
    })

    # Step 2: Check Local Dual Gates
    local_eval = check_local_gates(polished_text, evidence_pack)
    audit_trail.append({
        "step": "local_dual_gates",
        "passed": local_eval["passed"],
        "anti_ai_score": local_eval["anti_ai_score"],
        "evidence_errors": local_eval["evidence_errors"],
    })

    current_text = polished_text
    zhuque_report: dict[str, Any] | None = None

    # Step 3: Zhuque Check & Self-Healing (if requested and local gates pass)
    if run_zhuque and local_eval["passed"]:
        for round_idx in range(1, max_zhuque_rounds + 1):
            raw_res = call_zhuque_check(current_text, split=True)
            zhuque_eval = evaluate_zhuque_result(raw_res)
            zhuque_report = zhuque_eval

            audit_trail.append({
                "step": f"zhuque_round_{round_idx}",
                "is_all_green": zhuque_eval["is_all_green"],
                "confidence": zhuque_eval["softmax_confidence"],
                "human_ratio": zhuque_eval["human_ratio"],
                "ai_ratio": zhuque_eval["ai_ratio"],
                "danger_count": len(zhuque_eval["danger_sentences"]),
            })

            if zhuque_eval["is_all_green"]:
                break

            # Attempt targeted surgical repair if danger sentences exist
            if round_idx < max_zhuque_rounds and zhuque_eval["danger_sentences"]:
                repaired_text, repair_logs = perform_surgical_repair(
                    current_text, zhuque_eval["danger_sentences"]
                )
                if repair_logs:
                    current_text = repaired_text
                    audit_trail.append({
                        "step": f"surgical_repair_round_{round_idx}",
                        "fixes_applied": len(repair_logs),
                        "details": repair_logs,
                    })
                else:
                    break

    # Save output if specified
    dest_path = Path(output_path) if output_path else md_file
    dest_path.write_text(current_text, encoding="utf-8")

    is_final_passed = local_eval["passed"] and (
        not run_zhuque or (zhuque_report and zhuque_report.get("is_all_green", False))
    )

    return {
        "status": "PASS" if is_final_passed else "NEEDS_CHANGES",
        "file_updated": str(dest_path),
        "local_gates_passed": local_eval["passed"],
        "zhuque_passed": zhuque_report.get("is_all_green", False) if zhuque_report else None,
        "audit_trail": audit_trail,
        "zhuque_report": zhuque_report,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="文章组人工特征注入与脱敏自愈流水线")
    parser.add_argument("input", help="待处理的 Markdown 文件")
    parser.add_argument("--evidence", "-e", help="关联的 evidence-pack.json 路径")
    parser.add_argument("--output", "-o", help="输出路径（默认就地更新）")
    parser.add_argument("--run-zhuque", action="store_true", help="触发朱雀检测与自愈循环")
    parser.add_argument("--max-rounds", type=int, default=2, help="朱雀自愈最大轮次（默认2）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 结果")

    args = parser.parse_args(argv)
    res = run_humanize_pipeline(
        markdown_path=args.input,
        evidence_pack_path=args.evidence,
        output_path=args.output,
        run_zhuque=args.run_zhuque,
        max_zhuque_rounds=args.max_rounds,
    )

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print("=" * 60)
        print(f"人工特征注入与脱敏自愈结果: [{res['status']}]")
        print(f"- 目标文件: {res['file_updated']}")
        print(f"- 本地双门禁: {'PASS' if res['local_gates_passed'] else 'FAIL'}")
        if res['zhuque_passed'] is not None:
            print(f"- 朱雀全绿门禁: {'PASS' if res['zhuque_passed'] else 'FAIL'}")
        print("-" * 60)
        print("执行轨迹 (Audit Trail):")
        for a in res["audit_trail"]:
            step = a.get("step")
            if "fixes_applied" in a:
                print(f"  • [{step}] 应用修复 {a['fixes_applied']} 项")
            elif "anti_ai_score" in a:
                print(f"  • [{step}] 本地评分: {a['anti_ai_score']:.1f} (通过: {a['passed']})")
            elif "confidence" in a:
                print(f"  • [{step}] 朱雀置信度: {a['confidence']:.3f}, 人工占比: {a['human_ratio']*100:.1f}%, AI占比: {a['ai_ratio']*100:.1f}%")
        print("=" * 60)

    return 0 if res["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
