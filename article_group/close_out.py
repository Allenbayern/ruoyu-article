"""close_out: 一条命令完成收尾（证据核对 → 人工验收 → 总复核 → 记录 → 复制版）。

为什么需要（daily-008 收尾实录）：
收尾当时要手工做五件事——跑验收脚本、重跑 final_review、生成 machine record、
手写 RUN-RECORD §9、渲染公众号复制版；漏一步就会出现"verdict 仍是 PENDING"
或"记录里没有发布事实"的空档。

安全边界（本模块刻意不做的三件事）：
1. **不自签**：人工签字仍只走既有合法入口 `scripts/record_controller_acceptance.py`，
   并且必须显式 `--confirm` 才会执行；
2. **不掩盖陈旧证据**：存在失效（stale）的 approve 时直接阻断收尾，除非显式
   `--allow-stale-evidence`；
3. **不写发布授权**：全程 `publication_authorization: not_authorized`，"已发布"
   只作为人工签字与本段记录的事实描述。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "run-close-out-v1"
MARKER_BEGIN = "<!-- close-out:begin -->"
MARKER_END = "<!-- close-out:end -->"
SECTION_TITLE = "## 9. 收尾与发布记录"

_THIS = Path(__file__).resolve()
if str(_THIS.parents[1]) not in sys.path:  # pragma: no cover - 源码树内运行
    sys.path.insert(0, str(_THIS.parents[1]))

from article_group.evidence_rebind import reconcile  # noqa: E402
from article_group.step_log import StepLog, render_markdown, timeline  # noqa: E402

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def _now() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _load(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _subprocess_runner(argv: Sequence[str], cwd: Path) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(list(argv), cwd=str(cwd), capture_output=True, text=True)


def _run_step(
    report: dict[str, Any],
    run_dir: Path,
    name: str,
    action: Callable[[], Any],
) -> Any:
    with StepLog(run_dir, f"close_out:{name}"):
        try:
            result = action()
        except Exception as exc:  # noqa: BLE001 - 收尾失败要如实记录，不吞掉
            report["steps"].append({"name": name, "status": "failed",
                                    "reason": f"{type(exc).__name__}:{exc}"})
            report.update(status="failed", reason=f"{name}:{type(exc).__name__}:{exc}")
            raise
    report["steps"].append({"name": name, "status": "ok",
                            "detail": result if isinstance(result, (str, int, dict)) else ""})
    return result


def _section_body(run_dir: Path, identity: str, ref: str, wechat_index: str) -> str:
    final = _load(run_dir / "review" / "final-review.json")
    batch = _load(run_dir / "batch.json")
    articles = batch.get("articles") or []
    aids = ", ".join(str(item.get("article_id")) for item in articles if isinstance(item, Mapping))
    pending = sorted({
        f"{item.get('article_id')}:{key}"
        for item in articles if isinstance(item, Mapping)
        for key, value in (item.get("gate_status") or {}).items()
        if str(value).lower() in {"pending", "not_run", "warning"}
    })
    lines = [
        MARKER_BEGIN,
        f"- 生成时间：{_now()}（`python -m article_group.close_out`）",
        f"- 人工验收：{aids or '（无文章）'} → `controller_acceptance=accepted`，"
        f"署名 `{identity}`；依据：{ref}",
        f"- 总复核：verdict=`{final.get('verdict')}` content=`{final.get('content_result')}` "
        f"evidence=`{final.get('evidence_result')}` governance=`{final.get('governance_result')}`",
        "- 发布：由 controller 在流程外完成；机器侧 `publication_authorization` 全程 "
        "`not_authorized`、run 级 `delivery_state` 保持 `withheld`——"
        "\"已发布\"只体现在人工签字与本段记录中。",
        f"- 公众号复制版：`{wechat_index or '（未生成）'}`",
        "- 步骤日志：`step-log.jsonl`（append-only）/ `STEP-LOG.md`",
        f"- 仍 pending 的治理/人工项：{pending or '无'}",
        MARKER_END,
    ]
    return "\n".join(lines)


def write_close_out_section(run_dir: Path, body: str, *, force: bool = False) -> str:
    """把收尾段写进 RUN-RECORD.md（标记块幂等替换）。"""
    path = run_dir / "RUN-RECORD.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else "# RUN-RECORD\n"
    if MARKER_BEGIN in text and MARKER_END in text:
        start = text.index(MARKER_BEGIN)
        end = text.index(MARKER_END) + len(MARKER_END)
        text = text[:start] + body + text[end:]
    elif SECTION_TITLE in text:
        text = text.rstrip() + "\n\n" + body + "\n"
    else:
        text = text.rstrip() + f"\n\n{SECTION_TITLE}（{_dt.date.today().isoformat()}）\n\n{body}\n"
    from article_group.evidence_write import write_evidence

    write_evidence(path, text, run_dir=run_dir, reason="close_out:run_record_section", force=force)
    return str(path)


def write_step_log_markdown(run_dir: Path, *, force: bool = False) -> str:
    """把 step-log.jsonl 渲染成 STEP-LOG.md（同样走留底+记账；此前是裸写）。"""
    from article_group.evidence_write import write_evidence

    path = run_dir / "STEP-LOG.md"
    write_evidence(
        path,
        render_markdown(timeline(run_dir)),
        run_dir=run_dir,
        reason="close_out:step_log_markdown",
        force=force,
    )
    return str(path)


def close_out(
    run_dir: str | Path,
    *,
    identity: str = "owner",
    ref: str = "controller 在会话中明确验收通过",
    theme: str = "default",
    editor_url: str = "",
    renderer_cmd: str | None = None,
    force: bool = False,
    confirm: bool = False,
    allow_stale_evidence: bool = False,
    runner: Runner | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """执行收尾；未显式确认时只返回提示，不写任何东西。"""
    root = Path(run_dir)
    repo = repo_root or Path.cwd()
    run = runner or _subprocess_runner
    # 子进程写手（验收记录/总复核/机器记录）自己守门：force 必须一路传下去，
    # 否则 close_out --force 会在中途被"另一个入口"拒掉，等于 force 半生效。
    passthrough = ["--force"] if force else []
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_dir": str(root),
        "started_at": _now(),
        "steps": [],
        "status": "ok",
        "reason": "",
        "publication_authorization": "not_authorized",
    }
    if not confirm:
        report.update(status="confirmation_required",
                      reason="人工签字项必须显式确认：加 --confirm（并在 --identity 填署名）")
        return report

    if not force:
        from article_group.run_state import sealed_reason

        blocked = sealed_reason(root)
        if blocked:
            report.update(status="run_sealed",
                          reason=f"run 已封存（{blocked}）：需 controller 明确指令后加 --force 或先 unseal")
            return report

    rebound = _run_step(report, root, "evidence_rebind",
                        lambda: reconcile(root, apply=True, force=force))
    if rebound["stale_records"] and not allow_stale_evidence:
        report.update(
            status="blocked_stale_evidence",
            reason="存在失效的复核/签字记录，先重跑复核再收尾：" + ",".join(rebound["stale_records"]),
        )
        return report

    _run_step(report, root, "controller_acceptance", lambda: run(
        [sys.executable, "scripts/record_controller_acceptance.py",
         "--run-root", str(root), "--identity", identity, "--ref", ref, *passthrough], repo))
    _run_step(report, root, "final_review", lambda: run(
        [sys.executable, "-m", "article_group.final_review", "--batch", str(root), *passthrough], repo))
    _run_step(report, root, "run_record_machine", lambda: run(
        [sys.executable, "-m", "article_group.run_record", str(root), *passthrough], repo))

    from article_group.wechat_render import render_run

    wechat = _run_step(report, root, "wechat_render", lambda: render_run(
        root, theme=theme, editor_url=editor_url, renderer_cmd=renderer_cmd, force=force))
    report["wechat_index"] = wechat.get("index_path", "")

    _run_step(report, root, "run_record_section", lambda: write_close_out_section(
        root, _section_body(root, identity, ref, wechat.get("index_path", "")), force=force))
    _run_step(report, root, "step_log_markdown", lambda: write_step_log_markdown(root, force=force))

    from article_group.run_state import seal, seal_articles

    report["seal"] = _run_step(report, root, "seal", lambda: seal(
        root, identity=identity, ref=ref, articles=seal_articles(root)))

    report["finished_at"] = _now()
    report["final_review"] = dict(_load(root / "review" / "final-review.json"))
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m article_group.close_out",
        description="一条命令收尾：证据核对 → 人工验收（需 --confirm）→ 总复核 → "
                    "machine record → 公众号复制版 → RUN-RECORD §9 → 步骤日志",
    )
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--identity", default="owner", help="人工签字署名（不得含 agent/model/ai）")
    parser.add_argument("--ref", default="controller 在会话中明确验收通过")
    parser.add_argument("--theme", default="default")
    parser.add_argument("--editor-url", default="")
    parser.add_argument("--renderer-cmd", default=None,
                        help="渲染命令模板（占位符 {md_file} {theme}）；测试/离线环境可注入桩")
    parser.add_argument("--force", action="store_true",
                        help="在已封存 run 上强制执行（默认拒绝改写封存证据）")
    parser.add_argument("--confirm", action="store_true",
                        help="确认 controller 已明确验收通过（缺省则只提示、不写入）")
    parser.add_argument("--allow-stale-evidence", action="store_true",
                        help="存在失效记录时仍然收尾（不推荐；事实会留在报告里）")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = close_out(
        args.run_root,
        identity=args.identity,
        ref=args.ref,
        theme=args.theme,
        editor_url=args.editor_url,
        renderer_cmd=args.renderer_cmd,
        force=args.force,
        confirm=args.confirm,
        allow_stale_evidence=args.allow_stale_evidence,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"收尾状态：{report['status']}" + (f" — {report['reason']}" if report["reason"] else ""))
        for step in report["steps"]:
            print(f"  [{step['status']}] {step['name']}")
        if report.get("final_review"):
            fr = report["final_review"]
            print(f"  final_review: verdict={fr.get('verdict')} governance={fr.get('governance_result')}")
    return 0 if report["status"] == "ok" else 1


__all__ = [
    "SCHEMA_VERSION",
    "MARKER_BEGIN",
    "MARKER_END",
    "SECTION_TITLE",
    "close_out",
    "write_close_out_section",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
