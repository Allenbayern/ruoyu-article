"""收口回归：此前绕过留底通道的写手，现在也必须"先留底、再记账、封存守门"。

2026-09-17 runs_guard 上线后逐个咬出来的真实缺口（都不是五个"已守门入口"里的写法问题，
而是**同一批入口内部的旁路写入**）：

| 写手 | 原状 | 现状 |
|---|---|---|
| `scripts/record_controller_acceptance.py` | 三处裸写，不入账 | 走 write_evidence_json，带 --force |
| `article_group/run_record.py` | RUN-RECORD.machine.md 裸写 | 走 write_evidence，带 --force |
| `article_group/final_review.py` | review/final-review.json 裸写 | 走 write_evidence_json，带 --force |
| `close_out` 的 STEP-LOG.md | 裸写（封存 run 上无留底、无记账） | 走 write_evidence |
| `wechat_render` 的 `wechat/` mkdir | 显式 mkdir，force 时被护栏拦（force 半生效） | 目录由写入通道在令牌内创建 |

拒绝口径与五个入口一致：**退出码 2 + 一句人话**，不让人看 traceback 去猜。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from article_group.close_out import write_step_log_markdown
from article_group.evidence_write import read_changelog
from article_group.run_state import seal, seal_articles

REPO_ROOT = Path(__file__).resolve().parents[1]


def _sealed_run(tmp_path: Path, *, with_capture: bool = False) -> Path:
    root = tmp_path / "daily-950"
    (root / "delivery" / "art-001").mkdir(parents=True)
    (root / "review" / "art-001").mkdir(parents=True)
    (root / "delivery" / "art-001" / "delivery.md").write_text("# 标题\n\n正文。\n", encoding="utf-8")
    (root / "review" / "art-001" / "source-stripped.md").write_text("正文。\n", encoding="utf-8")
    (root / "review" / "art-001" / "source-stripped-readability.json").write_text(
        json.dumps({"source_stripped_readability": "pending"}, ensure_ascii=False), encoding="utf-8"
    )
    (root / "batch.json").write_text(json.dumps({
        "articles": [{"article_id": "art-001", "gate_status": {}}],
        "publication_authorization": "not_authorized",
    }, ensure_ascii=False), encoding="utf-8")
    if with_capture:  # 必须在封存**之前**写（封存后连它自己也写不进去）
        (root / "capture-manifest.json").write_text(json.dumps({
            "run_id": "run-sealed-950",
            "created_at": "2026-09-17T09:00:00+08:00",
            "source_lanes": ["wechat_long_form"],
            "samples": [],
        }, ensure_ascii=False), encoding="utf-8")
    seal(root, identity="owner", articles=seal_articles(root))
    return root


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *argv], cwd=REPO_ROOT, capture_output=True, text=True, timeout=120
    )


# ---- controller 验收记录（人工签字入口） ----


def test_controller_acceptance_refuses_sealed_run_without_force(tmp_path: Path):
    root = _sealed_run(tmp_path)
    result = _run(["scripts/record_controller_acceptance.py",
                   "--run-root", str(root), "--identity", "owner"])
    assert result.returncode == 2
    assert "封存" in result.stderr and "force" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (root / "review" / "attestation" / "art-001.human.json").exists()
    assert read_changelog(root) == []


def test_controller_acceptance_force_writes_and_logs(tmp_path: Path):
    root = _sealed_run(tmp_path)
    result = _run(["scripts/record_controller_acceptance.py",
                   "--run-root", str(root), "--identity", "owner", "--force"])
    assert result.returncode == 0, result.stderr
    attestation = root / "review" / "attestation" / "art-001.human.json"
    assert attestation.is_file()
    reasons = [entry["reason"] for entry in read_changelog(root)]
    assert any(reason.startswith("controller_acceptance") for reason in reasons)
    assert all(entry["forced"] is True for entry in read_changelog(root))
    # batch.json 被改写前留了底
    assert any(entry["snapshot_path"] for entry in read_changelog(root))
    assert json.loads((root / "batch.json").read_text(encoding="utf-8"))["articles"][0][
        "gate_status"]["controller_acceptance"] == "accepted"


# ---- 机器记录 / 总复核 ----


def test_run_record_refuses_then_force_writes_with_log(tmp_path: Path):
    root = _sealed_run(tmp_path)
    refused = _run(["-m", "article_group.run_record", str(root)])
    assert refused.returncode == 2
    assert "封存" in refused.stderr and "Traceback" not in refused.stderr
    assert not (root / "RUN-RECORD.machine.md").exists()

    forced = _run(["-m", "article_group.run_record", str(root), "--force"])
    assert forced.returncode == 0, forced.stderr
    assert (root / "RUN-RECORD.machine.md").is_file()
    assert read_changelog(root)[-1]["reason"] == "run_record:machine"
    assert read_changelog(root)[-1]["forced"] is True


def test_final_review_refuses_then_force_writes_with_log(tmp_path: Path):
    root = _sealed_run(tmp_path)
    refused = _run(["-m", "article_group.final_review", "--batch", str(root)])
    assert refused.returncode == 2
    assert "封存" in refused.stderr and "Traceback" not in refused.stderr
    assert not (root / "review" / "final-review.json").exists()

    forced = _run(["-m", "article_group.final_review", "--batch", str(root), "--force"])
    assert forced.returncode in (0, 1), forced.stderr  # 1 = 记录生成但 verdict 非 PUBLISHABLE
    assert (root / "review" / "final-review.json").is_file()
    assert read_changelog(root)[-1]["reason"] == "final_review"


# ---- close_out 内部的 STEP-LOG.md ----


def test_step_log_markdown_goes_through_the_write_channel(tmp_path: Path):
    root = _sealed_run(tmp_path)
    write_step_log_markdown(root, force=True)
    assert (root / "STEP-LOG.md").is_file()
    entry = read_changelog(root)[-1]
    assert entry["reason"] == "close_out:step_log_markdown"
    assert entry["forced"] is True


# ---- 新管线 CLI：封存拒绝也要"退出码 2 + 一句人话"，不给 traceback ----


def _sealed_run_with_capture(tmp_path: Path) -> tuple[Path, Path]:
    root = _sealed_run(tmp_path, with_capture=True)
    return root, root / "capture-manifest.json"


def test_viral_research_package_cli_refuses_sealed_run_with_a_message(tmp_path: Path):
    root, capture = _sealed_run_with_capture(tmp_path)
    result = _run(["scripts/codex_viral_research_package.py",
                   "--capture-manifest", str(capture), "--run-root", str(root),
                   "--output-root", str(root / "viral-research" / "package")])
    assert result.returncode == 2
    assert "封存" in result.stderr and "--force" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (root / "viral-research").exists()


def test_viral_library_index_cli_refuses_sealed_output(tmp_path: Path):
    root, _capture = _sealed_run_with_capture(tmp_path)
    result = _run(["scripts/codex_viral_library_index.py",
                   "--project-root", str(tmp_path), "--evidence-run", "runs/2026-09-16/daily-008",
                   "--output", str(root / "review" / "index.json")])
    assert result.returncode == 2
    assert "封存" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (root / "review" / "index.json").exists()


def test_viral_research_attach_evidence_cli_refuses_sealed_run(tmp_path: Path):
    """给人签字的凭证补录工具：撞上封存 run 也要一句人话（008 那类补证会用到它）。"""
    from article_group.run_state import seal
    from tests.test_viral_research_cards import _build_package, _write_evidence

    package_root, sample_id = _build_package(tmp_path)
    evidence = _write_evidence(tmp_path)
    seal(tmp_path, identity="owner")  # 把整棵 tmp_path 变成封存区

    result = _run(["scripts/codex_viral_research_attach_evidence.py",
                   "--package-root", str(package_root), "--sample-id", sample_id,
                   "--evidence-file", str(evidence),
                   "--output-revision", str(package_root / "revisions" / "rev-001")])
    assert result.returncode == 2
    assert "封存" in result.stderr and "--force" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (package_root / "revisions").exists()


def test_viral_distill_cli_refuses_sealed_output(tmp_path: Path):
    from article_group.run_state import seal
    from tests.test_viral_research_distill import _criteria, _prepare_and_write_cards

    prepare_path, cards_root, _ = _prepare_and_write_cards(tmp_path)
    package_root = cards_root.parent / "package"
    seal(tmp_path, identity="owner")

    result = _run(["scripts/codex_viral_distill.py", "finalize",
                   "--prepared", str(prepare_path), "--package-root", str(package_root),
                   "--cards-root", str(cards_root),
                   "--platform", _criteria().platform, "--medium", _criteria().medium,
                   "--content-domain", _criteria().content_domain,
                   "--narrative-purpose", _criteria().narrative_purpose,
                   "--output", str(tmp_path / "review.json")])
    assert result.returncode == 2
    assert "封存" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "review.json").exists()
