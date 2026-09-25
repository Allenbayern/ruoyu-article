#!/usr/bin/env python3
"""Read the persistent viral library without exposing article content.

This module is deliberately independent from the library writer.  It opens
the database through a read-only SQLite URI, validates the supported library
schema versions and only reads allow-listed metadata.  Snapshot bodies are
streamed for UTF-8 and SHA-256 verification and are never returned to callers.
"""

from __future__ import annotations

from collections import Counter
import codecs
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from typing import Any, Iterable
from urllib.parse import quote, urlsplit, urlunsplit


READER_SCHEMA_VERSION = "codex-viral-library-reader-v1"
LIBRARY_SCHEMA_VERSION = "viral-library-schema-v3"
SUPPORTED_LIBRARY_SCHEMA_VERSIONS = frozenset(
    {
        "viral-library-schema-v1",
        "viral-library-schema-v2",
        "viral-library-schema-v3",
    }
)
DATABASE_NAME = "library.sqlite"
MAX_BOUNDED_CLASSIFIER_BYTES = 64 * 1024

CORE_TABLE_COLUMNS: dict[str, frozenset[str]] = {
    "schema_meta": frozenset({"key", "value"}),
    "cases": frozenset(
        {"case_id", "platform", "canonical_url", "first_seen_at", "last_seen_at"}
    ),
    "case_versions": frozenset(
        {
            "case_id",
            "platform",
            "canonical_url",
            "content_hash",
            "snapshot_relpath",
            "snapshot_bytes",
            "snapshot_sha256",
            "account_id",
            "account_name",
            "title",
            "published_at",
            "source_run_id",
            "qualification_status",
            "eligible_for_case",
            "is_republished",
            "review_decision_id",
            "version_of",
            "ingested_at",
        }
    ),
    "case_observations": frozenset(
        {"source_run_id", "case_id", "content_hash", "observed_at"}
    ),
}

_OPTIONAL_TABLE_KIND: dict[str, str] = {
    "evidence_refs": "evidence",
    "evidence_references": "evidence",
    "case_evidence_refs": "evidence",
    "case_evidence": "evidence",
    "evidence": "evidence",
    "reviews": "review",
    "review_records": "review",
    "review_log": "review",
    "review_decisions": "review",
}

_OPTIONAL_EVIDENCE_COLUMNS = frozenset(
    {
        "evidence_ref_id",
        "evidence_id",
        "reference_id",
        "ref_id",
        "id",
        "case_id",
        "content_hash",
        "source_run_id",
        "source_key",
        "source_role",
        "locator",
        "source_locator",
        "canonical_url",
        "source_url",
        "evidence_kind",
        "observed_at",
        "created_at",
        "sha256",
        "evidence_sha256",
        "artifact_path",
        "artifact_sha256",
        "artifact_bytes",
        "artifact_line",
        "metadata_sha256",
        "metadata_bytes",
        # These columns may exist in a future producer schema.  They are
        # intentionally never selected or returned.
        "payload",
        "raw_payload",
    }
)

_V3_EVIDENCE_COLUMNS = frozenset(
    {
        "reference_id",
        "case_id",
        "content_hash",
        "source_run_id",
        "source_key",
        "source_role",
        "locator",
        "canonical_url",
        "evidence_kind",
        "observed_at",
        "artifact_path",
        "artifact_sha256",
        "artifact_bytes",
        "artifact_line",
        "metadata_sha256",
        "metadata_bytes",
    }
)

_OPTIONAL_REVIEW_COLUMNS = frozenset(
    {
        "review_id",
        "case_id",
        "content_hash",
        "decision",
        "status",
        "reviewer_id",
        "reviewed_at",
        "created_at",
        "evidence_ref_id",
        "reference_id",
        # Current library schema v1 materializes these review fields.  They
        # are tolerated for schema compatibility but are never selected or
        # returned by the consumer projection.
        "qualification_status",
        "eligible_for_case",
        "evidence_reference_ids",
        "supersedes_review_id",
        # Review explanations are schema-tolerated but never exposed.
        "reason",
        "payload",
        "raw_payload",
    }
)

_V3_REVIEW_COLUMNS = frozenset(
    {
        "review_id",
        "case_id",
        "content_hash",
        "decision",
        "reviewer_id",
        "reviewed_at",
        "reason",
        "qualification_status",
        "eligible_for_case",
        "evidence_reference_ids",
        "supersedes_review_id",
    }
)

_V3_REQUIRED_EVIDENCE_KINDS = frozenset(
    {"article_body", "discovery_signal", "platform_metric", "review"}
)
_V3_ARTIFACT_PATHS = frozenset(
    {"article-candidates.jsonl", "viral-article-cases.jsonl"}
)

_READ_VERSION_COLUMNS = (
    "case_id",
    "platform",
    "canonical_url",
    "content_hash",
    "snapshot_relpath",
    "snapshot_bytes",
    "snapshot_sha256",
    "account_id",
    "published_at",
    "source_run_id",
    "qualification_status",
    "eligible_for_case",
    "is_republished",
    "review_decision_id",
    "version_of",
    "ingested_at",
)

_PLATFORM_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}\Z")
_CREDENTIAL_PATTERN = re.compile(
    r"(?:"
    r"\b(?:api[\s_-]*key|access[\s_-]*token|auth(?:orization)?|"
    r"cookie|cookies|credential|credentials|password|secret|secrets|"
    r"session(?:[\s_-]*(?:id|cookie|state))?|token|login[\s_-]*state|"
    r"connection[\s_-]*string|wxtoken|ad[\s_-]*token|appmsg[\s_-]*token|"
    r"pass[\s_-]*ticket)\b\s*(?::|=)"
    r"|\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"
    r")",
    re.IGNORECASE,
)

