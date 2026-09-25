"""run_seal: 封存不只是"写个 SEALED"，而是**全量清单 + 可事后验证**。

为什么需要（008 复盘后的最后一块）：
`SEALED` 只记了封存时间、署名和两篇交付的哈希。于是"封存之后有没有被改过"这个问题
此前无法回答——尤其 `runs/` 不进 git，连副本都没有。运行时护栏（`runs_guard`）挡得住
进程内的误写，挡不住进程外（编辑器 / rsync / git checkout），更挡不住"已经写进去了、
没人知道"。本模块补上事后可验：

- **seal 时**：把 run 内每个文件的 size + sha256（符号链接记目标）写进
  `SEALED.manifest.json`，并把即将写下的 `SEALED` 字节哈希一并记入
  （`sealed_marker_sha256`），这样标记自身也被覆盖；
- **verify 时**：逐项重算并分类——改动 / 新增 / 缺失 / 符号链接变化 / append-only 被重写，
  再与 `evidence-changelog.jsonl` 对照，区分"有账的 force 改动"与"无账的可疑改动"；
- **契约 append-only 文件**（`step-log.jsonl` / `evidence-changelog.jsonl`）按**前缀**校验：
  追加不算改动，重写/截断算。

排除项是显式的（见 `EXCLUDED_REASONS`）：封存生命周期标记、append-only 文件（另按前缀校验）、
清单自身、以及 `review/.before/**`（force 写入的留底快照，只会在封存后新增）。

退出码（CLI）：0 完好 / 2 有漂移 / 3 无法验证（缺清单，例如封存时还没有本模块的 run）。

**已知限制（七轮复核 H1 实测，必须知道再依赖它）**：本清单**防的是误写，不防蓄意的进程外改写**。
`SEALED.manifest.json` 自己在 `EXCLUDED_REASONS` 里，所以它不在自己的 `files` 里；`SEALED` 也不记
清单的哈希；变更日志同样没有它的记录。于是**进程外**写手（护栏与留底通道都覆盖不到的那一类）
可以删掉某条记录、改写某个 sha256、或删掉 `dirs`/`others` 块，让 `verify` 给出 `intact`——
实测：删掉成稿后同时删掉它那条记录 → `intact`；改文件内容后同时改记录的 sha256 → `intact`。
要真正锚定，需要 run 之外的锚点。本模块现在会把清单正文摘要写到 run 之外
（`RUOYU_SEAL_ANCHOR_DIR`，默认 `/home/allen/seal-anchors`），并在设置了
`RUOYU_SEAL_ANCHOR_PUSH=ssh://mac-backup/Users/Allen/Backups/seal-ledger.git` 时复制到离机仓库。
离机复制失败不阻断封存：此时**本机锚点确实写成了**，所以清单如实记
`anchored` / `kind=local-snapshot` / `replication=failed`（只有**写不进去**才记
`anchor_unavailable`），`verify` 也会打「仅本机快照」的警告。
**只改本机锚点仍能掩盖**；`verify=intact` 不能挡住「本机锚点和清单一起被改」的写手。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from article_group.evidence_paths import json_text

SCHEMA_VERSION = "run-sealed-manifest-v2"
SCHEMA_VERSION_V1 = "run-sealed-manifest-v1"
#: 认识的清单版本：v1（只收文件/符号链接，旧口径）与 v2（条目类型感知）。
#: **必须按清单格式门控**：v2 的 present 集合含目录，若拿它去比 v1 清单，每个封存 run 都会
#: 冒出成堆假 added（六轮复核实测：delivery / preview / review …）。
KNOWN_SCHEMA_VERSIONS = (SCHEMA_VERSION_V1, SCHEMA_VERSION)
#: v2 才有的"全条目"清单标志（显式写在清单里，便于事后判读）。
INVENTORY_ALL_ENTRIES = "all-entries-v2"
MANIFEST_NAME = "SEALED.manifest.json"
SEALED_NAME = "SEALED"
APPEND_ONLY_NAMES = ("step-log.jsonl", "evidence-changelog.jsonl")
BEFORE_DIR = "review/.before"

EXCLUDED_REASONS: dict[str, str] = {
    SEALED_NAME: "封存标记自身：用 sealed_marker_sha256 单独校验",
    MANIFEST_NAME: "清单自身（写清单时它还不存在）",
    "SEALED.*": "封存生命周期留下的标记（撤销封存 / 沙盘改名）",
    "evidence-changelog.jsonl": "契约 append-only：按前缀校验（追加放行、重写算改动）",
    "step-log.jsonl": "契约 append-only：同上（封存这一步自己的流水就在其后追加）",
    BEFORE_DIR + "/**": "force 写入的留底快照：只会在封存后新增",
}

#: 授权"封存后可以不在"的路径：**存在时必须与清单一致**（大小/哈希/符号链接照查），
#: 缺失不算漂移。用于 preview_site 的并发锁——瞬时件，封存后被正常构建删掉不该报篡改；
#: 但**不能**整条排除掉：那会形成一条对 added/modified 完全不可见的写入通道
#: （五轮复核 major 1：封存后往该路径写内容，verify 仍报 intact）。
MAY_BE_ABSENT: dict[str, str] = {
    ".preview-links.lock": "preview_site 并发构建锁：瞬时件；存在时内容受清单约束，缺失属授权",
}

#: 锚点存储（**必须在 run 之外**：run 内的东西正是被校验对象）。
#: 生产默认落本机此目录，再由运维复制/推送到 mac-backup（`…/Backups/seal-ledger.git`）。
DEFAULT_ANCHOR_DIR = "/home/allen/seal-anchors"
ANCHOR_DIR_ENV = "RUOYU_SEAL_ANCHOR_DIR"
ANCHOR_PUSH_ENV = "RUOYU_SEAL_ANCHOR_PUSH"
DEFAULT_ANCHOR_REMOTE = "ssh://mac-backup/Users/Allen/Backups/seal-ledger.git"
ANCHOR_FILE_SUFFIX = ".anchor.json"

EXIT_INTACT = 0
EXIT_DRIFTED = 2
EXIT_UNVERIFIABLE = 3
EXIT_NOT_APPLICABLE = 4
# 逐字节没变，但**没有外部锚点**——「清单有没有被改写」在这个 run 上查不出来，
# 所以它既不是 intact（那是"证明过没被改"），也不是 drifted（没证据说被改过）。
# 名字刻意不以 intact 开头（2026-09-25 复核 F2）：叫 intact_unanchored 时，操作者会
# 读成"文件没变、没事"，而这恰恰是一句没被证明的话。
STATUS_UNANCHORED = "unanchored"
SANDBOX_MARKER = "SANDBOX.json"


def manifest_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / MANIFEST_NAME


_RUN_DIR_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_run_root(path: str | Path) -> bool:
    """`runs/<date>/<run-id>` 形态才算 run 根（历史脚本也常写 runs/ 下的日目录）。

    判据 2026-09-18 收紧，三条都是 L2 只读复核实测出来的形状误判：

    - **扫描路径里所有 `runs` 组件**，而不是只看第一个：`…/runs/proj/runs/<date>/<id>`
      这种"runs 之前还有 runs"的布局里，旧判据把外层目录当 run 根、真正的 run 根反而不被
      承认（锚点写错地方、写手记错相对路径）；
    - **`<date>` 必须是 `YYYY-MM-DD`**：否则 `runs/radar/dailyhot`、`runs/<day>/quarantine`
      这类普通目录也会被当成 run 根；
    - **候选本身是已存在的非目录时不算 run 根**：`runs/<X>/<文件>`（仓库里 58 个）曾让
      `evidence_write.anchor_artifact` 把文件当 run 根去建目录，直接 `FileExistsError`。

    不存在的路径仍按形状判定（纯词法），"源 run 已删除"的重定位/锚点判定不会失效。
    """
    resolved = Path(path).expanduser().resolve()
    parts = resolved.parts
    for index, part in enumerate(parts):
        if part != "runs" or len(parts) - (index + 1) != 2:
            continue
        if not _RUN_DIR_DATE.fullmatch(parts[index + 1]):
            continue
        if resolved.is_file():
            continue
        return True
    return False


def find_run_root(path: str | Path) -> Path | None:
    """从一个产物路径向上找它所属的 run 根；不属于任何 run 时返回 None。

    用于"产物自带账 + run 级只记一条锚点"的写法：新管线的 package/cards/distill
    是 new-only、自带逐文件 SHA-256，不需要 before-image，但 run 的账本里要有一条
    锚点，否则封存校验会把它们全算成"无账改动"。
    """
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = candidate.resolve()
    for parent in (candidate, *candidate.parents):
        if is_run_root(parent):
            return parent
    return None


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stat_kind(path: Path) -> str:
    """fifo / socket / device / 其它——只用于清单里的人读字段。"""
    import stat as _stat

    mode = path.lstat().st_mode
    if _stat.S_ISFIFO(mode):
        return "fifo"
    if _stat.S_ISSOCK(mode):
        return "socket"
    if _stat.S_ISBLK(mode):
        return "block_device"
    if _stat.S_ISCHR(mode):
        return "char_device"
    return "unknown"


def _is_excluded(relative: str) -> bool:
    if relative in EXCLUDED_REASONS:
        return True
    if relative.startswith("SEALED."):
        return True
    if relative == BEFORE_DIR or relative.startswith(BEFORE_DIR + "/"):
        # 留底快照**目录本身**也要排除：v2 会枚举目录，否则它封存后才被创建、
        # 会被当成 added（旧口径只收文件，所以以前只需排除其内容）
        return True
    return False


def _scan_entries(root: Path) -> tuple[list[tuple[str, Path, str]], list[dict[str, str]]]:
    """按**条目类型**枚举 run 内全部条目，并**收集**扫描错误。

    为什么不能用 `Path.rglob`：本机 Python（3.14.4）下它会**吞掉 OSError**，扫不动的子树
    被无声丢弃，于是封存/校验会在从未读过的树上给出 `intact`（六轮复核 major）。这里显式
    递归 `os.scandir`，把错误交给调用方——宁可报"无法验证"，不给假 PASS。
    """
    entries: list[tuple[str, Path, str]] = []
    errors: list[dict[str, str]] = []
    stack: list[tuple[str, Path]] = [("", root)]
    while stack:
        relative_dir, directory = stack.pop()
        try:
            with os.scandir(directory) as listing:
                children = sorted(listing, key=lambda item: item.name)
        except OSError as exc:
            errors.append({"path": relative_dir or ".", "error": f"{type(exc).__name__}: {exc}"})
            continue
        for child in children:
            relative = f"{relative_dir}/{child.name}" if relative_dir else child.name
            if _is_excluded(relative):
                continue
            path = Path(child.path)
            try:
                if child.is_symlink():
                    entries.append((relative, path, "symlink"))
                elif child.is_dir(follow_symlinks=False):
                    entries.append((relative, path, "dir"))
                    stack.append((relative, path))
                elif child.is_file(follow_symlinks=False):
                    entries.append((relative, path, "file"))
                else:
                    entries.append((relative, path, "other"))
            except OSError as exc:
                errors.append({"path": relative, "error": f"{type(exc).__name__}: {exc}"})
    entries.sort(key=lambda item: item[0])
    errors.sort(key=lambda item: item["path"])
    return entries, errors


def build_manifest(
    run_dir: str | Path,
    *,
    sealed_at: str,
    sealed_by: str,
    seal_ref: str = "",
    sealed_marker_sha256: str = "",
) -> dict[str, Any]:
    """生成封存全量清单（不落盘）。"""
    root = Path(run_dir)
    files: list[dict[str, Any]] = []
    dirs: list[dict[str, Any]] = []
    others: list[dict[str, Any]] = []
    total_bytes = 0
    scanned, scan_errors = _scan_entries(root)
    for relative, path, kind in scanned:
        if kind == "symlink":
            files.append({"path": relative, "kind": "symlink", "symlink": os.readlink(path)})
        elif kind == "dir":
            dirs.append({"path": relative, "kind": "dir"})
        elif kind == "file":
            size = path.stat().st_size
            total_bytes += size
            files.append({"path": relative, "kind": "file", "size": size, "sha256": _sha256_file(path)})
        else:                       # fifo / socket / device：记类型即可（内容不可哈希）
            others.append({"path": relative, "kind": "other", "stat_kind": _stat_kind(path)})

    append_only: list[dict[str, Any]] = []
    for name in APPEND_ONLY_NAMES:
        path = root / name
        if not path.is_file():
            continue
        data = path.read_bytes()
        append_only.append({"path": name, "size": len(data), "sha256": _sha256_bytes(data)})

    return {
        "schema_version": SCHEMA_VERSION,
        "run_dir": str(root),
        "sealed_at": sealed_at,
        "sealed_by": sealed_by,
        "seal_ref": seal_ref,
        "sealed_marker_sha256": sealed_marker_sha256,
        "inventory": INVENTORY_ALL_ENTRIES,
        "file_count": len(files),
        "entry_count": len(files) + len(dirs) + len(others),
        "total_bytes": total_bytes,
        "files": files,
        "dirs": dirs,
        "others": others,
        # 封存时没扫全 ⇒ 如实记下（write_manifest 会据此拒绝封存，不给假覆盖）
        "scan_errors": scan_errors,
        "append_only": append_only,
        "excluded": dict(EXCLUDED_REASONS),
        "backfilled": False,
        "backfilled_at": "",
        "note": "封存全量清单：verify 逐项重算。force 改动合法但会被列出（有账可查）；"
                "无账改动一律视为可疑。",
        "publication_authorization": "not_authorized",
    }


def _anchor_dir() -> Path:
    return Path(os.environ.get(ANCHOR_DIR_ENV) or DEFAULT_ANCHOR_DIR)


def anchor_file_for(run_dir: str | Path) -> Path:
    """锚点文件路径：以 run 的相对标识命名（`<日期>-<批次>`），落在锚点存储里。"""
    root = Path(run_dir).resolve()
    try:
        tail = root.parts[-2:]
        ident = "-".join(tail)
    except Exception:                                    # pragma: no cover - 纯兜底
        ident = root.name
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in ident)
    return _anchor_dir() / (safe + ANCHOR_FILE_SUFFIX)


def _manifest_digest(payload: Mapping[str, Any]) -> str:
    """清单摘要——**排除 `anchor` 块自身**（否则自指）。

    锚点就是拿它来判"清单有没有被改写"：任何别处的改动都会改这个摘要。
    """
    body = {key: value for key, value in payload.items() if key != "anchor"}
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    # surrogateescape：路径含非 UTF-8 字节时 json 里会留下孤立代理字符（\udcff…），
    # 严格 utf-8 编码会抛 UnicodeEncodeError 把 seal() 直接打崩（复核 F5）。
    # 对合法 UTF-8 内容这个参数不改变任何字节，所以既有摘要不受影响。
    return _sha256_bytes(canonical.encode("utf-8", "surrogateescape"))


def _anchor_remote() -> str:
    return os.environ.get(ANCHOR_PUSH_ENV, "").strip()


def _replicate_anchor(path: Path, *, ident: str) -> tuple[str, str]:
    """把本机锚点文件提交并推到离机仓库。失败不抛——调用方按 `replication=failed` 如实记录
    （本机锚点仍然有效，只是没有离机副本）。"""
    remote = _anchor_remote()
    if not remote:
        return "local-only", ""
    work = path.parent / ".seal-ledger-work"
    env = {**os.environ, "GIT_AUTHOR_NAME": "ruoyu-seal-anchor",
           "GIT_AUTHOR_EMAIL": "seal-anchor@localhost",
           "GIT_COMMITTER_NAME": "ruoyu-seal-anchor",
           "GIT_COMMITTER_EMAIL": "seal-anchor@localhost"}
    try:
        if not (work / ".git").is_dir():
            work.mkdir(parents=True, exist_ok=True)
            clone = subprocess.run(
                ["git", "clone", "--depth", "1", remote, str(work)],
                capture_output=True, text=True, timeout=30, env=env,
            )
            if clone.returncode != 0:
                return "failed", (clone.stderr or clone.stdout or "clone failed")[-400:]
        else:
            pull = subprocess.run(
                ["git", "-C", str(work), "pull", "--ff-only"],
                capture_output=True, text=True, timeout=30, env=env,
            )
            if pull.returncode != 0:
                return "failed", (pull.stderr or pull.stdout or "pull failed")[-400:]
        dest = work / "anchors" / path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
        subprocess.run(["git", "-C", str(work), "add", "--", f"anchors/{path.name}"],
                       check=True, capture_output=True, text=True, timeout=15, env=env)
        commit = subprocess.run(
            ["git", "-C", str(work), "commit", "-m", f"anchor {ident}"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        if commit.returncode != 0 and "nothing to commit" not in (commit.stdout + commit.stderr):
            return "failed", (commit.stderr or commit.stdout)[-400:]
        push = subprocess.run(
            ["git", "-C", str(work), "push", "origin", "HEAD:main"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        if push.returncode != 0:
            return "failed", (push.stderr or push.stdout or "push failed")[-400:]
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        return "failed", f"{type(exc).__name__}: {exc}"
    return "pushed", remote


def write_anchor(run_dir: str | Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    """把清单摘要写到 run 之外，返回要嵌进清单的 `anchor` 块。

    离线策略（controller 2026-09-24 定）：锚点写不进去或离机复制失败都不阻断封存，
    但清单必须如实区分这两种情形——**别假装已锚定**：

    - 锚点**写不进去** → `anchor_unavailable`；
    - 锚点写成了、只是**离机复制失败** → `anchored` / `kind=local-snapshot` /
      `replication=failed`（此前这里也返回 `anchor_unavailable`，于是清单说"锚点不可用"、
      而 `verify` 走"锚点文件在"的分支报 `intact`，机器可读层自相矛盾，人读行也丢掉了
      「仅本机快照」的警告——第三轮复核 major）。
    """
    digest = _manifest_digest(payload)
    path = anchor_file_for(run_dir)
    remote_configured = bool(_anchor_remote())
    record = {
        "schema_version": "seal-anchor-v1",
        "run_dir": str(Path(run_dir).resolve()),
        "run_id": str(payload.get("run_dir", "")),
        "sealed_at": str(payload.get("sealed_at", "")),
        "sealed_by": str(payload.get("sealed_by", "")),
        "manifest_digest": digest,
        "anchored_at": _dt.datetime.now().astimezone().replace(microsecond=0).isoformat(),
        # 没配离机推送时**本机此刻就知道**结果是 local-only，不该写成 pending 让它永远错下去
        # （2026-09-25 复核 F1）；配了推送就先写 pending，复制完再回写真实结果（见下）。
        "replication": "pending" if remote_configured else "local-only",
    }

    def _persist() -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(_json_text(record), encoding="utf-8")
        os.replace(tmp, path)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _persist()
    except OSError as exc:
        return {
            "status": "anchor_unavailable",
            "reason": f"锚点存储不可写（{type(exc).__name__}: {exc}）：{path.parent}",
            "remedy": f"检查 {ANCHOR_DIR_ENV} 指向的目录是否可写",
            "manifest_digest": digest,
        }
    replication, detail = _replicate_anchor(path, ident=path.name)
    if replication != record["replication"]:
        # 回写本机锚点，让它记的是**真实**结果。
        # 注：配了离机推送时，离机仓库里那份是"推送当时"的内容（replication 仍写 pending），
        # 只有下一次推送同一锚点才会追上——这是已知的、仅影响离机账本显示的一步滞后。
        record["replication"] = replication
        try:
            _persist()
        except OSError:
            pass          # 回写失败不改结论：清单里的 anchor 块才是权威
    if replication == "failed":
        # 第二轮复核 major：本机锚点**确实写成了**，所以清单该说"已锚到 run 之外"，
        # 只把"离机那一步失败"记进 replication。此前返回 anchor_unavailable，于是同一份
        # 报告里清单说"锚点不可用"、verify 走"文件在"的分支说 intact/退出 0——机器可读层
        # 自相矛盾，人读行还丢掉了"仅本机快照可被本地改写掩盖"的警告。
        return {
            "status": "anchored",
            "kind": "local-snapshot",
            "path": str(path),
            "manifest_digest": digest,
            "replication": "failed",
            "remote": _anchor_remote(),
            "reason": f"本机锚点已写，离机复制失败：{detail}",
            # 不说"修好后重跑封存"：`seal()` 幂等（已有 SEALED 就 already_sealed），
            # 重跑既不重试复制、这条路在 verify 里也走不到（复核 minor）。
            "remedy": f"本机锚点已生效（清单已绑定到 run 之外）；离机副本没成。"
                      f"修好 {ANCHOR_PUSH_ENV} 指向的仓库后，要补推只能 unseal 再 reseal"
                      f"——重新封存不会重试这一步。",
            "note": "只有本机快照：同 uid 的写手可以同时改写本机锚点与清单来掩盖篡改。",
        }
    note = "清单自身已锚到 run 之外"
    if replication == "local-only":
        note += "；未设置离机推送，只改本机锚点仍能掩盖"
    return {
        "status": "anchored",
        "kind": "offhost-snapshot" if replication == "pushed" else "local-snapshot",
        "path": str(path),
        "manifest_digest": digest,
        "replication": replication,
        "remote": detail,
        "note": note,
    }


def check_remote_anchor(run_dir: str | Path, *, remote: str = "") -> dict[str, Any]:
    """对照离机副本。只在显式调用时联网；verify 不走这里。"""
    url = remote or _anchor_remote() or DEFAULT_ANCHOR_REMOTE
    name = anchor_file_for(run_dir).name
    local = read_anchor(run_dir)
    try:
        shown = subprocess.run(
            ["git", "archive", f"--remote={url}", "main", f"anchors/{name}"],
            capture_output=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "remote_unavailable", "remote": url, "reason": f"{type(exc).__name__}: {exc}"}
    if shown.returncode != 0:
        err = shown.stderr.decode("utf-8", "replace")[-300:]
        missing = any(token in err for token in ("does not exist in", "Not a valid object name", "not found in"))
        return {
            "status": "remote_missing" if missing else "remote_unavailable",
            "remote": url,
            "reason": err.strip() or "离机仓库没有这条锚点",
        }
    listed = subprocess.run(["tar", "-t"], input=shown.stdout, capture_output=True, timeout=10)
    if listed.returncode != 0 or name not in listed.stdout.decode():
        return {"status": "remote_missing", "remote": url, "reason": "离机仓库没有这条锚点"}
    extracted = subprocess.run(["tar", "-xO", f"anchors/{name}"], input=shown.stdout, capture_output=True, timeout=10)
    if extracted.returncode != 0:
        return {"status": "remote_unavailable", "remote": url, "reason": "离机锚点读不出来"}
    try:
        remote_record = json.loads(extracted.stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        return {"status": "remote_unavailable", "remote": url, "reason": f"离机锚点不是 JSON：{exc}"}
    remote_digest = str(remote_record.get("manifest_digest", ""))
    if not isinstance(local, dict):
        # 本机锚点没了。**但离机摘要已经在手里**——它是唯一穿得过"同 uid 同时改本机
        # 锚点"的证据，不能白白丢掉（2026-09-25 复核 F3：此前一律返回 local_missing，
        # 把"可证明的漂移"降级成"无法验证"；删掉本机锚点恰是攻击者最省力的一步）。
        manifest = load_manifest(run_dir)
        now_digest = _manifest_digest(manifest) if isinstance(manifest, dict) else ""
        if now_digest and remote_digest and now_digest != remote_digest:
            return {
                "status": "remote_mismatch",
                "remote": url,
                "local_digest": "",
                "remote_digest": remote_digest,
                "reason": "本机锚点缺失，但离机锚点记的摘要与现算的清单摘要不一致：清单被改写",
            }
        return {"status": "local_missing", "remote": url, "remote_digest": remote_digest}
    if str(local.get("manifest_digest")) != remote_digest:
        return {
            "status": "remote_mismatch",
            "remote": url,
            "local_digest": local.get("manifest_digest", ""),
            "remote_digest": remote_digest,
        }
    return {"status": "matches", "remote": url, "manifest_digest": local.get("manifest_digest", "")}


def read_anchor_state(run_dir: str | Path) -> tuple[dict[str, Any] | None, str]:
    """读锚点，并**区分**「没有」与「读不出」。

    返回 `(record, state)`，state ∈ `found` / `missing` / `unreadable` / `store_unreadable`：

    - `missing`：路径确实不存在（FileNotFoundError）。
    - `unreadable`：路径在，但内容损坏 / 不是 JSON 对象。
    - `store_unreadable`：连 `os.stat` 都做不了（父目录不可读、NFS、路径被换成不可进入的东西）。

    为什么必须分开（2026-09-25 独立复核 F2）：`Path.exists()` 会把 `PermissionError`
    吞成 False，于是「锚点库不可读」被当成「从来没有锚点」，还配上一句代码无从知道的历史
    断言。三种情形对应的操作动作完全不同（修权限 / 查篡改 / 就是老 run）。
    """
    path = anchor_file_for(run_dir)
    try:
        os.stat(path)
    except FileNotFoundError:
        return None, "missing"
    except OSError:
        return None, "store_unreadable"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "unreadable"
    return (payload, "found") if isinstance(payload, dict) else (None, "unreadable")


def read_anchor(run_dir: str | Path) -> dict[str, Any] | None:
    record, _state = read_anchor_state(run_dir)
    return record


def _json_text(payload: Mapping[str, Any], *, indent: int = 2) -> str:
    """把 payload 序列化成**能落盘**的 JSON 文本（含非 UTF-8 路径时也不崩）。

    路径里有非 UTF-8 字节时，`json.dumps(..., ensure_ascii=False)` 会留下孤立代理字符
    （`\\udcff`），而 `str.encode("utf-8")` 严格编码会抛 `UnicodeEncodeError`——封存
    直接崩在半路（2026-09-25 复核 F5）。此时退回 `ensure_ascii=True`：代理字符被写成
    `\\udcff` 转义，既能落盘、又能被 `json.loads` **原样**读回，因此清单摘要保持稳定。
    正常内容仍走 `ensure_ascii=False`，中文照旧可读（清单是给人复核的）。
    """
    return json_text(payload, indent=indent) + "\n"


def write_manifest(run_dir: str | Path, payload: dict[str, Any]) -> Path:
    # 扫不动的子树 ⇒ 这份清单**证明不了覆盖完整**：拒绝落盘（fail-closed），
    # 否则就会在没读完的树上留下"看起来全量"的封存（六轮复核 major）
    errors = payload.get("scan_errors") or []
    if errors:
        detail = "; ".join(f"{item.get('path')}: {item.get('error')}" for item in errors[:3])
        raise ValueError(
            f"封存清单不完整：有 {len(errors)} 处扫不动（{detail}）。"
            "先修好这些路径的权限/类型再封存——不许封存一份证明不了覆盖的清单。"
        )
    anchor = write_anchor(run_dir, payload)      # 先按"不含 anchor 块"的正文算摘要
    payload["anchor"] = anchor                   # 再嵌进清单（`_manifest_digest` 会排除它）
    path = manifest_path(run_dir)
    path.write_text(_json_text(payload), encoding="utf-8")
    return path


def load_manifest(run_dir: str | Path) -> dict[str, Any] | None:
    path = manifest_path(run_dir)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _changelog_index(run_dir: Path) -> dict[str, dict[str, Any]]:
    """路径 → 最后一条记账（谁/何时/是否 forced）。verify 只读，绝不写。"""
    path = run_dir / "evidence-changelog.jsonl"
    index: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return index
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            index[entry["path"]] = entry
    return index


def verify(run_dir: str | Path) -> dict[str, Any]:
    """逐项重算清单，返回 {status, changes, …}（只读）。

    **返回字典的键集契约**（第二轮复核 minor；第三轮复核 F7 更正了本文的枚举）：

    - 所有返回都带 `status` / `run_dir` / `changes`；
    - 给出结论或需要处置时带 `reason`；**能给出去路时**带 `remedy`（现在
      `unverifiable` 的每一条都有出路，见下）；
    - `anchor` **只有走到锚点判定的终态路径**才带。`unverifiable` 的早返回共 **6 条**
      （副本不适用 / 没有清单 / 版本不认识 / v2 缺 inventory 标志 / v1 带 inventory 标志 /
      树扫不动），它们的形状**不完全相同**（前三条与"树扫不动"没有锚点信息，也就无从带
      `anchor`；不是每条都带 `reason` 之外的同一组键）。调用方一律用 `.get()` 读，
      **别假定键一定在**——这一点是契约本身，不是实现细节。
    """
    root = Path(run_dir)
    if (root / SANDBOX_MARKER).is_file():
        # 演练副本（scripts/run_sandbox.py）：SEALED 被改名为 SEALED.from-source，
        # 副本本来就该可写。对它跑封存校验只会报"SEALED 不见了"这种假漂移。
        return {
            "status": "not_applicable",
            "run_dir": str(root),
            "reason": "这是演练副本（存在 SANDBOX.json），封存校验不适用于副本；"
                      "要校验请对源 run 跑。",
            "changes": [],
        }
    manifest = load_manifest(root)
    if manifest is None:
        return {
            "status": "unverifiable",
            "run_dir": str(root),
            "reason": "该 run 没有封存全量清单（封存时还没有 run_seal，或清单被删）",
            "remedy": "若确认要补录：python -m article_group.run_seal --run-root <run> --backfill"
                      "（补录只能证明补录之后未被改动，不能证明封存时刻的内容）",
            "changes": [],
        }
    if manifest.get("schema_version") not in KNOWN_SCHEMA_VERSIONS:
        return {
            "status": "unverifiable",
            "run_dir": str(root),
            "reason": f"清单版本不认识：{manifest.get('schema_version')!r}",
            # 补上 remedy（第二轮复核 minor：四种 unverifiable 早返回里只有这一条没有出路）
            "remedy": f"本版本只认 {KNOWN_SCHEMA_VERSIONS}。清单可能是被改写过的，"
                      "也可能是更新版本的工具写的：先确认这一轮没跑过更新的代码；"
                      "若确认清单完好，用 --backfill 重写（只能证明重写之后未被改动）。",
            "changes": [],
        }

    listed = {str(item["path"]): item for item in manifest.get("files", []) if isinstance(item, dict)}
    # 按**清单格式**门控：v1 走旧口径（只比文件/符号链接），v2 才用全条目集合。
    # 混用会让既有 v1 封存 run 冒出成堆假 added（六轮复核实测 4 条）。
    # 门控键在**版本**上，而不是标志上（七轮复核 H2）：标志可被进程外改写，
    # 且"标志丢了 → 拿 v2 清单走 v1 口径"会安静降级；反过来"v1 清单带标志 → 4 条假 added"。
    if manifest.get("schema_version") == SCHEMA_VERSION:
        if manifest.get("inventory") != INVENTORY_ALL_ENTRIES:
            return {
                "status": "unverifiable",
                "run_dir": str(root),
                "reason": "清单声明 v2 却缺 inventory 标志：可能被改写，拒绝给结论",
                # 第三轮复核 F7：这条此前没有 remedy，操作者拿到结论却没有出路
                "remedy": _contradictory_manifest_remedy(root),
                "changes": [],
            }
        all_kinds = True
    else:
        if "inventory" in manifest:
            # 版本与标志是两个独立信号；矛盾时**拒绝给结论**，不安静降级（2026-09-25）。
            # 此前是"v1 带标志 → 忽略标志走旧口径"，等于给"把 schema_version 改回 v1"
            # 留了一条降低校验强度的路。
            return {
                "status": "unverifiable",
                "run_dir": str(root),
                "reason": "清单声明 v1 却带着 v2 的 inventory 标志：两个信号矛盾，拒绝给结论",
                "remedy": _contradictory_manifest_remedy(root),
                "changes": [],
            }
        all_kinds = False          # 真 v1：只比文件/符号链接
    present: dict[str, tuple[Path, str | None]] = {}
    # 两个版本用**同一个**枚举器：v1 此前走 `_iter_entries`（Path.rglob），而本机
    # Python 3.14.4 下 rglob 会静默吞掉 OSError，于是"扫不动的树"在 v1 上照样给
    # intact（v2 同树给 unverifiable）。现存 daily-008/009/010 全是 v1，走的正是那条路。
    scanned, scan_errors = _scan_entries(root)
    if scan_errors:
        return {
            "status": "unverifiable",
            "changes": [
                {"path": item["path"], "kind": "scan_error", "detail": item["error"]}
                for item in scan_errors
            ],
            **scan_error_report(
                scan_errors, run_dir=root,
                reason="有扫不动的子树：清单无法证明覆盖完整，不许给 intact",
            ),
        }
    if all_kinds:
        present = {relative: (path, kind) for relative, path, kind in scanned}
    else:
        present = {relative: (path, None) for relative, path, kind in scanned
                   if kind in ("file", "symlink")}
    changes: list[dict[str, Any]] = []

    for relative, item in listed.items():
        found = present.get(relative)
        if found is None:
            if relative in MAY_BE_ABSENT:
                continue          # 授权缺失；内容若在，下面的 size/sha256 照查
            changes.append({"path": relative, "kind": "missing", "detail": "清单里有、现在不在"})
            continue
        path, kind = found
        expected = str(item.get("kind") or "file")
        if all_kinds and kind is not None and kind != expected:
            changes.append({"path": relative, "kind": "kind_changed",
                            "detail": f"{expected} → {kind}"})
            continue
        if path.is_symlink():
            if os.readlink(path) != item.get("symlink"):
                changes.append({"path": relative, "kind": "symlink_changed",
                                "detail": f"{item.get('symlink')!r} → {os.readlink(path)!r}"})
            continue
        if item.get("symlink") is not None:
            changes.append({"path": relative, "kind": "symlink_changed",
                            "detail": "清单记的是符号链接，现在是普通文件"})
            continue
        size = path.stat().st_size
        if size != item.get("size"):
            changes.append({"path": relative, "kind": "modified",
                            "detail": f"size {item.get('size')} → {size}"})
            continue
        digest = _sha256_file(path)
        if digest != item.get("sha256"):
            changes.append({"path": relative, "kind": "modified",
                            "detail": f"sha256 {str(item.get('sha256'))[:12]}… → {digest[:12]}…"})
    # 目录 / 其它类型（**只有 v2 清单才有**）：只查存在与类型
    #
    # 2026-09-25 独立审计修：这段此前**不受版本门控**，而 `accounted.add(relative)` 会把
    # 该路径从 added 集合里摘掉，同时 v1 的 `present[..][1]` 恒为 None 又让 kind_changed
    # 打不响——于是 v1 清单里塞一条伪造的 `dirs` 记录，就能让封存后新增的文件不被报
    # added（实测 intact）。v1 清单本来就没有 dirs/others，加门控不影响它。
    accounted = set(listed)
    if all_kinds:
        for key, want in (("dirs", "dir"), ("others", "other")):
            for item in manifest.get(key, []):
                if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                    continue
                relative = item["path"]
                accounted.add(relative)
                found = present.get(relative)
                if found is None:
                    if relative in MAY_BE_ABSENT:
                        continue
                    changes.append({"path": relative, "kind": "missing",
                                    "detail": f"清单里有（{key}）、现在不在"})
                elif found[1] is not None and found[1] != want:
                    changes.append({"path": relative, "kind": "kind_changed",
                                    "detail": f"{want} → {found[1]}"})
                elif want == "other":
                    # 同为 other 但具体类型不同（fifo↔socket↔device）也要报（七轮复核 minor 3）
                    was = str(item.get("stat_kind") or "")
                    now = _stat_kind(found[0])
                    if was and now and was != now:
                        changes.append({"path": relative, "kind": "kind_changed",
                                        "detail": f"{was} → {now}"})
    for relative in sorted(set(present) - accounted):
        changes.append({"path": relative, "kind": "added", "detail": "清单里没有、现在多出来"})

    for item in manifest.get("append_only", []):
        relative = str(item.get("path"))
        path = root / relative
        if not path.is_file():
            changes.append({"path": relative, "kind": "missing", "detail": "append-only 文件不见了"})
            continue
        data = path.read_bytes()
        frozen = int(item.get("size", 0))
        if len(data) < frozen:
            changes.append({"path": relative, "kind": "append_only_truncated",
                            "detail": f"封存时 {frozen} 字节，现在 {len(data)} 字节"})
        elif _sha256_bytes(data[:frozen]) != item.get("sha256"):
            changes.append({"path": relative, "kind": "append_only_rewritten",
                            "detail": "封存时的前 N 字节已被改写"})

    if manifest.get("sealed_marker_sha256"):
        marker = root / SEALED_NAME
        expected = str(manifest["sealed_marker_sha256"])
        if not marker.is_file():
            changes.append({"path": SEALED_NAME, "kind": "missing", "detail": "封存标记不见了"})
        elif _sha256_file(marker) != expected:
            changes.append({"path": SEALED_NAME, "kind": "modified",
                            "detail": "封存标记的字节与封存时不一致"})

    # 锚点交叉校验：清单自己在不在锚点里对得上（这是"清单被改写"唯一查得出的地方）
    #
    # 2026-09-25 独立审计修：此前 `if isinstance(block, dict)` 才去读锚点，于是**被校验
    # 对象自己就能把校验关掉**——进程外写手删掉 `anchor` 块、或把它改成
    # `anchor_unavailable`，一份被改写的清单照报 intact。现在**无条件读锚点**。
    #
    # **已知限制**（复核 F2 要求写明）：同 uid 的写手可以**同时**删掉本机锚点文件并抹掉
    # 清单里的 `anchor` 块——那样本函数只能报 `unanchored`（退出码 3），无法证明发生过
    # 篡改。唯一能穿过这一层的是**离机**锚点副本（配 RUOYU_SEAL_ANCHOR_PUSH），见
    # `check_remote_anchor`。
    anchor_note: dict[str, Any] = {}
    anchored = False
    anchor_path = anchor_file_for(root)
    recorded, anchor_state = read_anchor_state(root)
    block = manifest.get("anchor") if isinstance(manifest.get("anchor"), dict) else {}
    declared = block.get("status")
    if anchor_state == "found":
        now_digest = _manifest_digest(manifest)
        if str(recorded.get("manifest_digest")) != now_digest:
            anchor_note = {"status": "anchor_mismatch"}
            changes.append({
                "path": MANIFEST_NAME, "kind": "anchor_mismatch",
                "detail": f"清单被改写：锚点记 {str(recorded.get('manifest_digest'))[:12]}… "
                          f"现算 {now_digest[:12]}…",
            })
        else:
            anchored = True
            # 把锚点文件的**事实**带进报告：只报 "anchored" 而不说清它是本机快照还是
            # 已离机，会让操作者把 intact 读成"离机证明过"（复核 F1 的安全假象）。
            replication = str(recorded.get("replication") or block.get("replication") or "unknown")
            anchor_note = {
                "status": "anchored",
                "path": str(anchor_path),
                "kind": recorded.get("kind") or block.get("kind"),
                "replication": replication,
                "remote": recorded.get("remote") or block.get("remote") or "",
            }
            # 第三轮复核 F4：**离机失败的原因要带到报告里**。此前这里不带 `reason`，于是
            # `_describe_anchor` 的 `anchor.get("reason")` 永远取不到，人读行永远退化成
            # 「离机复制失败：见清单」——操作者拿到结论却拿不到 clone 的报错原文。
            if replication != "pushed":
                anchor_note["reason"] = (recorded.get("reason") or block.get("reason") or "")
                anchor_note["note"] = recorded.get("note") or block.get("note") or ""
    elif anchor_state == "store_unreadable":
        # 连 stat 都做不了 ⇒ 不是"未锚定"，是**查不了**：不许给任何完整性结论。
        anchor_note = {
            "status": "anchor_store_unreadable",
            "reason": f"锚点存储不可读（无法 stat）：{anchor_path}",
            "remedy": f"检查 {ANCHOR_DIR_ENV} 指向的目录是否存在、权限是否可读",
        }
    elif anchor_state == "unreadable":
        # 路径在、内容坏了：fail-closed 当漂移（复核 §1c 认可这一支）
        anchor_note = {
            "status": "anchor_unreadable",
            "reason": f"锚点文件在（{anchor_path}）但读不出内容：损坏、被换成目录或权限不足",
        }
        changes.append({
            "path": MANIFEST_NAME, "kind": "anchor_unreadable",
            "detail": anchor_note["reason"],
        })
    elif declared == "anchored":
        anchor_note = {
            "status": "anchor_missing",
            "reason": "清单声称已锚定，但锚点存储里找不到对应记录",
        }
        changes.append({
            "path": MANIFEST_NAME, "kind": "anchor_missing",
            "detail": anchor_note["reason"],
        })
    elif declared == "anchor_unavailable":
        # 封存当时锚点就写不进去；现在磁盘上也确实没有。如实沿用清单的说法。
        anchor_note = {
            "status": "anchor_unavailable",
            "reason": block.get("reason", ""),
            "remedy": _unanchored_remedy(root),
        }
    else:
        anchor_note = {
            "status": "unanchored",
            # 只陈述**已知**事实。此前这里写"封存早于锚点机制"是在断言一段代码无从知道的
            # 历史——攻击者删掉锚点并抹掉块之后，得到的正是同一句话（复核 F2）。
            "reason": f"在 {anchor_path} 没有找到锚点记录（可能是本 run 早于锚点机制，"
                      f"也可能是锚点被删）",
            "remedy": _unanchored_remedy(root),
        }

    ledger = _changelog_index(root)
    for change in changes:
        entry = ledger.get(change["path"])
        change["authorized"] = entry is not None
        if entry is not None:
            change["ledger"] = {
                "at": entry.get("at"),
                "author": entry.get("author"),
                "reason": entry.get("reason"),
                "forced": entry.get("forced"),
            }

    if changes:
        status = "drifted"
    elif anchored:
        status = "intact"
    elif anchor_note.get("status") == "anchor_store_unreadable":
        # 锚点库**查不了**：既不是有漂移的证据，也不是"这个 run 没锚过"。
        status = "unverifiable"
    else:
        # 没有外部锚点：清单**有没有被改写**在这个 run 上查不出来。
        # 状态名刻意不以 intact 开头（复核 F2）：此前叫 intact_unanchored，操作者会读成
        # "文件没变，没事"，而它恰恰是一句**没能证明**的话。
        status = STATUS_UNANCHORED
    return {
        "status": status,
        **({"reason": anchor_note.get("reason", ""), "remedy": anchor_note.get("remedy", "")}
           if status == "unverifiable" else {}),
        "run_dir": str(root),
        "sealed_at": manifest.get("sealed_at"),
        "sealed_by": manifest.get("sealed_by"),
        "backfilled": bool(manifest.get("backfilled")),
        "backfilled_at": manifest.get("backfilled_at", ""),
        "checked_files": len(listed),
        "append_only_checked": len(manifest.get("append_only", [])),
        "changes": changes,
        "anchor": anchor_note,
        "unauthorized_changes": [item for item in changes if not item.get("authorized")],
        "publication_authorization": "not_authorized",
    }


def scan_error_report(scan_errors: Sequence[Mapping[str, Any]], *, run_dir: str | Path = "",
                      reason: str = "") -> dict[str, Any]:
    """扫不动时的**统一词汇**：`ok` / `run_dir` / `reason` / `remedy` / `scan_errors`。

    `preflight_scan` 与 `verify` 都用它，调用方不必为两种形状各写一套消息
    （八轮复核 (c)：`ok`/`remedy` 与 `status`/`reason` 混用，得适配）。
    """
    items = [dict(item) for item in scan_errors]
    return {
        "ok": False,
        "run_dir": str(run_dir),
        "reason": reason or f"有 {len(items)} 处扫不动：清单无法证明覆盖完整",
        "remedy": "先修好这些路径的权限或类型（让它们可读 / 可 stat）再重试",
        "scan_errors": items,
    }


def preflight_scan(run_dir: str | Path) -> dict[str, Any]:
    """封存前的**预检**：这棵树现在扫得动吗？

    给 `close_out` 这类"先改一堆文件、最后才封存"的流程用：不完整树上应当**在动手之前**
    就停下，而不是改了两分钟再抛（七轮复核 minor 4）。
    """
    root = Path(run_dir)
    if not root.is_dir():
        # 坏路径 ≠ 扫不动的树：前者是 --run-root 打错（该查参数），后者才要修权限。
        # 混为一谈会把"路径不存在"报成"无法验证的树 + 去修权限"（八轮复核 H2）
        return {
            "ok": False,
            "bad_root": True,
            "run_dir": str(root),
            "reason": "run 目录不存在或不是目录",
            "remedy": "检查 --run-root 指向的路径（不是权限问题）",
            "scan_errors": [],
        }
    _, scan_errors = _scan_entries(root)
    if scan_errors:
        return {**scan_error_report(scan_errors, run_dir=root), "bad_root": False}
    return {"ok": True, "bad_root": False, "run_dir": str(root), "scan_errors": [], "remedy": ""}


def backfill(run_dir: str | Path, *, author: str = "agent", reason: str = "") -> dict[str, Any]:
    """给"封存时还没有清单"的老 run 事后补录清单（必须留痕、且不假装能证明历史）。"""
    from article_group import runs_guard
    from article_group.evidence_write import append_changelog
    from article_group.run_state import sealed_record

    root = Path(run_dir)
    record = sealed_record(root)
    if not record:
        return {"status": "not_sealed", "run_dir": str(root)}
    if load_manifest(root) is not None:
        return {"status": "already_present", "run_dir": str(root)}

    stamp = _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()
    payload = build_manifest(
        root,
        sealed_at=str(record.get("sealed_at", "")),
        sealed_by=str(record.get("sealed_by", "")),
        seal_ref=str(record.get("seal_ref", "")),
        sealed_marker_sha256=_sha256_file(root / SEALED_NAME) if (root / SEALED_NAME).is_file() else "",
    )
    payload.update({
        "backfilled": True,
        "backfilled_at": stamp,
        "backfilled_by": author,
        "backfill_note": "事后补录：只能证明补录之后未被改动，不能证明封存时刻的内容。",
    })
    with runs_guard.sealed_write_token(root, reason="run_seal:backfill", author=author):
        write_manifest(root, payload)
        append_changelog(
            root,
            path=MANIFEST_NAME,
            reason=f"run_seal:backfill:{reason}" if reason else "run_seal:backfill",
            author=author,
            existed=False,
            after_sha256=_sha256_bytes(manifest_path(root).read_bytes()),
            forced=True,  # 目标 run 已封存：这是经令牌的显式写入，照实记
        )
    return {"status": "backfilled", **{key: payload[key] for key in ("backfilled_at", "file_count")}}


def _unanchored_remedy(run_dir: str | Path) -> str:
    """未锚定时的**正确**补救路径（2026-09-25 复核 F4）。

    此前这里写"旧 run 用 --backfill 补录"——**对触发这个状态的 run 根本无效**：
    `backfill()` 见到清单已存在就返回 `already_present`（它服务的对象是"封存时还没有
    清单"的 run）。实测 daily-008/009/010 三个真实封存 run 都停在这个状态，而
    `--backfill` 只会再给一次 already_present。
    """
    return (f"本 run 的清单已存在但未锚定（锚点预期位置：{anchor_file_for(run_dir)}）。"
            "--backfill 不会重写已有清单（它只给\"封存时还没有清单\"的 run 补录，"
            "这里会返回 already_present）；要拿到锚点必须 unseal 后重新 seal——"
            "代价是失去封存的当时性。也可接受本状态：退出码 3 表示"
            "\"文件与清单一致，但清单自身没被证明没被改写\"，交付时如实注明。")


def _contradictory_manifest_remedy(run_dir: str | Path) -> str:
    """清单的版本与标志互相矛盾时给出的出路（第三轮复核 F7：这两支此前没有 remedy）。

    拒绝给结论是对的（矛盾信号不能安静降级），但操作者需要一条能走的路：先**从 run 之外**
    核对（本机锚点文件或离机副本里的那份摘要），确认清单是否被动过；确认无误再用
    `--backfill` 重写——注意重写只能证明"重写之后"未被改动。
    """
    return ("清单的版本与 inventory 标志互相矛盾，无法判定该走哪套口径。先**脱离本机**核对："
            f"比对锚点记录（{anchor_file_for(run_dir)}）或离机副本里的清单摘要，确认清单是否被改写。"
            "若确认只是历史遗留的形状问题，可用 --backfill 重写清单——"
            "但那只能证明重写之后未被改动，不能证明封存时刻的内容。")


def _describe(report: dict[str, Any]) -> str:
    status = report.get("status")
    if status == "not_applicable":
        return f"不适用：{report.get('reason')}"
    if status == "unverifiable":
        # 锚点行在这里也要打印（复核 F6）：此前 unverifiable 提前返回，"永远打印锚点
        # 状态"的注释对这条路径是假的，而这条路径恰恰最需要告诉人锚点怎么了。
        lines = [f"无法验证：{report.get('reason')}"]
        if report.get("remedy"):
            lines.append(f"  {report['remedy']}")
        if report.get("anchor"):
            lines.append(f"  {_describe_anchor(report['anchor'])}")
        return "\n".join(lines)
    lines = [
        f"封存完整性：{status}（核对 {report.get('checked_files')} 个文件，"
        f"append-only {report.get('append_only_checked')} 个）",
        f"  sealed_at={report.get('sealed_at')} by={report.get('sealed_by')}"
        + ("（事后补录清单）" if report.get("backfilled") else ""),
        # 锚点状态**永远打印**：默认部署不推离机，而"本 run 从未成功锚定"此前在人读
        # 模式里完全不可见（只有 --json 才看得到），于是 intact 被读成"证明过没被改"。
        f"  {_describe_anchor(report.get('anchor') or {})}",
    ]
    for change in report.get("changes", []):
        mark = "有账" if change.get("authorized") else "无账"
        detail = change.get("detail", "")
        lines.append(f"  [{mark}] {change.get('kind')}: {change.get('path')} — {detail}")
        if change.get("authorized"):
            entry = change["ledger"]
            lines.append(f"        记账：{entry.get('at')} by {entry.get('author')} "
                         f"reason={entry.get('reason')} forced={entry.get('forced')}")
    if not report.get("changes"):
        if status == STATUS_UNANCHORED:
            lines.append("  文件与清单逐字节一致；但**清单自身没有被证明没被改写**"
                         "（本 run 没有可用的外部锚点）——不按 intact 上报。")
        else:
            lines.append("  与封存时逐字节一致。")
    return "\n".join(lines)


def _describe_anchor(anchor: Mapping[str, Any]) -> str:
    """锚点状态的一行说明（人读模式也必须看得见，不许只在 --json 里）。"""
    status = str(anchor.get("status") or "unknown")
    if status == "anchored":
        # 不许再用 `or "snapshot"` 兜底：那个取值在数据里根本不存在（复核 F1）。
        # 更要紧的是**必须说清本机快照还是已离机**——默认部署不推离机，此时同 uid 的
        # 写手只要重写锚点文件就能让被改写的清单照样报 intact。
        kind = anchor.get("kind")
        replication = str(anchor.get("replication") or "unknown")
        head = f"锚点：anchored（{kind}）" if kind else "锚点：anchored"
        if replication == "pushed":
            remote = anchor.get("remote") or "?"
            return f"{head}；已离机复制（{remote}）"
        # 除 pushed 之外**一律**按"不能当作已有离机副本"警告（第二轮复核 major）：
        # local-only / failed / pending / unknown 的处境相同——本机锚点挡不住同 uid 写手。
        # 此前只对字面量 local-only 打印警告，"配了推送但失败"就漏掉了同等警告。
        #
        # 措辞按第三轮复核 #4 收紧：不要把"未知/未完成"说成"未离机复制"这个事实
        # （此前 pending 时头部断"未离机复制"、括号里又说"状态未知"，自相矛盾）。
        if replication == "local-only":
            why = "未设置离机推送，没有离机副本"
        elif replication == "failed":
            why = f"离机复制失败（{anchor.get('reason') or '见清单'}），没有离机副本"
        elif replication == "pending":
            why = "离机复制尚未完成（离机账本里那份滞后一步），此刻不能当作已有离机副本"
        else:
            why = f"离机复制状态无法判定（{replication}），不能当作已有离机副本"
        return f"{head}；**仅本机快照**（{why}）——只改本机锚点仍能掩盖篡改，" \
               "要真正关上需让 RUOYU_SEAL_ANCHOR_PUSH 可达并成功推送"
    if status == "unanchored":
        return f"锚点：未锚定 —— {anchor.get('reason', '')}"
    if status == "anchor_unavailable":
        return f"锚点：anchor_unavailable —— {anchor.get('reason', '')}"
    if status == "anchor_mismatch":
        return "锚点：anchor_mismatch（清单正文与 run 之外的锚点对不上）"
    if status == "anchor_missing":
        return f"锚点：anchor_missing —— {anchor.get('reason', '')}"
    if status == "anchor_store_unreadable":
        return f"锚点：anchor_store_unreadable —— {anchor.get('reason', '')}"
    if status == "anchor_unreadable":
        return f"锚点：anchor_unreadable —— {anchor.get('reason', '')}"
    return f"锚点：{status}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m article_group.run_seal",
        description="校验（或事后补录）run 的封存全量清单：0 完好 / 2 有漂移 / 3 无法验证 / 4 副本不适用",
    )
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--backfill", action="store_true",
                        help="给封存时还没有清单的老 run 补录（留痕；不假装能证明历史）")
    parser.add_argument("--author", default="agent")
    parser.add_argument("--reason", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--check-remote", action="store_true",
                        help="额外对照离机锚点（会联网；verify 本身不联网）")
    args = parser.parse_args(argv)

    if args.check_remote:
        remote_report = check_remote_anchor(args.run_root)
        print(json.dumps(remote_report, ensure_ascii=False, indent=2))
        # 「连不上」是**无法验证**（3），不是「有漂移」（2）；「离机也没有这条」同理。
        # 只有摘要确实对不上才算漂移。
        return {
            "matches": EXIT_INTACT,
            "remote_mismatch": EXIT_DRIFTED,
        }.get(str(remote_report.get("status")), EXIT_UNVERIFIABLE)

    if args.backfill:
        try:
            result = backfill(args.run_root, author=args.author, reason=args.reason)
        except ValueError as exc:
            # 补录也会遇到"扫不动"的树：按文档退出码 3 上报，不要甩 traceback（七轮复核 minor 4）。
            # **只发一份 JSON**（到 stderr）：stdout 与 stderr 各发一份不同形状的文档会让
            # `2>&1 | jq` 直接解析失败（八轮复核 minor 3）
            pre = preflight_scan(args.run_root)
            payload = {"status": "unverifiable", "reason": str(exc), **pre}
            print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
            return EXIT_UNVERIFIABLE
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["status"] != "backfilled":
            return EXIT_UNVERIFIABLE

    report = verify(args.run_root)
    # 扫不动要让人**看得见原因**：人读模式只印状态行，操作者会不知道该怎么修
    if report.get("scan_errors"):
        print(f"无法验证：有 {len(report['scan_errors'])} 处扫不动——先修好权限/类型再重试；"
              f"首个：{report['scan_errors'][0]['path']}（{report['scan_errors'][0]['error']}）",
              file=sys.stderr)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else _describe(report))
    return {
        "intact": EXIT_INTACT,
        STATUS_UNANCHORED: EXIT_UNVERIFIABLE,
        "drifted": EXIT_DRIFTED,
        "unverifiable": EXIT_UNVERIFIABLE,
        "not_applicable": EXIT_NOT_APPLICABLE,
    }.get(str(report.get("status")), EXIT_UNVERIFIABLE)


__all__ = [
    "APPEND_ONLY_NAMES",
    "find_run_root",
    "preflight_scan",
    "write_anchor",
    "read_anchor",
    "check_remote_anchor",
    "anchor_file_for",
    "DEFAULT_ANCHOR_DIR",
    "DEFAULT_ANCHOR_REMOTE",
    "ANCHOR_PUSH_ENV",
    "scan_error_report",
    "is_run_root",
    "EXCLUDED_REASONS",
    "MAY_BE_ABSENT",
    "EXIT_DRIFTED",
    "EXIT_INTACT",
    "STATUS_UNANCHORED",
    "read_anchor_state",
    "EXIT_NOT_APPLICABLE",
    "EXIT_UNVERIFIABLE",
    "MANIFEST_NAME",
    "SANDBOX_MARKER",
    "SCHEMA_VERSION",
    "backfill",
    "build_manifest",
    "load_manifest",
    "main",
    "manifest_path",
    "verify",
    "write_manifest",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
