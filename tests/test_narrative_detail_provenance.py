"""叙述性细节溯源网 + L2 哈希绑定（2026-10-16，case-009《李雪健》复盘回归测试）。

背景（两处"自述式放行"，同一类病根）：

1. **编造逃过全部门禁**。被封存的那版 case-009 稿件（sha256 ``191a079e…``）含
   ≥11 处叙述性细节编造——「你说你拿4000块…」的前半句、「对方嘴唇动到第几个
   节拍」、「肋骨与大腿…半身淤青」、「青石板」、「几十米外」、「面红耳赤」、
   「收废品」「养女」、「几十亿投资」、「小布包」等，在 15 个信源里逐字零命中。
   而那一版**全量确定性门禁 PASS、独立 L2 复核 approve / 0 findings**。
   根因：既有门禁只覆盖「时间跨度 / 受众行为 / 带量词数字 / 直接引语」四类。

2. **L2 不绑稿件哈希**。``build_gate_registry_report`` 的 L2 分支只读 ``decision``，
   不比对被复核稿件的 sha256，于是 ``draft.md`` 被整篇换掉后 L2 仍报 pass。

本文件为这两处补丁钉回归。第 2 轮的 8 条 fabricated 由独立复核在
``93a0f42b…`` 上实测得出，其词面已固化进 ``NARRATIVE_DETAIL_PROBES``。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from article_group.pilot_extensions import (
    NARRATIVE_DETAIL_PROBES,
    check_narrative_detail_provenance,
    load_run_source_corpus,
)
from article_group.run_gates import build_narrative_detail_gate

# 第 2 轮独立 L2 在 93a0f42b… 上实测命中的 fabricated 词面（含复核报告未单列、
# 但同属该失败类别的「粗砂纸」「青筋」「钝刀」「摄像机」「灯光」「水汽」）。
CASE009_FABRICATED_TERMS = (
    "石板", "泥水", "泥地", "地牢", "污泥", "龙德殿",
    "禁卫军", "王座", "地砖", "钝刀", "大功率", "老花镜", "手机屏幕",
    "摄像机", "灯光", "外交官", "粗砂纸", "青筋", "水汽",
)


# ---------------------------------------------------------------------------
# 1. 叙述性细节溯源网
# ---------------------------------------------------------------------------


def test_probe_flags_details_absent_from_corpus():
    draft = "铁镣铐砸在石板上，溅起一星泥水。"
    corpus = "赤脚戴镣铐游街，躺在地上赶野狗。"
    result = check_narrative_detail_provenance(draft, corpus)
    assert result["passed"] is False
    assert {item["term"] for item in result["unsourced"]} == {"石板", "泥水"}


def test_probe_passes_when_corpus_contains_the_detail():
    draft = "他赤脚戴镣铐游街，拍完半身淤青。"
    corpus = "赤脚戴镣铐游街、躺在地上赶野狗，反复实摔导致半身淤青。"
    result = check_narrative_detail_provenance(draft, corpus)
    assert result["passed"] is True
    assert result["unsourced"] == []


def test_probe_returns_context_window_for_each_hit():
    draft = "前文很长的一段铺垫。铁镣铐砸在石板上，溅起一星泥水。后面还有话。"
    result = check_narrative_detail_provenance(draft, "毫不相关的语料")
    hit = next(item for item in result["unsourced"] if item["term"] == "石板")
    assert "石板" in hit["context"]
    assert "泥水" in hit["context"]


def test_probe_ignores_terms_absent_from_the_draft():
    result = check_narrative_detail_provenance("他赤脚戴镣铐游街。", "赤脚戴镣铐游街")
    assert result["passed"] is True
    assert result["checked_probes"] == len(NARRATIVE_DETAIL_PROBES)


def test_probe_accepts_custom_probe_list():
    result = check_narrative_detail_provenance("张三去了火星", "语料", probes=("火星", "月球"))
    assert [item["term"] for item in result["unsourced"]] == ["火星"]


def test_probe_result_is_json_serialisable():
    result = check_narrative_detail_provenance("石板路", "无")
    assert json.loads(json.dumps(result, ensure_ascii=False))["passed"] is False


@pytest.mark.parametrize("term", CASE009_FABRICATED_TERMS)
def test_case009_regression_terms_stay_pinned_in_lexicon(term):
    """这些词是实测出来的失败面；被删掉就等于把回归网拆了。"""
    assert term in NARRATIVE_DETAIL_PROBES


# ---------------------------------------------------------------------------
# 2. 语料装载
# ---------------------------------------------------------------------------


def test_load_run_source_corpus_joins_manifest_artifacts(tmp_path):
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources" / "a.md").write_text("赤脚戴镣铐游街", encoding="utf-8")
    (tmp_path / "sources" / "b.md").write_text("反复实摔导致半身淤青", encoding="utf-8")
    (tmp_path / "source-manifest.json").write_text(
        json.dumps(
            {
                "sources": [
                    {"artifact_path": "sources/a.md"},
                    {"artifact_path": "sources/b.md"},
                ]
            }
        ),
        encoding="utf-8",
    )
    corpus = load_run_source_corpus(tmp_path)
    assert "镣铐" in corpus
    assert "淤青" in corpus


def test_load_run_source_corpus_tolerates_missing_manifest(tmp_path):
    assert load_run_source_corpus(tmp_path) == ""


def test_load_run_source_corpus_skips_dead_artifact_paths(tmp_path):
    (tmp_path / "source-manifest.json").write_text(
        json.dumps({"sources": [{"artifact_path": "sources/gone.md"}]}), encoding="utf-8"
    )
    assert load_run_source_corpus(tmp_path) == ""


# ---------------------------------------------------------------------------
# 3. 门禁外壳：永远是 advisory，但必须显式留痕
# ---------------------------------------------------------------------------


def _run_with_corpus(tmp_path: Path, draft: str, corpus: str) -> Path:
    (tmp_path / "draft.md").write_text(draft, encoding="utf-8")
    (tmp_path / "sources").mkdir(exist_ok=True)
    (tmp_path / "sources" / "a.md").write_text(corpus, encoding="utf-8")
    (tmp_path / "source-manifest.json").write_text(
        json.dumps({"sources": [{"artifact_path": "sources/a.md"}]}), encoding="utf-8"
    )
    return tmp_path


def test_gate_is_advisory_even_with_hits(tmp_path):
    root = _run_with_corpus(tmp_path, "铁镣铐砸在石板上。", "赤脚戴镣铐游街")
    gate = build_narrative_detail_gate(root)
    assert gate["blocking"] is False, "advisory 门禁绝不许阻断 run"
    assert gate["status"] == "advisory"
    assert gate["pass"] is False
    assert "unsourced_narrative_detail:石板" in gate["warnings"]
    assert gate["unsourced"][0]["term"] == "石板"


def test_gate_passes_on_clean_draft(tmp_path):
    root = _run_with_corpus(tmp_path, "赤脚戴镣铐游街。", "赤脚戴镣铐游街")
    gate = build_narrative_detail_gate(root)
    assert gate["pass"] is True
    assert gate["status"] == "pass"
    assert gate["warnings"] == []


def test_gate_not_run_without_draft(tmp_path):
    gate = build_narrative_detail_gate(tmp_path)
    assert gate["status"] == "not_run"
    assert gate["blocking"] is False
    assert gate["reason"] == "draft_md_missing"


def test_gate_not_run_when_corpus_empty(tmp_path):
    (tmp_path / "draft.md").write_text("正文", encoding="utf-8")
    gate = build_narrative_detail_gate(tmp_path)
    assert gate["status"] == "not_run", "没语料就必须报 not_run，不许伪装成检查过"
    assert gate["reason"] == "source_corpus_empty"
    assert gate["blocking"] is False


# ---------------------------------------------------------------------------
# 4. L2 哈希绑定（补掉"换了稿子还说 pass"）
# ---------------------------------------------------------------------------


def _write_l2(root: Path, payload: dict) -> None:
    (root / "review").mkdir(exist_ok=True)
    (root / "review" / "l2-adversarial-review.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _l2_gate(root: Path) -> dict:
    from article_group.pilot_adapters import build_gate_registry_report

    return build_gate_registry_report(root)["gates"]["l2_adversarial_review"]


def test_l2_gate_passes_when_bound_to_current_draft(tmp_path):
    draft = "当前稿件正文"
    (tmp_path / "draft.md").write_text(draft, encoding="utf-8")
    sha = hashlib.sha256(draft.encode("utf-8")).hexdigest()
    _write_l2(tmp_path, {"decision": "approve", "reviewed_draft_sha256": sha, "findings": []})
    entry = _l2_gate(tmp_path)
    assert entry["status"] == "pass"
    assert entry["reviewed_draft_sha256"] == sha
    assert entry["current_draft_sha256"] == sha


def test_l2_gate_fails_when_review_hash_is_stale(tmp_path):
    """draft.md 被换掉之后，旧 L2 的 approve 不许继续放行。"""
    (tmp_path / "draft.md").write_text("换过的新正文", encoding="utf-8")
    _write_l2(tmp_path, {"decision": "approve", "reviewed_draft_sha256": "0" * 64, "findings": []})
    entry = _l2_gate(tmp_path)
    assert entry["status"] == "fail"
    assert entry["error"] == "l2_review_stale:draft_changed_after_review"
    assert entry["reviewed_draft_sha256"] == "0" * 64
    assert entry["current_draft_sha256"] != "0" * 64


def test_l2_gate_accepts_target_sha256_alias(tmp_path):
    draft = "当前稿件正文"
    (tmp_path / "draft.md").write_text(draft, encoding="utf-8")
    sha = hashlib.sha256(draft.encode("utf-8")).hexdigest()
    _write_l2(tmp_path, {"decision": "approve", "target_sha256": sha, "findings": []})
    assert _l2_gate(tmp_path)["status"] == "pass"


def test_l2_gate_refuses_unbound_review(tmp_path):
    """没有哈希就没法证明这次复核针对的是当前稿 —— 不可验证，不许 pass。"""
    (tmp_path / "draft.md").write_text("当前稿件正文", encoding="utf-8")
    _write_l2(tmp_path, {"decision": "approve", "findings": []})
    entry = _l2_gate(tmp_path)
    assert entry["status"] == "fail"
    assert entry["error"] == "l2_review_unbound:missing_draft_sha256"


def test_l2_gate_still_reports_needs_changes(tmp_path):
    """stale 检查不许把「复核真的没通过」这件事盖掉。"""
    draft = "当前稿件正文"
    (tmp_path / "draft.md").write_text(draft, encoding="utf-8")
    sha = hashlib.sha256(draft.encode("utf-8")).hexdigest()
    _write_l2(
        tmp_path,
        {
            "decision": "needs_changes",
            "reviewed_draft_sha256": sha,
            "findings": [{"severity": "blocker", "type": "fabricated"}],
        },
    )
    entry = _l2_gate(tmp_path)
    assert entry["status"] == "needs_changes"
    assert entry["findings_count"] == 1
