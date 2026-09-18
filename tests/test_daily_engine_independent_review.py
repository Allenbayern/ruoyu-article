"""daily_engine 只允许刷新"还没复核"的 canonical L2 占位记录。

2026-09-18（daily-009 复盘）：引擎原来只认 ``status == "complete"``，于是
``codex_review`` 写的 ``status=PASS`` + ``decision=approve`` 记录被当成"还没复核"，
重跑时换成 PENDING 占位符——哈希绑定依旧逐位相同（evidence_rebind 看不出异常），
门禁又把 PENDING 只当治理待办，一次真实批准就这样静默消失。判据现在统一到
``independent_review.is_placeholder_record``。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import daily_engine


def _run_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs" / "2026-09-18" / "daily-900"
    (root / "delivery" / "art-001").mkdir(parents=True)
    (root / "drafts" / "art-001").mkdir(parents=True)
    (root / "review" / "art-001").mkdir(parents=True)
    (root / "delivery" / "art-001" / "delivery.md").write_text("# 标题\n\n正文\n", encoding="utf-8")
    (root / "drafts" / "art-001" / "body_draft.md").write_text("正文\n", encoding="utf-8")
    (root / "review" / "art-001" / "title-pack.json").write_text(
        '{"directions":[{"title":"标题"}]}', encoding="utf-8"
    )
    return root


@pytest.fixture()
def engine_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """把引擎的 spec 绑定换成一个 tmp run（ROOT/RUN_ID/digest/write_json）。"""

    root = _run_root(tmp_path)
    writes: list[str] = []
    monkeypatch.setattr(daily_engine, "ROOT", root, raising=False)
    monkeypatch.setattr(daily_engine, "RUN_ID", "2026-09-18/daily-900", raising=False)
    monkeypatch.setattr(
        daily_engine,
        "digest",
        lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        raising=False,
    )

    def fake_write_json(path: str, value: object) -> None:
        writes.append(path)
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    monkeypatch.setattr(daily_engine, "write_json", fake_write_json, raising=False)
    return root, writes


def _review_path(root: Path) -> Path:
    return root / "review" / "art-001" / "independent-review.json"


def _write_record(root: Path, record: dict) -> bytes:
    path = _review_path(root)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path.read_bytes()


FINISHED_RECORDS = {
    # codex_review 契约记录：daily-009 的 approve 就是这种形状被覆盖的
    "contract_pass": {
        "schema_version": "codex-review-contract-1.0",
        "article_id": "art-001",
        "status": "PASS",
        "decision": "approve",
        "structured_result": True,
        "artifact_sha256": "old" * 20,
    },
    # canonical 记录
    "canonical_complete": {
        "schema_version": "article-independent-review-v1",
        "article_id": "art-001",
        "status": "complete",
        "decision": "approve",
        "next_step": "stop",
        "artifact_sha256": "old" * 20,
    },
    # 跑过但没跑出结论：超时记录同样是证据
    "unverified_timeout": {
        "schema_version": "article-independent-review-v1",
        "article_id": "art-001",
        "status": "UNVERIFIED",
        "decision": "timeout",
        "timeout_reason": "review_deadline_exceeded",
        "artifact_sha256": "old" * 20,
    },
    # evidence_rebind 判失效后的记录：带 stale 痕迹，不能被占位符抹掉
    "stale_after_content_change": {
        "schema_version": "article-independent-review-v1",
        "article_id": "art-001",
        "status": "PENDING",
        "decision": "human_review_required",
        "stale": True,
        "stale_reason": "delivery_or_title_changed:artifact_sha256",
        "artifact_sha256": "old" * 20,
    },
}


def test_missing_record_gets_a_placeholder(engine_run):
    root, writes = engine_run

    written = daily_engine.ensure_independent_review_placeholder("art-001", "delivery/art-001/delivery.md")

    record = json.loads(_review_path(root).read_text(encoding="utf-8"))
    assert written is True
    assert writes == ["review/art-001/independent-review.json"]
    assert record["status"] == "PENDING"
    assert record["decision"] == "human_review_required"
    assert record["run_id"] == "2026-09-18/daily-900"
    assert record["artifact_sha256"] == hashlib.sha256(
        (root / "delivery" / "art-001" / "delivery.md").read_bytes()
    ).hexdigest()


def test_pending_placeholder_is_refreshed_to_the_current_hashes(engine_run):
    root, _ = engine_run
    _write_record(
        root,
        {
            "schema_version": "article-independent-review-v1",
            "article_id": "art-001",
            "status": "PENDING",
            "decision": "human_review_required",
            "artifact_sha256": "stale" * 12 + "stale",
        },
    )

    written = daily_engine.ensure_independent_review_placeholder("art-001", "delivery/art-001/delivery.md")

    record = json.loads(_review_path(root).read_text(encoding="utf-8"))
    assert written is True
    assert record["artifact_sha256"] == hashlib.sha256(
        (root / "delivery" / "art-001" / "delivery.md").read_bytes()
    ).hexdigest()


@pytest.mark.parametrize("name", sorted(FINISHED_RECORDS))
def test_finished_records_are_never_replaced_by_a_placeholder(engine_run, name):
    root, writes = engine_run
    before = _write_record(root, FINISHED_RECORDS[name])

    written = daily_engine.ensure_independent_review_placeholder("art-001", "delivery/art-001/delivery.md")

    assert written is False
    assert writes == []
    assert _review_path(root).read_bytes() == before
