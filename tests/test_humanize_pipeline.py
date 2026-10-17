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
    parse_zhuque_report,
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
总而言之，说白了，这是一部好电影。

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
    assert "总而言之" not in polished
    assert "说到底" not in polished  # 坚决不引入“说到底”等二次AI翻案词
    assert "说白了" not in polished
    assert len(fixes) >= 3


def test_deterministic_polish_lieflat_whitelist_rules():
    raw_draft = """# 第二幕

第一段讲述了基础的情节发展。

听起来像一条功能描述，其实底下换掉了一样更根本的东西。
一句话总结：排片量直接跌了百分之五十。
制作团队完成了对渲染流程的优化。
目前由于技术较为落后，剧组无法按期交付，必须通过技术升级来实现突破，并且对其进行全面排查。"""

    polished, fixes = deterministic_polish(raw_draft)

    # 1. 段首零回指自动补齐代词
    assert "这听起来像一条功能描述" in polished
    # 2. 正文提示性冒号切除
    assert "一句话总结：" not in polished
    assert "排片量直接跌了百分之五十" in polished
    # 3. 动词名词化轻动词还原
    assert "优化了渲染流程" in polished
    # 4. 公文书面词口语化
    assert "比较落后" in polished
    assert "没法按期交付" in polished
    assert "靠技术升级来实现突破" in polished
    assert "对其做全面排查" in polished

    assert any("零回指" in f for f in fixes)
    assert any("空转提示性冒号" in f for f in fixes)
    assert any("恢复动词活力" in f for f in fixes)
    assert any("公文书面词口语化" in f for f in fixes)


def test_deterministic_polish_protects_dialogue_quotes():
    raw_draft = """# 第三幕

旁白评论道：这绝不是单纯的商业探索，而是全行业的一次豪赌。

程警官冷冷地说：“这不是意外，而是故意谋杀！”

> 引用文献指出：这并非巧合，而是历史发展的必然规律。"""

    polished, fixes = deterministic_polish(raw_draft)

    # 1. 「不是…而是…」改写已于 2026-10-16 停用（E1 实测破坏语法并制造乱标点），
    #    旁白评论保持原样：语法正确优先于对仗形态。
    assert "这绝不是单纯的商业探索，而是全行业的一次豪赌。" in polished
    assert "这并非单纯的商业探索" not in polished
    assert any("跳过对仗改写" in f for f in fixes)

    # 2. 引号内的人物对白必须受到保护，禁止篡改
    assert "“这不是意外，而是故意谋杀！”" in polished

    # 3. 引用块受到保护，禁止篡改
    assert "> 引用文献指出：这并非巧合，而是历史发展的必然规律。" in polished


def test_deterministic_polish_does_not_break_syntax_e1_regressions():
    """E1 复盘回归：这四句曾被阶段1 改成语病，必须原样保留。

    证据：runs/2026-10-16-model-ablation-E1/ANALYSIS.md —— 12/15 稿出现乱标点，
    ``。。`` / ``。，`` 等共 22 处；语料样例即下列句子。
    """
    from article_group.humanize_pipeline import _malformed_punct_count

    cases = [
        "而他却不是走向沉默，而是走向了荒漠。",
        "真正的底层绝望，从来不是没钱买包，而是连命都买不起。",
        "这剧封神的地方从来不是贩毒的手法有多高明，而是它把“代价”两个字，一笔一划写进你的骨头里。",
        "你只需要回答一个问题：当现实生活把一笔账拍在你面前，你是乖乖掏钱，还是掀桌子？",
    ]
    body = "\n\n".join(cases)
    polished, _fixes = deterministic_polish(body)

    for sentence in cases:
        assert sentence in polished, f"被改坏：{sentence}"
    assert "这并非" not in polished and "核心在于" not in polished
    assert _malformed_punct_count(polished) == 0
    assert _malformed_punct_count(body) == 0


