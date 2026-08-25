#!/usr/bin/env python3
"""Build a stable, content-light inventory of the 若雨 viral-article library.

The inventory intentionally reads only an allow-listed set of project paths:
legacy Markdown notes, known evidence manifests/cards, and distillation JSON.
It never crawls the repository and never opens credentials, raw HTML, or Hermes
private state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

QUALIFICATION_STATUSES = (
    "qualified_viral",
    "observed_pending",
    "research_only",
)

LEGACY_DIRS = (
    Path("ruoyu-content/10-case-library"),
    Path("ruoyu-system"),
)

DEFAULT_EVIDENCE_RUN = Path("runs/2026-08-11/viral-research")


def _safe_resolve(root: Path, candidate: Path) -> Path | None:
    """Resolve an allow-listed candidate without permitting path escape."""
    root_resolved = root.resolve()
    path = candidate if candidate.is_absolute() else root / candidate
    resolved = path.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return None
    return resolved


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_record(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": _relative(root, path),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _read_json(path: Path) -> tuple[dict[str, Any] | list[Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, "unreadable_or_invalid_json"
    if not isinstance(value, (dict, list)):
        return None, "json_root_must_be_object_or_array"
    return value, None


def _strip_ref(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    ref = value.strip().strip("`")
    if "#sha256=" in ref:
        ref = ref.split("#sha256=", 1)[0]
    return ref.strip()


def _resolve_ref(root: Path, reference: Any, bases: Iterable[Path]) -> Path | None:
    ref = _strip_ref(reference)
    if not ref:
        return None
    ref_path = Path(ref)
    for base in bases:
        candidate = _safe_resolve(root, base / ref_path)
        if candidate is not None and candidate.is_file():
            return candidate
    return None


def _legacy_inventory(root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for directory in LEGACY_DIRS:
        resolved_dir = _safe_resolve(root, directory)
        if resolved_dir is None or not resolved_dir.is_dir():
            continue
        for path in sorted(resolved_dir.glob("*.md"), key=lambda item: item.name):
            if not path.is_file():
                continue
            try:
                files.append({"source_dir": directory.as_posix(), **_file_record(root, path)})
            except OSError:
                errors.append({"path": _relative(root, path), "error": "unreadable"})

    by_digest: dict[str, list[str]] = defaultdict(list)
    for record in files:
        by_digest[record["sha256"]].append(record["path"])
    duplicate_groups = [
        {"sha256": digest, "paths": sorted(paths)}
        for digest, paths in sorted(by_digest.items())
        if len(paths) > 1
    ]
    return {
        "preferred_entry_dir": "ruoyu-content/10-case-library",
        "compatibility_entry_dir": "ruoyu-system",
        "files": files,
        "duplicate_groups": duplicate_groups,
        "errors": errors,
    }


def _status_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(record.get("qualification_status", "unknown") for record in records)
    return {status: counts[status] for status in sorted(counts)}


def _wechat_cards(root: Path, run_root: Path) -> dict[str, Any]:
    pack_dir = run_root / "wechat-viral"
    cards_dir = pack_dir / "cards"
    card_records: list[dict[str, Any]] = []
    parse_errors: list[dict[str, str]] = []
    if cards_dir.is_dir():
        for path in sorted(cards_dir.glob("*.json"), key=lambda item: item.name):
            if path.name.startswith("_") or not path.is_file():
                continue
            data, error = _read_json(path)
            if error or not isinstance(data, dict):
                parse_errors.append({"path": _relative(root, path), "error": error or "invalid_card"})
                continue
            status = data.get("qualification_status", "unknown")
            snapshot_ref = data.get("snapshot_ref") or data.get("fulltext_snapshot_ref")
            performance_ref = data.get("performance_evidence_ref")
            snapshot = _resolve_ref(root, snapshot_ref, (run_root, pack_dir))
            performance = _resolve_ref(root, performance_ref, (run_root, pack_dir))
            card_records.append(
                {
                    "sample_id": data.get("sample_id", path.stem),
                    "qualification_status": status,
                    "card_ref": _relative(root, path),
                    "snapshot_ref": _strip_ref(snapshot_ref),
                    "snapshot_present": snapshot is not None,
                    "performance_evidence_ref": _strip_ref(performance_ref),
                    "performance_evidence_present": performance is not None,
                    "technique_observation_count": len(data.get("technique_observations", []))
                    if isinstance(data.get("technique_observations", []), list)
                    else 0,
                    "usable_for_positive_patterns": status == "qualified_viral"
                    and snapshot is not None
                    and performance is not None,
                }
            )

    missing_evidence = [
        {
            "sample_id": record["sample_id"],
            "missing": [
                field
                for field, present in (
                    ("snapshot", record["snapshot_present"]),
                    ("performance_evidence", record["performance_evidence_present"]),
                )
                if not present
            ],
        }
        for record in card_records
        if record["qualification_status"] == "qualified_viral"
        and not record["usable_for_positive_patterns"]
    ]

    distill_path = pack_dir / "distillation" / "wx-candidates-20260811.json"
    distill_count = 0
    distill_max_frequency = 0
    if distill_path.is_file():
        data, error = _read_json(distill_path)
        if error:
            parse_errors.append({"path": _relative(root, distill_path), "error": error})
        elif isinstance(data, list):
            distill_count = len(data)
            frequencies = [
                item.get("frequency", 0)
                for item in data
                if isinstance(item, dict) and isinstance(item.get("frequency", 0), int)
            ]
            distill_max_frequency = max(frequencies, default=0)

    manifest_path = run_root / "raw_articles" / "MANIFEST.md"
    manifest_present = manifest_path.is_file()
    declared_article_count: int | None = None
    if manifest_present:
        try:
            manifest_text = manifest_path.read_text(encoding="utf-8")
            match = re.search(r"共\s*(\d+)\s*篇", manifest_text)
            if match:
                declared_article_count = int(match.group(1))
        except (OSError, UnicodeDecodeError):
            parse_errors.append({"path": _relative(root, manifest_path), "error": "unreadable_manifest"})

    return {
        "pack": "wechat-viral",
        "path": _relative(root, pack_dir),
        "status": "available" if cards_dir.is_dir() else "unavailable",
        "qualification_status_counts": _status_counts(card_records),
        "samples": card_records,
        "qualified_usable_count": sum(
            record["usable_for_positive_patterns"] for record in card_records
        ),
        "qualified_missing_evidence": missing_evidence,
        "fulltext_manifest": {
            "path": _relative(root, manifest_path),
            "present": manifest_present,
            "declared_article_count": declared_article_count,
        },
        "distillation": {
            "path": _relative(root, distill_path),
            "present": distill_path.is_file(),
            "candidate_count": distill_count,
            "max_frequency": distill_max_frequency,
            "promotion_status": "provisional_only",
        },
        "parse_errors": parse_errors,
    }


def _bilibili_pack(root: Path, run_root: Path) -> dict[str, Any]:
    pack_dir = run_root / "bilibili-public-metrics"
    manifest_path = pack_dir / "case-manifest.json"
    if not manifest_path.is_file():
        return {
            "pack": "bilibili-public-metrics",
            "path": _relative(root, pack_dir),
            "status": "unavailable",
            "manifest": {"path": _relative(root, manifest_path), "present": False},
            "samples": [],
            "qualified_usable_count": 0,
            "parse_errors": [],
        }

    data, error = _read_json(manifest_path)
    if error or not isinstance(data, dict):
        return {
            "pack": "bilibili-public-metrics",
            "path": _relative(root, pack_dir),
            "status": "unavailable",
            "manifest": {"path": _relative(root, manifest_path), "present": True},
            "samples": [],
            "qualified_usable_count": 0,
            "parse_errors": [{"path": _relative(root, manifest_path), "error": error or "invalid_manifest"}],
        }

    samples: list[dict[str, Any]] = []
    for item in data.get("samples", []):
        if not isinstance(item, dict):
            continue
        snapshot_ref = item.get("snapshot_ref")
        performance_ref = item.get("performance_evidence_ref")
        snapshot = _resolve_ref(root, snapshot_ref, (pack_dir, run_root))
        performance = _resolve_ref(root, performance_ref, (pack_dir, run_root))
        status = item.get("qualification_status", "unknown")
        samples.append(
            {
                "sample_id": item.get("sample_id", ""),
                "qualification_status": status,
                "card_ref": _strip_ref(item.get("card_ref")),
                "snapshot_ref": _strip_ref(snapshot_ref),
                "snapshot_present": snapshot is not None,
                "performance_evidence_ref": _strip_ref(performance_ref),
                "performance_evidence_present": performance is not None,
                "usable_for_positive_patterns": status == "qualified_viral"
                and snapshot is not None
                and performance is not None,
            }
        )

    return {
        "pack": "bilibili-public-metrics",
        "path": _relative(root, pack_dir),
        "status": "available",
        "manifest": {
            "path": _relative(root, manifest_path),
            "present": True,
            "declared_sample_count": data.get("sample_count"),
            "declared_qualified_viral_count": data.get("qualified_viral_count"),
        },
        "qualification_status_counts": _status_counts(samples),
        "samples": samples,
        "qualified_usable_count": sum(
            sample["usable_for_positive_patterns"] for sample in samples
        ),
        "shape_policy": "observation_only_for_ruoyu_title_rules",
        "parse_errors": [],
    }


def _jsonl_records(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    if not path.is_file():
        return records, errors
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return records, [{"path": str(path), "error": "unreadable_jsonl"}]
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            errors.append({"path": str(path), "error": f"invalid_jsonl:{line_number}"})
            continue
        if isinstance(value, dict):
            records.append(value)
        else:
            errors.append({"path": str(path), "error": f"jsonl_object_required:{line_number}"})
    return records, errors


def _research_package_inventory(root: Path, run_root: Path) -> dict[str, Any]:
    """Read only the allow-listed package, card, and review artifacts."""
    package_dir = run_root / "package"
    manifest_path = package_dir / "manifest.json"
    samples_path = package_dir / "samples.jsonl"
    exclusions_path = package_dir / "exclusions.jsonl"
    review_path = run_root / "review" / "viral-distill-review.json"
    base = {
        "pack": "viral-research-package",
        "path": _relative(root, package_dir),
        "status": "unavailable",
        "package_schema_version": None,
        "package_status": None,
        "sample_state_counts": {},
        "qualified_usable_count": 0,
        "pending_count": 0,
        "blocked_count": 0,
        "sample_count": 0,
        "exclusion_count": 0,
        "cards_present": False,
        "distillation_report": {
            "path": _relative(root, review_path),
            "present": False,
            "promotion_status": None,
            "verification_state": None,
        },
        "review_status": "unavailable",
        "parse_errors": [],
    }
    if not manifest_path.is_file():
        return base
    manifest, error = _read_json(manifest_path)
    if error or not isinstance(manifest, dict):
        base["parse_errors"].append(
            {"path": _relative(root, manifest_path), "error": error or "invalid_manifest"}
        )
        return base
    samples, sample_errors = _jsonl_records(samples_path)
    if not samples and isinstance(manifest.get("samples"), list):
        samples = [item for item in manifest["samples"] if isinstance(item, dict)]
    base["parse_errors"].extend(sample_errors)
    base["status"] = "available"
    base["package_schema_version"] = manifest.get("schema_version")
    base["package_status"] = manifest.get("status")
    base["sample_count"] = len(samples)
    base["sample_state_counts"] = _status_counts(samples)
    base["pending_count"] = base["sample_state_counts"].get("observed_pending", 0)
    base["blocked_count"] = base["sample_state_counts"].get("blocked", 0)
    base["exclusion_count"] = len(_jsonl_records(exclusions_path)[0])
    cards_dir = run_root / "cards"
    base["cards_present"] = cards_dir.is_dir() and any(
        path.is_file() for path in cards_dir.glob("*.json")
    )
    usable = 0
    for sample in samples:
        if sample.get("qualification_status") != "qualified_viral":
            continue
        clean = _resolve_ref(root, sample.get("clean_ref"), (run_root, package_dir))
        metadata = _resolve_ref(root, sample.get("metadata_ref"), (run_root, package_dir))
        if clean is not None and metadata is not None:
            usable += 1
    base["qualified_usable_count"] = usable
    report, report_error = _read_json(review_path)
    if report_error:
        if review_path.exists():
            base["parse_errors"].append(
                {"path": _relative(root, review_path), "error": report_error}
            )
    elif isinstance(report, dict):
        base["distillation_report"] = {
            "path": _relative(root, review_path),
            "present": True,
            "promotion_status": report.get("promotion_status"),
            "verification_state": report.get("verification_state"),
        }
        base["review_status"] = report.get("verification_state") or report.get(
            "promotion_status", "available"
        )
    return base


def build_index(project_root: str | Path = ".", evidence_run: str | Path = DEFAULT_EVIDENCE_RUN) -> dict[str, Any]:
    root = Path(project_root).resolve()
    run_root = _safe_resolve(root, Path(evidence_run))
    if run_root is None:
        run_root = root / Path(evidence_run)

    evidence_available = run_root.is_dir()
    evidence_packs = []
    if evidence_available:
        evidence_packs = [
            _wechat_cards(root, run_root),
            _bilibili_pack(root, run_root),
            _research_package_inventory(root, run_root),
        ]
    else:
        evidence_packs = [
            {
                "pack": "wechat-viral",
                "path": Path(evidence_run, "wechat-viral").as_posix(),
                "status": "unavailable",
                "samples": [],
                "qualified_usable_count": 0,
                "qualified_missing_evidence": [],
                "parse_errors": [],
            },
            {
                "pack": "bilibili-public-metrics",
                "path": Path(evidence_run, "bilibili-public-metrics").as_posix(),
                "status": "unavailable",
                "samples": [],
                "qualified_usable_count": 0,
                "parse_errors": [],
            },
            _research_package_inventory(root, run_root),
        ]

    return {
        "schema_version": "codex-viral-library-index-v1",
        "project_root": ".",
        "library_entrypoints": {
            "codex_skill": ".agents/skills/ruoyu-viral-library/SKILL.md",
            "migration_note": "docs/codex/viral-library-migration.md",
            "qualification_contract": "article_group/case_contract.py",
            "distillation_contract": "article_group/case_distill.py",
            "external_canonical_governance": {
                "status": "external_read_only",
                "path": "Hermes Knowledge Vault/20_Hermes/10_Content_Production/01_Ruoyu/若雨爆款案例原则与反例库.md",
                "copy_policy": "do_not_copy_hermes_private_state",
            },
        },
        "legacy_library": _legacy_inventory(root),
        "evidence_library": {
            "run": Path(evidence_run).as_posix(),
            "status": "available" if evidence_available else "unavailable",
            "packs": evidence_packs,
        },
        "policy": {
            "positive_pattern_statuses": ["qualified_viral"],
            "observation_only_statuses": ["observed_pending", "research_only"],
            "missing_evidence_policy": "unavailable_not_promoted",
            "distillation_policy": "provisional_until_controller_review",
            "current_fact_policy": "reverify_authoritative_sources",
            "raw_html_policy": "not_read_by_this_indexer",
            "credential_policy": "never_read_or_copy",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".", help="repository root")
    parser.add_argument(
        "--evidence-run",
        default=str(DEFAULT_EVIDENCE_RUN),
        help="relative evidence run directory",
    )
    parser.add_argument("--compact", action="store_true", help="emit one-line JSON")
    args = parser.parse_args(argv)
    result = build_index(args.project_root, args.evidence_run)
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":") if args.compact else None,
            indent=None if args.compact else 2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
