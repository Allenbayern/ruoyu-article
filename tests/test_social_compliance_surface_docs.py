"""Contract tests for three-state social-compliance user-facing documents."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_surface_templates_document_three_state_processing_and_fail_boundary():
    for relative_path in (
        "templates/candidate-card.md",
        "templates/social-topic-five-gates.md",
        "templates/writing-brief.md",
        "references/social-topic-compliance.md",
    ):
        text = _read(relative_path)
        assert "PASS | CONDITIONAL | FAIL" in text

    candidate_card = _read("templates/candidate-card.md")
    assert "compliant_angle" in candidate_card
    assert "Archive | Reject | Wait" in candidate_card

    checklist = _read("templates/social-topic-five-gates.md")
    assert "A/B/C" in checklist
    assert "Archive/Reject/Wait" in checklist
    assert "不连坐" in checklist

    writing_brief = _read("templates/writing-brief.md")
    assert "compliant_angle" in writing_brief
    assert "CONDITIONAL" in writing_brief


def test_five_gate_conclusion_menus_each_offer_all_three_grades():
    checklist = _read("templates/social-topic-five-gates.md")

    for gate in range(1, 6):
        section = checklist.split(f"## 门 {gate} ", maxsplit=1)[1].split("## ", maxsplit=1)[0]
        assert "结论：`PASS | CONDITIONAL | FAIL`" in section


def test_handbook_preserves_conditional_manual_review_and_fail_boundary():
    handbook = _read("references/social-topic-compliance.md")

    assert "CONDITIONAL" in handbook
    assert "人工编辑判断" in handbook
    assert "FAIL" in handbook
    assert "A/B/C" in handbook
