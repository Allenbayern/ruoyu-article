from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys


def test_preview_contract_allows_independent_css_and_seals_route_bytes(tmp_path):
    assert importlib.util.find_spec("article_group.preview_contract") is not None
    from article_group.preview_contract import build_route_manifest, validate_route_response

    a = tmp_path / "a.html"
    b = tmp_path / "b.html"
    a.write_text("<style>a</style><article>A</article>", encoding="utf-8")
    b.write_text("<style>b</style><article>B</article>", encoding="utf-8")
    manifest = build_route_manifest({"/a.html": a, "/b.html": b})
    assert manifest["/a.html"]["body_sha256"] == hashlib.sha256(a.read_bytes()).hexdigest()
    assert manifest["/a.html"]["css_sha256"] != manifest["/b.html"]["css_sha256"]
    assert validate_route_response(manifest["/a.html"], a.read_bytes()) == []


def test_preview_contract_rejects_route_body_drift(tmp_path):
    from article_group.preview_contract import build_route_manifest, validate_route_response

    html = tmp_path / "a.html"
    html.write_text("<style>a</style><article>A</article>", encoding="utf-8")
    entry = build_route_manifest({"/a.html": html})["/a.html"]
    errors = validate_route_response(entry, b"changed")
    assert "preview_body_sha256_mismatch" in errors
    assert "preview_body_size_mismatch" in errors


def test_mobile_browser_screenshot_is_advisory_and_does_not_change_http_gate():
    from article_group.preview_contract import browser_preview_advisory

    report = browser_preview_advisory(None)

    assert report["blocking"] is False
    assert report["severity"] == "advisory"
    assert "mobile_browser_screenshot_not_run" in report["warnings"]


def test_http_response_status_and_bytes_are_hard_preview_contract(tmp_path):
    from article_group.preview_contract import build_route_manifest, validate_http_response

    html = tmp_path / "preview-contract-test.html"
    html.write_text("<article>stable</article>", encoding="utf-8")
    entry = build_route_manifest({"/stable.html": html})["/stable.html"]

    assert validate_http_response(entry, 200, html.read_bytes()) == []
    assert "preview_http_status_not_200" in validate_http_response(
        entry, 503, html.read_bytes()
    )


def test_preview_route_audit_cli_emits_per_route_manifest(tmp_path, capsys):
    from scripts import preview_route_audit

    html = tmp_path / "a.html"
    html.write_text("<style>a</style><article>A</article>", encoding="utf-8")

    exit_code = preview_route_audit.main(
        ["--route", f"/a.html={html}", "--mobile-screenshot-status", "not_run"]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["manifest"]["/a.html"]["bundle_mode"] == "per_route"
    assert payload["http_audit_status"] == "NOT_RUN"
    assert payload["browser_preview"]["blocking"] is False


def test_preview_route_audit_direct_script_entrypoint_resolves_project_package():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "preview_route_audit.py"), "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "per-route preview" in result.stdout
