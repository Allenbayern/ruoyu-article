#!/usr/bin/env python3
"""读者面↔账本 LLM 预检器（进 L2 前的自检，P0 优化 2026-09-16）。

把 L2 对抗复核的核对口径前置成生成侧自检，两段检查：

1. 确定性引号检查：读者面所有 “…” 引号内容必须能在账本条目（material-packs
   obtained_facts_by_source + content-fidelity hard_information）中逐字找到；
   找不到的列为 quote_unmatched（多为台词/弹幕/来源引语转录缺口）；
2. LLM 缺口检查：逐段找"读者面硬事实表述"（人名/作品名/数字/日期/剧情/角色
   设定/引号内容）中账本无法支撑的条目，输出 {location, quote, issue,
   suggestion(补账本条目 or 删改)}。判断句/作者观点不算硬事实，不报。

产物：review/<aid>/ledger-coverage-precheck.json；本脚本只报缺口，不阻断
（阻断仍由 L2 与门禁负责）。LLM 不可用时 quote 检查照常输出，llm_gaps
标记 skipped 并注明原因。

凭据：~/.config/ruoyu-llm/env（600 权限），经 scripts/llm_client 注入。

用法：
    python3 scripts/ledger_coverage_precheck.py --run-root runs/2026-09-16/daily-007 --aid art-001
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.llm_client import LlmUnavailable, chat as llm_chat, load_env, parse_json_array  # noqa: E402

QUOTE_RES = (
    re.compile(r"“([^”\n]{2,60})”"),
    re.compile(r'"([^"\n]{2,60})"'),
)

SYSTEM_PROMPT = (
    "你是严格的对抗复核员，口径：读者面（正文）里的每一条硬事实表述，"
    "都必须能在账本条目里找到支撑；判断句、比喻、作者观点不属于硬事实。\n"
    "任务：阅读读者面段落清单与账本条目清单，列出所有『读者面有、账本无』"
    "的硬事实缺口。每条输出：\n"
    "{\"location\":\"段落号\",\"quote\":\"读者面表述片段(≤30字)\","
    "\"issue\":\"缺什么支撑(≤20字)\",\"suggestion\":\"补账本条目 或 删改(≤20字)\"}\n"
    "只输出 JSON 数组；没有任何缺口就输出 []。禁止输出数组以外的任何文字。"
    "逐段独立判断即可，不要对整篇做全局性长篇推理。"
    "　特别检查两类易漏断言：①时间跨度（十几年/十多年/这些年/8 年之后…）；②受众行为（台词还在被引用/盘到包浆/如数家珍/网友都在…）。这两类在 daily-008 曾整轮漏过，是 L2 判 major 的主因。"
)


def load_run_inputs(run_root: Path, aid: str) -> tuple[str, list[str]]:
    delivery = (run_root / "delivery" / aid / "delivery.md").read_text(encoding="utf-8")
    ledger: list[str] = []
    pack_path = run_root / "material-packs" / f"{aid}.json"
    if pack_path.exists():
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
        by_source = pack.get("obtained_facts_by_source") or {}
        for source_id, facts in by_source.items():
            for fact in facts:
                ledger.append(f"[{source_id}] {fact}")
    fidelity_path = run_root / "review" / aid / "content-fidelity.json"
    if fidelity_path.exists():
        fidelity = json.loads(fidelity_path.read_text(encoding="utf-8"))
        for entry in fidelity.get("hard_information") or []:
            ledger.append(f"[hard:{entry.get('information_id')}] {entry.get('text', '')}")
    return delivery, ledger


def split_paragraphs(delivery: str) -> list[tuple[int, str]]:
    body = delivery.split("\n", 1)[1] if delivery.startswith("#") else delivery
    paragraphs = []
    for i, block in enumerate(body.split("\n\n"), 1):
        text = " ".join(block.split())
        if text and not text.startswith("##"):
            paragraphs.append((i, text))
    return paragraphs


_QUOTE_TRAILING_PUNCT = "。！？，、；："


def _quote_matches(quote: str, ledger_blob: str) -> bool:
    if quote in ledger_blob:
        return True
    # 中文引号常把句末标点包进引号内；账本条目按页面原文可能不含该标点，
    # 剥掉尾部标点再比一次，避免纯标点差异的误报。
    stripped = quote.rstrip(_QUOTE_TRAILING_PUNCT)
    return bool(stripped) and stripped in ledger_blob


def check_quotes(delivery: str, ledger: list[str]) -> list[dict]:
    ledger_blob = "\n".join(ledger)
    unmatched = []
    seen: set[str] = set()
    for quote_re in QUOTE_RES:
        for match in quote_re.finditer(delivery):
            quote = match.group(1)
            if quote in seen:
                continue
            seen.add(quote)
            if not _quote_matches(quote, ledger_blob):
                unmatched.append({"quote": quote, "issue": "引号内容未在账本逐字命中"})
    return unmatched


def assertion_gaps(run_root: Path, aid: str) -> dict:
    """确定性断言缺口（时间跨度/受众行为/数字/引号）+ 账本孤儿条目。

    2026-09-17：daily-008 的 L2 第一轮判的 2 条 major 都属于"读者面有、账本无"
    的断言，而当时预检只有逐字引号比对 + LLM 抽查，两类正好漏过。这里接入
    article_group.assertion_ledger_coverage 的确定性检查，LLM 不可用时照常出结果。
    """
    from article_group.assertion_ledger_coverage import check_coverage

    report = check_coverage(run_root, aid)
    return {
        "assertion_errors": list(report.get("errors") or []),
        "assertion_warnings": list(report.get("warnings") or []),
        "assertion_uncovered": list(report.get("uncovered") or []),
        "orphan_ledger": list(report.get("orphan_ledger") or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--aid", required=True)
    parser.add_argument("--force", action="store_true",
                        help="在已收尾的 run 上强制重跑并覆盖预检产物（默认拒绝）")
    args = parser.parse_args()

    run_root = Path(args.run_root)
    # 2026-09-17：已收尾的 run 是封存证据，默认不得覆盖。
    from article_group.run_state import closed_reason

    closed = closed_reason(run_root)
    if closed and not getattr(args, "force", False):
        print(f"拒绝执行：run 已收尾（{closed}）。加 --force 才会覆盖预检产物。", file=sys.stderr)
        return 2
    delivery, ledger = load_run_inputs(run_root, args.aid)
    quotes = check_quotes(delivery, ledger)
    assertion = assertion_gaps(run_root, args.aid)

    llm_gaps: list[dict] = []
    llm_status = "skipped"
    paragraphs = split_paragraphs(delivery)
    ledger_trimmed = [entry[:100] for entry in ledger]
    try:
        env = load_env()
        # 逐段分组（每 4 段一请求），避免整篇×全账本的一次性对比让模型
        # 把 max_tokens 全烧在推理上（实测 finish_reason=length）。
        for start in range(0, len(paragraphs), 4):
            chunk = paragraphs[start : start + 4]
            user = (
                "读者面段落清单（段落号<TAB>内容）：\n"
                + "\n".join(f"{i}\t{t[:200]}" for i, t in chunk)
                + "\n\n账本条目清单（截断）：\n"
                + "\n".join(ledger_trimmed)
            )
            try:
                raw = llm_chat(env, SYSTEM_PROMPT, user, max_tokens=8000)
            except LlmUnavailable:
                # 空回复/网络断开都重试一次（更强约束）；再失败才算该批跳过
                raw = llm_chat(
                    env, SYSTEM_PROMPT + "\n最终回答必须是 JSON 数组本身。", user, max_tokens=8000
                )
            parsed = parse_json_array(raw)
            if parsed is None:
                llm_status = "parse_failed"
                continue
            llm_status = "ok"
            for g in parsed:
                if isinstance(g, dict) and g.get("quote"):
                    llm_gaps.append(
                        {
                            "location": str(g.get("location", "")),
                            "quote": str(g.get("quote", ""))[:60],
                            "issue": str(g.get("issue", ""))[:40],
                            "suggestion": str(g.get("suggestion", ""))[:40],
                        }
                    )
    except (LlmUnavailable, SystemExit) as exc:
        llm_status = f"skipped: {exc}"

    record = {
        "schema_version": "ledger-coverage-precheck-v1",
        "aid": args.aid,
        "run_root": str(run_root),
        "ledger_entries": len(ledger),
        "paragraphs": len(paragraphs),
        "quote_unmatched": quotes,
        **assertion,
        "llm_gaps": llm_gaps,
        "llm_status": llm_status,
        "note": "预检只报缺口不阻断；判断句/作者观点不计硬事实；L2 复核仍为最终口径。"
                " 断言缺口为确定性检查（时间跨度/受众行为 error，数字/引号 warning）。",
        "publication_authorization": "not_authorized",
    }
    out = run_root / "review" / args.aid / "ledger-coverage-precheck.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"{args.aid}: 账本 {len(ledger)} 条 | 段落 {len(paragraphs)} | 引号未命中 {len(quotes)} | LLM 缺口 {len(llm_gaps)}（{llm_status}）")
    print(f"  确定性断言缺口: error {len(assertion['assertion_errors'])} | warning {len(assertion['assertion_warnings'])} | 孤儿账本条目 {len(assertion['orphan_ledger'])}")
    for item in assertion["assertion_uncovered"]:
        print(f"  [{item['severity']}] p{item['paragraph']} {item['category']}: {item['claim']}")
    for q in quotes:
        print(f"  [quote] {q['quote'][:50]}")
    for g in llm_gaps:
        print(f"  [gap] p{g['location']} {g['quote'][:40]} → {g['suggestion'][:30]}")
    print(f"产物: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