def test_deterministic_polish_still_cuts_real_signposts():
    """收紧后的提示词规则不得退化成不做事：句界起头的空转提示词仍要切除。"""
    draft = "第一段讲了情节。\n\n一句话总结：排片量直接跌了百分之五十。\n"
    polished, _fixes = deterministic_polish(draft)
    assert "一句话总结：" not in polished
    assert "排片量直接跌了百分之五十" in polished


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


# ---------------------------------------------------------------------------
# 朱雀兜底：报告解析 + 「读不到结果」≠「被判 AI」（2026-10-15 假失败事故回归）
# ---------------------------------------------------------------------------

REAL_REPORT_SHAPE = """# 腾讯朱雀 AI 文本生成检测报告
- **检测时间**：2026-10-15 15:20:00
- **文本总字数**：4702 字
- **AI 生成综合置信度**：`34.36%` (极低 (人工创作概率极高))
- **今日剩余检测额度**：3 次

## 1. 结构化统计
| 风险等级 | 对应特征 | 片段数量 | 字数统计 |
| :--- | :--- | :--- | :--- |
| 🔴 高危疑似 AI | 句式平滑、高频模板、AI 特征明显 | 0 段 | 0 字 |
| 🟡 中度可疑 | 句式略显僵硬或轻度改写 | 2 段 | 3229 字 |
| 🟢 人工自然 | 语言突发度高、符合真人行文习惯 | 1 段 | 1470 字 |

## 3. 🟡 中度可疑片段清单（建议适当润色）
**片段 1** (1600 字):
> 第一段可疑文字。

**片段 2** (1629 字):
> 第二段可疑文字。
"""


def test_parse_zhuque_report_reads_real_report_shape():
    parsed = parse_zhuque_report(REAL_REPORT_SHAPE)
    assert parsed is not None
    assert parsed["softmax_confidence"] == pytest.approx(0.3436)
    assert parsed["labels_ratio"]["0"] == pytest.approx(1 / 3)
    assert parsed["labels_ratio"]["1"] == 0.0
    assert parsed["labels_ratio"]["2"] == pytest.approx(2 / 3)
    assert [s["label"] for s in parsed["splits"]] == ["2", "2"]
    assert parsed["splits"][0]["text"] == "第一段可疑文字。"
    assert parsed["quota_remaining"] == 3


def test_parse_zhuque_report_returns_none_when_report_absent():
    # 只有进度输出、没有报告正文（2026-10-15 假失败的现场就是这种 stdout）
    assert parse_zhuque_report("[*] 正在加载朱雀大模型检测系统...\n[!] 页面提示错误: 请求过于频繁") is None
    assert parse_zhuque_report("") is None


def test_evaluate_zhuque_result_unavailable_is_not_a_verdict():
    for raw in (
        {"error": "web_cli_report_unreadable", "unavailable": True},
        {"error": "all_zhuque_methods_failed", "unavailable": True},
        {"error": "all_zhuque_methods_failed"},
    ):
        ev = evaluate_zhuque_result(raw)
        assert ev["available"] is False
        assert ev["is_all_green"] is None
        assert ev["ai_ratio"] is None and ev["human_ratio"] is None


def test_unavailable_diagnostics_are_preserved():
    ev = evaluate_zhuque_result({
        "error": "web_cli_report_unreadable",
        "unavailable": True,
        "diagnostics": {"returncode": 1, "stderr_tail": "TimeoutError: 检测超时"},
    })
    assert ev["available"] is False
    assert ev["diagnostics"]["returncode"] == 1
    assert "TimeoutError" in ev["diagnostics"]["stderr_tail"]


def _fake_local_pass(text, evidence=None, **kwargs):
    return {
        "passed": True,
        "anti_ai_score": 10.0,
        "evidence_errors": [],
        "lieflat_advisories": None,
    }


