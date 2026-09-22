"""assertion_ledger_coverage：读者面断言 ↔ 账本 双向覆盖检查。

回归样本取自 daily-008：L2 第一轮判的 2 条 major（「十几年过去」时间跨度、
「台词还在被引用」受众行为）在账本里都没有条目，而当时的机器门禁全绿。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from article_group.assertion_ledger_coverage import (
    AUDIENCE_ACTION_RE,
    TIME_SPAN_RE,
    check_coverage,
    extract_assertions,
    load_ledger,
    main,
    split_paragraphs,
)

DELIVERY_COVERED = """# 标题

## 第一节

十多年来，庞大的影迷群体把《让子弹飞》盘到包浆，他们对片中的台词金句如数家珍。
影片公映七天累计票房八千二百万左右，单日票房跌到第八名。
"""

DELIVERY_GAPS = """# 标题

## 第一节

十几年过去，《让子弹飞》的台词还在被引用。
"""


def _write_run(tmp_path: Path, delivery: str, *, pack_facts=(), hard=()) -> Path:
    root = tmp_path / "daily-900"
    (root / "delivery" / "art-001").mkdir(parents=True)
    (root / "delivery" / "art-001" / "delivery.md").write_text(delivery, encoding="utf-8")
    if pack_facts:
        (root / "material-packs").mkdir(parents=True, exist_ok=True)
        (root / "material-packs" / "art-001.json").write_text(
            json.dumps({"obtained_facts_by_source": {"src-a": list(pack_facts)}}, ensure_ascii=False),
            encoding="utf-8",
        )
    if hard:
        (root / "review" / "art-001").mkdir(parents=True, exist_ok=True)
        (root / "review" / "art-001" / "content-fidelity.json").write_text(
            json.dumps({"hard_information": list(hard)}, ensure_ascii=False), encoding="utf-8"
        )
    return root


def test_patterns_catch_the_two_008_categories():
    assert TIME_SPAN_RE.search("十几年过去")
    assert TIME_SPAN_RE.search("十五年来")
    assert AUDIENCE_ACTION_RE.search("台词还在被引用")
    assert AUDIENCE_ACTION_RE.search("盘到包浆")


def test_split_paragraphs_skips_headings_and_title():
    paragraphs = split_paragraphs(DELIVERY_GAPS)
    assert len(paragraphs) == 1  # 标题与 ## 小标题都不算段落
    assert "十几年过去" in paragraphs[0][1]
    assert paragraphs[0][0] > 1  # 段落号保留原文位置


def test_extract_assertions_tags_categories():
    found = extract_assertions(split_paragraphs(DELIVERY_GAPS))
    claims = {(item["category"], item["claim"]) for item in found}
    assert any(category == "time_span" and claim.startswith("十几年") for category, claim in claims)
    assert any(category == "audience_action" and "被引用" in claim for category, claim in claims)


def test_covered_assertions_are_not_flagged(tmp_path: Path):
    root = _write_run(
        tmp_path,
        DELIVERY_COVERED,
        pack_facts=[
            "十多年来，庞大的影迷群体把《让子弹飞》盘到包浆，他们对片中的台词金句如数家珍",
            "影片公映七天累计票房八千二百万左右，单日票房跌到第八名",
        ],
    )
    report = check_coverage(root, "art-001")
    assert report["status"] == "ok"
    assert report["errors"] == []
    assert report["uncovered"] == []


def test_008_regression_gaps_are_errors(tmp_path: Path):
    """两条 L2 major 的原样复现：账本为空时必须报 error。"""
    root = _write_run(tmp_path, DELIVERY_GAPS, pack_facts=["影片由姜文执导"])
    report = check_coverage(root, "art-001")
    assert report["status"] == "ok"
    assert any(item.startswith("assertion_not_in_ledger:time_span:") for item in report["errors"])
    assert any(item.startswith("assertion_not_in_ledger:audience_action:") for item in report["errors"])
    # 未覆盖项带段落定位，便于直接回改
    assert all(item["paragraph"] for item in report["uncovered"])


def test_specific_time_span_is_error_but_vague_span_is_warning(tmp_path: Path):
    """008 校准：给出具体跨度 = 硬事实（error）；「这些年」这类泛化 = warning。"""
    root = _write_run(
        tmp_path,
        "# 标题\n\n## 一\n\n十几年过去，《让子弹飞》的台词还在被引用。\n\n这三个词拼在一起，几乎就是这些年观众对姜文的全部怨言。\n",
        pack_facts=["影片由姜文执导"],
    )
    report = check_coverage(root, "art-001")
    severities = {(item["claim"], item["severity"]) for item in report["uncovered"]
                  if item["category"] == "time_span"}
    assert ("十几年过去", "error") in severities
    assert ("这些年", "warning") in severities


def test_number_and_quote_gaps_are_warnings_not_errors(tmp_path: Path):
    delivery = '# 标题\n\n## 一\n\n影片片长144分钟，有人说“这句话不在账本里”。\n'
    root = _write_run(tmp_path, delivery, pack_facts=["影片由姜文执导"])
    report = check_coverage(root, "art-001")
    assert report["errors"] == []
    assert any("number_fact" in item for item in report["warnings"])
    assert any("quote" in item for item in report["warnings"])


def test_reverse_direction_reports_orphan_ledger_items(tmp_path: Path):
    root = _write_run(tmp_path, DELIVERY_GAPS, pack_facts=["这条事实正文里根本没有提到过"])
    report = check_coverage(root, "art-001")
    assert report["orphan_ledger"] == [{"ref": "pack:src-a", "text": "这条事实正文里根本没有提到过"}]
    assert any(item.startswith("ledger_item_not_in_body:pack:src-a") for item in report["warnings"])


def test_ledger_reads_both_pack_and_fidelity(tmp_path: Path):
    root = _write_run(
        tmp_path,
        DELIVERY_GAPS,
        pack_facts=["材料包事实"],
        hard=[{"information_id": "i1", "text": "交付账本事实"}],
    )
    ledger = load_ledger(root, "art-001")
    assert {entry["ref"] for entry in ledger} == {"pack:src-a", "hard:i1"}


def test_missing_delivery_is_reported_not_raised(tmp_path: Path):
    report = check_coverage(tmp_path / "empty", "art-001")
    assert report["status"] == "no_delivery"
    assert report["errors"] == []


def test_cli_strict_exit_code_and_write(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    root = _write_run(tmp_path, DELIVERY_GAPS, pack_facts=["无补于事的条目"])
    assert main(["--run-root", str(root), "--aid", "art-001", "--strict", "--write"]) == 1
    out = capsys.readouterr().out
    assert "time_span" in out
    written = json.loads((root / "review" / "art-001" / "assertion-coverage.json").read_text(encoding="utf-8"))
    assert written["schema_version"] == "assertion-ledger-coverage-v1"
    assert written["publication_authorization"] == "not_authorized"


def test_cli_non_strict_returns_zero_even_with_errors(tmp_path: Path):
    root = _write_run(tmp_path, DELIVERY_GAPS)
    assert main(["--run-root", str(root), "--aid", "art-001"]) == 0


# ── 计数后缀归一（2026-09-20，daily-009 复盘） ──────────────────────────────
# 009 的 art-002 被新门禁判红 4 条 time_span，逐条回源后是两类：
#   形态差异：正文「1998年」 vs 账本英文「Based on the 1998 Dark Horse…」（该修）
#   真缺口：  正文「2006年 / 2007年」账本压根没有条目（该红，不能洗）
# 下面把两类都钉住：形态差异不再假红，真缺口仍然报 error。
DELIVERY_YEAR_CN = """# 标题

