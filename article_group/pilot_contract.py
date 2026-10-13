"""Contract layer for the manually-triggered Article Group Bot pilot.

This module owns the pilot protocol, not the article-quality decision itself.
Existing Article Group gates remain authoritative for sources, style, anti-AI,
L2 review, hashes, and ``CONTENT_READY``.  The pilot contract only makes the
role handoffs, human gates, and run-vs-artifact distinction auditable.

Usage::

    uv run python -m article_group.pilot_contract init \
      --project-root . --case-id case-001 --topic-label "..."
    uv run python -m article_group.pilot_contract handoff \
      --run-root runs/2026-10-12/dsh-pilot-case-001 \
      --stage discovery --status complete --owner scout \
      --payload-json '{"output_refs":["candidate-pool.json"]}'
    uv run python -m article_group.pilot_contract validate \
      --project-root . --run-root runs/2026-10-12/dsh-pilot-case-001

All run writes go through :mod:`article_group.evidence_write`, so this pilot
inherits before-images, append-only changelog entries, and sealed-run guards.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from typing import Any

from .evidence_write import write_evidence, write_evidence_json
from .pilot_extensions import (
    build_title_targeted_search_plan,
    check_markdown_image_integrity,
    classify_viral_pillar,
    evaluate_three_tier_evidence,
    freeze_title,
    prose_pilot_check,
    run_timestamp_peel_test,
    validate_and_normalize_l2_review,
    verify_artifact_hash_bindings,
    verify_claims_anchored_in_sources,
    verify_title_freeze,
)


CONTRACT_VERSION = "article-group-bot-pilot-v1"
PUBLICATION_AUTHORIZATION = "not_authorized"
PILOT_CASE_UNIT = "single_longform"
WORKFLOW_MODE = "manual_stage_pipeline"

ROLE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "controller": {
        "label": "Controller / Orchestrator",
        "responsibility": "维护状态、读取交接件、推进阶段、停稿和回退。",
        "inputs": ["当前 run 交接件", "用户人工决策", "门禁报告"],
        "outputs": ["阶段推进", "失败路由", "RUN-RECORD", "交付状态"],
        "forbidden": ["替用户批准选题", "替用户批准最终稿", "授予发布授权"],
    },
    "scout": {
        "label": "Scout",
        "responsibility": "搜刮热点、作品和事件，形成候选池。",
        "inputs": ["R0 雷达", "订阅索引", "当日公开信号"],
        "outputs": ["candidate-pool.json", "候选摘要", "证据准备度粗核"],
        "forbidden": ["自行立项", "直接起草正文", "把热度当作事实或价值"],
    },
    "evidence_researcher": {
        "label": "Evidence Researcher",
        "responsibility": "核验权威来源，生成事实包和待核清单。",
        "inputs": ["已批准选题与切口", "候选来源", "公开权威页面"],
        "outputs": ["fact-card.json", "sources/", "pending-review-sheet.json", "来源映射"],
        "forbidden": ["替用户做最终选题", "把推测写成事实", "补造动机、数据或因果"],
    },
    "editorial_planner": {
        "label": "Editorial Planner",
        "responsibility": "在选题和事实包获批后生成标题、切口、结构和任务卡。",
        "inputs": ["topic gate", "fact-card.json", "跨批检查结果"],
        "outputs": ["writing-brief.json", "<=30字标题候选", "结构承诺"],
        "forbidden": ["扩大事实边界", "绕过待核项", "未经核验修改事实"],
    },
    "writer": {
        "label": "Writer",
        "responsibility": "只依据批准事实包和任务卡起草及定向修订。",
        "inputs": ["writing-brief.json", "fact-card.json", "已回读来源"],
        "outputs": ["draft.md", "定向修订记录"],
        "forbidden": ["自行补写未核事实", "整篇无理由重写", "暴露内部审查过程"],
    },
    "quality_l2_reviewer": {
        "label": "Quality / L2 Reviewer",
        "responsibility": "执行确定性门禁并以独立只读会话完成对抗性复核。",
        "inputs": ["draft.md", "fact-card.json", "任务卡", "既有 gate 产物"],
        "outputs": ["gate reports", "independent-review.json", "findings"],
        "forbidden": ["直接改稿", "把 warning 伪装为 pass", "授予发布权"],
    },
}

STAGES: tuple[str, ...] = (
    "discovery",
    "topic_gate",
    "evidence",
    "planning",
    "draft",
    "quality_review",
    "final_gate",
    "delivery",
)
MANUAL_GATES = frozenset({"topic_gate", "final_gate"})
STAGE_OWNERS = {
    "discovery": "scout",
    "topic_gate": "human",
    "evidence": "evidence_researcher",
    "planning": "editorial_planner",
    "draft": "writer",
    "quality_review": "quality_l2_reviewer",
    "final_gate": "human",
    "delivery": "controller",
}
ALLOWED_STATUSES = frozenset({"not_run", "complete", "approved", "rejected", "blocked", "needs_changes"})
PASS_STATUSES = frozenset({"complete", "approved"})
FAIL_STATUSES = frozenset({"blocked", "rejected", "needs_changes"})
ALLOWED_ARTIFACT_STATUSES = frozenset({"not_ready", "candidate", "ready_for_controller", "content_ready"})
CASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


class PilotContractError(ValueError):
    """A deterministic pilot-contract violation."""


def _now() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _json_load(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _safe_case_id(value: str) -> str:
    if not isinstance(value, str) or not CASE_ID_RE.fullmatch(value):
        raise PilotContractError("case_id must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
    return value


def _project_root(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise PilotContractError(f"project_root_missing:{root}")
    return root


def _run_root(project_root: str | Path, raw: str | Path) -> Path:
    project = _project_root(project_root)
    root = Path(raw).expanduser().resolve()
    runs_root = (project / "runs").resolve()
    try:
        root.relative_to(runs_root)
    except ValueError as exc:
        raise PilotContractError("run_root_outside_project_runs") from exc
    if not root.is_dir():
        raise PilotContractError(f"run_root_missing:{root}")
    return root


def _write_json(root: Path, relative: str, payload: dict[str, Any], reason: str) -> dict[str, Any]:
    return write_evidence_json(root / relative, payload, run_dir=root, reason=reason, author="article-group-pilot")


def _write_text(root: Path, relative: str, text: str, reason: str) -> dict[str, Any]:
    return write_evidence(root / relative, text, run_dir=root, reason=reason, author="article-group-pilot")


def _stage_path(root: Path, stage: str) -> Path:
    return root / "handoffs" / f"{stage}.json"


def _stage_record(root: Path, stage: str) -> dict[str, Any]:
    record = _json_load(_stage_path(root, stage))
    if record is None:
        return {
            "contract_version": CONTRACT_VERSION,
            "stage": stage,
            "status": "not_run",
            "revision": 0,
            "not_run_reason": "missing_stage_record",
        }
    return record


def _initial_stage_record(stage: str) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "stage": stage,
        "status": "not_run",
        "revision": 0,
        "owner": STAGE_OWNERS[stage],
        "artifact_status": "not_ready",
        "publication_authorization": PUBLICATION_AUTHORIZATION,
        "not_run_reason": "not_started",
        "created_at": _now(),
        "updated_at": _now(),
    }


def _refresh_run_record(root: Path) -> None:
    """根据当前 run 的真实交接件、成稿哈希、L2 结论与微信排版清单，自动刷新 RUN-RECORD.md。"""
    import hashlib

    manifest = _json_load(root / "pilot-manifest.json") or {}
    run_id = str(manifest.get("run_id") or root.name)
    date_str = root.parent.name if root.parent.name[:4].isdigit() else "unknown-date"

    stage_default_summaries = {
        "discovery": "已完成热点搜刮与候选池构建",
        "topic_gate": "人工已批准选题与切口",
        "evidence": "已完成权威来源快照与事实账本核验",
        "planning": "已完成标题哈希冻结与写作任务卡",
        "draft": "已完成 12 篇母本呼吸律动成稿",
        "quality_review": "确定性门禁全绿且独立 L2 复核 approve",
        "final_gate": "人工终审已签发批准",
        "delivery": "摸鱼绿微信排版三件套与交付物就绪",
    }
    stage_rows: list[str] = []
    for st in STAGES:
        rec = _stage_record(root, st)
        st_status = str(rec.get("status") or "not_run")
        if st_status in PASS_STATUSES:
            summary_or_reason = str(rec.get("summary") or stage_default_summaries.get(st, "阶段已完成"))
        else:
            summary_or_reason = str(rec.get("summary") or rec.get("not_run_reason") or "未开始")
        stage_rows.append(f"| `{st}` | `handoffs/{st}.json` | `{st_status}` | {summary_or_reason} |")

    tp = _json_load(root / "title-pack.json") or {}
    selected_title = str(tp.get("selected_title") or "（待定题）")

    draft_path = root / "draft.md"
    if draft_path.is_file():
        draft_bytes = draft_path.read_bytes()
        draft_sha = hashlib.sha256(draft_bytes).hexdigest()[:12]
        draft_cjk = len(re.findall(r"[\u4e00-\u9fff]", draft_bytes.decode("utf-8", errors="ignore")))
    else:
        draft_sha = "not_run"
        draft_cjk = 0

    wx_manifest = _json_load(root / "wechat" / "wechat-manifest.json") or {}
    wx_body_sha = str(wx_manifest.get("body_sha256") or "")[:12] or "not_run"

    l2_data = _json_load(root / "review" / "l2-adversarial-review.json") or {}
    l2_decision = str(l2_data.get("decision") or "not_run")
    l2_findings_cnt = len(l2_data.get("findings") or []) if isinstance(l2_data.get("findings"), list) else 0

    run_status = str(manifest.get("run_status") or "active")
    artifact_status = str(manifest.get("artifact_status") or "not_ready")

    text = f"""# {root.name} 运行记录（{date_str}）

