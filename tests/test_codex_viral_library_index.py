from __future__ import annotations

import json
from pathlib import Path

from scripts.codex_viral_library_index import build_index, main


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _write_card(
    root: Path,
    run: Path,
    sample_id: str,
    status: str,
    snapshot_ref: str,
    performance_ref: str,
) -> None:
    _write_json(
        root / run / "wechat-viral" / "cards" / f"{sample_id}.json",
        {
            "sample_id": sample_id,
            "qualification_status": status,
            "snapshot_ref": f"`{snapshot_ref}#sha256={'a' * 64}`",
            "performance_evidence_ref": performance_ref,
            "technique_observations": [{"technique_id": "WX-O1"}],
        },
    )


def test_index_reports_legacy_duplicate_files(tmp_path: Path) -> None:
    content = "# same legacy note\n"
    first = tmp_path / "ruoyu-content/10-case-library/爆款案例库_清理版.md"
    second = tmp_path / "ruoyu-system/爆款案例库_清理版.md"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text(content, encoding="utf-8")
    second.write_text(content, encoding="utf-8")

    result = build_index(tmp_path, "runs/missing")

    assert result["legacy_library"]["preferred_entry_dir"] == "ruoyu-content/10-case-library"
    assert len(result["legacy_library"]["files"]) == 2
    assert len(result["legacy_library"]["duplicate_groups"]) == 1
    assert result["evidence_library"]["status"] == "unavailable"
    assert "viral_library" not in result


def test_index_keeps_qualification_and_evidence_boundaries(tmp_path: Path) -> None:
    run = Path("runs/test-run/viral-research")
    raw = tmp_path / run / "raw_articles" / "sample.md"
    metric = tmp_path / run / "wechat-viral" / "metrics" / "qualified.json"
    raw.parent.mkdir(parents=True)
    metric.parent.mkdir(parents=True)
    raw.write_text("# captured full text\n", encoding="utf-8")
    metric.write_text("{\"source\": \"client\"}\n", encoding="utf-8")

    _write_card(
        tmp_path,
        run,
        "qualified",
        "qualified_viral",
        "raw_articles/sample.md",
        "wechat-viral/metrics/qualified.json",
    )
    _write_card(
        tmp_path,
        run,
        "pending",
        "observed_pending",
        "raw_articles/missing.md",
        "wechat-viral/metrics/missing.json",
    )
    manifest = tmp_path / run / "raw_articles/MANIFEST.md"
    manifest.write_text("覆盖共 2 篇\n", encoding="utf-8")
    _write_json(
        tmp_path / run / "wechat-viral/distillation/wx-candidates-20260811.json",
        [{"frequency": 3}, {"frequency": 1}],
    )

    result = build_index(tmp_path, run)
    pack = result["evidence_library"]["packs"][0]

    assert pack["qualification_status_counts"] == {
        "observed_pending": 1,
        "qualified_viral": 1,
    }
    assert pack["qualified_usable_count"] == 1
    assert pack["qualified_missing_evidence"] == []
    assert pack["distillation"]["candidate_count"] == 2
    assert pack["distillation"]["promotion_status"] == "provisional_only"
    assert result["policy"]["observation_only_statuses"] == [
        "observed_pending",
        "research_only",
    ]


def test_qualified_card_with_missing_refs_is_unavailable(tmp_path: Path) -> None:
    run = Path("runs/test-run/viral-research")
    _write_card(
        tmp_path,
        run,
        "missing-qualified",
        "qualified_viral",
        "raw_articles/nope.md",
        "wechat-viral/metrics/nope.json",
    )

    result = build_index(tmp_path, run)
    pack = result["evidence_library"]["packs"][0]

    assert pack["qualified_usable_count"] == 0
    assert pack["qualified_missing_evidence"] == [
        {"sample_id": "missing-qualified", "missing": ["snapshot", "performance_evidence"]}
    ]


