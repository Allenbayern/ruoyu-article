from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest


def _read_library(root: Path) -> dict[str, object]:
    from scripts.codex_viral_library_reader import read_library

    return read_library(root)


def _reader(root: Path):
    from scripts.codex_viral_library_reader import LibraryReader

    return LibraryReader(root)


CORE_SCHEMA = """
CREATE TABLE schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE cases (
    case_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(platform, canonical_url)
);
CREATE TABLE case_versions (
    case_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    snapshot_relpath TEXT NOT NULL,
    snapshot_bytes INTEGER NOT NULL,
    snapshot_sha256 TEXT NOT NULL,
    account_id TEXT,
    account_name TEXT,
    title TEXT,
    published_at TEXT,
    source_run_id TEXT NOT NULL,
    qualification_status TEXT NOT NULL,
    eligible_for_case INTEGER NOT NULL,
    is_republished INTEGER,
    review_decision_id TEXT,
    version_of TEXT,
    ingested_at TEXT NOT NULL,
    CHECK(eligible_for_case IN (0, 1)),
    PRIMARY KEY(case_id, content_hash),
    UNIQUE(platform, canonical_url, content_hash),
    FOREIGN KEY(case_id) REFERENCES cases(case_id)
);
CREATE TABLE case_observations (
    source_run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    PRIMARY KEY(source_run_id, case_id, content_hash),
    FOREIGN KEY(case_id, content_hash)
        REFERENCES case_versions(case_id, content_hash)
);
"""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _row(
    root: Path,
    *,
    case_id: str,
    status: str,
    body: bytes = b"safe redacted plaintext\n",
    platform: str = "wechat",
    canonical_url: str | None = None,
    eligible_for_case: bool = True,
    snapshot_relpath: str | None = None,
    snapshot_bytes: int | None = None,
    snapshot_sha256: str | None = None,
    title: str = "SECRET TITLE MUST NOT ESCAPE",
    account_name: str = "SECRET ACCOUNT MUST NOT ESCAPE",
) -> dict[str, object]:
    content_hash = _sha256(body)
    canonical_url = canonical_url or f"https://mp.weixin.qq.com/s/{case_id}"
    relative = snapshot_relpath or f"snapshots/{platform}/{content_hash}.txt"
    snapshot_path = root / relative
    if snapshot_relpath is None:
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_bytes(body)
    return {
        "case_id": case_id,
        "platform": platform,
        "canonical_url": canonical_url,
        "content_hash": content_hash,
        "snapshot_relpath": relative,
        "snapshot_bytes": len(body) if snapshot_bytes is None else snapshot_bytes,
        "snapshot_sha256": content_hash if snapshot_sha256 is None else snapshot_sha256,
        "account_id": f"account-{case_id}",
        "account_name": account_name,
        "title": title,
        "published_at": "2026-09-03T00:00:00+00:00",
        "source_run_id": f"run-{case_id}",
        "qualification_status": status,
        "eligible_for_case": int(eligible_for_case),
        "is_republished": 0,
        "review_decision_id": f"review-{case_id}",
        "version_of": None,
        "ingested_at": "2026-09-03T00:01:00+00:00",
    }


