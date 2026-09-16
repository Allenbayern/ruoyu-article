"""source_independence: mechanical syndication / independence screening.

Why this exists (2026-09-16, daily-008 扩写实验):
the same newsroom copy is republished by several platforms as a *rewrite*.
Measured on real pairs (潮新闻 → 中华网 → 中国网), sentence-level string
overlap is 0% while fact-level overlap is close to 100%.  Counting sources by
URL, host, or sentence similarity therefore produces **fake second sources**
and lets a single-source claim look cross-verified.  The same trap applies to
`min_distinct_scene_sources` style requirements, which are only meaningful if
"distinct" means "not a rewrite of the same original".

What it does: extracts *fact points* (numeric tokens with units, 《titles》,
quoted spans) plus maximal shared CJK spans, scores a candidate source against
the sources already collected for the same topic, and returns an advisory
verdict.  It is a screening aid only: it never authorizes publication, never
promotes state, and ambiguous cases stay `needs_human_review`.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SPAN_SIZE = 6
COPY_SPAN_RATIO = 0.50
REWRITE_SPAN_RATIO = 0.15
SHARED_MATERIAL_SPAN_RATIO = 0.05
REWRITE_NUMBER_OVERLAP = 0.60
MIN_SHARED_NUMBERS = 3
SHARED_MATERIAL_NUMBER_OVERLAP = 0.40
TITLE_OVERLAP_FOR_REWRITE = 0.50

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)
_TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_CJK_RUN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
_DATE_RE = re.compile(r"\d{4}年|\d{1,2}月\d{1,2}日")
_NUMBER_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|％|亿|万亿|千万|百万|万|分钟|小时|年|月|日|个|条|部|场|人|次|岁|元|倍|帧)"
)
_TITLE_MARK_RE = re.compile(r"《[^《》\n]{2,30}》")
_QUOTE_RE = re.compile(r"[“\"「『]([^”\"」』\n]{4,80})[”\"」』]")

_PRIMARY_MARKERS = (
    "记者", "专访", "独家", "本报", "摄影", "剧组", "摄制", "制片人",
    "导演表示", "姜文表示", "他在接受", "新闻发布会", "首映式",
)

VERDICTS = (
    "syndicated_copy",
    "syndicated_rewrite",
    "shared_public_material",
    "independent",
)


def visible_text(raw: str) -> str:
    """Strip scripts/styles/tags and collapse whitespace; keeps 《》 and quotes."""
    text = _SCRIPT_RE.sub(" ", raw)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def document_title(raw: str) -> str:
    """Best-effort document title (``<title>`` tag, else empty)."""
    match = _TITLE_TAG_RE.search(raw)
    return visible_text(match.group(1)) if match else ""


def cjk_chars(text: str) -> int:
    return len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))


def fact_points(text: str) -> dict[str, set[str]]:
    """Extract comparable fact points from reader-visible text."""
    numbers = {re.sub(r"\s+", "", token) for token in _NUMBER_RE.findall(text)}
    # 完整日期整体保留（"7月18日"），否则拆成"7月/18日"会削弱同稿识别。
    numbers |= {re.sub(r"\s+", "", token) for token in _DATE_RE.findall(text)}
    titles = set(_TITLE_MARK_RE.findall(text))
    quotes = {re.sub(r"\s+", "", quote) for quote in _QUOTE_RE.findall(text)}
    return {"numbers": numbers, "titles": titles, "quotes": quotes}


def _cjk_stream(text: str) -> str:
    """CJK-only stream, so spans never straddle markup or latin noise."""
    return "".join(_CJK_RUN_RE.findall(text))


def shared_spans(candidate: str, reference: str, *, span_size: int = SPAN_SIZE) -> list[str]:
    """Maximal runs (>= ``span_size`` chars) shared by two CJK streams.

    Rolling n-gram index instead of pairwise alignment: O(n) memory/time and
    stable on the few-thousand-character sources this pipeline captures.
    """
    left = _cjk_stream(candidate)
    right = _cjk_stream(reference)
    if len(left) < span_size or len(right) < span_size:
        return []
    reference_grams = {right[i:i + span_size] for i in range(len(right) - span_size + 1)}
    matched = [
        left[i:i + span_size] in reference_grams
        for i in range(len(left) - span_size + 1)
    ]
    spans: list[str] = []
    start: int | None = None
    for index, hit in enumerate(matched + [False]):
        if hit and start is None:
            start = index
        elif not hit and start is not None:
            spans.append(left[start:index + span_size - 1])
            start = None
    return spans


def _overlap(candidate: set[str], reference: set[str]) -> tuple[float, list[str]]:
    if not candidate:
        return 0.0, []
    shared = sorted(candidate & reference)
    return len(shared) / len(candidate), shared


def compare_pair(candidate_text: str, reference_text: str) -> dict[str, Any]:
    """Score one candidate source against one already-collected source."""
    candidate_chars = cjk_chars(candidate_text)
    spans = shared_spans(candidate_text, reference_text)
    span_chars = sum(len(span) for span in spans)
    candidate_points = fact_points(candidate_text)
    reference_points = fact_points(reference_text)
    number_overlap, shared_numbers = _overlap(candidate_points["numbers"], reference_points["numbers"])
    title_overlap, shared_titles = _overlap(candidate_points["titles"], reference_points["titles"])
    quote_overlap, shared_quotes = _overlap(candidate_points["quotes"], reference_points["quotes"])
    return {
        "candidate_cjk": candidate_chars,
        "reference_cjk": cjk_chars(reference_text),
        "shared_span_chars": span_chars,
        "span_ratio": round(span_chars / candidate_chars, 4) if candidate_chars else 0.0,
        "longest_shared_spans": sorted(spans, key=len, reverse=True)[:5],
        "number_overlap": round(number_overlap, 4),
        "shared_numbers": shared_numbers[:12],
        "title_overlap": round(title_overlap, 4),
        "shared_titles": shared_titles[:8],
        "quote_overlap": round(quote_overlap, 4),
        "shared_quotes": shared_quotes[:5],
    }


def classify(comparisons: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Turn pairwise scores into one advisory verdict plus review flags."""
    if not comparisons:
        return {
            "verdict": "independent",
            "confidence": "low",
            "needs_human_review": True,
            "reasons": ["no_reference_sources_provided"],
            "primary_markers": [],
        }
    worst = max(comparisons, key=lambda item: (float(item.get("span_ratio") or 0.0),
                                               float(item.get("number_overlap") or 0.0)))
    span_ratio = float(worst.get("span_ratio") or 0.0)
    number_overlap = float(worst.get("number_overlap") or 0.0)
    title_overlap = float(worst.get("title_overlap") or 0.0)
    shared_numbers = list(worst.get("shared_numbers") or [])
    reasons = [f"span_ratio={span_ratio}", f"number_overlap={number_overlap}"]

    if span_ratio >= COPY_SPAN_RATIO:
        verdict, confidence = "syndicated_copy", "high"
    elif number_overlap >= REWRITE_NUMBER_OVERLAP and len(shared_numbers) >= MIN_SHARED_NUMBERS:
        verdict, confidence = "syndicated_rewrite", "high"
    elif span_ratio >= REWRITE_SPAN_RATIO and (
        number_overlap >= SHARED_MATERIAL_NUMBER_OVERLAP
        or title_overlap >= TITLE_OVERLAP_FOR_REWRITE
    ):
        verdict, confidence = "syndicated_rewrite", "medium"
    elif span_ratio >= SHARED_MATERIAL_SPAN_RATIO or number_overlap >= SHARED_MATERIAL_NUMBER_OVERLAP:
        verdict, confidence = "shared_public_material", "medium"
    else:
        verdict, confidence = "independent", "medium"

    if verdict == "syndicated_copy":
        reasons.append("candidate text largely reproduces a reference source")
    elif verdict == "syndicated_rewrite":
        reasons.append("same numbers/titles in different wording: rewrite of one original")
    elif verdict == "shared_public_material":
        reasons.append("shares public facts or event quotes; independence not established")
    reasons.append(f"closest_reference={worst.get('reference')}")
    return {
        "verdict": verdict,
        "confidence": confidence,
        "needs_human_review": verdict in {"shared_public_material", "independent"} and confidence != "high",
        "reasons": reasons,
        "primary_markers": [],
        "closest_reference": worst.get("reference"),
    }


