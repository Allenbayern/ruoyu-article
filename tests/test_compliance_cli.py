"""Tests for the compliance CLI's three-state surface projection."""

from __future__ import annotations

import json

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
