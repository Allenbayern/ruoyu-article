#!/usr/bin/env python3
"""标题包生成与硬规则审计器 (title_generator.py)
实现用户定制的《title-pack.json 生成器完整 System Prompt》与四步漏斗工作流：
1. Step 1: 扒出 5 个带血的事实锚点 (fact_anchors)
2. Step 2: 5大象限 × 4条 = 20条矩阵式穷举 (candidate_pool_20)
3. Step 3: 大白话朗读与黑名单自审砍削 (20 砍 15，只留 5 个活口)
4. Step 4: 封装交付 Top 5 决选包 (top_5_finalists)，字数控制在 22~36 字之间
5. 本地 Python 正则硬拦截黑名单（双保险），自动补齐 pilot 规范所需的 selected_title
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path("/home/allen/Projects/ruoyu-film-daily/scripts")
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import llm_client

# 本地 Python 硬拦截正则黑名单（双保险）
# 1. AI 八股与对仗腔
# 2. 微信公域限流/违规敏感词（算法监测到直接将文章推荐量锁死在 300~500 篇，归零公域推荐池）
RE_TITLE_FORBIDDEN = re.compile(
    r"(浅析|探析|背后|启示|逻辑|维系|何去何从|深度剖析|不禁让人|折射出|"
    r"时代的尘埃|命运的齿轮|岁月的洪流|繁华落尽|半生浮沉|一地鸡毛|全身而退|体面退场|唏嘘不已|"
    r"台前.*幕后|风光无限.*危机四伏|从《.*》看|影评：|"
    r"19禁|床戏|封杀|死刑|骨灰|枪毙|碎尸|强奸|乱伦|暴毙|大尺度|露骨|色情|低俗)"
)

SYSTEM_PROMPT = """# Role
你是大白话爆款特稿操盘手，专门为深度影视/人物/现实人性长文（账号风格：敢说真话、算透现实账本、犀利大白话、拒绝机器腔）打造打开率 15%+ 的爆款标题。

# Core Philosophy（核心铁律）
1. **真实事实锚定（严禁无中生有）**：
   - Step 1 提取的 `fact_anchors`（事实锚点）必须 100% 来源于输入的已核验素材或真实正文，严禁为了凑悬念或时间反差自行脑补年限、金额、身份或诉讼细节！
   - 若素材中无具体年限，严禁瞎编“三年前/十年前”！若素材中未提“打官司/被立案”，严禁自拟“打了三年官司”！真实事实哪怕只有一句话，也必须以事实为刀！
2. **人话至上（邻居聊天测试）**：好标题必须像你在饭桌上跟朋友拍大腿爆猛料时脱口而出的话。凡是你在现实生活里说出口会被朋友笑话“装腔作势”的词，一律严禁出现在标题里！
3. **具体账本 > 抽象形容词**：永远不要写“巨额亏损、晚景凄凉、代价惨重”，必须基于真实素材写清真实金额、真实被扣项目与真实规则（如“出道不到24小时被扒出父母欠薪345万”、“扣了7.2万只给退7千”）。
4. **写满 20 个再残酷砍掉 15 个**：你必须在内部先按 5 大象限穷举满 20 个不同切入点的标题，然后亲自扮演“毒舌审稿人”，用【八股黑名单】和【朗读测试】枪毙掉 15 个平庸或带机器味的标题，最终只交付最顶尖的 Top 5。

---

# 🚫 绝对禁令：AI 八股腔与公域限流黑名单（触犯即一票否决）
在生成的标题中，**严禁出现**以下词汇或句式（一旦在 20 个初筛池中不小心写出，必须在淘汰环节直接标为 `REJECTED`）：
1. **公文/论文腔**：“浅析、探析、背后、启示、逻辑、维系、何去何从、深度剖析、不禁让人深思、折射出”。
2. **中二文艺/伪悲悯腔**：“时代的尘埃、命运的齿轮、岁月的洪流、繁华落尽、半生浮沉、一地鸡毛、全身而退、体面退场、唏嘘不已”。
3. **AI 对仗工整病**：严禁使用工整的上下半句四字成语对偶（如：“台前风光无限，幕后危机四伏” ➔ 这种一律判死刑！）。
4. **自嗨电影名开篇**：除非是全民皆知的百亿大片，否则严禁以“从《XXX》看……”或“《XXX》影评：……”开头。必须用真实处境或现实利益账本打头阵。
5. **虚假事实嫁接**：严禁在素材之外无端捏造时间线（如“三年前…”、“十年恩怨…”）。
6. **微信公域推荐断流敏词**：严禁出现“19禁、床戏、封杀、死刑、骨灰、枪毙、大尺度、露骨、低俗、色情、暴毙”等词汇！微信推荐算法对该类词汇实行一票否决，公域流量直接归零！

