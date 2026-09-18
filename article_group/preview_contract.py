"""Per-route preview byte and CSS fingerprint contracts."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


PREVIEW_MODES = ("local_codex", "canonical_http")
DEFAULT_PREVIEW_MODE = "local_codex"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _css_bytes(data: bytes) -> bytes:
    text = data.decode("utf-8")
    matches = re.findall(r"<style[^>]*>(.*?)</style>", text, re.S | re.I)
    return "\n".join(match.strip() for match in matches).encode("utf-8")


def resolve_preview_mode(value: object) -> str:
    """Return the effective preview mode, defaulting legacy callers locally."""
    if value is None:
        return DEFAULT_PREVIEW_MODE
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid_preview_mode")
    mode = value.strip()
    if mode not in PREVIEW_MODES:
        raise ValueError(f"invalid_preview_mode:{mode}")
    return mode


def validate_batch_preview_mode(
    batch: dict[str, Any], *, require_explicit: bool = False
) -> list[str]:
    """Validate a batch's optional/required preview-mode declaration."""
    if "preview_mode" not in batch:
        return ["preview_mode_missing"] if require_explicit else []
    value = batch.get("preview_mode")
    if not isinstance(value, str) or not value.strip():
        return ["preview_mode_invalid"]
    mode = value.strip()
    if mode not in PREVIEW_MODES:
        return [f"preview_mode_invalid:{mode}"]
    return []


def build_route_manifest(routes: dict[str, Path]) -> dict[str, dict[str, object]]:
    # 路径按 run 相对记（run 内产物）——绝对路径在 run 被复制/搬移后会让
    # validate_preview_evidence 整体报 preview_route_file_missing（2026-09-18 L2 复核）。
    from article_group.evidence_paths import run_relative_reference

    manifest: dict[str, dict[str, object]] = {}
    for route, path in routes.items():
        data = path.read_bytes()
        manifest[route] = {
            "route": route,
            "path": run_relative_reference(path),
            "bundle_mode": "per_route",
            "size": len(data),
            "body_sha256": _sha256(data),
            "css_sha256": _sha256(_css_bytes(data)),
        }
    return manifest


def validate_route_response(entry: dict[str, object], body: bytes) -> list[str]:
    errors: list[str] = []
    if entry.get("size") != len(body):
        errors.append("preview_body_size_mismatch")
    if entry.get("body_sha256") != _sha256(body):
        errors.append("preview_body_sha256_mismatch")
    return errors


def validate_http_response(
    entry: dict[str, object], status_code: int, body: bytes
) -> list[str]:
    """Apply the hard HTTP status and byte checks for one frozen route."""
    errors = [] if status_code == 200 else ["preview_http_status_not_200"]
    errors.extend(validate_route_response(entry, body))
    return errors


def browser_preview_advisory(evidence: object) -> dict[str, object]:
    """Record mobile-browser evidence without weakening the hard HTTP hash gate."""
    if evidence is None:
        return {
            "severity": "advisory",
            "blocking": False,
            "status": "not_run",
            "warnings": ["mobile_browser_screenshot_not_run"],
        }
    if not isinstance(evidence, dict):
        return {
            "severity": "advisory",
            "blocking": False,
            "status": "invalid",
            "warnings": ["mobile_browser_screenshot_evidence_invalid"],
        }
    status = evidence.get("status", "unknown")
    warnings: list[str] = []
    if status not in {"captured", "not_run", "unavailable", "skipped"}:
        warnings.append("mobile_browser_screenshot_status_unknown")
    if status == "captured" and not evidence.get("screenshot_path"):
        warnings.append("mobile_browser_screenshot_path_missing")
    return {
        "severity": "advisory",
        "blocking": False,
        "status": status,
        "warnings": warnings,
    }


def _resolve_evidence_path(root: Path, raw_path: object) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    candidate = Path(raw_path)
    if not candidate.is_absolute() and ".." in candidate.parts:
        return None
    try:
        resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        resolved.relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        # 旧证据里可能记的是绝对路径：run 被复制/搬移后按 runs/<date>/<id>/ 尾巴重定位。
        # 与 style-gate 同一口径——重定位只找候选，放行仍由 body/css sha256 比对决定。
        from article_group.evidence_paths import rebase_moved_run_path

        return rebase_moved_run_path(root, candidate)
    return resolved


