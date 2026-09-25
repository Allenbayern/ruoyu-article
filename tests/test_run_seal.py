"""封存全量清单：seal 记清单，verify 逐项重算并区分"有账"与"无账"的改动。

为什么需要：`SEALED` 只有时间/署名/两篇交付哈希。"封存之后有没有被改过"此前无法回答——
`runs/` 不进 git，连副本都没有；运行时护栏挡得住进程内误写，挡不住进程外写入，
更挡不住"写进去了没人知道"。本组用例钉住：

- seal 时清单覆盖 run 内每个文件（size+sha256）+ 标记自身字节哈希；
- 改动/新增/缺失/符号链接变化都能被 verify 指出；
- append-only 文件（step-log / changelog）**追加不算改动、重写算**；
- 与 evidence-changelog 对照，区分"有账的 force 改动"与"无账的可疑改动"；
- 老 run（封存时还没有清单）如实报"无法验证"，`--backfill` 补录且明说证明不了历史。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from article_group import run_seal, runs_guard
from article_group.evidence_write import read_changelog, write_evidence
from article_group.run_state import seal, seal_articles

REPO_ROOT = Path(__file__).resolve().parents[1]


def _sealed_run(tmp_path: Path, name: str = "daily-960") -> Path:
    root = tmp_path / name
    (root / "delivery" / "art-001").mkdir(parents=True)
    (root / "review" / "art-001").mkdir(parents=True)
    (root / "delivery" / "art-001" / "delivery.md").write_text("# 标题\n\n正文。\n", encoding="utf-8")
    (root / "review" / "art-001" / "ledger-coverage-precheck.json").write_text('{"frozen": true}', encoding="utf-8")
    (root / "batch.json").write_text(json.dumps({"articles": [{"article_id": "art-001"}]}), encoding="utf-8")
    (root / "step-log.jsonl").write_text('{"name": "discovery"}\n', encoding="utf-8")
    seal(root, identity="owner", articles=seal_articles(root))
    return root


def _legacy_sealed_run(tmp_path: Path, name: str = "daily-961") -> Path:
    """模拟"封存时还没有 run_seal"的老 run（如 daily-008）：只有 SEALED，没有清单。"""
    root = tmp_path / name
    (root / "review" / "art-001").mkdir(parents=True)
    (root / "batch.json").write_text(json.dumps({"articles": [{"article_id": "art-001"}]}), encoding="utf-8")
    (root / "SEALED").write_text(json.dumps({
        "schema_version": "run-sealed-v1",
        "sealed_at": "2026-09-17T08:45:00+08:00",
        "sealed_by": "owner",
        "seal_ref": "controller 会话确认补封存（当日收尾时尚无 SEALED 机制）",
        "articles": [],
        "publication_authorization": "not_authorized",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    runs_guard.refresh()
    assert run_seal.load_manifest(root) is None
    return root


def _token(root: Path):
    return runs_guard.sealed_write_token(root, reason="test:tamper", author="tester")


# ---- ① seal 写清单 ----


def test_seal_writes_manifest_covering_every_file(tmp_path: Path) -> None:
    root = _sealed_run(tmp_path)
    manifest = run_seal.load_manifest(root)
    assert manifest is not None and manifest["schema_version"] == run_seal.SCHEMA_VERSION

    listed = {item["path"]: item for item in manifest["files"]}
    assert "delivery/art-001/delivery.md" in listed and "batch.json" in listed
    # 排除项不进去：标记自身、清单自身、append-only（它们另按前缀/哈希校验）
    assert not {"SEALED", run_seal.MANIFEST_NAME, "step-log.jsonl"} & set(listed)
    # 每个文件的哈希都对得上（清单不是"声明"，是可重算的）
    for relative, item in listed.items():
        data = (root / relative).read_bytes()
        assert item["size"] == len(data)
        assert item["sha256"] == hashlib.sha256(data).hexdigest()
    # 标记自身的字节也被覆盖
    assert manifest["sealed_marker_sha256"] == hashlib.sha256((root / "SEALED").read_bytes()).hexdigest()
    # append-only 按前缀校验
    assert [item["path"] for item in manifest["append_only"]] == ["step-log.jsonl"]

    report = run_seal.verify(root)
    assert report["status"] == "intact" and report["changes"] == []


# ---- ② 漂移识别 ----


def test_verify_detects_modified_added_and_missing(tmp_path: Path) -> None:
    root = _sealed_run(tmp_path)
    with _token(root):
        (root / "review" / "art-001" / "ledger-coverage-precheck.json").write_text('{"tampered": 1}', encoding="utf-8")
        (root / "review" / "art-001" / "sneaked-in.json").write_text("{}", encoding="utf-8")
        (root / "batch.json").unlink()

    report = run_seal.verify(root)
    assert report["status"] == "drifted"
    kinds = {change["path"]: change["kind"] for change in report["changes"]}
    assert kinds["review/art-001/ledger-coverage-precheck.json"] == "modified"
    assert kinds["review/art-001/sneaked-in.json"] == "added"
    assert kinds["batch.json"] == "missing"
    # 这些改动都没有记账 → 一律列为可疑
    assert len(report["unauthorized_changes"]) == 3


def test_verify_separates_ledgered_force_writes_from_silent_ones(tmp_path: Path) -> None:
    root = _sealed_run(tmp_path)
    write_evidence(
        root / "review" / "art-001" / "ledger-coverage-precheck.json",
        '{"frozen": false}',
        run_dir=root, reason="test:force", author="tester", force=True,
    )
    report = run_seal.verify(root)
    assert report["status"] == "drifted"
    change = next(item for item in report["changes"] if item["kind"] == "modified")
    assert change["authorized"] is True
    assert change["ledger"]["reason"] == "test:force" and change["ledger"]["forced"] is True
    assert report["unauthorized_changes"] == []


# ---- ③ append-only：追加放行，重写算改动 ----


def test_append_only_append_is_intact_but_rewrite_is_drift(tmp_path: Path) -> None:
    root = _sealed_run(tmp_path)
    with (root / "step-log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"name": "seal"}\n')  # 封存动作自己的流水就长这样
    assert run_seal.verify(root)["status"] == "intact"

    with _token(root):
        (root / "step-log.jsonl").write_text('{"name": "rewritten"}\n', encoding="utf-8")
    report = run_seal.verify(root)
    kinds = {change["kind"] for change in report["changes"]}
    assert report["status"] == "drifted"
    assert kinds & {"append_only_rewritten", "append_only_truncated"}


# ---- ④ 老 run：如实说"无法验证"，补录要留痕且不吹牛 ----


def test_verify_without_manifest_is_unverifiable(tmp_path: Path) -> None:
    root = _legacy_sealed_run(tmp_path)  # 封存时还没有 run_seal（如 daily-008）
    report = run_seal.verify(root)
    assert report["status"] == "unverifiable"
    assert "backfill" in report["remedy"]

    result = subprocess.run(
        [sys.executable, "-m", "article_group.run_seal", "--run-root", str(root), "--json"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == run_seal.EXIT_UNVERIFIABLE
    assert json.loads(result.stdout)["status"] == "unverifiable"


def test_backfill_records_that_it_cannot_prove_history(tmp_path: Path) -> None:
    root = _legacy_sealed_run(tmp_path)

    result = run_seal.backfill(root, author="owner", reason="008 复盘")
    assert result["status"] == "backfilled"

    manifest = run_seal.load_manifest(root)
    assert manifest["backfilled"] is True and manifest["backfilled_at"]
    assert manifest["backfilled_by"] == "owner"
    assert "不能证明封存时刻" in manifest["backfill_note"]
    report = run_seal.verify(root)
    assert report["status"] == "intact" and report["backfilled"] is True
    entries = [entry for entry in read_changelog(root) if entry["reason"].startswith("run_seal:backfill")]
    assert entries and entries[-1]["forced"] is True  # 目标 run 已封存：照实记为显式写入
    assert entries[-1]["author"] == "owner"

    # 补录之后再改动，verify 照样抓得住
    with _token(root):
        (root / "batch.json").write_text('{"tampered": true}', encoding="utf-8")
    assert run_seal.verify(root)["status"] == "drifted"


def test_verify_cli_exit_codes(tmp_path: Path) -> None:
    root = _sealed_run(tmp_path)

    def _cli() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "article_group.run_seal", "--run-root", str(root)],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
        )

    intact = _cli()
    assert intact.returncode == run_seal.EXIT_INTACT and "逐字节一致" in intact.stdout

    with _token(root):
        (root / "batch.json").write_text('{"tampered": true}', encoding="utf-8")
    drifted = _cli()
    assert drifted.returncode == run_seal.EXIT_DRIFTED
    assert "无账" in drifted.stdout and "batch.json" in drifted.stdout


def test_sandbox_copy_is_not_reported_as_drift(tmp_path: Path) -> None:
    """演练副本里 SEALED 被改名，对它报"SELED 不见了"是假漂移——直接说"不适用"。"""
    from scripts.run_sandbox import make_sandbox

    root = _sealed_run(tmp_path)
    sandbox = Path(make_sandbox(root, dest=tmp_path / "sandbox")["dest"])

    report = run_seal.verify(sandbox)
    assert report["status"] == "not_applicable"
    assert "副本" in report["reason"] and report["changes"] == []

    result = subprocess.run(
        [sys.executable, "-m", "article_group.run_seal", "--run-root", str(sandbox)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == run_seal.EXIT_NOT_APPLICABLE
    assert "不适用" in result.stdout
    # 源 run 仍然照常校验
    assert run_seal.verify(root)["status"] == "intact"


def test_a_nested_runs_layout_is_sealed_guarded_and_verified(tmp_path: Path) -> None:
    """nested-runs 布局里的封存闭环：intact → 拦写 → 进程外篡改 → drifted。

    2026-09-18 L2 复核：这种布局旧判据下根本不被认作 run 根（引擎裸写），
    所以"封存护栏在这种布局里是否照样生效"必须实测——护栏不依赖 is_run_root
    （它沿父链找 SEALED），这里把结论钉住。
    """

    root = tmp_path / "home" / "runs" / "proj" / "runs" / "2026-09-18" / "daily-960-nested"
    (root / "delivery").mkdir(parents=True)
    (root / "delivery" / "delivery.md").write_text("正文\n", encoding="utf-8")

    seal(root, identity="owner", articles=seal_articles(root))
    assert run_seal.verify(root)["status"] == "intact"

    with pytest.raises(runs_guard.SealedWriteBlocked):
        (root / "delivery" / "delivery.md").write_text("偷改\n", encoding="utf-8")

    # 进程外写入（护栏契约里明确不覆盖的那一层）：由全量哈希清单发现
    subprocess.run(["bash", "-c", f"printf x >> {root / 'delivery' / 'delivery.md'}"], check=True)
    report = run_seal.verify(root)
    assert report["status"] == "drifted"
    changes = {change["path"]: change for change in report["changes"]}
    assert changes["delivery/delivery.md"]["kind"] == "modified"
    assert changes["delivery/delivery.md"]["authorized"] is False  # 无账改动


# ---- ⑤ 锚点绑定：校验的开关不能由被校验对象自己掌管 ----
#
# 2026-09-25 独立只读审计实测出来的洞：`verify` 只在**清单自己带了 anchor 块**时
# 才去读锚点。于是进程外写手只要删掉那个块（或把状态改成 anchor_unavailable），
# 就能让一份被改写过的清单照报 intact——而锚点机制要关的恰恰是这种蓄意篡改。
# 这与仓库已有的病根同型：被检查的产物自己声明「我通过了」不算证据。
#
# 这一组把门重新钉死：锚点文件在就得对得上，块被抹掉同样是漂移；
# 而**没有锚点**的 run（含全部 v1 老 run）必须报 intact_unanchored，不许冒充 intact。

_FORGE = """
import json, sys
from pathlib import Path