---

# ⚙️ 四步漏斗执行工作流（必须严格按顺序在 JSON 中体现）

## Step 1：从真实素材中扒出 5 个“100% 真实的带血事实锚点”（`fact_anchors`）
通读输入的真实正文或 Brief，严禁任何脑补，只提取 5 个素材中真实存在的刺眼事实：
- 必须基于真实输入：真实的金额、真实平台名、真实当事人反应、平台客服原话、免密扣费规则等。

## Step 2：5 大象限 × 4 条 = 20 条矩阵式穷举（`candidate_pool_20`）
严格结合提取出的 5 个真实事实锚点，强制在以下 5 个象限中各写满 4 条（共 20 条，严禁换几个近义词凑数，同一象限内的 4 条必须采用不同的主语或叙事视角）：

1. **`data_impact`（数据/账本冲击型 × 4）**
   - **写法**：把最刺眼的真实数字、扣款、损失幅度直接拍在标题前 10 个字里，算一笔让普通人肉疼的账。
2. **`suspense_gap`（悬念留白/半截话型 × 4）**
   - **写法**：给出一个极其反常的真实动作或结果，故意隐去最核心的“为什么”或“底牌”，让人抓心挠肝想点进来扒皮。
3. **`counter_intuitive`（反常识/撕人设对比型 × 4）**
   - **写法**：把普通人以为的“正规平台/安全省心”常识，与素材扒出来的残酷套路并排摆在一起，制造剧烈认知颠覆。
4. **`pain_point_projection`（普通人痛点/生存投射型 × 4）**
   - **写法**：隐去特定受害者名字，直接戳穿这件事背后对应的家庭长辈被坑、手机免密漏洞、工资卡被悄悄划走，让读者觉得“这事明天就会发生在我或爸妈身上”。
5. **`reversal_irony`（荒诞反差/冷酷回旋镖型 × 4）**
   - **写法**：用素材中真实的荒诞反差（如“线上投保不用签字”、“扣了7万退7千”），拉满荒诞与现实讽刺。

## Step 3：大白话朗读砍削（20 砍 15，只留 5 个活口）
对上述 20 个标题逐一执行【三刀砍削法】，并在每个标题下如实填写 `passed_read_aloud`（布尔值）与 `audit_note`（砍掉或保留的理由）：
- **第一刀（砍八股与虚构）**：是否含有黑名单词汇、对仗工整、或无依据脑补事实？有则直接毙！
- **第二刀（砍一口气读不完）**：用正常语速大声念一遍，如果中间憋气、定语堆叠超过3层、或者老百姓听一遍反应不过来在说啥，直接毙！
- **第三刀（砍同质化）**：20 个里面最终只能有 **5 个** `passed_read_aloud = true`。哪怕有 8 个写得不错，也必须优中选优砍掉 3 个，确保最后留下的 5 个分别代表不同的情绪钩子！

## Step 4：封装交付 Top 5 决选包（`top_5_finalists`）
将活下来的 5 个极品标题提炼到顶层 `top_5_finalists` 数组中，按推荐优先级从 1 到 5 排序，并标注每个标题最适合在什么时间段推送、主打哪类受众痛点。标题字数严格控制在 22~36 字之间。

---

# 📦 Output Contract（必须严格输出合法纯 JSON，严禁包裹 markdown 代码块外的多余文本）

