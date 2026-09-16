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
            if quote not in ledger_blob:
                unmatched.append({"quote": quote, "issue": "引号内容未在账本逐字命中"})
    return unmatched


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--aid", required=True)
    args = parser.parse_args()

    run_root = Path(args.run_root)
    delivery, ledger = load_run_inputs(run_root, args.aid)
    quotes = check_quotes(delivery, ledger)

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
        "llm_gaps": llm_gaps,
        "llm_status": llm_status,
        "note": "预检只报缺口不阻断；判断句/作者观点不计硬事实；L2 复核仍为最终口径。",
        "publication_authorization": "not_authorized",
    }
    out = run_root / "review" / args.aid / "ledger-coverage-precheck.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"{args.aid}: 账本 {len(ledger)} 条 | 段落 {len(paragraphs)} | 引号未命中 {len(quotes)} | LLM 缺口 {len(llm_gaps)}（{llm_status}）")
    for q in quotes:
        print(f"  [quote] {q['quote'][:50]}")
    for g in llm_gaps:
        print(f"  [gap] p{g['location']} {g['quote'][:40]} → {g['suggestion'][:30]}")
    print(f"产物: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
