#!/usr/bin/env python3
"""Run second-batch experimental article candidates.

Goal: turn scrubbed experimental samples into reviewable article candidate
packages, not publish-ready output. Reads the repository-local sample article
approved file, extracts article candidates, ranks A/B/C, and collects failures
for pipeline repair.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

TZ = timezone(timedelta(hours=8))
WORKSPACE = Path(__file__).resolve().parents[3]
ROOT = Path(__file__).resolve().parents[1]
ARTICLE_SAMPLE = ROOT / "article-vault" / "samples" / "experimental" / "article-approved-latest.md"
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


def build_article_package(entry: dict[str, Any]) -> dict[str, Any]:
    score = infer_articleability(entry)
    if score >= 75:
        tier = "A"
    elif score >= 60:
        tier = "B"
    else:
        tier = "C"
    title = entry["title"]
    conflict = bool(re.search(r"不如|为什么|争议|吐槽|反转|乱套|寒了心|离婚|问题|吵", title + entry.get("raw_line", "")))
    readable_title = len(title) >= 8 and not title.startswith("无")
    # Only use topic-facing text for the film/TV gate.  The raw source line may
    # include diagnostic notes like "影视映射弱或缺失"; treating those notes as
    # positive relevance signals can promote non-film social topics into A-tier.
    relevance_text = title
    film_tv_source = str(entry.get("source", "")).lower() in {
        "douban_review",
        "douban",
        "dumou",
        "guduo",
        "maoyan",
        "tencent_platform",
        "bilibili",
        "douyin",
    }
    film_tv_relevance = film_tv_source or bool(re.search(r"电影|影视|影评|剧情|演员|导演|票房|院线|短剧|综艺|豆瓣|猫眼|片单|角色|观众", relevance_text))
    if re.search(r"民间故事|婚内单身|最棒的故事是哪一个", relevance_text):
        film_tv_relevance = False
    title_candidates = entry.get("title_candidates") or [
        title,
        f"{title}，真正的问题到底出在哪？",
        f"从{title[:24]}往后看，这类内容为什么反复出现？",
    ]
    claim_candidates = [
        f"{title}背后有可讨论的情绪或结构性矛盾",
        entry.get("reason") or "候选已有可改写结构，但需要主控复核",
    ]
    review_flags = ["experimental_candidate_requires_gpt55_review", "facts_and_platform_context_need_manual_check"]
    if score < 75:
        review_flags.append("below_a_tier_threshold_collect_for_pipeline_repair")
    if not conflict:
        review_flags.append("conflict_or_tension_needs_strengthening")
    if not film_tv_relevance:
        review_flags.append("not_film_tv_relevant")
    package = {
        "id": f"article_candidate_{entry['source_line']}",
        "source": entry["source"],
        "source_line": entry["source_line"],
        "tier": tier,
        "score": score,
        "label": "experimental_candidate",
        "main_topic": title,
        "backup_angles": [
            "结构性角度：从单个热点拉到平台/行业/人群机制",
            "反常识角度：先找最容易被忽略的判断差",
            "案例切入角度：用具体作品/人物/评论区补证据",
        ],
        "title_candidates": title_candidates[:5],
        "narrative_structure": ["hook", "conflict_or_tension", "case_or_evidence", "analysis_turn", "reader_payoff"],
        "claim_candidates": claim_candidates,
        "review_flags": review_flags,
        "lane": "article" if film_tv_relevance else "article_reject",
        "film_tv_relevance": film_tv_relevance,
        "film_tv_relevance_reason": "contains film/tv topic signal" if film_tv_relevance else "missing film/tv topic signal",
        "requires_main_controller_review": True,
        "stable_production_source": False,
        "ready_for_publish": False,
        "good_article_candidate": {
            "has_clear_topic": bool(title),
            "has_conflict_or_tension": conflict or score >= 75,
            "has_readable_title": readable_title,
            "has_structure": True,
            "has_non_empty_claim_candidates": True,
            "review_flags_present": True,
            "film_tv_relevance": film_tv_relevance,
            "label": "experimental_candidate",
            "publish_ready": False,
        },
    }
    # A tier requires all quality booleans except publish_ready to be true; if not, downgrade.
    bools = package["good_article_candidate"]
    required_true = [
        "has_clear_topic",
        "has_conflict_or_tension",
        "has_readable_title",
        "has_structure",
        "has_non_empty_claim_candidates",
        "review_flags_present",
        "film_tv_relevance",
    ]
    if tier == "A" and not all(bools.get(key) is True for key in required_true):
        package["tier"] = "B" if film_tv_relevance else "C"
    if not film_tv_relevance:
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


def run_batch(output_path: Path = OUTPUT_PATH) -> dict[str, Any]:
    article_text = ARTICLE_SAMPLE.read_text(encoding="utf-8", errors="ignore")
    article_entries = parse_article_entries(article_text, 200)
    mixed_article_packages = [build_article_package(entry) for entry in article_entries]
    article_packages, rejected_from_article_lane = split_article_lane(mixed_article_packages)
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
