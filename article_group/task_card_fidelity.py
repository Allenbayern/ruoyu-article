"""task_card_fidelity.py — task-card promise → draft fulfillment checker.

Compares what a task card PROMISED (title_promise, 站队点, H2 outline,
ending_destination) against what the final draft actually delivered.

Motivation (controlled-018, 2026-08-12): art-001's title drifted from the
task-card candidate to "沈腾顶替徐峥？…片方至今没有回应" and art-003's last
H2 was a self-reminder sentence ("还没上映的电影，不能提前写出它的票房") that
survived into the draft until a human flagged it. The style gate checks the
final HTML in isolation (redlines, data-hook anchoring) but never cross-checks
the article against its own task card — so promise drift was invisible to
machines.

Design:
- Promise fields are extracted from the task-card markdown via the fixed
  headings used by the article group pipeline (10 必填字段, Narrative Core,
  Promise And Route, 文章结构大纲 H2 目录).
- Draft side is read from the drafts/*.md (H1/H2/article text).
- Fulfillment = per-promise keyword/entity anchoring in the draft, reported as
  ok / partial / missing with reasons. This is a triage signal for the
  controller, NOT an automatic blocker (the controller may accept a drift as
  an intentional editorial change, e.g. user-directed title rewrite).

Exit code: 0 when every promise is at least partially fulfilled; 1 when any
promise is missing. The JSON verdict is printed on stdout; --json is default.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

H1_RE = re.compile(r"^#\s+(.+)$", re.M)
H2_RE = re.compile(r"^##\s+(.+)$", re.M)
ARTICLE_ATTR_RE = re.compile(r'<article[^>]*(?:data-hook|data-topic)="([^"]*)"')
STOPWORDS = {
    "的", "了", "在", "是", "和", "与", "及", "把", "被", "让", "对", "为", "从",
    "到", "于", "之", "而", "就", "都", "也", "很", "还", "再", "又", "更", "能",
    "会", "要", "等", "吗", "呢", "吧", "啊", "哪", "些", "这个", "那个", "什么",
    "为什么", "如何", "怎样", "怎么", "一次", "一部", "一个", "一家", "一项",
    "它", "他", "她", "这", "那", "中", "里", "后", "前", "先", "最后",
    "没有", "不是", "不会", "真正", "值得", "可以", "应该", "只是", "但", "却",
    "所以", "因为", "然后", "其实", "我们", "你们", "他们", "观众", "读者",
    "电影", "影片", "影院", "票房", "上映", "内地", "市场", "时间", "时候",
    "已经", "即将", "仍在", "仍", "再进", "重新", "首次", "时隔", "迎来",
}


def _strip_md(text: str) -> str:
    return re.sub(r"[#*`>\[\]()]", "", text)


def _entities(text: str) -> list[str]:
    """Extract meaningful search entities from Chinese text.

    - 《作品名》 / “引号短语” / 数字+单位 → strong entities
    - bigrams of consecutive chars with at least one non-stopword char →
      weak entities (works for CJK without a tokenizer)
    """
    found: list[str] = []
    # 《作品名》
    found += re.findall(r"《([^》]{1,30})》", text)
    # “引号短语”
    found += re.findall(r"[“\"]([^”\"]{2,20})[”\"]", text)
    # 数字 + 单位（32年 / 9.7分 / 14.8亿 / 5000万）
    found += re.findall(r"\d+(?:\.\d+)?\s*(?:年|月|日|分|亿|万|元|天|版)?", text)
    # CJK bigrams: 相邻两字至少含一个非停用词，且非纯停用词
    pure = re.sub(r"[^一-鿿A-Za-z0-9]", "", text)
    for i in range(len(pure) - 1):
        bigram = pure[i:i + 2]
        if bigram in STOPWORDS:
            continue
        if bigram[0] in STOPWORDS and bigram[1] in STOPWORDS:
            continue
        found.append(bigram)
    # de-dup, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for e in found:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


def _coverage(entities: list[str], haystack: str) -> tuple[list[str], list[str]]:
    hit = [e for e in entities if e in haystack]
    miss = [e for e in entities if e not in haystack]
    return hit, miss


def _full_text(draft: str) -> str:
    """H1 + all H2 + article text, minus the data-hook attribute value."""
    hook = ARTICLE_ATTR_RE.search(draft)
    text = draft
    if hook:
        text = text.replace(hook.group(0), "")
    text = re.sub(r"\[数据源:[^\]]+\]", "", text)
    return text


def _parse_promise_blocks(card_text: str) -> dict[str, str]:
    """Pull promise fields from the task-card markdown by heading names."""
    out: dict[str, str] = {}
    # 站队点 (line 1 of 必填字段), title_promise, ending_destination
    m = re.search(r"^\s*\d+\.\s*\*\*站队点/可转述句\*\*\s*[:：]?\s*(.+)$", card_text, re.M)
    if m:
        out["standing_point"] = m.group(1).strip()
    m = re.search(r"^\s*[-*]?\s*\*\*title_promise\*\*\s*[:：]\s*(.+)$", card_text, re.M)
    if m:
        out["title_promise"] = m.group(1).strip()
    m = re.search(r"^\s*[-*]?\s*\*\*ending_destination\*\*\s*[:：]\s*(.+)$", card_text, re.M)
    if m:
        out["ending_destination"] = m.group(1).strip()
    # H2 大纲：从 "## 文章结构大纲（H2 目录）" 起，收集后续 ## 行，到 "## 读者缺口分析" 为止
    m = re.search(r"^##\s*文章结构大纲（H2 目录）\s*$(.*)$", card_text, re.M | re.S)
    if m:
        h2s: list[str] = []
        for line in m.group(1).splitlines():
            if line.startswith("## "):
                if line.startswith("## 读者缺口"):
                    break
                h2s.append(line[3:].strip())
        out["h2_outline"] = "\n".join(h2s)
    return out


def check_fidelity(card_path: str | Path, draft_path: str | Path) -> dict:
    card_text = Path(card_path).read_text(encoding="utf-8")
    draft_text = Path(draft_path).read_text(encoding="utf-8")

    promises = _parse_promise_blocks(card_text)
    draft_h1 = H1_RE.search(draft_text)
    draft_h2 = H2_RE.findall(draft_text)
    full = _full_text(draft_text)

    checks: list[dict] = []
    # 1) title_promise → 成稿 H1 + 开头
    if "title_promise" in promises:
        ents = _entities(promises["title_promise"])
        hit, miss = _coverage(ents, (draft_h1.group(1) if draft_h1 else "") + "\n" + full[:400])
        checks.append({
            "field": "title_promise",
            "promise": promises["title_promise"][:90],
            "entities": ents[:12],
            "hit": hit[:12],
            "miss": miss[:12],
            "status": "ok" if hit and not miss else ("partial" if hit else "missing"),
        })
    else:
        checks.append({"field": "title_promise", "promise": "", "status": "missing-field"})

    # 2) 站队点 → 全文
    if "standing_point" in promises:
        ents = _entities(promises["standing_point"])
        hit, miss = _coverage(ents, full)
        checks.append({
            "field": "standing_point",
            "promise": promises["standing_point"][:90],
            "entities": ents[:12],
            "hit": hit[:12],
            "miss": miss[:12],
            "status": "ok" if hit and len(miss) <= 1 else ("partial" if hit else "missing"),
        })
    else:
        checks.append({"field": "standing_point", "promise": "", "status": "missing-field"})

    # 3) H2 大纲 → 成稿 H2（每一条大纲 H2 的关键实体至少部分出现在成稿 H2 集合或全文）
    if "h2_outline" in promises:
        promised = [h.strip() for h in promises["h2_outline"].splitlines() if h.strip()]
        delivered = [h.strip() for h in draft_h2]
        per_h2: list[dict] = []
        for p in promised:
            ents = [e for e in _entities(p) if e not in STOPWORDS]
            hit, miss = _coverage(ents, "\n".join(delivered) + "\n" + full)
            per_h2.append({
                "promised": p[:50],
                "status": "ok" if hit else "partial" if len(miss) < len(ents) else "missing",
                "miss": miss[:8],
            })
        missing_h2 = [h for h in per_h2 if h["status"] == "missing"]
        if not promised:
            status = "missing-field"
        elif not missing_h2:
            status = "ok"
        elif len(missing_h2) >= (len(promised) + 1) // 2:
            status = "missing"
        else:
            status = "partial"
        checks.append({
            "field": "h2_outline",
            "promised_count": len(promised),
            "delivered_count": len(delivered),
            "per_h2": per_h2,
            "status": status,
        })
    else:
        checks.append({"field": "h2_outline", "promise": "", "status": "missing-field"})

    # 4) ending_destination → 结尾段（最后 400 字符）
    if "ending_destination" in promises:
        ents = _entities(promises["ending_destination"])
        hit, miss = _coverage(ents, full[-400:])
        checks.append({
            "field": "ending_destination",
            "promise": promises["ending_destination"][:90],
            "entities": ents[:12],
            "hit": hit[:12],
            "miss": miss[:12],
            "status": "ok" if hit and not miss else ("partial" if hit else "missing"),
        })
    else:
        checks.append({"field": "ending_destination", "promise": "", "status": "missing-field"})

    verdict = {
        "card": str(card_path),
        "draft": str(draft_path),
        "draft_h1": draft_h1.group(1) if draft_h1 else "",
        "draft_h2_count": len(draft_h2),
        "checks": checks,
    }
    return verdict


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2:
        print(json.dumps({
            "error": "用法: uv run python -m article_group.task_card_fidelity <task-card.md> <draft.md> [<task-card.md> <draft.md> ...]"
        }, ensure_ascii=False, indent=2))
        return 2
    pairs = list(zip(args[0::2], args[1::2]))
    verdicts = [check_fidelity(c, d) for c, d in pairs]
    statuses = [v["checks"] for v in verdicts]
    any_missing = any(
        c["status"] in ("missing", "missing-field")
        for checks in statuses for c in checks
    )
    out = {"verdicts": verdicts, "pass": not any_missing}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if not any_missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