def _create_library(
    root: Path,
    rows: list[dict[str, object]],
    *,
    extra_table: bool = False,
    extra_case_version_column: bool = False,
    schema_version: str = "viral-library-schema-v1",
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(root / "library.sqlite")
    connection.executescript(CORE_SCHEMA)
    connection.execute(
        "INSERT INTO schema_meta(key, value) VALUES (?, ?)",
        ("schema_version", schema_version),
    )
    if extra_table:
        connection.execute(
            "CREATE TABLE secrets (payload TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO secrets(payload) VALUES (?)",
            ("MUST-NOT-BE-READ",),
        )
    if extra_case_version_column:
        connection.execute("ALTER TABLE case_versions ADD COLUMN raw_payload TEXT")
    for row in rows:
        connection.execute(
            """
            INSERT INTO cases(case_id, platform, canonical_url, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                row["case_id"],
                row["platform"],
                row["canonical_url"],
                row["ingested_at"],
                row["ingested_at"],
            ),
        )
        columns = (
            "case_id, platform, canonical_url, content_hash, snapshot_relpath,"
            " snapshot_bytes, snapshot_sha256, account_id, account_name, title,"
            " published_at, source_run_id, qualification_status, eligible_for_case,"
            " is_republished, review_decision_id, version_of, ingested_at"
        )
        connection.execute(
            f"INSERT INTO case_versions({columns}) VALUES ({','.join('?' for _ in range(18))})",
            tuple(row[column] for column in columns.replace(" ", "").split(",")),
        )
        connection.execute(
            """
            INSERT INTO case_observations(source_run_id, case_id, content_hash, observed_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                row["source_run_id"],
                row["case_id"],
                row["content_hash"],
                row["ingested_at"],
            ),
        )
    if extra_case_version_column:
        connection.execute(
            "UPDATE case_versions SET raw_payload = ?",
            ("MUST-NOT-BE-READ",),
        )
    connection.commit()
    connection.close()


def _add_v3_proof_tables(
    root: Path,
    row: dict[str, object],
    *,
    review_reference_ids: list[str] | None = None,
    reviewer_id: str = "reviewer-v3",
    reviewed_at: str = "2026-09-03T00:02:00+00:00",
    reason: str = "review reason",
) -> None:
    """Add a producer-shaped v3 evidence/review pair for negative tests."""

    connection = sqlite3.connect(root / "library.sqlite")
    connection.executescript(
        """
        CREATE TABLE evidence_refs (
            reference_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            source_run_id TEXT NOT NULL,
            source_key TEXT NOT NULL,
            source_role TEXT NOT NULL,
            locator TEXT,
            canonical_url TEXT,
            evidence_kind TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            artifact_path TEXT,
            artifact_sha256 TEXT,
            artifact_bytes INTEGER,
            artifact_line INTEGER,
            metadata_sha256 TEXT NOT NULL,
            metadata_bytes INTEGER NOT NULL
        );
        CREATE TABLE reviews (
            review_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            decision TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,
            reviewed_at TEXT NOT NULL,
            reason TEXT NOT NULL,
            qualification_status TEXT NOT NULL,
            eligible_for_case INTEGER NOT NULL,
            evidence_reference_ids TEXT NOT NULL,
            supersedes_review_id TEXT
        );
        """
    )
    evidence_rows = []
    for index, evidence_kind in enumerate(
        ("article_body", "discovery_signal", "platform_metric", "review"),
        start=1,
    ):
        evidence_rows.append(
            (
                f"evidence-ref-helper-{index}",
                row["case_id"],
                row["content_hash"],
                "producer-run-v3",
                "tophub" if evidence_kind != "article_body" else "wewe-rss",
                evidence_kind,
                f"https://evidence.example/helper/{index}",
                row["canonical_url"],
                evidence_kind,
                "2026-09-03T00:00:00+00:00",
                "viral-article-cases.jsonl",
                "a" * 64,
                128,
                index,
                "b" * 64,
                256,
            )
        )
    connection.executemany(
        "INSERT INTO evidence_refs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        evidence_rows,
    )
    reference_ids = review_reference_ids or [item[0] for item in evidence_rows]
    connection.execute(
        "INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            row["review_decision_id"],
            row["case_id"],
            row["content_hash"],
            "approved",
            reviewer_id,
            reviewed_at,
            reason,
            "review_ready",
            0,
            json.dumps(reference_ids),
            None,
        ),
    )
    connection.commit()
    connection.close()


