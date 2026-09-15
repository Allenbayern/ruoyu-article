from __future__ import annotations

from article_group.source_capability import (
    CAPABILITY_LEVELS,
    validate_claim_capabilities,
)


def _source(source_id, source_type, **overrides):
    return {
        "source_id": source_id,
        "capture_type": source_type,
        "locator": "可复核定位",
        "obtained_facts": ["一条事实"],
        **overrides,
    }


def test_capability_levels_have_a_deterministic_narrative_order():
    assert CAPABILITY_LEVELS.index("event_exists") < CAPABILITY_LEVELS.index("scene_action")
    assert CAPABILITY_LEVELS.index("scene_action") < CAPABILITY_LEVELS.index("mechanism")


def test_platform_synopsis_cannot_support_a_specific_scene_claim():
    errors = validate_claim_capabilities(
        [_source("synopsis", "page_metadata")],
        [{"claim_id": "c1", "claim_level": "scene_action", "source_ids": ["synopsis"]}],
        strict=True,
    )

    assert "claim_level_exceeds_source_capability:c1:synopsis" in errors


def test_explicitly_capable_scene_source_can_support_a_scene_claim():
    errors = validate_claim_capabilities(
        [_source("scene", "scene_verified", source_capability="scene_action")],
        [{"claim_id": "c1", "claim_level": "scene_action", "source_ids": ["scene"]}],
        strict=True,
    )

    assert errors == []


def test_strict_claim_requires_a_source_reference_and_capability_declaration():
    errors = validate_claim_capabilities(
        [_source("source", "unknown_capture")],
        [{"claim_id": "c1", "claim_level": "mechanism", "source_ids": ["source"]}],
        strict=True,
    )

    assert "invalid:source_capability:source" in errors

