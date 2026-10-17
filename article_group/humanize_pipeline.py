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
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from article_group.anti_ai_gate import check_anti_ai, strip_markdown
from article_group.lieflat_checks import run_lieflat_checks
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

# High-risk clichés and deterministic removals/replacements
# Grounded in 2.83M corpus research:
# - Cut empty signposts directly instead of replacing with flip formulas like '说到底'
# - Direct positive assertions have lower AI-tell rates than defensive/reframe openers
CLICHE_REPLACEMENTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"值得一提的是[，,]?"), ""),
    (re.compile(r"不可否认的是[，,]?"), ""),
    (re.compile(r"不可否认[，,]?"), ""),
    (re.compile(r"毋庸置疑[，,]?"), ""),
    (re.compile(r"综上所述[，,]?"), ""),
    (re.compile(r"总而言之[，,]?"), ""),
    (re.compile(r"总的来说[，,]?"), ""),
    (re.compile(r"由此可见[，,]?"), ""),
    (re.compile(r"众所周知[，,]?"), ""),
    (re.compile(r"不难发现[，,]?"), ""),
    (re.compile(r"显而易见[，,]?"), ""),
    (re.compile(r"归根结底[，,]?"), ""),
    (re.compile(r"从某种意义上(说|讲)[，,]?"), ""),
    (re.compile(r"在当今社会[，,]?"), "如今，"),
    (re.compile(r"不仅如此[，,]?"), ""),
    (re.compile(r"毫无疑问[，,]?"), ""),
    (re.compile(r"说白了[，,]?"), ""),
    (re.compile(r"说穿了[，,]?"), ""),
    (re.compile(r"先说结论[，,：:]?"), ""),
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

# Formal bureaucratic words to conversational plain Chinese (ported from HelpWriting / shuorenhua)
FORMAL_REPLACEMENTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"较为(?=[\u4e00-\u9fff])"), "比较"),
    (re.compile(r"无法(?=[\u4e00-\u9fff])"), "没法"),
    (re.compile(r"能够(?=[\u4e00-\u9fff])"), "能"),
    (re.compile(r"从而(?=[\u4e00-\u9fff])"), "这样就能"),
    (re.compile(r"通过(?=[\u4e00-\u9fff]{2,8}(?:来|去|实现|达成|完成))"), "靠"),
    (re.compile(r"进行(?=(?:深入|全面|系统|重点)?(?:分析|排查|梳理|对比|交涉|调查|沟通|探讨))"), "做"),
]


def _mask_protected_spans(text: str) -> tuple[str, list[str]]:
    """Protect dialogue, blockquotes, and code blocks from overzealous regex alterations."""
    spans: list[str] = []

    def repl(m: re.Match) -> str:
        idx = len(spans)
        spans.append(m.group(0))
        return f"__RUOYU_PROTECTED_SPAN_{idx}__"

    # Protect code blocks, quoted speech, and markdown quotes
    pattern = re.compile(
        r"```[\s\S]*?```|[“\"][^”\"\n]{1,250}[”\"]|[「\'][^」\'\n]{1,250}[」\']|^>.*$",
        re.M,
    )
    masked = pattern.sub(repl, text)
    return masked, spans


def _unmask_protected_spans(text: str, spans: list[str]) -> str:
    for idx, span in enumerate(spans):
        text = text.replace(f"__RUOYU_PROTECTED_SPAN_{idx}__", span)
    return text


# 2026-10-16 E1 复盘（runs/2026-10-16-model-ablation-E1/E1-REPORT.md）：阶段1 的
# 机械替换曾在 12/15 稿里制造乱标点与语法崩坏（例：「而他却不是走向沉默，而是走向了
# 荒漠。」→「而他却这并非走向沉默，核心在于走向了荒漠。。」）。这里给所有表驱动替换
# 加一道确定性护栏：任何一条替换只要**增加**乱标点计数，就整体回滚该条并留痕。
_MALFORMED_PUNCT = re.compile(r"。。|。，|，。|：。|。：|，、|、，|；。|。；")


