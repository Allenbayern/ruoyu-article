"""evidence_paths：证据路径的"run 内相对 / 跨副本可重定位"判据（2026-09-18）。

这些用例来自 L2 只读对抗复核对 74770e3 的证伪：
- ``runs/<X>/<文件>`` 形状曾被记成 ``"."``（``is_run_root`` 把文件当 run 根）；
- "runs 之前还有 runs"的布局曾写出错误相对路径，同一个 run 原地就 BLOCKED。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from article_group.evidence_paths import rebase_moved_run_path, run_relative_reference


def _run(tmp_path: Path, *parts: str) -> Path:
    run = tmp_path.joinpath(*parts)
    (run / "delivery").mkdir(parents=True, exist_ok=True)
    (run / "delivery" / "delivery.md").write_text("# 标题\n\n正文\n", encoding="utf-8")
    return run


def test_artifact_inside_a_canonical_run_is_recorded_relative(tmp_path: Path) -> None:
    run = _run(tmp_path, "runs", "2026-09-18", "daily-900")
    assert run_relative_reference(run / "delivery" / "delivery.md") == "delivery/delivery.md"


def test_a_file_directly_under_runs_stays_absolute(tmp_path: Path) -> None:
    """runs/<X>/<文件> 里 is_run_root 会把文件本身当 run 根 → 不能记成 "."。"""

    (tmp_path / "runs" / "2026-09-06").mkdir(parents=True)
    loose = tmp_path / "runs" / "2026-09-06" / "article-003.md"
    loose.write_text("# 标题\n\n正文\n", encoding="utf-8")

    assert run_relative_reference(loose) == str(loose.resolve())


def test_runs_before_runs_layout_is_recognized_by_shape(tmp_path: Path) -> None:
    """'runs 之前还有 runs'：is_run_root 扫全部 runs 组件后，真 run 根被承认。

    旧判据只认第一个 runs 组件：外层目录被当 run 根 → 写出的相对路径原地就 BLOCKED。
    根因修好后自动识别给出**正确**相对路径（而不是退回绝对路径）。
    """

    from article_group.run_seal import find_run_root

    run = _run(tmp_path, "home", "runs", "proj", "runs", "2026-09-18", "daily-952")
    delivery = run / "delivery" / "delivery.md"

    assert find_run_root(delivery) == run
    assert run_relative_reference(delivery) == "delivery/delivery.md"
    # 显式 run_root（daily_engine 的口径）同样记相对
    assert run_relative_reference(delivery, run_root=run) == "delivery/delivery.md"


def test_relative_declared_path_is_not_rebased(tmp_path: Path) -> None:
    run = _run(tmp_path, "runs", "2026-09-18", "daily-900")
    assert rebase_moved_run_path(run, Path("delivery/delivery.md")) is None


def test_rebase_prefers_the_innermost_run_root(tmp_path: Path) -> None:
    """声明路径里"runs 之前还有 runs"时，用最内层那个规范 run 根取尾巴。"""

    original = _run(tmp_path, "home", "runs", "proj", "runs", "2026-09-18", "daily-952")
    declared = (original / "delivery" / "delivery.md").resolve()
    copy = _run(tmp_path / "backup", "home", "runs", "proj", "runs", "2026-09-18", "daily-952")

    rebased = rebase_moved_run_path(copy, declared)

    assert rebased == (copy / "delivery" / "delivery.md").resolve()


def test_rebase_requires_the_candidate_to_exist(tmp_path: Path) -> None:
    original = _run(tmp_path, "runs", "2026-09-18", "daily-900")
    declared = (original / "delivery" / "delivery.md").resolve()
    copy = _run(tmp_path / "backup", "runs", "2026-09-18", "daily-900")
    (copy / "delivery" / "delivery.md").unlink()

    assert rebase_moved_run_path(copy, declared) is None


def test_rebase_ignores_a_file_shaped_declared_path(tmp_path: Path) -> None:
    """runs/<X>/<文件> 不产生候选（run 内至少还要有一层）。"""

    (tmp_path / "runs" / "2026-09-06").mkdir(parents=True)
    loose = tmp_path / "runs" / "2026-09-06" / "article-003.md"
    loose.write_text("# 标题\n\n正文\n", encoding="utf-8")
    other = tmp_path / "backup"
    shutil.copytree(tmp_path / "runs" / "2026-09-06", other / "2026-09-06")

    assert rebase_moved_run_path(other, loose.resolve()) is None
