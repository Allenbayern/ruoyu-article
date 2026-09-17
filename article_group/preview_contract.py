"""Per-route preview byte and CSS fingerprint contracts."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _css_bytes(data: bytes) -> bytes:
    text = data.decode("utf-8")
    matches = re.findall(r"<style[^>]*>(.*?)</style>", text, re.S | re.I)
    return "\n".join(match.strip() for match in matches).encode("utf-8")


def build_route_manifest(routes: dict[str, Path]) -> dict[str, dict[str, object]]:
    manifest: dict[str, dict[str, object]] = {}
    for route, path in routes.items():
        data = path.read_bytes()
        manifest[route] = {
            "route": route,
            "path": str(path),
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
