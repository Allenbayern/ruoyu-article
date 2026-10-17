"""tests for article_group.lieflat_checks —— lieflat 第 3/10/11 条接入检查。

约定：
- 真实 skill 目录存在时跑完整断言；不存在时 skip（本模块是 advisory，不应让环境缺失挂测试）。
- 另有一组用临时 stub skill 目录的密闭测试，验证加载/降级路径不依赖真实 skill。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from article_group.lieflat_checks import (
    DEFAULT_SKILL_DIR,
    _TRANSLATIONESE_ACTIONABLE,
    _TRANSLATIONESE_REFERENCE_ONLY,
    check_structure_advisories,
    check_translationese_advisories,
    run_lieflat_checks,
    skill_dir,
)
from article_group.humanize_pipeline import (
    check_local_gates,
    deterministic_polish,
    run_humanize_pipeline,
)

REAL_SKILL_DIR = Path(DEFAULT_SKILL_DIR)
SKILL_MD = REAL_SKILL_DIR / "SKILL.md"


def _skill_line(line_no: int) -> str:
    """取 SKILL.md 的第 line_no 行（1-based）——用来核对模块常数与 skill 原文是否同源。"""
    return SKILL_MD.read_text(encoding="utf-8").splitlines()[line_no - 1]


requires_skill = pytest.mark.skipif(
    not (REAL_SKILL_DIR / "scripts" / "check-structure.py").is_file()
    or not (REAL_SKILL_DIR / "scripts" / "check-translationese.py").is_file(),
    reason="本机未安装 lieflat-less-ai-tone skill",
)

SAMPLE = """# 标题

这是第一段，讲了一个很长的故事，主角在雨里跑，跑到了桥上，又跑了回来。

听起来像一条功能描述，其实底下换掉了一样更根本的东西。这里还有第二句，逗号很多，结构一样，长度也接近，收尾也相同。第三句同样如此，逗号很多，结构一样，长度也接近，收尾也相同。

当所有人都能用 AI 写文章时，内容本身就不再是竞争优势。对于早期团队来说，招人是最难的事。然而，成本也是一个需要考虑的因素。