def _malformed_punct_count(text: str) -> int:
    return len(_MALFORMED_PUNCT.findall(text))


def _apply_table_rules(
    text: str,
    table: list[tuple[re.Pattern, str]],
    label: str,
    fixes: list[str],
) -> str:
    """逐条应用表驱动替换；引入乱标点的条目回滚（不改变文本）。"""
    for pat, rep in table:
        matches = pat.findall(text)
        if not matches:
            continue
        candidate = pat.sub(rep, text)
        if _malformed_punct_count(candidate) > _malformed_punct_count(text):
            fixes.append(f"回滚（替换会引入乱标点）[{label} {pat.pattern}]")
            continue
        text = candidate
        fixes.append(f"{label} [{pat.pattern}] -> '{rep}' ({len(matches)}处)")
    return text


def deterministic_polish(
    text: str,
    evidence_pack: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    """Perform deterministic rule-based polish to eliminate AI residue and inject human beats."""
    fixes: list[str] = []
    lines = text.splitlines()

    # 1. Strip conversational endings from tail paragraphs (preserving dialogue quotes)
    new_lines = []
    for line in lines:
        cleaned_line = line
        # If line is pure dialogue quote, do not strip tail conversational endings
        if not re.match(r"^\s*[“\"「\'].*[”\"」\']\s*$", cleaned_line):
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
                lines[first_para_idx] = f"{declared_hook}。{stripped_para}" if not declared_hook.endswith(("。", "！", "？", "…")) else f"{declared_hook}{stripped_para}"
                fixes.append("替换首段宏观背景套话为极端动作破题钩子")
            elif declared_hook not in first_para and not any(t in first_para for t in re.findall(r"[\u4e00-\u9fff]{2,4}", declared_hook)):
                lines[first_para_idx] = f"{declared_hook}\n\n{first_para}"
                fixes.append("在首段前置注入动作破题钩子")

    # Mask protected spans before body-level regex replacements
    raw_body = "\n".join(lines)
    masked_body, protected_spans = _mask_protected_spans(raw_body)
    polished_text = masked_body

    # 3. Apply cliché and buzzword replacements in body（每条替换自带乱标点护栏）
    polished_text = _apply_table_rules(polished_text, CLICHE_REPLACEMENTS, "清理AI套话", fixes)
    polished_text = _apply_table_rules(polished_text, BUZZWORD_REPLACEMENTS, "平替公关黑话", fixes)
    polished_text = _apply_table_rules(polished_text, FORMAL_REPLACEMENTS, "公文书面词口语化", fixes)

    # 4. 打破对仗排比（不是...而是...）——2026-10-16 停用。
    # E1 实测：该规则把主语/副词与谓语焊错（「而他却这并非走向沉默，核心在于走向了荒漠。」、
    # 「从来这并非没钱买包，核心在于连命都买不起。」），并在 `[^，。；]+` 截断处吞掉逗号，
    # 在 12/15 稿里制造 `。。`、`。，` 等乱标点；且「这并非……核心在于……」本身是更强的
    # 模板腔，反 AI 分收益 ≤2.7。语法正确优先于对仗形态 —— 量尺若仍计「不是…而是…」，
    # 属于尺子待校准（E1 建议②），不用语病来换分。
    if re.search(r"不是[^，。；]+[，,]而是", polished_text):
        fixes.append("跳过对仗改写（会破坏语法/制造模板腔，待量尺校准）")

    # 5. Eliminate in-body signpost colons (e.g. '核心是：' -> cut signpost,正面直陈)
    # 2026-10-16 收紧：只切除本身位于句界/段首的空转提示词。原实现无位置约束，把
    # 「你只需要回答一个问题：当现实生活把一笔账拍在你面前」里的「问题：」也删掉，
    # 留下「回答一个当现实生活把…」这种残句（E1 15 稿中实测出现）。提示词跟在名词
    # 短语之后时是句子成分，必须保留。
    signpost_colon_pat = re.compile(
        r"(^|[。！？；\n])(?:一句话(?:总结|说|概括)|简单说|说白了|总结|小结|结论|原因(?:如下|在于)?|问题(?:是|在于)?|本质(?:是|上)?|具体(?:来说|如下)?)[：:]",
        re.MULTILINE,
    )
    sc_matches = signpost_colon_pat.findall(polished_text)
    if sc_matches:
        polished_text = signpost_colon_pat.sub(r"\1", polished_text)
        fixes.append(f"清理正文空转提示性冒号 ({len(sc_matches)}处)")

    # 6. Restore de-verbalized noun phrases (完成了对X的优化 -> 优化了X)
    deverbal_matches = re.findall(r"完成(了)?对([^，。\n]{1,15})的(优化|改造|调整|升级)", polished_text)
    if deverbal_matches:
        polished_text = re.sub(
            r"完成(了)?对([^，。\n]{1,15})的(优化|改造|调整|升级)",
            r"\3\1\2",
            polished_text,
        )
        fixes.append(f"恢复动词活力 (完成了对...的优化 -> 优化了...) ({len(deverbal_matches)}处)")

    # 7. Fix paragraph-opening zero-anaphor comments (non-first body paragraphs)
    paras = polished_text.split("\n\n")
    fixed_paras = []
    zero_anaphor_pat = re.compile(
        r"^([ \t]*)(听起来|看起来|看上去|听上去|值得注意|不难看出|更重要的是|关键在于|问题在于)([^，。\n]{0,20}[，。])"
    )
    for p_idx, para in enumerate(paras):
        st = para.strip()
        if p_idx > 0 and st and not st.startswith(("#", "|", "```", ">", "-", "*", "1.")):
            m = zero_anaphor_pat.match(para)
            if m and not re.match(r"^[ \t]*(这|那|其|此|该|它)", para):
                indent = m.group(1)
                term = m.group(2)
                rest = para[m.end(2):]
                if term in ("听起来", "看起来", "看上去", "听上去"):
                    fixed_paras.append(f"{indent}这{term}{rest}")
                else:
                    fixed_paras.append(f"{indent}这一点{term}{rest}")
                fixes.append(f"补齐非首段零回指评论主语: '{term}' -> '这{term}'")
                continue
        fixed_paras.append(para)
    polished_text = "\n\n".join(fixed_paras)

    # Restore protected dialogue and quote spans
    polished_text = _unmask_protected_spans(polished_text, protected_spans)

    return polished_text, fixes


def check_local_gates(
    text: str,
    evidence_pack: dict[str, Any] | None = None,
    article_id: str = "art-001",
    include_lieflat_checks: bool = True,
) -> dict[str, Any]:
    """Run dual local gates: anti_ai_gate (< 45.0) and prewrite evidence checks.

    `include_lieflat_checks` 额外跑 lieflat 第 3/10/11 条的 advisory 检查
    （`article_group.lieflat_checks`）。这些结论**不参与 passed 判定**：
    lieflat 自己要求这三条最终由人读裁决（SKILL.md:185/:426/:449）。
    """
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

    lieflat_report = run_lieflat_checks(text) if include_lieflat_checks else None

    return {
        "passed": all_passed,
        "anti_ai_passed": ai_passed,
        "anti_ai_score": ai_report.get("total_score", 0.0),
        "hit_phrases": ai_report.get("hit_phrases", []),
        "hit_vocab": ai_report.get("hit_vocab", []),
        "evidence_passed": len(evidence_errors) == 0,
        "evidence_errors": evidence_errors,
        "full_ai_report": ai_report,
        # advisory only —— 不计入 passed，供人工复核与审计留痕
        "lieflat_advisories": lieflat_report,
    }


_ZHUQUE_CONFIDENCE_RE = re.compile(r"AI\s*生成综合置信度[\*`\s]*[：:]\s*`?([\d.]+)\s*%")
_ZHUQUE_HIGH_RISK_RE = re.compile(r"🔴\s*高危疑似\s*AI.*?\|\s*(\d+)\s*段")
_ZHUQUE_MEDIUM_RISK_RE = re.compile(r"🟡\s*中度可疑.*?\|\s*(\d+)\s*段")
_ZHUQUE_HUMAN_RE = re.compile(r"🟢\s*人工自然.*?\|\s*(\d+)\s*段")
_ZHUQUE_QUOTA_RE = re.compile(r"今日剩余检测额度[\*\s]*[：:]\s*(\d+)")
_ZHUQUE_SECTION_RE = re.compile(r"^##\s*[23]\.\s*(🔴|🟡)")
_ZHUQUE_QUOTE_RE = re.compile(r"^>\s*(.+)$")


def parse_zhuque_report(report_text: str) -> dict[str, Any] | None:
    """把朱雀 Markdown 报告解析成流水线内部结果 dict；读不到关键行时返回 ``None``。

    ``None`` 的语义是**「没取得读数」**，绝不能被当成「被判 AI」。2026-10-15 的事故
    正是只解析 stdout：页面/额度异常时 stdout 里根本没有报告，正则落到默认值
    （置信度 0.10、各计数 0），最后被当成实读数报出 NEEDS_CHANGES（假失败）。
    报告里的置信度行形如 ``- **AI 生成综合置信度**：`34.36%` (极低 …)``，注意
    ``置信度`` 与 ``：`` 之间有 ``**``，旧正则 ``置信度[：:]`` 因此在真实报告上永不命中。
    """
    if not report_text:
        return None
    conf_match = _ZHUQUE_CONFIDENCE_RE.search(report_text)
    if not conf_match:
        return None
    conf = float(conf_match.group(1)) / 100.0

    def _count(rx: re.Pattern[str]) -> int:
        m = rx.search(report_text)
        return int(m.group(1)) if m else 0

    danger_cnt = _count(_ZHUQUE_HIGH_RISK_RE)
    suspect_cnt = _count(_ZHUQUE_MEDIUM_RISK_RE)
    human_cnt = _count(_ZHUQUE_HUMAN_RE)
    tot = max(1, danger_cnt + suspect_cnt + human_cnt)

    # 片段清单按章节归属：🔴 高危 → label 1，🟡 中度可疑 → label 2
    splits: list[dict[str, Any]] = []
    current_label = ""
    for line in report_text.splitlines():
        if _ZHUQUE_SECTION_RE.match(line):
            current_label = "1" if "🔴" in line else "2"
            continue
        quote_match = _ZHUQUE_QUOTE_RE.match(line) if current_label else None
        if quote_match:
            seg_text = quote_match.group(1).strip()
            if seg_text:
                splits.append({"label": current_label, "text": seg_text})

    quota_match = _ZHUQUE_QUOTA_RE.search(report_text)
    return {
        "softmax_confidence": conf,
        "labels_ratio": {
            "0": human_cnt / tot,
            "1": danger_cnt / tot,
            "2": suspect_cnt / tot,
        },
        "splits": splits,
        "quota_remaining": int(quota_match.group(1)) if quota_match else None,
    }


# 朱雀 Web 兜底的等待预算（2026-10-15 用户授权放宽）：
# CLI 内部页面轮询上限，以及外层 subprocess 超时；外层必须更大，让 CLI 先自己失败并带回诊断。
ZHUQUE_WEB_WAIT_TIMEOUT = 240.0
ZHUQUE_WEB_SUBPROCESS_TIMEOUT = 300


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
        import tempfile
        tmp_dir = tempfile.mkdtemp(prefix="zhuque_input_")
        tmp_path = os.path.join(tmp_dir, "input.md")
        report_path = os.path.join(tmp_dir, "report.md")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(text)

            # 报告走 --output 落文件后解析，stdout 只作备份。
            # --wait-timeout 是 CLI 侧的页面轮询预算（2026-10-15 由写死的 90s 放宽到 240s：当天 3 次
            # 兜底全部撞在 90s 上且额度未减，说明是结果没渲染而不是被判 AI）。
            cmd = [
                python_env, web_cli, "detect", "--file", tmp_path, "--output", report_path,
                "--wait-timeout", str(ZHUQUE_WEB_WAIT_TIMEOUT),
            ]
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=ZHUQUE_WEB_SUBPROCESS_TIMEOUT
            )
            retried_without_flag = False
            if proc.returncode == 2 and "unrecognized arguments" in (proc.stderr or ""):
                # 软耦合：旧版 skill CLI 不认 --wait-timeout → 退回不带该参数的调用。
                # 宁可为「读不到读数」（unavailable），也绝不伪造读数。
                retried_without_flag = True
                cmd = [python_env, web_cli, "detect", "--file", tmp_path, "--output", report_path]
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=ZHUQUE_WEB_SUBPROCESS_TIMEOUT
                )

            report_text = ""
            if os.path.exists(report_path):
                with open(report_path, encoding="utf-8") as f:
                    report_text = f.read()
            if not report_text.strip():
                report_text = proc.stdout or ""

            parsed = parse_zhuque_report(report_text)
            if parsed is None:
                return {
                    "error": "web_cli_report_unreadable",
                    "unavailable": True,
                    "diagnostics": {
                        "returncode": proc.returncode,
                        "wait_timeout": ZHUQUE_WEB_WAIT_TIMEOUT,
                        "retried_without_wait_timeout": retried_without_flag,
                        "stdout_tail": (proc.stdout or "")[-400:],
                        "stderr_tail": (proc.stderr or "")[-400:],
                    },
                }
            parsed["source"] = "web_cli"
            return parsed
        except Exception as e:
            return {"error": f"web_cli_fallback_failed: {e}", "unavailable": True}
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return {"error": "all_zhuque_methods_failed", "unavailable": True}


