"""run_record: assemble the machine sections of a run's RUN-RECORD.md.

Machine-checkable sections (§2 选题与来源、§3 成稿、§4 门禁表、§6 收口)
are assembled from the run's own artifacts; human narrative sections
(§5 L2 复核、§7 顺带修复、§8 遗留) are left as placeholders for the agent
to fill.  This is a report builder: it reads artifacts, never writes them.

用法:
    python -m article_group.run_record <run_dir> [-o RUN-RECORD.md]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _pass_word(report: dict[str, Any] | None) -> str:
    if report is None:
        return "not_run"
    if report.get("pass") is True:
        return "pass"
    if report.get("pass") is False:
        return "fail"
    return str(report.get("full_gate") or report.get("status") or "not_run")


def build_run_record(run_dir: str | Path) -> str:
    root = Path(run_dir)
    run_id = f"{root.parent.name}/{root.name}" if root.parent.name[:4].isdigit() else root.name
    lines: list[str] = []
    lines.append(f"# {root.name} 运行记录（{root.parent.name}）")
    lines.append("")
    lines.append("> 类型：`two_article_daily`（默认两篇 Markdown 成品，交付终点 `CONTENT_READY`，不发布）")
    lines.append(f"> run 根：`runs/{run_id}`")
    lines.append("> 授权边界：`publication_authorization: not_authorized`，全程未发布、未推送、未合并、未写 Vault")
    lines.append("> 记录状态：provisional（agent 产出的运行记录，不是 controller 验收）")
    lines.append("> 机器节（§2/§3/§4/§6）由 `article_group.run_record` 从产物组装；人工叙事节（§5/§7/§8）请填写")
    lines.append("")

    # §1
    lines.append("## 1. 本次任务是什么")
    lines.append("")
    lines.append("按 `Hermes Article Group Workflow` 的日更主流程，从选题发现一路跑到 final review。")
    lines.append("上游发现层（R0 雷达）只提供发现信号，不充当事实。")
    lines.append("")

    # §2 选题与来源
    pool = _load(root / "candidate-pool.json")
    slots = _load(root / "slot-decisions.json")
    manifest = _load(root / "source-manifest.json")
    lines.append("## 2. 选题与来源")
    lines.append("")
    lines.append("| 篇 | 作品 | 文章模式 | content_map | 事件簇 | 核心问题 |")
    lines.append("|---|---|---|---|---|---|")
    by_cid: dict[str, dict[str, Any]] = {}
    if pool is not None:
        for candidate in pool.get("candidates", []) if isinstance(pool.get("candidates"), list) else []:
            if isinstance(candidate, dict) and candidate.get("candidate_id"):
                by_cid[str(candidate["candidate_id"])] = candidate
    if slots is not None:
        for decision in slots.get("decisions", []) if isinstance(slots.get("decisions"), list) else []:
            if not isinstance(decision, dict):
                continue
            candidate = by_cid.get(str(decision.get("candidate_id")), {})
            lines.append(
                f"| {decision.get('article_id', '?')} | {candidate.get('work_title', '?')} | "
                f"`{candidate.get('article_mode', '?')}` | {candidate.get('content_map', '?')} | "
                f"`{candidate.get('event_cluster_id', '?')}` | {candidate.get('core_question', '?')} |"
            )
    lines.append("")
    lines.append("来源全部为本机抓取的公开页面（无 cookie、无登录态），落盘于 `sources/`：")
    lines.append("")
    lines.append("| source_id | 来源 | 角色 |")
    lines.append("|---|---|---|")
    if manifest is not None:
        for source in manifest.get("sources", []) if isinstance(manifest.get("sources"), list) else []:
            if isinstance(source, dict):
                lines.append(
                    f"| `{source.get('source_id', '?')}` | {source.get('source_type', '?')} "
                    f"({source.get('source_url', '')}) | {source.get('source_role', '?')} |"
                )
    lines.append("")
    lines.append("跨批查重结论（same_work 黄灯解释）：__待填__")
    lines.append("")

    # §3 成稿
    delivery = _load(root / "review/content-delivery.json")
    lines.append("## 3. 两篇成稿")
    lines.append("")
    lines.append("| 篇 | 标题 | CJK 字数 | SHA-256（前 12 位） |")
    lines.append("|---|---|---|---|")
    if delivery is not None:
        for article in delivery.get("articles", []) if isinstance(delivery.get("articles"), list) else []:
            if not isinstance(article, dict):
                continue
            sha = str(article.get("markdown_sha256") or article.get("delivery_sha256") or "")
            lines.append(
                f"| {article.get('article_id', '?')} | {article.get('title', '?')} | "
                f"{article.get('cjk_chars', '?')} | {sha[:12]} |"
            )
    lines.append("")

    # §4 门禁与证据
    def gate_row(label: str, artifact: str, verdict: str) -> str:
        return f"| {label} | `{artifact}` | {verdict} |"

    lines.append("## 4. 门禁与证据")
    lines.append("")
    lines.append("| 门禁 | 产物 | 结果 |")
    lines.append("|---|---|---|")
    lines.append(gate_row("run contract", "review/gates/run-contract.json", "见文件"))
    preflight = _load(root / "preflight-report.json")
    lines.append(gate_row("规则合规 + preflight", "preflight-report.json", str(preflight.get("status") or "见文件") if preflight else "not_run"))
    style = _load(root / "review/style-gate-markdown-art-001.json")
    lines.append(gate_row("风格门禁（两篇）", "review/style-gate-markdown-art-00{1,2}.json", "pass" if style and style.get("pass") else "fail"))
    portfolio = _load(root / "portfolio-gate-report.json")
    lines.append(gate_row("组合门禁（跨批）", "portfolio-gate-report.json", "pass" if portfolio and portfolio.get("pass") else "fail"))
    lines.append(gate_row("task-hierarchy 1.0 契约", "task-hierarchy-validation-report.json", _pass_word(_load(root / "task-hierarchy-validation-report.json"))))
    lines.append(gate_row("claim↔来源溯源核验", "review/gates/claim-source-check.json", _pass_word(_load(root / "review/gates/claim-source-check.json"))))
    lines.append(gate_row("四阶段复核协议", "review/gates/editorial-protocol.json", _pass_word(_load(root / "review/gates/editorial-protocol.json"))))
    lines.append(gate_row("L2 内容阻塞检查", "review/gates/independent-review.json", _pass_word(_load(root / "review/gates/independent-review.json"))))
    lines.append(gate_row("prose_pilot（advisory）", "review/prose-pilot-report.json", "advisory，不阻断"))
    lines.append(gate_row("git_hygiene infra", "review/gates/git-hygiene.json", _pass_word(_load(root / "review/gates/git-hygiene.json"))))
    compliance = _load(root / "review/gates/compliance-gate.json")
    lines.append(gate_row("compliance_gate（五道门）", "review/gates/compliance-gate.json", str(compliance.get("full_gate") or "not_run") if compliance else "not_run"))
    lines.append(gate_row("final review", "review/final-review.json", "见 §6"))
    lines.append(gate_row("内容就绪", "review/content-delivery.json", str(delivery.get("content_status") or "见 §6") if delivery else "见 §6"))
    lines.append("")

    # §5 占位
    lines.append("## 5. 独立 L2 对抗复核")
    lines.append("")
    lines.append("__待填__（执行者、复核输入、入库命令、结论路径与逐条 finding）")
    lines.append("")

    # §6 收口
    final = _load(root / "review/final-review.json")
    lines.append("## 6. 收口状态（分栏）")
    lines.append("")
    lines.append("| 栏位 | 状态 | 依据 |")
    lines.append("|---|---|---|")
    content_status = str(delivery.get("content_status") or "?") if delivery else "?"
    governance = str(final.get("governance_result") or "PENDING") if final else "PENDING"
    lines.append(f"| 内容栏 | `{content_status}` | `review/content-delivery.json` |")
    lines.append(f"| 证据栏 | 见 §4 | 来源清单、哈希链、全部门禁产物 |")
    lines.append(f"| 治理栏 | `{governance}`（未做，如设计） | controller 验收、人工签署、R8 |")
    lines.append("")
    if final is not None:
        lines.append(
            "final review 终局：`verdict=%s`，`content_result=%s`，`evidence_result=%s`，"
            "`governance_result=%s`，`content_blockers=%s`。"
            % (
                final.get("verdict"), final.get("content_result"),
                final.get("evidence_result"), final.get("governance_result"),
                final.get("content_blockers"),
            )
        )
        lines.append("")
    lines.append("**注意**：`CONTENT_READY` 只表示\"可以交给人复制发布\"，不等于发布授权；本 run 的 `publication_authorization` 始终为 `not_authorized`。")
    lines.append("")

    # §7/§8 占位
    lines.append("## 7. 本轮顺带修掉的工具缺陷（有测试）")
    lines.append("")
    lines.append("__待填__（无则写\"无\"）")
    lines.append("")
    lines.append("## 8. 未验证与遗留")
    lines.append("")
    lines.append("- 未做：R8 治理推进、controller 验收、人工可读性签署、HTML 渲染与预览、发布。")
    lines.append("- 四阶段复核入口（project_precheck/prewrite/postdraft/prepublication）尚未接入日更，按 coverage gap 记录。")
    lines.append("__待填__（本 run 遗留观察）")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="组装 run 的 RUN-RECORD 机器节")
    parser.add_argument("run_dir", help="run 根目录（如 runs/2026-09-15/daily-005）")
    parser.add_argument("-o", "--output", help="输出路径；默认 run_dir/RUN-RECORD.machine.md")
    args = parser.parse_args(argv)
    root = Path(args.run_dir)
    out = Path(args.output) if args.output else root / "RUN-RECORD.machine.md"
    out.write_text(build_run_record(root), encoding="utf-8")
    print(f"已写入: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
