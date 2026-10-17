"""lieflat_checks: 把 lieflat 去 AI 味 skill 的三处测量脚本接成流水线可用的 advisory 检查。

为什么需要这个模块（2026-10-15 对照证据，见
`runs/2026-10-15/baimiao-vs-lieflat-rule-matrix/BAIMIAO-VS-LIEFLAT-MATRIX.md` §5）：
lieflat 的 11 条规则里，真正进流水线的只有第 1/4/6 条（+第 8 条部分），第 3、10、11 条
虽然 skill 自带现成脚本（`scripts/check-structure.py`、`scripts/check-translationese.py`），
却从未被任何代码引用。本模块把这两支脚本接成「可跑、可定位、可审计」的检查。

三条不可协商的设计约束：

1. **复用 skill 自带口径，不复制规则。** 通过 importlib 直接加载 skill 目录下的脚本，
   使用它自己的正则与测量函数。复制过来会漂移，也会违反
   `ruoyu-article-production/SKILL.md:44-51` 禁止造第三份规则副本的要求。
2. **advisory only，不参与门禁判定。** lieflat 自己写明这三条的最终裁决要人读
   （`SKILL.md:185` 案例是否在凑数、`:426` 翻译腔只处理五种、`:449` 比喻贴不贴切），
   因此本模块结论只进报告与人工复核清单，**不改 `check_local_gates` 的 passed**。
3. **翻译腔分桶。** `SKILL.md:330` 明确「以一种……的方式」0.01/千字、「扮演……角色」0.02、
   「使得……能够」0.03、抽象被动 0.09 等**低于收录门槛，不作为改写理由**；
   被动句、名词化、长句本身是正常中文写作。把它们当命中项会直接违反该 skill，
   所以只报 5 种可改结构，其余标记单独归入 reference-only 桶并标注「禁止据以改写」。
"""

from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path
from typing import Any

# skill 目录：默认机器上的安装位置，可用环境变量覆盖（便于测试与迁移）
DEFAULT_SKILL_DIR = "/home/allen/.agents/skills/lieflat-less-ai-tone"

# 公布基线（人类 vs AI），来源 lieflat/SKILL.md；结构类指标分母是「段」不是「字」
_STRUCT_BASELINE: dict[str, tuple[float, float]] = {
    # 指标: (人类, AI)
    "iso2_per_100_para": (4.81, 9.41),  # SKILL.md:165 连续两句同构
    "iso3_per_100_para": (0.41, 0.84),  # SKILL.md:165 连续三句同构
    "zero_anaphor_nonfirst_pct": (0.14, 0.61),  # SKILL.md:431 段首零主语评论/非首段
}
# 对照项（人类反而更多）：只能报告，禁止据此改写 —— SKILL.md:449
_STRUCT_CONTROL: dict[str, tuple[float, float]] = {
    "metaphor_per_100_para": (0.21, 0.03),
}

# 样本量下限：低于此段数不下「正常/异常」判断，只报原始值（避免短稿噪声当结论）
_MIN_PARAS_FOR_BAND = 20
_MIN_NONFIRST_FOR_BAND = 10

# 翻译腔：skill 收录的 5 种可改结构（SKILL.md:336-416）+ 公布频率（每千汉字，AI 语料）
_TRANSLATIONESE_ACTIONABLE: dict[str, dict[str, Any]] = {
    "过长前置定语": {
        "markers": ("长前置定语", "的…的…的连用"),
        "ai_per_kchars": 0.42,
        "coverage": "179/300",
        "ref": "SKILL.md:336-344",
        "requires_semantic_confirmation": False,
    },
    "当…时前置时间从句": {
        "markers": ("当…的时候",),
        "ai_per_kchars": 0.26,
        "coverage": "136/300",
        "ref": "SKILL.md:354-362",
        "requires_semantic_confirmation": False,
        # SKILL.md:362「的时候」类口语说法不是 AI 特征 → 检测器需排除
        "exclude": r"的时候",
    },
    "前置话题壳": {
        "markers": ("前置话题壳",),
        "ai_per_kchars": 0.22,
        "coverage": "137/300",
        "ref": "SKILL.md:372-380",
        "requires_semantic_confirmation": False,
    },
    "句首连接词当路标": {
        "markers": ("句首连接词",),
        "ai_per_kchars": 0.18,
        "coverage": "102/300",
        "ref": "SKILL.md:394-402",
        "requires_semantic_confirmation": False,
    },
    "这意味着式复述": {
        "markers": ("这意味着",),
        "ai_per_kchars": 0.15,
        "coverage": "122/300",
        "ref": "SKILL.md:412-419",
        # 触发还需「后句与前句同义」——正则判断不了，必须人读
        "requires_semantic_confirmation": True,
    },
}