def evaluate_zhuque_result(result: dict[str, Any]) -> dict[str, Any]:
    """Evaluate whether Zhuque result satisfies All-Green criteria.

    ``available=False`` 表示**没取得读数**（API 与 Web 兜底都失败，或报告读不出来）。
    这类结果 ``is_all_green=None``，调用方不得据此判失败——「读不到结果」≠「被判 AI」。
    """
    if "error" in result or result.get("unavailable"):
        return {
            "available": False,
            "is_all_green": None,
            "error": result.get("error") or "zhuque_unavailable",
            "diagnostics": result.get("diagnostics") or {},
            "softmax_confidence": None,
            "human_ratio": None,
            "ai_ratio": None,
            "suspect_ratio": None,
            "danger_sentences": [],
        }

    # 形状校验（L2 B2-L2-02）：无法解读的返回体不得被读成「判决」。
    # 旧写法 `result.get("softmax_confidence", 1.0)` + `labels_ratio {}` 会让
    # 「返回体形状不符」静默变成 available=True / is_all_green=False（conf 1.0），
    # 与本函数确立的「读不到 ≠ 判决」语义相反。缺键即按不可用处理。
    def _is_unit(value: Any) -> bool:
        """0..1 之间的有限实数（排除 bool / NaN / inf / 负值 / 超 1）。"""
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and 0.0 <= float(value) <= 1.0
        )

    conf = result.get("softmax_confidence")
    labels = result.get("labels_ratio")
    labels_ok = isinstance(labels, dict) and all(_is_unit(labels.get(k)) for k in ("0", "1", "2"))
    if not _is_unit(conf) or not labels_ok:
        # 数值域同样校验（L2 增量复核 L2D-04）：旧写法下 conf=NaN/inf 会得到
        # available=True（判不绿，尚可），而 conf=-1 会得到 is_all_green=True ——
        # **假全绿（fail-open）**。json.loads 默认接受 NaN/Infinity，故必须显式拦。
        unparsed_keys = sorted(
            {
                str(k)
                for src in (result, result.get("data"))
                if isinstance(src, dict)
                for k in src
                if re.search(r"conf|ratio|label|score|prob", str(k), re.I)
            }
        )[:20]
        return {
            "available": False,
            "is_all_green": None,
            "error": "zhuque_shape_unrecognized",
            "diagnostics": {
                "received_keys": sorted(str(k) for k in result)[:20],
                "expected": ["softmax_confidence: number in [0,1]", "labels_ratio: {0,1,2: number in [0,1]}"],
                "confidence_like_keys": unparsed_keys,
                "confidence_like_keys_present": bool(unparsed_keys),
            },
            "softmax_confidence": None,
            "human_ratio": None,
            "ai_ratio": None,
            "suspect_ratio": None,
            "danger_sentences": [],
        }

    human_ratio = labels.get("0", 0.0)
    ai_ratio = labels.get("1", 0.0)
    suspect_ratio = labels.get("2", 0.0)

    # Extract sentences flagged as danger (1) or suspect (2) if split data exists
    danger_sentences: list[dict[str, Any]] = []
    data = result.get("data")
    splits = result.get("splits") or (data.get("splits") if isinstance(data, dict) else []) or []
    if not isinstance(splits, list):
        # L2 增量复核 L2D-03：splits 形状不可预期时曾有
        # `AttributeError: 'str' object has no attribute 'get'` 穿透本函数。
        splits = []
    for item in splits:
        if not isinstance(item, dict):
            continue
        lbl = str(item.get("label", ""))
        txt = item.get("text", "")
        if lbl in ("1", "2") and txt:
            danger_sentences.append({
                "label": lbl,
                "label_name": "AI" if lbl == "1" else "疑似AI",
                "text": txt,
            })

    conditions = {
        "ai_ratio_is_zero": ai_ratio == 0.0,
        "confidence_below_0_50": conf < 0.50,
        "human_ratio_at_least_0_70": human_ratio >= 0.70,
    }
    is_all_green = all(conditions.values())

    return {
        "available": True,
        "is_all_green": is_all_green,
        "softmax_confidence": conf,
        "human_ratio": human_ratio,
        "ai_ratio": ai_ratio,
        "suspect_ratio": suspect_ratio,
        "danger_sentences": danger_sentences,
        "conditions": conditions,
    }