def test_cli_does_not_inventory_sensitive_files(tmp_path: Path, capsys) -> None:
    (tmp_path / ".env").write_text("OPENAI_API_KEY=must-not-appear\n", encoding="utf-8")
    (tmp_path / "auth.json").write_text('{"token":"must-not-appear"}\n', encoding="utf-8")
    (tmp_path / "ruoyu-content/10-case-library").mkdir(parents=True)
    (tmp_path / "ruoyu-content/10-case-library/notes.md").write_text(
        "# notes\n", encoding="utf-8"
    )

    assert main(["--project-root", str(tmp_path), "--evidence-run", "runs/missing"]) == 0
    output = capsys.readouterr().out
    parsed = json.loads(output)

    assert "must-not-appear" not in output
    assert "auth.json" not in output
    assert parsed["policy"]["credential_policy"] == "never_read_or_copy"


def test_bilibili_manifest_is_indexed_as_observation_shape(tmp_path: Path) -> None:
    run = Path("runs/test-run/viral-research")
    pack = tmp_path / run / "bilibili-public-metrics"
    _write_json(
        pack / "case-manifest.json",
        {
            "sample_count": 1,
            "qualified_viral_count": 1,
            "samples": [
                {
                    "sample_id": "cv-one",
                    "qualification_status": "qualified_viral",
                    "card_ref": "cards/cv-one.json",
                    "snapshot_ref": "sources/cv-one.clean.md#sha256=abc",
                    "performance_evidence_ref": "metrics/cv-one.api.json",
                }
            ],
        },
    )
    (pack / "sources").mkdir()
    (pack / "metrics").mkdir()
    (pack / "sources/cv-one.clean.md").write_text("full text\n", encoding="utf-8")
    (pack / "metrics/cv-one.api.json").write_text("{}\n", encoding="utf-8")

    result = build_index(tmp_path, run)
    bilibili = result["evidence_library"]["packs"][1]

    assert bilibili["qualified_usable_count"] == 1
    assert bilibili["shape_policy"] == "observation_only_for_ruoyu_title_rules"


