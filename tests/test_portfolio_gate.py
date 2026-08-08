"""Tests for article_group.portfolio_gate - batch topic-diversity checks.

Fixtures mirror real production shapes:
- controlled-015: three schedule-change articles from ONE event cluster
  (summer release-date changes) - must FAIL
- controlled-009: mixed pool (person, work-deep-dive, culture, film) - the
  first three "A" candidates should PASS quadrant/window/mode checks
"""
from __future__ import annotations

import json

import pytest

from article_group import portfolio_gate as pg


def _cand(cid: str, **kw) -> dict:
    base = {
        "candidate_id": cid,
        "work": f"作品-{cid}",
        "recommendation": "A",
        "content_map": "A",
        "topic_mode": "release_event",
        "freshness_window": "same-day",
        "event_cluster_id": f"cluster-{cid}",
        "remove_timestamp_test": "fail",
        "editorial_value_score": 3,
        "evidence_readiness": "high",
    }
    base.update(kw)
    return base


@pytest.fixture
def pool015(tmp_path):
    """The controlled-015 failure pattern: 3 same-cluster schedule items."""
    candidates = [
        _cand(
            "c1",
            content_map="A",
            topic_mode="release_event",
            event_cluster_id="summer-release-change-2026",
            freshness_window="same-day",
            remove_timestamp_test="fail",
        ),
        _cand(
            "c2",
            content_map="A",
            topic_mode="release_event",
            event_cluster_id="summer-release-change-2026",
            freshness_window="same-day",
            remove_timestamp_test="fail",
        ),
        _cand(
            "c3",
            content_map="A",
            topic_mode="release_event",
            event_cluster_id="summer-release-change-2026",
            freshness_window="same-day",
            remove_timestamp_test="fail",
        ),
    ]
    pool = {"run_id": "test-015", "candidates": candidates}
    path = tmp_path / "pool015.json"
    path.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
    return str(path)


@pytest.fixture
def pool009(tmp_path):
    """The controlled-009 healthy pattern: person + work-deep-dive + culture."""
    candidates = [
        _cand(
            "c1",
            content_map="D",
            topic_mode="character",
            event_cluster_id="youbenchang-77-roles",
            freshness_window="same-day",
            remove_timestamp_test="pass",
            editorial_value_score=5,
        ),
        _cand(
            "c2",
            content_map="B",
            topic_mode="craft",
            event_cluster_id="anime-ordinary-gods",
            freshness_window="fermenting-1-3d",
            remove_timestamp_test="pass",
            editorial_value_score=4,
        ),
        _cand(
            "c3",
            content_map="C",
            topic_mode="culture",
            event_cluster_id="cinema-return-culture",
            freshness_window="revival",
            remove_timestamp_test="pass",
            editorial_value_score=4,
        ),
    ]
    pool = {"run_id": "test-009", "candidates": candidates}
    path = tmp_path / "pool009.json"
    path.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
    return str(path)


# ---- quadrant checks -----------------------------------------------------

def test_quadrants_concentrated_error(pool015):
    verdict, code = pg.run_checks(pool015)
    assert code == 1
    ids = [i["id"] for i in verdict["errors"]]
    assert "portfolio.quadrant.concentrated" in ids
    assert "portfolio.cluster.duplicate" in ids
    assert "portfolio.topic_mode.all_release_event" in ids


def test_quadrants_ok(pool009):
    verdict, code = pg.run_checks(pool009)
    assert code == 0
    assert verdict["pass"] is True
    assert len(verdict["errors"]) == 0


def test_quadrant_overquota(tmp_path):
    c = [
        _cand("a", content_map="A"),
        _cand("b", content_map="A"),
        _cand("c", content_map="A", topic_mode="character"),
    ]
    pool = {"candidates": c}
    path = tmp_path / "over.json"
    path.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
    verdict, code = pg.run_checks(str(path))
    assert code == 1
    assert any(i["id"] == "portfolio.quadrant.overquota" for i in verdict["errors"])


def test_quadrant_label_normalization(tmp_path):
    """content_map stored as 'C 文化现象' (legacy label) must normalize to C."""
    c = [
        _cand("a", content_map="A 新片事件", topic_mode="market"),
        _cand("b", content_map="B 作品深度", topic_mode="revisit"),
        _cand("c", content_map="C 文化现象", topic_mode="culture"),
    ]
    pool = {"candidates": c}
    path = tmp_path / "label.json"
    path.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
    verdict, code = pg.run_checks(str(path))
    assert code == 0
    assert verdict["quadrant_counts"] == {"A": 1, "B": 1, "C": 1}


def test_quadrant_missing_is_error(tmp_path):
    c = [
        _cand("a", content_map="A"),
        _cand("b", content_map="B"),
        _cand("c", content_map=""),
    ]
    pool = {"candidates": c}
    path = tmp_path / "missing.json"
    path.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
    verdict, code = pg.run_checks(str(path))
    assert code == 1
    assert any(i["id"] == "portfolio.quadrant.missing" for i in verdict["errors"])


