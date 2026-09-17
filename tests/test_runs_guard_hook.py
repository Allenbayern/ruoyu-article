"""runs_guard：封存 run 的**进程级**写入护栏（不再靠"每个入口自己记得接守卫"）。

为什么需要（2026-09-17，008 事故第二层）：
封存守门此前是白名单制——能写 run 的模块三十来个，接了守卫的只有五个。事故的同构
风险不是"这五个写错了"，而是"**新入口忘了接**"。本模块用 PEP 578 audit hook 把
"忘记"变成"写不进去"：只要进程 import 过 article_group，凡以写/删/改名模式触碰
含 `SEALED` 的目录，一律抛 `SealedWriteBlocked`，除非显式进入 `sealed_write_token`
（与 `--force` 同一等级的授权，走同一套留底+记账）。

明确不覆盖（避免误以为已全保）：护栏只在 import 过 article_group 的进程内生效。
vim / rsync / `git checkout` / 裸 `python -c`（未 import 本包）这类进程外写入不在
其内——那属于文件系统层只读与全量哈希清单的职责。第 12 个用例把这个边界钉住。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from article_group import runs_guard
from article_group.evidence_write import read_changelog, write_evidence
from article_group.run_state import is_sealed, seal, seal_articles, unseal
from scripts.run_sandbox import make_sandbox

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_tree(tmp_path: Path, name: str = "daily-900") -> Path:
    """一个最小可封存 run（写入一律发生在封存**之前**）。"""
    root = tmp_path / name
    (root / "delivery" / "art-001").mkdir(parents=True)
    (root / "review" / "art-001").mkdir(parents=True)
    (root / "delivery" / "art-001" / "delivery.md").write_text("# 标题\n\n正文。\n", encoding="utf-8")
    (root / "review" / "art-001" / "ledger-coverage-precheck.json").write_text(
        '{"frozen": true}', encoding="utf-8"
    )
    (root / "batch.json").write_text(
        json.dumps({"articles": [{"article_id": "art-001"}]}, ensure_ascii=False), encoding="utf-8"
    )
    return root


def _sealed_run(tmp_path: Path, name: str = "daily-900") -> Path:
    root = _run_tree(tmp_path, name)
    seal(root, identity="owner", articles=seal_articles(root))
    assert is_sealed(root) is True
    return root


def _child(code: str, *argv: str) -> subprocess.CompletedProcess[str]:
    """在干净子进程里跑一段代码（cwd=仓库根，article_group 可导入）。"""
    return subprocess.run(
        [sys.executable, "-c", code, *argv],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


# ---- ① 拦截：所有写形态 ----


def test_write_text_under_sealed_run_is_blocked(tmp_path: Path):
    root = _sealed_run(tmp_path)
    target = root / "review" / "art-001" / "ledger-coverage-precheck.json"
    with pytest.raises(runs_guard.SealedWriteBlocked):
        target.write_text('{"overwritten": true}', encoding="utf-8")
    assert target.read_text(encoding="utf-8") == '{"frozen": true}'


def test_open_write_and_append_modes_are_blocked(tmp_path: Path):
    root = _sealed_run(tmp_path)
    with pytest.raises(runs_guard.SealedWriteBlocked):
        (root / "new-file.json").open("w", encoding="utf-8")
    with pytest.raises(runs_guard.SealedWriteBlocked):
        (root / "batch.json").open("a", encoding="utf-8")
    with pytest.raises(runs_guard.SealedWriteBlocked):
        (root / "batch.json").open("r+", encoding="utf-8")


def test_reads_are_never_blocked(tmp_path: Path):
    root = _sealed_run(tmp_path)
    assert (root / "batch.json").read_text(encoding="utf-8")
    assert (root / "delivery" / "art-001" / "delivery.md").read_bytes()
    assert [p.name for p in sorted(root.iterdir())]


def test_delete_rename_copy_and_mkdir_are_blocked(tmp_path: Path):
    import os
    import shutil

    root = _sealed_run(tmp_path)
    with pytest.raises(runs_guard.SealedWriteBlocked):
        (root / "batch.json").unlink()
    with pytest.raises(runs_guard.SealedWriteBlocked):
        os.replace(root / "batch.json", root / "batch.json.bak")
    with pytest.raises(runs_guard.SealedWriteBlocked):
        (root / "batch.json").rename(root / "batch.json.bak")
    with pytest.raises(runs_guard.SealedWriteBlocked):
        shutil.copy2(tmp_path / "outside.txt", root / "review" / "copied.txt")
    with pytest.raises(runs_guard.SealedWriteBlocked):
        (root / "wechat").mkdir()
    assert (root / "batch.json").is_file()


def test_noop_destructive_calls_are_allowed(tmp_path: Path):
    """破坏性调用的空操作不算写入（文件本就不存在，没有东西可毁）。"""
    import os

    root = _sealed_run(tmp_path)
    (root / "review" / "art-001" / "title-freeze.json").unlink(missing_ok=True)  # 不存在 → 空操作
    with pytest.raises(FileNotFoundError):  # 该失败还是它自己的失败，不是护栏拦的
        os.replace(root / "missing.json", root / "missing2.json")
    assert not (root / "review" / "art-001" / "title-freeze.json").exists()


def test_writes_to_unsealed_runs_and_outside_are_unaffected(tmp_path: Path):
    sealed = _sealed_run(tmp_path)
    open_run = _run_tree(tmp_path, "daily-901")
    (open_run / "review" / "art-001" / "note.json").write_text("{}", encoding="utf-8")
    (tmp_path / "scratch.txt").write_text("ok", encoding="utf-8")
    assert (open_run / "review" / "art-001" / "note.json").is_file()
    assert sealed.is_dir()


# ---- ② 令牌：放行必须显式、且只放行目标 run ----


def test_append_only_logs_accept_appends_but_not_rewrites(tmp_path: Path):
    """两个 append-only 文件：追加放行（封存动作自身的流水行在其后），重写/删除照拦。"""
    root = _run_tree(tmp_path)
    (root / "step-log.jsonl").write_text('{"name": "discovery"}\n', encoding="utf-8")
    (root / "evidence-changelog.jsonl").write_text("", encoding="utf-8")
    seal(root, identity="owner", articles=seal_articles(root))

    with (root / "step-log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"name": "seal"}\n')
    assert len((root / "step-log.jsonl").read_text(encoding="utf-8").strip().splitlines()) == 2

    with pytest.raises(runs_guard.SealedWriteBlocked):  # 非 append-only 文件即便 'a' 也拦
        (root / "batch.json").open("a", encoding="utf-8")
    with pytest.raises(runs_guard.SealedWriteBlocked):  # 同一文件重写仍拦
        (root / "step-log.jsonl").open("w", encoding="utf-8")
    with pytest.raises(runs_guard.SealedWriteBlocked):  # 删除仍拦
        (root / "step-log.jsonl").unlink()
    assert (root / "step-log.jsonl").is_file()


def test_token_allows_writes_and_is_scoped_to_one_run(tmp_path: Path):
    root = _sealed_run(tmp_path, "daily-902")
    other = _sealed_run(tmp_path, "daily-903")
    with runs_guard.sealed_write_token(root, reason="unit-test", author="tester"):
        (root / "review" / "art-001" / "token-note.json").write_text("{}", encoding="utf-8")
        with pytest.raises(runs_guard.SealedWriteBlocked):
            (other / "review" / "art-001" / "token-note.json").write_text("{}", encoding="utf-8")
    with pytest.raises(runs_guard.SealedWriteBlocked):
        (root / "review" / "art-001" / "after-token.json").write_text("{}", encoding="utf-8")


def test_evidence_write_force_runs_inside_the_token(tmp_path: Path):
    """合法的 force 写入必须穿过自己的护栏：留底 + 记账 + 真正落盘。"""
    root = _sealed_run(tmp_path)
    entry = write_evidence(
        root / "review" / "art-001" / "ledger-coverage-precheck.json",
        '{"frozen": false}',
        run_dir=root,
        reason="unit-test:force",
        author="tester",
        force=True,
    )
    assert entry["forced"] is True
    assert entry["before_sha256"] and entry["before_sha256"] != entry["after_sha256"]
    assert (root / entry["snapshot_path"]).is_file()
    assert json.loads(
        (root / "review" / "art-001" / "ledger-coverage-precheck.json").read_text(encoding="utf-8")
    ) == {"frozen": False}
    assert read_changelog(root)[-1]["reason"] == "unit-test:force"


def test_unseal_is_not_blocked_and_reenables_plain_writes(tmp_path: Path):
    root = _sealed_run(tmp_path)
    record = unseal(root, reason="unit-test", identity="owner")
    assert record["status"] == "unsealed"
    (root / "review" / "art-001" / "after-unseal.json").write_text("{}", encoding="utf-8")
    assert (root / "review" / "art-001" / "after-unseal.json").is_file()


def test_sealing_mid_process_takes_effect(tmp_path: Path):
    """先写过（探测缓存已记住"未封存"），封存后同一进程必须立刻改判。"""
    root = _run_tree(tmp_path)
    (root / "review" / "art-001" / "early.json").write_text("{}", encoding="utf-8")
    seal(root, identity="owner", articles=seal_articles(root))
    with pytest.raises(runs_guard.SealedWriteBlocked):
        (root / "review" / "art-001" / "late.json").write_text("{}", encoding="utf-8")


def test_sandbox_copy_stays_writable(tmp_path: Path):
    root = _sealed_run(tmp_path)
    marker = make_sandbox(root, dest=tmp_path / "sandbox", label="unit-test")
    sandbox = Path(marker["dest"])
    (sandbox / "review" / "art-001" / "rehearsal.json").write_text("{}", encoding="utf-8")
    assert (sandbox / "review" / "art-001" / "rehearsal.json").is_file()
    assert not (sandbox / "SEALED").exists()  # 副本不封存，故可写


# ---- ③ 真正的收益：没接守卫的入口也写不进去 ----


def test_unguarded_writer_in_a_subprocess_is_blocked(tmp_path: Path):
    """新入口只要忘了接守卫，就撞在护栏上——这正是本项要买的东西。"""
    root = _sealed_run(tmp_path)
    target = root / "review" / "art-001" / "unguarded.json"
    result = _child(
        "import sys, pathlib\n"
        "import article_group  # 任何 article_group 导入都会装护栏\n"
        "pathlib.Path(sys.argv[1]).write_text('{}', encoding='utf-8')\n",
        str(target),
    )
    assert result.returncode != 0
    assert "封存" in result.stderr
    assert not target.exists()


def test_guard_is_in_process_only_documented_limit(tmp_path: Path):
    """边界如实钉住：没 import 本包的进程不受护栏约束（需文件系统层兜底）。"""
    root = _sealed_run(tmp_path)
    target = root / "review" / "art-001" / "outside-process.json"
    result = _child(
        "import sys, pathlib\n"
        "pathlib.Path(sys.argv[1]).write_text('{}', encoding='utf-8')\n",
        str(target),
    )
    assert result.returncode == 0
    assert target.is_file()


def test_block_message_names_the_remedies(tmp_path: Path):
    root = _sealed_run(tmp_path)
    with pytest.raises(runs_guard.SealedWriteBlocked) as excinfo:
        (root / "x.json").write_text("{}", encoding="utf-8")
    message = str(excinfo.value)
    assert "封存" in message
    assert "--force" in message and "unseal" in message and "run_sandbox" in message


def test_install_is_idempotent():
    assert runs_guard.install() is False  # 导入 article_group 时已装
    assert runs_guard.is_installed() is True