_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(
    os, "O_CLOEXEC", 0
)
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


class LibraryReaderError(ValueError):
    """Stable, content-free error reported by the read-only boundary."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _raise(code: str) -> None:
    raise LibraryReaderError(code)


def _normalise_root(library_root: str | Path) -> Path:
    try:
        raw = os.fspath(library_root)
    except TypeError:
        _raise("LIBRARY_ROOT_INVALID")
    if not isinstance(raw, str) or not raw.strip():
        _raise("LIBRARY_ROOT_INVALID")

    requested = Path(raw)
    if not requested.is_absolute():
        _raise("LIBRARY_ROOT_MUST_BE_ABSOLUTE")
    if requested == Path("/") or any(part == ".." for part in requested.parts):
        _raise("LIBRARY_ROOT_INVALID")
    try:
        path = Path(os.path.abspath(raw))
    except (OSError, TypeError, ValueError):
        _raise("LIBRARY_ROOT_INVALID")
    if path == Path("/"):
        _raise("LIBRARY_ROOT_INVALID")
    return path


def _reject_symlink_components(path: Path, *, missing_code: str, unsafe_code: str) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            item = os.lstat(current)
        except FileNotFoundError:
            _raise(missing_code)
        except OSError:
            _raise(unsafe_code)
        if stat.S_ISLNK(item.st_mode):
            _raise(unsafe_code)


def _validate_root(library_root: Path) -> Path:
    _reject_symlink_components(
        library_root,
        missing_code="LIBRARY_ROOT_UNAVAILABLE",
        unsafe_code="LIBRARY_ROOT_SYMLINK",
    )
    try:
        item = os.lstat(library_root)
    except FileNotFoundError:
        _raise("LIBRARY_ROOT_UNAVAILABLE")
    except OSError:
        _raise("LIBRARY_ROOT_UNAVAILABLE")
    if stat.S_ISLNK(item.st_mode):
        _raise("LIBRARY_ROOT_SYMLINK")
    if not stat.S_ISDIR(item.st_mode):
        _raise("LIBRARY_ROOT_NOT_DIRECTORY")
    return library_root


def _validate_regular_file(path: Path, missing_code: str, unsafe_code: str) -> None:
    try:
        item = os.lstat(path)
    except FileNotFoundError:
        _raise(missing_code)
    except OSError:
        _raise(unsafe_code)
    if stat.S_ISLNK(item.st_mode):
        _raise(unsafe_code)
    if not stat.S_ISREG(item.st_mode):
        _raise(unsafe_code)


def _validate_database(root: Path) -> Path:
    database = root / DATABASE_NAME
    _validate_regular_file(database, "LIBRARY_DATABASE_UNAVAILABLE", "LIBRARY_DATABASE_UNSAFE")
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = root / f"{DATABASE_NAME}{suffix}"
        try:
            item = os.lstat(sidecar)
        except FileNotFoundError:
            continue
        except OSError:
            _raise("LIBRARY_DATABASE_UNSAFE")
        if stat.S_ISLNK(item.st_mode) or not stat.S_ISREG(item.st_mode):
            _raise("LIBRARY_DATABASE_UNSAFE")
    return database


def _sqlite_uri(database: Path) -> str:
    # ``mode=ro`` is intentional.  Keep SQLite able to consult WAL sidecars
    # for a current consistent snapshot; do not request an immutable URI mode.
    return f"file:{quote(str(database), safe='/:')}?mode=ro"


def _open_readonly_connection(library_root: Path) -> sqlite3.Connection:
    root = _validate_root(library_root)
    database = _validate_database(root)
    try:
        connection = sqlite3.connect(
            _sqlite_uri(database),
            uri=True,
            timeout=30.0,
        )
    except (OSError, sqlite3.Error) as error:
        raise LibraryReaderError("LIBRARY_DATABASE_UNAVAILABLE") from error
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        query_only = connection.execute("PRAGMA query_only").fetchone()
        if query_only is None or query_only[0] != 1:
            _raise("LIBRARY_QUERY_ONLY_UNAVAILABLE")
    except (OSError, sqlite3.Error):
        connection.close()
        _raise("LIBRARY_QUERY_ONLY_UNAVAILABLE")
    except LibraryReaderError:
        connection.close()
        raise
    return connection


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _table_columns(connection: sqlite3.Connection, table_name: str) -> frozenset[str]:
    try:
        rows = connection.execute(
            f"PRAGMA table_info({_quote_identifier(table_name)})"
        ).fetchall()
    except sqlite3.Error as error:
        raise LibraryReaderError("LIBRARY_SCHEMA_UNAVAILABLE") from error
    columns = frozenset(row[1] for row in rows if len(row) > 1 and isinstance(row[1], str))
    if not columns:
        _raise("LIBRARY_SCHEMA_UNAVAILABLE")
    return columns


def _validate_schema(
    connection: sqlite3.Connection,
) -> tuple[str, dict[str, dict[str, Any]]]:
    try:
        objects = {
            name: object_type
            for name, object_type in connection.execute(
                "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
            if isinstance(name, str) and isinstance(object_type, str)
        }
    except sqlite3.Error as error:
        raise LibraryReaderError("LIBRARY_SCHEMA_UNAVAILABLE") from error

    allowed_names = set(CORE_TABLE_COLUMNS) | set(_OPTIONAL_TABLE_KIND)
    if any(name not in allowed_names for name in objects):
        _raise("LIBRARY_TABLE_NOT_ALLOWLISTED")
    for table_name in CORE_TABLE_COLUMNS:
        if objects.get(table_name) != "table":
            _raise("LIBRARY_REQUIRED_TABLE_UNAVAILABLE")
        if _table_columns(connection, table_name) != CORE_TABLE_COLUMNS[table_name]:
            _raise("LIBRARY_COLUMNS_NOT_ALLOWLISTED")

    try:
        schema_row = connection.execute(
            f"SELECT value FROM {_quote_identifier('schema_meta')} WHERE key = ?",
            ("schema_version",),
        ).fetchone()
    except sqlite3.Error as error:
        raise LibraryReaderError("LIBRARY_SCHEMA_UNAVAILABLE") from error
    if (
        schema_row is None
        or not isinstance(schema_row[0], str)
        or schema_row[0] not in SUPPORTED_LIBRARY_SCHEMA_VERSIONS
    ):
        _raise("LIBRARY_SCHEMA_VERSION_UNSUPPORTED")
    schema_version = schema_row[0]
    try:
        qualified_row = connection.execute(
            """
            SELECT 1
            FROM case_versions
            WHERE qualification_status = 'qualified_viral'
            LIMIT 1
            """
        ).fetchone()
    except sqlite3.Error as error:
        raise LibraryReaderError("LIBRARY_CASES_UNAVAILABLE") from error
    qualified_requires_v3_evidence = (
        schema_version == "viral-library-schema-v3" and qualified_row is not None
    )

    optional: dict[str, dict[str, Any]] = {}
    for table_name, kind in sorted(_OPTIONAL_TABLE_KIND.items()):
        if table_name not in objects:
            continue
        entry: dict[str, Any] = {"kind": kind, "status": "unavailable"}
        optional[table_name] = entry
        if objects[table_name] != "table":
            entry["reason"] = "not_a_table"
            continue
        columns = _table_columns(connection, table_name)
        allowed_columns = (
            _OPTIONAL_EVIDENCE_COLUMNS if kind == "evidence" else _OPTIONAL_REVIEW_COLUMNS
        )
        if not columns <= allowed_columns:
            entry["reason"] = "columns_not_allowlisted"
            continue
        if schema_version == "viral-library-schema-v3":
            expected_columns = (
                _V3_EVIDENCE_COLUMNS
                if table_name == "evidence_refs"
                else _V3_REVIEW_COLUMNS
                if table_name == "reviews"
                else None
            )
            if expected_columns is not None and columns != expected_columns:
                entry["reason"] = "v3_columns_invalid"
                continue
        if "case_id" not in columns:
            entry["reason"] = "case_id_unavailable"
            continue
        required_output = (
            {"evidence_ref_id", "evidence_id", "reference_id", "ref_id", "id"}
            if kind == "evidence"
            else {"review_id"}
        )
        if not columns & required_output:
            entry["reason"] = "reference_id_unavailable"
            continue
        entry.update({"status": "available", "columns": sorted(columns)})
    if qualified_requires_v3_evidence:
        for table_name in ("evidence_refs", "reviews"):
            if optional.get(table_name, {}).get("status") != "available":
                _raise("LIBRARY_V3_EVIDENCE_UNAVAILABLE")
    return schema_version, optional


def _safe_text(value: object, *, max_length: int = 512) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > max_length:
        return None
    if _CREDENTIAL_PATTERN.search(text):
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in text):
        return None
    return text


def _safe_aware_timestamp(value: object) -> str | None:
    """Return a trimmed ISO-8601 timestamp only when it carries an offset."""

    text = _safe_text(value)
    if text is None:
        return None
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return text


def _safe_url(value: object) -> str | None:
    text = _safe_text(value, max_length=2048)
    if text is None:
        return None
    try:
        parsed = urlsplit(text)
        username = parsed.username
        password = parsed.password
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    if username is not None or password is not None:
        return None
    try:
        return urlunsplit(
            (parsed.scheme.lower(), parsed.netloc, parsed.path or "/", "", "")
        )
    except ValueError:
        return None


def _safe_hash(value: object) -> str | None:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        return None
    return value.lower()


def _safe_bool(value: object) -> bool | None:
    if type(value) is not int or value not in (0, 1):
        return None
    return bool(value)


def _safe_snapshot_reference(values: dict[str, Any]) -> tuple[str, str, str, int]:
    platform = values.get("platform")
    if not isinstance(platform, str) or _PLATFORM_PATTERN.fullmatch(platform) is None:
        _raise("SNAPSHOT_PLATFORM_INVALID")
    content_hash = _safe_hash(values.get("content_hash"))
    stored_hash = _safe_hash(values.get("snapshot_sha256"))
    if content_hash is None or stored_hash is None:
        _raise("SNAPSHOT_HASH_INVALID")
    if stored_hash != content_hash:
        _raise("SNAPSHOT_HASH_MISMATCH")
    snapshot_bytes = values.get("snapshot_bytes")
    if type(snapshot_bytes) is not int or snapshot_bytes < 0:
        _raise("SNAPSHOT_BYTES_INVALID")
    relative_path = values.get("snapshot_relpath")
    expected_path = f"snapshots/{platform}/{content_hash}.txt"
    if not isinstance(relative_path, str) or relative_path != expected_path:
        _raise("SNAPSHOT_PATH_INVALID")
    path_parts = relative_path.split("/")
    if (
        len(path_parts) != 3
        or any(part in {"", ".", ".."} for part in path_parts)
        or Path(relative_path).is_absolute()
    ):
        _raise("SNAPSHOT_PATH_INVALID")
    return relative_path, content_hash, stored_hash, snapshot_bytes


def _open_child_directory(parent_fd: int, name: str) -> int:
    try:
        descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    except OSError as error:
        raise LibraryReaderError("SNAPSHOT_PATH_UNAVAILABLE") from error
    try:
        item = os.fstat(descriptor)
    except OSError as error:
        os.close(descriptor)
        raise LibraryReaderError("SNAPSHOT_PATH_UNAVAILABLE") from error
    if not stat.S_ISDIR(item.st_mode):
        os.close(descriptor)
        _raise("SNAPSHOT_PATH_UNAVAILABLE")
    return descriptor


def _read_verified_snapshot(
    library_root: Path,
    relative_path: str,
    expected_hash: str,
    expected_bytes: int,
    *,
    max_bytes: int | None = None,
) -> tuple[dict[str, Any], str | None]:
    if max_bytes is not None and (type(max_bytes) is not int or max_bytes < 0):
        _raise("SNAPSHOT_CLASSIFIER_LIMIT_INVALID")
    parts = relative_path.split("/")
    root_fd: int | None = None
    snapshots_fd: int | None = None
    platform_fd: int | None = None
    snapshot_fd: int | None = None
    text_parts: list[str] = []
    try:
        try:
            root_fd = os.open(library_root, _DIRECTORY_FLAGS)
        except OSError as error:
            raise LibraryReaderError("LIBRARY_ROOT_UNAVAILABLE") from error
        try:
            root_item = os.fstat(root_fd)
        except OSError as error:
            raise LibraryReaderError("LIBRARY_ROOT_UNAVAILABLE") from error
        if not stat.S_ISDIR(root_item.st_mode):
            _raise("LIBRARY_ROOT_UNAVAILABLE")

        snapshots_fd = _open_child_directory(root_fd, parts[0])
        platform_fd = _open_child_directory(snapshots_fd, parts[1])
        try:
            snapshot_fd = os.open(parts[2], _FILE_FLAGS, dir_fd=platform_fd)
        except OSError as error:
            raise LibraryReaderError("SNAPSHOT_FILE_UNAVAILABLE") from error

        try:
            before = os.fstat(snapshot_fd)
        except OSError as error:
            raise LibraryReaderError("SNAPSHOT_FILE_UNAVAILABLE") from error
        if not stat.S_ISREG(before.st_mode):
            _raise("SNAPSHOT_FILE_NOT_REGULAR")

        digest = hashlib.sha256()
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        total_bytes = 0
        while True:
            read_size = 1024 * 1024
            if max_bytes is not None:
                read_size = min(read_size, max_bytes - total_bytes + 1)
            try:
                chunk = os.read(snapshot_fd, read_size)
            except OSError as error:
                raise LibraryReaderError("SNAPSHOT_FILE_UNAVAILABLE") from error
            if not chunk:
                break
            total_bytes += len(chunk)
            if max_bytes is not None and total_bytes > max_bytes:
                _raise("SNAPSHOT_TOO_LARGE_FOR_CLASSIFIER")
            digest.update(chunk)
            try:
                decoded = decoder.decode(chunk, final=False)
            except UnicodeDecodeError as error:
                raise LibraryReaderError("SNAPSHOT_UTF8_INVALID") from error
            if max_bytes is not None:
                text_parts.append(decoded)
        try:
            decoded_tail = decoder.decode(b"", final=True)
        except UnicodeDecodeError as error:
            raise LibraryReaderError("SNAPSHOT_UTF8_INVALID") from error
        if max_bytes is not None:
            text_parts.append(decoded_tail)

        try:
            after = os.fstat(snapshot_fd)
        except OSError as error:
            raise LibraryReaderError("SNAPSHOT_FILE_UNAVAILABLE") from error
        if (
            not stat.S_ISREG(after.st_mode)
            or (before.st_dev, before.st_ino, before.st_size)
            != (after.st_dev, after.st_ino, after.st_size)
        ):
            _raise("SNAPSHOT_CHANGED_DURING_READ")
        if total_bytes != expected_bytes or digest.hexdigest() != expected_hash:
            _raise("SNAPSHOT_HASH_MISMATCH")
        metadata = {
            "path": relative_path,
            "bytes": total_bytes,
            "sha256": digest.hexdigest(),
        }
        return metadata, "".join(text_parts) if max_bytes is not None else None
    finally:
        for descriptor in (snapshot_fd, platform_fd, snapshots_fd, root_fd):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


def _verify_snapshot(
    library_root: Path,
    relative_path: str,
    expected_hash: str,
    expected_bytes: int,
) -> dict[str, Any]:
    metadata, _ = _read_verified_snapshot(
        library_root,
        relative_path,
        expected_hash,
        expected_bytes,
    )
    return metadata


def read_snapshot_for_bounded_classifier(
    library_root: str | Path,
    sample: dict[str, Any],
    *,
    max_bytes: int = MAX_BOUNDED_CLASSIFIER_BYTES,
) -> str:
    """Return one verified snapshot only to a bounded in-memory classifier.

    The caller must pass a sample projection produced by this reader.  The
    snapshot is opened through the same no-follow descriptor walk as the
    ordinary report, and it is returned only after the path, size, UTF-8, and
    SHA-256 checks pass.  This helper is intentionally not used by ``read``;
    ordinary reader reports never contain article text.
    """

    if not isinstance(sample, dict):
        _raise("SNAPSHOT_CLASSIFIER_SAMPLE_INVALID")
    root = _validate_root(_normalise_root(library_root))
    relative_path, content_hash, _, snapshot_bytes = _safe_snapshot_reference(sample)
    _, text = _read_verified_snapshot(
        root,
        relative_path,
        content_hash,
        snapshot_bytes,
        max_bytes=max_bytes,
    )
    if text is None:  # pragma: no cover - max_bytes is always supplied above.
        _raise("SNAPSHOT_CLASSIFIER_READ_FAILED")
    return text


def _first_value(row: dict[str, Any], candidates: Iterable[str]) -> Any:
    for candidate in candidates:
        if candidate in row:
            return row[candidate]
    return None


def _optional_select_columns(kind: str, columns: frozenset[str]) -> list[str]:
    if kind == "evidence":
        candidates = (
            "evidence_ref_id",
            "evidence_id",
            "reference_id",
            "ref_id",
            "id",
            "source_run_id",
            "source_key",
            "source_role",
            "locator",
            "source_locator",
            "canonical_url",
            "source_url",
            "evidence_kind",
            "observed_at",
            "created_at",
        )
    else:
        candidates = (
            "review_id",
            "decision",
            "status",
            "reviewer_id",
            "reviewed_at",
            "created_at",
        )
    return [column for column in candidates if column in columns]


def _safe_evidence_ref(row: dict[str, Any]) -> dict[str, Any] | None:
    reference_id = _safe_text(
        _first_value(
            row,
            ("evidence_ref_id", "evidence_id", "reference_id", "ref_id", "id"),
        )
    )
    if reference_id is None:
        return None
    result: dict[str, Any] = {"evidence_ref_id": reference_id}
    for output_name, candidates in (
        ("source_run_id", ("source_run_id",)),
        ("source_key", ("source_key",)),
        ("source_role", ("source_role",)),
        ("locator", ("locator", "source_locator")),
        ("canonical_url", ("canonical_url", "source_url")),
        ("evidence_kind", ("evidence_kind",)),
        ("observed_at", ("observed_at", "created_at")),
    ):
        value = (
            _safe_url(_first_value(row, candidates))
            if output_name == "canonical_url"
            else _safe_text(_first_value(row, candidates))
        )
        if value is not None:
            result[output_name] = value
    return result


def _safe_review_ref(row: dict[str, Any]) -> dict[str, Any] | None:
    review_id = _safe_text(row.get("review_id"))
    if review_id is None:
        return None
    result: dict[str, Any] = {"review_id": review_id}
    for output_name, candidates in (
        ("decision", ("decision", "status")),
        ("reviewer_id", ("reviewer_id",)),
        ("reviewed_at", ("reviewed_at", "created_at")),
    ):
        value = _safe_text(_first_value(row, candidates))
        if value is not None:
            result[output_name] = value
    return result


def _validate_v3_positive_evidence(
    connection: sqlite3.Connection,
    optional_tables: dict[str, dict[str, Any]],
    *,
    case_id: str,
    content_hash: str,
    review_decision_id: object,
) -> str | None:
    """Validate the proof rows that make a v3 positive sample usable.

    The reader does not expose proof payloads or artifact contents.  It does,
    however, require the producer's normalized v3 metadata to be present,
    internally consistent, and structurally complete before a qualified row
    can be counted as a positive sample.
    """

    evidence_table = optional_tables.get("evidence_refs")
    review_table = optional_tables.get("reviews")
    if (
        not isinstance(evidence_table, dict)
        or evidence_table.get("status") != "available"
        or not isinstance(review_table, dict)
        or review_table.get("status") != "available"
    ):
        return "LIBRARY_V3_EVIDENCE_UNAVAILABLE"

    evidence_columns = (
        "reference_id",
        "case_id",
        "content_hash",
        "source_run_id",
        "source_key",
        "source_role",
        "locator",
        "canonical_url",
        "evidence_kind",
        "observed_at",
        "artifact_path",
        "artifact_sha256",
        "artifact_bytes",
        "artifact_line",
        "metadata_sha256",
        "metadata_bytes",
    )
    try:
        evidence_rows = connection.execute(
            "SELECT "
            + ", ".join(_quote_identifier(column) for column in evidence_columns)
            + " FROM "
            + _quote_identifier("evidence_refs")
            + " WHERE case_id = ? AND content_hash = ?",
            (case_id, content_hash),
        ).fetchall()
    except sqlite3.Error:
        return "LIBRARY_V3_EVIDENCE_QUERY_FAILED"

    reference_ids: set[str] = set()
    evidence_kind_by_reference_id: dict[str, str] = {}
    evidence_kinds: set[str] = set()
    for raw_row in evidence_rows:
        row = dict(zip(evidence_columns, raw_row))
        safe_reference = _safe_evidence_ref(row)
        reference_id = safe_reference.get("evidence_ref_id") if safe_reference else None
        if (
            reference_id is None
            or reference_id in reference_ids
            or row.get("case_id") != case_id
            or _safe_hash(row.get("content_hash")) != content_hash
            or any(
                _safe_text(row.get(field)) is None
                for field in ("source_run_id", "source_key", "source_role", "evidence_kind")
            )
            or _safe_aware_timestamp(row.get("observed_at")) is None
            or (
                row.get("locator") is None
                and row.get("canonical_url") is None
            )
            or (
                row.get("locator") is not None
                and _safe_text(row.get("locator")) is None
            )
            or (
                row.get("canonical_url") is not None
                and _safe_url(row.get("canonical_url")) is None
            )
            or row.get("artifact_path") not in _V3_ARTIFACT_PATHS
            or _safe_hash(row.get("artifact_sha256")) is None
            or type(row.get("artifact_bytes")) is not int
            or row.get("artifact_bytes") < 0
            or type(row.get("artifact_line")) is not int
            or row.get("artifact_line") < 1
            or _safe_hash(row.get("metadata_sha256")) is None
            or type(row.get("metadata_bytes")) is not int
            or row.get("metadata_bytes") < 0
        ):
            return "LIBRARY_V3_EVIDENCE_INVALID"
        reference_ids.add(reference_id)
        evidence_kind = str(row["evidence_kind"])
        evidence_kind_by_reference_id[reference_id] = evidence_kind
        evidence_kinds.add(evidence_kind)

    if not _V3_REQUIRED_EVIDENCE_KINDS <= evidence_kinds:
        return "LIBRARY_V3_EVIDENCE_INCOMPLETE"
    normalized_review_id = _safe_text(review_decision_id)
    if normalized_review_id is None:
        return "LIBRARY_V3_REVIEW_INVALID"

    review_columns = (
        "review_id",
        "case_id",
        "content_hash",
        "decision",
        "reviewer_id",
        "reviewed_at",
        "reason",
        "qualification_status",
        "eligible_for_case",
        "evidence_reference_ids",
        "supersedes_review_id",
    )
    try:
        review_rows = connection.execute(
            "SELECT "
            + ", ".join(_quote_identifier(column) for column in review_columns)
            + " FROM "
            + _quote_identifier("reviews")
            + " WHERE case_id = ? AND content_hash = ? AND review_id = ?",
            (case_id, content_hash, normalized_review_id),
        ).fetchall()
    except sqlite3.Error:
        return "LIBRARY_V3_REVIEW_QUERY_FAILED"
    if len(review_rows) != 1:
        return "LIBRARY_V3_REVIEW_INVALID"

    review = dict(zip(review_columns, review_rows[0]))
    review_status = review.get("qualification_status")
    review_eligible = review.get("eligible_for_case")
    # The producer deliberately persists an approved review before the
    # explicit case-state transition.  In that two-step path the materialized
    # review row is ``review_ready/0`` while the case version is already
    # ``qualified_viral/1`` after the transition.  A direct positive review
    # may instead materialize as ``qualified_viral/1``.  Both are valid only
    # when their status/eligibility pair is internally consistent.
    review_state_valid = (review_status, review_eligible) in {
        ("review_ready", 0),
        ("qualified_viral", 1),
    }
    if (
        review.get("review_id") != normalized_review_id
        or review.get("case_id") != case_id
        or _safe_hash(review.get("content_hash")) != content_hash
        or review.get("decision") != "approved"
        or _safe_text(review.get("reviewer_id")) is None
        or _safe_aware_timestamp(review.get("reviewed_at")) is None
        or _safe_text(review.get("reason")) is None
        or not review_state_valid
    ):
        return "LIBRARY_V3_REVIEW_INVALID"
    raw_reference_ids = review.get("evidence_reference_ids")
    if not isinstance(raw_reference_ids, str):
        return "LIBRARY_V3_REVIEW_INVALID"
    try:
        review_reference_ids = json.loads(raw_reference_ids)
    except (TypeError, ValueError, json.JSONDecodeError):
        return "LIBRARY_V3_REVIEW_INVALID"
    if not isinstance(review_reference_ids, list) or not review_reference_ids:
        return "LIBRARY_V3_REVIEW_INVALID"
    normalized_review_references: list[str] = []
    for reference_id in review_reference_ids:
        normalized = _safe_text(reference_id)
        if normalized is None or normalized in normalized_review_references:
            return "LIBRARY_V3_REVIEW_INVALID"
        normalized_review_references.append(normalized)
    if not set(normalized_review_references) <= reference_ids:
        return "LIBRARY_V3_REVIEW_INVALID"
    review_evidence_kinds = {
        evidence_kind_by_reference_id[reference_id]
        for reference_id in normalized_review_references
    }
    if not _V3_REQUIRED_EVIDENCE_KINDS <= review_evidence_kinds:
        return "LIBRARY_V3_REVIEW_EVIDENCE_INCOMPLETE"
    return None


def _query_optional_refs(
    connection: sqlite3.Connection,
    optional_tables: dict[str, dict[str, Any]],
    *,
    case_id: str,
    content_hash: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evidence_refs: list[dict[str, Any]] = []
    review_refs: list[dict[str, Any]] = []
    for table_name, table in optional_tables.items():
        if table.get("status") != "available":
            continue
        columns = frozenset(table.get("columns", ()))
        select_columns = _optional_select_columns(table["kind"], columns)
        if not select_columns:
            continue
        where = f"{_quote_identifier('case_id')} = ?"
        parameters: list[Any] = [case_id]
        if "content_hash" in columns:
            content_column = _quote_identifier("content_hash")
            where += f" AND ({content_column} = ? OR {content_column} IS NULL)"
            parameters.append(content_hash)
        select_sql = ", ".join(_quote_identifier(column) for column in select_columns)
        try:
            rows = connection.execute(
                f"SELECT {select_sql} FROM {_quote_identifier(table_name)} WHERE {where}",
                parameters,
            ).fetchall()
        except sqlite3.Error as error:
            raise LibraryReaderError("LIBRARY_OPTIONAL_QUERY_UNAVAILABLE") from error
        for raw_row in rows:
            row = dict(zip(select_columns, raw_row))
            if table["kind"] == "evidence":
                reference = _safe_evidence_ref(row)
                if reference is not None:
                    evidence_refs.append(reference)
            else:
                reference = _safe_review_ref(row)
                if reference is not None:
                    review_refs.append(reference)

    def unique(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[tuple[tuple[str, Any], ...]] = set()
        result: list[dict[str, Any]] = []
        for item in items:
            key = tuple(sorted(item.items()))
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    return unique(evidence_refs), unique(review_refs)


def _digest_regular_file(path: Path) -> dict[str, Any]:
    """Hash one already allow-listed file without following its final link."""

    descriptor: int | None = None
    try:
        try:
            descriptor = os.open(path, _FILE_FLAGS)
        except FileNotFoundError as error:
            raise LibraryReaderError("CONSUMER_MANIFEST_FILE_UNAVAILABLE") from error
        except OSError as error:
            raise LibraryReaderError("CONSUMER_MANIFEST_FILE_UNAVAILABLE") from error
        try:
            before = os.fstat(descriptor)
        except OSError as error:
            raise LibraryReaderError("CONSUMER_MANIFEST_FILE_UNAVAILABLE") from error
        if not stat.S_ISREG(before.st_mode):
            _raise("CONSUMER_MANIFEST_FILE_NOT_REGULAR")

        digest = hashlib.sha256()
        total_bytes = 0
        while True:
            try:
                chunk = os.read(descriptor, 1024 * 1024)
            except OSError as error:
                raise LibraryReaderError("CONSUMER_MANIFEST_FILE_UNAVAILABLE") from error
            if not chunk:
                break
            total_bytes += len(chunk)
            digest.update(chunk)
        try:
            after = os.fstat(descriptor)
        except OSError as error:
            raise LibraryReaderError("CONSUMER_MANIFEST_FILE_UNAVAILABLE") from error
        if (
            (before.st_dev, before.st_ino, before.st_size)
            != (after.st_dev, after.st_ino, after.st_size)
        ):
            _raise("CONSUMER_MANIFEST_FILE_CHANGED")
        return {"bytes": total_bytes, "sha256": digest.hexdigest()}
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _consumer_manifest(
    library_root: Path,
    snapshot_files: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return the digest/readback boundary for every external file consumed."""

    files: list[dict[str, Any]] = []
    database = _validate_database(_validate_root(library_root))
    database_digest = _digest_regular_file(database)
    files.append({"path": DATABASE_NAME, **database_digest})

    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = library_root / f"{DATABASE_NAME}{suffix}"
        try:
            item = os.lstat(sidecar)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise LibraryReaderError("CONSUMER_MANIFEST_FILE_UNAVAILABLE") from error
        if stat.S_ISLNK(item.st_mode) or not stat.S_ISREG(item.st_mode):
            _raise("CONSUMER_MANIFEST_FILE_NOT_REGULAR")
        sidecar_digest = _digest_regular_file(sidecar)
        files.append({"path": sidecar.name, **sidecar_digest})

    for relative_path in sorted(snapshot_files):
        verified = snapshot_files[relative_path]
        files.append(dict(verified))

    return {
        "status": "verified",
        "files": files,
        "readback": {"verified": True, "checked": len(files)},
    }


