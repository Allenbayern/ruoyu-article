"""run_sandbox：演练沙盘（复制 run，副本可自由写入，源 run 保持封存）。

事故背景：在已收尾的 daily-008 上直接演练，覆盖了预检产物。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from article_group.evidence_write import write_evidence
from article_group.run_state import is_sealed, seal
from scripts.run_sandbox import SEALED_AS_COPIED, SANDBOX_MARKER, is_sandbox, main, make_sandbox


def _run(tmp_path: Path) -> Path:
    root = tmp_path / "runs" / "2026-09-16" / "daily-900"
    (root / "delivery" / "art-001").mkdir(parents=True)
    (root / "delivery" / "art-001" / "delivery.md").write_text("# 标题\n\n正文。\n", encoding="utf-8")
    (root / "batch.json").write_text(json.dumps({"articles": []}), encoding="utf-8")
    return root


def test_sandbox_is_writable_even_when_source_is_sealed(tmp_path: Path):
    root = _run(tmp_path)
    seal(root, identity="owner")
    dest = tmp_path / "sandbox"
    marker = make_sandbox(root, dest=dest)

    assert marker["dest"] == str(dest)
    assert marker["sealed_marker_renamed_to"] == SEALED_AS_COPIED
    assert is_sandbox(dest) is True
    assert is_sealed(dest) is False                    # 副本不再被封存挡路
    assert (dest / SEALED_AS_COPIED).is_file()         # 但保留了"来自封存 run"的痕迹
    # 副本内可自由写证据（真实 run 仍然拒绝）
    write_evidence(dest / "review" / "x.json", "演练写入", run_dir=dest, reason="sandbox_demo")
    assert (dest / "review" / "x.json").read_text(encoding="utf-8") == "演练写入"


def test_source_run_untouched(tmp_path: Path):
    root = _run(tmp_path)
    seal(root, identity="owner")
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    make_sandbox(root, dest=tmp_path / "sandbox")
    after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    assert before == after
    assert is_sealed(root) is True


def test_refuses_existing_dest_without_force(tmp_path: Path):
    root = _run(tmp_path)
    dest = tmp_path / "sandbox"
    dest.mkdir()
    with pytest.raises(FileExistsError):
        make_sandbox(root, dest=dest)
    marker = make_sandbox(root, dest=dest, force=True)
    assert marker["dest"] == str(dest)


def test_marker_records_provenance_and_hint(tmp_path: Path):
    root = _run(tmp_path)
    marker = make_sandbox(root, dest=tmp_path / "sandbox", label="演示预检")
    written = json.loads((Path(marker["dest"]) / SANDBOX_MARKER).read_text(encoding="utf-8"))
    assert written["schema_version"] == "run-sandbox-v1"
    assert written["source_run"] == str(root.resolve())
    assert written["label"] == "演示预检"
    assert written["publication_authorization"] == "not_authorized"
    assert "--run-root" in written["hint"]


def test_default_dest_is_under_tmp_with_timestamp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _run(tmp_path)
    monkeypatch.setattr("scripts.run_sandbox.sandbox_path", lambda source, dest=None: tmp_path / "auto")
    marker = make_sandbox(root)
    assert marker["dest"] == str(tmp_path / "auto")


def test_not_a_run_dir_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        make_sandbox(tmp_path / "empty")


def test_cli_prints_dest_and_hint(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    root = _run(tmp_path)
    dest = tmp_path / "sandbox"
    assert main([str(root), "--dest", str(dest), "--label", "演练"]) == 0
    out = capsys.readouterr().out
    assert "沙盘已就绪" in out and str(dest) in out
    assert "--run-root" in out
