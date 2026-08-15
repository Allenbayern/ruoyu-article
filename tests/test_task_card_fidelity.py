"""Tests for article_group.task_card_fidelity - task-card promise fulfillment.

Motivation (controlled-018): title drift and a self-reminder H2 survived into
final drafts because nothing cross-checked the article against its own task
card. This checker extracts the card's promises (title_promise / standing
point / H2 outline / ending destination) and anchors them in the draft.

Contract:
- h2_outline must be fully delivered (missing H2 = drift).
- standing_point must have at least one hit (core stance preserved).
- title_promise / ending_destination may be partial (editorial polish of the
  title/wording is allowed; wholesale topic loss is not) but never missing
  when the field exists.
- exit code 1 when any check is missing or a promise field cannot be parsed.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from article_group import task_card_fidelity as tcf

C018 = Path("/home/allen/Projects/ruoyu-film-daily/runs/2026-08-12/controlled-018")


def _mk_card(tmp_path: Path, h2s: list[str], stance: str = "主角是张三", promise: str = "讲述张三的成长") -> Path:
    card = tmp_path / "card.md"
    h2_block = "## 文章结构大纲（H2 目录）\n\n" + "\n\n".join(f"## {h}" for h in h2s) + "\n"
    card.write_text(
        "1. **站队点/可转述句**：" + stance + "\n\n"
        "- **title_promise**：" + promise + "\n\n"
        "- **ending_destination**：读者记得主角张三\n\n"
        + h2_block,
        encoding="utf-8",
    )
    return card


def _mk_draft(tmp_path: Path, h1: str, h2s: list[str], body: str = "张三在故事里做出了自己的选择。") -> Path:
    draft = tmp_path / "draft.md"
    text = f"# {h1}\n\n" + "\n\n".join(f"## {h}\n\n{body}" for h in h2s) + "\n"
    draft.write_text(text, encoding="utf-8")
    return draft


# ---- field parsing ---------------------------------------------------------

def test_parses_all_promise_fields_from_real_card():
    card = C018 / "task-cards" / "task-card-art-003.md"
    draft = C018 / "drafts" / "art-003.md"
    v = tcf.check_fidelity(card, draft)
    fields = {c["field"] for c in v["checks"]}
    assert fields == {"title_promise", "standing_point", "h2_outline", "ending_destination"}
    by_field = {c["field"]: c for c in v["checks"]}
    assert by_field["title_promise"]["status"] != "missing-field"
    assert by_field["ending_destination"]["status"] != "missing-field"
    assert by_field["h2_outline"]["promised_count"] >= 5


# ---- controlled-018 regression (fulfilled batch must pass) ----------------

@pytest.mark.parametrize("aid", ["art-001", "art-002", "art-003"])
def test_c018_fulfilled_batch_passes(tmp_path, aid):
    card = C018 / "task-cards" / f"task-card-{aid}.md"
    draft = C018 / "drafts" / f"{aid}.md"
    assert card.exists(), card
    assert draft.exists(), draft
    v = tcf.check_fidelity(card, draft)
    by_field = {c["field"]: c for c in v["checks"]}
    # H2 骨架必须全部兑现
    assert by_field["h2_outline"]["status"] == "ok", by_field["h2_outline"]
    # 站队点必须至少部分兑现（正文保留核心判断）
    assert by_field["standing_point"]["status"] in ("ok", "partial")
    # title_promise 允许 partial（标题打磨），不允许 missing
    assert by_field["title_promise"]["status"] in ("ok", "partial")
    assert by_field["ending_destination"]["status"] in ("ok", "partial")


# ---- drift detection -------------------------------------------------------

def test_missing_h2_detected_as_drift(tmp_path):
    card = _mk_card(tmp_path, ["第一章：人物的选择", "第二章：时代的重量", "第三章：结局"])
    draft = _mk_draft(tmp_path, "标题", ["第一章：人物的选择"])  # 承诺 3 个 H2，只交付 1 个
    v = tcf.check_fidelity(card, draft)
    by_field = {c["field"]: c for c in v["checks"]}
    assert by_field["h2_outline"]["status"] == "missing"
    assert any(h["status"] == "missing" for h in by_field["h2_outline"]["per_h2"])


def test_topic_completely_lost_is_missing(tmp_path):
    card = _mk_card(
        tmp_path,
        ["唯一主题：深海捕鲸的伦理"],
        stance="鲸鱼不该成为猎杀对象",
        promise="深海里捕鲸人的挣扎",
    )
    # 成稿完全没提鲸鱼/深海/捕鲸，换成了无关内容
    draft = _mk_draft(tmp_path, "无关标题", ["第一章"], body="张三在沙漠里寻找绿洲，故事在这里结束。")
    v = tcf.check_fidelity(card, draft)
    by_field = {c["field"]: c for c in v["checks"]}
    assert by_field["standing_point"]["status"] == "missing"


def test_main_returns_1_on_missing(tmp_path):
    card = _mk_card(tmp_path, ["承诺的章节A", "承诺的章节B"])
    draft = _mk_draft(tmp_path, "标题", ["只写了A"])
    code = tcf.main([str(card), str(draft)])
    assert code == 1


def test_main_returns_0_on_fulfilled(tmp_path):
    card = _mk_card(tmp_path, ["承诺的章节A"])
    draft = _mk_draft(tmp_path, "标题", ["承诺的章节A"])
    code = tcf.main([str(card), str(draft)])
    assert code == 0


def test_usage_requires_card_and_draft(tmp_path, capsys):
    code = tcf.main([])
    assert code == 2