def screen_source(
    candidate_text: str,
    references: Mapping[str, str],
    *,
    candidate_name: str = "candidate",
) -> dict[str, Any]:
    """Screen one candidate source against a mapping of reference sources."""
    comparisons: list[dict[str, Any]] = []
    for name, text in references.items():
        if name == candidate_name:
            continue
        comparison = compare_pair(candidate_text, text)
        comparison["reference"] = name
        comparisons.append(comparison)
    primary_markers = sorted({marker for marker in _PRIMARY_MARKERS if marker in candidate_text})
    verdict = classify(comparisons)
    verdict["primary_markers"] = primary_markers
    independent = verdict["verdict"] == "independent"
    verdict["counts_as_distinct_source"] = bool(independent)
    verdict["candidate"] = candidate_name
    verdict["candidate_cjk"] = cjk_chars(candidate_text)
    verdict["pairwise"] = comparisons
    verdict["advisory"] = True
    verdict["publication_authorization"] = "not_authorized"
    return verdict


def _published_epoch(value: str | None) -> float:
    """Parse an ISO-ish publication stamp into a sortable epoch (0 when absent)."""
    if not value:
        return 0.0
    token = value.strip().replace("/", "-").replace("T", " ")
    match = re.match(
        r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ ](\d{1,2}):(\d{2}))?",
        token,
    )
    if not match:
        return 0.0
    year, month, day, hour, minute = match.groups()
    return (((int(year) * 13 + int(month)) * 32 + int(day)) * 24 + int(hour or 0)) * 60 + int(minute or 0)


