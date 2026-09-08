from __future__ import annotations

from copy import deepcopy

from article_group.v4.template_guard import (
    analyze_template_signals,
    validate_template_signals,
)


RUN_ID = "run-template-1"
GENERATED_AT = "2026-09-08T10:00:00+08:00"


def _candidate(candidate_id: str, **overrides: object) -> dict[str, object]:
    candidate: dict[str, object] = {
        "candidate_id": candidate_id,
        "run_id": RUN_ID,
        "generated_at": GENERATED_AT,
        "title": "《长夜》值得讨论的，不只是结局？",
        "opening": "影片于2026年9月上映，主演在首映礼确认了这一点。但真正的问题是，结局为何让人意外？",
        "h2": ["## 事实先摆出来", "## 争议从哪里开始", "## 观众会怎么选"],
        "paragraphs": [
            "影片在9月上映，主创确认了人物关系。",
            "但关键不在结果，而在这个选择带来的争议。",
            "最后，观众会把自己放在哪一边？",
        ],
        "ending": "你怎么看这部电影的选择？",
    }
    candidate.update(overrides)
    return candidate


def _signal(report: dict[str, object], signal_type: str) -> dict[str, object]:
    payload = report["payload"]
    assert isinstance(payload, dict)
    signals = payload["signals"]
    assert isinstance(signals, list)
    return next(signal for signal in signals if signal["signal_type"] == signal_type)


def test_repeated_title_skeleton_is_manual_review_not_rejection() -> None:
    current = _candidate("current", title="为什么《长夜》值得讨论？")
    history = [
        _candidate(f"history-{index}", title=f"为什么《作品{index}》值得讨论？")
        for index in range(1, 5)
    ]

    report = analyze_template_signals(current, history)
    payload = report["payload"]

    assert payload["decision"] == "manual_review"
    assert payload["auto_reject"] is False
    title_signal = _signal(report, "title_skeleton")
    assert title_signal["severity"] == "warning"
    assert title_signal["matched_history_ids"] == [
        "history-1",
        "history-2",
        "history-3",
        "history-4",
    ]
    assert title_signal["evidence"]["match_count"] == 4
    assert title_signal["threshold"]["min_matches"] == 2
    assert validate_template_signals(report) == []


def test_single_shared_title_word_does_not_trigger_a_rejection() -> None:
    current = _candidate(
        "current",
        title="电影与一封未寄出的信",
        opening="主创公布了新的片名。现场没有提出悬念式问题。",
        h2=["## 主创信息", "## 制作背景"],
        paragraphs=["主创公布了片名。", "制作背景随后公开。"],
        ending="故事在这里收束。",
    )
    history = [
        _candidate(
            f"history-{index}",
            title=title,
            opening=f"第{index}部作品的资料已经公开。",
            h2=["## 放映信息", "## 观看提示"],
            paragraphs=[f"第{index}部作品已经完成。", "资料到此结束。"],
            ending="文章在这里结束。",
        )
        for index, title in enumerate(
            (
                "演员谈到新的角色",
                "一场首映礼公布阵容",
                "观众讨论新的结局",
                "导演解释拍摄方式",
            ),
            start=1,
        )
    ]

    report = analyze_template_signals(current, history)
    payload = report["payload"]

    assert payload["decision"] == "info"
    assert all(signal["severity"] == "info" for signal in payload["signals"])
    assert payload["auto_reject"] is False


def test_repeated_opening_fact_and_suspense_pattern_is_reported() -> None:
    current = _candidate(
        "current",
        opening="影片在2026年9月上映，导演确认了档期。但真正的问题是，这个选择会带来什么？",
    )
    history = [
        _candidate(
            f"history-{index}",
            opening=f"作品在202{index}年上映，主创确认了档期。但真正的问题是，它为何改变了？",
        )
        for index in range(1, 4)
    ]

    report = analyze_template_signals(current, history)
    opening_signal = _signal(report, "opening_fact_suspense")

    assert opening_signal["severity"] == "warning"
    assert opening_signal["matched_history_ids"] == [
        "history-1",
        "history-2",
        "history-3",
    ]
    assert opening_signal["evidence"]["current_has_fact"] is True
    assert opening_signal["evidence"]["current_has_suspense"] is True


