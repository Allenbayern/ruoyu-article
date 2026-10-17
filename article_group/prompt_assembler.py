"""prompt_assembler: 将 12 篇定稿母本呼吸律动、外语片地道中文法则与四阶事实包
全自动装配为高完成度 Writer 提示词。

作用与演进：
1. 在 planning 阶段完成后，自动读取 title-pack, article-brief, evidence-pack 与 pending-review-sheet；
2. 匹配 12 篇母本中最契合的 2 篇 Few-Shot；
3. 2026-10-14 阈值统一：律动物理红线与写作目标全量从 `dna_engine.DNA_RHYTHM_STANDARD` 单一权威源读取，
   不再维护第二份硬编码数字；
4. 输出可直接交付给任意 LLM（DeepSeek / Claude / Gemini）的完整结构化提示词，
   并落盘至 `review/writer-prompt.md` 与 `review/writer-prompt.json`（走 evidence_write）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from article_group.dna_engine import CANONICAL_MOTHER_TEXTS, DNA_RHYTHM_STANDARD, match_dna
from article_group.evidence_write import write_evidence, write_evidence_json
from article_group.projection_card import validate_projection_card
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

    # 提取并对焦《动笔前投射对焦卡》（读者三问与一行动）
    card_raw = brief.get("projection_card") or title_pack.get("projection_card")
    proj_val = validate_projection_card(card_raw)
    if proj_val["passed"]:
        proj_card = proj_val["card"]
    else:
        proj_card = {
            "self_relevance": "剥离明星与题材光环，拆透普通人生活里那笔避无可避的现实利益账本与生存代价。",
            "emotional_outlet": "读完看清虚伪温情背后的利益机关，顺出心头闷气，获得一身清爽的人间清醒。",
            "one_liner_conflict": killer_stance[:30] if len(killer_stance) <= 30 else "台前全是体面，台后全在算计利益",
            "expected_action": "截图某句人间清醒发朋友圈",
        }

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
   - 全文段落中位数必须保持在 **{int(DNA_RHYTHM_STANDARD.target_para_median_min)} ~ {int(DNA_RHYTHM_STANDARD.target_para_median_max)} 字** 之间！
   - **绝对严禁一句话一行的碎片化短视频口播体！** 必须像成熟出版特稿一样，把起承转合自然融在段落中。
2. **长短交错呼吸感 (Standard Deviation ≥ {DNA_RHYTHM_STANDARD.target_para_stdev_min:.1f})**：
   - 必须包含 **≥ {DNA_RHYTHM_STANDARD.target_immersive_paras_min} 个 {DNA_RHYTHM_STANDARD.target_immersive_len_min} ~ {DNA_RHYTHM_STANDARD.target_immersive_len_max} 字的沉浸式微观拉片/现实算账大段落**（交代环境质感、道具细节与心理博弈，赋予文章厚重纵深）；
   - 短段（≤ {DNA_RHYTHM_STANDARD.target_short_para_len_max} 字）比例控制在 **{int(DNA_RHYTHM_STANDARD.target_short_para_pct_min)}% ~ {int(DNA_RHYTHM_STANDARD.target_short_para_pct_max)}%**，专用于段末冷酷收刀、转折压茬或强烈停顿；
   - 超过 {DNA_RHYTHM_STANDARD.gate_wall_para_len_max} 字的拥挤死墙段落数必须为 {DNA_RHYTHM_STANDARD.gate_wall_paras_max}！
3. **文章总字数底线与写作目标**：
   - 正文 CJK 纯汉字数写作目标建议落在 **{DNA_RHYTHM_STANDARD.target_cjk_min} ~ {DNA_RHYTHM_STANDARD.target_cjk_max} 字** 的深水区（底线硬阻断 ≥ {DNA_RHYTHM_STANDARD.gate_cjk_min} 字，严禁注水套话凑字，全靠硬核拉片与利益机制推进）。

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

### 三、 四阶深度素材 100% 消化与感官节拍器（严防中后段稀释）
1. **感官道具与核心主张必兑现（全篇穿透）**：
   - 事实包中声明的 **≥ 3 个微观物理感官道具** 必须作为全篇叙事推进的物理骨架在正文中如实展开并产生阻力；
   - **严禁开篇摆设道具后中后段蒸发**：正文每个二级小节（`##`）必须至少唤醒或承载 1~2 个具体微观道具或动作动线，严禁连续两段纯写抽象影评判断句；
   - 严禁脑补原片不存在的虚构道具。
2. **千字微观物理锚点密度硬指标（量化底线）**：
   - **千字锚点密度要求**：正文每 1000 字必须分布不少于 **3 ~ 5 处** 具象物理锚点（具体道具交互、动作动线、不可篡改的账本数字或带引号一手台词）；
   - **全篇均匀度红线**：严禁把所有锚点堆砌在开篇第一幕！第二幕、第三幕乃至尾声必须同频维持该锚点密度，中后段如出现连续 400 字以上无道具/动线/数字的纯情绪发泄或道德空评，复核视为重大失守。
3. **严格断言覆盖**：
   - 正文凡涉及具体时间跨度、带量词数字（美元金额、房贷细则、年份人数）与关键双引号台词，必须 100% 来自下方事实包；
   - 严禁脱离账本自创新数字。
4. **已降级待核事实绝对禁止回弹**：
   - 下方【降级与禁用词清单】中列明的未核项目，严禁在正文擅自恢复写入。

### 四、 叙事与文风偏好（9 喜欢 + 7 避免，注入人味儿）
- **开篇夺魂**：第一段必须是极具物理张力、反常伦理或倒置结果的人物极端动作（≤ 30 字极简破题），严禁“近年来/由某某执导/探讨了人性”等平庸八股！
- **旁白大白话拆台**：遇到虚伪假大空，立即用民间大白话拆穿算盘，敢骂敢讽，绝不中庸端水。
- **首尾八股套话绝对物理黑名单（触碰即判废）**：
  - **首段严禁套话**：严禁出现“近年来……”、“在浮躁的当下/时代里……”、“随着……的发展……”、“提起某某，大家往往会想到……”、“由某某执导的电影……”、“这部作品探讨了人性深处的……”、“在当今社会……”等一切大词引言；
  - **尾声严禁套话**：严禁出现“这何尝不是……”、“生活仍在继续……”、“或许这就是人性的……”、“愿我们都能……”、“在这个快节奏的时代……”、“一部优秀的电影不仅在于……更在于……”、“时代的一粒沙……”、“你怎么看？欢迎在评论区留言”等一切公文感悟与客服收尾；
- **投射对焦军规（物理红线）**：
  - **关读者屁事贯穿**：故事不管多悬殊，必须时刻把名利场算盘投射到普通人的生活账本上（{proj_card['self_relevance']}）；
  - **情绪出口兑现**：整篇文章的高潮与收口必须精准顺出读者的心头闷气（{proj_card['emotional_outlet']}）；
  - **一句话矛盾暗线**：以极简大白话反差（{proj_card['one_liner_conflict']}）统领叙事，绝对严禁任何公文词汇；
  - **促成预期动作**：全文必须铺设至少 3 处有算账说服力的透彻金句，促使读者【{proj_card['expected_action']}】。

### 五、 三大失守区靶向红线（L2 独立对抗复核必查项）
1. **失守区一：尾声和稀泥与升华坍缩（绝对禁止升华与端平，冷酷收刀）**：
   - **严禁尾声感悟升华**：结尾绝对严禁出现上述尾声黑名单套话，严禁哲学总结与精神灌顶；
   - **严禁立场和稀泥**：结尾绝不许替剥削者或投机者洗白找补，绝不端平为“谁都没错、时代之殇、两边都有道理”；
   - **物理动作落锁（冷酷收刀）**：结尾必须停在最后一个极简平淡的物理动作、不可逆事实或账本数字上（如“门关上了”、“账本合上了”、“账面上只剩下了…”），不作道德裁决，戛然而止！
2. **失守区二：可预测同义句与公版套话（Q3 意外性审查）**：
   - **严禁单段连串平庸句**：严禁连续套用“不仅是…更是…”、“表面上是…本质上是…”、“背后折射出…”等八股连词脚手架；
   - **反可预测测试**：若某段有 ≥3 句可被同义、无风险、谁都会说的平庸套话无损替换，会被 L2 直接记 major 拦截；推论必须有出其不意的大白话转折和切肤的利益刺痛感。
3. **失守区三：道具与数字账本在中后段隐形（感官断层）**：
   - 物理感官道具与量化账本是推动全文拉片的节拍器，不是开篇的点缀物；
   - 贯彻千字 3~5 处物理锚点密度，全文绝不允许用形容词堆砌冒充事实，每一小节的推论必须始终绑在可见的镜头动线、账本金额或道具交互上。

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
- **动笔前投射对焦卡（读者三问与一行动）**：
  - 1. 关读者屁事 (Self-Relevance)：{proj_card['self_relevance']}
  - 2. 情绪出口 (Emotional Outlet)：{proj_card['emotional_outlet']}
  - 3. 一句话矛盾 (One-Liner Conflict)：{proj_card['one_liner_conflict']}
  - 4. 预期读者动作 (Expected Action)：【{proj_card['expected_action']}】

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
1. 开头以 `# {title}` 起笔，第一段立即切入极端动作夺魂，严禁任何形式的宏观大词或引言套话（严禁“近年来/在浮躁的当下/探讨了人性”等）；
2. 各小节使用 `## 一、...` 编号，每小节至少承载 1~2 处微观感官道具或具体动作展开，正文全篇维持每千字 3~5 处物理锚点密度，坚决抵御抽象词汇中后段稀释；
3. 全文各小节推论必须有出其不意的大白话刺痛感，严禁连续使用公版对仗套话；
4. 尾声严格执行【冷酷收刀】，停在平淡物理动作或不可逆事实，严禁出现“这何尝不是/生活仍在继续/愿我们都能/你怎么看”等任何感悟哲理、和稀泥或互动设问！"""

    result_payload = {
        "run_id": manifest.get("run_id", root.name),
        "title": title,
        "work": work_name,
        "archetype": archetype,
        "dna_rhythm_standard": DNA_RHYTHM_STANDARD.to_prompt_assembler_dict(),
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
