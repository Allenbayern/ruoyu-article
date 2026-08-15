from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final, Sequence

OUTPUT_FIELDS: Final[tuple[str, ...]] = (
    "account_id",
    "article_key",
    "title",
    "digest",
    "create_time",
    "update_time",
    "public_link",
    "itemidx",
    "cover_url",
    "copyright_type",
    "is_pay_subscribe",
    "discovery_source",
    "captured_at",
)

ALLOWLIST_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "account_id",
        "status",
        "allowed_operation",
        "expires_at",
        "service_identity_ref",
        "profile_ref",
    }
)


class BackendPreflightError(ValueError):
    """Stable fail-closed policy error."""


def _text(value: object, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BackendPreflightError(code)
    return value.strip()


def _time(value: object, code: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_text(value, code))
    except ValueError as error:
        raise BackendPreflightError(code) from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(hours=8):
        raise BackendPreflightError(code)
    return parsed


def preflight_allowlist(
    record: dict[str, Any] | None,
    *,
    account_id: str,
    operation: str,
    now: datetime,
) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise BackendPreflightError("allowlist_missing")
    unknown = sorted(set(record) - ALLOWLIST_FIELDS)
    if unknown:
        raise BackendPreflightError(f"allowlist_field_not_allowed:{unknown[0]}")
    expected_account = _text(account_id, "account_id_missing")
    requested_operation = _text(operation, "operation_missing")
    actual_account = _text(record.get("account_id"), "allowlist_account_id_missing")
    if actual_account != expected_account:
        raise BackendPreflightError("account_mismatch")
    status = _text(record.get("status"), "allowlist_status_missing")
    if status == "revoked":
        raise BackendPreflightError("allowlist_revoked")
    if status != "active":
        raise BackendPreflightError("allowlist_not_active")
    allowed_operation = _text(record.get("allowed_operation"), "allowed_operation_missing")
    if allowed_operation != requested_operation:
        raise BackendPreflightError("operation_not_allowed")
    expires_at = _time(record.get("expires_at"), "allowlist_expiry_missing")
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() != timedelta(hours=8)
    ):
        raise BackendPreflightError("now_must_be_asia_shanghai")
    if expires_at <= now:
        raise BackendPreflightError("allowlist_expired")
    service_ref = _text(record.get("service_identity_ref"), "service_identity_ref_missing")
    if service_ref != f"refs/service-identity/{expected_account}":
        raise BackendPreflightError("service_identity_ref_account_mismatch")
    profile_ref = _text(record.get("profile_ref"), "profile_ref_missing")
    if profile_ref != f"refs/profile/{expected_account}":
        raise BackendPreflightError("profile_ref_account_mismatch")
    return {
        "authorized": True,
        "account_id": actual_account,
        "operation": allowed_operation,
        "service_identity_ref": service_ref,
        "profile_ref": profile_ref,
    }


def whitelist_output(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise BackendPreflightError("output_record_invalid")
    unknown = sorted(set(record) - set(OUTPUT_FIELDS))
    if unknown:
        raise BackendPreflightError(f"output_field_not_allowed:{unknown[0]}")
    missing = [field for field in OUTPUT_FIELDS if field not in record]
    if missing:
        raise BackendPreflightError(f"output_field_missing:{missing[0]}")
    return {field: record[field] for field in OUTPUT_FIELDS}


def authorize_peer_uid(*, peer_uid: int | None, expected_uid: int | None) -> dict[str, Any]:
    if not isinstance(peer_uid, int) or isinstance(peer_uid, bool):
        raise BackendPreflightError("peer_uid_missing")
    if not isinstance(expected_uid, int) or isinstance(expected_uid, bool):
        raise BackendPreflightError("expected_peer_uid_missing")
    if peer_uid != expected_uid:
        raise BackendPreflightError("peer_uid_mismatch")
    return {"authorized": True, "peer_uid": peer_uid}


def _load_record(path: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BackendPreflightError("allowlist_unreadable") from error
    if not isinstance(value, dict):
        raise BackendPreflightError("allowlist_missing")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline backend enhancement allowlist preflight.")
    parser.add_argument("--allowlist", required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--operation", required=True)
    parser.add_argument("--now", required=True)
    args = parser.parse_args(argv)
    try:
        report = preflight_allowlist(
            _load_record(args.allowlist),
            account_id=args.account_id,
            operation=args.operation,
            now=_time(args.now, "now_invalid"),
        )
    except BackendPreflightError as error:
        print(f"PREFLIGHT_FAILED:{error}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
