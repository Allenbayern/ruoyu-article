from __future__ import annotations

import importlib
import json
import os
from datetime import date
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load(module_name: str):
    return importlib.import_module(module_name)


def test_newrank_watch_missing_token_is_stable_and_side_effect_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load("scripts.codex_newrank_watch")
    output_root = tmp_path / "newrank"
    monkeypatch.delenv("NEWRANK_N_TOKEN", raising=False)

    result = module.main(["--days", "1", "--output-root", str(output_root)])

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == "source_unavailable\n"
    assert captured.err == ""
    assert not output_root.exists()


def test_newrank_watch_uses_runtime_token_and_immutable_date_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load("scripts.codex_newrank_watch")
    output_root = tmp_path / "newrank"
    seen: dict[str, object] = {}
    monkeypatch.setenv("NEWRANK_N_TOKEN", "runtime-token-that-must-not-print")
    monkeypatch.setattr(module, "_today", lambda: date(2026, 8, 25))

    class FakeCollector:
        def __init__(self, *, n_token: str) -> None:
            seen["token"] = n_token

        def collect(self, public_times: list[str], output: Path) -> dict[str, object]:
            seen["public_times"] = public_times
            seen["output"] = output
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text('{"status":"ok"}\n', encoding="utf-8")
            output.with_name(output.name + ".manifest.json").write_text(
                '{"status":"ok"}\n', encoding="utf-8"
            )
            return {"status": "ok"}

    monkeypatch.setattr(module.newrank_hot_article, "NewrankCollector", FakeCollector)

    first = module.main(["--days", "2", "--output-root", str(output_root)])
    first_output = output_root / "2026-08-25" / "newrank-hot-articles.json"
    second = module.main(["--days", "2", "--output-root", str(output_root)])

    captured = capsys.readouterr()
    assert first == 0
    assert second == 2
    assert seen["token"] == "runtime-token-that-must-not-print"
    assert seen["public_times"] == ["2026-08-25", "2026-08-24"]
    assert seen["output"] == first_output
    assert "runtime-token-that-must-not-print" not in captured.out
    assert first_output.read_text(encoding="utf-8") == '{"status":"ok"}\n'


