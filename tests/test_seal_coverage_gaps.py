"""封存锚点的**覆盖缺口**回归（2026-09-25 第一轮独立复核点名的空白）。

为什么单独一个文件：这些用例要补的三个对象当轮正被第二轮复核用
`round2-frozen.sha256` 钉着，**不能改**（改了复核的哈希核对会失败）。所以新用例集中
放在这里，不改 `tests/test_run_seal.py` / `tests/test_preview_site.py` 一行。

补的是第一轮复核列出的 coverage_gaps：

1. `_replicate_anchor`（约 45 行：clone / pull / commit / push / 各失败分支）在整套测试里
   **从未真实执行**，只有 monkeypatch —— 这里用一个真的本地裸仓库当离机账本跑通。
2. **生产锚点库"保持为空"没有自动化断言**：fixture 隔离是防"写进默认库"的唯一机制，
   却只靠一次性人工计数。这里把它钉住，专门防"读走 env、写走常量"这种对称 bug。
3. v1 清单的 `MAY_BE_ABSENT` / `append_only` / `sealed_marker_sha256` / 新增文件
   没有回归测试；`--check-remote` 的 `remote_missing` 退出码映射也没有。
4. `publish()` 的 `ignore` 只测了顶层：要钉住"嵌套同名文件仍照发"（否则将来把回调写成
   全层级排除会静默丢文件）。
5. `render` 的封存拒绝没有独立用例。
6. 非 UTF-8 路径 × 锚点的**交互**：此前只断言状态落在集合里，这里钉住"锚点确实写成、
   且摘要比对跨代理字符仍成立"（即 F5 的修复真的生效）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from article_group import preview_site, run_seal, runs_guard
from article_group.run_state import seal
from tests.test_preview_site import _make_run as _make_preview_run
from tests.test_preview_site import build as build_preview
from tests.test_preview_site import publish as publish_preview
from tests.test_run_seal import _v1_sealed_run

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── ① `_replicate_anchor` 的真实路径：拿一个真的本地裸仓库当离机账本 ──────────────


def _bare_ledger(tmp_path: Path) -> Path:
    remote = tmp_path / "seal-ledger.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)],
                   check=True, capture_output=True)
    return remote


def _sealed_run(tmp_path: Path, name: str = "daily-970") -> Path:
    root = tmp_path / name
    (root / "delivery" / "art-001").mkdir(parents=True)
    (root / "delivery" / "art-001" / "delivery.md").write_text("# 正文\n", encoding="utf-8")
    (root / "batch.json").write_text(json.dumps({"articles": [{"article_id": "art-001"}]}), encoding="utf-8")
    seal(root, identity="owner")
    return root


def test_anchor_is_actually_pushed_to_a_real_offhost_ledger(tmp_path: Path, monkeypatch) -> None:
    """`_replicate_anchor` 的 clone→add→commit→push 真跑一遍，并回读离机副本。"""
    remote = _bare_ledger(tmp_path)
    monkeypatch.setenv(run_seal.ANCHOR_PUSH_ENV, str(remote))
    root = _sealed_run(tmp_path)

    block = run_seal.load_manifest(root)["anchor"]
    assert block["status"] == "anchored", block
    assert block["replication"] == "pushed", block
    assert block["kind"] == "offhost-snapshot", block

    name = run_seal.anchor_file_for(root).name
    shown = subprocess.run(["git", "-C", str(remote), "show", f"main:anchors/{name}"],
                           capture_output=True, text=True, check=True)
    pushed = json.loads(shown.stdout)
    assert pushed["manifest_digest"] == block["manifest_digest"]
    # 本机那份也已被回写成真实结果（不是永远 pending）
    local = json.loads(run_seal.anchor_file_for(root).read_text(encoding="utf-8"))
    assert local["replication"] == "pushed", local


def test_a_second_seal_reuses_the_existing_clone_and_pushes_again(tmp_path: Path, monkeypatch) -> None:
    """第二次封存走 `git pull --ff-only` 那一支（不是每次重新 clone）。"""
    from article_group.run_state import unseal

    remote = _bare_ledger(tmp_path)
    monkeypatch.setenv(run_seal.ANCHOR_PUSH_ENV, str(remote))
    root = _sealed_run(tmp_path, name="daily-971")

    unseal(root, reason="测试：改完再封一次", identity="owner")
    seal(root, identity="owner")

    work = run_seal.anchor_file_for(root).parent / ".seal-ledger-work"
    assert (work / ".git").is_dir(), "第二次应当复用已有克隆（走 pull 分支）"
    name = run_seal.anchor_file_for(root).name
    subprocess.run(["git", "-C", str(remote), "show", f"main:anchors/{name}"],
                   check=True, capture_output=True)


# ── ② 生产锚点库必须保持为空（防"读 env、写常量"的对称 bug） ──────────────────


def test_the_default_anchor_store_is_never_written_by_tests(tmp_path: Path) -> None:
    """隔离 fixture 的守门能力本身要被测试钉住，而不是靠人工数一次。

    现有锚点用例全都经 `anchor_file_for()` 走 env，所以"写死在常量上"的 bug 会全程绿、
    却把 pytest 残留重新倒进生产库（2026-09-25 实测那里曾累积 58 个）。
    """
    default_dir = Path(run_seal.DEFAULT_ANCHOR_DIR)
    before = sorted(p.name for p in default_dir.glob("*.anchor.json")) if default_dir.is_dir() else []
    assert run_seal.anchor_file_for(tmp_path / "x").parent != default_dir, \
        "前提：测试期间锚点目录应已被 fixture 指到 tmp"

    _sealed_run(tmp_path, name="daily-972")

    after = sorted(p.name for p in default_dir.glob("*.anchor.json")) if default_dir.is_dir() else []
    assert after == before, f"测试往生产锚点库写了：{set(after) - set(before)}"


# ── ③ v1 清单的几段分支 + --check-remote 的 remote_missing ────────────────────


def test_v1_inventory_authorizes_a_missing_transient_but_catches_a_rewrite(tmp_path: Path) -> None:
    """v1：`MAY_BE_ABSENT` 的瞬时件缺失属授权，但内容被改写照样要抓。"""
    root = _v1_sealed_run(tmp_path, name="daily-973")

    # 封存 run 内的写入一律走留底通道（护栏会拦裸写——这本身也是它的契约）
    with runs_guard.sealed_write_token(root, reason="test:fixture", author="tester"):
        (root / ".preview-links.lock").write_text('{"pid": 1}', encoding="utf-8")
        payload = run_seal.load_manifest(root)
        payload["files"].append({
            "path": ".preview-links.lock", "size": 10,
            "sha256": "0" * 64,
        })
        (root / run_seal.MANIFEST_NAME).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 进程外删掉（瞬时件被正常清理）→ `MAY_BE_ABSENT` 授权缺失，不算漂移
    subprocess.run(["rm", "-f", str(root / ".preview-links.lock")], check=True)
    report = run_seal.verify(root)
    assert not [c for c in report["changes"] if c["path"] == ".preview-links.lock"], \
        f"瞬时件缺失被判成漂移：{report['changes']}"

    # 但"存在且内容不符"必须报（授权的是缺失，不是改写）
    with runs_guard.sealed_write_token(root, reason="test:tamper", author="tester"):
        (root / ".preview-links.lock").write_text("tampered", encoding="utf-8")
    kinds = {c["path"]: c["kind"] for c in run_seal.verify(root)["changes"]}
    assert kinds.get(".preview-links.lock") == "modified", kinds


def test_v1_inventory_catches_an_added_file_and_an_append_only_rewrite(tmp_path: Path) -> None:
    """v1：新增文件与 append-only 重写都要报（复核手测过，但此前没有回归测试）。"""
    root = _v1_sealed_run(tmp_path, name="daily-974")

    subprocess.run(["bash", "-c", f"printf x > {root / 'sneaked.txt'}"], check=True)
    with runs_guard.sealed_write_token(root, reason="test", author="tester"):
        (root / "step-log.jsonl").write_text('{"name": "rewritten"}\n', encoding="utf-8")

    kinds = {c["path"]: c["kind"] for c in run_seal.verify(root)["changes"]}
    assert kinds.get("sneaked.txt") == "added", kinds
    assert kinds.get("step-log.jsonl") in {"append_only_rewritten", "append_only_truncated"}, kinds


def test_v1_inventory_catches_a_changed_sealed_marker(tmp_path: Path) -> None:
    """v1：`SEALED` 标记自身的字节被改动要报。"""
    root = _v1_sealed_run(tmp_path, name="daily-975")
    with runs_guard.sealed_write_token(root, reason="test", author="tester"):
        (root / run_seal.SEALED_NAME).write_text('{"tampered": true}\n', encoding="utf-8")

    kinds = {c["path"]: c["kind"] for c in run_seal.verify(root)["changes"]}
    assert kinds.get(run_seal.SEALED_NAME) == "modified", kinds


def test_check_remote_missing_maps_to_unverifiable(tmp_path: Path, monkeypatch, capsys) -> None:
    """离机账本里没有这条锚点 = 无法验证（3），不是有漂移（2）。"""
    root = _sealed_run(tmp_path, name="daily-976")
    monkeypatch.setattr(run_seal, "check_remote_anchor",
                        lambda *_a, **_k: {"status": "remote_missing", "remote": "ssh://x/y.git"})
    assert run_seal.main(["--run-root", str(root), "--check-remote"]) == run_seal.EXIT_UNVERIFIABLE
    assert json.loads(capsys.readouterr().out)["status"] == "remote_missing"


# ── ④ publish 的 ignore 只排除顶层那一份 ─────────────────────────────────────


def test_publish_still_ships_a_nested_file_that_happens_to_share_the_record_name(tmp_path: Path) -> None:
    """排除的是**顶层**自己的账；`preview/wechat/` 下同名文件必须照发。"""
    run = _make_preview_run(tmp_path)
    build_preview(run)
    nested = run / "preview" / "wechat" / preview_site.PUBLISH_RECORD_NAME
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_text('{"nested": true}', encoding="utf-8")

    static = tmp_path / "outbox"
    static.mkdir()
    record = publish_preview(run, static, base_url="http://192.168.100.168:8899")

    shipped = sorted(p.relative_to(static / "2026-09-17-daily-999").as_posix()
                     for p in (static / "2026-09-17-daily-999").rglob("*") if p.is_file())
    assert f"wechat/{preview_site.PUBLISH_RECORD_NAME}" in shipped, shipped
    assert preview_site.PUBLISH_RECORD_NAME not in shipped, shipped
    assert f"wechat/{preview_site.PUBLISH_RECORD_NAME}" in record["files"]


# ── ⑤ render 的封存拒绝（与 export 同一条护栏） ────────────────────────────────


def test_topic_backlog_render_refuses_to_write_into_a_sealed_run(tmp_path: Path, capsys) -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from topic_backlog import main as backlog_main

    sealed = tmp_path / "runs" / "2026-09-25" / "daily-977"
    sealed.mkdir(parents=True)
    (sealed / "SEALED").write_text("{}", encoding="utf-8")
    db = tmp_path / "backlog.sqlite"

    code = backlog_main(["--db", str(db), "render", "--out", str(sealed / "view.md")])

    assert code == 3
    assert "refuse_sealed_run" in capsys.readouterr().out
    assert not (sealed / "view.md").exists()


# ── ⑥ 非 UTF-8 路径 × 锚点：修复要真的生效，而不只是"状态落在集合里" ─────────────


def test_a_non_utf8_run_is_anchored_and_verifies_intact(tmp_path: Path) -> None:
    """F5 的实质：非 UTF-8 run 不仅能封存，锚点也要写成、摘要比对跨代理字符仍成立。"""
    parent = tmp_path / "runs" / "2026-09-25"
    parent.mkdir(parents=True)
    root = Path(os.fsdecode(os.fsencode(str(parent)) + b"/daily-\xffanchor"))
    (root / "delivery" / "art-001").mkdir(parents=True)
    (root / "delivery" / "art-001" / "delivery.md").write_text("# 正文\n", encoding="utf-8")

    seal(root, identity="owner")

    assert run_seal.read_anchor(root) is not None, "非 UTF-8 run 的锚点没写成"
    report = run_seal.verify(root)
    assert report["status"] == "intact", report
    assert report["changes"] == []
    assert report["anchor"]["status"] == "anchored"
