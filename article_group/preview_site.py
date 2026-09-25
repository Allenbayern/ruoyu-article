"""日更交付的"可点开预览页"生成器（2026-09-18 接入 daily_engine）。

**为什么要它**：run 里的 Markdown 与公众号 HTML 本身**点不开**——它们躺在
`runs/` 里，没有被任何服务托管；controller 要的是"标题能点、点开能读"的链接。
本模块把 run 既有产物渲染成一套自包含静态站点，写进 run 内的 `preview/`：

- `preview/index.html`：目录页，**标题即链接**，另给公众号复制版入口与交付状态；
- `preview/art-00N.html`：阅读页，自包含、**零外链**（内网/离线可读）、
  适配手机 / 暗色 / 打印，正文与 Markdown 成稿**逐段一致**（有测试钉死）；
- `preview/wechat/**`：把既有的公众号复制版原样搬进来，站点自洽；
- `preview/links.json`：**交付链接清单**（2026-09-24）——每篇的正文 / 阅读页 /
  （有则）公众号版的 run 相对路径、**绝对路径**、SHA-256 与可直接粘贴的
  Markdown 链接。交付期读它即可，不必手写路径；无桌面宿主的侧边栏预览限制
  （绝对路径、链接目标不能带 `?`、HTML 页内相对跳转点不动）也写在 `notes` 里。

**边界**：只读 run 内既有产物（`delivery/`、`wechat/`、`batch.json`、
`review/*.json`），不改正文、不产生新事实；`build()` 的每次写入都走
`evidence_write` 留底通道（封存 run 上默认拒绝），并如实记录
`preview/publish-record.json`（发布到主机静态根是**另一个动作**，见
`publish()` 与 `scripts/publish_preview.py`，产物生成与主机交付分离）。

预览页是给 controller 看的**未发布**内部页，页内显式标注
`publication_authorization: not_authorized`。
"""

from __future__ import annotations

import contextlib
import hashlib
import html
import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, quote_from_bytes

from .evidence_write import RunSealedError, write_evidence  # 留底通道（写手清单测试按此识别）
from .runs_guard import SealedWriteBlocked  # 封存 run 的写入护栏（与 RunSealedError 是两道关）

READING_CSS = """
:root{--fg:#1a1a1a;--fg2:#5b5b5b;--bg:#f5f5f3;--card:#fff;--line:#e6e6e2;--accent:#0a58ca}
@media (prefers-color-scheme:dark){:root{--fg:#e8e8e6;--fg2:#a0a0a0;--bg:#141414;--card:#1c1c1c;--line:#2c2c2c;--accent:#7fb0ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC","Microsoft YaHei",sans-serif;
  font-size:17.5px;line-height:1.95;letter-spacing:.01em;-webkit-text-size-adjust:100%}
.bar{position:sticky;top:0;z-index:9;display:flex;flex-wrap:wrap;gap:.9em;align-items:center;
  padding:.55em 1.1em;background:color-mix(in srgb,var(--card) 88%,transparent);
  backdrop-filter:saturate(1.4) blur(8px);border-bottom:1px solid var(--line);font-size:.86em}
.bar a{color:var(--accent);text-decoration:none}
.bar a:hover{text-decoration:underline}
.badge{margin-left:auto;color:var(--fg2);border:1px solid var(--line);border-radius:999px;padding:.05em .7em;white-space:nowrap}
.wrap{max-width:760px;margin:0 auto;padding:2.6em 1.3em 5em}
article{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:2.4em 2.2em 2.8em;
  box-shadow:0 1px 2px rgba(0,0,0,.04)}
h1{font-size:1.55em;line-height:1.4;margin:0 0 .5em;font-weight:700}
.meta{color:var(--fg2);font-size:.8em;line-height:1.7;border-bottom:1px solid var(--line);padding-bottom:1.1em;margin-bottom:1.6em}
.meta code{font-size:.95em;background:transparent;color:inherit}
h2{font-size:1.16em;line-height:1.6;margin:2.1em 0 .7em;padding-left:.6em;border-left:3px solid var(--accent);font-weight:700}
p{margin:1.05em 0;text-align:justify}
p:first-of-type{margin-top:.2em}
footer{color:var(--fg2);font-size:.8em;text-align:center;margin-top:2.2em;line-height:1.9}
@media (max-width:560px){body{font-size:17px}.wrap{padding:1.4em .8em 3em}article{padding:1.6em 1.2em 2em;border-radius:10px}}
@media print{body{background:#fff}.bar,footer{display:none}article{border:0;box-shadow:none;padding:0}.wrap{max-width:none;padding:0}}
"""

