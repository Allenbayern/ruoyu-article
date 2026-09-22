"""编辑门禁单测（2026-09-21，daily-010 编读复盘后新增）。

这些用例对应"010 两篇成品倒推出来的规则"：
- 标题问"为什么"而正文没有本文的因果/机制段 → 报警（声明 strict 时阻断）；
- 同一"要求/动作"概念被复述超过 2 次 → 报警；
- own_analysis_locator（本文自己的判断段）缺失或指向归属句 → 阻断；
- subject_content_locator（让读者知道"这部作品是什么"的那句）缺失 → 阻断；
- 声明了 editor_read 却没有 complete 的编读记录 → 阻断。
"""

from __future__ import annotations

import json
from pathlib import Path

from article_group.editorial_gate import build_editorial_gate

BODY_WITH_CAUSAL = (
    "9月17日，一场发布会在北京举行。\n\n"
    "官方给出的数字是：前8个月上线43万部微短剧，其中AI剧占比超过九成。\n\n"
    "之所以是现在，是因为《微短剧发展管理办法》月初刚落地，"
    "十五五开局的第一场发布会需要给这一年定规矩。"
)

BODY_WITHOUT_CAUSAL = (
    "9月17日，一场发布会在北京举行。\n\n"
    "官方给出的数字是：前8个月上线43万部微短剧，其中AI剧占比超过九成。\n\n"
    "他介绍说，这一轮有四条要求，还介绍了其他情况。"
)

BODY_ATTRIBUTED_ANALYSIS = (
    "9月17日，一场发布会在北京举行。\n\n"
    "他说，这一轮的重点是把好内容关。"
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, (dict, list)):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        path.write_text(str(value), encoding="utf-8")


def _make_run(
    tmp_path: Path,
    *,
    aid: str = "art-001",
    title: str = "官方为什么这时候力挺真人剧",
    body: str = BODY_WITHOUT_CAUSAL,
    extra_record: dict | None = None,
    editor_review: dict | None = None,
) -> Path:
    root = tmp_path
    _write(root / f"task-hierarchy/article-task-{aid}.json", {"article_id": aid})
    _write(root / f"drafts/{aid}/body_draft.md", body)
    title_pack = {
        "schema_version": "title-pack-v1",
        "directions": [{"title_id": "t1", "title": title, "body_locators": ["p1"]}],
    }
    _write(root / f"review/{aid}/title-pack.json", title_pack)
    record = {
        "schema_version": "content-fidelity-v1",
        "article_id": aid,
        "mechanism_locator": "p3",
        "reader_takeaway_locator": "p3",
    }
    record.update(extra_record or {})
    _write(root / f"review/{aid}/content-fidelity.json", record)
    if editor_review is not None:
        _write(root / f"review/{aid}/editor-review.json", editor_review)
    return root


def test_title_question_without_causal_paragraph_warns_when_advisory(tmp_path: Path) -> None:
    root = _make_run(tmp_path, body=BODY_WITHOUT_CAUSAL)

    report = build_editorial_gate(root)

    assert report["pass"] is True, report["errors"]
    assert any("title_answerability" in w for w in report["warnings"]), report["warnings"]
    check = report["articles"][0]["checks"]["title_answerability"]
    assert check["status"] == "warning"
    assert check["causal_paragraphs"] == []


def test_title_question_without_causal_paragraph_blocks_when_strict(tmp_path: Path) -> None:
    root = _make_run(tmp_path, body=BODY_WITHOUT_CAUSAL)

    report = build_editorial_gate(root, {"art-001": {"strict": True}})

    assert report["pass"] is False
    assert any("title_answerability" in e for e in report["errors"]), report["errors"]


def test_title_question_with_causal_paragraph_passes(tmp_path: Path) -> None:
    root = _make_run(tmp_path, body=BODY_WITH_CAUSAL)

    report = build_editorial_gate(root, {"art-001": {"strict": True}})

    check = report["articles"][0]["checks"]["title_answerability"]
    assert check["status"] == "ok"
    assert "p3" in check["causal_paragraphs"]
    assert report["pass"] is True, report["errors"]


def test_title_without_question_is_not_checked(tmp_path: Path) -> None:
    root = _make_run(tmp_path, title="一部七年前的老片成了中秋档最热的一部", body=BODY_WITHOUT_CAUSAL)

    report = build_editorial_gate(root, {"art-001": {"strict": True}})

    assert report["articles"][0]["checks"]["title_answerability"]["status"] == "not_applicable"
    assert report["pass"] is True, report["errors"]