> 类型：`article_group_bot_pilot`（单篇长文，手动触发，阶段流水线）
> run 根：`runs/{run_id}`
> 授权边界：`publication_authorization: not_authorized`，不发布、不推送、不写 Vault
> 记录状态：provisional；工具完成不等于文章可交付

## 1. 本次任务是什么

这是 Article Group Bot 分工系统的受控单篇长文运行（`{manifest.get('case_id', root.name)}`：{manifest.get('topic_label', '')}）。

## 2. 选题与来源

- 选定标题：`{selected_title}`
- 来源清单：`source-manifest.json`（真实快照落盘于 `sources/*.clean.md`）

## 3. 成稿与微信排版

| 产物 | 路径 | CJK 字数 | SHA-256（前 12 位） |
|---|---|---|---|
| Markdown 成稿 | `draft.md` | {draft_cjk} | `{draft_sha}` |
| 摸鱼绿微信纯享片段 | `wechat/body.html` | — | `{wx_body_sha}` |
| 摸鱼绿微信预览页 | `wechat/preview.html` | — | 见 `wechat/wechat-manifest.json` |

## 4. 门禁与阶段交接

| 阶段 | 交接件 | 状态 | 摘要 / 原因 |
|---|---|---|---|
{chr(10).join(stage_rows)}

## 5. 独立 L2 对抗复核

- 复核记录：`review/l2-adversarial-review.json`
- 结论：`{l2_decision}`（findings 数量：{l2_findings_cnt}）