# 其余标记：实测低于收录门槛或本身是正常中文写作，禁止作为改写理由（SKILL.md:330、:332、:474）
#
# 「禁止」的口径要说准：是**不得以「翻译腔」为理由**改写（SKILL.md:332「触发标记之外的表达
# 必须原样保留」）。其中两个标记另有正主，命中时走对应规则而不是这里：
#   - 「轻动词」（进行/作出…）：属规则 8 名词化还原，已由 humanize_pipeline.py:210-217 处理；
#   - 「形式主语」（值得注意的是…）：若出现在非首段段首，属规则 11 段首零主语，由本模块的
#     structure 检查（lieflat-11）单独报出，补回指词即可。
_TRANSLATIONESE_REFERENCE_ONLY = (
    "被动-抽象",
    "受到…的",
    "形式主语",
    "存在着/有着",
    "在…的过程中",
    "如果…的话",
    "并列连词密集",
    "轻动词",
    "不仅仅是",
    "正是/恰恰是",
    "复数硬译",
    "程度直译",
    "扮演角色",
    "以一种…方式",
    "使得…能够",
)

# 上表里「另有正主」的标记：命中时按正主规则处理，这里的「禁止改写」只针对翻译腔那一侧。
# 逐条随报告输出，避免调用方只看桶名就停手（L2 复核 findings #2，2026-10-15）。
_TRANSLATIONESE_OTHER_RULE = {
    "轻动词": "规则 8（lieflat-8 名词化/轻动词还原）：结构本身在改写范围内，正确改法是恢复实义动词（SKILL.md:314）",
    "形式主语": "规则 11（lieflat-11 段首零主语）：出现在非首段段首时补回指词即可（SKILL.md:431）",
    "不仅仅是": "规则 1（lieflat-1 模板复现）：与「不仅……更……」模板同族，先看规则 1 是否命中（SKILL.md:29）",
}


def skill_dir() -> Path:
    return Path(os.environ.get("LIEFLAT_SKILL_DIR", DEFAULT_SKILL_DIR))


