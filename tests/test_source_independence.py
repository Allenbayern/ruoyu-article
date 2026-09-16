"""Tests for source_independence (syndication / rewrite screening).

Fixtures mirror the real daily-008 pattern: one newsroom copy republished by
several platforms as a *rewrite* (0% sentence overlap, ~100% fact overlap).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from article_group.source_independence import (
    classify,
    compare_pair,
    document_title,
    fact_points,
    group_files,
    group_sources,
    main,
    screen_source,
    shared_spans,
    visible_text,
)

ORIGINAL = (
    "潮新闻记者陆芳报道。影片由姜文、马丽、张乘郝主演，取材于钢琴家郎朗的成长经历。"
    "影片7月18日正式上映，片长144分钟，公映七天累计票房八千二百万左右。"
    "姜文表示，塔吊那场戏拍了很久，剧组专门请了钢琴专家团。"
)

REWRITE = (
    "据钱江晚报消息，这部作品由姜文、马丽、张乘郝出演，故事来自钢琴家郎朗的经历。"
    "该片于7月18日与观众见面，片长144分钟，上映首周票房大约八千二百万。"
    "姜文透露，那段塔吊戏拍摄时间很长，片方还邀请了钢琴专家参与。"
)

FRAGMENT = "该片7月18日上映，片长144分钟，首周票房八千二百万。"

INDEPENDENT = (
    "另一家媒体的评论认为，这部电影写父子关系写得很别扭，真正好看的是音乐段落。"
    "作者提到，结尾那场比赛让他想起《爆裂鼓手》，而隐喻的部分反而拖慢了节奏。"
    "文章还批评了宣传时的口径，认为观众并不需要被反复解释。"
)


def test_visible_text_strips_markup_and_scripts():
    raw = "<html><head><title>标题甲</title><script>var x=1;</script></head>" \
          "<body><p>正文<b>第一句</b></p></body></html>"
    text = visible_text(raw)
    assert "var x" not in text
    assert "正文" in text and "第一句" in text
    assert document_title(raw) == "标题甲"


def test_fact_points_extract_numbers_titles_and_quotes():
    points = fact_points("片长144分钟，票房八千二百万。他说：“这段戏拍了很久”；见《爆裂鼓手》。")
    assert "144分钟" in points["numbers"]
    assert "《爆裂鼓手》" in points["titles"]
    assert "这段戏拍了很久" in points["quotes"]


def test_shared_spans_returns_long_common_passage():
    spans = shared_spans(ORIGINAL, ORIGINAL)
    assert spans
    assert max(len(span) for span in spans) >= 20


def test_compare_pair_scores_facts_when_wording_differs():
    comparison = compare_pair(REWRITE, ORIGINAL)
    assert comparison["number_overlap"] >= 0.6
    assert {"7月18日", "144分钟"} <= set(comparison["shared_numbers"])
    assert comparison["span_ratio"] < 0.5  # rewrite, not a copy


def test_rewrite_is_not_a_distinct_source():
    report = screen_source(REWRITE, {"original": ORIGINAL})
    assert report["verdict"] == "syndicated_rewrite"
    assert report["counts_as_distinct_source"] is False
    assert report["advisory"] is True
    assert report["publication_authorization"] == "not_authorized"


def test_independent_source_is_distinct():
    report = screen_source(INDEPENDENT, {"original": ORIGINAL, "rewrite": REWRITE})
    assert report["verdict"] == "independent"
    assert report["counts_as_distinct_source"] is True


def test_classify_without_reference_stays_needs_review():
    verdict = classify([])
    assert verdict["verdict"] == "independent"
    assert verdict["confidence"] == "low"
    assert verdict["needs_human_review"] is True


def test_group_sources_counts_rewrite_chain_once():
    report = group_sources(
        {"original": ORIGINAL, "rewrite": REWRITE, "fragment": FRAGMENT, "other": INDEPENDENT},
        published={
            "original": "2025-07-19 06:30",
            "rewrite": "2025-07-19 19:06",
            "fragment": "2025-07-20 10:00",
            "other": "2025-07-23 12:00",
        },
    )
    assert report["distinct_source_count"] == 2
    assert set(report["distinct_sources"]) == {"original", "other"}
    groups = {group["canonical"]: group for group in report["groups"]}
    assert set(groups) == {"original", "other"}
    assert groups["original"]["distinct_source"] is False
    roles = {member["source_id"]: member["role"] for member in groups["original"]["members"]}
    assert roles["original"] == "canonical"
    assert roles["rewrite"] == "syndicated_rewrite"
    assert roles["fragment"] != "canonical"


def test_group_prefers_primary_marker_source_over_longer_rewrite():
    """The rewrite is longer here, so length alone must not pick the canonical."""
    padded_rewrite = REWRITE + "此外，片方还发布了一组幕后花絮照片，记录了拍摄期间的点滴，" \
                                "并公布了新一轮的宣传活动安排与主创见面会的城市名单。"
    report = group_sources({"newsroom": ORIGINAL, "aggregator": padded_rewrite})
    assert report["groups"][0]["canonical"] == "newsroom"


def test_group_files_reads_html_and_text(tmp_path: Path):
    (tmp_path / "a.html").write_text(f"<html><body><p>{ORIGINAL}</p></body></html>", encoding="utf-8")
    (tmp_path / "b.txt").write_text(REWRITE, encoding="utf-8")
    report = group_files([tmp_path / "a.html", tmp_path / "b.txt"])
    assert report["distinct_source_count"] == 1


def test_cli_group_mode_reports_distinct_sources(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    left = tmp_path / "left.txt"
    right = tmp_path / "right.txt"
    left.write_text(ORIGINAL, encoding="utf-8")
    right.write_text(REWRITE, encoding="utf-8")
    assert main(["--source", str(left), "--source", str(right)]) == 0
    out = capsys.readouterr().out
    assert "distinct sources: 1" in out
    assert "canonical=" in out


def test_cli_group_mode_json_is_machine_readable(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    left = tmp_path / "left.txt"
    right = tmp_path / "right.txt"
    left.write_text(ORIGINAL, encoding="utf-8")
    right.write_text(INDEPENDENT, encoding="utf-8")
    assert main(["--source", str(left), "--source", str(right), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["distinct_source_count"] == 2
    assert payload["publication_authorization"] == "not_authorized"


def test_cli_candidate_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    candidate = tmp_path / "candidate.txt"
    reference = tmp_path / "reference.txt"
    candidate.write_text(REWRITE, encoding="utf-8")
    reference.write_text(ORIGINAL, encoding="utf-8")
    assert main(["--candidate", str(candidate), "--source", str(reference)]) == 0
    out = capsys.readouterr().out
    assert "syndicated_rewrite" in out
    assert "distinct_source=False" in out
