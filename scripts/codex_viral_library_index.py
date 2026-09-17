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
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

try:  # Support both package imports and ``python scripts/...`` execution.
    from .codex_viral_library_reader import read_library
except ImportError:  # pragma: no cover - exercised by direct script execution.
    from codex_viral_library_reader import read_library  # type: ignore[no-redef]

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

# 生产端 article_group/viral_research_package.py 的产物契约。
PACKAGE_SCHEMA_VERSION = "viral-research-package-v1"
PACKAGE_INTEGRITY_SCHEMA_VERSION = "viral-research-package-integrity-v1"


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


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [], "unreadable"
    records: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            return [], f"invalid_jsonl_line:{number}"
        if not isinstance(value, dict):
            return [], f"jsonl_line_not_object:{number}"
        records.append(value)
    return records, None


def _viral_package(root: Path, run_root: Path) -> dict[str, Any]:
    """Read a ``viral-research-package-v1`` built by the viral-research producer.

    Additive: the historical lane layout (``wechat-viral/``,
    ``bilibili-public-metrics/``) is untouched.  A package must carry
    ``integrity.json``; when it is missing or any digest disagrees, no sample is
    usable for positive patterns — the producer's fail-closed guarantee is only
    worth anything if this side actually checks it.
    """
    pack_dir = run_root / "package"
    manifest_path = pack_dir / "manifest.json"
    samples_path = pack_dir / "samples.jsonl"
    exclusions_path = pack_dir / "exclusions.jsonl"
    integrity_path = pack_dir / "integrity.json"

    result: dict[str, Any] = {
        "pack": "viral-research-package",
        "path": _relative(root, pack_dir),
        "status": "unavailable",
        "manifest": {"path": _relative(root, manifest_path), "present": False},
        "integrity": {
            "path": _relative(root, integrity_path),
            "present": integrity_path.is_file(),
            "verified": False,
            "mismatches": [],
        },
        "run_id": None,
        "package_status": None,
        "source_lanes": [],
        "declared_errors": [],
        "qualification_status_counts": {},
        "samples": [],
        "qualified_usable_count": 0,
        "qualified_missing_evidence": [],
        "exclusions": {
            "path": _relative(root, exclusions_path),
            "present": False,
            "count": 0,
        },
        "parse_errors": [],
    }
    if not manifest_path.is_file():
        return result

    result["manifest"] = {"path": _relative(root, manifest_path), "present": True}
    manifest, error = _read_json(manifest_path)
    if error or not isinstance(manifest, dict):
        result["status"] = "invalid"
        result["parse_errors"].append(
            {"path": _relative(root, manifest_path), "error": error or "invalid_manifest"}
        )
        return result
    if manifest.get("schema_version") != PACKAGE_SCHEMA_VERSION:
        result["status"] = "invalid"
        result["parse_errors"].append(
            {
                "path": _relative(root, manifest_path),
                "error": f"unexpected_schema_version:{manifest.get('schema_version')}",
            }
        )
        return result

    result["run_id"] = manifest.get("run_id")
    result["package_status"] = manifest.get("status")
    lanes = manifest.get("source_lanes")
    result["source_lanes"] = sorted(lanes) if isinstance(lanes, list) else []
    declared = manifest.get("errors")
    result["declared_errors"] = (
        sorted(str(item) for item in declared) if isinstance(declared, list) else []
    )

    samples, samples_error = _read_jsonl(samples_path)
    if samples_error:
        result["status"] = "invalid"
        result["parse_errors"].append(
            {"path": _relative(root, samples_path), "error": samples_error}
        )
        return result
    exclusions, exclusions_error = _read_jsonl(exclusions_path)
    if exclusions_error:
        result["parse_errors"].append(
            {"path": _relative(root, exclusions_path), "error": exclusions_error}
        )
    else:
        result["exclusions"]["present"] = exclusions_path.is_file()
        result["exclusions"]["count"] = len(exclusions)

    mismatches: list[str] = []
    if integrity_path.is_file():
        integrity, integrity_error = _read_json(integrity_path)
        if integrity_error or not isinstance(integrity, dict):
            mismatches.append(f"integrity.json:{integrity_error or 'invalid_integrity'}")
        elif integrity.get("schema_version") != PACKAGE_INTEGRITY_SCHEMA_VERSION:
            mismatches.append(
                "integrity.json:unexpected_schema_version:"
                f"{integrity.get('schema_version')}"
            )
        else:
            for filename, path in (
                ("manifest.json", manifest_path),
                ("samples.jsonl", samples_path),
                ("exclusions.jsonl", exclusions_path),
            ):
                expected = integrity.get(f"{filename.split('.')[0]}_sha256")
                actual = _sha256(path) if path.is_file() else None
                if expected != actual:
                    mismatches.append(f"{filename}:sha256_mismatch")
    verified = integrity_path.is_file() and not mismatches
    result["integrity"]["verified"] = verified
    result["integrity"]["mismatches"] = mismatches

    records: list[dict[str, Any]] = []
    # 生产端的样本 ref 是相对**它拿到的 run_root**（即 `--output-root` 的祖父，
    # 也就是本消费端 run_root 的父目录）写的；同时容忍 ref 相对包目录或
    # run_root 本身，避免两边约定再漂移一次。
    ref_bases = (run_root.parent, run_root, pack_dir)
    for item in samples:
        status = item.get("qualification_status", "unknown")
        snapshot_ref = item.get("snapshot_ref") or item.get("clean_ref")
        performance_ref = item.get("performance_evidence_ref") or item.get("metadata_ref")
        snapshot = _resolve_ref(root, snapshot_ref, ref_bases)
        performance = _resolve_ref(root, performance_ref, ref_bases)
        sample_id = item.get("sample_id", "")
        card_path = run_root / "cards" / f"{sample_id}.json"
        card_present = bool(sample_id) and card_path.is_file()
        observations = 0
        if card_present:
            card, card_error = _read_json(card_path)
            if (
                not card_error
                and isinstance(card, dict)
                and isinstance(card.get("technique_observations"), list)
            ):
                observations = len(card["technique_observations"])
        records.append(
            {
                "sample_id": sample_id,
                "qualification_status": status,
                "platform": item.get("platform", ""),
                "shape": item.get("shape", ""),
                "card_ref": _relative(root, card_path) if card_present else "",
                "card_present": card_present,
                "snapshot_ref": _strip_ref(snapshot_ref),
                "snapshot_present": snapshot is not None,
                "performance_evidence_ref": _strip_ref(performance_ref),
                "performance_evidence_present": performance is not None,
                "technique_observation_count": observations,
                "usable_for_positive_patterns": verified
                and status == "qualified_viral"
                and snapshot is not None
                and performance is not None,
            }
        )

    if not integrity_path.is_file():
        result["status"] = "integrity_missing"
    elif mismatches:
        result["status"] = "integrity_failed"
    else:
        result["status"] = "available"
    result["samples"] = records
    result["qualification_status_counts"] = _status_counts(records)
    result["qualified_usable_count"] = sum(
        record["usable_for_positive_patterns"] for record in records
    )
    result["qualified_missing_evidence"] = [
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
        for record in records
        if record["qualification_status"] == "qualified_viral"
        and not record["usable_for_positive_patterns"]
    ]
    return result


