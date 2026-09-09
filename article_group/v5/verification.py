"""Offline V5 orchestration, validation, safe writes, and read-back."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from .contracts import (
    PUBLICATION_AUTHORIZATION,
    new_artifact_envelope,
    validate_v5_artifact_envelope,
)
from .dna import extract_article_dna, validate_article_dna
from .experiment import (
    assess_experiment,
    build_experiment_record,
    validate_experiment_record,
)
from .failure import build_failure_artifact, validate_failure_artifact
from .lifecycle import (
    advance_content_lifecycle,
    build_content_lifecycle,
    validate_lifecycle_record,
)
from .quota import derive_dynamic_quotas, validate_quota_plan
from .resources import plan_resource_allocation, validate_resource_plan
from .strategy import (
    advance_strategy_state,
    build_strategy_library,
    build_strategy_record,
    validate_strategy_library,
)


ARTIFACT_FILES = (
    "experiment-record.json",
    "content-lifecycle.json",
    "article-dna.json",
    "failure-samples.json",
    "dynamic-quotas.json",
    "strategy-library.json",
    "resource-plan.json",
    "v5-verification.json",
)
_ARTIFACT_SCHEMAS = {
    "experiment-record.json": "v5-experiment-record-v1",
    "content-lifecycle.json": "v5-content-lifecycle-v1",
    "article-dna.json": "v5-article-dna-v1",
    "failure-samples.json": "v5-failure-samples-v1",
    "dynamic-quotas.json": "v5-dynamic-quotas-v1",
    "strategy-library.json": "v5-strategy-library-v1",
    "resource-plan.json": "v5-resource-plan-v1",
    "v5-verification.json": "v5-verification-v1",
}
_INPUT_FILES = (
    "batch.json",
    "experiment.json",
    "observations.json",
    "article-records.json",
    "metric-events.json",
    "quota-history.json",
    "strategy-input.json",
    "strategy-evidence.json",
    "resource-candidates.json",
    "resource-budget.json",
    "source-audit.json",
    "draft.md",
)


class VerificationError(RuntimeError):
    """A safe, user-facing offline verification failure."""


@dataclass(frozen=True)
class _Fixture:
    run_dir: Path
    batch: Mapping[str, Any]
    input_hashes: Mapping[str, str]

    @property
    def run_id(self) -> str:
        value = self.batch.get("run_id")
        if not isinstance(value, str) or not value.strip():
            raise VerificationError("invalid_batch:run_id")
        return value

    @property
    def generated_at(self) -> str:
        value = self.batch.get("generated_at")
        if not isinstance(value, str) or not value.strip():
            raise VerificationError("invalid_batch:generated_at")
        return value


def _canonical_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise VerificationError(f"non_json_value:{exc}") from exc
    return (encoded + "\n").encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _safe_path(run_dir: Path, relative: str) -> Path:
    root = run_dir.resolve()
    if Path(relative).is_absolute():
        raise VerificationError(f"input_path_must_be_relative:{relative}")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise VerificationError(f"input_outside_run_dir:{relative}") from exc
    if candidate.suffix.lower() not in {".json", ".md"}:
        raise VerificationError(f"unsupported_input_type:{relative}")
    if not candidate.is_file():
        raise VerificationError(f"missing_input:{relative}")
    return candidate


def _read_json(run_dir: Path, name: str) -> Any:
    path = _safe_path(run_dir, name)
    if path.suffix.lower() != ".json":
        raise VerificationError(f"expected_json:{name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"invalid_json:{name}") from exc


def _read_text(run_dir: Path, name: str) -> str:
    path = _safe_path(run_dir, name)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise VerificationError(f"invalid_text:{name}") from exc


def _file_hash(run_dir: Path, name: str) -> str:
    return _digest_bytes(_safe_path(run_dir, name).read_bytes())


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VerificationError(f"invalid_input_shape:{name}")
    return value


def _list_of_mappings(value: object, name: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise VerificationError(f"invalid_input_shape:{name}")
    return list(value)


def _fixture(run_dir: Path) -> _Fixture:
    root = run_dir.resolve()
    if not root.is_dir():
        raise VerificationError("invalid_run_dir")
    batch = _mapping(_read_json(root, "batch.json"), "batch.json")
    hashes = {name: _file_hash(root, name) for name in _INPUT_FILES}
    return _Fixture(root, batch, hashes)


def _attach_inputs(artifact: dict[str, Any], fixture: _Fixture, names: Sequence[str]) -> dict[str, Any]:
    result = deepcopy(artifact)
    existing = result.get("input_hashes")
    hashes = dict(existing) if isinstance(existing, Mapping) else {}
    hashes.update({name: fixture.input_hashes[name] for name in names})
    result["input_hashes"] = hashes
    payload = result.get("payload")
    if isinstance(payload, dict):
        payload.setdefault("synthetic_fixture", True)
    return result


def _build_artifacts(fixture: _Fixture) -> dict[str, dict[str, Any]]:
    run_dir = fixture.run_dir
    batch = fixture.batch
    run_id = fixture.run_id
    generated_at = fixture.generated_at
    topic_id = _text(batch.get("topic_id"))
    article_id = _text(batch.get("article_id"))
    if not topic_id or not article_id:
        raise VerificationError("invalid_batch:topic_or_article_id")

    experiment_input = dict(_mapping(_read_json(run_dir, "experiment.json"), "experiment.json"))
    experiment_input.setdefault("run_id", run_id)
    experiment_input.setdefault("generated_at", generated_at)
    experiment = build_experiment_record(**experiment_input)
    observations = _list_of_mappings(_read_json(run_dir, "observations.json"), "observations.json")
    assessment = assess_experiment(experiment, observations, controller_decision="approve_causal_support")
    experiment["payload"]["assessment"] = assessment
    experiment = _attach_inputs(experiment, fixture, ("batch.json", "experiment.json", "observations.json"))

    metric_events = _list_of_mappings(_read_json(run_dir, "metric-events.json"), "metric-events.json")
    publication_events = [event for event in metric_events if event.get("event_type") == "published"]
    observation_events = [event for event in metric_events if event.get("event_type") != "published"]
    lifecycle = build_content_lifecycle(
        article_id=article_id,
        run_id=run_id,
        generated_at=generated_at,
    )
    lifecycle = advance_content_lifecycle(lifecycle, publication_events)
    lifecycle = advance_content_lifecycle(lifecycle, observation_events)
    lifecycle = _attach_inputs(lifecycle, fixture, ("batch.json", "metric-events.json"))

    articles = _list_of_mappings(_read_json(run_dir, "article-records.json"), "article-records.json")
    article = next((item for item in articles if item.get("article_id") == article_id), None)
    if article is None:
        raise VerificationError("missing_article_record")
    draft = _read_text(run_dir, "draft.md")
    metric_event = next(
        (event for event in metric_events if event.get("article_id") == article_id and event.get("event_type") != "published"),
        None,
    )
    dna = extract_article_dna(
        article,
        draft_text=draft,
        metric_event=metric_event,
        run_id=run_id,
        generated_at=generated_at,
    )
    dna = _attach_inputs(dna, fixture, ("batch.json", "article-records.json", "metric-events.json", "draft.md"))

    failure_events = [event for event in metric_events if event.get("event_type") != "published"]
    failures = build_failure_artifact(failure_events, run_id=run_id, generated_at=generated_at)
    failures = _attach_inputs(failures, fixture, ("batch.json", "metric-events.json"))

    history = _list_of_mappings(_read_json(run_dir, "quota-history.json"), "quota-history.json")
    base_quotas = _mapping(batch.get("base_quotas"), "batch.base_quotas")
    quotas = derive_dynamic_quotas(
        history,
        base_quotas,
        run_id=run_id,
        generated_at=generated_at,
    )
    quotas = _attach_inputs(quotas, fixture, ("batch.json", "quota-history.json"))

    strategy_input = dict(_mapping(_read_json(run_dir, "strategy-input.json"), "strategy-input.json"))
    strategy_decision = strategy_input.pop("controller_decision", None)
    strategy_input.setdefault("run_id", run_id)
    strategy_input.setdefault("generated_at", generated_at)
    strategy = build_strategy_record(**strategy_input)
    strategy_evidence = _list_of_mappings(_read_json(run_dir, "strategy-evidence.json"), "strategy-evidence.json")
    strategy = advance_strategy_state(
        strategy,
        strategy_evidence,
        controller_decision=strategy_decision,
    )
    library = build_strategy_library([strategy], run_id=run_id, generated_at=generated_at)
    library = _attach_inputs(library, fixture, ("batch.json", "strategy-input.json", "strategy-evidence.json"))

    candidates = _list_of_mappings(_read_json(run_dir, "resource-candidates.json"), "resource-candidates.json")
    budget_input = _mapping(_read_json(run_dir, "resource-budget.json"), "resource-budget.json")
    budget = budget_input.get("budget")
    if not isinstance(budget, (int, float)) or isinstance(budget, bool):
        raise VerificationError("invalid_resource_budget")
    resources = plan_resource_allocation(
        candidates,
        budget=float(budget),
        run_id=run_id,
        generated_at=generated_at,
    )
    resources = _attach_inputs(resources, fixture, ("batch.json", "resource-candidates.json", "resource-budget.json"))

    return {
        "experiment-record.json": experiment,
        "content-lifecycle.json": lifecycle,
        "article-dna.json": dna,
        "failure-samples.json": failures,
        "dynamic-quotas.json": quotas,
        "strategy-library.json": library,
        "resource-plan.json": resources,
    }


def validate_v5_artifact(
    name: str,
    artifact: Mapping[str, Any],
    run_dir: Path,
) -> list[str]:
    """Validate one named V5 artifact and its envelope."""

    if name not in _ARTIFACT_SCHEMAS:
        return [f"unknown_artifact:{name}"]
    run_id = artifact.get("run_id") if isinstance(artifact.get("run_id"), str) else ""
    errors = validate_v5_artifact_envelope(
        artifact,
        _ARTIFACT_SCHEMAS[name],
        run_id=run_id,
    )
    if name == "experiment-record.json":
        errors.extend(validate_experiment_record(artifact))
    elif name == "content-lifecycle.json":
        errors.extend(validate_lifecycle_record(artifact))
    elif name == "article-dna.json":
        errors.extend(validate_article_dna(artifact))
    elif name == "failure-samples.json":
        errors.extend(validate_failure_artifact(artifact))
    elif name == "dynamic-quotas.json":
        errors.extend(validate_quota_plan(artifact))
    elif name == "strategy-library.json":
        errors.extend(validate_strategy_library(artifact))
    elif name == "resource-plan.json":
        errors.extend(validate_resource_plan(artifact))
    else:
        payload = artifact.get("payload") if isinstance(artifact, Mapping) else None
        if not isinstance(payload, Mapping):
            errors.append("invalid:verification_payload")
        elif payload.get("publication_authorization") != PUBLICATION_AUTHORIZATION:
            errors.append("publication_authorization_must_be_not_authorized")
    return list(dict.fromkeys(errors))


def _destination(output_path: Path, name: str) -> Path:
    return output_path if output_path.suffix.lower() == ".json" else output_path / name


def _preflight_writes(items: Mapping[Path, Mapping[str, Any]]) -> None:
    for path, artifact in items.items():
        if not path.exists():
            continue
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise VerificationError(f"refuse_overwrite:{path}") from exc
        if existing != artifact:
            raise VerificationError(f"refuse_overwrite:{path}")


def write_v5_artifact(
    name: str,
    artifact: Mapping[str, Any],
    *,
    output_path: Path,
) -> Path:
    """Write one JSON artifact, accepting an identical existing file only."""

    if name not in _ARTIFACT_SCHEMAS:
        raise VerificationError(f"unknown_artifact:{name}")
    if output_path.suffix.lower() != ".json":
        raise VerificationError("output_must_be_json")
    errors = validate_v5_artifact(name, artifact, Path("."))
    if errors:
        raise VerificationError("artifact_invalid:" + ";".join(errors))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _preflight_writes({output_path: artifact})
    try:
        output_path.write_bytes(_canonical_bytes(artifact))
    except OSError as exc:
        raise VerificationError(f"write_failed:{output_path}") from exc
    return output_path


def _source_summary(source_audit: Mapping[str, Any]) -> tuple[list[str], list[str], list[str]]:
    missing: list[str] = []
    roles = source_audit.get("source_roles")
    if isinstance(roles, Mapping):
        for role, detail in roles.items():
            if isinstance(detail, Mapping) and detail.get("status") in {"missing", "unavailable"}:
                missing.append(str(role))
    explicit_missing = source_audit.get("missing_source_roles")
    if isinstance(explicit_missing, list):
        missing.extend(item for item in explicit_missing if isinstance(item, str))
    retry: list[str] = []
    if source_audit.get("retry_required") is True:
        retry.append("source_audit_retry_required")
    for key in ("retry_requirements", "failed_sources"):
        values = source_audit.get(key)
        if isinstance(values, list):
            retry.extend(
                item if isinstance(item, str) else str(item)
                for item in values
                if item
            )
    manual: list[str] = []
    values = source_audit.get("manual_escalations")
    if isinstance(values, list):
        manual.extend(item for item in values if isinstance(item, str))
    return sorted(set(missing)), sorted(set(retry)), sorted(set(manual))


def _verification_report(
    fixture: _Fixture,
    artifacts: Mapping[str, Mapping[str, Any]],
    module_checks: Mapping[str, Mapping[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    source_audit = _mapping(_read_json(fixture.run_dir, "source-audit.json"), "source-audit.json")
    missing, retry, manual = _source_summary(source_audit)
    manual = sorted(set([*manual, "controller_review_required_before_apply_or_publish"]))
    blocked = bool(missing or retry or any(check["errors"] for check in module_checks.values()))
    output_hashes = {
        name: _digest_bytes(_canonical_bytes(artifact))
        for name, artifact in artifacts.items()
    }
    output_hashes["v5-verification.json"] = ""
    checks = {
        name: {
            "status": "PASS" if not details["errors"] else "BLOCKED",
            "errors": list(details["errors"]),
            "sha256": output_hashes.get(name),
            "read_back": True,
        }
        for name, details in module_checks.items()
    }
    payload = {
        "status": "BLOCKED" if blocked else "PASS",
        "decision": "hold_for_gap_recovery" if blocked else "eligible_for_article_group_review",
        "module_checks": checks,
        "missing_source_roles": missing,
        "retry_requirements": retry,
        "manual_escalations": manual,
        "content_status": "CONTENT_BLOCKED" if blocked else "CONTENT_READY",
        "output_hashes": output_hashes,
        "hash_basis": {
            "v5-verification.json": "canonical_envelope_with_self_hash_blank"
        },
        "read_back": True,
        "output_files": list(ARTIFACT_FILES),
        "synthetic_fixture": True,
        "controller_only": True,
        "auto_apply": False,
        "publication_authorization": PUBLICATION_AUTHORIZATION,
    }
    report = new_artifact_envelope(
        _ARTIFACT_SCHEMAS["v5-verification.json"],
        fixture.run_id,
        payload,
        generated_at=fixture.generated_at,
    )
    basis = deepcopy(report)
    basis["payload"]["output_hashes"]["v5-verification.json"] = ""
    report["payload"]["output_hashes"]["v5-verification.json"] = _digest_bytes(
        _canonical_bytes(basis)
    )
    return report


def run_v5_verification(run_dir: Path, *, output_path: Path) -> dict[str, Any]:
    """Build, validate, write, and read back all eight V5 artifacts."""

    fixture = _fixture(Path(run_dir))
    output = Path(output_path)
    output_dir = output.parent if output.suffix.lower() == ".json" else output
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = _build_artifacts(fixture)
    module_checks: dict[str, dict[str, Any]] = {}
    for name, artifact in artifacts.items():
        module_checks[name] = {"errors": validate_v5_artifact(name, artifact, fixture.run_dir)}
    report = _verification_report(fixture, artifacts, module_checks, output_dir)
    report_errors = validate_v5_artifact(
        "v5-verification.json", report, fixture.run_dir
    )
    if report_errors:
        raise VerificationError("artifact_invalid:" + ";".join(report_errors))
    all_artifacts = {**artifacts, "v5-verification.json": report}
    destinations_by_name: dict[str, Path] = {}
    for name in all_artifacts:
        if output.suffix.lower() == ".json" and name == "v5-verification.json":
            destinations_by_name[name] = output
        else:
            destinations_by_name[name] = output_dir / name
    destinations = {
        destinations_by_name[name]: artifact
        for name, artifact in all_artifacts.items()
    }
    _preflight_writes(destinations)
    for path, artifact in destinations.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_canonical_bytes(artifact))

    for name, artifact in all_artifacts.items():
        path = destinations_by_name[name]
        try:
            read_back = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise VerificationError(f"read_back_failed:{name}") from exc
        if read_back != artifact:
            raise VerificationError(f"read_back_mismatch:{name}")
    return report


__all__ = [
    "ARTIFACT_FILES",
    "VerificationError",
    "run_v5_verification",
    "validate_v5_artifact",
    "write_v5_artifact",
]