def test_daily_article_runner_requires_explicit_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load("scripts.codex_daily_article_runner")

    result = module.main(
        ["--date", "2026-08-25", "--output-root", str(tmp_path / "run")]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == "input_unavailable\n"
    assert captured.err == ""


def test_daily_article_runner_invokes_article_lane_without_publish_or_kanban(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load("scripts.codex_daily_article_runner")
    input_path = tmp_path / "candidates.jsonl"
    input_path.write_text('{"title":"candidate","summary":"evidence"}\n', encoding="utf-8")
    output_root = tmp_path / "article-run"
    seen: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen["command"] = command
        seen["kwargs"] = kwargs
        output_root.mkdir()
        for name in module.REQUIRED_ARTIFACTS:
            path = output_root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("evidence\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, '{"status":"OK","lane":"article"}\n', "")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.main(
        [
            "--date",
            "2026-08-25",
            "--input",
            str(input_path),
            "--output-root",
            str(output_root),
        ]
    )

    captured = capsys.readouterr()
    command = seen["command"]
    assert isinstance(command, list)
    assert result == 0
    assert captured.err == ""
    assert "--lane" in command and command[command.index("--lane") + 1] == "article"
    assert "--dailyhot-article" in command
    assert not any("publish" in str(item).lower() for item in command)
    assert not any("kanban" in str(item).lower() for item in command)
    manifest = json.loads((output_root / "codex-daily-article-run.json").read_text(encoding="utf-8"))
    assert manifest["publication_authorized"] is False
    assert manifest["publication_performed"] is False
    assert manifest["hermes_modified"] is False
    assert manifest["kanban_modified"] is False


def test_review_audit_is_read_only_and_reports_schema_and_run_structure(tmp_path: Path) -> None:
    module = _load("scripts.codex_review_audit")
    home_agents = tmp_path / "home-AGENTS.md"
    project_agents = tmp_path / "project" / "AGENTS.md"
    skills = tmp_path / "skills"
    schema = tmp_path / "project" / "schemas" / "review.json"
    runs = tmp_path / "project" / "runs"
    home_agents.write_text("home rules\n", encoding="utf-8")
    project_agents.parent.mkdir(parents=True, exist_ok=True)
    project_agents.write_text("project rules\n", encoding="utf-8")
    (skills / "alpha").mkdir(parents=True)
    (skills / "alpha" / "SKILL.md").write_text("skill\n", encoding="utf-8")
    schema.parent.mkdir(parents=True, exist_ok=True)
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["decision", "scope_reviewed", "findings", "non_findings", "coverage_gaps"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (runs / "2026-08-25" / "review").mkdir(parents=True)
    (runs / "2026-08-25" / "review" / "result.json").write_text("{}\n", encoding="utf-8")
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    report = module.build_report(
        home_agents=home_agents,
        project_agents=project_agents,
        skills_root=skills,
        schema_path=schema,
        runs_root=runs,
        recent_limit=3,
    )

    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert before == after
    assert report["read_only"] is True
    assert report["mutation"]["files_written"] == []
    assert report["checks"]["review_schema"]["valid_json"] is True
    assert report["checks"]["review_schema"]["required_fields"] == [
        "decision",
        "scope_reviewed",
        "findings",
        "non_findings",
        "coverage_gaps",
    ]
    assert report["checks"]["codex_skills"]["skill_count"] == 1
    assert report["checks"]["recent_runs"]["entries"][0]["name"] == "2026-08-25"


def test_review_audit_cli_emits_json_without_writing_an_output_file(capsys: pytest.CaptureFixture[str]) -> None:
    module = _load("scripts.codex_review_audit")

    result = module.main([])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result in {0, 2}
    assert payload["read_only"] is True
    assert payload["mutation"]["files_written"] == []
    assert captured.err == ""


def test_review_audit_can_write_an_immutable_monthly_snapshot(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    module = _load("scripts.codex_review_audit")
    home_agents = tmp_path / "home-AGENTS.md"
    project_agents = tmp_path / "project" / "AGENTS.md"
    skills = tmp_path / "skills"
    schema = tmp_path / "project" / "schemas" / "review.json"
    runs = tmp_path / "project" / "runs"
    output_root = tmp_path / "audit-output"
    home_agents.write_text("home rules\n", encoding="utf-8")
    project_agents.parent.mkdir(parents=True, exist_ok=True)
    project_agents.write_text("project rules\n", encoding="utf-8")
    (skills / "alpha").mkdir(parents=True)
    (skills / "alpha" / "SKILL.md").write_text("skill\n", encoding="utf-8")
    schema.parent.mkdir(parents=True, exist_ok=True)
    schema.write_text(json.dumps({"type": "object", "required": ["decision"]}) + "\n", encoding="utf-8")
    runs.mkdir(parents=True)

    first = module.main(
        [
            "--home-agents",
            str(home_agents),
            "--project-agents",
            str(project_agents),
            "--skills-root",
            str(skills),
            "--schema",
            str(schema),
            "--runs-root",
            str(runs),
            "--month",
            "2026-08",
            "--output-root",
            str(output_root),
        ]
    )
    first_output = output_root / "codex-review-audit-2026-08.json"
    first_manifest = output_root / "codex-review-audit-2026-08.json.manifest.json"
    first_stdout = capsys.readouterr()

    second = module.main(
        [
            "--month",
            "2026-08",
            "--output-root",
            str(output_root),
        ]
    )
    second_stdout = capsys.readouterr()

    assert first == 0
    assert second == 2
    assert json.loads(first_stdout.out)["status"] == "written"
    assert second_stdout.out == "artifact_exists\n"
    assert json.loads(first_output.read_text(encoding="utf-8"))["read_only"] is True
    manifest = json.loads(first_manifest.read_text(encoding="utf-8"))
    assert manifest["month"] == "2026-08"
    assert manifest["report_sha256"]
