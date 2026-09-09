from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from scripts.codex_viral_library_context import build_library_context, main


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

UNIQUE_FIXTURE_STRINGS = (
    "FIXTURE_TITLE 李雷 42",
    "FIXTURE_BODY 李雷 42 \"quoted\"",
    "https://fixture.invalid/article?token=secret",
    "FIXTURE_ACCOUNT 李雷",
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _make_row(
    root: Path,
    *,
    case_id: str,
    status: str = "qualified_viral",
    account_id: str | None = None,
    platform: str = "wechat",
    eligible_for_case: bool = True,
    is_republished: int | None = 0,
    body: str | bytes | None = None,
    write_snapshot: bool = True,
    snapshot_sha256: str | None = None,
) -> dict[str, object]:
    if body is None:
        body = (
            "标题句\n\n"
            "冲突与问题？这一段提供场景和上下文。\n\n"
            "随后转向分析，并保留一个互动问题？"
        )
    encoded = body.encode("utf-8") if isinstance(body, str) else body
    content_hash = _sha256(encoded)
    relative = f"snapshots/{platform}/{content_hash}.txt"
    snapshot_path = root / relative
    if write_snapshot:
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_bytes(encoded)
    return {
        "case_id": case_id,
        "platform": platform,
        "canonical_url": f"https://mp.weixin.qq.com/s/{case_id}",
        "content_hash": content_hash,
        "snapshot_relpath": relative,
        "snapshot_bytes": len(encoded),
        "snapshot_sha256": snapshot_sha256 or content_hash,
        "account_id": account_id or f"account-{case_id}",
        "account_name": "FIXTURE_ACCOUNT 李雷",
        "title": "FIXTURE_TITLE 李雷 42",
        "published_at": "2026-09-03T00:00:00+00:00",
        "source_run_id": f"run-{case_id}",
        "qualification_status": status,
        "eligible_for_case": int(eligible_for_case),
        "is_republished": is_republished,
        "review_decision_id": f"review-{case_id}",
        "version_of": None,
        "ingested_at": "2026-09-03T00:01:00+00:00",
    }


def _create_library(
    root: Path,
    rows: list[dict[str, object]],
    *,
    include_refs: bool = True,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(root / "library.sqlite")
    connection.executescript(CORE_SCHEMA)
    connection.execute(
        "INSERT INTO schema_meta(key, value) VALUES (?, ?)",
        ("schema_version", "viral-library-schema-v1"),
    )
    if include_refs:
        connection.executescript(
            """
            CREATE TABLE evidence_refs (
                evidence_ref_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                content_hash TEXT,
                source_run_id TEXT,
                source_key TEXT,
                source_role TEXT,
                locator TEXT,
                canonical_url TEXT,
                evidence_kind TEXT,
                observed_at TEXT
            );
            CREATE TABLE reviews (
                review_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                content_hash TEXT,
                decision TEXT,
                reviewer_id TEXT,
                reviewed_at TEXT
            );
            """
        )
    columns = (
        "case_id, platform, canonical_url, content_hash, snapshot_relpath,"
        " snapshot_bytes, snapshot_sha256, account_id, account_name, title,"
        " published_at, source_run_id, qualification_status, eligible_for_case,"
        " is_republished, review_decision_id, version_of, ingested_at"
    )
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
        if include_refs:
            connection.execute(
                """
                INSERT INTO evidence_refs(
                    evidence_ref_id, case_id, content_hash, source_run_id,
                    source_key, source_role, locator, canonical_url,
                    evidence_kind, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"evidence-{row['case_id']}",
                    row["case_id"],
                    row["content_hash"],
                    row["source_run_id"],
                    "metrics-record",
                    "platform_metric_evidence",
                    "metrics/record.json#sha256=abc",
                    "https://evidence.invalid/record",
                    "performance",
                    row["ingested_at"],
                ),
            )
            connection.execute(
                """
                INSERT INTO reviews(
                    review_id, case_id, content_hash, decision,
                    reviewer_id, reviewed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"review-{row['case_id']}",
                    row["case_id"],
                    row["content_hash"],
                    "approved",
                    "reviewer-safe",
                    "2026-09-03T00:02:00+00:00",
                ),
            )
    connection.commit()
    connection.close()


def _read_output(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _all_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for key in value for item in _all_strings(key)] + [
            item for item in value.values() for item in _all_strings(item)
        ]
    if isinstance(value, list):
        return [item for item in value for item in _all_strings(item)]
    return []


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _all_keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _all_keys(item)}
    return set()


def test_context_is_structured_and_does_not_leak_fixture_content(tmp_path: Path) -> None:
    root = tmp_path / "viral-library"
    body = (
        "FIXTURE_BODY 李雷 42 \"quoted\" "
        "https://fixture.invalid/article?token=secret\n\n"
        "这个开头提出问题？随后交代场景。\n\n"
        "转折之后给出分析与证据，最后邀请互动？"
    )
    row = _make_row(root, case_id="qualified-safe", body=body)
    _create_library(root, [row])
    output = tmp_path / "runs" / "context.json"

    result = build_library_context(root, output)
    encoded = json.dumps(result, ensure_ascii=False)

    assert result["status"] == "available"
    assert result["schema_version"] == "codex-viral-library-context-v1"
    assert result["positive_samples"]
    sample = result["positive_samples"][0]
    assert sample["title_strategy"] in {
        "question",
        "contrast",
        "event",
        "statement",
        "unknown",
    }
    assert sample["opening_hook"]["type"] in {"conflict", "question", "scene", "claim", "unknown"}
    assert sample["opening_hook"]["length_bucket"] in {"short", "medium", "long"}
    assert set(sample["structure_outline"]) <= {
        "hook",
        "context",
        "turn",
        "analysis",
        "evidence",
        "close",
    }
    assert len(sample["structure_outline"]) <= 8
    assert sample["closing_action"] in {
        "question",
        "interaction",
        "insight",
        "summary",
        "none",
        "unknown",
    }
    assert _read_output(output) == result
    assert all(
        needle not in value
        for value in _all_strings(result)
        for needle in UNIQUE_FIXTURE_STRINGS
    )
    assert all(needle not in encoded for needle in UNIQUE_FIXTURE_STRINGS)
    assert not {
        "title",
        "account_name",
        "account_id",
        "canonical_url",
        "body",
        "raw_url",
        "url",
        "source_run_id",
    } & _all_keys(result)


def test_only_qualified_samples_enter_and_accounts_are_deduplicated(tmp_path: Path) -> None:
    root = tmp_path / "viral-library"
    rows = [
        _make_row(
            root,
            case_id="qualified-a-first",
            account_id="account-a",
            body="首个样本提出问题？随后交代背景。最后邀请互动？",
        ),
        _make_row(
            root,
            case_id="qualified-a-second",
            account_id="account-a",
            body="第二个样本提出问题？随后交代背景。最后邀请互动？",
        ),
        _make_row(
            root,
            case_id="qualified-b",
            account_id="account-b",
            body="另一个账号提出问题？随后交代背景。最后邀请互动？",
        ),
        _make_row(root, case_id="pending", status="observed_pending", account_id="account-p"),
        _make_row(root, case_id="research", status="research_only", account_id="account-r"),
        _make_row(root, case_id="ineligible", eligible_for_case=False, account_id="account-i"),
        _make_row(root, case_id="republished", is_republished=1, account_id="account-x"),
        _make_row(root, case_id="other-platform", platform="bilibili", account_id="account-z"),
    ]
    _create_library(root, rows)

    result = build_library_context(root, tmp_path / "context.json")
    sample_ids = [sample["sample_id"] for sample in result["positive_samples"]]
    content_hashes = {sample["content_hash"] for sample in result["positive_samples"]}

    assert result["status"] == "available"
    assert len(sample_ids) == 2
    assert len(
        {rows[0]["content_hash"], rows[1]["content_hash"]} & content_hashes
    ) == 1
    assert rows[2]["content_hash"] in content_hashes
    assert all(sample_id.startswith("sample-") for sample_id in sample_ids)
    assert len(result["positive_samples"]) <= 3


def test_one_sample_reports_insufficient_diversity(tmp_path: Path) -> None:
    root = tmp_path / "viral-library"
    _create_library(root, [_make_row(root, case_id="only-sample")])

    result = build_library_context(root, tmp_path / "context.json")

    assert result["positive_samples"]
    assert "insufficient_diversity" in result["limitations"]


@pytest.mark.parametrize(
    "row_kwargs",
    [
        {"write_snapshot": False},
        {"snapshot_sha256": "0" * 64},
        {"body": b"\xff\xfe"},
    ],
)
def test_corrupt_or_missing_snapshot_makes_context_unavailable(
    tmp_path: Path, row_kwargs: dict[str, object]
) -> None:
    root = tmp_path / "viral-library"
    row = _make_row(root, case_id="broken", **row_kwargs)
    _create_library(root, [row])

    result = build_library_context(root, tmp_path / "context.json")

    assert result["status"] == "unavailable"
    assert result["positive_samples"] == []
    assert result["reason"]
    assert _read_output(tmp_path / "context.json") == result


def test_snapshot_above_classifier_bound_is_unavailable_without_fallback(tmp_path: Path) -> None:
    root = tmp_path / "viral-library"
    oversized = "x" * (64 * 1024 + 1)
    _create_library(root, [_make_row(root, case_id="oversized", body=oversized)])

    result = build_library_context(root, tmp_path / "context.json")

    assert result["status"] == "unavailable"
    assert result["positive_samples"] == []
    assert "SNAPSHOT_TOO_LARGE_FOR_CLASSIFIER" in result["reason"]


def test_no_match_is_truthful_and_topic_is_not_leaked(tmp_path: Path) -> None:
    root = tmp_path / "viral-library"
    _create_library(root, [_make_row(root, case_id="unrelated")])
    topic = "TOPIC_SECRET 李雷 4242 \"quoted\" https://topic.invalid/q?x=1"

    result = build_library_context(
        root,
        tmp_path / "context.json",
        current_topic=topic,
        current_brief="A brief with the same private topic token",
    )
    encoded = json.dumps(result, ensure_ascii=False)

    assert result["status"] == "available"
    assert result["positive_samples"] == []
    assert result["reason"] == "no_topic_matching_samples"
    assert result["input"]["topic_match"] == "unknown"
    assert topic not in encoded


def test_current_topic_can_label_without_being_copied(tmp_path: Path) -> None:
    root = tmp_path / "viral-library"
    topic = "TOPIC_SECRET 李雷 4242 \"quoted\" https://topic.invalid/q?x=1"
    body = f"标题句\n\n围绕 {topic} 展开冲突与分析。"
    _create_library(root, [_make_row(root, case_id="related", body=body)])

    result = build_library_context(
        root,
        tmp_path / "context.json",
        current_topic=topic,
    )
    encoded = json.dumps(result, ensure_ascii=False)

    assert result["positive_samples"]
    assert result["input"]["topic_match"] in {"broad", "related"}
    assert result["positive_samples"][0]["topic_match"] in {"broad", "related"}
    assert topic not in encoded


def test_output_inside_library_is_rejected_without_touching_database(tmp_path: Path) -> None:
    root = tmp_path / "viral-library"
    row = _make_row(root, case_id="conflict")
    _create_library(root, [row])
    database = root / "library.sqlite"
    before = database.read_bytes()

    with pytest.raises(ValueError, match="CONTEXT_OUTPUT_EXTERNAL_LIBRARY_CONFLICT"):
        build_library_context(root, root / "context.json")

    assert database.read_bytes() == before
    assert not (root / "context.json").exists()


def test_cli_help_mentions_required_library_context_flags(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--help"])

    assert raised.value.code == 0
    help_text = capsys.readouterr().out
    assert "--viral-library-root" in help_text
    assert "--output" in help_text
    assert "--topic" in help_text