这意味着产品找到了 PMF。这是一个能够让团队在不增加人力的情况下显著提升审核速度的工具。他扮演了关键角色。
"""


@requires_skill
def test_structure_advisories_locate_zero_anaphor_and_isomorph():
    res = check_structure_advisories(SAMPLE)

    zero = res["metrics"]["zero_anaphor_nonfirst_pct"]
    assert zero["hits"] == 1
    assert zero["paragraph_indexes"] == [1]
    assert zero["human_baseline"] == 0.14 and zero["ai_baseline"] == 0.61
    assert zero["value"] == 33.33  # 1/3 非首段

    iso2 = res["metrics"]["iso2_per_100_para"]
    assert iso2["hits"] == 2
    assert iso2["paragraph_indexes"] == [1, 2]
    assert iso2["value"] == 50.0  # 2/4 段
    assert iso2["human_baseline"] == 4.81 and iso2["ai_baseline"] == 9.41

    iso3 = res["metrics"]["iso3_per_100_para"]
    assert iso3["hits"] == 1 and iso3["value"] == 25.0
    assert iso3["human_baseline"] == 0.41 and iso3["ai_baseline"] == 0.84

    assert [(f["rule"], f["paragraph_index"]) for f in res["findings"]] == [
        ("lieflat-11", 1),
        ("lieflat-3", 1),
        ("lieflat-3", 2),
    ]
    assert all(f["severity"] == "advisory" for f in res["findings"])
    assert res["read_by_human_required"] is True


@requires_skill
def test_structure_advisories_mark_small_sample_without_verdict():
    """短稿段数不足时只报原始值，不给「正常/异常」结论（零主语指标同样受 20 段下限约束）。"""
    res = check_structure_advisories(SAMPLE)
    assert res["total_paragraphs"] < 20
    assert res["sample_ok"] is False
    assert all(
        m["band"] == "样本不足" for m in res["metrics"].values() if m["band"] != "对照项"
    )
    # L2 复核 I7 回归：零主语指标曾用独立的 10 非首段门槛，导致 11–19 段短稿照出硬结论
    zero = res["metrics"]["zero_anaphor_nonfirst_pct"]
    assert zero["band"] == "样本不足"
    assert zero["sample_ok"] is False
    assert "非首段" in zero["sample_note"]


@requires_skill
def test_structure_metaphor_is_control_not_target():
    """比喻起段人类更多 → 必须是「对照项」，不得变成待改项。"""
    res = check_structure_advisories("开头一段话足够长可以计入段落统计。\n\n就像那年的夏天，一切都慢了下来。")
    metaphor = res["metrics"]["metaphor_per_100_para"]
    assert metaphor["band"] == "对照项"
    assert metaphor["hits"] == 1
    assert "禁止据此删除或改写" in metaphor["note"]
    assert not any("metaphor" in f["rule"] for f in res["findings"])


@requires_skill
def test_translationese_splits_actionable_from_reference_only():
    res = check_translationese_advisories(SAMPLE)

    names = {a["name"] for a in res["actionable"]}
    assert names == {
        "过长前置定语",
        "当…时前置时间从句",
        "前置话题壳",
        "句首连接词当路标",
        "这意味着式复述",
    }
    # 5 种可改结构都带 skill 原文出处、AI 语料基线频次与覆盖率（数值须与 SKILL.md 一致，
    # 见 test_baselines_and_coverage_match_skill_citation_lines）
    rates = {a["name"]: a["ai_baseline_per_kchars"] for a in res["actionable"]}
    assert rates == {
        "过长前置定语": 0.42,
        "当…时前置时间从句": 0.26,
        "前置话题壳": 0.22,
        "句首连接词当路标": 0.18,
        "这意味着式复述": 0.15,
    }
    coverages = {a["name"]: a["coverage_in_ai_corpus"] for a in res["actionable"]}
    assert coverages == {
        "过长前置定语": "179/300",
        "当…时前置时间从句": "136/300",
        "前置话题壳": "137/300",
        "句首连接词当路标": "102/300",
        "这意味着式复述": "122/300",
    }
    for item in res["actionable"]:
        assert item["skill_ref"].startswith("SKILL.md:")
    # 「这意味着」必须标注需人读确认（正则判不了「后句与前句同义」）
    semantic = {a["name"]: a for a in res["actionable"]}
    assert semantic["这意味着式复述"]["requires_semantic_confirmation"] is True
    assert semantic["当…时前置时间从句"]["requires_semantic_confirmation"] is False

    # 「扮演…角色」属实测低于收录门槛 → 只进 reference-only 桶，且明示禁止据以改写
    ref_names = {r["name"] for r in res["reference_only"]}
    assert "扮演角色" in ref_names
    assert "扮演角色" not in names
    assert res["translationese_forbidden_as_rewrite_reason"] is True
    # 两桶必须互斥：可改结构不得同时出现在 reference-only（否则调用方会收到相反指令）
    assert not (names & ref_names)
    # 光比中文名不够：标记键重名不同也会造成「同一信号两桶结论相反」，必须按 skill 标记键比
    actionable_markers = {
        marker for spec in _TRANSLATIONESE_ACTIONABLE.values() for marker in spec["markers"]
    }
    assert not (actionable_markers & set(_TRANSLATIONESE_REFERENCE_ONLY))
    assert not any(r["name"] in actionable_markers for r in res["reference_only"])
    for item in res["reference_only"]:
        assert item["forbidden_scope"] == "仅『不得以翻译腔为理由改写』"
    # 另有正主的标记必须随条输出 other_rule，避免「桶名一刀切」把规则 8/11 的活也停了
    nuanced = check_translationese_advisories(
        "我们进行了流程的优化。\n\n值得注意的是，团队规模在扩大。\n\n他扮演了关键角色。"
    )
    ref_by_name = {r["name"]: r for r in nuanced["reference_only"]}
    assert "规则 8" in ref_by_name["轻动词"]["other_rule"]
    assert "规则 11" in ref_by_name["形式主语"]["other_rule"]
    assert "other_rule" not in ref_by_name["扮演角色"]
    # reference-only 的「禁止」只限于「以翻译腔为理由」；规则 8/11 另有正主
    assert "不得以『翻译腔』为理由改写" in res["reference_only_scope_note"]
    assert "规则 8" in res["reference_only_scope_note"]
    assert "规则 11" in res["reference_only_scope_note"]

    # 排除项：「的时候」类口语不算「当…时」翻译腔（SKILL.md:362）
    colloquial = check_translationese_advisories("当你回家的时候，记得关灯。")
    when_rule = [a for a in colloquial["actionable"] if a["name"] == "当…时前置时间从句"][0]
    assert when_rule["hits"] == 0


def test_run_checks_degrades_when_skill_missing(tmp_path: Path, monkeypatch):
    """skill 缺失时降级为 unavailable，不抛异常、不阻断流水线。"""
    monkeypatch.setenv("LIEFLAT_SKILL_DIR", str(tmp_path / "nope"))
    assert skill_dir() == tmp_path / "nope"

    res = run_lieflat_checks(SAMPLE)
    assert res["available"] is False
    assert "FileNotFoundError" in res["reason"]
    assert res["advisory_only"] is True
    assert "LIEFLAT_SKILL_DIR" in res["hint"]


def test_run_checks_reports_missing_marker_as_unavailable(tmp_path: Path, monkeypatch):
    """skill 脚本被改动导致标记映射失效 → 显式不可用，不静默漏检。"""
    scripts = tmp_path / "skill" / "scripts"
    scripts.mkdir(parents=True)
    # 结构脚本保持可用口径（最小实现），翻译腔脚本的 MARKERS 被清空
    (scripts / "check-structure.py").write_text(
        "import re\n"
        "COMMENT = re.compile(r'^再说')\n"
        "ANAPHOR = re.compile(r'^这')\n"
        "METAPHOR = re.compile(r'^像')\n"
        "def paragraphs(text):\n"
        "    return [p.strip() for p in text.split('\\n') if len(p.strip()) >= 8]\n"
        "def isomorphic(para, n):\n"
        "    return 0\n",
        encoding="utf-8",
    )
    (scripts / "check-translationese.py").write_text("MARKERS = {}\n", encoding="utf-8")
    monkeypatch.setenv("LIEFLAT_SKILL_DIR", str(tmp_path / "skill"))

    res = run_lieflat_checks(SAMPLE)
    assert res["available"] is False
    assert "skill_marker_missing" in res["reason"]


def test_run_checks_degrades_on_skill_interface_drift(tmp_path: Path, monkeypatch):
    """skill 脚本接口变了（缺函数）→ 同样降级，不把异常抛给文章流水线。"""
    scripts = tmp_path / "skill" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "check-structure.py").write_text("VERSION = 1\n", encoding="utf-8")
    (scripts / "check-translationese.py").write_text("MARKERS = {}\n", encoding="utf-8")
    monkeypatch.setenv("LIEFLAT_SKILL_DIR", str(tmp_path / "skill"))

    res = run_lieflat_checks(SAMPLE)
    assert res["available"] is False
    assert "AttributeError" in res["reason"]


@requires_skill
def test_advisories_do_not_change_gate_verdict():
    """核心不变量：advisory 不得改变 check_local_gates 的 passed。"""
    with_advisory = check_local_gates(SAMPLE)
    without = check_local_gates(SAMPLE, include_lieflat_checks=False)

    assert with_advisory["passed"] == without["passed"]
    assert with_advisory["anti_ai_score"] == without["anti_ai_score"]
    assert without["lieflat_advisories"] is None
    assert with_advisory["lieflat_advisories"]["available"] is True
    assert with_advisory["lieflat_advisories"]["advisory_only"] is True


@requires_skill
def test_humanize_pipeline_records_advisory_step(tmp_path: Path):
    md = tmp_path / "draft.md"
    md.write_text(SAMPLE, encoding="utf-8")

    res = run_humanize_pipeline(md)
    assert "lieflat_advisories" in res
    steps = [a["step"] for a in res["audit_trail"]]
    assert "lieflat_advisories" in steps
    step = [a for a in res["audit_trail"] if a["step"] == "lieflat_advisories"][0]
    assert step["advisory_only"] is True
    assert step["summary"]["structure_findings"] >= 1
    # 审计留痕可 JSON 序列化（不被非序列化对象破坏）
    json.dumps(res, ensure_ascii=False)


@requires_skill
def test_pipeline_still_passes_when_skill_missing(tmp_path: Path, monkeypatch):
    """skill 缺失时 advisory 降级，文章流水线判定不变（advisory 绝不阻断生产）。"""
    md_ok = tmp_path / "a.md"
    md_ok.write_text(SAMPLE, encoding="utf-8")
    baseline = run_humanize_pipeline(md_ok, output_path=tmp_path / "a.out.md")

    monkeypatch.setenv("LIEFLAT_SKILL_DIR", str(tmp_path / "missing-skill"))
    md_broken = tmp_path / "b.md"
    md_broken.write_text(SAMPLE, encoding="utf-8")
    degraded = run_humanize_pipeline(md_broken, output_path=tmp_path / "b.out.md")

    assert degraded["status"] == baseline["status"]
    assert degraded["local_gates_passed"] == baseline["local_gates_passed"]
    assert degraded["lieflat_advisories"]["available"] is False
    step = [a for a in degraded["audit_trail"] if a["step"] == "lieflat_advisories"][0]
    assert step["available"] is False and step["advisory_only"] is True
    # 正文产物不受 advisory 可用性影响
    assert (tmp_path / "a.out.md").read_bytes() == (tmp_path / "b.out.md").read_bytes()


# --- 补强断言：锁住数值口径、分类与降级路径（L2 复核对弱断言的复核意见）-------------------------

# 一稿打满 5 种可改结构（每项恰好 1 次命中）
ALL_FIVE_STRUCTURES = (
    "一个能够在很短时间里把整条审核链路速度提上来的工具已经在昨天正式上线了。\n\n"
    "当所有人都能用 AI 写文章时，内容本身就不再是竞争优势。\n\n"
    "对于早期团队来说，招人是最难的事。\n\n"
    "然而，成本也是一个需要考虑的因素。\n\n"
    "这意味着产品找到了 PMF，而且这个结论被反复复述。\n"
)

# 25 段同构段：连续两句/三句结构同款（AI 特征区）
ISOMORPHIC_PARA = (
    "这里还有第二句，逗号很多，结构一样，长度也接近，收尾也相同。"
    "第三句同样如此，逗号很多，结构一样，长度也接近，收尾也相同。"
    "第四句还是这样，逗号很多，结构一样，长度也接近，收尾也相同。"
)

# 25 段零主语评论起段
ZERO_ANAPHOR_PARA = "听起来像一条功能描述，其实底下换掉了一样更根本的东西。"


def _paras(text: str, n: int) -> str:
    return "\n\n".join([text] * n)


@requires_skill
def test_five_actionable_structures_hit_exactly():
    """5 种结构各自的正命中计数与样本必须锁死（检出全灭或样本置空都属回归）。"""
    res = check_translationese_advisories(ALL_FIVE_STRUCTURES)

    assert res["chinese_chars"] == 108
    counts = {a["name"]: a["hits"] for a in res["actionable"]}
    assert counts == {
        "过长前置定语": 1,
        "当…时前置时间从句": 1,
        "前置话题壳": 1,
        "句首连接词当路标": 1,
        "这意味着式复述": 1,
    }
    assert res["actionable_total_hits"] == 5
    for item in res["actionable"]:
        assert item["hits"] == 1
        assert item["per_kchars"] == 9.259  # 5 命中 / 108 字 = 1 / 0.108（每千字）
        assert len(item["snippets"]) == 1  # 样本不得为空（否则人读复核失去依据）


@requires_skill
def test_per_100_denominator_is_total_paragraphs():
    """结构指标的分母是「总段数」而不是「非首段数」（差 1 段就会算错百分比）。"""
    res = check_structure_advisories(_paras(ISOMORPHIC_PARA, 25))
    iso2 = res["metrics"]["iso2_per_100_para"]

    assert res["total_paragraphs"] == 25
    assert res["nonfirst_paragraphs"] == 24
    assert iso2["hits"] == 25
    assert iso2["value"] == 100.0  # 25/25；若误用非首段则会是 104.17
    assert round(25 / res["nonfirst_paragraphs"] * 100, 2) == 104.17


@requires_skill
def test_band_is_exact_when_sample_sufficient():
    """样本充足时必须给出可判定的区间标签，且方向正确（不得恒「正常」）。"""
    hot = check_structure_advisories(_paras(ISOMORPHIC_PARA, 25))
    assert hot["sample_ok"] is True
    for key in ("iso2_per_100_para", "iso3_per_100_para"):
        assert hot["metrics"][key]["value"] == 100.0
        assert hot["metrics"][key]["band"] == "AI特征区(≥AI基线)"
        assert hot["metrics"][key]["sample_ok"] is True
    assert hot["metrics"]["zero_anaphor_nonfirst_pct"]["band"] == "正常(≤人类基线)"

    normal = check_structure_advisories(
        _paras("第 X 段讲的是那天下午的事，人物动作各不相同，句法也没有重复。", 22)
    )
    assert normal["sample_ok"] is True
    assert normal["metrics"]["iso2_per_100_para"]["band"] == "正常(≤人类基线)"
    assert normal["metrics"]["iso2_per_100_para"]["value"] == 0.0
    assert normal["findings"] == []


@requires_skill
def test_zero_anaphor_band_respects_min_paragraphs():
    """零主语指标同样吃 20 段下限：11/19 段短稿只能报「样本不足」，25 段才出标签。"""
    for n in (11, 19):
        short = check_structure_advisories(_paras(ZERO_ANAPHOR_PARA, n))
        assert short["sample_ok"] is False
        zero = short["metrics"]["zero_anaphor_nonfirst_pct"]
        assert zero["band"] == "样本不足"
        assert zero["sample_ok"] is False
        # 短稿仍报原始值（此处 100.0），只是不给「正常/AI特征区」结论
        assert zero["value"] == 100.0

    long = check_structure_advisories(_paras(ZERO_ANAPHOR_PARA, 25))
    zero = long["metrics"]["zero_anaphor_nonfirst_pct"]
    assert zero["hits"] == 24 and zero["value"] == 100.0
    assert zero["band"] == "AI特征区(≥AI基线)"
    assert zero["sample_ok"] is True
    assert [f["rule"] for f in long["findings"]] == ["lieflat-11"] * 24


@requires_skill
def test_metaphor_stays_control_even_at_high_rate():
    """对照项语义：比喻起段再多也只是「对照项」，永远不会被判成待改的 AI 特征。"""
    res = check_structure_advisories(_paras("就像那年的夏天，一切都慢了下来。", 25))
    metaphor = res["metrics"]["metaphor_per_100_para"]
    assert res["sample_ok"] is True
    assert metaphor["hits"] == 25
    assert metaphor["band"] == "对照项"
    assert metaphor["note"].startswith("人类用得比 AI 多")
    assert not any(f["rule"] in {"lieflat-9", "lieflat-metaphor"} for f in res["findings"])


@requires_skill
def test_baselines_and_coverage_match_skill_citation_lines():
    """模块里的基线与覆盖率必须与 SKILL.md 被引用行逐字一致（防止口径漂移成两套数）。"""
    if not SKILL_MD.is_file():
        pytest.skip("SKILL.md 不存在")

    metrics = check_structure_advisories(SAMPLE)["metrics"]
    expected_structure = {
        "iso2_per_100_para": (165, 4.81, 9.41),
        "iso3_per_100_para": (165, 0.41, 0.84),
        "zero_anaphor_nonfirst_pct": (431, 0.14, 0.61),
        "metaphor_per_100_para": (449, 0.21, 0.03),
    }
    for key, (line_no, human, ai) in expected_structure.items():
        line = _skill_line(line_no)
        assert f"{human}" in line, (key, line_no, line)
        assert f"{ai}" in line, (key, line_no, line)
        assert metrics[key]["human_baseline"] == human
        assert metrics[key]["ai_baseline"] == ai

    expected_translationese = {
        "过长前置定语": (336, 0.42, "179/300"),
        "当…时前置时间从句": (354, 0.26, "136/300"),
        "前置话题壳": (372, 0.22, "137/300"),
        "句首连接词当路标": (394, 0.18, "102/300"),
        "这意味着式复述": (412, 0.15, "122/300"),
    }
    items = {a["name"]: a for a in check_translationese_advisories(SAMPLE)["actionable"]}
    assert set(items) == set(expected_translationese)
    for name, (line_no, rate, coverage) in expected_translationese.items():
        line = _skill_line(line_no)
        assert f"{rate}" in line, (name, line_no, line)
        assert coverage in line, (name, line_no, line)
        assert items[name]["ai_baseline_per_kchars"] == rate
        assert items[name]["coverage_in_ai_corpus"] == coverage


@pytest.mark.parametrize(
    "broken_script",
    [
        "MARKERS = {\n",  # 语法错误：SyntaxError
        "x = 1 / 0\nMARKERS = {}\n",  # 运行期异常：ZeroDivisionError
    ],
)
def test_run_checks_survives_broken_skill_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, broken_script: str
):
    """回归（L2 复核 major）：外部 skill 脚本崩了也只能降级，不得打崩文章流水线。"""
    scripts = tmp_path / "skill" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "check-structure.py").write_text(
        "import re\n"
        "COMMENT = re.compile(r'^再说')\n"
        "ANAPHOR = re.compile(r'^这')\n"
        "METAPHOR = re.compile(r'^像')\n"
        "def paragraphs(text):\n"
        "    return [p.strip() for p in text.split('\\n') if len(p.strip()) >= 8]\n"
        "def isomorphic(para, n):\n"
        "    return 0\n",
        encoding="utf-8",
    )
    (scripts / "check-translationese.py").write_text(broken_script, encoding="utf-8")
    monkeypatch.setenv("LIEFLAT_SKILL_DIR", str(tmp_path / "skill"))

    res = run_lieflat_checks(SAMPLE)
    assert res["available"] is False
    assert res["advisory_only"] is True
    assert res["reason"].startswith(("SyntaxError", "ZeroDivisionError")), res["reason"]

    md = tmp_path / "draft.md"
    md.write_text(SAMPLE, encoding="utf-8")
    pipeline = run_humanize_pipeline(md, output_path=tmp_path / "out.md")
    assert pipeline["status"] in {"PASS", "FAIL"}  # 重点是没抛异常
    assert pipeline["lieflat_advisories"]["available"] is False


# 固定输入 + 黄金哈希：任何往产物里塞东西的改动（包括与 advisory 无关的无条件改动）都会红。
GOLDEN_INPUT = """# 标题

