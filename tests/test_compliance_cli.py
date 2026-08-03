"""Tests for the compliance CLI's three-state surface projection."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from article_group.compliance_cli import main


def _five_gates(*, overall: str, gate1: str = "PASS") -> dict[str, str]:
    return {
        "gate1_news_license": gate1,
        "gate2_privacy": "PASS",
        "gate3_judicial": "PASS",
        "gate4_copyright": "PASS",
        "gate5_sensationalism": "PASS",
        "overall": overall,
    }


def _candidate(*, recommendation: str, gates: dict[str, str], **extra: object) -> dict[str, object]:
    return {
        "candidate_id": "social-1",
        "topic_type": "social",
        "recommendation": recommendation,
        "five_gates": gates,
        **extra,
    }


def test_cli_reports_valid_archived_fail_as_fail_not_all_pass(tmp_path, capsys):
    candidate = _candidate(
        recommendation="Archive",
        gates=_five_gates(overall="FAIL", gate1="FAIL"),
    )
    source = tmp_path / "candidate.json"
    source.write_text(json.dumps(candidate), encoding="utf-8")

    assert main(["--candidate", str(source), "--json"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["compliant"] is True
    assert report["declaration_valid"] is True
    assert report["overall"] == "FAIL"
    assert report["reports"][0]["recommendation"] == "Archive"
    assert report["reports"][0]["overall"] == "FAIL"
    assert "all candidates are pass" not in report["summary"].lower()


def test_cli_reports_valid_conditional_editorial_candidate_with_angle(tmp_path, capsys):
    candidate = _candidate(
        recommendation="A",
        gates=_five_gates(overall="CONDITIONAL", gate1="CONDITIONAL"),
        compliant_angle="Use an institutional-analysis angle.",
    )
    source = tmp_path / "candidate.json"
    source.write_text(json.dumps(candidate), encoding="utf-8")

    assert main(["--candidate", str(source), "--json"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["compliant"] is True
    assert report["declaration_valid"] is True
    assert report["overall"] == "CONDITIONAL"
    assert report["recommendation"] == "A"
    assert report["compliant_angle"] == "Use an institutional-analysis angle."


def test_cli_rejects_invalid_declarations_without_misreporting_grade(tmp_path, capsys):
    candidate = _candidate(
        recommendation="A",
        gates=_five_gates(overall="FAIL", gate1="FAIL"),
    )
    source = tmp_path / "candidate.json"
    source.write_text(json.dumps(candidate), encoding="utf-8")

    assert main(["--candidate", str(source), "--json"]) == 2

    report = json.loads(capsys.readouterr().out)
    assert report["compliant"] is False
    assert report["declaration_valid"] is False
    assert report["overall"] == "FAIL"
    assert report["errors"] == ["candidate_social-1_failed_gate_cannot_recommend_A"]


def test_cli_uses_legacy_result_when_overall_is_missing(tmp_path, capsys):
    gates = _five_gates(overall="PASS")
    gates.pop("overall")
    gates["result"] = "PASS"
    candidate = _candidate(recommendation="A", gates=gates)
    source = tmp_path / "candidate.json"
    source.write_text(json.dumps(candidate), encoding="utf-8")

    assert main(["--candidate", str(source), "--json"]) == 0

    assert json.loads(capsys.readouterr().out)["overall"] == "PASS"


def test_cli_rejects_non_object_pool_member_as_invalid_json_input():
    result = subprocess.run(
        [sys.executable, "-m", "article_group.compliance_cli", "--json"],
        input='{"candidates":["bad"]}',
        text=True,
        capture_output=True,
        cwd=Path(__file__).resolve().parents[1],
        check=False,
    )

    assert result.returncode == 2
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert report["declaration_valid"] is False
    assert report["invalid_declaration_count"] == 1
    assert report["reports"] == []
    assert report["grade_counts"] == {"PASS": 0, "CONDITIONAL": 0, "FAIL": 0}
    assert report["errors"] == ["candidate_record_0_must_be_a_dict"]


def test_cli_counts_one_invalid_dict_declaration_despite_five_gate_errors(tmp_path, capsys):
    candidate = _candidate(
        recommendation="A",
        gates={
            "gate1_news_license": "INVALID",
            "gate2_privacy": "INVALID",
            "gate3_judicial": "INVALID",
            "gate4_copyright": "INVALID",
            "gate5_sensationalism": "INVALID",
            "overall": "INVALID",
        },
    )
    source = tmp_path / "pool.json"
    source.write_text(json.dumps({"candidates": [candidate]}), encoding="utf-8")

    assert main(["--pool", str(source), "--json"]) == 2

    report = json.loads(capsys.readouterr().out)
    assert report["candidate_count"] == 1
    assert report["invalid_declaration_count"] == 1
    assert len(report["errors"]) == 5


def test_cli_counts_each_malformed_pool_member_once(tmp_path, capsys):
    source = tmp_path / "pool.json"
    source.write_text(json.dumps({"candidates": ["bad", None]}), encoding="utf-8")

    assert main(["--pool", str(source), "--json"]) == 2

    report = json.loads(capsys.readouterr().out)
    assert report["candidate_count"] == 0
    assert report["invalid_declaration_count"] == 2
    assert report["errors"] == [
        "candidate_record_0_must_be_a_dict",
        "candidate_record_1_must_be_a_dict",
    ]


def test_cli_counts_malformed_member_alongside_valid_dict(tmp_path, capsys):
    candidate = _candidate(recommendation="A", gates=_five_gates(overall="PASS"))
    source = tmp_path / "pool.json"
    source.write_text(json.dumps({"candidates": [candidate, "bad"]}), encoding="utf-8")

    assert main(["--pool", str(source), "--json"]) == 2

    report = json.loads(capsys.readouterr().out)
    assert report["candidate_count"] == 1
    assert report["invalid_declaration_count"] == 1
    assert report["reports"][0]["declaration_valid"] is True
