"""assertion_ledger_coverage: 读者面断言 ↔ 账本的确定性双向覆盖检查。

为什么需要（daily-008 复盘）：
该期账本 46 条事实全部锚定、机器门禁全绿，但 L2 第一轮仍判了 2 条 major——
读者面写了「十几年过去」（时间跨度数字）与「《让子弹飞》的台词还在被引用」
（受众行为），两条在账本里**都没有对应条目**。既有预算检查只有两种手段：
逐字引号比对 + LLM 抽查（4 段一请求），这两类断言正好从中间漏过去。

本模块把这两类（以及数字断言、引号）做成确定性检查，两个方向都查：

- 正向 `assertion_not_in_ledger`：读者面的断言在账本里找不到支撑；
- 反向 `ledger_item_not_in_body`：账本条目在正文里没有任何对应（孤儿条目）。

严重级：时间跨度与受众行为缺口记 error（L2 判 major 的正是这两类），
数字与引号缺口记 warning。产物 `review/<aid>/assertion-coverage.json`；
`--strict` 时存在 error 会以非零码退出，供门禁调用。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

# 复用 claim-source 的锚定口径：读者面断言必须能在账本里"锚得住"。
_THIS = Path(__file__).resolve()
if str(_THIS.parents[1]) not in sys.path:  # pragma: no cover - 源码树内运行
    sys.path.insert(0, str(_THIS.parents[1]))

from article_group.claim_source_check import fact_anchors_in_source  # noqa: E402

SCHEMA_VERSION = "assertion-ledger-coverage-v1"

# 时间跨度断言：008 的「十几年过去」正是这一类。
# 注意字数词要含 几/多/余/数，否则「十几年」「十多年」都匹配不上（实测踩过）。
TIME_SPAN_RE = re.compile(
    r"[0-9一二三四五六七八九十百千几多余数]{1,6}\s*年(?:来|间|之后|以后|后|前|过去|时间)?"
    r"|多年来|这些?年(?:来)?|一直以来|多年以前"
)
# 受众行为断言：008 的「台词还在被引用」正是这一类。
AUDIENCE_ACTION_RE = re.compile(
    r"(?:还在|仍在|依旧在|仍被|被反复|被不断|不断被|纷纷|都在|人人|一致)"
    r"[^。！？；\n]{0,10}?"
    r"(?:引用|提起|提及|讨论|转发|传播|模仿|致敬|重看|重播|刷屏|传颂)"
    r"|盘到包浆|如数家珍|口口相传|家喻户晓|刷屏|出圈"
)
NUMBER_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|％|亿|万亿|千万|百万|万|分钟|小时|个|条|部|场|人|次|岁|元|倍|帧)"
)
QUOTE_RES = (
    re.compile(r"“([^”\n]{2,60})”"),
    re.compile(r'"([^"\n]{2,60})"'),
)

CATEGORY_SEVERITY = {
    "time_span": "error",
    "audience_action": "error",
    "number_fact": "warning",
    "quote": "warning",
}
# 只有"给出具体跨度"的时间断言才算硬事实（十几/十多/数十年/2010 年…）。
# 泛化表述（这些年/多年来/一直以来）降为 warning：实测 008 里
# 「几乎就是这些年观众对姜文的全部怨言」属作者判断，判 error 是误报。
_SPECIFIC_SPAN_RE = re.compile(r"[0-9]|十几|十多|数十|近[0-9一二三四五六七八九十]|将近")
_TRAILING_PUNCT = "。！？，、；：）)】」』"


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def load_delivery(run_dir: Path, aid: str) -> str:
    return (run_dir / "delivery" / aid / "delivery.md").read_text(encoding="utf-8")


def load_ledger(run_dir: Path, aid: str) -> list[dict[str, str]]:
    """账本条目：材料包 obtained_facts_by_source + 交付账本 hard_information。"""
    ledger: list[dict[str, str]] = []
    pack = _load_json(run_dir / "material-packs" / f"{aid}.json")
    by_source = pack.get("obtained_facts_by_source") or {}
    if isinstance(by_source, Mapping):
        for source_id, facts in by_source.items():
            for fact in facts if isinstance(facts, list) else []:
                if isinstance(fact, str) and fact.strip():
                    ledger.append({"ref": f"pack:{source_id}", "text": fact.strip()})
    fidelity = _load_json(run_dir / "review" / aid / "content-fidelity.json")
    for entry in fidelity.get("hard_information") or []:
        if isinstance(entry, Mapping) and isinstance(entry.get("text"), str):
            ledger.append({
                "ref": f"hard:{entry.get('information_id', '?')}",
                "text": entry["text"].strip(),
            })
    return ledger


def split_paragraphs(delivery: str) -> list[tuple[int, str]]:
    body = delivery.split("\n", 1)[1] if delivery.startswith("#") else delivery
    paragraphs: list[tuple[int, str]] = []
    for index, block in enumerate(body.split("\n\n"), 1):
        text = " ".join(block.split())
        if text and not text.startswith("##"):
            paragraphs.append((index, text))
    return paragraphs


def extract_assertions(paragraphs: Sequence[tuple[int, str]]) -> list[dict[str, str]]:
    """抽出需要账本支撑的读者面断言（带段落定位与类别）。"""
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    patterns: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("time_span", TIME_SPAN_RE),
        ("audience_action", AUDIENCE_ACTION_RE),
        ("number_fact", NUMBER_RE),
    )
    for index, text in paragraphs:
        for category, pattern in patterns:
            for match in pattern.finditer(text):
                claim = match.group(0).strip().strip(_TRAILING_PUNCT)
                key = (category, claim)
                if not claim or key in seen:
                    continue
                seen.add(key)
                found.append({"category": category, "claim": claim, "paragraph": str(index),
                              "sentence": text[:120]})
        for quote_re in QUOTE_RES:
            for match in quote_re.finditer(text):
                claim = match.group(1).strip().strip(_TRAILING_PUNCT)
                key = ("quote", claim)
                if not claim or key in seen:
                    continue
                seen.add(key)
                found.append({"category": "quote", "claim": claim, "paragraph": str(index),
                              "sentence": text[:120]})
    return found


def _covered(claim: str, ledger_blob: str) -> bool:
    anchored, _ = fact_anchors_in_source(claim, ledger_blob)
    if anchored:
        return True
    stripped = claim.rstrip(_TRAILING_PUNCT)
    return bool(stripped) and stripped in ledger_blob


def check_coverage(run_dir: str | Path, aid: str) -> dict[str, Any]:
    """双向覆盖检查：读者面→账本 缺口 + 账本→读者面 孤儿条目。"""
    root = Path(run_dir)
    delivery_path = root / "delivery" / aid / "delivery.md"
    if not delivery_path.is_file():
        return {
            "schema_version": SCHEMA_VERSION,
            "aid": aid,
            "status": "no_delivery",
            "errors": [], "warnings": [],
            "uncovered": [], "orphan_ledger": [],
            "publication_authorization": "not_authorized",
        }
    delivery = load_delivery(root, aid)
    ledger = load_ledger(root, aid)
    ledger_blob = "\n".join(entry["text"] for entry in ledger)
    paragraphs = split_paragraphs(delivery)
    assertions = extract_assertions(paragraphs)

    uncovered: list[dict[str, Any]] = []
    for item in assertions:
        if _covered(item["claim"], ledger_blob):
            continue
        severity = CATEGORY_SEVERITY.get(item["category"], "warning")
        if (item["category"] == "time_span" and severity == "error"
                and not _SPECIFIC_SPAN_RE.search(item["claim"])):
            severity = "warning"
        uncovered.append({**item, "severity": severity})

    orphan: list[dict[str, str]] = []
    body_blob = "\n".join(text for _, text in paragraphs)
    for entry in ledger:
        if not _covered(entry["text"][:40], body_blob):
            orphan.append(entry)

    errors = [f"assertion_not_in_ledger:{item['category']}:{item['claim'][:32]}"
              for item in uncovered if item["severity"] == "error"]
    warnings = [f"assertion_not_in_ledger:{item['category']}:{item['claim'][:32]}"
                for item in uncovered if item["severity"] != "error"]
    warnings.extend(f"ledger_item_not_in_body:{entry['ref']}" for entry in orphan)

    return {
        "schema_version": SCHEMA_VERSION,
        "aid": aid,
        "status": "ok",
        "ledger_entries": len(ledger),
        "paragraphs": len(paragraphs),
        "assertions": len(assertions),
        "uncovered": uncovered,
        "orphan_ledger": orphan,
        "errors": errors,
        "warnings": warnings,
        "note": "确定性预检：时间跨度/受众行为缺口记 error（L2 判 major 的两类），"
                "数字/引号记 warning；判断句与作者观点不属于断言。",
        "publication_authorization": "not_authorized",
    }


def write_report(path: Path, report: Mapping[str, Any], *, run_dir: Path) -> None:
    """报告进 run 时走留底通道（留底+记账+封存守门）；run 外保持普通写入。

    2026-09-18：本模块此前在写手覆盖 lint 的 PENDING 名单里（"写 run 但绕过通道"）。
    """

    from article_group.run_seal import is_run_root

    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if is_run_root(run_dir):
        from article_group.evidence_write import write_evidence

        write_evidence(
            path,
            payload,
            run_dir=run_dir,
            reason=f"assertion_ledger_coverage:{report.get('aid', '')}",
        )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m article_group.assertion_ledger_coverage",
        description="读者面断言 ↔ 账本 双向覆盖检查（确定性，进 L2 前自检）",
    )
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--aid", required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="存在 error 时以非零码退出")
    parser.add_argument("--write", action="store_true",
                        help="写 review/<aid>/assertion-coverage.json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = check_coverage(args.run_root, args.aid)
    if args.write and report["status"] == "ok":
        write_report(
            args.run_root / "review" / args.aid / "assertion-coverage.json",
            report,
            run_dir=args.run_root,
        )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"{args.aid}: 账本 {report.get('ledger_entries', 0)} 条 | 段落 {report.get('paragraphs', 0)} | "
              f"断言 {report.get('assertions', 0)} | 未覆盖 {len(report['uncovered'])} | "
              f"孤儿条目 {len(report['orphan_ledger'])}")
        for item in report["uncovered"]:
            print(f"  [{item['severity']}] p{item['paragraph']} {item['category']}: {item['claim']}")
        for entry in report["orphan_ledger"]:
            print(f"  [orphan] {entry['ref']}: {entry['text'][:40]}")
    if args.strict and report["errors"]:
        return 1
    return 0


__all__ = [
    "SCHEMA_VERSION",
    "CATEGORY_SEVERITY",
    "TIME_SPAN_RE",
    "AUDIENCE_ACTION_RE",
    "load_ledger",
    "split_paragraphs",
    "extract_assertions",
    "check_coverage",
    "write_report",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
