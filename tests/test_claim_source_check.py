"""claim_source_check：事实必须能在声明来源的抓取文件中锚定。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from article_group.claim_source_check import (
    check_material_pack,
    check_run_material_packs,
    fact_anchors_in_source,
    normalize_text,
)

DAILY_005 = Path("runs/2026-09-15/daily-005")
needs_daily_005 = pytest.mark.skipif(
    not (DAILY_005 / "batch.json").exists(),
    reason="runs/ 是本地审计目录（gitignore），daily-005 不在当前工作树时不跑集成断言",
)


def test_normalize_strips_tags_and_whitespace():
    raw = "<html><script>var x=1;</script><style>a{}</style><p>王凯 把 马憩 与 林看山 的对手戏 形容成 下棋</p></html>"
    normalized = normalize_text(raw)
    assert "script" not in normalized.lower() or "var x" not in normalized
    assert " " not in normalized
    assert "王凯把马憩与林看山的对手戏形容成下棋" in normalized


def test_contiguous_window_anchors():
    anchored, windows = fact_anchors_in_source(
        "《交锋》2026年9月6日在央视八套、腾讯视频、咪咕视频开播，共40集",
        "据官方消息，《交锋》2026年9月6日在央视八套、腾讯视频、咪咕视频开播，共40集。",
    )
    assert anchored is True
    assert windows


def test_token_coverage_anchors_separated_entities():
    # 来源页人名分散排布，无 6 字连续窗口，但实体 token 全部逐字存在
    anchored, matched = fact_anchors_in_source(
        "王凯、马憩、林看山",
        "王凯主演，马憩与林看山是剧中人物。",
    )
    assert anchored is True
    assert any(str(item).startswith("token:") for item in matched)


def test_unrelated_fact_fails_to_anchor():
    anchored, _ = fact_anchors_in_source(
        "片名原本是“欢迎来到龙餐馆”，最后删掉了“到”字",
        "这篇文章讲的是完全无关的另一部电影。",
    )
    assert anchored is False


def _write(tmp_path: Path, rel: str, content: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _pack_with_fact(source_id: str, fact: str) -> dict:
    return {
        "sources": [
            {"source_id": source_id, "locator": "fulltext"},
        ],
        "obtained_facts_by_source": {source_id: [fact]},
        "content_value_plan": {},
    }


def test_check_material_pack_passes_anchored_and_fails_unanchored(tmp_path):
    _write(tmp_path, "source-manifest.json", json.dumps(
        {"sources": [{"source_id": "src-a", "artifact_path": "sources/a.html"}]}
    ))
    _write(tmp_path, "sources/a.html", "<p>王凯把马憩与林看山的对手戏形容成下棋</p>")

    good = check_material_pack(tmp_path, _pack_with_fact("src-a", "王凯把马憩与林看山的对手戏形容成下棋"))
    assert good["pass"] is True
    assert good["errors"] == []

    bad = check_material_pack(tmp_path, _pack_with_fact("src-a", "导演声称本片票房突破百亿"))
    assert bad["pass"] is False
    assert any(e.startswith("fact_not_anchored:") for e in bad["errors"])


@needs_daily_005
def test_daily_005_material_packs_all_anchor():
    report = check_run_material_packs(DAILY_005)
    assert report["pass"], report["errors"]
    assert len(report["packs"]) == 2
    for pack in report["packs"]:
        assert all(item["anchored"] for item in pack["results"])
