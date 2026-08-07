#!/usr/bin/env python3
"""Opt-in Graphite Minimal external-validator adapter.

This local adapter renders only supplied text into a deterministic, section-only
HTML fragment.  It contains no upstream template, component, CSS, or script.
The separately installed upstream validator is required at the caller-provided
checkout and exact Git commit; any dependency failure stops rendering.
"""
from __future__ import annotations

import hashlib
import html
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

MODE = "graphite_minimal_external"
VALIDATOR_RELATIVE_PATH = Path("scripts") / "validate_gzh_html.py"
APPROVED_UPSTREAM_ROOT = Path(os.environ.get('GRAPHITE_UPSTREAM_ROOT', str(Path.home() / '.hermes' / 'graphite' / 'gzh-design-skill')))
APPROVED_UPSTREAM_ORIGIN = "https://github.com/isjiamu/gzh-design-skill.git"
REQUIRED_VALIDATOR_COMMIT = "ba1f4175519b481cb3566616c9e5178705067904"
REQUIRED_VALIDATOR_SHA256 = "de21aa3decac10c6ef89040bdc4e19930dbed33d6ccf7bc963b744c53da01185"


class AdapterInputError(ValueError):
    """The supplied deterministic render input is not within this adapter's contract."""


class ExternalValidatorError(RuntimeError):
    """The separately attributed external validator cannot be verified or run."""


def _require_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdapterInputError(code)
    text = value.strip()
    if "{{" in text or "}}" in text:
        raise AdapterInputError("PLACEHOLDER_TEXT_FORBIDDEN")
    return text


def _run_checked(command: list[str], failure_code: str) -> str:
    try:
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise ExternalValidatorError(failure_code) from error
    if completed.returncode != 0:
        raise ExternalValidatorError(failure_code)
    return completed.stdout.strip()


def verify_external_validator(upstream_root: Path, expected_commit: str, expected_validator_sha256: str) -> dict[str, str]:
    """Verify the canonical checkout, origin, commit, and validator bytes."""
    root = Path(upstream_root)
    if not root.is_dir():
        raise ExternalValidatorError("EXTERNAL_VALIDATOR_UNAVAILABLE")
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as error:
        raise ExternalValidatorError("EXTERNAL_VALIDATOR_UNAVAILABLE") from error
    if resolved_root != APPROVED_UPSTREAM_ROOT.resolve():
        raise ExternalValidatorError("EXTERNAL_VALIDATOR_ROOT_MISMATCH")
    if not (resolved_root / ".git").is_dir():
        raise ExternalValidatorError("EXTERNAL_VALIDATOR_UNAVAILABLE")
    expected = _require_text(expected_commit, "INVALID_EXPECTED_COMMIT")
    expected_hash = _require_text(expected_validator_sha256, "INVALID_EXPECTED_VALIDATOR_HASH")
    if expected != REQUIRED_VALIDATOR_COMMIT:
        raise ExternalValidatorError("EXTERNAL_DEPENDENCY_COMMIT_MISMATCH")
    if expected_hash != REQUIRED_VALIDATOR_SHA256:
        raise ExternalValidatorError("EXTERNAL_DEPENDENCY_HASH_MISMATCH")
    origin = _run_checked(["git", "-C", str(resolved_root), "config", "--get", "remote.origin.url"], "EXTERNAL_VALIDATOR_UNAVAILABLE")
    if origin != APPROVED_UPSTREAM_ORIGIN:
        raise ExternalValidatorError("EXTERNAL_VALIDATOR_ORIGIN_MISMATCH")
    actual = _run_checked(["git", "-C", str(resolved_root), "rev-parse", "HEAD"], "EXTERNAL_VALIDATOR_UNAVAILABLE")
    if actual != REQUIRED_VALIDATOR_COMMIT:
        raise ExternalValidatorError("EXTERNAL_DEPENDENCY_COMMIT_MISMATCH")
    validator = resolved_root / VALIDATOR_RELATIVE_PATH
    if not validator.is_file():
        raise ExternalValidatorError("EXTERNAL_VALIDATOR_UNAVAILABLE")
    try:
        validator_hash = hashlib.sha256(validator.read_bytes()).hexdigest()
    except OSError as error:
        raise ExternalValidatorError("EXTERNAL_VALIDATOR_UNAVAILABLE") from error
    if validator_hash != REQUIRED_VALIDATOR_SHA256:
        raise ExternalValidatorError("EXTERNAL_DEPENDENCY_HASH_MISMATCH")
    return {"upstream_root": str(resolved_root), "commit": actual, "validator_path": str(validator), "validator_sha256": validator_hash}


def _leaf(text: str) -> str:
    return f'<span leaf="" style="color:#202124;">{html.escape(text, quote=False)}</span>'


def _section(heading: str, paragraphs: list[str]) -> str:
    rendered = [
        '<section style="margin:28px 0 0 0;">',
        f'<p style="margin:0 0 12px 0;font-size:18px;line-height:1.55;font-weight:700;color:#202124;">{_leaf(heading)}</p>',
    ]
    rendered.extend(
        f'<p style="margin:0 0 14px 0;font-size:16px;line-height:1.8;color:#202124;">{_leaf(paragraph)}</p>'
        for paragraph in paragraphs
    )
    rendered.append("</section>")
    return "".join(rendered)


def render_graphite_minimal_external(*, mode: str, title: Any, introduction: Any, sections: Any, upstream_root: Path, expected_commit: str, expected_validator_sha256: str) -> dict[str, Any]:
    """Render supplied fields only after external-validator verification succeeds."""
    if mode != MODE:
        raise AdapterInputError("UNSUPPORTED_RENDER_MODE")
    dependency = verify_external_validator(Path(upstream_root), expected_commit, expected_validator_sha256)
    clean_title = _require_text(title, "MISSING_TITLE")
    clean_introduction = _require_text(introduction, "MISSING_INTRODUCTION")
    if not isinstance(sections, list) or not sections:
        raise AdapterInputError("MISSING_NUMBERED_SECTIONS")

    rendered_sections: list[str] = []
    for section in sections:
        if not isinstance(section, dict):
            raise AdapterInputError("INVALID_SECTION")
        heading = _require_text(section.get("heading"), "INVALID_SECTION_HEADING")
        paragraphs = section.get("paragraphs")
        if not isinstance(paragraphs, list) or not paragraphs:
            raise AdapterInputError("INVALID_SECTION_PARAGRAPHS")
        clean_paragraphs = [_require_text(item, "INVALID_SECTION_PARAGRAPH") for item in paragraphs]
        rendered_sections.append(_section(heading, clean_paragraphs))

    fragment = "".join([
        '<section style="margin:0;padding:0;color:#202124;">',
        f'<p style="margin:0 0 16px 0;font-size:24px;line-height:1.4;font-weight:700;color:#202124;">{_leaf(clean_title)}</p>',
        f'<p style="margin:0;font-size:16px;line-height:1.8;color:#4a4a4a;">{_leaf(clean_introduction)}</p>',
        *rendered_sections,
        "</section>",
    ])
    try:
        completed = subprocess.run([sys.executable, dependency["validator_path"], "--stdin"], input=fragment, text=True, capture_output=True, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise ExternalValidatorError("EXTERNAL_VALIDATOR_FAILED") from error
    diagnostics = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode != 0 or "ERROR" in diagnostics or "WARNING" in diagnostics:
        raise ExternalValidatorError("EXTERNAL_VALIDATOR_FAILED")
    return {
        "mode": MODE,
        "html": fragment,
        "validator": {
            **dependency,
            "validated": True,
            "compatibility": "validator-backed only; no WeChat paste proof",
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        },
    }
