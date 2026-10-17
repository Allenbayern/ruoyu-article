"""tests for prompt_assembler and DNA_RHYTHM_STANDARD integration (2026-10-14 统一)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from article_group.dna_engine import DNA_RHYTHM_STANDARD, DnaRhythmStandard, audit_draft_dna
from article_group.prompt_assembler import assemble_writer_prompt


def test_dna_rhythm_standard_immutable_and_synced():
    """验证 DNA_RHYTHM_STANDARD 常量字段与口径完整性（目标与硬线双轨）。"""
    assert isinstance(DNA_RHYTHM_STANDARD, DnaRhythmStandard)

    # 1. 写作目标
    assert DNA_RHYTHM_STANDARD.target_para_median_min == 45.0
    assert DNA_RHYTHM_STANDARD.target_para_median_max == 65.0
    assert DNA_RHYTHM_STANDARD.target_para_stdev_min == 25.0
    assert DNA_RHYTHM_STANDARD.target_immersive_len_min == 80
    assert DNA_RHYTHM_STANDARD.target_immersive_len_max == 170
    assert DNA_RHYTHM_STANDARD.target_immersive_paras_min == 4
    assert DNA_RHYTHM_STANDARD.target_short_para_len_max == 35
    assert DNA_RHYTHM_STANDARD.target_short_para_pct_min == 20.0
    assert DNA_RHYTHM_STANDARD.target_short_para_pct_max == 45.0
    assert DNA_RHYTHM_STANDARD.target_cjk_min == 2000
    assert DNA_RHYTHM_STANDARD.target_cjk_max == 2700

    # 2. 门禁硬线
    assert DNA_RHYTHM_STANDARD.gate_para_median_min == 37.0
    assert DNA_RHYTHM_STANDARD.gate_para_median_max == 65.0
    assert DNA_RHYTHM_STANDARD.gate_para_stdev_min == 25.0
    assert DNA_RHYTHM_STANDARD.gate_immersive_len_min == 80
    assert DNA_RHYTHM_STANDARD.gate_immersive_len_max == 170
    assert DNA_RHYTHM_STANDARD.gate_immersive_paras_min == 4
    assert DNA_RHYTHM_STANDARD.gate_short_para_len_max == 35
    assert DNA_RHYTHM_STANDARD.gate_short_para_pct_min == 15.0
    assert DNA_RHYTHM_STANDARD.gate_short_para_pct_max == 50.0
    assert DNA_RHYTHM_STANDARD.gate_wall_para_len_max == 205
    assert DNA_RHYTHM_STANDARD.gate_wall_paras_max == 0
    assert DNA_RHYTHM_STANDARD.gate_cjk_min == 1500

    # 字典转换结构（提示词走目标，rhythm_standard 走硬线）
    prompt_dict = DNA_RHYTHM_STANDARD.to_prompt_assembler_dict()
    assert prompt_dict["para_median_target"] == "45~65字"
    assert prompt_dict["para_stdev_min"] == 25.0
    assert prompt_dict["immersive_paras_min"] == 4
    assert prompt_dict["wall_paras_max"] == 0
    assert prompt_dict["short_paras_pct_range"] == "20%~45%"
    assert prompt_dict["cjk_chars_range"] == "2000~2700字"

    rhythm_dict = DNA_RHYTHM_STANDARD.to_rhythm_standard_dict()
    assert rhythm_dict["para_median_range"] == [37.0, 65.0]
    assert rhythm_dict["para_median_target_range"] == [45.0, 65.0]
    assert rhythm_dict["para_stdev_min"] == 25.0
    assert rhythm_dict["short_paras_le_35_pct_range"] == [15.0, 50.0]
    assert rhythm_dict["short_paras_pct_target_range"] == [20.0, 45.0]
    assert rhythm_dict["cjk_hard_min"] == 1500


def test_prompt_assembler_formats_from_dna_rhythm_standard(tmp_path: Path):
    """验证 prompt_assembler 输出的 System Prompt 与字典无缝继承 DNA_RHYTHM_STANDARD。"""
    run_dir = tmp_path / "run-test"
    run_dir.mkdir()

    (run_dir / "pilot-manifest.json").write_text(json.dumps({
        "run_id": "test-prompt-001",
        "topic_label": "绝命毒师深度拉片",
    }, ensure_ascii=False), encoding="utf-8")

    (run_dir / "title-pack.json").write_text(json.dumps({
        "selected_title": "老白算平绝命账本的那一夜",
        "work": "绝命毒师",
        "killer_stance": "算透中年危机破产账本",
    }, ensure_ascii=False), encoding="utf-8")

    (run_dir / "evidence-pack.json").write_text(json.dumps({
        "work": "绝命毒师",
        "core_claims": [
            {"claim_id": "c1", "assertion": "老白不仅为家人，更为了权力尊严", "support": "台词证明"}
        ],
        "sensory_anchors": [
            {"anchor_id": "a1", "name": "洗车行沾湿的旧抹布", "function": "折射社会地位反差"}
        ],
        "verified_facts": [
            {"fact": "第一季老白查出肺癌晚期", "source_id": "src-bb-s1"}
        ],
    }, ensure_ascii=False), encoding="utf-8")

    res = assemble_writer_prompt(run_dir, author="editorial_planner", save_evidence=True)

    # 1. 验证 dna_rhythm_standard 字典来源于常量
    assert res["dna_rhythm_standard"] == DNA_RHYTHM_STANDARD.to_prompt_assembler_dict()

    # 2. 验证 system prompt 包含常量格式化文字
    sys_prompt = res["system_prompt"]
    assert "45 ~ 65 字" in sys_prompt
    assert "Standard Deviation ≥ 25.0" in sys_prompt
    assert "≥ 4 个 80 ~ 170 字" in sys_prompt
    assert "20% ~ 45%" in sys_prompt
    assert "超过 205 字的拥挤死墙段落数必须为 0" in sys_prompt
    assert "2000 ~ 2700 字" in sys_prompt
    assert "≥ 1500 字" in sys_prompt

    # 3. 验证落盘物料存在
    review_dir = run_dir / "review"
    assert (review_dir / "writer-prompt.json").is_file()
    assert (review_dir / "writer-prompt.md").is_file()


def test_prompt_assembler_handles_empty_packs_gracefully(tmp_path: Path):
    """验证空物料目录下的容错装配。"""
    run_dir = tmp_path / "run-empty"
    run_dir.mkdir()

    res = assemble_writer_prompt(run_dir, save_evidence=False)
    assert res["title"] == "影视深度长文"
    assert res["dna_rhythm_standard"] == DNA_RHYTHM_STANDARD.to_prompt_assembler_dict()
    assert "45 ~ 65 字" in res["system_prompt"]


def test_audit_draft_dna_new_thresholds_pass_and_advisory(tmp_path: Path):
    """验证新阈值门禁：合格稿件通过、<1500 硬阻断、>2700 给出 advisory 而非 violation。"""
    p_imm = "这是一个关于现实利益算盘与人性博弈的沉浸叙事大段落，深度拉片分析影视作品中的微观道具与阶层撕裂感，通过精准的动作与心理机制推进情节发展，让读者切实感受到普通人在名利场中的无力与挣扎。"  # 96字
    p_mid = "镜头一转，现实的残酷再次逼近每个当事人，大家都在为生存底线付出代价，名利场的账本早已算不平了，谁也逃不开。"  # 54字
    p_short = "老实人彻底疯了。"  # 9字

    # 1. 2056 字标准稿件（应通过）
    good_paras = (
        [p_imm] * 14  # 14 * 96
        + [p_mid] * 16  # 16 * 54
        + [p_short] * 10  # 10 * 9
    )
    draft_file = tmp_path / "good_draft.md"
    draft_file.write_text("# 深度剖析\n\n" + "\n\n".join(good_paras), encoding="utf-8")

    report = audit_draft_dna(draft_file)
    assert report["ok"] is True
    assert report["passed"] is True
    assert len(report["violations"]) == 0
    assert report["immersive_para_count"] >= 4
    assert report["wall_para_count"] == 0
    assert 20.0 <= report["short_para_pct"] <= 45.0
    assert 45.0 <= report["para_median"] <= 65.0
    assert report["para_stdev"] >= 25.0

    # 2. 短稿件（<1500 字，应硬阻断）
    short_file = tmp_path / "short_draft.md"
    short_file.write_text("# 深度短稿\n\n" + "\n\n".join(good_paras[:10]), encoding="utf-8")
    short_report = audit_draft_dna(short_file)
    assert short_report["passed"] is False
    assert any("正文字数不足深水区底线" in v for v in short_report["violations"])

    # 3. 超长稿件（>2800 字，根据 2026-10-14 裁决不应硬阻断，只应出 advisory 提醒）
    long_file = tmp_path / "long_draft.md"
    long_file.write_text("# 深度长稿\n\n" + "\n\n".join(good_paras * 2), encoding="utf-8")
    long_report = audit_draft_dna(long_file)
    assert long_report["passed"] is True
    assert any("字数偏离写作目标区间" in a for a in long_report.get("advisories", []))


def test_audit_draft_dna_boundary_cases(tmp_path: Path):
    """用常量构造边界用例：中位数 36 FAIL / 37 PASS(带advisory)；短段 51% FAIL / 48% PASS(带advisory)。"""
    p_imm = "这是一个关于现实利益算盘与人性博弈的沉浸叙事大段落，深度拉片分析影视作品中的微观道具与阶层撕裂感，通过精准的动作与心理机制推进情节发展，让读者切实感受到普通人在名利场中的无力与挣扎。"  # 96字 (>=80, <=170)
    p_short = "老实人彻底被逼急了。"  # 10字 (<=35)
    p_36 = "测" * 36  # 36字 (>35)
    p_37 = "测" * 37  # 37字 (>35)
    p_50 = "现实的残酷再次逼近每个当事人，大家都在为生存底线付出代价，名利场的账本早已算不平了。"  # 43字

    # --- 边界 1: 中位数 36 判 FAIL ---
    # 40 段: 8段短(10), 16段(36), 6段(43), 10段(96)
    # 中位数恰为 36.0 (< gate_para_median_min 37.0)
    paras_36 = [p_short] * 8 + [p_36] * 16 + [p_50] * 6 + [p_imm] * 10
    f_36 = tmp_path / "median_36.md"
    f_36.write_text("# 标题\n\n" + "\n\n".join(paras_36), encoding="utf-8")
    r36 = audit_draft_dna(f_36)
    assert r36["passed"] is False
    assert r36["para_median"] == 36.0
    assert any("中位数仅 36.0 字" in v and ">= 37 字" in v for v in r36["violations"])

    # --- 边界 2: 中位数 37 判 PASS（带 advisory） ---
    # 40 段: 8段短(10), 16段(37), 6段(43), 10段(96)
    # 中位数恰为 37.0 (>= gate_para_median_min 37.0, 但 < target 45.0)
    paras_37 = [p_short] * 8 + [p_37] * 16 + [p_50] * 6 + [p_imm] * 10
    f_37 = tmp_path / "median_37.md"
    f_37.write_text("# 标题\n\n" + "\n\n".join(paras_37), encoding="utf-8")
    r37 = audit_draft_dna(f_37)
    assert r37["passed"] is True
    assert r37["para_median"] == 37.0
    assert len(r37["violations"]) == 0
    assert any("段落中位数偏离最佳写作区间" in a and "37.0 字" in a for a in r37["advisories"])

    # --- 边界 3: 短段占比 51% 判 FAIL ---
    # 100 段: 51段短(15), 39段中(45), 10段沉浸(100)
    # short_para_pct = 51.0% (> gate_short_para_pct_max 50.0%)
    p_s15 = "测" * 15
    p_m45 = "测" * 45
    p_i100 = "测" * 100
    paras_51 = [p_s15] * 51 + [p_m45] * 39 + [p_i100] * 10
    f_51 = tmp_path / "short_51.md"
    f_51.write_text("# 标题\n\n" + "\n\n".join(paras_51), encoding="utf-8")
    r51 = audit_draft_dna(f_51)
    assert r51["passed"] is False
    assert r51["short_para_pct"] == 51.0
    assert any("短碎段(<=35字)占比过高: 51.0%" in v and "<= 50.0%" in v for v in r51["violations"])

    # --- 边界 4: 短段占比 48% 判 PASS（带 advisory） ---
    # 100 段: 48段短(15), 42段中(45), 10段沉浸(100)
    # short_para_pct = 48.0% (<= gate_short_para_pct_max 50.0%, 但 > target 45.0%)
    paras_48 = [p_s15] * 48 + [p_m45] * 42 + [p_i100] * 10
    f_48 = tmp_path / "short_48.md"
    f_48.write_text("# 标题\n\n" + "\n\n".join(paras_48), encoding="utf-8")
    r48 = audit_draft_dna(f_48)
    assert r48["passed"] is True
    assert r48["short_para_pct"] == 48.0
    assert len(r48["violations"]) == 0
    assert any("短段占比偏离最佳写作区间" in a and "48.0%" in a for a in r48["advisories"])


def test_prompt_assembler_carries_three_failure_zone_defenses(tmp_path: Path):
    """验证 prompt_assembler 装配的提示词严格贯彻三大失守区靶向约束（B8 与 10 份复核收敛结论）。"""
    run_dir = tmp_path / "run-three-defenses"
    run_dir.mkdir()

    res = assemble_writer_prompt(run_dir, save_evidence=False)
    sys_prompt = res["system_prompt"]
    user_prompt = res["user_prompt"]

    # 1. 失守区一：尾声和稀泥与升华坍缩
    assert "三大失守区靶向红线" in sys_prompt
    assert "失守区一：尾声和稀泥与升华坍缩" in sys_prompt
    assert "严禁尾声感悟升华" in sys_prompt
    assert "严禁立场和稀泥" in sys_prompt
    assert "物理动作落锁（冷酷收刀）" in sys_prompt

    # 2. 失守区二：可预测同义句与公版套话（Q3 意外性）
    assert "失守区二：可预测同义句与公版套话" in sys_prompt
    assert "反可预测测试" in sys_prompt
    assert "若某段有 ≥3 句可被同义、无风险、谁都会说的平庸套话无损替换" in sys_prompt

    # 3. 失守区三：道具与账本中后段蒸发
    assert "失守区三：道具与数字账本在中后段隐形" in sys_prompt
    assert "严禁开篇摆设道具后中后段蒸发" in sys_prompt
    assert "每个二级小节（`##`）必须至少唤醒或承载 1~2 个具体微观道具" in sys_prompt
    assert "千字微观物理锚点密度硬指标" in sys_prompt
    assert "正文每 1000 字必须分布不少于 **3 ~ 5 处** 具象物理锚点" in sys_prompt
    assert "全篇均匀度红线" in sys_prompt

    # 4. 首尾可预测套话绝对黑名单
    assert "首尾八股套话绝对物理黑名单" in sys_prompt
    assert "首段严禁套话" in sys_prompt
    assert "在浮躁的当下/时代里" in sys_prompt
    assert "尾声严禁套话" in sys_prompt
    assert "生活仍在继续" in sys_prompt
    assert "一部优秀的电影不仅在于……更在于……" in sys_prompt

    # 5. User Prompt 输出要求对齐
    assert "每小节至少承载 1~2 处微观感官道具" in user_prompt
    assert "正文全篇维持每千字 3~5 处物理锚点密度" in user_prompt
    assert "严禁出现“这何尝不是/生活仍在继续/愿我们都能/你怎么看”" in user_prompt


