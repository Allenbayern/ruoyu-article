#!/usr/bin/env python3
"""Offline, fail-closed release rendering for verified daily3 candidate packets.

This layer consumes adapter output without altering raw/source/adapter/structural-gate
artifacts. It emits a WeChat-paste HTML fragment and a separate evidence artifact.
It does not publish, authorize publication, or assert WeChat-editor preview success.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

SLOTS = ("A", "B", "C")
MODE = "graphite_minimal_release"
MAX_TITLE_CJK = 30
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
# Every audience-visible text field must satisfy this policy. Rejecting, rather
# than rewriting, keeps audit text out of release artifacts deterministically.
#
# Canonical internal-audit text contract: a field label is forbidden when it
# names claim/source/atom identifiers, raw content hashes, or audit status/state.
# Labels are case-insensitive and may use whitespace, hyphen, underscore, slash,
# colon, period, or equals sign as separators. The value following a label is not
# interpreted; the internal label itself is enough to reject the candidate.
RELEASE_TEXT_POLICY = (
    re.compile(r"【\s*事实\s*】"),
    re.compile(r"claim[-_/\s]*map", re.IGNORECASE),
    re.compile(r"provenance", re.IGNORECASE),
    re.compile(r"run[-_/\s]*(?:status|id)", re.IGNORECASE),
    re.compile(r"publication[-_/\s]", re.IGNORECASE),
    re.compile(r"structural[-_/\s]*gate", re.IGNORECASE),
    re.compile(r"\b(?:claim|source|atom)[\s_\-/:.=]*id\b", re.IGNORECASE),
    re.compile(r"\braw[\s_\-/:.=]*sha[\s_\-/:.=]*256\b", re.IGNORECASE),
    re.compile(r"\braw[\s_\-/:.=]*hash\b", re.IGNORECASE),
    re.compile(r"\baudit[\s_\-/:.=]*(?:status|state)\b", re.IGNORECASE),
    re.compile(r"\{\{|\}\}|\$\{|<%|%>"),
)
FACT_PREFIX_RE = re.compile(r"^【\s*事实\s*】\s*")


class ReleaseRenderError(ValueError):
    """The candidate cannot become a controlled release-render artifact."""


def cjk_count(text: str) -> int:
    return len(CJK_RE.findall(text))


def require_text(value: Any, code: str, *, clean_fact_prefix: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReleaseRenderError(code)
    text = value.strip()
    if clean_fact_prefix:
        text = FACT_PREFIX_RE.sub("", text).strip()
        if not text:
            raise ReleaseRenderError(code)
    if any(pattern.search(text) for pattern in RELEASE_TEXT_POLICY):
        raise ReleaseRenderError("RELEASE_TEXT_POLICY_FORBIDDEN")
    return text


def clean_body(value: Any) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        raise ReleaseRenderError("MISSING_BODY")
    body = value.strip()
    paragraphs: list[str] = []
    for raw in re.split(r"\n{2,}", body):
        paragraph = raw.strip()
        if not paragraph:
            continue
        paragraphs.append(require_text(paragraph, "MISSING_BODY", clean_fact_prefix=True))
    if not paragraphs:
        raise ReleaseRenderError("MISSING_BODY")
    return paragraphs


def evidence_from_candidate(candidate: Any) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise ReleaseRenderError("INVALID_CANDIDATE")
    evidence = candidate.get("evidence")
    if not isinstance(evidence, dict):
        raise ReleaseRenderError("MISSING_EVIDENCE")
    claims, sources = evidence.get("claims"), evidence.get("sources")
    if not isinstance(claims, list) or not claims or not isinstance(sources, list) or not sources:
        raise ReleaseRenderError("MISSING_EVIDENCE")
    # Preserve evidence byte-for-byte in a separate JSON artifact; it must not render.
    return {"claims": claims, "sources": sources}


def leaf(text: str) -> str:
    return f'<span leaf="">{html.escape(text, quote=False)}</span>'


def render_fragment(title: str, paragraphs: list[str]) -> str:
    rendered = [
        '<section style="max-width:677px;margin:0 auto;background:#FFFFFF;font-family:-apple-system,BlinkMacSystemFont,\'PingFang SC\',\'Hiragino Sans GB\',\'Microsoft YaHei\',sans-serif;color:#52525B;line-height:1.8;letter-spacing:0.3px;overflow-x:hidden;">',
        '<section style="margin:10px 10px 40px;padding:24px 0 20px;border-bottom:1px solid #E4E4E7;background:#FFFFFF;">',
        f'<h1 style="font-size:24px;font-weight:800;color:#27272A;margin:0;letter-spacing:0.5px;line-height:1.4;">{leaf(title)}</h1>',
        "</section>",
        '<section style="padding:0 10px;">',
    ]
    rendered.extend(
        f'<p style="margin:0 0 22px;font-size:15px;line-height:1.8;text-align:justify;color:#52525B;letter-spacing:0.3px;">{leaf(paragraph)}</p>'
        for paragraph in paragraphs
    )
    rendered.extend(["</section>", "</section>"])
    return "".join(rendered)


def preview_document(title: str, fragment: str) -> str:
    return "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><title>" + html.escape(title, quote=False) + "</title></head><body>" + fragment + "</body></html>"


class _FragmentPreflightParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.open_tags: list[str] = []
        self.invalid = False

    def handle_decl(self, decl: str) -> None:
        self.invalid = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in {"html", "head", "body", "script"} or any(name.lower().startswith("on") for name, _ in attrs):
            self.invalid = True
        if lowered not in {"br", "meta", "link", "img", "input", "hr"}:
            self.open_tags.append(lowered)

    def handle_endtag(self, tag: str) -> None:
        if not self.open_tags or self.open_tags.pop() != tag.lower():
            self.invalid = True


def validate_local_deterministic_preflight(html_fragment: str) -> dict[str, Any]:
    """Fail closed on fragment wrappers, scripts, event attributes, and malformed HTML."""
    if not isinstance(html_fragment, str) or not html_fragment.strip():
        raise ReleaseRenderError("LOCAL_PREFLIGHT_HTML_EMPTY")
    parser = _FragmentPreflightParser()
    try:
        parser.feed(html_fragment)
        parser.close()
    except Exception as error:
        raise ReleaseRenderError("LOCAL_PREFLIGHT_HTML_INVALID") from error
    if parser.invalid or parser.open_tags:
        raise ReleaseRenderError("LOCAL_PREFLIGHT_HTML_INVALID")
    return {"kind": "local_deterministic_preflight", "validated": True}


def render_release_article(*, candidate: Any) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise ReleaseRenderError("INVALID_CANDIDATE")
    title = require_text(candidate.get("headline"), "MISSING_HEADLINE")
    if cjk_count(title) > MAX_TITLE_CJK:
        raise ReleaseRenderError("TITLE_CJK_LIMIT_EXCEEDED")
    paragraphs = clean_body(candidate.get("body"))
    evidence = evidence_from_candidate(candidate)
    fragment = render_fragment(title, paragraphs)
    validator = validate_local_deterministic_preflight(fragment)
    return {
        "mode": MODE,
        "title": title,
        "html": fragment,
        "preview_html": preview_document(title, fragment),
        "evidence": evidence,
        "validator": validator,
        "wechat_preview_verified": False,
        "coverage_gaps": ["No controlled WeChat-editor preview capability was available; local deterministic preflight is not preview verification."],
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def selected_candidate(data: dict[str, Any], slot: str) -> dict[str, Any]:
    slots = data.get("slots")
    candidates = slots.get(slot) if isinstance(slots, dict) else None
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise ReleaseRenderError(f"AMBIGUOUS_OR_MISSING_SLOT_{slot}")
    if not isinstance(candidates[0], dict):
        raise ReleaseRenderError("INVALID_CANDIDATE")
    return candidates[0]


def render_run(data: dict[str, Any], output: Path) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ReleaseRenderError("INVALID_INPUT")
    if output.exists():
        raise ReleaseRenderError("OUTPUT_PATH_ALREADY_EXISTS")
    temporary_root = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        slots_manifest: dict[str, Any] = {}
        for slot in SLOTS:
            candidate = selected_candidate(data, slot)
            rendered = render_release_article(candidate=candidate)
            slot_dir = temporary_root / "slots" / slot
            slot_dir.mkdir(parents=True)
            (slot_dir / "article.html").write_text(rendered["html"] + "\n", encoding="utf-8")
            (slot_dir / "preview.html").write_text(rendered["preview_html"] + "\n", encoding="utf-8")
            write_json(slot_dir / "evidence.json", rendered["evidence"])
            slots_manifest[slot] = {
                "candidate_id": candidate.get("id"),
                "title": rendered["title"],
                "title_cjk_count": cjk_count(rendered["title"]),
                "validator": rendered["validator"],
                "wechat_preview_verified": False,
            }
        manifest = {
            "run_id": data.get("run_id"),
            "status": "rendered_not_published",
            "publication_performed": False,
            "publication_authorized": False,
            "structural_gate_is_not_publication_authorization": True,
            "preflight": "local_deterministic_preflight",
            "validation": {"mode": "local_deterministic_preflight"},
            "wechat_preview_verified": False,
            "release_acceptance": {
                "status": "not_accepted",
                "reason": "WECHAT_PREVIEW_UNVERIFIED",
            },
            "coverage_gaps": ["No controlled WeChat-editor preview capability was available; local deterministic preflight is not preview verification."],
            "slots": slots_manifest,
        }
        write_json(temporary_root / "manifest.json", manifest)
        os.replace(temporary_root, output)
        return manifest
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="离线发布层渲染：生成粘贴 HTML 与独立 evidence，不发布、不授权发布。")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        manifest = render_run(data, args.output)
    except (OSError, json.JSONDecodeError, ReleaseRenderError) as error:
        print(str(error), file=sys.stderr)
        return 1
    if manifest["release_acceptance"]["status"] != "accepted":
        print(f"RELEASE_ACCEPTANCE_NOT_MET:{manifest['release_acceptance']['reason']}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