root = Path(sys.argv[1])
variant = sys.argv[2]
(root / "delivery/art-001/delivery.md").unlink()
p = root / "SEALED.manifest.json"
m = json.loads(p.read_text(encoding="utf-8"))
m["files"] = [f for f in m["files"] if f["path"] != "delivery/art-001/delivery.md"]
if variant == "drop":
    m.pop("anchor", None)
elif variant == "downgrade":
    m["anchor"] = {"status": "anchor_unavailable", "reason": "offline"}
p.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
"""


@pytest.fixture(autouse=True)
def _anchor_store_is_isolated(isolated_seal_anchor_store):
    """锚点存储由根 conftest 统一隔离到 tmp（见 `isolated_seal_anchor_store`）。

    这里显式声明依赖，是为了让"本模块的锚点测试不碰生产库"这件事在文件里也读得出来。
    """
    return isolated_seal_anchor_store


def _forge(root: Path, variant: str) -> None:
    """进程外伪造：删成稿 + 抹掉清单记录 + 按 variant 处理 anchor 块。"""
    subprocess.run([sys.executable, "-c", _FORGE, str(root), variant], check=True)


@pytest.mark.parametrize("variant", ["drop", "downgrade"])
def test_verify_refuses_a_manifest_that_switches_off_its_own_anchor(tmp_path: Path, variant: str) -> None:
    """抹掉 anchor 块 / 假称没锚上，都不能让被改写的清单过检。"""
    root = _sealed_run(tmp_path)
    assert run_seal.verify(root)["status"] == "intact"

    _forge(root, variant)

    report = run_seal.verify(root)
    assert report["status"] == "drifted", (
        f"被校验对象自己关掉了锚点校验（variant={variant}）：{report}"
    )
    assert any(change["kind"] == "anchor_mismatch" for change in report["changes"]), report["changes"]


def test_verify_still_catches_a_forge_that_keeps_the_anchor_block(tmp_path: Path) -> None:
    """对照：保留 anchor 块时本来就能抓住——这条确保上一条测的是新增能力，不是既有行为。"""
    root = _sealed_run(tmp_path)
    _forge(root, "keep")
    report = run_seal.verify(root)
    assert report["status"] == "drifted"
    assert any(change["kind"] == "anchor_mismatch" for change in report["changes"])


def _sealed_run_without_anchor(tmp_path: Path, monkeypatch) -> Path:
    """让锚点写入失败（只读目录），得到一份「清单在、锚点不在」的真实形态。"""
    store = tmp_path / "readonly-anchors"
    store.mkdir()
    store.chmod(0o500)
    monkeypatch.setenv(run_seal.ANCHOR_DIR_ENV, str(store))
    try:
        root = _sealed_run(tmp_path, name="daily-962")
    finally:
        store.chmod(0o700)
    return root


def test_a_run_without_an_anchor_is_not_reported_intact(tmp_path: Path, monkeypatch) -> None:
    """没有锚点就别报 intact：清单被改写这件事在该 run 上根本查不出来。"""
    root = _sealed_run_without_anchor(tmp_path, monkeypatch)
    manifest = run_seal.load_manifest(root)
    assert manifest["anchor"]["status"] == "anchor_unavailable"
    assert run_seal.read_anchor(root) is None

    report = run_seal.verify(root)
    assert report["changes"] == []
    assert report["status"] == run_seal.STATUS_UNANCHORED
    assert report["anchor"]["status"] == "anchor_unavailable"


def test_cli_reports_an_unanchored_run_as_unverifiable(tmp_path: Path, monkeypatch) -> None:
    """退出码要与人读文字一致：未锚定 = 无法验证（3），不是完好（0）。

    状态名刻意不以 `intact` 开头（复核 F2）——`intact_unanchored` 会被读成
    「文件没变、没事」，而它恰恰是一句没能证明的话。
    """
    root = _sealed_run_without_anchor(tmp_path, monkeypatch)
    result = subprocess.run(
        [sys.executable, "-m", "article_group.run_seal", "--run-root", str(root)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == run_seal.EXIT_UNVERIFIABLE, result.stdout
    assert "封存完整性：unanchored" in result.stdout, result.stdout
    assert "intact" not in result.stdout.split("\n")[0], result.stdout
    # 锚点那一行必须在（复核 F6：这条路径此前只有"无法验证"一行）
    assert "锚点：" in result.stdout, result.stdout


def test_verify_reports_a_corrupt_anchor_as_drift(tmp_path: Path) -> None:
    """锚点文件在但读不出来（损坏/是目录/权限）＝ fail-closed，不许当「没锚点」放行。"""
    root = _sealed_run(tmp_path)
    anchor = run_seal.anchor_file_for(root)
    assert anchor.is_file()
    anchor.write_text("{ not json", encoding="utf-8")

    report = run_seal.verify(root)
    assert report["status"] == "drifted", report
    assert any(change["kind"] == "anchor_unreadable" for change in report["changes"]), report["changes"]


def test_check_remote_maps_unavailable_to_unverifiable(tmp_path: Path, monkeypatch) -> None:
    """离机对照「连不上」是「无法验证」（3），不是「有漂移」（2）——两者含义不同。"""
    root = _sealed_run(tmp_path)

    monkeypatch.setattr(run_seal, "check_remote_anchor", lambda *_a, **_k: {"status": "matches"})
    assert run_seal.main(["--run-root", str(root), "--check-remote"]) == run_seal.EXIT_INTACT
    monkeypatch.setattr(run_seal, "check_remote_anchor", lambda *_a, **_k: {"status": "remote_mismatch"})
    assert run_seal.main(["--run-root", str(root), "--check-remote"]) == run_seal.EXIT_DRIFTED
    monkeypatch.setattr(run_seal, "check_remote_anchor", lambda *_a, **_k: {"status": "remote_unavailable"})
    assert run_seal.main(["--run-root", str(root), "--check-remote"]) == run_seal.EXIT_UNVERIFIABLE
    monkeypatch.setattr(run_seal, "check_remote_anchor", lambda *_a, **_k: {"status": "local_missing"})
    assert run_seal.main(["--run-root", str(root), "--check-remote"]) == run_seal.EXIT_UNVERIFIABLE


# ---- ⑥ v1 清单路径：现存三个封存 run 走的就是这条路 ----
#
# 2026-09-25 独立审计实测的两件事：
#   1. 两条「v1 兼容」测试是**空转**——`run_state.seal()` 会无条件重建清单，所以
#      `write_manifest(v1)` 之后再 seal()，磁盘上留下的是 v2（实测 v1 → v2）。
#      于是 v1 那条生产路径在整套测试里零覆盖，而 daily-008/009/010 全走它。
#   2. 那条路径用的 `_iter_entries` 基于 `Path.rglob`，本机 Python 3.14.4 下 rglob
#      **静默吞掉 OSError**：扫不动的子树在 v1 上照样给 intact（v2 同一棵树给
#      unverifiable）。另外 `dirs`/`others` 循环不受版本门控，v1 清单里塞一条
#      伪造的 dirs 记录，就能让封存后新增的文件不被报 added。
#
# 所以下面用一个**真正的** v1 run（手写清单 + 手写 SEALED，不经过 seal()）来钉住。

_V1_STRIP = """
import json, sys
from pathlib import Path