INDEX_CSS = """
:root{--fg:#1a1a1a;--fg2:#5b5b5b;--bg:#f5f5f3;--card:#fff;--line:#e6e6e2;--accent:#0a58ca}
@media (prefers-color-scheme:dark){:root{--fg:#e8e8e6;--fg2:#a0a0a0;--bg:#141414;--card:#1c1c1c;--line:#2c2c2c;--accent:#7fb0ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC",sans-serif;line-height:1.8}
.wrap{max-width:820px;margin:0 auto;padding:3em 1.3em 4em}
h1{font-size:1.5em;margin:0 0 .3em}
.sub{color:var(--fg2);font-size:.88em;margin-bottom:2em}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:1.5em 1.6em;margin:0 0 1.2em;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.card h2{margin:0 0 .45em;font-size:1.3em;line-height:1.5}
.card h2 a{color:var(--fg);text-decoration:none;border-bottom:2px solid transparent}
.card h2 a:hover{color:var(--accent);border-bottom-color:var(--accent)}
.hook{color:var(--fg2);font-size:.9em;margin:.2em 0 .9em}
.links{display:flex;flex-wrap:wrap;gap:.6em;margin:.2em 0 .9em}
.links a{display:inline-block;font-size:.85em;text-decoration:none;color:var(--accent);border:1px solid var(--line);border-radius:999px;padding:.18em .8em}
.links a:hover{background:color-mix(in srgb,var(--accent) 10%,transparent)}
.kv{color:var(--fg2);font-size:.78em;line-height:1.9;word-break:break-all}
.kv code{font-size:.95em}
.note{color:var(--fg2);font-size:.8em;border-top:1px solid var(--line);padding-top:1.2em;margin-top:2em;line-height:1.9}
"""


#: 交付链接清单（run 相对路径）；交付期读它取链接，不手写路径。
LINKS_PATH = "preview/links.json"

#: 清单格式版本。生成、失效桩、publish 校验**共用同一个常量**：
#: 此前是三处字面量，`publish` 还不校验版本——读得动就发（2026-09-25 审计）。
LINKS_SCHEMA_VERSION = "preview-links-v1"

#: 发布事实记录（run 相对路径）。它是 run 内的账，**不进发布内容**。
PUBLISH_RECORD_NAME = "publish-record.json"
PUBLISH_RECORD_PATH = f"preview/{PUBLISH_RECORD_NAME}"

#: 同一 run 的并发 build 互斥锁（run 根下的瞬时文件，不是证据）。
#: 放在 run 根而不是 `preview/`：锁若先建目录，首轮构建失败就会留下空的 `preview/`，
#: 而那正是 AGENTS.md 里"本阶段没跑"的信号（独立复核 finding 6）。
LOCK_PATH = ".preview-links.lock"

#: 锁的陈旧阈值：超过它就接管，覆盖"SIGKILL 后 pid 被无关进程复用"（finding 3）。
LOCK_TTL_SECONDS = 10 * 60

#: mtime 落在未来的容忍度：超过它就当锁是陈旧的（时钟回拨 / 拷贝带 -t）。
#: 否则 age 永远为负、TTL 永不触发，run 会被永久锁死（四轮复核 finding 3）。
LOCK_CLOCK_SKEW_TOLERANCE_SECONDS = 60


class LinksBuildInProgress(RuntimeError):
    """已有 preview_site 构建在进行中。

    并发重建会写出互相矛盾的清单（独立复核 finding a-2：B 先写完 complete，A 再覆盖
    页面并死掉 → 清单说 complete，页面却是 A 的旧字节）。宁可报错，不要静默。
    """


def _read_lock(lock: Path) -> dict | None:
    try:
        payload = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:      # 活着但不是我们的进程
        return True
    except (OSError, OverflowError, ValueError):
        # 畸形 pid（如 10**20）会让 os.kill 抛 OverflowError；按"已死"处理以便接管，
        # 而不是让它逃逸成一个没有路径、没有出路的崩溃（六轮复核 minor）
        return False
    return True


def _lock_is_stale(lock: Path, payload: dict | None) -> bool:
    """锁是否可接管（三条判定，顺序有讲究）。

    - 太旧（mtime 超过 TTL）→ 可接管：pid 可能已被无关的长命进程复用（finding 3）；
    - 内容读不懂但**很新** → 不可接管：那正是持有者"已创建、pid 还没落盘"的窗口，
      抢走就是对一个活着的持有者动手（finding 2）；
    - 有 pid 且进程已死 → 可接管。
    """
    try:
        age = time.time() - lock.stat().st_mtime
    except OSError:
        return True
    pid = payload.get("pid") if isinstance(payload, dict) else None
    if isinstance(pid, int) and pid > 0:
        # 先看 pid：**活持有者永不因 mtime 异常被抢占**（五轮复核 major 2——
        # 时钟偏斜不是抢锁的理由，否则第二轮的"清单说 complete、页面却是别人的字节"会回来）
        if not _pid_alive(pid):
            return True
        return 0 <= age and age > LOCK_TTL_SECONDS   # 只有"确实超龄"才接管（pid 复用）
    # 没有可用 pid（读不懂 / 畸形）：很新 → 占用中；超龄 或 mtime 在未来 → 接管
    return age > LOCK_TTL_SECONDS or age < -LOCK_CLOCK_SKEW_TOLERANCE_SECONDS


