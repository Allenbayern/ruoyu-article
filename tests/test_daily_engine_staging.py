"""daily_engine 分阶段重跑（2026-09-18，A2）。

背景：整条流水线跑一次要含 docker 公众号渲染（实测 ~60 min），尾段改一行也得从头再来。
这里把阶段编成显式清单（``stage_plan``）并按名字挑选（``select_stages``），跳过的阶段
按"磁盘上已有"对待；未知阶段名、缺前置产物一律拒绝执行，不静默跳过。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from article_group.step_log import read_steps
from scripts import daily_engine

SPEC_TEMPLATE = '''
import json
from pathlib import Path

ROOT = Path({root!r})
RUN_ID = "2026-09-18/daily-fake"
GROUP_ID = "fake-group"
CAPTURED_AT = "2026-09-18T00:00:00+08:00"
CONTRACT = {{}}
RADAR_RECORDS = []
SOURCES = []
CANDIDATES = []
REJECTED_PRIOR_WORKS = []
SLOT_DECISIONS = []
TASK_CARD_REQUIRED_FIELDS = []
STRONGEST_HOOKS = {{}}
MATERIAL_SPECS = {{"art-001": {{"role": "media_report"}}}}
BRIEFS = {{}}
BRIEF_SPECS = []
BODIES = {{"art-001": "正文"}}
CONTENT_RECORD_ARGS = [
    {{
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
    }}
]
TITLES = {{}}
SOURCE_IDS = {{}}
MODES = {{}}
RULE_CLAIMS = []
BATCH_SPECS = {{}}


def digest(path):
    return "0" * 64


def write_json(path, value):
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def write_text(path, value):
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value.rstrip() + "\\n", encoding="utf-8")


def ref(path, version="1.0"):
    return {{"path": path, "version": version}}
'''


@pytest.fixture()
def spec(tmp_path: Path):
    # run 根形态（runs/<date>/<id>）：写才会走留底通道，测试才能验证"接进通道"这件事。
    root = tmp_path / "runs" / "2026-09-18" / "daily-fake"
    root.mkdir(parents=True)
    spec_path = tmp_path / "run_fake_daily.py"
    spec_path.write_text(SPEC_TEMPLATE.format(root=str(root)), encoding="utf-8")
    return daily_engine.load_spec(spec_path), root


@pytest.fixture()
def stubbed(monkeypatch: pytest.MonkeyPatch):
    """把所有阶段换成分组计数桩（分阶段重跑只该调用被选中的那些）。"""

    calls: list[str] = []

    def make(name):
        def stage(*_args, **_kwargs):
            calls.append(name)
            return {"status": "ok", "stage": name}

        return stage

    for name in (
        "discovery",
        "source_manifest",
        "candidates",
        "briefs_and_tasks",
        "material_pack",
        "portfolio",
        "gates",
        "reviews_and_delivery",
        "batch_manifest",
        "wechat_render_step",
        "preview_site_step",
        "evidence_rebind_step",
    ):
        monkeypatch.setattr(daily_engine, name, make(name))
    return calls


def _bind(loaded):
    daily_engine.bind_spec(loaded)
    return loaded


def test_stage_plan_lists_every_unit_in_order(spec):
    loaded, _ = spec
    _bind(loaded)
    plan = daily_engine.stage_plan({"art-001": "正文"})
    assert [stage.name for stage in plan] == [
        "discovery",
        "source_manifest",
        "candidates",
        "briefs_and_tasks",
        "material_pack:art-001",
        "bodies",
        "drafts_write",
        "content_record:art-001",
        "editor_read",
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


def test_select_stages_accepts_groups_full_names_and_from(spec):
    loaded, _ = spec
    _bind(loaded)
    plan = daily_engine.stage_plan({"art-001": "正文"})

    assert [s.name for s in daily_engine.select_stages(plan, stages=["gates"])] == ["gates"]
    assert [s.name for s in daily_engine.select_stages(plan, stages=["material_pack"])] == [
        "material_pack:art-001"
    ]
    assert [s.name for s in daily_engine.select_stages(plan, from_stage="wechat_render")] == [
        "wechat_render",
        "preview_site",
        "run_manifest",
        "step_log_markdown",
    ]
    assert len(daily_engine.select_stages(plan)) == len(plan)


def test_unknown_stage_name_is_rejected_not_silently_skipped(spec):
    loaded, _ = spec
    _bind(loaded)
    plan = daily_engine.stage_plan({"art-001": "正文"})
    with pytest.raises(ValueError, match="未知阶段"):
        daily_engine.select_stages(plan, stages=["wechat-render"])  # 连字符是常见笔误
    with pytest.raises(ValueError, match="未知阶段"):
        daily_engine.select_stages(plan, from_stage="nope")


def _seed_gate_prerequisites(root: Path) -> None:
    (root / "task-hierarchy").mkdir(parents=True, exist_ok=True)
    (root / "task-hierarchy" / "article-task-art-001.json").write_text("{}", encoding="utf-8")
    (root / "material-packs").mkdir(parents=True, exist_ok=True)
    (root / "material-packs" / "art-001.json").write_text("{}", encoding="utf-8")
    (root / "candidate-pool.json").write_text("{}", encoding="utf-8")


def test_partial_run_executes_only_the_selected_stages(spec, stubbed):
    loaded, root = spec
    _seed_gate_prerequisites(root)
    executed = daily_engine.build_run(loaded, stages=["gates"])

    assert executed == ["gates"]
    assert stubbed == ["gates"]
    steps = read_steps(root)
    assert [step["name"] for step in steps] == ["gates"]
    assert "分阶段重跑" in steps[0]["note"]


def test_from_stage_runs_the_tail_in_order(spec, stubbed):
    loaded, root = spec
    delivery = root / "delivery" / "art-001"
    delivery.mkdir(parents=True)
    (delivery / "delivery.md").write_text("# 标题\n\n正文\n", encoding="utf-8")

    executed = daily_engine.build_run(loaded, from_stage="wechat_render")

    assert executed == ["wechat_render", "preview_site", "run_manifest", "step_log_markdown"]
    assert stubbed == ["wechat_render_step", "preview_site_step"]
    assert [step["name"] for step in read_steps(root)] == executed


def test_partial_run_refuses_a_missing_prerequisite(spec, stubbed):
    loaded, root = spec
    with pytest.raises(daily_engine.StagePrerequisiteMissing, match="delivery/\\*/delivery.md"):
        daily_engine.build_run(loaded, from_stage="wechat_render")
    assert read_steps(root) == []  # 拒绝在动手之前，不留半条日志


def test_partial_run_keeps_the_previous_wechat_status_in_the_manifest(spec, stubbed):
    loaded, root = spec
    (root / "run-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "run-manifest-v1",
                "wechat_render": {"status": "ok", "cached_articles": ["art-001"]},
                "preview_site": {"status": "ok", "index_path": "preview/index.html"},
            }
        ),
        encoding="utf-8",
    )

    daily_engine.build_run(loaded, stages=["run_manifest"])

    manifest = json.loads((root / "run-manifest.json").read_text(encoding="utf-8"))
    assert manifest["wechat_render"]["cached_articles"] == ["art-001"]
    assert manifest["preview_site"]["index_path"] == "preview/index.html"
    assert manifest["publication_authorization"] == "not_authorized"


def test_run_manifest_records_not_run_without_a_previous_status(spec, stubbed):
    loaded, root = spec
    daily_engine.build_run(loaded, stages=["run_manifest"])
    manifest = json.loads((root / "run-manifest.json").read_text(encoding="utf-8"))
    assert manifest["wechat_render"] == {"status": "not_run"}
    assert manifest["preview_site"] == {"status": "not_run"}


# --- CLI -------------------------------------------------------------------


def test_cli_lists_stages_without_running_anything(spec, stubbed, capsys: pytest.CaptureFixture):
    loaded, root = spec
    exit_code = daily_engine.main(["--spec", str(Path(loaded.__file__)), "--list-stages"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "wechat_render" in out and "material_pack:art-001" in out
    assert stubbed == []
    assert read_steps(root) == []


def test_cli_rejects_an_unknown_stage(spec, capsys: pytest.CaptureFixture):
    loaded, _ = spec
    exit_code = daily_engine.main(["--spec", str(Path(loaded.__file__)), "--stages", "gate"])
    assert exit_code == 2
    assert "未知阶段" in capsys.readouterr().err


def test_cli_rejects_a_missing_run_for_a_partial_rerun(tmp_path, capsys: pytest.CaptureFixture):
    spec_path = tmp_path / "run_fake_daily.py"
    spec_path.write_text(SPEC_TEMPLATE.format(root=str(tmp_path / "nope")), encoding="utf-8")
    exit_code = daily_engine.main(["--spec", str(spec_path), "--from", "run_manifest"])
    assert exit_code == 2
    assert "分阶段重跑需要已存在的 run" in capsys.readouterr().err


def test_cli_rejects_a_missing_spec(tmp_path, capsys: pytest.CaptureFixture):
    exit_code = daily_engine.main(["--spec", str(tmp_path / "nope.py")])
    assert exit_code == 2
    assert "spec 模块不存在" in capsys.readouterr().err


# --- 写手通道（2026-09-18，B7′）--------------------------------------------


def test_spec_writers_go_through_the_channel(spec):
    """spec 的 write_json/write_text 在 bind_spec 里被包进留底通道。"""

    from article_group.evidence_write import read_changelog

    loaded, root = spec
    daily_engine.bind_spec(loaded)

    daily_engine.write_text("drafts/art-001/body_draft.md", "第一版")
    daily_engine.write_text("drafts/art-001/body_draft.md", "第二版")

    assert (root / "drafts" / "art-001" / "body_draft.md").read_text(encoding="utf-8") == "第二版\n"
    reasons = [entry["reason"] for entry in read_changelog(root)]
    assert reasons.count("daily_engine:drafts/art-001/body_draft.md") == 2
    snapshots = list((root / "review" / ".before").rglob("drafts/art-001/body_draft.md"))
    assert snapshots and snapshots[0].read_text(encoding="utf-8") == "第一版\n"


def test_base_helper_writes_go_through_the_channel(spec):
    """base（generate_daily_001）的写不再绕过留底通道（daily-009 曾 63/152 文件无账）。"""

    from article_group.evidence_write import read_changelog
    from scripts import generate_daily_001 as base

    loaded, root = spec
    daily_engine.bind_spec(loaded)

    base.write_text("delivery/art-001/delivery.md", "# 标题\n\n正文")
    base.write_json("review/art-001/title-pack.json", {"directions": [{"title": "标题"}]})

    assert (root / "delivery" / "art-001" / "delivery.md").read_text(encoding="utf-8") == "# 标题\n\n正文\n"
    assert json.loads((root / "review" / "art-001" / "title-pack.json").read_text(encoding="utf-8")) == {
        "directions": [{"title": "标题"}]
    }
    reasons = {entry["reason"] for entry in read_changelog(root)}
    assert "daily_engine:delivery/art-001/delivery.md" in reasons
    assert "daily_engine:review/art-001/title-pack.json" in reasons


def test_base_writes_stay_raw_when_base_root_is_another_run(spec, tmp_path: Path):
    """别的调用方改了 base.ROOT 时按原样裸写，不记到本 run 的账上。"""

    from article_group.evidence_write import read_changelog
    from scripts import generate_daily_001 as base

    loaded, root = spec
    daily_engine.bind_spec(loaded)
    other = tmp_path / "runs" / "2026-09-18" / "daily-other"
    other.mkdir(parents=True)
    base.ROOT = other

    base.write_text("notes/x.md", "历史重跑")

    assert (other / "notes" / "x.md").read_text(encoding="utf-8") == "历史重跑\n"
    assert read_changelog(root) == []
    assert read_changelog(other) == []


def test_the_engine_routes_writes_in_a_nested_runs_layout(tmp_path: Path):
    """nested-runs 布局（…/runs/<x>/runs/<date>/<id>）里引擎产物照样进留底通道。

    2026-09-18 L2 复核：旧 is_run_root 只看第一个 `runs` 组件 → 这种布局里
    `_route_write` 判 ROOT 不是 run 根 → **全部裸写**（无 before-image、无账本）。
    实测（同 spec 同数据，daily-008 副本）：旧代码 25 条账 / delivery 0 条，
    新代码 100 条 / delivery 2 + title-pack 4。
    """

    from article_group.evidence_write import read_changelog

    run = tmp_path / "home" / "runs" / "proj" / "runs" / "2026-09-18" / "daily-nested"
    run.mkdir(parents=True)
    spec_path = tmp_path / "spec_nested.py"
    spec_path.write_text(SPEC_TEMPLATE.format(root=str(run)), encoding="utf-8")

    daily_engine.build_run(daily_engine.load_spec(spec_path), stages=["drafts_write"])

    assert (run / "drafts" / "art-001" / "body_draft.md").is_file()
    reasons = {entry["reason"] for entry in read_changelog(run)}
    assert "daily_engine:drafts/art-001/body_draft.md" in reasons
    for outer in (tmp_path / "home" / "runs", tmp_path / "home" / "runs" / "proj",
                  tmp_path / "home" / "runs" / "proj" / "runs"):
        assert not (outer / "evidence-changelog.jsonl").exists()
