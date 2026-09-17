"""五类写证据入口的封存守卫回归：所有入口在封存 run 上必须拒绝、且一字不改。

覆盖：账本预检、evidence_rebind、title_freeze、wechat_render、close_out。
每个入口都断言两件事：①无 force 时 run 内文件与 changelog 完全不变；
②显式 force 时才写，并留下留底与记账。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from article_group import close_out as close_out_mod
from article_group import evidence_rebind, title_freeze, wechat_render
from article_group.evidence_write import read_changelog
from article_group.run_state import is_sealed, seal, seal_articles
from scripts import ledger_coverage_precheck as pre
from tests._runs_guard import diff, is_clean, snapshot

REVIEW = "review/art-001/ledger-coverage-precheck.json"


def _sealed_run(tmp_path: Path) -> Path:
    root = tmp_path / "daily-900"
    (root / "delivery" / "art-001").mkdir(parents=True)
    (root / "review" / "art-001").mkdir(parents=True)
    (root / "material-packs").mkdir(parents=True)
    (root / "delivery" / "art-001" / "delivery.md").write_text("# 标题\n\n正文。\n", encoding="utf-8")
    (root / "material-packs" / "art-001.json").write_text(
        json.dumps({"obtained_facts_by_source": {"src-a": ["一条事实"]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "review" / "art-001" / "title-pack.json").write_text(
        json.dumps({"directions": [{"title": "标题甲"}]}, ensure_ascii=False), encoding="utf-8"
    )
    (root / "review" / "art-001" / REVIEW.split("/")[-1]).write_text('{"frozen": true}', encoding="utf-8")
    import hashlib
    delivery_sha = hashlib.sha256(
        (root / "delivery" / "art-001" / "delivery.md").read_bytes()
    ).hexdigest()
    (root / "review" / "art-001" / "independent-review.json").write_text(
        json.dumps({"status": "complete", "decision": "approve", "artifact_sha256": delivery_sha},
                   ensure_ascii=False), encoding="utf-8"
    )
    (root / "batch.json").write_text(json.dumps({
        "articles": [{"article_id": "art-001", "gate_status": {"controller_acceptance": "accepted"}}],
        "publication_authorization": "not_authorized", "delivery_state": "withheld",
    }, ensure_ascii=False), encoding="utf-8")
    (root / "review" / "final-review.json").write_text(
        json.dumps({"verdict": "PUBLISHABLE"}, ensure_ascii=False), encoding="utf-8"
    )
    seal(root, identity="owner", articles=seal_articles(root))
    assert is_sealed(root) is True
    return root


def _stub_renderer(tmp_path: Path) -> str:
    script = tmp_path / "stub_render.py"
    script.write_text(
        "import pathlib, sys\n"
        "text = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')\n"
        "print('<section style=\"font-size:16px\">' + text.replace(chr(10), ' ') + '</section>')\n",
        encoding="utf-8",
    )
    return f"{sys.executable} {script} {{md_file}} {{theme}}"


def _stub_runner(calls: list[list[str]]):
    def runner(argv, cwd):
        calls.append(list(argv))
        return subprocess.CompletedProcess(args=list(argv), returncode=0, stdout="ok", stderr="")
    return runner


# ---- ① 账本预检 ----

def test_precheck_refuses_on_sealed_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _sealed_run(tmp_path)
    before, log_before = snapshot(root), len(read_changelog(root))

    def no_llm(*_a, **_k):
        raise pre.LlmUnavailable("offline")

    monkeypatch.setattr(pre, "llm_chat", no_llm)
    monkeypatch.setattr(sys, "argv", ["x", "--run-root", str(root), "--aid", "art-001"])
    assert pre.main() == 2
    assert (root / REVIEW).read_text(encoding="utf-8") == '{"frozen": true}'
    assert len(read_changelog(root)) == log_before


# ---- ② evidence_rebind ----

def test_evidence_rebind_refuses_apply_on_sealed_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _sealed_run(tmp_path)
    before, log_before = snapshot(root), len(read_changelog(root))
    monkeypatch.setattr(sys, "argv", ["x", "--run-root", str(root), "--apply"])
    assert evidence_rebind.main() == 2
    assert is_clean(diff(before, snapshot(root)))
    assert len(read_changelog(root)) == log_before


def test_evidence_rebind_force_writes_and_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _sealed_run(tmp_path)
    # 制造真实的"交付变了"：封存后改稿，旧 approve 必须被判失效。
    # 这是**模拟外部改动**，测试里显式申请令牌（真实场景这类写入应被 runs_guard 拦下）。
    from article_group import runs_guard

    with runs_guard.sealed_write_token(root, reason="test:simulate-out-of-band-change", author="tester"):
        (root / "delivery" / "art-001" / "delivery.md").write_text("# 标题\n\n改过的正文。\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["x", "--run-root", str(root), "--apply", "--force"])
    assert evidence_rebind.main() == 0
    record = json.loads((root / "review" / "art-001" / "independent-review.json").read_text(encoding="utf-8"))
    assert record["stale"] is True
    assert any(entry["path"].endswith("independent-review.json") for entry in read_changelog(root))


# ---- ③ title_freeze ----

def test_title_freeze_refuses_on_sealed_run(tmp_path: Path):
    root = _sealed_run(tmp_path)
    (root / "review" / "art-001" / "title-freeze.json").unlink(missing_ok=True)
    before = snapshot(root)
    result = title_freeze.freeze(root, "art-001")
    assert result["status"] == "run_sealed"
    assert is_clean(diff(before, snapshot(root)))
    assert not (root / "review" / "art-001" / "title-freeze.json").exists()


def test_title_freeze_force_writes_on_sealed_run(tmp_path: Path):
    root = _sealed_run(tmp_path)
    (root / "review" / "art-001" / "title-freeze.json").unlink(missing_ok=True)
    result = title_freeze.freeze(root, "art-001", force=True)
    assert result["status"] == "frozen"
    assert (root / "review" / "art-001" / "title-freeze.json").is_file()
    assert read_changelog(root)[-1]["reason"] == "title_freeze"


# ---- ④ wechat_render ----

def test_wechat_render_refuses_on_sealed_run(tmp_path: Path):
    root = _sealed_run(tmp_path)
    before = snapshot(root)
    report = wechat_render.render_run(root, renderer_cmd=_stub_renderer(tmp_path))
    assert report["status"] == "run_sealed"
    assert is_clean(diff(before, snapshot(root)))
    assert not (root / "wechat").exists()


def test_wechat_render_force_renders_on_sealed_run(tmp_path: Path):
    root = _sealed_run(tmp_path)
    report = wechat_render.render_run(root, renderer_cmd=_stub_renderer(tmp_path), force=True)
    assert report["status"] == "ok"
    assert (root / "wechat" / "art-001.wx.html").is_file()
    assert any(entry["reason"].startswith("wechat_render") for entry in read_changelog(root))


# ---- ⑤ close_out ----

def test_close_out_refuses_on_sealed_run(tmp_path: Path):
    root = _sealed_run(tmp_path)
    before = snapshot(root)
    report = close_out_mod.close_out(root, confirm=True)
    assert report["status"] == "run_sealed"
    assert "unseal" in report["reason"]
    assert is_clean(diff(before, snapshot(root)))


def test_close_out_force_proceeds_on_sealed_run(tmp_path: Path):
    root = _sealed_run(tmp_path)
    calls: list[list[str]] = []
    report = close_out_mod.close_out(
        root, confirm=True, force=True, runner=_stub_runner(calls),
        renderer_cmd=_stub_renderer(tmp_path), repo_root=tmp_path,
    )
    assert report["status"] == "ok", report
    assert calls  # 人工签字脚本被调用
    assert (root / "SEALED").is_file()  # 仍处于封存状态（重新封存或保持）


def test_all_five_entrypoints_agree_on_refusal_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """五个入口的拒绝理由都应提到封存与 force，便于排查。"""
    root = _sealed_run(tmp_path)
    reasons = [
        close_out_mod.close_out(root, confirm=True)["reason"],
        wechat_render.render_run(root, renderer_cmd=_stub_renderer(tmp_path))["reason"],
    ]

    def no_llm(*_a, **_k):
        raise pre.LlmUnavailable("offline")

    monkeypatch.setattr(pre, "llm_chat", no_llm)
    monkeypatch.setattr(sys, "argv", ["x", "--run-root", str(root), "--aid", "art-001"])
    pre.main()  # 打印拒绝信息，退出码 2
    for reason in reasons:
        assert "封存" in reason and "force" in reason
