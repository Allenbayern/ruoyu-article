"""契约值迁移（`codex` → `dsh`）的兼容契约（2026-09-25，备案 §七）。

为什么单开一个文件：这次迁移跨 7 个契约族，**读端兼容**这件事散在各自的模块里，
需要一个地方一次性把"旧值仍然可读"钉住——否则某次重构把某个 `LEGACY_*` 删掉，
只有对应模块自己的用例会红，而"历史产物读不出来了"这件事要到线上才发现。

三个不变量，每个族都要满足：

1. **现值**是我们今天**写出去**的值（`dsh-*`）；
2. **历史值**在 `LEGACY_*` 里，且被 `ACCEPTED_*` 收录；
3. **历史产物不重写**：所以读端认历史值这件事本身必须有断言（下面的断言就是它）。

`article_group.review_surface` / `preview_contract` 两族的兼容用例在各自模块的
测试里（那里有真实夹具与证据文件可跑），这里不重复。
"""
from __future__ import annotations

import json
from pathlib import Path


def test_review_contract_schema_version_accepts_historical_records() -> None:
    from article_group import dsh_review

    assert dsh_review.SCHEMA_VERSION == "dsh-review-contract-1.0"
    # 实测补出来的第二个历史值：复核**超时**的兄弟形状（§七 清单里没有）
    assert dsh_review.LEGACY_SCHEMA_VERSIONS == (
        "codex-review-contract-1.0", "codex-l2-review-timeout-v1")
    assert set(dsh_review.ACCEPTED_SCHEMA_VERSIONS) == {
        "dsh-review-contract-1.0", "codex-review-contract-1.0", "codex-l2-review-timeout-v1"}

    assert dsh_review.is_review_contract_record({"schema_version": "dsh-review-contract-1.0"})
    assert dsh_review.is_review_contract_record({"schema_version": "codex-review-contract-1.0"})
    assert dsh_review.is_review_contract_record({"schema_version": "codex-l2-review-timeout-v1"})
    assert not dsh_review.is_review_contract_record({"schema_version": "article-independent-review-v1"})
    assert not dsh_review.is_review_contract_record({"schema_version": "dsh-review-contract-2.0"})
    assert not dsh_review.is_review_contract_record({"schema_version": None})
    assert not dsh_review.is_review_contract_record(None)
    assert not dsh_review.is_review_contract_record([])


def test_real_historical_review_records_still_parse_as_this_contract() -> None:
    """真实历史产物：`runs/` 里 2026-09-25 之前写的复核记录仍被认成本契约形状。

    这些文件不进版本库（`runs/` 被刻意排除），所以本用例在没有历史的干净检出里
    自动跳过——**跳过要说明原因**，不能静默。
    """
    import pytest

    from article_group import dsh_review

    runs = Path(__file__).resolve().parents[1] / "runs"
    records = sorted(runs.glob("**/review/**/*l2-review*.json")) if runs.is_dir() else []
    if not records:
        pytest.skip("干净检出（runs/ 不入版本库）：无历史复核记录可验")
    checked = 0
    for path in records:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or "schema_version" not in payload:
            continue
        checked += 1
        assert dsh_review.is_review_contract_record(payload), (str(path), payload.get("schema_version"))
    assert checked, "找到了文件却没有一份带 schema_version —— 断言退化成恒真了"


#: 2026-09-25 实测冻结的**历史 schema_version 全集**。
#: 来源：扫描 `runs/` 下 2534 个 json（+ `review/**/*l2-review*.json` 单列），
#: 含 `codex` 的 schema_version 恰好这 5 种，逐种份数见括注。
#:
#: 为什么把它钉成**字面量**而不是"现场扫 runs/"：`runs/` 只是**部分**被跟踪
#: （`git ls-files runs` = 187 个文件 / 88 个 json），所以干净检出里扫不到任何
#: `codex` schema_version——只靠现场扫描的话，这条防线在新克隆里会**恒真失败**
#: （第四轮复核 major 1 实测：干净检出因此多出 1 个失败）。
#: 钉成字面量之后，它在任何环境里都真的在守卫："有人删掉某个 LEGACY 值就红"。
FROZEN_HISTORICAL_SCHEMA_VERSIONS = {
    "codex-review-contract-1.0",        # 78 份
    "codex-l2-review-timeout-v1",       # 3 份（§七 清单漏登记，实测补出）
    "codex-viral-library-index-v1",     # 2 份
    "codex-viral-library-context-v1",   # 1 份
    "codex-daily-article-consumer/v1",  # 1 份
}


