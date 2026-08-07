#!/usr/bin/env python3
"""Offline, fail-closed adapter from verified evidence atoms to daily3 gate packets.

It consumes only explicit JSON.  It never fetches, generates text, publishes, or
marks any output final.  Every body fact must be explicitly tagged ``【事实】`` and
listed in ``factual_claims``; each list entry must exactly match one supplied atom.
Analytical prose may remain untagged, but is never emitted as evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

SLOTS = ("A", "B", "C")
REQUIRED_DRAFT_TEXT = ("id", "work_key", "origin_packet_id", "topic_key", "angle_key", "headline", "body")
REQUIRED_ATOM_TEXT = ("id", "work_key", "origin_packet_id", "origin_packet_sha256", "claim", "source_text", "source_locator", "url", "page_type", "published_at", "fact_class")
REQUIRED_SOURCE_METADATA = ("institution", "source_program", "author", "reporters", "editors", "published_at")


class AdapterError(ValueError):
    """A user-supplied input cannot safely become a daily3 packet."""


def require_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdapterError(code)
    return value.strip()


def atom_value(value: Any, name: str, code: str) -> str | None:
    if name == "published_at" and value is None:
        return None
    return require_text(value, code)


def atom_index(raw_atoms: Any) -> dict[str, dict[str, str]]:
    if not isinstance(raw_atoms, list) or not raw_atoms:
        raise AdapterError("MISSING_EVIDENCE_ATOMS")
    indexed: dict[str, dict[str, str]] = {}
    for raw_atom in raw_atoms:
        if not isinstance(raw_atom, dict):
            raise AdapterError("INVALID_EVIDENCE_ATOM")
        atom = {name: atom_value(raw_atom.get(name), name, "INVALID_EVIDENCE_ATOM") for name in REQUIRED_ATOM_TEXT}
        metadata = raw_atom.get("source_metadata")
        if metadata is not None:
            if not isinstance(metadata, dict) or set(metadata) != set(REQUIRED_SOURCE_METADATA):
                raise AdapterError("INVALID_SOURCE_METADATA")
            if not isinstance(metadata["institution"], str) or not metadata["institution"].strip():
                raise AdapterError("INVALID_SOURCE_METADATA")
            if metadata["source_program"] is not None and (not isinstance(metadata["source_program"], str) or not metadata["source_program"].strip()):
                raise AdapterError("INVALID_SOURCE_METADATA")
            if metadata["author"] is not None and (not isinstance(metadata["author"], str) or not metadata["author"].strip()):
                raise AdapterError("INVALID_SOURCE_METADATA")
            if not all(isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value) for value in (metadata["reporters"], metadata["editors"])):
                raise AdapterError("INVALID_SOURCE_METADATA")
            if metadata["published_at"] is not None and (not isinstance(metadata["published_at"], str) or not metadata["published_at"].strip()):
                raise AdapterError("INVALID_SOURCE_METADATA")
            atom["source_metadata"] = metadata
        if atom["claim"] not in atom["source_text"]:
            raise AdapterError("ATOM_CLAIM_SOURCE_TEXT_MISMATCH")
        if atom["id"] in indexed:
            raise AdapterError("DUPLICATE_EVIDENCE_ATOM_ID")
        indexed[atom["id"]] = atom
    return indexed


def packet_from_draft(raw_draft: Any, atoms: dict[str, dict[str, str]]) -> dict[str, Any]:
    if not isinstance(raw_draft, dict):
        raise AdapterError("INVALID_DRAFT")
    draft = {name: require_text(raw_draft.get(name), "MISSING_DRAFT_FIELD") for name in REQUIRED_DRAFT_TEXT}
    raw_claims = raw_draft.get("factual_claims")
    if not isinstance(raw_claims, list):
        raise AdapterError("MISSING_FACTUAL_CLAIMS")

    claims: list[dict[str, str]] = []
    marked_facts: list[str] = []
    for line in draft["body"].splitlines():
        if line.startswith("【事实】"):
            marked_facts.append(require_text(line.removeprefix("【事实】"), "EMPTY_MARKED_FACT"))
    if len(marked_facts) != len(raw_claims) or not marked_facts:
        raise AdapterError("UNMAPPED_OR_UNMARKED_FACTUAL_CLAIM")

    used_atom_ids: set[str] = set()
    sources: list[dict[str, str]] = []
    used_source_ids: set[str] = set()
    for raw_claim in raw_claims:
        if not isinstance(raw_claim, dict):
            raise AdapterError("INVALID_FACTUAL_CLAIM")
        atom_id = require_text(raw_claim.get("atom_id"), "INVALID_FACTUAL_CLAIM")
        if atom_id in used_atom_ids:
            raise AdapterError("DUPLICATE_FACTUAL_CLAIM_ATOM_ID")
        used_atom_ids.add(atom_id)
        text = require_text(raw_claim.get("text"), "INVALID_FACTUAL_CLAIM")
        atom = atoms.get(atom_id)
        if atom is None or text != atom["claim"] or text not in marked_facts:
            raise AdapterError("FACT_CLAIM_ATOM_MISMATCH")
        claims.append({"claim_id": atom_id, "text": text, "source_id": atom_id, "locator": atom["source_locator"], "work_key": atom["work_key"], "origin_packet_id": atom["origin_packet_id"], "origin_packet_sha256": atom["origin_packet_sha256"]})
        if atom_id not in used_source_ids:
            source = {"source_id": atom_id, "url": atom["url"], "quote": atom["claim"], "locator": atom["source_locator"], "work_key": atom["work_key"], "origin_packet_id": atom["origin_packet_id"], "origin_packet_sha256": atom["origin_packet_sha256"]}
            if "source_metadata" in atom:
                source["source_metadata"] = atom["source_metadata"]
            sources.append(source)
            used_source_ids.add(atom_id)

    if [claim["text"] for claim in claims] != marked_facts:
        raise AdapterError("UNMAPPED_OR_UNMARKED_FACTUAL_CLAIM")
    if any(draft["work_key"] != claim["work_key"] or draft["origin_packet_id"] != claim["origin_packet_id"] for claim in claims):
        raise AdapterError("DRAFT_WORK_ORIGIN_MISMATCH")
    packet: dict[str, Any] = {**draft, "evidence": {"sources": sources, "claims": claims}}
    if raw_draft.get("approved_evergreen") is True:
        packet["approved_evergreen"] = True
    return packet


def adapt(input_data: Any) -> dict[str, Any]:
    if not isinstance(input_data, dict):
        raise AdapterError("INVALID_INPUT")
    atoms = atom_index(input_data.get("evidence_atoms"))
    raw_slots = input_data.get("slots")
    if not isinstance(raw_slots, dict):
        raise AdapterError("MISSING_SLOTS")
    if any(slot not in SLOTS for slot in raw_slots):
        raise AdapterError("INVALID_SLOT_KEY")

    output: dict[str, Any] = {"slots": {}}
    if isinstance(input_data.get("run_id"), str) and input_data["run_id"].strip():
        output["run_id"] = input_data["run_id"].strip()
    for slot in SLOTS:
        candidates = raw_slots.get(slot)
        if not isinstance(candidates, list) or not candidates:
            raise AdapterError(f"MISSING_SLOT_{slot}")
        output["slots"][slot] = [packet_from_draft(candidate, atoms) for candidate in candidates]

    raw_pool = input_data.get("approved_evergreen_pool")
    if raw_pool is not None:
        if not isinstance(raw_pool, dict):
            raise AdapterError("INVALID_APPROVED_EVERGREEN_POOL")
        pool: dict[str, list[dict[str, Any]]] = {}
        for slot, candidates in raw_pool.items():
            if slot not in SLOTS or not isinstance(candidates, list):
                raise AdapterError("INVALID_APPROVED_EVERGREEN_POOL")
            packets = [packet_from_draft(candidate, atoms) for candidate in candidates]
            if any(packet.get("approved_evergreen") is not True for packet in packets):
                raise AdapterError("EVERGREEN_NOT_APPROVED")
            pool[slot] = packets
        output["approved_evergreen_pool"] = pool
    return output


def write_output_atomic(output_path: Path, result: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = temporary_file.name
            json.dump(result, temporary_file, ensure_ascii=False, indent=2, sort_keys=True)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, output_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            Path(temporary_path).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="将显式审验 evidence atoms 离线映射为 daily3 strict gate 输入；不联网、不生成、不标记 final。")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.input.resolve(strict=False) == args.output.resolve(strict=False):
            raise AdapterError("INPUT_OUTPUT_PATH_CONFLICT")
        if args.output.is_dir():
            raise AdapterError("OUTPUT_PATH_IS_DIRECTORY")
    except (OSError, AdapterError) as error:
        print(str(error), file=sys.stderr)
        return 1
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        result = adapt(data)
        write_output_atomic(args.output, result)
    except (OSError, json.JSONDecodeError, AdapterError) as error:
        try:
            if args.output.is_symlink() or args.output.is_file():
                args.output.unlink()
        except OSError:
            pass
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