root = Path(sys.argv[1])
p = root / "SEALED.manifest.json"
m = json.loads(p.read_text(encoding="utf-8"))
m.pop("anchor", None)                      # 老 run 没有 anchor 块
p.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
anchor = Path(sys.argv[2])
if anchor.exists():
    anchor.unlink()                        # 老 run 磁盘上也没有锚点
"""

_V1_PAD_DIRS = """
import json, sys
from pathlib import Path

root = Path(sys.argv[1])
sneaked = root / "review/art-001/sneaked.txt"
sneaked.write_text("planted after sealing", encoding="utf-8")
p = root / "SEALED.manifest.json"
m = json.loads(p.read_text(encoding="utf-8"))
m.setdefault("dirs", []).append({"path": "review/art-001/sneaked.txt", "kind": "dir"})
p.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
"""


def _v1_manifest(root: Path, *, sealed_at: str, sealed_by: str) -> dict:
    """按**真实 v1 的字节形状**造清单（复核 F10）。

    真实 v1（`runs/2026-09-16/daily-008` 实测）的条目键只有 `['path','sha256','size']`，
    顶层没有 `inventory` / `dirs` / `others` / `entry_count` / `scan_errors`。
    此前这个 helper 是"`build_manifest` 之后 pop 几个键"，造出来的是**v1 版本号 + v2 形状**
    的混合体：门控只看版本/标志，所以结论成立，但将来 v1 若开始比 `kind`，helper 仍绿而
    真实 v1 会红——正是本轮修掉的那类"测试自己骗自己"。所以这里手写条目形状并断言它。
    """
    files: list[dict] = []
    append_only: list[dict] = []
    total = 0
    # append-only 文件在 `_is_excluded` 里判 True（它们按前缀哈希单独校验），所以要像
    # build_manifest 那样单独收，否则会得到空的 append_only。
    for name in run_seal.APPEND_ONLY_NAMES:
        path = root / name
        if path.is_file():
            data = path.read_bytes()
            append_only.append({"path": name, "size": len(data),
                                "sha256": hashlib.sha256(data).hexdigest()})
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if run_seal._is_excluded(relative) or relative in run_seal.APPEND_ONLY_NAMES:
            continue
        entry = {"path": relative, "size": path.stat().st_size,
                 "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        files.append(entry)
        total += entry["size"]
    marker = root / run_seal.SEALED_NAME
    return {
        "schema_version": run_seal.SCHEMA_VERSION_V1,
        "run_dir": str(root),
        "sealed_at": sealed_at,
        "sealed_by": sealed_by,
        "seal_ref": "老 run（封存早于锚点机制）",
        "files": files,
        "file_count": len(files),
        "total_bytes": total,
        "append_only": append_only,
        "excluded": {},
        "sealed_marker_sha256": hashlib.sha256(marker.read_bytes()).hexdigest(),
        "note": "v1 形状的封存清单（测试夹具）",
        "publication_authorization": "not_authorized",
    }


def _v1_sealed_run(tmp_path: Path, name: str = "daily-963") -> Path:
    """造一个真 v1 封存 run：磁盘上的清单确实是 v1、没有 anchor 块、没有锚点文件。

    不能写成 `write_manifest(v1)` + `seal()`：seal() 会重建清单，把 v1 冲掉——
    那正是此前两条测试空转的原因。所以这里手写清单与 SEALED 标记；清单在 SEALED
    之后写，因此要走留底通道（真实 daily-008 就是 backfill 这么补出来的）。
    """
    root = tmp_path / name
    (root / "delivery" / "art-001").mkdir(parents=True)
    (root / "review" / "art-001").mkdir(parents=True)
    (root / "delivery" / "art-001" / "delivery.md").write_text("# 标题\n\n正文。\n", encoding="utf-8")
    (root / "review" / "art-001" / "ledger-coverage-precheck.json").write_text('{"frozen": true}', encoding="utf-8")
    (root / "batch.json").write_text(json.dumps({"articles": [{"article_id": "art-001"}]}), encoding="utf-8")
    (root / "step-log.jsonl").write_text('{"name": "discovery"}\n', encoding="utf-8")

    (root / "SEALED").write_text(json.dumps({
        "schema_version": "run-sealed-v1", "sealed_at": "2026-09-25T00:00:00+08:00",
        "sealed_by": "legacy", "seal_ref": "老 run（封存早于锚点机制）",
        "articles": [], "publication_authorization": "not_authorized",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    runs_guard.refresh()

    payload = _v1_manifest(root, sealed_at="2026-09-25T00:00:00+08:00", sealed_by="legacy")
    with runs_guard.sealed_write_token(root, reason="test:v1-fixture", author="tester"):
        run_seal.write_manifest(root, payload)      # 会顺手写锚点 + 嵌 anchor 块

    subprocess.run(
        [sys.executable, "-c", _V1_STRIP, str(root), str(run_seal.anchor_file_for(root))],
        check=True,
    )
    runs_guard.refresh()

    # 断言造出来的确实是 v1（否则这组测试又会空转）
    on_disk = run_seal.load_manifest(root)
    assert on_disk["schema_version"] == run_seal.SCHEMA_VERSION_V1
    assert "inventory" not in on_disk and "dirs" not in on_disk and "scan_errors" not in on_disk
    # 字节忠实性（复核 F10）：条目键集合必须与真实 v1（daily-008）一致
    assert set(on_disk["files"][0]) == {"path", "size", "sha256"}, on_disk["files"][0]
    assert set(on_disk["append_only"][0]) == {"path", "size", "sha256"}, on_disk["append_only"][0]
    assert run_seal.read_anchor(root) is None
    return root


def test_a_real_v1_sealed_run_is_intact_unanchored(tmp_path: Path) -> None:
    """基线：正常的 v1 run 不能被新口径误报 —— 逐字节一致但未锚定。"""
    root = _v1_sealed_run(tmp_path)
    report = run_seal.verify(root)
    assert report["status"] == run_seal.STATUS_UNANCHORED, report
    assert report["changes"] == []
    assert report["anchor"]["status"] == "unanchored"


def test_v1_manifest_refuses_to_conclude_when_a_subtree_cannot_be_scanned(tmp_path: Path) -> None:
    """v1 也不许在"没读完的树"上给结论（rglob 会静默吞 OSError，不能再用它）。"""
    root = _v1_sealed_run(tmp_path)
    assert run_seal.verify(root)["status"] == run_seal.STATUS_UNANCHORED

    victim = root / "review"
    # 改权限必须**进程外**做：封存 run 内的 chmod 会被 runs_guard 正确拦下，
    # 而这里要复现的正是"护栏覆盖不到的进程外写手"。
    subprocess.run(["chmod", "000", str(victim)], check=True)
    try:
        report = run_seal.verify(root)
    finally:
        subprocess.run(["chmod", "755", str(victim)], check=True)

    assert report["status"] == "unverifiable", f"扫不动的树在 v1 上报了结论：{report}"
    assert report.get("scan_errors"), report


def test_v1_manifest_cannot_be_padded_with_a_forged_dirs_entry(tmp_path: Path) -> None:
    """v1 清单塞一条伪造的 dirs 记录，不能把封存后新增的文件"认领"掉。"""
    root = _v1_sealed_run(tmp_path)
    subprocess.run([sys.executable, "-c", _V1_PAD_DIRS, str(root)], check=True)

    report = run_seal.verify(root)
    assert report["status"] == "drifted", f"新增文件被伪造的 dirs 记录掩盖了：{report}"
    assert any(
        change["kind"] == "added" and change["path"] == "review/art-001/sneaked.txt"
        for change in report["changes"]
    ), report["changes"]


def test_v1_manifest_carrying_the_v2_flag_is_refused(tmp_path: Path) -> None:
    """版本与标志是**两个**信号：互相矛盾时拒绝给结论，不安静降级。"""
    root = _v1_sealed_run(tmp_path)

    def _add_flag(path: Path) -> None:
        payload = json.loads((path / "SEALED.manifest.json").read_text(encoding="utf-8"))
        payload["inventory"] = run_seal.INVENTORY_ALL_ENTRIES
        (path / "SEALED.manifest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with runs_guard.sealed_write_token(root, reason="test:flag", author="tester"):
        _add_flag(root)

    report = run_seal.verify(root)
    assert report["status"] == "unverifiable", report
    # 精确断言（复核 F11）：`"inventory" in reason or "标志" in reason` 这种弱断言，
    # 任何含"标志"二字的别的原因都能过——门控被换成别的 unverifiable 理由时它就失效了。
    assert report["reason"] == "清单声明 v1 却带着 v2 的 inventory 标志：两个信号矛盾，拒绝给结论", report


# ---- ⑦ 第二轮独立复核（2026-09-25）F1–F6 的收口 ----
#
# 复核判 needs_changes：核心安全性质成立（没找到"被篡改的清单仍报 intact"的路径），
# 但四条 major 都直接影响"谁看什么、看到什么结论"——人读输出把本机锚点显示成
# "anchored"（安全假象）、未锚定状态名以 intact 开头且理由编造历史、--check-remote
# 拿到离机摘要却不比对、以及建议的补救路径对触发它的 run 无效。


def test_anchored_report_carries_the_real_replication_facts(tmp_path: Path) -> None:
    """F1：报告必须带上锚点文件的真实 kind/replication，人读行必须说清"未离机"。"""
    root = _sealed_run(tmp_path)
    report = run_seal.verify(root)
    assert report["status"] == "intact"
    anchor = report["anchor"]
    assert anchor["status"] == "anchored"
    assert anchor["kind"] == "local-snapshot", anchor
    assert anchor["replication"] == "local-only", anchor

    text = run_seal._describe(report)
    assert "local-snapshot" in text, text
    assert "未离机复制" in text, text
    assert "RUOYU_SEAL_ANCHOR_PUSH" in text, text
    # 不许再把一个数据里不存在的取值（"snapshot"）印给操作者
    assert "（snapshot）" not in text and "snapshot：" not in text, text


def test_anchor_file_records_local_only_not_a_perpetual_pending(tmp_path: Path) -> None:
    """F1 附带：没配离机推送时，锚点文件里的 replication 不该永远是 pending。"""
    root = _sealed_run(tmp_path)
    on_disk = json.loads(run_seal.anchor_file_for(root).read_text(encoding="utf-8"))
    assert on_disk["replication"] == "local-only", on_disk


def test_unanchored_reason_states_only_what_is_known(tmp_path: Path) -> None:
    """F2：理由不许断言代码无从知道的历史，且状态名不许以 intact 开头。"""
    root = _v1_sealed_run(tmp_path)
    report = run_seal.verify(root)
    assert report["status"] == run_seal.STATUS_UNANCHORED
    assert not report["status"].startswith("intact"), report["status"]
    reason = report["anchor"]["reason"]
    assert "封存早于锚点机制" not in reason, reason
    assert str(run_seal.anchor_file_for(root)) in reason, reason


def test_an_unreadable_anchor_store_is_unverifiable_not_unanchored(tmp_path: Path, monkeypatch) -> None:
    """F2：锚点库**查不了** ≠ 这个 run 没锚过。前者不许给任何结论。"""
    store = tmp_path / "anchors"
    store.mkdir()
    monkeypatch.setenv(run_seal.ANCHOR_DIR_ENV, str(store))
    root = _sealed_run(tmp_path, name="daily-964")
    assert run_seal.anchor_file_for(root).parent == store, "前提：锚点落在本测试的库里"
    assert run_seal.verify(root)["status"] == "intact"      # 前提：库可读时能验

    # 把库变成"看不见"（进程外 chmod：封存 run 内的 chmod 会被护栏拦，这里是 run 之外）
    subprocess.run(["chmod", "000", str(store)], check=True)
    try:
        report = run_seal.verify(root)
    finally:
        subprocess.run(["chmod", "755", str(store)], check=True)

    assert report["status"] == "unverifiable", report
    assert report["anchor"]["status"] == "anchor_store_unreadable", report["anchor"]
    assert "锚点" in run_seal._describe(report), "unverifiable 分支也要打印锚点状态（F6）"


def test_deleting_the_local_anchor_downgrades_to_unanchored_and_is_pinned(tmp_path: Path) -> None:
    """F2：钉住**已知限制**——同 uid 写手删掉本机锚点并抹掉 anchor 块后只能报未锚定。

    这不是被修好的洞，而是能力边界：能穿过它的是离机副本（见 check_remote_anchor）。
    把它钉住，免得将来有人以为 `unanchored` 意味着"没被改过"。
    """
    root = _sealed_run(tmp_path, name="daily-965")
    anchor = run_seal.anchor_file_for(root)

    subprocess.run([sys.executable, "-c", (
        "import json,sys\n"
        "from pathlib import Path\n"
        f"root=Path({str(root)!r})\n"
        "(root/'delivery/art-001/delivery.md').unlink()\n"
        "p=root/'SEALED.manifest.json'\n"
        "m=json.loads(p.read_text(encoding='utf-8'))\n"
        "m['files']=[f for f in m['files'] if f['path']!='delivery/art-001/delivery.md']\n"
        "m.pop('anchor',None)\n"
        "p.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\\n',encoding='utf-8')\n"
        f"Path({str(anchor)!r}).unlink(missing_ok=True)\n"
    )], check=True)

    report = run_seal.verify(root)
    assert report["status"] == run_seal.STATUS_UNANCHORED, report
    assert report["changes"] == []
    # 退出码 3（不是 0）：操作者不该把它读成"没事"
    assert run_seal.main(["--run-root", str(root), "--json"] if False else
                         ["--run-root", str(root)]) == run_seal.EXIT_UNVERIFIABLE


def test_check_remote_compares_the_remote_digest_when_the_local_anchor_is_gone(
        tmp_path: Path, monkeypatch) -> None:
    """F3：本机锚点没了，但离机摘要已在手里——它必须被用来判漂移，而不是白丢。"""
    import io
    import tarfile

    root = _sealed_run(tmp_path, name="daily-966")
    name = run_seal.anchor_file_for(root).name
    # 只让清单发生变化（不动文件），使现算摘要与离机摘要必然不同
    with runs_guard.sealed_write_token(root, reason="test:forge", author="tester"):
        payload = run_seal.load_manifest(root)
        payload["note"] = "被改写过的清单"
        (root / run_seal.MANIFEST_NAME).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # 删掉本机锚点（进程外）
    subprocess.run([sys.executable, "-c",
                    f"from pathlib import Path; Path({str(run_seal.anchor_file_for(root))!r}).unlink()"],
                   check=True)

    def _tar_bytes(member: str, blob: bytes) -> bytes:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo(member)
            info.size = len(blob)
            tar.addfile(info, io.BytesIO(blob))
        return buf.getvalue()

    remote_record = json.dumps({"manifest_digest": "d462f2bd31ae"}).encode()

    def fake_run(argv, *args, **kwargs):
        class _Done:
            returncode = 0
            stderr = b""
            stdout = b""
        if argv[:2] == ["git", "archive"]:
            done = _Done(); done.stdout = _tar_bytes(f"anchors/{name}", remote_record); return done
        if argv[:2] == ["tar", "-t"]:
            done = _Done(); done.stdout = f"anchors/{name}\n".encode(); return done
        if argv[:2] == ["tar", "-xO"]:
            done = _Done(); done.stdout = remote_record; return done
        raise AssertionError(argv)

    monkeypatch.setattr(run_seal.subprocess, "run", fake_run)
    report = run_seal.check_remote_anchor(root, remote="ssh://example/seal-ledger.git")

    assert report["status"] == "remote_mismatch", report
    assert report["remote_digest"] == "d462f2bd31ae"
    assert "清单被改写" in report["reason"]


def test_the_remedy_for_an_unanchored_run_is_actually_reachable(tmp_path: Path) -> None:
    """F4：清单已存在时 --backfill 只会 already_present，不能再把它当出路写进提示。"""
    root = _v1_sealed_run(tmp_path)
    remedy = run_seal.verify(root)["anchor"]["remedy"]
    assert "already_present" in remedy, remedy
    assert "unseal" in remedy, remedy
    assert "当时性" in remedy, remedy
    # 事实核对：--backfill 对这条 run 确实无效
    assert run_seal.backfill(root, author="tester", reason="复核 F4")["status"] == "already_present"


def test_seal_survives_a_non_utf8_run_path(tmp_path: Path) -> None:
    """F5：非 UTF-8 路径不得让 _manifest_digest 抛 UnicodeEncodeError 打崩封存。"""
    from article_group.run_state import seal

    parent = tmp_path / "runs" / "2026-09-25"
    parent.mkdir(parents=True)
    root = Path(os.fsdecode(os.fsencode(str(parent)) + b"/daily-\xffbad"))
    (root / "delivery" / "art-001").mkdir(parents=True)
    (root / "delivery" / "art-001" / "delivery.md").write_text("# 正文\n", encoding="utf-8")

    seal(root, identity="tester")                 # 修复前：这里抛 UnicodeEncodeError

    assert run_seal.load_manifest(root) is not None
    report = run_seal.verify(root)
    assert report["status"] in {"intact", run_seal.STATUS_UNANCHORED}, report
