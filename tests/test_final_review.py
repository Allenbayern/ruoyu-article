"""final_review（prepublication 总复核层）测试。

6 类用例：证据缺失 / 机械失败 / 发布不变量 / 重复指纹 / 存疑触发 / 全通过。
用 tmp_path 构造最小批次产物，不依赖 runs/ 存量。
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from article_group.final_review import (
    BLOCKED,
    PENDING,
    PUBLISHABLE,
    _validate_editorial_review_surface,
    evaluate_batch,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_valid_scoring_cards(batch: Path, html_paths: dict[str, Path]) -> None:
    scores = {
        "total_score": 87,
        "evidence_score": 20,
        "original_judgment_score": 18,
        "information_gain_score": 17,
        "structure_score": 13,
        "title_value_score": 9,
        "readability_score": 5,
        "compliance_score": 5,
    }
    for article_id, html_path in html_paths.items():
        card = {
            **scores,
            "html_sha256": hashlib.sha256(html_path.read_bytes()).hexdigest(),
            "title_promise": "回答读者最关心的电影问题",
            "first_screen_value": "开头交代核心事实和阅读收益",
            "reader_takeaway": "读者能带走一个清晰判断",
            "body_fulfillment": "正文完整兑现标题承诺",
        }
        _write_json(batch / "review" / "scoring" / f"{article_id}.json", card)


def _write_preview_evidence(
    batch: Path,
    html_paths: dict[str, Path],
    *,
    mode: str,
    http_status: int = 200,
) -> None:
    from article_group.preview_contract import build_route_manifest

    routes = {f"/{path.name}": path for path in html_paths.values()}
    manifest = build_route_manifest(routes)
    payload = {
        "schema_version": "preview-route-audit-v2",
        "preview_mode": mode,
        "canonical_http_required": mode == "canonical_http",
        "local_preview_status": "READY" if mode == "local_codex" else "NOT_APPLICABLE",
        "manifest": manifest,
        "http_audit_status": "PASS" if http_status == 200 else "FAIL",
    }
    if mode == "canonical_http":
        payload["http_checks"] = {
            route: {
                "url": f"http://192.168.100.168:8765{route}",
                "status": http_status,
                "body_size": entry["size"] if http_status == 200 else 0,
                "body_sha256": entry["body_sha256"] if http_status == 200 else "0" * 64,
                "errors": [] if http_status == 200 else ["preview_http_status_not_200"],
            }
            for route, entry in manifest.items()
        }
    filename = "preview-local-evidence.json" if mode == "local_codex" else "preview-http-evidence.json"
    _write_json(batch / "review" / filename, payload)


def _real_hook_declaration(run_dir: str, style_file: str) -> dict:
    repository_root = Path(__file__).resolve().parents[1]
    style_path = repository_root / "runs" / run_dir / "review" / style_file
    style = json.loads(style_path.read_text(encoding="utf-8"))
    return style["articles"][0]["hook_declaration"]


def _make_batch(root: Path, *, preflight_status: str = "PASS",
                auth: str = "not_authorized",
                style_error: int = 0, style_warning: bool = False,
                with_style: bool = True, with_prose: bool = True,
                with_editorial: bool = False, with_scoring: bool = True) -> Path:
    """构造一个最小可复核批次目录，返回 batch 目录。"""
    batch = root / "controlled-999"
    (batch / "review").mkdir(parents=True, exist_ok=True)
    _write_json(batch / "batch.json", {
        "run_id": "2026-08-16/controlled-999",
        "articles": [
            {
                "article_id": "art-001",
                "candidate_id": "cand-001",
                "work": "《测试电影》的票房奇迹",
                "reader_question": "为什么《测试电影》一夜爆红",
                "publication_authorization": auth,
            },
            {
                "article_id": "art-002",
                "work": "《另一部片》的口碑分化",
                "reader_question": "为什么《另一部片》口碑两极",
                "publication_authorization": auth,
            },
        ],
    })
    _write_json(batch / "preflight-report.json", {
        "status": preflight_status,
        "run_id": "2026-08-16/controlled-999",
    })
    if with_prose:
        _write_json(batch / "review" / "prose-pilot-report.json", {
            "advisory": True,
            "batches": [{"name": "controlled-999-v1",
                         "articles": [{"label": "art-001-v1#1", "advisory": True,
                                       "title": "测试文章标题", "chars": 1850}]}],
        })
    if with_editorial:
        # 合法的四阶段记录最小形态（协议 v1.0）
        _write_json(batch / "review" / "editorial-record.json", {
            "protocol_version": "1.0",
            "record_revision": 1,
            "run_id": "2026-08-16/controlled-999",
            "article_id": "art-001",
            "publication_authorization": "not_authorized",
            "card_refs": {},
            "stages": [],
            "stop_draft": None,
        })
    delivery_htmls = {}
    for article_id, title in (
        ("art-001", "测试文章标题"),
        ("art-002", "另一篇测试标题"),
    ):
        delivery_html = batch / "review" / f"ruoyu-{article_id}-2026-08-16.html"
        delivery_html.write_text(f"<h2>{title}</h2>", encoding="utf-8")
        delivery_htmls[article_id] = delivery_html
    if with_style:
        hits = [{"severity": "warning", "rule": "claim:age-inference",
                 "reason": "无源年龄推算"}] if style_warning else []
        for index, (article_id, title) in enumerate(
            (("art-001", "测试文章标题"), ("art-002", "另一篇测试标题")),
            start=1,
        ):
            delivery_html = delivery_htmls[article_id]
            _write_json(batch / "review" / f"style-gate-{article_id}.json", {
                "article_count": 1,
                "pass": style_error == 0 if article_id == "art-001" else True,
                "artifact_path": str(delivery_html.resolve()),
                "artifact_sha256": hashlib.sha256(delivery_html.read_bytes()).hexdigest(),
                "articles": [{
                    "index": index,
                    "title": title,
                    "char_count": 1800,
                    "error_count": style_error if article_id == "art-001" else 0,
                    "hits": hits if article_id == "art-001" else [],
                }],
            })
    if with_scoring:
        _write_valid_scoring_cards(batch, delivery_htmls)
    return batch


def _make_markdown_batch(root: Path) -> Path:
    from article_group.review_surface import build_markdown_review_evidence
    from article_group.style_gate import validate_markdown_file

    batch = root / "markdown-999"
    (batch / "review").mkdir(parents=True, exist_ok=True)
    articles = []
    markdown_paths: dict[str, Path] = {}
    for article_id, title, work in (
        ("art-001", "《新片》为什么要查命案？", "新片"),
        ("art-002", "《另一部片》居然把搭档写活了", "另一部片"),
    ):
        relative = f"drafts/{article_id}.md"
        path = batch / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\n"
            f"hook: {work} 命案\n"
            "---\n"
            f"# {title}\n\n"
            f"《{work}》于8月25日上映，一桩命案把两位搭档推到一起。\n\n"
            + ("故事把人物选择放进同一座城市，机关和线索不断改变判断。" * 90)
            + "\n\n你会先看命案，还是先看搭档？\n",
            encoding="utf-8",
        )
        markdown_paths[article_id] = path
        articles.append({
            "article_id": article_id,
            "work": f"《{work}》",
            "reader_question": "命案如何推动搭档关系",
            "markdown_path": relative,
            "html_delivery_state": "not_requested",
            "publication_authorization": "not_authorized",
        })

    payload = {
        "run_id": "2026-08-26/markdown-999",
        "review_surface": "markdown_codex",
        "articles": articles,
    }
    _write_json(batch / "batch.json", payload)
    _write_json(batch / "preflight-report.json", {
        "status": "PASS",
        "run_id": payload["run_id"],
    })
    evidence = build_markdown_review_evidence(batch, articles, run_id=payload["run_id"])
    _write_json(batch / "review" / "markdown-review-evidence.json", evidence)

    scores = {
        "total_score": 87,
        "evidence_score": 20,
        "original_judgment_score": 18,
        "information_gain_score": 17,
        "structure_score": 13,
        "title_value_score": 9,
        "readability_score": 5,
        "compliance_score": 5,
    }
    prose_articles = []
    for article in articles:
        article_id = article["article_id"]
        path = markdown_paths[article_id]
        style = validate_markdown_file(path)
        _write_json(batch / "review" / f"style-gate-markdown-{article_id}.json", style)
        title = style["articles"][0]["title"]
        cjk = style["articles"][0]["char_count"]
        _write_json(batch / "review" / "scoring" / f"{article_id}.json", {
            **scores,
            "markdown_path": article["markdown_path"],
            "markdown_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "title_promise": "回答读者最关心的故事问题",
            "first_screen_value": "开头交代核心事实和阅读收益",
            "reader_takeaway": "读者能带走一个清晰判断",
            "body_fulfillment": "正文完整兑现标题承诺",
        })
        prose_articles.append({"title": title, "chars": cjk})
    _write_json(batch / "review" / "prose-pilot-report.json", {
        "advisory": True,
        "batches": [{"name": "markdown-999", "articles": prose_articles}],
    })
    return batch


def test_evidence_missing_batch_json(tmp_path: Path) -> None:
    batch = tmp_path / "controlled-888"
    batch.mkdir(parents=True)
    report = evaluate_batch(batch)
    assert report["verdict"] == BLOCKED
    assert report["reason"] == "evidence_missing:batch.json"


def test_evidence_missing_preflight(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path)
    (batch / "preflight-report.json").unlink()
    report = evaluate_batch(batch)
    assert report["verdict"] == BLOCKED
    assert report["reason"] == "evidence_missing:preflight-report.json"


def test_mechanical_gate_preflight_fail(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path, preflight_status="FAIL")
    report = evaluate_batch(batch)
    assert report["verdict"] == BLOCKED
    assert report["reason"] == "gate:preflight"


def test_mechanical_gate_style_error(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path, style_error=2)
    report = evaluate_batch(batch)
    assert report["verdict"] == BLOCKED
    assert report["reason"] == "gate:style_gate"


def test_publication_authorization_violation(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path, auth="authorized")
    report = evaluate_batch(batch)
    assert report["verdict"] == BLOCKED
    assert report["reason"] == "gate:publication_authorization"


def test_missing_scoring_card_blocks(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path)
    (batch / "review" / "scoring" / "art-002.json").unlink()

    report = evaluate_batch(batch)

    assert report["verdict"] == BLOCKED
    assert report["reason"] == "evidence_missing:scoring-card"
    assert report["article"] == "art-002"


def test_low_scoring_card_blocks(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path)
    card_path = batch / "review" / "scoring" / "art-001.json"
    card = json.loads(card_path.read_text(encoding="utf-8"))
    card["total_score"] = 74
    card_path.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")

    report = evaluate_batch(batch)

    assert report["verdict"] == BLOCKED
    assert report["reason"] == "gate:scoring_card"
    assert report["article"] == "art-001"


def test_scoring_card_total_mismatch_blocks(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path)
    card_path = batch / "review" / "scoring" / "art-001.json"
    card = json.loads(card_path.read_text(encoding="utf-8"))
    card["total_score"] = 88
    card_path.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")

    report = evaluate_batch(batch)

    assert report["verdict"] == BLOCKED
    assert report["reason"] == "gate:scoring_card"
    assert "score_sum_mismatch" in report["errors"]


def test_scoring_card_hash_drift_blocks(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path)
    html_path = batch / "review" / "ruoyu-art-001-2026-08-16.html"
    html_path.write_text("<h2>测试文章标题</h2><p>发生了漂移</p>", encoding="utf-8")

    report = evaluate_batch(batch)

    assert report["verdict"] == BLOCKED
    assert report["reason"] == "gate:scoring_card"
    assert report["article"] == "art-001"


def test_scoring_card_cannot_bind_another_article_html(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path)
    other_html = batch / "review" / "ruoyu-art-002-2026-08-16.html"
    other_html.write_text("<h2>另一篇文章</h2>", encoding="utf-8")
    card_path = batch / "review" / "scoring" / "art-001.json"
    card = json.loads(card_path.read_text(encoding="utf-8"))
    card["html_sha256"] = hashlib.sha256(other_html.read_bytes()).hexdigest()
    card["html_path"] = "review/ruoyu-art-002-2026-08-16.html"
    card_path.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")

    report = evaluate_batch(batch)

    assert report["verdict"] == BLOCKED
    assert report["reason"] == "gate:scoring_card"
    assert "hash_mismatch" in report["errors"] or "path_not_delivery_html" in report["errors"]


def test_scoring_card_single_mismatched_html_blocks(tmp_path: Path) -> None:
    """唯一 HTML 属于另一篇文章时，不能被当前文章继承。"""
    batch = _make_batch(tmp_path)
    (batch / "review" / "ruoyu-art-002-2026-08-16.html").unlink()

    report = evaluate_batch(batch)

    assert report["verdict"] == BLOCKED
    assert report["reason"] == "gate:scoring_card"
    assert report["article"] == "art-002"
    assert "delivery_html_identity_missing" in report["errors"]


def test_scoring_card_single_bundle_without_article_identity_blocks(tmp_path: Path) -> None:
    """唯一 bundle 未声明文章身份时，不能被逐篇评分卡复用。"""
    batch = _make_batch(tmp_path)
    html_paths = [
        batch / "review" / "ruoyu-art-001-2026-08-16.html",
        batch / "review" / "ruoyu-art-002-2026-08-16.html",
    ]
    bundle = batch / "ruoyu-articles-2026-08-16.html"
    bundle.write_text(
        "\n".join(path.read_text(encoding="utf-8") for path in html_paths),
        encoding="utf-8",
    )
    for path in html_paths:
        path.unlink()
    bundle_hash = hashlib.sha256(bundle.read_bytes()).hexdigest()
    for article_id in ("art-001", "art-002"):
        card_path = batch / "review" / "scoring" / f"{article_id}.json"
        card = json.loads(card_path.read_text(encoding="utf-8"))
        card["html_sha256"] = bundle_hash
        card["html_path"] = bundle.name
        card_path.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")

    report = evaluate_batch(batch)

    assert report["verdict"] == BLOCKED
    assert report["reason"] == "gate:scoring_card"
    assert report["article"] == "art-001"
    assert "delivery_html_identity_missing" in report["errors"]


def test_style_report_without_artifact_binding_blocks(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path)
    style_path = batch / "review" / "style-gate-art-001.json"
    style = json.loads(style_path.read_text(encoding="utf-8"))
    style.pop("artifact_path")
    style.pop("artifact_sha256")
    style_path.write_text(json.dumps(style, ensure_ascii=False), encoding="utf-8")

    report = evaluate_batch(batch)

    assert report["verdict"] == BLOCKED
    assert report["reason"] == "evidence_invalid:style-gate"
    assert "artifact_binding_missing:path" in report["errors"]


def test_style_report_hash_drift_blocks(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path)
    style_path = batch / "review" / "style-gate-art-001.json"
    style = json.loads(style_path.read_text(encoding="utf-8"))
    style["artifact_sha256"] = "0" * 64
    style_path.write_text(json.dumps(style, ensure_ascii=False), encoding="utf-8")

    report = evaluate_batch(batch)

    assert report["verdict"] == BLOCKED
    assert report["reason"] == "evidence_invalid:style-gate"
    assert "artifact_binding_hash_mismatch" in report["errors"]


def test_scoring_card_html_matching_rejects_substring_collision(tmp_path: Path) -> None:
    """art-001 不能匹配文件名中的 art-0010。"""
    batch = _make_batch(tmp_path)
    original = batch / "review" / "ruoyu-art-001-2026-08-16.html"
    collision = batch / "review" / "ruoyu-art-0010-2026-08-16.html"
    original.rename(collision)

    report = evaluate_batch(batch)

    assert report["verdict"] == BLOCKED
    assert report["reason"] == "gate:scoring_card"
    assert report["article"] == "art-001"
    assert "delivery_html_identity_missing" in report["errors"]


def test_scoring_card_html_matching_rejects_identifier_suffix_collision(tmp_path: Path) -> None:
    """art-001 不能匹配文件名中的 art-001_extra。"""
    batch = _make_batch(tmp_path)
    original = batch / "review" / "ruoyu-art-001-2026-08-16.html"
    collision = batch / "review" / "ruoyu-art-001_extra-2026-08-16.html"
    original.rename(collision)

    report = evaluate_batch(batch)

    assert report["verdict"] == BLOCKED
    assert report["reason"] == "gate:scoring_card"
    assert report["article"] == "art-001"
    assert "delivery_html_identity_missing" in report["errors"]


def test_scoring_card_missing_entry_field_blocks(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path)
    card_path = batch / "review" / "scoring" / "art-001.json"
    card = json.loads(card_path.read_text(encoding="utf-8"))
    del card["title_promise"]
    card_path.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")

    report = evaluate_batch(batch)

    assert report["verdict"] == BLOCKED
    assert report["reason"] == "gate:scoring_card"
    assert report["article"] == "art-001"


def test_style_warning_triggers_pending(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path, style_warning=True)
    report = evaluate_batch(batch)
    assert report["verdict"] == PENDING
    assert any("claim:age-inference" in i for i in report["human_judgment_items"])


def test_release_info_does_not_trigger_pending(tmp_path: Path) -> None:
    """Release-specific info hints are advisory, not final-review PENDING."""
    batch = _make_batch(tmp_path)
    style_path = batch / "review" / "style-gate-art-001.json"
    style = json.loads(style_path.read_text(encoding="utf-8"))
    style["articles"][0]["hits"] = [
        {"severity": "info", "rule": "date:release-claim",
         "reason": "只需核对当前日期来源，不要求撤档史核验"},
        {"severity": "info", "rule": "release-history:claim",
         "reason": "条件性档期历史提示"},
    ]
    style_path.write_text(json.dumps(style, ensure_ascii=False), encoding="utf-8")

    report = evaluate_batch(batch)

    assert report["verdict"] == PUBLISHABLE
    assert report["human_judgment_items"] == []


def test_fact_density_warning_triggers_pending(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path)
    style_path = batch / "review" / "style-gate-art-001.json"
    style = json.loads(style_path.read_text(encoding="utf-8"))
    style["articles"][0]["fact_density"] = {
        "status": "warning",
        "reason": "事实锚点段落仅 4/16 (<1/3)",
    }
    style["articles"][0]["hits"] = []
    style_path.write_text(json.dumps(style, ensure_ascii=False), encoding="utf-8")

    report = evaluate_batch(batch)

    assert report["verdict"] == PENDING
    assert any(
        "fact_density" in item and "4/16" in item
        for item in report["human_judgment_items"]
    )


@pytest.mark.parametrize(
    ("run_dir", "style_file"),
    [
        ("2026-08-16/controlled-021", "style-gate-art-002.json"),
        ("2026-08-16/controlled-024", "style-gate-art-002.json"),
    ],
)
def test_real_hook_declaration_mismatch_triggers_pending(
    tmp_path: Path, run_dir: str, style_file: str
) -> None:
    batch = _make_batch(tmp_path)
    style_path = batch / "review" / "style-gate-art-001.json"
    style = json.loads(style_path.read_text(encoding="utf-8"))
    style["articles"][0]["hook_declaration"] = _real_hook_declaration(run_dir, style_file)
    style["articles"][0]["hits"] = []
    style_path.write_text(json.dumps(style, ensure_ascii=False), encoding="utf-8")

    report = evaluate_batch(batch)

    assert report["verdict"] == PENDING
    assert any(
        "hook_declaration" in item and "声明与正文不符" in item
        for item in report["human_judgment_items"]
    )


def test_hook_declaration_missing_triggers_pending(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path)
    style_path = batch / "review" / "style-gate-art-001.json"
    style = json.loads(style_path.read_text(encoding="utf-8"))
    style["articles"][0]["hook_declaration"] = {
        "status": "missing",
        "reason": "未声明最强钩子（data-hook）：审查无从核验。",
        "hook": "",
    }
    style["articles"][0]["hits"] = []
    style_path.write_text(json.dumps(style, ensure_ascii=False), encoding="utf-8")

    report = evaluate_batch(batch)

    assert report["verdict"] == PENDING
    assert any(
        "hook_declaration" in item and "未声明最强钩子" in item
        for item in report["human_judgment_items"]
    )


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("opening_hook", "开头缺少事实锚点"),
        ("title_gap", "标题缺少心理缺口"),
        ("fact_density", "事实锚点段落仅 4/16"),
        ("hook_declaration", "未声明最强钩子"),
        ("closing_interaction", "结尾互动检查需要人工判断"),
    ],
)
def test_structured_style_warning_triggers_pending(
    tmp_path: Path, field: str, reason: str
) -> None:
    batch = _make_batch(tmp_path)
    style_path = batch / "review" / "style-gate-art-001.json"
    style = json.loads(style_path.read_text(encoding="utf-8"))
    style["articles"][0][field] = {"status": "warning", "reason": reason}
    style["articles"][0]["hits"] = []
    style_path.write_text(json.dumps(style, ensure_ascii=False), encoding="utf-8")

    report = evaluate_batch(batch)

    assert report["verdict"] == PENDING
    assert any(f"{field}: {reason}" in item for item in report["human_judgment_items"])


def test_all_pass_publishable(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path)
    report = evaluate_batch(batch)
    assert report["verdict"] == PUBLISHABLE
    assert report["publication_authorization"] == "not_authorized"


def test_markdown_surface_is_publishable_without_html_or_preview_evidence(tmp_path: Path) -> None:
    batch = _make_markdown_batch(tmp_path)

    report = evaluate_batch(batch)

    assert report["verdict"] == PUBLISHABLE
    assert report["review_surface"] == "markdown_codex"
    assert "preview_mode" not in report


def test_markdown_surface_missing_evidence_blocks_without_html_fallback(tmp_path: Path) -> None:
    batch = _make_markdown_batch(tmp_path)
    (batch / "review" / "markdown-review-evidence.json").unlink()

    report = evaluate_batch(batch)

    assert report["verdict"] == BLOCKED
    assert report["reason"] == "evidence_missing:markdown-review-evidence"


def test_markdown_surface_scoring_card_binds_current_draft(tmp_path: Path) -> None:
    batch = _make_markdown_batch(tmp_path)
    draft = batch / "drafts" / "art-001.md"
    draft.write_text(draft.read_text(encoding="utf-8") + "漂移", encoding="utf-8")
    from article_group.review_surface import build_markdown_review_evidence
    payload = json.loads((batch / "batch.json").read_text(encoding="utf-8"))
    _write_json(
        batch / "review" / "markdown-review-evidence.json",
        build_markdown_review_evidence(batch, payload["articles"], run_id=payload["run_id"]),
    )

    report = evaluate_batch(batch)

    assert report["verdict"] == BLOCKED
    assert report["reason"] == "gate:scoring_card"
    assert report["article"] == "art-001"


def test_markdown_surface_rejects_preview_metadata(tmp_path: Path) -> None:
    batch = _make_markdown_batch(tmp_path)
    payload = json.loads((batch / "batch.json").read_text(encoding="utf-8"))
    payload["preview_mode"] = "local_codex"
    _write_json(batch / "batch.json", payload)

    report = evaluate_batch(batch)

    assert report["verdict"] == BLOCKED
    assert report["reason"] == "gate:review_surface"


def test_markdown_surface_rejects_editorial_record_html_bindings(tmp_path: Path) -> None:
    markdown = tmp_path / "drafts" / "art-001.md"
    markdown.parent.mkdir(parents=True)
    markdown.write_text("# 标题\n\n正文", encoding="utf-8")
    record = {
        "review_surface": "markdown_codex",
        "article_id": "art-001",
        "final_review_ref": {
            "path": "drafts/art-001.md",
            "version": "markdown-review-v1",
            "sha256": hashlib.sha256(markdown.read_bytes()).hexdigest(),
        },
        "stages": [{
            "evidence_refs": [{
                "path": "review/frozen/old.html",
                "version": "frozen-html-v1",
                "sha256": "0" * 64,
            }],
        }],
        "handoff": {"evidence_refs": []},
    }

    errors = _validate_editorial_review_surface(
        record, tmp_path, "markdown_codex", {"art-001": markdown}
    )

    assert "editorial_html_reference_forbidden:review/frozen/old.html" in errors


def test_explicit_local_preview_mode_does_not_require_canonical_http(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path)
    batch_json = batch / "batch.json"
    payload = json.loads(batch_json.read_text(encoding="utf-8"))
    payload["preview_mode"] = "local_codex"
    batch_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    html_paths = {
        article_id: batch / "review" / f"ruoyu-{article_id}-2026-08-16.html"
        for article_id in ("art-001", "art-002")
    }
    _write_preview_evidence(batch, html_paths, mode="local_codex")

    report = evaluate_batch(batch)

    assert report["verdict"] == PUBLISHABLE
    assert report["preview_mode"] == "local_codex"


def test_explicit_canonical_preview_mode_blocks_non_200_route(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path)
    batch_json = batch / "batch.json"
    payload = json.loads(batch_json.read_text(encoding="utf-8"))
    payload["preview_mode"] = "canonical_http"
    batch_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    html_paths = {
        article_id: batch / "review" / f"ruoyu-{article_id}-2026-08-16.html"
        for article_id in ("art-001", "art-002")
    }
    _write_preview_evidence(batch, html_paths, mode="canonical_http", http_status=404)

    report = evaluate_batch(batch)

    assert report["verdict"] == BLOCKED
    assert report["reason"] == "gate:preview_contract"
    assert "preview_canonical_http_not_pass" in report["errors"]


def test_m2_pending_review_state_cannot_be_publishable(tmp_path: Path) -> None:
    """M2 quality evidence stays PENDING until independent/human review is complete."""
    batch = _make_batch(tmp_path)
    batch_json = batch / "batch.json"
    payload = json.loads(batch_json.read_text(encoding="utf-8"))
    payload.update({
        "milestone": "M2 checkpoint",
        "manifest_state": "R7 mechanically-verified",
        "target_state": "R7.5 awaiting-independent-review",
    })
    for article in payload["articles"]:
        article["gate_status"] = {
            "independent_review": "needs_changes",
            "controller_acceptance": "pending",
        }
        article["delivery_state"] = "pending_independent_review"
        article["html_delivery_state"] = "withheld"
    batch_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    report = evaluate_batch(batch)

    assert report["verdict"] == PENDING
    assert any("independent_review=needs_changes" in item
               for item in report["human_judgment_items"])
    assert any("human_editor_attestation=pending_or_missing" in item
               for item in report["human_judgment_items"])


def test_m2_completed_state_requires_separate_human_attestation(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path)
    batch_json = batch / "batch.json"
    payload = json.loads(batch_json.read_text(encoding="utf-8"))
    payload.update({
        "milestone": "M2 checkpoint",
        "manifest_state": "R7.5 awaiting-independent-review",
        "target_state": "R8 review-ready",
    })
    for article in payload["articles"]:
        article["gate_status"] = {
            "independent_review": "approve",
            "controller_acceptance": "accepted",
        }
        article["delivery_state"] = "generated"
        article["html_delivery_state"] = "generated"
    batch_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    for article_id in ("art-001", "art-002"):
        card_path = batch / "review" / "scoring" / f"{article_id}.json"
        card = json.loads(card_path.read_text(encoding="utf-8"))
        card["review_status"] = "human_reviewed"
        card["human_editor_attestation"] = True
        card_path.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")

    report = evaluate_batch(batch)

    assert report["verdict"] == PENDING
    assert any("human_attestation_missing" in item for item in report["human_judgment_items"])


def test_m2_requires_revalidation_for_dynamic_fact_card(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path)
    batch_json = batch / "batch.json"
    payload = json.loads(batch_json.read_text(encoding="utf-8"))
    payload.update({
        "milestone": "M2 checkpoint",
        "manifest_state": "R7.5 awaiting-independent-review",
        "target_state": "R8 review-ready",
    })
    for article in payload["articles"]:
        article["gate_status"] = {
            "independent_review": "approve",
            "controller_acceptance": "accepted",
        }
        article["delivery_state"] = "generated"
        article["html_delivery_state"] = "generated"
    batch_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    for article_id in ("art-001", "art-002"):
        card_path = batch / "review" / "scoring" / f"{article_id}.json"
        card = json.loads(card_path.read_text(encoding="utf-8"))
        card["review_status"] = "human_reviewed"
        card["human_editor_attestation"] = True
        card_path.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
        _write_json(batch / "review" / article_id / "fact-card.json", {
            "article_id": article_id,
            "data_as_of": "2026-08-25T08:00:00+08:00",
            "update_required_before_publication": "yes",
            "permitted_claims": [{"claim_id": "F1", "claim": "动态事实"}],
        })

    report = evaluate_batch(batch)

    assert report["verdict"] == PENDING
    assert any("revalidation_missing" in item for item in report["human_judgment_items"])


def test_source_provenance_gate_rejects_excluded_source_in_new_contract(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path)
    payload = json.loads((batch / "batch.json").read_text(encoding="utf-8"))
    payload["provenance_contract_version"] = "source-provenance-v1"
    payload["articles"][0]["source_refs"] = ["src-excluded"]
    _write_json(batch / "batch.json", payload)
    _write_json(batch / "source-manifest.json", {
        "sources": [
            {"source_id": "src-good", "eligible_for_current_draft": True},
            {"source_id": "src-excluded", "role": "context-only-excluded", "eligible_for_current_draft": False},
        ]
    })

    report = evaluate_batch(batch)

    assert report["verdict"] == BLOCKED
    assert report["reason"] == "gate:source_provenance"
    assert "excluded_source_in_current_ref:art-001:src-excluded" in report["errors"]


def test_editorial_record_invalid_blocks(tmp_path: Path) -> None:
    """editorial-record 存在但校验失败 → 必须 BLOCKED（fail-closed）。

    合法记录的四阶段契约校验由 editorial_review 自身测试覆盖；
    final_review 只保证消费侧不放过非法记录。
    """
    batch = _make_batch(tmp_path, with_editorial=True)
    report = evaluate_batch(batch)
    assert report["verdict"] == BLOCKED
    assert report["reason"] == "gate:editorial_review"


def test_prose_missing_blocks(tmp_path: Path) -> None:
    """证据链缺失 = BLOCKED（fail-closed）：prose-pilot 报告是必需产物。"""
    batch = _make_batch(tmp_path, with_prose=False)
    report = evaluate_batch(batch)
    assert report["verdict"] == BLOCKED
    assert report["reason"] == "evidence_missing:prose-pilot-report.json"


def test_char_count_divergence_pending(tmp_path: Path) -> None:
    batch = _make_batch(tmp_path, with_style=True, with_prose=True)
    # prose chars 与 style chars 差距超阈值 → PENDING
    prose = json.loads((batch / "review" / "prose-pilot-report.json").read_text())
    prose["batches"][0]["articles"][0]["chars"] = 2600
    (batch / "review" / "prose-pilot-report.json").write_text(
        json.dumps(prose, ensure_ascii=False), encoding="utf-8")
    report = evaluate_batch(batch)
    assert report["verdict"] == PENDING
    assert report["publication_authorization"] == "not_authorized"


def _fake_history_with_duplicate(exclude_run: str = "") -> list[dict]:
    """历史批次含《测试电影》旧文 → check_cross_batch 应报 same_work error。

    签名与 collect_history 一致（接受 exclude_run），供 monkeypatch 替换。
    """
    assert exclude_run != "controlled-015"  # 排除本批时不命中（防御性）
    return [{
        "batch_dir": "controlled-015",
        "path": "/fake/controlled-015/review/frozen/x.html",
        "titles": ["《测试电影》的票房奇迹（旧角度）"],
        "works": ["测试电影"],
        "recent3": True,
    }]


def test_cross_batch_duplicate_without_waiver_blocks(tmp_path: Path, monkeypatch) -> None:
    """跨批重复、无人工裁决注记 → BLOCKED（机器只拦未裁决重复）。"""
    batch = _make_batch(tmp_path, with_style=True, with_prose=True)
    monkeypatch.setattr("article_group.final_review.collect_history",
                        _fake_history_with_duplicate)
    report = evaluate_batch(batch)
    assert report["verdict"] == BLOCKED
    assert "cross_batch" in str(report.get("reason", ""))


def test_cross_batch_duplicate_with_waiver_passes(tmp_path: Path, monkeypatch) -> None:
    """跨批重复、但 portfolio-gate-report.json 已有人工裁决豁免注记 → 放行。

    026 真实形态：controller_adjudication.result = 'cand-001 红灯确认豁免（confirmed_new_angle）'，
    adjudicated=True，机器 respect 人工裁决、绝不自造豁免。
    """
    batch = _make_batch(tmp_path, with_style=True, with_prose=True)
    _write_json(batch / "portfolio-gate-report.json", {
        "pass": False,
        "errors": [{"level": "error", "candidate": "cand-001",
                     "id": "portfolio.cross_batch.same_work.recent"}],
        "controller_adjudication": {
            "recorded_at": "2026-08-16 22:40 CST",
            "adjudicator": "controller",
            "adjudicated": True,
            "result": "cand-001 红灯确认豁免（confirmed_new_angle）",
        },
    })
    monkeypatch.setattr("article_group.final_review.collect_history",
                        _fake_history_with_duplicate)
    report = evaluate_batch(batch)
    assert report["verdict"] == PUBLISHABLE
    assert report["adjudicated_waivers"], "豁免注记应进入结果"
    assert report["adjudicated_waivers"][0]["candidate"] == "cand-001"
    assert "confirmed_new_angle" in report["adjudicated_waivers"][0]["verdict"]


def test_waiver_requires_candidate_match(tmp_path: Path, monkeypatch) -> None:
    """裁决注记存在但 candidate 不匹配 → 不豁免（仍 BLOCKED）。"""
    batch = _make_batch(tmp_path, with_style=True, with_prose=True)
    _write_json(batch / "portfolio-gate-report.json", {
        "controller_adjudication": {
            "adjudicated": True,
            "result": "cand-999 确认豁免",
        },
    })
    monkeypatch.setattr("article_group.final_review.collect_history",
                        _fake_history_with_duplicate)
    report = evaluate_batch(batch)
    assert report["verdict"] == BLOCKED


def test_waiver_requires_adjudicated_flag(tmp_path: Path, monkeypatch) -> None:
    """注记存在但 adjudicated 非 True → 不豁免（机器不自行解读）。"""
    batch = _make_batch(tmp_path, with_style=True, with_prose=True)
    _write_json(batch / "portfolio-gate-report.json", {
        "controller_adjudication": {
            "adjudicated": False,
            "result": "cand-001 确认豁免",
        },
    })
    monkeypatch.setattr("article_group.final_review.collect_history",
                        _fake_history_with_duplicate)
    report = evaluate_batch(batch)
    assert report["verdict"] == BLOCKED
