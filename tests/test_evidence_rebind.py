"""evidence_rebind：交付变更时让依赖它的 approve 失效（而不是重绑保住）。

daily-008 的反面教材：改稿后跑 sync_independent_review_008.py 把记录里的哈希
改成当前文件哈希，approve 被保住、哈希绑定形同虚设。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from article_group.evidence_rebind import (
    REPORT_NAME,
    dependent_records,
    main,
    reconcile,
    sha256_file,
)


def _run(tmp_path: Path, *, title_pack: bool = True) -> Path:
    root = tmp_path / "daily-900"
    (root / "delivery" / "art-001").mkdir(parents=True)
    (root / "drafts" / "art-001").mkdir(parents=True)
    (root / "review" / "art-001").mkdir(parents=True)
    (root / "review" / "attestation").mkdir(parents=True)
    (root / "delivery" / "art-001" / "delivery.md").write_text("正文 v1", encoding="utf-8")
    (root / "drafts" / "art-001" / "body_draft.md").write_text("草稿 v1", encoding="utf-8")
    if title_pack:
        (root / "review" / "art-001" / "title-pack.json").write_text(
            json.dumps({"directions": [{"title": "标题甲"}]}, ensure_ascii=False), encoding="utf-8"
        )
    return root


def _approve_independent(root: Path) -> Path:
    path = root / "review" / "art-001" / "independent-review.json"
    path.write_text(json.dumps({
        "schema_version": "article-independent-review-v1",
        "status": "complete",
        "decision": "approve",
        "artifact_sha256": sha256_file(root / "delivery" / "art-001" / "delivery.md"),
        "body_sha256": sha256_file(root / "drafts" / "art-001" / "body_draft.md"),
        "title_pack_sha256": sha256_file(root / "review" / "art-001" / "title-pack.json"),
    }, ensure_ascii=False), encoding="utf-8")
    return path


def test_no_change_means_no_findings(tmp_path: Path):
    root = _run(tmp_path)
    _approve_independent(root)
    report = reconcile(root)
    assert report["changes"] == []
    assert report["stale_records"] == []


def test_delivery_change_marks_approval_stale_without_rebinding(tmp_path: Path):
    root = _run(tmp_path)
    record_path = _approve_independent(root)
    before = json.loads(record_path.read_text(encoding="utf-8"))
    (root / "delivery" / "art-001" / "delivery.md").write_text("正文 v2（改稿）", encoding="utf-8")

    report = reconcile(root, apply=True)
    assert report["stale_records"] == ["review/art-001/independent-review.json"]

    after = json.loads(record_path.read_text(encoding="utf-8"))
    assert after["stale"] is True
    assert after["status"] == "PENDING"
    assert after["decision"] == "human_review_required"
    assert after["stale_reason"].startswith("delivery_or_title_changed:artifact_sha256")
    assert after["next_step"] == "rereview_after_content_change"
    # 关键：哈希没有被改成新值，旧值留在 superseded 里供审计
    assert after["artifact_sha256"] == before["artifact_sha256"]
    assert after["superseded"]["sha256"]["artifact_sha256"] == before["artifact_sha256"]
    assert after["publication_authorization"] == "not_authorized"


def test_dry_run_does_not_write(tmp_path: Path):
    root = _run(tmp_path)
    record_path = _approve_independent(root)
    (root / "delivery" / "art-001" / "delivery.md").write_text("正文 v2", encoding="utf-8")
    report = reconcile(root, apply=False)
    assert report["changes"] and report["stale_records"]
    assert not (root / "review" / REPORT_NAME).exists()
    assert "stale" not in json.loads(record_path.read_text(encoding="utf-8"))


def test_title_pack_change_invalidates_independent_and_l2(tmp_path: Path):
    root = _run(tmp_path)
    _approve_independent(root)
    l2 = root / "review" / "art-001" / "codex-l2-review.json"
    l2.write_text(json.dumps({
        "decision": "approve", "status": "PASS",
        "title_pack_sha256": sha256_file(root / "review" / "art-001" / "title-pack.json"),
    }, ensure_ascii=False), encoding="utf-8")
    # L2 之后换了标题（daily-008 art-002 的真实剧本）
    (root / "review" / "art-001" / "title-pack.json").write_text(
        json.dumps({"directions": [{"title": "标题乙（后换）"}]}, ensure_ascii=False), encoding="utf-8"
    )

    report = reconcile(root, apply=True)
    assert set(report["stale_records"]) == {
        "review/art-001/independent-review.json",
        "review/art-001/codex-l2-review.json",
    }
    assert json.loads(l2.read_text(encoding="utf-8"))["stale_reason"].endswith("title_pack_sha256")


def test_human_attestation_is_invalidated_too(tmp_path: Path):
    root = _run(tmp_path)
    attestation = root / "review" / "attestation" / "art-001.human.json"
    attestation.write_text(json.dumps({
        "schema_version": "human-attestation-v3",
        "decision": "accept",
        "markdown_sha256": sha256_file(root / "delivery" / "art-001" / "delivery.md"),
    }, ensure_ascii=False), encoding="utf-8")
    (root / "delivery" / "art-001" / "delivery.md").write_text("正文 v2", encoding="utf-8")

    report = reconcile(root, apply=True)
    assert "review/attestation/art-001.human.json" in report["stale_records"]
    after = json.loads(attestation.read_text(encoding="utf-8"))
    assert after["decision"] == "human_review_required"
    assert after["superseded"]["decision"] == "accept"


def test_non_approving_record_is_reported_but_not_rewritten(tmp_path: Path):
    root = _run(tmp_path)
    readability = root / "review" / "art-001" / "source-stripped-readability.json"
    readability.write_text(json.dumps({
        "source_stripped_readability": "PENDING",
        "reviewed_artifact_sha256": "0" * 64,
    }, ensure_ascii=False), encoding="utf-8")
    report = reconcile(root, apply=True)
    assert [entry["record"] for entry in report["changes"]] == [
        "review/art-001/source-stripped-readability.json"
    ]
    assert report["stale_records"] == []
    assert "stale" not in json.loads(readability.read_text(encoding="utf-8"))


def test_report_file_written_on_apply(tmp_path: Path):
    root = _run(tmp_path)
    _approve_independent(root)
    (root / "delivery" / "art-001" / "delivery.md").write_text("正文 v2", encoding="utf-8")
    reconcile(root, apply=True)
    report = json.loads((root / "review" / REPORT_NAME).read_text(encoding="utf-8"))
    assert report["applied"] is True
    assert report["publication_authorization"] == "not_authorized"


def test_dependent_records_cover_the_four_evidence_files(tmp_path: Path):
    names = {path.name for path in dependent_records(tmp_path, "art-001")}
    assert names == {"independent-review.json", "codex-l2-review.json",
                     "source-stripped-readability.json", "art-001.human.json"}


def test_cli_strict_and_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    root = _run(tmp_path)
    _approve_independent(root)
    (root / "delivery" / "art-001" / "delivery.md").write_text("正文 v2", encoding="utf-8")
    assert main(["--run-root", str(root), "--strict"]) == 1
    out = capsys.readouterr().out
    assert "dry-run" in out and "stale" in out
    assert main(["--run-root", str(root), "--apply"]) == 0
    assert "已应用" in capsys.readouterr().out