def _canonical_key(entry: Mapping[str, Any]) -> tuple[int, float, int]:
    """Rank a source as the probable original of its equivalence class.

    Primary-source markers first (记者/专访/首映式/剧组 …), then the earliest
    publication stamp, then the longest text.  Deliberately *not* length alone:
    in the daily-008 sample the rewrite (3 117 CJK) was longer than the
    newsroom original (2 028 CJK).
    """
    text = str(entry.get("text") or "")
    markers = sum(1 for marker in _PRIMARY_MARKERS if marker in text)
    epoch = _published_epoch(entry.get("published_at"))
    return (markers, -epoch if epoch else -float("inf"), cjk_chars(text))


def _pair_relation(left: str, right: str) -> dict[str, Any]:
    """Symmetric relation between two sources (no candidate/original bias).

    Scored in both directions and merged element-wise: overlap ratios are
    denominator-based, so a short rewrite of a long original only shows up in
    the short→long direction.  Taking one direction alone silently produced
    "independent" pairs for real rewrite chains.
    """
    forward = compare_pair(left, right)
    backward = compare_pair(right, left)
    merged = {
        "candidate_cjk": forward["candidate_cjk"],
        "reference_cjk": forward["reference_cjk"],
        "span_ratio": max(float(forward["span_ratio"]), float(backward["span_ratio"])),
        "shared_span_chars": max(int(forward["shared_span_chars"]), int(backward["shared_span_chars"])),
        "longest_shared_spans": forward["longest_shared_spans"],
        "number_overlap": max(float(forward["number_overlap"]), float(backward["number_overlap"])),
        "shared_numbers": sorted({*forward["shared_numbers"], *backward["shared_numbers"]}),
        "title_overlap": max(float(forward["title_overlap"]), float(backward["title_overlap"])),
        "shared_titles": sorted({*forward["shared_titles"], *backward["shared_titles"]}),
        "quote_overlap": max(float(forward["quote_overlap"]), float(backward["quote_overlap"])),
        "shared_quotes": forward["shared_quotes"],
    }
    verdict = classify([{**merged, "reference": "peer"}])["verdict"]
    return {**merged, "relation": verdict}


