"""Actual V4/V5 evidence, including stale and tampered bundles."""
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from article_group.controller_v1 import verify_context
from article_group.v4.verification import run_v4_verification
from article_group.v5.verification import run_v5_verification


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def context(tmp_path):
    args = {"expected_contexts": {}}
    for layer, fixture, runner in (
        ("v4", "controlled-002", run_v4_verification),
        ("v5", "controlled-001", run_v5_verification),
    ):
        source = tmp_path / f"{layer}-source"
        shutil.copytree(Path("tests/fixtures") / layer / fixture, source)
        output = tmp_path / layer
        report_path = output / f"{layer}-verification.json"
        report = runner(source, output_path=report_path)
        args[f"{layer}_run_dir"] = output
        args[f"{layer}_source_dir"] = source
        args["expected_contexts"][layer] = {
            "run_id": report["run_id"], "report_sha256": sha(report_path)
        }
    return args


def test_full_context_rechecks_all_modules_and_preserves_gaps(context):
    result = verify_context(**context)
    assert result["status"] == "PASS", result
    assert len(result["layers"]["v4"]["module_checks"]) == 6
    assert len(result["layers"]["v5"]["module_checks"]) == 7
    assert result["layers"]["v4"]["missing_source_roles"] == ["independent_short_review"]
    assert result["layers"]["v4"]["retry_requirements"]
    assert result["layers"]["v5"]["manual_escalations"]
    assert result["layers"]["v5"]["synthetic_fixture"] is True
    assert result["publication_authorization"] == "not_authorized"
    assert result["controller_acceptance"] == "not_evaluated"


@pytest.mark.parametrize("layer,filename", [("v4", "gap-priority.json"), ("v5", "article-dna.json")])
def test_changed_module_blocks_even_when_report_says_pass(context, layer, filename):
    path = context[f"{layer}_run_dir"] / filename
    path.write_text('{}\n')
    result = verify_context(**context)
    assert result["status"] == "BLOCKED"
    assert any("hash_mismatch" in e for e in result["layers"][layer]["errors"])


@pytest.mark.parametrize("layer,filename", [("v4", "candidate-pool.json"), ("v5", "draft.md")])
def test_stale_input_blocks(context, layer, filename):
    path = context[f"{layer}_source_dir"] / filename
    if filename.endswith(".md"):
        path.write_text(path.read_text() + "\nchanged material\n")
    else:
        data = json.loads(path.read_text())
        data["candidates"] = []
        path.write_text(json.dumps(data))
    result = verify_context(**context)
    assert result["status"] == "BLOCKED"
    assert result["layers"][layer]["errors"]


def test_wrong_run_binding_blocks(context):
    context["expected_contexts"]["v5"]["run_id"] = "another-run"
    result = verify_context(**context)
    assert "run_id_mismatch" in result["layers"]["v5"]["errors"]


def test_report_symlink_and_missing_layer_block(context, tmp_path):
    path = context["v5_run_dir"] / "v5-verification.json"
    copied = tmp_path / "external.json"
    path.rename(copied)
    path.symlink_to(copied)
    result = verify_context(**context)
    assert result["status"] == "BLOCKED"
    assert "unsafe_or_missing:v5-verification.json" in result["layers"]["v5"]["errors"]
    assert verify_context()["status"] == "BLOCKED"


def test_non_pass_content_cannot_be_promoted(context):
    path = context["v5_run_dir"] / "v5-verification.json"
    report = json.loads(path.read_text())
    report["payload"]["content_status"] = "CONTENT_BLOCKED"
    path.write_text(json.dumps(report))
    context["expected_contexts"]["v5"]["report_sha256"] = sha(path)
    result = verify_context(**context)
    assert result["status"] == "BLOCKED"
    assert result["content_status"] == "CONTENT_BLOCKED"
