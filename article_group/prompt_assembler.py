"""prompt_assembler: 将 12 篇定稿母本呼吸律动、外语片地道中文法则与四阶事实包
全自动装配为高完成度 Writer 提示词。

作用：
1. 在 planning 阶段完成后，自动读取 title-pack, article-brief, evidence-pack 与 pending-review-sheet；
2. 匹配 12 篇母本中最契合的 2 篇 Few-Shot；
3. 将段落中位数 (40~65字)、长段沉浸拉片、短段冷刀收口、严禁英文代号/单集名、严格事实纪律等物理红线
   硬编码进 System Prompt；
4. 输出可直接交付给任意 LLM（DeepSeek / Claude / Gemini）的完整结构化提示词，
   并落盘至 `review/writer-prompt.md` 与 `review/writer-prompt.json`（走 evidence_write）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from article_group.dna_engine import CANONICAL_MOTHER_TEXTS, match_dna
from article_group.evidence_write import write_evidence, write_evidence_json
from article_group.prompts.human_fingerprints.registry import get_human_fingerprints_instruction


def _load_json_safe(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def assemble_writer_prompt(
    run_root: str | Path,
    *,
    author: str = "editorial_planner",
    save_evidence: bool = True,
) -> dict[str, Any]:
    """从 run 目录全量提取事实物料，自动组装母本级 Writer System & User Prompt。"""
    root = Path(run_root).resolve()

    manifest = _load_json_safe(root / "pilot-manifest.json")
    title_pack = _load_json_safe(root / "title-pack.json")
    brief = _load_json_safe(root / "article-brief.json")
    ev_pack = _load_json_safe(root / "evidence-pack.json")
    sheet = _load_json_safe(root / "pending-review-sheet.json")

    title = str(
        title_pack.get("selected_title")
        or brief.get("selected_title")
        or manifest.get("topic_label")
        or "影视深度长文"
    ).strip()
    work_name = str(ev_pack.get("work") or title_pack.get("work") or brief.get("work") or title).strip()
    killer_stance = str(title_pack.get("killer_stance") or brief.get("killer_stance") or "算透现实账本").strip()
    reader_persona = str(brief.get("reader_persona") or "对现实利益博弈有体感、反感虚伪宣发口号的真实读者").strip()

    # 1. 匹配 12 篇母本与母题风格指纹
    dna_match = match_dna(f"{title} {work_name}")
    archetype = dna_match.get("detected_archetype", "单片深度解剖")
    genre_instruction = get_human_fingerprints_instruction(archetype)

    few_shot_texts: list[dict[str, str]] = []
    for m in dna_match.get("canonical_mother_articles") or []:
        m_path = Path(m.get("path", ""))
        if m_path.is_file():
            content = m_path.read_text(encoding="utf-8")
            few_shot_texts.append({
                "title": m.get("title", m_path.stem),
                "archetype": m.get("archetype", archetype),
                "excerpt": content[:1800] + ("\n\n……（后文接续，保持同等沉浸节奏）" if len(content) > 1800 else ""),
            })

    # 2. 提取四阶事实硬核
    core_claims = ev_pack.get("core_claims") or []
    sensory_anchors = ev_pack.get("sensory_anchors") or []
    origin_bg = str(ev_pack.get("origin_background") or "").strip()
    # 合并 verified_facts 与 source_facts
    all_facts_map: dict[str, dict[str, Any]] = {}
    for f in (ev_pack.get("verified_facts") or []):
        if isinstance(f, Mapping) and f.get("fact"):
            all_facts_map[str(f["fact"]).strip()] = dict(f)
    for f in (ev_pack.get("source_facts") or []):
        if isinstance(f, Mapping):
            f_text = str(f.get("fact") or f.get("text") or "").strip()
            if f_text and f_text not in all_facts_map:
                all_facts_map[f_text] = {"fact": f_text, "source_id": f.get("source_id", "")}
    verified_facts = list(all_facts_map.values())
    downgraded_facts = ev_pack.get("uncertain_facts_downgraded") or []
    pending_items = sheet.get("pending_items") or []

    # 提取绝对不可反弹的违规事实清单
    forbidden_tokens_list: list[str] = []
    for item in pending_items:
        if isinstance(item, Mapping):
            for t in item.get("forbidden_tokens") or []:
                forbidden_tokens_list.append(str(t).strip())
    for dg in downgraded_facts:
        if isinstance(dg, Mapping):
            pol = str(dg.get("policy") or "")
            forbidden_tokens_list.append(f"注意降级策略: {pol}")

    # 3. 构造 System Prompt
    system_prompt = f"""你现在是公众号【若雨随影】的唯一王牌主笔，也是一位深谙人情世故、冷峻算账的电影与剧集深度解说大师。