## 6. 收口状态（分栏）

- 运行状态：`{run_status}`
- 物料状态：`{artifact_status}`
- 发布授权：`not_authorized`（`CONTENT_READY` 不等于发布授权）

## 7. 本轮顺带修掉的工具缺陷（有测试）

- 全量数字与引语溯源核验、跨阶段 `draft_sha256` 哈希强绑定、L2 Schema 与防带病 approve 校验、Markdown 悬空图片拦截、摸鱼绿微信排版校验及 `RUN-RECORD.md` 自动刷新。

## 8. 未验证与遗留

- 朱雀在线 API 检测按需触发（离线时在 `review/gate-registry-report.json` 中显式记 `not_run`）。
- 未启用 cron、定时发现、自动选题或自动发布。
"""
    _write_text(root, "RUN-RECORD.md", text, "pilot:refresh_run_record")


def _run_record(run_id: str, date: str) -> str:
    gate_rows = "\n".join(
        f"| `{stage}` | `handoffs/{stage}.json` | `not_run` | 未开始 |" for stage in STAGES
    )
    return f"""# {run_id} 运行记录（{date}）

> 类型：`article_group_bot_pilot`（单篇长文，手动触发，阶段流水线）
> run 根：`runs/{date}/{run_id}`
> 授权边界：`publication_authorization: not_authorized`，不发布、不推送、不写 Vault
> 记录状态：provisional；工具完成不等于文章可交付

## 1. 本次任务是什么

这是 Article Group Bot 分工系统的第一个手动试点。目标是跑通发现、人工选题门、证据、规划、起草、质量复核、人工最终门和交付记录。

## 2. 选题与来源

选题必须遵循“搜刮 → 候选池 → controller/Allen 选题与切口批准”。候选和来源记录由 `scout` / `evidence_researcher` 写入本 run；热度不直接等于事实或内容价值。

## 3. 成稿

单篇 Markdown 成稿；正文不在会话中粘贴，最终以 run 内交付文件为准。

## 4. 门禁与证据

| 阶段 | 交接件 | 状态 | 原因 |
|---|---|---|---|
{gate_rows}

所有未跑阶段显式记为 `not_run`，不得静默跳过。既有 Article Group Python 门禁（来源、风格、反 AI、L2、哈希、`CONTENT_READY`）仍是内容判定权威。

## 5. 独立 L2 对抗复核

必须由独立只读子代理执行，并将结构化结果写入 `quality_review` 交接件。复核证据不能授权发布。

## 6. 收口状态（分栏）

- 运行状态：`active`
- 物料状态：`not_ready`
- 内容就绪与治理、发布授权分栏；`CONTENT_READY` 不等于发布授权。

## 7. 本轮顺带修掉的工具缺陷（有测试）

试点编排工具本身的修复与测试写入项目变更记录；文章 run 只记录本轮实际修复。

## 8. 未验证与遗留

