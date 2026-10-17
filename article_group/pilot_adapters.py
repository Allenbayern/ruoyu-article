"""pilot_adapters: 连接旧系统工业基础设施与新系统 6 角色契约的数据适配器。

包含四大核心适配器：
1. dailyhot_scout_adapter: 将全网 8 大平台争议热帖转换为带母题打标的候选池
2. topic_backlog_adapter: 将未入选候选持久化存入 topic-backlog.sqlite，已放弃候选绝不复活
3. evidence_sources_adapter: 将原始抓取物料落地为带 SHA-256 的 sources/ 快照与 manifest
4. gate_registry: 统一收集确定性门禁状态，如实报告 pass / fail / not_run
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from article_group.evidence_write import write_evidence, write_evidence_json
from article_group.pilot_extensions import (
    check_assertion_ledger_coverage,
    check_markdown_image_integrity,
    check_uncertainty_sheet_compliance,
    classify_viral_pillar,
    run_timestamp_peel_test,
    scan_historical_published_dedupe,
    validate_source_capabilities,
    verify_claims_anchored_in_sources,
    run_zhuque_gate_check,
)


# ==============================================================================
# 1. DailyHot 热帖 -> Candidate Pool 适配器与五源雷达融合
# ==============================================================================

def scout_radar_fusion(
    run_root: str | Path,
    *,
    classified_path: str | Path | None = None,
    extra_items: Sequence[Mapping[str, Any]] | None = None,
    top_n: int = 5,
    author: str = "scout",
) -> dict[str, Any]:
    """多源雷达融合选题适配器：
    1. 自动探测或读取 dailyhot 8大平台争议热榜快照；
    2. 融合外部传入的额外多源线索（微信公众号爆款、抖音文娱榜、知乎高赞、手工线索）；
    3. 全量过滤影视话题，按争议度与热度排序；
    4. 执行母题匹配、时间戳长青剥离与跨批次已发查重；
    5. 生成标准的 candidate-pool.json 并记账。
    """
    root = Path(run_root).resolve()
    c_path: Path | None = None
    if classified_path:
        c_path = Path(classified_path).resolve()
        if not c_path.is_file():
            raise ValueError(f"classified_path_not_found:{c_path}")
    else:
        # 自动探测最新的 radar 快照
        radar_dir = Path(__file__).resolve().parents[1] / "runs" / "radar" / "dailyhot"
        if radar_dir.is_dir():
            candidates_c = sorted(radar_dir.glob("*.classified.json"))
            if candidates_c:
                c_path = candidates_c[-1]

    items: list[dict[str, Any]] = []
    source_label_classified = "none"
    if c_path and c_path.is_file():
        source_label_classified = str(c_path)
        try:
            raw_data = json.loads(c_path.read_text(encoding="utf-8"))
            items.extend(raw_data.get("items", []))
        except Exception:
            pass

    if extra_items:
        for it in extra_items:
            items.append(dict(it))

    film_items = [it for it in items if it.get("film") is True or any(
        k in str(it.get("title", "")) for k in ["剧", "电影", "导演", "视帝", "视后", "票房", "演技", "塌房", "神作", "老戏骨"]
    )]

    # 去重：按 title
    seen_titles: set[str] = set()
    deduped_film: list[dict[str, Any]] = []
    for it in film_items:
        t = str(it.get("title") or "").strip()
        if t and t not in seen_titles:
            seen_titles.add(t)
            deduped_film.append(it)

    # 按照争议度降序、热度降序排序
    deduped_film.sort(key=lambda r: (-int(r.get("dispute") or 0), -float(r.get("hot") or 0)))

    candidates: list[dict[str, Any]] = []
    for idx, it in enumerate(deduped_film[:top_n], 1):
        cid = f"cand-{idx:02d}"
        title = str(it.get("title") or "").strip()
        desc = str(it.get("desc") or "").strip()
        combined = f"{title} {desc}".strip()

        pillar = classify_viral_pillar(combined)
        peel_test = run_timestamp_peel_test({"title": title, "angle": desc})
        dedupe_check = scan_historical_published_dedupe(combined, exclude_run_name=root.name)

        cand_card = {
            "candidate_id": cid,
            "work_title": title,
            "signal": title,
            "signal_source": str(it.get("source_label") or it.get("source") or "radar_signal"),
            "source_refs": [str(it.get("url") or "")],
            "dispute_level": int(it.get("dispute") or 0),
            "hot_score": float(it.get("hot") or 0),
            "viral_pillar": pillar,
            "timestamp_peel_test": peel_test,
            "historical_dedupe": dedupe_check,
            "freshness_window": "same-day",
            "evidence_readiness": "medium",
            "recommendation": "Wait" if dedupe_check["is_duplicate"] else ("A" if idx <= 2 else "B"),
            "status": "advisory_candidate",
        }
        candidates.append(cand_card)

    pool_payload = {
        "schema_version": "candidate-pool-v2",
        "run_id": root.name,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "classified_source": source_label_classified,
        "total_film_hits": len(deduped_film),
        "candidates": candidates,
        "publication_authorization": "not_authorized",
    }

    target = root / "candidate-pool.json"
    write_evidence_json(
        target,
        pool_payload,
        run_dir=root,
        reason="scout_radar_fusion:generate_candidate_pool",
        author=author,
    )
    return pool_payload


def dailyhot_scout_adapter(
    classified_path: str | Path,
    run_root: str | Path,
    *,
    top_n: int = 5,
    author: str = "scout"
) -> dict[str, Any]:
    """读取 dailyhot_classify 输出，生成带母题标签和长青测试结论的 candidate-pool.json（兼容旧接口）。"""
    return scout_radar_fusion(run_root, classified_path=classified_path, top_n=top_n, author=author)


# ==============================================================================
# 2. Topic Backlog SQLite 储备适配器
# ==============================================================================

DEFAULT_BACKLOG_DB = Path(__file__).resolve().parents[1] / "state" / "topic-backlog.sqlite"

def topic_backlog_adapter(
    candidate_pool: Mapping[str, Any],
    selected_id: str,
    *,
    db_path: Path | None = None,
    run_dir: str = "",
) -> dict[str, int]:
    """把入选的候选标记为 selected，其余未选候选持久化存入 topic-backlog.sqlite。
    遵循规则：dropped 候选再次出现只增 seen_count，绝不自动复活。
    """
    db_file = Path(db_path) if db_path else DEFAULT_BACKLOG_DB
    if not db_file.exists():
        # 如果不存在则忽略或初始化
        return {"added": 0, "updated": 0, "selected": 0}

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    now_stamp = datetime.now(timezone.utc).isoformat()

    added = updated = selected_count = 0
    candidates = candidate_pool.get("candidates", [])

    for cand in candidates:
        cid = str(cand.get("candidate_id") or "")
        title = str(cand.get("work_title") or cand.get("title") or "").strip()
        if not title:
            continue

        item_key = "title:" + hashlib.sha256(title.encode("utf-8")).hexdigest()[:32]
        is_selected = (cid == selected_id)

        existing = conn.execute(
            "SELECT state, seen_count FROM backlog_items WHERE item_key = ?", (item_key,)
        ).fetchone()

        if existing is None:
            init_state = "selected" if is_selected else "new"
            conn.execute(
                """INSERT INTO backlog_items
                   (item_key, candidate_id, title, first_seen_at, last_seen_at,
                    seen_count, first_run_dir, last_run_dir, state)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                (item_key, cid, title, now_stamp, now_stamp, run_dir, run_dir, init_state),
            )
            added += 1
            if is_selected:
                selected_count += 1
        else:
            current_state = existing["state"]
            if current_state == "dropped":
                new_state = "dropped"
            elif is_selected:
                new_state = "selected"
                selected_count += 1
            else:
                new_state = current_state
            # dropped 保持 dropped，不得被 is_selected 意外复活
            conn.execute(
                """UPDATE backlog_items SET
                   last_seen_at = ?, last_run_dir = ?, seen_count = seen_count + 1, state = ?
                   WHERE item_key = ?""",
                (now_stamp, run_dir, new_state, item_key),
            )
            updated += 1

    conn.commit()
    conn.close()
    return {"added": added, "updated": updated, "selected": selected_count}