def test_reader_reports_safe_statuses_without_title_or_body(tmp_path: Path) -> None:
    root = tmp_path / "viral-library"
    rows = [
        _row(root, case_id="qualified", status="qualified_viral"),
        _row(root, case_id="pending", status="observed_pending"),
        _row(root, case_id="research", status="research_only"),
        _row(root, case_id="review-ready", status="review_ready"),
    ]
    _create_library(root, rows)

    report = _read_library(root)
    encoded = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "available"
    assert report["schema_version"] == "viral-library-schema-v1"
    assert report["qualification_status_counts"] == {
        "observed_pending": 1,
        "qualified_viral": 1,
        "research_only": 1,
        "review_ready": 1,
    }
    assert report["qualified_usable_count"] == 1
    assert {sample["qualification_status"] for sample in report["samples"]} == {
        "qualified_viral",
        "observed_pending",
        "research_only",
        "review_ready",
    }
    assert "SECRET TITLE MUST NOT ESCAPE" not in encoded
    assert "SECRET ACCOUNT MUST NOT ESCAPE" not in encoded
    assert "safe redacted plaintext" not in encoded
    assert all("body" not in sample and "title" not in sample for sample in report["samples"])
    manifest = report["consumer_manifest"]
    assert manifest["status"] == "verified"
    assert manifest["readback"]["verified"] is True
    manifest_files = {item["path"]: item for item in manifest["files"]}
    assert manifest_files["library.sqlite"]["sha256"] == _sha256(
        (root / "library.sqlite").read_bytes()
    )
    assert manifest_files[report["samples"][0]["snapshot_relpath"]]["sha256"] == report[
        "samples"
    ][0]["content_hash"]


def test_reader_does_not_promote_malformed_core_flags(tmp_path: Path) -> None:
    root = tmp_path / "malformed-core-library"
    row = _row(root, case_id="malformed-core", status="qualified_viral")
    row["is_republished"] = 2
    _create_library(root, [row])

    report = _read_library(root)

    assert report["status"] == "unavailable"
    assert report["qualified_usable_count"] == 0
    assert report["samples"][0]["availability"] == "unavailable"


def test_reader_uses_readonly_query_only_uri_and_supports_wal(tmp_path: Path) -> None:
    root = tmp_path / "wal-library"
    root.mkdir()
    connection = sqlite3.connect(root / "library.sqlite")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(CORE_SCHEMA)
    connection.execute(
        "INSERT INTO schema_meta(key, value) VALUES ('schema_version', 'viral-library-schema-v1')"
    )
    connection.commit()

    reader = _reader(root)
    readonly = reader.connect()
    try:
        assert readonly.execute("PRAGMA query_only").fetchone()[0] == 1
        assert readonly.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        try:
            readonly.execute("CREATE TABLE must_not_be_created(value TEXT)")
        except sqlite3.OperationalError as error:
            assert "readonly" in str(error).lower()
        else:  # pragma: no cover - protects the actual read-only contract.
            raise AssertionError("reader connection permitted a write")
    finally:
        readonly.close()
        connection.close()

    assert not (root / "must_not_be_created").exists()
    report = _read_library(root)
    assert report["status"] == "available"
    assert report["database"]["journal_mode"] == "wal"
    assert report["consumer_manifest"]["status"] == "verified"


def test_reader_does_not_create_missing_root_or_database(tmp_path: Path) -> None:
    missing = tmp_path / "not-created"

    report = _read_library(missing)

    assert report["status"] == "unavailable"
    assert not missing.exists()


def test_reader_requires_an_explicit_absolute_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    report = _read_library(Path("relative-library"))

    assert report["status"] == "unavailable"
    assert not (tmp_path / "relative-library").exists()


def test_reader_fails_closed_for_missing_schema_and_database_symlink(
    tmp_path: Path,
) -> None:
    wrong_schema_root = tmp_path / "wrong-schema-library"
    wrong_schema_root.mkdir()
    connection = sqlite3.connect(wrong_schema_root / "library.sqlite")
    connection.execute("CREATE TABLE schema_meta (key TEXT, value TEXT)")
    connection.execute(
        "INSERT INTO schema_meta(key, value) VALUES ('schema_version', 'future-schema')"
    )
    connection.commit()
    connection.close()
    wrong_schema_report = _read_library(wrong_schema_root)
    assert wrong_schema_report["status"] == "unavailable"
    assert wrong_schema_report["qualified_usable_count"] == 0

    real_database_root = tmp_path / "real-database-library"
    real_database_root.mkdir()
    (real_database_root / "real.sqlite").write_bytes(b"not a library")
    (real_database_root / "library.sqlite").symlink_to(real_database_root / "real.sqlite")

    symlink_report = _read_library(real_database_root)
    assert symlink_report["status"] == "unavailable"
    assert symlink_report["qualified_usable_count"] == 0