- 首次初始化时所有阶段均 `not_run`。
- 未启用 cron、定时发现、自动选题或自动发布。
"""


def init_run(project_root: str | Path, case_id: str, topic_label: str = "") -> dict[str, Any]:
    project = _project_root(project_root)
    case = _safe_case_id(case_id)
    date = datetime.now().astimezone().date().isoformat()
    run_id = f"dsh-pilot-{case}"
    root = project / "runs" / date / run_id
    if root.exists():
        raise PilotContractError(f"run_exists:{root}")
    root.mkdir(parents=True)
    for directory in ("handoffs", "sources", "review", "delivery", "metrics"):
        (root / directory).mkdir()

    manifest: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "run_id": f"{date}/{run_id}",
        "case_id": case,
        "topic_label": topic_label.strip(),
        "pilot_case_unit": PILOT_CASE_UNIT,
        "workflow_mode": WORKFLOW_MODE,
        "roles": list(ROLE_DEFINITIONS),
        "stage_order": list(STAGES),
        "manual_gates": sorted(MANUAL_GATES),
        "publication_authorization": PUBLICATION_AUTHORIZATION,
        "schedule_enabled": False,
        "run_status": "active",
        "artifact_status": "not_ready",
        "created_at": _now(),
        "updated_at": _now(),
    }
    _write_json(root, "pilot-manifest.json", manifest, "pilot:init:manifest")
    _write_text(root, "RUN-RECORD.md", _run_record(run_id, date), "pilot:init:run-record")
    for stage in STAGES:
        _write_json(root, f"handoffs/{stage}.json", _initial_stage_record(stage), f"pilot:init:{stage}")
    return {
        "ok": True,
        "contract_version": CONTRACT_VERSION,
        "run_root": str(root),
        "run_id": manifest["run_id"],
        "case_id": case,
        "schedule_enabled": False,
        "publication_authorization": PUBLICATION_AUTHORIZATION,
        "status": "IN_PROGRESS",
    }


def _string_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise PilotContractError(f"{field}_must_be_nonempty_string_array")
    return [item.strip() for item in value]


def _payload(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise PilotContractError(f"payload_json_invalid:{exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise PilotContractError("payload_json_must_be_object")
    return parsed


def record_handoff(
    project_root: str | Path,
    run_root: str | Path,
    stage: str,
    status: str,
    owner: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = _run_root(project_root, run_root)
    if stage not in STAGES:
        raise PilotContractError(f"unknown_stage:{stage}")
    if status not in ALLOWED_STATUSES:
        raise PilotContractError(f"unknown_status:{status}")
    expected_owner = STAGE_OWNERS[stage]
    if owner != expected_owner:
        raise PilotContractError(f"owner_mismatch:{stage}:expected:{expected_owner}")
    data = dict(payload or {})
    current = _stage_record(root, stage)
    revision = int(current.get("revision") or 0) + 1
    previous_pass = True
    index = STAGES.index(stage)
    if index > 0:
        previous = _stage_record(root, STAGES[index - 1])
        previous_pass = previous.get("status") in PASS_STATUSES
        if status in PASS_STATUSES and not previous_pass:
            raise PilotContractError(f"upstream_not_passed:{STAGES[index - 1]}")
        if status in FAIL_STATUSES and not previous_pass:
            raise PilotContractError(f"cannot_fail_unstarted_stage:{STAGES[index - 1]}")

    if stage in MANUAL_GATES:
        if status not in {"not_run", "approved", "rejected", "blocked"}:
            raise PilotContractError(f"manual_gate_status_invalid:{stage}")
        if status == "not_run" and not data.get("not_run_reason"):
            raise PilotContractError(f"not_run_reason_required:{stage}")
        if status == "approved" and not (data.get("output_refs") or data.get("decision_ref")):
            raise PilotContractError(f"approval_evidence_required:{stage}")
    elif status == "approved":
        raise PilotContractError(f"non_manual_stage_cannot_be_approved:{stage}")

    if status in FAIL_STATUSES and not data.get("blocking_issues"):
        raise PilotContractError(f"blocking_issues_required:{stage}")
    if status == "not_run" and not data.get("not_run_reason"):
        raise PilotContractError(f"not_run_reason_required:{stage}")

    input_refs = _string_list(data.get("input_refs"), "input_refs")
    output_refs = _string_list(data.get("output_refs"), "output_refs")
    artifact_refs = _string_list(data.get("artifact_refs"), "artifact_refs")
    blocking_issues = _string_list(data.get("blocking_issues"), "blocking_issues")
    artifact_status = str(data.get("artifact_status") or current.get("artifact_status") or "not_ready")
    if artifact_status not in ALLOWED_ARTIFACT_STATUSES:
        raise PilotContractError(f"unknown_artifact_status:{artifact_status}")

    if stage == "planning" and status == "complete":
        ev_rec = _stage_record(root, "evidence")
        if ev_rec.get("human_material_approved") is False or data.get("human_material_approved") is False:
            raise PilotContractError("human_material_approval_required_before_planning")

        ev_pack_path = root / "evidence-pack.json"
        src_manifest_path = root / "source-manifest.json"
        if ev_pack_path.exists() and src_manifest_path.exists():
            ev_payload = _json_load(ev_pack_path) or {}
            prov = verify_claims_anchored_in_sources(root, ev_payload)
            if not prov["passed"]:
                raise PilotContractError(f"claim_source_provenance_failed:{','.join(prov['errors'])}")

        title_cand = str(data.get("selected_title") or "").strip()
        if title_cand:
            freeze_title(root, title_cand)
            search_plan = build_title_targeted_search_plan(title_cand, str(data.get("killer_stance") or ""))
            _write_json(root, "review/title-targeted-search-plan.json", search_plan, "planning:title_targeted_search_plan")

    if stage == "draft" and status == "complete":
        draft_file = root / "draft.md"
        if draft_file.exists():
            draft_text = draft_file.read_text(encoding="utf-8")
            ok, msg = prose_pilot_check(draft_text)
            if not ok:
                raise PilotContractError(f"prose_pilot_rejected:{msg}")
            img_res = check_markdown_image_integrity(draft_text, root)
            if not img_res["passed"]:
                raise PilotContractError(f"dangling_markdown_images:{','.join(img_res['dangling_images'])}")

    if stage == "quality_review" and status == "complete":
        if data.get("deterministic_gates") != "pass":
            raise PilotContractError("deterministic_gates_pass_required:quality_review")
        if data.get("l2_decision") != "approve":
            raise PilotContractError("l2_approve_required:quality_review")
        if not artifact_refs:
            raise PilotContractError("l2_review_artifact_required:quality_review")

        det_file = root / "review" / "deterministic-gates.json"
        if det_file.is_file():
            det_payload = _json_load(det_file) or {}
            det_stat = det_payload.get("deterministic_gates") or det_payload.get("overall")
            if det_stat != "pass":
                raise PilotContractError("deterministic_gates_file_failed:quality_review")

        l2_file = root / "review" / "l2-adversarial-review.json"
        if l2_file.is_file():
            l2_payload = _json_load(l2_file) or {}
            l2_val = validate_and_normalize_l2_review(l2_payload)
            if not l2_val["valid"] or l2_val["effective_decision"] != "approve":
                raise PilotContractError(f"l2_contract_violation:{','.join(l2_val['errors'])}")

        # 验证标题是否在冻结后被偷偷篡改
        title_to_verify = str(data.get("selected_title") or "").strip()
        freeze_rec = root / "review" / "title-freeze.json"
        if freeze_rec.exists() and title_to_verify:
            ok, msg = verify_title_freeze(root, title_to_verify)
            if not ok:
                raise PilotContractError(f"title_freeze_violation:{msg}")

    publication = str(data.get("publication_authorization") or PUBLICATION_AUTHORIZATION)
    if publication != PUBLICATION_AUTHORIZATION:
        raise PilotContractError("publication_authorization_must_remain_not_authorized")

    if stage == "delivery" and status == "complete":
        if artifact_status != "content_ready":
            raise PilotContractError("delivery_requires_content_ready_artifact_status")
        if not artifact_refs:
            raise PilotContractError("delivery_artifact_required")
        wx_body = root / "wechat" / "body.html"
        if wx_body.exists():
            from .moyu_green_renderer import validate_moyu_green_html
            wx_val = validate_moyu_green_html(wx_body.read_text(encoding="utf-8"))
            if not wx_val["passed"]:
                raise PilotContractError(f"moyu_green_wechat_redline_violation:{','.join(wx_val['errors'])}")
        bind_res = verify_artifact_hash_bindings(root)
        if not bind_res["passed"]:
            raise PilotContractError(f"artifact_hash_binding_violation:{','.join(bind_res['errors'])}")

    record: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "run_id": (_json_load(root / "pilot-manifest.json") or {}).get("run_id", root.name),
        "stage": stage,
        "revision": revision,
        "status": status,
        "owner": owner,
        "summary": str(data.get("summary") or "").strip(),
        "input_refs": input_refs,
        "output_refs": output_refs,
        "artifact_refs": artifact_refs,
        "blocking_issues": blocking_issues,
        "next_action": str(data.get("next_action") or "").strip(),
        "not_run_reason": str(data.get("not_run_reason") or "").strip(),
        "artifact_status": artifact_status,
        "publication_authorization": publication,
        "created_at": current.get("created_at") or _now(),
        "updated_at": _now(),
    }
    for key in (
        "human_decision",
        "decision_ref",
        "l2_decision",
        "deterministic_gates",
        "quality_gate_ref",
        "selected_candidate_ref",
        "human_material_approved",
    ):
        if key in data:
            record[key] = data[key]

    _write_json(root, f"handoffs/{stage}.json", record, f"pilot:handoff:{stage}")
    manifest = _json_load(root / "pilot-manifest.json")
    if manifest is None:
        raise PilotContractError("pilot_manifest_missing_or_invalid")
    manifest["updated_at"] = _now()
    manifest["current_stage"] = stage
    manifest["last_handoff_status"] = status
    manifest["run_status"] = "blocked" if status in FAIL_STATUSES else (
        "complete" if stage == "delivery" and status == "complete" else "active"
    )
    if stage == "delivery":
        manifest["artifact_status"] = artifact_status
    _write_json(root, "pilot-manifest.json", manifest, "pilot:handoff:manifest")
    _refresh_run_record(root)
    return {"ok": True, "handoff": record, "run_root": str(root)}


def validate_run(project_root: str | Path, run_root: str | Path) -> dict[str, Any]:
    root = _run_root(project_root, run_root)
    manifest = _json_load(root / "pilot-manifest.json")
    errors: list[str] = []
    warnings: list[str] = []
    if manifest is None:
        errors.append("pilot_manifest_missing_or_invalid")
        manifest = {}
    if manifest.get("contract_version") != CONTRACT_VERSION:
        errors.append("contract_version_mismatch")
    if manifest.get("publication_authorization") != PUBLICATION_AUTHORIZATION:
        errors.append("manifest_publication_authorization_invalid")
    if manifest.get("schedule_enabled") is not False:
        errors.append("schedule_must_remain_disabled")

    stages: dict[str, dict[str, Any]] = {}
    first_failure: str | None = None
    for index, stage in enumerate(STAGES):
        record = _stage_record(root, stage)
        stages[stage] = record
        status = record.get("status")
        if record.get("contract_version") != CONTRACT_VERSION:
            errors.append(f"{stage}:contract_version_mismatch")
        if status not in ALLOWED_STATUSES:
            errors.append(f"{stage}:unknown_status")
            continue
        if record.get("publication_authorization") != PUBLICATION_AUTHORIZATION:
            errors.append(f"{stage}:publication_authorization_invalid")
        if index > 0:
            previous = stages[STAGES[index - 1]]
            if status in PASS_STATUSES and previous.get("status") not in PASS_STATUSES:
                errors.append(f"{stage}:upstream_not_passed:{STAGES[index - 1]}")
        if status in FAIL_STATUSES:
            if first_failure is None:
                first_failure = stage
            errors.append(f"{stage}:stage_{status}")
        if first_failure is not None and index > STAGES.index(first_failure) and status in PASS_STATUSES:
            errors.append(f"{stage}:downstream_pass_after_failure:{first_failure}")
        if status == "not_run" and not record.get("not_run_reason"):
            errors.append(f"{stage}:not_run_reason_missing")
        if stage in MANUAL_GATES:
            if status == "approved" and record.get("owner") != "human":
                errors.append(f"{stage}:human_owner_required")
            if status not in {"not_run", "approved", "rejected", "blocked"}:
                errors.append(f"{stage}:manual_gate_status_invalid")

    quality = stages["quality_review"]
    if quality.get("status") in PASS_STATUSES:
        if quality.get("deterministic_gates") != "pass":
            errors.append("quality_review:deterministic_gates_not_pass")
        det_file = root / "review" / "deterministic-gates.json"
        if det_file.is_file():
            det_payload = _json_load(det_file) or {}
            det_stat = det_payload.get("deterministic_gates") or det_payload.get("overall")
            if det_stat != "pass":
                errors.append("quality_review:deterministic_gates_file_not_pass")
        if quality.get("l2_decision") != "approve":
            errors.append("quality_review:l2_not_approved")
        if not quality.get("artifact_refs"):
            errors.append("quality_review:l2_artifact_missing")
        l2_file = root / "review" / "l2-adversarial-review.json"
        if l2_file.is_file():
            l2_payload = _json_load(l2_file) or {}
            l2_val = validate_and_normalize_l2_review(l2_payload)
            if not l2_val["valid"]:
                errors.extend(f"quality_review:l2_schema:{e}" for e in l2_val["errors"])
            if l2_val["effective_decision"] != "approve":
                errors.append(f"quality_review:l2_file_decision_is_{l2_val['effective_decision']}")

    bind_res = verify_artifact_hash_bindings(root)
    if not bind_res["passed"]:
        errors.extend(f"hash_binding:{e}" for e in bind_res["errors"])

    delivery = stages["delivery"]
    run_completed = all(stages[stage].get("status") in PASS_STATUSES for stage in STAGES)
    artifact_ready = (
        not errors
        and run_completed
        and delivery.get("status") == "complete"
        and delivery.get("artifact_status") == "content_ready"
        and delivery.get("publication_authorization") == PUBLICATION_AUTHORIZATION
    )
    if not run_completed and not errors:
        warnings.append("run_in_progress_or_waiting_for_human_gate")
    if run_completed and delivery.get("artifact_status") != "content_ready":
        warnings.append("run_completed_but_artifact_not_ready")
    status = "BLOCKED" if errors else ("PASS" if run_completed else "IN_PROGRESS")
    report = {
        "contract_version": CONTRACT_VERSION,
        "run_root": str(root),
        "status": status,
        "run_completed": run_completed,
        "artifact_ready": artifact_ready,
        "publication_authorization": PUBLICATION_AUTHORIZATION,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "stages": {stage: stages[stage].get("status") for stage in STAGES},
        "first_failure_stage": first_failure,
        "validated_at": _now(),
    }
    _write_json(root, "pilot-validation.json", report, "pilot:validate")
    _refresh_run_record(root)
    return report


def advance_pipeline(
    project_root: str | Path,
    run_root: str | Path,
    *,
    author: str = "controller",
) -> dict[str, Any]:
    """半自动化向导：在两大人工门（topic_gate 与 final_gate）红线约束下，一键推进非人工阶段。
    1. topic_gate 未批：阻断并提示等待人工圈题；
    2. topic_gate 已批：自动串联推进 evidence -> planning（冻结标题、制定靶向搜检计划、装配 Writer 提示词）；
    3. draft 已完成：自动串联跑批全量确定性门禁 + 渲染摸鱼绿排版三件套，呈递等待 final_gate 人工终审；
    4. final_gate 已批：自动执行 delivery 交付物规整并执行不可变封存（SEALED）！
    """
    from .moyu_green_renderer import render_moyu_green_from_run
    from .pilot_adapters import run_all_pilot_gates
    from .prompt_assembler import assemble_writer_prompt

    root = _run_root(project_root, run_root)
    val = validate_run(project_root, root)
    stages = val.get("stages") or {}

    actions_taken: list[str] = []

    # 阶段 A：若 topic_gate 未批准
    if stages.get("discovery") != "complete":
        return {
            "ok": False,
            "next_gate": "discovery",
            "message": "需先由 Scout 生成候选池并完成 discovery 阶段交接",
            "actions_taken": actions_taken,
        }

    if stages.get("topic_gate") != "approved":
        return {
            "ok": True,
            "next_gate": "topic_gate",
            "message": "⏳ 等待人工选题门（topic_gate）批准。请用户签署选题与切口后再推进。",
            "actions_taken": actions_taken,
        }

    # 阶段 B：topic_gate 已批准 -> 推进 evidence
    if stages.get("evidence") != "complete":
        manifest_path = root / "source-manifest.json"
        ev_pack_path = root / "evidence-pack.json"
        if not (manifest_path.is_file() and ev_pack_path.is_file()):
            return {
                "ok": False,
                "next_gate": "evidence",
                "message": "缺少 source-manifest.json 或 evidence-pack.json，无法自动推进 evidence 阶段",
                "actions_taken": actions_taken,
            }
        record_handoff(
            project_root,
            root,
            "evidence",
            "complete",
            "evidence_researcher",
            {
                "output_refs": ["source-manifest.json", "evidence-pack.json"],
                "artifact_refs": ["source-manifest.json", "evidence-pack.json"],
                "summary": "已完成权威来源快照与四阶事实账本核验",
                "human_material_approved": True,
            },
        )
        actions_taken.append("evidence_completed")
        stages["evidence"] = "complete"

    # 阶段 C：evidence 已完成 -> 推进 planning
    if stages.get("planning") != "complete":
        title_pack_path = root / "title-pack.json"
        brief_path = root / "article-brief.json"
        if not (title_pack_path.is_file() and brief_path.is_file()):
            return {
                "ok": False,
                "next_gate": "planning",
                "message": "缺少 title-pack.json 或 article-brief.json，无法自动推进 planning 阶段",
                "actions_taken": actions_taken,
            }
        tp_data = _json_load(title_pack_path) or {}
        selected_title = str(tp_data.get("selected_title") or "").strip()
        brief_data = _json_load(brief_path) or {}
        killer_stance = str(brief_data.get("killer_stance") or "").strip()

        # 装配 Writer 提示词
        assemble_writer_prompt(root, author="editorial_planner", save_evidence=True)

        record_handoff(
            project_root,
            root,
            "planning",
            "complete",
            "editorial_planner",
            {
                "selected_title": selected_title,
                "killer_stance": killer_stance,
                "human_material_approved": True,
                "output_refs": ["title-pack.json", "article-brief.json", "review/writer-prompt.md"],
                "artifact_refs": ["title-pack.json", "article-brief.json"],
                "summary": "已完成标题哈希冻结、靶向搜检计划与主笔提示词装配",
            },
        )
        actions_taken.append("planning_completed_and_prompt_assembled")
        stages["planning"] = "complete"

    # 阶段 D：若 draft 尚未就绪
    draft_path = root / "draft.md"
    if stages.get("draft") != "complete":
        if not draft_path.is_file():
            return {
                "ok": True,
                "next_gate": "draft",
                "message": "📝 Planning 已就绪！请主笔参考 `review/writer-prompt.md` 起草 `draft.md`。",
                "actions_taken": actions_taken,
                "writer_prompt_file": str(root / "review" / "writer-prompt.md"),
            }
        else:
            record_handoff(
                project_root,
                root,
                "draft",
                "complete",
                "writer",
                {
                    "output_refs": ["draft.md"],
                    "artifact_refs": ["draft.md"],
                    "summary": "主笔已完成正文成稿",
                },
            )
            actions_taken.append("draft_completed")
            stages["draft"] = "complete"

    # 阶段 E：draft 已完成 -> 自动跑批门禁与微信排版
    if stages.get("quality_review") != "complete":
        gate_res = run_all_pilot_gates(root, strict_assertions=True)
        if gate_res.get("deterministic_gates") != "pass":
            return {
                "ok": False,
                "next_gate": "quality_review",
                "message": "确定性门禁未通过，请检查 `review/deterministic-gates.json`",
                "deterministic_gates": gate_res.get("deterministic_gates"),
                "actions_taken": actions_taken,
            }
        l2_path = root / "review" / "l2-adversarial-review.json"
        l2_data = _json_load(l2_path) or {}
        l2_dec = str(l2_data.get("decision") or "")
        if l2_dec != "approve":
            return {
                "ok": True,
                "next_gate": "l2_adversarial_review",
                "message": "确定性门禁已全绿，等待独立只读会话执行 L2 对抗复核签发 approve",
                "actions_taken": actions_taken,
            }

        record_handoff(
            project_root,
            root,
            "quality_review",
            "complete",
            "quality_l2_reviewer",
            {
                "deterministic_gates": "pass",
                "l2_decision": "approve",
                "output_refs": ["review/deterministic-gates.json", "review/l2-adversarial-review.json"],
                "artifact_refs": ["review/deterministic-gates.json", "review/l2-adversarial-review.json"],
                "summary": "全量确定性门禁PASS，独立L2复核approve (0 findings)",
            },
        )
        actions_taken.append("quality_review_completed")
        stages["quality_review"] = "complete"

        # 自动渲染摸鱼绿排版三件套
        render_moyu_green_from_run(root, author=author)
        actions_taken.append("moyu_green_wechat_rendered")

    # 阶段 F：若 final_gate 等待人工终审
    if stages.get("final_gate") != "approved":
        return {
            "ok": True,
            "next_gate": "final_gate",
            "message": "🔍 文字稿、全量门禁与摸鱼绿排版已就绪！请在 DSH 侧边栏预览 `wechat/preview.html` 确认文章。文章内容确定后，按规范进行最后一步配图（用户提供图片执行安全加工与插入），或直接签发终审批准推进交付。",
            "preview_url": str(root / "wechat" / "preview.html"),
            "actions_taken": actions_taken,
        }

    # 阶段 G：final_gate 已批准 -> 推进 delivery 并封存
    if stages.get("delivery") != "complete":
        delivery_dir = root / "delivery" / "art-001"
        delivery_dir.mkdir(parents=True, exist_ok=True)
        (delivery_dir / "delivery.md").write_bytes(draft_path.read_bytes())
        record_handoff(
            project_root,
            root,
            "delivery",
            "complete",
            "controller",
            {
                "artifact_status": "content_ready",
                "output_refs": [
                    "delivery/art-001/delivery.md",
                    "wechat/body.html",
                    "wechat/preview.html",
                    "wechat/delivery.md",
                ],
                "artifact_refs": [
                    "delivery/art-001/delivery.md",
                    "wechat/body.html",
                    "wechat/preview.html",
                    "wechat/delivery.md",
                ],
                "summary": "交付物规整与摸鱼绿排版就绪",
            },
        )
        actions_taken.append("delivery_completed")
        seal_pilot_run(project_root, root, signer=author)
        actions_taken.append("run_sealed")

        return {
            "ok": True,
            "next_gate": "completed_and_sealed",
            "message": "🎉 试点案例已全阶段完成并不可变封存 (SEALED)！",
            "actions_taken": actions_taken,
            "run_root": str(root),
        }

    return {
        "ok": True,
        "next_gate": "completed_and_sealed",
        "message": "当前 run 已处于完全交付与封存状态",
        "actions_taken": actions_taken,
    }


def seal_pilot_run(
    project_root: str | Path,
    run_root: str | Path,
    *,
    signer: str = "controller",
) -> dict[str, Any]:
    """在 validate_run 通过且 artifact_ready=True 后，调用 run_state.seal 写入 SEALED 与 SEALED.manifest.json。"""
    from .run_state import seal

    root = _run_root(project_root, run_root)
    val = validate_run(project_root, root)
    if val["status"] != "PASS" or not val["artifact_ready"]:
        raise PilotContractError(f"cannot_seal_unready_pilot_run:{val['status']}:{','.join(val['errors'])}")
    seal_res = seal(root, identity=signer)
    return {"ok": True, "run_root": str(root), "seal": seal_res}


def record_metric(project_root: str | Path, run_root: str | Path, kind: str, value: Any = None, note: str = "") -> dict[str, Any]:
    root = _run_root(project_root, run_root)
    allowed = {
        "manual_intervention",
        "elapsed_seconds",
        "return_stage",
        "l2_blocker_major",
        "user_edit_count",
        "coordination_seconds",
        "revision_count",
    }
    if kind not in allowed:
        raise PilotContractError(f"unknown_metric_kind:{kind}")
    existing = _json_load(root / "pilot-metrics.json") or {
        "contract_version": CONTRACT_VERSION,
        "run_root": str(root),
        "events": [],
    }
    events = existing.get("events")
    if not isinstance(events, list):
        raise PilotContractError("pilot_metrics_events_invalid")
    events.append({"kind": kind, "value": value, "note": str(note).strip(), "at": _now()})
    existing["events"] = events
    existing["updated_at"] = _now()
    _write_json(root, "pilot-metrics.json", existing, "pilot:metric")
    return {"ok": True, "metric": events[-1], "event_count": len(events), "run_root": str(root)}


def role_brief(role: str) -> dict[str, Any]:
    if role not in ROLE_DEFINITIONS:
        raise PilotContractError(f"unknown_role:{role}")
    return {"ok": True, "role": role, **ROLE_DEFINITIONS[role]}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Article Group Bot pilot contract")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("--project-root", required=True)
    init.add_argument("--case-id", required=True)
    init.add_argument("--topic-label", default="")

    handoff = sub.add_parser("handoff")
    handoff.add_argument("--project-root", required=True)
    handoff.add_argument("--run-root", required=True)
    handoff.add_argument("--stage", required=True)
    handoff.add_argument("--status", required=True)
    handoff.add_argument("--owner", required=True)
    handoff.add_argument("--payload-json", default="{}")

    validate = sub.add_parser("validate")
    validate.add_argument("--project-root", required=True)
    validate.add_argument("--run-root", required=True)

    metric = sub.add_parser("metric")
    metric.add_argument("--project-root", required=True)
    metric.add_argument("--run-root", required=True)
    metric.add_argument("--kind", required=True)
    metric.add_argument("--value", default=None)
    metric.add_argument("--note", default="")

    role = sub.add_parser("role")
    role.add_argument("--role", required=True)

    gates = sub.add_parser("gates")
    gates.add_argument("--project-root", required=True)
    gates.add_argument("--run-root", required=True)
    gates.add_argument("--lenient", action="store_true")
    gates.add_argument("--live-zhuque", action="store_true")

    wechat = sub.add_parser("wechat")
    wechat.add_argument("--project-root", required=True)
    wechat.add_argument("--run-root", required=True)

    seal_cmd = sub.add_parser("seal")
    seal_cmd.add_argument("--project-root", required=True)
    seal_cmd.add_argument("--run-root", required=True)
    seal_cmd.add_argument("--signer", default="controller")

    readiness = sub.add_parser("readiness")
    readiness.add_argument("--project-root", required=True)

    usage = sub.add_parser("usage", help="按 run 归因 DSH 会话 token 用量并落盘 metrics/token-usage.json")
    usage.add_argument("--project-root", required=True)
    usage.add_argument("--run-root", required=True)
    usage.add_argument("--case-id", default=None)
    usage.add_argument("--sessions-dir", default=None)
    usage.add_argument("--no-case-ref", action="store_true", help="只按 run 根路径归因，不按 case id 匹配")

    advance = sub.add_parser("advance")
    advance.add_argument("--project-root", required=True)
    advance.add_argument("--run-root", required=True)
    advance.add_argument("--author", default="controller")

    image = sub.add_parser("image")
    image.add_argument("--project-root", required=True)
    image.add_argument("--run-root", required=True)
    image.add_argument("--source-path", required=True)
    image.add_argument("--slot", default="01_cover")
    image.add_argument("--caption", default="")
    image.add_argument("--insert", action="store_true")
    image.add_argument("--position", default="after_title")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            result = init_run(args.project_root, args.case_id, args.topic_label)
        elif args.command == "handoff":
            result = record_handoff(
                args.project_root,
                args.run_root,
                args.stage,
                args.status,
                args.owner,
                _payload(args.payload_json),
            )
        elif args.command == "validate":
            result = validate_run(args.project_root, args.run_root)
        elif args.command == "metric":
            value: Any = args.value
            if value is not None:
                try:
                    value = float(value)
                    if value.is_integer():
                        value = int(value)
                except ValueError:
                    pass
            result = record_metric(args.project_root, args.run_root, args.kind, value, args.note)
        elif args.command == "advance":
            result = advance_pipeline(args.project_root, args.run_root, author=args.author)
        elif args.command == "image":
            from .image_processor import ingest_user_image, insert_image_to_draft
            root = _run_root(args.project_root, args.run_root)
            ingest_res = ingest_user_image(
                root,
                args.source_path,
                target_slot=args.slot,
                caption=args.caption,
            )
            inserted_res = None
            if args.insert:
                inserted_res = insert_image_to_draft(
                    root,
                    ingest_res["markdown_tag"],
                    position=args.position,
                )
            result = {"ok": True, "image": ingest_res, "insert": inserted_res}
        elif args.command == "gates":
            from .pilot_adapters import run_all_pilot_gates
            root = _run_root(args.project_root, args.run_root)
            gate_res = run_all_pilot_gates(
                root,
                strict_assertions=not args.lenient,
                execute_live_zhuque=args.live_zhuque,
            )
            _refresh_run_record(root)
            result = {"ok": True, "run_root": str(root), "gates": gate_res}
        elif args.command == "wechat":
            from .moyu_green_renderer import render_moyu_green_from_run
            root = _run_root(args.project_root, args.run_root)
            wx_res = render_moyu_green_from_run(root)
            _refresh_run_record(root)
            result = {"ok": True, "run_root": str(root), "wechat": wx_res}
        elif args.command == "seal":
            result = seal_pilot_run(args.project_root, args.run_root, signer=args.signer)
        elif args.command == "readiness":
            from .pilot_extensions import evaluate_pilot_readiness
            result = {"ok": True, **evaluate_pilot_readiness(args.project_root)}
        elif args.command == "usage":
            from .pilot_token_usage import record_run_token_usage
            result = record_run_token_usage(
                args.project_root,
                args.run_root,
                case_id=args.case_id,
                include_case_ref=not args.no_case_ref,
                sessions_dir=args.sessions_dir,
            )
        else:
            result = role_brief(args.role)
    except (PilotContractError, ValueError, OSError, UnicodeError) as exc:
        result = {"ok": False, "error": str(exc)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