def test_zhuque_unavailable_does_not_flip_status(tmp_path, monkeypatch):
    import article_group.humanize_pipeline as hp

    draft = tmp_path / "draft.md"
    draft.write_text("老周把车停在洗车行门口。" * 40, encoding="utf-8")

    monkeypatch.setattr(hp, "check_local_gates", _fake_local_pass)
    monkeypatch.setattr(
        hp, "call_zhuque_check",
        lambda *a, **k: {"error": "web_cli_report_unreadable", "unavailable": True},
    )
    res = hp.run_humanize_pipeline(str(draft), run_zhuque=True, max_zhuque_rounds=1)

    # 本地门禁通过 + 朱雀读不到 → 独立状态，既不是 NEEDS_CHANGES 也不是 PASS（2026-10-15 用户授权）
    assert res["status"] == "PASS_LOCAL_ONLY"
    assert res["status_reason"] == "zhuque_unavailable"
    assert res["zhuque_passed"] is None
    assert res["zhuque_available"] is False

    last = res["audit_trail"][-1]
    assert last["step"] == "zhuque_round_1"
    assert last["available"] is False
    assert last["reason"] == "web_cli_report_unreadable"


def test_zhuque_judged_not_green_still_blocks(tmp_path, monkeypatch):
    import article_group.humanize_pipeline as hp

    draft = tmp_path / "draft.md"
    draft.write_text("老周把车停在洗车行门口。" * 40, encoding="utf-8")
    judged = {
        "softmax_confidence": 0.3436,
        "labels_ratio": {"0": 1 / 3, "1": 0.0, "2": 2 / 3},
        "splits": [],
    }
    monkeypatch.setattr(hp, "check_local_gates", _fake_local_pass)
    monkeypatch.setattr(hp, "call_zhuque_check", lambda *a, **k: judged)
    res = hp.run_humanize_pipeline(str(draft), run_zhuque=True, max_zhuque_rounds=1)

    assert res["zhuque_available"] is True
    assert res["zhuque_passed"] is False
    assert res["status"] == "NEEDS_CHANGES"
    assert res["status_reason"] == "zhuque_judged_not_green"
    # 明确只差「人工特征≥70%」这一条：读数是真读数，不是基础设施故障
    assert res["zhuque_conditions"]["human_ratio_at_least_0_70"] is False
    assert res["zhuque_conditions"]["ai_ratio_is_zero"] is True
    assert res["zhuque_conditions"]["confidence_below_0_50"] is True


def test_pipeline_repair_round_does_not_touch_h1(tmp_path, monkeypatch):
    """整条流水线的产物不变式：朱雀判不绿 → 靶向修复 → H1 逐字不变（L2 B2-L2-01）。"""
    import article_group.humanize_pipeline as hp

    draft = tmp_path / "draft.md"
    body = "老周把车停在洗车行门口，手里攥着那张单子。" * 20
    draft.write_text(f"# {TITLE_LINE}\n\n{body}\n", encoding="utf-8")

    judged = {
        "softmax_confidence": 0.3436,
        "labels_ratio": {"0": 1 / 3, "1": 0.0, "2": 2 / 3},
        "splits": [{"label": "2", "text": f"# {TITLE_LINE}"}],
    }
    monkeypatch.setattr(hp, "check_local_gates", _fake_local_pass)
    monkeypatch.setattr(hp, "call_zhuque_check", lambda *a, **k: judged)
    out = tmp_path / "out.md"
    # 必须 max_zhuque_rounds>=2：humanize_pipeline 的修复只在 `round_idx < max` 时发生
    # （L2 增量复核 L2D-01——此前写 1，本用例的修复路径调用 0 次，是恒真断言）。
    res = hp.run_humanize_pipeline(
        str(draft), output_path=str(out), run_zhuque=True, max_zhuque_rounds=2
    )

    assert res["status"] == "NEEDS_CHANGES"          # 真读数判不绿 → 仍然阻断
    assert res["zhuque_available"] is True
    steps = [s["step"] for s in res["audit_trail"]]
    assert "surgical_repair_round_1" in steps, steps  # 修复路径确实被走到（非恒真）
    assert out.read_text(encoding="utf-8").split("\n", 1)[0] == f"# {TITLE_LINE}"


