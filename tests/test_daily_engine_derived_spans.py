"""content_record 的派生跨度即时入账（2026-09-21，daily-011 art-001「七年后」的坑）。

规则：正文里"由已入账年份推出的具体跨度"（七年后/十年前）必须在**写账本的这一趟**
补齐——要么直接在 hard 里登记，要么用 spec 的 DERIVED_SPANS 声明。补不齐就当场失败，
不等 gates 阶段（那时才发现，改稿要重走一遍冻结链）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import daily_engine

BODY = "## 一节\n\n七年后，这部片又回到了大银幕。\n"
ARG = {
    "aid": "art-001",
    "mode": "reported_feature",
    "role": "media_report",
    "core_object": "对象",
    "question": "为什么",
    "mechanism": "机制",
    "takeaway": "结论",
    "bases": [],
    "boundary": "边界",
    "source_ids": ["src-a"],
}


@pytest.fixture()
def engine_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path
    monkeypatch.setattr(daily_engine, "ROOT", root, raising=False)
    monkeypatch.setattr(daily_engine, "RUN_ID", "2026-09-21/daily-902", raising=False)

    def fake_base_content_record(
        aid, body, source_id, core_object, question, mechanism, takeaway, hard, bases, boundary
    ):
        target = root / f"review/{aid}/content-fidelity.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "schema_version": "content-fidelity-v1",
                    "article_id": aid,
                    "standalone_check": {},
                    "hard_information": [dict(item) for item in hard],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(daily_engine.base, "content_record", fake_base_content_record, raising=False)
    return root


def _record(root: Path) -> dict:
    return json.loads((root / "review/art-001/content-fidelity.json").read_text(encoding="utf-8"))


def _call(body: str = BODY, hard: list[dict] | None = None) -> None:
    daily_engine.content_record(
        ARG["aid"],
        body,
        ARG["mode"],
        ARG["role"],
        ARG["core_object"],
        ARG["question"],
        ARG["mechanism"],
        ARG["takeaway"],
        hard if hard is not None else [{"information_id": "i1", "text": "影片 2019 年首映", "kind": "fact", "body_locator": "p1", "source_refs": ["src-a"], "source_locators": ["来源: 首映"], "independence_key": "k1"}],
        ARG["bases"],
        ARG["boundary"],
        ARG["source_ids"],
    )


def test_unregistered_span_fails_fast(engine_run, capsys: pytest.CaptureFixture[str]) -> None:
    """缺口未清 → 当场 SystemExit(1)，且把缺口写进账本留痕。"""
    with pytest.raises(SystemExit) as excinfo:
        daily_engine.content_record(
            ARG["aid"], BODY, ARG["mode"], ARG["role"], ARG["core_object"], ARG["question"],
            ARG["mechanism"], ARG["takeaway"],
            [{"information_id": "i1", "text": "影片 2019 年首映", "kind": "fact", "body_locator": "p1", "source_refs": ["src-a"], "source_locators": ["来源: 首映"], "independence_key": "k1"}],
            ARG["bases"], ARG["boundary"], ARG["source_ids"],
        )
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "七年后" in err and "p1" in err
    assert _record(engine_run)["ledger_span_gaps"], "缺口没有留痕"


def test_declared_span_is_registered_in_the_same_pass(engine_run, monkeypatch: pytest.MonkeyPatch) -> None:
    """DERIVED_SPANS 声明后：同一趟补进 hard_information，标 derived，且不再失败。"""
    monkeypatch.setattr(
        daily_engine,
        "DERIVED_SPANS",
        {
            "art-001": [
                {
                    "text": "影片原版 2019 年首映，2026 年重映，七年后重回大银幕",
                    "body_locator": "p1",
                    "source_refs": ["src-a"],
                    "source_locators": ["来源: 首映年份"],
                }
            ]
        },
        raising=False,
    )

    _call()

    record = _record(engine_run)
    derived = [item for item in record["hard_information"] if item.get("derived")]
    assert len(derived) == 1, record["hard_information"]
    assert derived[0]["body_locator"] == "p1"
    assert record["ledger_span_gaps"] == []


def test_body_without_specific_spans_passes(engine_run) -> None:
    _call(body="## 一节\n\n这些年，这部片一直被记得。\n")
    record = _record(engine_run)
    assert record["ledger_span_gaps"] == []
    assert not any(item.get("derived") for item in record["hard_information"])