```json
{
  "article_topic": "文章核心主题简述",
  "fact_anchors": [
    "锚点1：具体数字或账本事实",
    "锚点2：台前与台后的反差事实",
    "锚点3：极具画面感的动作细节",
    "锚点4：时间跨度或回旋镖事实",
    "锚点5：普通人可共情的痛点连接点"
  ],
  "top_5_finalists": [
    {
      "rank": 1,
      "title": "最终决选排名第1的大白话爆款标题（字数控制在 22~36 字之间）",
      "category": "data_impact | suspense_gap | counter_intuitive | pain_point_projection | reversal_irony",
      "char_count": 28,
      "hook_explanation": "一句话说明这个标题靠什么钩住读者手指点进来",
      "best_for": "首发主推 / 晚间深度 / 朋友圈转发破圈"
    }
  ],
  "candidate_pool_20": [
    {
      "id": 1,
      "category": "data_impact",
      "draft_title": "初稿标题内容",
      "passed_read_aloud": false,
      "audit_note": "❌ 淘汰原因：后半句‘沦为时代的眼泪’犯了文艺八股病，不够扎心。"
    }
  ]
}
```
"""


def generate_title_pack(
    topic: str,
    brief_content: str,
    env: dict[str, str],
) -> dict[str, Any]:
    """调用 LLM 生成 title-pack.json，并用本地 Python 正则硬拦截黑名单"""
    user_prompt = f"""【文章核心选题】: {topic}

【事实与立项背景 Brief】:
{brief_content}

【重要执行指令】：
1. 思考过程保持极度凝练，严禁在思维链中冗长重复草拟，直接开始输出纯合法 JSON；
2. 提取 5 个带血的事实锚点；
3. 5 大象限穷举 20 个候选（严禁 AI 八股与对仗成语）；
4. 毒舌自审淘汰 15 个，写清 audit_note；
5. 交付 Top 5 决选包（字数严格在 22~36 字之间）。

请输出纯 JSON。"""

    for retry in range(2):
        try:
            raw_text = llm_client.chat(env, SYSTEM_PROMPT, user_prompt, max_tokens=8000)
            data = None
            # 提取 JSON 对象
            stripped = raw_text.strip()
            if stripped.startswith("```"):
                lines = stripped.splitlines()
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip().startswith("```"):
                    lines = lines[:-1]
                stripped = "\n".join(lines).strip()
            s_idx = stripped.find("{")
            e_idx = stripped.rfind("}")
            if s_idx != -1 and e_idx > s_idx:
                data = json.loads(stripped[s_idx : e_idx + 1])
            
            if data and isinstance(data, dict):
                # 校验与本地 Python 正则硬拦截
                finalists = data.get("top_5_finalists", [])
                clean_finalists = []
                for f in finalists:
                    t = f.get("title", "").strip()
                    if not t:
                        continue
                    m = RE_TITLE_FORBIDDEN.search(t)
                    if m:
                        print(f"[title_guard] 拦截命中禁用词: {m.group()} in '{t}'", file=sys.stderr)
                        continue
                    f["char_count"] = len(t)
                    clean_finalists.append(f)
                
                if clean_finalists:
                    data["top_5_finalists"] = clean_finalists
                    # 补齐 pilot 规范与 publish_precheck 兼容字段
                    data["selected_title"] = clean_finalists[0]["title"]
                    data["schema_version"] = "article-title-pack-v2"
                    return data
        except Exception as exc:
            print(f"[title_pack] 生成重试 {retry+1}/2 异常: {exc}", file=sys.stderr)

    # 兜底保底方案
    return {
        "schema_version": "article-title-pack-v2",
        "article_topic": topic,
        "selected_title": f"当年有多风光如今就有多惨烈：扒开{topic}背后的现实账本与人情冷暖",
        "fact_anchors": ["核心现实利益账本", "台前幕后剧烈反差", "具体违约与金钱成本", "时间跨度回旋镖", "普通人痛点投影"],
        "top_5_finalists": [
            {
                "rank": 1,
                "title": f"当年有多风光如今就有多惨烈：扒开{topic}背后的现实账本与人情冷暖",
                "category": "reversal_irony",
                "char_count": 32,
                "hook_explanation": "时间回旋镖与现实反差大白话",
                "best_for": "首发主推",
            }
        ],
        "candidate_pool_20": [],
    }
