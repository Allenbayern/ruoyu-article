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


def _sealed_run(tmp_path: Path) -> Path:
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
