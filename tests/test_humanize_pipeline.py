"""tests for humanize_pipeline, human fingerprints registry, and prewrite validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from article_group.article_skeleton import build_skeleton, format_skeleton_markdown
from article_group.humanize_pipeline import (
    deterministic_polish,
    check_local_gates,
    evaluate_zhuque_result,
    perform_surgical_repair,
)
from article_group.prewrite import (
    validate_opening_hook,
    validate_realistic_stakes,
)
from article_group.prompts.human_fingerprints import (
    get_genre_sample,
    get_human_fingerprints_instruction,
)


def test_skeleton_builds_with_human_fingerprints():
    res = build_skeleton(
        topic="三大队与迟到的正义",
        structure_type="contrarian",
        killer_stance="真正的正义不是写在判决书上的死条文，而是普通刑警用下半辈子熬出来的血泪账。",
        opening_hook="王二勇被按倒在泥水里时，老程手里的送水单据已经被血水浸透。",
        sensory_anchors=["折断的实心拖把杆", "被血迹浸透的送水单", "生锈的大铁链子"],
        realistic_stakes=["三大队七名刑警脱掉警服后的生计", "每个月六百块钱的房贷与抚养费"],
        target_words=2000,
    )
    assert res["opening_hook"].startswith("王二勇被按倒")
    assert len(res["sensory_anchors"]) == 3
    assert len(res["realistic_stakes"]) == 2
    assert res["stance_valid"] is True

    md = format_skeleton_markdown(res)
    assert "开篇反差钩子 (Opening Hook)" in md
    assert "切肤现实账本" in md
    assert "王二勇被按倒" in md


def test_validate_opening_hook_catches_cliches_and_missing_hook():
    evidence_bad_cliche = {
        "opening_hook": "随着影视行业的不断发展，刑侦剧走入了新时代"
    }
    body = "随着影视行业的不断发展，刑侦剧走入了新时代。这是一部好戏。"
    errs = validate_opening_hook(evidence_bad_cliche, body)
    assert any("contains_cliche" in e for e in errs)

    evidence_valid = {
        "opening_hook": "王二勇被按倒在泥水里时，老程手里的单据已碎。"
    }
    # Body first paragraph doesn't have it
    body_missing = "故事发生在一个普通的夏夜。巡警小李走在路上。"
    errs_missing = validate_opening_hook(evidence_valid, body_missing)
    assert any("not_reflected" in e for e in errs_missing)

    # Body first paragraph has it
    body_ok = "王二勇被按倒在泥水里时，老程手里的单据已碎。老程喘着粗气。\n\n接下来进入第二段。"
    errs_ok = validate_opening_hook(evidence_valid, body_ok)
    assert errs_ok == []


def test_validate_realistic_stakes_requires_mention_in_body():
    evidence = {
        "realistic_stakes": ["房贷六百块", "被扒掉警服后的生计"]
    }
    body_missing = "这是一场关于正义与邪恶的宏大较量，每个人都在追寻真理。"
    errs = validate_realistic_stakes(evidence, body_missing)
    assert len(errs) > 0

    body_present = "老张叹气，家里房贷六百块逾期了，被扒掉警服后的生计成了最大的难题。"
    errs_ok = validate_realistic_stakes(evidence, body_present)
    assert errs_ok == []


def test_genre_fingerprints_registry():
    crime = get_genre_sample("悬疑刑侦破案片")
    assert crime.genre_key == "crime_suspense"
    assert "三大队" in crime.works

    biz = get_genre_sample("影视票房与投资商战")
    assert biz.genre_key == "business_workplace"
    assert "老狐狸" in biz.works

    instr = get_human_fingerprints_instruction("社会伦理第二十条")
    assert "三秒夺魂" in instr
    assert "大白话拆台" in instr
    assert "利益算盘" in instr


def test_deterministic_polish_cleans_ai_markers():
    raw_draft = """# 测试文章

近年来，随着电影市场的繁荣，一部新片上映了。

值得一提的是，这部电影不仅视觉震撼，而且思想深刻。从某种意义上说，它赋予了角色全新的底层逻辑。
这绝不是偶然，而是必然。毋庸置疑，它打造了全新的闭环。

对此，你怎么看？欢迎在评论区留言讨论！"""

    evidence = {
        "opening_hook": "聋哑女人转身跳下了楼，重重砸在车顶上"
    }

    polished, fixes = deterministic_polish(raw_draft, evidence)

    assert "欢迎在评论区留言讨论" not in polished
    assert "对此，你怎么看" not in polished
    assert "近年来，随着" not in polished
    assert "聋哑女人转身跳下了楼" in polished
    assert "值得一提的是" not in polished
    assert "毋庸置疑" not in polished
    assert len(fixes) >= 3


def test_evaluate_zhuque_result():
    green_data = {
        "softmax_confidence": 0.22,
        "labels_ratio": {"0": 0.85, "1": 0.0, "2": 0.15},
    }
    eval_green = evaluate_zhuque_result(green_data)
    assert eval_green["is_all_green"] is True

    red_data = {
        "softmax_confidence": 0.78,
        "labels_ratio": {"0": 0.30, "1": 0.50, "2": 0.20},
        "splits": [
            {"label": "1", "text": "毋庸置疑，这部作品展现出了深刻的人性思考。"},
            {"label": "0", "text": "他蹲在马路牙子上啃完了硬馒头。"}
        ]
    }
    eval_red = evaluate_zhuque_result(red_data)
    assert eval_red["is_all_green"] is False
    assert len(eval_red["danger_sentences"]) == 1


def test_perform_surgical_repair():
    text = "毋庸置疑，这部作品展现出了深刻的人性思考。他蹲在马路牙子上啃完了硬馒头。"
    danger = [{"label": "1", "text": "毋庸置疑，这部作品展现出了深刻的人性思考。"}]

    repaired, logs = perform_surgical_repair(text, danger)
    assert "展现出" not in repaired
    assert len(logs) == 1
