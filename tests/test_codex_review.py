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