def _all_accepted_schema_versions() -> set[str]:
    """所有族的 `ACCEPTED_*` 并集（每个族都必须把自己的历史值收进去）。"""
    import importlib

    from article_group import dsh_review

    accepted: set[str] = set(dsh_review.ACCEPTED_SCHEMA_VERSIONS)
    for module_name, attr in (
        ("scripts.dsh_daily_article_runner", "ACCEPTED_CONSUMER_SCHEMA_VERSIONS"),
        ("scripts.dsh_viral_library_index", "ACCEPTED_INDEX_SCHEMA_VERSIONS"),
        ("scripts.dsh_viral_library_context", "ACCEPTED_CONTEXT_SCHEMA_VERSIONS"),
        ("scripts.dsh_viral_library_reader", "ACCEPTED_READER_SCHEMA_VERSIONS"),
        ("scripts.dsh_review_audit", "ACCEPTED_AUDIT_SCHEMA_VERSIONS"),
        ("scripts.dsh_skill_inventory", "ACCEPTED_INVENTORY_SCHEMA_VERSIONS"),
    ):
        accepted.update(getattr(importlib.import_module(module_name), attr))
    return accepted


def test_every_measured_historical_schema_version_is_still_accepted() -> None:
    """**这次迁移最要紧的一条**：实测到的每个历史 `codex-*` schema_version 都必须在某个
    `ACCEPTED_*` 里——否则那批历史证据在新读端下就是读不出来的东西。

    它已经赚回一次：`codex-l2-review-timeout-v1`（3 份，
    `runs/2026-09-04/daily-003/…`）在 §七 的清单里根本没登记，是"扫真实产物"抓出来的。

    这条**不依赖 `runs/`**，所以在干净检出里也在真的守卫（现场扫描见下一条）。
    """
    accepted = _all_accepted_schema_versions()
    missing = FROZEN_HISTORICAL_SCHEMA_VERSIONS - accepted
    assert not missing, f"这些历史 schema_version 没有任何 ACCEPTED_* 收录：{sorted(missing)}"
    assert "dsh-review-contract-1.0" in accepted, "现值没进 ACCEPTED_* —— 集合自己就错了"


def test_no_real_historical_schema_version_falls_outside_the_accepted_sets() -> None:
    """现场扫描 `runs/`：**有没有出现清单之外的新形态**。

    与上一条分工：上一条用冻结集合守卫"别删"，这一条用现场数据守卫"别无登记"。

    注意 `runs/` 只是**部分**被跟踪，所以干净检出里扫到的对象不完整；扫不到 `codex`
    值时**显式跳过并说明**，而不是让断言恒真失败——那会变成第四个"干净检出多出来的
    失败"，把真正的信号淹掉（第四轮复核 major 1）。
    """
    import pytest

    accepted = _all_accepted_schema_versions()
    runs = Path(__file__).resolve().parents[1] / "runs"
    if not runs.is_dir():
        pytest.skip("干净检出（runs/ 不入版本库）：无历史产物可扫描")

    scanned = 0
    seen: dict[str, list[str]] = {}
    for path in runs.rglob("*.json"):
        if ".before" in path.parts:
            continue
        scanned += 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        version = payload.get("schema_version")
        if isinstance(version, str) and "codex" in version.lower():
            seen.setdefault(version, []).append(str(path.relative_to(runs.parent)))

    if not seen:
        pytest.skip(
            f"扫了 {scanned} 个 json 但没有含 codex 的 schema_version："
            "这条路径上 runs/ 只是部分跟踪（git ls-files runs = 187 个文件），"
            "本环境的现场数据不足以做这条检查；『别删历史值』由上一条冻结集合守卫"
        )
    assert scanned > 0

    unreadable = {v: paths[:3] for v, paths in seen.items() if v not in accepted}
    assert not unreadable, f"这些历史 schema_version 没有任何 ACCEPTED_* 集合收录：{unreadable}"
    unreadable = {v: paths[:3] for v, paths in seen.items() if v not in accepted}
    assert not unreadable, f"这些历史 schema_version 没有任何 ACCEPTED_* 集合收录：{unreadable}"


def test_viral_library_schema_versions_accept_historical_outputs() -> None:
    import importlib

    reader = importlib.import_module("scripts.dsh_viral_library_reader")
    context = importlib.import_module("scripts.dsh_viral_library_context")

    assert reader.READER_SCHEMA_VERSION == "dsh-viral-library-reader-v1"
    assert reader.LEGACY_READER_SCHEMA_VERSIONS == ("codex-viral-library-reader-v1",)
    assert "codex-viral-library-reader-v1" in reader.ACCEPTED_READER_SCHEMA_VERSIONS

    assert context.CONTEXT_SCHEMA_VERSION == "dsh-viral-library-context-v1"
    assert context.LEGACY_CONTEXT_SCHEMA_VERSIONS == ("codex-viral-library-context-v1",)
    assert "codex-viral-library-context-v1" in context.ACCEPTED_CONTEXT_SCHEMA_VERSIONS