def _release_lock(lock: Path, handle: int | None) -> None:
    """释放锁，**只删属于自己的那一把**。

    封存 run 里 unlink 会被 runs_guard 抛 `SealedWriteBlocked`（RuntimeError，不是
    OSError）；但那是一次**已经成功**的构建，不能因为释放锁而报错（finding 4）。

    归属校验（2026-09-25 独立审计 P2）：被合法接管后（TTL 到期），原持有者若无条件
    unlink，删掉的是**接管者**的锁，第三个构建随即能拿到锁并与接管者并行写同一个 run。
    读不出归属（空锁 / 坏 JSON）时 fail-closed 不删——陈旧锁另有 TTL 接管路径，
    不依赖这里清理。
    """
    if handle is None:
        return
    with contextlib.suppress(OSError):
        os.close(handle)
    payload = _read_lock(lock)
    if not isinstance(payload, dict) or payload.get("pid") != os.getpid():
        return
    with contextlib.suppress(OSError, SealedWriteBlocked):
        os.unlink(lock)


@contextlib.contextmanager
def _links_build_lock(run_root: Path):
    """同一 run 的 build 互斥；持有者已死或锁太旧则接管。

    锁本身建不出来（例如封存 run 上护栏挡下写锁文件）时**不阻断构建**：封存该由留底
    通道给出它自己的错误，不能因为加锁而改变既有的报错路径。
    """
    lock = run_root / LOCK_PATH
    handle: int | None = None
    try:
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            if not _lock_is_stale(lock, _read_lock(lock)):
                raise LinksBuildInProgress(
                    f"已有 preview_site 构建在进行：{lock}\n"
                    "并发重建会写出互相矛盾的清单。等它结束；若确认进程已死"
                    f"（或锁已超过 {LOCK_TTL_SECONDS // 60} 分钟），删掉这个文件再重试。"
                ) from None
            # 接管：删不掉就**拒绝**，不能悄悄降级成"不加锁"（四轮复核 finding 2：
            # 锁路径是超龄目录时，unlink 抛 IsADirectoryError 曾被宽 except 吞掉，
            # 于是构建在互斥关闭的状态下继续跑）
            try:
                os.unlink(lock)
            except OSError as exc:
                raise LinksBuildInProgress(
                    f"锁已超龄但删不掉（{type(exc).__name__}: {exc}）：{lock}\n"
                    "无法接管——拒绝在无锁状态下构建（先确认没有别的构建在跑，再手工清理该路径）。"
                ) from exc
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.write(handle, json.dumps({"pid": os.getpid()}).encode("utf-8"))
    except LinksBuildInProgress:
        raise
    except SealedWriteBlocked:
        # 封存 run：后面的留底通道写入本来就会拒绝，不因为加锁而改变既有报错路径
        handle = None
    except OSError as exc:
        # 其余建锁失败（只读 run 根 / EACCES…）**拒绝**：否则两个构建会在无锁下并行
        #（五轮复核 minor 3）
        raise LinksBuildInProgress(
            f"无法建立构建锁（{type(exc).__name__}: {exc}）：{lock}\n"
            "拒绝在无锁状态下构建（先修好该路径权限，或确认没有别的构建在跑）。"
        ) from exc
    try:
        yield
    finally:
        _release_lock(lock, handle)


def md_to_html(body: str) -> str:
    """把本项目成稿（H1 + H2 + 段落）渲染为 HTML。

    正文不使用强调/列表/链接语法，因此只处理标题与段落；遇到未知行按普通段落
    处理——渲染失败的方向只能是"退化成段落"，不会丢内容。
    """
    out: list[str] = []
    for block in re.split(r"\n\s*\n", body.strip()):
        line = block.strip()
        if not line:
            continue
        if line.startswith("## "):
            out.append(f"<h2>{html.escape(line[3:].strip())}</h2>")
        elif line.startswith("# "):
            continue
        else:
            out.append("<p>" + html.escape(line).replace("\n", "<br>") + "</p>")
    return "\n".join(out)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_article(run_root: Path, article_id: str) -> dict:
    """读一篇成稿（Markdown 为规范稿），返回渲染所需的全部字段。"""
    delivery = run_root / f"delivery/{article_id}/delivery.md"
    if not delivery.is_file():
        raise FileNotFoundError(f"缺少成稿：{delivery}")
    raw = delivery.read_text(encoding="utf-8")
    title, _, body = raw.partition("\n")
    title = title.lstrip("# ").strip()
    body = body.strip()
    return {
        "article_id": article_id,
        "title": title,
        "body": body,
        "body_html": md_to_html(body),
        "cjk_chars": len(re.findall(r"[\u4e00-\u9fff]", body)),
        "sha256": _sha256(delivery),
    }


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def delivery_status(run_root: Path, batch: dict) -> str:
    """交付状态：content-delivery 优先，缺失时退回 batch 的 gate_status。"""
    record = _load_json(run_root / "review/content-delivery.json")
    if isinstance(record.get("content_status"), str) and record["content_status"]:
        return record["content_status"]
    statuses = {
        str(article.get("gate_status", {}).get("content_fidelity") or "")
        for article in batch.get("articles", [])
        if isinstance(article, dict)
    }
    return "PENDING_L2" if statuses else "UNKNOWN"