def test_reader_rejects_root_and_snapshot_symlinks(tmp_path: Path) -> None:
    actual = tmp_path / "actual-library"
    row = _row(actual, case_id="symlinked", status="qualified_viral")
    _create_library(actual, [row])
    root_link = tmp_path / "root-link"
    root_link.symlink_to(actual, target_is_directory=True)

    linked_report = _read_library(root_link)
    assert linked_report["status"] == "unavailable"

    snapshots = actual / "snapshots"
    real_snapshot = snapshots / "wechat"
    redirected = actual / "redirected"
    redirected.mkdir()
    (snapshots / "wechat").rename(snapshots / "wechat-real")
    real_snapshot.symlink_to(redirected, target_is_directory=True)

    snapshot_report = _read_library(actual)
    assert snapshot_report["status"] == "unavailable"
    assert snapshot_report["qualified_usable_count"] == 0
    assert snapshot_report["samples"][0]["availability"] == "unavailable"
    assert not list(redirected.iterdir())


def test_reader_fails_closed_for_traversal_utf8_and_hash_mismatch(tmp_path: Path) -> None:
    traversal_root = tmp_path / "traversal-library"
    traversal_row = _row(
        traversal_root,
        case_id="traversal",
        status="qualified_viral",
        snapshot_relpath="../outside.txt",
    )
    _create_library(traversal_root, [traversal_row])
    (tmp_path / "outside.txt").write_text("MUST-NOT-BE-READ", encoding="utf-8")
    traversal_report = _read_library(traversal_root)
    assert traversal_report["status"] == "unavailable"
    assert traversal_report["qualified_usable_count"] == 0
    assert "MUST-NOT-BE-READ" not in json.dumps(traversal_report)

    invalid_root = tmp_path / "invalid-utf8-library"
    invalid_row = _row(invalid_root, case_id="invalid-utf8", status="research_only")
    invalid_snapshot = invalid_root / invalid_row["snapshot_relpath"]
    invalid_snapshot.parent.mkdir(parents=True, exist_ok=True)
    invalid_snapshot.write_bytes(b"\xff\xfe")
    _create_library(invalid_root, [invalid_row])
    invalid_report = _read_library(invalid_root)
    assert invalid_report["status"] == "unavailable"
    assert invalid_report["samples"][0]["availability"] == "unavailable"

    mismatch_root = tmp_path / "mismatch-library"
    mismatch_row = _row(
        mismatch_root,
        case_id="mismatch",
        status="qualified_viral",
        snapshot_sha256="0" * 64,
    )
    _create_library(mismatch_root, [mismatch_row])
    mismatch_report = _read_library(mismatch_root)
    assert mismatch_report["status"] == "unavailable"
    assert mismatch_report["qualified_usable_count"] == 0


def test_reader_rejects_non_allowlisted_tables_and_columns(tmp_path: Path) -> None:
    table_root = tmp_path / "table-library"
    _create_library(
        table_root,
        [_row(table_root, case_id="table-case", status="research_only")],
        extra_table=True,
    )
    table_report = _read_library(table_root)
    assert table_report["status"] == "unavailable"
    assert "MUST-NOT-BE-READ" not in json.dumps(table_report)

    column_root = tmp_path / "column-library"
    _create_library(
        column_root,
        [_row(column_root, case_id="column-case", status="research_only")],
        extra_case_version_column=True,
    )
    column_report = _read_library(column_root)
    assert column_report["status"] == "unavailable"
    assert "MUST-NOT-BE-READ" not in json.dumps(column_report)


