"""发布前审补充层（yuwen-publish-precheck）—— **advisory only**。

这一层把第三方 skill「发布前审」接进文章组流水线，只做一件事：**发布前词面预检 + 官方
规则索引**，产出"哪里值得看"的复核候选，交给独立只读复核做语义判定。

为什么是补充层而不是门禁（照抄 `third_party/yuwen-publish-precheck/VENDOR.md` 的边界）：

- 上游自己写明：**词面命中不等于违规，零候选不等于安全**；判定靠 LLM 语义判。
  一个由被检产物自己跑的 LLM 判定，按项目 `AGENTS.md` §7 就是自述式门禁，历史上栽过。
- 所以本模块：不产出 PASS/FAIL、不阻断 run、**不构成任何发布授权**（记录里
  `gate_effect: "none"` / `authorizes_publication: false` / `publication_authorization: "not_authorized"`）。
- 候选数量、严重度**永不**影响退出码；只有"扫描器不可用或没扫全"才让 CLI 非零退出。
  这条是防"扫描失败被当成干净"的唯一机制，改代码时不许放宽。

**稿件怎么找**（两种版式都要认，否则补充层"接上了但永远不开火"）：

1. 现行 pilot 版式（`runs/2026-10-*` 全是这种）：正文 `<run>/draft.md`，稿件 id 取
   `pilot-manifest.json` 的 `case_id`，退化到 run 目录名；标题包 `<run>/title-pack.json`
   的 `selected_title` 字符串；
2. 早期 daily/controlled 版式：`<run>/drafts/<aid>/body_draft.md`（跳过 `.before/` 这类
   点目录），标题包 `<run>/review/<aid>/title-pack.json` 的 `directions[].selected`。

两种都在时以 `drafts/` 为准，不重复扫。

**"没扫成"必须显形**（2026-10-15 独立复核 L2-01/02/03/05 实测推翻了初版）：以下情形
一律不报 `ran`，也一律不报 0 命中：

- 缺 vendor、缺我们的规则目录、无稿件、声明关闭 → `not_run` + 原因；
- 官方词表哈希与 `VENDOR.sha256` 不符、词表为空、scan 退出非零/输出非 JSON/超时 → `error`；
- **正文扫到了但标题子扫描失败** → 该篇 `partial`，`scanned` 不含它，`errors` 记原因；
- 部分篇目失败 → 顶层 `partial`。

数据与代码分离：

- vendor（只读，可整目录升级）：`third_party/yuwen-publish-precheck/`
- 我们的规则与沉淀（tracked）：`references/publish-precheck/`

调用时把 vendor 的 `scripts/`（`scan.py` + `terms.json`）复制进一个临时工作目录、把我们的
规则目录挂成它的 `data/`，于是 `scan.py` 读到我们的词库，而 vendor 一个字节不改。
用 `ARTICLE_GROUP_PUBLISH_PRECHECK_DIR` / `ARTICLE_GROUP_PUBLISH_PRECHECK_DATA` 可覆盖两个路径。

run 内声明（可选，放 run 根 `publish-precheck.json`）::

    {"enabled": true, "commercial": true, "industries": ["medical"],
     "articles": {"art-001": "drafts/art-001/body_draft.md"}}

没声明 `commercial` 时按上游硬规则**从严**取 `true`（漏套用商业规则是漏判），并记
`options.commercial_source = "default_strict"`。声明的 `article_id` 与稿件路径都做
**白名单 + run 内包含性**校验（L2-04：未校验时实测可把逐篇报告写到 run 根之外）。

CLI::

    uv run python -m article_group.publish_precheck --run-root runs/…/daily-009   # 只打印
    uv run python -m article_group.publish_precheck --run-root … --write          # 落 run 证据（走封存守门）
    uv run python -m article_group.publish_precheck --file 草稿.md --no-commercial

退出码只表达"扫描器状态"，不表达"内容有没有问题"：

``0``
    跑完（含 0 候选、含 critical 候选），或"没什么可扫"的良性 `not_run`
    （`no_articles_to_scan` / `disabled_by_declaration`）。
``1``
    没跑成。含 `error`、`partial`（有篇目没扫全），以及**非良性** `not_run`
    （缺 vendor / 缺规则目录等扫描器不可用情形）——未知原因**默认非零**（fail-closed）。
    此时 stderr 一定给出原因，且措辞明确"不是通过"。

**候选数量与严重度永不改变退出码。**
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Callable

SCHEMA_VERSION = "publish-precheck-advisory-v1"
SKILL_ID = "yuwen-publish-precheck"
SKILL_DIR_ENV = "ARTICLE_GROUP_PUBLISH_PRECHECK_DIR"
DATA_DIR_ENV = "ARTICLE_GROUP_PUBLISH_PRECHECK_DATA"
DECLARATION_NAME = "publish-precheck.json"
GATE_RECORD_PATH = "review/gates/publish-precheck-advisory.json"

# 上游硬规则：用户没说清是否商业 → 按有商业从严处理（漏套用商业规则是漏判）。
DEFAULT_COMMERCIAL = True
COMMERCIAL_SOURCES = ("declaration", "cli", "default_strict")

# 声明文件只认这几个键；其余（如伪造的 "pass"）不回显，只列进 ignored（L2-07）。
DECLARATION_KEYS = ("enabled", "commercial", "industries", "articles")

# article_id 进写路径（review/<id>/…），必须白名单（L2-04）。
ARTICLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# 原因串长度上界（L2R4-07：`reason` 必须定形，不许随 vendor 回溯行数变化）。
_REASON_MAX = 160
# 清单条目路径长度上界（L2R7-03：实测 1,000,002 字符的路径会原样进 missing[]/reason）。
_MANIFEST_ENTRY_MAX = 512
# article_id 长度上界（L2R11-06：id 会进写路径与记录，超长 id 让记录形状不稳）。
_ARTICLE_ID_MAX = 128
# `articles` 键"缺席"与"显式 null"的区分哨兵（L2R11-01）。
_MISSING_ARTICLES = object()

# 良性 not_run：确实没什么可扫，不是扫描器坏了 → 允许 0 退出。其余一律非零。
BENIGN_NOT_RUN_REASONS = frozenset({"no_articles_to_scan", "disabled_by_declaration"})

SEVERITY_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}

# 我的规则库里的级别是「高/中/低」，映射到与官方同一套分诊词。
MY_LEVEL_RANK = {"高": 2, "中": 1, "低": 0}

ADVISORY_NOTE = (
    "本层只做词面预检，产出复核候选与官方规则索引；不出 PASS/FAIL、不阻断 run、"
    "不构成任何发布授权。候选必须交独立只读复核做语义判定（词面命中≠违规，零候选≠安全）。"
)
KNOWN_PLATFORM_GAP = (
    "上游只有抖音/小红书/微信视频号三份 platform 规则包，微信公众号与今日头条无专属包；"
    "本层结论只覆盖 rules-common/rules-commercial 通用层。"
)

WriteFn = Callable[[str, object], None]

_COMMIT_RE = re.compile(r"固定 commit\D*([0-9a-f]{40})")


# --------------------------------------------------------------------------- paths


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_dir(env_name: str, fallback: Path) -> Path:
    override = os.environ.get(env_name, "").strip()
    if override:
        return Path(override).expanduser()
    return fallback


def skill_dir() -> Path:
    """vendor 的 skill 根目录（只读）。"""
    return _resolve_dir(SKILL_DIR_ENV, repo_root() / "third_party" / SKILL_ID)


def rules_data_dir() -> Path:
    """我们自己的 `data/`（tracked）：my-rules.md / wordlists / cases / history。"""
    return _resolve_dir(DATA_DIR_ENV, repo_root() / "references" / "publish-precheck")


def _rel(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(repo_root()))
    except (ValueError, OSError):
        return str(path)


def _sha256_file(path: Path) -> str:
    """文件字节 sha256；**非普通文件一律返回空串**（判型靠 `stat`，绝不 `open()`）。

    L2R10-03：L2R9-02 只在 `vendor_identity` 那个调用点加了判型 —— 可"读文件"这件事
    本身就发生在这两个底层原语里（`read_bytes()` / `read_text()` 都是 `open()`）。于是
    只要别处还有一个非普通文件（FIFO / 设备节点 / 目录），照样永久阻塞。守卫下沉到
    原语这一层，"会不会挂死"就不再取决于每个调用点是否记得先判型。
    """
    try:
        target = Path(path)
        if not target.is_file():
            return ""
        return hashlib.sha256(target.read_bytes()).hexdigest()
    except (OSError, ValueError):
        return ""


def _read_text(path: Path, *, base: Path | None = None) -> tuple[str | None, str]:
    """读 UTF-8 文本，**任何**故障都转成 ``(None, reason)``，绝不抛。

    L2R2-01：初版在六处裸用 ``path.read_text(encoding="utf-8")``，只按 `OSError` 兜底。
    于是非 UTF-8 的正文/声明/标题包/词表抛未捕获 `UnicodeDecodeError`，路径含 NUL 抛
    `ValueError`，CLI 直接吐裸回溯、rc=1 且 stdout 空 —— 与 docstring 承诺的
    "任何故障都落成 status=error / not_run" 正面矛盾。

    L2R3-06：原因串里的路径原先一律走 `_rel()`（仓库相对；仓库外退化成绝对路径），
    而同一份记录里 `body_path` 走 `_run_relative()`（run 相对）—— 同一个文件两个基准，
    复核者按 `body_path` 的串去 grep `reason` 找不到。`base` 给了就与调用方同基。

    返回值第二项是**稳定可读的原因串**（不含路径外内容），供记录与复核追溯。

    L2R10-03：先 `stat` 判型再读 —— 非普通文件（FIFO / 目录 / 设备）一律不 `open()`。
    没有 `is_file()` 时，`open()` 一个无写端的 FIFO 会**永久阻塞**：这种失败形态既不是
    `error` 也不是 `not_run`，而是整轮门禁挂死（第 8、9、10 轮各在**不同读点**复现过一次）。
    "文件缺失"仍保留原来的 `unreadable:…:FileNotFoundError`，好让既有原因串不变。
    """
    where = _run_relative(path, base) if base is not None else _rel(path)
    target = Path(path)
    try:
        if not target.exists():
            return None, f"unreadable:{where}:FileNotFoundError"
        if not target.is_file():
            return None, f"not_a_file:{where}"
    except OSError as exc:
        return None, f"unreadable:{where}:{type(exc).__name__}"
    try:
        return target.read_text(encoding="utf-8"), ""
    except UnicodeDecodeError:
        return None, f"not_utf8:{where}"
    except (OSError, ValueError) as exc:
        return None, f"unreadable:{where}:{type(exc).__name__}"


def _reason_detail(*parts: Any) -> str:
    """把任意文本/异常压成**单行、有界、无控制字符**的原因串（L2R4-07）。

    `reason` 是机器消费的字段（如 `scan_exit_<rc>:…`）。初版把 vendor 的多行回溯原样
    拼进去，字段形状随回溯行数变化，也没有长度上界；调用方无法用固定模式匹配。

    L2R5-03：截断会**改名**——两类故障若前 `_REASON_MAX` 个字符相同、差异在第 160 字符之后，
    初版会把它们塌成逐字相同的 `reason`。所以被截断时补 `…+<8 位摘要>`：长度仍 ≤
    `_REASON_MAX`，但"同一前缀的两类故障"不再同名。未被截断的串一字不改，既有测试不受影响。
    """
    text = " ".join(str(part) for part in parts if part not in (None, ""))
    text = "".join(char if char.isprintable() else " " for char in text)
    text = " ".join(text.split())
    if not text:
        return "no_detail"
    if len(text) > _REASON_MAX:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
        return text[: _REASON_MAX - len(digest) - 2] + "…+" + digest
    return text


#: 公开别名：宿主侧（`article_group/run_gates.py` 的接线）必须用**同一把尺子**压原因串，
#: 否则 vendor 回溯会从门禁层原样漏进 run 级记录（L2R11-08）。
bounded_reason_detail = _reason_detail


def _stdout_snippet(stdout: str, *, limit: int = 80) -> str:
    """坏输出的取证摘要：**整段** stdout 压成单行后限长，超限补 8 位摘要（L2R6-03）。

    L2R5-03 只取了"首个非空行"：两次坏输出首行相同、次行不同时，`reason` 与 `errors`
    逐字节相同（46 字符，够短所以截断摘要分支根本不触发）—— 两类故障又塌成同一名字。
    现在摘要长度由**整段** stdout 决定（不只是首行），超限就带全段摘要。
    """
    collapsed = " ".join((stdout or "").split())
    if not collapsed:
        return "<空 stdout>"
    if len(collapsed) > limit:
        digest = hashlib.sha256(collapsed.encode("utf-8")).hexdigest()[:8]
        return collapsed[: limit - len(digest) - 2] + "…+" + digest
    return collapsed


def _within(path: Path, root: Path) -> bool:
    """``path`` 解析后是否落在 ``root`` 内（L2-04：声明可越界的唯一防线）。"""
    try:
        return Path(path).resolve().is_relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False


def _body_kind_problem(path: Path, root: Path) -> str:
    """``""`` = "run 内的普通文件，可以读"；否则给拒绝原因（**不含路径**）。

    L2R8 家族（第 8 轮，1 major + 3 minor）：前七轮修的都是"**路径**越界"与"**内容**读不出来"，
    而"**根本不是普通文件**"这条一直漏着，四个分支口径还不一致 ——
    - 声明版式的正文：直接 `read_text()`（= `open()`）。指向 **FIFO** 且没有写端时 `open()`
      **永久阻塞**；`run_gates` 是 inline 调用且只 `except Exception`，于是**整轮门禁挂死**
      （第 8 轮实测 `timeout 6` → rc=124，无任何输出）。同一条 FIFO 走 pilot 分支却是
      立刻 `body_not_file` —— 所以是"漏了一个分支"，不是"没法判"。
    - drafts 版式：`if not path.is_file(): continue` 把 FIFO / 悬空软链 / 目录**静默丢掉**；
      若那是唯一一篇，记录降级成良性 `no_articles_to_scan` + rc=0。
    - 声明文件自己（`publish-precheck.json` 是目录或悬空软链）→ 被当成"没声明"，
      范围反而**放大**成扫全部 `drafts/*`。
    - `pilot-manifest.json` / `title-pack.json` 同类：静默退化成"没有 manifest / 没有标题包"。

    判据顺序要紧：先 `is_symlink()`（悬空软链的 `exists()` 是 False，会被误当成"没有"），
    再 `exists()`（真没有 vs 有东西），再 `is_file()`（FIFO / 目录 / 设备），最后 `_within()`
    （软链指向 run 外）。**四步全是 `stat`，一次都不 `open`** —— 这正是 FIFO 不会再挂的原因。
    """
    # 越界排在最前：`../../outside` 这类**不存在**的逃逸路径若先判存在性，会被报成
    # `missing`（"文件没了"），把"声明想写到 run 外"这个安全信号说成"文件缺失"。
    # `_within()` 内部是 `resolve()`，对不存在的路径也按字面解析，所以这里判得准。
    if not _within(path, root):
        return "path_escape"
    if path.is_symlink() and not path.exists():
        return "dangling_symlink"
    if not path.exists():
        return "missing"
    if not path.is_file():
        return "not_a_file"
    return ""


def safe_article_id(article_id: str) -> bool:
    """id 会被拼进 ``review/<id>/…`` 写路径，必须白名单且不含 ``..``。

    L2R11-06：白名单原本不限长 —— 一个几万字符的 id 仍会进写路径与记录（形状不稳）。
    """
    text = str(article_id)
    if len(text) > _ARTICLE_ID_MAX:
        return False
    return bool(ARTICLE_ID_RE.match(text)) and ".." not in text


# --------------------------------------------------------------------------- identity


def vendor_identity(skill: str | Path | None = None) -> dict[str, Any]:
    """记录本次扫描用的是哪一版 vendor + 哪份官方词表（报告可逐字复现）。

    L2R9-02（major）：这里原先直接 `_sha256_file(root/'scripts'/name)` —— 而 `_sha256_file`
    是 `open()` 分块读。**一个 FIFO（或设备节点）会让它永久阻塞**，而且这是**生产路径**
    （`build_publish_precheck_advisory` → `run_gates` → 日更流水线，不需要任何人敲 CLI）。
    `verify_vendor_manifest()` 有 `is_file()` 守卫，这条当时是唯一漏网的读点 —— 第 10 轮
    证明"唯一"是错的（`verify_terms_table` 与 CLI 上还有同类读点，L2R10-03），所以判型
    已经下沉到 `_sha256_file` / `_read_text` 两个 IO 原语；这里保留显式判型是为了给出
    **精确到文件**的原因串。现在先 `stat` 判型（绝不对非普通文件 `open()`），问题串随
    vendor 一起回传，由调用方升级成显式 `error`（fail-closed，且不再有"挂死"这种失败形态）。
    """
    root = Path(skill) if skill is not None else skill_dir()
    commit = ""
    vendor_md = root / "VENDOR.md"
    if vendor_md.is_file():
        match = _COMMIT_RE.search(vendor_md.read_text(encoding="utf-8", errors="replace"))
        if match:
            commit = match.group(1)
    problems: list[str] = []
    digests: dict[str, str] = {}
    for name in ("scan.py", "terms.json"):
        path = root / "scripts" / name
        kind = ""
        if path.is_symlink() and not path.exists():
            kind = "dangling_symlink"
        elif not path.exists():
            kind = "missing"
        elif not path.is_file():
            kind = "not_a_file"
        if kind:
            problems.append(f"{kind}:scripts/{name}")
        else:
            digests[name] = _sha256_file(path)
    return {
        "skill_id": SKILL_ID,
        "skill_dir": _rel(root),
        "commit": commit,
        "scan_sha256": digests.get("scan.py", ""),
        "terms_sha256": digests.get("terms.json", ""),
        # 非空即表示 vendor 读点有"存在但不是普通文件 / 缺失"（调用方必须降级成 error）
        "problem": f"vendor_{problems[0]}" if problems else "",
    }


def verify_terms_table(skill: str | Path | None = None) -> dict[str, Any]:
    """官方词表必须**哈希对得上清单、且非空**，否则这一层没资格报"已扫"（L2-03）。

    初版只算 `terms_sha256` 却从不比对：`terms.json` 换成合法 JSON 的空表，照样
    `status=ran` + 0 候选 + 无告警，还带着一个看起来可复现的哈希。
    """
    root = Path(skill) if skill is not None else skill_dir()
    terms_path = root / "scripts" / "terms.json"
    # L2R10-03：这是 `terms.json` 的**第二个**读点（L2R9-02 只修了 `vendor_identity` 那一处）。
    # 实测 FIFO 在这里挂死（signal 14）。判型已下沉到 IO 原语，但这里仍显式给**精确**原因：
    # 没有它就只能得到"哈希对不上"这种含糊信号，读不出来 ≠ 内容被改。
    kind = _body_kind_problem(terms_path, root)
    if kind and kind != "missing":
        return {
            "sha256": "",
            "expected_sha256": "",
            "terms_count": 0,
            "myth_count": 0,
            "ok": False,
            "reason": f"terms_table_{kind}",
        }
    actual = _sha256_file(terms_path)

    expected = ""
    manifest = root / "VENDOR.sha256"
    manifest_text, manifest_reason = (
        # base=root：原因串与 vendor 同基（skill 在仓库外时不漏绝对宿主路径，L2R6-04c）
        _read_text(manifest, base=root) if manifest.is_file() else ("", "missing")
    )
    # L2R7-03（残余）→ L2R8：与 `verify_vendor_manifest` 用同一套换行口径 ——
    # `splitlines()` 会在 NEL(U+0085)/U+2028 处断行，于是清单里可以"伪造"条目；
    # 换行只认 \n / \r\n / \r。两处口径一致才不会出现「清单被判非法、词表却 ok=True」。
    normalized = (manifest_text or "").replace("\r\n", "\n").replace("\r", "\n")
    for line in normalized.split("\n"):
        parts = line.split()
        if len(parts) != 2 or len(parts[0]) != 64:
            continue
        # 与 verify_vendor_manifest 同一把尺子（L2R6-04/05）：不信任原始路径内容。
        rel, reject = _manifest_entry_rel(parts[1], root)
        if not reject and rel == "scripts/terms.json":
            expected = parts[0]
            break

    info: dict[str, Any] = {
        "sha256": actual,
        "expected_sha256": expected,
        "terms_count": 0,
        "myth_count": 0,
        "ok": False,
        "reason": "",
    }
    # L2R2-03：初版是 `if expected and actual != expected` —— 清单缺失、或清单里没有
    # terms.json 那一行时，`expected` 为空，比对被**静默跳过**，于是「删掉清单 + 把词表
    # 从 41 条改成 1 条」照样 ok=True / status=ran。校验缺席必须等于失败，不是等于通过。
    if not manifest.is_file():
        info["reason"] = "vendor_manifest_missing"
        return info
    if manifest_reason:
        info["reason"] = f"vendor_manifest_{manifest_reason}"
        return info
    if not expected:
        info["reason"] = "vendor_manifest_lacks_terms_entry"
        return info

    text, read_reason = _read_text(terms_path)
    if text is None:
        info["reason"] = f"terms_table_{read_reason}"
        return info
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        info["reason"] = "terms_table_not_json"
        return info
    except RecursionError:
        # L2R12-01：超深嵌套（复核方实测 6 万层数组）让 `json.loads` 抛 RecursionError —— 既非
        # JSONDecodeError 也非 OSError，原先它会**逃出 build()**、CLI 只吐回溯。而这份 terms.json
        # 是**通过哈希校验**的（复核方同步重算了 VENDOR.sha256），所以"内容合法但解析器受不了"
        # 是一条真实路径。同族缺陷在 `scripts/daily_engine.py` 早修过（L2R8-05），那轮没把修法
        # 传播到本模块 —— 现在五处 `json.loads` 全部补齐。
        info["reason"] = "terms_table_too_deep"
        return info
    if not isinstance(payload, Mapping):
        info["reason"] = "terms_table_not_mapping"
        return info
    terms = payload.get("terms")
    myths = payload.get("debunked_myths")
    info["terms_count"] = len(terms) if isinstance(terms, list) else 0
    info["myth_count"] = len(myths) if isinstance(myths, list) else 0

    if actual != expected:
        info["reason"] = "terms_table_hash_mismatch"
        return info
    if info["terms_count"] == 0:
        info["reason"] = "terms_table_empty"
        return info
    info["ok"] = True
    return info


REQUIRED_MANIFEST_ENTRIES = ("scripts/scan.py", "scripts/terms.json")
"""清单里**必须有**的条目：本层真正执行/读取的那两件（`stage_workspace` 只暂存它们）。

