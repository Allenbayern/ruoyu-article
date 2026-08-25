from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Iterable

from article_group.case_contract import CaseContractError, validate_case_card
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
