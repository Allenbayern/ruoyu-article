from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from article_group.backend_preflight import (
    OUTPUT_FIELDS,
    BackendPreflightError,
    authorize_peer_uid,
    preflight_allowlist,
    whitelist_output,
)


NOW = datetime.fromisoformat("2026-08-13T12:00:00+08:00")


def allowlist(**changes: object) -> dict[str, object]:
    record: dict[str, object] = {
        "account_id": "acct-authorized-001",
        "status": "active",
        "allowed_operation": "list_ex",
        "expires_at": "2026-09-01T00:00:00+08:00",
        "service_identity_ref": "refs/service-identity/acct-authorized-001",
        "profile_ref": "refs/profile/acct-authorized-001",
    }
    record.update(changes)
    return record


def output_record() -> dict[str, object]:
    return {field: f"value-{index}" for index, field in enumerate(OUTPUT_FIELDS)}


def test_allowlist_accepts_one_active_unexpired_matching_operation() -> None:
    report = preflight_allowlist(
        allowlist(),
        account_id="acct-authorized-001",
        operation="list_ex",
        now=NOW,
    )
    assert report == {
        "authorized": True,
        "account_id": "acct-authorized-001",
        "operation": "list_ex",
        "service_identity_ref": "refs/service-identity/acct-authorized-001",
        "profile_ref": "refs/profile/acct-authorized-001",
    }


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"account_id": "other"}, "account_mismatch"),
        ({"status": "revoked"}, "allowlist_revoked"),
        ({"expires_at": "2026-08-01T00:00:00+08:00"}, "allowlist_expired"),
        ({"allowed_operation": "export"}, "operation_not_allowed"),
        ({"service_identity_ref": ""}, "service_identity_ref_missing"),
        ({"profile_ref": ""}, "profile_ref_missing"),
    ],
)
def test_allowlist_fail_closed_on_authorization_boundary(
    changes: dict[str, object], code: str
) -> None:
    with pytest.raises(BackendPreflightError, match=code):
        preflight_allowlist(
            allowlist(**changes),
            account_id="acct-authorized-001",
            operation="list_ex",
            now=NOW,
        )


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        (
            "service_identity_ref",
            "refs/service-identity/other-account",
            "service_identity_ref_account_mismatch",
        ),
        (
            "profile_ref",
            "refs/profile/other-account",
            "profile_ref_account_mismatch",
        ),
    ],
)
def test_allowlist_requires_account_bound_identity_references(
    field: str, value: str, code: str
) -> None:
    with pytest.raises(BackendPreflightError, match=code):
        preflight_allowlist(
            allowlist(**{field: value}),
            account_id="acct-authorized-001",
            operation="list_ex",
            now=NOW,
        )


def test_allowlist_fail_closed_on_missing_record_or_fields() -> None:
    with pytest.raises(BackendPreflightError, match="allowlist_missing"):
        preflight_allowlist(None, account_id="acct-authorized-001", operation="list_ex", now=NOW)
    missing = allowlist()
    missing.pop("profile_ref")
    with pytest.raises(BackendPreflightError, match="profile_ref_missing"):
        preflight_allowlist(missing, account_id="acct-authorized-001", operation="list_ex", now=NOW)


def test_allowlist_fails_closed_on_invalid_clock() -> None:
    with pytest.raises(BackendPreflightError, match="now_must_be_asia_shanghai"):
        preflight_allowlist(
            allowlist(),
            account_id="acct-authorized-001",
            operation="list_ex",
            now=None,  # type: ignore[arg-type]
        )


def test_allowlist_rejects_unknown_authority_fields() -> None:
    with pytest.raises(BackendPreflightError, match="allowlist_field_not_allowed:extra"):
        preflight_allowlist(
            allowlist(extra="unexpected"),
            account_id="acct-authorized-001",
            operation="list_ex",
            now=NOW,
        )


def test_output_whitelist_is_exact_and_deterministic() -> None:
    result = whitelist_output(output_record())
    assert tuple(result) == OUTPUT_FIELDS
    assert set(result) == set(OUTPUT_FIELDS)


def test_output_whitelist_rejects_disallowed_fields() -> None:
    record = output_record()
    record["cookie"] = "must never pass"
    with pytest.raises(BackendPreflightError, match="output_field_not_allowed:cookie"):
        whitelist_output(record)


def test_peer_uid_policy_is_pure_and_fail_closed() -> None:
    assert authorize_peer_uid(peer_uid=1001, expected_uid=1001) == {
        "authorized": True,
        "peer_uid": 1001,
    }
    with pytest.raises(BackendPreflightError, match="peer_uid_missing"):
        authorize_peer_uid(peer_uid=None, expected_uid=1001)
    with pytest.raises(BackendPreflightError, match="peer_uid_mismatch"):
        authorize_peer_uid(peer_uid=1002, expected_uid=1001)


def test_cli_accepts_offline_allowlist_and_emits_no_extra_metadata(tmp_path: Path) -> None:
    path = tmp_path / "allowlist.json"
    path.write_text(json.dumps(allowlist()), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "article_group.backend_preflight",
            "--allowlist",
            str(path),
            "--account-id",
            "acct-authorized-001",
            "--operation",
            "list_ex",
            "--now",
            "2026-08-13T12:00:00+08:00",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["authorized"] is True
    assert set(report) == {
        "authorized",
        "account_id",
        "operation",
        "service_identity_ref",
        "profile_ref",
    }


def test_cli_fails_closed_on_expired_allowlist(tmp_path: Path) -> None:
    path = tmp_path / "expired.json"
    path.write_text(json.dumps(allowlist(expires_at="2026-08-01T00:00:00+08:00")), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "article_group.backend_preflight",
            "--allowlist",
            str(path),
            "--account-id",
            "acct-authorized-001",
            "--operation",
            "list_ex",
            "--now",
            "2026-08-13T12:00:00+08:00",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.strip() == "PREFLIGHT_FAILED:allowlist_expired"
