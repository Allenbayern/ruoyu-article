from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from article_group.case_contract import (
    CaseContractError,
    assess_qualification,
    validate_case_card,
)
from article_group.viral_research_contract import (
    ViralResearchContractError,
    validate_local_ref,
)

CARD_SCHEMA_VERSION = "viral-research-case-card-v1"
_SAMPLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ViralResearchCardError(ViralResearchContractError):
    """Raised when a deterministic case-card envelope is unsafe."""


def _error(code: str, detail: str = "") -> ViralResearchCardError:
    return ViralResearchCardError(f"{code}:{detail}" if detail else code)


def _text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(code)
    return value.strip()


def _schema_validate(card: Mapping[str, Any]) -> None:
    try:
        from jsonschema import Draft202012Validator, FormatChecker
        schema_path = Path(__file__).resolve().parents[1] / "schemas" / "viral-research-case-card.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(card),
            key=lambda item: list(item.absolute_path),
        )
    except (OSError, json.JSONDecodeError, ImportError) as exc:
        raise _error("schema_unavailable") from exc
    if errors:
        location = ".".join(str(part) for part in errors[0].absolute_path)
        raise _error("schema_error", f"{location}:{errors[0].message}")


def _normalized_ref(reference: Any, *, run_root: Path, field: str) -> str:
    if not isinstance(reference, str) or not reference.strip():
        raise _error("evidence_ref_missing", field)
    try:
        path, digest = validate_local_ref(reference, root=run_root)
    except ViralResearchContractError as exc:
        raise _error(str(exc).split(":", 1)[0], field) from exc
    return f"{path.relative_to(run_root).as_posix()}#sha256={digest}"


def _validate_case_contract(payload: Mapping[str, Any]) -> dict[str, Any]:
    try:
        status = validate_case_card(dict(payload))
    except CaseContractError as exc:
        raise _error("case_contract_failed", str(exc)) from exc
    return {
        "status": "validated",
        "qualification_status": status,
        "sample_id": str(payload.get("sample_id") or ""),
    }


