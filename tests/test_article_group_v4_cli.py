from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from article_group.v4.contracts import validate_artifact_envelope
from article_group.v4.verification import (
    ARTIFACT_FILES,
    run_v4_verification,
    validate_v4_verification,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "v4" / "controlled-002"
SCRIPT = ROOT / "scripts" / "article_group_v4.py"
EXPECTED_FILES = {
    "portfolio-plan.json": "v4-portfolio-plan-v1",
    "evidence-graph.json": "v4-evidence-graph-v1",
    "gap-priority.json": "v4-gap-priority-v1",
    "template-signals.json": "v4-template-signals-v1",
    "effect-feedback.json": "v4-effect-feedback-v1",
    "recovery-actions.json": "v4-recovery-actions-v1",
    "v4-verification.json": "v4-verification-v1",
}


def _invoke(
    command: str,
    *,
    output_dir: Path | None = None,
    output_path: Path | None = None,
    include_run: bool = True,
) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(SCRIPT), command]
    if include_run:
        args.extend(["--run-dir", str(FIXTURE)])
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


def test_verify_writes_all_v4_artifacts_and_separates_source_retry_status(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "verify",
            "--run-dir",
            str(FIXTURE),
            "--output-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    summary = json.loads(result.stdout)
    assert summary["status"] == "PASS"
    expected = {
        "portfolio-plan.json",
        "evidence-graph.json",
        "gap-priority.json",
        "template-signals.json",
        "effect-feedback.json",
        "recovery-actions.json",
        "v4-verification.json",
    }
    assert {path.name for path in tmp_path.iterdir()} == expected
    verification = json.loads((tmp_path / "v4-verification.json").read_text())
    payload = verification["payload"]
    assert payload["decision"] == "PASS"
    assert payload["read_back"] is True
    assert payload["content_status"] == "CONTENT_READY"
    assert payload["publication_authorization"] == "not_authorized"
    assert payload["missing_source_roles"] == ["independent_short_review"]
    assert payload["retry_requirements"]
    assert not list(tmp_path.glob("*.html"))


def test_single_subcommand_rejects_different_existing_output(tmp_path: Path):
    output = tmp_path / "portfolio-plan.json"
    output.write_text("{}\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "plan",
            "--run-dir",
            str(FIXTURE),
            "--output-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "refuse_overwrite" in result.stdout


def test_every_subcommand_requires_explicit_run_and_output(tmp_path: Path):
    for command in ("plan", "graph", "gaps", "templates", "effects", "recover", "verify"):
        missing_run = _invoke(command, output_dir=tmp_path / command, include_run=False)
        assert missing_run.returncode == 2

        missing_output = _invoke(command)
        assert missing_output.returncode == 2


def test_each_subcommand_writes_its_versioned_artifact_to_explicit_file(tmp_path: Path):
    commands = {
        "plan": "portfolio-plan.json",
        "graph": "evidence-graph.json",
        "gaps": "gap-priority.json",
        "templates": "template-signals.json",
        "effects": "effect-feedback.json",
        "recover": "recovery-actions.json",
    }
    for command, filename in commands.items():
        output = tmp_path / f"{command}-explicit.json"
        result = _invoke(command, output_path=output)
        assert result.returncode == 0, result.stderr or result.stdout
        artifact = json.loads(output.read_text(encoding="utf-8"))
        assert set(artifact) == {
            "schema_version",
            "run_id",
            "generated_at",
            "input_hashes",
            "payload",
        }
        assert artifact["schema_version"] == EXPECTED_FILES[filename]
        assert artifact["run_id"] == "v4-fixture-002"
        assert not validate_artifact_envelope(
            artifact,
            EXPECTED_FILES[filename],
            run_id="v4-fixture-002",
        )


def test_verify_is_idempotent_but_refuses_a_different_hash(tmp_path: Path):
    first = _invoke("verify", output_dir=tmp_path)
    second = _invoke("verify", output_dir=tmp_path)
    assert first.returncode == 0, first.stderr or first.stdout
    assert second.returncode == 0, second.stderr or second.stdout

    final = tmp_path / "v4-verification.json"
    changed = json.loads(final.read_text(encoding="utf-8"))
    changed["payload"]["test_marker"] = "different-content"
    final.write_text(json.dumps(changed, ensure_ascii=False) + "\n", encoding="utf-8")

    third = _invoke("verify", output_dir=tmp_path)
    assert third.returncode != 0
    assert "refuse_overwrite" in third.stdout
    assert json.loads(final.read_text(encoding="utf-8"))["payload"]["test_marker"] == (
        "different-content"
    )


def test_direct_verifier_reads_back_seven_artifacts_with_custom_final_path(tmp_path: Path):
    final = tmp_path / "custom-verification.json"
    report = run_v4_verification(FIXTURE, output_path=final)

    assert report["schema_version"] == "v4-verification-v1"
    assert report["payload"]["readback"] == {
        "verified": True,
        "artifact_count": 7,
        "files": list(ARTIFACT_FILES.values()),
    }
    assert not validate_v4_verification(report, run_id="v4-fixture-002")
    assert final.exists()
    assert not (tmp_path / "v4-verification.json").exists()
    assert {
        path.name for path in tmp_path.iterdir()
    } == {
        "custom-verification.json",
        "portfolio-plan.json",
        "evidence-graph.json",
        "gap-priority.json",
        "template-signals.json",
        "effect-feedback.json",
        "recovery-actions.json",
    }


def test_effects_do_not_fabricate_platform_results(tmp_path: Path):
    result = _invoke("effects", output_dir=tmp_path)
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(
        (tmp_path / "effect-feedback.json").read_text(encoding="utf-8")
    )["payload"]
    assert payload["state"] == "candidate"
    assert payload["sample_count"] == 0
    assert payload["aggregates"] == []
    assert payload["baseline"] is None
    assert all(value is None for value in payload["medians"].values())
