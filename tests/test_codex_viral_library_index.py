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
        "clean_ref": "clean/a.md#sha256=" + "a" * 64,
        "metadata_ref": "metadata/a.json#sha256=" + "b" * 64,
    }
    pending = {
        "sample_id": "sample-p",
        "qualification_status": "observed_pending",
        "clean_ref": "clean/missing.md#sha256=" + "c" * 64,
        "metadata_ref": "metadata/missing.json#sha256=" + "d" * 64,
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
            "exclusions_ref": "package/exclusions.jsonl",
            "errors": [],
        },
    )
    (package / "samples.jsonl").write_text(
        "\n".join(json.dumps(item) for item in (sample, pending)) + "\n",
        encoding="utf-8",
    )
    (package / "exclusions.jsonl").write_text("", encoding="utf-8")
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


def test_package_inventory_does_not_read_raw_or_sensitive_paths(tmp_path: Path) -> None:
    run = Path("runs/test-run/viral-research")
    raw = tmp_path / run / "raw_articles" / "secret.html"
    raw.parent.mkdir(parents=True)
    raw.write_text("token=must-not-appear", encoding="utf-8")
    result = build_index(tmp_path, run)
    package_inventory = result["evidence_library"]["packs"][2]
    assert "must-not-appear" not in json.dumps(package_inventory)
    assert package_inventory["status"] == "unavailable"
