"""Verify bound V4/V5 bundles against current inputs without changing them.

Existing lane verifiers run in a temporary output directory. Their complete
results must match the supplied bundles; saved PASS flags alone are insufficient.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .v4.verification import (
    ARTIFACT_FILES as V4_FILES,
    V4VerificationError,
    run_v4_verification,
    validate_v4_artifact,
    validate_v4_verification,
)
from .v5.verification import (
    ARTIFACT_FILES as V5_FILES,
    VerificationError,
    run_v5_verification,
    validate_v5_artifact,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(root: Path, name: str) -> tuple[dict[str, Any], str]:
    path = root / name
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError(f"unsafe_or_missing:{name}")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"invalid_object:{name}")
    return value, _sha(raw)


def _authority_errors(value: object) -> list[str]:
    errors = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "publication_authorization" and item != "not_authorized":
                errors.append("publication_authorization_must_be_not_authorized")
            if key in {"auto_apply", "auto_publish"} and item is not False:
                errors.append(f"forbidden:{key}")
            errors.extend(_authority_errors(item))
    elif isinstance(value, list):
        for item in value:
            errors.extend(_authority_errors(item))
    return errors


def _layer(
    name: str, output: Path | None, source: Path | None, binding: object,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "BLOCKED", "errors": [], "module_checks": {},
        "content_status": "CONTENT_BLOCKED", "read_back": False,
    }
    errors = result["errors"]
    if output is None:
        errors.append("missing:output_dir")
        return result
    if output.is_symlink() or not output.is_dir():
        errors.append("unsafe_or_missing:output_dir")
        return result
    root = output.resolve()
    report_name = f"{name}-verification.json"
    try:
        report, report_sha = _read(root, report_name)
        result.update(report_path=str(root / report_name), sha256=report_sha)
        if not isinstance(binding, Mapping):
            errors.append("missing:manifest_context_binding")
        else:
            if not binding.get("run_id") or report.get("run_id") != binding["run_id"]:
                errors.append("run_id_mismatch")
            if report_sha != binding.get("report_sha256"):
                errors.append("report_hash_mismatch")
        payload = report.get("payload")
        if not isinstance(payload, dict):
            errors.append("invalid:payload")
            return result
        # Preserve the original evidence, including non-blocking gaps and provenance.
        result["reported"] = payload
        for field in ("decision", "content_status", "synthetic_fixture"):
            result[field] = payload.get(field)
        for field in ("missing_source_roles", "retry_requirements", "manual_escalations"):
            result[field] = payload.get(field, [])
            if not isinstance(result[field], list):
                errors.append(f"invalid:{field}")
        errors.extend(_authority_errors(report))
        if payload.get("status") != "PASS":
            errors.append("report_not_pass")
        if payload.get("content_status") != "CONTENT_READY":
            errors.append("content_not_ready")
        if payload.get("read_back") is not True:
            errors.append("report_not_read_back")
        if source is None or source.is_symlink() or not source.is_dir():
            errors.append("missing_or_unsafe:source_dir")
            return result
        source = source.resolve()
        if name == "v4":
            errors.extend(validate_v4_verification(report, run_id=report.get("run_id", "")))
            files = {key: file for key, file in V4_FILES.items() if key != "verify"}
            hashes = payload.get("artifact_hashes", {})
        else:
            errors.extend(validate_v5_artifact(report_name, report, source))
            files = {file: file for file in V5_FILES if file != report_name}
            hashes = payload.get("output_hashes", {})
            basis = deepcopy(report)
            if isinstance(hashes, dict):
                basis["payload"]["output_hashes"][report_name] = ""
                encoded = (json.dumps(basis, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":"), allow_nan=False) + "\n").encode()
                if hashes.get(report_name) != _sha(encoded):
                    errors.append("self_hash_mismatch")
        if not isinstance(hashes, dict):
            hashes = {}
            errors.append("invalid:artifact_hashes")
        artifacts = {}
        for key, filename in files.items():
            check: dict[str, Any] = {"status": "BLOCKED", "errors": [], "read_back": False}
            result["module_checks"][filename] = check
            try:
                artifact, digest = _read(root, filename)
                artifacts[filename] = artifact
                check["sha256"] = digest
                check["read_back"] = True
                if hashes.get(filename) != digest:
                    check["errors"].append("hash_mismatch")
                if artifact.get("run_id") != report.get("run_id"):
                    check["errors"].append("run_id_mismatch")
                check["errors"].extend(_authority_errors(artifact))
                validator = validate_v4_artifact if name == "v4" else validate_v5_artifact
                check["errors"].extend(validator(key, artifact, source))
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                check["errors"].append(f"invalid_artifact:{type(exc).__name__}")
            errors.extend(f"{filename}:{error}" for error in check["errors"])
            check["status"] = "PASS" if not check["errors"] else "BLOCKED"
        # Replay includes source audit, content handoff and all module validators.
        # Nothing is written into either the supplied inputs or output bundle.
        with TemporaryDirectory(prefix="article-controller-context-") as temporary:
            replay_dir = Path(temporary)
            runner = run_v4_verification if name == "v4" else run_v5_verification
            fresh = runner(source, output_path=replay_dir / report_name)
            result["revalidated"] = fresh["payload"]
            if fresh != report:
                errors.append("stale_or_inconsistent:verification_report")
            for filename, artifact in artifacts.items():
                regenerated, _ = _read(replay_dir, filename)
                if regenerated != artifact:
                    errors.append(f"stale_or_inconsistent:{filename}")
                    result["module_checks"][filename]["status"] = "BLOCKED"
                    result["module_checks"][filename]["errors"].append("stale_or_inconsistent")
        # Detect modification of consumed bundle files during verification.
        if _read(root, report_name)[1] != report_sha:
            errors.append("report_changed_during_verification")
        for filename, check in result["module_checks"].items():
            if _read(root, filename)[1] != check.get("sha256"):
                errors.append(f"changed_during_verification:{filename}")
        result["read_back"] = True
    except (OSError, ValueError, TypeError, KeyError, AttributeError,
            V4VerificationError, VerificationError) as exc:
        # Keep errors concise; do not echo malformed input contents.
        message = str(exc)
        errors.append(message if message.startswith("unsafe_or_missing:")
                      else f"context_verification_failed:{type(exc).__name__}")
    result["errors"] = sorted(set(errors))
    result["status"] = "PASS" if not errors else "BLOCKED"
    return result


def verify_context(
    *, v4_run_dir: Path | None = None, v5_run_dir: Path | None = None,
    v4_source_dir: Path | None = None, v5_source_dir: Path | None = None,
    expected_contexts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Require both layers, pinned by run identity and report hash in the manifest."""
    bindings = expected_contexts if isinstance(expected_contexts, Mapping) else {}
    layers = {
        name: _layer(name, output, source, bindings.get(name))
        for name, output, source in (
            ("v4", v4_run_dir, v4_source_dir), ("v5", v5_run_dir, v5_source_dir)
        )
    }
    passed = all(layer["status"] == "PASS" for layer in layers.values())
    return {
        "status": "PASS" if passed else "BLOCKED", "layers": layers,
        "content_status": "CONTENT_READY" if passed else "CONTENT_BLOCKED",
        "content_status_basis": "revalidated_v4_content_handoff_and_v5_context",
        "evidence_only": True, "controller_acceptance": "not_evaluated",
        "r8_status": "not_evaluated", "auto_apply": False,
        "publication_authorization": "not_authorized",
    }
