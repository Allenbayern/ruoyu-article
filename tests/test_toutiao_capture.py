"""Tests for Toutiao source-capture utility."""

from __future__ import annotations

from pathlib import Path

import pytest

from article_group.toutiao import ToutiaoExtractionError
from article_group.toutiao_capture import capture_toutiao_source
from article_group.prewrite import validate_claim_locators


def test_capture_returns_manifest_mapping_with_correct_fields(tmp_path: Path):
    """Capture returns manifest-compatible mapping with expected fields and digest."""
    # Mock fetch that returns a valid article
    def fake_fetch(url: str, *, timeout: float = 30.0) -> dict[str, str]:
        return {
            "source": "toutiao",
            "canonical_url": "https://m.toutiao.com/article/123226726166179/",
            "title": "测试标题",
            "body": "这是第一段真实正文，长度足够用于验证。\n\n这是第二段真实正文，不能被挑战页面替代。",
            "status": "success",
        }

    import article_group.toutiao_capture
    original_fetch = article_group.toutiao_capture.fetch_toutiao_article
    article_group.toutiao_capture.fetch_toutiao_article = fake_fetch

    try:
        result = capture_toutiao_source(
            url="https://www.toutiao.com/a123456/",
            run_root=tmp_path,
            source_id="S1",
            role="confirmed-primary",
            independence_group="example",
        )

        # Verify manifest-compatible fields
        assert result["source_id"] == "S1"
        assert result["relative_path"] == "sources/S1.txt"
        assert len(result["sha256"]) == 64  # hex digest length
        assert result["url"] == "https://m.toutiao.com/article/123226726166179/"
        assert result["role"] == "confirmed-primary"
        assert result["independence_group"] == "example"
        assert "captured_at" in result
        assert "+00:00" in result["captured_at"] or result["captured_at"].endswith("+00:00")

        # Verify snapshot file exists and content matches
        snapshot_path = tmp_path / "sources" / "S1.txt"
        assert snapshot_path.exists()
        assert snapshot_path.read_text(encoding="utf-8") == (
            "这是第一段真实正文，长度足够用于验证。\n\n"
            "这是第二段真实正文，不能被挑战页面替代。"
        )
        # Digest matches file content
        import hashlib
        assert result["sha256"] == hashlib.sha256(snapshot_path.read_bytes()).hexdigest()

    finally:
        article_group.toutiao_capture.fetch_toutiao_article = original_fetch


def test_capture_fails_when_snapshot_exists(tmp_path: Path):
    """No overwrite: raise ValueError if snapshot file already exists."""
    snapshot_path = tmp_path / "sources" / "S1.txt"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text("existing", encoding="utf-8")

    def fake_fetch(url: str, *, timeout: float = 30.0) -> dict[str, str]:
        return {
            "source": "toutiao",
            "canonical_url": "https://m.toutiao.com/article/123/",
            "title": "test",
            "body": "new body",
            "status": "success",
        }

    import article_group.toutiao_capture
    original_fetch = article_group.toutiao_capture.fetch_toutiao_article
    article_group.toutiao_capture.fetch_toutiao_article = fake_fetch

    try:
        with pytest.raises(ValueError, match="snapshot already exists"):
            capture_toutiao_source(
                url="https://www.toutiao.com/a123/",
                run_root=tmp_path,
                source_id="S1",
            )
    finally:
        article_group.toutiao_capture.fetch_toutiao_article = original_fetch


def test_capture_rejects_sources_symlink_without_writing(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "sources").symlink_to(outside, target_is_directory=True)

    def fake_fetch(url: str, *, timeout: float = 30.0) -> dict[str, str]:
        return {
            "source": "toutiao",
            "canonical_url": "https://m.toutiao.com/article/123/",
            "title": "test",
            "body": "new body",
            "status": "success",
        }

    import article_group.toutiao_capture
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(article_group.toutiao_capture, "fetch_toutiao_article", fake_fetch)
    try:
        with pytest.raises(ValueError, match="sources directory escapes run root"):
            capture_toutiao_source(
                url="https://www.toutiao.com/a123/", run_root=tmp_path, source_id="S1"
            )
        assert not (outside / "S1.txt").exists()
    finally:
        monkeypatch.undo()


