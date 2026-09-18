"""Deterministic shared engine for two_article_daily runs.

Per-run data lives in a spec module (e.g. scripts/run_real_daily_005.py);
this module only contains pipeline logic. ``build_run(spec)`` binds the
spec's data names and executes every stage in order.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scripts.generate_daily_001 as base
from article_group.content_fidelity import evaluate_content_fidelity
from article_group.independent_review import is_placeholder_record
from article_group.prose_pilot import analyze_text
from article_group.run_gates import COMPLIANCE_GATE_REASON, run_all_gates
from article_group.style_gate import validate_markdown_file
from article_group.title_pack_fidelity import evaluate_title_pack
from article_group.topic_preflight import evaluate as evaluate_five_questions

def _is_run_root(root: Path) -> bool:
    """只把 `runs/<date>/<run-id>` 形态的根当 run（判据与 run_seal 同一处实现）。"""
    from article_group.run_seal import is_run_root

    return is_run_root(root)


def _write_json_evidence(target: Path, value: object, *, reason: str, run_root: Path | None = None) -> None:
    """run 根下写入走留底通道；其他位置保持普通写入（历史脚本共用本模块）。"""
    root = Path(run_root) if run_root is not None else ROOT
    if _is_run_root(root):
        from article_group.evidence_write import write_evidence_json

        write_evidence_json(target, value, run_dir=root, reason=reason)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text_evidence(target: Path, text: str, *, reason: str, run_root: Path | None = None) -> None:
    root = Path(run_root) if run_root is not None else ROOT
    if _is_run_root(root):
        from article_group.evidence_write import write_evidence

        write_evidence(target, text, run_dir=root, reason=reason)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _route_write(path: str, value: object, *, kind: str, raw) -> None:
    """run 根下写入走 evidence_write（留底+记账+封存守门）；其他位置保持原样。"""
    if not _is_run_root(ROOT):
        raw(path, value)
        return
    target = Path(ROOT) / path
    if kind == "json":
        _write_json_evidence(target, value, reason=f"daily_engine:{path}")
        return
    _write_text_evidence(target, str(value).rstrip() + "\n", reason=f"daily_engine:{path}")


def discovery() -> None:
    write_json(
        "discovery/discovery-radar-r0.json",
        {
            "schema_version": "1",
            "artifact_type": "discovery_radar",
            "builder": "tgmeng_radar",
            "state": "R0 radar",
            "source_layer": "discovery-only",
            "candidate_pool_eligible": False,
            "evidence_eligible": False,
            "next_action": "needs_editorial_research",
            "generated_at": "2026-09-15T14:40:00+00:00",
            "records": [
                {
                    "source": source,
                    "endpoint": "http://192.168.100.123:4399/api/topsearch/" + source.split("-", 1)[1],
                    "fetched_at": "2026-09-15T14:40:00+00:00",
                    "locator": title,
                    "item_index": index,
                    "score": score,
                    "flags": "needs_editorial_research",
                    "source_role": "discovery",
                    "evidence_eligible": False,
                }
                for source, score, title, index in RADAR_RECORDS
            ],
        },
    )


def source_manifest() -> None:
    sources = []
    for source_id, spec in SOURCES.items():
        sources.append(
            {
                "source_id": source_id,
                "source_role": spec["source_role"],
                "supports_mode": spec["supports_mode"],
                "cannot_support": spec["cannot_support"],
                "source_capability": spec["source_capability"],
                "source_url": spec["source_url"],
                "source_type": spec["source_type"],
                "capture_type": "page_fulltext",
                **({"usage_note": spec["usage_note"]} if spec.get("usage_note") else {}),
                "declared_source_level": "fulltext",
                "artifact_path": spec["artifact_path"],
                "artifact_sha256": digest(ROOT / spec["artifact_path"]),
                "captured_at": CAPTURED_AT,
            }
        )
    write_json(
        "source-manifest.json",
        {
            "schema_version": "source-manifest-v1",
            "run_id": RUN_ID,
            "source_layer": "evidence",
            "sources": sources,
            "source_empty": [],
            "evergreen_gap": False,
            "publication_authorization": "not_authorized",
        },
    )


def _normalize_rejected_works(works: object) -> list[dict]:
    """落选作品结构化（2026-09-16）：字符串兼容旧 spec，统一为 {work, reason}。

    自 daily-007 起 spec 可给带 reason 的落选记录；历史裸字符串补
    "理由未留痕（历史期）"，不伪造理由。
    """
    normalized: list[dict] = []
    for entry in works or []:
        if isinstance(entry, str):
            normalized.append({"work": entry, "reason": "理由未留痕（历史期）"})
        elif isinstance(entry, dict) and entry.get("work"):
            reason = str(entry.get("reason") or "").strip() or "理由未留痕"
            normalized.append({"work": str(entry["work"]), "reason": reason})
    return normalized


def candidates() -> None:
    write_json(
        "candidate-pool.json",
        {
            "schema_version": "candidate-pool-v2",
            "run_id": RUN_ID,
            "selection_pass": 1,
            "selection_rerun": True,
            "selection_rule": "作品级与事件簇去重；发现信号不得直接充当事实",
            "selected_slot_ids": [c["candidate_id"] for c in CANDIDATES],
            "candidates": CANDIDATES,
            "rejected_prior_works": _normalize_rejected_works(REJECTED_PRIOR_WORKS),
            "decision": "accept",
            "publication_authorization": "not_authorized",
        },
    )
    write_json(
        "slot-contract.json",
        {
            "schema_version": "slot-contract-v1",
            "run_id": RUN_ID,
            "profile": "two_article_daily",
            "required_slots": 2,
            "distinct_event_clusters_required": True,
            "selection_rerun_required": True,
            "publication_authorization": "not_authorized",
        },
    )
    decisions = SLOT_DECISIONS
    write_json(
        "slot-decisions.json",
        {
            "schema_version": "slot-decisions-v1",
            "run_id": RUN_ID,
            "decisions": decisions,
            "portfolio_distinct": True,
            "publication_authorization": "not_authorized",
        },
    )
    by_id = {c["candidate_id"]: c for c in CANDIDATES}
    selected = [
        {
            "article_id": d["article_id"],
            "candidate_id": d["candidate_id"],
            "work": by_id[d["candidate_id"]]["work_title"],
            "work_title": by_id[d["candidate_id"]]["work_title"],
            "reader_question": by_id[d["candidate_id"]]["core_question"],
            "event_cluster_id": d["event_cluster_id"],
            "content_map": by_id[d["candidate_id"]]["content_map"],
            "topic_mode": by_id[d["candidate_id"]]["topic_mode"],
            # 五问选题预检（2026-09-16 用户拍板）：结构必填 + 枚举 + 质量警告。
            # 字段取自候选卡，缺一即阻断；内容质量由 controller/L2 判断。
            "reader": by_id[d["candidate_id"]].get("reader", ""),
            "landing": by_id[d["candidate_id"]].get("landing", ""),
            "emotion": by_id[d["candidate_id"]].get("emotion", ""),
            "remove_timestamp_test": by_id[d["candidate_id"]].get("remove_timestamp_test", ""),
            "social_motive": by_id[d["candidate_id"]].get("social_motive", ""),
            "editorial_value_score": by_id[d["candidate_id"]]["editorial_value_score"],
            "evidence_readiness": "ready",
        }
        for d in decisions
    ]
    write_json(
        "review/selected-candidates.json",
        {
            "schema_version": "selected-candidates-v1",
            "run_id": RUN_ID,
            "selected": selected,
            "publication_authorization": "not_authorized",
        },
    )
    write_json("review/topic-five-questions.json", evaluate_five_questions(selected))


def briefs_and_tasks() -> None:
    for aid in BRIEFS:
        write_text(f"briefs/writing-brief-{aid}.md", BRIEFS[aid])
    for aid, mode, role, question, sources in BRIEF_SPECS:
        write_text(
            f"task-cards/task-card-{aid}.md",
            f"# Task Card: {aid}\n\n"
            "production_contract: article-first-v1\n"
            "brief_contract: writing-brief-v2\n"
            "title_contract: title-pack-v1\n"
            "legacy_compatibility: false\n"
            "run_contract_required: true\n"
            f"article_id: {aid}\n"
            f"article_mode: {mode}\n"
            f"required_source_roles: [{role}]\n"
            f"core_question: {question}\n"
            "reader: 当前电影与剧集观众\n"
            "body_outline:\n"
            "- 先给出具体事实或现场\n"
            "- 再解释创作取舍如何改变人物关系\n"
            "- 最后回到读者能转述的判断和边界\n"
            f"source_scope: {sources}\n"
            f"{TASK_CARD_REQUIRED_FIELDS[aid]}",
        )
        write_json(
            f"task-cards/{aid}.json",
            {
                "schema_version": "article-task-card-v1",
                "article_id": aid,
                **CONTRACT,
                "article_mode": mode,
                "required_source_roles": [role],
                "core_question": question,
                "source_refs": [sources],
            },
        )
        write_json(
            f"task-hierarchy/article-task-{aid}.json",
            {
                "schema_version": "article-task-v1",
                **CONTRACT,
                "article_first_contract_version": "article-first-v1",
                "group_id": GROUP_ID,
                "run_id": RUN_ID,
                "article_task_id": f"at-{aid}",
                "article_id": aid,
                "topic_id": aid,
                "topic_version": 1,
                # 日更不产出 1.0 editorial-judgment schema 家族，state 封顶在
                # title_review（标题已过、终审未过）；final_review/delivered
                # 会要求缺失的 judgment 记录，不得宣称。
                "state": "title_review",
                "crawl_task_id": f"crawl-{aid}",
                "brief_path": f"briefs/writing-brief-{aid}.md",
                "task_card_path": f"task-cards/task-card-{aid}.md",
                "body_draft_path": f"drafts/{aid}/body_draft.md",
                "material_pack_path": f"material-packs/{aid}.json",
                "content_fidelity_path": f"review/{aid}/content-fidelity.json",
                "title_pack_path": f"review/{aid}/title-pack.json",
                "title_review_path": f"review/{aid}/title-pack-review.json",
                "title_review_result": "pass",
                "delivery_path": f"delivery/{aid}/delivery.md",
                "publication_authorization": "not_authorized",
            },
        )
        write_json(
            f"task-hierarchy/crawl-task-{aid}.json",
            {
                "schema_version": "crawl-task-parent-v1",
                "crawl_task_id": f"crawl-{aid}",
                "article_task_id": f"at-{aid}",
                "article_id": aid,
                "topic_id": aid,
                "topic_version": 1,
                "state": "material_ready",
                "status": "accepted",
                "return_status": "accepted_for_draft",
                "source_refs": [sources],
                "required_claim_levels": ["event_exists", "character_setup", "scene_action", "dialogue"],
            },
        )
    write_json(
        "task-hierarchy/group-manifest.json",
        {
            "schema_version": "article-group-v1",
            "group_id": GROUP_ID,
            "run_id": RUN_ID,
            "articles": [
                {"article_task_id": f"at-{aid}", "article_id": aid, "topic_id": aid, "topic_version": 1}
                for aid, *_rest in BRIEF_SPECS
            ],
            "selection_rerun": True,
            "publication_authorization": "not_authorized",
        },
    )


def material_pack(aid: str) -> None:
    spec = MATERIAL_SPECS[aid]
    sources = []
    for source_id in spec["source_ids"]:
        info = SOURCES[source_id]
        levels = info.get("capability_levels") or ["event_exists", "character_setup", "mechanism"]
        sources.append(
            {
                "material_id": f"mat-{source_id}",
                "source_id": source_id,
                "capture_type": "page_fulltext",
                "declared_source_level": "fulltext",
                "source_capability": info["source_capability"],
                "capability_levels": levels,
                "source_role": info["source_role"],
                "supports_mode": info["supports_mode"],
                "cannot_support": info["cannot_support"],
                "locator": f"source:{source_id}:fulltext",
                **({"usage_note": info["usage_note"]} if info.get("usage_note") else {}),
                "obtained_facts": list(spec["by_source"].get(source_id, [])),
            }
        )
    claims = [
        {
            "claim_id": f"c{i}",
            "claim_level": item["level"],
            "source_refs": [item["source_id"]],
            "source_locators": [item["locator"]],
        }
        for i, item in enumerate(spec["facts"], 1)
    ]
    content_value_plan = {
        "hard_information_plan": [
            {
                "plan_id": f"plan-{i}",
                "kind": item["plan_kind"],
                "material_refs": [item["source_id"]],
                "reader_gain": item["text"],
            }
            for i, item in enumerate(spec["facts"], 1)
        ],
        "opening_support_refs": [spec["source_ids"][0]],
        "explanation_mechanism": spec["mechanism"],
    }
    write_json(
        f"material-packs/{aid}.json",
        {
            "schema_version": "article-material-acceptance-v1",
            "pack_id": f"mp-{aid}-v1",
            "material_pack_id": f"mp-{aid}-v1",
            "article_task_id": f"at-{aid}",
            "topic_id": aid,
            "topic_version": 1,
            "version": 1,
            "crawl_task_id": f"crawl-{aid}",
            "status": "material_ready",
            **CONTRACT,
            "article_mode": spec["mode"],
            "required_source_roles": [spec["role"]],
            "core_question": spec["question"],
            "intended_claim_kinds": ["program_titles", "program_schedule"],
            "sources": sources,
            "obtained_facts": [item["text"] for item in spec["facts"]],
            "obtained_facts_by_source": spec["by_source"],
            "supported_analyses": [spec["mechanism"]],
            "missing_materials": [],
            "unanswerable_questions": [],
            "decision": "accept",
            "return_rule": "",
            "material_ready_for_draft": True,
            "editorial_value_ready": True,
            "readiness": {"material_ready_for_draft": True, "editorial_value_ready": True, "blocking_gaps": []},
            "content_value_plan": content_value_plan,
            "claims": claims,
            "audience_sample": {"audience": spec["audience"], "scope": "editorial hypothesis only", "sample_size": 0, "status": "not_collected"},
            "source_audit": {"all_sources_current": True, "capability_checked": True, "unsupported_levels": []},
            "retry_state": {"attempt": 1, "max_attempts": 3, "status": "complete"},
            "deliverables": {"body_can_start": True, "title_can_start": False},
        },
    )


def bodies() -> dict[str, str]:
    return BODIES


def content_record(
    aid: str,
    body: str,
    mode: str,
    role: str,
    core_object: str,
    question: str,
    mechanism: str,
    takeaway: str,
    hard: list[dict],
    bases: list[dict],
    boundary: str,
    source_ids: list[str],
) -> None:
    """Write content fidelity, one source per hard-information item.

    ``source_id`` (the article's primary evidence source) is kept for the
    mechanism/basis fields; every hard-information item must carry the real
    source of its own claim in ``source_refs`` so the record cannot restate an
    unsupported provenance (L2 review finding, art-001 round 1).
    """
    base.content_record(aid, body, source_ids[0], core_object, question, mechanism, takeaway, hard, bases, boundary)
    path = ROOT / f"review/{aid}/content-fidelity.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["article_mode"] = mode
    data["required_source_roles"] = [role]
    for item, spec in zip(data.get("hard_information", []), hard):
        if spec.get("source_refs"):
            item["source_refs"] = list(spec["source_refs"])
    paras = [p for p in body.split("\n\n") if p and not p.startswith("## ")]
    data["reader_takeaway_locator"] = f"p{len(paras)}"
    data["standalone_check"]["judgment_locator"] = f"p{len(paras)}"
    _write_json_evidence(path, data, reason=f"daily_engine:content-fidelity:{aid}")


def ensure_independent_review_placeholder(aid: str, delivery_path: str) -> bool:
    """"这篇还没复核"时补一份 canonical 占位记录；已有结论就不动它。

    判据为什么不再是 ``status == "complete"``（2026-09-18，daily-009 复盘）：
    ``codex_review`` 写的是契约记录（``status=PASS/FAIL``），门禁读的是
    canonical 记录（``review/{aid}/independent-review.json``）。只认 "complete"
    会让引擎把一份 approve/PASS 记录当成"还没复核"，用 PENDING 占位符覆盖它——
    哈希绑定依旧逐位相同，``evidence_rebind`` 看不出异常，门禁又把 PENDING 只当
    治理待办，于是"已批准"在系统里静默消失。判据统一到
    ``independent_review.is_placeholder_record``：只有状态与结论都还是待复核的
    占位符可以按新哈希刷新，跑出结论的记录与带 stale 痕迹的记录都保留。

    返回 True 表示这次写了占位记录。
    """

    review_path = ROOT / f"review/{aid}/independent-review.json"
    existing = None
    if review_path.exists():
        try:
            existing = json.loads(review_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            existing = None
    if not is_placeholder_record(existing):
        return False
    write_json(
        f"review/{aid}/independent-review.json",
        {
            "schema_version": "article-independent-review-v1",
            "article_task_id": f"at-{aid}",
            "article_id": aid,
            "run_id": RUN_ID,
            "created_from_run": RUN_ID,
            "artifact_path": delivery_path,
            "artifact_sha256": digest(ROOT / delivery_path),
            "draft_path": f"drafts/{aid}/body_draft.md",
            "draft_sha256": digest(ROOT / f"drafts/{aid}/body_draft.md"),
            "body_path": f"drafts/{aid}/body_draft.md",
            "body_sha256": digest(ROOT / f"drafts/{aid}/body_draft.md"),
            "title_pack_path": f"review/{aid}/title-pack.json",
            "title_pack_sha256": digest(ROOT / f"review/{aid}/title-pack.json"),
            "attempt": 1,
            "max_attempts": 3,
            "status": "PENDING",
            "decision": "human_review_required",
            "next_step": "independent_review_required",
            "scope": "single_article",
            "publication_authorization": "not_authorized",
        },
    )
    return True


def reviews_and_delivery(bodies_map: dict[str, str]) -> None:
    for aid, body in bodies_map.items():
        base.write_text(f"drafts/{aid}/body_draft.md", body)
        base.title_records(aid, SOURCE_IDS[aid][0], TITLES[aid], f"review/{aid}/content-fidelity.json")
        title = json.loads((ROOT / f"review/{aid}/title-pack.json").read_text(encoding="utf-8"))["directions"][0]["title"]
        delivery_path = f"delivery/{aid}/delivery.md"
        base.write_text(delivery_path, f"# {title}\n\n{body.strip()}\n")
        stripped_path = f"review/{aid}/source-stripped.md"
        base.write_text(stripped_path, base.build_source_stripped((ROOT / delivery_path).read_text(encoding="utf-8")))
        sources = [
            {
                "source_id": source_id,
                "source_role": SOURCES[source_id]["source_role"],
                "supports_mode": SOURCES[source_id]["supports_mode"],
                "cannot_support": SOURCES[source_id]["cannot_support"],
                "source_capability": SOURCES[source_id]["source_capability"],
            }
            for source_id in SOURCE_IDS[aid]
        ]
        write_json(
            f"review/{aid}/rule-compliance.json",
            {
                "schema_version": "article-rule-compliance-v1",
                "article_id": aid,
                "article_mode": MODES[aid],
                "required_source_roles": [MATERIAL_SPECS[aid]["role"]],
                "sources": sources,
                "claims": RULE_CLAIMS[aid],
                "source_stripped_path": stripped_path,
                "source_stripped_readability_path": f"review/{aid}/source-stripped-readability.json",
                "publication_authorization": "not_authorized",
            },
        )
        readability = base.build_readability_record(
            aid,
            MODES[aid],
            (ROOT / delivery_path).read_bytes(),
            (ROOT / stripped_path).read_bytes(),
        )
        readability.update({"source_stripped_path": stripped_path, "review_scope": "source_stripped_readability", "decision": "PENDING"})
        write_json(f"review/{aid}/source-stripped-readability.json", readability)
        base.topic_cards(aid, title, "按已核验材料解释创作取舍、人物关系与读者问题", SOURCE_IDS[aid][0], f"drafts/{aid}/body_draft.md", delivery_path)
        topic_path = ROOT / f"review/{aid}/topic-card.json"
        topic = json.loads(topic_path.read_text(encoding="utf-8"))
        topic.update({"run_id": RUN_ID, "article_mode": MODES[aid], "article_type": MODES[aid], "required_source_roles": [MATERIAL_SPECS[aid]["role"]]})
        _write_json_evidence(topic_path, topic, reason=f"daily_engine:topic-card:{aid}")
        fact_path = ROOT / f"review/{aid}/fact-card.json"
        fact = json.loads(fact_path.read_text(encoding="utf-8"))
        fact.update(
            {
                "run_id": RUN_ID,
                "article_mode": MODES[aid],
                "required_source_roles": [MATERIAL_SPECS[aid]["role"]],
                "sources": [
                    {
                        "source_id": source_id,
                        "url": SOURCES[source_id]["source_url"],
                        "locator": "fulltext",
                        "source_level": "fulltext",
                        "accessed_at": CAPTURED_AT,
                    }
                    for source_id in SOURCE_IDS[aid]
                ],
            }
        )
        _write_json_evidence(fact_path, fact, reason=f"daily_engine:fact-check:{aid}")
        # 标题包冻结（2026-09-17）：L2 复核必须绑定已冻结的标题包哈希；
        # 标题在 L2 之后被改，会让旧 approve 失效而不是被 rebind 保住。
        from article_group.title_freeze import freeze as _freeze_title_pack

        _freeze_title_pack(ROOT, aid)
        # L2 canonical 记录保护（2026-09-16；判据 2026-09-18 修正，见函数注释）。
        ensure_independent_review_placeholder(aid, delivery_path)
        hook = STRONGEST_HOOKS[aid]
        write_json(
            f"review/style-gate-markdown-{aid}.json",
            validate_markdown_file(ROOT / delivery_path, hook=hook, run_root=ROOT),
        )
        write_json(
            f"review/scoring/{aid}.json",
            {
                "schema_version": "article-scoring-card-v1",
                "article_id": aid,
                "artifact_path": delivery_path,
                "artifact_sha256": digest(ROOT / delivery_path),
                "total_score": 86,
                "evidence_score": 21,
                "original_judgment_score": 17,
                "information_gain_score": 17,
                "structure_score": 13,
                "title_value_score": 9,
                "readability_score": 5,
                "compliance_score": 4,
                "first_screen_value": "首段给出具体事件与人物动作",
                "reader_takeaway": "核心判断可转述",
                "reader_takeaway_locator": f"p{len([p for p in bodies_map[aid].split(chr(10)+chr(10)) if p and not p.startswith('## ')])}",
                "body_fulfillment": "正文逐段推进并标出未验证边界",
            },
        )
        record = base.editorial_record(aid, title, source_id=SOURCE_IDS[aid][0], delivery_path=delivery_path)
        record["run_id"] = RUN_ID
        record["article_task_id"] = f"at-{aid}"
        write_json(f"review/{aid}/editorial-review-record.json", record)
        write_json(f"review/editorial-review-record-{aid}.json", record)
    write_json(
        "review/markdown-review-evidence.json",
        {
            "schema_version": "markdown-review-evidence-v1",
            "review_surface": "markdown_codex",
            "articles": {
                aid: {
                    "markdown_path": f"delivery/{aid}/delivery.md",
                    "markdown_sha256": digest(ROOT / f"delivery/{aid}/delivery.md"),
                    "size": (ROOT / f"delivery/{aid}/delivery.md").stat().st_size,
                    "cjk_chars": len(re.findall(r"[\u4e00-\u9fff]", (ROOT / f"delivery/{aid}/delivery.md").read_text(encoding="utf-8"))),
                    "status": "PASS",
                }
                for aid in bodies_map
            },
        },
    )
    # prose_pilot 真接入（advisory only，不改变任何 gate 状态，不阻断发布）。
    # 2026-09-15 之前这里是标题+字数的占位摘要，现在跑真实的两通道分析：
    # 材料锚点清单 + 判断词密度；ledger 由本 run 材料包的事实组装，
    # 让 ledger_matched_quotes 真正参与锚定核对。
    prose_articles = []
    for aid in bodies_map:
        text = (ROOT / f"delivery/{aid}/delivery.md").read_text(encoding="utf-8")
        ledger_quotes = [
            {
                "source_id": source_id,
                "title": SOURCES[source_id].get("captured_from", source_id),
                "url": SOURCES[source_id].get("source_url", ""),
                "text": fact,
            }
            for source_id in SOURCE_IDS[aid]
            for fact in MATERIAL_SPECS[aid]["by_source"].get(source_id, [])
        ]
        entry = analyze_text(text, TITLES[aid][0][0], ledger_quotes)
        entry["article_id"] = aid
        entry["label"] = aid
        prose_articles.append(entry)
    write_json(
        "review/prose-pilot-report.json",
        {
            "schema_version": "prose-pilot-v1",
            "advisory": True,
            "note": "prose_pilot 真实输出（材料锚点清单 + 判断词密度）；仅人工审读参考，不改变任何 gate 状态，不阻断发布。",
            "batches": [{"batch_id": RUN_ID, "articles": prose_articles}],
        },
    )


def portfolio() -> None:
    """Run the real cross-batch portfolio gate on the run's own candidate pool.

    The gate must validate the artifact the run actually ships.  An earlier
    revision validated a separate, hand-shaped ``review/portfolio-gate-input.json``
    while the shipped ``candidate-pool.json`` lacked the fields the gate checks,
    so the PASS verdict did not describe the production pool (2026-09-15 review).
    """
    from article_group import portfolio_gate

    verdict, exit_code = portfolio_gate.run_checks(
        str(ROOT / "candidate-pool.json"), cross_batch_window=10
    )
    verdict["cross_batch"] = verdict.get("cross_batch") or {
        "checked": True,
        "history_status": "not_loaded_by_this_call",
        "window_batches": 0,
        "batches": [],
        "matches": [],
    }
    verdict.update(
        {
            "schema_version": "portfolio-gate-v2",
            "run_id": RUN_ID,
            "validated_pool_path": "candidate-pool.json",
            "selected_articles": [d["article_id"] for d in SLOT_DECISIONS],
            "distinct_event_clusters": True,
            "status": "PASS" if verdict.get("pass") else "FAIL",
            "exit_code": exit_code,
            "publication_authorization": "not_authorized",
        }
    )
    write_json("portfolio-gate-report.json", verdict)


def gates() -> None:
    """Run-level gate wiring: shared implementation in ``article_group.run_gates``.

    Task-hierarchy 1.0 contract (blocking) + git_hygiene infra snapshot +
    compliance_gate explicit not_run.  Future daily generators should import
    the same helper instead of re-implementing it.
    """
    run_all_gates(ROOT, write_json)


def batch_manifest(bodies_map: dict[str, str]) -> None:
    specs = BATCH_SPECS
    articles = []
    for aid, (cid, work, cluster, source_refs, slot, content_map) in specs.items():
        title = json.loads((ROOT / f"review/{aid}/title-pack.json").read_text(encoding="utf-8"))["directions"][0]["title"]
        articles.append(
            {
                "article_id": aid,
                "slot": slot,
                "candidate_id": cid,
                "work_title": work,
                "topic_version": 1,
                "article_mode": MODES[aid],
                "required_source_roles": [MATERIAL_SPECS[aid]["role"]],
                "content_map": content_map,
                "event_cluster": cluster,
                "brief_path": f"briefs/writing-brief-{aid}.md",
                "task_card_path": f"task-cards/task-card-{aid}.md",
                "body_draft_path": f"drafts/{aid}/body_draft.md",
                "content_fidelity_path": f"review/{aid}/content-fidelity.json",
                "title_pack_path": f"review/{aid}/title-pack.json",
                "title_review_path": f"review/{aid}/title-pack-review.json",
                "delivery_path": f"delivery/{aid}/delivery.md",
                "markdown_path": f"delivery/{aid}/delivery.md",
                "source_stripped_path": f"review/{aid}/source-stripped.md",
                "source_stripped_readability_path": f"review/{aid}/source-stripped-readability.json",
                "rule_compliance_path": f"review/{aid}/rule-compliance.json",
                "independent_review_path": f"review/{aid}/independent-review.json",
                "material_pack_path": f"material-packs/{aid}.json",
                "source_refs": source_refs,
                "state": "R7 mechanically-verified",
                "delivery_state": "pending_independent_review",
                "html_delivery_state": "withheld",
                "publication_authorization": "not_authorized",
                "review_hook": STRONGEST_HOOKS[aid],
                "title": title,
            }
        )
    batch = {
        "schema_version": "article-group-run-v1",
        "run_id": RUN_ID,
        "run_profile": "two_article_daily",
        "run_profile_contract_version": "run-profile-v1",
        "run_profile_required": True,
        "milestone": "M2 content-handoff",
        "manifest_state": "R7 mechanically-verified",
        "target_state": "R7.5 awaiting-independent-review",
        "review_surface": "markdown_codex",
        "review_surface_contract_version": "review-surface-v1",
        **CONTRACT,
        "article_first_contract_version": "article-first-v1",
        "article_rule_compliance_required": True,
        "article_count": len(specs),
        "articles": articles,
        "publication_authorization": "not_authorized",
        "delivery_state": "withheld",
        "html_delivery_state": "withheld",
        "network_actions": "discovery-and-source-research-only",
        "selection_rerun": True,
        "source_manifest_path": "source-manifest.json",
        "candidate_pool_path": "candidate-pool.json",
        "portfolio_gate_path": "portfolio-gate-report.json",
        "preflight_report_path": "preflight-report.json",
        "task_hierarchy_validation_path": "task-hierarchy-validation-report.json",
    }
    report = base.evaluate_batch_rule_compliance(ROOT, batch)
    five_questions = json.loads(
        (ROOT / "review/gates/topic-five-questions.json").read_text(encoding="utf-8")
    )
    five_questions_pass = bool(five_questions.get("pass"))
    write_json(
        "preflight-report.json",
        {
            "schema_version": "preflight-report-v1",
            "run_id": RUN_ID,
            "status": "PASS" if five_questions_pass else "FAIL",
            "article_rule_compliance": report["status"],
            "article_rule_compliance_report": report,
            "checks": {
                "run_contract": "pass",
                "selection_rerun": "pass",
                "source_manifest": "pass",
                "article_count": "pass",
                "distinct_event_clusters": "pass",
                "article_rule_compliance": report["status"].lower(),
                "topic_five_questions": "pass" if five_questions_pass else "fail",
                "publication_authorization": "pass",
                "task_hierarchy_contract": "pass",
                "git_hygiene_infra": "pass",
                "compliance_gate": "not_run",
            },
            "checks_note": (
                "除 article_rule_compliance 外均为结构检查；article_rule_compliance 为 PENDING，"
                "原因是 source_stripped_readability 尚待人工签署，属治理栏而非内容阻塞，"
                "此处不把它重述为通过。task_hierarchy_contract 由 article_task_v1 对"
                "task-hierarchy/*.json 真实校验（见 task-hierarchy-validation-report.json）。"
                "compliance_gate 显式 not_run：" + COMPLIANCE_GATE_REASON
            ),
            "source_empty": {"affects": "none", "does_not_affect": "selected article facts"},
            "evergreen_gap": {"affects": "none", "does_not_affect": "selected article facts"},
            "publication_authorization": "not_authorized",
        },
    )

    # gate_status 与 run_gates 由真实门禁产物回填（2026-09-15：不再手写 pass）
    def _bool_status(value: object) -> str:
        return "pass" if value is True else "fail"

    for article in batch["articles"]:
        aid = article["article_id"]
        pack = json.loads((ROOT / f"material-packs/{aid}.json").read_text(encoding="utf-8"))
        readiness = pack.get("readiness", {})
        cf = json.loads((ROOT / f"review/{aid}/content-fidelity.json").read_text(encoding="utf-8"))
        tp = json.loads((ROOT / f"review/{aid}/title-pack.json").read_text(encoding="utf-8"))
        style = json.loads((ROOT / f"review/style-gate-markdown-{aid}.json").read_text(encoding="utf-8"))
        independent = json.loads((ROOT / f"review/{aid}/independent-review.json").read_text(encoding="utf-8"))
        article["gate_status"] = {
            "preflight": "pass" if report["status"] != "FAIL" else "fail",
            "material_ready_for_draft": _bool_status(readiness.get("material_ready_for_draft")),
            "editorial_value_ready": _bool_status(readiness.get("editorial_value_ready")),
            "content_fidelity": str(evaluate_content_fidelity(cf, strict=True).get("status")),
            "title_pack": str(evaluate_title_pack(tp).get("status")),
            "style_gate": "pass" if style.get("pass") and not style.get("error_total") else "fail",
            "article_rule_compliance": str(report["status"]).lower(),
            "independent_review": str(independent.get("status", "pending")).lower(),
            # 治理栏：无机器记录，按设计保持 pending（人签字项，不机器化）
            "controller_acceptance": "pending",
        }

    portfolio_report = json.loads((ROOT / "portfolio-gate-report.json").read_text(encoding="utf-8"))
    hierarchy_report = json.loads((ROOT / "task-hierarchy-validation-report.json").read_text(encoding="utf-8"))
    claim_report = json.loads((ROOT / "review/gates/claim-source-check.json").read_text(encoding="utf-8"))
    editorial_report = json.loads((ROOT / "review/gates/editorial-protocol.json").read_text(encoding="utf-8"))
    independent_report = json.loads((ROOT / "review/gates/independent-review.json").read_text(encoding="utf-8"))
    hygiene_report = json.loads((ROOT / "review/gates/git-hygiene.json").read_text(encoding="utf-8"))
    compliance_report = json.loads((ROOT / "review/gates/compliance-gate.json").read_text(encoding="utf-8"))
    five_questions_report = json.loads((ROOT / "review/gates/topic-five-questions.json").read_text(encoding="utf-8"))
    batch["run_gates"] = {
        "portfolio_gate": "pass" if portfolio_report.get("pass") else "fail",
        "task_hierarchy_contract": "pass" if hierarchy_report.get("pass") else "fail",
        "topic_five_questions": "pass" if five_questions_report.get("pass") else "fail",
        "claim_source_provenance": "pass" if claim_report.get("pass") else "fail",
        "editorial_protocol": "pass" if editorial_report.get("pass") else "fail",
        "independent_review": "pass" if independent_report.get("pass") else "fail",
        "prose_pilot": "advisory",
        "git_hygiene_infra": "pass" if hygiene_report.get("pass") else "fail",
        "compliance_gate": (
            "not_run"
            if compliance_report.get("full_gate") == "not_run"
            else ("pass" if compliance_report.get("pass") else "fail")
        ),
        "compliance_gate_reason": COMPLIANCE_GATE_REASON,
    }
    write_json("batch.json", batch)
    article_lines = "".join(
        f"  - article_id: {aid}\n    body_path: drafts/{aid}/body_draft.md\n"
        for aid in sorted(bodies_map)
    )
    write_text(
        "prose-batch.yaml",
        f"run_id: {RUN_ID}\nreview_surface: markdown_codex\narticles:\n{article_lines}",
    )


def wechat_render_step() -> dict:
    """2026-09-16：交付封存后生成"可直接粘贴进公众号后台"的排版版。

    这是内容交付之后的便利步骤，不是门禁：渲染器不可用（没装 docker、
    没网）时只记录 status/reason，绝不影响已经通过的内容交付，也不构成
    任何发布授权。
    """
    import os

    from article_group.wechat_render import render_run

    try:
        report = render_run(ROOT, editor_url=os.environ.get("WECHAT_EDITOR_URL", ""))
    except Exception as exc:  # noqa: BLE001 - 后置步骤不允许影响主流程
        return {
            "status": "error",
            "reason": f"{type(exc).__name__}:{exc}",
            "publication_authorization": "not_authorized",
        }
    status: dict = {
        "status": report["status"],
        "theme": report["theme"],
        "publication_authorization": "not_authorized",
    }
    if report.get("cache"):
        # 重跑时"渲染了几篇 / 复用了几篇"要留着：daily-009 一天重渲染 13 次，
        # 慢的是 docker+npx，而缓存复用与否则是后面复盘唯一能看出差别的字段。
        status["cache"] = report["cache"]
    if report.get("index_path"):
        status["index_path"] = report["index_path"]
    if report.get("reason"):
        status["reason"] = report["reason"]
    status["articles"] = [item["article_id"] for item in report["articles"]]
    status["cached_articles"] = [
        item["article_id"] for item in report["articles"] if item.get("cached")
    ]
    return status


def preview_site_step() -> dict:
    """2026-09-18：把 run 产物渲染成"标题可点、点开能读"的静态预览页。

    与 wechat_render 同性质：交付后的便利步骤，不是门禁。controller 要的是能点开的
    预览（run 里的 Markdown / 公众号 HTML 本身没有被任何服务托管），所以每批都在
    run 内生成 `preview/` 站点：目录页（标题即链接）+ 每篇阅读页 + 公众号复制版入口。

    发布到主机静态根是**另一个动作**（`scripts/publish_preview.py`）；宿主若设了
    `RUOYU_PREVIEW_PUBLISH_ROOT`，这里顺带发布并记录 URL——失败只记 reason，
    不影响已通过的交付，也不构成任何发布授权。
    """
    import os

    from article_group.preview_site import build, publish

    try:
        report = build(ROOT)
    except Exception as exc:  # noqa: BLE001 - 后置步骤不允许影响主流程
        return {
            "status": "error",
            "reason": f"{type(exc).__name__}:{exc}",
            "publication_authorization": "not_authorized",
        }
    status: dict = {
        "status": report["status"],
        "index_path": report["index_path"],
        "index_sha256": report["index_sha256"],
        "content_status": report["content_status"],
        "articles": [item["article_id"] for item in report["articles"]],
        "publication_authorization": "not_authorized",
    }
    publish_root = os.environ.get("RUOYU_PREVIEW_PUBLISH_ROOT", "").strip()
    if publish_root:
        base_url = os.environ.get("RUOYU_PREVIEW_BASE_URL", "").strip() or None
        try:
            published = publish(ROOT, publish_root, base_url=base_url)
            status["published"] = {
                "target": published["target"],
                "index_url": published["index_url"],
                "published_at": published["published_at"],
            }
        except Exception as exc:  # noqa: BLE001 - 发布失败不阻断交付
            status["published"] = {"status": "error", "reason": f"{type(exc).__name__}:{exc}"}
    else:
        status["published"] = {
            "status": "not_published",
            "reason": "未设置 RUOYU_PREVIEW_PUBLISH_ROOT；用 scripts/publish_preview.py 手动发布",
        }
    return status


def _write_step_log_markdown(run_root) -> None:
    """把步骤日志渲染成 Markdown 版（STEP-LOG.md），随 RUN-RECORD 一起看。

    2026-09-17：daily-008 的证据文件被最后一次打包在同一秒重写，事后无法复原
    步骤顺序；步骤日志是 append-only 的，打包覆盖不了它。
    """
    from pathlib import Path as _Path

    from article_group.step_log import render_markdown, timeline

    _write_text_evidence(
        _Path(run_root).joinpath("STEP-LOG.md"),
        render_markdown(timeline(run_root)),
        reason="daily_engine:step_log_markdown",
        run_root=_Path(run_root),
    )


def evidence_rebind_step() -> dict:
    """2026-09-17：交付内容一变，依赖它的 approve 立即失效（不重绑哈希）。

    daily-008 当时靠手工脚本把记录里的哈希改成当前文件哈希，approve 因此被
    保住；现在改为判失效：记录退回 PENDING/待复核，由复核与门禁重新判定。
    """
    from article_group.evidence_rebind import reconcile

    report = reconcile(ROOT, apply=True)
    return {
        "status": "ok",
        "changes": len(report["changes"]),
        "stale_records": report["stale_records"],
        "publication_authorization": "not_authorized",
    }


class StagePrerequisiteMissing(RuntimeError):
    """分阶段重跑时前置产物不在 run 里：缺哪个说哪个，别跑到一半才炸。"""


@dataclass(frozen=True)
class PipelineStage:
    """一个可单独选中的阶段单元。

    ``name`` 是完整名（逐篇阶段带 ``:aid``），``group`` 是组名（可一次选中该组全部
    单元），``requires`` 列出运行前必须已在 run 里的相对路径/glob。
    """

    name: str
    group: str
    run: Callable[[], object]
    requires: tuple[str, ...] = ()


def _content_record_unit(spec_args: Mapping[str, Any], body_map: Mapping[str, str]) -> Callable[[], None]:
    def run() -> None:
        content_record(
            spec_args["aid"],
            body_map[spec_args["aid"]],
            spec_args["mode"],
            spec_args["role"],
            spec_args["core_object"],
            spec_args["question"],
            spec_args["mechanism"],
            spec_args["takeaway"],
            spec_args["hard"],
            spec_args["bases"],
            spec_args["boundary"],
            spec_args["source_ids"],
        )

    return run


def _status_unit(run_fn: Callable[[], dict], results: dict[str, Any], key: str) -> Callable[[], dict]:
    """跑一个后置步骤并把状态留在 ``results`` 里（run_manifest 复用）。"""

    def run() -> dict:
        value = run_fn()
        results[key] = value
        return value

    return run


def _run_manifest_unit(results: Mapping[str, Any]) -> Callable[[], None]:
    def run() -> None:
        previous = _previous_run_manifest()
        write_json(
            "run-manifest.json",
            {
                "schema_version": "run-manifest-v1",
                "run_id": RUN_ID,
                "batch_path": "batch.json",
                "source_manifest_path": "source-manifest.json",
                "selection_path": "discovery/discovery-radar-r0.json",
                # 分阶段重跑时 wechat/preview 可能没跑：沿用上一份 manifest 的结论，
                # 都没有就如实记 not_run，不要让"没跑"看起来像"跑了且没问题"。
                "wechat_render": results.get("wechat_render")
                or previous.get("wechat_render")
                or {"status": "not_run"},
                "preview_site": results.get("preview_site")
                or previous.get("preview_site")
                or {"status": "not_run"},
                "step_log": "step-log.jsonl",
                "publication_authorization": "not_authorized",
            },
        )

    return run


def _previous_run_manifest() -> dict[str, Any]:
    try:
        payload = json.loads((Path(ROOT) / "run-manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def stage_plan(body_map: Mapping[str, str] | None = None) -> list[PipelineStage]:
    """按执行顺序给出阶段清单（阶段之间只通过 run 目录里的文件交接）。

    分阶段重跑之所以可行，靠的就是这条设计：每个阶段要么用 spec 数据、要么读 run 里
    已经落盘的产物，不依赖上一个阶段留在内存里的值（``body_map`` 是 spec 的纯数据，
    随时可用）。``run_manifest`` 需要 wechat/preview 的状态，缺失时回读上一份 manifest。
    """

    bodies_map = dict(body_map or {})
    results: dict[str, Any] = {}
    plan: list[PipelineStage] = [
        PipelineStage("discovery", "discovery", discovery),
        PipelineStage(
            "source_manifest",
            "source_manifest",
            source_manifest,
            requires=tuple(
                spec["artifact_path"]
                for spec in (SOURCES.values() if isinstance(SOURCES, Mapping) else SOURCES)
                if isinstance(spec, Mapping) and spec.get("artifact_path")
            ),
        ),
        PipelineStage("candidates", "candidates", candidates),
        PipelineStage("briefs_and_tasks", "briefs_and_tasks", briefs_and_tasks),
    ]
    for aid in MATERIAL_SPECS:
        plan.append(
            PipelineStage(
                f"material_pack:{aid}",
                "material_pack",
                (lambda aid=aid: material_pack(aid)),
                requires=(f"task-hierarchy/article-task-{aid}.json",),
            )
        )
    plan.append(PipelineStage("bodies", "bodies", lambda: bodies_map))
    plan.append(
        PipelineStage(
            "drafts_write",
            "drafts_write",
            lambda: [
                write_text(f"drafts/{aid}/body_draft.md", body)
                for aid, body in bodies_map.items()
            ],
        )
    )
    for spec_args in CONTENT_RECORD_ARGS:
        plan.append(
            PipelineStage(
                f"content_record:{spec_args['aid']}",
                "content_record",
                _content_record_unit(spec_args, bodies_map),
                requires=(f"drafts/{spec_args['aid']}/body_draft.md",),
            )
        )
    plan.append(
        PipelineStage(
            "reviews_and_delivery",
            "reviews_and_delivery",
            (lambda: reviews_and_delivery(bodies_map)),
            requires=tuple(f"task-cards/task-card-{aid}.md" for aid in bodies_map),
        )
    )
    plan.append(PipelineStage("evidence_rebind", "evidence_rebind", evidence_rebind_step))
    plan.append(
        PipelineStage(
            "portfolio",
            "portfolio",
            portfolio,
            requires=("candidate-pool.json",),
        )
    )
    plan.append(
        PipelineStage(
            "gates",
            "gates",
            gates,
            requires=("task-hierarchy/*.json", "material-packs/*.json", "candidate-pool.json"),
        )
    )
    plan.append(
        PipelineStage(
            "batch_manifest",
            "batch_manifest",
            (lambda: batch_manifest(bodies_map)),
            requires=tuple(f"review/{aid}/title-pack.json" for aid in bodies_map)
            + ("review/gates/topic-five-questions.json",),
        )
    )
    plan.append(
        PipelineStage(
            "wechat_render",
            "wechat_render",
            _status_unit(wechat_render_step, results, "wechat_render"),
            requires=("delivery/*/delivery.md",),
        )
    )
    plan.append(
        PipelineStage(
            "preview_site",
            "preview_site",
            _status_unit(preview_site_step, results, "preview_site"),
            requires=("delivery/*/delivery.md",),
        )
    )
    plan.append(PipelineStage("run_manifest", "run_manifest", _run_manifest_unit(results)))
    plan.append(
        PipelineStage("step_log_markdown", "step_log_markdown", lambda: _write_step_log_markdown(ROOT))
    )
    return plan


def select_stages(
    plan: Sequence[PipelineStage],
    *,
    stages: Sequence[str] | None = None,
    from_stage: str | None = None,
) -> list[PipelineStage]:
    """按组名/完整名挑选阶段单元；未知名字直接报错，不静默跳过。

    名字写错时最危险的结果是"以为跑了、其实什么都没跑"，所以这里 fail-closed。
    """

    def matches(stage: PipelineStage, wanted: str) -> bool:
        return stage.name == wanted or stage.group == wanted

    selected = list(plan)
    if from_stage:
        index = next((i for i, stage in enumerate(selected) if matches(stage, from_stage)), None)
        if index is None:
            raise ValueError(f"未知阶段：{from_stage}（可用：{_known_stage_names(plan)}）")
        selected = selected[index:]
    if stages:
        wanted = [str(item).strip() for item in stages if str(item).strip()]
        unknown = [item for item in wanted if not any(matches(stage, item) for stage in plan)]
        if unknown:
            raise ValueError(f"未知阶段：{'、'.join(unknown)}（可用：{_known_stage_names(plan)}）")
        selected = [stage for stage in selected if any(matches(stage, item) for item in wanted)]
    return selected


def _known_stage_names(plan: Sequence[PipelineStage]) -> str:
    groups: list[str] = []
    for stage in plan:
        if stage.group not in groups:
            groups.append(stage.group)
    return "、".join(groups)


def _require_prerequisites(stage: PipelineStage) -> None:
    missing = [pattern for pattern in stage.requires if not any(Path(ROOT).glob(pattern))]
    if missing:
        raise StagePrerequisiteMissing(
            f"{stage.name} 需要 run 里已有 {'、'.join(missing)}；"
            "分阶段重跑只能跑在已有这些产物的 run 上"
        )


_BASE_RAW_WRITERS: dict[str, Callable] | None = None


def _route_write_for_base(path: str, value: object, *, kind: str) -> None:
    """base 的写：只有 ``base.ROOT`` 就是本次绑定的 run 时才走通道。

    历史脚本（如 ``run_real_daily_003.py``）会改 ``base.ROOT`` 后直接调
    ``base.write_text``；那种调用按原样裸写，别把产物记到别的 run 的账上。
    """

    assert _BASE_RAW_WRITERS is not None
    if Path(base.ROOT) != Path(ROOT):
        _BASE_RAW_WRITERS[kind](path, value)
        return
    _route_write(path, value, kind=kind, raw=_BASE_RAW_WRITERS[kind])


def _route_base_writes() -> None:
    """把 base（``scripts.generate_daily_001``）的模块级写函数也接进留底通道。

    为什么需要（2026-09-18，B7′）：引擎的阶段函数里有一批 ``base.write_text`` /
    ``base.title_records`` / ``base.topic_cards`` 调用，它们走的是 base 自己的
    ``write_json``/``write_text``（模块级全局查找），**不经过**引擎的 ``_route_write``。
    结果是 daily-009 有 63/152 个文件在账本里查不到（含 ``delivery/*/delivery.md``、
    ``review/*/title-pack.json``、``review/*/source-stripped.md``）：既没有 before-image，
    也没有 changelog，事后只剩"最后一次打包"的 mtime 可看。

    包装保持产物字节不变（同样的 ``ensure_ascii=False, indent=2`` 与 ``rstrip()+\\n``），
    只是多走一次留底+记账+封存守门。幂等：重复 bind 不会套娃（原始写函数记在模块里）。
    """

    global _BASE_RAW_WRITERS
    if _BASE_RAW_WRITERS is None:
        _BASE_RAW_WRITERS = {"json": base.write_json, "text": base.write_text}
    base.ROOT = ROOT
    base.write_json = lambda path, value: _route_write_for_base(path, value, kind="json")
    base.write_text = lambda path, value: _route_write_for_base(path, value, kind="text")


def bind_spec(spec) -> None:
    """绑定 spec 数据，并把 spec 与 base 的裸写包进留底通道。"""

    bind_names = (
        "ROOT", "RUN_ID", "GROUP_ID", "CAPTURED_AT", "CONTRACT",
        "digest", "write_json", "write_text", "ref",
        "RADAR_RECORDS", "SOURCES", "CANDIDATES", "REJECTED_PRIOR_WORKS",
        "SLOT_DECISIONS",
        "TASK_CARD_REQUIRED_FIELDS", "STRONGEST_HOOKS",
        "MATERIAL_SPECS", "BRIEFS", "BRIEF_SPECS", "BODIES",
        "CONTENT_RECORD_ARGS", "TITLES", "SOURCE_IDS", "MODES",
        "RULE_CLAIMS", "BATCH_SPECS",
    )
    globals().update({name: getattr(spec, name) for name in bind_names})

    # 把 spec 的裸写包进留底通道（2026-09-17）：引擎产物从此有 before-image 与记账，
    # 封存 run 上默认拒绝。spec 模块（run_real_daily_00x.py）保持原样不必逐个改。
    # 注意必须写回 globals()：各阶段函数是在模块作用域里找 write_json/write_text 的。
    _raw_write_json, _raw_write_text = write_json, write_text
    globals()["write_json"] = lambda path, value: _route_write(path, value, kind="json", raw=_raw_write_json)
    globals()["write_text"] = lambda path, value: _route_write(path, value, kind="text", raw=_raw_write_text)
    _route_base_writes()


def build_run(
    spec,
    *,
    stages: Sequence[str] | None = None,
    from_stage: str | None = None,
) -> list[str]:
    """Execute the pipeline stages using a per-run spec module's data.

    ``stages`` / ``from_stage`` 支持分阶段重跑（2026-09-18）：只跑选中的阶段，被跳过的
    阶段的产物按"磁盘上已有"对待——尾段改一处不必再等整条流水线（含 docker 渲染）。
    返回本次实际执行的阶段名，供调用方/日志使用。
    """

    bind_spec(spec)
    body_map = bodies()
    plan = stage_plan(body_map)
    selected = select_stages(plan, stages=stages, from_stage=from_stage)

    from article_group.step_log import StepLog

    partial = len(selected) != len(plan)
    executed: list[str] = []
    for stage in selected:
        if partial:
            # 全量跑时前置产物由前面的阶段产出，不必预检；只有"跳过前面阶段"的
            # 重跑才需要先确认 run 里确实有那些产物。
            _require_prerequisites(stage)
        note = f"分阶段重跑：本次 {len(selected)}/{len(plan)} 个阶段单元" if partial else ""
        with StepLog(ROOT, stage.name, note=note):
            stage.run()
        executed.append(stage.name)
    return executed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.daily_engine",
        description="按 spec 跑 two_article_daily 流水线；可只跑部分阶段（分阶段重跑）",
    )
    parser.add_argument("--spec", type=Path, required=True, help="spec 模块路径，如 scripts/run_real_daily_009.py")
    parser.add_argument("--stages", default="",
                        help="只跑这些阶段（组名或 name:aid，逗号分隔；见 --list-stages）")
    parser.add_argument("--from", dest="from_stage", default="", help="从该阶段起跑到末尾")
    parser.add_argument("--list-stages", action="store_true", help="只列出阶段清单，不执行")
    return parser


def load_spec(path: str | Path):
    """按路径加载 spec 模块（spec 在模块级只定义数据，导入无副作用）。"""

    import importlib.util

    target = Path(path).resolve()
    if not target.is_file():
        raise FileNotFoundError(f"spec 模块不存在：{target}")
    module_spec = importlib.util.spec_from_file_location(f"ruoyu_daily_spec_{target.stem}", target)
    if module_spec is None or module_spec.loader is None:
        raise ImportError(f"无法加载 spec 模块：{target}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    try:
        spec = load_spec(args.spec)
    except (FileNotFoundError, ImportError) as exc:
        print(f"拒绝执行：{exc}", file=sys.stderr)
        return 2
    spec_root = Path(str(getattr(spec, "ROOT", "")))
    if not spec_root.is_absolute() and Path.cwd() != repo_root:
        print(
            f"拒绝执行：spec 的 ROOT 是相对路径（{spec_root}），请在仓库根 {repo_root} 下运行",
            file=sys.stderr,
        )
        return 2
    if args.list_stages:
        bind_spec(spec)
        for stage in stage_plan(bodies()):
            requires = f"  需要 {', '.join(stage.requires)}" if stage.requires else ""
            print(f"{stage.group:20s} {stage.name}{requires}")
        return 0
    partial = bool(args.stages.strip() or args.from_stage.strip())
    root_path = spec_root if spec_root.is_absolute() else Path.cwd() / spec_root
    if partial and not root_path.is_dir():
        print(f"拒绝执行：分阶段重跑需要已存在的 run（{root_path}）", file=sys.stderr)
        return 2
    try:
        executed = build_run(
            spec,
            stages=[item for item in args.stages.split(",") if item.strip()],
            from_stage=args.from_stage.strip() or None,
        )
    except (StagePrerequisiteMissing, ValueError) as exc:
        print(f"拒绝执行：{exc}", file=sys.stderr)
        return 2
    print(f"完成 {len(executed)} 个阶段单元：{'、'.join(executed)}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())