def test_evaluate_zhuque_result_rejects_out_of_domain_numbers():
    """L2 增量复核 L2D-04：域外数值不得产出「假全绿」（conf=-1 曾是 fail-open）。"""
    import article_group.humanize_pipeline as hp

    cases = [
        {"softmax_confidence": -1.0, "labels_ratio": {"0": 0.9, "1": 0.0, "2": 0.1}},
        {"softmax_confidence": float("nan"), "labels_ratio": {"0": 0.9, "1": 0.0, "2": 0.1}},
        {"softmax_confidence": float("inf"), "labels_ratio": {"0": 0.9, "1": 0.0, "2": 0.1}},
        {"softmax_confidence": 1.5, "labels_ratio": {"0": 0.9, "1": 0.0, "2": 0.1}},
        {"softmax_confidence": 0.1, "labels_ratio": {"0": 0.9, "1": -0.5, "2": 0.1}},
        {"softmax_confidence": 0.1, "labels_ratio": {"0": 1.7, "1": 0.0, "2": 0.1}},
        {"softmax_confidence": True, "labels_ratio": {"0": 0.9, "1": 0.0, "2": 0.1}},
    ]
    for raw in cases:
        got = hp.evaluate_zhuque_result(dict(raw))
        assert got["available"] is False, raw
        assert got["is_all_green"] is None, raw          # 绝不出现 True
        assert got["error"] == "zhuque_shape_unrecognized", raw
        assert got["diagnostics"]["confidence_like_keys_present"] is True, raw

    ok = hp.evaluate_zhuque_result(
        {"softmax_confidence": 0.34, "labels_ratio": {"0": 0.33, "1": 0.0, "2": 0.67}}
    )
    assert ok["available"] is True and ok["is_all_green"] is False  # 正控制：域内正常读数


def test_evaluate_zhuque_result_survives_hostile_splits():
    """L2 增量复核 L2D-03：splits 形状不可预期时不得抛 AttributeError。"""
    import article_group.humanize_pipeline as hp

    base = {"softmax_confidence": 0.34, "labels_ratio": {"0": 0.33, "1": 0.0, "2": 0.67}}
    for hostile in ["not-a-list", 7, None, [None, 3, "x"], {"a": 1}, [{"label": "2"}], [{"text": "x"}]]:
        got = hp.evaluate_zhuque_result({**base, "splits": hostile})
        assert got["available"] is True, hostile
        assert got["danger_sentences"] == [], hostile

    nested = hp.evaluate_zhuque_result({**base, "data": {"splits": [{"label": "1", "text": "句"}]}})
    assert [d["label"] for d in nested["danger_sentences"]] == ["1"]


def test_call_zhuque_check_uses_output_file_and_wide_timeout(monkeypatch):
    """兜底必须把报告落文件再解析，且超时放宽到 240s。"""
    import article_group.humanize_pipeline as hp

    captured: dict = {}

    class FakeProc:
        def __init__(self, returncode, stdout):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def fake_run(cmd, **kwargs):
        if "--output" in cmd:
            captured["cmd"] = cmd
            captured["timeout"] = kwargs.get("timeout")
            Path(cmd[cmd.index("--output") + 1]).write_text(REAL_REPORT_SHAPE, encoding="utf-8")
            return FakeProc(0, "[*] 进度输出，没有报告正文\n")
        return FakeProc(1, "")  # API 通道失败 → 走兜底

    monkeypatch.setattr(hp.os.path, "exists", lambda p: True)
    monkeypatch.setattr(hp.subprocess, "run", fake_run)
    res = hp.call_zhuque_check("正文" * 300)

    assert "--output" in captured["cmd"]
    # 页面轮询预算交给 CLI（240s），外层 subprocess 必须更大（300s）以便 CLI 先自己失败
    assert "--wait-timeout" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--wait-timeout") + 1] == "240.0"
    assert captured["timeout"] == 300
    assert res["softmax_confidence"] == pytest.approx(0.3436)
    assert res["source"] == "web_cli"
    assert len(res["splits"]) == 2


