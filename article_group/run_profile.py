"""Explicit article-batch profiles shared by daily and controlled runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# The editorial target remains 1500–2200 Chinese characters.  The production
# policy allows elasticity on either side so a complete article is not padded
# merely to hit the target band.  2026-09-16 controller ruling: 字数要求允许
# ±100 误差（下限 1000→900，上限 2700→2800），篇幅以素材为准。
TARGET_MIN_CJK_CHARS = 1500
TARGET_MAX_CJK_CHARS = 2200
CHAR_COUNT_FLEX_MARGIN = 600
MIN_CJK_CHARS = TARGET_MIN_CJK_CHARS - CHAR_COUNT_FLEX_MARGIN
MAX_CJK_CHARS = TARGET_MAX_CJK_CHARS + CHAR_COUNT_FLEX_MARGIN


@dataclass(frozen=True)
class RunProfile:
    name: str
    article_count: int
    slot_labels: tuple[str, ...]
    min_cjk_chars: int = MIN_CJK_CHARS
    max_cjk_chars: int = MAX_CJK_CHARS


RUN_PROFILES: dict[str, RunProfile] = {
    "two_article_daily": RunProfile(
        name="two_article_daily",
        article_count=2,
        slot_labels=("A", "B"),
    ),
    "three_slot_controlled": RunProfile(
        name="three_slot_controlled",
        article_count=3,
        slot_labels=("A", "B", "C"),
    ),
}


def get_run_profile(name: str) -> RunProfile:
    try:
        return RUN_PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"unknown_run_profile:{name}") from exc


def validate_batch_profile(
    batch: dict[str, Any], *, require_explicit: bool = False
) -> list[str]:
    """Validate count and slot identity without changing legacy callers.

    Historical three-slot fixtures may omit ``run_profile`` unless the caller
    opts into ``require_explicit``. New production entry points should opt in.
    """
    raw_name = batch.get("run_profile")
    if not isinstance(raw_name, str) or not raw_name.strip():
        return ["run_profile_missing"] if require_explicit else []

    name = raw_name.strip()
    try:
        profile = get_run_profile(name)
    except ValueError:
        return [f"run_profile_unknown:{name}"]

    articles = batch.get("articles")
    if not isinstance(articles, list):
        return [f"articles_must_be_list:{name}"]

    errors: list[str] = []
    actual_count = len(articles)
    if actual_count != profile.article_count:
        errors.append(
            f"article_count_mismatch:{name}:expected={profile.article_count}:actual={actual_count}"
        )
    declared_count = batch.get("article_count")
    if declared_count is not None and declared_count != profile.article_count:
        errors.append(
            f"declared_article_count_mismatch:{name}:expected={profile.article_count}:actual={declared_count}"
        )

    actual_slots: list[str] = []
    for index, article in enumerate(articles):
        if not isinstance(article, dict):
            errors.append(f"article_not_object:{index}")
            continue
        slot = article.get("slot")
        if not isinstance(slot, str) or not slot.strip():
            errors.append(f"article_slot_missing:{index}")
            continue
        actual_slots.append(slot.strip())
        if slot.strip() not in profile.slot_labels:
            errors.append(f"article_slot_invalid:{slot.strip()}:{name}")

    if len(set(actual_slots)) != len(actual_slots):
        errors.append("article_slots_duplicate")
    if set(actual_slots) != set(profile.slot_labels):
        errors.append(
            f"article_slots_mismatch:{name}:expected={','.join(profile.slot_labels)}:"
            f"actual={','.join(sorted(set(actual_slots)))}"
        )
    return errors
