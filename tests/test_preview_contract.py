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


def test_preview_mode_defaults_to_local_codex_and_rejects_unknown_values():
    from article_group.preview_contract import (
        DEFAULT_PREVIEW_MODE,
        resolve_preview_mode,
        validate_batch_preview_mode,
    )

    assert DEFAULT_PREVIEW_MODE == "local_codex"
    assert resolve_preview_mode(None) == "local_codex"
    assert validate_batch_preview_mode({}, require_explicit=False) == []
    assert validate_batch_preview_mode({}, require_explicit=True) == [
        "preview_mode_missing"
    ]
    assert validate_batch_preview_mode({"preview_mode": "local_codex"}) == []
    assert validate_batch_preview_mode({"preview_mode": "canonical_http"}) == []
    assert validate_batch_preview_mode({"preview_mode": "remote"}) == [
        "preview_mode_invalid:remote"
    ]


def test_local_preview_evidence_does_not_require_canonical_http(tmp_path):
    from article_group.preview_contract import (
        build_route_manifest,
        validate_preview_evidence,
    )

    html = tmp_path / "review" / "frozen" / "ruoyu-art-001.html"
    html.parent.mkdir(parents=True)
    html.write_text("<style>a</style><article>A</article>", encoding="utf-8")
    route = "/ruoyu-art-001.html"
    manifest = build_route_manifest({route: html})
    payload = {
        "schema_version": "preview-route-audit-v2",
        "preview_mode": "local_codex",
        "canonical_http_required": False,
        "local_preview_status": "READY",
        "manifest": manifest,
        "http_audit_status": "NOT_REQUIRED",
    }

    assert validate_preview_evidence(
        payload, mode="local_codex", root=tmp_path, delivery_htmls=[html]
    ) == []


def test_canonical_preview_evidence_requires_pass_and_route_checks(tmp_path):
    from article_group.preview_contract import build_route_manifest, validate_preview_evidence

    html = tmp_path / "review" / "frozen" / "ruoyu-art-001.html"
    html.parent.mkdir(parents=True)
    html.write_text("<article>stable</article>", encoding="utf-8")
    route = "/ruoyu-art-001.html"
    manifest = build_route_manifest({route: html})
    base = {
        "schema_version": "preview-route-audit-v2",
        "preview_mode": "canonical_http",
        "canonical_http_required": True,
        "manifest": manifest,
        "http_audit_status": "FAIL",
        "http_checks": {
            route: {
                "url": "http://192.168.100.168:8765/ruoyu-art-001.html",
                "status": 404,
                "body_size": 0,
                "body_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "errors": ["preview_http_status_not_200"],
            }
        },
    }

    errors = validate_preview_evidence(
        base, mode="canonical_http", root=tmp_path, delivery_htmls=[html]
    )
    assert "preview_canonical_http_not_pass" in errors
    assert "preview_canonical_route_not_200:/ruoyu-art-001.html" in errors

    base["http_audit_status"] = "PASS"
    base["http_checks"][route] = {
        "url": "http://192.168.100.168:8765/ruoyu-art-001.html",
        "status": 200,
        "body_size": len(html.read_bytes()),
        "body_sha256": manifest[route]["body_sha256"],
        "errors": [],
    }
    assert validate_preview_evidence(
        base, mode="canonical_http", root=tmp_path, delivery_htmls=[html]
    ) == []

    base["http_checks"][route].pop("url")
    errors = validate_preview_evidence(
        base, mode="canonical_http", root=tmp_path, delivery_htmls=[html]
    )
    assert "preview_canonical_url_missing:/ruoyu-art-001.html" in errors


def test_preview_evidence_rejects_frozen_file_hash_drift(tmp_path):
    from article_group.preview_contract import build_route_manifest, validate_preview_evidence

    html = tmp_path / "review" / "frozen" / "ruoyu-art-001.html"
    html.parent.mkdir(parents=True)
    html.write_text("<article>before</article>", encoding="utf-8")
    route = "/ruoyu-art-001.html"
    manifest = build_route_manifest({route: html})
    html.write_text("<article>after</article>", encoding="utf-8")
    payload = {
        "schema_version": "preview-route-audit-v2",
        "preview_mode": "local_codex",
        "canonical_http_required": False,
        "local_preview_status": "READY",
        "manifest": manifest,
        "http_audit_status": "NOT_REQUIRED",
    }

    errors = validate_preview_evidence(
        payload, mode="local_codex", root=tmp_path, delivery_htmls=[html]
    )
    assert "preview_route_body_sha256_mismatch:/ruoyu-art-001.html" in errors


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
    assert payload["preview_mode"] == "local_codex"
    assert payload["canonical_http_required"] is False
    assert payload["local_preview_status"] == "READY"
    assert payload["http_audit_status"] == "NOT_REQUIRED"
    assert payload["browser_preview"]["blocking"] is False


def test_preview_route_audit_canonical_mode_requires_explicit_urls(tmp_path, capsys):
    from scripts import preview_route_audit

    html = tmp_path / "a.html"
    html.write_text("<article>A</article>", encoding="utf-8")

    exit_code = preview_route_audit.main(
        ["--preview-mode", "canonical_http", "--route", f"/a.html={html}"]
    )

    assert exit_code == 2
    assert "canonical_http_requires_url" in capsys.readouterr().out


def test_preview_route_audit_canonical_mode_requires_one_url_per_route(tmp_path, capsys):
    from scripts import preview_route_audit

    first = tmp_path / "a.html"
    second = tmp_path / "b.html"
    first.write_text("<article>A</article>", encoding="utf-8")
    second.write_text("<article>B</article>", encoding="utf-8")

    exit_code = preview_route_audit.main(
        [
            "--preview-mode",
            "canonical_http",
            "--route",
            f"/a.html={first}",
            "--route",
            f"/b.html={second}",
            "--url",
            "/a.html=http://127.0.0.1:1/a.html",
        ]
    )

    assert exit_code == 2
    assert "canonical_http_route_set_mismatch" in capsys.readouterr().out


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
