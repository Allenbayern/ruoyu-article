from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from article_group.case_contract import CaseContractError, validate_case_card
from article_group.viral_research_evidence import (
    ViralResearchEvidenceError,
    scan_evidence_file,
)
from article_group.viral_research_contract import (
    ViralResearchContractError,
    _platform_matches_case_contract,
    evidence_cluster_id,
    normalize_sample_id,
    validate_local_ref,
    validate_package_manifest,
)

PACKAGE_MANIFEST_NAME = "manifest.json"
SAMPLES_NAME = "samples.jsonl"
EXCLUSIONS_NAME = "exclusions.jsonl"
INTEGRITY_NAME = "integrity.json"
_FILM_DOMAINS = frozenset({"film", "film_tv", "film_and_tv", "cinema", "television"})


class ViralResearchPackageError(ViralResearchContractError):
    """Raised when a capture manifest cannot become an immutable package."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}:{detail}" if detail else code)


def _error(code: str, detail: str = "") -> ViralResearchPackageError:
    return ViralResearchPackageError(code, detail)


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _error("input_unavailable", path.name) from exc
    if not isinstance(value, dict):
        raise _error("input_shape_invalid", path.name)
    return value


def _text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(code)
    return value.strip()


def _resolve_capture_ref(reference: Any, *, root: Path, field: str) -> str:
    if not isinstance(reference, str) or not reference.strip():
        raise _error("capture_ref_missing", field)
    reference = reference.strip()
    if "#sha256=" in reference:
        try:
            path, digest = validate_local_ref(reference, root=root)
        except ViralResearchContractError as exc:
            raise _error(str(exc).split(":", 1)[0], field) from exc
        relative = path.relative_to(root).as_posix()
        return f"{relative}#sha256={digest}"
    if "\\" in reference:
        raise _error("path_escape", field)
    relative = Path(reference)
    if relative.is_absolute() or ".." in relative.parts:
        raise _error("path_escape", field)
    path = (root / relative).resolve(strict=False)
    if root not in path.parents or not path.is_file():
        raise _error("capture_ref_missing", field)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"{path.relative_to(root).as_posix()}#sha256={digest}"


def _capture_status(value: Any) -> str:
    if value in {"full", "complete"}:
        return "complete"
    if value in {"partial", "discovery_only", "missing"}:
        return "partial"
    if value == "blocked":
        return "blocked"
    return "partial"


def _lane(sample: Mapping[str, Any]) -> str:
    raw = sample.get("source_lane") or sample.get("platform") or "unknown"
    lane = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    if lane in {"wechat", "wechat_long_form", "wechat_qualified"}:
        return "wechat_qualified"
    if lane in {"newrank", "hotboard", "newrank_discovery"}:
        return "newrank_discovery"
    if lane in {"bilibili", "bilibili_long_form"}:
        return "bilibili_observation"
    if lane in {"toutiao", "toutiao_long_form"}:
        return "toutiao_observation"
    return lane or "unknown"


def _shape(sample: Mapping[str, Any]) -> dict[str, Any]:
    value = sample.get("shape", {})
    if not isinstance(value, dict):
        raise _error("shape_invalid")
    return dict(value)


def _is_film(sample: Mapping[str, Any], shape: Mapping[str, Any]) -> bool:
    domain = sample.get("content_domain", shape.get("content_domain"))
    if domain is None:
        return True
    return str(domain).strip().lower() in _FILM_DOMAINS


def _sample_identity(sample: Mapping[str, Any]) -> str:
    return normalize_sample_id(
        platform=_text(sample.get("platform"), "platform_missing"),
        account_id=_text(sample.get("account_id"), "account_id_missing"),
        canonical_url=_text(sample.get("canonical_url"), "canonical_url_missing"),
        published_at=_text(sample.get("published_at"), "published_at_missing"),
    )


def _revision_marker(sample: Mapping[str, Any]) -> str | None:
    for key in ("revision", "revision_id", "capture_revision"):
        value = sample.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _qualified_case_contract(
    sample: Mapping[str, Any],
    sample_id: str,
    refs: Mapping[str, str],
    *,
    root: Path,
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Validate and bind capture qualification evidence to one normalized sample.

    ``warnings`` 是可选收集器：卡片"格式合法但语义为空"（如占位符凭证）时，
    资格会被降级——降级原因必须随 sample 落盘，不能无声无息。
    """
    card = sample.get("case_contract_card")
    if not isinstance(card, Mapping):
        return None
    if card.get("sample_id") != sample_id or card.get("account_id") != sample.get("account_id"):
        return None
    for field, expected_field in (
        ("snapshot_ref", "clean_ref"),
        ("performance_evidence_ref", "metadata_ref"),
    ):
        try:
            normalized = _resolve_capture_ref(
                card.get(field), root=root, field=f"case_contract_{field}"
            )
        except ViralResearchPackageError:
            return None
        if normalized != refs[expected_field]:
            return None
    if not _platform_matches_case_contract(sample.get("platform"), card):
        return None
    try:
        if validate_case_card(dict(card), warnings=warnings) != "qualified_viral":
            return None
    except CaseContractError:
        return None
    client_evidence = card.get("client_evidence")
    if not isinstance(client_evidence, Mapping):
        return None
    try:
        evidence_path, evidence_digest = validate_local_ref(
            str(client_evidence.get("evidence_ref")), root=root
        )
    except ViralResearchContractError:
        return None
    if client_evidence.get("sha256") != evidence_digest:
        return None
    try:
        scan_evidence_file(evidence_path, expected_digest=evidence_digest)
    except ViralResearchEvidenceError:
        return None
    metrics = card.get("metrics")
    if not isinstance(metrics, list):
        return None
    bound_metrics: list[dict[str, Any]] = []
    for metric in metrics:
        if not isinstance(metric, Mapping):
            return None
        try:
            metric_reference = _resolve_capture_ref(
                metric.get("evidence_ref"),
                root=root,
                field="case_contract_metric_evidence",
            )
        except ViralResearchPackageError:
            return None
        metric_path = (root / metric_reference.split("#sha256=", 1)[0]).resolve()
        metric_digest = hashlib.sha256(metric_path.read_bytes()).hexdigest()
        try:
            scan_evidence_file(metric_path, expected_digest=metric_digest)
        except ViralResearchEvidenceError:
            return None
        bound_metric = dict(metric)
        bound_metric["evidence_ref"] = (
            f"{metric_path.relative_to(root).as_posix()}#sha256={metric_digest}"
        )
        bound_metrics.append(bound_metric)
    bound = dict(card)
    bound["sample_id"] = sample_id
    bound["account_id"] = str(sample["account_id"]).strip()
    bound["snapshot_ref"] = refs["clean_ref"]
    bound["performance_evidence_ref"] = refs["metadata_ref"]
    bound_evidence = dict(client_evidence)
    bound_evidence["evidence_ref"] = (
        f"{evidence_path.relative_to(root).as_posix()}#sha256={evidence_digest}"
    )
    bound_evidence["sha256"] = evidence_digest
    bound["client_evidence"] = bound_evidence
    bound["metrics"] = bound_metrics
    return bound


