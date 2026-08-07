#!/usr/bin/env python3
"""Build the bounded F1/F3 repair artifact without touching the original candidate."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "outputs/daily3_today_source_research/20260720-repair-t_4571e854"
TARGET = ROOT / "outputs/daily3_today_source_research/20260720-repair-t_e67ffacb"
ORIGINAL = ROOT / "outputs/daily3_today_source_research/20260720-original-pre-t_e67ffacb"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def copy_original() -> None:
    original_source = ROOT / "outputs/daily3_today_source_research/20260720"
    if ORIGINAL.exists():
        shutil.rmtree(ORIGINAL)
    shutil.copytree(original_source, ORIGINAL)


def build_source_input() -> dict:
    source = json.loads((SOURCE / "source-input-candidate.json").read_text(encoding="utf-8"))
    raw_dir = TARGET / "raw-packets"
    for atom in source["evidence_atoms"]:
        subject = atom["origin_packet_id"].split("-")[2]
        atom["origin_packet_sha256"] = digest(raw_dir / f"{subject}.json")
    return source


def build_inventory(source: dict) -> dict:
    slots = source["slots"]
    candidates = []
    for slot in "ABC":
        draft = slots[slot][0]
        subject = draft["work_key"].rsplit(":", 1)[1]
        raw_path = TARGET / "raw-packets" / f"{subject}.json"
        packet = json.loads(raw_path.read_text(encoding="utf-8"))
        candidates.append({
            "slot": slot,
            "work_key": draft["work_key"],
            "work_identity": packet["work_identity"]["title"],
            "raw_packet": f"raw-packets/{subject}.json",
            "raw_packet_sha256": digest(raw_path),
            "source_page_count": len(packet["source_pages"]),
            "verified_source_pages": packet["source_pages"],
            "evidence_atom_count": len(packet["evidence_atoms"]),
        })
    return {
        "inventory_id": "daily3-today-source-repair-t_e67ffacb",
        "scope": "F1/F3-only repair; no historical delivery-ledger analysis, article generation, registry update, cron change, publication, or final acceptance",
        "original_preserved_at": str(ORIGINAL.relative_to(ROOT)),
        "candidate_status": "scoped_repair_for_independent_review",
        "work_identity_namespace": "1905:film:* verified by the preserved 1905 catalog identifiers; no 1905 identifier is labeled douban:*.",
        "f1_mapping": {
            "burning_dad": {
                "canonical_work_key": "1905:film:2258538",
                "alias_observed_in_page_01_html": "1905:film:2258416",
                "resolution": "2258416 is retained only as an observed page-link alias; candidate identity, raw packet, source input, adapter output, and bundle consistently use the explicit catalog identity 1905:film:2258538.",
            }
        },
        "f3_metadata_rule": "Metadata is transcribed from the preserved HTML. Unknown author/date is null; page dates are never inferred from image URLs.",
        "candidates": candidates,
        "coverage_gaps": [
            "F2 historical delivery-ledger proof is explicitly outside this repair card and has not been claimed or recomputed.",
            "No title/article prose was generated; this artifact is a source-input repair only.",
        ],
    }


def build_page_metadata_audit() -> list[dict]:
    rows = []
    for packet_path in sorted((TARGET / "raw-packets").glob("*.json")):
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        for page in packet["source_pages"]:
            rows.append({
                "work_key": packet["work_identity"]["work_key"],
                "canonical_url": page["canonical_url"],
                "page_sha256": page["page_sha256"],
                "institution": page["source_metadata"]["institution"],
                "source_program": page["source_metadata"]["source_program"],
                "author": page["source_metadata"]["author"],
                "reporters": page["source_metadata"]["reporters"],
                "editors": page["source_metadata"]["editors"],
                "published_at": page["source_metadata"]["published_at"],
            })
    return rows


def build_bundle(source_path: Path) -> dict:
    return {
        "bundle_id": "daily3-today-source-bundle-repair-t_e67ffacb",
        "created_at": "2026-07-21T00:00:00Z",
        "content_sha256": digest(source_path),
        "work_identities": ["1905:film:2258538", "1905:film:2259172", "1905:film:2259123"],
        "status": "scoped_repair_candidate_for_independent_review",
        "non_publication": True,
        "scope": ["F1", "F3"],
        "historical_delivery_ledger": "not_evaluated_out_of_scope",
        "source_input_path": "source-input-candidate.json",
        "raw_packet_paths": [f"raw-packets/{subject}.json" for subject in ("2258538", "2259172", "2259123")],
    }


def build_manifest() -> None:
    entries = []
    for path in sorted(TARGET.rglob("*")):
        if path.is_file() and path.name != "artifact-manifest.json":
            entries.append({"path": str(path.relative_to(TARGET)), "bytes": path.stat().st_size, "sha256": digest(path)})
    write_json(TARGET / "artifact-manifest.json", {
        "artifact_id": "daily3-today-source-repair-t_e67ffacb",
        "scope": ["F1", "F3"],
        "non_publication": True,
        "original_preserved_at": str(ORIGINAL.relative_to(ROOT)),
        "entries": entries,
    })


def main() -> None:
    copy_original()
    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.mkdir(parents=True)
    for name in ["raw-packets", "page-fetch-audit.json"] + [f"page-{number:02d}.html" for number in range(1, 10)]:
        source = SOURCE / name
        destination = TARGET / name
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
    source = build_source_input()
    write_json(TARGET / "source-input-candidate.json", source)
    write_json(TARGET / "research-inventory.json", build_inventory(source))
    write_json(TARGET / "page-metadata-audit.json", build_page_metadata_audit())
    write_json(TARGET / "source-bundle-candidate.json", build_bundle(TARGET / "source-input-candidate.json"))


if __name__ == "__main__":
    main()