## 一节

影片改编自弗兰克·米勒与 Lynn Varley 1998年为 Dark Horse 创作的漫画。
"""

DELIVERY_YEAR_CN_ABSENT = """# 标题

## 一节

这部电影 1776年上映的说法没有依据。
"""


def test_counter_suffix_matches_bare_number_in_ledger(tmp_path: Path):
    """正文「1998年」⇄ 账本英文「1998」：形态差异不再假红。"""
    root = _write_run(tmp_path, DELIVERY_YEAR_CN,
                      pack_facts=["Based on the 1998 Dark Horse Comics limited series"])
    report = check_coverage(root, "art-001")
    assert report["errors"] == [], report["errors"]
    assert not [i for i in report["uncovered"] if i["claim"] == "1998年"]


def test_counter_suffix_does_not_match_a_different_year(tmp_path: Path):
    """归一不会把"账本真的没有"洗成通过：只给了 2011，1998年 仍报缺口。"""
    root = _write_run(tmp_path, DELIVERY_YEAR_CN,
                      pack_facts=["In April 2011, it was reported that two actors were in talks"])
    report = check_coverage(root, "art-001")
    assert any("1998年" in item for item in report["errors"]), report["errors"]


def test_counter_suffix_keeps_absolute_gap_red(tmp_path: Path):
    """真缺口保持 error 级（009 的 2006/2007 就属这一类）。"""
    root = _write_run(tmp_path, DELIVERY_YEAR_CN_ABSENT, pack_facts=["影片由同名漫画改编"])
    report = check_coverage(root, "art-001")
    assert any("1776年" in item for item in report["errors"]), report["errors"]


def test_counter_suffix_does_not_touch_relative_spans(tmp_path: Path):
    """文字跨度不归它管：「十九年前」仍需账本有条目。"""
    root = _write_run(
        tmp_path,
        """# 标题