def test_capture_no_write_when_extraction_errors(tmp_path: Path):
    """Extraction error propagates and no snapshot file is written."""
    def bad_fetch(url: str, *, timeout: float = 30.0) -> dict[str, str]:
        raise ToutiaoExtractionError("static_body_missing")

    import article_group.toutiao_capture
    original_fetch = article_group.toutiao_capture.fetch_toutiao_article
    article_group.toutiao_capture.fetch_toutiao_article = bad_fetch

    try:
        with pytest.raises(ToutiaoExtractionError, match="static_body_missing"):
            capture_toutiao_source(
                url="https://www.toutiao.com/bad/",
                run_root=tmp_path,
                source_id="S2",
            )

        # The failed fetch must not create either the snapshot or its parent directory.
        snapshot_path = tmp_path / "sources" / "S2.txt"
        assert not snapshot_path.exists()
        assert not snapshot_path.parent.exists()
    finally:
        article_group.toutiao_capture.fetch_toutiao_article = original_fetch


def test_capture_snapshot_text_sufficient_for_locator_validator(tmp_path: Path):
    """Ordinary source snapshot text is sufficient for existing locator validator."""
    def fake_fetch(url: str, *, timeout: float = 30.0) -> dict[str, str]:
        return {
            "source": "toutiao",
            "canonical_url": "https://m.toutiao.com/article/locator123/",
            "title": "定位器文本验证测试标题",
            "body": "这里有定位器文本：某句话需要被定位。\n\n其他正文内容。",
            "status": "success",
        }

    import article_group.toutiao_capture
    original_fetch = article_group.toutiao_capture.fetch_toutiao_article
    article_group.toutiao_capture.fetch_toutiao_article = fake_fetch

    try:
        result = capture_toutiao_source(
            url="https://www.toutiao.com/locator/",
            run_root=tmp_path,
            source_id="S_LOC",
            role="confirmed-primary",
            independence_group="locator-test",
        )

        # Verify the snapshot can be used by locator validator
        manifest = {"sources": [result]}
        claims = [{
            "claim_id": "C1",
            "source_id": "S_LOC",
            "locator": "某句话需要被定位",
        }]

        errors = validate_claim_locators(claims, manifest, tmp_path)
        assert errors == []

    finally:
        article_group.toutiao_capture.fetch_toutiao_article = original_fetch


def test_capture_unsafe_source_id_raises(tmp_path: Path):
    """Capture validates source_id for safe path usage."""
    for bad_id in ["", "/absolute", "../parent", "..", "./dot", "nested/S1", "S 1"]:
        with pytest.raises(ValueError, match="source_id must be a safe filename component"):
            capture_toutiao_source(
                url="https://www.toutiao.com/a123/",
                run_root=tmp_path,
                source_id=bad_id,
            )


def test_capture_uses_canonical_url_in_manifest(tmp_path: Path):
    """Manifest url field uses canonical mobile URL from fetch result."""
    def fake_fetch(url: str, *, timeout: float = 30.0) -> dict[str, str]:
        return {
            "source": "toutiao",
            "canonical_url": "https://m.toutiao.com/article/7667134749114925620/",
            "title": "标题",
            "body": "正文",
            "status": "success",
        }

    import article_group.toutiao_capture
    original_fetch = article_group.toutiao_capture.fetch_toutiao_article
    article_group.toutiao_capture.fetch_toutiao_article = fake_fetch

    try:
        result = capture_toutiao_source(
            url="https://www.toutiao.com/article/7667134749114925620/",
            run_root=tmp_path,
            source_id="S_CANON",
        )

        assert result["url"] == "https://m.toutiao.com/article/7667134749114925620/"
    finally:
        article_group.toutiao_capture.fetch_toutiao_article = original_fetch