def _canonical_checks(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    checks = payload.get("http_checks")
    if isinstance(checks, dict):
        return {
            str(route): entry
            for route, entry in checks.items()
            if isinstance(entry, dict)
        }
    legacy_routes = payload.get("routes")
    if isinstance(legacy_routes, list):
        result: dict[str, dict[str, object]] = {}
        for entry in legacy_routes:
            if isinstance(entry, dict) and isinstance(entry.get("route"), str):
                result[entry["route"]] = entry
        return result
    return {}


def validate_preview_evidence(
    payload: object,
    *,
    mode: str,
    root: Path,
    delivery_htmls: list[Path],
) -> list[str]:
    """Validate a mode-specific packet against the current frozen HTML files."""
    errors: list[str] = []
    if mode not in PREVIEW_MODES:
        return [f"preview_mode_invalid:{mode}"]
    if not isinstance(payload, dict):
        return ["preview_evidence_invalid"]
    if payload.get("preview_mode") != mode:
        errors.append("preview_evidence_mode_mismatch")

    manifest = payload.get("manifest")
    if not isinstance(manifest, dict) or not manifest:
        return [*errors, "preview_evidence_manifest_missing"]

    root_resolved = root.resolve()
    delivery_targets: set[Path] = set()
    for path in delivery_htmls:
        try:
            delivery_targets.add(path.resolve())
        except OSError:
            errors.append(f"preview_delivery_file_unreadable:{path.name}")

    bound_targets: set[Path] = set()
    for route, entry in manifest.items():
        route_label = str(route)
        if not isinstance(entry, dict):
            errors.append(f"preview_route_entry_invalid:{route_label}")
            continue
        target = _resolve_evidence_path(root_resolved, entry.get("path"))
        if target is None or not target.is_file():
            errors.append(f"preview_route_file_missing:{route_label}")
            continue
        bound_targets.add(target)
        if target not in delivery_targets:
            errors.append(f"preview_route_not_current_delivery:{route_label}")
        try:
            actual = build_route_manifest({route_label: target})[route_label]
        except (OSError, UnicodeError, ValueError):
            errors.append(f"preview_route_file_unreadable:{route_label}")
            continue
        if entry.get("size") != actual["size"]:
            errors.append(f"preview_route_body_size_mismatch:{route_label}")
        if entry.get("body_sha256") != actual["body_sha256"]:
            errors.append(f"preview_route_body_sha256_mismatch:{route_label}")
        if entry.get("css_sha256") != actual["css_sha256"]:
            errors.append(f"preview_route_css_sha256_mismatch:{route_label}")

    for target in sorted(delivery_targets - bound_targets):
        errors.append(f"preview_route_missing_current_delivery:{target.name}")

    if mode == "local_codex":
        if payload.get("canonical_http_required") is not False:
            errors.append("preview_local_canonical_http_must_not_be_required")
        if payload.get("local_preview_status") not in {"READY", "PASS"}:
            errors.append("preview_local_not_ready")
        return errors

    if payload.get("canonical_http_required") is not True:
        errors.append("preview_canonical_http_required_missing")
    if payload.get("http_audit_status") != "PASS":
        errors.append("preview_canonical_http_not_pass")
    checks = _canonical_checks(payload)
    for route, entry in manifest.items():
        route_label = str(route)
        check = checks.get(route_label)
        if check is None:
            errors.append(f"preview_canonical_route_missing:{route_label}")
            continue
        if not isinstance(check.get("url"), str) or not check["url"].strip():
            errors.append(f"preview_canonical_url_missing:{route_label}")
        if check.get("status") != 200:
            errors.append(f"preview_canonical_route_not_200:{route_label}")
        if check.get("errors"):
            errors.append(f"preview_canonical_route_errors:{route_label}")
        if "body_size" in check and check.get("body_size") != entry.get("size"):
            errors.append(f"preview_canonical_body_size_mismatch:{route_label}")
        if "body_sha256" in check and check.get("body_sha256") != entry.get("body_sha256"):
            errors.append(f"preview_canonical_body_sha256_mismatch:{route_label}")
    for route in sorted(set(checks) - {str(item) for item in manifest}):
        errors.append(f"preview_canonical_route_extra:{route}")
    return errors
