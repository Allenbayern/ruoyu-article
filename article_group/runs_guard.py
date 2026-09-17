"""runs_guard: 封存 run 的**进程级**写入护栏（PEP 578 audit hook）。

为什么需要（2026-09-17，008 事故的第二层）：
第一层守门（`evidence_write` + 五个入口的封存检查）是**白名单制**——能写 run 的模块
三十来个，接了守卫的只有五个。事故的同构风险不是"这五个写错了"，而是"新入口忘了接"。
本模块把"忘记"变成"写不进去"：

- 只要进程 import 过 `article_group`，护栏即自动装上（见 `article_group/__init__.py`）；
- 凡以写/删/改名/改权限模式触碰**含 `SEALED` 的目录**，一律抛 `SealedWriteBlocked`；
- 放行必须显式：`with sealed_write_token(run_dir, reason=…, author=…):`——它与 `--force`
  同一等级（controller 决定），因此只被 `evidence_write(force=True)` 与 `unseal()` 使用，
  账目照记。

设计判据（有意保守）：
- **保守方向是"宁可多拦"**：拦截后写入方要么改用 `evidence_write` 留底记账，要么显式申请令牌；
- **破坏性调用的空操作放行**：目标本就不存在时没有东西可毁（`unlink(missing_ok=True)`
  这类调用不该被拦），失败仍由系统调用自己报 ENOENT；
- **只读永不拦**：读走的是不含写标志的 `open`。

明确不覆盖（不要误以为已全保）：护栏只在 import 过本包的进程内生效。`vim` / `rsync` /
`git checkout` / 裸 `python -c`（未 import 本包）这类**进程外**写入不受约束——那属于
文件系统层只读与全量哈希清单的职责。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

SEALED_NAME = "SEALED"

# 契约上的 append-only 文件：只能追加、不能重写。追加不毁数据（封存动作自身的
# 时间线行就写在 SEALED 之后），所以**同目录、'a' 模式**的追加放行；改名/删除/
# 截断/重写仍然拦。
APPEND_ONLY_NAMES = frozenset({"step-log.jsonl", "evidence-changelog.jsonl"})

_WRITE_MODES = frozenset("wax+")
_FLAG_MASK = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

_INSTALLED = False
_LOCK = threading.RLock()
_LOCAL = threading.local()
_TOKENS: dict[str, int] = {}
_PROBE: dict[str, tuple[float, str | None]] = {}
_FOREVER = float("inf")
_NEGATIVE_TTL = 2.0
_PROBE_CAP = 50_000


class SealedWriteBlocked(RuntimeError):
    """目标路径落在封存 run 内，未显式申请令牌的写入被护栏拦下。"""


def _norm(path: object) -> str | None:
    """绝对化 + 归一化；不可解释为路径的输入（如文件描述符）返回 None。"""
    if isinstance(path, int):
        return None
    try:
        raw = os.fspath(path)  # type: ignore[arg-type]
    except TypeError:
        return None
    if isinstance(raw, bytes):
        raw = os.fsdecode(raw)
    return os.path.normpath(os.path.abspath(raw))


def _probe(directory: str) -> str | None:
    """向上找最近的含 SEALED 的目录（带 memo，避免每次 open 都走一遍父链）。

    缓存口径：**命中（找到封存）永久缓存**；**未命中只缓存 `_NEGATIVE_TTL` 秒**——
    否则"先写文件、SEALED 随后才出现"的顺序会让旧进程一直判未封存（这正是本护栏
    第一版踩到的坑）。`refresh()` 可立即清空。
    """
    cached = _PROBE.get(directory)
    if cached is not None:
        expires, value = cached
        if value is not None or expires > time.monotonic():
            return value
    if len(_PROBE) > _PROBE_CAP:  # 长命进程别把内存吃光（清空后重新探测，代价可忽略）
        _PROBE.clear()
    parent = os.path.dirname(directory)
    if os.path.lexists(os.path.join(directory, SEALED_NAME)):
        result: str | None = directory
    elif parent and parent != directory:
        result = _probe(parent)
    else:
        result = None
    _PROBE[directory] = (
        _FOREVER if result is not None else time.monotonic() + _NEGATIVE_TTL,
        result,
    )
    return result


def refresh() -> None:
    """清空探测缓存（封存/撤销封存/每次证据写入前调用，保证状态改判及时）。"""
    _PROBE.clear()


def cli_refusal(exc: BaseException) -> int:
    """CLI 的统一封存拒绝口径：一句人话 + 退出码 2（与五个写证据入口一致）。

    用法：`except SealedWriteBlocked as exc: return cli_refusal(exc)`
    ——不要让人从 traceback 里猜"为什么写不进去"。
    """
    print(str(exc), file=sys.stderr)
    return 2


def _remedies() -> str:
    return (
        "要改封存证据，请走留底通道："
        "article_group.evidence_write.write_evidence(..., force=True)（controller 决定，"
        "等价于 --force 或 python -m article_group.close_out --force）；"
        "或先 unseal（SEALED 改名留痕）再改、改完重新收尾；"
        "只想演练/复现，请先 python scripts/run_sandbox.py <run> 建副本。"
    )


def _sealed_note(root: str) -> str:
    try:
        record = json.loads((Path(root) / SEALED_NAME).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 报错信息不值得再抛一次
        return ""
    if not isinstance(record, dict):
        return ""
    return f"（sealed_at={record.get('sealed_at', '?')},by={record.get('sealed_by', '?')}）"


def _block(path: str, root: str, action: str) -> None:
    raise SealedWriteBlocked(
        f"拒绝{action}封存 run 内的路径：{path}\n"
        f"  所属封存 run：{root}{_sealed_note(root)}\n"
        f"  {_remedies()}"
    )


def _token_allows(root: str) -> bool:
    if not _TOKENS:
        return False
    with _LOCK:
        for token_root in _TOKENS:
            if root == token_root or root.startswith(token_root + os.sep):
                return True
    return False


def _guard(path: object, action: str, *, noop_if_missing: bool = False) -> None:
    target = _norm(path)
    if target is None:
        return
    if noop_if_missing and not os.path.lexists(target):
        return  # 空操作：没有东西可毁，失败交给系统调用自己报
    root = _probe(os.path.dirname(target))
    if root is None or _token_allows(root):
        return
    _block(target, root, action)


def _guard_pair(src: object, dst: object, action: str) -> None:
    """改名/移动：两端都要查——搬进来是新增，搬出去是销毁证据。"""
    source, destination = _norm(src), _norm(dst)
    if source is None and destination is None:
        return
    if source is not None and destination is not None:
        if not os.path.lexists(source) and not os.path.lexists(destination):
            return  # 空操作
    for candidate in (source, destination):
        if candidate is None:
            continue
        root = _probe(os.path.dirname(candidate))
        if root is not None and not _token_allows(root):
            _block(candidate, root, action)


def _is_write_open(mode: object, flags: object) -> bool:
    if isinstance(mode, str):
        return any(char in mode for char in _WRITE_MODES)
    if isinstance(flags, int):
        return bool(flags & _FLAG_MASK)
    return False


def _own_append_only(target: str, mode: object) -> bool:
    """是封存 run 根下、契约 append-only 文件的**追加**吗？"""
    if not isinstance(mode, str) or "a" not in mode:
        return False
    if os.path.basename(target) not in APPEND_ONLY_NAMES:
        return False
    directory = os.path.dirname(target)
    return _probe(directory) == directory  # 该目录自己就带 SEALED


def _hook(event: str, args: tuple[object, ...]) -> None:
    if event != "open" and event not in _EVENTS:
        return
    if getattr(_LOCAL, "busy", False):
        return  # 护栏自身的文件访问不再递归（读 SEALED 记录等）
    _LOCAL.busy = True
    try:
        if event == "open":
            path = args[0] if args else None
            mode = args[1] if len(args) > 1 else None
            flags = args[2] if len(args) > 2 else None
            if _is_write_open(mode, flags):
                target = _norm(path)
                if target is not None and _own_append_only(target, mode):
                    return
                _guard(path, "写入")
            return
        _EVENTS[event](args)
    finally:
        _LOCAL.busy = False


def _handle_mkdir(args: tuple[object, ...]) -> None:
    target = _norm(args[0])
    if target is not None and os.path.isdir(target):
        return  # mkdir(exist_ok=True) 的空操作
    _guard(args[0], "新建目录")


def _handle_single(action: str) -> Callable[[tuple[object, ...]], None]:
    def handler(args: tuple[object, ...]) -> None:
        _guard(args[0], action, noop_if_missing=True)  # 删/截断/改属性：不存在即空操作

    return handler


def _handle_copy(args: tuple[object, ...]) -> None:
    _guard(args[1], "复制写入")  # 只写目标端；从封存 run 里往外拷是读


def _handle_pair(action: str) -> Callable[[tuple[object, ...]], None]:
    def handler(args: tuple[object, ...]) -> None:
        _guard_pair(args[0], args[1], action)

    return handler


# 事件名 → 处理函数。open 单独在 _hook 里判写模式。
_EVENTS: dict[str, Callable[[tuple[object, ...]], None]] = {
    "os.mkdir": _handle_mkdir,
    "os.rmdir": _handle_single("删除目录"),
    "os.remove": _handle_single("删除"),
    "os.truncate": _handle_single("截断"),
    "os.chmod": _handle_single("改权限"),
    "os.chown": _handle_single("改属主"),
    "os.utime": _handle_single("改时间戳"),
    "os.rename": _handle_pair("改名/覆盖"),
    "os.link": _handle_pair("建硬链接"),
    "os.symlink": _handle_pair("建符号链接"),
    "shutil.copyfile": _handle_copy,
    "shutil.copymode": _handle_copy,
    "shutil.copystat": _handle_copy,
    "shutil.move": _handle_pair("移动"),
}


def install() -> bool:
    """装上护栏（幂等）。返回 True 表示本次真的装了。"""
    global _INSTALLED
    if _INSTALLED:
        return False
    sys.addaudithook(_hook)
    _INSTALLED = True
    return True


def is_installed() -> bool:
    return _INSTALLED


@contextmanager
def sealed_write_token(
    run_dir: str | Path,
    *,
    reason: str = "",
    author: str = "agent",
) -> Iterator[str]:
    """显式放行某个封存 run 的写入（与 --force 同级；只给留底通道与 unseal 用）。"""
    key = _norm(run_dir)
    if key is None:  # pragma: no cover - 传进来的不是路径
        raise ValueError(f"无效的 run 目录：{run_dir!r}")
    with _LOCK:
        _TOKENS[key] = _TOKENS.get(key, 0) + 1
    try:
        yield key
    finally:
        with _LOCK:
            remaining = _TOKENS.get(key, 0) - 1
            if remaining > 0:
                _TOKENS[key] = remaining
            else:
                _TOKENS.pop(key, None)


__all__ = [
    "SEALED_NAME",
    "SealedWriteBlocked",
    "cli_refusal",
    "install",
    "is_installed",
    "refresh",
    "sealed_write_token",
]
