from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any


_CREDENTIAL_MARKERS = (
    "token",
    "cookie",
    "session",
    "authorization",
    "password",
    "secret",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
)
_EVIDENCE_TEXT_MARKER_RE = re.compile(
    r"token|cookie|session|authorization|password|secret|"
    r"api[\s_-]*key|access[\s_-]*key|private[\s_-]*key|"
    r"bearer\s+",
    re.IGNORECASE,
)
_BASE64_BLOB_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
_AUTHORITY_KEYS = frozenset(
    {
        "qualification_status",
        "proposed_qualification_status",
        "derived_qualification_status",
        "automatic_publication_authority",
        "promotion_status",
        "verification_state",
    }
)


class ViralResearchEvidenceError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}:{detail}" if detail else code)


def _error(code: str, detail: str = "") -> ViralResearchEvidenceError:
    return ViralResearchEvidenceError(code, detail)


def _scan_value(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).lower().replace("-", "_")
            if key_text in _AUTHORITY_KEYS:
                raise _error("authority_field_forbidden", f"{path}.{key}")
            if any(marker in key_text for marker in _CREDENTIAL_MARKERS):
                raise _error("credential_marker", f"{path}.{key}")
            _scan_value(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_value(child, f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in ("bearer ", "cookie=", "set-cookie:", "session=")):
            raise _error("credential_marker", path)


def scan_evidence_file(path: Path, *, expected_digest: str) -> None:
    """Verify digest and scan decodable evidence without copying it to artifacts."""
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise _error("evidence_unreadable", "evidence_ref") from exc
    if hashlib.sha256(content).hexdigest() != expected_digest.lower():
        raise _error("client_evidence_sha256_mismatch", "evidence_ref")
    try:
        if content.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = content.decode("utf-16")
        else:
            text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _error("evidence_format_unsupported", "evidence_ref") from exc
    if "\x00" in text:
        raise _error("evidence_format_unsupported", "evidence_ref")
    compact = "".join(text.split())
    if len(compact) >= 16 and len(compact) % 4 == 0 and _BASE64_BLOB_RE.fullmatch(compact):
        raise _error("evidence_format_unsupported", "evidence_ref")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, (Mapping, list)):
        _scan_value(parsed, path="evidence_ref")
    if _EVIDENCE_TEXT_MARKER_RE.search(text):
        raise _error("credential_marker", "evidence_ref")