L2R6-01：逐条校验只保证"清单上写的对得上"，不保证"该写在上面的没被删"。把
`VENDOR.sha256` 里 `./scripts/scan.py` 那一行**删掉**（文件换成永远零候选的桩），
记录会落成 `rc=0` / `status=ran` / `candidates=0` / `errors=[]` / `vendor_manifest.ok=true`
（`checked` 36→35）—— 比"词表+清单双改自洽"更便宜：不需要哈希知识，只删一行。
`terms.json` 侧本来就有反向强制（`vendor_manifest_lacks_terms_entry`），`scan.py` 侧没有，
于是最危险的那件（产出候选的代码）成了唯一"可以被静默摘掉"的一件。
"""


def _entry_label(rel: str, *, limit: int = 120) -> str:
    """进记录用的条目名：短的照抄，长的截断+摘要（L2R7-03：长度原先完全无界）。

    复核实测：清单里塞一条 1,000,002 字符的路径，`missing[]` 与 `reason` 会把它**原样**
    落进 run 证据（`reason` 长 1,000,026 字符）。现在条目本身已被 `_manifest_entry_rel`
    按长度拒绝，这里再兜一层，保证任何进记录的串都有上界且**可区分**。
    """
    if len(rel) <= limit:
        return rel
    digest = hashlib.sha256(rel.encode("utf-8", "replace")).hexdigest()[:8]
    return f"{rel[:limit]}…+{digest}"


def _manifest_entry_rel(raw: str, root: Path) -> tuple[str, str]:
    """清单里的目标路径 → ``(规范相对路径, 拒绝原因)``；拒绝串里**不含**原始内容。

    L2R6-04：初版把清单路径原样信任 —— ① 含 NUL 的路径直达 `reason`/`missing`/`errors`
    （`vendor_manifest_missing:ref\\x00s.md`），违背 `_reason_detail` 自己的"无控制字符"口径；
    ② `../outside.txt` 被解析到 vendor **之外**、真去哈希并计入 `checked`（`ok=true`）。
    这里按"行号定位、不回显"的写法拒绝，绝对路径也不会进记录。

    L2R7-03 补三处同类洞（第 6 轮只关了 NUL / 越界）：
    ③ **C1 控制字符**（U+0080–U+009F）与 Cf/Zl/Zp 类都不算"显示字符"，此前 `ord(ch)<32`
       只盖住 C0 —— 现在按 Unicode 类别判；
    ④ **长度无界**：1,000,002 字符的路径会原样进 `missing[]`/`reason` —— 现在超过
       `_MANIFEST_ENTRY_MAX` 直接拒绝（`too_long`），进记录的串另经 `_entry_label` 截断；
    ⑤ **摘标记顺序**：`sha256sum -b` 的 `*` 与 `./` 可以叠成 `*./x`，初版先剥 `./` 再剥 `*`
       会留下 `./x` 二次不规范化，把**合法**清单误判成缺条目（fail-closed 的假报错）；
       现在先剥 `*`、再循环剥 `./`。
    """
    rel = raw.strip()
    if rel.startswith("*"):  # sha256sum -b 的二进制标记（可能叠在 ./ 之前）
        rel = rel[1:]
    while rel.startswith("./"):
        rel = rel[2:]
    if not rel:
        return "", "empty"
    if len(rel) > _MANIFEST_ENTRY_MAX:
        return "", "too_long"
    if any(unicodedata.category(char) in ("Cc", "Cf", "Zl", "Zp") for char in rel):
        return "", "control_char"
    path = PurePosixPath(rel)
    if path.is_absolute() or ".." in path.parts:
        return "", "path_escape"
    if not _within(root / rel, root):
        return "", "path_escape"
    return rel, ""


def verify_vendor_manifest(skill: str | Path | None = None) -> dict[str, Any]:
    """`VENDOR.sha256` 里**每一条**都要在磁盘上对得上（L2R5-01）。

    初版只比对清单里 `scripts/terms.json` 那一行：于是把 vendor 的 `scripts/scan.py`
    换成"永远输出零候选"的桩，本层照样 `status=ran` + 候选 0 + 无告警 —— 而
    `scan.py` 正是**产出候选的那段代码**，它被换掉时连清单都不用改。这正是本层要拦的
    "假阴性被读成干净"，而且比"terms.json 与清单同步改写"更便宜（那一版至少要改两处）。

    口径（第 6 轮补强）：
    - 清单里列出的每条都要**存在且逐字节相符**；清单外的文件多出来不算错
      （升级 vendor 时先落文件后补清单是正常时序），但清单本身为空算错。
    - **`REQUIRED_MANIFEST_ENTRIES` 里的条目必须出现在清单上**（L2R6-01）——
      "逐条校验"管不了"把该有的那行删掉"。
    - 路径必须是 vendor 内的相对路径（拒绝绝对路径、`..`、控制字符）；重复条目算错
      （L2R6-04 / L2R6-05：重复一行会让 `checked` 虚增，"35 与 37 谁算异常"不再有歧义）。
    - 摘要**大小写敏感**（与 `verify_terms_table` 口径一致；`sha256sum` 只产出小写），
      仅大小写不同时给可区分的 `vendor_manifest_hash_case_mismatch`（L2R6-05）。
    - `checked` = **唯一且已核验通过**的条目数（存在 + 逐字节相符），`unique_count` =
      去重后参与核验的条目数，`listed` = 清单里的非空行数（L2R7-04：初版 `checked` 与
      `unique_count` 结构恒等、且在 missing/mismatch 判定**之前**自增，于是混合场景里
      `checked=37` 而 `missing` 有 1 条，"已核验"名不副实）。三者关系
      `checked ≤ unique_count ≤ listed`。
    """
    root = Path(skill) if skill is not None else skill_dir()
    manifest = root / "VENDOR.sha256"
    info: dict[str, Any] = {
        "ok": False,
        "checked": 0,
        "listed": 0,
        "unique_count": 0,
        "missing": [],
        "mismatched": [],
        "mismatched_case_only": [],
        "malformed_lines": [],
        "rejected_entries": [],
        "duplicate_entries": [],
        "required_missing": [],
        "reason": "",
    }
    if not manifest.is_file():
        info["reason"] = "vendor_manifest_missing"
        return info
    # base=root：原因串里的路径与 vendor 同基（skill 目录在仓库外时不再漏出绝对宿主路径，L2R6-04c）
    manifest_text, manifest_reason = _read_text(manifest, base=root)
    if manifest_text is None:
        info["reason"] = f"vendor_manifest_{manifest_reason}"
        return info

    seen: set[str] = set()
    # L2R7-03⑤：`splitlines()` 会在 NEL(U+0085)/U+2028 处断行，于是清单里可以"伪造"出条目
    # 并让 malformed/rejected 的**行号失真**；换行只认 \n / \r\n / \r。
    lines = manifest_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        info["listed"] += 1
        parts = line.split()
        if len(parts) != 2 or len(parts[0]) != 64:
            info["malformed_lines"].append(f"{number}")
            continue
        raw_digest, raw_rel = parts[0], parts[1]
        rel, reject = _manifest_entry_rel(raw_rel, root)
        if reject:
            info["rejected_entries"].append(f"{number}:{reject}")
            continue
        if rel in seen:
            info["duplicate_entries"].append(_entry_label(rel))
            continue
        seen.add(rel)
        target = root / rel
        if not target.is_file():
            info["missing"].append(_entry_label(rel))
            continue
        actual = _sha256_file(target)
        if actual == raw_digest:
            info["checked"] += 1  # 只有"存在且逐字节相符"才算已核验（L2R7-04）
            continue
        if actual == raw_digest.lower() and raw_digest != raw_digest.lower():
            info["mismatched_case_only"].append(_entry_label(rel))
        else:
            info["mismatched"].append(_entry_label(rel))

    info["unique_count"] = len(seen)
    info["required_missing"] = [
        _entry_label(rel) for rel in REQUIRED_MANIFEST_ENTRIES if rel not in seen
    ]

    if info["malformed_lines"]:
        info["reason"] = f"vendor_manifest_malformed_line:{info['malformed_lines'][0]}"
        return info
    if info["rejected_entries"]:
        info["reason"] = f"vendor_manifest_rejected_entry:{info['rejected_entries'][0]}"
        return info
    if info["duplicate_entries"]:
        info["reason"] = f"vendor_manifest_duplicate_entry:{info['duplicate_entries'][0]}"
        return info
    # 空清单 = 一条都没列；判据是 unique_count 而不是 checked（后者是"已核验"，L2R7-04）
    if not info["unique_count"]:
        info["reason"] = "vendor_manifest_empty"
        return info
    if info["required_missing"]:
        # 最危险的一类：该有的那行被删掉，于是"没扫成"看起来像"扫过且 0 命中"。
        info["reason"] = (
            f"vendor_manifest_lacks_required_entry:{info['required_missing'][0]}"
        )
        return info
    if info["missing"]:
        info["reason"] = f"vendor_manifest_missing:{info['missing'][0]}"
        return info
    if info["mismatched"]:
        info["reason"] = f"vendor_manifest_hash_mismatch:{info['mismatched'][0]}"
        return info
    if info["mismatched_case_only"]:
        info["reason"] = (
            f"vendor_manifest_hash_case_mismatch:{info['mismatched_case_only'][0]}"
        )
        return info
    info["ok"] = True
    return info


def _scan_wordlist_files(root: Path) -> list[Path]:
    """`scan.py:load_wordlists()` **真正会加载**的词库文件。

    上游是 ``wordlists`` **顶层** 的 `*.md`/`*.txt`，且显式排除 `readme*`；用 `rglob`
    或只认 `.md`，都会让"我们以为有规则"和"扫描器实际有规则"脱节（L2R2-02）。
    """
    wordlists = Path(root) / "wordlists"
    if not wordlists.is_dir():
        return []
    files = {
        path
        for suffix in ("*.md", "*.txt")
        for path in wordlists.glob(suffix)
        if path.is_file() and not path.name.lower().startswith("readme")
    }
    return sorted(files)


def _wordlist_non_regular_files(root: Path) -> list[str]:
    """上游 glob **会试着读**、但不是普通文件的词库文件（第 11 轮 finding 3）。

    `scan.py:load_wordlists()`（`:145-152`）只按 `wordlists/` 顶层 `*.md`/`*.txt` glob，
    **没有 `is_file()` 过滤** —— 放一个无写端 FIFO 当 `wordlists/x.md`，vendor 自己就挂住了，
    本层的 `subprocess.run(timeout=…)` 只是把「永久阻塞」降级成「最长 120 秒无输出」。
    这里用 `stat` 判型（绝不 `open()`）把两个入口都变成启动 vendor 之前的 fail-closed；
    同时让 `rules_identity()` 的计数集合与 vendor 实际会尝试加载的集合不再脱节。
    """
    wordlists = Path(root) / "wordlists"
    if not wordlists.is_dir():
        return []
    found: set[str] = set()
    for suffix in ("*.md", "*.txt"):
        for path in wordlists.glob(suffix):
            if path.name.lower().startswith("readme"):
                continue
            if not path.is_file():
                found.add(f"wordlists/{path.name}")
    return sorted(found)


def _wordlist_terms(path: Path) -> tuple[int, str]:
    """按 scan.py 的行过滤规则数**实际可匹配词条**（# 说明行与空行不算）。"""
    text, reason = _read_text(path)
    if text is None:
        return 0, reason
    count = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("<!--"):
            continue
        head = re.split(r"[|\t]", line, maxsplit=1)[0]
        if head.strip("- ").strip():
            count += 1
    return count, ""


