"""隔离区清理工具不能顺手毁掉封存证据。

`scripts/purge_quarantine.py` 按设计整目录销毁（NAS 侧源视频隔离区）。它可以被指向
任意目录——包括一个封存 run。2026-09-17 决定：**含 SEALED 的目录一律拒删**，
除非 controller 明确点头并加 `--allow-sealed --ref "<谁批准的>"`；
run 内的账目会随文件一起被删，所以授权与封存标记的哈希写进幸存的 `PURGED.txt`。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import purge_quarantine


def _quarantine_run(tmp_path: Path, name: str = "run-001", *, sealed: bool = False) -> Path:
    quarantine = tmp_path / "quarantine"
    run_dir = quarantine / name
    (run_dir / "sources").mkdir(parents=True)
    (run_dir / "sources" / "a.mp4").write_bytes(b"video")
    (run_dir / "movement-ledger.jsonl").write_text(
        json.dumps({"source": "/vol2/1000/Photos/MobileBackup/a.mp4"}) + "\n", encoding="utf-8"
    )
    if sealed:
        (run_dir / "SEALED").write_text(
            json.dumps({"sealed_by": "owner", "sealed_at": "2026-09-17T08:45:00+08:00"}),
            encoding="utf-8",
        )
    return run_dir


@pytest.fixture
def quarantine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "quarantine"
    monkeypatch.setattr(purge_quarantine, "QUARANTINE", root)
    # 压缩副本校验与本组用例无关（要 ffprobe + 真实产物）：直接放行
    monkeypatch.setattr(purge_quarantine, "check_compressed_copies", lambda ledger: (1, 0, []))
    return root


def test_sealed_run_is_refused_without_explicit_authorization(quarantine: Path):
    run_dir = _quarantine_run(quarantine.parent, "sealed-001", sealed=True)
    with pytest.raises(SystemExit) as excinfo:
        purge_quarantine.purge_run("sealed-001", dry_run=False)
    assert excinfo.value.code == 3
    assert (run_dir / "SEALED").is_file()  # 一个字节都没动
    assert (run_dir / "sources" / "a.mp4").is_file()
    assert not (run_dir / "PURGED.txt").exists()


def test_sealed_run_can_be_purged_only_with_authorization_recorded(quarantine: Path):
    run_dir = _quarantine_run(quarantine.parent, "sealed-002", sealed=True)
    marker_digest = hashlib.sha256((run_dir / "SEALED").read_bytes()).hexdigest()

    purge_quarantine.purge_run(
        "sealed-002", dry_run=False, allow_sealed=True, ref="controller 会话点头"
    )

    assert not (run_dir / "SEALED").exists()  # 授权后才销毁
    assert not (run_dir / "sources" / "a.mp4").exists()
    purged = (run_dir / "PURGED.txt").read_text(encoding="utf-8")
    assert "controller 会话点头" in purged
    assert marker_digest in purged  # 毁掉的是什么，留下来可查


def test_unsealed_run_purges_without_the_sealed_lines(quarantine: Path):
    run_dir = _quarantine_run(quarantine.parent, "plain-001")
    purge_quarantine.purge_run("plain-001", dry_run=False)
    purged = (run_dir / "PURGED.txt").read_text(encoding="utf-8")
    assert "sealed_markers_destroyed" not in purged
    assert not (run_dir / "sources" / "a.mp4").exists()


def test_dry_run_still_reports_but_deletes_nothing(quarantine: Path):
    run_dir = _quarantine_run(quarantine.parent, "plain-002")
    purge_quarantine.purge_run("plain-002", dry_run=True)
    assert (run_dir / "sources" / "a.mp4").is_file()
    assert not (run_dir / "PURGED.txt").exists()


def test_sealed_marker_helpers_cover_lifecycle_names(quarantine: Path):
    run_dir = _quarantine_run(quarantine.parent, "sealed-003", sealed=True)
    (run_dir / "SEALED.revoked.20260917T090000").write_text("{}", encoding="utf-8")
    names = [marker.name for marker in purge_quarantine.sealed_markers(run_dir)]
    assert names == ["SEALED", "SEALED.revoked.20260917T090000"]
