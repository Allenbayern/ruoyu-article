"""Offline tests for the isolated R0 Yuafeng discovery radar."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from article_group.discovery_radar import (
    DiscoveryRadarError,
    build_yuafeng_discovery_radar,
    validate_discovery_radar,
)
from article_group.prewrite import validate_candidate_pool


def _result(
    *,
    source: str = "yuafeng-uc",
    endpoint: str = "/API/xq_shenmahot.php",
    items: list[dict[str, Any]] | None = None,
    source_role: str = "discovery",
    evidence_eligible: bool = False,
) -> dict[str, Any]:
    return {
        "source": source,
        "endpoint": endpoint,
        "fetched_at": "2026-08-01T12:00:00+00:00",
        "source_role": source_role,
        "evidence_eligible": evidence_eligible,
        "raw_json": {"must_not_be_written": True},
        "items": [{"title": "热搜标题", "url": "https://example.test/1"}] if items is None else items,
    }


def _fetchers() -> dict[str, Any]:
    return {
        "uc": lambda **kwargs: _result(),
        "tencent": lambda **kwargs: _result(source="yuafeng-tencent", endpoint="/API/txxw.php"),
        "aggregate": lambda **kwargs: _result(source="yuafeng-aggregate", endpoint="/API/jinri_hot.php"),
    }


def test_writes_atomic_r0_artifact_without_raw_json(tmp_path: Path) -> None:
    target = tmp_path / "radar.json"
    artifact = build_yuafeng_discovery_radar(target, [{"name": "uc"}], _fetchers=_fetchers())

    assert json.loads(target.read_text(encoding="utf-8")) == artifact
    assert not (tmp_path / ".radar.json.tmp").exists()
    assert artifact["artifact_type"] == "discovery_radar"
    assert artifact["state"] == "R0 radar"
    assert artifact["source_layer"] == "discovery-only"
    assert artifact["candidate_pool_eligible"] is False
    assert artifact["evidence_eligible"] is False
    assert artifact["next_action"] == "needs_editorial_research"
    assert artifact["records"][0]["locator"] == "热搜标题"
    assert "raw_json" not in artifact["records"][0]


@pytest.mark.parametrize(
    "descriptor,error",
    [
        ({"name": "unknown"}, "invalid_source_name"),
        ({"name": "uc", "page": 1}, "invalid_uc_descriptor"),
        ({"name": "tencent", "page": True}, "invalid_tencent_page"),
        ({"name": "tencent", "type_": " hot"}, "invalid_tencent_type"),
        ({"name": "aggregate"}, "invalid_aggregate_action"),
        ({"name": "aggregate", "action": "任意热榜"}, "invalid_aggregate_action"),
        ({"name": "aggregate", "action": "微博热榜", "page": False}, "invalid_aggregate_page"),
    ],
)
def test_rejects_invalid_descriptors_before_fetch(
    tmp_path: Path, descriptor: dict[str, Any], error: str
) -> None:
    calls = 0

    def must_not_fetch(**kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return _result()

    with pytest.raises(DiscoveryRadarError, match=error):
        build_yuafeng_discovery_radar(
            tmp_path / "radar.json", [descriptor],
            _fetchers={"uc": must_not_fetch, "tencent": must_not_fetch, "aggregate": must_not_fetch},
        )
    assert calls == 0


def test_validates_every_descriptor_before_first_fetch(tmp_path: Path) -> None:
    calls = 0

    def uc(**kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return _result()

    with pytest.raises(DiscoveryRadarError, match="invalid_aggregate_action"):
        build_yuafeng_discovery_radar(
            tmp_path / "radar.json",
            [{"name": "uc"}, {"name": "aggregate", "action": "bad"}],
            _fetchers={"uc": uc, "aggregate": uc},
        )
    assert calls == 0


def test_passes_descriptor_arguments_to_injected_fetchers(tmp_path: Path) -> None:
    received: dict[str, Any] = {}

    def tencent(**kwargs: Any) -> dict[str, Any]:
        received.update(kwargs)
        return _result(source="yuafeng-tencent", endpoint="/API/txxw.php")

    build_yuafeng_discovery_radar(
        tmp_path / "radar.json", [{"name": "tencent", "page": 2, "type_": "hot"}],
        _fetchers={"tencent": tencent},
    )
    assert received == {"page": 2, "type_": "hot"}


def test_fails_closed_without_partial_artifact_on_fetch_or_envelope_error(tmp_path: Path) -> None:
    target = tmp_path / "radar.json"
    with pytest.raises(RuntimeError, match="upstream"):
        build_yuafeng_discovery_radar(target, [{"name": "uc"}], _fetchers={"uc": lambda **_: (_ for _ in ()).throw(RuntimeError("upstream"))})
    assert not target.exists()

    with pytest.raises(DiscoveryRadarError, match="fetch_result_not_discovery"):
        build_yuafeng_discovery_radar(target, [{"name": "uc"}], _fetchers={"uc": lambda **_: _result(source_role="evidence")})
    assert not target.exists()


@pytest.mark.parametrize("items", ["not-a-list", [{"title": "valid"}, "not-a-dict"]])
def test_rejects_malformed_upstream_items(tmp_path: Path, items: object) -> None:
    with pytest.raises(DiscoveryRadarError, match="invalid_fetch_result_items"):
        build_yuafeng_discovery_radar(
            tmp_path / "radar.json", [{"name": "uc"}],
            _fetchers={"uc": lambda **_: _result(items=items)},  # type: ignore[arg-type]
        )


def test_url_is_locator_when_title_absent(tmp_path: Path) -> None:
    artifact = build_yuafeng_discovery_radar(
        tmp_path / "radar.json", [{"name": "uc"}],
        _fetchers={"uc": lambda **_: _result(items=[{"url": "https://example.test/only"}])},
    )
    assert artifact["records"][0]["locator"] == "https://example.test/only"


def test_radar_is_rejected_by_candidate_pool_gate(tmp_path: Path) -> None:
    artifact = build_yuafeng_discovery_radar(tmp_path / "radar.json", [{"name": "uc"}], _fetchers=_fetchers())
    errors = validate_candidate_pool(artifact)
    assert errors
    assert any("candidate_pool" in error or "candidates" in error for error in errors)


def test_radar_validator_rejects_promotion_fields(tmp_path: Path) -> None:
    artifact = build_yuafeng_discovery_radar(tmp_path / "radar.json", [{"name": "uc"}], _fetchers=_fetchers())
    artifact["records"][0]["evidence_atom_ids"] = ["E1"]
    artifact["records"][0]["candidate_id"] = "C1"
    errors = validate_discovery_radar(artifact)
    assert "record_0_prohibited_evidence_atom_ids" in errors
    assert "record_0_prohibited_candidate_id" in errors


def test_radar_validator_rejects_promotion_flags(tmp_path: Path) -> None:
    artifact = build_yuafeng_discovery_radar(tmp_path / "radar.json", [{"name": "uc"}], _fetchers=_fetchers())
    artifact["candidate_pool_eligible"] = True
    artifact["records"][0]["evidence_eligible"] = True
    errors = validate_discovery_radar(artifact)
    assert "invalid_candidate_pool_eligible" in errors
    assert "record_0_invalid_evidence_eligible" in errors


def test_radar_validator_rejects_top_level_promotion_and_non_utc_timestamp(tmp_path: Path) -> None:
    artifact = build_yuafeng_discovery_radar(tmp_path / "radar.json", [{"name": "uc"}], _fetchers=_fetchers())
    artifact["candidates"] = []
    artifact["observed_at"] = "2026-08-01T12:00:00"
    errors = validate_discovery_radar(artifact)
    assert "prohibited_top_level_candidates" in errors
    assert "invalid_observed_at_utc" in errors


def test_import_does_not_fetch() -> None:
    import article_group.discovery_radar  # noqa: F401
