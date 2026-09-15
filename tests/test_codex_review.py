from __future__ import annotations

import json
from pathlib import Path

import pytest

from article_group import codex_review


def test_parse_l2_output_uses_last_structured_json_line():
    output = "progress\n{" + '"noise": true' + "}\n" + json.dumps(
        {
            "decision": "needs_changes",
            "findings": [],
            "scope_reviewed": [],
            "non_findings": [],
            "coverage_gaps": [],
        }
    )

    result = codex_review._parse_l2_output(output)

    assert result is not None
    assert result["decision"] == "needs_changes"


def test_parse_l2_output_rejects_unstructured_output():
    assert codex_review._parse_l2_output("review text without contract") is None


def test_run_review_fails_closed_when_codex_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run_root = tmp_path / "run"
    run_root.mkdir()
    output = run_root / "review.json"
    monkeypatch.setattr(codex_review.shutil, "which", lambda _: None)

    with pytest.raises(SystemExit, match="codex executable not found"):
        codex_review.run_review(
            codex_review.build_parser().parse_args(
                [
                    "--mode",
                    "normal",
                    "--run-root",
                    str(run_root),
                    "--output",
                    str(output),
                    "--request",
                    "review the change",
                ]
            )
        )


def test_l2_record_keeps_publication_unauthorized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run_root = tmp_path / "run"
    run_root.mkdir()
    output = run_root / "review.json"

    class Completed:
        returncode = 0
        stdout = json.dumps(
            {
                "decision": "approve",
                "scope_reviewed": ["artifact"],
                "findings": [],
                "non_findings": ["tests passed"],
                "coverage_gaps": [],
            }
        )
        stderr = ""

    monkeypatch.setattr(codex_review.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(codex_review.subprocess, "run", lambda *args, **kwargs: Completed())

    exit_code = codex_review.run_review(
        codex_review.build_parser().parse_args(
            [
                "--mode",
                "l2",
                "--run-root",
                str(run_root),
                "--output",
                str(output),
                "--request",
                "review the change",
            ]
        )
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert record["decision"] == "approve"
    assert record["structured_result"] is True
    assert record["publication_authorization"] == "not_authorized"


def test_normal_review_record_is_explicitly_not_an_article_independent_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    run_root = tmp_path / "run"
    run_root.mkdir()
    output = run_root / "review.json"

    class Completed:
        returncode = 0
        stdout = "normal review completed"
        stderr = ""

    monkeypatch.setattr(codex_review.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(codex_review.subprocess, "run", lambda *args, **kwargs: Completed())

    exit_code = codex_review.run_review(
        codex_review.build_parser().parse_args(
            [
                "--mode",
                "normal",
                "--run-root",
                str(run_root),
                "--output",
                str(output),
                "--request",
                "review the change",
            ]
        )
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert record["decision"] == "review_completed"
    assert record["status"] == "PASS"
    assert record["review_kind"] == "repository_code_review"
    assert record["independent_review_eligible"] is False


def test_timeout_record_stays_unverified_and_keeps_article_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run_root = tmp_path / "run"
    run_root.mkdir()
    output = run_root / "review.json"

    def boom(*args, **kwargs):
        raise __import__("subprocess").TimeoutExpired(cmd=args[0] if args else "codex", timeout=kwargs.get("timeout", 1))

    monkeypatch.setattr(codex_review.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(codex_review.subprocess, "run", boom)

    exit_code = codex_review.run_review(
        codex_review.build_parser().parse_args(
            [
                "--mode",
                "l2",
                "--run-root",
                str(run_root),
                "--output",
                str(output),
                "--request",
                "review one article",
                "--timeout-seconds",
                "1",
                "--article-task-id",
                "at-art-001",
                "--article-id",
                "art-001",
                "--draft-path",
                "articles/art-001.md",
                "--draft-sha256",
                "a" * 64,
                "--attempt",
                "1",
                "--l2-required",
                "--l2-risk-basis",
                "人物动机需要独立核对",
            ]
        )
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert record["status"] == "UNVERIFIED"
    assert record["decision"] == "timeout"
    assert record["article_task_id"] == "at-art-001"
    assert record["next_step"] == "resume_single_article"
    assert record["publication_authorization"] == "not_authorized"
    assert "review_timeout" in record["coverage_gaps"]


def test_strict_review_sidecar_writes_current_artifact_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run_root = tmp_path / "run"
    (run_root / "articles").mkdir(parents=True)
    (run_root / "review").mkdir()
    (run_root / "articles" / "art-001.md").write_text("正文", encoding="utf-8")
    (run_root / "review" / "body.md").write_text("正文", encoding="utf-8")
    (run_root / "review" / "title-pack.json").write_text("{}", encoding="utf-8")
    (run_root / "batch.json").write_text(
        json.dumps(
            {
                "production_contract": "article-first-v1",
                "brief_contract": "writing-brief-v2",
                "title_contract": "title-pack-v1",
                "legacy_compatibility": False,
            }
        ),
        encoding="utf-8",
    )
    output = run_root / "review.json"

    class Completed:
        returncode = 0
        stdout = json.dumps(
            {
                "decision": "approve",
                "scope_reviewed": ["artifact"],
                "findings": [],
                "non_findings": [],
                "coverage_gaps": [],
            }
        )
        stderr = ""

    monkeypatch.setattr(codex_review.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(codex_review.subprocess, "run", lambda *args, **kwargs: Completed())

    exit_code = codex_review.run_review(
        codex_review.build_parser().parse_args(
            [
                "--mode",
                "l2",
                "--run-root",
                str(run_root),
                "--output",
                str(output),
                "--request",
                "review one article",
                "--article-id",
                "art-001",
                "--artifact-path",
                "articles/art-001.md",
                "--body-path",
                "review/body.md",
                "--title-pack-path",
                "review/title-pack.json",
            ]
        )
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert record["artifact_path"] == "articles/art-001.md"
    assert len(record["artifact_sha256"]) == 64
    assert len(record["body_sha256"]) == 64
    assert len(record["title_pack_sha256"]) == 64
    assert record["created_from_run"] == "run"


def test_l2_review_json_records_an_externally_produced_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The L2 gate must stay usable when no Codex CLI is installed."""

    run_root = tmp_path / "run"
    run_root.mkdir()
    output = run_root / "review.json"
    external = run_root / "dsh-review.json"
    external.write_text(
        json.dumps(
            {
                "decision": "needs_changes",
                "scope_reviewed": ["artifact"],
                "findings": [{"id": "F1", "severity": "high"}],
                "non_findings": [],
                "coverage_gaps": ["no runtime execution"],
            }
        ),
        encoding="utf-8",
    )

    def _no_subprocess(*args, **kwargs):
        raise AssertionError("--review-json must not spawn the Codex CLI")

    monkeypatch.setattr(codex_review.shutil, "which", lambda _: None)
    monkeypatch.setattr(codex_review.subprocess, "run", _no_subprocess)

    exit_code = codex_review.run_review(
        codex_review.build_parser().parse_args(
            [
                "--mode",
                "l2",
                "--run-root",
                str(run_root),
                "--output",
                str(output),
                "--request",
                "review one article",
                "--review-json",
                str(external),
            ]
        )
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    # Parity with the native path: a successfully produced review exits 0 even
    # when the decision is not an approval; the decision lives in the JSON.
    assert exit_code == 0
    assert record["decision"] == "needs_changes"
    assert record["status"] == "FAIL"
    assert record["structured_result"] is True
    assert record["review_source"] == "external_review_json"
    assert record["publication_authorization"] == "not_authorized"
    assert record["coverage_gaps"] == ["no runtime execution"]
    assert output.with_suffix(".log").read_text(encoding="utf-8").strip().startswith("{")


def test_l2_review_json_fails_closed_on_an_invalid_document(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run_root = tmp_path / "run"
    run_root.mkdir()
    output = run_root / "review.json"
    external = run_root / "not-a-review.json"
    external.write_text(json.dumps({"summary": "looks fine"}), encoding="utf-8")
    monkeypatch.setattr(codex_review.shutil, "which", lambda _: None)

    exit_code = codex_review.run_review(
        codex_review.build_parser().parse_args(
            [
                "--mode",
                "l2",
                "--run-root",
                str(run_root),
                "--output",
                str(output),
                "--request",
                "review one article",
                "--review-json",
                str(external),
            ]
        )
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert record["decision"] == "evidence_insufficient"
    assert record["error"] == "l2_structured_result_missing"
    assert record["coverage_gaps"] == ["l2_structured_result_missing"]