# ---------------------------------------------------------------------------
# L2 复核 B2-L2-01 / B2-L2-02 的回归（2026-10-15）：
#   ① 形状不符的返回体 = 不可用，不是「被判 AI」；
#   ② 靶向修复不得把标题/结构行当高危句改写。
# ---------------------------------------------------------------------------

TITLE_LINE = "同一艘太平轮、近千条命：台北蔡康永第一排挥绿棒，上海周家卖血33年还债"
REPORT_TITLE_AS_SEGMENT = REAL_REPORT_SHAPE.replace("第一段可疑文字。", f"# {TITLE_LINE}")


def test_evaluate_zhuque_result_unrecognized_shape_is_unavailable():
    """缺键/类型不符 → available False（旧行为是 conf=1.0 + is_all_green False）。"""
    for raw in (
        {},
        {"foo": "bar"},
        {"softmax_confidence": 0.2},  # 缺 labels_ratio
        {"labels_ratio": {"0": 0.9, "1": 0.0, "2": 0.1}},  # 缺 softmax_confidence
        {"softmax_confidence": "0.2", "labels_ratio": {"0": 0.9, "1": 0.0, "2": 0.1}},
        {"softmax_confidence": 0.2, "labels_ratio": {"0": 0.9, "2": 0.1}},  # 缺 "1"
        {"softmax_confidence": 0.2, "labels_ratio": ["0", "1", "2"]},
        {"softmax_confidence": True, "labels_ratio": {"0": 0.9, "1": 0.0, "2": 0.1}},
    ):
        ev = evaluate_zhuque_result(raw)
        assert ev["available"] is False, raw
        assert ev["is_all_green"] is None, raw
        assert ev["error"] == "zhuque_shape_unrecognized", raw
        assert "received_keys" in ev["diagnostics"], raw

    # 正控制：形状完整仍然照旧判定
    ok = evaluate_zhuque_result(
        {"softmax_confidence": 0.22, "labels_ratio": {"0": 0.85, "1": 0.0, "2": 0.15}}
    )
    assert ok["available"] is True and ok["is_all_green"] is True


def test_surgical_repair_skips_headings_and_protects_title_line():
    """标题（带 # 与不带 # 两种口径）都不得被改写。"""
    body = "天塌下来，先保自己不受损；死道友，不死贫道。"
    text = f"# {TITLE_LINE}\n\n{body}\n"

    # ① 报告里带 markdown 标记的标题首行 → 直接按结构行跳过
    repaired, logs = perform_surgical_repair(
        text, [{"label": "2", "text": f"# {TITLE_LINE}"}]
    )
    assert repaired == text
    assert any("跳过非正文目标" in ln for ln in logs)

    # ② 报告里不带 # 的标题文本（会命中标题内部）→ 由标题行不变量拦截
    repaired2, logs2 = perform_surgical_repair(text, [{"label": "2", "text": TITLE_LINE}])
    assert repaired2.split("\n", 1)[0] == f"# {TITLE_LINE}"
    assert TITLE_LINE in repaired2
    assert any("跳过会改动标题行" in ln for ln in logs2)

    # ③ 正文句仍然照常被修复（防止兜底改成「什么都不修」）
    repaired3, logs3 = perform_surgical_repair(text, [{"label": "2", "text": body}])
    assert repaired3 != text and logs3 and "靶向拆解" in logs3[0]
    assert repaired3.split("\n", 1)[0] == f"# {TITLE_LINE}"


