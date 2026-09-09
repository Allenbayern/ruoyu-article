"""Pure, offline helpers for Article Group V5 artifact contracts."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Mapping


ARTIFACT_SCHEMA_VERSIONS = (
    "v5-experiment-record-v1",
    "v5-content-lifecycle-v1",
    "v5-article-dna-v1",
    "v5-failure-samples-v1",
    "v5-dynamic-quotas-v1",
    "v5-strategy-library-v1",
    "v5-resource-plan-v1",
    "v5-verification-v1",
)

LIFECYCLE_STATES = (
    "draft",
    "published",
    "observing",
    "stable",
    "rising",
    "decaying",
    "evergreen",
    "archived",
)

EXPERIMENT_DESIGNS = (
    "observational",
    "same_topic_different_title",
    "same_topic_different_opening",
    "controlled",
)

FAILURE_TYPES = (
    "exposure_without_click",
    "click_low_completion",
    "high_completion_low_exposure",
    "high_interaction_low_revenue",
    "good_data_high_risk",
    "insufficient_data",
)

STRATEGY_STATES = (
    "provisional",
    "testing",
    "supported",
    "deprecated",
    "retired",
)

PUBLICATION_AUTHORIZATION = "not_authorized"

_ENVELOPE_KEYS = frozenset(
    {"schema_version", "run_id", "generated_at", "input_hashes", "payload"}
)
_SHA256_LENGTH = 64
_RFC3339_SUBSET = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(?:\.[0-9]+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)


def new_artifact_envelope(
    schema_version: str,
    run_id: str,
    payload: Mapping[str, Any],
    *,
    generated_at: str,
) -> dict[str, Any]:
    """Create a V5 envelope without adding publication or environment state."""

    return {
        "schema_version": schema_version,
        "run_id": run_id,
        "generated_at": generated_at,
        "input_hashes": {},
        "payload": dict(payload),
    }


def payload_of(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return an envelope payload, or an empty mapping for malformed input."""

    payload = value.get("payload") if isinstance(value, Mapping) else None
    return payload if isinstance(payload, Mapping) else {}


def _is_authorization_key(key: object) -> bool:
    return isinstance(key, str) and "authorization" in key.casefold()


def _has_forbidden_authorization(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if _is_authorization_key(key) and nested != PUBLICATION_AUTHORIZATION:
                return True
            if _has_forbidden_authorization(nested):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_has_forbidden_authorization(nested) for nested in value)
    return False


def _valid_hashes(value: object) -> bool:
    return isinstance(value, Mapping) and all(
        isinstance(key, str)
        and isinstance(digest, str)
        and len(digest) == _SHA256_LENGTH
        and all(character in "0123456789abcdefABCDEF" for character in digest)
        for key, digest in value.items()
    )


def validate_v5_artifact_envelope(
    value: Mapping[str, Any],
    expected_schema: str,
    *,
    run_id: str,
) -> list[str]:
    """Return stable errors for a V5 envelope, failing closed on boundaries."""

    errors: list[str] = []
    if not isinstance(value, Mapping):
        return ["invalid:artifact"]

    if set(value) - _ENVELOPE_KEYS:
        errors.append("invalid:top_level")

    schema = value.get("schema_version")
    if schema is None:
        errors.append("missing:schema_version")
    elif schema not in ARTIFACT_SCHEMA_VERSIONS:
        errors.append("unknown:schema_version")
    elif schema != expected_schema:
        errors.append("mismatch:schema_version")

    actual_run_id = value.get("run_id")
    if not isinstance(actual_run_id, str) or not actual_run_id.strip():
        errors.append("missing:run_id")
    elif actual_run_id != run_id:
        errors.append("mismatch:run_id")

    generated_at = value.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at.strip():
        errors.append("missing:generated_at")
    elif _RFC3339_SUBSET.fullmatch(generated_at) is None:
        errors.append("invalid:generated_at")
    else:
        try:
            datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError:
            errors.append("invalid:generated_at")

    if "input_hashes" not in value:
        errors.append("missing:input_hashes")
    elif not _valid_hashes(value["input_hashes"]):
        errors.append("invalid:input_hashes")

    if "payload" not in value:
        errors.append("missing:payload")
    elif not isinstance(value["payload"], Mapping):
        errors.append("invalid:payload")
    elif _has_forbidden_authorization(value["payload"]):
        errors.append("publication_authorization_must_be_not_authorized")

    return list(dict.fromkeys(errors))
