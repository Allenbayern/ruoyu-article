#!/usr/bin/env python3
"""Consume one explicit media article producer run as local evidence.

The active boundary is intentionally read-only on the producer side.  The
consumer receives a completed media run directory, verifies its manifest and
research handoff, and writes a separate consumer manifest.  It never invokes
the media producer, writes Vault state, or performs publication/Kanban work.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any, NoReturn, Sequence

try:  # Support package imports and direct ``python scripts/...`` execution.
    from .codex_viral_library_context import build_library_context
    from .codex_viral_library_index import build_index
    from .codex_viral_library_reader import read_library
except ImportError:  # pragma: no cover - exercised by direct script execution.
    from codex_viral_library_context import build_library_context  # type: ignore[no-redef]
    from codex_viral_library_index import build_index  # type: ignore[no-redef]
    from codex_viral_library_reader import read_library  # type: ignore[no-redef]

MANIFEST_NAME = "run-manifest.json"
HANDOFF_NAME = "article-research-handoff.json"
SUMMARY_NAME = "run_summary.json"
CONSUMER_MANIFEST_NAME = "codex-daily-article-run.json"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCER_REQUIRED_ARTIFACTS = (
    "source-audit.json",
    "retry-state.json",
    "verification.json",
    "viral-topic-signals.jsonl",
    "article-candidates.jsonl",
    "viral-article-cases.jsonl",
    SUMMARY_NAME,
    HANDOFF_NAME,
)
# ``pending_consumer`` is accepted from the media producer and must be
# resolved to ``available`` or ``unavailable`` when an explicit root is read.
LIBRARY_CONTEXT_STATUSES = frozenset(
    {"not_requested", "pending_consumer", "available", "unavailable"}
)
ALLOWED_STAGE_STATUSES = {
    "PASS",
    "BLOCKED",
    "FAIL",
    *LIBRARY_CONTEXT_STATUSES,
}


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, "argument_error\n")


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        description="Consume an explicit media article producer run as local evidence only."
    )
    parser.add_argument(
        "--producer-run-root",
        type=Path,
        required=True,
        help="completed media producer run directory; read-only input",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="fresh ruoyu consumer output directory",
    )
    parser.add_argument(
        "--viral-library-root",
        type=Path,
        default=None,
        help="explicit consumer-visible library root; read-only input",
    )
    parser.add_argument(
        "--library-output-root",
        type=Path,
        default=None,
        help="separate output directory for the read-only library index/context",
    )
    return parser


def _raw_sha256(path: Path) -> str | None:
    if path.is_symlink() or not path.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any] | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _read_artifact(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    if path.suffix.lower() == ".json":
        try:
            return isinstance(json.loads(content), (dict, list))
        except json.JSONDecodeError:
            return False
    if path.suffix.lower() == ".jsonl":
        try:
            for line in content.splitlines():
                if line.strip() and not isinstance(json.loads(line), (dict, list)):
                    return False
        except json.JSONDecodeError:
            return False
    return True


def _relative_path(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    if path.is_absolute() or "\\" in value or path == Path(".") or ".." in path.parts:
        return None
    return path.as_posix()


def _normalise_digest(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if text.startswith("sha256:"):
        text = text.removeprefix("sha256:")
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        return None
    return text


def _blank_manifest_self_hash(manifest: dict[str, Any]) -> dict[str, Any]:
    blank = json.loads(json.dumps(manifest, ensure_ascii=False))
    rows = blank.get("files")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("path") == MANIFEST_NAME:
                row["sha256"] = ""
    hashes = blank.get("artifact_hashes")
    if isinstance(hashes, dict) and MANIFEST_NAME in hashes:
        hashes[MANIFEST_NAME] = ""
    return blank


def _manifest_self_digest(manifest: dict[str, Any]) -> str:
    blank = _blank_manifest_self_hash(manifest)
    encoded = (
        json.dumps(blank, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _manifest_hash_map(manifest: dict[str, Any]) -> dict[str, str] | None:
    raw = manifest.get("artifact_hashes")
    if not isinstance(raw, dict):
        return None
    result: dict[str, str] = {}
    for name, digest in raw.items():
        relative = _relative_path(name)
        normalised = _normalise_digest(digest)
        if relative is None or normalised is None:
            return None
        result[relative] = normalised
    return result


def _verify_producer_manifest(
    producer_root: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    if manifest.get("schema") != "media-intel-run-manifest/v1":
        return False, {"reason": "producer_manifest_schema_invalid"}
    if manifest.get("lane") != "article":
        return False, {"reason": "producer_lane_invalid"}
    hashes = _manifest_hash_map(manifest)
    if hashes is None or MANIFEST_NAME not in hashes:
        return False, {"reason": "producer_manifest_hashes_invalid"}
    if hashes[MANIFEST_NAME] != _manifest_self_digest(manifest):
        return False, {"reason": "producer_manifest_self_hash_mismatch"}

    actual_paths: set[str] = set()
    for path in producer_root.rglob("*"):
        if path.is_symlink():
            return False, {"reason": "producer_symlink_not_allowed"}
        if path.is_file():
            actual_paths.add(path.relative_to(producer_root).as_posix())
    if actual_paths != set(hashes):
        return False, {"reason": "producer_manifest_file_boundary_mismatch"}

    required = manifest.get("required_files")
    if not isinstance(required, list):
        return False, {"reason": "producer_manifest_required_files_invalid"}
    required_names = {_relative_path(item) for item in required}
    if None in required_names:
        return False, {"reason": "producer_manifest_required_path_invalid"}
    missing_required = sorted(
        name for name in PRODUCER_REQUIRED_ARTIFACTS if name not in required_names
    )
    if missing_required:
        return False, {
            "reason": "producer_required_artifacts_not_declared",
            "missing": missing_required,
        }

    file_rows = manifest.get("files")
    if not isinstance(file_rows, list):
        return False, {"reason": "producer_manifest_files_invalid"}
    row_hashes: dict[str, str] = {}
    for row in file_rows:
        if not isinstance(row, dict):
            return False, {"reason": "producer_manifest_file_row_invalid"}
        relative = _relative_path(row.get("path"))
        digest = _normalise_digest(row.get("sha256"))
        if relative is None or digest is None or relative in row_hashes:
            return False, {"reason": "producer_manifest_file_row_invalid"}
        row_hashes[relative] = digest
    if row_hashes != hashes:
        return False, {"reason": "producer_manifest_hash_views_mismatch"}

    mismatches: list[str] = []
    unreadable: list[str] = []
    for relative, expected in sorted(hashes.items()):
        path = producer_root / relative
        if relative == MANIFEST_NAME:
            continue
        actual = _raw_sha256(path)
        if actual is None:
            unreadable.append(relative)
        elif actual != expected:
            mismatches.append(relative)
    for name in PRODUCER_REQUIRED_ARTIFACTS:
        if not _read_artifact(producer_root / name):
            unreadable.append(name)
    if mismatches or unreadable:
        return False, {
            "reason": "producer_artifact_readback_failed",
            "hash_mismatches": sorted(set(mismatches)),
            "unreadable": sorted(set(unreadable)),
        }
    return True, {
        "verified": True,
        "path": str(manifest_path),
        "sha256": _raw_sha256(manifest_path),
        "artifact_count": len(hashes),
        "required_files": sorted(required_names),
    }


def _stage_status(value: object, default: str = "not_requested") -> str | None:
    if not isinstance(value, str):
        return default
    text = value.strip()
    if text.upper() in {"PASS", "BLOCKED", "FAIL"}:
        return text.upper()
    if text in LIBRARY_CONTEXT_STATUSES:
        return text
    return None


def _verify_research_reference(
    producer_root: Path, handoff: dict[str, Any]
) -> tuple[bool, dict[str, Any]]:
    reference = handoff.get("research_manifest")
    if not isinstance(reference, dict):
        return False, {"reason": "research_manifest_reference_missing"}
    raw_path = reference.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return False, {"reason": "research_manifest_path_missing"}
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = producer_root / path
    expected = _normalise_digest(reference.get("sha256"))
    actual = _raw_sha256(path)
    if expected is None or actual is None or actual != expected:
        return False, {"reason": "research_manifest_digest_mismatch"}
    if _read_json(path) is None:
        return False, {"reason": "research_manifest_readback_failed"}
    readback = reference.get("readback")
    if isinstance(readback, dict) and readback.get("verified") is not True:
        return False, {"reason": "research_manifest_readback_unverified"}
    return True, {
        "path": str(path),
        "sha256": actual,
        "readback": {"verified": True},
    }


def _library_error_code(report: object, default: str = "LIBRARY_UNAVAILABLE") -> str | None:
    if not isinstance(report, dict):
        return default
    errors = report.get("errors")
    if isinstance(errors, list):
        for item in errors:
            if not isinstance(item, dict):
                continue
            code = item.get("code")
            if (
                isinstance(code, str)
                and code
                and all(character.isupper() or character.isdigit() or character == "_" for character in code)
            ):
                return code
    if report.get("status") == "available":
        return None
    return default


def _library_file_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        digest = _normalise_digest(item.get("sha256"))
        if not isinstance(path, str) or not path.strip() or digest is None:
            continue
        row: dict[str, Any] = {"path": path, "sha256": digest}
        if type(item.get("bytes")) is int and item["bytes"] >= 0:
            row["bytes"] = item["bytes"]
        rows.append(row)
    return rows


def _library_reader_summary(report: object) -> dict[str, Any]:
    source = report if isinstance(report, dict) else {}
    status = source.get("status") if source.get("status") in {"available", "unavailable"} else "unavailable"
    database_source = source.get("database")
    database = database_source if isinstance(database_source, dict) else {}
    consumer_source = source.get("consumer_manifest")
    consumer = consumer_source if isinstance(consumer_source, dict) else {}
    files = _library_file_rows(consumer.get("files"))
    database_file = next(
        (item for item in files if item.get("path") == "library.sqlite"),
        None,
    )
    snapshot_files = [
        item for item in files if str(item.get("path") or "").startswith("snapshots/")
    ]
    consumer_readback = consumer.get("readback")
    consumer_readback = (
        consumer_readback if isinstance(consumer_readback, dict) else {"verified": False}
    )
    reader_verified = (
        status == "available"
        and consumer.get("status") == "verified"
        and consumer_readback.get("verified") is True
    )
    database_summary: dict[str, Any] = {
        "path": database.get("path") or "library.sqlite",
        "mode": database.get("mode") or "ro",
        "query_only": database.get("query_only") is True,
        "sha256": database_file.get("sha256") if database_file else None,
        "readback": {"verified": database_file is not None and reader_verified},
    }
    if isinstance(database.get("journal_mode"), str):
        database_summary["journal_mode"] = database["journal_mode"]
    return {
        "status": status,
        "reason": _library_error_code(source),
        "reader_schema_version": source.get("reader_schema_version"),
        "schema_version": source.get("schema_version"),
        "database": database_summary,
        "snapshots": {
            "files": snapshot_files,
            "readback": {
                "verified": reader_verified,
                "checked": len(snapshot_files),
            },
        },
        "consumer_manifest": {
            "status": consumer.get("status") or "unavailable",
            "files": files,
            "readback": {
                key: consumer_readback.get(key)
                for key in ("verified", "checked")
                if key in consumer_readback
            },
        },
        "readback": {
            "verified": reader_verified,
            "database_sha256": database_file.get("sha256") if database_file else None,
            "snapshot_sha256": [item["sha256"] for item in snapshot_files],
        },
    }


def _artifact_readback(path: Path, expected: object) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    value = _read_json(path)
    return value == expected and _raw_sha256(path) is not None


def _write_library_json_artifact(
    path: Path,
    payload: dict[str, Any],
    *,
    status: str,
    reason: str | None,
) -> dict[str, Any]:
    try:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        verified = _artifact_readback(path, payload)
    except (OSError, UnicodeError, TypeError, ValueError):
        verified = False
    return {
        "path": str(path),
        "sha256": _raw_sha256(path),
        "status": status,
        "reason": reason,
        "readback": {"verified": verified},
    }


def _empty_library_artifact(path: Path, *, name: str, reason: str) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": None,
        "status": "unavailable",
        "reason": reason,
        "readback": {"verified": False},
        "name": name,
    }


def _prepare_empty_directory(path: Path) -> bool:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        return False
    if path.exists() and any(path.iterdir()):
        return False
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return True


def _library_output_conflict(
    library_output: Path,
    *,
    output_root: Path,
    producer_root: Path,
    library_root: Path,
) -> bool:
    if library_output in {output_root, producer_root, library_root}:
        return True
    if (
        _path_is_inside(library_output, output_root)
        or _path_is_inside(output_root, library_output)
        or _path_is_inside(library_output, producer_root)
        or _path_is_inside(library_output, library_root)
    ):
        return True
    return False


def _consume_library(
    *,
    library_root: Path,
    output_root: Path,
    producer_root: Path,
    requested_output_root: Path | None,
) -> tuple[dict[str, Any], str, str | None]:
    if requested_output_root is not None and requested_output_root.expanduser().is_symlink():
        raise ValueError("LIBRARY_OUTPUT_CONFLICT")
    library_output = (
        requested_output_root.expanduser().resolve()
        if requested_output_root is not None
        else output_root.with_name(f"{output_root.name}-library")
    )
    if _library_output_conflict(
        library_output,
        output_root=output_root,
        producer_root=producer_root,
        library_root=library_root.resolve(strict=False),
    ):
        raise ValueError("LIBRARY_OUTPUT_CONFLICT")
    if not _prepare_empty_directory(library_output):
        raise ValueError("LIBRARY_OUTPUT_NOT_FRESH")

    try:
        reader_report = read_library(library_root)
    except Exception:
        reader_report = {"status": "unavailable", "errors": [{"code": "LIBRARY_READER_FAILED"}]}
    reader_summary = _library_reader_summary(reader_report)
    reader_ok = reader_summary["readback"]["verified"] is True

    index_path = library_output / "library-index.json"
    try:
        index_result = build_index(
            str(PROJECT_ROOT),
            viral_library_root=library_root,
        )
        index_library_report = (
            index_result.get("viral_library")
            if isinstance(index_result, dict)
            else None
        )
        index_status = (
            index_library_report.get("status")
            if isinstance(index_library_report, dict)
            else "unavailable"
        )
        index_status = index_status if index_status in {"available", "unavailable"} else "unavailable"
        index_reason = _library_error_code(index_library_report)
        index_ref = _write_library_json_artifact(
            index_path,
            index_result if isinstance(index_result, dict) else {},
            status=index_status,
            reason=index_reason,
        )
    except Exception:
        index_ref = _empty_library_artifact(
            index_path,
            name="library-index",
            reason="LIBRARY_INDEX_BUILD_FAILED",
        )

    context_path = library_output / "library-context.json"
    try:
        context_result = build_library_context(library_root, context_path)
        context_result = context_result if isinstance(context_result, dict) else {}
        context_status = context_result.get("status")
        context_status = (
            context_status if context_status in {"available", "unavailable"} else "unavailable"
        )
        context_reason = context_result.get("reason")
        context_reason = context_reason if isinstance(context_reason, str) else None
        context_ref = {
            "path": str(context_path),
            "sha256": _raw_sha256(context_path),
            "status": context_status,
            "reason": context_reason or reader_summary.get("reason"),
            "readback": {"verified": _artifact_readback(context_path, context_result)},
        }
    except Exception:
        context_status = "unavailable"
        context_ref = _empty_library_artifact(
            context_path,
            name="library-context",
            reason="LIBRARY_CONTEXT_BUILD_FAILED",
        )

    if not reader_ok:
        context_status = "unavailable"
    context_reason = context_ref.get("reason") or reader_summary.get("reason")
    all_verified = bool(
        reader_ok
        and index_ref.get("readback", {}).get("verified") is True
        and context_ref.get("readback", {}).get("verified") is True
        and context_status == "available"
    )
    library = {
        "status": "available" if all_verified else "unavailable",
        "reason": None if all_verified else context_reason,
        "root": str(library_root),
        "output_root": str(library_output),
        "reader": reader_summary,
        "index": index_ref,
        "context": context_ref,
        "readback": {
            "verified": all_verified,
            "reader": reader_ok,
            "index": index_ref.get("readback", {}).get("verified") is True,
            "context": context_ref.get("readback", {}).get("verified") is True,
        },
    }
    return library, context_status, context_reason


def _unconfigured_library(
    *,
    handoff_status: str,
    declared_root: object,
) -> tuple[dict[str, Any], str, str | None]:
    root_declared = isinstance(declared_root, str) and bool(declared_root.strip())
    if handoff_status == "not_requested" and not root_declared:
        return (
            {
                "status": "not_requested",
                "reason": "library_root_not_configured",
                "root": declared_root,
                "output_root": None,
                "readback": {"verified": False},
            },
            "not_requested",
            "library_root_not_configured",
        )
    return (
        {
            "status": "unavailable",
            "reason": "LIBRARY_ROOT_NOT_PROVIDED",
            "root": declared_root,
            "output_root": None,
            "readback": {"verified": False},
        },
        "unavailable",
        "LIBRARY_ROOT_NOT_PROVIDED",
    )


def _write_consumer_manifest(path: Path, payload: dict[str, Any]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        first = json.loads(path.read_text(encoding="utf-8"))
        if first != payload:
            return False
        readback = payload.get("readback")
        readback = dict(readback) if isinstance(readback, dict) else {}
        readback.update({"verified": True, "path": str(path)})
        payload["readback"] = readback
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        final = json.loads(path.read_text(encoding="utf-8"))
        return final == payload
    except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _path_is_inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _library_roots_match(supplied_root: Path, declared_root: object) -> bool:
    if not isinstance(declared_root, str) or not declared_root.strip():
        return False
    try:
        return supplied_root.resolve(strict=False) == Path(declared_root).expanduser().resolve(
            strict=False
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    producer_root = args.producer_run_root.expanduser()
    output_root = args.output_root.expanduser()
    if producer_root.is_symlink() or not producer_root.is_dir():
        print("producer_unavailable")
        return 2
    producer_root = producer_root.resolve()
    output_resolved = output_root.resolve()
    if _path_is_inside(output_resolved, producer_root):
        print("consumer_output_conflict")
        return 2
    if output_root.is_symlink() or (output_root.exists() and not output_root.is_dir()):
        print("output_conflict")
        return 2
    if output_root.exists() and any(output_root.iterdir()):
        print("output_exists")
        return 2

    library_arg = args.viral_library_root
    library_value = library_arg or (
        Path(os.environ["MEDIA_INTEL_VIRAL_LIBRARY_ROOT"])
        if os.environ.get("MEDIA_INTEL_VIRAL_LIBRARY_ROOT")
        else None
    )
    if library_value is not None:
        library_value = Path(os.path.abspath(os.fspath(library_value.expanduser())))
        library_boundary = library_value.resolve(strict=False)
        if _path_is_inside(output_resolved, library_boundary):
            print("consumer_output_conflict")
            return 2

    manifest_path = producer_root / MANIFEST_NAME
    handoff_path = producer_root / HANDOFF_NAME
    summary_path = producer_root / SUMMARY_NAME
    producer_manifest = _read_json(manifest_path)
    handoff = _read_json(handoff_path)
    summary = _read_json(summary_path)
    if producer_manifest is None or handoff is None or summary is None:
        print("producer_evidence_incomplete")
        return 2
    valid_manifest, manifest_details = _verify_producer_manifest(
        producer_root, manifest_path, producer_manifest
    )
    if not valid_manifest:
        print(str(manifest_details.get("reason") or "producer_manifest_invalid"))
        return 2
    if (
        handoff.get("schema") != "media-intel-article-research-handoff/v1"
        or handoff.get("kind") != "producer_handoff"
    ):
        print("producer_handoff_invalid")
        return 2
    run_id = producer_manifest.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        print("producer_run_id_missing")
        return 2
    if handoff.get("daily_run_id") != run_id or summary.get("run_id") != run_id:
        print("producer_run_id_mismatch")
        return 2
    if summary.get("lane") != "article" or producer_manifest.get("lane") != "article":
        print("producer_lane_invalid")
        return 2
    handoff_statuses = {
        "research_status": _stage_status(handoff.get("research_status"), "FAIL"),
        "library_intake_status": _stage_status(
            handoff.get("library_intake_status"), "unavailable"
        ),
        "library_context_status": _stage_status(
            handoff.get("library_context_status"), "not_requested"
        ),
    }
    for key, value in handoff_statuses.items():
        if value is None or value not in ALLOWED_STAGE_STATUSES:
            print("producer_handoff_status_invalid")
            return 2
        if summary.get(key) != value:
            print("producer_status_mismatch")
            return 2
    if (
        handoff.get("publication_authorized") is not False
        or handoff.get("publication_performed") is not False
        or summary.get("publication_authorized") is not False
        or summary.get("publication_performed") is not False
    ):
        print("producer_publication_boundary_invalid")
        return 2
    research_valid, research_details = _verify_research_reference(
        producer_root, handoff
    )
    if not research_valid:
        print(str(research_details.get("reason") or "research_manifest_invalid"))
        return 2

    producer_manifest_digest = _raw_sha256(manifest_path)
    handoff_digest = _raw_sha256(handoff_path)
    summary_digest = _raw_sha256(summary_path)
    if not producer_manifest_digest or not handoff_digest or not summary_digest:
        print("producer_evidence_incomplete")
        return 2
    manifest_hashes = _manifest_hash_map(producer_manifest) or {}
    handoff_digest_verified = manifest_hashes.get(HANDOFF_NAME) == handoff_digest
    if not handoff_digest_verified:
        print("producer_handoff_digest_invalid")
        return 2

    if library_value is not None:
        if not _library_roots_match(library_value, handoff.get("library_root")):
            print("library_root_mismatch")
            return 2
        try:
            library_details, library_context_status, library_context_reason = _consume_library(
                library_root=library_value,
                output_root=output_resolved,
                producer_root=producer_root,
                requested_output_root=args.library_output_root,
            )
        except ValueError as error:
            print(str(error))
            return 2
    else:
        library_details, library_context_status, library_context_reason = _unconfigured_library(
            handoff_status=handoff_statuses["library_context_status"],
            declared_root=handoff.get("library_root"),
        )

    payload: dict[str, Any] = {
        "schema_version": "codex-daily-article-consumer/v1",
        "status": "candidate_evidence_only",
        "lane": "article",
        "date": summary.get("date") or producer_manifest.get("date"),
        "consumer_output_root": str(output_root),
        "producer": {
            "run_id": run_id,
            "run_root": str(producer_root),
            "manifest": {
                "path": str(manifest_path),
                "sha256": producer_manifest_digest,
                "readback": {"verified": True},
            },
            "handoff": {
                "path": str(handoff_path),
                "sha256": handoff_digest,
                "readback": {"verified": True},
                "digest_verified": handoff_digest_verified,
            },
            "summary": {
                "path": str(summary_path),
                "sha256": summary_digest,
                "readback": {"verified": True},
            },
            "research_manifest": research_details,
            "library_root": handoff.get("library_root"),
            "external_library_root": handoff.get("external_library_root")
            or handoff.get("library_root"),
            "status": summary.get("status"),
        },
        "research_status": handoff_statuses["research_status"],
        "research_run_id": handoff.get("research_run_id"),
        "library_intake_status": handoff_statuses["library_intake_status"],
        "library_context_status": library_context_status,
        "library_context_reason": library_context_reason,
        "library_root": str(library_value) if library_value is not None else None,
        "external_library_root": str(library_value) if library_value is not None else None,
        "library": library_details,
        "library_index": library_details.get("index"),
        "library_context": library_details.get("context"),
        "library_readback": library_details.get("readback", {"verified": False}),
        "producer_handoff_digest": {
            "path": str(handoff_path),
            "sha256": handoff_digest,
            "verified": handoff_digest_verified,
        },
        "source_retry_required": summary.get("source_retry_required"),
        "research_retry_required": handoff.get("research_retry_required"),
        "library_retry_required": handoff.get("library_retry_required"),
        "publication_authorized": False,
        "publication_performed": False,
        "hermes_modified": False,
        "kanban_modified": False,
        "coverage_gaps": [
            "This consumer verifies producer evidence and does not establish factual truth or publication readiness.",
            "The consumer reads the explicit library root read-only and writes index/context metadata outside both producer and library roots.",
        ],
        "readback": {
            "verified": False,
            "producer_handoff": handoff_digest_verified,
            "library": library_details.get("readback", {}).get("verified") is True,
        },
        "created_at": datetime.now().astimezone().isoformat(),
    }
    consumer_manifest_path = output_root / CONSUMER_MANIFEST_NAME
    if not _write_consumer_manifest(consumer_manifest_path, payload):
        print("consumer_manifest_write_failed")
        return 2
    print(
        json.dumps(
            {
                "status": payload["status"],
                "run_id": run_id,
                "producer_manifest_sha256": producer_manifest_digest,
                "consumer_manifest": str(consumer_manifest_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