def test_h2_and_paragraph_progression_normalizes_labels_and_numbering() -> None:
    current = _candidate(
        "current",
        h2=["## 1. 事实先摆出来", "## 2. 争议从哪里开始", "## 3. 观众会怎么选"],
        paragraphs=[
            "先看影片的上映信息。",
            "但真正的争议在人物选择。",
            "最后，观众会怎么选？",
        ],
    )
    history = [
        _candidate(
            f"history-{index}",
            h2=["<h2>一、事实先摆出来</h2>", "<h2>二、争议从哪里开始</h2>", "<h2>三、观众会怎么选</h2>"],
            paragraphs=[
                "先看作品的上映信息。",
                "不过真正的争议在人物选择。",
                "最后，读者会怎么选？",
            ],
        )
        for index in range(1, 4)
    ]

    report = analyze_template_signals(current, history)
    progression_signal = _signal(report, "h2_paragraph_progression")

    assert progression_signal["severity"] == "warning"
    assert progression_signal["matched_history_ids"] == [
        "history-1",
        "history-2",
        "history-3",
    ]
    assert progression_signal["evidence"]["h2_count"] == 3
    assert progression_signal["evidence"]["paragraph_count"] == 3


def test_number_and_adjective_groups_are_normalized_as_a_combination() -> None:
    current = _candidate(
        "current",
        title="3次惊人的反转，为什么仍然有效？",
        number_tokens=["3"],
        adjective_groups=["惊人的反转"],
    )
    history = [
        _candidate(
            f"history-{index}",
            title=f"{index + 3}次惊人的反转，为什么仍然有效？",
            number_tokens=[str(index + 3)],
            adjective_groups=["惊人的反转"],
        )
        for index in range(1, 4)
    ]

    report = analyze_template_signals(current, history)
    combo_signal = _signal(report, "number_adjective_combination")

    assert combo_signal["severity"] == "warning"
    assert combo_signal["matched_history_ids"] == [
        "history-1",
        "history-2",
        "history-3",
    ]
    assert combo_signal["evidence"]["current_number_tokens"] == ["<NUM>"]
    assert combo_signal["evidence"]["current_adjective_groups"] == ["惊人的反转"]


def test_repeated_mechanical_ending_question_is_reported() -> None:
    current = _candidate("current", ending="看到这里，你怎么看？")
    history = [
        _candidate(f"history-{index}", ending="读完这篇文章，你怎么看？")
        for index in range(1, 4)
    ]

    report = analyze_template_signals(current, history)
    ending_signal = _signal(report, "mechanical_ending_question")

    assert ending_signal["severity"] == "warning"
    assert ending_signal["matched_history_ids"] == [
        "history-1",
        "history-2",
        "history-3",
    ]
    assert ending_signal["evidence"]["current_is_mechanical_question"] is True


def test_only_recent_window_is_compared() -> None:
    current = _candidate("current", title="为什么《长夜》值得讨论？")
    history = [
        _candidate("old-match", title="为什么《旧作》值得讨论?"),
        *[
            _candidate(
                f"recent-{index}",
                title=f"第{index}部作品的上映信息",
                opening=f"第{index}部作品的资料已经公开。",
                h2=["## 近期资料", "## 资料收束"],
                paragraphs=[f"第{index}部作品的资料已经公开。", "文章在这里结束。"],
                ending="故事在这里收束。",
            )
            for index in range(1, 6)
        ],
    ]

    report = analyze_template_signals(current, history, window=5)
    title_signal = _signal(report, "title_skeleton")

    assert report["payload"]["history_ids"] == [
        "recent-1",
        "recent-2",
        "recent-3",
        "recent-4",
        "recent-5",
    ]
    assert title_signal["matched_history_ids"] == []
    assert report["payload"]["decision"] == "info"


def test_invalid_input_is_fail_closed_and_never_authorizes_publication() -> None:
    report = analyze_template_signals(
        {"candidate_id": "current", "run_id": RUN_ID, "generated_at": "bad"},
        "not-a-history",  # type: ignore[arg-type]
    )

    payload = report["payload"]
    assert payload["decision"] == "manual_review"
    assert payload["auto_reject"] is False
    assert payload["errors"]
    assert payload["publication_authorization"] == "not_authorized"
    assert validate_template_signals(report)


def test_validator_rejects_open_or_authorizing_report_mutations() -> None:
    report = analyze_template_signals(_candidate("current"), [_candidate("history-1")])

    extra = deepcopy(report)
    extra["unexpected"] = True
    assert "invalid:top_level" in validate_template_signals(extra)

    rejected = deepcopy(report)
    rejected["payload"]["auto_reject"] = True
    assert "auto_reject_must_be_false" in validate_template_signals(rejected)

    authorized = deepcopy(report)
    authorized["payload"]["publication_authorization"] = "authorized"
    assert (
        "publication_authorization_must_be_not_authorized"
        in validate_template_signals(authorized)
    )


def test_all_reports_use_the_closed_task1_envelope() -> None:
    report = analyze_template_signals(_candidate("current"), [_candidate("history-1")])

    assert set(report) == {
        "schema_version",
        "run_id",
        "generated_at",
        "input_hashes",
        "payload",
    }
    assert report["schema_version"] == "v4-template-signals-v1"
    assert set(report["input_hashes"]) == {"current", "history"}
    assert validate_template_signals(report) == []