def test_real_report_danger_segment_never_rewrites_draft_title():
    """真实报告形状 + 真实标题：整条链路（解析→评估→修复）不得动标题。"""
    parsed = parse_zhuque_report(REPORT_TITLE_AS_SEGMENT)
    assert parsed is not None
    ev = evaluate_zhuque_result(parsed)
    assert ev["available"] is True
    assert [d["text"] for d in ev["danger_sentences"]][0] == f"# {TITLE_LINE}"

    body = "正文第一句，后面还有内容。"
    draft = f"# {TITLE_LINE}\n\n{body}\n"
    repaired, logs = perform_surgical_repair(draft, ev["danger_sentences"])
    assert repaired.split("\n", 1)[0] == f"# {TITLE_LINE}"
    assert "。" not in repaired.split("\n", 1)[0]
    assert not any("靶向拆解" in ln for ln in logs)

    # 反向对照：正文句确实会被修复（证明上面的「没动」不是空转）
    repaired2, logs2 = perform_surgical_repair(draft, [{"label": "2", "text": body}])
    assert repaired2 != draft
    assert any("靶向拆解" in ln for ln in logs2)
    assert repaired2.split("\n", 1)[0] == f"# {TITLE_LINE}"


# ---------------------------------------------------------------------------
# 2026-10-15 用户授权：① skill 侧等待预算可配置（软耦合）；② 三态交付判定
# ---------------------------------------------------------------------------


def test_call_zhuque_check_soft_degrades_when_cli_rejects_wait_timeout(monkeypatch):
    """旧版 skill CLI 不认识 --wait-timeout 时，退回不带该参数的调用（宁可为读不到，不可伪读数）。"""
    import article_group.humanize_pipeline as hp

    seen: list[list[str]] = []

    class FakeProc:
        def __init__(self, returncode, stdout, stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, **kwargs):
        seen.append(list(cmd))
        if "--output" not in cmd:
            return FakeProc(1, "")
        if "--wait-timeout" in cmd:
            return FakeProc(2, "", "zhuque_cli.py: error: unrecognized arguments: --wait-timeout")
        Path(cmd[cmd.index("--output") + 1]).write_text(REAL_REPORT_SHAPE, encoding="utf-8")
        return FakeProc(0, "")

    monkeypatch.setattr(hp.os.path, "exists", lambda p: True)
    monkeypatch.setattr(hp.subprocess, "run", fake_run)
    res = hp.call_zhuque_check("正文" * 300)

    assert len(seen) == 3, seen                       # API → 带 flag → 退化为不带 flag
    assert "--wait-timeout" in seen[1] and "--wait-timeout" not in seen[2]
    assert res["softmax_confidence"] == pytest.approx(0.3436)
    assert res["source"] == "web_cli"


def test_call_zhuque_check_unavailable_diagnostics_carry_wait_timeout(monkeypatch):
    """读不到读数时必须把预算与退化标记带进 diagnostics，便于事后归因。"""
    import article_group.humanize_pipeline as hp

    class FakeProc:
        def __init__(self):
            self.returncode = 1
            self.stdout = "[*] 仍在等待检测结果（已等待 240s / 上限 240s）..."
            self.stderr = "TimeoutError: 检测超时（已等待 240s，上限 240s）"

    # 只让 CLI 路径「存在」：report.md 必须真的不存在，才能测「读不到」
    monkeypatch.setattr(
        hp.os.path, "exists",
        lambda p: "zhuque_cli" in str(p) or ".venv-tools" in str(p),
    )
    monkeypatch.setattr(hp.subprocess, "run", lambda cmd, **k: FakeProc())
    res = hp.call_zhuque_check("正文" * 300)

    assert res["unavailable"] is True
    assert res["error"] == "web_cli_report_unreadable"
    assert res["diagnostics"]["wait_timeout"] == hp.ZHUQUE_WEB_WAIT_TIMEOUT == 240.0
    assert res["diagnostics"]["retried_without_wait_timeout"] is False
    assert hp.ZHUQUE_WEB_SUBPROCESS_TIMEOUT > hp.ZHUQUE_WEB_WAIT_TIMEOUT


def test_run_zhuque_false_is_plain_pass(tmp_path, monkeypatch):
    import article_group.humanize_pipeline as hp

    draft = tmp_path / "draft.md"
    draft.write_text("老周把车停在洗车行门口。" * 40, encoding="utf-8")
    monkeypatch.setattr(hp, "check_local_gates", _fake_local_pass)
    res = hp.run_humanize_pipeline(str(draft), run_zhuque=False)

    assert res["status"] == "PASS"
    assert res["status_reason"] == "all_requested_gates_passed"