def rules_identity(rules: str | Path | None = None) -> dict[str, Any]:
    """我们自己规则表的身份与规模（L2-02/08/L2R2-02）。

    初版对"规则目录缺失"和"规则目录存在但没有任何词条"都毫无表示：前者静默建空
    `data/` 后报 `ran` + 0 自查命中，与"扫过且没命中"逐字段同形。

    L2R2-02：`can_match` 必须按**扫描器真正加载的文件**算。初版用 `rglob` + 仅 `.md`，
    于是词库挪进 `wordlists/sub/` 时 `can_match=True` 却一条都没加载（把"没规则"报成
    "规则放行"），而 `.txt` 词库确实命中时反而附上"personal_hits 恒为 0"的免责说明。
    现在：`wordlist_terms` 数的是实际词条，`scan_files` 是实际加载集，`extra_files`
    列出"存在但扫描器永远不会读"的文件 —— 放错目录当场显形，不再靠约定。
    """
    root = Path(rules) if rules is not None else rules_data_dir()
    info: dict[str, Any] = {
        "dir": _rel(root),
        "exists": root.is_dir(),
        "file_count": 0,
        "sha256": "",
        # L2R3-07：`sha256` 只覆盖"实际加载集"，而 file_count/extra_files 覆盖全目录 ——
        # 往 wordlists/sub/ 放词库时 file_count 变、sha256 不变，字段名很容易被读成
        # "规则目录的身份"，于是"摘要没变"被错读成"规则目录没被改"。显式标注口径，
        # 并另给一个真·全目录的 dir_sha256。
        "sha256_scope": "loaded_rules_only",
        "dir_sha256": "",
        "blacklist_rows": 0,
        # L2R3-01：正则非法、被上游跳过的行数（不计入 blacklist_rows，也不推进 can_match）。
        "blacklist_invalid_rows": 0,
        "blacklist_invalid_samples": [],
        "wordlist_files": 0,
        "wordlist_terms": 0,
        # 第 11 轮 finding 3：vendor 的 glob 会试着读、但不是普通文件的词库（FIFO/悬空软链）。
        "wordlist_non_regular": [],
        "can_match": False,
        "scan_files": [],
        "extra_files": [],
    }
    if not info["exists"]:
        return info
    present = sorted(p for p in root.rglob("*") if p.is_file())
    info["file_count"] = len(present)

    dir_digest = hashlib.sha256()
    for path in present:
        dir_digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        dir_digest.update(b"\0")
        try:
            dir_digest.update(path.read_bytes())
        except (OSError, ValueError):
            info["dir_sha256"] = ""
            info["dir_sha256_unreadable"] = _rel(path)
            break
        dir_digest.update(b"\0")
    else:
        info["dir_sha256"] = dir_digest.hexdigest()

    scan_files: list[Path] = []
    my_rules = root / "my-rules.md"
    if my_rules.is_file():
        scan_files.append(my_rules)
    wordlist_files = _scan_wordlist_files(root)
    scan_files.extend(wordlist_files)
    info["scan_files"] = [str(p.relative_to(root).as_posix()) for p in scan_files]
    info["wordlist_files"] = len(wordlist_files)
    info["wordlist_non_regular"] = _wordlist_non_regular_files(root)
    info["extra_files"] = [
        str(p.relative_to(root).as_posix()) for p in present if p not in set(scan_files)
    ]

    digest = hashlib.sha256()
    for path in scan_files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except (OSError, ValueError):
            info["sha256"] = ""
            info["unreadable"] = _rel(path)
            return info
        digest.update(b"\0")
    info["sha256"] = digest.hexdigest()

    if my_rules.is_file():
        text, reason = _read_text(my_rules)
        if text is None:
            # L2R4-04：非 UTF-8 的 my-rules.md 原先报成"零黑名单规则"（`read_bytes()` 成功，
            # 只有 `_read_text` 才解不开 → `unreadable` 不设、`blacklist_rows=0`、
            # `invalid_rows=0`、note 为空），词库还可能有词条把 `can_match` 顶成 True。
            # 现在显式标注，调用方据此写进 note/errors。
            info["blacklist_unreadable"] = reason
        else:
            stats = _blacklist_stats(text)
            info["blacklist_rows"] = int(stats.get("rows", 0))
            info["blacklist_invalid_rows"] = int(stats.get("invalid", 0))
            info["blacklist_invalid_samples"] = list(stats.get("samples", []))
    info["wordlist_terms"] = sum(_wordlist_terms(p)[0] for p in wordlist_files)
    info["can_match"] = (info["blacklist_rows"] + info["wordlist_terms"]) > 0
    return info


def _blacklist_stats(text: str) -> dict[str, Any]:
    """按**上游真正的装载规则**数 `my-rules.md` 黑名单行（L2R3-01）。

    初版只数行数、不编译 cells[0]：一行非法正则（如 `[`）在上游 `scan.py:110-114` 会
    `re.compile` 失败并跳过（`personal_hits` 恒 0），本层却照报 `can_match=True`、
    `blacklist_rows=1`，于是"一条规则都没装载"被写成"规则放行"。

    这里逐行复刻 `scan.py:parse_my_rules()`（vendor 里没有 `_load_my_rules`）：章节识别、`\\|` 占位还原、表头过滤、
    `re.compile` 失败即跳过并计入 invalid。
    """
    stat: dict[str, Any] = {"rows": 0, "invalid": 0, "invalid_lines": [], "samples": []}
    section = ""
    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if line.startswith("#"):
            if "黑名单" in line:
                section = "black"
            elif "白名单" in line:
                section = "white"
            else:
                section = "notes" if "语义笔记" in line else ""
            continue
        if not line.startswith("|") or set(line) <= {"|", "-", " ", ":"}:
            continue
        # 表格内正则的"或"要写 `\|`（裸 `|` 会被切列），上游解析时还原。
        placeholder = "\x00PIPE\x00"
        cells = [
            cell.strip().replace(placeholder, "|")
            for cell in line.strip("|").replace("\\|", placeholder).split("|")
        ]
        if cells and cells[0] in {"词/正则", "词", "词/表达"}:
            continue
        if section != "black" or not cells or not cells[0]:
            continue
        try:
            re.compile(cells[0])
        except re.error:
            stat["invalid"] += 1
            stat["invalid_lines"].append(line_no)
            if len(stat["samples"]) < 5:
                stat["samples"].append(f"第{line_no}行:{cells[0]}")
            continue
        stat["rows"] += 1
    return stat


# --------------------------------------------------------------------------- staging


class RulesStagingError(RuntimeError):
    """规则目录"挂上去了但读不到"（R9-04；第 10 轮 F2 改成**可达**）。

    上游 `scan.py` 用 `Path(__file__).resolve().parent.parent` 当 SKILL_ROOT、`data/` 写死在那儿，
    所以我们的规则目录是**软链**过去给它的。软链按**自身所在目录**解析目标：规则目录传相对路径时
    会变成悬空链接，vendor 于是加载到**空黑名单且 `warnings=[]`**，而 `rules_identity()` 仍按源目录
    如实报 `blacklist_rows=13 / can_match=True` —— 「记录说有规则、实际一条没装载」，正是本层存在的
    意义所要防的那类假干净。

    第 10 轮复核证明初版断言**不可达**（它比较的是自指软链后的同一个文件，`samefile` 恒 True）。
    现在改成**内容比对**：源目录 `my-rules.md` 存在（含悬空软链 / 目录 / 不可读）时，挂载后必须能
    读出**逐字节相同**的内容，否则抛本异常。三种真实形态都会走到这里：悬空软链、`my-rules.md`
    是目录、规则目录 `chmod 000`。调用方（`scan_text`）把它转成 `status=error / rules_unstaged:…`。
    """


def _source_my_rules_digest(rules_abs: Path) -> str | None:
    """源目录 `my-rules.md` 的字节摘要：不存在 → `None`；存在但读不出来 → 直接抛。

    用 `os.path.lexists` 而不是 `Path.exists()`：悬空软链在 `exists()` 下是 False，会被当成
    "这份规则库没有 my-rules.md"，而那正是我们要拦的假干净。

    第 11 轮 finding 1（major）：`lexists` 只回答「在不在」，**不回答「是不是普通文件」** ——
    规则目录里放一个无写端 FIFO 当 `my-rules.md`，这里就直接 `read_bytes()` **永久阻塞**
    （CLI `--text/--file` 实测 `timeout 15` → rc=124、stdout/stderr 全空）。这与第 8/9/10 轮
    在正文、vendor 文件上修过的是**同一个不变量**：判型一律走 `stat`/`os.path.isfile`，
    绝不 `open()`。挂载后的一致性比对在 `stage_workspace()` 里，本函数只管源侧。
    """
    path = rules_abs / "my-rules.md"
    if not os.path.lexists(path):
        return None
    if not os.path.isfile(path):
        # FIFO / 字符设备 / 目录 / 悬空软链都到此为止 —— 它们**不是**「没有 my-rules.md」，
        # 而是「有东西在那儿却不是可读的规则文件」，必须显式报错而不是静默当空规则。
        raise RulesStagingError(
            f"rules_unstaged:{_rel(rules_abs)}:源 my-rules.md 不是普通文件（FIFO/目录/设备/悬空软链）"
        )
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, ValueError) as exc:
        raise RulesStagingError(
            f"rules_unstaged:{_rel(rules_abs)}:源 my-rules.md 在位但读不出来（{type(exc).__name__}）"
        ) from exc


