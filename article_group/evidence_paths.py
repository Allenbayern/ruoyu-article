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

import json
import re
from pathlib import Path
from typing import Any

__all__ = [
    "L2_REVIEW_RECORD_NAME",
    "LEGACY_L2_REVIEW_RECORD_NAMES",
    "json_text",
    "rebase_moved_run_path",
    "resolve_l2_review_record",
    "run_relative_reference",
]


# L2 复核记录的**文件名约定**（2026-09-25 契约值迁移）。
# 历史产物（200 个文件 / 10 个 run）叫 `codex-l2-review.json` 及 `codex-l2-review-r*.json`。
# 文件已经有 200 份，**不重写**——"改文件名 = 那些 run 的复核证据在脚本里找不到"。
# 所以规矩是：**新名写、旧名读**（读端回退），见 resolve_l2_review_record()。
L2_REVIEW_RECORD_NAME = "dsh-l2-review.json"
LEGACY_L2_REVIEW_RECORD_NAMES = ("codex-l2-review.json",)


def resolve_l2_review_record(run_root: str | Path, article_id: str) -> Path:
    """找一条 L2 复核记录：**新名优先，回退历史名**。

    返回**存在**的那一个；两个都不在时返回新名路径（调用方照旧用 `.is_file()` 判断，
    语义不变）。回退是必需的：历史 run 里躺的就是旧名，而它们不重写。
    """
    base = Path(run_root) / "review" / str(article_id)
    for name in (L2_REVIEW_RECORD_NAME, *LEGACY_L2_REVIEW_RECORD_NAMES):
        candidate = base / name
        if candidate.is_file():
            return candidate
    return base / L2_REVIEW_RECORD_NAME


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


def json_text(payload: Any, *, indent: int | None = None) -> str:
    """序列化成**能落盘**的 JSON 文本（路径含非 UTF-8 字节时也不崩）。

    为什么放在这个叶子模块：`run_seal`（清单与锚点）、`run_state`（SEALED 标记）、
    `step_log`（步骤流水）、`evidence_write`（变更日志）四个写手都要落 JSON 文本，
    而它们之间有依赖方向（`evidence_write` 依赖 `run_state`），共用实现只能放在
    谁都不依赖的叶子里——否则要么循环导入，要么同一段取舍被抄三遍。

    取舍：路径带 surrogateescape 还原出的孤立代理字符（`\\udcff`）时，
    `ensure_ascii=False` 的文本**无法用严格 utf-8 编码落盘**，而这类写入往往发生在
    "目标文件已经写下去之后"或"封存收尾中途"，于是变成证据丢失（2026-09-25 复核实测：
    文件已写、`evidence-changelog.jsonl` 为 0 字节）。此时退回 `ensure_ascii=True`：
    代理字符写成 `\\udcff` 转义，既能落盘、又能被 `json.loads` **原样读回**，
    内容摘要因此保持稳定。正常内容仍走 `ensure_ascii=False`（中文可读）。

    返回的文本**不含**结尾换行——调用方自己决定要不要补。
    """
    text = json.dumps(payload, ensure_ascii=False, indent=indent)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        text = json.dumps(payload, ensure_ascii=True, indent=indent)
    return text
