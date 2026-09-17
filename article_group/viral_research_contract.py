from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

from article_group.case_contract import CaseContractError, validate_case_card

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover
    Draft202012Validator = None
    FormatChecker = None

PACKAGE_SCHEMA_VERSION = "viral-research-package-v1"
SAMPLE_STATES = frozenset(
    {
        "captured",
        "normalized",
        "evidence_checked",
        "qualified",
        "observed_pending",
        "research_only",
        "blocked",
        "selected",
        "distilled",
        "reviewed",
    }
)
_SHA256_RE = re.compile(r"^(?P<path>[^#]+)#sha256=(?P<digest>[0-9a-fA-F]{64})$")


class ViralResearchContractError(ValueError):
    """Raised when a research package cannot be safely accepted."""


def _error(code: str, detail: str = "") -> ViralResearchContractError:
    return ViralResearchContractError(f"{code}:{detail}" if detail else code)


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error("invalid_field", field)
    return value.strip()


def _canonical_url(value: str) -> str:
    url = _required_text(value, "canonical_url")
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise _error("invalid_canonical_url")
    try:
        port = parsed.port
    except ValueError as exc:
        raise _error("invalid_canonical_url") from exc
    host = parsed.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if parsed.username is not None or parsed.password is not None:
        raise _error("invalid_canonical_url")
    if port is not None and not (
        (parsed.scheme.lower() == "http" and port == 80)
        or (parsed.scheme.lower() == "https" and port == 443)
    ):
        netloc = f"{netloc}:{port}"
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, ""))


def normalize_sample_id(
    *, platform: str, account_id: str, canonical_url: str, published_at: str
) -> str:
    """Return a stable logical identity for one source article."""
    payload = [
        _required_text(platform, "platform").lower(),
        _required_text(account_id, "account_id"),
        _canonical_url(canonical_url),
        _required_text(published_at, "published_at"),
    ]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return "sample-" + hashlib.sha256(encoded).hexdigest()[:32]


def evidence_cluster_id(sample: Mapping[str, Any]) -> str:
    """Derive a conservative cluster key from the three captured evidence digests."""
    digests: list[str] = []
    for field in ("raw_ref", "clean_ref", "metadata_ref"):
        reference = sample.get(field)
        if not isinstance(reference, str):
            return ""
        match = _SHA256_RE.fullmatch(reference.strip())
        if match is None:
            return ""
        digests.append(match.group("digest").lower())
    payload = "|".join(digests).encode("ascii")
    return "cluster-" + hashlib.sha256(payload).hexdigest()[:32]


def validate_local_ref(reference: str, *, root: Path) -> tuple[Path, str]:
    """Resolve and hash-check an in-root relative snapshot reference."""
    if not isinstance(reference, str) or "\\0" in reference:
        raise _error("invalid_ref")
    match = _SHA256_RE.fullmatch(reference)
    if not match:
        if "#sha256=" in reference:
            raise _error("invalid_hash")
        raise _error("invalid_ref")
    relative = match.group("path")
    if "\\" in relative:
        raise _error("path_escape")
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise _error("path_escape")
    root_path = Path(root).resolve()
    candidate = (root_path / relative_path).resolve(strict=False)
    if candidate == root_path or root_path not in candidate.parents:
        raise _error("path_escape")
    if not candidate.exists() or not candidate.is_file():
        raise _error("missing_ref", relative)
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    declared = match.group("digest").lower()
    if digest != declared:
        raise _error("sha256_mismatch", relative)
    return candidate, digest


def _validate_timestamp(value: Any, field: str) -> None:
    if not isinstance(value, str):
        raise _error("invalid_timestamp", field)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _error("invalid_timestamp", field) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(hours=8):
        raise _error("timestamp_timezone", field)


def _revision_marker(sample: Mapping[str, Any]) -> Any:
    for key in ("revision", "revision_id", "capture_revision"):
        if key in sample and sample[key] not in (None, ""):
            return sample[key]
    return None


def _platform_matches_case_contract(
    platform: Any, card: Mapping[str, Any]
) -> bool:
    rule = card.get("threshold_or_rank_rule")
    if not isinstance(rule, Mapping):
        return False
    if not isinstance(platform, str) or not isinstance(rule.get("platform"), str):
        return False
    return platform.strip().casefold() == rule["platform"].strip().casefold()