def _jsonl(path: Path, rows: list[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_lanes(capture: Mapping[str, Any], samples: list[Mapping[str, Any]]) -> list[str]:
    supplied = capture.get("source_lanes")
    if isinstance(supplied, list) and all(isinstance(item, str) and item.strip() for item in supplied):
        return sorted({item.strip() for item in supplied})
    return sorted({_lane(sample) for sample in samples})


def build_package(
    capture_manifest: str | Path,
    *,
    run_root: str | Path,
    output_root: str | Path,
) -> dict[str, Any]:
    """Build one immutable package from an explicit local capture manifest."""
    root = Path(run_root).expanduser().resolve()
    capture_path = Path(capture_manifest).expanduser().resolve()
    if root not in capture_path.parents and capture_path != root:
        raise _error("path_escape", "capture_manifest")
    capture = _load_object(capture_path)
    output = Path(output_root).expanduser().resolve()
    if root not in output.parents:
        raise _error("path_escape", "output_root")
    if output.exists():
        raise _error("artifact_exists")
    raw_samples = capture.get("samples")
    if not isinstance(raw_samples, list):
        raise _error("capture_samples_missing")
    run_id = _text(capture.get("run_id"), "run_id_missing")
    created_at = _text(capture.get("created_at"), "created_at_missing")
    output.mkdir(parents=True)
    samples: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    errors: list[str] = []
    identities: dict[str, set[str]] = {}

    for index, raw in enumerate(raw_samples):
        if not isinstance(raw, Mapping):
            errors.append(f"sample_{index}:sample_invalid")
            continue
        try:
            sample_id = _sample_identity(raw)
            lane = _lane(raw)
            shape = _shape(raw)
        except ViralResearchContractError as exc:
            exclusions.append({"source_index": index, "exclusion_reason": str(exc)})
            errors.append(f"sample_{index}:{str(exc).split(':', 1)[0]}")
            continue
        marker = _revision_marker(raw)
        marker_key = "<none>" if marker is None else marker
        if sample_id in identities and marker is None:
            exclusions.append({"sample_id": sample_id, "exclusion_reason": "duplicate_sample_identity"})
            errors.append(f"{sample_id}:duplicate_sample_identity")
            continue
        if marker_key in identities.setdefault(sample_id, set()):
            exclusions.append({"sample_id": sample_id, "exclusion_reason": "duplicate_sample_identity"})
            errors.append(f"{sample_id}:duplicate_sample_identity")
            continue
        identities[sample_id].add(marker_key)
        if not _is_film(raw, shape):
            exclusions.append(
                {
                    "sample_id": sample_id,
                    "title": str(raw.get("title") or ""),
                    "exclusion_reason": "non_film_content",
                }
            )
            continue
        capture_status = _capture_status(raw.get("capture_status"))
        fields = ("raw_ref", "clean_ref", "metadata_ref")
        missing = [field for field in fields if not isinstance(raw.get(field), str) or not raw[field].strip()]
        if missing and (lane == "newrank_discovery" or capture_status == "partial"):
            exclusions.append(
                {
                    "sample_id": sample_id,
                    "title": str(raw.get("title") or ""),
                    "exclusion_reason": "full_text_capture_missing",
                    "missing_fields": missing,
                }
            )
            continue
        if missing:
            errors.append(f"{sample_id}:capture_ref_missing:{missing[0]}")
            exclusions.append(
                {"sample_id": sample_id, "exclusion_reason": "capture_ref_missing", "missing_fields": missing}
            )
            continue
        try:
            refs = {
                field: _resolve_capture_ref(raw[field], root=root, field=field)
                for field in fields
            }
        except ViralResearchPackageError as exc:
            errors.append(f"{sample_id}:{exc.code}")
            exclusions.append({"sample_id": sample_id, "exclusion_reason": exc.code})
            continue
        qualification = raw.get("qualification_status")
        if qualification not in {"qualified_viral", "observed_pending", "research_only", "blocked"}:
            qualification = "research_only"
        qualification_evidence: dict[str, Any] | None = None
        case_warnings: list[dict[str, Any]] = []
        if qualification == "qualified_viral":
            qualification_evidence = _qualified_case_contract(
                raw, sample_id, refs, root=root, warnings=case_warnings
            )
            if qualification_evidence is None:
                qualification = "observed_pending" if capture_status == "complete" else "research_only"
        platform_lane = _lane({"platform": raw.get("platform")})
        if (
            qualification == "qualified_viral"
            and (lane != "wechat_qualified" or platform_lane != "wechat_qualified")
        ):
            qualification = "observed_pending"
        if capture_status != "complete" and qualification == "qualified_viral":
            qualification = "research_only"
        normalized: dict[str, Any] = {
            "sample_id": sample_id,
            "platform": _text(raw.get("platform"), "platform_missing"),
            "account_id": _text(raw.get("account_id"), "account_id_missing"),
            "title": _text(raw.get("title"), "title_missing"),
            "canonical_url": _text(raw.get("canonical_url"), "canonical_url_missing"),
            "published_at": _text(raw.get("published_at"), "published_at_missing"),
            "capture_status": capture_status,
            **refs,
            "evidence_cluster": evidence_cluster_id(refs),
            "shape": shape,
            "qualification_status": qualification,
        }
        if qualification == "qualified_viral" and qualification_evidence is not None:
            normalized["qualification_evidence"] = qualification_evidence
        if case_warnings:
            normalized["warnings"] = case_warnings
        for key in ("revision", "revision_id", "capture_revision"):
            if key in raw and raw[key] not in (None, ""):
                normalized[key] = raw[key]
                break
        samples.append(normalized)

    status = "blocked" if errors else "research_only"
    manifest: dict[str, Any] = {
        "schema_version": "viral-research-package-v1",
        "run_id": run_id,
        "status": status,
        "created_at": created_at,
        "source_lanes": _source_lanes(capture, raw_samples),
        "samples": samples,
        "exclusions_ref": "",
        "errors": sorted(errors),
    }
    _jsonl(output / SAMPLES_NAME, samples)
    _jsonl(output / EXCLUSIONS_NAME, exclusions)
    output_relative = output.relative_to(root).as_posix()
    exclusions_digest = _sha256_file(output / EXCLUSIONS_NAME)
    manifest["exclusions_ref"] = (
        f"{output_relative}/{EXCLUSIONS_NAME}#sha256={exclusions_digest}"
    )
    if not errors:
        try:
            status = validate_package_manifest(manifest, root=root)
        except ViralResearchContractError as exc:
            manifest["status"] = "blocked"
            manifest["errors"] = [str(exc).split(":", 1)[0]]
            status = "blocked"
        else:
            manifest["status"] = status
    (output / PACKAGE_MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    integrity = {
        "schema_version": "viral-research-package-integrity-v1",
        "manifest_sha256": _sha256_file(output / PACKAGE_MANIFEST_NAME),
        "samples_sha256": _sha256_file(output / SAMPLES_NAME),
        "exclusions_sha256": _sha256_file(output / EXCLUSIONS_NAME),
    }
    (output / INTEGRITY_NAME).write_text(
        json.dumps(integrity, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def validate_package_root(package_root: str | Path) -> dict[str, Any]:
    """Read and validate an existing immutable package root."""
    package = Path(package_root).expanduser().resolve()
    if not package.is_dir():
        raise _error("package_incomplete")
    manifest_path = package / PACKAGE_MANIFEST_NAME
    samples_path = package / SAMPLES_NAME
    exclusions_path = package / EXCLUSIONS_NAME
    integrity_path = package / INTEGRITY_NAME
    if not all(path.is_file() for path in (manifest_path, samples_path, exclusions_path, integrity_path)):
        raise _error("package_incomplete")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _error("package_incomplete") from exc
    if not isinstance(manifest, dict):
        raise _error("package_incomplete")
    try:
        integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _error("package_integrity_missing") from exc
    if not isinstance(integrity, dict) or integrity.get("schema_version") != "viral-research-package-integrity-v1":
        raise _error("package_integrity_invalid")
    expected_digests = {
        "manifest_sha256": _sha256_file(manifest_path),
        "samples_sha256": _sha256_file(samples_path),
        "exclusions_sha256": _sha256_file(exclusions_path),
    }
    if any(integrity.get(field) != digest for field, digest in expected_digests.items()):
        raise _error("package_integrity_mismatch")
    run_root = package.parent.parent
    try:
        status = validate_package_manifest(manifest, root=run_root)
    except ViralResearchContractError as exc:
        raise _error("contract_failed", str(exc).split(":", 1)[0]) from exc
    if manifest.get("status") != status:
        raise _error("package_status_mismatch")
    try:
        exclusions_target, _ = validate_local_ref(
            manifest["exclusions_ref"], root=run_root
        )
    except ViralResearchContractError as exc:
        raise _error("contract_failed", "exclusions_ref_invalid") from exc
    if exclusions_target != exclusions_path.resolve():
        raise _error("exclusions_ref_mismatch")
    if status == "blocked":
        # A capture that produced no usable sample keeps the CLI's historical
        # incomplete-package code; a blocked package with rows must stop
        # downstream preparation with the explicit blocked code.
        if not manifest.get("samples") and manifest.get("errors"):
            raise _error("package_incomplete")
        raise _error("package_blocked")
    try:
        sample_rows = [
            json.loads(line)
            for line in samples_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        exclusion_rows = [
            json.loads(line)
            for line in exclusions_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise _error("package_incomplete") from exc
    if sample_rows != manifest.get("samples") or not all(isinstance(row, dict) for row in exclusion_rows):
        raise _error("package_incomplete")
    return manifest
