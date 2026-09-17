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
import subprocess
import sys
from pathlib import Path

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
    assert any(entry["reason"].startswith("run_seal:backfill") for entry in read_changelog(root))

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
