"""evidence_write + SEALED：写证据前留底、记账、封存守门、可还原。

事故背景（2026-09-17）：在已收尾的 daily-008 上重跑预检，覆盖了
review/art-001/ledger-coverage-precheck.json 且无备份、不可还原。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from article_group.evidence_write import (
    BEFORE_DIR,
    RunSealedError,
    changelog_path,
    latest_snapshot,
    read_changelog,
    restore,
    write_evidence,
    write_evidence_json,
)
from article_group.run_state import (
    closed_reason,
    is_sealed,
    seal,
    seal_articles,
    sealed_reason,
)
from scripts import ledger_coverage_precheck as pre


def _run(tmp_path: Path) -> Path:
    root = tmp_path / "daily-900"
    (root / "review" / "art-001").mkdir(parents=True)
    return root


def test_first_write_has_no_snapshot_but_is_logged(tmp_path: Path):
    root = _run(tmp_path)
    target = root / "review" / "art-001" / "x.json"
    entry = write_evidence_json(target, {"a": 1}, run_dir=root, reason="unit")
    assert entry["existed"] is False
    assert entry["snapshot_path"] == ""
    assert entry["after_sha256"]
    assert target.is_file()
    log = read_changelog(root)
    assert len(log) == 1 and log[0]["reason"] == "unit"
    assert log[0]["publication_authorization"] == "not_authorized"


def test_overwrite_keeps_before_image(tmp_path: Path):
    root = _run(tmp_path)
    target = root / "review" / "art-001" / "x.json"
    write_evidence(target, "旧内容", run_dir=root, reason="v1")
    entry = write_evidence(target, "新内容", run_dir=root, reason="v2")
    assert entry["existed"] is True
    snapshot = root / entry["snapshot_path"]
    assert snapshot.read_text(encoding="utf-8") == "旧内容"
    assert target.read_text(encoding="utf-8") == "新内容"
    assert entry["before_sha256"] != entry["after_sha256"]


def test_restore_brings_back_previous_bytes(tmp_path: Path):
    root = _run(tmp_path)
    target = root / "review" / "art-001" / "x.json"
    write_evidence(target, "初版", run_dir=root, reason="v1")
    write_evidence(target, "被覆盖的版本", run_dir=root, reason="v2")
    entry = restore(root, "review/art-001/x.json")
    assert target.read_text(encoding="utf-8") == "初版"
    assert entry["reason"].startswith("restore_from_snapshot")
    assert len(read_changelog(root)) == 3  # v1 + v2 + restore


def test_latest_snapshot_picks_newest(tmp_path: Path):
    root = _run(tmp_path)
    target = root / "review" / "art-001" / "x.json"
    write_evidence(target, "第一版", run_dir=root, reason="v1")
    write_evidence(target, "第二版", run_dir=root, reason="v2")
    snapshot = latest_snapshot(root, "review/art-001/x.json")
    assert snapshot is not None and snapshot.read_text(encoding="utf-8") == "第一版"
    assert (root / BEFORE_DIR).is_dir()


def test_restore_without_snapshot_raises(tmp_path: Path):
    root = _run(tmp_path)
    with pytest.raises(FileNotFoundError):
        restore(root, "review/art-001/missing.json")


def test_sealed_run_refuses_write_without_force(tmp_path: Path):
    root = _run(tmp_path)
    seal(root, identity="owner", articles=seal_articles(root))
    target = root / "review" / "art-001" / "x.json"
    with pytest.raises(RunSealedError):
        write_evidence(target, "不该写进去", run_dir=root, reason="demo")
    assert not target.exists()
    assert read_changelog(root) == []


def test_sealed_run_allows_write_with_force_and_marks_forced(tmp_path: Path):
    root = _run(tmp_path)
    seal(root, identity="owner")
    target = root / "review" / "art-001" / "x.json"
    entry = write_evidence(target, "强制写入", run_dir=root, reason="demo", force=True)
    assert entry["forced"] is True
    assert target.read_text(encoding="utf-8") == "强制写入"


def test_seal_is_idempotent_and_preferred_by_closed_reason(tmp_path: Path):
    root = _run(tmp_path)
    assert is_sealed(root) is False
    first = seal(root, identity="owner", ref="会话确认")
    second = seal(root, identity="owner")
    assert first["status"] == "sealed" and second["status"] == "already_sealed"
    assert sealed_reason(root).startswith("sealed_at=")
    assert closed_reason(root) == sealed_reason(root)


def test_seal_articles_collects_delivery_hashes(tmp_path: Path):
    root = _run(tmp_path)
    (root / "delivery" / "art-001").mkdir(parents=True)
    (root / "delivery" / "art-001" / "delivery.md").write_text("正文", encoding="utf-8")
    articles = seal_articles(root)
    assert articles[0]["article_id"] == "art-001"
    assert len(articles[0]["delivery_sha256"]) == 64


def test_precheck_on_sealed_run_keeps_file_untouched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _run(tmp_path)
    (root / "delivery" / "art-001").mkdir(parents=True)
    (root / "material-packs").mkdir(parents=True)
    (root / "delivery" / "art-001" / "delivery.md").write_text("# 标题\n\n正文。\n", encoding="utf-8")
    (root / "material-packs" / "art-001.json").write_text(
        json.dumps({"obtained_facts_by_source": {"src-a": ["一条事实"]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    record = root / "review" / "art-001" / "ledger-coverage-precheck.json"
    record.write_text('{"frozen": true}', encoding="utf-8")
    seal(root, identity="owner")

    def no_llm(*_args, **_kwargs):
        raise pre.LlmUnavailable("offline")

    monkeypatch.setattr(pre, "llm_chat", no_llm)
    monkeypatch.setattr(sys, "argv", ["x", "--run-root", str(root), "--aid", "art-001"])
    assert pre.main() == 2
    assert record.read_text(encoding="utf-8") == '{"frozen": true}'


def test_precheck_force_on_sealed_run_leaves_before_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _run(tmp_path)
    (root / "delivery" / "art-001").mkdir(parents=True)
    (root / "material-packs").mkdir(parents=True)
    (root / "delivery" / "art-001" / "delivery.md").write_text("# 标题\n\n正文。\n", encoding="utf-8")
    (root / "material-packs" / "art-001.json").write_text(
        json.dumps({"obtained_facts_by_source": {"src-a": ["一条事实"]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    record = root / "review" / "art-001" / "ledger-coverage-precheck.json"
    record.write_text('{"frozen": true}', encoding="utf-8")
    seal(root, identity="owner")

    def no_llm(*_args, **_kwargs):
        raise pre.LlmUnavailable("offline")

    monkeypatch.setattr(pre, "llm_chat", no_llm)
    monkeypatch.setattr(sys, "argv", ["x", "--run-root", str(root), "--aid", "art-001", "--force"])
    assert pre.main() == 0
    # 覆盖发生了，但旧内容留在快照里 → 可还原
    assert json.loads(record.read_text(encoding="utf-8"))["schema_version"] == "ledger-coverage-precheck-v1"
    snapshot = latest_snapshot(root, "review/art-001/ledger-coverage-precheck.json")
    assert snapshot is not None and snapshot.read_text(encoding="utf-8") == '{"frozen": true}'
    assert changelog_path(root).is_file()
    assert any(entry["forced"] for entry in read_changelog(root))


# ---- 撤销封存（unseal）：留痕、恢复可写 ----

from article_group.run_state import unseal  # noqa: E402


def test_unseal_revokes_with_audit_trail(tmp_path: Path):
    root = _run(tmp_path)
    seal(root, identity="owner", ref="首次收尾")
    assert is_sealed(root) is True

    result = unseal(root, reason="controller 要求补一段结尾", identity="owner")
    assert result["status"] == "unsealed"
    assert is_sealed(root) is False
    revoked = root / result["revoked_path"]
    assert revoked.is_file() and "SEALED.revoked." in result["revoked_path"]
    assert json.loads(revoked.read_text(encoding="utf-8"))["sealed_by"] == "owner"

    log = read_changelog(root)
    assert log[-1]["reason"] == "unseal:controller 要求补一段结尾"
    assert log[-1]["author"] == "owner"
    assert log[-1]["publication_authorization"] == "not_authorized"


def test_writes_allowed_again_after_unseal_then_reseal(tmp_path: Path):
    root = _run(tmp_path)
    seal(root, identity="owner")
    unseal(root, reason="改稿", identity="owner")
    target = root / "review" / "art-001" / "x.json"
    write_evidence(target, "改后的内容", run_dir=root, reason="post_unseal_edit")
    assert target.read_text(encoding="utf-8") == "改后的内容"

    again = seal(root, identity="owner")
    assert again["status"] == "sealed"
    with pytest.raises(RunSealedError):
        write_evidence(target, "又不该写了", run_dir=root, reason="demo")


def test_unseal_on_open_run_is_noop(tmp_path: Path):
    root = _run(tmp_path)
    assert unseal(root, reason="x", identity="owner")["status"] == "not_sealed"


# ---- 路径解析回归（2026-09-17：二次拼接把产物写进 <run>/runs/<date>/<run>/）----

from article_group.evidence_write import _resolve_target  # noqa: E402


def test_run_relative_path_is_not_joined_twice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    root = Path("runs/2026-09-16/daily-008")
    root.mkdir(parents=True)
    # 调用方自己拼过的路径：不得再拼一次
    assert _resolve_target(root, root / "SEALED") == root / "SEALED"
    # 裸相对路径：按 run 内解析
    assert _resolve_target(root, "review/art-001/x.json") == root / "review/art-001/x.json"
    # 绝对路径：原样
    absolute = tmp_path / "elsewhere" / "y.json"
    assert _resolve_target(root, absolute) == absolute


def test_write_evidence_with_prejoined_relative_path_stays_inside_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    root = Path("runs/2026-09-16/daily-008")
    (root / "review").mkdir(parents=True)
    entry = write_evidence(root / "SEALED", "{}", run_dir=root, reason="regression")
    assert (root / "SEALED").is_file()
    assert not (root / "runs").exists()          # 不再产生嵌套目录
    assert entry["path"] == "SEALED"