def stage_workspace(skill: str | Path, rules: str | Path, dest: str | Path) -> Path:
    """把 vendor 的 scripts 复制进工作目录，并把我们的规则挂成它的 `data/`。

    为什么不直接跑 vendor：上游 `scan.py` 用 `Path(__file__).resolve().parent.parent`
    当 SKILL_ROOT，`data/` 路径写死在那儿。想用我们的规则又不改上游，只能这样摆一次。
    """
    dest = Path(dest)
    scripts_dest = dest / "scripts"
    scripts_dest.mkdir(parents=True, exist_ok=True)
    for name in ("scan.py", "terms.json"):
        source = Path(skill) / "scripts" / name
        if not source.is_file():
            raise FileNotFoundError(f"vendor 缺文件：{source}")
        shutil.copy2(source, scripts_dest / name)
    data_dest = dest / "data"
    rules = Path(rules)
    if os.path.lexists(rules) and not os.access(rules, os.R_OK | os.X_OK):
        # 第 10 轮 F2：目录 `chmod 000` 时 `Path.is_dir()` 直接返回 False → 走 else 分支建一个
        # **空** data/，vendor 加载 0 条规则而 `status=ran`。必须先按可读性拦下（`os.access`
        # 对 root 恒真，所以本判据只在非 root 下起作用 —— 与生产一致）。
        raise RulesStagingError(
            f"rules_unstaged:{_rel(rules)}:规则目录不可读（一条规则都没装载）"
        )
    if rules.is_dir():
        # R9-04：**必须** resolve 成绝对路径再挂 —— 相对路径会被软链按自身目录解析成悬空链接。
        rules_abs = rules.resolve()
        expected = _source_my_rules_digest(rules_abs)
        try:
            data_dest.symlink_to(rules_abs, target_is_directory=True)
        except OSError:  # 不支持符号链接的文件系统：退化成复制
            shutil.copytree(rules_abs, data_dest)
        if expected is not None:
            # 第 10 轮 F2：断言必须是**内容比对**（初版比"挂载后是不是普通文件"，
            # 而软链指向的就是同一个文件，`samefile` 恒 True → 断言不可达）。
            staged = data_dest / "my-rules.md"
            try:
                actual = hashlib.sha256(staged.read_bytes()).hexdigest()
            except (OSError, ValueError) as exc:
                raise RulesStagingError(
                    f"rules_unstaged:{_rel(rules_abs)}:挂载后读不到 my-rules.md（{type(exc).__name__}）"
                ) from exc
            if actual != expected:
                raise RulesStagingError(
                    f"rules_unstaged:{_rel(rules_abs)}:挂载后的 my-rules.md 与源目录不一致"
                )
    else:
        data_dest.mkdir(parents=True, exist_ok=True)
    return dest


def _rules_unstaged_problem(rules_info: Mapping[str, Any], rules: str | Path) -> str:
    """「规则在位却一条都没装载」的结构化病因（第 10 轮 F2）；`""` 表示没有这个问题。

    只看**源目录**的事实，不依赖拿到多少条规则，所以它覆盖三条真实形态：`my-rules.md` 是悬空
    软链 / 是目录 / 读不出来，以及「声明了黑名单区段但装载 0 行」这个更一般的形态。
    缺 `my-rules.md`（整份规则库从没写过）**不算**问题 —— 那种情况由 `can_match=False` +
    `personal_rules_note`（"没有规则，不是规则放行"）如实显形。
    """
    root = Path(rules)
    my_rules = root / "my-rules.md"
    unreadable = str(rules_info.get("blacklist_unreadable") or "")
    dir_readable = os.access(root, os.R_OK | os.X_OK)
    if unreadable and (os.path.lexists(my_rules) or not dir_readable):
        return f"rules_unstaged:{_rel(root)}:my-rules.md 在位但读不出来（{_reason_detail(unreadable)}）"
    if my_rules.is_dir():
        return f"rules_unstaged:{_rel(root)}:my-rules.md 是目录（一条规则都没装载）"
    if os.path.lexists(my_rules) and not my_rules.is_file():
        return f"rules_unstaged:{_rel(root)}:my-rules.md 不是普通文件（悬空软链/特殊文件）"
    if not dir_readable:
        return f"rules_unstaged:{_rel(root)}:规则目录不可读（一条规则都没装载）"
    # 第 11 轮 finding 3：`wordlists/` 里有 FIFO/悬空软链时上游 glob 会挂住 ——
    # 本层必须在**启动 vendor 之前**就 fail-closed（`subprocess.run(timeout=…)` 只是把
    # 永久阻塞降级成"最长 120 秒静默"，那不是可区分的故障形态）。
    non_regular = [str(name) for name in (rules_info.get("wordlist_non_regular") or [])]
    if non_regular:
        return (
            f"rules_unstaged:{_rel(root)}:wordlists 里有非普通文件"
            f"（vendor 会挂住）:{','.join(non_regular)}"
        )
    if my_rules.is_file():
        try:
            declared = "黑名单" in my_rules.read_text(encoding="utf-8", errors="ignore")
        except (OSError, ValueError):
            declared = False
        loaded = int(rules_info.get("blacklist_rows") or 0)
        invalid = int(rules_info.get("blacklist_invalid_rows") or 0)
        if declared and loaded == 0 and invalid == 0:
            return f"rules_unstaged:{_rel(root)}:my-rules.md 声明了黑名单区段却装载 0 行"
    return ""



def _personal_rules_note(rules_info: Mapping[str, Any]) -> str:
    """「我们的规则库里到底有没有能开火的规则」的显形说明（L2R3-01 / L2R4-04 / 第 11 轮 finding 2）。

    `build` 与 ad-hoc 记录（CLI `--text/--file/--json`）必须用**同一份**措辞：第 11 轮复核发现
    ad-hoc 记录里从来没有这个字段，于是 `--json` 里只剩一句 `可匹配=False`，而 run 级记录里
    那句「personal_hits 恒为 0 是**没有规则**，不是**规则放行**」在 CLI 路线上缺席。

    返回 `""` 表示没有需要显形的问题（规则库正常装载且 `can_match=True`）。
    """
    notes: list[str] = []
    blacklist_unreadable = str(rules_info.get("blacklist_unreadable") or "")
    if blacklist_unreadable:
        # L2R4-04：读不出来的黑名单**不许**算成"零黑名单规则"。
        notes.append(
            f"my-rules.md **读不出来**（{blacklist_unreadable}）：黑名单装载数未知，"
            "personal_hits 为 0 是**规则没读到**，不是**规则放行**。"
        )
    invalid_rows = int(rules_info.get("blacklist_invalid_rows") or 0)
    if invalid_rows:
        samples = "、".join(rules_info.get("blacklist_invalid_samples") or [])
        # L2R3-01：非法正则的行上游会跳过，本层必须显形 —— 否则"一条都没装载"
        # 会被读成"规则放行"（personal_hits 恒 0 也一样）。
        notes.append(
            f"my-rules.md 有 {invalid_rows} 行黑名单**正则非法**，上游 re.compile 失败会跳过"
            f"（{samples}）：这几条**没有装载**，对应词面不会被扫到。"
        )
    if not rules_info.get("can_match"):
        # 不报 error（规则库为空是合法起步状态），但必须显形：否则"自查 0 命中"
        # 会被读成"我们的规则放行了"，而实际是还没有规则。
        detail = (
            "黑名单装载数**未知**（文件读不出来）"
            if blacklist_unreadable
            else f"黑名单已装载 {rules_info.get('blacklist_rows', 0)} 条"
        )
        if invalid_rows:
            detail += f"（另有 {invalid_rows} 条因正则非法未装载）"
        notes.append(
            "我们的规则库里没有任何**已装载的**可匹配词条"
            f"（{detail}、词表 {rules_info.get('wordlist_files', 0)} 个文件 / "
            f"{rules_info.get('wordlist_terms', 0)} 条词条）："
            "personal_hits 恒为 0 是**没有规则**，不是**规则放行**。"
        )
    return " ".join(notes)


# --------------------------------------------------------------------------- scan

#: vendor `--json` 输出**必须**带的键（scan.py 的 `_scan_one` 恒定产出；键改名/裁表都是故障）。
_VENDOR_REQUIRED_KEYS = ("characters", "candidates", "personal_hits", "myth_advisories", "warnings")
#: 其中必须是 list 的字段（`characters` 单独要求 int）。
_VENDOR_LIST_KEYS = ("candidates", "personal_hits", "myth_advisories", "warnings")


def _vendor_output_shape_problem(raw: Mapping[str, Any]) -> str:
    """vendor 输出的**形状**校验（L2R11-03）。返回 ""=形状可用，否则是可区分的病因串。

    只要求 `isinstance(Mapping)` 会让「键改名 / `{}` / 缺键」的 vendor 输出一路走成
    `ran + 0 候选 + rc=0` —— 与「扫过且干净」逐字段同形。真 vendor 的输出键固定为
    `characters(int) / candidates / personal_hits / myth_advisories / warnings(list)`
    （另有 commercial/industries/note），所以这里不会误伤。
    """
    missing = [key for key in _VENDOR_REQUIRED_KEYS if key not in raw]
    if missing:
        return "scan_output_malformed:missing:" + ",".join(missing)
    characters = raw.get("characters")
    # bool 是 int 的子类，`{"characters": true}` 不是字数。
    if isinstance(characters, bool) or not isinstance(characters, int):
        return f"scan_output_malformed:characters:{type(characters).__name__}"
    for key in _VENDOR_LIST_KEYS:
        value = raw.get(key)
        if not isinstance(value, list):
            return f"scan_output_malformed:{key}:{type(value).__name__}"
    return ""


