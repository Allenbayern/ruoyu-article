"""daily_engine 接线测试：每个阶段都要落一条步骤日志，顺序正确。

不跑真实流水线：阶段函数换成计数桩，spec 换成最小假对象，只验证 daily_engine
的 build_run 是否把每一步都包进了 append-only 的 step-log.jsonl，并在最后生成
STEP-LOG.md。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from article_group.step_log import read_steps
from scripts import daily_engine as engine


class FakeSpec:
    """提供 build_run 通过 getattr 绑定的全部名字。"""

    ROOT = ""
    RUN_ID = ""
    GROUP_ID = "fake-group"
    CAPTURED_AT = "2026-09-17T00:00:00+08:00"
    CONTRACT = {}
    RADAR_RECORDS: list = []
    SOURCES: list = []
    CANDIDATES: list = []
    REJECTED_PRIOR_WORKS: list = []
    SLOT_DECISIONS: list = []
    TASK_CARD_REQUIRED_FIELDS: list = []
    STRONGEST_HOOKS: dict = {}
    MATERIAL_SPECS: dict = {}
    BRIEFS: dict = {}
    BRIEF_SPECS: dict = {}
    BODIES: dict = {}
    CONTENT_RECORD_ARGS: list = []
    TITLES: dict = {}
    SOURCE_IDS: dict = {}
    MODES: dict = {}
    RULE_CLAIMS: list = []
    BATCH_SPECS: dict = {}

    @staticmethod
    def digest(path):  # noqa: ARG004
        return {"sha256": "0" * 64}

    @staticmethod
    def ref(path):  # noqa: ARG004
        return {"ref": True}


@pytest.fixture()
def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """桩掉所有阶段函数与写文件助手，记录调用顺序。"""
    calls: list[str] = []

    def make(name):
        def stage(*_args, **_kwargs):
            calls.append(name)
            return {"ok": name}
        return stage

    for name in ("discovery", "source_manifest", "candidates", "briefs_and_tasks",
                 "material_pack", "portfolio", "gates"):
        monkeypatch.setattr(engine, name, make(name))
    monkeypatch.setattr(engine, "bodies", lambda: {"art-001": "正文"})
    monkeypatch.setattr(engine, "content_record", make("content_record"))
    monkeypatch.setattr(engine, "reviews_and_delivery", make("reviews_and_delivery"))
    monkeypatch.setattr(engine, "batch_manifest", make("batch_manifest"))
    monkeypatch.setattr(engine, "wechat_render_step", lambda: {"status": "ok"})

    def write_text(path, value):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding="utf-8")

    def write_json(path, value):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    spec = FakeSpec()
    spec.ROOT = str(tmp_path)
    spec.RUN_ID = "2026-09-17/daily-fake"
    spec.MATERIAL_SPECS = {"art-001": {}}
    spec.CONTENT_RECORD_ARGS = [{
        "aid": "art-001",
        "mode": "reported_feature",
        "role": "media_report",
        "core_object": "对象",
        "question": "问题",
        "mechanism": "机制",
        "takeaway": "结论",
        "hard": [],
        "bases": [],
        "boundary": "边界",
        "source_ids": ["src-a"],
    }]
    spec.write_text = write_text
    spec.write_json = write_json
    return spec, calls


def test_build_run_logs_every_stage_in_order(wired):
    spec, calls = wired
    engine.build_run(spec)

    names = [step["name"] for step in read_steps(spec.ROOT)]
    assert names == [
        "discovery",
        "source_manifest",
        "candidates",
        "briefs_and_tasks",
        "material_pack:art-001",
        "bodies",
        "drafts_write",
        "content_record:art-001",
        "reviews_and_delivery",
        "evidence_rebind",
        "portfolio",
        "gates",
        "batch_manifest",
        "wechat_render",
        "preview_site",
        "run_manifest",
        "step_log_markdown",
    ]
    assert calls[:4] == ["discovery", "source_manifest", "candidates", "briefs_and_tasks"]


def test_build_run_writes_markdown_timeline_and_manifest_field(wired):
    spec, _ = wired
    engine.build_run(spec)

    timeline = Path(spec.ROOT) / "STEP-LOG.md"
    assert timeline.is_file()
    text = timeline.read_text(encoding="utf-8")
    assert "| 步骤 | 状态 |" in text and "not_authorized" in text

    manifest = json.loads((Path(spec.ROOT) / "run-manifest.json").read_text(encoding="utf-8"))
    assert manifest["step_log"] == "step-log.jsonl"
    assert manifest["wechat_render"]["status"] == "ok"
    assert manifest["publication_authorization"] == "not_authorized"


def test_failed_stage_is_logged_and_propagated(wired, monkeypatch: pytest.MonkeyPatch):
    spec, _ = wired

    def boom():
        raise RuntimeError("gate exploded")

    monkeypatch.setattr(engine, "gates", boom)
    with pytest.raises(RuntimeError):
        engine.build_run(spec)

    steps = read_steps(spec.ROOT)
    failed = [step for step in steps if step["status"] == "failed"]
    assert [step["name"] for step in failed] == ["gates"]
    assert failed[0]["error"].startswith("RuntimeError:gate exploded")
    # 失败之前的步骤仍然留痕，且日志是追加的
    assert [step["name"] for step in steps][:3] == ["discovery", "source_manifest", "candidates"]