# ---- cluster checks ------------------------------------------------------

def test_cluster_missing_is_warning_not_error(tmp_path):
    c = [
        _cand("a", content_map="A", topic_mode="market"),
        _cand("b", content_map="B", topic_mode="character"),
        _cand("c", content_map="C", topic_mode="culture", event_cluster_id=""),
    ]
    pool = {"candidates": c}
    path = tmp_path / "nocluster.json"
    path.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
    verdict, code = pg.run_checks(str(path))
    assert code == 0
    assert any(i["id"] == "portfolio.cluster.missing" for i in verdict["warnings"])


def test_selected_slot_ids_used(tmp_path):
    """Gate must honor selected_slot_ids when present (drop mid-batch)."""
    candidates = [
        _cand("a", content_map="A", event_cluster_id="cl-A", topic_mode="market"),
        _cand("b", content_map="B", event_cluster_id="cl-B", topic_mode="character"),
        _cand("c", content_map="C", event_cluster_id="cl-C", topic_mode="culture"),
        _cand("d", content_map="A", event_cluster_id="cl-A"),  # duplicate cluster
    ]
    pool = {
        "candidates": candidates,
        "selected_slot_ids": ["a", "b", "c"],
    }
    path = tmp_path / "sel.json"
    path.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
    verdict, code = pg.run_checks(str(path))
    assert code == 0
    assert verdict["batch_size"] == 3


def test_selected_slot_missing_reference_is_error(tmp_path):
    candidates = [_cand("a", content_map="A")]
    pool = {"candidates": candidates, "selected_slot_ids": ["a", "ghost", "x"]}
    path = tmp_path / "ghost.json"
    path.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
    verdict, code = pg.run_checks(str(path))
    assert code == 1
    assert any(i["id"] == "portfolio.input" for i in verdict["errors"])


# ---- window checks -------------------------------------------------------

def test_evergreen_gap_is_info_not_error(tmp_path):
    c = [
        _cand("a", content_map="A", freshness_window="same-day", topic_mode="market"),
        _cand("b", content_map="B", freshness_window="fermenting-1-3d", topic_mode="character"),
        _cand("c", content_map="C", freshness_window="fermenting-1-3d", topic_mode="culture"),
    ]
    pool = {"candidates": c}
    path = tmp_path / "gap.json"
    path.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
    verdict, code = pg.run_checks(str(path))
    assert code == 0
    assert any(i["id"] == "portfolio.window.evergreen_gap" for i in verdict["infos"])


def test_window_invalid_value_warns(tmp_path):
    c = [
        _cand("a", content_map="A", freshness_window="same-day", topic_mode="market"),
        _cand("b", content_map="B", freshness_window="fermenting-1-3d", topic_mode="character"),
        _cand("c", content_map="C", freshness_window="soon", topic_mode="culture"),
    ]
    pool = {"candidates": c}
    path = tmp_path / "badwin.json"
    path.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
    verdict, code = pg.run_checks(str(path))
    assert code == 0
    assert any(i["id"] == "portfolio.window.invalid" for i in verdict["warnings"])


# ---- topic_mode checks ---------------------------------------------------

def test_all_release_event_is_error(tmp_path):
    c = [_cand("a"), _cand("b"), _cand("c", content_map="B")]
    pool = {"candidates": c}
    path = tmp_path / "rel.json"
    path.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
    verdict, code = pg.run_checks(str(path))
    assert code == 1
    assert any(i["id"] == "portfolio.topic_mode.all_release_event" for i in verdict["errors"])


def test_mixed_modes_ok(tmp_path):
    c = [
        _cand("a", topic_mode="release_event"),
        _cand("b", content_map="B", topic_mode="character"),
        _cand("c", content_map="C", topic_mode="culture"),
    ]
    pool = {"candidates": c}
    path = tmp_path / "mixed.json"
    path.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
    verdict, code = pg.run_checks(str(path))
    assert code == 0


# ---- readiness / value checks -------------------------------------------

def test_readiness_never_substitutes_value(tmp_path):
    """High readiness + missing editorial value must still warn."""
    c = [
        _cand("a", content_map="A", editorial_value_score=None, topic_mode="market"),
        _cand("b", content_map="B", topic_mode="character"),
        _cand("c", content_map="C", topic_mode="culture"),
    ]
    pool = {"candidates": c}
    path = tmp_path / "val.json"
    path.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
    verdict, code = pg.run_checks(str(path))
    assert code == 0
    assert any(i["id"] == "portfolio.value.missing" for i in verdict["warnings"])


# ---- input handling ------------------------------------------------------

def test_underfull_batch_is_error(tmp_path):
    c = [_cand("a", content_map="A"), _cand("b", content_map="B")]
    pool = {"candidates": c}
    path = tmp_path / "two.json"
    path.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
    verdict, code = pg.run_checks(str(path))
    assert code == 1
    assert any(i["id"] == "portfolio.input" for i in verdict["errors"])
