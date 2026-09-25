from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from article_group.review_surface import (
    DEFAULT_REVIEW_SURFACE,
    LEGACY_REVIEW_SURFACES,
    build_markdown_review_evidence,
    is_markdown_surface,
    normalize_review_surface,
    resolve_review_surface,
    validate_batch_review_surface,
    validate_markdown_review_evidence,
)


def _article(article_id: str, path: str) -> dict[str, str]:
    return {"article_id": article_id, "markdown_path": path}


def test_legacy_contract_value_still_reads_as_the_markdown_surface() -> None:
    """2026-09-25 契约值迁移：**历史产物不重写**，所以读端必须照样认旧值。

    旧值是 `markdown_codex`（写它的时候还没有这次改名）。读端把它折到现值，
    写端只写现值——两边都靠这里钉住。
    """
    assert LEGACY_REVIEW_SURFACES == {"markdown_codex": DEFAULT_REVIEW_SURFACE}
    assert DEFAULT_REVIEW_SURFACE == "markdown_dsh"

    # 折值：只折历史值，非法值原样交给校验去拒
    assert normalize_review_surface("markdown_codex") == DEFAULT_REVIEW_SURFACE
    assert normalize_review_surface("  markdown_codex  ") == DEFAULT_REVIEW_SURFACE
    assert normalize_review_surface("html_delivery") == "html_delivery"
    assert normalize_review_surface("browser") == "browser"
    assert normalize_review_surface(None) is None

    # 判定与解析
    assert is_markdown_surface("markdown_codex") is True
    assert is_markdown_surface("markdown_dsh") is True
    assert is_markdown_surface("html_delivery") is False
    assert resolve_review_surface("markdown_codex") == DEFAULT_REVIEW_SURFACE

    # 校验：历史 batch 仍然合法（否则迁移就等于让既有 run 的门禁读不出自己）
    assert validate_batch_review_surface({"review_surface": "markdown_codex"}) == []
    assert validate_batch_review_surface(
        {"review_surface": "markdown_codex"}, require_explicit=True) == []
    # 但"markdown 面 + preview_mode"这条禁令对**历史值**一样生效
    assert "preview_mode_forbidden_for_markdown_surface" in validate_batch_review_surface(
        {"review_surface": "markdown_codex", "preview_mode": "local_dsh"})
    # 非法值不许被静默兜底成合法值
    assert validate_batch_review_surface({"review_surface": "browser"}) == [
        "review_surface_invalid:browser"]


def test_a_real_historical_batch_fixture_still_gates_as_markdown(tmp_path: Path) -> None:
    """真实的**历史产物**（v4 夹具里写的就是旧值）走读端不许被读成"不是 markdown 面"。"""
    fixture = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "v4" / "controlled-002" / "batch.json")
        .read_text(encoding="utf-8")
    )
    assert fixture["review_surface"] == "markdown_codex", "夹具应保留历史值（它正是兼容证据）"
    assert validate_batch_review_surface(fixture, require_explicit=True) == []
    assert resolve_review_surface(fixture["review_surface"]) == DEFAULT_REVIEW_SURFACE


def test_markdown_review_evidence_written_today_uses_the_new_value(tmp_path: Path) -> None:
    """写端只写新值：今天再生成的证据里不许出现历史值。"""
    _write_markdown(tmp_path, "drafts/art-001.md", "# 标题\n\n" + "黄金" * 750 + "\n")
    payload = build_markdown_review_evidence(
        tmp_path, [_article("art-001", "drafts/art-001.md")], run_id="2026-09-25/daily-014")
    assert payload["review_surface"] == "markdown_dsh"
    assert "markdown_codex" not in json.dumps(payload, ensure_ascii=False)
    # 历史证据（旧值）仍然可校验
    payload["review_surface"] = "markdown_codex"
    assert validate_markdown_review_evidence(
        payload, tmp_path, [_article("art-001", "drafts/art-001.md")]) == []


def _write_markdown(root: Path, relative: str, text: str = "# 标题\n\n正文中的事实。\n") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_review_surface_defaults_to_markdown_and_accepts_explicit_legacy_html():
    assert DEFAULT_REVIEW_SURFACE == "markdown_dsh"
    assert resolve_review_surface(None) == "markdown_dsh"
    assert resolve_review_surface("html_delivery") == "html_delivery"
    assert validate_batch_review_surface({}, require_explicit=False) == []
    assert validate_batch_review_surface({}, require_explicit=True) == [
        "review_surface_missing"
    ]


def test_review_surface_rejects_unknown_values_and_html_preview_mixing():
    assert validate_batch_review_surface({"review_surface": "browser"}) == [
        "review_surface_invalid:browser"
    ]
    errors = validate_batch_review_surface({
        "review_surface": "markdown_dsh",
        "preview_mode": "local_codex",
    })
    assert "preview_mode_forbidden_for_markdown_surface" in errors


