#!/usr/bin/env python3
"""No-agent shadow runner for the explicit daily3 offline orchestrator.

This is intentionally isolated from the production 17:00 cron job. It copies the
controlled fixture source input only to bind a fresh shadow run_id, invokes the
accepted offline orchestrator, and rejects every result unless all three slots,
provenance, and retained delivery artifacts verify. It never publishes.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tmp" / "daily3-real-1905-20260718"
ORCHESTRATOR = ROOT / "scripts" / "daily3_production_orchestrator.py"
DEFAULT_OUTPUT_BASE = Path(os.environ.get('MEDIA_INTEL_SHADOW_OUTPUT', str(Path.home() / '.hermes' / 'artifacts' / 'media-intel' / 'daily3-shadow')))
SLOTS = ("A", "B", "C")


def sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(code: str, detail: str = "") -> None:
    payload = {"status": "shadow_failed", "failure_code": code, "fixture_only": code == "SHADOW_FIXTURE_ONLY_NOT_FRESH_DAILY"}
    if detail:
        try:
            payload.update(json.loads(detail))
        except json.JSONDecodeError:
            payload["detail"] = detail
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)
    raise SystemExit(1)


def fresh_run_id() -> str:
    requested = os.environ.get("DAILY3_SHADOW_RUN_ID")
    if requested:
        return requested
    return "daily3-shadow-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def write_source_copy(source: Path, destination: Path, run_id: str) -> str:
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail("SHADOW_SOURCE_INPUT_INVALID", str(error))
    if not isinstance(data, dict) or not isinstance(data.get("run_id"), str):
        fail("SHADOW_SOURCE_INPUT_INVALID")
    original_sha256 = sha256(source)
    data["run_id"] = run_id
    destination.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return original_sha256


def verify(run_dir: Path, run_id: str) -> dict[str, Any]:
    try:
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        provenance = json.loads((run_dir / "provenance-report.json").read_text(encoding="utf-8"))
        delivery = json.loads((run_dir / "delivery" / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail("SHADOW_ARTIFACT_INVALID", str(error))
    required = {
        "run_id": run_id,
        "status": "completed_nonpublishing_candidate",
        "source_packet_verified": True,
        "three_slot_structural_gate_passed": True,
        "delivery_html_validated": True,
        "delivery_candidate_created": True,
        "publication_authorized": False,
        "publication_performed": False,
    }
    if not isinstance(manifest, dict) or any(manifest.get(key) != value for key, value in required.items()):
        fail("SHADOW_MANIFEST_CONTRACT_FAILED")
    if not isinstance(provenance, dict) or provenance.get("status") != "pass" or provenance.get("phases") != {"raw_source": "passed", "adapter": "passed", "gate": "passed"}:
        fail("SHADOW_PROVENANCE_CONTRACT_FAILED")
    if not isinstance(delivery, dict) or delivery.get("run_id") != run_id or delivery.get("publication_authorized") is not False or delivery.get("publication_performed") is not False:
        fail("SHADOW_DELIVERY_CONTRACT_FAILED")
    slots = delivery.get("slots")
    if not isinstance(slots, dict) or set(slots) != set(SLOTS):
        fail("SHADOW_THREE_SLOT_DELIVERY_FAILED")
    for slot in SLOTS:
        slot_dir = run_dir / "delivery" / "slots" / slot
        if not all((slot_dir / name).is_file() for name in ("article.html", "preview.html", "evidence.json")):
            fail("SHADOW_THREE_SLOT_DELIVERY_FAILED", slot)
    return {"manifest_sha256": sha256(run_dir / "manifest.json"), "provenance_sha256": sha256(run_dir / "provenance-report.json"), "delivery_manifest_sha256": sha256(run_dir / "delivery" / "manifest.json")}


def main() -> int:
    output_base = Path(os.environ.get("DAILY3_SHADOW_OUTPUT_BASE", str(DEFAULT_OUTPUT_BASE))).expanduser()
    run_id = fresh_run_id()
    fail("SHADOW_FIXTURE_ONLY_NOT_FRESH_DAILY", json.dumps({"run_id": run_id, "fixture_only": True}, ensure_ascii=False, sort_keys=True))
    if not all((FIXTURE / relative).is_file() for relative in ("source-input-draft.json", "raw-packets/36372941.json", "raw-packets/37242440.json", "raw-packets/37379599.json")):
        fail("SHADOW_FIXTURE_INCOMPLETE")

    output_base.mkdir(parents=True, exist_ok=True)
    if (output_base / run_id).exists():
        fail("SHADOW_RUN_OUTPUT_ALREADY_EXISTS")
    with tempfile.TemporaryDirectory(prefix="daily3-shadow-source-") as temporary:
        source_copy = Path(temporary) / "source-input.json"
        source_input_sha256 = write_source_copy(FIXTURE / "source-input-draft.json", source_copy, run_id)
        result = subprocess.run([
            sys.executable, str(ORCHESTRATOR), "--run-id", run_id,
            "--raw-dir", str(FIXTURE / "raw-packets"), "--source-input", str(source_copy),
            "--output-base", str(output_base),
        ], cwd=ROOT, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        fail("SHADOW_ORCHESTRATOR_FAILED", (result.stderr or result.stdout).strip())
    run_dir = output_base / run_id
    hashes = verify(run_dir, run_id)
    evidence = {
        "status": "shadow_completed_nonpublishing",
        "run_id": run_id,
        "run_dir": str(run_dir),
        "source_fixture_sha256": source_input_sha256,
        "publication_authorized": False,
        "publication_performed": False,

        **hashes,
    }
    (run_dir / "shadow-cron-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
