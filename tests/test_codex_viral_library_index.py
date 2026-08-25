from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.codex_viral_library_index import build_index, main


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hashed_ref(path: Path, reference: str) -> str:
    return f"{reference}#sha256={_sha256(path)}"


def _write_card(
    root: Path,
    run: Path,
    sample_id: str,
    status: str,
    snapshot_ref: str,
    performance_ref: str,
) -> None:
    snapshot_path = root / run / snapshot_ref
    performance_path = root / run / performance_ref
    snapshot_ref = (
        _hashed_ref(snapshot_path, snapshot_ref)
        if snapshot_path.is_file()
        else snapshot_ref
    )
    performance_ref = (
        _hashed_ref(performance_path, performance_ref)
        if performance_path.is_file()
        else performance_ref
    )
    _write_json(
        root / run / "wechat-viral" / "cards" / f"{sample_id}.json",
        {
            "sample_id": sample_id,
            "qualification_status": status,
            "snapshot_ref": f"`{snapshot_ref}`",
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


def test_hash_mismatch_is_not_usable(tmp_path: Path) -> None:
    run = Path("runs/test-run/viral-research")
    wrong_hash = hashlib.sha256(b"wrong evidence digest").hexdigest()

    wechat_snapshot = tmp_path / run / "raw_articles/sample.md"
    wechat_metric = tmp_path / run / "wechat-viral/metrics/qualified.json"
    wechat_snapshot.parent.mkdir(parents=True)
    wechat_metric.parent.mkdir(parents=True)
    wechat_snapshot.write_text("# captured full text\n", encoding="utf-8")
    wechat_metric.write_text("{}\n", encoding="utf-8")
    _write_json(
        tmp_path / run / "wechat-viral/cards/qualified.json",
        {
            "sample_id": "qualified",
            "qualification_status": "qualified_viral",
            "snapshot_ref": f"raw_articles/sample.md#sha256={wrong_hash}",
            "performance_evidence_ref": f"wechat-viral/metrics/qualified.json#sha256={wrong_hash}",
        },
    )

    bilibili_pack = tmp_path / run / "bilibili-public-metrics"
    bilibili_snapshot = bilibili_pack / "sources/cv-one.clean.md"
    bilibili_metric = bilibili_pack / "metrics/cv-one.api.json"
    bilibili_snapshot.parent.mkdir(parents=True)
    bilibili_metric.parent.mkdir(parents=True)
    bilibili_snapshot.write_text("full text\n", encoding="utf-8")
    bilibili_metric.write_text("{}\n", encoding="utf-8")
    _write_json(
        bilibili_pack / "case-manifest.json",
        {
            "samples": [
                {
                    "sample_id": "cv-one",
                    "qualification_status": "qualified_viral",
                    "snapshot_ref": f"sources/cv-one.clean.md#sha256={wrong_hash}",
                    "performance_evidence_ref": f"metrics/cv-one.api.json#sha256={wrong_hash}",
                }
            ]
        },
    )

    package_dir = tmp_path / run / "package"
    package_snapshot = tmp_path / run / "clean/package.md"
    package_metadata = tmp_path / run / "metadata/package.json"
    package_snapshot.parent.mkdir(parents=True)
    package_metadata.parent.mkdir(parents=True)
    package_snapshot.write_text("# package sample\n", encoding="utf-8")
    package_metadata.write_text("{}\n", encoding="utf-8")
    package_sample = {
        "sample_id": "package-sample",
        "qualification_status": "qualified_viral",
        "clean_ref": f"clean/package.md#sha256={wrong_hash}",
        "metadata_ref": f"metadata/package.json#sha256={wrong_hash}",
    }
    _write_json(
        package_dir / "manifest.json",
        {"schema_version": "viral-research-package-v1", "samples": [package_sample]},
    )
    (package_dir / "samples.jsonl").write_text(
        json.dumps(package_sample) + "\n", encoding="utf-8"
    )

    result = build_index(tmp_path, run)
    packs = {pack["pack"]: pack for pack in result["evidence_library"]["packs"]}

    assert packs["wechat-viral"]["qualified_usable_count"] == 0
    assert packs["bilibili-public-metrics"]["qualified_usable_count"] == 0
    assert packs["viral-research-package"]["qualified_usable_count"] == 0


def test_outside_evidence_run_is_unavailable_without_reading_outside(tmp_path: Path) -> None:
    with TemporaryDirectory(dir=tmp_path.parent) as outside:
        result = build_index(tmp_path, outside)
    assert result["evidence_library"]["status"] == "unavailable"
    assert result["evidence_library"]["packs"][2]["status"] == "unavailable"


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
                    "snapshot_ref": "sources/cv-one.clean.md#sha256="
                    + hashlib.sha256(b"full text\n").hexdigest(),
                    "performance_evidence_ref": "metrics/cv-one.api.json#sha256="
                    + hashlib.sha256(b"{}\n").hexdigest(),
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


def test_index_reports_research_package_layer(tmp_path: Path) -> None:
    run = Path("runs/test-run/viral-research")
    package = tmp_path / run / "package"
    clean = tmp_path / run / "clean" / "a.md"
    metric = tmp_path / run / "metadata" / "a.json"
    clean.parent.mkdir(parents=True)
    metric.parent.mkdir(parents=True)
    clean.write_text("# bounded sample\n", encoding="utf-8")
    metric.write_text("{}\n", encoding="utf-8")
    sample = {
        "sample_id": "sample-a",
        "qualification_status": "qualified_viral",
        "clean_ref": "clean/a.md#sha256=" + hashlib.sha256(b"# bounded sample\n").hexdigest(),
        "metadata_ref": "metadata/a.json#sha256=" + hashlib.sha256(b"{}\n").hexdigest(),
    }
    pending = {
        "sample_id": "sample-p",
        "qualification_status": "observed_pending",
        "clean_ref": "clean/missing.md",
        "metadata_ref": "metadata/missing.json",
    }
    package.mkdir(parents=True)
    _write_json(
        package / "manifest.json",
        {
            "schema_version": "viral-research-package-v1",
            "run_id": "run-test",
            "status": "evidence_checked",
            "created_at": "2026-08-25T10:00:00+08:00",
            "source_lanes": ["wechat_qualified"],
            "samples": [sample, pending],
            "exclusions_ref": "package/exclusions.jsonl#sha256="
            + hashlib.sha256(b"").hexdigest(),
            "errors": [],
        },
    )
    (package / "samples.jsonl").write_text(
        "\n".join(json.dumps(item) for item in (sample, pending)) + "\n",
        encoding="utf-8",
    )
    (package / "exclusions.jsonl").write_text("", encoding="utf-8")
    manifest_digest = hashlib.sha256((package / "manifest.json").read_bytes()).hexdigest()
    samples_digest = hashlib.sha256((package / "samples.jsonl").read_bytes()).hexdigest()
    exclusions_digest = hashlib.sha256((package / "exclusions.jsonl").read_bytes()).hexdigest()
    _write_json(
        package / "integrity.json",
        {
            "schema_version": "viral-research-package-integrity-v1",
            "manifest_sha256": manifest_digest,
            "samples_sha256": samples_digest,
            "exclusions_sha256": exclusions_digest,
        },
    )
    _write_json(
        tmp_path / run / "review" / "viral-distill-review.json",
        {
            "promotion_status": "provisional_only",
            "verification_state": "promising",
        },
    )
    result = build_index(tmp_path, run)
    package_inventory = result["evidence_library"]["packs"][2]
    assert package_inventory["pack"] == "viral-research-package"
    assert package_inventory["status"] == "available"
    assert package_inventory["package_schema_version"] == "viral-research-package-v1"
    assert package_inventory["sample_state_counts"] == {
        "observed_pending": 1,
        "qualified_viral": 1,
    }
    assert package_inventory["qualified_usable_count"] == 1
    assert package_inventory["pending_count"] == 1
    assert package_inventory["blocked_count"] == 0
    assert package_inventory["distillation_report"]["present"] is True
    assert package_inventory["review_status"] == "promising"


def test_package_inventory_rejects_tampered_core_file(tmp_path: Path) -> None:
    run = Path("runs/test-run/viral-research")
    package = tmp_path / run / "package"
    package.mkdir(parents=True)
    (package / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "viral-research-package-v1",
                "run_id": "run-test",
                "status": "research_only",
                "created_at": "2026-08-25T10:00:00+08:00",
                "source_lanes": ["wechat_qualified"],
                "samples": [],
                "exclusions_ref": "package/exclusions.jsonl#sha256="
                + hashlib.sha256(b"").hexdigest(),
                "errors": [],
            }
        ),
        encoding="utf-8",
    )
    (package / "samples.jsonl").write_text("", encoding="utf-8")
    (package / "exclusions.jsonl").write_text("", encoding="utf-8")
    _write_json(
        package / "integrity.json",
        {
            "schema_version": "viral-research-package-integrity-v1",
            "manifest_sha256": "0" * 64,
            "samples_sha256": hashlib.sha256(b"").hexdigest(),
            "exclusions_sha256": hashlib.sha256(b"").hexdigest(),
        },
    )

    inventory = build_index(tmp_path, run)["evidence_library"]["packs"][2]
    assert inventory["status"] == "unavailable"
    assert inventory["parse_errors"][-1]["error"] == "package_integrity_mismatch"


def test_package_inventory_does_not_read_raw_or_sensitive_paths(tmp_path: Path) -> None:
    run = Path("runs/test-run/viral-research")
    raw = tmp_path / run / "raw_articles" / "secret.html"
    raw.parent.mkdir(parents=True)
    raw.write_text("token=must-not-appear", encoding="utf-8")
    result = build_index(tmp_path, run)
    package_inventory = result["evidence_library"]["packs"][2]
    assert "must-not-appear" not in json.dumps(package_inventory)
    assert package_inventory["status"] == "unavailable"
