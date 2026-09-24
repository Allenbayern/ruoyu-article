"""第二批接入留底通道的写手：codex_review / delivery / content_delivery / daily_engine。

它们此前是"能写 run 但绕过通道"（护栏兜住、但无 before-image、无记账）。现在统一为：
run 内目标 → `evidence_write`（留底+记账+封存守门）；run 外目标 → 普通写入（不该被
别人的封存挡）。拒绝口径与五个入口一致：退出码 2 + 一句人话。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from article_group import content_delivery, delivery
from article_group.evidence_write import RunSealedError, read_changelog
from article_group.run_state import seal, seal_articles

REPO_ROOT = Path(__file__).resolve().parents[1]


def _sealed_run(tmp_path: Path) -> Path:
    root = tmp_path / "runs" / "2026-09-17" / "daily-970"
    (root / "delivery" / "art-001").mkdir(parents=True)
    (root / "review" / "art-001").mkdir(parents=True)
    (root / "delivery" / "art-001" / "delivery.md").write_text("# 标题\n\n正文。\n", encoding="utf-8")
    (root / "batch.json").write_text(json.dumps({"articles": [{"article_id": "art-001"}]}), encoding="utf-8")
    seal(root, identity="owner", articles=seal_articles(root))
    return root


# ---- ① codex_review：L2 复核记录 + 评审日志 ----


def _l2_review_json(tmp_path: Path) -> Path:
    path = tmp_path / "l2.json"
    path.write_text(json.dumps({
        "decision": "approve",
        "scope_reviewed": ["article body"],
        "findings": [],
        "non_findings": [],
        "coverage_gaps": [],
    }, ensure_ascii=False), encoding="utf-8")
    return path


def _codex_review_cli(root: Path, review_json: Path, output: Path, *extra: str):
    return subprocess.run(
        [sys.executable, "-m", "article_group.codex_review",
         "--mode", "l2", "--run-root", str(root), "--output", str(output),
         "--request", "unit-test", "--review-json", str(review_json), *extra],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
    )


def test_codex_review_refuses_sealed_run_then_force_writes_with_ledger(tmp_path: Path):
    root = _sealed_run(tmp_path)
    review_json = _l2_review_json(tmp_path)
    output = root / "review" / "art-001" / "independent-review.json"

    refused = _codex_review_cli(root, review_json, output)
    assert refused.returncode == 2
    assert "封存" in refused.stderr and "force" in refused.stderr
    assert "Traceback" not in refused.stderr
    assert not output.exists() and not output.with_suffix(".log").exists()
    assert read_changelog(root) == []

    forced = _codex_review_cli(root, review_json, output, "--force")
    assert forced.returncode == 0, forced.stderr
    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["review_source"] == "external_review_json" and record["decision"] == "approve"
    assert output.with_suffix(".log").exists()  # 评审原文日志同样入账
    reasons = {entry["reason"] for entry in read_changelog(root)}
    assert {"codex_review:l2", "codex_review:log"} <= reasons
    assert all(entry["forced"] is True for entry in read_changelog(root))


def _dsh_review_cli(root: Path, review_json: Path, output: Path, *extra: str):
    return subprocess.run(
        [sys.executable, "-m", "article_group.dsh_review",
         "--mode", "l2", "--run-root", str(root), "--output", str(output),
         "--request", "unit-test", "--review-json", str(review_json), *extra],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
    )


def test_dsh_review_refuses_sealed_run_then_force_writes_with_ledger(tmp_path: Path):
    root = _sealed_run(tmp_path)
    review_json = _l2_review_json(tmp_path)
    output = root / "review" / "art-001" / "independent-review.json"

    refused = _dsh_review_cli(root, review_json, output)
    assert refused.returncode == 2
    assert "封存" in refused.stderr and "force" in refused.stderr
    assert "Traceback" not in refused.stderr
    assert not output.exists() and not output.with_suffix(".log").exists()
    assert read_changelog(root) == []

    forced = _dsh_review_cli(root, review_json, output, "--force")
    assert forced.returncode == 0, forced.stderr
    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["review_source"] == "external_review_json" and record["decision"] == "approve"
    assert output.with_suffix(".log").exists()
    reasons = {entry["reason"] for entry in read_changelog(root)}
    assert {"dsh_review:l2", "dsh_review:log"} <= reasons
    assert all(entry["forced"] is True for entry in read_changelog(root))


# ---- ② delivery：纯文本交付副本 ----


def test_delivery_plain_copy_goes_through_the_channel(tmp_path: Path):
    root = _sealed_run(tmp_path)
    markdown = root / "delivery" / "art-001" / "delivery.md"
    plain = root / "delivery" / "art-001" / "delivery.txt"

    with pytest.raises(RunSealedError):
        delivery.write_plain_from_markdown(markdown, plain, run_dir=root)
    assert not plain.exists()

    text = delivery.write_plain_from_markdown(markdown, plain, run_dir=root, force=True)
    assert plain.read_text(encoding="utf-8") == text
    assert read_changelog(root)[-1]["reason"] == "delivery:plain_from_markdown"
    assert read_changelog(root)[-1]["forced"] is True


def test_delivery_without_run_dir_keeps_plain_write(tmp_path: Path):
    markdown = tmp_path / "a.md"
    markdown.write_text("# 标题\n\n正文。\n", encoding="utf-8")
    plain = tmp_path / "out" / "a.txt"
    delivery.write_plain_from_markdown(markdown, plain)
    assert plain.is_file()
    assert not (tmp_path / "evidence-changelog.jsonl").exists()  # run 外不建账


# ---- ③ content_delivery：交付记录 ----


def test_content_delivery_record_refuses_then_force_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _sealed_run(tmp_path)
    monkeypatch.setattr(content_delivery, "build_content_delivery_record", lambda run_dir: {"content_status": "content_ready"})

    target = root / "review" / "content-delivery.json"
    with pytest.raises(RunSealedError):
        content_delivery.write_content_delivery_record(root)
    assert not target.exists()

    content_delivery.write_content_delivery_record(root, force=True)
    assert json.loads(target.read_text(encoding="utf-8"))["content_status"] == "content_ready"
    assert read_changelog(root)[-1]["reason"] == "content_delivery:record"


def test_content_delivery_cli_reports_sealed_refusal_cleanly(monkeypatch: pytest.MonkeyPatch, capsys):
    from scripts import content_delivery_audit

    def _refuse(*_args, **_kwargs):
        raise RunSealedError("run 已封存（sealed_at=…）：加 force 才会改写封存证据")

    monkeypatch.setattr(content_delivery_audit, "write_content_delivery_record", _refuse)
    monkeypatch.setattr(sys, "argv", ["content_delivery_audit.py", "--run-dir", "/tmp/whatever"])
    assert content_delivery_audit.main() == 2
    captured = capsys.readouterr()
    assert "封存" in captured.err and "Traceback" not in captured.err


# ---- ④ daily_engine：引擎产物走同一条通道 ----


def test_daily_engine_routes_run_writes_through_the_channel(tmp_path: Path):
    from scripts import daily_engine

    run_root = tmp_path / "runs" / "2026-09-17" / "daily-971"
    run_root.mkdir(parents=True)
    calls: list[tuple[str, object]] = []

    def raw(path: str, value: object) -> None:  # spec 模块的原始写法（不该被调用）
        calls.append((path, value))

    previous = getattr(daily_engine, "ROOT", None)
    daily_engine.ROOT = run_root
    try:
        daily_engine._route_write("review/x.json", {"a": 1}, kind="json", raw=raw)
        daily_engine._route_write("drafts/body.md", "正文\n", kind="text", raw=raw)
    finally:
        if previous is None:
            delattr(daily_engine, "ROOT")
        else:
            daily_engine.ROOT = previous

    assert calls == []  # 走了通道，没落到 spec 的裸写
    assert json.loads((run_root / "review" / "x.json").read_text(encoding="utf-8")) == {"a": 1}
    assert (run_root / "drafts" / "body.md").read_text(encoding="utf-8") == "正文\n"
    reasons = {entry["reason"] for entry in read_changelog(run_root)}
    assert {"daily_engine:review/x.json", "daily_engine:drafts/body.md"} <= reasons


def test_daily_engine_keeps_plain_writes_outside_a_run_root(tmp_path: Path):
    from scripts import daily_engine

    outside = tmp_path / "somewhere"
    outside.mkdir()
    daily_engine.ROOT = outside
    calls: list[str] = []
    try:
        daily_engine._route_write("note.md", "hi\n", kind="text", raw=lambda path, value: calls.append(path))
        assert daily_engine._is_run_root(outside) is False
    finally:
        daily_engine.ROOT = Path(".")
    assert calls == ["note.md"]
    assert not (outside / "evidence-changelog.jsonl").exists()