def test_reader_tolerates_absent_or_malformed_optional_evidence_and_reviews(
    tmp_path: Path,
) -> None:
    root = tmp_path / "optional-library"
    row = _row(root, case_id="optional", status="qualified_viral")
    _create_library(root, [row])
    connection = sqlite3.connect(root / "library.sqlite")
    connection.execute("CREATE TABLE evidence_refs (case_id TEXT, payload TEXT)")
    connection.execute("CREATE TABLE reviews (case_id TEXT, raw_payload TEXT)")
    connection.commit()
    connection.close()

    report = _read_library(root)

    assert report["status"] == "available"
    assert report["qualified_usable_count"] == 1
    assert report["samples"][0]["evidence_refs"] == []
    assert report["samples"][0]["review_refs"] == []
    assert "raw_payload" not in json.dumps(report)
    assert "payload" not in json.dumps(report)


@pytest.mark.parametrize(
    "schema_version", ["viral-library-schema-v1", "viral-library-schema-v2"]
)
def test_reader_returns_only_safe_optional_reference_metadata(
    tmp_path: Path, schema_version: str
) -> None:
    root = tmp_path / "safe-optional-library"
    row = _row(root, case_id="safe-optional", status="qualified_viral")
    _create_library(root, [row], schema_version=schema_version)
    connection = sqlite3.connect(root / "library.sqlite")
    connection.executescript(
        """
        CREATE TABLE evidence_refs (
            reference_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            content_hash TEXT,
            source_run_id TEXT,
            source_key TEXT,
            source_role TEXT,
            locator TEXT,
            canonical_url TEXT,
            evidence_kind TEXT,
            observed_at TEXT,
            payload TEXT
        );
        CREATE TABLE reviews (
            review_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            content_hash TEXT,
            decision TEXT,
            reviewer_id TEXT,
            reviewed_at TEXT,
            reason TEXT,
            qualification_status TEXT,
            eligible_for_case INTEGER,
            evidence_reference_ids TEXT,
            supersedes_review_id TEXT
        );
        """
    )
    connection.execute(
        """
            INSERT INTO evidence_refs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "evidence-ref-1",
            row["case_id"],
            row["content_hash"],
            "run-safe-optional",
            "metric-source",
            "platform_metric_evidence",
            "metrics/record.json#sha256=abc",
            "https://evidence.example/record",
            "performance",
            "2026-09-03T00:00:00+00:00",
            "SECRET RAW PAYLOAD",
        ),
    )
    connection.execute(
        "INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "review-1",
            row["case_id"],
            row["content_hash"],
            "approved",
            "reviewer-1",
            "2026-09-03T00:02:00+00:00",
            "SECRET REVIEW REASON",
            "qualified_viral",
            1,
            '["evidence-ref-1"]',
            None,
        ),
    )
    connection.commit()
    connection.close()

    report = _read_library(root)
    sample = report["samples"][0]
    encoded = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "available"
    assert report["schema_version"] == schema_version
    assert report["tables"]["optional"]["reviews"]["status"] == "available"
    assert sample["evidence_refs"] == [
        {
            "evidence_ref_id": "evidence-ref-1",
            "source_run_id": "run-safe-optional",
            "source_key": "metric-source",
            "source_role": "platform_metric_evidence",
            "locator": "metrics/record.json#sha256=abc",
            "canonical_url": "https://evidence.example/record",
            "evidence_kind": "performance",
            "observed_at": "2026-09-03T00:00:00+00:00",
        }
    ]
    assert sample["review_refs"] == [
        {
            "review_id": "review-1",
            "decision": "approved",
            "reviewer_id": "reviewer-1",
            "reviewed_at": "2026-09-03T00:02:00+00:00",
        }
    ]
    assert "SECRET RAW PAYLOAD" not in encoded
    assert "SECRET REVIEW REASON" not in encoded


def test_reader_accepts_real_v3_evidence_reference_columns_without_body_leak(
    tmp_path: Path,
) -> None:
    """The consumer must understand the producer's v3 evidence proof fields."""

    root = tmp_path / "real-v3-library"
    row = _row(root, case_id="real-v3", status="qualified_viral")
    _create_library(root, [row], schema_version="viral-library-schema-v3")
    connection = sqlite3.connect(root / "library.sqlite")
    connection.executescript(
        """
        CREATE TABLE evidence_refs (
            reference_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            source_run_id TEXT NOT NULL,
            source_key TEXT NOT NULL,
            source_role TEXT NOT NULL,
            locator TEXT,
            canonical_url TEXT,
            evidence_kind TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            artifact_path TEXT,
            artifact_sha256 TEXT,
            artifact_bytes INTEGER,
            artifact_line INTEGER,
            metadata_sha256 TEXT NOT NULL,
            metadata_bytes INTEGER NOT NULL
        );
        CREATE TABLE reviews (
            review_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            decision TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,
            reviewed_at TEXT NOT NULL,
            reason TEXT NOT NULL,
            qualification_status TEXT NOT NULL,
            eligible_for_case INTEGER NOT NULL,
            evidence_reference_ids TEXT NOT NULL,
            supersedes_review_id TEXT
        );
        """
    )
    evidence_rows = []
    for index, evidence_kind in enumerate(
        ("article_body", "discovery_signal", "platform_metric", "review"),
        start=1,
    ):
        evidence_rows.append(
            (
                f"evidence-ref-v3-{index}",
                row["case_id"],
                row["content_hash"],
                "producer-run-v3",
                "tophub" if evidence_kind != "article_body" else "wewe-rss",
                evidence_kind,
                f"https://evidence.example/v3/{index}",
                row["canonical_url"],
                evidence_kind,
                "2026-09-03T00:00:00+00:00",
                "viral-article-cases.jsonl",
                "a" * 64,
                128,
                index,
                "b" * 64,
                256,
            )
        )
    connection.executemany(
        "INSERT INTO evidence_refs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        evidence_rows,
    )
    connection.execute(
        "INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            row["review_decision_id"],
            row["case_id"],
            row["content_hash"],
            "approved",
            "reviewer-v3",
            "2026-09-03T00:02:00+00:00",
            "review reason is not returned",
            "review_ready",
            0,
            json.dumps([evidence[0] for evidence in evidence_rows]),
            None,
        ),
    )
    connection.commit()
    connection.close()

    report = _read_library(root)
    encoded = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "available"
    assert report["schema_version"] == "viral-library-schema-v3"
    assert report["tables"]["optional"]["evidence_refs"]["status"] == "available"
    evidence_refs = report["samples"][0]["evidence_refs"]
    assert {
        evidence["evidence_ref_id"] for evidence in evidence_refs
    } == {f"evidence-ref-v3-{index}" for index in range(1, 5)}
    assert {
        evidence["evidence_kind"] for evidence in evidence_refs
    } == {"article_body", "discovery_signal", "platform_metric", "review"}
    assert all(
        set(evidence) <= {
            "evidence_ref_id",
            "source_run_id",
            "source_key",
            "source_role",
            "locator",
            "canonical_url",
            "evidence_kind",
            "observed_at",
        }
        for evidence in evidence_refs
    )
    assert "review reason is not returned" not in encoded
    assert "safe redacted plaintext" not in encoded


