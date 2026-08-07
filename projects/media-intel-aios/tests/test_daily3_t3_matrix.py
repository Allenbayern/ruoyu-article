import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "daily3_t3_matrix.py"
FIXTURE = ROOT / "tmp" / "daily3-real-1905-20260718"


def test_persistent_matrix_retains_real_case_evidence_and_fail_closed_contracts(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output-base",
            str(tmp_path),
            "--matrix-id",
            "t3-focused-matrix",
            "--raw-dir",
            str(FIXTURE / "raw-packets"),
            "--source-input",
            str(FIXTURE / "source-input-draft.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    matrix_dir = tmp_path / "t3-focused-matrix"
    manifest = json.loads((matrix_dir / "matrix-manifest.json").read_text(encoding="utf-8"))
    outer = json.loads((matrix_dir / "outer-manifest.json").read_text(encoding="utf-8"))
    expected_cases = {
        "positive_abc",
        "missing_c",
        "duplicate_work",
        "duplicate_atom",
        "raw_provenance_mismatch",
        "renderer_failure",
        "sequential_same_run_id",
        "concurrent_same_run_id",
    }
    assert set(manifest["cases"]) == expected_cases
    assert outer["matrix_status"] == "completed"
    assert outer["publication_authorized"] is False
    assert outer["publication_performed"] is False
    assert (matrix_dir / "audit" / "events.jsonl").is_file()

    for name, record in manifest["cases"].items():
        case_dir = matrix_dir / "cases" / name
        assert (case_dir / "stdout.txt").is_file()
        assert (case_dir / "stderr.txt").is_file()
        assert (case_dir / "result.json").is_file()
        assert record["publication_authorized"] is False
        assert record["publication_performed"] is False

    positive = manifest["cases"]["positive_abc"]
    assert positive["exit_code"] == 0
    assert positive["delivery_candidate_created"] is True
    assert positive["release_acceptance"]["status"] == "not_accepted"
    assert set(positive["raw_packet_sha256"]) == {"36372941", "37242440", "37379599"}

    for name in expected_cases - {"positive_abc"}:
        record = manifest["cases"][name]
        assert record["exit_code"] != 0
        assert record["failure_code"]
        assert record["delivery_candidate_created"] is False
        assert record["delivery_exists"] is False


def test_matrix_cases_use_explicit_case_local_source_bundles_and_ledgers(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output-base",
            str(tmp_path),
            "--matrix-id",
            "t3-bundle-ledger-compatibility",
            "--raw-dir",
            str(FIXTURE / "raw-packets"),
            "--source-input",
            str(FIXTURE / "source-input-draft.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    matrix_dir = tmp_path / "t3-bundle-ledger-compatibility"
    manifest = json.loads((matrix_dir / "matrix-manifest.json").read_text(encoding="utf-8"))
    positive_input = matrix_dir / "cases" / "positive_abc" / "input"
    assert (positive_input / "source-bundle.json").is_file()
    assert (positive_input / "delivery-ledger.json").is_file()
    assert manifest["cases"]["positive_abc"]["source_bundle_verified"] is True
    assert manifest["cases"]["positive_abc"]["delivery_ledger_committed"] is True