def test_repetition_watch_warns_over_two_and_blocks_when_strict(tmp_path: Path) -> None:
    body = (
        "AI剧要带内容标识。\n\n"
        "平台要强化内容标识与授权底线。\n\n"
        "这一轮最关键的是内容标识，其次是人工审核。\n\n"
        "说到底，内容标识是这一轮的落点。"
    )
    root = _make_run(tmp_path, body=body)

    advisory = build_editorial_gate(root, {"art-001": {"repetition_watch": ["内容标识"]}})
    assert advisory["pass"] is True
    assert any("repetition_watch" in w for w in advisory["warnings"])
    counts = advisory["articles"][0]["checks"]["repetition_watch"]["counts"]
    assert counts["内容标识"] == 4

    strict = build_editorial_gate(root, {"art-001": {"strict": True, "repetition_watch": ["内容标识"]}})
    assert strict["pass"] is False
    assert any("repetition_watch" in e for e in strict["errors"])


def test_own_analysis_locator_missing_blocks(tmp_path: Path) -> None:
    root = _make_run(tmp_path, body=BODY_WITH_CAUSAL)

    report = build_editorial_gate(root, {"art-001": {"strict": True, "own_analysis": True}})

    assert report["pass"] is False
    assert any("own_analysis_locator_missing" in e for e in report["errors"]), report["errors"]


def test_own_analysis_locator_pointing_at_attribution_blocks(tmp_path: Path) -> None:
    root = _make_run(
        tmp_path,
        body=BODY_WITH_CAUSAL + "\n\n他说，这一轮的重点是把好内容关。",
        extra_record={"own_analysis_locator": "p4"},
    )

    report = build_editorial_gate(root, {"art-001": {"strict": True, "own_analysis": True}})

    assert report["pass"] is False
    assert any("own_analysis_locator_is_attribution" in e for e in report["errors"]), report["errors"]


def test_own_analysis_locator_with_own_judgment_passes(tmp_path: Path) -> None:
    root = _make_run(
        tmp_path,
        body=BODY_WITH_CAUSAL + "\n\n把两个数字并排看：43万部里九成是AI剧，而被下架的6.8万部里九成以上也是AI剧。",
        extra_record={"own_analysis_locator": "p4"},
    )

    report = build_editorial_gate(root, {"art-001": {"strict": True, "own_analysis": True}})

    assert report["pass"] is True, report["errors"]
    assert report["articles"][0]["checks"]["own_analysis"]["status"] == "ok"


def test_subject_content_locator_missing_blocks(tmp_path: Path) -> None:
    root = _make_run(tmp_path, body=BODY_WITH_CAUSAL)

    report = build_editorial_gate(root, {"art-001": {"strict": True, "subject_content": True}})

    assert report["pass"] is False
    assert any("subject_content_locator_missing" in e for e in report["errors"]), report["errors"]


def test_editor_read_declared_requires_complete_record(tmp_path: Path) -> None:
    root = _make_run(tmp_path, body=BODY_WITH_CAUSAL)

    missing = build_editorial_gate(root, {"art-001": {"strict": True, "editor_read": True}})
    assert missing["pass"] is False
    assert any("editor_review_missing" in e for e in missing["errors"]), missing["errors"]

    pending = _make_run(
        tmp_path,
        body=BODY_WITH_CAUSAL,
        editor_review={"status": "PENDING", "decision": "human_review_required"},
    )
    report = build_editorial_gate(pending, {"art-001": {"strict": True, "editor_read": True}})
    assert report["pass"] is False
    assert any("editor_review_not_complete" in e for e in report["errors"]), report["errors"]

    done = _make_run(
        tmp_path,
        body=BODY_WITH_CAUSAL,
        extra_record={"own_analysis_locator": "p3"},
        editor_review={"status": "complete", "decision": "approve"},
    )
    ok = build_editorial_gate(done, {"art-001": {"strict": True, "editor_read": True, "own_analysis": True}})
    assert ok["pass"] is True, ok["errors"]


def test_no_declarations_means_advisory_only(tmp_path: Path) -> None:
    root = _make_run(tmp_path, body=BODY_WITHOUT_CAUSAL)

    report = build_editorial_gate(root)

    assert report["pass"] is True, report["errors"]
    assert report["declarations"] == {}
    assert report["publication_authorization"] == "not_authorized"