def group_sources(
    sources: Mapping[str, str],
    *,
    published: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Group sources into equivalence classes; one class == one distinct source.

    A rewrite of the same newsroom copy must not inflate
    ``min_distinct_scene_sources``; this is where that is computed.
    """
    stamps = dict(published or {})
    entries = {
        name: {"name": name, "text": text, "published_at": stamps.get(name)}
        for name, text in sources.items()
    }
    names = list(entries)
    parent = {name: name for name in names}

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    def union(left: str, right: str) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    relations: list[dict[str, Any]] = []
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            relation = _pair_relation(entries[left]["text"], entries[right]["text"])
            relation.update({"left": left, "right": right})
            relations.append(relation)
            if relation["relation"] in {"syndicated_copy", "syndicated_rewrite"}:
                union(left, right)

    classes: dict[str, list[str]] = {}
    for name in names:
        classes.setdefault(find(name), []).append(name)

    groups: list[dict[str, Any]] = []
    for members in classes.values():
        canonical = max(members, key=lambda name: _canonical_key(entries[name]))
        group: dict[str, Any] = {
            "canonical": canonical,
            "canonical_reason": "primary_markers > earlier_published_at > longer_text",
            "members": [],
            "distinct_source": True,
        }
        for name in sorted(members):
            if name == canonical:
                group["members"].append({
                    "source_id": name,
                    "role": "canonical",
                    "published_at": entries[name].get("published_at") or "",
                    "cjk_chars": cjk_chars(entries[name]["text"]),
                    "primary_markers": sorted(
                        {marker for marker in _PRIMARY_MARKERS if marker in entries[name]["text"]}
                    ),
                })
                continue
            relation = _pair_relation(entries[name]["text"], entries[canonical]["text"])
            group["members"].append({
                "source_id": name,
                "role": relation["relation"],
                "published_at": entries[name].get("published_at") or "",
                "cjk_chars": cjk_chars(entries[name]["text"]),
                "span_ratio": relation["span_ratio"],
                "number_overlap": relation["number_overlap"],
                "shared_numbers": relation["shared_numbers"][:8],
                "counts_as_distinct_source": False,
            })
        if len(members) > 1:
            group["distinct_source"] = False
            group["note"] = "same original copy republished via rewrite; counts once"
        groups.append(group)

    distinct = [group["canonical"] for group in groups]
    return {
        "schema_version": "source-independence-v1",
        "groups": groups,
        "relations": relations,
        "distinct_source_count": len(groups),
        "distinct_sources": distinct,
        "advisory": True,
        "publication_authorization": "not_authorized",
    }


def group_files(
    paths: Sequence[Path],
    *,
    published: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """File-level wrapper around :func:`group_sources`."""
    texts = {
        path.name: visible_text(path.read_text(encoding="utf-8", errors="replace"))
        for path in paths
    }
    return group_sources(texts, published=published)


def screen_files(candidate: Path, references: Sequence[Path]) -> dict[str, Any]:
    """File-level wrapper: reads UTF-8 text (HTML tolerated) and screens it."""
    candidate_text = visible_text(candidate.read_text(encoding="utf-8", errors="replace"))
    reference_texts = {
        path.name: visible_text(path.read_text(encoding="utf-8", errors="replace"))
        for path in references
    }
    return screen_source(candidate_text, reference_texts, candidate_name=candidate.name)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m article_group.source_independence",
        description="Group collected sources into equivalence classes (syndication / "
                    "rewrite detection) and screen a candidate source. Advisory only.",
    )
    parser.add_argument("--source", type=Path, action="append", default=[], metavar="PATH",
                        help="any collected source file (HTML or text); repeat per source")
    parser.add_argument("--published", action="append", default=[], metavar="NAME=ISO",
                        help="publication stamp for a source name; repeat per source")
    parser.add_argument("--candidate", type=Path,
                        help="screen this file against every --source instead of grouping")
    parser.add_argument("--json", action="store_true", help="print the full report")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    stamps: dict[str, str] = {}
    for item in args.published:
        name, _, value = str(item).partition("=")
        if name and value:
            stamps[name.strip()] = value.strip()

    if args.candidate is not None:
        report = screen_files(args.candidate, list(args.source))
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"{report['candidate']}: {report['verdict']} ({report['confidence']})")
            print(f"  distinct_source={report['counts_as_distinct_source']} "
                  f"cjk={report['candidate_cjk']}")
            print(f"  reasons: {'; '.join(report['reasons'])}")
            if report["primary_markers"]:
                print(f"  primary_markers: {', '.join(report['primary_markers'])}")
        return 0

    if not args.source:
        _build_parser().error("provide --source PATH (repeatable) or --candidate PATH")
    report = group_files(list(args.source), published=stamps)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    print(f"distinct sources: {report['distinct_source_count']}")
    for group in report["groups"]:
        flag = "distinct" if group["distinct_source"] else "duplicate-group"
        print(f"- [{flag}] canonical={group['canonical']}")
        for member in group["members"]:
            extra = ""
            if member["role"] != "canonical":
                extra = f" span_ratio={member.get('span_ratio')} number_overlap={member.get('number_overlap')}"
            print(f"    {member['source_id']}: {member['role']}{extra}")
    return 0


__all__ = [
    "SPAN_SIZE",
    "VERDICTS",
    "visible_text",
    "document_title",
    "fact_points",
    "shared_spans",
    "compare_pair",
    "classify",
    "screen_source",
    "screen_files",
    "group_sources",
    "group_files",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())

