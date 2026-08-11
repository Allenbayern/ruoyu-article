from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from article_group.bilibili_capture import BilibiliCaptureError, build_case_cards


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _packet(tmp_path: Path) -> Path:
    root = tmp_path / "packet"
    (root / "sources").mkdir(parents=True)
    (root / "metrics").mkdir()
    plan = {
        "metric_plan": [
            {
                "metric": "view_count",
                "visible": True,
                "required": True,
                "source_type": "official_api",
                "capture_window": "at_capture",
                "rule_role": "minimum_threshold",
            },
            {
                "metric": "like_count",
                "visible": True,
                "required": True,
                "source_type": "official_api",
                "capture_window": "at_capture",
                "rule_role": "supporting_engagement_evidence",
            },
            {
                "metric": "comment_count",
                "visible": True,
                "required": True,
                "source_type": "official_api",
                "capture_window": "at_capture",
                "rule_role": "supporting_engagement_evidence",
            },
            {
                "metric": "share_count",
                "visible": True,
                "required": True,
                "source_type": "official_api",
                "capture_window": "at_capture",
                "rule_role": "supporting_engagement_evidence",
            },
            {
                "metric": "favorite_count",
                "visible": True,
                "required": True,
                "source_type": "official_api",
                "capture_window": "at_capture",
                "rule_role": "supporting_engagement_evidence",
            },
        ],
        "threshold_or_rank_rule": {
            "platform": "bilibili_column",
            "baseline": "test-batch",
            "window": "cumulative_count_at_capture",
            "rule": "view_count >= 100000",
            "minimums": {"view_count": 100000},
        },
    }
    _write_json(root / "metric-plan.json", plan)

    body = "这是一篇完整影视文章的正文。" * 100
    clean_path = root / "sources" / "sample.clean.md"
    clean_path.write_text(body + "\n", encoding="utf-8")
    _write_json(
        root / "sources" / "sample.source.json",
        {
            "capture_status": "full",
            "clean_sha256": hashlib.sha256((body + "\n").encode()).hexdigest(),
        },
    )
    payload = {
        "code": 0,
        "data": {
            "title": "测试影视文章",
            "author_name": "测试作者",
            "stats": {"view": 150000, "like": 7000, "reply": 500, "share": 300, "favorite": 900},
        },
    }
    _write_json(root / "metrics" / "sample.api.json", {"payload": payload})
    _write_json(
        root / "capture-results.json",
        {
            "results": [
                {
                    "article_id": 1,
                    "slug": "sample",
                    "title": "测试影视文章",
                    "author": "测试作者",
                    "url": "https://www.bilibili.com/read/cv1",
                    "theme": "电影",
                    "observed_at": "2026-08-11T12:30:00+08:00",
                    "api_evidence_ref": "metrics/sample.api.json",
                    "body_evidence_ref": "sources/sample.clean.md",
                    "metrics": {
                        "view_count": 150000,
                        "like_count": 7000,
                        "comment_count": 500,
                        "share_count": 300,
                        "favorite_count": 900,
                    },
                }
            ]
        },
    )
    return root


def test_build_case_cards_qualifies_closed_packet(tmp_path: Path) -> None:
    root = _packet(tmp_path)

    manifest = build_case_cards(root)

    assert manifest["sample_count"] == 1
    assert manifest["qualified_viral_count"] == 1
    card = json.loads((root / "cards" / "sample.json").read_text(encoding="utf-8"))
    assert card["qualification_status"] == "qualified_viral"
    assert card["metrics"][0]["value"] == 150000
    assert card["metric_plan"][0]["source_type"] == "official_api"


def test_build_case_cards_rejects_metric_summary_that_disagrees_with_api(
    tmp_path: Path,
) -> None:
    root = _packet(tmp_path)
    results_path = root / "capture-results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    results["results"][0]["metrics"]["view_count"] = 999999
    _write_json(results_path, results)

    with pytest.raises(BilibiliCaptureError, match="result_metric_disagrees_with_api:view_count"):
        build_case_cards(root)


def test_build_case_cards_rejects_changed_body_snapshot(tmp_path: Path) -> None:
    root = _packet(tmp_path)
    (root / "sources" / "sample.clean.md").write_text("altered", encoding="utf-8")

    with pytest.raises(BilibiliCaptureError, match="body_snapshot_digest_mismatch"):
        build_case_cards(root)


def test_build_case_cards_rejects_result_title_disagrees_with_api(
    tmp_path: Path,
) -> None:
    root = _packet(tmp_path)
    results_path = root / "capture-results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    results["results"][0]["title"] = "被篡改的标题"
    _write_json(results_path, results)

    with pytest.raises(BilibiliCaptureError, match="result_title_disagrees_with_api"):
        build_case_cards(root)