def slug(run_root: Path) -> str:
    """主机静态根下的目录名：`<日期>-<run 名>`，如 `2026-09-17-daily-009`。"""
    run_root = Path(run_root).resolve()
    return f"{run_root.parent.name}-{run_root.name}"


def _write(run_root: Path, relative: str, content: str | bytes, reason: str) -> None:
    """run 内写入一律走留底通道（封存 run 上会抛 RunSealedError）。

    run 路径含非 UTF-8 字节时（surrogateescape），页面里内嵌的 run 名也带 surrogate，
    `encode("utf-8")` 会抛——这里按"替换成可见字符"写出，而不是把整个预览步骤炸掉：
    这是本模块既定的降级方向（渲染不出完美版，也不该丢交付）。
    """
    if isinstance(content, bytes):
        payload = content
    else:
        try:
            payload = content.encode("utf-8")
        except UnicodeEncodeError:
            payload = content.encode("utf-8", "replace")
    write_evidence(
        run_root / relative,
        payload,
        run_dir=run_root,
        reason=f"preview_site:{reason}",
    )


def _markdown_label(text: str) -> str:
    """链接标签转义：`[` / `]` / 反斜杠不转义会把 Markdown 链接结构撑破。"""
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _utf8_safe(text: str) -> tuple[str, bool]:
    """把无法用 UTF-8 编码的路径（surrogateescape 字节）换成可见形式。

    返回 `(文本, 是否有损)`。有损时调用方**必须**标注出来：路径里有一个非 UTF-8
    字节，不该让整个预览步骤失败，但也不能假装这个字符串就是原路径。
    """
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return text.encode("utf-8", "replace").decode("utf-8"), True
    return text, False


def _link_unavailable_reason(path: Path) -> str | None:
    """给不出可点链接时说明原因，否则 None。

    前端 `parseFileLink` 的判定是「先切 `#`、查 `?`、**再** decodeURIComponent，
    最后拒控制字符」——所以制表符/换行会被百分号编码成 `%09`/`%0A`，解码回来仍是
    控制字符而被拒。这种路径给不出可点链接，只能如实说明。
    """
    if re.search(r"[\u0000-\u001f\u007f]", str(path)):
        return "path_contains_control_char"
    try:
        str(path).encode("utf-8")
    except UnicodeEncodeError:
        return "path_not_encodable"
    return None


def _markdown_link(label: str, path: Path) -> str | None:
    """生成可直接粘贴的 Markdown 文件链接（绝对路径 + 百分号转义）；给不出时 None。

    前端 `parseFileLink` 先按 `#` 切分、检查 destination 里有没有 `?`，**之后**才
    `decodeURIComponent`——所以空格、`?`、`#`、括号都得转义：否则链接会被当成普通
    链接（点不动），或把路径截断成锚点。
    """
    if _link_unavailable_reason(path) is not None:
        return None
    try:
        target = quote(str(path), safe="/")
    except UnicodeEncodeError:  # 兜底：_link_unavailable_reason 已经先判过一次
        return None
    return f"[{_markdown_label(label)}]({target})"


def _link_entry(run_root: Path, relative: str, label: str) -> dict | None:
    """一个可点开的交付入口；文件不存在时返回 None（清单不记幽灵链接）。

    路径不可点（控制字符 / 非 UTF-8）时 `markdown_link` 给 `null` 并附
    `link_unavailable_reason`：哈希与路径照给，只是别让人以为能点。
    """
    path = run_root / relative
    if not path.is_file():
        return None
    absolute = path.resolve()
    shown, lossy = _utf8_safe(str(absolute))
    reason = _link_unavailable_reason(absolute)
    entry: dict = {
        "path": relative,
        "abs_path": shown,
        "sha256": _sha256(absolute),
        "markdown_link": None if reason is not None else _markdown_link(label, absolute),
    }
    if reason is not None:
        entry["link_unavailable_reason"] = reason
    if lossy:
        entry["abs_path_lossy"] = True
    return entry


def _stale_preview_files(run_root: Path, maintained: set[str]) -> list[str]:
    """`preview/` 里本模块管理、但这一轮不再维护的文件（源已删 / 子集重建）。

    只统计本模块管的产物（顶层 `preview/*.html` 与 `preview/wechat/**`），不碰别的。
    **不删文件**：删除在留底通道里没有语义，而"悄悄不广告、又不说明"会让人以为站点
    干净——所以如实列出来，让复核者与交付者都看得见。
    """
    managed: list[str] = []
    root = run_root / "preview"
    for path in sorted(root.glob("*.html")):
        managed.append(f"preview/{path.name}")
    wechat = root / "wechat"
    if wechat.is_dir():
        for path in sorted(wechat.rglob("*")):
            if path.is_file():
                managed.append(f"preview/wechat/{path.relative_to(wechat).as_posix()}")
    return [relative for relative in managed if relative not in maintained]