def _validate_qualification_evidence(
    sample: Mapping[str, Any], index: int, *, root: Path
) -> None:
    if sample.get("qualification_status") != "qualified_viral":
        return
    evidence = sample.get("qualification_evidence")
    if not isinstance(evidence, Mapping):
        raise _error("qualification_evidence_missing", str(index))
    if evidence.get("sample_id") != sample.get("sample_id"):
        raise _error("qualification_evidence_sample_id_mismatch", str(index))
    if evidence.get("account_id") != sample.get("account_id"):
        raise _error("qualification_evidence_account_id_mismatch", str(index))
    if evidence.get("snapshot_ref") != sample.get("clean_ref"):
        raise _error("qualification_evidence_snapshot_ref_mismatch", str(index))
    if evidence.get("performance_evidence_ref") != sample.get("metadata_ref"):
        raise _error("qualification_evidence_performance_ref_mismatch", str(index))
    if not _platform_matches_case_contract(sample.get("platform"), evidence):
        raise _error("qualification_evidence_platform_mismatch", str(index))
    client_evidence = evidence.get("client_evidence")
    if not isinstance(client_evidence, Mapping):
        raise _error("qualification_evidence_client_evidence_missing", str(index))
    try:
        _, evidence_digest = validate_local_ref(
            str(client_evidence.get("evidence_ref")), root=root
        )
    except ViralResearchContractError as exc:
        raise _error("qualification_evidence_ref_invalid", f"{index}:{exc}") from exc
    if client_evidence.get("sha256") != evidence_digest:
        raise _error("qualification_evidence_sha256_mismatch", str(index))
    try:
        status = validate_case_card(dict(evidence))
    except CaseContractError as exc:
        raise _error("qualification_evidence_invalid", f"{index}:{exc}") from exc
    if status != "qualified_viral":
        raise _error("qualification_evidence_not_qualified", str(index))


def assess_sample_state(sample: Mapping[str, Any]) -> str:
    """Return the conservative evidence state for one sample."""
    qualification = sample.get("qualification_status")
    capture = sample.get("capture_status")
    if qualification == "blocked" or capture in {"missing", "blocked"}:
        return "blocked"
    if capture != "complete":
        return "research_only"
    if qualification in {"qualified", "qualified_viral"}:
        if all(isinstance(sample.get(key), str) and sample[key].strip() for key in ("raw_ref", "clean_ref", "metadata_ref")):
            return "qualified"
        return "research_only"
    if qualification == "observed_pending":
        return "observed_pending"
    if qualification == "research_only":
        return "research_only"
    return "research_only"


def _schema_validate(manifest: Mapping[str, Any]) -> None:
    if Draft202012Validator is None or FormatChecker is None:
        raise _error("schema_unavailable")
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "viral-research-package.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _error("schema_unavailable") from exc
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(manifest), key=lambda item: list(item.absolute_path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path)
        raise _error("schema_error", f"{location}:{first.message}")


def validate_package_manifest(manifest: Mapping[str, Any], *, root: Path) -> str:
    """Validate a package and return its highest safe, non-promoting state."""
    if not isinstance(manifest, Mapping):
        raise _error("schema_error", "manifest_not_object")
    _schema_validate(manifest)
    if manifest.get("schema_version") != PACKAGE_SCHEMA_VERSION:
        raise _error("schema_error", "schema_version")
    _validate_timestamp(manifest["created_at"], "created_at")
    try:
        validate_local_ref(manifest["exclusions_ref"], root=Path(root))
    except ViralResearchContractError as exc:
        raise _error("exclusions_ref_invalid", str(exc)) from exc
    samples = manifest["samples"]
    seen: dict[str, set[str]] = {}
    for index, sample in enumerate(samples):
        if not isinstance(sample, Mapping):
            raise _error("schema_error", f"samples.{index}")
        _validate_timestamp(sample["published_at"], f"samples.{index}.published_at")
        expected_id = normalize_sample_id(
            platform=sample["platform"],
            account_id=sample["account_id"],
            canonical_url=sample["canonical_url"],
            published_at=sample["published_at"],
        )
        if sample["sample_id"] != expected_id:
            raise _error("sample_id_mismatch", str(index))
        identity = expected_id
        marker = _revision_marker(sample)
        marker_key = "<none>" if marker is None else str(marker)
        if identity in seen and marker is None:
            raise _error("duplicate_sample_identity", identity)
        if marker_key in seen.setdefault(identity, set()):
            raise _error("duplicate_sample_identity", identity)
        seen[identity].add(marker_key)
        for field in ("raw_ref", "clean_ref", "metadata_ref"):
            validate_local_ref(sample[field], root=Path(root))
        expected_cluster = evidence_cluster_id(sample)
        if sample.get("evidence_cluster") != expected_cluster:
            raise _error("evidence_cluster_mismatch", str(index))
        _validate_qualification_evidence(sample, index, root=Path(root))
    if manifest.get("errors"):
        return "blocked"
    states = [assess_sample_state(sample) for sample in samples]
    if any(state == "blocked" for state in states):
        return "blocked"
    if states and all(state == "qualified" for state in states):
        return "evidence_checked"
    if any(state == "observed_pending" for state in states):
        return "observed_pending"
    return "research_only"