def build_case_card(
    sample: Mapping[str, Any],
    *,
    run_root: str | Path,
    case_contract_card: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a non-promoting card envelope and optionally validate its case card."""
    if not isinstance(sample, Mapping):
        raise _error("sample_invalid")
    sample_id = _text(sample.get("sample_id"), "sample_id_missing")
    if not _SAMPLE_ID_RE.fullmatch(sample_id):
        raise _error("sample_id_unsafe")
    root = Path(run_root).expanduser().resolve()
    evidence = {
        field: _normalized_ref(sample.get(field), run_root=root, field=field)
        for field in ("raw_ref", "clean_ref", "metadata_ref")
    }
    shape = sample.get("shape")
    if not isinstance(shape, Mapping):
        raise _error("shape_invalid")
    qualification = sample.get("qualification_status")
    if qualification not in {"qualified_viral", "observed_pending", "research_only", "blocked"}:
        raise _error("qualification_status_invalid")
    card: dict[str, Any] = {
        "schema_version": CARD_SCHEMA_VERSION,
        "sample_id": sample_id,
        "platform": _text(sample.get("platform"), "platform_missing"),
        "account_id": _text(sample.get("account_id"), "account_id_missing"),
        "title": _text(sample.get("title"), "title_missing"),
        "canonical_url": _text(sample.get("canonical_url"), "canonical_url_missing"),
        "published_at": _text(sample.get("published_at"), "published_at_missing"),
        "shape": dict(shape),
        "qualification_status": qualification,
        "snapshot_ref": evidence["clean_ref"],
        "performance_evidence_ref": evidence["metadata_ref"],
        "evidence": {
            **evidence,
            "evidence_origin": "local_capture",
            "qualification_basis": "capture_and_source_evidence_only",
            "automatic_publication_authority": False,
        },
    }
    for key in ("revision", "revision_id", "capture_revision"):
        if key in sample and sample[key] not in (None, ""):
            card[key] = sample[key]
            break
    if case_contract_card is not None:
        if not isinstance(case_contract_card, Mapping):
            raise _error("case_contract_invalid")
        card["case_contract"] = _validate_case_contract(case_contract_card)
    _schema_validate(card)
    return card


def validate_case_card_envelope(
    card: Mapping[str, Any], *, run_root: str | Path
) -> dict[str, Any]:
    """Validate the envelope schema and all in-root evidence references."""
    if not isinstance(card, Mapping):
        raise _error("card_invalid")
    _schema_validate(card)
    root = Path(run_root).expanduser().resolve()
    evidence = card["evidence"]
    for field in ("raw_ref", "clean_ref", "metadata_ref"):
        _normalized_ref(evidence[field], run_root=root, field=field)
    return dict(card)


def write_case_cards(
    samples: Iterable[Mapping[str, Any]],
    *,
    run_root: str | Path,
    output_root: str | Path,
) -> dict[str, Any]:
    """Write deterministic card envelopes without copying source bodies."""
    output = Path(output_root).expanduser().resolve()
    if output.exists():
        raise _error("artifact_exists")
    output.mkdir(parents=True)
    cards: list[dict[str, Any]] = []
    try:
        for sample in samples:
            card = build_case_card(sample, run_root=run_root)
            card_path = output / f"{card['sample_id']}.json"
            card_path.write_text(
                json.dumps(card, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            cards.append(
                {
                    "sample_id": card["sample_id"],
                    "card_ref": card_path.name,
                    "qualification_status": card["qualification_status"],
                }
            )
        manifest = {
            "schema_version": CARD_SCHEMA_VERSION,
            "card_count": len(cards),
            "cards": cards,
            "automatic_publication_authority": False,
        }
        (output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return manifest
    except Exception:
        for path in output.glob("*.json"):
            path.unlink()
        output.rmdir()
        raise


# --- Sanitized client-evidence attachment ---------------------------------

_CREDENTIAL_MARKERS = (
    "token",
    "cookie",
    "session",
    "authorization",
    "password",
    "secret",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
)
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


def _attachment_error(code: str, detail: str = "") -> ViralResearchCardError:
    return ViralResearchCardError(f"{code}:{detail}" if detail else code)


def _scan_attachment_value(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).lower().replace("-", "_")
            if any(marker in key_text for marker in _CREDENTIAL_MARKERS):
                raise _attachment_error("credential_marker", f"{path}.{key}")
            _scan_attachment_value(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_attachment_value(child, f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if any(
            marker in lowered
            for marker in ("bearer ", "cookie=", "set-cookie:", "session=")
        ):
            raise _attachment_error("credential_marker", path)


def _attachment_timestamp(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _attachment_error(code)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _attachment_error(code) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(hours=8):
        raise _attachment_error(code)
    return value.strip()


def _attachment_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _attachment_error(code)
    return value.strip()


def _load_attachment(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _attachment_error("evidence_unreadable") from exc
    if not isinstance(value, dict):
        raise _attachment_error("evidence_object_required")
    return value


def _case_contract_payload(
    sample: Mapping[str, Any], evidence: Mapping[str, Any]
) -> dict[str, Any]:
    shape = sample.get("shape")
    subject_category = "unspecified"
    if isinstance(shape, Mapping):
        subject_category = str(shape.get("content_domain") or "unspecified")
    return {
        "sample_id": sample["sample_id"],
        "evidence_domain": "competitive_research_evidence",
        "evidence_origin": "client",
        "account_id": sample["account_id"],
        "subject_category": subject_category,
        "snapshot_ref": sample["clean_ref"],
        "performance_evidence_ref": evidence["evidence_ref"],
        "metric_plan_version": evidence["metric_plan_version"],
        "metric_plan_frozen_at": evidence["metric_plan_frozen_at"],
        "metric_plan": evidence["metric_plan"],
        "metrics": evidence["metrics"],
        "threshold_or_rank_rule": evidence["threshold_or_rank_rule"],
        "qualification_reason": "Sanitized client evidence was attached and assessed by the existing case contract.",
        "client_evidence": {
            "evidence_ref": evidence["evidence_ref"],
            "original_display": evidence["original_display"],
            "observed_at": evidence["observed_at"],
            "confirmer": evidence["confirmer"],
            "sha256": evidence["sha256"],
            "sanitized": True,
        },
    }


def _validate_attachment(
    evidence: Mapping[str, Any], *, run_root: Path
) -> tuple[dict[str, Any], str]:
    if "qualification_status" in evidence:
        raise _attachment_error("qualification_status_forbidden")
    _scan_attachment_value(evidence)
    required = (
        "evidence_domain",
        "evidence_ref",
        "original_display",
        "observed_at",
        "confirmer",
        "sha256",
        "sanitized",
        "metric_plan_version",
        "metric_plan_frozen_at",
        "metric_plan",
        "threshold_or_rank_rule",
        "metrics",
    )
    for field in required:
        if field not in evidence:
            code = {
                "confirmer": "client_evidence_confirmer_missing",
                "observed_at": "client_evidence_observed_at_missing",
                "sha256": "client_evidence_sha256_missing",
            }.get(field, f"client_evidence_{field}_missing")
            raise _attachment_error(code)
    if evidence["evidence_domain"] != "competitive_research_evidence":
        raise _attachment_error("evidence_domain_invalid")
    if evidence["sanitized"] is not True:
        raise _attachment_error("client_evidence_not_sanitized")
    _attachment_text(evidence["original_display"], "client_evidence_original_display_missing")
    _attachment_timestamp(evidence["observed_at"], "client_evidence_observed_at_missing")
    _attachment_text(evidence["confirmer"], "client_evidence_confirmer_missing")
    digest = evidence["sha256"]
    if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
        raise _attachment_error("client_evidence_sha256_missing")
    _attachment_timestamp(evidence["metric_plan_frozen_at"], "client_metric_plan_not_prefrozen")
    if not isinstance(evidence["metric_plan"], list) or not evidence["metric_plan"]:
        raise _attachment_error("client_metric_plan_missing")
    if not isinstance(evidence["metrics"], list) or not evidence["metrics"]:
        raise _attachment_error("client_metrics_missing")
    if not isinstance(evidence["threshold_or_rank_rule"], Mapping):
        raise _attachment_error("client_rule_missing")
    try:
        evidence_path, evidence_digest = validate_local_ref(
            str(evidence["evidence_ref"]), root=run_root
        )
    except ViralResearchContractError as exc:
        raise _attachment_error(str(exc).split(":", 1)[0], "evidence_ref") from exc
    if evidence_digest != digest.lower():
        raise _attachment_error("client_evidence_sha256_mismatch")
    return dict(evidence), evidence_path.relative_to(run_root).as_posix()


def attach_client_evidence(
    *,
    package_root: str | Path,
    sample_id: str,
    evidence_file: str | Path,
    output_revision: str | Path,
) -> dict[str, Any]:
    """Write a new sanitized evidence revision without mutating the package."""
    package = Path(package_root).expanduser().resolve()
    revision = Path(output_revision).expanduser().resolve()
    if revision.exists():
        raise _attachment_error("artifact_exists")
    try:
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _attachment_error("package_incomplete") from exc
    if not isinstance(manifest, Mapping):
        raise _attachment_error("package_incomplete")
    run_root = package.parent.parent
    evidence_path = Path(evidence_file).expanduser().resolve(strict=False)
    if run_root not in evidence_path.parents or not evidence_path.is_file():
        raise _attachment_error("path_escape", "evidence_file")
    samples = manifest.get("samples")
    if not isinstance(samples, list):
        raise _attachment_error("package_incomplete")
    sample = next(
        (item for item in samples if isinstance(item, Mapping) and item.get("sample_id") == sample_id),
        None,
    )
    if sample is None:
        raise _attachment_error("sample_not_found", sample_id)
    evidence = _load_attachment(evidence_path)
    normalized_evidence, evidence_relative = _validate_attachment(
        evidence, run_root=run_root
    )
    try:
        status = assess_qualification(_case_contract_payload(sample, normalized_evidence))
    except CaseContractError as exc:
        raise _attachment_error("case_contract_failed", str(exc)) from exc
    manifest_path = package / "manifest.json"
    base_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    revision.mkdir(parents=True)
    try:
        (revision / "evidence.json").write_text(
            json.dumps(normalized_evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        revision_record = {
            "schema_version": "viral-research-card-revision-v1",
            "revision_id": revision.name,
            "sample_id": sample_id,
            "evidence_ref": evidence_relative,
            "base_package_manifest_sha256": base_digest,
            "previous_qualification_status": sample.get("qualification_status"),
            "derived_qualification_status": status,
            "case_contract_status": status,
            "automatic_publication_authority": False,
            "promotion_status": "provisional_only",
        }
        (revision / "revision.json").write_text(
            json.dumps(revision_record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        attached_card = dict(sample)
        attached_card["client_evidence"] = normalized_evidence
        attached_card["derived_qualification_status"] = status
        attached_card["automatic_publication_authority"] = False
        (revision / "card.json").write_text(
            json.dumps(attached_card, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except Exception:
        for child in revision.iterdir():
            if child.is_file():
                child.unlink()
        revision.rmdir()
        raise
    return revision_record
