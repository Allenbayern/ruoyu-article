import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "daily3_shadow_cron_runner.py"
FIXTURE = ROOT / "tmp" / "daily3-real-1905-20260718"



def run_shadow(tmp_path: Path, run_id: str) -> subprocess.CompletedProcess[str]:
    env = os.environ | {
        "DAILY3_SHADOW_OUTPUT_BASE": str(tmp_path),
        "DAILY3_SHADOW_RUN_ID": run_id,
    }
    return subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, env=env, text=True, capture_output=True, check=False)


def test_shadow_runner_labels_controlled_fixture_as_not_fresh_and_creates_no_candidate(tmp_path):
    result = run_shadow(tmp_path, "shadow-test-evidence")

    assert result.returncode == 1
    evidence = json.loads(result.stderr)
    assert evidence["status"] == "shadow_failed"
    assert evidence["failure_code"] == "SHADOW_FIXTURE_ONLY_NOT_FRESH_DAILY"
    assert evidence["run_id"] == "shadow-test-evidence"
    assert evidence["fixture_only"] is True
    assert not (tmp_path / "shadow-test-evidence").exists()


def test_shadow_runner_rejects_fixture_only_before_output_claim(tmp_path):
    first = run_shadow(tmp_path, "shadow-test-duplicate")
    second = run_shadow(tmp_path, "shadow-test-duplicate")

    assert first.returncode == 1
    assert second.returncode == 1
    assert json.loads(first.stderr)["failure_code"] == "SHADOW_FIXTURE_ONLY_NOT_FRESH_DAILY"
    assert json.loads(second.stderr)["failure_code"] == "SHADOW_FIXTURE_ONLY_NOT_FRESH_DAILY"


def test_shadow_runner_contains_no_external_validator_checkout_or_pin():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "gzh-design-skill" not in source
    assert "validate_gzh_html.py" not in source
    assert "EXPECTED_VALIDATOR" not in source
