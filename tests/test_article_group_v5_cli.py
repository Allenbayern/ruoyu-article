from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "v5" / "controlled-001"
SCRIPT = ROOT / "scripts" / "article_group_v5.py"
EXPECTED_FILES = {
    "experiment": "experiment-record.json",
    "lifecycle": "content-lifecycle.json",
    "dna": "article-dna.json",
    "failures": "failure-samples.json",
    "quotas": "dynamic-quotas.json",
    "strategy": "strategy-library.json",
    "resources": "resource-plan.json",
    "verify": "v5-verification.json",
}


def invoke(
    command: str,
    *,
    run_dir: Path | None = FIXTURE,
    output_dir: Path | None = None,
    output_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(SCRIPT), command]
    if run_dir is not None:
        args.extend(["--run-dir", str(run_dir)])
    if output_dir is not None:
        args.extend(["--output-dir", str(output_dir)])
    if output_path is not None:
        args.extend(["--output-path", str(output_path)])
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_verify_writes_eight_v5_artifacts_and_stays_non_authorizing(tmp_path: Path):
    result = invoke("verify", output_dir=tmp_path)

    assert result.returncode == 0, result.stderr or result.stdout
    assert {path.name for path in tmp_path.iterdir()} == {
        "experiment-record.json",
        "content-lifecycle.json",
        "article-dna.json",
        "failure-samples.json",
        "dynamic-quotas.json",
        "strategy-library.json",
        "resource-plan.json",
        "v5-verification.json",
    }
    report = json.loads(
        (tmp_path / "v5-verification.json").read_text(encoding="utf-8")
    )
    assert report["payload"]["read_back"] is True
    assert report["payload"]["publication_authorization"] == "not_authorized"
    assert not list(tmp_path.glob("*.html"))


def test_v5_cli_requires_explicit_run_and_output_and_refuses_overwrite(
    tmp_path: Path,
):
    assert invoke("verify", run_dir=None, output_dir=tmp_path).returncode == 2

    output = tmp_path / "experiment-record.json"
    output.write_text("{}\n", encoding="utf-8")
    result = invoke("experiment", output_path=output)

    assert result.returncode != 0
    assert "refuse_overwrite" in result.stdout


def test_each_v5_subcommand_writes_its_artifact_to_an_explicit_path(
    tmp_path: Path,
):
    for command, filename in EXPECTED_FILES.items():
        output = tmp_path / f"{command}-explicit.json"
        result = invoke(command, output_path=output)

        assert result.returncode == 0, result.stderr or result.stdout
        artifact = json.loads(output.read_text(encoding="utf-8"))
        assert set(artifact) == {
            "schema_version",
            "run_id",
            "generated_at",
            "input_hashes",
            "payload",
        }
        assert artifact["schema_version"].startswith("v5-")
        assert filename in result.stdout


def test_verify_is_idempotent_but_refuses_different_content(tmp_path: Path):
    first = invoke("verify", output_dir=tmp_path)
    second = invoke("verify", output_dir=tmp_path)

    assert first.returncode == 0, first.stderr or first.stdout
    assert second.returncode == 0, second.stderr or second.stdout

    final = tmp_path / "v5-verification.json"
    changed = json.loads(final.read_text(encoding="utf-8"))
    changed["payload"]["test_marker"] = "different-content"
    final.write_text(
        json.dumps(changed, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    third = invoke("verify", output_dir=tmp_path)

    assert third.returncode != 0
    assert "refuse_overwrite" in third.stdout
    assert json.loads(final.read_text(encoding="utf-8"))["payload"][
        "test_marker"
    ] == "different-content"