def build_index(
    project_root: str | Path = ".",
    evidence_run: str | Path = DEFAULT_EVIDENCE_RUN,
    viral_library_root: str | Path | None = None,
) -> dict[str, Any]:
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
            _viral_package(root, run_root),
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
            {
                "pack": "viral-research-package",
                "path": Path(evidence_run, "package").as_posix(),
                "status": "unavailable",
                "samples": [],
                "qualified_usable_count": 0,
                "qualified_missing_evidence": [],
                "parse_errors": [],
            },
        ]

    result = {
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
    if viral_library_root is not None:
        # This is additive.  A failed live-library read remains visible and
        # never falls back to the dormant historical compatibility copy.
        result["viral_library"] = read_library(viral_library_root)
    return result


def _serialized_json(result: dict[str, Any], *, compact: bool) -> str:
    return json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":") if compact else None,
        indent=None if compact else 2,
    )


def _output_conflicts_with_external_library(
    output_path: Path, viral_library_root: str | Path | None
) -> bool:
    """Keep the consumer output writer outside the external read-only root."""

    if viral_library_root is None:
        return False
    try:
        external_root = Path(viral_library_root).expanduser().resolve(strict=False)
        resolved_output = output_path.expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return True
    if resolved_output == external_root or external_root in resolved_output.parents:
        return True

    # Also refuse an existing hard link to the library or its journal/WAL
    # sidecars, even when the output pathname itself is outside the root.
    try:
        output_stat = os.stat(resolved_output)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            library_stat = os.stat(external_root / f"library.sqlite{suffix}")
        except FileNotFoundError:
            continue
        except OSError:
            return True
        if (output_stat.st_dev, output_stat.st_ino) == (
            library_stat.st_dev,
            library_stat.st_ino,
        ):
            return True
    return False


def _write_and_readback(path: Path, payload: str, result: dict[str, Any]) -> None:
    output_path = path.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = payload + "\n"
    output_path.write_text(serialized, encoding="utf-8")
    try:
        readback = output_path.read_text(encoding="utf-8")
        if json.loads(readback) != result:
            raise ValueError
        if hashlib.sha256(readback.encode("utf-8")).hexdigest() != hashlib.sha256(
            serialized.encode("utf-8")
        ).hexdigest():
            raise ValueError
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise RuntimeError("INDEX_OUTPUT_READBACK_FAILED") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".", help="repository root")
    parser.add_argument(
        "--evidence-run",
        default=str(DEFAULT_EVIDENCE_RUN),
        help="relative evidence run directory",
    )
    parser.add_argument(
        "--viral-library-root",
        type=Path,
        help="explicit absolute persistent viral-library root (read-only)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="optional JSON output path; the file is read back after writing",
    )
    parser.add_argument("--compact", action="store_true", help="emit one-line JSON")
    args = parser.parse_args(argv)
    result = build_index(
        args.project_root,
        args.evidence_run,
        viral_library_root=args.viral_library_root,
    )
    payload = _serialized_json(result, compact=args.compact)
    if args.output is not None:
        try:
            if _output_conflicts_with_external_library(
                args.output, args.viral_library_root
            ):
                raise RuntimeError("INDEX_OUTPUT_EXTERNAL_LIBRARY_CONFLICT")
            _write_and_readback(args.output, payload, result)
        except RuntimeError:
            print("output_readback_failed")
            return 2
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
