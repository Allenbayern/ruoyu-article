"""run_seal.is_run_root 的形状判据（2026-09-18 L2 复核后收紧）。

三条判据都对应一个实测出来的误判：
- `runs/<X>/<文件>`：文件被当成 run 根 → `anchor_artifact` 直接 FileExistsError（仓库里 58 个这种文件）；
- `runs/radar/dailyhot` 这类非日期目录：普通快照目录被当成 run 根；
- "runs 之前还有 runs"：外层目录被当 run 根、真正的 run 根反而不被承认（锚点写错地方）。
"""
from __future__ import annotations

from pathlib import Path

from article_group.evidence_write import anchor_artifact, read_changelog
from article_group.run_seal import find_run_root, is_run_root


def test_a_real_run_root_still_matches(tmp_path: Path) -> None:
    root = tmp_path / "runs" / "2026-09-17" / "daily-980"
    root.mkdir(parents=True)
    assert is_run_root(root) is True
    assert find_run_root(root / "delivery" / "x.md") == root


def test_a_file_directly_under_runs_is_not_a_run_root(tmp_path: Path) -> None:
    (tmp_path / "runs" / "2026-09-06").mkdir(parents=True)
    loose = tmp_path / "runs" / "2026-09-06" / "article-003.md"
    loose.write_text("正文\n", encoding="utf-8")

    assert is_run_root(loose) is False
    assert find_run_root(loose) is None
    # 曾经的行为：把文件当 run 根去建目录 → FileExistsError。现在静默返回 None。
    assert anchor_artifact(loose, reason="probe", digest="0" * 64) is None


def test_a_non_date_directory_under_runs_is_not_a_run_root(tmp_path: Path) -> None:
    snapshots = tmp_path / "runs" / "radar" / "dailyhot"
    snapshots.mkdir(parents=True)
    (snapshots / "2026-09-18.json").write_text("{}", encoding="utf-8")

    assert is_run_root(snapshots) is False
    assert find_run_root(snapshots / "2026-09-18.json") is None


def test_a_day_directory_is_not_a_run_root(tmp_path: Path) -> None:
    assert is_run_root(tmp_path / "runs" / "2026-09-17") is False


def test_a_run_root_before_another_runs_component_is_recognized(tmp_path: Path) -> None:
    """"runs 之前还有 runs"：真正的 run 根要被承认（旧判据认外层、丢内层）。"""

    run = tmp_path / "home" / "runs" / "proj" / "runs" / "2026-08-21" / "controlled-031-revision-001"
    (run / "delivery").mkdir(parents=True)
    nested = run / "delivery" / "x.md"
    nested.write_text("正文\n", encoding="utf-8")

    assert is_run_root(run) is True
    assert is_run_root(run.parent) is False  # 外层目录不是 run 根
    assert find_run_root(nested) == run
    # 锚点落在真正的 run 里，而不是外层目录
    anchor = anchor_artifact(nested, reason="probe", digest="0" * 64)
    assert anchor is not None
    entries = read_changelog(run)
    assert entries and entries[-1]["path"] == "delivery/x.md"
    assert not (run.parent / "evidence-changelog.jsonl").exists()


def test_a_missing_run_shaped_path_is_still_lexically_a_run_root(tmp_path: Path) -> None:
    """源 run 已删除时仍要能按形状判定（重定位/锚点不该因为文件不在而失效）。"""

    gone = tmp_path / "runs" / "2026-09-18" / "daily-999"
    assert is_run_root(gone) is True
