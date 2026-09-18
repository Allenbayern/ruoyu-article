from __future__ import annotations

import json
from pathlib import Path

import pytest

from article_group import codex_review


def test_parse_l2_output_uses_last_structured_json_line():
    output = "progress\n{" + '"noise": true' + "}\n" + json.dumps(
        {
            "decision": "needs_changes",
            "findings": [],
            "scope_reviewed": [],
            "non_findings": [],
            "coverage_gaps": [],
        }
    )

    result = codex_review._parse_l2_output(output)

    assert result is not None
    assert result["decision"] == "needs_changes"


def test_parse_l2_output_rejects_unstructured_output():
    assert codex_review._parse_l2_output("review text without contract") is None


def test_run_review_fails_closed_when_codex_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run_root = tmp_path / "run"
    run_root.mkdir()
    output = run_root / "review.json"
    monkeypatch.setattr(codex_review.shutil, "which", lambda _: None)

    with pytest.raises(SystemExit, match="codex executable not found"):
        codex_review.run_review(
            codex_review.build_parser().parse_args(
                [
                    "--mode",
                    "normal",
                    "--run-root",
                    str(run_root),
                    "--output",
                    str(output),
                    "--request",
                    "review the change",
                ]
            )
        )


def test_l2_record_keeps_publication_unauthorized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run_root = tmp_path / "run"
    run_root.mkdir()
    output = run_root / "review.json"

    class Completed:
        returncode = 0
        stdout = json.dumps(
            {
                "decision": "approve",
                "scope_reviewed": ["artifact"],
                "findings": [],
                "non_findings": ["tests passed"],
                "coverage_gaps": [],
            }
        )
        stderr = ""

    monkeypatch.setattr(codex_review.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(codex_review.subprocess, "run", lambda *args, **kwargs: Completed())

    exit_code = codex_review.run_review(
        codex_review.build_parser().parse_args(
            [
                "--mode",
                "l2",
                "--run-root",
                str(run_root),
                "--output",
                str(output),
                "--request",
                "review the change",
            ]
        )
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert record["decision"] == "approve"
    assert record["structured_result"] is True
    assert record["publication_authorization"] == "not_authorized"


def test_normal_review_record_is_explicitly_not_an_article_independent_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    run_root = tmp_path / "run"
    run_root.mkdir()
    output = run_root / "review.json"

    class Completed:
        returncode = 0
        stdout = "normal review completed"
        stderr = ""

    monkeypatch.setattr(codex_review.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(codex_review.subprocess, "run", lambda *args, **kwargs: Completed())

    exit_code = codex_review.run_review(
        codex_review.build_parser().parse_args(
            [
                "--mode",
                "normal",
                "--run-root",
                str(run_root),
                "--output",
                str(output),
                "--request",
                "review the change",
            ]
        )
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert record["decision"] == "review_completed"
    assert record["status"] == "PASS"
    assert record["review_kind"] == "repository_code_review"
    assert record["independent_review_eligible"] is False


def test_timeout_record_stays_unverified_and_keeps_article_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run_root = tmp_path / "run"
    run_root.mkdir()
    output = run_root / "review.json"

    def boom(*args, **kwargs):
        raise __import__("subprocess").TimeoutExpired(cmd=args[0] if args else "codex", timeout=kwargs.get("timeout", 1))

    monkeypatch.setattr(codex_review.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(codex_review.subprocess, "run", boom)

    exit_code = codex_review.run_review(
        codex_review.build_parser().parse_args(
            [
                "--mode",
                "l2",
                "--run-root",
                str(run_root),
                "--output",
                str(output),
                "--request",
                "review one article",
                "--timeout-seconds",
                "1",
                "--article-task-id",
                "at-art-001",
                "--article-id",
                "art-001",
                "--draft-path",
                "articles/art-001.md",
                "--draft-sha256",
                "a" * 64,
                "--attempt",
                "1",
                "--l2-required",
                "--l2-risk-basis",
                "人物动机需要独立核对",
            ]
        )
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert record["status"] == "UNVERIFIED"
    assert record["decision"] == "timeout"
    assert record["article_task_id"] == "at-art-001"
    assert record["next_step"] == "resume_single_article"
    assert record["publication_authorization"] == "not_authorized"
    assert "review_timeout" in record["coverage_gaps"]


def test_strict_review_sidecar_writes_current_artifact_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run_root = tmp_path / "run"
    (run_root / "articles").mkdir(parents=True)
    (run_root / "review").mkdir()
    (run_root / "articles" / "art-001.md").write_text("正文", encoding="utf-8")
    (run_root / "review" / "body.md").write_text("正文", encoding="utf-8")
    (run_root / "review" / "title-pack.json").write_text("{}", encoding="utf-8")
    (run_root / "batch.json").write_text(
        json.dumps(
            {
                "production_contract": "article-first-v1",
                "brief_contract": "writing-brief-v2",
                "title_contract": "title-pack-v1",
                "legacy_compatibility": False,
            }
        ),
        encoding="utf-8",
    )
    output = run_root / "review.json"

    class Completed:
        returncode = 0
        stdout = json.dumps(
            {
                "decision": "approve",
                "scope_reviewed": ["artifact"],
                "findings": [],
                "non_findings": [],
                "coverage_gaps": [],
            }
        )
        stderr = ""

    monkeypatch.setattr(codex_review.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(codex_review.subprocess, "run", lambda *args, **kwargs: Completed())

    exit_code = codex_review.run_review(
        codex_review.build_parser().parse_args(
            [
                "--mode",
                "l2",
                "--run-root",
                str(run_root),
                "--output",
                str(output),
                "--request",
                "review one article",
                "--article-id",
                "art-001",
                "--artifact-path",
                "articles/art-001.md",
                "--body-path",
                "review/body.md",
                "--title-pack-path",
                "review/title-pack.json",
            ]
        )
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert record["artifact_path"] == "articles/art-001.md"
    assert len(record["artifact_sha256"]) == 64
    assert len(record["body_sha256"]) == 64
    assert len(record["title_pack_sha256"]) == 64
    assert record["created_from_run"] == "run"


def test_l2_review_json_records_an_externally_produced_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The L2 gate must stay usable when no Codex CLI is installed."""

    run_root = tmp_path / "run"
    run_root.mkdir()
    output = run_root / "review.json"
    external = run_root / "dsh-review.json"
    external.write_text(
        json.dumps(
            {
                "decision": "needs_changes",
                "scope_reviewed": ["artifact"],
                "findings": [
                    {
                        "severity": "major",
                        "target": "正文第 3 段",
                        "evidence": "该句在材料包里找不到来源",
                        "counterexample_or_failure_mode": "改稿后仍可能残留同类断言",
                        "required_fix": "删除或补来源",
                        "recheck": "重跑账本预检并逐句比对",
                    }
                ],
                "non_findings": [],
                "coverage_gaps": ["no runtime execution"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def _no_subprocess(*args, **kwargs):
        raise AssertionError("--review-json must not spawn the Codex CLI")

    monkeypatch.setattr(codex_review.shutil, "which", lambda _: None)
    monkeypatch.setattr(codex_review.subprocess, "run", _no_subprocess)

    exit_code = codex_review.run_review(
        codex_review.build_parser().parse_args(
            [
                "--mode",
                "l2",
                "--run-root",
                str(run_root),
                "--output",
                str(output),
                "--request",
                "review one article",
                "--review-json",
                str(external),
            ]
        )
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    # Parity with the native path: a successfully produced review exits 0 even
    # when the decision is not an approval; the decision lives in the JSON.
    assert exit_code == 0
    assert record["decision"] == "needs_changes"
    assert record["status"] == "FAIL"
    assert record["structured_result"] is True
    assert record["review_source"] == "external_review_json"
    assert record["publication_authorization"] == "not_authorized"
    assert record["coverage_gaps"] == ["no runtime execution"]
    assert output.with_suffix(".log").read_text(encoding="utf-8").strip().startswith("{")


def test_l2_review_json_fails_closed_on_an_invalid_document(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run_root = tmp_path / "run"
    run_root.mkdir()
    output = run_root / "review.json"
    external = run_root / "not-a-review.json"
    external.write_text(json.dumps({"summary": "looks fine"}), encoding="utf-8")
    monkeypatch.setattr(codex_review.shutil, "which", lambda _: None)

    exit_code = codex_review.run_review(
        codex_review.build_parser().parse_args(
            [
                "--mode",
                "l2",
                "--run-root",
                str(run_root),
                "--output",
                str(output),
                "--request",
                "review one article",
                "--review-json",
                str(external),
            ]
        )
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert record["decision"] == "evidence_insufficient"
    assert record["error"] == "l2_structured_result_missing"
    assert record["coverage_gaps"] == ["l2_structured_result_missing"]


def test_l2_record_marks_diff_only_scope_with_base_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # 增量复核协议（2026-09-16）：--base-review 指向上一轮归档记录，
    # canonical 记录应带 scope_mode=diff_only 与基线哈希。
    run_root = tmp_path / "run"
    run_root.mkdir()
    output = run_root / "review.json"
    base = run_root / "codex-l2-review-r1-needs-changes.json"
    base.write_text('{"decision": "needs_changes"}', encoding="utf-8")

    class Completed:
        returncode = 0
        stdout = json.dumps(
            {
                "decision": "approve",
                "scope_reviewed": ["artifact"],
                "findings": [],
                "non_findings": [],
                "coverage_gaps": [],
            }
        )
        stderr = ""

    monkeypatch.setattr(codex_review.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(codex_review.subprocess, "run", lambda *args, **kwargs: Completed())

    exit_code = codex_review.run_review(
        codex_review.build_parser().parse_args(
            [
                "--mode",
                "l2",
                "--run-root",
                str(run_root),
                "--output",
                str(output),
                "--request",
                "verify the two fixes only",
                "--base-review",
                str(base),
            ]
        )
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert record["scope_mode"] == "diff_only"
    assert record["base_review"] == str(base)
    assert len(record["base_review_sha256"]) == 64


def test_l2_record_marks_missing_base_review():
    # 基线路径不存在也要如实留痕（scope_mode 仍声明 diff_only）。
    args = codex_review.build_parser().parse_args(
        [
            "--mode",
            "l2",
            "--run-root",
            "/tmp/nonexistent-run",
            "--output",
            "/tmp/nonexistent-review.json",
            "--request",
            "r",
            "--base-review",
            "/tmp/no-such-base.json",
        ]
    )
    record = codex_review._base_record(args, "l2", ["review-json", "/tmp/x.json"])
    assert record["scope_mode"] == "diff_only"
    assert record["base_review_missing"] is True


# --- canonical independent-review 输出（2026-09-18，daily-009 复盘）----------


def _canonical_run_root(tmp_path: Path) -> Path:
    """一个带完整文章链与已冻结标题包的最小 run。"""

    from article_group.title_freeze import freeze

    run_root = tmp_path / "runs" / "2026-09-18" / "daily-900"
    (run_root / "delivery" / "art-001").mkdir(parents=True)
    (run_root / "drafts" / "art-001").mkdir(parents=True)
    (run_root / "review" / "art-001").mkdir(parents=True)
    (run_root / "delivery" / "art-001" / "delivery.md").write_text("# 标题\n\n正文\n", encoding="utf-8")
    (run_root / "drafts" / "art-001" / "body_draft.md").write_text("正文\n", encoding="utf-8")
    (run_root / "review" / "art-001" / "title-pack.json").write_text(
        '{"directions":[{"title":"标题"}]}', encoding="utf-8"
    )
    (run_root / "batch.json").write_text(
        json.dumps(
            {
                "run_id": "2026-09-18/daily-900",
                "production_contract": "article-first-v1",
                "brief_contract": "writing-brief-v2",
                "title_contract": "title-pack-v1",
                "legacy_compatibility": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    freeze(run_root, "art-001")
    return run_root


def _canonical_argv(run_root: Path, output: Path, external: Path, *extra: str) -> list[str]:
    return [
        "--mode", "l2",
        "--run-root", str(run_root),
        "--output", str(output),
        "--request", "2026-09-18 daily-900 art-001 的 L2 对抗复核",
        "--risk", "L2",
        "--article-id", "art-001",
        "--artifact-path", "delivery/art-001/delivery.md",
        "--body-path", "drafts/art-001/body_draft.md",
        "--title-pack-path", "review/art-001/title-pack.json",
        "--review-json", str(external),
        *extra,
    ]


def test_canonical_output_name_writes_the_record_the_gate_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """输出名 = independent-review.json 时直接写 canonical 记录。

    daily-009 的 approve 之所以静默消失，是因为契约记录（status=PASS）和门禁读的
    canonical 记录（status=complete）之间要靠人手抄；这里一次写对。
    """

    from article_group.independent_review import evaluate_independent_review

    run_root = _canonical_run_root(tmp_path)
    output = run_root / "review" / "art-001" / "independent-review.json"
    external = run_root / "review" / "art-001" / "l2-input.json"
    external.write_text(
        json.dumps(
            {
                "decision": "approve",
                "scope_reviewed": ["artifact"],
                "findings": [],
                "non_findings": ["来源逐字核对通过"],
                "coverage_gaps": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(codex_review.shutil, "which", lambda _: None)

    exit_code = codex_review.run_review(
        codex_review.build_parser().parse_args(_canonical_argv(run_root, output, external))
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert record["schema_version"] == "article-independent-review-v1"
    assert record["status"] == "complete"
    assert record["contract_status"] == "PASS"
    assert record["decision"] == "approve"
    assert record["next_step"] == "stop"
    assert record["max_attempts"] == 3
    assert record["run_id"] == "2026-09-18/daily-900"
    assert record["draft_path"] == "drafts/art-001/body_draft.md"
    assert record["title_freeze_status"] == "frozen_ok"
    assert record["review_evidence_path"] == "review/art-001/l2-input.json"
    assert record["canonical_validation_errors"] == []
    assert record["publication_authorization"] == "not_authorized"

    result = evaluate_independent_review(
        record,
        run_root=run_root,
        expected_artifact_path="delivery/art-001/delivery.md",
        expected_body_path="drafts/art-001/body_draft.md",
        expected_title_pack_path="review/art-001/title-pack.json",
        expected_run_id="2026-09-18/daily-900",
        strict=True,
    )
    assert result["errors"] == []
    assert result["pass"] is True


def test_canonical_flag_keeps_a_rejected_review_complete_but_not_passing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from article_group.independent_review import evaluate_independent_review

    run_root = _canonical_run_root(tmp_path)
    output = run_root / "review" / "art-001" / "l2-contract.json"
    external = run_root / "review" / "art-001" / "l2-input.json"
    external.write_text(
        json.dumps(
            {
                "decision": "needs_changes",
                "scope_reviewed": ["artifact"],
                "findings": [
                    {
                        "severity": "major",
                        "target": "正文第 3 段",
                        "evidence": "无源断言",
                        "counterexample_or_failure_mode": "同类断言可能残留",
                        "required_fix": "删除或补来源",
                        "recheck": "重跑账本预检",
                    }
                ],
                "non_findings": [],
                "coverage_gaps": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(codex_review.shutil, "which", lambda _: None)

    exit_code = codex_review.run_review(
        codex_review.build_parser().parse_args(
            _canonical_argv(run_root, output, external, "--canonical-independent-review")
        )
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert record["status"] == "complete"  # 复核跑完了
    assert record["contract_status"] == "FAIL"
    assert record["next_step"] == "needs_changes"
    assert evaluate_independent_review(record)["pass"] is False


def test_contract_named_output_keeps_the_contract_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    run_root = _canonical_run_root(tmp_path)
    output = run_root / "review" / "art-001" / "codex-l2-review.json"
    external = run_root / "review" / "art-001" / "l2-input.json"
    external.write_text(
        json.dumps(
            {
                "decision": "approve",
                "scope_reviewed": ["artifact"],
                "findings": [],
                "non_findings": [],
                "coverage_gaps": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(codex_review.shutil, "which", lambda _: None)

    codex_review.run_review(
        codex_review.build_parser().parse_args(_canonical_argv(run_root, output, external))
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["schema_version"] == "codex-review-contract-1.0"
    assert record["status"] == "PASS"
    assert "contract_status" not in record


def test_explicit_canonical_flag_requires_the_article_binding(tmp_path: Path):
    """显式要求 canonical 却缺文章链 = operator 错误，直接拒绝（不写半份记录）。"""

    run_root = tmp_path / "run"
    run_root.mkdir()
    output = run_root / "review" / "art-001" / "independent-review.json"

    with pytest.raises(SystemExit, match="--article-id"):
        codex_review.run_review(
            codex_review.build_parser().parse_args(
                [
                    "--mode", "l2",
                    "--run-root", str(run_root),
                    "--output", str(output),
                    "--request", "r",
                    "--canonical-independent-review",
                    "--review-json", str(run_root / "l2-input.json"),
                ]
            )
        )


def test_contract_record_reports_the_state_of_the_gate_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """结论只落在契约记录里时，"门禁那份还是占位符"必须可见。"""

    run_root = _canonical_run_root(tmp_path)
    output = run_root / "review" / "art-001" / "codex-l2-review.json"
    external = run_root / "review" / "art-001" / "l2-input.json"
    external.write_text(
        json.dumps(
            {
                "decision": "approve",
                "scope_reviewed": ["artifact"],
                "findings": [],
                "non_findings": [],
                "coverage_gaps": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(codex_review.shutil, "which", lambda _: None)

    codex_review.run_review(
        codex_review.build_parser().parse_args(_canonical_argv(run_root, output, external))
    )
    assert json.loads(output.read_text(encoding="utf-8"))["canonical_record_state"] == "missing"

    (run_root / "review" / "art-001" / "independent-review.json").write_text(
        json.dumps(
            {
                "schema_version": "article-independent-review-v1",
                "article_id": "art-001",
                "status": "PENDING",
                "decision": "human_review_required",
            }
        ),
        encoding="utf-8",
    )
    codex_review.run_review(
        codex_review.build_parser().parse_args(_canonical_argv(run_root, output, external))
    )
    assert json.loads(output.read_text(encoding="utf-8"))["canonical_record_state"] == "placeholder"


def test_canonical_name_without_the_article_chain_records_the_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    run_root = _canonical_run_root(tmp_path)
    output = run_root / "review" / "art-001" / "independent-review.json"
    external = run_root / "review" / "art-001" / "l2-input.json"
    external.write_text(
        json.dumps(
            {
                "decision": "approve",
                "scope_reviewed": ["artifact"],
                "findings": [],
                "non_findings": [],
                "coverage_gaps": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(codex_review.shutil, "which", lambda _: None)

    codex_review.run_review(
        codex_review.build_parser().parse_args(
            [
                "--mode", "l2",
                "--run-root", str(run_root),
                "--output", str(output),
                "--request", "r",
                "--review-json", str(external),
            ]
        )
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["schema_version"] == "codex-review-contract-1.0"  # 不假装写成 canonical
    assert record["canonical_record_incomplete"] == [
        "--article-id",
        "--artifact-path",
        "--body-path",
        "--title-pack-path",
    ]
    assert "canonical" in capsys.readouterr().err


# --- 契约拒收与 severity→decision 映射（2026-09-18，B5′）---------------------


def _review_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


VALID_FINDING = {
    "severity": "minor",
    "target": "delivery.md line 19",
    "evidence": "账本条目少了「十四阿哥送的寿礼」这一环",
    "counterexample_or_failure_mode": "读者会把来源里的细节当成正文自述",
    "required_fix": "扩账本条目或改写该句",
    "recheck": "重跑账本预检确认 warning 归零",
}


def test_review_json_with_a_self_invented_finding_shape_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """daily-009 的复核员自造了 id/category/location…，此前无人拦。"""

    run_root = tmp_path / "run"
    run_root.mkdir()
    output = run_root / "review.json"
    external = _review_json(
        run_root / "l2-input.json",
        {
            "decision": "approve",
            "scope_reviewed": ["artifact"],
            "findings": [
                {
                    "id": "Y1",
                    "severity": "minor",
                    "category": "ledger_coverage",
                    "location": "delivery.md line 19",
                    "summary": "账本明细未收全来源要素",
                }
            ],
            "non_findings": [],
            "coverage_gaps": [],
        },
    )
    monkeypatch.setattr(codex_review.shutil, "which", lambda _: None)

    exit_code = codex_review.run_review(
        codex_review.build_parser().parse_args(
            [
                "--mode", "l2",
                "--run-root", str(run_root),
                "--output", str(output),
                "--request", "r",
                "--review-json", str(external),
            ]
        )
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert record["decision"] == "evidence_insufficient"
    assert record["status"] == "UNVERIFIED"
    assert record["error"] == "l2_review_contract_invalid"
    assert record["coverage_gaps"] == ["l2_review_contract_invalid"]
    assert any("findings/0" in error for error in record["contract_errors"])
    # 复核原文仍然留档（拒收不等于丢证据），并给人一句能读的拒绝理由
    assert "Y1" in output.with_suffix(".log").read_text(encoding="utf-8")
    assert "不合契约" in capsys.readouterr().err


def test_review_json_missing_a_contract_key_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run_root = tmp_path / "run"
    run_root.mkdir()
    output = run_root / "review.json"
    external = _review_json(
        run_root / "l2-input.json",
        {
            "decision": "approve",
            "findings": [],
            "non_findings": [],
            "coverage_gaps": [],
        },
    )
    monkeypatch.setattr(codex_review.shutil, "which", lambda _: None)

    codex_review.run_review(
        codex_review.build_parser().parse_args(
            [
                "--mode", "l2",
                "--run-root", str(run_root),
                "--output", str(output),
                "--request", "r",
                "--review-json", str(external),
            ]
        )
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["status"] == "UNVERIFIED"
    assert any("scope_reviewed" in error for error in record["contract_errors"])


def test_blocking_finding_cannot_be_recorded_as_an_approve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run_root = tmp_path / "run"
    run_root.mkdir()
    output = run_root / "review.json"
    external = _review_json(
        run_root / "l2-input.json",
        {
            "decision": "approve",
            "scope_reviewed": ["artifact"],
            "findings": [{**VALID_FINDING, "severity": "major"}],
            "non_findings": [],
            "coverage_gaps": [],
        },
    )
    monkeypatch.setattr(codex_review.shutil, "which", lambda _: None)

    codex_review.run_review(
        codex_review.build_parser().parse_args(
            [
                "--mode", "l2",
                "--run-root", str(run_root),
                "--output", str(output),
                "--request", "r",
                "--review-json", str(external),
            ]
        )
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["decision"] == "needs_changes"
    assert record["decision_adjusted_from"] == "approve"
    assert record["severity_mapping"]["blocking_severities"] == ["major"]
    assert record["status"] == "FAIL"
    assert "severity_mapping:blocking_finding_cannot_approve" in record["coverage_gaps"]


def test_minor_findings_still_allow_an_approve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """daily-009 的 approve 只带 minor：映射规则不能把这种正常批准也降级。"""

    run_root = tmp_path / "run"
    run_root.mkdir()
    output = run_root / "review.json"
    external = _review_json(
        run_root / "l2-input.json",
        {
            "decision": "approve",
            "scope_reviewed": ["artifact"],
            "findings": [VALID_FINDING],
            "non_findings": ["来源逐字核对通过"],
            "coverage_gaps": [],
        },
    )
    monkeypatch.setattr(codex_review.shutil, "which", lambda _: None)

    codex_review.run_review(
        codex_review.build_parser().parse_args(
            [
                "--mode", "l2",
                "--run-root", str(run_root),
                "--output", str(output),
                "--request", "r",
                "--review-json", str(external),
            ]
        )
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["decision"] == "approve"
    assert record["status"] == "PASS"
    assert "severity_mapping" not in record


def test_rejected_contract_never_becomes_a_canonical_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from article_group.independent_review import evaluate_independent_review

    run_root = _canonical_run_root(tmp_path)
    output = run_root / "review" / "art-001" / "independent-review.json"
    external = _review_json(
        run_root / "review" / "art-001" / "l2-input.json",
        {
            "decision": "approve",
            "scope_reviewed": ["artifact"],
            "findings": [{"id": "Y1", "severity": "minor"}],
            "non_findings": [],
            "coverage_gaps": [],
        },
    )
    monkeypatch.setattr(codex_review.shutil, "which", lambda _: None)

    codex_review.run_review(
        codex_review.build_parser().parse_args(_canonical_argv(run_root, output, external))
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["schema_version"] == "article-independent-review-v1"
    assert record["status"] == "UNVERIFIED"
    assert record["error"] == "l2_review_contract_invalid"
    assert evaluate_independent_review(record)["pass"] is False


def test_native_l2_output_is_validated_against_the_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run_root = tmp_path / "run"
    run_root.mkdir()
    output = run_root / "review.json"

    class Completed:
        returncode = 0
        stdout = json.dumps(
            {
                "decision": "approve",
                "scope_reviewed": ["artifact"],
                "findings": [{"severity": "very-high", "target": "x"}],
                "non_findings": [],
                "coverage_gaps": [],
            }
        )
        stderr = ""

    monkeypatch.setattr(codex_review.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(codex_review.subprocess, "run", lambda *args, **kwargs: Completed())

    exit_code = codex_review.run_review(
        codex_review.build_parser().parse_args(
            [
                "--mode", "l2",
                "--run-root", str(run_root),
                "--output", str(output),
                "--request", "r",
            ]
        )
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert record["status"] == "UNVERIFIED"
    assert record["error"] == "l2_review_contract_invalid"