# ==============================================================================
# 3. 证据快照落盘与 Manifest 适配器 (Evidence Sources Adapter)
# ==============================================================================

def evidence_sources_adapter(
    run_root: str | Path,
    sources_data: Sequence[Mapping[str, Any]],
    *,
    author: str = "evidence_researcher"
) -> dict[str, Any]:
    """将采集到的材料正文落地为 sources/<id>.clean.md 快照，计算 SHA-256 并生成 source-manifest.json。"""
    root = Path(run_root).resolve()
    sources_dir = root / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    manifest_sources: list[dict[str, Any]] = []

    for src in sources_data:
        sid = str(src.get("source_id") or "").strip()
        if not sid:
            continue
        if ".." in sid or not re.match(r"^[A-Za-z0-9_.-]+$", sid):
            raise ValueError(f"invalid_source_id_or_traversal:{sid}")
        text = str(src.get("text") or src.get("body") or "").strip()
        title = str(src.get("title") or sid).strip()
        url = str(src.get("url") or src.get("source_url") or "").strip()
        role = str(src.get("source_role") or "confirmed-primary").strip()
        group = str(src.get("independence_group") or sid).strip()

        # 写入 clean.md 快照（严格防御路径穿越）
        target_md = (sources_dir / f"{sid}.clean.md").resolve()
        if not target_md.is_relative_to(root):
            raise ValueError(f"source_path_traversal:{sid}")
        write_evidence(
            target_md,
            f"# {title}\n\nURL: {url}\n\n---\n\n{text}\n",
            run_dir=root,
            reason=f"evidence_sources_adapter:snapshot_{sid}",
            author=author,
        )

        sha = hashlib.sha256(target_md.read_bytes()).hexdigest()
        manifest_sources.append({
            "source_id": sid,
            "title": title,
            "source_url": url,
            "artifact_path": str(target_md.relative_to(root)),
            "sha256": sha,
            "source_role": role,
            "independence_group": group,
            "captured_at": datetime.now(timezone.utc).isoformat(),
        })

    manifest_payload = {
        "schema_version": "source-manifest-v1",
        "run_id": root.name,
        "sources_count": len(manifest_sources),
        "sources": manifest_sources,
        "publication_authorization": "not_authorized",
    }

    manifest_target = root / "source-manifest.json"
    write_evidence_json(
        manifest_target,
        manifest_payload,
        run_dir=root,
        reason="evidence_sources_adapter:build_source_manifest",
        author=author,
    )
    return manifest_payload