def test_reader_rejects_v3_qualified_library_without_required_evidence_tables(
    tmp_path: Path,
) -> None:
    root = tmp_path / "incomplete-v3-library"
    row = _row(root, case_id="incomplete-v3", status="qualified_viral")
    _create_library(root, [row], schema_version="viral-library-schema-v3")

    report = _read_library(root)

    assert report["status"] == "unavailable"
    assert report["qualified_usable_count"] == 0
    assert report["errors"] == [
        {"code": "LIBRARY_V3_EVIDENCE_UNAVAILABLE"}
    ]


def test_reader_rejects_v3_qualified_library_with_malformed_evidence_proof(
    tmp_path: Path,
) -> None:
    root = tmp_path / "malformed-v3-library"
    row = _row(root, case_id="malformed-v3", status="qualified_viral")
    _create_library(root, [row], schema_version="viral-library-schema-v3")
    connection = sqlite3.connect(root / "library.sqlite")
    connection.executescript(
        """
        CREATE TABLE evidence_refs (
            reference_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            source_run_id TEXT NOT NULL,
            source_key TEXT NOT NULL,
            source_role TEXT NOT NULL,
            locator TEXT,
            canonical_url TEXT,
            evidence_kind TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            artifact_path TEXT,
            artifact_sha256 TEXT,
            artifact_bytes INTEGER,
            artifact_line INTEGER,
            metadata_sha256 TEXT NOT NULL,
            metadata_bytes INTEGER NOT NULL
        );
        CREATE TABLE reviews (
            review_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            decision TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,
            reviewed_at TEXT NOT NULL,
            reason TEXT NOT NULL,
            qualification_status TEXT NOT NULL,
            eligible_for_case INTEGER NOT NULL,
            evidence_reference_ids TEXT NOT NULL,
            supersedes_review_id TEXT
        );
        """
    )
    reference_id = "evidence-ref-malformed"
    connection.execute(
        "INSERT INTO evidence_refs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            reference_id,
            row["case_id"],
            row["content_hash"],
            "producer-run-v3",
            "tophub",
            "discovery_signal",
            "https://evidence.example/v3",
            row["canonical_url"],
            "discovery_signal",
            "2026-09-03T00:00:00+00:00",
            "viral-article-cases.jsonl",
            "not-a-digest",
            128,
            1,
            "b" * 64,
            256,
        ),
    )
    connection.execute(
        "INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            row["review_decision_id"],
            row["case_id"],
            row["content_hash"],
            "approved",
            "reviewer-v3",
            "2026-09-03T00:02:00+00:00",
            "review reason",
            "qualified_viral",
            1,
            json.dumps([reference_id]),
            None,
        ),
    )
    connection.commit()
    connection.close()

    report = _read_library(root)

    assert report["status"] == "unavailable"
    assert report["qualified_usable_count"] == 0
    assert report["errors"] == [
        {"code": "LIBRARY_V3_EVIDENCE_INVALID", "case_id": "malformed-v3"}
    ]


