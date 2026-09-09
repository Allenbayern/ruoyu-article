from __future__ import annotations

import importlib
import hashlib
import json
import os
from datetime import date
from pathlib import Path
import sqlite3
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


LIBRARY_CORE_SCHEMA = """
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


def _load(module_name: str):
    return importlib.import_module(module_name)


def test_newrank_watch_missing_token_is_stable_and_side_effect_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load("scripts.codex_newrank_watch")
    output_root = tmp_path / "newrank"
    monkeypatch.delenv("NEWRANK_N_TOKEN", raising=False)

    result = module.main(["--days", "1", "--output-root", str(output_root)])

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == "source_unavailable\n"
    assert captured.err == ""
    assert not output_root.exists()


def test_newrank_watch_uses_runtime_token_and_immutable_date_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load("scripts.codex_newrank_watch")
    output_root = tmp_path / "newrank"
    seen: dict[str, object] = {}
    monkeypatch.setenv("NEWRANK_N_TOKEN", "runtime-token-that-must-not-print")
    monkeypatch.setattr(module, "_today", lambda: date(2026, 8, 25))

    class FakeCollector:
        def __init__(self, *, n_token: str) -> None:
            seen["token"] = n_token

        def collect(self, public_times: list[str], output: Path) -> dict[str, object]:
            seen["public_times"] = public_times
            seen["output"] = output
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text('{"status":"ok"}\n', encoding="utf-8")
            output.with_name(output.name + ".manifest.json").write_text(
                '{"status":"ok"}\n', encoding="utf-8"
            )
            return {"status": "ok"}

    monkeypatch.setattr(module.newrank_hot_article, "NewrankCollector", FakeCollector)

    first = module.main(["--days", "2", "--output-root", str(output_root)])
    first_output = output_root / "2026-08-25" / "newrank-hot-articles.json"
    second = module.main(["--days", "2", "--output-root", str(output_root)])

    captured = capsys.readouterr()
    assert first == 0
    assert second == 2
    assert seen["token"] == "runtime-token-that-must-not-print"
    assert seen["public_times"] == ["2026-08-25", "2026-08-24"]
    assert seen["output"] == first_output
    assert "runtime-token-that-must-not-print" not in captured.out
    assert first_output.read_text(encoding="utf-8") == '{"status":"ok"}\n'


def test_daily_article_runner_requires_explicit_producer_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load("scripts.codex_daily_article_runner")

    result = module.main(
        [
            "--producer-run-root",
            str(tmp_path / "missing-producer"),
            "--output-root",
            str(tmp_path / "run"),
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == "producer_unavailable\n"
    assert captured.err == ""


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_valid_library(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True)
    body = b"bounded structural fixture\n"
    content_hash = hashlib.sha256(body).hexdigest()
    snapshot = root / "snapshots" / "wechat" / f"{content_hash}.txt"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_bytes(body)
    connection = sqlite3.connect(root / "library.sqlite")
    connection.executescript(LIBRARY_CORE_SCHEMA)
    connection.execute(
        "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?)",
        ("viral-library-schema-v1",),
    )
    connection.execute(
        "INSERT INTO cases(case_id, platform, canonical_url, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?)",
        (
            "case-success",
            "wechat",
            "https://mp.weixin.qq.com/s/case-success",
            "2026-09-03T00:00:00+00:00",
            "2026-09-03T00:00:00+00:00",
        ),
    )
    connection.execute(
        """
        INSERT INTO case_versions(
            case_id, platform, canonical_url, content_hash, snapshot_relpath,
            snapshot_bytes, snapshot_sha256, account_id, account_name, title,
            published_at, source_run_id, qualification_status, eligible_for_case,
            is_republished, review_decision_id, version_of, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "case-success",
            "wechat",
            "https://mp.weixin.qq.com/s/case-success",
            content_hash,
            snapshot.relative_to(root).as_posix(),
            len(body),
            content_hash,
            "account-success",
            "fixture-account",
            "fixture-title",
            "2026-09-03T00:00:00+00:00",
            "run-case-success",
            "qualified_viral",
            1,
            0,
            "review-case-success",
            None,
            "2026-09-03T00:01:00+00:00",
        ),
    )
    connection.execute(
        "INSERT INTO case_observations(source_run_id, case_id, content_hash, observed_at) VALUES (?, ?, ?, ?)",
        (
            "run-case-success",
            "case-success",
            content_hash,
            "2026-09-03T00:01:00+00:00",
        ),
    )
    connection.commit()
    connection.close()
    return root / "library.sqlite", snapshot