def test_index_can_add_persistent_library_without_exposing_content(tmp_path: Path) -> None:
    import hashlib
    import sqlite3

    library_root = tmp_path / "viral-library"
    body = "脱敏持久库正文不得出现在索引"
    content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    snapshot = library_root / "snapshots/wechat" / f"{content_hash}.txt"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text(body, encoding="utf-8")
    library_root.mkdir(exist_ok=True)
    connection = sqlite3.connect(library_root / "library.sqlite")
    connection.executescript(
        """
        CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE cases (
            case_id TEXT PRIMARY KEY, platform TEXT NOT NULL, canonical_url TEXT NOT NULL,
            first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
            UNIQUE(platform, canonical_url)
        );
        CREATE TABLE case_versions (
            case_id TEXT NOT NULL, platform TEXT NOT NULL, canonical_url TEXT NOT NULL,
            content_hash TEXT NOT NULL, snapshot_relpath TEXT NOT NULL,
            snapshot_bytes INTEGER NOT NULL, snapshot_sha256 TEXT NOT NULL,
            account_id TEXT, account_name TEXT, title TEXT, published_at TEXT,
            source_run_id TEXT NOT NULL, qualification_status TEXT NOT NULL,
            eligible_for_case INTEGER NOT NULL, is_republished INTEGER,
            review_decision_id TEXT, version_of TEXT, ingested_at TEXT NOT NULL,
            PRIMARY KEY(case_id, content_hash), UNIQUE(platform, canonical_url, content_hash)
        );
        CREATE TABLE case_observations (
            source_run_id TEXT NOT NULL, case_id TEXT NOT NULL,
            content_hash TEXT NOT NULL, observed_at TEXT NOT NULL,
            PRIMARY KEY(source_run_id, case_id, content_hash)
        );
        """
    )
    connection.execute(
        "INSERT INTO schema_meta(key, value) VALUES ('schema_version', 'viral-library-schema-v1')"
    )
    connection.execute(
        "INSERT INTO cases VALUES (?, ?, ?, ?, ?)",
        ("safe-case", "wechat", "https://mp.weixin.qq.com/s/safe", "now", "now"),
    )
    connection.execute(
        """
        INSERT INTO case_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "safe-case", "wechat", "https://mp.weixin.qq.com/s/safe", content_hash,
            f"snapshots/wechat/{content_hash}.txt", len(body.encode("utf-8")), content_hash,
            "account-safe", "SECRET ACCOUNT", "SECRET TITLE", "2026-09-03T00:00:00+00:00",
            "run-safe", "qualified_viral", 1, 0, "review-safe", None,
            "2026-09-03T00:01:00+00:00",
        ),
    )
    connection.execute(
        "INSERT INTO case_observations VALUES (?, ?, ?, ?)",
        ("run-safe", "safe-case", content_hash, "2026-09-03T00:00:00+00:00"),
    )
    connection.commit()
    connection.close()

    result = build_index(tmp_path, "runs/missing", viral_library_root=library_root)
    encoded = json.dumps(result, ensure_ascii=False)

    assert result["evidence_library"]["status"] == "unavailable"
    assert result["viral_library"]["status"] == "available"
    assert result["viral_library"]["qualified_usable_count"] == 1
    assert "脱敏持久库正文不得出现在索引" not in encoded
    assert "SECRET ACCOUNT" not in encoded
    assert "SECRET TITLE" not in encoded


def test_index_cli_writes_optional_output_and_accepts_library_root(
    tmp_path: Path, capsys
) -> None:
    import hashlib
    import sqlite3

    library_root = tmp_path / "empty-library"
    library_root.mkdir()
    connection = sqlite3.connect(library_root / "library.sqlite")
    connection.executescript(
        """
        CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE cases (
            case_id TEXT PRIMARY KEY, platform TEXT NOT NULL, canonical_url TEXT NOT NULL,
            first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
            UNIQUE(platform, canonical_url)
        );
        CREATE TABLE case_versions (
            case_id TEXT NOT NULL, platform TEXT NOT NULL, canonical_url TEXT NOT NULL,
            content_hash TEXT NOT NULL, snapshot_relpath TEXT NOT NULL,
            snapshot_bytes INTEGER NOT NULL, snapshot_sha256 TEXT NOT NULL,
            account_id TEXT, account_name TEXT, title TEXT, published_at TEXT,
            source_run_id TEXT NOT NULL, qualification_status TEXT NOT NULL,
            eligible_for_case INTEGER NOT NULL, is_republished INTEGER,
            review_decision_id TEXT, version_of TEXT, ingested_at TEXT NOT NULL,
            PRIMARY KEY(case_id, content_hash), UNIQUE(platform, canonical_url, content_hash)
        );
        CREATE TABLE case_observations (
            source_run_id TEXT NOT NULL, case_id TEXT NOT NULL,
            content_hash TEXT NOT NULL, observed_at TEXT NOT NULL,
            PRIMARY KEY(source_run_id, case_id, content_hash)
        );
        INSERT INTO schema_meta(key, value) VALUES ('schema_version', 'viral-library-schema-v1');
        """
    )
    connection.commit()
    connection.close()
    output = tmp_path / "run" / "library-index.json"

    assert (
        main(
            [
                "--project-root",
                str(tmp_path),
                "--evidence-run",
                "runs/missing",
                "--viral-library-root",
                str(library_root),
                "--output",
                str(output),
                "--compact",
            ]
        )
        == 0
    )

    stdout = capsys.readouterr().out.strip()
    assert output.is_file()
    output_text = output.read_text(encoding="utf-8")
    assert json.loads(stdout) == json.loads(output_text)
    assert hashlib.sha256((output_text).encode("utf-8")).hexdigest() == hashlib.sha256(
        (stdout + "\n").encode("utf-8")
    ).hexdigest()
    assert "viral_library" in json.loads(stdout)


def test_index_cli_refuses_output_inside_external_library_root(
    tmp_path: Path, capsys
) -> None:
    library_root = tmp_path / "external-library"
    library_root.mkdir()
    database = library_root / "library.sqlite"
    sentinel = b"external library database must remain untouched"
    database.write_bytes(sentinel)

    assert (
        main(
            [
                "--project-root",
                str(tmp_path),
                "--evidence-run",
                "runs/missing",
                "--viral-library-root",
                str(library_root),
                "--output",
                str(database),
            ]
        )
        == 2
    )

    assert database.read_bytes() == sentinel
    assert capsys.readouterr().out.strip() == "output_readback_failed"
