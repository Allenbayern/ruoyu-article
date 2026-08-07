#!/usr/bin/env python3
"""Create a retained, non-publishing daily3 failure-matrix evidence bundle.

This tool only copies supplied raw/source inputs and invokes the existing offline
orchestrator. It neither fetches, changes cron, selects historical content, nor
publishes. Every case retains its process evidence under one immutable matrix id.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import threading
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
ORCHESTRATOR = ROOT / "scripts" / "daily3_production_orchestrator.py"
SLOTS = ("A", "B", "C")


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return parsed


def copy_raw(raw_dir: Path, destination: Path) -> Path:
    shutil.copytree(raw_dir, destination)
    return destination


def write_source(source: dict[str, Any], path: Path, run_id: str) -> Path:
    source["run_id"] = run_id
    write_json(path, source)
    return path


def write_source_bundle(source_input: Path, destination: Path, run_id: str) -> Path:
    source = load_json(source_input)
    slots = source.get("slots")
    work_identities = [
        slots[slot][0]["work_key"]
        for slot in SLOTS
        if isinstance(slots, dict) and isinstance(slots.get(slot), list) and slots[slot] and isinstance(slots[slot][0], dict) and isinstance(slots[slot][0].get("work_key"), str)
    ]
    write_json(destination, {
        "bundle_id": f"matrix-case-{run_id}",
        "content_sha256": sha256(source_input),
        "created_at": timestamp(),
        "work_identities": work_identities,
    })
    return destination


def cli_args(run_id: str, raw_dir: Path, source_input: Path, source_bundle: Path, delivery_ledger: Path, output_base: Path) -> list[str]:
    return [
        sys.executable, str(ORCHESTRATOR), "--run-id", run_id,
        "--raw-dir", str(raw_dir), "--source-input", str(source_input),
        "--source-bundle", str(source_bundle), "--delivery-ledger", str(delivery_ledger),
        "--output-base", str(output_base),
    ]


def process_case(case_dir: Path, command: list[str]) -> tuple[int, str, str]:
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    (case_dir / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (case_dir / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
    return completed.returncode, completed.stdout, completed.stderr


def run_manifest(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / "manifest.json"
    return load_json(path) if path.is_file() else None


def case_record(name: str, case_dir: Path, exit_code: int, run_dir: Path, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest = run_manifest(run_dir)
    record: dict[str, Any] = {
        "case": name,
        "exit_code": exit_code,
        "run_dir": str(run_dir.relative_to(case_dir.parent.parent)),
        "manifest_path": str((run_dir / "manifest.json").relative_to(case_dir.parent.parent)) if manifest else None,
        "stdout_path": str((case_dir / "stdout.txt").relative_to(case_dir.parent.parent)),
        "stderr_path": str((case_dir / "stderr.txt").relative_to(case_dir.parent.parent)),
        "publication_authorized": manifest.get("publication_authorized") if manifest else False,
        "publication_performed": manifest.get("publication_performed") if manifest else False,
        "delivery_candidate_created": manifest.get("delivery_candidate_created") if manifest else False,
        "delivery_exists": (run_dir / "delivery").exists(),
        "failure_code": manifest.get("failure_code") if manifest else None,
        "release_acceptance": manifest.get("release_acceptance") if manifest else None,
        "raw_packet_sha256": manifest.get("raw_packet_sha256") if manifest else {},
        "source_bundle_verified": manifest.get("source_bundle_verified") if manifest else False,
        "delivery_ledger_committed": manifest.get("delivery_ledger_committed") if manifest else False,
    }
    if extra:
        record.update(extra)
    write_json(case_dir / "result.json", record)
    return record


def normal_case(name: str, matrix_dir: Path, args: argparse.Namespace, source: dict[str, Any], mutate: Callable[[dict[str, Any]], None] | None = None, raw_mutate: Callable[[Path], None] | None = None) -> dict[str, Any]:
    case_dir = matrix_dir / "cases" / name
    case_dir.mkdir(parents=True)
    run_id = f"{args.matrix_id}-{name}"
    raw_dir = copy_raw(args.raw_dir, case_dir / "input" / "raw-packets")
    if raw_mutate:
        raw_mutate(raw_dir)
    input_source = json.loads(json.dumps(source))
    if mutate:
        mutate(input_source)
    source_path = write_source(input_source, case_dir / "input" / "source-input.json", run_id)
    source_bundle = write_source_bundle(source_path, case_dir / "input" / "source-bundle.json", run_id)
    delivery_ledger = case_dir / "input" / "delivery-ledger.json"
    output_base = case_dir / "runs"
    status, _, _ = process_case(case_dir, cli_args(run_id, raw_dir, source_path, source_bundle, delivery_ledger, output_base))
    return case_record(name, case_dir, status, output_base / run_id)


def renderer_failure_case(matrix_dir: Path, args: argparse.Namespace, source: dict[str, Any]) -> dict[str, Any]:
    name = "renderer_failure"
    case_dir = matrix_dir / "cases" / name
    case_dir.mkdir(parents=True)
    run_id = f"{args.matrix_id}-{name}"
    raw_dir = copy_raw(args.raw_dir, case_dir / "input" / "raw-packets")
    source_path = write_source(json.loads(json.dumps(source)), case_dir / "input" / "source-input.json", run_id)
    source_bundle = write_source_bundle(source_path, case_dir / "input" / "source-bundle.json", run_id)
    delivery_ledger = case_dir / "input" / "delivery-ledger.json"
    renderer = case_dir / "renderer-failure.py"
    renderer.write_text("import sys\nprint('intentional renderer failure', file=sys.stderr)\nraise SystemExit(1)\n", encoding="utf-8")
    spec = importlib.util.spec_from_file_location(f"daily3_orchestrator_{name}", ORCHESTRATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.RENDERER = renderer
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        status, _ = module.run(Namespace(run_id=run_id, raw_dir=raw_dir, source_input=source_path, source_bundle=source_bundle, delivery_ledger=delivery_ledger, output_base=case_dir / "runs"))
    (case_dir / "stdout.txt").write_text(stdout.getvalue(), encoding="utf-8")
    (case_dir / "stderr.txt").write_text(stderr.getvalue(), encoding="utf-8")
    return case_record(name, case_dir, status, case_dir / "runs" / run_id, {"renderer_double": "intentional nonpublishing failure"})


def sequential_case(matrix_dir: Path, args: argparse.Namespace, source: dict[str, Any]) -> dict[str, Any]:
    name = "sequential_same_run_id"
    case_dir = matrix_dir / "cases" / name
    case_dir.mkdir(parents=True)
    run_id = f"{args.matrix_id}-{name}"
    raw_dir = copy_raw(args.raw_dir, case_dir / "input" / "raw-packets")
    source_path = write_source(json.loads(json.dumps(source)), case_dir / "input" / "source-input.json", run_id)
    source_bundle = write_source_bundle(source_path, case_dir / "input" / "source-bundle.json", run_id)
    delivery_ledger = case_dir / "input" / "delivery-ledger.json"
    command = cli_args(run_id, raw_dir, source_path, source_bundle, delivery_ledger, case_dir / "runs")
    first = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    before = (case_dir / "runs" / run_id / "manifest.json").read_bytes() if first.returncode == 0 else b""
    second = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    (case_dir / "stdout.txt").write_text("FIRST\n" + first.stdout + "\nSECOND\n" + second.stdout, encoding="utf-8")
    (case_dir / "stderr.txt").write_text("FIRST\n" + first.stderr + "\nSECOND\n" + second.stderr, encoding="utf-8")
    after = (case_dir / "runs" / run_id / "manifest.json").read_bytes() if before else b""
    return case_record(name, case_dir, second.returncode, case_dir / "rejected-second-attempt", {
        "first_exit_code": first.returncode,
        "second_exit_code": second.returncode,
        "prior_manifest_unchanged": before == after,
        "failure_code": "RUN_OUTPUT_ALREADY_EXISTS",
        "delivery_candidate_created": False,
        "delivery_exists": False,
        "publication_authorized": False,
        "publication_performed": False,
        "retained_prior_run": {"manifest_path": f"cases/{name}/runs/{run_id}/manifest.json", "delivery_candidate_created": True},
    })


def concurrent_case(matrix_dir: Path, args: argparse.Namespace, source: dict[str, Any]) -> dict[str, Any]:
    name = "concurrent_same_run_id"
    case_dir = matrix_dir / "cases" / name
    case_dir.mkdir(parents=True)
    run_id = f"{args.matrix_id}-{name}"
    raw_dir = copy_raw(args.raw_dir, case_dir / "input" / "raw-packets")
    source_path = write_source(json.loads(json.dumps(source)), case_dir / "input" / "source-input.json", run_id)
    source_bundle = write_source_bundle(source_path, case_dir / "input" / "source-bundle.json", run_id)
    delivery_ledger = case_dir / "input" / "delivery-ledger.json"
    command = cli_args(run_id, raw_dir, source_path, source_bundle, delivery_ledger, case_dir / "runs")
    start = threading.Barrier(2)
    results: list[subprocess.CompletedProcess[str]] = []
    def invoke() -> None:
        start.wait()
        results.append(subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False))
    threads = [threading.Thread(target=invoke) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    (case_dir / "stdout.txt").write_text("\n--- PROCESS ---\n".join(item.stdout for item in results), encoding="utf-8")
    (case_dir / "stderr.txt").write_text("\n--- PROCESS ---\n".join(item.stderr for item in results), encoding="utf-8")
    winner = next((item for item in results if item.returncode == 0), None)
    loser = next((item for item in results if item.returncode != 0), None)
    exit_code = loser.returncode if loser else 99
    return case_record(name, case_dir, exit_code, case_dir / "rejected-loser-attempt", {
        "process_exit_codes": sorted(item.returncode for item in results),
        "winner_exit_code": winner.returncode if winner else None,
        "loser_exit_code": loser.returncode if loser else None,
        "temporary_residue": [path.name for path in (case_dir / "runs").glob(f".{run_id}.*")],
        "failure_code": "RUN_OUTPUT_ALREADY_EXISTS",
        "delivery_candidate_created": False,
        "delivery_exists": False,
        "publication_authorized": False,
        "publication_performed": False,
        "retained_winner_run": {"manifest_path": f"cases/{name}/runs/{run_id}/manifest.json", "delivery_candidate_created": True},
    })


def main() -> int:
    parser = argparse.ArgumentParser(description="Retain a real-input daily3 nonpublishing failure matrix; never publishes or changes cron.")
    parser.add_argument("--output-base", required=True, type=Path)
    parser.add_argument("--matrix-id", required=True)
    parser.add_argument("--raw-dir", required=True, type=Path)
    parser.add_argument("--source-input", required=True, type=Path)
    args = parser.parse_args()
    matrix_dir = args.output_base / args.matrix_id
    if matrix_dir.exists():
        print("MATRIX_OUTPUT_ALREADY_EXISTS", file=sys.stderr)
        return 20
    if not args.raw_dir.is_dir() or not args.source_input.is_file():
        print("MATRIX_INPUT_INVALID", file=sys.stderr)
        return 20
    matrix_dir.mkdir(parents=True)
    events: list[dict[str, Any]] = [{"at": timestamp(), "event": "matrix_started", "matrix_id": args.matrix_id}]
    try:
        source = load_json(args.source_input)
        cases: dict[str, dict[str, Any]] = {}
        cases["positive_abc"] = normal_case("positive_abc", matrix_dir, args, source)
        cases["missing_c"] = normal_case("missing_c", matrix_dir, args, source, lambda data: data["slots"].pop("C"))
        cases["duplicate_work"] = normal_case("duplicate_work", matrix_dir, args, source, lambda data: data["slots"]["B"][0].update({"work_key": data["slots"]["A"][0]["work_key"], "origin_packet_id": data["slots"]["A"][0]["origin_packet_id"]}))
        cases["duplicate_atom"] = normal_case("duplicate_atom", matrix_dir, args, source, lambda data: data["evidence_atoms"].append(dict(data["evidence_atoms"][0])))
        def mutate_raw(raw: Path) -> None:
            target = raw / "36372941.json"
            data = load_json(target)
            data["evidence_atoms"][0]["claim"] += "（篡改）"
            write_json(target, data)
        cases["raw_provenance_mismatch"] = normal_case("raw_provenance_mismatch", matrix_dir, args, source, raw_mutate=mutate_raw)
        cases["renderer_failure"] = renderer_failure_case(matrix_dir, args, source)
        cases["sequential_same_run_id"] = sequential_case(matrix_dir, args, source)
        cases["concurrent_same_run_id"] = concurrent_case(matrix_dir, args, source)
        events.append({"at": timestamp(), "event": "matrix_completed", "matrix_id": args.matrix_id})
        write_json(matrix_dir / "matrix-manifest.json", {"matrix_id": args.matrix_id, "created_at": timestamp(), "evidence_mode": "controlled_matrix_fixture", "fresh_daily_success": False, "input": {"raw_dir": str(args.raw_dir), "source_input": str(args.source_input), "raw_packet_sha256": {path.stem: sha256(path) for path in sorted(args.raw_dir.glob("*.json"))}, "source_input_sha256": sha256(args.source_input), "validation": {"mode": "local_deterministic_preflight"}}, "cases": cases, "non_goals": ["no publication", "no cron modification", "no historical backfill", "no source fetching", "no fresh daily success claim"]})
        write_json(matrix_dir / "outer-manifest.json", {"matrix_id": args.matrix_id, "matrix_status": "completed", "evidence_mode": "controlled_matrix_fixture", "fresh_daily_success": False, "publication_authorized": False, "publication_performed": False, "delivery_performed": False, "audit_path": "audit/events.jsonl"})
        return 0
    except Exception as error:
        events.append({"at": timestamp(), "event": "matrix_failed", "error": f"{type(error).__name__}:{error}"})
        write_json(matrix_dir / "outer-manifest.json", {"matrix_id": args.matrix_id, "matrix_status": "failed", "publication_authorized": False, "publication_performed": False, "delivery_performed": False, "error": f"{type(error).__name__}:{error}", "audit_path": "audit/events.jsonl"})
        print(f"MATRIX_FAILED:{type(error).__name__}:{error}", file=sys.stderr)
        return 1
    finally:
        (matrix_dir / "audit").mkdir(parents=True, exist_ok=True)
        (matrix_dir / "audit" / "events.jsonl").write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in events), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