这是第一段，讲了一个很长的故事，主角在雨里跑，跑到了桥上，又跑了回来。

当所有人都能用 AI 写文章时，内容本身就不再是竞争优势。对于早期团队来说，招人是最难的事。然而，成本也是一个需要考虑的因素。

这意味着产品找到了 PMF。这是一个能够让团队在不增加人力的情况下显著提升审核速度的工具。他扮演了关键角色。
"""
GOLDEN_OUTPUT_SHA16 = "909f871027656120"


@requires_skill
def test_output_is_exactly_deterministic_polish_and_has_no_advisory_artifacts(tmp_path: Path):
    """绝对产物不变式（不是两次运行互比）：产物只能等于确定性润色结果本身。

    L2 第二轮复核的 P02 变异（在 run_humanize_pipeline 里无条件往正文追加一行注释）能逃过
    原有用例——原有用例比的是「advisory 可用 vs 不可用」两次运行，无条件改动两边同时变。
    这里改为对固定输入的**绝对**断言 + 黄金哈希，任何产物改动都会立刻失败。
    """
    md = tmp_path / "draft.md"
    md.write_text(GOLDEN_INPUT, encoding="utf-8")
    out = tmp_path / "out.md"
    res = run_humanize_pipeline(md, output_path=out)

    text = out.read_text(encoding="utf-8")
    polished, _ = deterministic_polish(GOLDEN_INPUT)
    assert text == polished  # 产物里不许出现确定性润色以外的任何字节
    assert "lieflat" not in text.lower()
    assert "<!--" not in text
    assert hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] == GOLDEN_OUTPUT_SHA16
    assert res["lieflat_advisories"]["available"] is True  # advisory 是开着的，只是不落产物