def _base_report(
    *,
    status: str,
    schema_version: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    if error:
        errors.append({"code": error})
    return {
        "reader_schema_version": READER_SCHEMA_VERSION,
        "schema_version": schema_version,
        "status": status,
        "read_only": True,
        "database": {
            "path": DATABASE_NAME,
            "mode": "ro",
            "query_only": True,
        },
        "tables": {
            "required": sorted(CORE_TABLE_COLUMNS),
            "optional": {},
        },
        "qualification_status_counts": {},
        "qualified_usable_count": 0,
        "samples": [],
        "errors": errors,
        "consumer_manifest": {
            "status": "unavailable",
            "files": [],
            "readback": {"verified": False, "checked": 0},
        },
        "policy": {
            "positive_pattern_statuses": ["qualified_viral"],
            "observation_only_statuses": [
                "observed_pending",
                "research_only",
                "review_ready",
            ],
            "snapshot_failure_policy": "unavailable_not_promoted",
            "content_policy": "metadata_hashes_and_evidence_refs_only",
            "credential_policy": "never_read_or_copy",
            "dormant_copy_fallback": "disabled",
        },
    }


def _sample_from_row(
    library_root: Path,
    connection: sqlite3.Connection,
    optional_tables: dict[str, dict[str, Any]],
    schema_version: str,
    raw_row: tuple[Any, ...],
) -> tuple[dict[str, Any], str | None, dict[str, Any] | None]:
    values = dict(zip(_READ_VERSION_COLUMNS, raw_row))
    case_id = _safe_text(values.get("case_id"))
    platform = _safe_text(values.get("platform"), max_length=64)
    status = _safe_text(values.get("qualification_status")) or "unknown"
    sample: dict[str, Any] = {
        "case_id": case_id,
        "platform": platform,
        "canonical_url": _safe_url(values.get("canonical_url")),
        "content_hash": _safe_hash(values.get("content_hash")),
        "snapshot_relpath": None,
        "snapshot_bytes": None,
        "snapshot_sha256": _safe_hash(values.get("snapshot_sha256")),
        "account_id": _safe_text(values.get("account_id")),
        "published_at": _safe_text(values.get("published_at")),
        "source_run_id": _safe_text(values.get("source_run_id")),
        "qualification_status": status,
        "eligible_for_case": _safe_bool(values.get("eligible_for_case")),
        "is_republished": _safe_bool(values.get("is_republished")),
        "review_decision_id": _safe_text(values.get("review_decision_id")),
        "version_of": _safe_text(values.get("version_of")),
        "ingested_at": _safe_text(values.get("ingested_at")),
        "availability": "unavailable",
        "evidence_refs": [],
        "review_refs": [],
        "usable_for_positive_patterns": False,
    }
    error_code: str | None = None
    snapshot_file: dict[str, Any] | None = None
    try:
        if case_id is None:
            _raise("CASE_ID_INVALID")
        if platform is None:
            _raise("PLATFORM_INVALID")
        if _safe_url(values.get("canonical_url")) is None:
            _raise("CANONICAL_URL_UNSAFE")
        if _safe_text(values.get("source_run_id")) is None:
            _raise("SOURCE_RUN_ID_INVALID")
        if _safe_text(values.get("qualification_status")) is None:
            _raise("QUALIFICATION_STATUS_INVALID")
        if _safe_bool(values.get("eligible_for_case")) is None:
            _raise("ELIGIBILITY_INVALID")
        republished = values.get("is_republished")
        if republished is not None and _safe_bool(republished) is None:
            _raise("REPUBLISHED_INVALID")
        relative_path, content_hash, _, snapshot_bytes = _safe_snapshot_reference(values)
        snapshot_file = _verify_snapshot(
            library_root, relative_path, content_hash, snapshot_bytes
        )
        evidence_refs, review_refs = _query_optional_refs(
            connection,
            optional_tables,
            case_id=case_id,
            content_hash=content_hash,
        )
        if status == "qualified_viral":
            if schema_version == "viral-library-schema-v3":
                if sample["eligible_for_case"] is not True:
                    _raise("LIBRARY_QUALIFICATION_ELIGIBILITY_INVALID")
                evidence_error = _validate_v3_positive_evidence(
                    connection,
                    optional_tables,
                    case_id=case_id,
                    content_hash=content_hash,
                    review_decision_id=values.get("review_decision_id"),
                )
                if evidence_error is not None:
                    _raise(evidence_error)
        sample["snapshot_relpath"] = relative_path
        sample["snapshot_bytes"] = snapshot_bytes
        sample["availability"] = "available"
        sample["evidence_refs"] = evidence_refs
        sample["review_refs"] = review_refs
        sample["usable_for_positive_patterns"] = (
            status == "qualified_viral"
            and sample["eligible_for_case"] is True
            and sample["is_republished"] is not True
        )
    except LibraryReaderError as error:
        error_code = error.code
    return sample, error_code, snapshot_file


class LibraryReader:
    """Independent, read-only view of one explicit viral-library root."""

    def __init__(self, library_root: str | Path):
        self._library_root = _normalise_root(library_root)

    @property
    def library_root(self) -> Path:
        return self._library_root

    def connect(self) -> sqlite3.Connection:
        """Return a read-only, query-only SQLite connection."""

        return _open_readonly_connection(self._library_root)

    def read(self) -> dict[str, Any]:
        """Return a content-light, integrity-checked library report."""

        connection = self.connect()
        try:
            schema_version, optional_tables = _validate_schema(connection)
            try:
                journal_row = connection.execute("PRAGMA journal_mode").fetchone()
            except sqlite3.Error as error:
                raise LibraryReaderError("LIBRARY_DATABASE_UNAVAILABLE") from error
            journal_mode = (
                journal_row[0].lower()
                if journal_row and isinstance(journal_row[0], str)
                else "unknown"
            )
            report = _base_report(status="available", schema_version=schema_version)
            report["database"]["journal_mode"] = journal_mode
            report["tables"]["optional"] = {
                name: {
                    key: value
                    for key, value in details.items()
                    if key != "columns"
                }
                for name, details in optional_tables.items()
            }
            status_counts: Counter[str] = Counter()
            samples: list[dict[str, Any]] = []
            errors: list[dict[str, str]] = []
            snapshot_files: dict[str, dict[str, Any]] = {}
            try:
                rows = connection.execute(
                    "SELECT "
                    + ", ".join(_quote_identifier(column) for column in _READ_VERSION_COLUMNS)
                    + f" FROM {_quote_identifier('case_versions')}"
                    + " ORDER BY case_id, content_hash"
                ).fetchall()
            except sqlite3.Error as error:
                raise LibraryReaderError("LIBRARY_CASES_UNAVAILABLE") from error

            for raw_row in rows:
                sample, error_code, snapshot_file = _sample_from_row(
                    self._library_root,
                    connection,
                    optional_tables,
                    schema_version,
                    raw_row,
                )
                status_counts[sample["qualification_status"]] += 1
                samples.append(sample)
                if error_code is not None:
                    error_item = {"code": error_code}
                    if isinstance(sample.get("case_id"), str):
                        error_item["case_id"] = sample["case_id"]
                    errors.append(error_item)
                if snapshot_file is not None:
                    snapshot_files[snapshot_file["path"]] = snapshot_file

            report["qualification_status_counts"] = dict(sorted(status_counts.items()))
            report["qualified_usable_count"] = sum(
                sample["usable_for_positive_patterns"] for sample in samples
            )
            report["samples"] = samples
            report["errors"] = errors
            try:
                report["consumer_manifest"] = _consumer_manifest(
                    self._library_root, snapshot_files
                )
            except LibraryReaderError as error:
                report["consumer_manifest"] = {
                    "status": "unavailable",
                    "files": [],
                    "readback": {"verified": False, "checked": 0},
                }
                report["errors"].append({"code": error.code})
            if errors:
                report["status"] = "unavailable"
            if report["consumer_manifest"]["status"] != "verified":
                report["status"] = "unavailable"
            return report
        finally:
            connection.close()


def read_library(library_root: str | Path) -> dict[str, Any]:
    """Read one explicit root and fail closed with a safe report."""

    try:
        return LibraryReader(library_root).read()
    except LibraryReaderError as error:
        return _base_report(status="unavailable", error=error.code)
    except (OSError, sqlite3.Error, UnicodeError, ValueError):
        return _base_report(status="unavailable", error="LIBRARY_READER_FAILED")
    except Exception:
        # A malformed or unexpectedly evolving producer schema must not leak
        # an exception string or tempt callers to use an unverified fallback.
        return _base_report(status="unavailable", error="LIBRARY_READER_FAILED")


# Explicit aliases make the small read-only API convenient for downstream
# consumers without creating any writer dependency.
build_library_index = read_library
read_viral_library = read_library


__all__ = [
    "CORE_TABLE_COLUMNS",
    "LIBRARY_SCHEMA_VERSION",
    "MAX_BOUNDED_CLASSIFIER_BYTES",
    "SUPPORTED_LIBRARY_SCHEMA_VERSIONS",
    "LibraryReader",
    "LibraryReaderError",
    "READER_SCHEMA_VERSION",
    "build_library_index",
    "read_library",
    "read_snapshot_for_bounded_classifier",
    "read_viral_library",
]
