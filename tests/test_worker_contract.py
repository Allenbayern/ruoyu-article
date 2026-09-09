from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys


def test_worker_contract_records_explicit_fallback_without_claiming_skill_success():
    assert importlib.util.find_spec("article_group.worker_contract") is not None
    from article_group.worker_contract import resolve_worker_capability

    result = resolve_worker_capability(
        requested_skill="ruoyu-controlled-production",
        registered_skills={"ruoyu-article-production"},
        fallback_allowed=True,
        stage="drafting",
    )
    assert result == {
        "status": "fallback",
        "requested_skill": "ruoyu-controlled-production",
        "fallback_used": True,
        "fallback_reason": "requested_skill_not_registered",
    }


def test_worker_contract_blocks_missing_skill_for_review_stages():
    from article_group.worker_contract import resolve_worker_capability

    result = resolve_worker_capability(
        requested_skill="ruoyu-controlled-production",
        registered_skills=set(),
        fallback_allowed=True,
        stage="prepublication",
    )
    assert result["status"] == "blocked"
    assert result["fallback_used"] is False


def test_worker_contract_rejects_raw_html_and_requires_structured_extract():
    from article_group.worker_contract import validate_worker_input

    errors = validate_worker_input({"input_kind": "raw_html", "html": "<p>raw</p>"})

    assert "worker_input_kind_invalid" in errors
    assert "worker_raw_html_not_allowed:html" in errors
    assert "worker_structured_extract_missing" in errors


def test_worker_dispatch_record_keeps_fallback_metadata_and_blocks_bad_input():
    from article_group.worker_contract import build_worker_dispatch_record

    record = build_worker_dispatch_record(
        requested_skill="missing-skill",
        registered_skills=set(),
        fallback_allowed=True,
        stage="prepublication",
        worker_input={"input_kind": "raw_html", "html": "<p>raw</p>"},
    )

    assert record["schema_version"] == "worker-dispatch-v1"
    assert record["status"] == "blocked"
    assert record["capability"]["fallback_used"] is False
    assert "worker_raw_html_not_allowed:html" in record["input_errors"]


def test_worker_preflight_cli_emits_auditable_fallback_record(tmp_path: Path, capsys):
    from scripts import worker_dispatch_preflight

    input_path = tmp_path / "worker-input.json"
    input_path.write_text(
        json.dumps({"input_kind": "structured_extract", "extract": {"facts": ["x"]}}),
        encoding="utf-8",
    )

    exit_code = worker_dispatch_preflight.main(
        [
            "--requested-skill",
            "missing-skill",
            "--stage",
            "drafting",
            "--fallback-allowed",
            "--input",
            str(input_path),
            "--project-root",
            str(tmp_path / "project"),
            "--codex-skills-root",
            str(tmp_path / "codex"),
        ]
    )

    assert exit_code == 0
    record = json.loads(capsys.readouterr().out)
    assert record["status"] == "fallback"
    assert record["capability"]["fallback_used"] is True


def test_worker_preflight_direct_script_entrypoint_resolves_project_package():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "worker_dispatch_preflight.py"), "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Validate a worker dispatch" in result.stdout
