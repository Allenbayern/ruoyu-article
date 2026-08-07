#!/usr/bin/env python3
"""Fail-closed daily3 run orchestrator.

A run consumes only explicit 1905 raw packets and an explicit source-input JSON.
It stages immutable raw packets, verifies provenance, runs adapter and structural
validation, then invokes the non-publishing T1 HTML renderer. It never fetches,
publishes, changes cron, selects historical material, or authorizes publication.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
from html.parser import HTMLParser
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SLOTS = ("A", "B", "C")
REQUIRED_SUBJECTS = ("36372941", "37242440", "37379599")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
EXIT_SUCCESS = 0
EXIT_INVALID_ARGUMENT = 20
EXIT_SOURCE_PACKET_VERIFICATION_FAILED = 21
EXIT_ADAPTER_FAILED = 22
EXIT_STRUCTURAL_GATE_FAILED = 23
EXIT_PROVENANCE_VERIFICATION_FAILED = 24
EXIT_DELIVERY_HTML_VALIDATION_FAILED = 25
EXIT_FRESH_SOURCE_DELIVERY_REJECTED = 26
FORWARD_LEDGER_SCHEMA = "daily3-forward-delivery-ledger/v1"
FORWARD_LEDGER_BASELINE_KEYS = {
    "historical_delivery_ledger",
    "scope",
    "created_at",
    "source_repair_artifact",
}
FORWARD_LEDGER_HISTORICAL_DELIVERY = "NOT_FOUND_AND_UNVERIFIABLE"
FORWARD_LEDGER_SCOPE = "forward_only_from_2026-07-21"
FORWARD_LEDGER_SOURCE_REPAIR_ARTIFACT = "outputs/daily3_today_source_research/20260720-repair-t_e67ffacb"
LEGACY_LEDGER_KEYS = {"committed"}

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
ADAPTER = SCRIPTS / "daily3_packet_adapter.py"
GATE = SCRIPTS / "daily_three_article_production.py"
PROVENANCE = SCRIPTS / "verify_daily3_provenance.py"
RENDERER = SCRIPTS / "daily3_release_renderer.py"


class RunFailure(ValueError):
    def __init__(self, code: str, exit_code: int, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.exit_code = exit_code
        self.detail = detail


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def event(events: list[dict[str, Any]], run_id: str, name: str, **details: Any) -> None:
    events.append({"at": now(), "event": name, "run_id": run_id, **details})


def write_events(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in events), encoding="utf-8")


def source_work_identities(source_input: Path) -> list[str]:
    try:
        source = json.loads(source_input.read_text(encoding="utf-8"))
        slots = source["slots"]
        identities = [slots[slot][0]["work_key"] for slot in SLOTS]
    except (OSError, json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise RunFailure("SOURCE_BUNDLE_SOURCE_INVALID", EXIT_FRESH_SOURCE_DELIVERY_REJECTED, str(error)) from error
    if any(not isinstance(identity, str) or not identity.strip() for identity in identities) or len(set(identities)) != 3:
        raise RunFailure("SOURCE_BUNDLE_WORK_IDENTITIES_INVALID", EXIT_FRESH_SOURCE_DELIVERY_REJECTED)
    return identities


def source_subjects(work_identities: list[str]) -> tuple[str, str, str]:
    subjects = []
    for identity in work_identities:
        parts = identity.split(":")
        if len(parts) == 2 and parts[0] == "douban":
            subject = parts[1]
        elif len(parts) == 3 and parts[:2] == ["1905", "film"]:
            subject = parts[2]
        else:
            raise RunFailure("SOURCE_BUNDLE_WORK_IDENTITIES_INVALID", EXIT_FRESH_SOURCE_DELIVERY_REJECTED)
        if not subject.isdigit():
            raise RunFailure("SOURCE_BUNDLE_WORK_IDENTITIES_INVALID", EXIT_FRESH_SOURCE_DELIVERY_REJECTED)
        subjects.append(subject)
    return tuple(subjects)  # type: ignore[return-value]


def validate_source_bundle(bundle_path: Path, source_input: Path) -> dict[str, Any]:
    try:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RunFailure("SOURCE_BUNDLE_INVALID", EXIT_FRESH_SOURCE_DELIVERY_REJECTED, str(error)) from error
    if not isinstance(bundle, dict):
        raise RunFailure("SOURCE_BUNDLE_INVALID", EXIT_FRESH_SOURCE_DELIVERY_REJECTED)
    bundle_id = bundle.get("bundle_id")
    content_sha256 = bundle.get("content_sha256")
    created_at = bundle.get("created_at")
    work_identities = bundle.get("work_identities")
    if not all(isinstance(value, str) and value.strip() for value in (bundle_id, content_sha256, created_at)):
        raise RunFailure("SOURCE_BUNDLE_INVALID", EXIT_FRESH_SOURCE_DELIVERY_REJECTED)
    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise RunFailure("SOURCE_BUNDLE_INVALID", EXIT_FRESH_SOURCE_DELIVERY_REJECTED, "created_at") from error
    if content_sha256 != digest(source_input):
        raise RunFailure("SOURCE_BUNDLE_CONTENT_SHA256_MISMATCH", EXIT_FRESH_SOURCE_DELIVERY_REJECTED)
    if not isinstance(work_identities, list) or len(work_identities) != 3 or any(not isinstance(identity, str) or not identity.strip() for identity in work_identities) or len(set(work_identities)) != 3:
        raise RunFailure("SOURCE_BUNDLE_WORK_IDENTITIES_INVALID", EXIT_FRESH_SOURCE_DELIVERY_REJECTED)
    try:
        source_identities = source_work_identities(source_input)
    except RunFailure:
        return {"bundle_id": bundle_id, "bundle_sha256": digest(bundle_path), "content_sha256": content_sha256, "created_at": created_at, "work_identities": work_identities}
    if work_identities != source_identities:
        raise RunFailure("SOURCE_BUNDLE_WORK_IDENTITIES_MISMATCH", EXIT_FRESH_SOURCE_DELIVERY_REJECTED)
    return {"bundle_id": bundle_id, "bundle_sha256": digest(bundle_path), "content_sha256": content_sha256, "created_at": created_at, "work_identities": source_identities}


def load_ledger_document(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"committed": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        committed = data["committed"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise RunFailure("DELIVERY_LEDGER_INVALID", EXIT_FRESH_SOURCE_DELIVERY_REJECTED, str(error)) from error
    if not isinstance(data, dict) or not isinstance(committed, list) or any(not isinstance(entry, dict) for entry in committed):
        raise RunFailure("DELIVERY_LEDGER_INVALID", EXIT_FRESH_SOURCE_DELIVERY_REJECTED)
    if "schema" in data:
        if data["schema"] != FORWARD_LEDGER_SCHEMA:
            raise RunFailure("DELIVERY_LEDGER_INVALID", EXIT_FRESH_SOURCE_DELIVERY_REJECTED)
        if set(data) != {"schema", "baseline", "entries", "committed"}:
            raise RunFailure("DELIVERY_LEDGER_INVALID", EXIT_FRESH_SOURCE_DELIVERY_REJECTED)
        baseline = data["baseline"]
        if not isinstance(baseline, dict) or set(baseline) != FORWARD_LEDGER_BASELINE_KEYS:
            raise RunFailure("DELIVERY_LEDGER_INVALID", EXIT_FRESH_SOURCE_DELIVERY_REJECTED)
        if baseline["historical_delivery_ledger"] != FORWARD_LEDGER_HISTORICAL_DELIVERY or baseline["scope"] != FORWARD_LEDGER_SCOPE:
            raise RunFailure("DELIVERY_LEDGER_INVALID", EXIT_FRESH_SOURCE_DELIVERY_REJECTED)
        if baseline["source_repair_artifact"] != FORWARD_LEDGER_SOURCE_REPAIR_ARTIFACT:
            raise RunFailure("DELIVERY_LEDGER_INVALID", EXIT_FRESH_SOURCE_DELIVERY_REJECTED)
        if not isinstance(baseline["created_at"], str) or not baseline["created_at"].strip():
            raise RunFailure("DELIVERY_LEDGER_INVALID", EXIT_FRESH_SOURCE_DELIVERY_REJECTED)
        try:
            datetime.fromisoformat(baseline["created_at"].replace("Z", "+00:00"))
        except ValueError as error:
            raise RunFailure("DELIVERY_LEDGER_INVALID", EXIT_FRESH_SOURCE_DELIVERY_REJECTED, "baseline.created_at") from error
        if not isinstance(data["entries"], list):
            raise RunFailure("DELIVERY_LEDGER_INVALID", EXIT_FRESH_SOURCE_DELIVERY_REJECTED)
    elif set(data) != LEGACY_LEDGER_KEYS:
        raise RunFailure("DELIVERY_LEDGER_INVALID", EXIT_FRESH_SOURCE_DELIVERY_REJECTED)
    return data


def load_ledger(path: Path) -> list[dict[str, Any]]:
    return load_ledger_document(path)["committed"]


@contextmanager
def ledger_claim(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    claim = path.parent / f".{path.name}.claim"
    try:
        claim.mkdir()
    except FileExistsError as error:
        raise RunFailure("DELIVERY_LEDGER_BUSY", EXIT_FRESH_SOURCE_DELIVERY_REJECTED) from error
    try:
        yield
    finally:
        shutil.rmtree(claim, ignore_errors=True)


def reject_previously_delivered(bundle: dict[str, Any], committed: list[dict[str, Any]]) -> None:
    for prior in committed:
        if bundle["bundle_sha256"] == prior.get("bundle_sha256") or bundle["content_sha256"] == prior.get("content_sha256"):
            raise RunFailure("DELIVERY_LEDGER_BUNDLE_REUSED", EXIT_FRESH_SOURCE_DELIVERY_REJECTED)
        if set(bundle["work_identities"]) & set(prior.get("work_identities", [])):
            raise RunFailure("DELIVERY_LEDGER_WORK_IDENTITY_REUSED", EXIT_FRESH_SOURCE_DELIVERY_REJECTED)


def reject_article_delivery_hashes(article_delivery_sha256: dict[str, str], committed: list[dict[str, Any]]) -> None:
    proposed = set(article_delivery_sha256.values())
    for prior in committed:
        if proposed & set(prior.get("article_delivery_sha256", {}).values()):
            raise RunFailure("DELIVERY_LEDGER_ARTICLE_HASH_REUSED", EXIT_FRESH_SOURCE_DELIVERY_REJECTED)


def commit_ledger(path: Path, bundle: dict[str, Any], article_delivery_sha256: dict[str, str]) -> None:
    document = load_ledger_document(path)
    committed = document["committed"]
    reject_previously_delivered(bundle, committed)
    reject_article_delivery_hashes(article_delivery_sha256, committed)
    record = {**bundle, "article_delivery_sha256": article_delivery_sha256, "committed_at": now()}
    temporary = path.parent / f".{path.name}.tmp"
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump({**document, "committed": [*committed, record]}, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def command(args: list[str], *, code: str, exit_code: int) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RunFailure(code, exit_code, detail)
    return result


def stage_raw_packets(raw_dir: Path, destination: Path, subjects: tuple[str, str, str]) -> dict[str, str]:
    if not raw_dir.is_dir():
        raise RunFailure("RAW_PACKET_DIRECTORY_INVALID", EXIT_SOURCE_PACKET_VERIFICATION_FAILED)
    destination.mkdir(parents=True)
    hashes: dict[str, str] = {}
    for subject in subjects:
        source = raw_dir / f"{subject}.json"
        if not source.is_file() or source.is_symlink():
            raise RunFailure("RAW_PACKET_SET_INCOMPLETE", EXIT_SOURCE_PACKET_VERIFICATION_FAILED, subject)
        target = destination / source.name
        shutil.copyfile(source, target)
        hashes[subject] = digest(target)
    if {path.stem for path in raw_dir.glob("*.json")} != set(subjects):
        raise RunFailure("RAW_PACKET_SET_NOT_EXACT_ALLOWLIST", EXIT_SOURCE_PACKET_VERIFICATION_FAILED)
    return hashes


def initial_manifest(run_id: str, raw_hashes: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "status": "failed",
        "failure_code": None,
        "failure_detail": None,
        "raw_packet_sha256": raw_hashes or {},
        "source_packet_verified": False,
        "three_slot_structural_gate_passed": False,
        "delivery_html_validated": False,
        "delivery_candidate_created": False,
        "source_bundle_verified": False,
        "delivery_ledger_committed": False,
        "publication_authorized": False,
        "publication_performed": False,
        "release_acceptance": {"status": "not_created", "reason": "DELIVERY_NOT_CREATED"},
    }


def verify_source_run_id(source_input: Path, run_id: str) -> None:
    try:
        source_data = json.loads(source_input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RunFailure("SOURCE_INPUT_INVALID", EXIT_SOURCE_PACKET_VERIFICATION_FAILED, str(error)) from error
    if not isinstance(source_data, dict):
        raise RunFailure("SOURCE_INPUT_INVALID", EXIT_SOURCE_PACKET_VERIFICATION_FAILED)
    if source_data.get("run_id") != run_id:
        raise RunFailure("SOURCE_RUN_ID_MISMATCH", EXIT_SOURCE_PACKET_VERIFICATION_FAILED)


class _DeliveryHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.open_tags: list[str] = []
        self.malformed = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))
        if tag not in {"br", "meta", "link", "img", "input", "hr"}:
            self.open_tags.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.open_tags or self.open_tags.pop() != tag:
            self.malformed = True


def read_nonempty_text(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8")
    except OSError as error:
        raise RunFailure("DELIVERY_ARTIFACT_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED, str(error)) from error
    if not value.strip():
        raise RunFailure("DELIVERY_ARTIFACT_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED, str(path))
    return value


def verify_html(path: Path, *, preview: bool) -> None:
    value = read_nonempty_text(path)
    parser = _DeliveryHtmlParser()
    try:
        parser.feed(value)
        parser.close()
    except Exception as error:
        raise RunFailure("DELIVERY_ARTIFACT_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED, str(error)) from error
    tags = [tag for tag, _ in parser.tags]
    if parser.malformed or parser.open_tags or "section" not in tags or "span" not in tags:
        raise RunFailure("DELIVERY_ARTIFACT_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED, str(path))
    if preview and (not value.lstrip().lower().startswith("<!doctype html>") or "html" not in tags or "body" not in tags):
        raise RunFailure("DELIVERY_ARTIFACT_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED, str(path))


def expected_delivery_candidates(adapter_output: Path) -> dict[str, dict[str, Any]]:
    try:
        adapter = json.loads(adapter_output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RunFailure("DELIVERY_ARTIFACT_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED, str(error)) from error
    slots = adapter.get("slots") if isinstance(adapter, dict) else None
    if not isinstance(slots, dict):
        raise RunFailure("DELIVERY_ARTIFACT_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED)
    expected: dict[str, dict[str, Any]] = {}
    for slot in SLOTS:
        candidates = slots.get(slot)
        if not isinstance(candidates, list) or len(candidates) != 1 or not isinstance(candidates[0], dict):
            raise RunFailure("DELIVERY_ARTIFACT_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED)
        expected[slot] = candidates[0]
    return expected


def validator_record_is_consistent(record: Any) -> bool:
    return record == {"kind": "local_deterministic_preflight", "validated": True}


def verify_delivery_manifest(path: Path, run_id: str, renderer_exit_code: int, expected: dict[str, dict[str, Any]]) -> dict[str, str]:
    try:
        delivery = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RunFailure("DELIVERY_MANIFEST_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED, str(error)) from error
    if not isinstance(delivery, dict):
        raise RunFailure("DELIVERY_MANIFEST_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED)
    if delivery.get("run_id") != run_id:
        raise RunFailure("DELIVERY_MANIFEST_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED)
    if delivery.get("status") != "rendered_not_published":
        raise RunFailure("DELIVERY_MANIFEST_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED)
    if delivery.get("publication_authorized") is not False or delivery.get("publication_performed") is not False:
        raise RunFailure("DELIVERY_MANIFEST_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED)
    release = delivery.get("release_acceptance")
    if not isinstance(release, dict) or set(release) != {"status", "reason"}:
        raise RunFailure("DELIVERY_MANIFEST_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED)
    if not isinstance(release["status"], str) or not isinstance(release["reason"], str):
        raise RunFailure("DELIVERY_MANIFEST_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED)
    if renderer_exit_code == 2:
        if release != {"status": "not_accepted", "reason": "WECHAT_PREVIEW_UNVERIFIED"}:
            raise RunFailure("DELIVERY_MANIFEST_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED)
    elif renderer_exit_code == 0:
        if release["status"] != "accepted":
            raise RunFailure("DELIVERY_MANIFEST_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED)
    else:
        raise RunFailure("DELIVERY_MANIFEST_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED)
    slots = delivery.get("slots")
    if not isinstance(slots, dict) or set(slots) != set(SLOTS):
        raise RunFailure("DELIVERY_ARTIFACT_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED)
    slots_root = path.parent / "slots"
    if not slots_root.is_dir() or {entry.name for entry in slots_root.iterdir()} != set(SLOTS):
        raise RunFailure("DELIVERY_ARTIFACT_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED)
    for slot, candidate in expected.items():
        record = slots.get(slot)
        if not isinstance(record, dict) or record.get("candidate_id") != candidate.get("id"):
            raise RunFailure("DELIVERY_ARTIFACT_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED)
        validator = record.get("validator")
        if not validator_record_is_consistent(validator):
            raise RunFailure("DELIVERY_ARTIFACT_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED)
        slot_dir = path.parent / "slots" / slot
        verify_html(slot_dir / "article.html", preview=False)
        verify_html(slot_dir / "preview.html", preview=True)
        try:
            evidence = json.loads(read_nonempty_text(slot_dir / "evidence.json"))
        except json.JSONDecodeError as error:
            raise RunFailure("DELIVERY_ARTIFACT_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED, str(error)) from error
        candidate_evidence = candidate.get("evidence")
        if not isinstance(evidence, dict) or evidence != candidate_evidence:
            raise RunFailure("DELIVERY_ARTIFACT_INVALID", EXIT_DELIVERY_HTML_VALIDATION_FAILED)
    return release


def discard_delivery(work: Path) -> None:
    shutil.rmtree(work / "delivery", ignore_errors=True)


def run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    if not RUN_ID_RE.fullmatch(args.run_id):
        raise RunFailure("INVALID_RUN_ID", EXIT_INVALID_ARGUMENT)
    output = args.output_base / args.run_id
    if output.exists():
        raise RunFailure("RUN_OUTPUT_ALREADY_EXISTS", EXIT_INVALID_ARGUMENT)
    output.parent.mkdir(parents=True, exist_ok=True)
    claim = output.parent / f".{args.run_id}.claim"
    try:
        claim.mkdir()
    except FileExistsError as error:
        raise RunFailure("RUN_OUTPUT_ALREADY_EXISTS", EXIT_INVALID_ARGUMENT) from error
    work: Path | None = None
    try:
        work = Path(tempfile.mkdtemp(prefix=f".{args.run_id}.tmp.", dir=output.parent))
        events: list[dict[str, Any]] = []
        manifest = initial_manifest(args.run_id)
    except Exception as error:
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)
        for temporary in output.parent.glob(f".{args.run_id}.tmp.*"):
            shutil.rmtree(temporary, ignore_errors=True)
        shutil.rmtree(claim, ignore_errors=True)
        raise RunFailure("RUN_INITIALIZATION_FAILED", EXIT_INVALID_ARGUMENT, str(error)) from error
    try:
        event(events, args.run_id, "run_started", mode="offline_explicit_artifacts")
        bundle = validate_source_bundle(args.source_bundle, args.source_input)
        subjects = source_subjects(bundle["work_identities"])
        raw_hashes = stage_raw_packets(args.raw_dir, work / "raw-packets", subjects)
        manifest["raw_packet_sha256"] = raw_hashes
        event(events, args.run_id, "raw_packets_staged", raw_packet_sha256=raw_hashes)
        if not args.source_input.is_file() or args.source_input.is_symlink():
            raise RunFailure("SOURCE_INPUT_INVALID", EXIT_SOURCE_PACKET_VERIFICATION_FAILED)
        verify_source_run_id(args.source_input, args.run_id)
        manifest["source_bundle_verified"] = True
        manifest["source_bundle"] = bundle
        event(events, args.run_id, "source_bundle_verified", bundle_id=bundle["bundle_id"], bundle_sha256=bundle["bundle_sha256"])
        shutil.copyfile(args.source_input, work / "source-input.json")
        command([sys.executable, str(PROVENANCE), "--raw-dir", str(work / "raw-packets"), "--source-input", str(work / "source-input.json"), "--output", str(work / "source-packet-report.json")], code="SOURCE_PACKET_VERIFICATION_FAILED", exit_code=EXIT_SOURCE_PACKET_VERIFICATION_FAILED)
        manifest["source_packet_verified"] = True
        event(events, args.run_id, "source_packet_verified")
        command([sys.executable, str(ADAPTER), "--input", str(work / "source-input.json"), "--output", str(work / "adapter-output.json")], code="ADAPTER_FAILED", exit_code=EXIT_ADAPTER_FAILED)
        event(events, args.run_id, "adapter_completed")
        command([sys.executable, str(GATE), "--input", str(work / "adapter-output.json"), "--output", str(work / "structural-gate")], code="THREE_SLOT_STRUCTURAL_GATE_FAILED", exit_code=EXIT_STRUCTURAL_GATE_FAILED)
        manifest["three_slot_structural_gate_passed"] = True
        event(events, args.run_id, "three_slot_structural_gate_passed")
        command([sys.executable, str(PROVENANCE), "--raw-dir", str(work / "raw-packets"), "--source-input", str(work / "source-input.json"), "--adapter-output", str(work / "adapter-output.json"), "--gate-output", str(work / "structural-gate"), "--output", str(work / "provenance-report.json")], code="PROVENANCE_VERIFICATION_FAILED", exit_code=EXIT_PROVENANCE_VERIFICATION_FAILED)
        event(events, args.run_id, "provenance_verified")
        render = subprocess.run([sys.executable, str(RENDERER), "--input", str(work / "adapter-output.json"), "--output", str(work / "delivery")], cwd=ROOT, text=True, capture_output=True, check=False)
        delivery_manifest = work / "delivery" / "manifest.json"
        try:
            if render.returncode not in (0, 2) or not delivery_manifest.is_file():
                raise RunFailure("DELIVERY_HTML_VALIDATION_FAILED", EXIT_DELIVERY_HTML_VALIDATION_FAILED, (render.stderr or render.stdout).strip())
            release = verify_delivery_manifest(
                delivery_manifest,
                args.run_id,
                render.returncode,
                expected_delivery_candidates(work / "adapter-output.json"),
            )
        except RunFailure:
            discard_delivery(work)
            raise
        manifest["delivery_html_validated"] = True
        manifest["delivery_candidate_created"] = True
        manifest["release_acceptance"] = release
        event(events, args.run_id, "delivery_html_validated", renderer_exit_code=render.returncode, release_acceptance=release)
        article_delivery_sha256 = {slot: digest(work / "delivery" / "slots" / slot / "article.html") for slot in SLOTS}
        try:
            with ledger_claim(args.delivery_ledger):
                commit_ledger(args.delivery_ledger, bundle, article_delivery_sha256)
        except RunFailure:
            discard_delivery(work)
            manifest["delivery_candidate_created"] = False
            manifest["delivery_html_validated"] = False
            raise
        manifest["delivery_ledger_committed"] = True
        manifest["delivery_ledger_path"] = str(args.delivery_ledger)
        event(events, args.run_id, "delivery_ledger_committed", bundle_id=bundle["bundle_id"])
        manifest["status"] = "completed_nonpublishing_candidate"
        event(events, args.run_id, "run_completed", status=manifest["status"])
        return EXIT_SUCCESS, manifest
    except RunFailure as failure:
        manifest["failure_code"] = failure.code
        manifest["failure_detail"] = failure.detail or None
        event(events, args.run_id, "run_failed", failure_code=failure.code)
        return failure.exit_code, manifest
    finally:
        write_json(work / "manifest.json", manifest)
        write_events(work / "audit" / "events.jsonl", events)
        try:
            os.replace(work, output)
        finally:
            shutil.rmtree(work, ignore_errors=True)
            shutil.rmtree(claim, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run explicit daily3 raw→source→adapter→gate→provenance→T1 rendering. Never publishes or authorizes publication.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--raw-dir", required=True, type=Path, help="exactly three allowlisted 1905 raw JSON packets")
    parser.add_argument("--source-input", required=True, type=Path, help="explicit source drafts and evidence atoms")
    parser.add_argument("--source-bundle", required=True, type=Path, help="explicit per-run source bundle identity; no fixture fallback")
    parser.add_argument("--delivery-ledger", required=True, type=Path, help="isolated atomic delivery ledger")
    parser.add_argument("--output-base", required=True, type=Path)

    args = parser.parse_args()
    try:
        status, manifest = run(args)
    except RunFailure as failure:
        print(f"{failure.code}:{failure.detail}" if failure.detail else failure.code, file=sys.stderr)
        return failure.exit_code
    print(json.dumps({"run_id": manifest["run_id"], "status": manifest["status"], "publication_authorized": False, "exit_code": status}, ensure_ascii=False))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
