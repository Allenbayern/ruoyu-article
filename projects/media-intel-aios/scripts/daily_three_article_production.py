#!/usr/bin/env python3
"""Strict, offline daily three-article production gate.

Consumes explicit article/evidence packets only.  It neither fetches nor generates
content, touches cron, sends messages, or publishes.  All three slots must pass
before any run is marked final/publish_ready.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SLOTS = ("A", "B", "C")
MIN_CHINESE_CHARS = 1500
MAX_CHINESE_CHARS = 2200
SAFE_TAGS = {"p", "strong", "em", "br"}
TAG_RE = re.compile(r"</?([a-zA-Z0-9]+)(?:\s[^>]*)?>")


def chinese_character_count(text: str) -> int:
    """Count only CJK Unified Ideographs; punctuation/Latin/markup do not count."""
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def safe_html(title: str, body: str) -> str:
    escaped_title = html.escape(title, quote=False)
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", body.strip()) if part.strip()]
    return "<p><strong>" + escaped_title + "</strong></p>" + "".join(
        "<p>" + html.escape(paragraph, quote=False) + "</p>" for paragraph in paragraphs
    )


def html_is_safe(value: str) -> bool:
    lowered = value.lower()
    if any(token in lowered for token in ("<script", "javascript:", "<iframe", "<form", "onerror=", "onclick=")):
        return False
    return all(match.group(1).lower() in SAFE_TAGS for match in TAG_RE.finditer(value))


def validate_packet(packet: Any) -> tuple[list[str], dict[str, Any] | None]:
    if not isinstance(packet, dict):
        return ["INVALID_PACKET"], None
    required_text = ("id", "work_key", "origin_packet_id", "topic_key", "angle_key", "headline", "body")
    missing = [name for name in required_text if not isinstance(packet.get(name), str) or not packet[name].strip()]
    if missing or "evidence" not in packet:
        return ["MISSING_REQUIRED_FIELD"], None
    evidence = packet["evidence"]
    if not isinstance(evidence, dict):
        return ["INVALID_EVIDENCE"], None
    sources = evidence.get("sources")
    claims = evidence.get("claims")
    if not isinstance(sources, list) or not sources or not isinstance(claims, list) or not claims:
        return ["MISSING_CLAIM_SOURCE_MAPPING"], None
    source_index: dict[str, dict[str, str]] = {}
    for source in sources:
        if not isinstance(source, dict) or any(not isinstance(source.get(k), str) or not source[k].strip() for k in ("source_id", "url", "quote", "locator")):
            return ["MISSING_SOURCE_LOCATION"], None
        if any(not isinstance(source.get(k), str) or not source[k].strip() for k in ("work_key", "origin_packet_id", "origin_packet_sha256")):
            return ["MISSING_PROVENANCE_MAPPING"], None
        if source["work_key"] != packet["work_key"] or source["origin_packet_id"] != packet["origin_packet_id"]:
            return ["CLAIM_SOURCE_PROVENANCE_MISMATCH"], None
        source_index[source["source_id"]] = source
    for claim in claims:
        if not isinstance(claim, dict) or any(not isinstance(claim.get(k), str) or not claim[k].strip() for k in ("claim_id", "text", "source_id", "locator")):
            return ["MISSING_CLAIM_SOURCE_MAPPING"], None
        if any(not isinstance(claim.get(k), str) or not claim[k].strip() for k in ("work_key", "origin_packet_id", "origin_packet_sha256")):
            return ["MISSING_PROVENANCE_MAPPING"], None
        source = source_index.get(claim["source_id"])
        if source is None or source["locator"] != claim["locator"] or claim["text"] not in source["quote"]:
            return ["CLAIM_SOURCE_LOCATOR_MISMATCH"], None
        if any(claim[key] != source[key] for key in ("work_key", "origin_packet_id", "origin_packet_sha256")) or claim["work_key"] != packet["work_key"] or claim["origin_packet_id"] != packet["origin_packet_id"]:
            return ["CLAIM_SOURCE_PROVENANCE_MISMATCH"], None
    count = chinese_character_count(packet["body"])
    if not MIN_CHINESE_CHARS <= count <= MAX_CHINESE_CHARS:
        return ["CHINESE_CHARACTER_COUNT_OUT_OF_RANGE"], None
    rendered = safe_html(packet["headline"], packet["body"])
    if not html_is_safe(rendered):
        return ["HTML_SANITIZATION_FAILED"], None
    return [], {"chinese_character_count": count, "html": rendered}


def attempt_record(packet: Any, codes: list[str], details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "packet_id": packet.get("id") if isinstance(packet, dict) else None,
        "approved_evergreen": bool(packet.get("approved_evergreen", False)) if isinstance(packet, dict) else False,
        "status": "passed" if not codes else "failed",
        "failure_codes": codes,
        **(details or {}),
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(input_data: dict[str, Any], output: Path) -> int:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    events: list[dict[str, Any]] = []
    slot_results: dict[str, dict[str, Any]] = {}
    selected: dict[str, dict[str, Any]] = {}
    used_topics: set[str] = set()
    used_angles: set[str] = set()
    used_work_keys: set[str] = set()
    used_claim_ids: set[str] = set()

    raw_slots = input_data.get("slots") if isinstance(input_data, dict) else None
    for slot in SLOTS:
        attempts: list[dict[str, Any]] = []
        candidates = raw_slots.get(slot) if isinstance(raw_slots, dict) else None
        regular_count = len(candidates) if isinstance(candidates, list) else 0
        evergreen_pool = input_data.get("approved_evergreen_pool") if isinstance(input_data, dict) else None
        evergreen_candidates = evergreen_pool.get(slot) if isinstance(evergreen_pool, dict) else []
        if not isinstance(evergreen_candidates, list):
            evergreen_candidates = []
        if isinstance(candidates, list):
            candidates = [*candidates, *evergreen_candidates]
        elif evergreen_candidates:
            candidates = evergreen_candidates
        choice: dict[str, Any] | None = None
        choice_details: dict[str, Any] | None = None
        if not isinstance(candidates, list) or not candidates:
            attempts.append(attempt_record({}, ["MISSING_SLOT_PACKET"]))
        else:
            for index, packet in enumerate(candidates):
                codes, details = validate_packet(packet)
                if index >= regular_count and (not isinstance(packet, dict) or packet.get("approved_evergreen") is not True):
                    codes = ["EVERGREEN_NOT_APPROVED", *codes]
                if not codes and (packet["topic_key"] in used_topics or packet["angle_key"] in used_angles):
                    codes = ["DUPLICATE_TOPIC_OR_ANGLE"]
                if not codes and (
                    packet["work_key"] in used_work_keys
                    or any(claim["claim_id"] in used_claim_ids for claim in packet["evidence"]["claims"])
                ):
                    codes = ["DUPLICATE_WORK_OR_ATOM_ACROSS_SLOTS"]
                attempts.append(attempt_record(packet, codes, details))
                if not codes:
                    choice, choice_details = packet, details
                    if index:
                        events.append({"at": datetime.now(timezone.utc).isoformat(), "event": "slot_replaced", "slot": slot, "replaced_ids": [item["packet_id"] for item in attempts[:-1]], "selected_id": packet["id"]})
                    break
        slot_dir = output / "slots" / slot
        if choice is None:
            failure_codes = sorted({code for attempt in attempts for code in attempt["failure_codes"]}) or ["MISSING_SLOT_PACKET"]
            result = {"status": "failed", "selected_id": None, "replacements": [], "failure_codes": failure_codes, "attempts": attempts}
            write_json(slot_dir / "draft.json", result)
        else:
            used_topics.add(choice["topic_key"])
            used_angles.add(choice["angle_key"])
            used_work_keys.add(choice["work_key"])
            used_claim_ids.update(claim["claim_id"] for claim in choice["evidence"]["claims"])
            replacements = [item["packet_id"] for item in attempts[:-1]]
            evidence = choice["evidence"]
            write_json(slot_dir / "evidence.json", evidence)
            (slot_dir / "article.html").parent.mkdir(parents=True, exist_ok=True)
            (slot_dir / "article.html").write_text(choice_details["html"] + "\n", encoding="utf-8")
            (slot_dir / "article.md").write_text("# " + choice["headline"] + "\n\n" + choice["body"] + "\n", encoding="utf-8")
            result = {"status": "passed", "selected_id": choice["id"], "replacements": replacements, "failure_codes": [], "attempts": attempts, "chinese_character_count": choice_details["chinese_character_count"]}
            selected[slot] = choice
        slot_results[slot] = result
        events.append({"at": datetime.now(timezone.utc).isoformat(), "event": "slot_evaluated", "slot": slot, "status": result["status"]})

    all_passed = len(selected) == 3
    manifest = {
        "run_id": input_data.get("run_id") if isinstance(input_data, dict) else None,
        "status": "final" if all_passed else "failed",
        "publish_ready": all_passed,
        "publication_performed": False,
        "final_article_ids": [selected[slot]["id"] for slot in SLOTS] if all_passed else [],
        "slots": slot_results,
        "artifact_hashes": {},
    }
    if all_passed:
        for slot in SLOTS:
            for filename in ("evidence.json", "article.md", "article.html"):
                path = output / "slots" / slot / filename
                manifest["artifact_hashes"][str(path.relative_to(output))] = sha256_file(path)
    events.append({"at": datetime.now(timezone.utc).isoformat(), "event": "run_completed", "status": manifest["status"], "publish_ready": all_passed})
    write_json(output / "manifest.json", manifest)
    audit_path = output / "audit" / "events.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text("".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events), encoding="utf-8")
    return 0 if all_passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="严格离线每日三篇影视文章生产门禁；不联网、不发布。")
    parser.add_argument("--input", required=True, type=Path, help="显式 article/evidence packet JSON")
    parser.add_argument("--output", required=True, type=Path, help="本次运行输出目录（会被替换）")
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        parser.error(f"无法读取 input JSON：{error}")
    if not isinstance(data, dict):
        parser.error("input JSON 根节点必须为对象")
    return run(data, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
