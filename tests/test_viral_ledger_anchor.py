"""新管线的账本口径：产物自带 integrity 为主，run 的账本只记**一条产物级锚点**。

为什么不是逐文件留底：package / cards / distill 三个写手都是 new-only
（`artifact_exists` 拒覆盖、`_write_new` 存在即拒），**没有旧字节可还原**——
`evidence_write` 的 before-image 那一半对它们没有意义。真正需要的是账本里有一条
记录，否则 `run_seal.verify` 会把整批新增文件算成"无账改动"。

为什么账本粒度是产物根而不是每个文件：一个 package 可能上百个文件；而且产物自带
逐文件 SHA-256（`integrity.json` / `manifest.json`），文件级可验证性由产物自己保证，
账本只回答"这批东西是谁、什么时候、以什么理由落进来的"。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from article_group import run_seal
from article_group.evidence_write import anchor_artifact, read_changelog


def _run_root(tmp_path: Path, name: str = "daily-980") -> Path:
    root = tmp_path / "runs" / "2026-09-17" / name
    root.mkdir(parents=True)
    return root


def test_find_run_root_matches_only_run_shaped_paths(tmp_path: Path):
    root = _run_root(tmp_path)
    nested = root / "viral-research" / "package"
    nested.mkdir(parents=True)
    assert run_seal.find_run_root(nested) == root
    assert run_seal.find_run_root(root) == root
    assert run_seal.find_run_root(tmp_path / "runs" / "2026-09-17") is None
    assert run_seal.find_run_root(tmp_path / "elsewhere") is None


def test_anchor_artifact_records_one_line_and_is_idempotent_without_before_image(tmp_path: Path):
    root = _run_root(tmp_path)
    artifact = root / "viral-research" / "package"
    artifact.mkdir(parents=True)
    (artifact / "integrity.json").write_text('{"a": 1}', encoding="utf-8")

    entry = anchor_artifact(artifact, reason="viral_research:package", digest="deadbeef", run_root=root)

    assert entry is not None
    assert entry["path"] == "viral-research/package"
    assert entry["reason"] == "viral_research:package"
    assert entry["after_sha256"] == "deadbeef"
    assert entry["snapshot_path"] == ""  # 不假装有 before-image
    assert entry["existed"] is False
    assert not (root / "review" / ".before").exists()
    assert len(read_changelog(root)) == 1


def test_anchor_artifact_skips_artifacts_outside_any_run(tmp_path: Path):
    outside = tmp_path / "scratch" / "package"
    outside.mkdir(parents=True)
    assert anchor_artifact(outside, reason="viral_research:package") is None
    assert not (tmp_path / "scratch" / "evidence-changelog.jsonl").exists()


def test_package_anchor_carries_integrity_hash(tmp_path: Path):
    from tests.test_viral_research_cards import _build_package

    root = _run_root(tmp_path, "daily-981")
    _build_package(tmp_path)  # 复用夹具建好 raw/clean/metadata 与 capture.json
    capture = tmp_path / "capture.json"
    # capture 与产物都必须落在 run 内（build_package 有 path_escape 校验）
    inside_capture = root / "capture.json"
    inside_capture.write_bytes(capture.read_bytes())
    for name in ("raw", "clean", "metadata"):
        (root / name).mkdir(exist_ok=True)
    capture_payload = __import__("json").loads(inside_capture.read_text(encoding="utf-8"))
    inside_capture.write_text(__import__("json").dumps(capture_payload), encoding="utf-8")

    from article_group.viral_research_package import build_package

    output = root / "viral-research" / "package"
    build_package(inside_capture, run_root=root, output_root=output)

    entries = read_changelog(root)
    assert [entry["reason"] for entry in entries] == ["viral_research:package"]
    assert entries[0]["path"] == "viral-research/package"
    assert entries[0]["after_sha256"] == hashlib.sha256(
        (output / "integrity.json").read_bytes()
    ).hexdigest()


def test_cards_anchor_is_written_once_per_artifact_root(tmp_path: Path):
    from tests.test_viral_research_cards import _sample
    from article_group.viral_research_cards import write_case_cards

    root = _run_root(tmp_path, "daily-982")
    output = root / "viral-research" / "cards"
    manifest = write_case_cards([_sample(root)], run_root=root, output_root=output)

    entries = read_changelog(root)
    assert [entry["reason"] for entry in entries] == ["viral_research:cards"]
    assert entries[0]["after_sha256"] == hashlib.sha256(
        (output / "manifest.json").read_bytes()
    ).hexdigest()
    assert manifest["card_count"] == 1
    assert len(entries) < manifest["card_count"] + 2  # 产物级：不是每个文件一条


def test_distill_report_is_anchored_when_it_lives_in_a_run(tmp_path: Path):
    from tests.test_viral_research_distill import _criteria, _prepare_and_write_cards

    prepare_path, cards_root, _ = _prepare_and_write_cards(tmp_path)
    package_root = cards_root.parent / "package"
    run_root = _run_root(tmp_path, "daily-983")
    output = run_root / "review.json"

    from article_group.viral_research_distill import finalize_distillation

    finalize_distillation(
        prepare_path, package_root=package_root, criteria=_criteria(),
        cards_root=cards_root, output_path=output,
    )

    entries = read_changelog(run_root)
    assert [entry["reason"] for entry in entries] == ["viral_research:distill"]
    assert entries[0]["after_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    # 报告写在 run 外时不该往任何 run 里记（判据看产物自身的位置）
    outside = tmp_path / "elsewhere.json"
    finalize_distillation(
        prepare_path, package_root=package_root, criteria=_criteria(),
        cards_root=cards_root, output_path=outside,
    )
    assert len(read_changelog(run_root)) == 1
    assert json.loads(outside.read_text(encoding="utf-8"))["promotion_status"] == "provisional_only"