def _wechat_source(run_root: Path, article_id: str, suffix: str) -> bool:
    """公众号复制版的**源**是否还在 run 里。

    源没了以后 `preview/wechat/**` 只剩上一轮的陈旧副本：清单不广告它，页面也不再
    链向它——发布到 8899 的站点里相对锚点是能点开的（与侧边栏沙箱不同），
    留着锚点等于把本 run 已经没有的公众号版递给读者（独立复核 finding d）。
    """
    return (run_root / f"wechat/{article_id}{suffix}").is_file()


def _build_links_manifest(
    run_root: Path,
    status: str,
    rendered: list[dict],
    copied: list[str] = (),
) -> dict:
    """交付链接清单：每篇的正文 / 阅读页 /（有则）公众号版的路径、哈希与粘贴链接。

    清单自身**不含时间戳**；但 `index.sha256` 是生成页面的哈希，页面内嵌分钟级生成
    时间，所以跨分钟重建时它会变——这一点写进 `notes`，免得被当成逐字节可复现。
    缺失的入口直接不出现，不用占位符假装存在；`state` 只有 `complete` 才可信
    （构建开始时先写成 `building`，中途失败就不会留下"看起来完整"的旧清单）。
    """
    run_root = Path(run_root)
    run_id_text, run_id_lossy = _utf8_safe(slug(run_root))
    root_text, root_lossy = _utf8_safe(str(run_root.resolve()))
    payload: dict = {
        "schema_version": LINKS_SCHEMA_VERSION,
        "state": "complete",
        "run_id": run_id_text,
        "run_root": root_text,
        "content_status": status,
        "publication_authorization": "not_authorized",
        "notes": [
            "链接必须用绝对路径：相对路径按会话工作区根解析（dsh 默认 /home/allen/dsh），"
            "run 在项目目录下，相对链接会解析到错误位置。",
            "侧边栏 HTML 预览是 sandbox + blob: iframe，页内相对跳转点不动；"
            "单篇请直接给 articles[].reading.markdown_link。",
            "本清单是内部预览入口，不是发布授权（publication_authorization: not_authorized）。",
            "index.sha256 是生成页面的哈希：index.html 内嵌分钟级生成时间，"
            "因此跨分钟重建时 index.sha256（进而本文件的字节）会变；清单自身不含时间戳。",
            "只信 state=complete；构建中途失败时本文件会被改写成 state=building，"
            "这时旧哈希已失效，请重跑 preview_site 阶段。",
        ],
        "index": _link_entry(run_root, "preview/index.html", f"{run_id_text} · 目录页"),
        "articles": [],
    }
    if root_lossy:
        payload["run_root_lossy"] = True
    if run_id_lossy:
        payload["run_id_lossy"] = True

    # 本轮实际维护的产物（含原样搬进来的公众号复制版），用于声明陈旧文件
    maintained: set[str] = set(copied)
    if payload["index"] is not None:
        maintained.add("preview/index.html")

    for art in rendered:
        aid = art["article_id"]
        title = art["title"]
        entry: dict = {
            "article_id": aid,
            "title": title,
            "cjk_chars": art["cjk_chars"],
            "body_md": _link_entry(run_root, f"delivery/{aid}/delivery.md", f"{title} · 正文"),
            "reading": _link_entry(run_root, f"preview/{aid}.html", f"{title} · 阅读页"),
        }
        if entry["reading"] is not None:
            maintained.add(f"preview/{aid}.html")
        for slot, suffix, relative, label_suffix in (
            ("wechat_copy", ".html", f"preview/wechat/{aid}.html", "公众号复制版"),
            ("wechat_fragment", ".wx.html", f"preview/wechat/{aid}.wx.html", "公众号片段"),
        ):
            # 源已不在 run 里就不再广告：留着的只是上一轮的陈旧副本，
            # 给出去等于让人贴一个本 run 已经没有的公众号版（列进 stale_preview_files）
            if not _wechat_source(run_root, aid, suffix):
                continue
            found = _link_entry(run_root, relative, f"{title} · {label_suffix}")
            if found is not None:
                entry[slot] = found
                maintained.add(relative)
        payload["articles"].append(entry)

    payload["stale_preview_files"] = _stale_preview_files(run_root, maintained)
    return payload