你写出的长文既有极高密度的微观影视细节拉片，又把普通人在名利场里的切肤利益算盘剖析得入木三分。

严格贯彻以下五大【母本级创作军规】：

### 一、 12篇定稿母本呼吸律动规范（物理红线）
1. **段落字数严卡黄金区间**：
   - 全文段落中位数必须保持在 **45 ~ 65 字** 之间！
   - **绝对严禁一句话一行的碎片化短视频口播体！** 必须像成熟出版特稿一样，把起承转合自然融在段落中。
2. **长短交错呼吸感 (Standard Deviation ≥ 25.0)**：
   - 必须包含 **≥ 4 个 80 ~ 170 字的沉浸式微观拉片/现实算账大段落**（交代环境质感、道具细节与心理博弈，赋予文章厚重纵深）；
   - 短段（≤ 35 字）比例控制在 **20% ~ 45%**，专用于段末冷酷收刀、转折压茬或强烈停顿；
   - 超过 205 字的拥挤死墙段落数必须为 0！
3. **文章总字数底线**：
   - 正文 CJK 纯汉字数严格落在 **2000 ~ 2700 字** 的深水区（严禁注水套话凑字，全靠硬核拉片与利益机制推进）。

### 二、 外语片地道中文语境重塑（严禁翻译腔与生硬英文字母）
1. **去英文人名/角色代号**：
   - 严禁直呼怪异英文名或代号（如 A1A、Chad）。
   - **必须使用「社会阶层反差描述 + 中文自然音译」**！例如：将“学生Chad”改为“平日里在班上最刺头、成天开跑车炫耀的富二代学生查德”；将“A1A洗车行”改为“街角那家潮湿逼仄的兼职洗车行”。读者要看的是清贫老师与二世祖顾客之间的阶层刺痛感！
2. **去英文单集代码**：
   - 严禁堆砌如“第一季第五集《Gray Matter》”、“第四季第六集《Cornered》”、“第五季第十四集《Ozymandias》”。
   - **必须使用「中文名场面戏核」或「经典文学意译」**！例如：
     - 将《Seven Thirty-Seven》译为“第二季开篇那场著名的‘活命账本’名场面（编剧极具讽刺意味地将其命名为《737》）”；
     - 将《Gray Matter》融入为“第一季那场被称为命运分水岭的‘灰质公司’豪宅派对”；
     - 将《Cornered》融入为“第四季老白被逼入绝境死角的那场经典夫妻对手戏（《走投无路》）”；
     - 将《Ozymandias》借用雪莱名诗翻译为“被全球剧迷奉为电视史巅峰的第十四集《万王之王》（Ozymandias）”；
     - 将《Felina》自然收口为“终章大结局”。

### 三、 四阶深度素材 100% 消化与事实铁律
1. **感官道具与核心主张必兑现**：
   - 事实包中声明的 **≥ 3 个微观物理感官道具** 必须作为叙事骨架在正文中如实展开并产生阻力；
   - 严禁脑补原片不存在的虚构道具。
2. **严格断言覆盖**：
   - 正文凡涉及具体时间跨度、带量词数字（美元金额、房贷细则、年份人数）与关键双引号台词，必须 100% 来自下方事实包；
   - 严禁脱离账本自创新数字。
3. **已降级待核事实绝对禁止回弹**：
   - 下方【降级与禁用词清单】中列明的未核项目，严禁在正文擅自恢复写入。

