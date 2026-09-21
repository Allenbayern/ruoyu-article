"""覆盖 lint：能写 run 的模块，必须在护栏内，或在名单上写明理由。

为什么需要（2026-09-17）：护栏（`runs_guard` 的 audit hook）只在 **import 过
`article_group` 的进程**里生效；留底通道（`evidence_write`）又要求写手主动接入。
两者都靠"记得"，而记忆会漏。本测试把"谁能够写 run"变成一张**必须维护的清单**：

- 新写手出现 → 测试失败，直到你把它登记成"护栏内 / 范围外（附理由）/ 待收口（附下一步）"；
- 名单里过期条目（模块已删或不再写 run）→ 同样失败，防止名单变成摆设；
- `PENDING` 是**明处的欠账**，不是许可：它们只是被运行时护栏兜住，仍应逐个接入留底通道。

探针是启发式的（`run_dir|run_root|batch_dir|ROOT|RUN_ROOT|RUN_ID` + 常见写调用）；它的
失效方向是**漏检**，所以它不构成"已全保"的证明——真正的保证来自 `runs_guard` 的运行时拦截。
2026-09-18（B7′）补上 `ROOT|RUN_ROOT|RUN_ID`：spec 模块与 `generate_daily_00X` 用的是
模块级 `ROOT`，此前**整个扫不到**，其中 base 的写还真的绕过了留底通道（daily-009 有
63/152 个文件无账）。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

RUN_HINTS = re.compile(r"\brun_dir\b|\brun_root\b|\bbatch_dir\b|\bROOT\b|\bRUN_ROOT\b|\bRUN_ID\b")
WRITE_CALLS = re.compile(
    r"write_text\(|write_bytes\(|json\.dump\(|shutil\.copy|shutil\.move|copytree\(|"
    r"rmtree\(|os\.replace\(|os\.remove\(|os\.unlink\(|os\.rename\(|os\.makedirs\(|"
    r"\.mkdir\(|\bopen\([^)]*[\"'][wax]"
)
GUARD_IMPORT = re.compile(r"^\s*(?:from|import)\s+article_group", re.M)
SCAN_DIRS = ("article_group", "scripts")
# 留底通道：写 run 证据的正规路径。**没走它的写手一律要登记**（含 in-package 模块）——
# 否则"新写手裸写"会静默通过，而这正是 2026-09-17 新管线落地时发生的事。
CHANNEL = re.compile(r"evidence_write|write_evidence")

# ── 范围外：验证过"写不到封存 run 的证据"的模块，附理由（不是豁免，是判定） ──
OUT_OF_SCOPE: dict[str, str] = {
    # 只写自己的 CLI 产物 / 报告，不写 run 内证据
    "article_group/toutiao_capture.py": "抓取快照：'x' 独占创建，文件已存在即失败，不覆盖既有证据",
    "article_group/wechat_capture.py": "抓取快照：'x' 独占创建，同上",
    "article_group/step_log.py": "append-only 时间线：护栏按契约放行追加（'a' 同目录同文件），重写/删除仍拦",
    "scripts/markdown_review_audit.py": "只写显式 --output 审计报告",
    "scripts/markdown_style_audit.py": "只写显式 --output 报告目录",
    "scripts/codex_viral_library_index.py": "只写显式 --output 索引报告（读 run 卡，不写 run）",
    "scripts/article_group_controller.py": "只写显式 --output 控制面产物",
    "scripts/mp_fetch.py": "写 runs/<date>/ 抓取候选（日目录，非 run 目录）",
    "scripts/mp_search.py": "写 runs/<date>/ 抓取候选（日目录，非 run 目录）",
    "scripts/sogou_fetch.py": "写 runs/<date>/ 抓取候选（日目录，非 run 目录）",
    "scripts/run_sandbox.py": "只写 /tmp 副本（副本内 SEALED 已改名为 from-source）",
    # 历史/一次性
    "scripts/run_daily_005_record_review.py": "历史一次性脚本（daily-005 录制复核），已定格不再用于新 run",
    "scripts/run_real_daily_003.py": "历史一次性生成器（daily-003，自带 main() 直接写 run），已定格",
    "scripts/run_real_daily_004.py": "历史一次性生成器（daily-004），已定格",
    "scripts/generate_daily_002.py": "历史一次性生成器（daily-002），已定格；同 run_real_daily_004",
    # spec 数据模块：只定义数据与裸写函数，唯一入口是 __main__ → daily_engine.build_run，
    # build_run 会把 spec 的 write_json/write_text 包进留底通道后才调用（见
    # tests/test_daily_engine_staging.py::test_spec_writers_go_through_the_channel）。
    "scripts/run_real_daily_005.py": "spec 数据模块（daily-005）：入口 daily_engine.build_run，写函数在 bind_spec 里被包进通道",
    "scripts/run_real_daily_006.py": "spec 数据模块（daily-006）：同上",
    "scripts/run_real_daily_007.py": "spec 数据模块（daily-007）：同上",
    "scripts/run_real_daily_008.py": "spec 数据模块（daily-008）：同上",
    "scripts/run_real_daily_009.py": "spec 数据模块（daily-009）：同上",
    "scripts/run_real_daily_010.py": "spec 数据模块（daily-010）：入口同样是 daily_engine.build_run；除数据外只在 §8 包装 "
                                     "base.content_record/topic_cards/title_records/editorial_record，包装内的回写一律调 "
                                     "base.write_json（bind_spec 已把它换成走通道的版本），不直接落盘",
    # 引擎共用 helper：活动入口只有 build_run，bind_spec 已把它的写函数换成走通道的版本。
    "scripts/generate_daily_001.py": "引擎共用 helper（base）：bind_spec 把 base.write_json/write_text 换成走通道的版本；"
                                     "自带 ROOT 是历史 daily-001，直接跑属历史重跑",
    # 其它位置
    "scripts/gen_sources_021.py": "写 runs/<date>/ 证据文件（日目录，非 run 目录）；与 mp_fetch 同口径",
    "scripts/preview_route_audit.py": "审计 CLI：ROOT 指仓库根，只写显式 --output 报告",
    "scripts/move_completed_20260807.py": "视频隔离区搬运（/vol2 素材盘；RUN_ID 是隔离批次号，不写 runs/ 下的文章 run）",
    "scripts/move_completed_to_quarantine.py": "视频隔离区搬运（同上，2026-08-06 批次）",
    "scripts/patches/2026-09-17-mac/patch_daily_engine_wechat.py": "一次性补丁：改仓库源码，不写 run",
    "scripts/patches/2026-09-17-mac/patch_evidence_rebind.py": "一次性补丁：改仓库源码，不写 run",
    "scripts/patches/2026-09-17-mac/patch_closed_run_guard.py": "一次性补丁：改仓库源码，不写 run",
    "scripts/patches/2026-09-17-mac/patch_daily_engine_step_log.py": "一次性补丁：改仓库源码，不写 run",
    "scripts/patches/2026-09-17-mac/patch_evidence_write.py": "一次性补丁：改仓库源码，不写 run",
    "scripts/patches/2026-09-17-mac/patch_ledger_precheck.py": "一次性补丁：改仓库源码，不写 run",
    "scripts/patches/2026-09-17-mac/patch_title_freeze.py": "一次性补丁：改仓库源码，不写 run",
    # 破坏性工具（按设计销毁，且自带 --purge --yes 双确认）
    "scripts/purge_quarantine.py": "隔离区清理工具：按设计整 run 删除（--purge --yes 双确认）；不属写入通道，"
                                   "但它清空的 run 若是封存 run，等于绕开护栏——需 controller 决定是否禁止",
}

# ── 待收口：确实写 run 内证据、但还没走留底通道（运行时由护栏兜住） ──
# 2026-09-18 收口（B1）：assertion_ledger_coverage 的报告改写走 write_report → evidence_write。
# 2026-09-17 第二批收口（已改走通道、从此不在名单里）：codex_review（L2 复核记录 + 日志）、
# delivery（纯文本交付副本）、content_delivery（交付记录）、daily_engine（引擎产物）。
# 第三批：新管线三个写手（cards / package / distill）改为"产物自带 integrity 为主 +
# run 账本一条产物级锚点"（见 evidence_write.anchor_artifact），也不再欠账。
PENDING: dict[str, str] = {
    "article_group/v4/verification.py": "旁路校验产物（v4 冻结层）：接入前先确认是否仍在用",
    "article_group/v5/verification.py": "旁路校验产物（v5 冻结层）：同上",
    "scripts/codex_daily_article_runner.py": "消费清单按路径写、可覆盖（有读回校验但无留底）：下一步接入留底通道或改成 new-only",
}


def _scan() -> dict[str, dict[str, bool]]:
    found: dict[str, dict[str, bool]] = {}
    for base in SCAN_DIRS:
        for path in sorted((REPO_ROOT / base).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if not (RUN_HINTS.search(text) and WRITE_CALLS.search(text)):
                continue
            relative = path.relative_to(REPO_ROOT).as_posix()
            found[relative] = {
                "in_package": relative.startswith("article_group/"),
                "imports_package": bool(GUARD_IMPORT.search(text)),
            }
    return found


def _guard_covered(info: dict[str, bool]) -> bool:
    """in-package 的模块必然经包 __init__ 导入 → 护栏自动装上。"""
    return info["in_package"] or info["imports_package"]


def test_probe_sees_the_spec_modules_and_the_shared_helper() -> None:
    """B7′：spec 与 base 用的是模块级 ``ROOT``，探针必须看得见它们。

    2026-09-18 之前，``run_real_daily_009.py``（写 run 的 spec）与
    ``generate_daily_001.py``（引擎共用 helper）都在扫描范围外，于是它们的裸写
    既没被登记，也没人发现 base 的写绕过了留底通道。
    """

    found = _scan()
    for name in (
        "scripts/run_real_daily_008.py",
        "scripts/run_real_daily_009.py",
        "scripts/generate_daily_001.py",
    ):
        assert name in found, f"探针又看不见 {name} 了（RUN_HINTS 退化了？）"


def test_every_run_writer_is_classified() -> None:
    found = _scan()
    assert found, "探针失效：一个 run 写手都没扫到，检查 RUN_HINTS/WRITE_CALLS"

    unclassified = sorted(
        name for name, info in found.items()
        if not _guard_covered(info) and name not in OUT_OF_SCOPE and name not in PENDING
    )
    assert not unclassified, (
        "以下模块能写 run，却既不在护栏内（未 import article_group），也没登记理由：\n  "
        + "\n  ".join(unclassified)
        + "\n请二选一：① 让它 import article_group（护栏生效）；"
          "② 写清为什么它写不到封存 run 的证据，加进 OUT_OF_SCOPE；"
          "③ 确认是真欠账，加进 PENDING 并写下下一步。"
    )

    unguarded_pending = sorted(
        name for name in PENDING
        if not _guard_covered(found.get(name, {"in_package": False, "imports_package": False}))
    )
    assert not unguarded_pending, (
        "PENDING 里的模块连运行时护栏都没兜住（未 import article_group）：\n  "
        + "\n  ".join(unguarded_pending)
        + "\n先让它 import article_group，再谈接入留底通道。"
    )


def test_writers_bypassing_the_snapshot_channel_are_listed() -> None:
    """盲点修复（2026-09-17）：in-package ≠ 已接入留底通道。

    护栏只管"封存 run 写不进去"；**没走留底通道**的写手在未封存的 run 上照样裸写、
    无 before image、无 changelog。此前 in-package 模块靠 `_guard_covered` 静默通过，
    新管线（viral_research_*）因此裸写了 2000+ 行而无人提示。现在：没走通道就必须登记。
    """
    found = _scan()
    unlisted = sorted(
        name for name in found
        if not CHANNEL.search((REPO_ROOT / name).read_text(encoding="utf-8"))
        and name not in OUT_OF_SCOPE
        and name not in PENDING
    )
    assert not unlisted, (
        "以下模块写 run 但没走留底通道，且未登记理由：\n  "
        + "\n  ".join(unlisted)
        + "\n二选一：① 接入 evidence_write（留底+记账）；"
          "② 加进 OUT_OF_SCOPE（说明为什么它写不到 run 内证据）或 PENDING（写明下一步）。"
    )


def test_classification_lists_have_no_stale_entries() -> None:
    found = _scan()
    stale = sorted(name for name in list(OUT_OF_SCOPE) + list(PENDING) if name not in found)
    assert not stale, (
        "名单里有过期条目（模块已删或不再写 run）：\n  " + "\n  ".join(stale)
        + "\n名单是清单不是纪念册：删掉或修正它。"
    )


def test_reasons_are_written_out() -> None:
    empty = sorted(name for name, reason in {**OUT_OF_SCOPE, **PENDING}.items() if not reason.strip())
    assert not empty, f"这些条目没有理由：{empty}（名单必须能被人复核，不能只是名字）"


def test_pending_debt_is_visible() -> None:
    """欠账要能一眼数出来（在报告里如实写，不要藏在绿测试后面）。"""
    pending = sorted(PENDING)
    print(f"\n[runs 覆盖 lint] 范围内模块 {len(_scan())} 个；待收口 {len(pending)} 个：")
    for name in pending:
        print(f"  - {name}：{PENDING[name]}")
    assert pending == sorted(pending)
