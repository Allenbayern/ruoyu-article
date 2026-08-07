#!/usr/bin/env python3
"""Create a forward-only daily3 delivery-ledger baseline without delivering content.

This utility reads the independently reviewed source-repair bundle, writes an
empty ledger baseline, and writes a production-input manifest. It never renders,
publishes, or records an article delivery.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Iterator


SLOTS = ("A", "B", "C")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
WORK_KEY_RE = re.compile(r"^1905:film:\d+$")
LEDGER_SCHEMA = "daily3-forward-delivery-ledger/v1"
FORWARD_ONLY_SCOPE = "forward_only_from_2026-07-21"
SOURCE_REPAIR_ARTIFACT = "outputs/daily3_today_source_research/20260720-repair-t_e67ffacb"


class LedgerFailure(ValueError):
    """Stable fail-closed ledger validation error."""


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp"
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path, failure_code: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LedgerFailure(failure_code) from error


def iso8601(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LedgerFailure("DELIVERY_LEDGER_ENTRY_INVALID")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise LedgerFailure("DELIVERY_LEDGER_ENTRY_INVALID") from error
    return value


def sha256(value: Any) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise LedgerFailure("DELIVERY_LEDGER_ENTRY_INVALID")
    return value


def work_key(value: Any) -> str:
    if not isinstance(value, str) or not WORK_KEY_RE.fullmatch(value):
        raise LedgerFailure("DELIVERY_LEDGER_ENTRY_INVALID")
    return value


def validate_entry(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {
        "work_key",
        "source_bundle_sha256",
        "article_content_sha256",
        "source_packet_sha256",
        "created_at",
        "delivery_status",
    }:
        raise LedgerFailure("DELIVERY_LEDGER_ENTRY_INVALID")
    if value["delivery_status"] != "not_delivered":
        raise LedgerFailure("DELIVERY_LEDGER_ENTRY_INVALID")
    return {
        "work_key": work_key(value["work_key"]),
        "source_bundle_sha256": sha256(value["source_bundle_sha256"]),
        "article_content_sha256": sha256(value["article_content_sha256"]),
        "source_packet_sha256": sha256(value["source_packet_sha256"]),
        "created_at": iso8601(value["created_at"]),
        "delivery_status": "not_delivered",
    }


def validate_baseline(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {
        "historical_delivery_ledger",
        "scope",
        "created_at",
        "source_repair_artifact",
    }:
        raise LedgerFailure("DELIVERY_LEDGER_BASELINE_INVALID")
    if value["historical_delivery_ledger"] != "NOT_FOUND_AND_UNVERIFIABLE":
        raise LedgerFailure("DELIVERY_LEDGER_BASELINE_INVALID")
    if value["scope"] != FORWARD_ONLY_SCOPE:
        raise LedgerFailure("DELIVERY_LEDGER_BASELINE_INVALID")
    if value["source_repair_artifact"] != SOURCE_REPAIR_ARTIFACT:
        raise LedgerFailure("DELIVERY_LEDGER_BASELINE_INVALID")
    try:
        created_at = iso8601(value["created_at"])
    except LedgerFailure as error:
        raise LedgerFailure("DELIVERY_LEDGER_BASELINE_INVALID") from error
    return {
        "historical_delivery_ledger": "NOT_FOUND_AND_UNVERIFIABLE",
        "scope": FORWARD_ONLY_SCOPE,
        "created_at": created_at,
        "source_repair_artifact": SOURCE_REPAIR_ARTIFACT,
    }


def load_ledger(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise LedgerFailure("DELIVERY_LEDGER_MISSING")
    data = read_json(path, "DELIVERY_LEDGER_INVALID")
    if not isinstance(data, dict) or set(data) != {"schema", "baseline", "entries", "committed"}:
        raise LedgerFailure("DELIVERY_LEDGER_INVALID")
    if data["schema"] != LEDGER_SCHEMA:
        raise LedgerFailure("DELIVERY_LEDGER_INVALID")
    if not isinstance(data["entries"], list) or not isinstance(data["committed"], list):
        raise LedgerFailure("DELIVERY_LEDGER_INVALID")
    return {
        "schema": LEDGER_SCHEMA,
        "baseline": validate_baseline(data["baseline"]),
        "entries": [validate_entry(item) for item in data["entries"]],
        "committed": data["committed"],
    }


def initialize_ledger(path: Path, baseline: dict[str, str]) -> None:
    if path.exists():
        raise LedgerFailure("DELIVERY_LEDGER_ALREADY_EXISTS")
    write_json_atomic(path, {"schema": LEDGER_SCHEMA, "baseline": validate_baseline(baseline), "entries": [], "committed": []})


@contextmanager
def ledger_claim(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    claim = path.parent / f".{path.name}.claim"
    try:
        claim.mkdir()
    except FileExistsError as error:
        raise LedgerFailure("DELIVERY_LEDGER_BUSY") from error
    try:
        yield
    finally:
        shutil.rmtree(claim, ignore_errors=True)


@contextmanager
def commit_claim(path: Path) -> Iterator[None]:
    deadline = time.monotonic() + 5
    while True:
        try:
            with ledger_claim(path):
                yield
                return
        except LedgerFailure as error:
            if str(error) != "DELIVERY_LEDGER_BUSY" or time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def commit_ledger(path: Path, record: dict[str, Any]) -> None:
    candidate = validate_entry(record)
    with commit_claim(path):
        ledger = load_ledger(path)
        for prior in ledger["entries"]:
            if candidate["work_key"] == prior["work_key"]:
                raise LedgerFailure("DELIVERY_LEDGER_DUPLICATE_WORK_KEY")
            if candidate["source_bundle_sha256"] == prior["source_bundle_sha256"]:
                raise LedgerFailure("DELIVERY_LEDGER_DUPLICATE_SOURCE_BUNDLE_SHA256")
            if candidate["article_content_sha256"] == prior["article_content_sha256"]:
                raise LedgerFailure("DELIVERY_LEDGER_DUPLICATE_ARTICLE_CONTENT_SHA256")
        write_json_atomic(path, {**ledger, "entries": [*ledger["entries"], candidate]})


def source_packet_hashes(source_root: Path, source: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    slots = source.get("slots") if isinstance(source, dict) else None
    if not isinstance(slots, dict) or set(slots) != set(SLOTS):
        raise LedgerFailure("TODAY_SOURCE_INPUT_INVALID")
    keys: list[str] = []
    hashes: dict[str, str] = {}
    for slot in SLOTS:
        candidates = slots.get(slot)
        if not isinstance(candidates, list) or len(candidates) != 1 or not isinstance(candidates[0], dict):
            raise LedgerFailure("TODAY_SOURCE_INPUT_INVALID")
        candidate = candidates[0]
        key = work_key(candidate.get("work_key"))
        origin = candidate.get("origin_packet_id")
        if not isinstance(origin, str) or not origin:
            raise LedgerFailure("TODAY_SOURCE_INPUT_INVALID")
        keys.append(key)
    atoms = source.get("evidence_atoms")
    if not isinstance(atoms, list):
        raise LedgerFailure("TODAY_SOURCE_INPUT_INVALID")
    for key in keys:
        matching = [atom for atom in atoms if isinstance(atom, dict) and atom.get("work_key") == key]
        if not matching:
            raise LedgerFailure("TODAY_SOURCE_INPUT_INVALID")
        packet_hashes = {sha256(atom.get("origin_packet_sha256")) for atom in matching}
        if len(packet_hashes) != 1:
            raise LedgerFailure("TODAY_SOURCE_INPUT_INVALID")
        expected_hash = packet_hashes.pop()
        subject = key.rsplit(":", 1)[1]
        raw_packet = source_root / "raw-packets" / f"{subject}.json"
        if not raw_packet.is_file() or raw_packet.is_symlink() or digest(raw_packet) != expected_hash:
            raise LedgerFailure("TODAY_SOURCE_INPUT_INVALID")
        hashes[key] = expected_hash
    if len(set(keys)) != 3:
        raise LedgerFailure("TODAY_SOURCE_INPUT_INVALID")
    return keys, hashes


def initialize_today_ledger_and_manifest(source_root: Path, ledger_path: Path, manifest_path: Path, created_at: str) -> None:
    created_at = iso8601(created_at)
    bundle_path = source_root / "source-bundle-candidate.json"
    source_path = source_root / "source-input-candidate.json"
    bundle = read_json(bundle_path, "TODAY_SOURCE_BUNDLE_INVALID")
    source = read_json(source_path, "TODAY_SOURCE_INPUT_INVALID")
    if not isinstance(bundle, dict) or bundle.get("historical_delivery_ledger") != "not_evaluated_out_of_scope":
        raise LedgerFailure("TODAY_SOURCE_BUNDLE_INVALID")
    bundle_id = bundle.get("bundle_id")
    if not isinstance(bundle_id, str) or not bundle_id:
        raise LedgerFailure("TODAY_SOURCE_BUNDLE_INVALID")
    if bundle.get("content_sha256") != digest(source_path):
        raise LedgerFailure("TODAY_SOURCE_BUNDLE_INVALID")
    keys, packet_hashes = source_packet_hashes(source_root, source)
    if bundle.get("work_identities") != keys:
        raise LedgerFailure("TODAY_SOURCE_BUNDLE_INVALID")
    baseline = {
        "historical_delivery_ledger": "NOT_FOUND_AND_UNVERIFIABLE",
        "scope": FORWARD_ONLY_SCOPE,
        "created_at": created_at,
        "source_repair_artifact": SOURCE_REPAIR_ARTIFACT,
    }
    initialize_ledger(ledger_path, baseline)
    manifest = {
        "schema": "daily3-today-production-input/v1",
        "created_at": created_at,
        "source_repair_artifact": str(source_root),
        "source_bundle": {
            "bundle_id": bundle_id,
            "sha256": digest(bundle_path),
            "content_sha256": digest(source_path),
        },
        "work_keys": keys,
        "source_packet_sha256": packet_hashes,
        "ledger_path": str(ledger_path),
        "historical_delivery_ledger": "NOT_FOUND_AND_UNVERIFIABLE",
        "delivery_status": "registered_input_only_not_delivered",
        "publication_authorized": False,
        "publication_performed": False,
        "article_content_hashes": {},
        "coverage_gaps": [
            "Historical delivery deduplication is NOT_FOUND_AND_UNVERIFIABLE; this ledger is forward-only from this baseline.",
            "No article content exists or is committed; article-content SHA-256 checks apply only at a later explicit non-delivery ledger commit.",
        ],
    }
    write_json_atomic(manifest_path, manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize only a forward daily3 ledger and today-production-input manifest; never delivers or publishes.")
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--created-at", required=True)
    args = parser.parse_args()
    try:
        initialize_today_ledger_and_manifest(args.source_root, args.ledger, args.manifest, args.created_at)
    except LedgerFailure as error:
        print(str(error), file=__import__("sys").stderr)
        return 26
    print(json.dumps({"ledger": str(args.ledger), "manifest": str(args.manifest), "delivery_status": "registered_input_only_not_delivered"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
