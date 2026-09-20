"""证据里的路径引用：run 内记相对、跨副本可重定位（2026-09-18）。

为什么单独成模块：style-gate 记录、preview 证据、final_review 读回都要同一套口径——
run 内产物记 run 相对路径（可移植），run 外记绝对路径。写错路径的代价是整批 BLOCKED，
所以这里的判据是**往返可验证**，而不是"看着像 run 就记相对"：

- 相对路径只在 ``(root / rel).resolve() == 产物`` 时才写（写不回去就落回绝对路径）；
- 自动识别 run 根时额外要求它是规范形状（``…/runs/<YYYY-MM-DD>/<id>``）。
  ``run_seal.is_run_root`` 本身也已在 2026-09-18 收紧（扫全部 ``runs`` 组件 + 日期形状 +
  拒绝已存在的非目录）；这里保留同款检查作为**第二层防线**——写手不得仅凭"它说是 run 根"
  就记相对路径，必须自己证明这条相对路径能往返；
- 历史失效形状（L2 复核实测）：文件正好落在 ``runs/<X>/<文件>`` 时被当成 run 根（记出 ``"."``，
  仓库里 58 个这种文件）；"runs 之前还有 runs"时外层目录被当成 run 根（记出错误相对路径，
  原地就 BLOCKED）。两种形状现在都会落回绝对路径或（根因修好后）给出正确相对路径。

旧记录里的绝对路径在 run 被复制/搬移后由 :func:`rebase_moved_run_path` 重定位：按声明
路径里每个规范形状的 run 根（最内层优先）取尾巴，在当前 run 里找**存在**的候选文件。
重定位只负责找到候选；是否放行仍由调用方的 sha256 比对决定。
"""
from __future__ import annotations

from pathlib import Path
import re

__all__ = ["rebase_moved_run_path", "run_relative_reference"]


_RUN_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _canonical_run_root(path: Path) -> Path | None:
    """自动识别：只认规范形状 ``…/runs/<YYYY-MM-DD>/<id>`` 的目录，且必须是路径的真祖先。

    为什么还要自己再判一遍（2026-09-18 L2 复核实测）：``run_seal.is_run_root`` 当时只看
    路径里**第一个** ``runs`` 组件、且不校验日期与目录，于是

    - 文件正好落在 ``runs/<X>/<文件>`` 时它把**文件**当 run 根 → 记出 ``"."``；
    - 路径里"runs 之前还有 runs"时它把外层目录当 run 根 → 记出错误相对路径，
      同一个 run 原地 evaluate 就 BLOCKED（相对绝对路径是回归）。

    根因已在 ``run_seal.is_run_root`` 修掉；这里保留同款检查是刻意的第二层防线：
    自动识别宁可落回绝对路径，也不能记一个错的相对路径。显式 ``run_root=`` 不受形状限制
    （调用方知道自己的布局，例如 daily_engine），但仍要过往返校验。
    """

    from article_group.run_seal import find_run_root

    root = find_run_root(path)
    if root is None or root == path or not root.is_dir():
        return None
    if not _RUN_DATE_RE.fullmatch(root.parent.name) or root.parent.parent.name != "runs":
        return None
    return root


def _resolved_explicit_root(path: Path, run_root: str | Path) -> Path | None:
    """调用方显式声明的 run 根：只做"是目录且是真祖先"的检查（布局由调用方负责）。"""

    root = Path(run_root).expanduser().resolve()
    if root == path or not root.is_dir():
        return None
    return root


def run_relative_reference(path: str | Path, *, run_root: str | Path | None = None) -> str:
    """证据里记的产物路径：属于某个 run 时记 run 相对 posix 路径，否则记绝对路径。"""

    resolved = Path(path).expanduser().resolve()
    root = (
        _resolved_explicit_root(resolved, run_root)
        if run_root is not None
        else _canonical_run_root(resolved)
    )
    if root is not None:
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            relative = None
        if relative is not None and relative.parts:
            try:
                if (root / relative).resolve() == resolved:
                    return relative.as_posix()
            except (OSError, RuntimeError, ValueError):
                pass
    return str(resolved)


def _declared_run_roots(declared: Path) -> list[Path]:
    """声明路径里所有规范形状的 run 根（最内层优先；纯词法，不要求路径存在）。

    ``runs/<date>/<id>`` 之后至少还要有一层（说明声明的是 run **内**的产物）；
    因此 ``runs/<X>/<文件>`` 这种形状不会产生候选。
    """

    parts = declared.parts
    roots: list[Path] = []
    for index, part in enumerate(parts):
        if part != "runs":
            continue
        if len(parts) - (index + 1) >= 3:
            roots.append(Path(*parts[: index + 3]))
    return list(reversed(roots))


def rebase_moved_run_path(root: str | Path, declared: str | Path) -> Path | None:
    """把旧记录里的绝对路径按 ``runs/<date>/<id>/`` 尾巴重定位到当前 run 内。

    只在重定位结果**确实存在**时返回；授权（sha256 比对）由调用方紧接着做。
    """

    declared_path = Path(declared).expanduser()
    if not declared_path.is_absolute():
        return None
    root_path = Path(root).expanduser().resolve()
    for declared_run in _declared_run_roots(declared_path):
        try:
            tail = declared_path.relative_to(declared_run)
        except ValueError:
            continue
        if not tail.parts:
            continue
        try:
            candidate = (root_path / tail).resolve()
            candidate.relative_to(root_path)
        except (OSError, RuntimeError, ValueError):
            continue
        if candidate.is_file():
            return candidate
    return None