# ==============================================================================
# 4. 全量门禁注册与透明履约汇总 (Gate Registry)
# ==============================================================================

def build_gate_registry_report(run_root: str | Path) -> dict[str, Any]:
    """汇总所有确定性门禁、审计工具的状态，绝不隐瞒 not_run。"""
    root = Path(run_root).resolve()
    review_dir = root / "review"

    gates: dict[str, dict[str, Any]] = {}

    # 1. 标题冻结门禁
    freeze_path = review_dir / "title-freeze.json"
    if freeze_path.exists():
        try:
            fz = json.loads(freeze_path.read_text(encoding="utf-8"))
            gates["title_freeze"] = {
                "status": "pass" if fz.get("status") == "frozen_ok" else "fail",
                "blocking": True,
                "artifact": str(freeze_path.relative_to(root)),
                "title": fz.get("title"),
            }
        except Exception:
            gates["title_freeze"] = {"status": "fail", "blocking": True, "error": "corrupted_freeze_json"}
    else:
        gates["title_freeze"] = {"status": "not_run", "blocking": True, "reason": "title_freeze_json_missing"}

    # 2. 开篇试写熔断
    draft_path = root / "draft.md"
    if draft_path.exists():
        draft_text = draft_path.read_text(encoding="utf-8")
        from article_group.pilot_extensions import prose_pilot_check
        ok, msg = prose_pilot_check(draft_text)
        gates["prose_pilot"] = {
            "status": "pass" if ok else "fail",
            "blocking": True,
            "artifact": "draft.md",
            "message": msg,
        }
    else:
        gates["prose_pilot"] = {"status": "not_run", "blocking": True, "reason": "draft_md_missing"}

    # 3. 素材完整度
    ev_path = root / "evidence-pack.json"
    if ev_path.exists():
        try:
            ev = json.loads(ev_path.read_text(encoding="utf-8"))
            from article_group.pilot_extensions import evaluate_three_tier_evidence
            tier_res = evaluate_three_tier_evidence(ev)
            gates["three_tier_evidence"] = {
                "status": "pass" if tier_res["passed"] else "fail",
                "blocking": False,  # 80分以下提醒补料
                "score": tier_res["score"],
                "missing": tier_res["missing_items"],
            }
        except Exception:
            gates["three_tier_evidence"] = {"status": "fail", "blocking": False, "error": "corrupted_evidence_json"}
    else:
        gates["three_tier_evidence"] = {"status": "not_run", "blocking": False, "reason": "evidence_pack_missing"}

    # 4. 独立 L2 复核
    l2_path = review_dir / "l2-adversarial-review.json"
    if l2_path.exists():
        try:
            l2_data = json.loads(l2_path.read_text(encoding="utf-8"))
            dec = l2_data.get("decision")
            # 2026-10-16（case-009 复盘）：此前只读 decision、**从不比对稿件哈希**，
            # 于是 draft.md 被整篇换掉之后 L2 仍报 pass —— 与封存稿 11 处编造并列的
            # 同一类「自述式放行」。这里补上哈希绑定：复核对象必须就是当前 draft.md。
            reviewed_sha = str(
                l2_data.get("reviewed_draft_sha256") or l2_data.get("target_sha256") or ""
            ).strip()
            current_sha = ""
            if draft_path.is_file():
                current_sha = hashlib.sha256(draft_path.read_bytes()).hexdigest()
            entry: dict[str, Any] = {
                "status": "pass"
                if dec == "approve"
                else ("needs_changes" if dec == "needs_changes" else "fail"),
                "blocking": True,
                "decision": dec,
                "findings_count": len(l2_data.get("findings") or []),
                "reviewed_draft_sha256": reviewed_sha or None,
                "current_draft_sha256": current_sha or None,
            }
            if not reviewed_sha:
                # 没有哈希就没法证明这次复核针对的是当前稿 —— 不可验证，不许放行。
                entry["status"] = "fail"
                entry["error"] = "l2_review_unbound:missing_draft_sha256"
            elif current_sha and reviewed_sha != current_sha:
                entry["status"] = "fail"
                entry["error"] = "l2_review_stale:draft_changed_after_review"
            gates["l2_adversarial_review"] = entry
        except Exception:
            gates["l2_adversarial_review"] = {"status": "fail", "blocking": True, "error": "corrupted_l2_json"}
    else:
        gates["l2_adversarial_review"] = {"status": "not_run", "blocking": True, "reason": "l2_review_not_conducted"}

    # 4.1 叙述性细节溯源网（2026-10-16，case-009 复盘）
    # advisory：把「正文有、信源逐字无」的可证伪细节清单化，供人工逐条处置；
    # 刻意 blocking=False —— 零命中可能是编造，也可能是作者自己的比喻。
    detail_path = review_dir / "gates" / "narrative-detail-provenance.json"
    if detail_path.exists():
        try:
            detail = json.loads(detail_path.read_text(encoding="utf-8"))
            gates["narrative_detail_provenance"] = {
                "status": detail.get("status", "not_run"),
                "blocking": False,
                "checked_probes": detail.get("checked_probes"),
                "unsourced_count": len(detail.get("unsourced") or []),
                "unsourced": [u.get("term") for u in (detail.get("unsourced") or [])],
                "artifact": str(detail_path.relative_to(root)),
                "reason": detail.get("reason"),
            }
        except Exception:
            gates["narrative_detail_provenance"] = {
                "status": "fail",
                "blocking": False,
                "error": "corrupted_narrative_detail_json",
            }
    else:
        gates["narrative_detail_provenance"] = {
            "status": "not_run",
            "blocking": False,
            "reason": "narrative_detail_report_missing",
        }

    # 5. 脱水可读性透视稿 (source-stripped.md)
    if draft_path.exists():
        draft_text = draft_path.read_text(encoding="utf-8")
        from article_group.pilot_extensions import generate_source_stripped_body
        stripped_res = generate_source_stripped_body(draft_text)
        stripped_target = review_dir / "source-stripped.md"
        write_evidence(
            stripped_target,
            f"# 脱水观点骨架（去剧情与长引述透视稿）\n\n> 压缩率: {stripped_res['compression_ratio']*100:.1f}% (原 {stripped_res['raw_cjk_chars']} 字 -> 核心 {stripped_res['stripped_cjk_chars']} 字)\n\n---\n\n{stripped_res['stripped_body']}\n",
            run_dir=root,
            reason="source_stripped:generate_readability_body",
            author="quality_l2_reviewer",
        )
        gates["source_stripped_readability"] = {
            "status": "pass" if stripped_res["is_substantive"] else "advisory",
            "blocking": False,
            "compression_ratio": stripped_res["compression_ratio"],
            "artifact": str(stripped_target.relative_to(root)),
            "summary": stripped_res["summary"],
        }
    else:
        gates["source_stripped_readability"] = {"status": "not_run", "blocking": False, "reason": "draft_md_missing"}

    # 6. 账本孤儿检查 (ledger_orphans)
    if draft_path.exists() and ev_path.exists():
        try:
            ev = json.loads(ev_path.read_text(encoding="utf-8"))
            from article_group.pilot_extensions import detect_ledger_orphans
            orphan_res = detect_ledger_orphans(draft_text, ev)
            gates["ledger_orphan_detection"] = {
                "status": "pass" if orphan_res["passed"] else "advisory",
                "blocking": False,
                "absorption_rate": orphan_res["absorption_rate"],
                "warnings": orphan_res["warnings"],
            }
        except Exception:
            gates["ledger_orphan_detection"] = {"status": "fail", "blocking": False, "error": "orphan_check_failed"}
    else:
        gates["ledger_orphan_detection"] = {"status": "not_run", "blocking": False, "reason": "draft_or_evidence_missing"}

    # 7. 原文滑窗防脑补溯源校验 (claim_source_provenance)
    manifest_path = root / "source-manifest.json"
    if not manifest_path.exists():
        gates["claim_source_provenance"] = {"status": "fail", "blocking": True, "reason": "source_manifest_missing"}
    elif not ev_path.exists():
        gates["claim_source_provenance"] = {"status": "fail", "blocking": True, "reason": "evidence_pack_missing"}
    else:
        try:
            ev = json.loads(ev_path.read_text(encoding="utf-8"))
            prov_res = verify_claims_anchored_in_sources(root, ev)
            gates["claim_source_provenance"] = {
                "status": "pass" if prov_res["passed"] else "fail",
                "blocking": True,
                "anchored_count": prov_res["anchored_count"],
                "total_facts": prov_res["total_facts"],
                "errors": prov_res["errors"],
            }
        except Exception:
            gates["claim_source_provenance"] = {"status": "fail", "blocking": True, "error": "provenance_check_failed"}

    # 8. 信源权能分级校验 (source_capabilities)
    if not manifest_path.exists():
        gates["source_capabilities"] = {"status": "fail", "blocking": True, "reason": "source_manifest_missing"}
    elif not draft_path.exists():
        gates["source_capabilities"] = {"status": "fail", "blocking": True, "reason": "draft_md_missing"}
    else:
        try:
            draft_text = draft_path.read_text(encoding="utf-8")
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            cap_res = validate_source_capabilities(draft_text, manifest_data)
            gates["source_capabilities"] = {
                "status": "pass" if cap_res["passed"] else "fail",
                "blocking": True,
                "max_capability_level": cap_res["max_capability_level"],
                "violations": cap_res["violations"],
            }
        except Exception:
            gates["source_capabilities"] = {"status": "fail", "blocking": True, "error": "capability_check_failed"}

    # 9. 待核清单决断与防泄漏校验 (uncertainty_compliance)
    sheet_path = root / "pending-review-sheet.json"
    if draft_path.exists() and (sheet_path.exists() or ev_path.exists()):
        try:
            draft_text = draft_path.read_text(encoding="utf-8")
            sheet_data = json.loads(sheet_path.read_text(encoding="utf-8")) if sheet_path.exists() else {}
            ev_data = json.loads(ev_path.read_text(encoding="utf-8")) if ev_path.exists() else {}
            unc_res = check_uncertainty_sheet_compliance(draft_text, sheet_data, ev_data)
            gates["uncertainty_compliance"] = {
                "status": "pass" if unc_res["passed"] else "fail",
                "blocking": True,
                "errors": unc_res["errors"],
                "leaked_tokens": unc_res["leaked_tokens"],
            }
        except Exception:
            gates["uncertainty_compliance"] = {"status": "fail", "blocking": True, "error": "uncertainty_check_failed"}
    else:
        gates["uncertainty_compliance"] = {"status": "not_run", "blocking": False, "reason": "no_pending_sheet"}

    # 10. 12篇定稿母本 DNA 与 style_gate/anti_ai_gate 联合审计 (dna_mother_audit)
    if draft_path.exists():
        from article_group.dna_engine import audit_draft_dna
        dna_res = audit_draft_dna(draft_path, run_root=root, write_report=True)
        gates["dna_mother_audit"] = {
            "status": "pass" if dna_res["passed"] else "fail",
            "blocking": True,
            "para_median": dna_res["para_median"],
            "para_stdev": dna_res["para_stdev"],
            "immersive_para_count": dna_res["immersive_para_count"],
            "anti_ai_score": dna_res["anti_ai_score"],
            "violations": dna_res["violations"],
        }
    else:
        gates["dna_mother_audit"] = {"status": "not_run", "blocking": True, "reason": "draft_md_missing"}

    # 11. 朱雀检测（真机外部服务）
    gates["zhuque_detector"] = run_zhuque_gate_check(draft_path, execute_live=False)

    # 12. 手机端深度长文排版与叙事呼吸节奏门禁 (mobile_rhythm_gate)
    if draft_path.exists():
        from article_group.mobile_rhythm_gate import check_mobile_rhythm
        draft_text = draft_path.read_text(encoding="utf-8")
        mobile_res = check_mobile_rhythm(draft_text)
        gates["mobile_rhythm"] = {
            "status": "pass" if mobile_res["passed"] else "fail",
            "blocking": True,
            "metrics": {
                "h2_count": mobile_res["metrics"]["h2_count"],
                "overlength_count": mobile_res["metrics"]["overlength_count"],
                "consecutive_long_spans_count": mobile_res["metrics"]["consecutive_long_spans_count"],
                "anchor_gaps_count": mobile_res["metrics"]["anchor_gaps_count"],
                "screenshot_anchors_count": mobile_res["metrics"]["screenshot_anchors_count"],
            },
            "errors": mobile_res["errors"],
            "warnings": mobile_res["warnings"],
            "advice": mobile_res["advice"],
        }
    else:
        gates["mobile_rhythm"] = {"status": "not_run", "blocking": True, "reason": "draft_md_missing"}

    blocking_failures = [
        name for name, g in gates.items()
        if g.get("blocking") is True and g.get("status") in {"fail", "not_run"}
    ]

    draft_sha = hashlib.sha256(draft_path.read_bytes()).hexdigest() if draft_path.is_file() else None
    l2_file = review_dir / "l2-adversarial-review.json"
    l2_sha = hashlib.sha256(l2_file.read_bytes()).hexdigest() if l2_file.is_file() else None

    report = {
        "schema_version": "gate-registry-v2",
        "run_id": root.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "draft_sha256": draft_sha,
        "l2_file_sha256": l2_sha,
        "all_blocking_passed": len(blocking_failures) == 0,
        "blocking_failures": blocking_failures,
        "gates": gates,
        "publication_authorization": "not_authorized",
    }

    write_evidence_json(
        review_dir / "gate-registry-report.json",
        report,
        run_dir=root,
        reason="gate_registry:assemble_report",
        author="quality_l2_reviewer",
    )
    return report


