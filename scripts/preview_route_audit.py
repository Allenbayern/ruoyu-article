#!/usr/bin/env python3
"""Build per-route preview fingerprints and optionally audit HTTP bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from article_group.preview_contract import (
    DEFAULT_PREVIEW_MODE,
    PREVIEW_MODES,
    browser_preview_advisory,
    build_route_manifest,
    validate_http_response,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preview-mode",
        choices=PREVIEW_MODES,
        default=DEFAULT_PREVIEW_MODE,
        help="Preview contract: local Codex preview by default, or explicit canonical HTTP delivery",
    )
    parser.add_argument(
        "--route",
        action="append",
        required=True,
        metavar="/route.html=PATH",
        help="Frozen local HTML route; repeat for each independent route",
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        metavar="/route.html=URL",
        help="Optional HTTP URL to audit against the route fingerprint",
    )
    parser.add_argument(
        "--mobile-screenshot-status",
        choices=("captured", "not_run", "unavailable", "skipped"),
        default="not_run",
    )
    parser.add_argument("--mobile-screenshot-path")
    parser.add_argument("--output", type=Path)
    return parser


def _pairs(values: list[str], label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in values:
        route, separator, value = raw.partition("=")
        if not separator or not route or not value:
            raise ValueError(f"invalid_{label}_mapping:{raw}")
        if route in result:
            raise ValueError(f"duplicate_{label}_route:{route}")
        result[route] = value
    return result


def _audit_url(entry: dict[str, object], url: str) -> dict[str, Any]:
    result: dict[str, Any] = {"url": url, "status": None, "errors": []}
    try:
        request = Request(url, headers={"User-Agent": "ruoyu-preview-audit/1"})
        with urlopen(request, timeout=15) as response:  # noqa: S310 - explicit audit URL
            status = int(response.status)
            body = response.read()
    except HTTPError as exc:
        status = int(exc.code)
        body = exc.read()
    except URLError as exc:
        result["errors"] = [f"preview_http_request_failed:{exc.reason}"]
        return result
    except OSError as exc:
        result["errors"] = [f"preview_http_request_failed:{exc}"]
        return result

    result["status"] = status
    result["body_size"] = len(body)
    result["body_sha256"] = hashlib.sha256(body).hexdigest()
    result["errors"] = validate_http_response(entry, status, body)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        route_paths = _pairs(args.route, "route")
        url_paths = _pairs(args.url, "url")
        if args.preview_mode == "canonical_http" and not url_paths:
            raise ValueError("canonical_http_requires_url")
        if args.preview_mode == "canonical_http" and set(url_paths) != set(route_paths):
            raise ValueError("canonical_http_route_set_mismatch")
        route_files = {route: Path(path) for route, path in route_paths.items()}
        manifest = build_route_manifest(route_files)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"INPUT_ERROR:{exc}")
        return 2

    http_checks: dict[str, dict[str, Any]] = {}
    for route, url in url_paths.items():
        if route not in manifest:
            http_checks[route] = {
                "url": url,
                "status": None,
                "errors": ["preview_route_not_in_manifest"],
            }
            continue
        http_checks[route] = _audit_url(manifest[route], url)

    if not url_paths:
        http_audit_status = "NOT_REQUIRED"
    elif args.preview_mode == "local_codex":
        http_audit_status = (
            "OPTIONAL_PASS"
            if all(not item["errors"] for item in http_checks.values())
            else "OPTIONAL_FAIL"
        )
    else:
        http_audit_status = (
            "PASS"
            if all(not item["errors"] for item in http_checks.values())
            else "FAIL"
        )

    browser = browser_preview_advisory({
        "status": args.mobile_screenshot_status,
        "screenshot_path": args.mobile_screenshot_path,
    })
    payload = {
        "schema_version": "preview-route-audit-v2",
        "preview_mode": args.preview_mode,
        "canonical_http_required": args.preview_mode == "canonical_http",
        "local_preview_status": (
            "READY" if args.preview_mode == "local_codex" else "NOT_APPLICABLE"
        ),
        "manifest": manifest,
        "http_audit_status": http_audit_status,
        "http_checks": http_checks,
        "browser_preview": browser,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 1 if args.preview_mode == "canonical_http" and http_audit_status == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
