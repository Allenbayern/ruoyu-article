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


def test_legacy_preview_contract_value_still_reads_as_the_local_mode():
    """2026-09-25 契约值迁移：历史产物写的是 `local_codex`，读端必须照样认。

    与 review_surface 的 `markdown_codex` 同一波；**历史产物不重写**，所以兼容只能落在读端。
    """
    from article_group.preview_contract import (
        DEFAULT_PREVIEW_MODE,
        LEGACY_PREVIEW_MODES,
        is_local_preview,
        normalize_preview_mode,
        resolve_preview_mode,
        validate_batch_preview_mode,
    )

    assert LEGACY_PREVIEW_MODES == {"local_codex": DEFAULT_PREVIEW_MODE}
    assert DEFAULT_PREVIEW_MODE == "local_dsh"

    # 折值：只折历史值，非法值原样交给校验去拒（不许被静默兜底）
    assert normalize_preview_mode("local_codex") == "local_dsh"
    assert normalize_preview_mode("  local_codex  ") == "local_dsh"
    assert normalize_preview_mode("canonical_http") == "canonical_http"
    assert normalize_preview_mode("remote") == "remote"
    assert normalize_preview_mode(None) is None

    assert is_local_preview("local_codex") is True
    assert is_local_preview("local_dsh") is True
    assert is_local_preview("canonical_http") is False

    assert resolve_preview_mode("local_codex") == "local_dsh"
    assert validate_batch_preview_mode({"preview_mode": "local_codex"}) == []
    assert validate_batch_preview_mode({"preview_mode": "local_codex"}, require_explicit=True) == []
    assert validate_batch_preview_mode({"preview_mode": "remote"}) == [
        "preview_mode_invalid:remote"
    ]


def test_local_mode_evidence_accepts_a_historical_preview_mode(tmp_path):
    """一份**历史**的预览证据（里面写着 local_codex）仍要能校验通过。

    调用方给的 mode 也一样：旧命令行/旧记录里的 `local_codex` 折到现值，
    否则迁移就等于让既有证据整体报 preview_mode_invalid。
    """
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
        "schema_version": "preview-evidence-v2",
        "preview_mode": "local_codex",           # 历史产物里的写法
        "manifest": manifest,
    }
    # 证据里是旧值、调用方给新值 → 通过
    errors = validate_preview_evidence(
        payload, mode="local_dsh", root=tmp_path, delivery_htmls=[html])
    assert "preview_evidence_mode_mismatch" not in errors, errors
    assert not any(e.startswith("preview_mode_invalid") for e in errors), errors
    # 调用方也给旧值 → 一样通过（旧命令行不该因为一次改名就整体失效）
    assert validate_preview_evidence(
        payload, mode="local_codex", root=tmp_path, delivery_htmls=[html]) == errors
    # 真正的模式不符仍要被抓
    payload["preview_mode"] = "canonical_http"
    assert "preview_evidence_mode_mismatch" in validate_preview_evidence(
        payload, mode="local_dsh", root=tmp_path, delivery_htmls=[html])
    # 非法 mode 不被静默兜底
    assert validate_preview_evidence(
        payload, mode="remote", root=tmp_path,
        delivery_htmls=[html]) == ["preview_mode_invalid:remote"]


def test_preview_mode_defaults_to_local_dsh_and_rejects_unknown_values():
    from article_group.preview_contract import (
        DEFAULT_PREVIEW_MODE,
        resolve_preview_mode,
        validate_batch_preview_mode,
    )

    assert DEFAULT_PREVIEW_MODE == "local_dsh"
    assert resolve_preview_mode(None) == "local_dsh"
    assert validate_batch_preview_mode({}, require_explicit=False) == []
    assert validate_batch_preview_mode({}, require_explicit=True) == [
        "preview_mode_missing"
    ]
    assert validate_batch_preview_mode({"preview_mode": "local_dsh"}) == []
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
        "preview_mode": "local_dsh",
        "canonical_http_required": False,
        "local_preview_status": "READY",
        "manifest": manifest,
        "http_audit_status": "NOT_REQUIRED",
    }

    assert validate_preview_evidence(
        payload, mode="local_dsh", root=tmp_path, delivery_htmls=[html]
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
        "preview_mode": "local_dsh",
        "canonical_http_required": False,
        "local_preview_status": "READY",
        "manifest": manifest,
        "http_audit_status": "NOT_REQUIRED",
    }

    errors = validate_preview_evidence(
        payload, mode="local_dsh", root=tmp_path, delivery_htmls=[html]
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
    assert payload["preview_mode"] == "local_dsh"
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


# --- preview 证据路径：run 内记相对 + 旧绝对路径跨副本可重定位（2026-09-18）----


def _preview_run(tmp_path: Path, *parts: str) -> tuple[Path, Path]:
    run = tmp_path.joinpath(*parts)
    html = run / "review" / "frozen" / "ruoyu-art-001.html"
    html.parent.mkdir(parents=True, exist_ok=True)
    html.write_text("<article>stable</article>", encoding="utf-8")
    return run, html


def test_route_manifest_records_run_relative_paths(tmp_path: Path):
    from article_group.preview_contract import build_route_manifest

    _, html = _preview_run(tmp_path, "runs", "2026-09-18", "daily-901")
    entry = build_route_manifest({"/ruoyu-art-001.html": html})["/ruoyu-art-001.html"]
    assert entry["path"] == "review/frozen/ruoyu-art-001.html"


def test_legacy_absolute_preview_evidence_survives_a_copied_run(tmp_path: Path):
    """绝对路径的旧证据 + 副本：重定位后按 body/css sha256 授权，不再整体 BLOCKED。"""

    import json
    import shutil

    from article_group.preview_contract import build_route_manifest, validate_preview_evidence

    original, html = _preview_run(tmp_path, "runs", "2026-09-18", "daily-902")
    route = "/ruoyu-art-001.html"
    legacy = json.loads(json.dumps(build_route_manifest({route: html})))
    legacy[route]["path"] = str(html.resolve())  # 改动前的写法：绝对路径
    payload = {
        "schema_version": "preview-route-audit-v2",
        "preview_mode": "local_dsh",
        "canonical_http_required": False,
        "local_preview_status": "READY",
        "manifest": legacy,
        "http_audit_status": "NOT_REQUIRED",
    }
    copy = tmp_path / "backup" / "runs" / "2026-09-18" / "daily-902"
    shutil.copytree(original, copy)
    copy_html = copy / "review" / "frozen" / "ruoyu-art-001.html"

    assert validate_preview_evidence(
        payload, mode="local_dsh", root=copy, delivery_htmls=[copy_html]
    ) == []

    copy_html.write_text("<article>changed</article>", encoding="utf-8")
    errors = validate_preview_evidence(
        payload, mode="local_dsh", root=copy, delivery_htmls=[copy_html]
    )
    assert any("body_sha256_mismatch" in error for error in errors)
