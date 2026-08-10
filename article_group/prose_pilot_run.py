"""prose_pilot_run: 试点运行器 —— 用真实冻结成稿跑 prose_pilot 并汇总。

用法
----
    python3 article_group/prose_pilot_run.py <batch.yaml> -o <report.json>

batch.yaml 结构:
    batches:
      - name: controlled-014
        ledger: runs/2026-08-05/controlled-014/review/evidence/citations-ledger.json
        articles:
          - path: runs/2026-08-05/controlled-014/review/frozen/ruoyu-articles-2026-08-05.1761f2e2075e.html
            label: c014-a1   # 可选

输出：单文件 JSON 报告 + 同路径 .md 人读摘要。advisory only。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from article_group.prose_pilot import analyze_html, analyze_text, _ledger_from_path


def _load_batch_yaml(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    # 极简 yaml 子集解析（仅本项目 batch 文件使用，不引入依赖）
    batches: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in raw.splitlines():
        line = line.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0 and line.strip() == "batches:":
            continue
        if indent == 2:
            # 带值的键（ledger: path）
            m_val = re.match(r"\s*(\w+):\s*(.+)$", line)
            if m_val and current is not None:
                current[m_val.group(1)] = m_val.group(2).strip()
                continue
            # 纯批次名（controlled-014:）
            m = re.match(r"\s*([\w\-]+):\s*$", line)
            if m:
                if current is not None:
                    batches.append(current)
                current = {"name": m.group(1)}
                continue
        elif indent >= 4 and current is not None:
            m = re.match(r"\s*-\s*path:\s*(.+)$", line)
            if m:
                current.setdefault("articles", []).append(
                    {"path": m.group(1).strip()})
                continue
            m2 = re.match(r"\s*label:\s*(.+)$", line)
            if m2 and current.get("articles"):
                current["articles"][-1]["label"] = m2.group(1).strip()
                continue
            m3 = re.match(r"\s*(\w+):\s*(.+)$", line)
            if m3 and current is not None:
                current[m3.group(1)] = m3.group(2).strip()
    if current is not None:
        batches.append(current)
    return {"batches": batches}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="试点运行器（advisory only）")
    parser.add_argument("batch", help="batch.yaml 路径")
    parser.add_argument("-o", "--output", required=True, help="报告输出路径 (json)")
    args = parser.parse_args(argv)

    try:
        spec = _load_batch_yaml(Path(args.batch))
    except OSError as e:
        print(f"无法读取 batch 文件: {e}", file=sys.stderr)
        return 2

    report: dict[str, Any] = {
        "advisory": True,
        "note": "试点报告（human-writing 吸收 v1）。仅人工审读参考；不改变任何 gate 状态，不阻断发布。",
        "batches": [],
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
    }

    for b in spec["batches"]:
        ledger_path = Path(b.get("ledger", "")) if b.get("ledger") else None
        quotes = _ledger_from_path(str(ledger_path)) if ledger_path else []
        articles_out = []
        for a in b.get("articles", []):
            p = Path(a["path"])
            label = a.get("label") or p.stem
            raw = p.read_text(encoding="utf-8", errors="replace")
            if "<article" in raw:
                res = analyze_html(raw, quotes)
                for i, r in enumerate(res):
                    r["label"] = f"{label}#{i + 1}"
                    articles_out.append(r)
            else:
                r = analyze_text(raw, label, quotes)
                r["label"] = label
                articles_out.append(r)
        report["batches"].append({
            "name": b["name"],
            "ledger": str(ledger_path) if ledger_path else None,
            "articles": articles_out,
        })

    out = Path(args.output)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 人读摘要
    md = ["# prose_pilot 试点报告（advisory only）\n", ""]
    for b in report["batches"]:
        md.append(f"## {b['name']}  (ledger: {b['ledger'] or '无'})")
        md.append("")
        for r in b["articles"]:
            mat = r["material"]
            md.append(f"- **{r['label']}**（{r['chars']}字 / {r['content_paragraphs']}段）")
            md.append(f"  - 材料锚点 {mat['anchor_total']}（阈值 {mat['bare_threshold']}）："
                      f"{mat['anchors'] if mat['anchors'] else '无'}"
                      f"{'；⚠低于阈值' if mat['below_threshold'] else ''}")
            if mat["matched_sources"]:
                srcs = ", ".join(mat["matched_sources"][:3])
                md.append(f"  - ledger 逐字命中 {mat['ledger_matched_quotes']} 条: {srcs}")
            for w in r["syntax_warnings"]:
                md.append(f"  - ⚠ {w['signal']}: {w['detail']}")
            md.append("")
        md.append("")

    md_path = out.with_suffix(".md")
    md_path.write_text("\n".join(md), encoding="utf-8")
    print(f"报告已写入: {out} (JSON) / {md_path} (摘要)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