def _write_producer_package(
    root: Path,
    *,
    library_root: Path | None = None,
    library_context_status: str = "not_requested",
    declared_required_files: list[str] | None = None,
) -> tuple[Path, Path]:
    root.mkdir(parents=True)
    research_dir = root / "research" / "2026-08-31" / "article-research-001"
    research_dir.mkdir(parents=True)
    (research_dir / "run-manifest.json").write_text(
        '{"schema":"producer-research-manifest","run_id":"article-research-001"}\n',
        encoding="utf-8",
    )
    research_manifest = research_dir / "run-manifest.json"
    artifact_names = [
        "article-approved-latest.md",
        "director-review.md",
        "latest-feedback.md",
        "today-hook-dispatch.md",
        "today-hook-dispatch.jsonl",
        "reference-candidate-export.jsonl",
        "source-audit.json",
        "retry-state.json",
        "verification.json",
        "viral-topic-signals.jsonl",
        "article-candidates.jsonl",
        "viral-article-cases.jsonl",
    ]
    for name in artifact_names:
        path = root / name
        path.write_text(
            "{}\n" if path.suffix == ".json" else "",
            encoding="utf-8",
        )
    handoff = root / "article-research-handoff.json"
    handoff.write_text(
        json.dumps(
            {
                "schema": "media-intel-article-research-handoff/v1",
                "kind": "producer_handoff",
                "daily_run_id": "daily-001",
                "research_run_id": "article-research-001",
                "research_status": "PASS",
                "library_intake_status": "PASS",
                "library_context_status": library_context_status,
                "library_context_reason": (
                    "context_deferred_to_active_consumer"
                    if library_context_status == "pending_consumer"
                    else "context_consumer_not_run"
                ),
                "library_root": str(library_root) if library_root is not None else None,
                "library_readback": {
                    "status": library_context_status,
                    "reason": "context_deferred_to_active_consumer"
                    if library_context_status == "pending_consumer"
                    else "library_root_not_configured",
                    "root": str(library_root) if library_root is not None else None,
                    "schema": "viral-library-intake/v1",
                    "database": {
                        "path": str(library_root / "library.sqlite")
                        if library_root is not None
                        else None,
                        "sha256": None,
                        "readback": {"verified": False},
                    },
                    "snapshot_readback": {
                        "verified": False,
                        "checked": 0,
                        "failed": 0,
                    },
                },
                "research_output_dir": str(research_dir),
                "research_manifest": {
                    "path": str(research_manifest),
                    "sha256": _digest(research_manifest),
                    "readback": {"verified": True},
                },
                "research_retry_required": False,
                "library_retry_required": False,
                "publication_authorized": False,
                "publication_performed": False,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    summary = root / "run_summary.json"
    summary.write_text(
        json.dumps(
            {
                "status": "BLOCKED",
                "execution_status": "PASS",
                "date": "2026-08-31",
                "lane": "article",
                "run_id": "daily-001",
                "research_status": "PASS",
                "library_intake_status": "PASS",
                "library_context_status": library_context_status,
                "library_context_reason": (
                    "context_deferred_to_active_consumer"
                    if library_context_status == "pending_consumer"
                    else "context_consumer_not_run"
                ),
                "library_root": str(library_root) if library_root is not None else None,
                "publication_authorized": False,
                "publication_performed": False,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    all_files = sorted(
        path for path in root.rglob("*") if path.is_file()
    )
    artifact_hashes = {
        path.relative_to(root).as_posix(): "sha256:" + _digest(path)
        for path in all_files
    }
    artifact_hashes["run-manifest.json"] = ""
    manifest = {
        "schema": "media-intel-run-manifest/v1",
        "run_id": "daily-001",
        "date": "2026-08-31",
        "lane": "article",
        "contract_version": "article-capture-contract/v1",
        "generated_at": "2026-08-31T00:00:00+00:00",
        "required_files": sorted(
            declared_required_files
            if declared_required_files is not None
            else [*artifact_hashes.keys(), "run-manifest.json"]
        ),
        "artifact_hashes": artifact_hashes,
        "files": [
            {"path": name, "sha256": digest}
            for name, digest in sorted(artifact_hashes.items())
        ],
    }
    blank = json.loads(json.dumps(manifest, ensure_ascii=False))
    for row in blank["files"]:
        if row["path"] == "run-manifest.json":
            row["sha256"] = ""
    blank["artifact_hashes"]["run-manifest.json"] = ""
    self_hash = "sha256:" + hashlib.sha256(
        (json.dumps(blank, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    ).hexdigest()
    manifest["artifact_hashes"]["run-manifest.json"] = self_hash
    for row in manifest["files"]:
        if row["path"] == "run-manifest.json":
            row["sha256"] = self_hash
    producer_manifest = root / "run-manifest.json"
    producer_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return producer_manifest, handoff


def test_daily_article_runner_accepts_current_producer_core_manifest_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load("scripts.codex_daily_article_runner")
    producer_root = tmp_path / "producer-run"
    required = [
        "article-candidates.jsonl",
        "article-research-handoff.json",
        "retry-state.json",
        "run_summary.json",
        "source-audit.json",
        "verification.json",
        "viral-article-cases.jsonl",
        "viral-topic-signals.jsonl",
    ]
    _write_producer_package(
        producer_root,
        declared_required_files=required,
    )
    monkeypatch.delenv("MEDIA_INTEL_VIRAL_LIBRARY_ROOT", raising=False)

    result = module.main(
        [
            "--producer-run-root",
            str(producer_root),
            "--output-root",
            str(tmp_path / "consumer-run"),
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert json.loads(
        (tmp_path / "consumer-run" / "codex-daily-article-run.json").read_text(
            encoding="utf-8"
        )
    )["producer"]["run_id"] == "daily-001"


def test_daily_article_runner_consumes_explicit_producer_read_only_and_separates_manifests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load("scripts.codex_daily_article_runner")
    producer_root = tmp_path / "producer-run"
    library_root = tmp_path / "library"
    producer_manifest, handoff = _write_producer_package(
        producer_root,
        library_root=library_root,
    )
    consumer_root = tmp_path / "consumer-run"
    library_root.mkdir()
    before = sorted(path.relative_to(producer_root).as_posix() for path in producer_root.rglob("*"))
    monkeypatch.setenv("MEDIA_INTEL_VIRAL_LIBRARY_ROOT", str(library_root))

    result = module.main(
        [
            "--producer-run-root",
            str(producer_root),
            "--output-root",
            str(consumer_root),
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    manifest = json.loads(
        (consumer_root / "codex-daily-article-run.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "candidate_evidence_only"
    assert manifest["producer"]["run_id"] == "daily-001"
    assert manifest["producer"]["manifest"]["sha256"] == _digest(producer_manifest)
    assert manifest["producer"]["handoff"]["sha256"] == _digest(handoff)
    assert manifest["research_status"] == "PASS"
    assert manifest["library_intake_status"] == "PASS"
    assert manifest["library_context_status"] == "unavailable"
    assert manifest["library_root"] == str(library_root)
    assert manifest["library"]["reader"]["status"] == "unavailable"
    assert manifest["library"]["reader"]["readback"]["verified"] is False
    assert manifest["library"]["context"]["status"] == "unavailable"
    assert manifest["library"]["context"]["readback"]["verified"] is True
    assert manifest["library"]["index"]["status"] == "unavailable"
    assert manifest["library"]["readback"]["verified"] is False
    assert manifest["publication_authorized"] is False
    assert manifest["publication_performed"] is False
    library_output = Path(manifest["library"]["output_root"])
    assert library_output != consumer_root.resolve()
    assert consumer_root.resolve() not in library_output.parents
    assert producer_root.resolve() not in library_output.parents
    assert library_root.resolve() not in library_output.parents
    after = sorted(path.relative_to(producer_root).as_posix() for path in producer_root.rglob("*"))
    assert before == after


def test_daily_article_runner_reads_valid_library_and_records_external_readbacks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load("scripts.codex_daily_article_runner")
    producer_root = tmp_path / "producer-run"
    producer_manifest, handoff = _write_producer_package(
        producer_root,
        library_root=tmp_path / "library",
        library_context_status="pending_consumer",
    )
    library_root = tmp_path / "library"
    database, snapshot = _write_valid_library(library_root)
    consumer_root = tmp_path / "consumer-run"
    before = sorted(
        (
            path.relative_to(producer_root).as_posix(),
            path.read_bytes() if path.is_file() else None,
        )
        for path in producer_root.rglob("*")
    )
    library_before = sorted(
        (
            path.relative_to(library_root).as_posix(),
            path.read_bytes() if path.is_file() else None,
        )
        for path in library_root.rglob("*")
    )

    result = module.main(
        [
            "--producer-run-root",
            str(producer_root),
            "--output-root",
            str(consumer_root),
            "--viral-library-root",
            str(library_root),
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    manifest = json.loads(
        (consumer_root / "codex-daily-article-run.json").read_text(encoding="utf-8")
    )
    assert "pending_consumer" in module.LIBRARY_CONTEXT_STATUSES
    assert manifest["producer"]["handoff"]["sha256"] == _digest(handoff)
    assert manifest["producer"]["handoff"]["digest_verified"] is True
    assert manifest["library_context_status"] == "available"
    assert manifest["library"]["reader"]["status"] == "available"
    assert manifest["library"]["reader"]["readback"]["verified"] is True
    assert manifest["library"]["context"]["status"] == "available"
    assert manifest["library"]["index"]["status"] == "available"
    assert manifest["library"]["readback"]["verified"] is True
    assert manifest["readback"]["producer_handoff"] is True
    assert manifest["readback"]["library"] is True

    files = manifest["library"]["reader"]["consumer_manifest"]["files"]
    file_hashes = {item["path"]: item["sha256"] for item in files}
    assert file_hashes["library.sqlite"] == _digest(database)
    assert file_hashes[snapshot.relative_to(library_root).as_posix()] == _digest(snapshot)
    assert manifest["library"]["reader"]["consumer_manifest"]["readback"]["verified"] is True

    library_output = Path(manifest["library"]["output_root"])
    index_path = Path(manifest["library"]["index"]["path"])
    context_path = Path(manifest["library"]["context"]["path"])
    assert index_path.is_file()
    assert context_path.is_file()
    assert index_path.parent == library_output
    assert context_path.parent == library_output
    assert library_output != consumer_root.resolve()
    assert consumer_root.resolve() not in library_output.parents
    assert producer_root.resolve() not in library_output.parents
    assert library_root.resolve() not in library_output.parents
    assert manifest["publication_authorized"] is False
    assert manifest["publication_performed"] is False

    after = sorted(
        (
            path.relative_to(producer_root).as_posix(),
            path.read_bytes() if path.is_file() else None,
        )
        for path in producer_root.rglob("*")
    )
    assert before == after
    library_after = sorted(
        (
            path.relative_to(library_root).as_posix(),
            path.read_bytes() if path.is_file() else None,
        )
        for path in library_root.rglob("*")
    )
    assert library_before == library_after


def test_daily_article_runner_rejects_supplied_library_root_that_differs_from_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load("scripts.codex_daily_article_runner")
    producer_root = tmp_path / "producer-run"
    declared_root = tmp_path / "declared-library"
    supplied_root = tmp_path / "supplied-library"
    _write_producer_package(
        producer_root,
        library_root=declared_root,
        library_context_status="pending_consumer",
    )
    _write_valid_library(declared_root)
    _write_valid_library(supplied_root)
    consumer_root = tmp_path / "consumer-run"
    calls: dict[str, list[object]] = {"reader": [], "index": [], "context": []}

    real_reader = module.read_library
    real_index = module.build_index
    real_context = module.build_library_context

    def tracking_reader(root: Path) -> dict[str, object]:
        calls["reader"].append(root)
        return real_reader(root)

    def tracking_index(*args: object, **kwargs: object) -> dict[str, object]:
        calls["index"].append(kwargs.get("viral_library_root"))
        return real_index(*args, **kwargs)

    def tracking_context(root: Path, output_path: Path) -> dict[str, object]:
        calls["context"].append(root)
        return real_context(root, output_path)

    monkeypatch.setattr(module, "read_library", tracking_reader)
    monkeypatch.setattr(module, "build_index", tracking_index)
    monkeypatch.setattr(module, "build_library_context", tracking_context)

    result = module.main(
        [
            "--producer-run-root",
            str(producer_root),
            "--output-root",
            str(consumer_root),
            "--viral-library-root",
            str(supplied_root),
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == "library_root_mismatch\n"
    assert captured.err == ""
    assert calls == {"reader": [], "index": [], "context": []}
    assert not consumer_root.exists()
    assert not consumer_root.with_name("consumer-run-library").exists()


def test_daily_article_runner_keeps_pending_consumer_visible_for_missing_library(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load("scripts.codex_daily_article_runner")
    producer_root = tmp_path / "producer-run"
    _write_producer_package(
        producer_root,
        library_root=tmp_path / "missing-library",
        library_context_status="pending_consumer",
    )
    consumer_root = tmp_path / "consumer-run"
    library_root = tmp_path / "missing-library"

    result = module.main(
        [
            "--producer-run-root",
            str(producer_root),
            "--output-root",
            str(consumer_root),
            "--viral-library-root",
            str(library_root),
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    manifest = json.loads(
        (consumer_root / "codex-daily-article-run.json").read_text(encoding="utf-8")
    )
    assert manifest["library_context_status"] == "unavailable"
    assert manifest["library"]["reader"]["status"] == "unavailable"
    assert manifest["library"]["reader"]["reason"] == "LIBRARY_ROOT_UNAVAILABLE"
    assert manifest["library"]["context"]["status"] == "unavailable"
    assert manifest["library"]["context"]["readback"]["verified"] is True
    assert manifest["library"]["readback"]["verified"] is False
    assert manifest["library_context_status"] != "not_requested"


def test_daily_article_runner_keeps_corrupt_library_unavailable_without_mutation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load("scripts.codex_daily_article_runner")
    producer_root = tmp_path / "producer-run"
    _write_producer_package(
        producer_root,
        library_root=tmp_path / "corrupt-library",
        library_context_status="pending_consumer",
    )
    library_root = tmp_path / "corrupt-library"
    _, snapshot = _write_valid_library(library_root)
    snapshot.write_bytes(b"tampered fixture\n")
    before = sorted(
        (
            path.relative_to(library_root).as_posix(),
            path.read_bytes() if path.is_file() else None,
        )
        for path in library_root.rglob("*")
    )
    consumer_root = tmp_path / "consumer-run"

    result = module.main(
        [
            "--producer-run-root",
            str(producer_root),
            "--output-root",
            str(consumer_root),
            "--viral-library-root",
            str(library_root),
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    manifest = json.loads(
        (consumer_root / "codex-daily-article-run.json").read_text(encoding="utf-8")
    )
    assert manifest["library_context_status"] == "unavailable"
    assert manifest["library"]["reader"]["status"] == "unavailable"
    assert manifest["library"]["reader"]["reason"] == "SNAPSHOT_HASH_MISMATCH"
    assert manifest["library"]["context"]["status"] == "unavailable"
    assert manifest["library"]["readback"]["verified"] is False
    assert manifest["library_context_status"] != "not_requested"
    after = sorted(
        (
            path.relative_to(library_root).as_posix(),
            path.read_bytes() if path.is_file() else None,
        )
        for path in library_root.rglob("*")
    )
    assert before == after


def test_review_audit_is_read_only_and_reports_schema_and_run_structure(tmp_path: Path) -> None:
    module = _load("scripts.codex_review_audit")
    home_agents = tmp_path / "home-AGENTS.md"
    project_agents = tmp_path / "project" / "AGENTS.md"
    skills = tmp_path / "skills"
    schema = tmp_path / "project" / "schemas" / "review.json"
    runs = tmp_path / "project" / "runs"
    home_agents.write_text("home rules\n", encoding="utf-8")
    project_agents.parent.mkdir(parents=True, exist_ok=True)
    project_agents.write_text("project rules\n", encoding="utf-8")
    (skills / "alpha").mkdir(parents=True)
    (skills / "alpha" / "SKILL.md").write_text("skill\n", encoding="utf-8")
    schema.parent.mkdir(parents=True, exist_ok=True)
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["decision", "scope_reviewed", "findings", "non_findings", "coverage_gaps"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (runs / "2026-08-25" / "review").mkdir(parents=True)
    (runs / "2026-08-25" / "review" / "result.json").write_text("{}\n", encoding="utf-8")
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    report = module.build_report(
        home_agents=home_agents,
        project_agents=project_agents,
        skills_root=skills,
        schema_path=schema,
        runs_root=runs,
        recent_limit=3,
    )

    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert before == after
    assert report["read_only"] is True
    assert report["mutation"]["files_written"] == []
    assert report["checks"]["review_schema"]["valid_json"] is True
    assert report["checks"]["review_schema"]["required_fields"] == [
        "decision",
        "scope_reviewed",
        "findings",
        "non_findings",
        "coverage_gaps",
    ]
    assert report["checks"]["codex_skills"]["skill_count"] == 1
    assert report["checks"]["recent_runs"]["entries"][0]["name"] == "2026-08-25"


def test_review_audit_cli_emits_json_without_writing_an_output_file(capsys: pytest.CaptureFixture[str]) -> None:
    module = _load("scripts.codex_review_audit")

    result = module.main([])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result in {0, 2}
    assert payload["read_only"] is True
    assert payload["mutation"]["files_written"] == []
    assert captured.err == ""


def test_review_audit_can_write_an_immutable_monthly_snapshot(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    module = _load("scripts.codex_review_audit")
    home_agents = tmp_path / "home-AGENTS.md"
    project_agents = tmp_path / "project" / "AGENTS.md"
    skills = tmp_path / "skills"
    schema = tmp_path / "project" / "schemas" / "review.json"
    runs = tmp_path / "project" / "runs"
    output_root = tmp_path / "audit-output"
    home_agents.write_text("home rules\n", encoding="utf-8")
    project_agents.parent.mkdir(parents=True, exist_ok=True)
    project_agents.write_text("project rules\n", encoding="utf-8")
    (skills / "alpha").mkdir(parents=True)
    (skills / "alpha" / "SKILL.md").write_text("skill\n", encoding="utf-8")
    schema.parent.mkdir(parents=True, exist_ok=True)
    schema.write_text(json.dumps({"type": "object", "required": ["decision"]}) + "\n", encoding="utf-8")
    runs.mkdir(parents=True)

    first = module.main(
        [
            "--home-agents",
            str(home_agents),
            "--project-agents",
            str(project_agents),
            "--skills-root",
            str(skills),
            "--schema",
            str(schema),
            "--runs-root",
            str(runs),
            "--month",
            "2026-08",
            "--output-root",
            str(output_root),
        ]
    )
    first_output = output_root / "codex-review-audit-2026-08.json"
    first_manifest = output_root / "codex-review-audit-2026-08.json.manifest.json"
    first_stdout = capsys.readouterr()

    second = module.main(
        [
            "--month",
            "2026-08",
            "--output-root",
            str(output_root),
        ]
    )
    second_stdout = capsys.readouterr()

    assert first == 0
    assert second == 2
    assert json.loads(first_stdout.out)["status"] == "written"
    assert second_stdout.out == "artifact_exists\n"
    assert json.loads(first_output.read_text(encoding="utf-8"))["read_only"] is True
    manifest = json.loads(first_manifest.read_text(encoding="utf-8"))
    assert manifest["month"] == "2026-08"
    assert manifest["report_sha256"]
