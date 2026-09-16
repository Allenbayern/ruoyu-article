"""标题不得当论据（claim_source_check.title_only_anchor）。

背景（2026-09-16，daily-008 扩写实验）：该期成稿的三句"结论式论据"分别取自
c02/c03/c04 的**标题**（"姜文没变，观众和时代变了"等），旧门禁只检查"能否在来源
文本里锚定"，标题也文本一部分，于是全部通过。现在把"只在标题命中"单列为 warning。
"""
from __future__ import annotations

import json
from pathlib import Path

from article_group.claim_source_check import (
    body_only_text,
    check_content_fidelity,
    check_material_pack,
    source_titles,
)

HEADLINE = "姜文没变，观众和时代变了"
BODY = "影片公映七天累计票房八千二百万左右，单日票房跌到第八名，差评集中在看不懂与爹味。"
BODY_FACT = "影片公映七天累计票房八千二百万左右"


def _run_root(tmp_path: Path, *, title: str = HEADLINE) -> Path:
    root = tmp_path / "daily-900"
    sources = root / "sources"
    sources.mkdir(parents=True)
    (sources / "c02.html").write_text(
        f"<html><head><title>{title}</title></head><body><p>{BODY}</p></body></html>",
        encoding="utf-8",
    )
    (root / "source-manifest.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": "src-sohu",
                        "title": title,
                        "artifact_path": "sources/c02.html",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return root


def _pack(fact: str) -> dict:
    return {
        "sources": [{"source_id": "src-sohu"}],
        "obtained_facts_by_source": {"src-sohu": [fact]},
    }


def test_body_only_text_removes_headline_occurrences():
    assert body_only_text("标题甲正文标题甲", "标题甲") == "正文"


def test_source_titles_uses_manifest_title(tmp_path):
    root = _run_root(tmp_path)
    assert source_titles(root, ["src-sohu"]) == {"src-sohu": HEADLINE}


def test_source_titles_falls_back_to_title_tag(tmp_path):
    root = _run_root(tmp_path)
    (root / "source-manifest.json").write_text(
        json.dumps({"sources": [{"source_id": "src-sohu", "artifact_path": "sources/c02.html"}]},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    assert source_titles(root, ["src-sohu"]) == {"src-sohu": HEADLINE}


def test_headline_only_fact_is_a_warning_and_keeps_pass(tmp_path):
    root = _run_root(tmp_path)
    report = check_material_pack(root, _pack(HEADLINE))
    assert report["pass"] is True
    assert report["errors"] == []
    assert any(item.startswith("title_only_anchor:src-sohu:") for item in report["warnings"])
    assert report["results"][0]["title_only"] is True


def test_body_fact_is_not_flagged(tmp_path):
    root = _run_root(tmp_path)
    report = check_material_pack(root, _pack(BODY_FACT))
    assert report["warnings"] == []
    assert report["results"][0]["title_only"] is False


def test_missing_fact_still_errors(tmp_path):
    root = _run_root(tmp_path)
    report = check_material_pack(root, _pack("这条事实在两处都找不到"))
    assert report["pass"] is False
    assert any(item.startswith("fact_not_anchored:") for item in report["errors"])


def test_content_fidelity_ledger_flags_headline_item(tmp_path):
    root = _run_root(tmp_path)
    fidelity = {
        "article_id": "art-001",
        "hard_information": [
            {
                "information_id": "i7",
                "text": HEADLINE,
                "body_locator": "p3",
                "source_refs": ["src-sohu"],
            },
            {
                "information_id": "i5",
                "text": BODY_FACT,
                "body_locator": "p2",
                "source_refs": ["src-sohu"],
            },
        ],
    }
    report = check_content_fidelity(root, fidelity)
    assert report["pass"] is True
    assert report["errors"] == []
    assert report["warnings"] == [f"title_only_anchor:i7:{HEADLINE[:32]}"]
    flagged = {item["information_id"]: item["title_only"] for item in report["results"]}
    assert flagged == {"i7": True, "i5": False}