def test_reader_rejects_v3_qualified_row_with_ineligible_state(tmp_path: Path) -> None:
    root = tmp_path / "ineligible-v3-library"
    row = _row(
        root,
        case_id="ineligible-v3",
        status="qualified_viral",
        eligible_for_case=False,
    )
    _create_library(root, [row], schema_version="viral-library-schema-v3")
    _add_v3_proof_tables(root, row)

    report = _read_library(root)

    assert report["status"] == "unavailable"
    assert report["qualified_usable_count"] == 0
    assert report["errors"] == [
        {
            "code": "LIBRARY_QUALIFICATION_ELIGIBILITY_INVALID",
            "case_id": "ineligible-v3",
        }
    ]


def test_reader_rejects_v3_review_that_does_not_cover_all_evidence_kinds(
    tmp_path: Path,
) -> None:
    root = tmp_path / "partial-review-v3-library"
    row = _row(root, case_id="partial-review-v3", status="qualified_viral")
    _create_library(root, [row], schema_version="viral-library-schema-v3")
    _add_v3_proof_tables(
        root,
        row,
        review_reference_ids=["evidence-ref-helper-1"],
    )

    report = _read_library(root)

    assert report["status"] == "unavailable"
    assert report["qualified_usable_count"] == 0
    assert report["errors"] == [
        {
            "code": "LIBRARY_V3_REVIEW_EVIDENCE_INCOMPLETE",
            "case_id": "partial-review-v3",
        }
    ]


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("reviewer_id", "   "),
        ("reviewed_at", "not-an-iso-time"),
        ("reason", "   "),
    ],
)
def test_reader_rejects_v3_review_with_invalid_audit_metadata(
    tmp_path: Path,
    field_name: str,
    field_value: str,
) -> None:
    root = tmp_path / f"invalid-review-{field_name}-v3-library"
    row = _row(root, case_id=f"invalid-{field_name}-v3", status="qualified_viral")
    _create_library(root, [row], schema_version="viral-library-schema-v3")
    _add_v3_proof_tables(root, row, **{field_name: field_value})

    report = _read_library(root)

    assert report["status"] == "unavailable"
    assert report["qualified_usable_count"] == 0
    assert report["errors"] == [
        {"code": "LIBRARY_V3_REVIEW_INVALID", "case_id": row["case_id"]}
    ]
