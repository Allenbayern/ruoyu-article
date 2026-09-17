"""runs 指纹/护栏脚本：把"跑前跑后人工比对"变成两条命令。

- `scripts/runs_fingerprint.py print|save|compare`：可复现指纹（默认 size+mtime_ns，
  `--hash` 连内容一起），比对有变更退出码 2。
- `scripts/with_runs_guard.py -- <命令…>`：包住真实操作，跑前拍、跑后比，
  出现未放行的改动退出码 3。

这组用例同时钉住两件事：指纹确实能发现改动；以及**默认口径发现不了**的
"同尺寸 + mtime 被还原"的改写，`--hash` 能发现——这正是它比测试套件里那份
快速自检（`tests/_runs_guard.py`，只比 size/mtime）多出来的一层。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import runs_fingerprint, with_runs_guard
from tests import _runs_guard

REPO_ROOT = Path(__file__).resolve().parents[1]


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    (root / "2026-09-16" / "daily-960").mkdir(parents=True)
    (root / "2026-09-16" / "daily-960" / "batch.json").write_text('{"a": 1}', encoding="utf-8")
    (root / "2026-09-16" / "daily-960" / "review").mkdir()
    (root / "2026-09-16" / "daily-960" / "review" / "precheck.json").write_text("{}", encoding="utf-8")
    return root


def test_fingerprint_is_stable_and_reproducible(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    first = runs_fingerprint.build_payload(root)
    second = runs_fingerprint.build_payload(root)
    assert first["fingerprint"] == second["fingerprint"]
    assert first["file_count"] == 2
    # 与测试套件那份快速自检口径一致（同一棵树上快照相同）
    assert set(first["entries"]) == set(_runs_guard.snapshot(root))


def test_compare_reports_added_changed_removed(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    before = runs_fingerprint.build_payload(root)

    (root / "2026-09-16" / "daily-960" / "batch.json").write_text('{"a": 2}', encoding="utf-8")
    (root / "2026-09-16" / "daily-960" / "new.json").write_text("{}", encoding="utf-8")
    (root / "2026-09-16" / "daily-960" / "review" / "precheck.json").unlink()

    changes = runs_fingerprint.compare(before, runs_fingerprint.build_payload(root))
    assert changes["changed"] == ["2026-09-16/daily-960/batch.json"]
    assert changes["added"] == ["2026-09-16/daily-960/new.json"]
    assert changes["removed"] == ["2026-09-16/daily-960/review/precheck.json"]
    assert not runs_fingerprint.is_clean(changes)


def test_hash_mode_catches_rewrite_that_mtime_restore_hides(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    target = root / "2026-09-16" / "daily-960" / "batch.json"
    stat = target.stat()
    hashed_before = runs_fingerprint.build_payload(root, with_hash=True)
    plain_before = runs_fingerprint.build_payload(root)

    target.write_text('{"b": 9}', encoding="utf-8")  # 同样 8 字节
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # mtime 还原

    plain_changes = runs_fingerprint.compare(plain_before, runs_fingerprint.build_payload(root))
    assert runs_fingerprint.is_clean(plain_changes)  # 默认口径看不出来
    hashed_changes = runs_fingerprint.compare(hashed_before, runs_fingerprint.build_payload(root, with_hash=True))
    assert hashed_changes["rewritten"] == ["2026-09-16/daily-960/batch.json"]


def test_compare_cli_exit_codes(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    snapshot = tmp_path / "before.json"

    def _cli(command: str, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "scripts/runs_fingerprint.py", command, "--root", str(root), *extra],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
        )

    saved = _cli("save", "--out", str(snapshot))
    assert saved.returncode == runs_fingerprint.EXIT_CLEAN and snapshot.is_file()
    clean = _cli("compare", "--snapshot", str(snapshot))
    assert clean.returncode == runs_fingerprint.EXIT_CLEAN and "逐项一致" in clean.stdout

    (root / "2026-09-16" / "daily-960" / "batch.json").write_text('{"a": 3}', encoding="utf-8")
    dirty = _cli("compare", "--snapshot", str(snapshot))
    assert dirty.returncode == runs_fingerprint.EXIT_CHANGED and "changed(1)" in dirty.stdout


def test_with_runs_guard_detects_and_passes_through(tmp_path: Path) -> None:
    root = _tree(tmp_path)

    def _cli(*extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "scripts/with_runs_guard.py", "--root", str(root), "--", *extra],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
        )

    clean = _cli(sys.executable, "-c", "print('no writes')")
    assert clean.returncode == with_runs_guard.EXIT_CLEAN and "逐项一致" in clean.stdout

    dirty = _cli(sys.executable, "-c",
                 f"from pathlib import Path; Path(r'{root}/2026-09-16/daily-960/x.json').write_text('{{}}')")
    assert dirty.returncode == with_runs_guard.EXIT_UNEXPECTED_CHANGES
    assert "added(1)" in dirty.stdout and "不该发生" in dirty.stdout

    allowed = subprocess.run(
        [sys.executable, "scripts/with_runs_guard.py", "--root", str(root), "--allow-changes",
         "--", sys.executable, "-c",
         f"from pathlib import Path; Path(r'{root}/2026-09-16/daily-960/y.json').write_text('{{}}')"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    assert allowed.returncode == with_runs_guard.EXIT_CLEAN
    assert "已显式放行" in allowed.stdout


def test_failing_command_does_not_mask_the_change_report(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    result = subprocess.run(
        [sys.executable, "scripts/with_runs_guard.py", "--root", str(root), "--",
         sys.executable, "-c",
         f"from pathlib import Path; Path(r'{root}/2026-09-16/daily-960/z.json').write_text('{{}}'); raise SystemExit(7)"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == with_runs_guard.EXIT_UNEXPECTED_CHANGES  # 改动优先，不被命令退出码盖掉
    assert "added(1)" in result.stdout


def test_print_json_is_reloadable_and_matches_the_api(tmp_path: Path) -> None:
    """CLI 打印的 JSON 必须是能直接喂给 compare 的快照（别让两条路径各算一套）。"""
    root = _tree(tmp_path)
    result = subprocess.run(
        [sys.executable, "scripts/runs_fingerprint.py", "print", "--root", str(root), "--json"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == runs_fingerprint.EXIT_CLEAN
    payload = json.loads(result.stdout)
    assert payload["fingerprint"] == runs_fingerprint.build_payload(root)["fingerprint"]
    assert runs_fingerprint.is_clean(
        runs_fingerprint.compare(payload, runs_fingerprint.build_payload(root))
    )
