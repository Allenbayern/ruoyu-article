from __future__ import annotations

from article_group.viral_research_selection import (
    select_shape_matched_samples,
    shape_matches,
)


def _sample(sample_id: str, account_id: str, *, status: str = "qualified_viral", domain: str = "film") -> dict:
    return {
        "sample_id": sample_id,
        "platform": "wechat",
        "account_id": account_id,
        "qualification_status": status,
        "shape": {
            "medium": "long_form",
            "content_domain": domain,
            "account_type": "publisher",
            "narrative_purpose": "review",
            "topic": "work",
            "work_relation": "adaptation",
        },
    }


def test_shape_match_requires_all_specified_dimensions():
    sample = _sample("s-1", "acct-1")
    target = {"medium": "long_form", "content_domain": "film"}
    assert shape_matches(sample, target)
    assert not shape_matches(sample, {"content_domain": "gaming"})


def test_selection_prioritizes_cross_account_and_is_ready():
    samples = [
        _sample("s-1", "acct-a"),
        _sample("s-2", "acct-a"),
        _sample("s-3", "acct-b"),
        _sample("s-4", "acct-b"),
        _sample("s-5", "acct-c"),
    ]
    result = select_shape_matched_samples(
        samples,
        target_shape={"medium": "long_form", "content_domain": "film"},
        min_samples=5,
        min_accounts=2,
    )
    assert result.ready
    assert [item["account_id"] for item in result.selected[:3]] == [
        "acct-a",
        "acct-b",
        "acct-c",
    ]
    assert result.reason is None


def test_selection_keeps_pending_and_excludes_nonqualified_or_mismatched():
    samples = [
        _sample("s-p", "acct-p", status="observed_pending"),
        _sample("s-r", "acct-r", status="research_only"),
        _sample("s-b", "acct-b", status="qualified_viral", domain="gaming"),
        _sample("s-v", "acct-v", status="qualified_viral"),
    ]
    result = select_shape_matched_samples(
        samples,
        target_shape={"content_domain": "film"},
        min_samples=2,
        min_accounts=2,
    )
    assert {item["sample_id"] for item in result.pending} == {"s-p", "s-r"}
    assert any(item.get("exclusion_reason") == "shape_mismatch" for item in result.excluded)
    assert result.selected[0]["sample_id"] == "s-v"
    assert result.reason == "insufficient_qualified_samples"


def test_bilibili_qualified_signal_does_not_enter_wechat_qualified_selection():
    sample = _sample("b-1", "acct-b")
    sample["platform"] = "bilibili"
    result = select_shape_matched_samples(
        [sample],
        target_shape={"content_domain": "film"},
        min_samples=1,
        min_accounts=1,
    )
    assert not result.selected
    assert result.excluded[0]["exclusion_reason"] == "not_qualified"


def test_named_revisions_are_selected_deterministically():
    first = _sample("same", "acct-a")
    first["revision_id"] = "a"
    second = _sample("same", "acct-a")
    second["revision_id"] = "b"
    result_forward = select_shape_matched_samples(
        [first, second], target_shape={"content_domain": "film"}, min_samples=1, min_accounts=1
    )
    result_reverse = select_shape_matched_samples(
        [second, first], target_shape={"content_domain": "film"}, min_samples=1, min_accounts=1
    )
    assert result_forward.selected[0]["revision_id"] == "b"
    assert result_reverse.selected[0]["revision_id"] == "b"


def test_mixed_numeric_and_named_revisions_are_order_independent():
    numeric = _sample("same", "acct-a")
    numeric["revision_id"] = 2
    named = _sample("same", "acct-a")
    named["revision_id"] = "b"

    result_forward = select_shape_matched_samples(
        [named, numeric], target_shape={"content_domain": "film"}, min_samples=1, min_accounts=1
    )
    result_reverse = select_shape_matched_samples(
        [numeric, named], target_shape={"content_domain": "film"}, min_samples=1, min_accounts=1
    )

    assert result_forward.selected[0]["revision_id"] == 2
    assert result_reverse.selected[0]["revision_id"] == 2


def test_duplicate_evidence_cluster_cannot_supply_independent_sample_count():
    first = _sample("s-1", "acct-a")
    second = _sample("s-2", "acct-b")
    for sample in (first, second):
        sample.update(
            {
                "raw_ref": "raw/shared.html#sha256=" + "1" * 64,
                "clean_ref": "clean/shared.md#sha256=" + "2" * 64,
                "metadata_ref": "metadata/shared.json#sha256=" + "3" * 64,
                "evidence_cluster": "cluster-" + "4" * 32,
            }
        )

    result = select_shape_matched_samples(
        [first, second],
        target_shape={"content_domain": "film"},
        min_samples=2,
        min_accounts=2,
    )

    assert len(result.selected) == 1
    assert not result.ready
    assert any(
        item.get("exclusion_reason") == "duplicate_evidence_cluster"
        for item in result.excluded
    )