def test_zhuque_green_is_plain_pass(tmp_path, monkeypatch):
    import article_group.humanize_pipeline as hp

    draft = tmp_path / "draft.md"
    draft.write_text("老周把车停在洗车行门口。" * 40, encoding="utf-8")
    green = {
        "softmax_confidence": 0.34,
        "labels_ratio": {"0": 0.8, "1": 0.0, "2": 0.2},
        "splits": [],
    }
    monkeypatch.setattr(hp, "check_local_gates", _fake_local_pass)
    monkeypatch.setattr(hp, "call_zhuque_check", lambda *a, **k: green)
    res = hp.run_humanize_pipeline(str(draft), run_zhuque=True, max_zhuque_rounds=1)

    assert res["status"] == "PASS"
    assert res["status_reason"] == "all_requested_gates_passed"
    assert res["zhuque_available"] is True


def test_local_gate_failure_reason(tmp_path, monkeypatch):
    """本地门禁没过 → NEEDS_CHANGES，原因是本地，而不是朱雀。"""
    import article_group.humanize_pipeline as hp

    draft = tmp_path / "draft.md"
    draft.write_text("老周把车停在洗车行门口。" * 40, encoding="utf-8")

    def fake_fail(text, evidence=None, **kwargs):
        return {"passed": False, "anti_ai_score": 99.0, "evidence_errors": [], "lieflat_advisories": None}

    monkeypatch.setattr(hp, "check_local_gates", fake_fail)
    res = hp.run_humanize_pipeline(str(draft), run_zhuque=True, max_zhuque_rounds=1)

    assert res["status"] == "NEEDS_CHANGES"
    assert res["status_reason"] == "local_gates_failed"
    # 2026-10-16：本地门禁未过时朱雀被跳过，必须显式留痕，不得静默（否则
    # audit_trail 里查不到任何朱雀记录，容易被读成「朱雀已全绿」）。
    assert res["zhuque_skipped_reason"] == "local_gates_failed"
    assert res["zhuque_available"] is False
    assert any(s.get("step") == "zhuque_skipped" for s in res["audit_trail"])


def test_exit_code_for_status():
    import article_group.humanize_pipeline as hp

    assert hp.exit_code_for_status("PASS") == 0
    assert hp.exit_code_for_status("PASS_LOCAL_ONLY") == 0
    assert hp.exit_code_for_status("NEEDS_CHANGES") == 1
    assert hp.exit_code_for_status("SOMETHING_ELSE") == 1


def test_call_zhuque_check_does_not_retry_on_unrelated_rc2(monkeypatch):
    """软退化必须认 stderr（`unrecognized arguments`），不能只认返回码 2。

    L2 第十轮 coverage_gap R10-B3：把守卫弱化成「只看 rc==2」在行为上可观测
    （弱化体=2 次调用且 retried=True，正确体=1 次且 retried=False），此前无用例钉住。
    """
    import article_group.humanize_pipeline as hp

    seen: list[list[str]] = []

    class FakeProc:
        def __init__(self, returncode, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, **kwargs):
        seen.append(list(cmd))
        if "--output" not in cmd:
            return FakeProc(1, "")                      # API 通道失败 → 走兜底
        return FakeProc(2, "", "zhuque_cli.py: error: some other problem")

    monkeypatch.setattr(
        hp.os.path, "exists",
        lambda p: any(k in str(p) for k in ("zhuque_cli", ".venv-tools", "zhuque_check.py")),
    )
    monkeypatch.setattr(hp.subprocess, "run", fake_run)
    res = hp.call_zhuque_check("正文" * 300)

    assert len(seen) == 2, seen                        # API 1 次 + 兜底 1 次，不因 rc=2 盲目重试
    assert res["unavailable"] is True
    assert res["diagnostics"]["retried_without_wait_timeout"] is False
    assert "softmax_confidence" not in res             # 绝不伪造读数
