"""editor_read 阶段：写请求包 + 占位记录，且绝不覆盖已完成的编读结论。

为什么要有这个阶段（2026-09-21，daily-010 编读复盘 + daily-011 三轮 L2 复盘）：
编辑意见一旦在冻结（`reviews_and_delivery` 写标题包与交付）之后提出，每改一句正文都会
让标题包 / L2 approve / 渲染的哈希全部失效——daily-011 因此多跑了两轮 L2。所以编读必须
排在 `content_record` 之后、`reviews_and_delivery` 之前。

占位符判据沿用 daily-009 的教训：只有 status/decision 都还是待复核时才允许按新哈希刷新，
真跑过的结论（approve / needs_changes / UNVERIFIED）不得被引擎覆盖。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import daily_engine


def _run_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs" / "2026-09-21" / "daily-901"
    (root / "drafts" / "art-001").mkdir(parents=True)
    (root / "review" / "art-001").mkdir(parents=True)
    (root / "drafts" / "art-001" / "body_draft.md").write_text("正文\n", encoding="utf-8")
    return root


@pytest.fixture()
def engine_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """把引擎绑定换成一个 tmp run（ROOT/RUN_ID/digest/write_json + 最小 spec 数据）。"""

    root = _run_root(tmp_path)
    writes: list[str] = []
    monkeypatch.setattr(daily_engine, "ROOT", root, raising=False)
    monkeypatch.setattr(daily_engine, "RUN_ID", "2026-09-21/daily-901", raising=False)
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
    monkeypatch.setattr(
        daily_engine,
        "CONTENT_RECORD_ARGS",
        [
            {
                "aid": "art-001",
                "core_object": "对象",
                "question": "为什么只卖了 2 万多",
                "takeaway": "落点",
                "mechanism": "机制",
                "boundary": "边界",
            }
        ],
        raising=False,
    )
    monkeypatch.setattr(
        daily_engine,
        "TITLES",
        {"art-001": [("标题一", "疑问"), ("标题二", "机制")]},
        raising=False,
    )
    monkeypatch.setattr(
        daily_engine,
        "MATERIAL_SPECS",
        {"art-001": {"audience": "目标读者"}},
        raising=False,
    )
    return root, writes


def _editor_path(root: Path) -> Path:
    return root / "review" / "art-001" / "editor-review.json"


def test_editor_read_writes_request_pack(engine_run) -> None:
    root, writes = engine_run

    daily_engine.editor_read()

    request = json.loads(
        (root / "review/art-001/editor-read-request.json").read_text(encoding="utf-8")
    )
    assert request["planned_title"] == "标题一"
    assert request["core_question"] == "为什么只卖了 2 万多"
    assert request["reader"] == "目标读者"
    assert len(request["questions"]) == 7
    assert request["reply_contract"]["record_path"] == "review/art-001/editor-review.json"
    assert request["reply_contract"]["severity_rule"]
    assert "review/art-001/editor-read-request.json" in writes


def test_editor_read_writes_pending_placeholder_bound_to_body(engine_run) -> None:
    root, _ = engine_run

    daily_engine.editor_read()

    placeholder = json.loads(_editor_path(root).read_text(encoding="utf-8"))
    assert placeholder["status"] == "PENDING"
    assert placeholder["decision"] == "human_review_required"
    assert placeholder["body_sha256"] == hashlib.sha256("正文\n".encode("utf-8")).hexdigest()
    assert placeholder["publication_authorization"] == "not_authorized"


def test_editor_read_does_not_clobber_completed_record(engine_run) -> None:
    root, _ = engine_run
    _editor_path(root).write_text(
        json.dumps(
            {"status": "complete", "decision": "approve", "findings": []}, ensure_ascii=False
        ),
        encoding="utf-8",
    )

    daily_engine.editor_read()

    kept = json.loads(_editor_path(root).read_text(encoding="utf-8"))
    assert kept["status"] == "complete"
    assert kept["decision"] == "approve"


def test_editor_read_does_not_clobber_needs_changes_record(engine_run) -> None:
    root, _ = engine_run
    _editor_path(root).write_text(
        json.dumps(
            {"status": "complete", "decision": "needs_changes", "findings": [{"severity": "major"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    daily_engine.editor_read()

    kept = json.loads(_editor_path(root).read_text(encoding="utf-8"))
    assert kept["decision"] == "needs_changes"


def test_editor_read_refreshes_stale_placeholder(engine_run) -> None:
    root, _ = engine_run
    # 先写一份占位符，再让正文变长，重跑应当按新哈希刷新占位符
    daily_engine.editor_read()
    before = json.loads(_editor_path(root).read_text(encoding="utf-8"))["body_sha256"]
    (root / "drafts" / "art-001" / "body_draft.md").write_text("正文改了\n", encoding="utf-8")

    daily_engine.editor_read()

    after = json.loads(_editor_path(root).read_text(encoding="utf-8"))["body_sha256"]
    assert after == hashlib.sha256("正文改了\n".encode("utf-8")).hexdigest()
    assert after != before