def _load_skill_module(filename: str, module_name: str) -> Any:
    """按文件路径加载 skill 脚本（文件名带连字符，不能用普通 import）。"""
    path = skill_dir() / "scripts" / filename
    if not path.is_file():
        raise FileNotFoundError(f"skill_script_not_found: {path}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - 环境损坏
        raise ImportError(f"skill_script_unloadable: {path}")
    module = importlib.util.module_from_spec(spec)
    # 不写 sys.modules：同一进程内允许夹具替换 skill 目录后重新加载
    spec.loader.exec_module(module)
    return module


def _band(value: float, human: float, ai: float, sample_ok: bool) -> str:
    """按公布的人类/AI 基线给区间标签。

    只用于「AI 偏高」类指标（human < ai）。人类本就更多、禁止据此改写的对照项
    （比喻起段）不走这里，直接在 metrics 里硬编码 `对照项`。
    """
    if not sample_ok:
        return "样本不足"
    if value <= human:
        return "正常(≤人类基线)"
    if value < ai:
        return "注意(人类与AI之间)"
    return "AI特征区(≥AI基线)"


def _snippet(para: str, limit: int = 40) -> str:
    para = para.strip()
    return para if len(para) <= limit else para[:limit] + "…"


def check_structure_advisories(text: str) -> dict[str, Any]:
    """规则 3（相邻句结构同款）与规则 11（段首零主语评论）的可定位报告。"""
    mod = _load_skill_module("check-structure.py", "lieflat_check_structure")

    paragraphs: list[str] = mod.paragraphs(text)
    total = len(paragraphs)
    iso2_hits: list[int] = []
    iso3_hits: list[int] = []
    zero_hits: list[int] = []
    metaphor_hits: list[int] = []
    nonfirst = 0

    for i, para in enumerate(paragraphs):
        if mod.isomorphic(para, 2):
            iso2_hits.append(i)
        if mod.isomorphic(para, 3):
            iso3_hits.append(i)
        if mod.METAPHOR.match(para):
            metaphor_hits.append(i)
        if i == 0:
            continue
        nonfirst += 1
        if mod.COMMENT.match(para) and not mod.ANAPHOR.match(para):
            zero_hits.append(i)

    def per_100(hits: list[int]) -> float:
        return (len(hits) / total * 100) if total else 0.0

    zero_pct = (len(zero_hits) / nonfirst * 100) if nonfirst else 0.0
    band_ok = total >= _MIN_PARAS_FOR_BAND
    # 零主语指标的分母是非首段：必须**同时**满足段数下限与非首段下限才给区间标签，
    # 否则会出现「顶层 sample_ok=False、却对零主语直接下『AI特征区』硬结论」的自相矛盾
    # （L2 复核 I7，2026-10-15）。
    zero_band_ok = band_ok and nonfirst >= _MIN_NONFIRST_FOR_BAND

    metrics: dict[str, Any] = {}
    for key, hits in (
        ("iso2_per_100_para", iso2_hits),
        ("iso3_per_100_para", iso3_hits),
    ):
        human, ai = _STRUCT_BASELINE[key]
        value = per_100(hits)
        metrics[key] = {
            "value": round(value, 2),
            "human_baseline": human,
            "ai_baseline": ai,
            "band": _band(value, human, ai, band_ok),
            "sample_ok": band_ok,
            "hits": len(hits),
            "paragraph_indexes": hits,
        }

    human, ai = _STRUCT_BASELINE["zero_anaphor_nonfirst_pct"]
    metrics["zero_anaphor_nonfirst_pct"] = {
        "value": round(zero_pct, 2),
        "human_baseline": human,
        "ai_baseline": ai,
        "band": _band(zero_pct, human, ai, zero_band_ok),
        "sample_ok": zero_band_ok,
        "sample_note": f"分母为非首段 {nonfirst} 段（下限 {_MIN_NONFIRST_FOR_BAND}）且全篇不少于 {_MIN_PARAS_FOR_BAND} 段",
        "hits": len(zero_hits),
        "paragraph_indexes": zero_hits,
    }

    human, ai = _STRUCT_CONTROL["metaphor_per_100_para"]
    value = per_100(metaphor_hits)
    metrics["metaphor_per_100_para"] = {
        "value": round(value, 2),
        "human_baseline": human,
        "ai_baseline": ai,
        "band": "对照项",
        "sample_ok": band_ok,
        "hits": len(metaphor_hits),
        "paragraph_indexes": metaphor_hits,
        "note": "人类用得比 AI 多，禁止据此删除或改写（SKILL.md:449）",
    }

    findings: list[dict[str, Any]] = []
    for idx in zero_hits:
        findings.append({
            "rule": "lieflat-11",
            "rule_name": "段首零主语评论",
            "severity": "advisory",
            "paragraph_index": idx,
            "snippet": _snippet(paragraphs[idx]),
            "suggested_fix": "补回指词或点明评论对象（多数加一个「这」字），不改段落顺序",
        })
    for idx in iso2_hits:
        findings.append({
            "rule": "lieflat-3",
            "rule_name": "相邻句结构同款",
            "severity": "advisory",
            "paragraph_index": idx,
            "snippet": _snippet(paragraphs[idx]),
            "suggested_fix": "打散其中一句句法（合并/拆分/换语序），只改句内，不动段落顺序",
        })

    return {
        "total_paragraphs": total,
        "nonfirst_paragraphs": nonfirst,
        "sample_ok": band_ok,
        "metrics": metrics,
        "findings": findings,
        "read_by_human_required": True,
    }


def check_translationese_advisories(text: str) -> dict[str, Any]:
    """规则 10（翻译腔只保留五种）：可改结构与「禁止据以改写」标记分桶报告。"""
    mod = _load_skill_module("check-translationese.py", "lieflat_check_translationese")

    chinese_chars = len(re.findall(r"[一-鿿]", text))
    kchars = chinese_chars / 1000

    actionable: list[dict[str, Any]] = []
    for name, spec in _TRANSLATIONESE_ACTIONABLE.items():
        patterns: list[str] = []
        for marker in spec["markers"]:
            raw = mod.MARKERS.get(marker)
            if raw is None:  # skill 脚本改动导致映射失效 → 显式报错，不静默漏检
                raise KeyError(f"skill_marker_missing: {marker}")
            patterns.append(raw)
        rx = re.compile("|".join(f"(?:{p})" for p in patterns))
        samples = [m.group(0) for m in rx.finditer(text)]
        if spec.get("exclude"):
            samples = [s for s in samples if not re.search(spec["exclude"], s)]
        actionable.append({
            "name": name,
            "skill_ref": spec["ref"],
            "ai_baseline_per_kchars": spec["ai_per_kchars"],
            "coverage_in_ai_corpus": spec["coverage"],
            "hits": len(samples),
            "per_kchars": round(len(samples) / kchars, 3) if kchars else 0.0,
            "snippets": samples[:8],
            "requires_semantic_confirmation": spec["requires_semantic_confirmation"],
        })

    reference_only: list[dict[str, Any]] = []
    for name in _TRANSLATIONESE_REFERENCE_ONLY:
        raw = mod.MARKERS.get(name)
        if raw is None:
            raise KeyError(f"skill_marker_missing: {name}")
        rx = re.compile(raw)
        hits = len(rx.findall(text))
        if hits:
            item = {
                "name": name,
                "hits": hits,
                "per_kchars": round(hits / kchars, 3) if kchars else 0.0,
                "forbidden_scope": "仅『不得以翻译腔为理由改写』",
            }
            if name in _TRANSLATIONESE_OTHER_RULE:
                item["other_rule"] = _TRANSLATIONESE_OTHER_RULE[name]
            reference_only.append(item)

    return {
        "chinese_chars": chinese_chars,
        "actionable": actionable,
        "actionable_total_hits": sum(a["hits"] for a in actionable),
        "reference_only": reference_only,
        # 键名刻意带上 translationese_ 前缀：这个 True 只覆盖翻译腔那一侧，
        # 不代表命中项在别的规则下也不用改（见 _TRANSLATIONESE_OTHER_RULE）。
        "translationese_forbidden_as_rewrite_reason": True,
        "reference_only_scope_note": (
            "reference-only 桶的含义是「不得以『翻译腔』为理由改写」；若同时命中规则 8"
            "（名词化/轻动词还原，见 humanize_pipeline.py:210-217）或规则 11（段首零主语，"
            "见本模块 structure 检查 lieflat-11），按对应规则处理，并读该条的 other_rule 字段。"
        ),
        "read_by_human_required": True,
    }


def run_lieflat_checks(text: str) -> dict[str, Any]:
    """跑全部接入项。skill 缺失或脚本不可加载时降级为 unavailable，不阻断流水线。"""
    result: dict[str, Any] = {
        "available": False,
        "skill_dir": str(skill_dir()),
        "checks": ["lieflat-3", "lieflat-10", "lieflat-11"],
        "advisory_only": True,
    }
    try:
        structure = check_structure_advisories(text)
        translationese = check_translationese_advisories(text)
    except Exception as exc:  # noqa: BLE001 - advisory 路径必须吞掉一切异常
        # 这里刻意用宽 except：加载的是**外部 skill 脚本**，除了接口变化（KeyError/AttributeError）、
        # 文件缺失（FileNotFoundError/ImportError），还可能抛语法错误（SyntaxError）、除零等任意
        # 运行期异常。职责上本模块只是「不影响门禁」的 advisory，绝不能反把文章流水线打崩
        # （L2 复核 findings #1，2026-10-15：窄 except 曾让 SyntaxError/ZeroDivisionError 穿透
        # run_lieflat_checks → check_local_gates → run_humanize_pipeline）。
        result["reason"] = f"{type(exc).__name__}: {exc}"
        result["hint"] = "设置 LIEFLAT_SKILL_DIR 指向 lieflat-less-ai-tone skill 目录"
        return result

    result["available"] = True
    result["structure"] = structure
    result["translationese"] = translationese
    result["summary"] = {
        "structure_findings": len(structure["findings"]),
        "structure_band": {
            k: v["band"] for k, v in structure["metrics"].items()
        },
        "translationese_actionable_hits": translationese["actionable_total_hits"],
        "translationese_reference_only_hits": sum(
            m["hits"] for m in translationese["reference_only"]
        ),
    }
    return result


__all__ = [
    "check_structure_advisories",
    "check_translationese_advisories",
    "run_lieflat_checks",
    "skill_dir",
]