## 一节

十九年前柏林放映时被嘘，这段旧事他至今还记得。
""",
        pack_facts=["影片 2006 年上映"],
    )
    report = check_coverage(root, "art-001")
    assert any("十九年前" in item for item in report["errors"] + report["warnings"]), report


def test_chinese_numeral_specific_spans_are_error(tmp_path: Path):
    """2026-09-21（daily-010/011 L2 复盘）：中文数字的具体跨度曾被静默降级为 warning。

    原正则只认阿拉伯数字与「十几/十多/数十/近X」，于是「七年后」这类**具体跨度**既不
    匹配、又被 time_span 的降级规则洗成 warning，而工具 note 与 run_gates 都声明时间
    跨度类阻断——规则与输出自相矛盾。这里钉住：具体跨度必须是 error。
    """
    root = _write_run(
        tmp_path,
        "# 标题\n\n## 一\n\n七年后，这部片又回到了大银幕。\n\n十年前它在柏林放过一次。\n",
        pack_facts=["影片 2019 年首映"],
    )
    report = check_coverage(root, "art-001")
    severities = {
        (item["claim"], item["severity"])
        for item in report["uncovered"]
        if item["category"] == "time_span"
    }
    assert any("七年后" in claim and sev == "error" for claim, sev in severities), severities
    assert any("十年前" in claim and sev == "error" for claim, sev in severities), severities
    assert report["errors"], "具体跨度未进 errors，等于没拦住"


def test_vague_chinese_spans_stay_warning(tmp_path: Path):
    """扩展正则不许误伤泛化表述：这些年/多年来/近年来仍是 warning（008 校准）。"""
    root = _write_run(
        tmp_path,
        "# 标题\n\n## 一\n\n这些年观众对他的怨言，几乎都集中在这三个词上。\n\n多年来一直如此。\n",
        pack_facts=["影片由姜文执导"],
    )
    report = check_coverage(root, "art-001")
    spans = [
        (item["claim"], item["severity"])
        for item in report["uncovered"]
        if item["category"] == "time_span"
    ]
    assert spans, "泛化跨度没被抽出来，测试前提不成立"
    assert all(sev == "warning" for _, sev in spans), spans
    error_text = "\n".join(str(item) for item in report["errors"])
    assert "这些年" not in error_text and "多年来" not in error_text, error_text


# ── 派生跨度即时入账（2026-09-21，daily-011 art-001「七年后」的坑） ──────────────


def test_apply_derived_spans_registers_and_clears_gap():
    """spec 声明了派生跨度 → 补进账本、标 derived=True、缺口清零。"""
    from article_group.assertion_ledger_coverage import apply_derived_spans

    body = "# 标题\n\n## 一\n\n七年后，这部片重回大银幕。\n"
    record = {"hard_information": [{"information_id": "i1", "text": "影片 2019 年首映"}]}
    gaps = apply_derived_spans(
        record,
        body,
        [
            {
                "text": "影片原版 2019 年首映，2026 年重映，前后相隔七年后重回大银幕",
                "body_locator": "p1",
                "source_refs": ["src-a"],
                "source_locators": ["来源: 首映年份"],
            }
        ],
    )
    assert gaps == []
    derived = [item for item in record["hard_information"] if item.get("derived")]
    assert len(derived) == 1
    assert derived[0]["information_id"] == "d1"
    assert derived[0]["independence_key"] == "derived-span-1"


def test_apply_derived_spans_reports_remaining_gap():
    """没声明 → 缺口如实报出来（引擎据此当场失败，而不是等 gates）。"""
    from article_group.assertion_ledger_coverage import apply_derived_spans

    body = "# 标题\n\n## 一\n\n七年后，这部片重回大银幕。\n"
    record = {"hard_information": [{"information_id": "i1", "text": "影片 2019 年首映"}]}
    gaps = apply_derived_spans(record, body, [])
    assert [gap["claim"] for gap in gaps] == ["七年后"]
    # body_locator 与账本同口径（标题不占号），另附原文块位置
    assert gaps[0]["body_locator"] == "p1"
    assert gaps[0]["source_position"].startswith("第")


def test_apply_derived_spans_avoids_id_collision():
    from article_group.assertion_ledger_coverage import apply_derived_spans

    record = {"hard_information": [{"information_id": "d1", "text": "已有一条 d1"}]}
    apply_derived_spans(
        record,
        "# 标题\n\n正文。\n",
        [{"text": "派生条目", "body_locator": "p1", "source_locators": ["来源: x"]}],
    )
    ids = [item["information_id"] for item in record["hard_information"]]
    assert len(ids) == len(set(ids)) == 2
    assert "d1" in ids and "d1d" in ids