def scan_text(
    text: str,
    *,
    commercial: bool = DEFAULT_COMMERCIAL,
    industries: Sequence[str] = (),
    skill: str | Path | None = None,
    rules: str | Path | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """调上游 `scan.py --json`。**不抛异常**：任何故障都落成 status=error / not_run。

    返回 ``{"status": "ran"|"error"|"not_run", "reason": str, "raw": dict|None, ...}``。
    """
    skill_root = Path(skill) if skill is not None else skill_dir()
    rules_root = Path(rules) if rules is not None else rules_data_dir()
    vendor = vendor_identity(skill_root)
    options = {"commercial": bool(commercial), "industries": sorted({str(i) for i in industries})}
    rules_info = rules_identity(rules_root)
    base = {
        "raw": None,
        "vendor": vendor,
        "rules": rules_info,
        "options": options,
        "terms": None,
        "vendor_manifest": None,
    }
    if not (skill_root / "scripts" / "scan.py").is_file():
        return {**base, "status": "not_run", "reason": f"skill_missing:{_rel(skill_root)}"}
    # 我们的规则目录缺失 → 扫描器"跑得起来"但没有我们的规则，必须显式 not_run。
    if not rules_info["exists"]:
        return {**base, "status": "not_run", "reason": f"rules_missing:{_rel(rules_root)}"}
    # 第 11 轮 finding 2：同一判据必须覆盖 **scan_text（`--text`/`--file`/ad-hoc）** 入口。
    # 否则「`my-rules.md` 声明了黑名单区段却装载 0 行」在 `build` 里是 error、在 CLI 里却是
    # rc=0 的 `ran`（只剩一句「可匹配=False」），runbook §12.9 的那张表就只对一半入口成立。
    # 这条也顺带覆盖第 11 轮 finding 3（`wordlists/` 里有 FIFO）—— 在启动 vendor 之前拦下。
    unstaged = _rules_unstaged_problem(rules_info, rules_root)
    if unstaged:
        return {**base, "status": "error", "reason": unstaged}
    # L2R9-02：vendor 的 `scripts/{scan.py,terms.json}` 存在但**不是普通文件**（FIFO/目录/
    # 悬空软链）时，`vendor_identity()` 已经拒绝 `open()` 并回了问题串 —— 这里升级成 error。
    if vendor.get("problem"):
        return {**base, "status": "error", "reason": str(vendor["problem"])}
    terms_info = verify_terms_table(skill_root)
    base["terms"] = terms_info
    if not terms_info["ok"]:
        return {**base, "status": "error", "reason": terms_info["reason"]}
    # L2R5-01：清单里每一条都要对得上 —— 尤其是真正产出候选的 `scripts/scan.py`。
    manifest_info = verify_vendor_manifest(skill_root)
    base["vendor_manifest"] = manifest_info
    if not manifest_info["ok"]:
        return {**base, "status": "error", "reason": manifest_info["reason"]}

    try:
        with tempfile.TemporaryDirectory(prefix="publish-precheck-") as tmp:
            work = stage_workspace(skill_root, rules_root, Path(tmp) / "skill")
            command = [
                sys.executable,
                str(work / "scripts" / "scan.py"),
                "--text",
                text,
                "--json",
            ]
            if commercial:
                command.append("--commercial")
            if options["industries"]:
                command += ["--industry", ",".join(options["industries"])]
            proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except UnicodeDecodeError as exc:
        # L2R7-02：`text=True` 是 strict 解码，vendor 的 stdout/stderr 里只要有一个非 UTF-8
        # 字节，`communicate()` 就抛 UnicodeDecodeError —— 它是 **ValueError 的子类**，
        # 不在 `except (OSError, SubprocessError)` 里，于是穿透 `scan_text`：该篇报告乃至整跑
        # 的 per-article 报告全丢，病因退化成 `advisory_crashed:UnicodeDecodeError`，
        # 与"任何故障都落成 status=error 且带病因"的承诺不符。这里单独接住并给可区分的理由
        # （**不**改成 `errors="replace"` 去继续解析：坏字节可能吃掉候选，那是假阴性方向）。
        return {
            **base,
            "status": "error",
            "reason": f"scan_output_not_utf8:{_reason_detail(exc)}",
        }
    except RulesStagingError as exc:
        # R9-04 / 第 10 轮 F2：规则目录"在位却装载不到" → 显式 error，绝不退化成
        # "跑得起来但一条规则没装载"。异常消息本身已带 `rules_unstaged:` 前缀，这里不再叠一层。
        return {
            **base,
            "status": "error",
            "reason": _reason_detail(exc),
        }
    except (OSError, subprocess.SubprocessError) as exc:  # 含 TimeoutExpired
        return {
            **base,
            "status": "error",
            "reason": f"scan_invocation_failed:{type(exc).__name__}:{_reason_detail(exc)}",
        }
    if proc.returncode != 0:
        # L2R4-07：只取最后一行非空输出并压成单行，别把整段多行回溯拼进 reason。
        lines = [line.strip() for line in (proc.stderr or proc.stdout or "").splitlines()]
        lines = [line for line in lines if line]
        return {
            **base,
            "status": "error",
            "reason": f"scan_exit_{proc.returncode}:{_reason_detail(lines[-1] if lines else '')}",
        }
    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        # L2R5-03 + L2R6-03：附**整段** stdout 的限长摘要（不是首行），两类坏输出不再同名。
        return {
            **base,
            "status": "error",
            "reason": f"scan_output_not_json:{_reason_detail(type(exc).__name__, _stdout_snippet(proc.stdout or ''))}",
        }
    except RecursionError:
        # L2R12-01 同族：vendor 吐出超深嵌套 JSON 时 `json.loads` 抛 RecursionError（不是
        # JSONDecodeError），必须收成本层的结构化 error，不许逃出 build()/CLI。
        return {
            **base,
            "status": "error",
            "reason": f"scan_output_too_deep:{_stdout_snippet(proc.stdout or '')}",
        }
    if not isinstance(raw, Mapping):
        return {**base, "status": "error", "reason": "scan_output_not_mapping"}
    # L2R11-03：只有"是 Mapping"这一条守卫太松 —— 键改名、`{}`、缺键的 vendor 输出会一路
    # 走成 `ran + 0 候选 + rc=0`，与"扫过且干净"同形（直接违反 §5 的可区分性承诺）。
    shape_problem = _vendor_output_shape_problem(raw)
    if shape_problem:
        return {**base, "status": "error", "reason": shape_problem}
    return {**base, "status": "ran", "reason": "", "raw": dict(raw)}


def _triage(candidates: Sequence[Mapping[str, Any]], personal: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """只做分诊计数，不是判定：高等级需马上看，其余记一笔。"""
    counts = {"review_now": 0, "note": 0}
    for item in candidates:
        severity = str(item.get("severity") or "").lower()
        counts["review_now" if SEVERITY_RANK.get(severity, 0) >= 2 else "note"] += 1
    for item in personal:
        level = str(item.get("level") or "")
        counts["review_now" if MY_LEVEL_RANK.get(level, 0) >= 2 else "note"] += 1
    return counts


def _blank_article(article_id: str, body_rel: str) -> dict[str, Any]:
    return {
        "article_id": article_id,
        "body_path": body_rel,
        "body_sha256": "",
        "status": "error",
        "reason": "",
        "characters": 0,
        "candidates": [],
        "personal_hits": [],
        "myth_advisories": [],
        "parse_warnings": [],
        "title": None,
        "candidate_count": 0,
        "triage": {"review_now": 0, "note": 0},
    }


# vendor `scan.py` 三类输出的字段白名单（L2R9-05）。
#
# 为什么是**白名单**而不是"删掉 `pass` 键就行"：候选 dict 原先是从 vendor 输出逐字 `dict()`
# 复制的，于是本层记录里能否出现 `pass` 取决于**vendor 的输出**（上游被改过、或未来上游
# 自己加了一个叫 `pass` 的字段，记录里就会出现 `pass`）—— 不变量 A（"结构上不可能被读成
# 通过"）就落在了 vendor 身上，而不是本层身上。现在只投影已知字段，多出来的键只留**键名**，
# 不进记录（上游新增字段会表现为 `dropped_vendor_keys`，一眼可见，不会静默）。
_VENDOR_CANDIDATE_KEYS = (
    "match", "start", "end", "line", "context", "rule", "title", "severity", "doc",
    "muted_by_whitelist",
)
_VENDOR_PERSONAL_KEYS = ("match", "start", "end", "line", "context", "reason", "level", "mode")
_VENDOR_MYTH_KEYS = ("match", "start", "end", "line", "context", "myth", "note", "suggestion")


def _project_vendor_item(
    item: Mapping[str, Any], allowed: tuple[str, ...]
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """把 vendor 输出项投影到白名单；返回 ``(投影后的项, 被丢掉的键名)``。

    L2R11-02：只挡键名不够 —— **值**仍可以是任意嵌套结构（如 ``{"line": {"pass": true}}``），
    键名全部合规却把 ``pass`` 键带进 run 记录、逐篇证据、CLI `--json` 与复核候选四种形状。
    这里只放行**标量**值：非标量降级成留痕 ``"<key>[non_scalar:<type>]"``，一个都不透传。
    """
    projected: dict[str, Any] = {}
    dropped: list[str] = []
    for key in allowed:
        if key not in item:
            continue
        value = item[key]
        if _is_scalar(value):
            projected[key] = value
        else:
            dropped.append(f"{key}[non_scalar:{type(value).__name__}]")
    for key in item:
        if str(key) not in allowed:
            dropped.append(str(key))
    return projected, tuple(sorted(set(dropped)))


def _project_vendor_items(
    raw: Mapping[str, Any], field: str, allowed: tuple[str, ...]
) -> tuple[list[dict[str, Any]], set[str]]:
    """投影一个 vendor 列表字段；非 Mapping 的元素直接丢（并留痕 `"<field>[non_mapping]"`）。"""
    out: list[dict[str, Any]] = []
    dropped: set[str] = set()
    for item in raw.get(field, []) or []:
        if not isinstance(item, Mapping):
            dropped.add(f"{field}[non_mapping]")
            continue
        projected, lost = _project_vendor_item(item, allowed)
        out.append(projected)
        dropped.update(lost)
    return out, dropped


def _article_report(
    article_id: str,
    body_path: Path,
    *,
    run_root: Path,
    commercial: bool,
    industries: Sequence[str],
    skill: Path,
    rules: Path,
    title: str = "",
    title_problem: str = "",
) -> dict[str, Any]:
    report = _blank_article(article_id, _run_relative(body_path, run_root))
    text, read_reason = _read_text(body_path, base=run_root)
    if text is None:
        report["reason"] = f"body_{read_reason}"
        return report
    # 钉住"扫的是哪一版正文"：正文改写后候选与正文必须能对上号。
    # L2R3-05：初版是 sha256(解码后经通用换行归一化的文本)，而项目里同名 `body_sha256`
    # 的既有语义是**文件字节**（independent_review.py / evidence_rebind.py）。含 CRLF 的
    # 正文会让本层记录与别的记录对不上，拿去 `sha256sum` 核对会得到假不一致。
    report["body_sha256"] = _sha256_file(body_path)
    result = scan_text(
        text, commercial=commercial, industries=industries, skill=skill, rules=rules
    )
    report["status"] = result["status"]
    report["reason"] = result["reason"]
    report["vendor"] = result["vendor"]
    report["rules"] = result["rules"]
    if result["status"] != "ran":
        return report
    raw = result["raw"] or {}
    # L2R9-05：只投影白名单字段 —— 记录里不可能出现 `pass`（或任何本层没预期的键），
    # 哪怕 vendor 输出里带了；多出来的键名留在 `dropped_vendor_keys` 里可查。
    candidates, dropped_c = _project_vendor_items(raw, "candidates", _VENDOR_CANDIDATE_KEYS)
    personal, dropped_p = _project_vendor_items(raw, "personal_hits", _VENDOR_PERSONAL_KEYS)
    myths, dropped_m = _project_vendor_items(raw, "myth_advisories", _VENDOR_MYTH_KEYS)
    report.update(
        {
            "characters": int(raw.get("characters") or 0),
            "candidates": candidates,
            "personal_hits": personal,
            "myth_advisories": myths,
            # L2R11-02：warnings 里的**值**同样只收标量 —— 一个 `{"pass": true}` 会被
            # `str()` 成 `{'pass': True}` 原样写进记录，四种形状一起漏。
            "parse_warnings": [str(w) for w in raw.get("warnings", []) if _is_scalar(w)],
            "candidate_count": len(candidates),
            "triage": _triage(candidates, personal),
            "dropped_vendor_keys": sorted(dropped_c | dropped_p | dropped_m),
        }
    )
    if title_problem:
        # L2R3-03：标题包存在但读不进来时，初版把标题当空串、整条子扫描静默跳过，
        # 记录却是 ran / title=null / title_failed=0 —— 与"根本没有标题包"逐字段同形，
        # 而丢掉的正是 G14（标题党 / 标题与正文严重不一致）这条唯一检查面。
        # 没扫成不许伪装成扫过且 0 命中（不变量 C）。
        report["title"] = {
            "text": title,
            "status": "error",
            "reason": title_problem,
            "candidates": [],
            "personal_hits": [],
        }
        report["title_failed"] = True
        report["status"] = "partial"
        report["reason"] = title_problem
    if title:
        title_result = scan_text(
            title, commercial=commercial, industries=industries, skill=skill, rules=rules
        )
        title_raw = title_result["raw"] or {}
        # L2R9-05：标题面同样只投影白名单字段（原先在此逐字 `dict()` 复制）。
        if title_result["status"] == "ran":
            title_candidates, dropped_tc = _project_vendor_items(
                title_raw, "candidates", _VENDOR_CANDIDATE_KEYS
            )
            title_personal, dropped_tp = _project_vendor_items(
                title_raw, "personal_hits", _VENDOR_PERSONAL_KEYS
            )
            report["dropped_vendor_keys"] = sorted(
                set(report.get("dropped_vendor_keys") or []) | dropped_tc | dropped_tp
            )
        else:
            title_candidates, title_personal = [], []
        # 自有规则命中标题同样要留：只存官方 candidates 会让"我们自己的黑名单盯到了标题"
        # 在记录里凭空消失（标题面本就只剩这一条检查路径）。
        report["title"] = {
            "text": title,
            "status": title_result["status"],
            "reason": title_result["reason"],
            "candidates": title_candidates,
            "personal_hits": title_personal,
        }
        # L2-01（blocker）：标题扫失败在初版里完全隐形 —— 聚合只看正文报告的 status，
        # 于是"有一篇标题从未被检查"被报成 ran / failed=0 / errors=[]。标题党与
        # G14（标题与正文不一致）正是这个子扫描的唯一职责，不能静默。
        report["title_failed"] = title_result["status"] != "ran"
        if report["title_failed"]:
            report["status"] = "partial"
            report["reason"] = f"title_scan_{title_result['status']}:{title_result['reason']}"
    return report


def _run_relative(path: Path, run_root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(run_root).resolve()))
    except (ValueError, OSError):
        return str(path)


# --------------------------------------------------------------------------- run wiring


def load_declaration(run_root: str | Path) -> dict[str, Any] | None:
    """读 run 根的 `publish-precheck.json`；缺文件返回 None（不静默当 False）。

    L2R3-02：坏声明的标记键原先叫 `path`/`reason`（不带下划线），而 `_echo_declaration`
    只保留白名单键与 `_` 前缀键 —— 于是 `{"_invalid": true}` 进了记录、**为什么坏**
    被吃掉。现在标记键一律下划线开头，坏的理由在记录里可查。
    """
    path = Path(run_root) / DECLARATION_NAME
    # L2R8-03：`if not path.is_file(): return None` 把「悬空软链 / 目录」也当成"**没声明**"，
    # 于是范围被**放大**成扫全部 `drafts/*`（实测 1 篇声明 → 2 篇被扫、errors=[]、rc=0）。
    # 只有真不存在才算"没声明"；有东西但不是普通文件 → 显式坏声明（顶层降 error）。
    kind = _body_kind_problem(path, Path(run_root))
    if kind == "missing":
        return None
    if kind:
        return {"_invalid": True, "_path": DECLARATION_NAME, "_reason": kind}
    text, read_reason = _read_text(path, base=Path(run_root))
    if text is None:
        # L2R2-01：非 UTF-8 的声明原先抛未捕获 UnicodeDecodeError（崩在 build 里）。
        return {"_unreadable": True, "_path": DECLARATION_NAME, "_reason": read_reason}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return {
            "_unreadable": True,
            "_path": DECLARATION_NAME,
            "_reason": f"not_json:{exc.lineno}:{exc.colno}",
        }
    except RecursionError:
        # L2R12-01 同族：坏声明必须是显式 error，不能以任何方式逃出去。
        return {"_unreadable": True, "_path": DECLARATION_NAME, "_reason": "too_deep"}
    if not isinstance(payload, Mapping):
        return {
            "_invalid": True,
            "_path": DECLARATION_NAME,
            "_reason": f"not_mapping:{type(payload).__name__}",
        }
    return dict(payload)


def _declaration_problem(declaration: Mapping[str, Any] | None) -> str:
    """坏声明的顶层原因串；良好或缺席都返回空串（L2R3-02）。"""
    if not isinstance(declaration, Mapping):
        return ""
    if declaration.get("_unreadable"):
        return f"declaration_unreadable:{declaration.get('_reason') or 'unknown'}"
    if declaration.get("_invalid"):
        return f"declaration_invalid:{declaration.get('_reason') or 'unknown'}"
    return ""


def _declaration_type_problem(declaration: Mapping[str, Any] | None) -> str:
    """声明里**类型写错**的键 → 原因串（L2R10-05）；良好或缺席返回空串。

    `articles` 的类型是早先就 fail-closed 的（L2R2-05），但 `enabled` / `industries` /
    `commercial` 一直在被静默忽略：想关掉这一层却写成 `{"enabled": "false"}` 的声明
    照扫不误、`{"industries": "medical"}` 被读成"无强监管行业"、`{"commercial": "false"}`
    静默回落到从严 —— 三者都 `status=ran` / `errors=[]`，与一次干净扫描逐字段同形。
    **宁可报"没按声明跑"，也不假装按声明跑了。**
    """
    if not isinstance(declaration, Mapping):
        return ""
    for key in ("enabled", "commercial", "industries"):
        if key not in declaration:
            continue
        value = declaration[key]
        if key in ("enabled", "commercial"):
            if not isinstance(value, bool):
                return f"declaration_invalid_type:{key}:{type(value).__name__}"
            continue
        if not isinstance(value, list):
            return f"declaration_invalid_type:{key}:{type(value).__name__}"
        # L2R11-07：元素类型写错时原先报成 `list`（看着像合法形态，看不出哪个元素坏），
        # 而且这个 list 仍会被 `str()` 后送进 `--industry`，于是"被拒的声明"同时又生效了。
        # 现在点名**第几个元素、什么类型**；被拒 → 本函数返回原因 → 调用方整层 error 返回。
        # L2R12-02 更正：上一版这里写"`options.industries` 根本不会被构建"，与当时的实现**不符**
        # （options 在调用方的类型校验之前就建好了，复核方实测 `["medical",3]` 被拒后记录里
        # 仍是 `["3","medical"]`）。现在调用方把 options 的构建点移到校验之后、拒绝分支显式给
        # 空口径，那句话才真的成立。
        for index, item in enumerate(value):
            if not isinstance(item, str):
                return (
                    f"declaration_invalid_type:{key}[{index}]:{type(item).__name__}"
                )
    return ""


def _declared_articles(
    declaration: Mapping[str, Any] | None, run_root: Path
) -> list[tuple[str, Path | None, str, str, str]]:
    """返回 ``(article_id, body_path, error_reason, id_source, id_problem)``。

    L2-04 实测：未校验时 ``{"../../../../outside-art": …}`` 能把逐篇报告写到 run 根之外，
    ``{"x": "/etc/hostname"}`` 能把任意文件当稿件读 —— 而顶层记录照样报 `ran`。

    `id_source` 是「id 怎么来的」可查据；`id_problem` 非空表示 id **没能验证**
    （L2R3-04：坏 manifest 原先完全无痕）—— 调用方要据此降级，不许报 `ran`。
    """
    root = Path(run_root)
    # L2R11-01：`(declaration or {}).get("articles")` 对**显式 null** 与"键不存在"返回同一个
    # `None`，于是 `{"articles": null}` 被读成"没声明"→ 静默回退扫 drafts/ 全量（`ran`/rc=0），
    # 与"根本没声明"逐字段同形 —— 声明本该收窄范围，却悄悄放大。这里用哨兵把两者分开。
    declared: Any = _MISSING_ARTICLES
    if isinstance(declaration, Mapping) and "articles" in declaration:
        declared = declaration.get("articles")
    # L2R2-05：类型写错的声明原先被**静默忽略**并回退成"扫 drafts/ 下全部稿件" ——
    # 声明本来是要收窄范围，结果悄悄放大了范围且无任何提示。现在显形为一条 error，
    # 宁可报"没扫成"也不假装按声明扫了。
    if declared is not _MISSING_ARTICLES and not isinstance(declared, Mapping):
        return [("", None, f"declaration_articles_not_a_mapping:{type(declared).__name__}", "", "")]
    if isinstance(declared, Mapping) and declared:
        out: list[tuple[str, Path | None, str, str, str]] = []
        for article_id, rel in sorted(declared.items(), key=lambda kv: str(kv[0])):
            aid = str(article_id)
            if not safe_article_id(aid):
                # L2R11-06：这个 reason 直接进记录，`aid` 是外部输入 —— 过同一把限长/单行尺子。
                out.append((aid, None, f"invalid_article_id:{_reason_detail(aid)}", "", ""))
                continue
            # L2R9-04：`_within()` 只保证"解析后仍在 run 内"，所以**绝对路径**与含 `..` 的
            # 相对路径只要恰好落回 run 内就被放行（`/…/run/drafts/a/body_draft.md`、
            # `drafts/x/../a/body_draft.md`）—— 声明是外部输入，字面形态本身就该被拒：
            # "指向 run 内的绝对路径"没有正当用法，而放行它等于把"路径合法"的说服力
            # 交给文件系统的解析结果。这里按字面形态先拒（与 `_manifest_entry_rel` 同一把尺子）。
            raw_rel = str(rel)
            rel_parts = PurePosixPath(raw_rel)
            if rel_parts.is_absolute() or ".." in rel_parts.parts:
                out.append((aid, None, f"path_escape:{_reason_detail(raw_rel)}", "", ""))
                continue
            candidate = root / raw_rel
            # L2R8-01（major）：这里原先只查 `_within` 就交给 `read_text()`。声明指向 **FIFO**
            # 时 `open()` 无写端会永久阻塞，而 `run_gates` inline 调用本层且只 `except Exception`
            # → **整轮门禁挂死**（实测 rc=124）。现在"不是普通文件"在读之前就拒（纯 stat）。
            kind = _body_kind_problem(candidate, root)
            if kind:
                # 标签也过 `_reason_detail`：`rel` 里的 NUL/C1/超长不许直达记录
                # （声明里的路径是外部输入，`path_escape:a\x00b` 这种串以前真的进过 reason）。
                out.append((aid, None, f"{kind}:{_reason_detail(rel)}", "", ""))
                continue
            out.append((aid, candidate, "", "declared", ""))
        return out
    if declared is not _MISSING_ARTICLES:
        # 显式声明了 `articles: {}`＝声明"没有稿件"，不许被读成"没声明、去全扫"。
        return [("", None, "declaration_articles_empty", "", "")]
    out: list[tuple[str, Path | None, str, str, str]] = []
    drafts_dir = root / "drafts"
    for path in sorted(drafts_dir.glob("*/body_draft.md")):
        # 过滤点开头目录（如 drafts/.before/）：* 会匹配点目录，备份不能被当正式稿。
        # L2R4-02：只按 **run 相对**的段过滤，别拿绝对路径 `path.parts` 再滤一次 ——
        # run 根只要嵌在任一点开头目录下（如 `runs/.staging/run-x/`），**全部**稿件会被静默
        # 滤光，落进良性 `no_articles_to_scan` 且退出码 0，理由串还断言"没有稿件"。
        if any(part.startswith(".") for part in path.relative_to(drafts_dir).parts[:-1]):
            continue
        # L2R8-02：`if not path.is_file(): continue` 会把 FIFO / 悬空软链 / 目录**静默丢掉**
        # （只剩这一篇时降级成良性 `no_articles_to_scan` + rc=0，与"这篇本来没有正文"同形）。
        # L2R4-03 的越界判断也并进同一个 helper，四条路径口径一致。
        kind = _body_kind_problem(path, root)
        if kind:
            if kind == "missing":
                continue  # glob 命中但文件真的不在（并发删除）：如实算"没有"，不算故障
            label = f"{path.parent.name}/{path.name}"
            out.append((path.parent.name, None, f"{kind}:{_reason_detail(label)}", "", ""))
            continue
        out.append((path.parent.name, path, "", "drafts_layout", ""))
    if out:
        return out
    # pilot 版式（2026-10 现行）：正文在 run 根 draft.md，没有 drafts/<aid>/。
    # 少了这条兜底，现行 run 会一律 no_articles_to_scan —— 补充层等于没接（不会假报干净，
    # 但也永远不会开火）。实测 runs/2026-10-* 全部是这一版式。
    fallback = root / "draft.md"
    # L2R7-01：这一格原先只写 `is_file() and _within(...)`，于是 `draft.md` 变成指向 run 外的
    # 软链时**两条判据一起失败**，落进良性 `not_run / no_articles_to_scan / errors=[] / rc=0`
    # —— 记录事实上声称"没有稿件"，而稿件是在的，只是被 `_within` 拒扫（L2R4-03 只补了
    # drafts 分支那一半）。现在"有东西但不可用"与"真没有"分开报。
    if fallback.is_symlink() or fallback.exists():
        if not _within(fallback, root):
            return [("", None, "path_escape:draft.md", "", "")]
        if not fallback.is_file():
            return [("", None, "body_not_file:draft.md", "", "")]
        aid, source, problem = _pilot_article_id(root)
        return [(aid, fallback, "", source, problem)]
    return out


def _pilot_article_id(run_root: Path) -> tuple[str, str, str]:
    """pilot 单篇 run 的 ``(稿件 id, id 来源, 读 manifest 失败的原因)``。

    第一项必须过 `safe_article_id`（它会被拼进 ``review/<id>/…`` 写路径）。
    第三项非空 = id 是猜的：初版完全无痕，"manifest 坏了"与"没有 manifest"在记录里
    逐字段一致，而逐篇证据已经按猜出来的 id 落到 `review/<id>/` 了（L2R3-04 / 残留 1）。
    """
    root = Path(run_root)
    problem = ""
    for name in ("pilot-manifest.json", "article-brief.json"):
        path = root / name
        # L2R8-04：`if not path.is_file(): continue` 把「目录 / 悬空软链」也当成"没有 manifest"，
        # 于是静默退化成 run 目录名、`problem` 为空、记录仍报 `ran`。现在留痕（调用方降 partial）。
        kind = _body_kind_problem(path, root)
        if kind == "missing":
            continue
        if kind:
            problem = problem or f"{name}_{kind}"
            continue
        text, reason = _read_text(path, base=root)
        if text is None:
            problem = f"{name}_{reason}"
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            problem = f"{name}_not_json"
            continue
        except RecursionError:
            problem = f"{name}_too_deep"
            continue
        if not isinstance(payload, Mapping):
            problem = f"{name}_not_mapping:{type(payload).__name__}"
            continue
        for key in ("case_id", "article_id", "id"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                if safe_article_id(value):
                    return value, f"{name}:{key}", ""
                # L2R4-01 的姊妹洞：manifest 里有 id 但过不了**写路径**白名单（id 要拼进
                # `review/<id>/`）时，初版静默换用目录名、一点据都不留 —— "id 不可用"
                # 与"根本没有 id"在记录里逐字段同形。这里留痕，调用方据此降 partial。
                problem = problem or f"id_rejected:{name}:{key}"
    name = root.name
    aid = name if safe_article_id(name) else "draft"
    return aid, "run_dir_name", problem


def _uses_run_root_draft(run_root: Path, body_path: Path | None) -> bool:
    """正文就是 run 根的 `draft.md` → 单篇 pilot 版式，可以读 run 根的 `title-pack.json`。

    L2R10-07：run 根标题包只属于**单篇** run；drafts 版式（每篇一个 id）里再去读它，
    会把同一份标题串给多篇稿件（实测两篇都报出根标题）。

    L2R11-05：放行条件原先是 `_is_pilot_layout(id_source)`（按 **id 来源** 判断），于是
    ①「有声明、正文指向根 draft.md」时根标题包被静默丢掉（不变量 C 的另一处半边）；
    ②「drafts 版式、id 恰好来自 article-brief.json」时又可能放行。改按**正文本体**判断：
    只有正文确实等于 `run_root/draft.md`（含声明把它写成 `draft.md` 的情形）才是单篇 pilot run。
    """
    if body_path is None:
        return False
    return Path(body_path) == Path(run_root) / "draft.md"


def _selected_title(
    run_root: Path, article_id: str, *, allow_root_pack: bool = False
) -> tuple[str, str]:
    """标题包里的被选中标题 **+ 读不出来的原因**（G14 标题党是真实风险面）。

    返回 ``(title, problem)``：`problem` 非空表示"标题包**在**，但没读成" —— 见 L2R3-03。
    初版把这两种情况都返回空串，于是坏标题包让整条子扫描静默消失，记录与"没有标题包"
    逐字段同形，丢的正是 G14（标题与正文严重不一致）这条唯一检查面。

    L2R4-01：本函数的**读**路径不许复用 `safe_article_id`（那是**写**路径白名单）。初版首行
    `if not safe_article_id(article_id): return "", ""` 让 drafts 版式下目录名含中文等非白名单
    字符的稿件（`drafts/解说稿-001/`）标题子扫描**查都不查**就消失，记录与"这篇本来没有
    标题包"逐字段同形（`title=None` / 无 `title_failed` / `errors=[]` / `status=ran` / rc=0）。
    现在：**能被 `_within` 收住就查**（读路径的真约束是"不许越出 run 根"），收不住才拒绝，
    并把拒绝显式报出来让调用方降级 —— 不许静默当成"没有标题包"。
    """
    root = Path(run_root)
    problems: list[str] = []
    candidates = [
        root / "review" / str(article_id) / "title-pack.json",
        root / "drafts" / str(article_id) / "title_pack.json",
    ]
    if allow_root_pack:
        # pilot 版式（单篇 run）：标题包在 run 根。
        # L2R10-07：这一格**只对 pilot 版式开放** —— 初版对 drafts 版式的每一篇都查它，
        # 于是 `drafts/a/`、`drafts/b/` 两篇会同时拿到 run 根那份标题，标题面的证据被
        # **串味**归属（实测两篇都报出根标题）。多篇 run 里 run 根标题包本来就不属于任何一篇。
        candidates.append(root / "title-pack.json")
    for candidate in candidates:
        if not _within(candidate, root):
            # id 含 `..` / 绝对路径等 → 候选落在 run 外：**不能装作没有标题包**。
            problems.append("title_pack_lookup_refused:path_escape")
            continue
        kind = _body_kind_problem(candidate, root)
        if kind == "missing":
            continue
        if kind:
            # L2R8-04：目录 / 悬空软链 / FIFO 原先也走 `continue`（= "这篇文章没有标题包"），
            # 于是 `title_failed=0`、`status=ran` —— 与"标题包在但读不出来"一样丢 G14 面。
            if kind == "path_escape":
                problems.append("title_pack_lookup_refused:path_escape")
            else:
                problems.append(
                    f"title_pack_{kind}:{_reason_detail(_run_relative(candidate, root))}"
                )
            continue
        where = _run_relative(candidate, root)
        text, reason = _read_text(candidate, base=root)
        if text is None:
            problems.append(f"title_pack_{reason}")
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            problems.append(f"title_pack_not_json:{where}")
            continue
        except RecursionError:
            problems.append(f"title_pack_too_deep:{where}")
            continue
        if not isinstance(payload, Mapping):
            problems.append(f"title_pack_not_mapping:{type(payload).__name__}:{where}")
            continue
        directions = payload.get("directions")
        if isinstance(directions, list):
            for direction in directions:
                if isinstance(direction, Mapping) and direction.get("selected"):
                    candidate_title = direction.get("title")
                    if isinstance(candidate_title, str) and candidate_title.strip():
                        return candidate_title.strip(), ""
                    # L2R10-04：`selected: true` 却给不出标题（缺键 / 非串 / 全空白）。
                    # 选中的那一条就是权威，不再往下猜，且必须与"没有标题包"分开报。
                    problems.append(f"title_pack_selected_title_empty:{where}")
                    return "", problems[-1]
        # pilot 版式（dsh-pilot-case-*）：被选中标题直接是 `selected_title` 字符串。
        selected = payload.get("selected_title")
        if isinstance(selected, str) and selected.strip():
            return selected.strip(), ""
        # L2R10-04（不变量 C）：包**在**、能解析，却给不出可用标题 —— 初版这里直接
        # `return "", ""`，于是 `{"directions":[{"selected":true}]}`、`{"directions":[]}`、
        # `{"selected_title":123}` 三种形状与"这篇本来没有标题包"逐字段同形
        # （`title=null` / 无 `title_failed` / `errors=[]` / `status=ran` / rc=0），
        # 丢的正是 G14（标题党 / 标题与正文不一致）这条**唯一**的标题检查面。
        # 全空白标题也不再拿去扫（扫空白毫无意义，只会让"扫过了"看起来成立）。
        problems.append(
            f"title_pack_no_usable_title:{_reason_detail(type(selected).__name__)}:{where}"
        )
        return "", problems[-1]
    return "", (problems[-1] if problems else "")


def _is_scalar(value: Any) -> bool:
    """能安全回显进记录的标量（bool/int/float/str/None）。"""
    return value is None or isinstance(value, (bool, int, float, str))


def _echo_declaration(declaration: Mapping[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    """只回显白名单键，**值也只回显标量**（L2-07 + L2R10-02）。

    L2-07 只挡了*顶层键*：`{"enabled": {"pass": true}}` 这种把伪造键藏在**值**里的写法，
    回显时会把 `pass` 原样带进**落盘的 run 级记录**（`run_gates` 会把它写进
    `review/gates/publish-precheck-advisory.json`，不是只在 CLI stdout 里）—— 不变量 A
    就被一个嵌套 mapping 推翻了。所以：标量原样；列表只收标量元素；**任何 Mapping 值
    一律不回显**，键名进 `declaration_nested_keys` 供追溯。
    """
    if not declaration:
        return {}, []
    echoed: dict[str, Any] = {}
    ignored: list[str] = []
    nested: list[str] = []
    for key, value in declaration.items():
        if not (key in DECLARATION_KEYS or str(key).startswith("_")):
            ignored.append(str(key))
            continue
        name = str(key)
        if _is_scalar(value):
            echoed[name] = value
        elif isinstance(value, (list, tuple)):
            items = [item for item in value if _is_scalar(item)]
            if len(items) != len(value):
                nested.append(name)
            echoed[name] = items
        else:
            # Mapping / 其它不可安全回显的值：只留键名，值一概不进记录
            nested.append(name)
    if nested:
        echoed["declaration_nested_keys"] = sorted(set(nested))
    return echoed, sorted(ignored)


def build_publish_precheck_advisory(
    run_root: str | Path,
    *,
    write_article_reports: WriteFn | None = None,
    declaration: Mapping[str, Any] | None = None,
    commercial: bool | None = None,
    industries: Sequence[str] | None = None,
) -> dict[str, Any]:
    """产出补充层记录。**它没有 pass 字段**——这是刻意的，见模块 docstring。"""
    root = Path(run_root)
    skill = skill_dir()
    rules = rules_data_dir()
    decl = load_declaration(root) if declaration is None else dict(declaration)
    vendor = vendor_identity(skill)
    rules_info = rules_identity(rules)

    if commercial is None:
        declared = (decl or {}).get("commercial")
        if isinstance(declared, bool):
            commercial_value, commercial_source = declared, "declaration"
        else:
            commercial_value, commercial_source = DEFAULT_COMMERCIAL, "default_strict"
    else:
        commercial_value, commercial_source = bool(commercial), "cli"

    echoed, ignored_keys = _echo_declaration(decl)

    def _options(industry_values: Sequence[str]) -> dict[str, Any]:
        """L2R12-02：`options` 只反映**真正被采纳**的口径（校验通过之后才构建）。"""
        return {
            "commercial": commercial_value,
            "commercial_source": commercial_source,
            "industries": sorted({str(i) for i in industry_values}),
        }

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "skill_id": SKILL_ID,
        "layer": "advisory",
        "gate_effect": "none",
        "blocking": False,
        "authorizes_publication": False,
        "publication_authorization": "not_authorized",
        "verdict": "advisory_only",
        "note": ADVISORY_NOTE,
        "platform_gap": KNOWN_PLATFORM_GAP,
        "status": "not_run",
        "reason": "",
        "vendor": vendor,
        "rules": rules_info,
        "rules_dir": _rel(rules),
        "declaration": echoed,
        "articles": [],
        "totals": {"articles": 0, "scanned": 0, "failed": 0, "candidates": 0,
                   "personal_hits": 0, "myth_advisories": 0, "title_failed": 0},
        "errors": [],
        "handoff": (
            "候选 ≠ 结论。把 candidates/personal_hits 连同 vendor `references/judgment.md` 与"
            "对应 rules 文档交给独立只读复核，判定结果落进 schemas/dsh-review-contract.json 形状，"
            "再经 dsh_review 记录；本层不得被引用为发布依据。"
        ),
    }
    if ignored_keys:
        record["declaration_ignored_keys"] = ignored_keys

    # L2R3-02：坏声明原先被当成"没声明"，静默回退成扫 drafts/ 全量 —— 而声明的本意是
    # **收窄**范围，坏掉之后范围反而被放大（实测合法声明 scanned=1，声明写成 `[]` 后
    # scanned=2），且 status=ran / errors=[] 一点痕迹都没有。校验缺席必须等于失败。
    decl_problem = _declaration_problem(decl)
    if decl_problem:
        record["status"] = "error"
        record["reason"] = decl_problem
        record["errors"].append(decl_problem)
        record["options"] = _options(())  # 声明被拒 → 它的 industries 一律不生效
        return record

    # L2R10-05：`articles` 的类型早就 fail-closed，`enabled` / `industries` / `commercial`
    # 却还在被静默忽略 —— 用户写了 `{"enabled": "false"}`（想关掉这一层）却照样扫、
    # `{"industries": "medical"}` 被读成 `[]`、`{"commercial": "false"}` 静默从严，
    # 三者都 `status=ran` / `errors=[]`，与一次干净扫描逐字段同形。类型不对就整层 error。
    type_problem = _declaration_type_problem(decl)
    if type_problem:
        record["status"] = "error"
        record["reason"] = type_problem
        record["errors"].append(type_problem)
        record["options"] = _options(())  # 复核方实测：被拒的 industries 以前仍进了 options
        return record

    # L2R12-02（minor，真）：`options` 以前在**校验之前**就构建完毕，于是
    # `{"industries":["medical",3]}` 虽然整层 error、`scanned=0`，记录里
    # `options.industries` 仍是 `["3","medical"]` —— "拒了却仍然生效"。构建点现在移到
    # 类型校验之后，两个拒绝分支显式给空口径（此前 :1244 的注释宣称"根本不会被构建"，
    # 与实现不符；现在实现才对得上那句注释）。
    declared_industries = (decl or {}).get("industries")
    if industries is None:
        industries_value = (
            [str(i) for i in declared_industries] if isinstance(declared_industries, list) else []
        )
    else:
        industries_value = [str(i) for i in industries]
    record["options"] = _options(industries_value)

    enabled = (decl or {}).get("enabled")
    if enabled is False:
        record["reason"] = "disabled_by_declaration"
        return record
    if not (skill / "scripts" / "scan.py").is_file():
        record["reason"] = f"skill_missing:{_rel(skill)}"
        return record
    if not rules_info["exists"]:
        record["reason"] = f"rules_missing:{_rel(rules)}"
        return record
    # 第 10 轮 F2（major）：规则目录**在位却一条都没装载**（悬空软链 / my-rules.md 是目录 /
    # 目录不可读 / 声明了黑名单区段却 0 行）原先一律走成 `ran + 0 命中` —— 与"扫过且干净"
    # 逐字段同形。这里升级成显式 error（`scan_text` 里的 `rules_unstaged:` 是第二道）。
    unstaged = _rules_unstaged_problem(rules_info, rules)
    if unstaged:
        record["status"] = "error"
        record["reason"] = unstaged
        record["errors"].append(unstaged)
        return record
    # L2R9-02（major）：vendor 的读点出现"存在但非普通文件"（FIFO/目录/悬空软链）必须
    # fail-closed。放在 `skill_missing` 之后是为了保留既有的"整目录缺失 → skill_missing"
    # 语义；能走到这里说明 `scripts/scan.py` 是普通文件，问题只可能出在 `terms.json` 上。
    if vendor.get("problem"):
        record["status"] = "error"
        record["reason"] = str(vendor["problem"])
        record["errors"].append(str(vendor["problem"]))
        return record

    # L2R5-01：vendor 完整性不只关系"词表还在不在"，还关系**产出候选的那段代码**在不在。
    # 逐篇扫描各自校验一次（见 `scan_text`），这里再在 run 级留一份快照 —— 让记录本身
    # 就能回答"这次跑的是哪一版 vendor、清单项逐条对不对得上"，而不用翻逐篇报告。
    record["terms"] = verify_terms_table(skill)
    record["vendor_manifest"] = verify_vendor_manifest(skill)

    articles = _declared_articles(decl, root)
    if not articles:
        record["reason"] = "no_articles_to_scan"
        return record

    reports: list[dict[str, Any]] = []
    for article_id, body_path, error_reason, id_source, id_problem in articles:
        if error_reason or body_path is None:
            report = _blank_article(article_id, "")
            report["reason"] = error_reason or "missing_body_path"
            if id_source:
                report["article_id_note"] = id_source
            reports.append(report)
            record["errors"].append(f"{article_id}:error:{report['reason']}")
            # 被拒的 id **绝不**进写路径：否则拒绝逻辑本身成了越界写入通道。
            if write_article_reports is not None:
                if safe_article_id(article_id):
                    _try_write_article(write_article_reports, article_id, report, record, root)
                else:
                    # L2R11-10：glob 发现的目录名可能过不了写路径白名单（`drafts/解说稿-001/`），
                    # 原先一声不响地不写 —— 与"写成了"在记录里同形。现在留痕（可见但非阻断）。
                    skipped = f"{_reason_detail(article_id)}:invalid_article_id"
                    record.setdefault("write_skipped", []).append(skipped)
                    record.setdefault("errors", []).append(
                        f"{skipped}:evidence_write_skipped:unsafe_article_id"
                    )
            continue
        title, title_problem = _selected_title(
            root, article_id, allow_root_pack=_uses_run_root_draft(root, body_path)
        )
        report = _article_report(
            article_id,
            body_path,
            run_root=root,
            commercial=commercial_value,
            industries=industries_value,
            skill=skill,
            rules=rules,
            title=title,
            title_problem=title_problem,
        )
        if id_source:
            report["article_id_note"] = id_source
        if id_problem:
            # L2R3-04 / 残留 1：manifest 读不出来时 id 是猜的，而 id 决定逐篇证据落到
            # `review/<id>/` —— "正文扫了、但证明不了是哪一篇"不许报 ran（初版完全无痕）。
            if report["status"] == "ran":
                report["status"] = "partial"
            report["reason"] = (
                f"{report['reason']}|id_unverified:{id_problem}"
                if report["reason"]
                else f"id_unverified:{id_problem}"
            )
        reports.append(report)
        if report["status"] != "ran":
            record["errors"].append(f"{article_id}:{report['status']}:{report['reason']}")
        # L2R10-06：错误分支早有 `safe_article_id` 白名单（:1451），正常分支却没有 ——
        # 于是 `drafts/解说稿-001/` 这种过不了**写路径**白名单的 id 照样去请求
        # `review/解说稿-001/publish-precheck.json`，"被拒的 id 绝不进写路径"名不副实。
        # 读路径不收白名单（L2R4-01），**写**路径必须收：两处口径一致。
        if write_article_reports is not None:
            if safe_article_id(article_id):
                _try_write_article(write_article_reports, article_id, report, record, root)
            else:
                # L2R11-10：见上（错误分支同一留痕口径）。
                skipped = f"{_reason_detail(article_id)}:invalid_article_id"
                record.setdefault("write_skipped", []).append(skipped)
                record.setdefault("errors", []).append(
                    f"{skipped}:evidence_write_skipped:unsafe_article_id"
                )

    scanned = [r for r in reports if r["status"] == "ran"]
    # 有正文扫成了、只是子面（标题）没扫完，也算"有进展" → partial，不是 error。
    progressed = [r for r in reports if r["status"] in {"ran", "partial"}]
    record["articles"] = reports
    record["totals"] = {
        "articles": len(reports),
        "scanned": len(scanned),
        "failed": len(reports) - len(scanned),
        "candidates": sum(r["candidate_count"] for r in scanned),
        "personal_hits": sum(len(r["personal_hits"]) for r in scanned),
        "myth_advisories": sum(len(r["myth_advisories"]) for r in scanned),
        "title_failed": sum(1 for r in reports if r.get("title_failed")),
    }
    if len(scanned) == len(reports):
        record["status"] = "ran"
    elif progressed:
        record["status"] = "partial"
        record["reason"] = "some_scans_failed"
    else:
        record["status"] = "error"
        record["reason"] = "all_scans_failed"
    # 第 11 轮 finding 2：措辞抽到 `_personal_rules_note()`，与 ad-hoc（CLI）记录共用一份。
    note = _personal_rules_note(rules_info)
    if note:
        record["personal_rules_note"] = note
    return record


def _write_target_problem(run_root: Path, rel: str) -> str:
    """写路径的**容器**判定（L2R11-09）：返回 ""=可写，否则是原因串。

    写路径的字符串形态已被白名单管住，但**目录本身**可以是越界软链：`review/gates/` 若是指向
    run 外的软链（或 `review/<id>/` 是），记录与逐篇证据会一声不响落到 run 之外，而调用方与
    记录都以为它落在 run 里（L2R4-03 / L2R7-01 修的都是"文件"那一层，这是"目录"层）。
    纯 `resolve()`/`stat`，不对目标 `open()`。
    """
    root = Path(run_root)
    try:
        resolved_root = root.resolve()
        resolved_parent = (root / rel).parent.resolve()
    except (OSError, RuntimeError):
        return "write_path_unresolvable"
    if resolved_parent != resolved_root and not resolved_parent.is_relative_to(resolved_root):
        return "path_escape"
    return ""


#: 公开别名：宿主侧（`run_gates` 写 `review/gates/…` 记录）要用同一个容器判据（L2R11-09）。
write_target_problem = _write_target_problem


def _try_write_article(
    write: WriteFn,
    article_id: str,
    report: Mapping[str, Any],
    record: dict[str, Any],
    run_root: Path,
) -> None:
    """逐篇写失败不许让整批结果在 run 级消失（L2-12）；容器越界同样显形（L2R11-09）。"""
    rel = f"review/{article_id}/publish-precheck.json"
    problem = _write_target_problem(run_root, rel)
    if problem:
        # L2R11-09：容器是越界软链 → **不写**（否则证据落到 run 之外而记录一无所知），
        # 但必须显形为可查据（`write_refused:path_escape:<rel>`），不是静默跳过。
        record.setdefault("errors", []).append(f"write_refused:{problem}:{rel}")
        record.setdefault("write_refused", []).append(rel)
        return
    try:
        write(rel, report)
    except Exception as exc:  # noqa: BLE001 — 留痕优先，失败要显形
        record.setdefault("errors", []).append(
            f"{article_id}:write_failed:{type(exc).__name__}:{exc}"
        )
        record.setdefault("write_failures", []).append(article_id)


def candidate_findings_for_reviewer(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """把候选摊成给**复核者**看的输入清单——每项都标 `unjudged`。

    刻意不套 `schemas/dsh-review-contract.json` 的 finding 形状：那个形状代表"已判定"，
    一填进去就等于本层自任裁判。复核者的结论必须由复核者自己写。

    L2-06：自有规则命中（my-rules）在上游返回里只有 `reason`/`level`/`mode`，没有
    `rule`/`title`/`doc`；初版照抄导致自有来源三项全空，且测试因规则目录为空而从未覆盖。
    """
    out: list[dict[str, Any]] = []
    for article in record.get("articles", []) or []:
        if not isinstance(article, Mapping):
            continue
        aid = str(article.get("article_id") or "")
        title_block = article.get("title") if isinstance(article.get("title"), Mapping) else {}
        for surface, source, items in (
            ("body", "official", article.get("candidates") or []),
            ("body", "my-rules", article.get("personal_hits") or []),
            ("title", "official", title_block.get("candidates") or []),
            ("title", "my-rules", title_block.get("personal_hits") or []),
        ):
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                match = str(item.get("match", ""))
                if source == "official":
                    rule = str(item.get("rule", ""))
                    title = str(item.get("title", ""))
                    doc = str(item.get("doc", ""))
                    severity_hint = str(item.get("severity", ""))
                else:
                    # 自有规则的"身份"就是命中的词面（黑名单第一列即正则/词）+
                    # 其"为什么"就是原因列。合成稳定引用，复核者能回 my-rules.md 查。
                    rule = f"my-rules:{match}" if match else "my-rules"
                    title = str(item.get("reason", ""))
                    doc = "my-rules.md"
                    severity_hint = str(item.get("level", ""))
                out.append(
                    {
                        "article_id": aid,
                        "surface": surface,
                        "source": source,
                        "status": "unjudged",
                        "requires_semantic_judgment": True,
                        "rule": rule,
                        "title": title,
                        "severity_hint": severity_hint,
                        "doc": doc,
                        "match": match,
                        "context": str(item.get("context", "")),
                        # L2R11-02：这三个字段也走"只收标量"—— vendor 把容器塞进
                        # `line`/`start`/`end` 时，清单同样会把嵌套的 `pass` 键摊给复核者。
                        "line": _scalar_or_none(item.get("line")),
                        "start": _scalar_or_none(item.get("start")),
                        "end": _scalar_or_none(item.get("end")),
                        "mode": str(item.get("mode", "")),
                        "muted_by_whitelist": bool(item.get("muted_by_whitelist")),
                    }
                )
    return out


def _scalar_or_none(value: Any) -> Any:
    """非标量降级成 `None`（L2R11-02：复核清单里的 `line/start/end` 只许是标量）。"""
    return value if _is_scalar(value) and not isinstance(value, bool) else None


# --------------------------------------------------------------------------- CLI


def _write_record(run_root: str | Path, record: Mapping[str, Any]) -> str:
    from article_group import evidence_write

    path = GATE_RECORD_PATH
    # L2R11-09：容器越界（`review/gates` 是外链软链）时**不写** —— 否则记录悄悄落到 run 之外，
    # 而 CLI 会打印"已写入"。
    problem = _write_target_problem(Path(run_root), path)
    if problem:
        raise OSError(f"write_refused:{problem}:{path}")
    evidence_write.write_evidence_json(
        path,
        dict(record),
        run_dir=run_root,
        reason="发布前审补充层：词面预检候选（advisory，不阻断）",
        author="publish_precheck",
    )
    return path


def _format_summary(record: Mapping[str, Any]) -> str:
    """人读摘要。**故意不打印「通过/不通过」**——本层没有这个结论。"""
    vendor = record.get("vendor") or {}
    options = record.get("options") or {}
    rules = record.get("rules") or {}
    lines = [
        f"发布前审补充层（advisory，不阻断）  状态：{record.get('status')}"
        + (f"（{record.get('reason')}）" if record.get("reason") else ""),
        f"  vendor: {vendor.get('skill_dir')} @ {str(vendor.get('commit') or '')[:12]}",
        f"  规则表: {record.get('rules_dir')}"
        + (
            f"（{rules.get('file_count')} 文件，黑名单 {rules.get('blacklist_rows')} 条已装载"
            + (
                f"、{rules.get('blacklist_invalid_rows')} 行正则非法未装载"
                if rules.get("blacklist_invalid_rows")
                else ""
            )
            + f"，词表 {rules.get('wordlist_files')} 个 / {rules.get('wordlist_terms')} 条词条"
            f"，可匹配={rules.get('can_match')}）"
            if rules
            else ""
        ),
        f"  商业口径: {options.get('commercial')}（来源 {options.get('commercial_source')}）"
        f"  行业: {options.get('industries') or '无'}",
        "  注意：候选 ≠ 违规结论；零候选 ≠ 安全。语义判定交独立只读复核。",
    ]
    gap = record.get("platform_gap")
    if gap:
        lines.append(f"  覆盖缺口：{gap}")
    note = record.get("personal_rules_note")
    if note:
        lines.append(f"  ⚠ {note}")
    totals = record.get("totals") or {}
    if totals:
        lines.append(
            f"  稿件 {totals.get('articles')}（已扫 {totals.get('scanned')}，失败 {totals.get('failed')}"
            + (
                f"，其中标题未扫 {totals.get('title_failed')}"
                if totals.get("title_failed")
                else ""
            )
            + f"）  候选 {totals.get('candidates')}（自查 {totals.get('personal_hits')}"
            f" / 辟谣提示 {totals.get('myth_advisories')}）"
        )
    if record.get("declaration_ignored_keys"):
        lines.append(f"  声明中未识别、已忽略的键：{record['declaration_ignored_keys']}")
    for article in record.get("articles", []) or []:
        if not isinstance(article, Mapping):
            continue
        triage = article.get("triage") or {}
        head = (
            f"  - {article.get('article_id')} [{article.get('status')}]"
            + (f" {article.get('reason')}" if article.get("reason") else "")
        )
        if article.get("status") in {"ran", "partial"}:
            head += (
                f"  {article.get('characters')} 字 / 候选 {article.get('candidate_count')}"
                f"（先看 {triage.get('review_now', 0)}、记一笔 {triage.get('note', 0)}）"
            )
        lines.append(head)
        if article.get("article_id_note"):
            lines.append(f"      id 来源：{article['article_id_note']}")
        title = article.get("title")
        if isinstance(title, Mapping):
            lines.append(
                f"      标题 [{title.get('status')}] {title.get('text', '')}"
                + (f" — {title.get('reason')}" if title.get("reason") else "")
                + f"（候选 {len(title.get('candidates') or [])}"
                f" / 自查 {len(title.get('personal_hits') or [])}）"
            )
        for item in (article.get("candidates") or []) + (article.get("personal_hits") or []):
            if not isinstance(item, Mapping):
                continue
            label = item.get("severity") or item.get("level") or "?"
            if "reason" in item and "rule" not in item:
                rule, title_text = f"my-rules:{item.get('match', '')}", item.get("reason", "")
            else:
                rule, title_text = item.get("rule", ""), item.get("title", "")
            lines.append(
                f"      · [{label}] {rule} | {title_text} | 命中「{item.get('match', '')}」"
                + (f" | 行 {item.get('line')}" if item.get("line") else "")
            )
        for warning in article.get("parse_warnings") or []:
            lines.append(f"      ! 规则表解析告警：{warning}")
    for failure in record.get("write_failures", []) or []:
        lines.append(f"  ! 逐篇报告写入失败：{failure}")
    # L2R11-09：容器越界被拒写（不是"写失败"）—— 也要在摘要里看得见。
    for refused in record.get("write_refused", []) or []:
        lines.append(f"  ! 逐篇报告写入被拒（容器越界）：{refused}")
    # L2R11-10：glob 发现的 id 过不了写路径白名单时不写 —— 留痕，别与"写成了"同形。
    for skipped in record.get("write_skipped", []) or []:
        lines.append(f"  ! 逐篇报告未写（id 不过写路径白名单）：{skipped}")
    for error in record.get("errors", []) or []:
        lines.append(f"  ! {error}")
    lines.append(f"  交接：{record.get('handoff', '')}")
    return "\n".join(lines)


def _adhoc_record(
    *, status: str, reason: str, raw: Mapping[str, Any] | None, extra: Mapping[str, Any]
) -> dict[str, Any]:
    raw = raw or {}
    # L2R10-01（major）：CLI/临时记录原先也是 `[dict(i) for i in raw[...]]` —— 与 L2R9-05 在
    # `_article_report` 里修掉的**同一类**逐字复制，只是漏了这个记录形状（不变量 A 在这里
    # 被推翻：vendor 输出带 `pass`/`status`/`verdict` 时，CLI 的 `--json` 里就有 `pass`）。
    # 现在两个形状共用同一套白名单投影，多出来的键名只留在 `dropped_vendor_keys`。
    candidates, dropped_c = _project_vendor_items(raw, "candidates", _VENDOR_CANDIDATE_KEYS)
    personal, dropped_p = _project_vendor_items(raw, "personal_hits", _VENDOR_PERSONAL_KEYS)
    myths, dropped_m = _project_vendor_items(raw, "myth_advisories", _VENDOR_MYTH_KEYS)
    dropped = sorted(dropped_c | dropped_p | dropped_m)
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "skill_id": SKILL_ID,
        "layer": "advisory",
        "gate_effect": "none",
        "blocking": False,
        "authorizes_publication": False,
        "publication_authorization": "not_authorized",
        "verdict": "advisory_only",
        "note": ADVISORY_NOTE,
        "platform_gap": KNOWN_PLATFORM_GAP,
        "status": status,
        "reason": reason,
        **extra,
        "articles": [],
        "totals": {},
        "errors": [] if status == "ran" else [reason],
        "handoff": "候选 ≠ 结论；语义判定由复核者做。",
    }
    if status == "ran":
        article = _blank_article("adhoc", "")
        article.update(
            {
                "status": "ran",
                "characters": int(raw.get("characters") or 0),
                "candidates": candidates,
                "personal_hits": personal,
                "myth_advisories": myths,
                "dropped_vendor_keys": dropped,
                # L2R11-02：warnings 里的**值**同样只收标量 —— 一个 `{"pass": true}` 会被
            # `str()` 成 `{'pass': True}` 原样写进记录，四种形状一起漏。
            "parse_warnings": [str(w) for w in raw.get("warnings", []) if _is_scalar(w)],
                "candidate_count": len(candidates),
                "triage": _triage(candidates, personal),
            }
        )
        record["articles"] = [article]
    record["totals"] = {
        "articles": len(record["articles"]),
        "scanned": 1 if status == "ran" else 0,
        "failed": 0 if status == "ran" else 1,
        "candidates": len(candidates) if status == "ran" else 0,
        "personal_hits": len(personal) if status == "ran" else 0,
        "myth_advisories": len(myths) if status == "ran" else 0,
        "title_failed": 0,
    }
    # 第 11 轮 finding 2：ad-hoc（CLI `--text/--file/--json`）记录过去从不带这句 ——
    # 于是 CLI 路线上唯一提示只剩 `可匹配=False`，而 run 级记录里那句
    # 「personal_hits 恒为 0 是**没有规则**，不是**规则放行**」在 CLI 输出里缺席。
    # 与 `build_publish_precheck_advisory` 共用 `_personal_rules_note()`，措辞只有一份。
    rules_info = extra.get("rules")
    if isinstance(rules_info, Mapping):
        note = _personal_rules_note(rules_info)
        if note:
            record["personal_rules_note"] = note
    return record


def _run_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="发布前审补充层（advisory only）")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--run-root",
        help="run 根目录：认 <run>/draft.md（现行 pilot）与 <run>/drafts/<aid>/body_draft.md",
    )
    source.add_argument("--file", type=Path, help="单个稿件文件")
    source.add_argument("--text", help="直接传入文本")
    parser.add_argument("--commercial", dest="commercial", action="store_true", default=None)
    parser.add_argument("--no-commercial", dest="commercial", action="store_false")
    parser.add_argument("--industry", default="", help="逗号分隔：medical,finance")
    parser.add_argument("--json", action="store_true", help="输出 JSON（默认人读摘要）")
    parser.add_argument("--write", action="store_true", help=f"把记录落进 run（{GATE_RECORD_PATH}）")
    args = parser.parse_args(argv)

    industries = [i.strip() for i in args.industry.split(",") if i.strip()] or None

    if args.run_root:
        record = build_publish_precheck_advisory(
            args.run_root, commercial=args.commercial, industries=industries
        )
    else:
        commercial = DEFAULT_COMMERCIAL if args.commercial is None else args.commercial
        source_name = "cli" if args.commercial is not None else "default_strict"
        extra: dict[str, Any] = {
            "vendor": vendor_identity(),
            "rules": rules_identity(),
            "rules_dir": _rel(rules_data_dir()),
            "options": {
                "commercial": commercial,
                "commercial_source": source_name,
                "industries": sorted(industries or []),
            },
        }
        if args.text is not None:
            text: str | None = args.text
        else:
            # L2-11 / L2R2-01：单文件模式也要结构化状态，不要裸回溯（非 UTF-8 也不许崩）。
            # L2R9-03：`--file` 走的是同一把 `open()` —— 指向 FIFO 会**永久阻塞**操作者。
            # 存在但不是普通文件（FIFO/目录/设备）在这里拦住。
            target = Path(args.file)
            if target.exists() and not target.is_file():
                text = None  # 不读（见上），但下面的分支判据要用它
                record = _adhoc_record(
                    status="error",
                    reason=f"body_not_a_file:{_rel(target)}",
                    raw=None,
                    extra=extra,
                )
            else:
                text, read_reason = _read_text(args.file)
                if text is None:
                    record = _adhoc_record(
                        status="not_run",
                        reason=f"body_{read_reason}",
                        raw=None,
                        extra=extra,
                    )
        if text is not None:
            result = scan_text(text, commercial=commercial, industries=industries or ())
            extra["vendor"] = result["vendor"]
            extra["rules"] = result["rules"]
            if result.get("terms"):
                extra["terms"] = result["terms"]
            record = _adhoc_record(
                status=result["status"],
                reason=result["reason"],
                raw=result["raw"],
                extra=extra,
            )

    if args.write:
        if not args.run_root:
            print("--write 需要 --run-root", file=sys.stderr)
            return 1
        try:
            _write_record(args.run_root, record)
        except Exception as exc:  # noqa: BLE001 — L2R2-06：封存 run 上原先裸抛 RunSealedError
            record["status"] = "error"
            # L2R11-09：把原因带进 reason（`write_path_escape` 这类判据不能只剩类型名）。
            record["reason"] = (
                f"record_write_failed:{type(exc).__name__}:{_reason_detail(exc)}"
            )
            record.setdefault("errors", []).append(
                f"record_write_failed:{type(exc).__name__}:{exc}"
            )
            if args.json:
                print(json.dumps(record, ensure_ascii=False, indent=2))
            else:
                print(_format_summary(record))
            print(
                f"ADVISORY WRITE FAILED（记录没落盘，不是通过）: {type(exc).__name__}",
                file=sys.stderr,
            )
            return 1
        print(f"written: {GATE_RECORD_PATH}", file=sys.stderr)

    if args.json:
        print(json.dumps(record, ensure_ascii=False, indent=2))
    else:
        print(_format_summary(record))

    # 退出码只表达"扫描器状态"；候选数量与严重度永不影响它。
    status = record["status"]
    reason = record.get("reason", "")
    if status == "ran":
        return 0
    if status == "error":
        # 措辞别只写"扫描器坏了"：单文件模式的 `--file` 指向 FIFO/目录（L2R9-03）也会走这里，
        # 而那是**调用方给的路径**问题。统一说"不是干净、也不是扫过了"。
        print(f"ADVISORY SCAN ERROR（既不是\"内容干净\"，也不是\"扫过了\"）: {reason}", file=sys.stderr)
        return 1
    if status == "partial":
        failed = (record.get("totals") or {}).get("failed")
        print(
            f"ADVISORY PARTIAL（未扫全，不是通过；失败 {failed} 篇）: {reason}",
            file=sys.stderr,
        )
        return 1
    # not_run：良性（没什么可扫）允许 0；其余一律非零，未知原因 fail-closed。
    if reason in BENIGN_NOT_RUN_REASONS:
        print(f"ADVISORY NOT RUN（不是通过）: {reason}", file=sys.stderr)
        return 0
    print(f"ADVISORY NOT RUN（扫描器不可用，不是通过）: {reason}", file=sys.stderr)
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 兜底：**任何**未预期的异常都不许变成裸回溯（L2R2-01）。

    docstring 承诺"任何故障都落成 status=error / not_run"；各分支已各自返回结构化状态，
    这里是最后一道网 —— 万一仍漏掉某个抛点，至少给出一行文档化的 stderr 说明与非零码，
    而不是让使用者面对 traceback 去猜"到底扫没扫"。
    """
    try:
        return _run_cli(argv)
    except Exception as exc:  # noqa: BLE001 — 兜底网，故意宽
        print(
            f"ADVISORY SCAN ERROR（扫描器内部故障，不是通过）: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
