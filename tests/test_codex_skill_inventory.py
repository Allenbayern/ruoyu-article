from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import codex_skill_inventory


def _write_skill(root: Path, directory: str, name: str, description: str) -> Path:
    skill_file = root / directory / "SKILL.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(
        f'---\nname: "{name}"\ndescription: "{description}"\n---\n\nbody\n',
        encoding="utf-8",
    )
    return skill_file


def test_inventory_scans_project_and_codex_roots_in_stable_order(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_skills = project_root / ".agents" / "skills"
    codex_root = tmp_path / "codex" / "skills"
    _write_skill(project_skills, "zeta", "zeta", "project skill")
    _write_skill(project_skills, "alpha", "alpha", "another project skill")
    _write_skill(codex_root, "beta", "beta", "user skill")

    report = codex_skill_inventory.build_report(project_root, codex_root)

    assert report["read_only"] is True
    assert report["schema_version"] == "codex-skill-inventory-1"
    assert [item["directory"] for item in report["sources"][0]["skills"]] == ["alpha", "zeta"]
    assert report["sources"][0]["skills"][0]["metadata"] == {
        "description": "another project skill",
        "name": "alpha",
    }
    assert [item["directory"] for item in report["sources"][1]["skills"]] == ["beta"]
    assert report["summary"]["total_skill_count"] == 3


def test_inventory_handles_missing_roots_without_writing(tmp_path: Path) -> None:
    project_root = tmp_path / "missing-project"
    codex_root = tmp_path / "missing-codex"
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    report = codex_skill_inventory.build_report(project_root, codex_root)

    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert before == after
    assert all(source["exists"] is False for source in report["sources"])
    assert report["summary"]["total_skill_count"] == 0


def test_inventory_does_not_read_or_emit_sensitive_files(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_skills = project_root / ".agents" / "skills"
    codex_root = tmp_path / "codex" / "skills"
    _write_skill(project_skills, "safe", "safe", "safe description")
    codex_root.mkdir(parents=True)
    (codex_root / "auth.json").write_text('{"token":"SHOULD_NOT_APPEAR"}\n', encoding="utf-8")
    (codex_root / ".env").write_text("API_KEY=SHOULD_NOT_APPEAR\n", encoding="utf-8")
    (codex_root / "not-a-skill").mkdir()
    (codex_root / "not-a-skill" / "payload.txt").write_text("SHOULD_NOT_APPEAR\n", encoding="utf-8")

    report = codex_skill_inventory.build_report(project_root, codex_root)
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)

    assert "SHOULD_NOT_APPEAR" not in rendered
    assert "auth.json" not in rendered
    assert ".env" not in rendered
    assert [item["directory"] for item in report["sources"][1]["skills"]] == []


def test_inventory_redacts_common_secret_markers_from_frontmatter(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    skill_root = project_root / ".agents" / "skills"
    skill_file = skill_root / "unsafe-description" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(
        '---\nname: unsafe\ndescription: "token=secret-value Bearer abc sk-live-value"\n---\n',
        encoding="utf-8",
    )

    report = codex_skill_inventory.build_report(project_root, tmp_path / "no-codex")
    metadata = report["sources"][0]["skills"][0]["metadata"]

    assert "secret-value" not in metadata["description"]
    assert "abc" not in metadata["description"]
    assert "sk-live-value" not in metadata["description"]
    assert "[REDACTED]" in metadata["description"]


def test_cli_emits_parseable_stable_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project_root = tmp_path / "project"
    _write_skill(project_root / ".agents" / "skills", "one", "one", "one")

    result = codex_skill_inventory.main(
        ["--project-root", str(project_root), "--codex-skills-root", str(tmp_path / "codex")]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["summary"]["project_skill_count"] == 1
    assert captured.out.endswith("\n")
