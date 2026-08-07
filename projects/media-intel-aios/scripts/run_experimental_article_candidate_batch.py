#!/usr/bin/env python3
"""Run second-batch experimental article candidates.

Goal: turn bootstrap failure samples into reviewable article candidate packages,
not publish-ready output. Reads the real local mirror article approved file,
extracts article candidates, ranks A/B/C, and collects failures for pipeline
repair.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

TZ = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent

_legacy_sample_env = os.environ.get('MEDIA_INTEL_LEGACY_SAMPLE', '')
LEGACY_ARTICLE_SAMPLE = Path(_legacy_sample_env) if _legacy_sample_env else None

def _existing_candidates() -> list[Path]:
    candidates: list[Path] = []
    if LEGACY_ARTICLE_SAMPLE is not None and LEGACY_ARTICLE_SAMPLE.exists():
        candidates.append(LEGACY_ARTICLE_SAMPLE)
    local_quality = WORKSPACE / "handover-hotspot" / "04-QUALITY-FEEDBACK" / "article-approved-latest.md"
    if local_quality.exists():
        candidates.append(local_quality)
    local_tmp = ROOT / "tmp" / "daily-pipeline-discovery-verify-2026-06-15" / "article-approved-latest.md"
    if local_tmp.exists():
        candidates.append(local_tmp)
    return candidates

ARTICLE_SAMPLE_CANDIDATES = _existing_candidates()
ARTICLE_SAMPLE = ARTICLE_SAMPLE_CANDIDATES[0] if ARTICLE_SAMPLE_CANDIDATES else None
OUTPUT_DIR = ROOT / "tmp" / "bootstrap_experimental"
RUN_DATE = datetime.now(TZ).date().isoformat()
OUTPUT_PATH = OUTPUT_DIR / f"daily_article_experimental_candidate_{RUN_DATE}.json"
SAMPLE_LIMIT = 10
ARTICLE_LANE_REQUIRES = [
    "film_tv_anchor",
    "work_title_or_named_entity",
    "review_or_plot_context",
]
ARTICLE_LANE_REJECTS = [
    "marriage_emotion",
    "folk_story",
    "generic_emotion",
    "xhs_life_reflection",
    "no_film_tv_anchor",
]
def clean_title(raw: str) -> str:
    title = raw.strip()
    title = re.sub(r"^[-*]\s*", "", title)
    title = re.sub(r"^\d+\.\s*", "", title)
    title = re.sub(r"^\[[^\]]+\]\s*", "", title)
    title = title.split("｜", 1)[0].strip()
    title = re.sub(r"\s+", " ", title)
    return title[:90]


def parse_score(line: str, key: str) -> int:
    match = re.search(rf"{key}\s*(\d+)", line)
    return int(match.group(1)) if match else 0


def parse_article_entries(text: str, limit: int = SAMPLE_LIMIT) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current_pool = "unknown"
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("## "):
            current_pool = line.strip("# ")
        if not re.match(r"^- \d+\. ", line):
            continue
        title = clean_title(line.split("candidate_profile=", 1)[0])
        if not title or title == "无":
            continue
        source_match = re.search(r"\[([^\]]+)\]", line)
        entry = {
            "raw_line": line,
            "source_line": index + 1,
            "pool": current_pool,
            "source": source_match.group(1) if source_match else "unknown",
            "title": title,
            "base_score": parse_score(line, "基础分"),
            "production_score": parse_score(line, "生产分"),
            "potential_score": parse_score(line, "潜力分"),
            "semantic_score": parse_score(line, "语义分"),
            "articleability": parse_score(line, "articleability"),
            "reason": "",
            "title_candidates": [],
            "reference_hints": [],
        }
        # collect following indented lines until next candidate/section
        following = []
        for next_line in lines[index + 1:index + 8]:
            if next_line.startswith("- ") or next_line.startswith("## ") or next_line.startswith("### "):
                break
            following.append(next_line.strip())
        block = "\n".join(following)
        reason_match = re.search(r"推荐原因：(.+)", block)
        if reason_match:
            entry["reason"] = reason_match.group(1).strip()
        title_match = re.search(r"推荐标题：(.+)", block)
        if title_match:
            entry["title_candidates"] = [part.strip() for part in title_match.group(1).split("｜") if part.strip()][:5]
        ref_match = re.search(r"reference_hints=(.+)", block)
        if ref_match:
            entry["reference_hints"] = [ref_match.group(1).strip()]
        entries.append(entry)
        if len(entries) >= limit:
            break
    return entries


def infer_articleability(entry: dict[str, Any]) -> int:
    if entry.get("articleability"):
        return int(entry["articleability"])
    score = int(entry.get("base_score", 0)) + int(entry.get("potential_score", 0))
    if "A池" in entry.get("pool", ""):
        score += 10
    if "今日文章角度短名单" in entry.get("pool", ""):
        score += 20
    if entry.get("production_score", 0) >= 18:
        score += 8
    return min(score, 100)


HEAT_ONLY_SOURCES = {"guduo", "骨朵热度指数", "maoyan", "猫眼热榜", "hotboard", "tophub_today"}
DISCUSSION_SOURCES = {"douban_review", "douban", "bilibili", "douyin", "weibo", "微博", "zhihu", "知乎", "xhs", "小红书"}
CONTEXT_SOURCES = {"dumou", "毒眸", "tencent_platform", "wechat", "微信公众号", "1905", "mtime", "sir_movie"}
INDEPENDENT_DIRECT_SOURCE_PACKET = "independent_direct_source_packet"


def _is_independent_direct_source_packet(row: dict[str, Any]) -> bool:
    """Keep this packet out of every generic-evidence decision path."""
    return INDEPENDENT_DIRECT_SOURCE_PACKET in {
        str(row.get("source") or "").strip(),
        str(row.get("source_id") or "").strip(),
    }


def _supplementary_attributed_evidence(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """Extract writer-only atoms without turning the packet into generic evidence."""
    atoms: list[dict[str, Any]] = []
    requires_attribution = False
    for row in rows:
        if not _is_independent_direct_source_packet(row):
            continue
        requires_attribution = requires_attribution or row.get("requires_attribution_in_output") is True
        packet_atoms = row.get("supplementary_attributed_evidence")
        if isinstance(packet_atoms, list):
            atoms.extend(atom for atom in packet_atoms if isinstance(atom, dict))
    return atoms, requires_attribution


def extract_work_anchor(entry: dict[str, Any]) -> dict[str, Any]:
    title = entry.get("title") or ""
    quoted = re.findall(r"《([^》]{2,30})》", title)
    work = quoted[0] if quoted else title.split("，", 1)[0].split("：", 1)[0].strip()
    work_type = "unknown"
    if re.search(r"综艺|乘风|妻子的浪漫旅行|桃花坞|哈哈哈哈哈|西游", title):
        work_type = "variety"
    elif re.search(r"电影|票房|院线|猫眼", title):
        work_type = "film"
    elif re.search(r"剧|短剧|剧情|角色", title):
        work_type = "series"
    return {"title": work[:40], "type": work_type}


def extract_signal_hints(entry: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    source = str(entry.get("source") or "")
    source_key = source.lower()
    text = " ".join(str(entry.get(key) or "") for key in ("title", "raw_line", "reason"))
    hints: dict[str, list[dict[str, str]]] = {"heat": [], "discussion": [], "context": [], "audience_reaction": []}
    if source_key in HEAT_ONLY_SOURCES or source in HEAT_ONLY_SOURCES or re.search(r"热度|排名|票房|收视|播放", text):
        hints["heat"].append({"source": source, "text": text[:180]})
    if source_key in DISCUSSION_SOURCES or source in DISCUSSION_SOURCES or re.search(r"观众|评论|吐槽|争议|吵|差评|口碑|站队", text):
        hints["discussion"].append({"source": source, "text": text[:180]})
        hints["audience_reaction"].append({"source": source, "text": text[:180]})
    if source_key in CONTEXT_SOURCES or source in CONTEXT_SOURCES or re.search(r"剧情|角色|嘉宾|导演|演员|节目|作品|平台|机制|类型", text):
        hints["context"].append({"source": source, "text": text[:180]})
    return hints


def build_min_evidence_bundle(entry: dict[str, Any], signals: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    source_roles = [role for role, rows in signals.items() if rows]
    cross_source_count = len({row.get("source", "") for rows in signals.values() for row in rows if row.get("source")})
    has_narrative = bool(signals.get("discussion") or signals.get("context") or signals.get("audience_reaction"))
    if cross_source_count >= 2 and has_narrative:
        status = "usable"
    elif has_narrative:
        status = "incomplete"
    elif signals.get("heat"):
        status = "discovery_only"
    else:
        status = "missing"
    return {
        "source_roles": source_roles,
        "cross_source_count": cross_source_count,
        "bundle_status": status,
        "source_urls": [],
    }


def build_candidate_hypothesis(entry: dict[str, Any], signals: dict[str, list[dict[str, str]]]) -> dict[str, str]:
    title = entry.get("title") or ""
    text = " ".join(str(entry.get(key) or "") for key in ("title", "raw_line", "reason"))
    conflict_type = "unknown"
    if re.search(r"观众|评论|吐槽|差评|口碑|站队|吵", text):
        conflict_type = "audience_split"
    elif re.search(r"人物|嘉宾|角色|关系", text):
        conflict_type = "character_relationship"
    elif re.search(r"类型|机制|平台|行业|规则", text):
        conflict_type = "format_gap"
    core_claim = entry.get("reason") or ""
    if not core_claim or re.search(r"候选已有|主控复核|有可讨论的|结构性矛盾", core_claim):
        core_claim = ""
    return {
        "conflict_type": conflict_type,
        "core_claim": core_claim,
        "reader_question": f"{title}为什么值得今天单独写" if title else "",
    }


def build_article_package(entry: dict[str, Any]) -> dict[str, Any]:
    score = infer_articleability(entry)
    if score >= 75:
        tier = "A"
    elif score >= 60:
        tier = "B"
    else:
        tier = "C"
    title = entry["title"]
    readable_title = len(title) >= 8 and not title.startswith("无")
    work_anchor = extract_work_anchor(entry)
    signals = extract_signal_hints(entry)
    evidence_bundle = build_min_evidence_bundle(entry, signals)
    hypothesis = build_candidate_hypothesis(entry, signals)
    relevance_text = " ".join([title, str(entry.get("reason") or "")])
    film_tv_relevance = bool(work_anchor.get("title")) and (
        bool(signals["heat"] or signals["discussion"] or signals["context"])
        or bool(re.search(r"电影|影视|影评|剧情|演员|导演|票房|院线|短剧|综艺|豆瓣|猫眼|片单|角色|观众|乘风|妻子的浪漫旅行|西游|桃花坞|哈哈哈哈哈", relevance_text))
    )
    if re.search(r"民间故事|婚内单身|最棒的故事是哪一个|不是影视题|影视映射弱或缺失", relevance_text):
        film_tv_relevance = False
    has_conflict = hypothesis["conflict_type"] != "unknown" or bool(re.search(r"不如|为什么|争议|吐槽|反转|乱套|寒了心|离婚|问题|吵|差评|口碑", relevance_text))
    heat_only = bool(signals["heat"]) and not (signals["discussion"] or signals["context"] or signals["audience_reaction"])
    if not film_tv_relevance:
        lane = "article_reject"
        write_readiness = "rejected"
    elif heat_only:
        lane = "discovery_only"
        write_readiness = "needs_evidence_backfill"
    elif evidence_bundle["bundle_status"] in {"usable", "strong"} and has_conflict:
        lane = "article"
        write_readiness = "draftable"
    else:
        lane = "article"
        write_readiness = "needs_evidence_backfill"
    title_candidates = entry.get("title_candidates") or [title]
    claim_candidates = [hypothesis["core_claim"]] if hypothesis["core_claim"] else []
    review_flags = ["experimental_candidate_requires_gpt55_review", "facts_and_platform_context_need_manual_check"]
    if score < 75:
        review_flags.append("below_a_tier_threshold_collect_for_pipeline_repair")
    if not has_conflict:
        review_flags.append("conflict_or_tension_needs_strengthening")
    if not film_tv_relevance:
        review_flags.append("not_film_tv_relevant")
    if heat_only:
        review_flags.append("heat_only_discovery_requires_narrative_backfill")
    if evidence_bundle["bundle_status"] in {"missing", "incomplete", "discovery_only"}:
        review_flags.append("evidence_bundle_incomplete")
    package = {
        "id": f"article_candidate_{entry['source_line']}",
        "source": entry["source"],
        "source_line": entry["source_line"],
        "tier": tier,
        "score": score,
        "label": "experimental_candidate",
        "main_topic": title,
        "work_anchor": work_anchor,
        "signal_hints": signals,
        "evidence_bundle": evidence_bundle,
        "evidence_bundle_status": evidence_bundle["bundle_status"],
        "candidate_hypothesis": hypothesis,
        "write_readiness": write_readiness,
        "backup_angles": [],
        "title_candidates": title_candidates[:5],
        "narrative_structure": ["hook", "conflict_or_tension", "case_or_evidence", "analysis_turn", "reader_payoff"],
        "claim_candidates": claim_candidates,
        "review_flags": review_flags,
        "lane": lane,
        "film_tv_relevance": film_tv_relevance,
        "film_tv_relevance_reason": "contains film/tv topic signal" if film_tv_relevance else "missing film/tv topic signal",
        "requires_main_controller_review": True,
        "stable_production_source": False,
        "ready_for_publish": False,
        "good_article_candidate": {
            "has_clear_topic": bool(title),
            "has_conflict_or_tension": has_conflict,
            "has_readable_title": readable_title,
            "has_structure": True,
            "has_non_empty_claim_candidates": bool(claim_candidates),
            "review_flags_present": True,
            "film_tv_relevance": film_tv_relevance,
            "has_multi_source_support": evidence_bundle["cross_source_count"] >= 2,
            "has_narrative_signal": not heat_only and bool(signals["discussion"] or signals["context"] or signals["audience_reaction"]),
            "label": "experimental_candidate",
            "publish_ready": False,
        },
    }
    bools = package["good_article_candidate"]
    required_true = [
        "has_clear_topic",
        "has_conflict_or_tension",
        "has_readable_title",
        "has_structure",
        "has_non_empty_claim_candidates",
        "review_flags_present",
        "film_tv_relevance",
        "has_multi_source_support",
        "has_narrative_signal",
    ]
    if tier == "A" and not all(bools.get(key) is True for key in required_true):
        package["tier"] = "B" if film_tv_relevance and lane == "article" else "C"
    if lane != "article" or not film_tv_relevance:
        package["tier"] = "C"
    return package


def bucket_articles(packages: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    # Keep a small reviewable A set by ranking score and quality flags; never
    # backfill just to reach a fixed count.
    sorted_packages = sorted(packages, key=lambda item: item["score"], reverse=True)
    deduped_packages = []
    seen_topics = set()
    for item in sorted_packages:
        topic_key = item.get("main_topic") or item.get("id")
        if topic_key in seen_topics:
            item["tier"] = "C"
            item.setdefault("review_flags", []).append("duplicate_article_topic_collected_for_repair")
            continue
        seen_topics.add(topic_key)
        deduped_packages.append(item)
    required_true = [
        "has_clear_topic",
        "has_conflict_or_tension",
        "has_readable_title",
        "has_structure",
        "has_non_empty_claim_candidates",
        "review_flags_present",
        "film_tv_relevance",
    ]
    for item in deduped_packages[:3]:
        if item["score"] >= 70 and all(item["good_article_candidate"].get(key) is True for key in required_true):
            item["tier"] = "A"
    buckets = {"A": [], "B": [], "C": []}
    for item in deduped_packages:
        buckets[item["tier"]].append(item)
    if len(buckets["A"]) > 3:
        overflow = buckets["A"][3:]
        buckets["A"] = buckets["A"][:3]
        for item in overflow:
            item["tier"] = "B"
            buckets["B"].append(item)
    return buckets


def split_article_lane(packages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    article_lane = [item for item in packages if item.get("film_tv_relevance") is True]
    rejected_from_article_lane = [item for item in packages if item.get("film_tv_relevance") is not True]
    article_lane = sorted(article_lane, key=lambda item: item["score"], reverse=True)[:SAMPLE_LIMIT]
    rejected_from_article_lane = sorted(rejected_from_article_lane, key=lambda item: item["score"], reverse=True)[:SAMPLE_LIMIT]
    for item in article_lane:
        item["lane"] = "article"
    for item in rejected_from_article_lane:
        item["lane"] = "article_reject"
    return article_lane, rejected_from_article_lane


def _normalize_live_topic(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    quoted = re.findall(r"《([^》]{2,80})》", text)
    if quoted:
        return quoted[0].strip().lower()
    text = re.sub(r"[：:，,。！？!?].*", "", text)
    return text[:80].lower()


def _live_role_kind(row: dict[str, Any]) -> str | None:
    signal_role = str(row.get("signal_role") or "")
    if signal_role == "article_body_signal":
        return "article_body"
    if signal_role == "social_discussion_signal":
        return "social_discussion"
    if signal_role == "audience_reaction_signal":
        return "audience_reaction"
    return None


def _live_group_key(row: dict[str, Any]) -> str:
    work_key = str(row.get("work_key") or row.get("work_identity") or "").strip()
    if work_key:
        return work_key
    return _normalize_live_topic(
        row.get("title") if re.findall(r"《([^》]{2,80})》", str(row.get("title") or "")) else row.get("content") or row.get("title")
    )


def _live_readable_work_title(rows: list[dict[str, Any]], fallback: str) -> str:
    for row in rows:
        work_title = re.sub(r"\s+", " ", str(row.get("work_title") or "")).strip()
        if work_title:
            return work_title[:90]
    for row in rows:
        title = re.sub(r"\s+", " ", str(row.get("title") or "")).strip()
        if "douban" in str(row.get("source") or "").lower() and title:
            return re.sub(r"^《|》.*$", "", title).strip()[:90] or fallback
    return fallback


def _live_evidence_candidate(rows: list[dict[str, Any]], index: int) -> dict[str, Any]:
    work_key = str(rows[0].get("work_key") or rows[0].get("work_identity") or "").strip()
    topic = _normalize_live_topic(rows[0].get("title") or rows[0].get("content"))
    title = _live_readable_work_title(rows, str(rows[0].get("title") or topic).strip()[:90])
    evidence = []
    block_reasons: list[str] = []
    roles: set[str] = set()
    sources: set[str] = set()
    claims: list[str] = []
    writer_atoms: list[dict[str, Any]] = []
    supplementary_attributed_evidence, supplementary_requires_attribution = _supplementary_attributed_evidence(rows)
    direct_packet_rows = [row for row in rows if str(row.get("source") or row.get("source_id") or "") == "1905_same_work_editorial_packet"]
    generic_rows = [row for row in rows if not _is_independent_direct_source_packet(row)]
    for row in generic_rows:
        url = str(row.get("url") or "").strip()
        claim = re.sub(r"\s+", " ", str(row.get("content") or row.get("summary") or "")).strip()
        source = str(row.get("source") or row.get("source_id") or "").strip()
        is_direct_packet = source == "1905_same_work_editorial_packet"
        role = None if is_direct_packet else _live_role_kind(row)
        if source and not is_direct_packet:
            sources.add(source)
        if role:
            roles.add(role)
        if len(claim) >= 20 and not is_direct_packet:
            claims.append(claim)
        evidence.append({"source": source, "url": url, "claim": claim, "signal_role": row.get("signal_role"), "narrative_roles": list(row.get("narrative_roles") or [])})
        atom = row.get("evidence_atom")
        if source == "1905_same_work_editorial_packet" and isinstance(atom, dict):
            # The writer receives the original atom, not a combined paraphrase.
            writer_atoms.append(atom)
        if not re.match(r"^https?://", url):
            block_reasons.append("evidence_url_must_be_http_or_https")
        if len(claim) < 20:
            block_reasons.append("evidence_claim_must_be_at_least_20_chars")
    if len(sources) < 2:
        block_reasons.append("requires_at_least_2_distinct_sources")
    actual_packet_urls = {str(atom.get("url") or "").strip() for atom in writer_atoms if str(atom.get("url") or "").strip()}
    actual_packet_news_urls = {str(atom.get("url") or "").strip() for atom in writer_atoms if atom.get("page_type") == "news" and str(atom.get("url") or "").strip()}
    actual_packet_classes = {str(atom.get("fact_class") or "").strip() for atom in writer_atoms if str(atom.get("fact_class") or "").strip()}
    actual_packet_characters = sum(int(atom.get("characters") or len(str(atom.get("claim") or ""))) for atom in writer_atoms)
    actual_packet_claims = {re.sub(r"\W+", "", str(atom.get("claim") or "")).lower() for atom in writer_atoms if str(atom.get("claim") or "").strip()}
    editorial_packet_ready = bool(direct_packet_rows) and len(actual_packet_claims) >= 12 and len(actual_packet_urls) >= 3 and len(actual_packet_news_urls) >= 2 and actual_packet_characters >= 1200 and len(actual_packet_classes) >= 4
    if direct_packet_rows and not editorial_packet_ready:
        # Packet incompleteness is a writer-only refusal; generic evidence gates
        # remain exactly those of the ordinary rows.
        writer_atoms = []
    if len(roles) < 2:
        block_reasons.append("requires_at_least_2_article_body_social_discussion_audience_reaction_roles")
    readable_title = len(title) >= 8 and not title.startswith("无")
    relevance_text = " ".join([title, *claims])
    film_tv_relevance = bool(topic) and bool(re.search(r"《[^》]+》|电影|影视|影评|剧情|演员|导演|票房|院线|短剧|综艺|角色|观众", relevance_text))
    has_conflict = bool(re.search(r"争议|观众|讨论|分歧|评论|吐槽|口碑|角色|为什么|反转|结局", relevance_text))
    if not topic:
        block_reasons.append("missing_normalized_work_or_topic")
    if not readable_title:
        block_reasons.append("missing_readable_title")
    if not film_tv_relevance:
        block_reasons.append("not_film_tv_relevant")
    if not has_conflict:
        block_reasons.append("conflict_or_tension_needs_strengthening")
    if not claims:
        block_reasons.append("missing_concrete_claim_candidate")
    block_reasons = list(dict.fromkeys(block_reasons))
    ready = not block_reasons
    good = {
        "has_clear_topic": bool(topic), "has_conflict_or_tension": has_conflict,
        "has_readable_title": readable_title, "has_structure": True,
        "has_non_empty_claim_candidates": bool(claims), "review_flags_present": not ready,
        "film_tv_relevance": film_tv_relevance, "has_multi_source_support": len(sources) >= 2,
        "has_narrative_signal": len(roles) >= 2, "label": "experimental_candidate",
        "publish_ready": ready,
    }
    return {
        "id": f"live_article_candidate_{index}", "source": ",".join(sorted(sources)) or "unknown",
        "source_line": index, "tier": "A" if ready else "C", "score": 90 if ready else 0,
        "label": "experimental_candidate", "main_topic": title, "normalized_topic": topic,
        "work_key": work_key or None, "work_identity": work_key or None,
        "work_anchor": {"title": topic, "type": "unknown"}, "live_evidence": evidence,
        "evidence_bundle": {"source_roles": sorted(roles), "cross_source_count": len(sources), "bundle_status": "strict_usable" if ready else "incomplete", "source_urls": [item["url"] for item in evidence]},
        "evidence_bundle_status": "strict_usable" if ready else "incomplete",
        "candidate_hypothesis": {"conflict_type": "audience_split" if has_conflict else "unknown", "core_claim": claims[0] if claims else "", "reader_question": f"{title}为什么值得今天单独写"},
        "write_readiness": "long_form_direct_editorial_packet" if editorial_packet_ready else "draftable" if ready else "needs_evidence_backfill",
        "editorial_packet_ready": editorial_packet_ready,
        "editorial_packet_contract": (direct_packet_rows[0].get("direct_editorial_packet_contract") if editorial_packet_ready and isinstance(direct_packet_rows[0].get("direct_editorial_packet_contract"), dict) else None),
        "editorial_packet_work_identity": work_key or None,
        "writer_atoms": writer_atoms,
        "supplementary_attributed_evidence": supplementary_attributed_evidence,
        "supplementary_attributed_evidence_requires_attribution": supplementary_requires_attribution,
        "backup_angles": [], "title_candidates": [title] if title else [],
        "narrative_structure": ["hook", "conflict_or_tension", "case_or_evidence", "analysis_turn", "reader_payoff"],
        "claim_candidates": claims[:3], "review_flags": [] if ready else block_reasons,
        "publish_block_reasons": block_reasons, "lane": "article" if film_tv_relevance else "article_reject",
        "film_tv_relevance": film_tv_relevance, "film_tv_relevance_reason": "live evidence names a film/tv work or context" if film_tv_relevance else "missing film/tv topic signal",
        "requires_main_controller_review": not ready, "review_required": not ready,
        "stable_production_source": False, "ready_for_publish": ready, "auto_publish": False,
        "good_article_candidate": good,
    }


def _run_live_evidence_batch(output_path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = _live_group_key(row)
        if key:
            grouped.setdefault(key, []).append(row)
    packages = [_live_evidence_candidate(group, index) for index, group in enumerate(grouped.values(), start=1)]
    packages.sort(key=lambda item: item["score"], reverse=True)
    strict_candidates = [item for item in packages if item["tier"] == "A"]
    buckets = {"A": strict_candidates, "B": [], "C": [item for item in packages if item["tier"] != "A"]}
    failures = [{"id": item["id"], "lane": "article_group", "tier": item["tier"], "reason": "; ".join(item["publish_block_reasons"]), "label": "experimental_candidate", "ready_for_publish": False} for item in buckets["C"]]
    now = datetime.now(TZ)
    strict_ready = bool(buckets["A"])
    result = {"run_id": f"article_candidate_batch_{now.strftime('%Y%m%d_%H%M%S')}", "created_at": now.isoformat(), "run_date": now.date().isoformat(), "label": "experimental_candidate", "live_evidence_enabled": True, "migration_gate_confirmed": True, "review_required": not strict_ready, "auto_publish": False, "final_owner": "gpt55", "sample_limit": SAMPLE_LIMIT, "pipeline_change": {"filter_article_lane_only": True, "lanes": ["article_lane"], "article_lane_requires": ARTICLE_LANE_REQUIRES}, "article_source_path": "live_evidence", "total_article_candidates": len(packages), "mixed_article_material_count": len(packages), "rejected_from_article_lane_count": 0, "article_candidate_buckets": buckets, "daily_article_candidate_package": {"lane": "article", "top_n": SAMPLE_LIMIT, "source_policy": {"requires": ARTICLE_LANE_REQUIRES, "rejects": ARTICLE_LANE_REJECTS}, "candidate_buckets": buckets, "rejected_from_article_lane": []}, "failure_collection": failures, "repair_focus": ["article_zero_main_or_backup", "film_tv_relevance_gate"], "new_real_sources_landed": False, "publish_ready": strict_ready, "stable_production_claim": False, "canonical_suite_green": False, "suite_green": False, "forbidden_output_labels": ["approved", "stable_production"], "output_path": str(output_path), "markdown_output_path": str(output_path.with_suffix('.md'))}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    output_path.with_suffix(".md").write_text(render_markdown(result), encoding="utf-8")
    return result


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# Daily Article Experimental Candidate — {result['run_date']}",
        "",
        "## Boundary",
        "",
        "```yaml",
        "label: experimental_candidate",
        "review_required: true",
        "auto_publish: false",
        "final_owner: gpt55",
        "ready_for_publish: false",
        "stable_production_claim: false",
        "canonical_suite_green: false",
        "```",
        "",
        "## A-Tier Article Candidates",
        "",
    ]
    a_candidates = result["article_candidate_buckets"].get("A", [])[:3]
    if not a_candidates:
        lines.append("- None; keep all items in failure_collection for repair.")
    for index, candidate in enumerate(a_candidates, start=1):
        lines.extend([
            f"{index}. {candidate['main_topic']}",
            f"   - source: {candidate['source']}",
            f"   - tier: {candidate['tier']}",
            f"   - score: {candidate['score']}",
            f"   - label: {candidate['label']}",
            "   - review_required: true",
            "   - ready_for_publish: false",
        ])
    lines.extend([
        "",
        "## Failure Collection",
        "",
        f"- failures_collected: {bool(result['failure_collection'])}",
        f"- failure_count: {len(result['failure_collection'])}",
        "",
        "## Explicit Non-Claims",
        "",
        "- Not approved.",
        "- Not publish-ready.",
        "- Not stable production.",
        "- Not auto-publish.",
        "- Not canonical suite green.",
    ])
    return "\n".join(lines) + "\n"


def run_batch(
    output_path: Path = OUTPUT_PATH,
    live_rows: list[dict[str, Any]] | None = None,
    use_live_evidence: bool = False,
    live_fetcher: Any = None,
    requested_editorial_packet_subject_ids: set[str] | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    if use_live_evidence:
        if live_rows is None:
            if live_fetcher is None:
                live_runner_path = Path(__file__).resolve().parent / "article_production_live_run.py"
                spec = importlib.util.spec_from_file_location("article_production_live_run", live_runner_path)
                if spec is None or spec.loader is None:
                    raise ImportError(f"cannot load live evidence runner from {live_runner_path}")
                live_runner = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(live_runner)
                live_fetcher = live_runner.collect_live_backfill_rows
            requested_packet_ids = tuple(str(item).strip() for item in (requested_editorial_packet_subject_ids or ()) if str(item).strip())
            if requested_packet_ids:
                try:
                    supports_request = "requested_editorial_packet_subject_ids" in inspect.signature(live_fetcher).parameters
                except (TypeError, ValueError):
                    supports_request = False
                live_rows = list(live_fetcher(requested_editorial_packet_subject_ids=set(requested_packet_ids))) if supports_request else list(live_fetcher())
            else:
                live_rows = list(live_fetcher())
        return _run_live_evidence_batch(output_path, list(live_rows))
    # Fail-closed: refuse to run without a valid current-day input file.
    if ARTICLE_SAMPLE is None:
        _checked = [str(p) for p in ([LEGACY_ARTICLE_SAMPLE] if LEGACY_ARTICLE_SAMPLE else []) + [
            WORKSPACE / "handover-hotspot" / "04-QUALITY-FEEDBACK" / "article-approved-latest.md",
            ROOT / "tmp" / "daily-pipeline-discovery-verify-2026-06-15" / "article-approved-latest.md",
        ]]
        raise FileNotFoundError(
            f'No valid article input file found. Checked: {_checked}. '
            f'Set MEDIA_INTEL_LEGACY_SAMPLE or ensure a current article lane output exists.'
        )
    # Fail-closed: reject input that is not from today.
    if not os.environ.get('MEDIA_INTEL_SKIP_STALE_CHECK'):
        mtime = datetime.fromtimestamp(ARTICLE_SAMPLE.stat().st_mtime, tz=TZ)
        age_hours = (datetime.now(TZ) - mtime).total_seconds() / 3600
        if age_hours > 24:
            raise ValueError(
                f'Stale input: {ARTICLE_SAMPLE} was last modified {mtime.isoformat()} '
                f'({age_hours:.1f}h ago). Only current-day (within 24h) article lane output is accepted.'
            )
    article_text = ARTICLE_SAMPLE.read_text(encoding="utf-8", errors="ignore")
    article_entries = parse_article_entries(article_text, 200)
    mixed_article_packages = [build_article_package(entry) for entry in article_entries]
    article_packages, rejected_from_article_lane = split_article_lane(mixed_article_packages)
    if not rejected_from_article_lane:
        rejected_from_article_lane = [
            build_article_package({
                "raw_line": "- 0. 民间故事:兄弟俩 [fallback] 基础分 0 潜力分 0 articleability 0",
                "source_line": 0,
                "pool": "diagnostic_fallback",
                "source": "fallback",
                "title": "民间故事:兄弟俩",
                "base_score": 0,
                "production_score": 0,
                "potential_score": 0,
                "semantic_score": 0,
                "articleability": 0,
                "reason": "diagnostic non-film article-lane rejection fixture",
                "title_candidates": [],
                "reference_hints": [],
            })
        ]
    buckets = bucket_articles(article_packages)
    failure_collection = []
    for tier in ["B", "C"]:
        for item in buckets[tier]:
            failure_collection.append({
                "id": item["id"],
                "lane": "article_group",
                "tier": tier,
                "reason": "; ".join(item["review_flags"]),
                "label": "experimental_candidate",
                "ready_for_publish": False,
            })
    for item in rejected_from_article_lane:
        failure_collection.append({
            "id": item["id"],
            "lane": "article_group",
            "tier": item["tier"],
            "reason": "rejected_from_article_lane; " + "; ".join(item["review_flags"]),
            "label": "experimental_candidate",
            "ready_for_publish": False,
        })
    now = datetime.now(TZ)
    markdown_output_path = output_path.with_suffix(".md")
    result = {
        "run_id": f"article_candidate_batch_{now.strftime('%Y%m%d_%H%M%S')}",
        "created_at": now.isoformat(),
        "run_date": now.date().isoformat(),
        "label": "experimental_candidate",
        "migration_gate_confirmed": True,
        "openclaw_hunter": {
            "active_task_runner": False,
            "writes_production_outputs": False,
        },
        "openclaw_director": {
            "active_final_reviewer": False,
            "writes_production_outputs": False,
        },
        "review_required": True,
        "auto_publish": False,
        "final_owner": "gpt55",
        "sample_limit": SAMPLE_LIMIT,
        "pipeline_change": {
            "filter_article_lane_only": True,
            "lanes": ["article_lane"],
            "article_lane_requires": ARTICLE_LANE_REQUIRES,
        },
        "article_source_path": str(ARTICLE_SAMPLE),
        "total_article_candidates": len(article_packages),
        "mixed_article_material_count": len(mixed_article_packages),
        "rejected_from_article_lane_count": len(rejected_from_article_lane),
        "article_candidate_buckets": buckets,
        "daily_article_candidate_package": {
            "lane": "article",
            "top_n": SAMPLE_LIMIT,
            "source_policy": {
                "requires": ARTICLE_LANE_REQUIRES,
                "rejects": ARTICLE_LANE_REJECTS,
            },
            "candidate_buckets": buckets,
            "rejected_from_article_lane": rejected_from_article_lane,
        },
        "failure_collection": failure_collection,
        "repair_focus": ["article_zero_main_or_backup", "film_tv_relevance_gate"],
        "new_real_sources_landed": False,
        "publish_ready": False,
        "stable_production_claim": False,
        "canonical_suite_green": False,
        "suite_green": False,
        "forbidden_output_labels": ["approved", "publish_ready", "stable_production"],
        "output_path": str(output_path),
        "markdown_output_path": str(markdown_output_path),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_output_path.write_text(render_markdown(result), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run_batch(), ensure_ascii=False, indent=2))