def test_index_and_skill_inventory_write_the_new_schema_versions() -> None:
    """写出去的值必须是新值：**写端只写现值**（历史值只活在读端的 ACCEPTED_* 里）。"""
    import importlib

    index = importlib.import_module("scripts.dsh_viral_library_index")
    inventory = importlib.import_module("scripts.dsh_skill_inventory")
    audit = importlib.import_module("scripts.dsh_review_audit")

    assert index.INDEX_SCHEMA_VERSION == "dsh-viral-library-index-v1"
    assert index.LEGACY_INDEX_SCHEMA_VERSIONS == ("codex-viral-library-index-v1",)
    assert inventory.INVENTORY_SCHEMA_VERSION == "dsh-skill-inventory-1"
    assert inventory.LEGACY_INVENTORY_SCHEMA_VERSIONS == ("codex-skill-inventory-1",)
    assert audit.AUDIT_SCHEMA_VERSION == "dsh-review-audit-1.0"
    assert audit.AUDIT_MANIFEST_SCHEMA_VERSION == "dsh-review-audit-manifest-1.0"
    assert set(audit.LEGACY_AUDIT_SCHEMA_VERSIONS) == {
        "codex-review-audit-1.0", "codex-review-audit-manifest-1.0"}

    root = Path(__file__).resolve().parents[1]
    audit_src = (root / "scripts" / "dsh_review_audit.py").read_text(encoding="utf-8")
    # 月报的产物名与它自己的 schema 一起改（同一族的产物文件名）
    assert 'f"dsh-review-audit-{month}.json"' in audit_src
    # 只钉产物名模板：`codex-review-audit-*` 仍会出现在 LEGACY_* 常量与注释里（那是读端契约）
    assert 'f"codex-review-audit-{month}.json"' not in audit_src


def test_consumer_manifest_name_moves_but_the_old_name_stays_accepted() -> None:
    """消费者 manifest：写端写新名；**旧名仍是读端契约的一部分**（外部消费者可能还在找它）。"""
    import importlib

    module = importlib.import_module("scripts.dsh_daily_article_runner")

    assert module.CONSUMER_MANIFEST_NAME == "dsh-daily-article-run.json"
    assert module.LEGACY_CONSUMER_MANIFEST_NAMES == ("codex-daily-article-run.json",)
    assert set(module.ACCEPTED_CONSUMER_MANIFEST_NAMES) == {
        "dsh-daily-article-run.json", "codex-daily-article-run.json"}
    assert module.CONSUMER_MANIFEST_NAME in module.ACCEPTED_CONSUMER_MANIFEST_NAMES


def test_the_two_surfaces_of_the_migration_agree_on_being_legacy_tolerant() -> None:
    """迁移的两个"面值"（审阅面 / 预览模式）也必须保留历史映射——防被顺手删掉。"""
    from article_group.preview_contract import LEGACY_PREVIEW_MODES
    from article_group.review_surface import LEGACY_REVIEW_SURFACES

    assert LEGACY_REVIEW_SURFACES == {"markdown_codex": "markdown_dsh"}
    assert LEGACY_PREVIEW_MODES == {"local_codex": "local_dsh"}


def test_l2_review_record_name_moves_but_the_old_name_still_resolves(tmp_path: Path) -> None:
    """L2 复核产物名：**新名写、旧名读**（旧名有 200 份真实产物，不重写）。"""
    from article_group.evidence_paths import (
        L2_REVIEW_RECORD_NAME,
        LEGACY_L2_REVIEW_RECORD_NAMES,
        resolve_l2_review_record,
    )

    assert L2_REVIEW_RECORD_NAME == "dsh-l2-review.json"
    assert LEGACY_L2_REVIEW_RECORD_NAMES == ("codex-l2-review.json",)

    base = tmp_path / "review" / "art-001"
    base.mkdir(parents=True)
    # 两个都不在 → 返回新名（调用方照旧用 .is_file() 判断，语义不变）
    assert resolve_l2_review_record(tmp_path, "art-001").name == "dsh-l2-review.json"
    # 只有历史名 → 回退到它
    legacy = base / "codex-l2-review.json"
    legacy.write_text("{}", encoding="utf-8")
    assert resolve_l2_review_record(tmp_path, "art-001") == legacy
    # 两个都在 → 新名优先
    new = base / "dsh-l2-review.json"
    new.write_text("{}", encoding="utf-8")
    assert resolve_l2_review_record(tmp_path, "art-001") == new


def test_ledger_reason_prefix_writes_the_new_one_and_keeps_the_alias() -> None:
    """账本原因前缀：新写的行是 `dsh_review:*`；`codex_review` 是**有意的兼容别名**。

    历史 `evidence-changelog.jsonl` 里的 `codex_review:l2` 行不重写（改写历史账目会破坏
    "当时记的是什么"）。`article_group.codex_review` 会显式把前缀改回旧值——那是给旧入口
    留的路，不是漏改。
    """
    from article_group import codex_review, dsh_review

    assert dsh_review.REASON_PREFIX == "dsh_review"
    assert codex_review.REASON_PREFIX == "codex_review"
