#!/usr/bin/env python3
"""Bounded, offline verifier for the daily3 1905 provenance chain.

Reads only supplied JSON/artifact paths; it never fetches, generates, publishes, or
labels a result final.  A report is atomically written only after every requested
phase verifies.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

SLOTS = ("A", "B", "C")

RAW_ATOM_FIELDS = ("claim", "source_text", "url", "source_locator", "page_type", "published_at", "fact_class")
PROVENANCE_FIELDS = ("work_key", "origin_packet_id", "origin_packet_sha256")
ORIGIN_RE = re.compile(r"^1905-editorial-(\d+)-20260718$")


class VerifyError(ValueError):
    pass


def text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VerifyError(code)
    return value.strip()


def atom_field(value: Any, field: str, code: str) -> str | None:
    if field == "published_at" and value is None:
        return None
    return text(value, code)


def load_json(path: Path, code: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VerifyError(f"{code}: {error}") from error


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def provenance(atom: dict[str, Any], code: str) -> dict[str, str]:
    # Current draft packets store these under provenance; flat fields are accepted
    # for the adapter's normalized representation.
    nested = atom.get("provenance")
    source = nested if isinstance(nested, dict) else atom
    return {field: text(source.get(field), code) for field in PROVENANCE_FIELDS}


def raw_packets(raw_dir: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, str]]:
    if not raw_dir.is_dir():
        raise VerifyError("RAW_DIR_NOT_DIRECTORY")
    packets: dict[str, dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    work_keys: dict[str, str] = {}
    for path in sorted(raw_dir.glob("*.json")):
        subject = path.stem
        if not subject.isdigit():
            raise VerifyError("INVALID_RAW_PACKET_FILENAME")
        packet = load_json(path, "INVALID_RAW_PACKET_JSON")
        if not isinstance(packet, dict) or packet.get("success") is not True or packet.get("status") != "focused_live_verified":
            raise VerifyError("RAW_PACKET_NOT_FOCUSED_LIVE_VERIFIED")
        if not isinstance(packet.get("evidence_atoms"), list):
            raise VerifyError("RAW_PACKET_MISSING_EVIDENCE_ATOMS")
        identity = packet.get("work_identity")
        if identity is None:
            # Legacy raw packets predate explicit identities. They remain readable
            # only in their original numeric-douban contract; a packet declaring
            # a canonical identity must be checked against it.
            work_key = f"douban:{subject}"
        else:
            if not isinstance(identity, dict):
                raise VerifyError("RAW_PACKET_MISSING_WORK_IDENTITY")
            work_key = text(identity.get("work_key"), "RAW_PACKET_INVALID_WORK_IDENTITY")
            if not re.fullmatch(r"(?:douban:\d+|1905:film:\d+)", work_key):
                raise VerifyError("RAW_PACKET_UNSUPPORTED_WORK_IDENTITY_NAMESPACE")
        packets[subject] = packet
        hashes[subject] = sha256(path)
        work_keys[subject] = work_key
    if not packets:
        raise VerifyError("RAW_PACKET_SET_EMPTY")
    return packets, hashes, work_keys


def verify_source(raw: dict[str, dict[str, Any]], hashes: dict[str, str], work_keys: dict[str, str], source_data: Any) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(source_data, dict) or not isinstance(source_data.get("evidence_atoms"), list):
        raise VerifyError("SOURCE_MISSING_EVIDENCE_ATOMS")
    atoms: dict[str, dict[str, Any]] = {}
    for source_atom in source_data["evidence_atoms"]:
        if not isinstance(source_atom, dict):
            raise VerifyError("INVALID_SOURCE_ATOM")
        atom_id = text(source_atom.get("id"), "INVALID_SOURCE_ATOM")
        if atom_id in atoms:
            raise VerifyError("DUPLICATE_SOURCE_ATOM_ID")
        prov = provenance(source_atom, "INVALID_SOURCE_PROVENANCE")
        match = ORIGIN_RE.fullmatch(prov["origin_packet_id"])
        if not match:
            raise VerifyError("INVALID_ORIGIN_PACKET_ID")
        subject = match.group(1)
        if subject not in raw:
            raise VerifyError("SOURCE_ORIGIN_PACKET_NOT_FOUND")
        if prov["work_key"] != work_keys[subject]:
            raise VerifyError("SOURCE_WORK_KEY_RAW_IDENTITY_MISMATCH")
        if prov["origin_packet_sha256"] != hashes[subject]:
            raise VerifyError("SOURCE_RAW_SHA256_MISMATCH")
        candidate_atoms = raw[subject]["evidence_atoms"]
        if not any(
            isinstance(candidate, dict)
            and all(source_atom.get(field) == candidate.get(field) for field in RAW_ATOM_FIELDS)
            and ("source_metadata" not in candidate or source_atom.get("source_metadata") == candidate["source_metadata"])
            for candidate in candidate_atoms
        ):
            raise VerifyError("SOURCE_ATOM_RAW_CONTENT_MISMATCH")
        source_metadata = source_atom.get("source_metadata")
        if source_metadata is not None and not isinstance(source_metadata, dict):
            raise VerifyError("INVALID_SOURCE_METADATA")
        atoms[atom_id] = {
            "id": atom_id,
            **{field: atom_field(source_atom.get(field), field, "INVALID_SOURCE_ATOM") for field in RAW_ATOM_FIELDS},
            **prov,
        }
        if source_metadata is not None:
            atoms[atom_id]["source_metadata"] = source_metadata

    slots = source_data.get("slots")
    if not isinstance(slots, dict) or set(slots) != set(SLOTS):
        raise VerifyError("SOURCE_SLOTS_MUST_BE_A_B_C")
    matrix: list[dict[str, Any]] = []
    cited_global: set[str] = set()
    for slot in SLOTS:
        drafts = slots[slot]
        if not isinstance(drafts, list) or len(drafts) != 1 or not isinstance(drafts[0], dict):
            raise VerifyError("SOURCE_SLOT_MUST_HAVE_ONE_DRAFT")
        draft = drafts[0]
        article_id = text(draft.get("id"), "INVALID_DRAFT")
        work_key = text(draft.get("work_key"), "INVALID_DRAFT")
        origin = text(draft.get("origin_packet_id"), "INVALID_DRAFT")
        angle = text(draft.get("angle_key"), "INVALID_DRAFT")
        factual = draft.get("factual_claims")
        if not isinstance(factual, list) or not factual:
            raise VerifyError("DRAFT_MISSING_FACTUAL_CLAIMS")
        atom_ids: list[str] = []
        for claim in factual:
            if not isinstance(claim, dict):
                raise VerifyError("INVALID_DRAFT_FACTUAL_CLAIM")
            atom_id = text(claim.get("atom_id"), "INVALID_DRAFT_FACTUAL_CLAIM")
            atom = atoms.get(atom_id)
            if atom is None or claim.get("text") != atom["claim"]:
                raise VerifyError("DRAFT_FACTUAL_CLAIM_SOURCE_MISMATCH")
            if atom["work_key"] != work_key or atom["origin_packet_id"] != origin:
                raise VerifyError("DRAFT_WORK_ORIGIN_ATOM_MISMATCH")
            if atom_id in cited_global:
                raise VerifyError("DUPLICATE_SLOT_ATOM_ID")
            cited_global.add(atom_id)
            atom_ids.append(atom_id)
        matrix.append({"slot": slot, "article_id": article_id, "work_key": work_key, "origin_packet_id": origin, "angle_key": angle, "atom_ids": atom_ids})
    if len({row["work_key"] for row in matrix}) != 3:
        raise VerifyError("THREE_DISTINCT_WORK_KEYS_REQUIRED")
    if len({row["angle_key"] for row in matrix}) != 3:
        raise VerifyError("THREE_DISTINCT_ANGLE_KEYS_REQUIRED")
    return atoms, matrix


def matching_atom(atom: dict[str, str], data: dict[str, Any], fields: tuple[str, ...], code: str) -> None:
    if any(data.get(field) != atom[field] for field in fields):
        raise VerifyError(code)


def one_packet(raw: Any, slot: str, code: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or not isinstance(raw.get("slots"), dict):
        raise VerifyError(code)
    candidates = raw["slots"].get(slot)
    if not isinstance(candidates, list) or len(candidates) != 1 or not isinstance(candidates[0], dict):
        raise VerifyError(code)
    return candidates[0]


def verify_adapter(adapter: Any, atoms: dict[str, dict[str, str]], matrix: list[dict[str, Any]]) -> None:
    for row in matrix:
        packet = one_packet(adapter, row["slot"], "INVALID_ADAPTER_SLOT")
        if packet.get("work_key") != row["work_key"] or packet.get("origin_packet_id") != row["origin_packet_id"]:
            raise VerifyError("ADAPTER_DRAFT_PROVENANCE_MISMATCH")
        evidence = packet.get("evidence")
        if not isinstance(evidence, dict) or not isinstance(evidence.get("claims"), list) or not isinstance(evidence.get("sources"), list):
            raise VerifyError("INVALID_ADAPTER_EVIDENCE")
        claims = evidence["claims"]
        if {claim.get("claim_id") for claim in claims if isinstance(claim, dict)} != set(row["atom_ids"]):
            raise VerifyError("ADAPTER_CLAIM_SET_MISMATCH")
        source_ids = set()
        for claim in claims:
            if not isinstance(claim, dict) or not isinstance(claim.get("claim_id"), str) or claim["claim_id"] not in atoms:
                raise VerifyError("ADAPTER_UNKNOWN_CLAIM")
            atom = atoms[claim["claim_id"]]
            matching_atom(atom, claim, ("work_key", "origin_packet_id", "origin_packet_sha256"), "ADAPTER_CLAIM_PROVENANCE_MISMATCH")
            if claim.get("text") != atom["claim"] or claim.get("source_id") != atom["id"] or claim.get("locator") != atom["source_locator"]:
                raise VerifyError("ADAPTER_CLAIM_CONTENT_MISMATCH")
            source_ids.add(atom["id"])
        sources = evidence["sources"]
        if {item.get("source_id") for item in sources if isinstance(item, dict)} != source_ids:
            raise VerifyError("ADAPTER_SOURCE_SET_MISMATCH")
        for item in sources:
            if not isinstance(item, dict) or not isinstance(item.get("source_id"), str) or item["source_id"] not in atoms:
                raise VerifyError("ADAPTER_UNKNOWN_SOURCE")
            atom = atoms[item["source_id"]]
            matching_atom(atom, item, ("work_key", "origin_packet_id", "origin_packet_sha256"), "ADAPTER_SOURCE_PROVENANCE_MISMATCH")
            if item.get("quote") != atom["claim"] or item.get("url") != atom["url"] or item.get("locator") != atom["source_locator"]:
                raise VerifyError("ADAPTER_SOURCE_CONTENT_MISMATCH")


def verify_gate(gate_path: Path, adapter: Any, matrix: list[dict[str, Any]]) -> None:
    gate = load_json(gate_path / "manifest.json" if gate_path.is_dir() else gate_path, "INVALID_GATE_OUTPUT")
    if not isinstance(gate, dict) or gate.get("status") != "final" or gate.get("publish_ready") is not True or gate.get("publication_performed") is not False:
        raise VerifyError("GATE_FINAL_MANIFEST_MISMATCH")
    root = gate_path if gate_path.is_dir() else gate_path.parent
    for row in matrix:
        slot = row["slot"]
        evidence_path = root / "slots" / slot / "evidence.json"
        if not evidence_path.is_file():
            raise VerifyError("GATE_EVIDENCE_ARTIFACT_MISSING")
        rendered = load_json(evidence_path, "INVALID_GATE_EVIDENCE")
        # Gate's evidence.json must retain the adapter's exact claims and sources;
        # gate-added draft status metadata is deliberately not evidence.
        adapter_packet = one_packet(adapter, slot, "INVALID_ADAPTER_SLOT")
        if rendered.get("claims") != adapter_packet.get("evidence", {}).get("claims") or rendered.get("sources") != adapter_packet.get("evidence", {}).get("sources"):
            raise VerifyError("GATE_EVIDENCE_CLAIM_MISMATCH")
        if not ((root / "slots" / slot / "article.md").is_file() and (root / "slots" / slot / "article.html").is_file()):
            raise VerifyError("GATE_ARTICLE_ARTIFACT_MISSING")


def write_atomic(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="离线审验 raw 1905 packet → source input → adapter/gate provenance。")
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--source-input", type=Path, required=True)
    parser.add_argument("--adapter-output", type=Path)
    parser.add_argument("--gate-output", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.is_dir():
            raise VerifyError("OUTPUT_PATH_IS_DIRECTORY")
        raw, hashes, work_keys = raw_packets(args.raw_dir)
        source = load_json(args.source_input, "INVALID_SOURCE_INPUT")
        atoms, matrix = verify_source(raw, hashes, work_keys, source)
        phases = {"raw_source": "passed", "adapter": "skipped", "gate": "skipped"}
        adapter = None
        if args.adapter_output is not None:
            adapter = load_json(args.adapter_output, "INVALID_ADAPTER_OUTPUT")
            verify_adapter(adapter, atoms, matrix)
            phases["adapter"] = "passed"
        if args.gate_output is not None:
            if adapter is None:
                raise VerifyError("GATE_REQUIRES_ADAPTER_OUTPUT")
            verify_gate(args.gate_output, adapter, matrix)
            phases["gate"] = "passed"
        write_atomic(args.output, {"status": "pass", "phases": phases, "raw_packet_sha256": hashes, "source_input_sha256": sha256(args.source_input), "adapter_output_sha256": sha256(args.adapter_output) if args.adapter_output else None, "gate_output_path": str(args.gate_output) if args.gate_output else None, "matrix": matrix})
    except VerifyError as error:
        if args.output.is_symlink() or args.output.is_file():
            args.output.unlink(missing_ok=True)
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
