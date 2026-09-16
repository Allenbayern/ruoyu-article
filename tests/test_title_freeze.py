"""title_freeze：标题包冻结，改标题即让旧 L2 approve 失效。

daily-008 的教训：art-002 在 L2 approve 之后才换标题，多花一轮增量复核；
而引擎"completed 记录不回写" + 手工 rebind 脚本会把 title_pack_sha256 改成
当前文件哈希，旧 approve 因此被保住。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from article_group.title_freeze import (
    BLOCKING_STATUSES,
    check,
    freeze,
    freeze_path,
    main,
    selected_title,
    title_pack_path,
)


def _run(tmp_path: Path, *, title: str = "标题甲", with_pack: bool = True) -> Path:
    root = tmp_path / "daily-900"
    review = root / "review" / "art-001"
    review.mkdir(parents=True, exist_ok=True)
    if with_pack:
        (review / "title-pack.json").write_text(
            json.dumps({"directions": [{"title": title, "evidence_refs": ["x"]}]}, ensure_ascii=False),
            encoding="utf-8",
        )
    return root


def test_selected_title_reads_first_direction(tmp_path: Path):
    root = _run(tmp_path, title="《让子弹飞》之后，姜文为什么一部比一部拧巴")
    assert selected_title(root, "art-001").startswith("《让子弹飞》之后")


def test_freeze_records_hash_and_title(tmp_path: Path):
    root = _run(tmp_path)
    result = freeze(root, "art-001")
    assert result["status"] == "frozen"
    record = json.loads(freeze_path(root, "art-001").read_text(encoding="utf-8"))
    assert record["schema_version"] == "title-freeze-v1"
    assert len(record["title_pack_sha256"]) == 64
    assert record["selected_title"] == "标题甲"
    assert record["publication_authorization"] == "not_authorized"


def test_freeze_is_idempotent(tmp_path: Path):
    root = _run(tmp_path)
    freeze(root, "art-001")
    assert freeze(root, "art-001")["status"] == "already_frozen"


def test_freeze_without_title_pack_reports_status(tmp_path: Path):
    root = _run(tmp_path, with_pack=False)
    assert freeze(root, "art-001")["status"] == "no_title_pack"
    assert check(root, "art-001")["status"] == "no_title_pack"


def test_check_without_freeze_record(tmp_path: Path):
    root = _run(tmp_path)
    report = check(root, "art-001")
    assert report["status"] == "not_frozen"
    assert "先冻结" in report["reason"]


def test_check_detects_title_change_after_freeze(tmp_path: Path):
    root = _run(tmp_path, title="旧标题")
    freeze(root, "art-001")
    pack = json.loads(title_pack_path(root, "art-001").read_text(encoding="utf-8"))
    pack["directions"][0]["title"] = "新标题（L2 之后换的）"
    title_pack_path(root, "art-001").write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")

    report = check(root, "art-001")
    assert report["status"] == "title_changed_after_freeze"
    assert report["frozen_selected_title"] == "旧标题"
    assert report["current_selected_title"] == "新标题（L2 之后换的）"
    assert report["status"] in BLOCKING_STATUSES


def test_check_detects_l2_bound_to_other_freeze(tmp_path: Path):
    root = _run(tmp_path)
    freeze(root, "art-001")
    (root / "review" / "art-001" / "codex-l2-review.json").write_text(
        json.dumps({"decision": "approve", "title_pack_sha256": "f" * 64}, ensure_ascii=False),
        encoding="utf-8",
    )
    report = check(root, "art-001")
    assert report["status"] == "l2_reviewed_other_freeze"
    assert report["l2_title_pack_sha256"] == "f" * 64


def test_check_ok_when_l2_bound_to_same_freeze(tmp_path: Path):
    root = _run(tmp_path)
    frozen = freeze(root, "art-001")
    (root / "review" / "art-001" / "codex-l2-review.json").write_text(
        json.dumps({"decision": "approve", "title_pack_sha256": frozen["title_pack_sha256"]},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    report = check(root, "art-001")
    assert report["status"] == "frozen_ok"
    assert report["frozen_at"]


def test_cli_freeze_then_strict(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    root = _run(tmp_path)
    assert main(["--run-root", str(root), "--aid", "art-001", "--freeze", "--strict"]) == 0
    capsys.readouterr()
    assert main(["--run-root", str(root), "--aid", "art-001", "--strict"]) == 0
    assert "frozen_ok" in capsys.readouterr().out


def test_cli_strict_fails_without_freeze(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    root = _run(tmp_path)
    assert main(["--run-root", str(root), "--aid", "art-001", "--strict"]) == 1
    assert "not_frozen" in capsys.readouterr().out


# ---- L2 闸门接线：codex_review 在标题包未冻结时不得记 approve ----

from article_group import codex_review  # noqa: E402


def _l2_args(run_root: Path, output: Path, review_json: Path, *extra: str):
    return codex_review.build_parser().parse_args([
        "--mode", "l2", "--run-root", str(run_root), "--output", str(output),
        "--request", "复核这篇稿", "--review-json", str(review_json),
        "--article-id", "art-001", *extra,
    ])


def _review_json(tmp_path: Path, decision: str = "approve") -> Path:
    path = tmp_path / "l2.json"
    path.write_text(json.dumps({
        "decision": decision, "findings": [], "scope_reviewed": ["delivery"],
        "non_findings": [], "coverage_gaps": [],
    }, ensure_ascii=False), encoding="utf-8")
    return path


def test_l2_cannot_approve_when_title_pack_not_frozen(tmp_path: Path):
    root = _run(tmp_path)
    output = root / "review" / "l2-record.json"
    codex_review.run_review(_l2_args(root, output, _review_json(tmp_path)))
    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["decision"] == "needs_changes"
    assert record["status"] == "FAIL"
    assert record["title_freeze_status"] == "not_frozen"
    assert "title_freeze:not_frozen" in record["coverage_gaps"]


def test_l2_approve_survives_when_title_pack_frozen(tmp_path: Path):
    root = _run(tmp_path)
    frozen = freeze(root, "art-001")
    output = root / "review" / "l2-record.json"
    codex_review.run_review(_l2_args(root, output, _review_json(tmp_path)))
    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["decision"] == "approve"
    assert record["title_freeze_status"] == "frozen_ok"
    assert record["title_pack_sha256"] == frozen["title_pack_sha256"]


def test_l2_blocks_when_title_changed_after_freeze(tmp_path: Path):
    root = _run(tmp_path, title="旧标题")
    freeze(root, "art-001")
    pack = json.loads(title_pack_path(root, "art-001").read_text(encoding="utf-8"))
    pack["directions"][0]["title"] = "后换的标题"
    title_pack_path(root, "art-001").write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")

    output = root / "review" / "l2-record.json"
    codex_review.run_review(_l2_args(root, output, _review_json(tmp_path)))
    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["title_freeze_status"] == "title_changed_after_freeze"
    assert record["decision"] == "needs_changes"
    assert record["title_freeze_violation"]["frozen_selected_title"] == "旧标题"


def test_l2_explicit_allow_unfrozen_title_flag_is_recorded(tmp_path: Path):
    root = _run(tmp_path)
    output = root / "review" / "l2-record.json"
    codex_review.run_review(
        _l2_args(root, output, _review_json(tmp_path), "--allow-unfrozen-title")
    )
    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["decision"] == "approve"          # 显式放行
    assert record["title_freeze_status"] == "not_frozen"  # 但事实照记
    assert "title_freeze_violation" not in record
