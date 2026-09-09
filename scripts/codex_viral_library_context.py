#!/usr/bin/env python3
"""Build a bounded, content-free context from one live viral library.

The context is a research aid only.  It contains deterministic structure
labels and opaque references, never article wording, titles, account names,
URLs, facts, or publication authority.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any, Iterable

try:  # Support both package imports and ``python scripts/...`` execution.
    from .codex_viral_library_reader import (
        LibraryReaderError,
        read_library,
        read_snapshot_for_bounded_classifier,
    )
except ImportError:  # pragma: no cover - exercised by direct script execution.
    from codex_viral_library_reader import (  # type: ignore[no-redef]
        LibraryReaderError,
        read_library,
        read_snapshot_for_bounded_classifier,
    )


CONTEXT_SCHEMA_VERSION = "codex-viral-library-context-v1"
MAX_POSITIVE_SAMPLES = 3
MAX_REFERENCE_IDS = 8
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_OPAQUE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_ERROR_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,79}\Z")
_TOKEN_PATTERN = re.compile(
    r"[\u4e00-\u9fff]{2,}|[a-z]{3,}|\d{2,}",
    re.IGNORECASE,
)

TITLE_STRATEGIES = frozenset({"question", "contrast", "event", "statement", "unknown"})
HOOK_TYPES = frozenset({"conflict", "question", "scene", "claim", "unknown"})
LENGTH_BUCKETS = frozenset({"short", "medium", "long"})
STRUCTURE_ROLES = frozenset({"hook", "context", "turn", "analysis", "evidence", "close"})
CLOSING_ACTIONS = frozenset(
    {"question", "interaction", "insight", "summary", "none", "unknown"}
)
TOPIC_MATCHES = frozenset({"broad", "related", "unknown"})

_DEFAULT_LIMITATIONS = [
    "structure_labels_are_bounded_heuristics",
    "facts_titles_accounts_and_wording_are_excluded",
    "historical_samples_do_not_verify_current_facts",
]
_DISCLAIMER = (
    "Research metadata only; labels are not factual proof, a writing rule, "
    "or publication authorization."
)


def _require_absolute_path(
    value: str | Path,
    *,
    code: str,
    preserve_symlinks: bool = False,
) -> Path:
    try:
        raw = os.fspath(value)
    except TypeError as error:
        raise ValueError(code) from error
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(code)
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError(code)
    if preserve_symlinks:
        return path
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as error:
        raise ValueError(code) from error


def _safe_error_code(value: object, fallback: str) -> str:
    if isinstance(value, str) and _ERROR_PATTERN.fullmatch(value):
        return value
    return fallback


def _first_error_code(report: dict[str, Any], fallback: str = "LIBRARY_UNAVAILABLE") -> str:
    errors = report.get("errors")
    if isinstance(errors, list):
        for error in errors:
            if isinstance(error, dict):
                code = _safe_error_code(error.get("code"), "")
                if code:
                    return code
    return fallback


def _output_conflicts_with_library(output_path: Path, library_root: Path) -> bool:
    try:
        resolved_output = output_path.resolve(strict=False)
        resolved_root = library_root.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return True
    if resolved_output == resolved_root or resolved_root in resolved_output.parents:
        return True

    # Refuse replacing an external hard link to the library database or its
    # journal/WAL sidecars.  This keeps the output boundary explicit even when
    # the pathname itself is outside the root.
    try:
        output_stat = os.stat(output_path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            library_stat = os.stat(resolved_root / f"library.sqlite{suffix}")
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


def _serialized_json(result: dict[str, Any]) -> str:
    return json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _write_and_readback(path: Path, result: dict[str, Any]) -> None:
    parent = path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise RuntimeError("CONTEXT_OUTPUT_DIRECTORY_FAILED") from error
    try:
        parent_stat = os.stat(parent)
    except OSError as error:
        raise RuntimeError("CONTEXT_OUTPUT_DIRECTORY_FAILED") from error
    if not stat.S_ISDIR(parent_stat.st_mode):
        raise RuntimeError("CONTEXT_OUTPUT_DIRECTORY_FAILED")

    serialized = _serialized_json(result) + "\n"
    temporary_path: Path | None = None
    descriptor: int | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(parent),
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = None
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None

        readback = path.read_text(encoding="utf-8")
        if json.loads(readback) != result:
            raise ValueError
        if hashlib.sha256(readback.encode("utf-8")).hexdigest() != hashlib.sha256(
            serialized.encode("utf-8")
        ).hexdigest():
            raise ValueError
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise RuntimeError("CONTEXT_OUTPUT_READBACK_FAILED") from error
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass


def _nonempty_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value else None


def _tokens(value: str) -> set[str]:
    return {match.group(0).lower() for match in _TOKEN_PATTERN.finditer(value)}


def _normalised_for_phrase(value: str) -> str:
    return "".join(character.lower() for character in value if character.isalnum())


def _topic_terms(current_topic: object, current_brief: object) -> tuple[str | None, set[str]]:
    topic = _nonempty_text(current_topic)
    brief = _nonempty_text(current_brief)
    combined = " ".join(part for part in (topic, brief) if part)
    return topic, _tokens(combined)


def _topic_match(body: str, topic: str | None, terms: set[str]) -> str:
    if topic is None and not terms:
        return "unknown"
    body_tokens = _tokens(body)
    overlap = terms & body_tokens
    phrase = _normalised_for_phrase(topic) if topic is not None else ""
    body_phrase = _normalised_for_phrase(body)
    if phrase and len(phrase) >= 2 and phrase in body_phrase:
        return "broad"
    if len(overlap) >= 2:
        return "broad"
    if overlap:
        return "related"
    return "unknown"


def _paragraphs(body: str) -> list[str]:
    paragraphs = [
        re.sub(r"^[>#*\-\s]+", "", part).strip()
        for part in re.split(r"\n\s*\n+", body)
    ]
    return [paragraph for paragraph in paragraphs if paragraph]


def _length_bucket(text: str) -> str:
    length = len(text)
    if length <= 80:
        return "short"
    if length <= 240:
        return "medium"
    return "long"


def _title_strategy(title: str) -> str:
    if not title:
        return "unknown"
    if "?" in title or "？" in title or re.search(r"为什么|如何|谁是|到底|难道", title):
        return "question"
    if re.search(r"不是.{0,24}(而是|却是)|却|然而|但是|反而|对比|两种", title):
        return "contrast"
    if re.search(r"官宣|定档|上映|开播|发布|回应|获奖|票房|热搜|突发|宣布", title):
        return "event"
    return "statement"


def _opening_hook(paragraph: str) -> dict[str, str]:
    if not paragraph:
        return {"type": "unknown", "length_bucket": "short"}
    if "?" in paragraph or "？" in paragraph or re.search(
        r"为什么|如何|谁是|到底|难道|你会|你觉得", paragraph
    ):
        hook_type = "question"
    elif re.search(r"冲突|争议|矛盾|却|然而|但是|反而|失去|对立|问题|真相", paragraph):
        hook_type = "conflict"
    elif re.search(r"镜头|银幕|散场|现场|走进|站在|夜里|清晨|灯光|雨中|门口", paragraph):
        hook_type = "scene"
    else:
        hook_type = "claim"
    return {"type": hook_type, "length_bucket": _length_bucket(paragraph)}


def _paragraph_role(paragraph: str, index: int, total: int) -> str:
    if index == 0:
        return "hook"
    if index == total - 1 and total > 1:
        return "close"
    if re.search(r"但|然而|不过|转折|真正|关键|问题在于|反而", paragraph):
        return "turn"
    if re.search(r"数据|证据|根据|显示|报道|来源|调查|纪录|\d{2,}", paragraph):
        return "evidence"
    if index == 1 or re.search(r"背景|此前|一直|从前|如今|当时|随后", paragraph):
        return "context"
    return "analysis"


def _structure_outline(paragraphs: list[str]) -> list[str]:
    if not paragraphs:
        return []
    return [
        role
        for index, paragraph in enumerate(paragraphs[:8])
        if (role := _paragraph_role(paragraph, index, len(paragraphs))) in STRUCTURE_ROLES
    ]


def _closing_action(paragraphs: list[str]) -> str:
    if not paragraphs:
        return "unknown"
    closing = paragraphs[-1]
    if "?" in closing or "？" in closing or re.search(r"你怎么看|怎么看|觉得呢|是否会", closing):
        return "question"
    if re.search(r"留言|评论|分享|互动|告诉我|说说", closing):
        return "interaction"
    if re.search(r"这说明|真正|意味着|答案|归根", closing):
        return "insight"
    if re.search(r"总之|因此|所以|最后|总结", closing):
        return "summary"
    return "none"


def _reference_ids(
    references: object,
    *,
    key: str,
) -> list[str]:
    if not isinstance(references, list):
        return []
    values: set[str] = set()
    for reference in references:
        if not isinstance(reference, dict):
            continue
        value = reference.get(key)
        if isinstance(value, str) and _OPAQUE_ID_PATTERN.fullmatch(value):
            values.add(value)
    return sorted(values)[:MAX_REFERENCE_IDS]


def _content_hash(sample: dict[str, Any]) -> str | None:
    value = sample.get("content_hash")
    if not isinstance(value, str) or _HASH_PATTERN.fullmatch(value) is None:
        return None
    return value


def _opaque_sample_id(sample: dict[str, Any], content_hash: str) -> str:
    case_id = sample.get("case_id")
    seed = f"{content_hash}\x00{case_id if isinstance(case_id, str) else ''}"
    return "sample-" + hashlib.sha256(seed.encode("utf-8", "surrogatepass")).hexdigest()[:24]


def _base_context(
    *,
    generated_at: str,
    status: str,
    reason: str,
    topic_provided: bool,
    brief_provided: bool,
    topic_match: str,
    positive_samples: list[dict[str, Any]],
    limitations: Iterable[str] = (),
) -> dict[str, Any]:
    if topic_match not in TOPIC_MATCHES:
        topic_match = "unknown"
    all_limitations = list(dict.fromkeys([*_DEFAULT_LIMITATIONS, *limitations]))
    return {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "version": 1,
        "generated_at": generated_at,
        "status": status,
        "reason": reason,
        "input": {
            "topic_provided": topic_provided,
            "brief_provided": brief_provided,
            "topic_match": topic_match,
        },
        "positive_samples": positive_samples,
        "limitations": all_limitations,
        "disclaimer": _DISCLAIMER,
    }


def _unavailable_context(
    *,
    generated_at: str,
    reason: str,
    topic_provided: bool,
    brief_provided: bool,
) -> dict[str, Any]:
    return _base_context(
        generated_at=generated_at,
        status="unavailable",
        reason=_safe_error_code(reason, "LIBRARY_UNAVAILABLE"),
        topic_provided=topic_provided,
        brief_provided=brief_provided,
        topic_match="unknown",
        positive_samples=[],
        limitations=("live_library_only", "no_historical_fallback"),
    )


def build_library_context(
    library_root: str | Path,
    output_path: str | Path,
    current_topic: str | None = None,
    current_brief: str | None = None,
) -> dict[str, Any]:
    """Build and atomically write a safe context for one explicit library.

    Both paths are required to be absolute.  ``current_topic`` and
    ``current_brief`` are used only in memory for matching and never copied to
    the result.
    """

    root = _require_absolute_path(
        library_root,
        code="LIBRARY_ROOT_MUST_BE_ABSOLUTE",
        preserve_symlinks=True,
    )
    output = _require_absolute_path(output_path, code="CONTEXT_OUTPUT_MUST_BE_ABSOLUTE")
    if _output_conflicts_with_library(output, root):
        raise ValueError("CONTEXT_OUTPUT_EXTERNAL_LIBRARY_CONFLICT")

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    topic, terms = _topic_terms(current_topic, current_brief)
    topic_provided = topic is not None
    brief_provided = _nonempty_text(current_brief) is not None

    report = read_library(root)
    if not isinstance(report, dict) or report.get("status") != "available":
        result = _unavailable_context(
            generated_at=generated_at,
            reason=_first_error_code(report if isinstance(report, dict) else {}),
            topic_provided=topic_provided,
            brief_provided=brief_provided,
        )
        _write_and_readback(output, result)
        return result

    manifest = report.get("consumer_manifest")
    if (
        not isinstance(manifest, dict)
        or manifest.get("status") != "verified"
        or not isinstance(manifest.get("readback"), dict)
        or manifest["readback"].get("verified") is not True
    ):
        result = _unavailable_context(
            generated_at=generated_at,
            reason="CONSUMER_MANIFEST_READBACK_UNVERIFIED",
            topic_provided=topic_provided,
            brief_provided=brief_provided,
        )
        _write_and_readback(output, result)
        return result

    raw_samples = report.get("samples")
    if not isinstance(raw_samples, list):
        result = _unavailable_context(
            generated_at=generated_at,
            reason="LIBRARY_SAMPLES_UNAVAILABLE",
            topic_provided=topic_provided,
            brief_provided=brief_provided,
        )
        _write_and_readback(output, result)
        return result

    eligible: list[dict[str, Any]] = []
    for sample in raw_samples:
        if not isinstance(sample, dict):
            continue
        if sample.get("platform") != "wechat":
            continue
        if sample.get("qualification_status") != "qualified_viral":
            continue
        if sample.get("eligible_for_case") is not True:
            continue
        if sample.get("is_republished") is True:
            continue
        if sample.get("availability") != "available":
            continue
        if sample.get("usable_for_positive_patterns") is not True:
            continue
        content_hash = _content_hash(sample)
        account_id = sample.get("account_id")
        if content_hash is None or not isinstance(account_id, str) or not account_id:
            continue
        evidence_ids = _reference_ids(sample.get("evidence_refs"), key="evidence_ref_id")
        review_ids = _reference_ids(sample.get("review_refs"), key="review_id")
        if not evidence_ids or not review_ids:
            continue
        eligible.append(
            {
                "sample": sample,
                "content_hash": content_hash,
                "account_id": account_id,
                "evidence_ids": evidence_ids,
                "review_ids": review_ids,
            }
        )

    # Pick one deterministic representative per account before applying the
    # three-sample cap.  Account IDs never cross the output boundary.
    by_account: dict[str, dict[str, Any]] = {}
    for candidate in sorted(
        eligible,
        key=lambda item: (
            item["account_id"],
            item["content_hash"],
            str(item["sample"].get("case_id", "")),
        ),
    ):
        by_account.setdefault(candidate["account_id"], candidate)
    deduplicated = sorted(
        by_account.values(),
        key=lambda item: (item["content_hash"], str(item["sample"].get("case_id", ""))),
    )

    selected: list[dict[str, Any]] = []
    matches: list[str] = []
    for candidate in deduplicated:
        sample = candidate["sample"]
        try:
            body = read_snapshot_for_bounded_classifier(root, sample)
        except LibraryReaderError as error:
            result = _unavailable_context(
                generated_at=generated_at,
                reason=_safe_error_code(getattr(error, "code", None), "SNAPSHOT_CLASSIFIER_FAILED"),
                topic_provided=topic_provided,
                brief_provided=brief_provided,
            )
            _write_and_readback(output, result)
            return result
        except (OSError, UnicodeError, ValueError):
            result = _unavailable_context(
                generated_at=generated_at,
                reason="SNAPSHOT_CLASSIFIER_FAILED",
                topic_provided=topic_provided,
                brief_provided=brief_provided,
            )
            _write_and_readback(output, result)
            return result
        except Exception:
            result = _unavailable_context(
                generated_at=generated_at,
                reason="SNAPSHOT_CLASSIFIER_FAILED",
                topic_provided=topic_provided,
                brief_provided=brief_provided,
            )
            _write_and_readback(output, result)
            return result

        match = _topic_match(body, topic, terms)
        if topic is not None or terms:
            if match == "unknown":
                continue
        matches.append(match)
        paragraphs = _paragraphs(body)
        title = paragraphs[0] if paragraphs else ""
        opening = paragraphs[1] if len(paragraphs) > 1 else (paragraphs[0] if paragraphs else "")
        selected.append(
            {
                "sample_id": _opaque_sample_id(sample, candidate["content_hash"]),
                "content_hash": candidate["content_hash"],
                "evidence_ref_ids": candidate["evidence_ids"],
                "review_ref_ids": candidate["review_ids"],
                "title_strategy": _title_strategy(title),
                "opening_hook": _opening_hook(opening),
                "structure_outline": _structure_outline(paragraphs),
                "closing_action": _closing_action(paragraphs),
                "topic_match": match if match in TOPIC_MATCHES else "unknown",
            }
        )
        if len(selected) >= MAX_POSITIVE_SAMPLES:
            break

    limitations: list[str] = []
    if len(by_account) < len(eligible):
        limitations.append("account_deduplicated")
    if len(eligible) > MAX_POSITIVE_SAMPLES:
        limitations.append("positive_samples_capped_at_three")
    if len(selected) == 1:
        limitations.append("insufficient_diversity")

    if not selected:
        reason = "no_topic_matching_samples" if topic is not None or terms else "no_safe_qualified_samples"
        overall_match = "unknown"
    else:
        reason = "qualified_samples_selected"
        overall_match = "broad" if "broad" in matches else "related" if "related" in matches else "unknown"

    result = _base_context(
        generated_at=generated_at,
        status="available",
        reason=reason,
        topic_provided=topic_provided,
        brief_provided=brief_provided,
        topic_match=overall_match,
        positive_samples=selected,
        limitations=limitations,
    )
    _write_and_readback(output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--viral-library-root",
        type=Path,
        required=True,
        help="explicit absolute persistent viral-library root (read-only)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="explicit absolute JSON output path outside the library root",
    )
    parser.add_argument(
        "--topic",
        help="optional current topic used only for internal matching",
    )
    args = parser.parse_args(argv)
    try:
        result = build_library_context(
            args.viral_library_root,
            args.output,
            current_topic=args.topic,
        )
    except (ValueError, RuntimeError):
        print("context_output_failed")
        return 2
    print(_serialized_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_library_context", "main"]