def test_markdown_review_evidence_binds_current_bytes_and_cjk_count(tmp_path: Path):
    # 2026-09-23 controller ruling：字数硬下限 900→1500（1200 → 1500 CJK）。
    first = _write_markdown(tmp_path, "drafts/art-001.md", "# 第一篇\n\n" + "黄金" * 750 + "\n")
    second = _write_markdown(tmp_path, "drafts/art-002.md", "# 第二篇\n\n" + "命案" * 750 + "\n")
    articles = [_article("art-001", "drafts/art-001.md"), _article("art-002", "drafts/art-002.md")]

    payload = build_markdown_review_evidence(
        tmp_path, articles, run_id="2026-08-26/daily-002"
    )

    assert payload["schema_version"] == "markdown-review-evidence-v1"
    assert payload["review_surface"] == "markdown_dsh"
    assert payload["articles"]["art-001"]["markdown_path"] == "drafts/art-001.md"
    assert payload["articles"]["art-001"]["size"] == first.stat().st_size
    assert payload["articles"]["art-001"]["markdown_sha256"] == hashlib.sha256(
        first.read_bytes()
    ).hexdigest()
    assert payload["articles"]["art-002"]["size"] == second.stat().st_size
    assert validate_markdown_review_evidence(payload, tmp_path, articles) == []


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda p: p["articles"].pop("art-002"), "markdown_evidence_article_missing:art-002"),
        (lambda p: p["articles"].update({"art-003": p["articles"]["art-001"]}), "markdown_evidence_article_extra:art-003"),
        (lambda p: p["articles"]["art-001"].update({"markdown_path": "../outside.md"}), "markdown_evidence_path_unsafe:art-001"),
        (lambda p: p["articles"]["art-001"].update({"markdown_sha256": "0" * 64}), "markdown_evidence_hash_mismatch:art-001"),
        (lambda p: p["articles"]["art-001"].update({"size": 1}), "markdown_evidence_size_mismatch:art-001"),
        (lambda p: p["articles"]["art-001"].update({"cjk_chars": 1}), "markdown_evidence_cjk_count_mismatch:art-001"),
    ],
)
def test_markdown_review_evidence_fails_closed_for_drift_and_shape(
    tmp_path: Path, mutation, expected: str
):
    _write_markdown(tmp_path, "drafts/art-001.md")
    _write_markdown(tmp_path, "drafts/art-002.md")
    articles = [_article("art-001", "drafts/art-001.md"), _article("art-002", "drafts/art-002.md")]
    payload = build_markdown_review_evidence(tmp_path, articles)
    mutation(payload)

    errors = validate_markdown_review_evidence(payload, tmp_path, articles)

    assert expected in errors


def test_markdown_review_evidence_rejects_cjk_count_outside_flexible_band(tmp_path: Path):
    _write_markdown(tmp_path, "drafts/art-001.md", "# 标题\n\n短文。\n")
    articles = [_article("art-001", "drafts/art-001.md")]
    payload = build_markdown_review_evidence(tmp_path, articles)

    errors = validate_markdown_review_evidence(payload, tmp_path, articles)

    assert any(error.startswith("markdown_evidence_cjk_count_out_of_range:art-001:") for error in errors)


def test_markdown_review_evidence_rejects_one_draft_bound_to_two_articles(tmp_path: Path):
    _write_markdown(tmp_path, "drafts/art-001.md", "# 标题\n\n" + "事实" * 600 + "\n")
    articles = [
        _article("art-001", "drafts/art-001.md"),
        _article("art-002", "drafts/art-001.md"),
    ]
    payload = build_markdown_review_evidence(tmp_path, articles)

    errors = validate_markdown_review_evidence(payload, tmp_path, articles)

    assert "markdown_evidence_path_duplicate:art-002:art-001" in errors


def test_markdown_review_audit_cli_writes_only_json_evidence(tmp_path: Path):
    from scripts.markdown_review_audit import main

    # 2026-09-23 controller ruling：字数硬下限 900→1500，夹具同步抬到 1500 CJK。
    _write_markdown(tmp_path, "drafts/art-001.md", "# 标题\n\n" + "事实" * 750 + "\n")
    _write_markdown(tmp_path, "drafts/art-002.md", "# 标题\n\n" + "事实" * 750 + "\n")
    batch = {
        "run_id": "2026-08-26/daily-002",
        "review_surface": "markdown_dsh",
        "articles": [
            _article("art-001", "drafts/art-001.md"),
            _article("art-002", "drafts/art-002.md"),
        ],
    }
    (tmp_path / "batch.json").write_text(json.dumps(batch), encoding="utf-8")

    assert main(["--run-dir", str(tmp_path)]) == 0
    evidence = tmp_path / "review" / "markdown-review-evidence.json"
    assert evidence.is_file()
    assert not list(tmp_path.rglob("*.html"))
    assert json.loads(evidence.read_text(encoding="utf-8"))["review_surface"] == "markdown_dsh"