def _building_stub(run_root: Path) -> str:
    """`state != complete` 的清单桩：只要它在，交付期就不该信这份清单。"""
    return json.dumps(
        {
            "schema_version": LINKS_SCHEMA_VERSION,
            "state": "building",
            "run_id": slug(run_root),
            "note": "本轮 preview_site 正在重建；state 不为 complete 时清单不可信。",
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def _invalidate_links_manifest(run_root: Path) -> None:
    """让上一轮的清单先失效（独立复核 finding 1/a）。

    必须在**任何**可能失败的步骤之前调用：`read_article`（成稿缺失 / 非 UTF-8 /
    权限 / 成稿变目录）与 `batch.json` 畸形都会在第一阶段抛，若那时清单还是
    `complete`，交付期就会拿到指向已消失文件的哈希——这正是"看起来完整"的旧清单。
    构建开始时先写成 `building`，中途失败就不会留下可信的旧清单。
    """
    # 没有清单就直接返回，**除非** `preview/index.html` 已经在：那是 links.json 之前的
    # 旧版产物形态（daily-009 / daily-010 实测就是"有 index.html、没有 links.json"），
    # 而 publish() 把"没有清单"当旧 run 放行。不给它落桩的话，这次 rebuild 若在写第一页
    # 之前失败（read_article / 空 ids），磁盘上会留下一份**可发布**的陈旧站点（复核 F7）。
    if not (run_root / LINKS_PATH).is_file() and not (run_root / "preview/index.html").is_file():
        return
    _write(run_root, LINKS_PATH, _building_stub(run_root), "links-invalidated")


def build(run_root: str | Path, *, articles: list[str] | None = None) -> dict:
    """生成 `preview/` 站点（幂等；重复生成会覆盖并留底）。

    先让上一轮清单失效，再在并发锁内构建——失败不会留下"看起来完整"的旧清单。

    :param run_root: run 根目录。
    :param articles: 要渲染的 article_id；默认取 `batch.json` 的 articles 顺序。
    :returns: 摘要（页面路径、每篇 CJK 数与哈希、交付状态）。
    """
    run_root = Path(run_root)
    # 先拿锁、再失效清单：加锁失败（并发 / 僵尸锁）不能把上一份好的 complete 清单
    # 打成 building——那会让 run 既编不了又发不出去（独立复核 finding 3）。
    with _links_build_lock(run_root):
        _invalidate_links_manifest(run_root)
        return _build_locked(run_root, articles=articles)


def _build_locked(run_root: Path, *, articles: list[str] | None = None) -> dict:
    """`build()` 的实际构建体（调用方已失效旧清单并持有并发锁）。"""
    run_root = Path(run_root)
    batch = _load_json(run_root / "batch.json")
    ids = articles or [a["article_id"] for a in batch.get("articles", []) if isinstance(a, dict) and a.get("article_id")]
    if not ids:
        raise ValueError(f"batch.json 未给出 articles：{run_root / 'batch.json'}")
    hooks = {
        a["article_id"]: a.get("review_hook", "")
        for a in batch.get("articles", [])
        if isinstance(a, dict) and a.get("article_id")
    }
    final = _load_json(run_root / "review/final-review.json")
    status = delivery_status(run_root, batch)
    rendered = [read_article(run_root, aid) for aid in ids]

    # 旧清单的失效已在 build() 里、任何可能失败的步骤之前完成（复核 finding 1/a）
    #
    # 首轮构建（此前根本没有清单）要补一个 building 桩：`_invalidate_links_manifest`
    # 对不存在的清单直接早退，而 `publish()` 把"没有清单"当早于本产物的旧 run 兼容，
    # 于是"写了第一页之后才失败"会留下一个**可发布**的半成品站点（2026-09-25 审计）。
    # 放在这里（前置条件都过了、还没写任何页面）而不是更早：更早的失败
    # （batch.json 畸形 / 成稿读不出来）仍不该产生 `preview/`，那是"本阶段没跑"的信号。
    if not (run_root / LINKS_PATH).is_file():
        _write(run_root, LINKS_PATH, _building_stub(run_root), "links-building-stub")

    # 1) 公众号复制版原样搬进站点（缺失时只记录，不阻断）
    copied: list[str] = []
    for relative in ("wechat/index.html", "wechat/manifest.json"):
        src = run_root / relative
        if src.is_file():
            _write(run_root, f"preview/{relative}", src.read_bytes(), f"copy:{relative}")
            copied.append(f"preview/{relative}")
    for art in rendered:
        for suffix in (".html", ".wx.html"):
            relative = f"wechat/{art['article_id']}{suffix}"
            src = run_root / relative
            if src.is_file():
                _write(run_root, f"preview/{relative}", src.read_bytes(), f"copy:{relative}")
                copied.append(f"preview/{relative}")

    # 2) 目录页：标题即链接
    cards: list[str] = []
    for art in rendered:
        aid = art["article_id"]
        hook = html.escape(hooks.get(aid, ""))
        # 公众号入口只在源还在时给：源删了以后 preview/wechat/** 只是上一轮的陈旧副本，
        # 页面（以及发布到 8899 的站点，那里相对锚点是能点开的）不能再链向它（复核 finding d）
        card_links = [f'<a href="{aid}.html">阅读</a>']
        if _wechat_source(run_root, aid, ".html"):
            card_links.append(f'<a href="wechat/{aid}.html">公众号复制版（点「复制全文（含样式）」）</a>')
        if _wechat_source(run_root, aid, ".wx.html"):
            card_links.append(f'<a href="wechat/{aid}.wx.html">复制片段 HTML</a>')
        cards.append(
            f"""<div class="card">
  <h2><a href="{aid}.html">{html.escape(art['title'])}</a></h2>
  {f'<p class="hook">最强钩子：{hook}</p>' if hook else ''}
  <div class="links">
    {"".join(card_links)}
  </div>
  <div class="kv">article_id <code>{aid}</code> · CJK <code>{art['cjk_chars']}</code> ·
  sha256 <code>{art['sha256'][:16]}…</code> · content_status <code>{html.escape(status)}</code></div>
</div>"""
        )
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    finals = " · ".join(
        f"{key} <code>{html.escape(str(final.get(key)))}</code>"
        for key in ("content_result", "evidence_result", "governance_result", "verdict")
        if final.get(key) is not None
    )
    index = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>日更文章预览 · {html.escape(slug(run_root))}</title>
<style>{INDEX_CSS}</style></head><body><div class="wrap">
<h1>日更文章预览 · {html.escape(slug(run_root))}</h1>
<p class="sub">{len(rendered)} 篇 Markdown 成稿；内容栏 <strong>{html.escape(status)}</strong>。<strong>点标题即读</strong>。</p>
{''.join(cards)}
<div class="note">
{f'终审：{finals}<br>' if finals else ''}
publication_authorization: <code>not_authorized</code> —— 本页仅供预览与人工签署，系统未发布、未推送。<br>
页面生成：{generated}（源：<code>runs/{html.escape(slug(run_root))}/</code>）
</div></div></body></html>"""
    _write(run_root, "preview/index.html", index, "index")

    # 3) 阅读页
    for art in rendered:
        aid = art["article_id"]
        # 公众号入口只在源还在时给（同 finding d：陈旧副本不能再链）
        bar_wechat = (
            f'  <a href="wechat/{aid}.html">公众号复制版</a>\n'
            if _wechat_source(run_root, aid, ".html")
            else ""
        )
        page = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(art['title'])}</title>
<style>{READING_CSS}</style></head><body>
<div class="bar">
  <a href="index.html">← 返回目录</a>
{bar_wechat}  <span class="badge">内部预览 · 未发布 · {html.escape(status)}</span>
</div>
<div class="wrap"><article>
<h1>{html.escape(art['title'])}</h1>
<div class="meta">{aid} · CJK {art['cjk_chars']} 字 · sha256 <code>{art['sha256'][:16]}…</code> ·
run <code>{html.escape(slug(run_root))}</code></div>
{art['body_html']}
</article>
<footer>publication_authorization: not_authorized · 本页为交付前内部预览</footer>
</div></body></html>"""
        _write(run_root, f"preview/{aid}.html", page, f"article:{aid}")

    # 4) 交付链接清单：交付期直接读它，不再手写路径（2026-09-24）
    links = _build_links_manifest(run_root, status, rendered, copied)
    _write(
        run_root,
        LINKS_PATH,
        json.dumps(links, ensure_ascii=False, indent=2) + "\n",
        "links",
    )

    return {
        "status": "ok",
        "run_id": slug(run_root),
        "content_status": status,
        "index_path": "preview/index.html",
        "index_sha256": _sha256(run_root / "preview/index.html"),
        "links_path": LINKS_PATH,
        "links_sha256": _sha256(run_root / LINKS_PATH),
        "articles": [
            {"article_id": a["article_id"], "title": a["title"], "cjk_chars": a["cjk_chars"], "sha256": a["sha256"]}
            for a in rendered
        ],
        "copied": copied,
        "publication_authorization": "not_authorized",
    }


def publish(
    run_root: str | Path,
    root: str | Path,
    *,
    name: str | None = None,
    base_url: str | None = None,
) -> dict:
    """把 `preview/` 复制到主机静态根下（交付动作，产物生成之外的独立一步）。

    只复制、不改 run 内产物；落地页必须在 `root` 之内（越界即拒绝，fail-closed）。
    发布事实（时间、目标、哈希）记进 `preview/publish-record.json`（走留底通道）。
    """
    run_root = Path(run_root).resolve()
    source = run_root / "preview"
    if not (source / "index.html").is_file():
        raise FileNotFoundError(f"预览页尚未生成：{source / 'index.html'}（先运行 build()）")
    # 半成品站点不许发布（独立复核 finding b）：build 中止时清单是 state=building，
    # 但页面与陈旧副本都在磁盘上；publish() 只看 index.html 在不在，会把半成品拷进
    # 静态根——`scripts/publish_preview.py --no-build` 这条路径正好能走到。
    # 没有清单的旧 run 仍然允许（向后兼容）；但**坏清单不能当成"没有清单"放行**——
    # 截断的 JSON 正是写一半被打断（SIGKILL / ENOSPC）留下的形态，而它恰好会绕过这道
    # 门（独立复核 finding 1）。读不出、不是对象、state 不对，一律拒绝。
    manifest_path = source / "links.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"preview/links.json 读不出或解析不了（{type(exc).__name__}: {exc}）："
                "拒绝发布——损坏的清单与 state!=complete 同等对待。"
                f"若页面本身是好的：重跑 preview_site 阶段，或删掉 {manifest_path} 再用 --no-build 发布"
            ) from exc
        if not isinstance(manifest, dict):
            raise ValueError(
                f"preview/links.json 不是对象（{type(manifest).__name__}）：拒绝发布"
            )
        if manifest.get("state") != "complete":
            raise ValueError(
                f"preview/links.json state={manifest.get('state')!r}：上一轮 build 中止，"
                f"拒绝发布半成品站点（先重跑 preview_site 阶段，或删掉 {manifest_path} 再 --no-build）"
            )
        if manifest.get("schema_version") != LINKS_SCHEMA_VERSION:
            # 版本是契约的一部分：读得动不等于读得懂（2026-09-25 审计 finding R1）。
            raise ValueError(
                f"preview/links.json schema_version={manifest.get('schema_version')!r}，"
                f"本版本只认 {LINKS_SCHEMA_VERSION!r}：拒绝发布——清单格式不认识时，"
                "里面的路径与哈希都不保证语义正确（先重跑 preview_site 阶段）"
            )
    destination_root = Path(root).expanduser().resolve()
    if not destination_root.is_dir():
        raise NotADirectoryError(f"静态根不存在：{destination_root}")
    target = (destination_root / (name or slug(run_root))).resolve()
    if destination_root != target and destination_root not in target.parents:
        raise ValueError(f"发布目标越界：{target} 不在 {destination_root} 之内")

    if target.exists():
        shutil.rmtree(target)
    # 发布记录本身不是交付物：它含绝对宿主路径与文件清单，而 8899 是内网可访问的
    # （2026-09-25 审计 finding R5：第二次发布会把上一次写的记录一起拷进静态根）。
    def _skip_publish_record(directory: str, names: list[str]) -> list[str]:
        if Path(directory) == source:
            return [name for name in names if name == PUBLISH_RECORD_NAME]
        return []

    shutil.copytree(source, target, ignore=_skip_publish_record)
    pages = sorted(p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file())
    base = (base_url or "").rstrip("/")
    # 路径里有非 UTF-8 字节时，落盘只能写有损形式；那就让**返回值与落盘值一致**并显式
    # 标注（复核 finding c：此前返回真值、落盘写 `?`，而 AGENTS.md 又说以记录为准）。
    root_text, root_lossy = _utf8_safe(str(run_root))
    static_text, static_lossy = _utf8_safe(str(destination_root))
    target_text, target_lossy = _utf8_safe(str(target))
    # URL 段按**磁盘真实字节**百分号编码：有损显示里的 `?` 若直接进 URL 会变成查询串
    # 起点，把链接导到另一个路径（独立复核 finding 5）。普通 ASCII 名不受影响。
    url_name = quote_from_bytes(os.fsencode(target.name))
    record = {
        "schema_version": "preview-publish-v1",
        "published_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_root": root_text,
        "static_root": static_text,
        "target": target_text,
        "base_url": base,
        # 不可服务的 URL 就不给（四轮复核 finding 4）：8899 后端是
        # `python -m http.server`，其 unquote() 会把 `%FF` 解成 U+FFFD → 必然 404。
        # 给出一个没人能打开的链接比诚实地留空更糟。
        "index_url": None if target_lossy else (f"{base}/{url_name}/" if base else f"{url_name}/"),
        "files": pages,
        "index_sha256": _sha256(target / "index.html"),
        "publication_authorization": "not_authorized",
    }
    if root_lossy or static_lossy or target_lossy:
        record["path_repr_lossy"] = True
    try:
        _write(run_root, PUBLISH_RECORD_PATH, json.dumps(record, ensure_ascii=False, indent=2) + "\n", "publish-record")
    except (RunSealedError, SealedWriteBlocked):
        # 封存 run 不允许再写记录：发布本身仍可完成，但如实标注未记账。
        # 两道关都要接住（独立复核 finding 6）：
        # - RunSealedError 来自 evidence_write 的 sealed_reason 检查（能解析的 SEALED）；
        # - SealedWriteBlocked 来自 runs_guard 的审计钩子，按"SEALED 文件存在"判定——
        #   `touch SEALED` 这类不可解析的标记会让前者判"未封存"、后者照样拦，
        #   旧代码只捕前者，于是 copytree 已经发布、异常却逃出去，CLI 报失败且无 run 侧记录。
        record["record_error"] = "run_sealed_publish_record_not_written"
    return record


__all__ = [
    "READING_CSS",
    "INDEX_CSS",
    "LINKS_PATH",
    "md_to_html",
    "read_article",
    "delivery_status",
    "slug",
    "build",
    "publish",
]