### 四、 叙事与文风偏好（9 喜欢 + 7 避免）
- **开篇夺魂**：第一段必须是极具物理张力、反常伦理或倒置结果的人物极端动作（≤ 30 字极简破题），严禁“近年来/由某某执导/探讨了人性”等平庸八股！
- **旁白大白话拆台**：遇到虚伪假大空，立即用民间大白话拆穿算盘，敢骂敢讽，绝不中庸端水。
- **冷酷收刀**：结尾停在最后一个极简平淡的物理动作或苍凉叹息上，严禁正能量口号，**严禁文末出现“你怎么看/欢迎在评论区留言”等客服式套话！**

---

### 【参考母本典范片段 (Few-Shot)】
"""
    for idx, fs in enumerate(few_shot_texts, 1):
        system_prompt += f"\n#### 典范母本 {idx}：《{fs['title']}》（{fs['archetype']}）\n```markdown\n{fs['excerpt']}\n```\n"

    # 4. 构造 User Prompt
    claims_formatted = "\n".join(
        f"- 【论点 {c.get('claim_id', i)}】：{c.get('assertion', '')}（支撑：{c.get('support', '')}）"
        for i, c in enumerate(core_claims, 1) if isinstance(c, Mapping)
    )
    anchors_formatted = "\n".join(
        f"- 【道具 {a.get('anchor_id', i)}】：{a.get('name', '')} —— 叙事功能：{a.get('function', '')}"
        for i, a in enumerate(sensory_anchors, 1) if isinstance(a, Mapping)
    )
    facts_formatted = "\n".join(
        f"- {f.get('fact', '')} (出处: {f.get('source_id', '')})"
        for f in verified_facts if isinstance(f, Mapping)
    )
    forbid_formatted = "\n".join(f"- 🚫 {tok}" for tok in forbidden_tokens_list) or "- 无特殊禁用项"

    user_prompt = f"""请依据以下已被核实的真实物料包，为公众号【若雨随影】起草一篇完整的深度长文：

### 【定稿标题与核心立项】
- **定稿标题（物理冻结，不可更改）**：# {title}
- **核心剖析作品**：《{work_name}》
- **所属母题与体裁**：{archetype}
- **读者画像**：{reader_persona}
- **主刀核心立场**：{killer_stance}

### 【四阶深度事实包】
1. **背景渊源与底层机制**：
{origin_bg or "无特殊背景"}

2. **核心论证主张（必须全量落地，不可做账本孤儿）**：
{claims_formatted or "无明确主张列表"}

3. **微观物理感官道具（必须作为叙事推进节拍器）**：
{anchors_formatted or "无道具列表"}

4. **已锚定确凿事实与数字明细（所有正文数字引述以此为准）**：
{facts_formatted or "无单独事实列表"}

### 【待核清单与绝对禁用项】
{forbid_formatted}

---

【输出要求】：
直接输出 Markdown 正文。
开头以 `# {title}` 起笔，第一段立即切入极端动作夺魂，各小节使用 `## 一、...` 编号，正文严格保持 12 篇母本的长短交错律动与地道中文戏核表达！"""

    result_payload = {
        "run_id": manifest.get("run_id", root.name),
        "title": title,
        "work": work_name,
        "archetype": archetype,
        "dna_rhythm_standard": {
            "para_median_target": "45~65字",
            "para_stdev_min": 25.0,
            "immersive_paras_min": 4,
            "wall_paras_max": 0,
            "short_paras_pct_range": "20%~45%",
            "cjk_chars_range": "2000~2700字",
        },
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "matched_mother_articles": [m["title"] for m in dna_match.get("canonical_mother_articles") or []],
    }

    if save_evidence:
        review_dir = root / "review"
        write_evidence_json(
            review_dir / "writer-prompt.json",
            result_payload,
            run_dir=root,
            reason="prompt_assembler:writer_prompt_json",
            author=author,
        )
        md_readable = (
            f"# 若雨随影主笔提示词装配包 ({title})\n\n"
            f"> 对应作品: 《{work_name}》 | 母题: {archetype}\n\n"
            f"## 一、 System Prompt\n\n```markdown\n{system_prompt}\n```\n\n"
            f"## 二、 User Prompt\n\n```markdown\n{user_prompt}\n```\n"
        )
        write_evidence(
            review_dir / "writer-prompt.md",
            md_readable,
            run_dir=root,
            reason="prompt_assembler:writer_prompt_md",
            author=author,
        )

    return result_payload