def run_all_pilot_gates(
    run_root: str | Path,
    *,
    strict_assertions: bool = True,
    execute_live_zhuque: bool = False,
) -> dict[str, Any]:
    """一键执行新系统全量确定性门禁并写入 review/dna-audit-report.json、
    review/deterministic-gates.json 与 review/gate-registry-report.json。
    """
    from article_group.dna_engine import audit_draft_dna

    root = Path(run_root).resolve()
    draft_path = root / "draft.md"
    if not draft_path.is_file():
        raise ValueError(f"draft_missing:{draft_path}")

    draft_bytes = draft_path.read_bytes()
    draft_sha256 = hashlib.sha256(draft_bytes).hexdigest()
    draft_text = draft_bytes.decode("utf-8")

    ev_path = root / "evidence-pack.json"
    ev_data = json.loads(ev_path.read_text(encoding="utf-8")) if ev_path.is_file() else {}
    manifest_path = root / "source-manifest.json"
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    sheet_path = root / "pending-review-sheet.json"
    sheet_data = json.loads(sheet_path.read_text(encoding="utf-8")) if sheet_path.is_file() else {}

    dna_audit = audit_draft_dna(draft_path, run_root=root, write_report=True)
    assertion_cov = check_assertion_ledger_coverage(
        draft_text, ev_data, run_root=root, strict=strict_assertions
    )
    img_integrity = check_markdown_image_integrity(draft_text, root)
    claim_prov = (
        verify_claims_anchored_in_sources(root, ev_data)
        if manifest_path.is_file()
        else {"passed": False, "errors": ["source_manifest_missing"], "anchored_count": 0, "total_facts": 0}
    )
    src_cap = (
        validate_source_capabilities(draft_text, manifest_data)
        if manifest_path.is_file()
        else {"passed": False, "violations": ["source_manifest_missing"], "max_capability_level": 0}
    )
    unc_comp = check_uncertainty_sheet_compliance(draft_text, sheet_data, ev_data)
    from article_group.run_gates import build_narrative_detail_gate
    narrative_detail = build_narrative_detail_gate(root)
    (root / "review" / "gates").mkdir(parents=True, exist_ok=True)
    write_evidence_json(
        root / "review" / "gates" / "narrative-detail-provenance.json",
        narrative_detail,
        run_dir=root,
        reason="pilot_adapters:narrative_detail_provenance",
        author="writer",
    )
    registry_report = build_gate_registry_report(root)
    if execute_live_zhuque:
        registry_report["gates"]["zhuque_detector"] = run_zhuque_gate_check(draft_path, execute_live=True)

    all_passed = (
        dna_audit["passed"]
        and assertion_cov["passed"]
        and img_integrity["passed"]
        and claim_prov["passed"]
        and src_cap["passed"]
        and unc_comp["passed"]
        and bool(registry_report.get("all_blocking_passed"))
    )

    l2_path = root / "review" / "l2-adversarial-review.json"
    l2_dec = "not_run"
    if l2_path.is_file():
        try:
            l2_dec = str(json.loads(l2_path.read_text(encoding="utf-8")).get("decision") or "not_run")
        except Exception:
            l2_dec = "invalid"

    det_payload = {
        "case_id": root.name,
        "reviewed_draft_sha256": draft_sha256,
        "deterministic_gates": "pass" if all_passed else "fail",
        "l2_decision": l2_dec,
        "dna_audit": dna_audit,
        "anti_ai_score": dna_audit["anti_ai_score"],
        "assertion_coverage": assertion_cov,
        "image_integrity": img_integrity,
        "claim_provenance": claim_prov,
        "source_capabilities": src_cap,
        "uncertainty_compliance": unc_comp,
        "mobile_rhythm": registry_report["gates"].get("mobile_rhythm", {}),
        "publication_authorization": "not_authorized",
    }

    write_evidence_json(
        root / "review" / "deterministic-gates.json",
        det_payload,
        run_dir=root,
        reason="pilot_adapters:run_all_pilot_gates",
        author="quality_l2_reviewer",
    )
    return det_payload