_STRUCTURAL_TARGET_RE = re.compile(r"^(?:#{1,6}\s|>|\||```|[-*+]\s|\d+[.、)])")


def _is_body_target(target: str) -> bool:
    """修复目标必须是**正文句**，不能是标题 / 引用 / 表格 / 列表等结构行。

    L2 B2-L2-01：朱雀报告每个片段的 `>` 引用只覆盖该片段**首行**，而当片段以
    文章 H1 开头时，被当成「高危句」的其实是标题；旧代码会因标题里的第一个逗号
    把它改成句号（`…挥绿棒，上海周家…` → `…挥绿棒。上海周家…`），audit 却记成
    「靶向拆解高危句」。这里在改写前把结构行排除。
    """
    s = target.lstrip()
    return bool(s) and not _STRUCTURAL_TARGET_RE.match(s)


def perform_surgical_repair(
    text: str,
    danger_sentences: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    """Surgically repair sentences identified as AI/suspect by Zhuque."""
    repaired_text = text
    repair_logs: list[str] = []
    # 标题行不变量（L2 B2-L2-01 兜底）：文档首行为 markdown 标题（`#…`）时，
    # 修复前后它必须逐字不变。首行不是标题的稿件（如单段测试文本）不启用该保护，
    # 否则正文第一段会被误当标题而拒绝修复。
    _first_line = next((ln for ln in text.split("\n") if ln.strip()), "")
    _guard_title = _first_line.lstrip().startswith("#")

    for d in danger_sentences:
        target_s = d["text"].strip()
        if not target_s or len(target_s) < 6:
            continue
        if not _is_body_target(target_s):
            repair_logs.append(f"跳过非正文目标（标题/结构行）: '{target_s[:15]}...'")
            continue

        # If sentence exists in text, perform targeted breaking and colloquial tone injection
        if target_s in repaired_text:
            replacement = target_s
            # Break compound punctuation cleanly without AI tone clichés like "说白了"
            if "，" in replacement:
                parts = replacement.split("，", 1)
                replacement = f"{parts[0]}。{parts[1]}"
            elif "、" in replacement:
                replacement = replacement.replace("、", "还有")

            # Remove generic linking markers
            for w in ("因此", "从而", "进而", "展现出", "体现了"):
                if w in replacement:
                    replacement = replacement.replace(w, "")

            if replacement != target_s:
                candidate = repaired_text.replace(target_s, replacement, 1)
                cand_first = next((ln for ln in candidate.split("\n") if ln.strip()), "")
                if _guard_title and cand_first != _first_line:
                    repair_logs.append(f"跳过会改动标题行的目标: '{target_s[:15]}...'")
                    continue
                repaired_text = candidate
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

    # Step 2b: lieflat 3/10/11 advisory 检查（只留痕，不影响 passed）
    lieflat_report = local_eval.get("lieflat_advisories")
    if lieflat_report is not None:
        audit_trail.append({
            "step": "lieflat_advisories",
            "available": lieflat_report.get("available", False),
            "advisory_only": True,
            "summary": lieflat_report.get("summary", {}),
            "reason": lieflat_report.get("reason"),
        })

    current_text = polished_text
    zhuque_report: dict[str, Any] | None = None

    # Step 3: Zhuque Check & Self-Healing (if requested and local gates pass)
    # 2026-10-16：本地门禁未过时不再静默跳过朱雀，显式留痕。此前 `--run-zhuque`
    # 在门禁 fail 时连一次检测都不会发，audit_trail 里也查不到，容易被读成
    # 「朱雀已全绿」或「自愈已跑过」（详见 E1-REPORT.md 的 schema 分叉一节）。
    zhuque_skipped_reason: str | None = None
    if run_zhuque and not local_eval["passed"]:
        zhuque_skipped_reason = "local_gates_failed"
        audit_trail.append({
            "step": "zhuque_skipped",
            "reason": zhuque_skipped_reason,
            "anti_ai_score": local_eval["anti_ai_score"],
            "evidence_errors": local_eval["evidence_errors"],
            "note": "本地门禁未过，朱雀未取得读数（既未判绿也未判 AI）",
        })
    if run_zhuque and local_eval["passed"]:
        for round_idx in range(1, max_zhuque_rounds + 1):
            raw_res = call_zhuque_check(current_text, split=True)
            zhuque_eval = evaluate_zhuque_result(raw_res)
            zhuque_report = zhuque_eval

            # 读不到读数：留痕后跳出，不进入自愈，也不据此判失败
            if not zhuque_eval.get("available", True):
                audit_trail.append({
                    "step": f"zhuque_round_{round_idx}",
                    "available": False,
                    "reason": zhuque_eval.get("error"),
                    "diagnostics": zhuque_eval.get("diagnostics") or {},
                })
                break

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

    # 交付判定分三态（2026-10-15 用户授权）：
    #   NEEDS_CHANGES   本地门禁未过，或朱雀给出了「不绿」的判决
    #   PASS_LOCAL_ONLY 本地门禁已过，但朱雀未取得读数（不可用、未参与判定）——必须显式区别于全绿
    #   PASS            本次请求的全部门禁都通过
    zhuque_available = bool(zhuque_report is not None and zhuque_report.get("available", True))
    zhuque_passed = (
        zhuque_report.get("is_all_green") if (zhuque_report and zhuque_available) else None
    )

    is_final_passed = local_eval["passed"] and (
        not run_zhuque or zhuque_passed is True or not zhuque_available
    )

    if not is_final_passed:
        status = "NEEDS_CHANGES"
        status_reason = (
            "local_gates_failed" if not local_eval["passed"] else "zhuque_judged_not_green"
        )
    elif run_zhuque and not zhuque_available:
        status = "PASS_LOCAL_ONLY"
        status_reason = "zhuque_unavailable"
    else:
        status = "PASS"
        status_reason = "all_requested_gates_passed"

    return {
        "status": status,
        "status_reason": status_reason,
        "file_updated": str(dest_path),
        "local_gates_passed": local_eval["passed"],
        "zhuque_passed": zhuque_passed,
        "zhuque_available": zhuque_available,
        "zhuque_skipped_reason": zhuque_skipped_reason,
        "zhuque_conditions": (zhuque_report or {}).get("conditions"),
        "audit_trail": audit_trail,
        "zhuque_report": zhuque_report,
        "lieflat_advisories": lieflat_report,
    }


def exit_code_for_status(status: str) -> int:
    """PASS 与 PASS_LOCAL_ONLY 都表示「可以交付」（后者缺朱雀读数）；其余一律非零。"""
    return 0 if status in ("PASS", "PASS_LOCAL_ONLY") else 1


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
        if res["status"] == "PASS_LOCAL_ONLY":
            print("人工特征注入与脱敏自愈结果: [PASS_LOCAL_ONLY]")
            print("  ⚠ 本地门禁通过；朱雀未取得读数（不可用，未参与判定）——")
            print("    这不等于「朱雀全绿」，交付前如需该读数请另行人工复核。")
        else:
            print(f"人工特征注入与脱敏自愈结果: [{res['status']}]")
        print(f"- 目标文件: {res['file_updated']}")
        print(f"- 本地双门禁: {'PASS' if res['local_gates_passed'] else 'FAIL'}")
        if res.get("zhuque_available") is False and res.get("zhuque_report"):
            print("- 朱雀全绿门禁: 未取得读数（不可用，未参与判定）")
        elif res['zhuque_passed'] is not None:
            print(f"- 朱雀全绿门禁: {'PASS' if res['zhuque_passed'] else 'FAIL'}")
            conds = res.get("zhuque_conditions") or {}
            if conds:
                failed = [k for k, ok in conds.items() if not ok]
                if failed:
                    print(f"    未满足条件: {', '.join(failed)}")
        print("-" * 60)
        print("执行轨迹 (Audit Trail):")
        for a in res["audit_trail"]:
            step = a.get("step")
            if "fixes_applied" in a:
                print(f"  • [{step}] 应用修复 {a['fixes_applied']} 项")
            elif "anti_ai_score" in a:
                print(f"  • [{step}] 本地评分: {a['anti_ai_score']:.1f} (通过: {a['passed']})")
            elif step == "lieflat_advisories":
                if a.get("available"):
                    s = a.get("summary") or {}
                    bands = s.get("structure_band") or {}
                    print(
                        f"  • [{step}] advisory（不影响门禁）: 结构命中 {s.get('structure_findings', 0)} 处，"
                        f"翻译腔可改 {s.get('translationese_actionable_hits', 0)} 处，"
                        f"禁止据以改写标记 {s.get('translationese_reference_only_hits', 0)} 处"
                    )
                    if bands:
                        print("      结构区间: " + ", ".join(f"{k}={v}" for k, v in bands.items()))
                else:
                    print(f"  • [{step}] 不可用: {a.get('reason')}")
            elif a.get("available") is False:
                print(f"  • [{step}] 朱雀未取得读数（未参与判定）: {a.get('reason')}")
            elif "confidence" in a:
                print(f"  • [{step}] 朱雀置信度: {a['confidence']:.3f}, 人工占比: {a['human_ratio']*100:.1f}%, AI占比: {a['ai_ratio']*100:.1f}%")
        print("=" * 60)

    return exit_code_for_status(res["status"])


if __name__ == "__main__":
    sys.exit(main())
