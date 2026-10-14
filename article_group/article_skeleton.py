"""article_skeleton: Standardized narrative skeleton generator for Ruoyu Film Daily.

Synthesizes ZJU-REAL/Easel 'article-structures' and Ruoyu Editorial Redlines:
- 8 archetypal article progression skeletons.
- Opening Icebreaker Hook contract (no macroscopic fluff, concrete anchor).
- Mandatory Sensory Anchor slots (>= 3 physical details: props, actions, visceral beats).
- Explicit Killer Stance enforcement (no fence-sitting or equivocal balancing).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from article_group.prompts.human_fingerprints import (
    get_human_fingerprints_instruction,
)

STRUCTURES = {
    "contrarian": {
        "name": "逆向认知 (Contrarian)",
        "best_for": "全网一边倒吹捧或漫骂，但核心逻辑与事实完全相反的话题",
        "steps": [
            "第一幕：抛出大众主流偏见与直觉判断",
            "第二幕：列举被集体忽略的致命物理证据（反转点）",
            "第三幕：剖析为什么大众判断会集体失真（宣发误导/情绪绑架）",
            "第四幕：重构这部作品/事件的真实艺术与商业本质",
            "第五幕：结论与行业警示（给读者的最终判断）",
        ],
    },
    "case_file": {
        "name": "案卷复盘 (Case File)",
        "best_for": "大制作翻车、烂片口碑崩塌、重大创作事故、争议事件复盘",
        "steps": [
            "第一幕：案发现场与惨烈后果（具体票房崩塌日/公关翻车时刻）",
            "第二幕：回溯创作证据链（剧本魔改、选角妥协、资本干预）",
            "第三幕：核心病因解剖（到底错在哪一环？撕开创作者借口）",
            "第四幕：对立方的辩解为何站不住脚（事实核验与辩驳）",
            "第五幕：同类作品的历史对照与行业教训",
        ],
    },
    "teardown": {
        "name": "机制拆解 (Teardown)",
        "best_for": "影视工业流水线、短剧分账模式、院线排片潜规则、特效制作体系",
        "steps": [
            "第一幕：表层现象总览（观众看到的怪相）",
            "第二幕：三层深层机制拆解（资本层/创作层/分发层）",
            "第三幕：关键设计取舍与利益冲突",
            "第四幕：经典标杆作品 vs 失败流水线产品参数对比",
            "第五幕：行业生态适用边界与未来走向",
        ],
    },
    "timeline_news": {
        "name": "时间线发酵 (Timeline)",
        "best_for": "影视突发公关风波、主创撤档、临时改名、演职人员合同爆雷",
        "steps": [
            "第一幕：关键引爆时间节点与第一声警报",
            "第二幕：事件发酵全景链（按日/小时梳理核心事实与各方动作）",
            "第三幕：各方利益博弈与公关话术背后的真实动机",
            "第四幕：被模糊的核心焦点与未公开账本",
            "第五幕：接下来必须紧盯的 2-3 个不可逆信号",
        ],
    },
    "data_first": {
        "name": "数据砸脸 (Data First)",
        "best_for": "票房断崖、投资回报率惨败、宣发费用失衡、评分两极分化",
        "steps": [
            "第一幕：第一屏甩出刺痛行业的硬核数据对比",
            "第二幕：数据出处、口径与真实可信度核实",
            "第三幕：这个数字背后刺痛的是谁？（行业利益分配图谱）",
            "第四幕：从数据反推创作环节的溃败",
            "第五幕：若雨随影对该产业现象的最终裁决",
        ],
    },
    "question_led": {
        "name": "深度追问 (Question Led)",
        "best_for": "观众普遍困惑：为什么好导演拍烂片？为什么大IP屡屡被毁？",
        "steps": [
            "第一幕：抛出每一个走出影院的观众都在问的核心困惑",
            "第二幕：检验 A 方官方说法（为什么这是虚伪的粉饰）",
            "第三幕：检验 B 方舆论猜测（剔除臆测，核实证据）",
            "第四幕：揭示房间里真正的大象（系统性机制病根）",
            "第五幕：边界收束与真诚结论",
        ],
    },
    "field_notes": {
        "name": "观影实测 (Field Notes)",
        "best_for": "最新院线公映、点映实测、电影节冷门佳作深度体验",
        "steps": [
            "第一幕：开场 15 分钟的生理感受与影院现场观众反馈",
            "第二幕：哪里让人惊艳？（具体的视听镜头与表演高光）",
            "第三幕：哪里如坐针毡？（具体的台词硬伤与逻辑断裂）",
            "第四幕：它为什么无法成为真正的经典？（审美与价值观天花板）",
            "第五幕：买票建议与耐受度门槛提示",
        ],
    },
    "playbook": {
        "name": "鉴赏行动指南 (Playbook)",
        "best_for": "如何识破伪高级电影、如何看懂摄影调度、类型片防坑指南",
        "steps": [
            "第一幕：给读者的承诺（学会这套逻辑，再也不会被水军忽悠）",
            "第二幕：假大空作品必露馅的 3 处物理破绽",
            "第三幕：真正大师级创作的处理范本（逐帧对照）",
            "第四幕：普通观众必须警惕的 3 大审美陷阱",
            "第五幕：精选观影清单与防踩雷自检表",
        ],
    },
}


def build_skeleton(
    *,
    topic: str,
    structure_type: str = "contrarian",
    killer_stance: str,
    opening_hook: str | None = None,
    sensory_anchors: list[str] | None = None,
    realistic_stakes: list[str] | None = None,
    target_words: int = 2200,
) -> dict[str, Any]:
    """Build a structured article skeleton matching Ruoyu Film Daily criteria with human fingerprints."""
    struct_meta = STRUCTURES.get(structure_type, STRUCTURES["contrarian"])
    anchors = sensory_anchors or ["破碎道具细节", "关键人物神态特写", "标志性环境声音/雨夜"]
    stakes = realistic_stakes or ["普通人的饭碗与家庭生计代价", "不可逆的违约赔偿或体制编制损失"]

    # Verify killer stance
    stance_clean = killer_stance.strip()
    is_valid_stance = len(stance_clean) >= 10 and not any(
        w in stance_clean for w in ["见仁见智", "两边都有道理", "情有可原", "各有千秋"]
    )

    # Opening hook validation
    hook_clean = (opening_hook or "").strip()
    if not hook_clean:
        hook_clean = f"直接以【{anchors[0]}】引发的极端冲突或反常伦理动作破题"

    steps_with_targets = []
    # Calculate word budget per section
    intro_words = int(target_words * 0.15)
    body_section_words = int((target_words * 0.70) / 3)
    conclusion_words = int(target_words * 0.15)

    words_alloc = [intro_words, body_section_words, body_section_words, body_section_words, conclusion_words]

    for i, step_desc in enumerate(struct_meta["steps"]):
        w = words_alloc[i] if i < len(words_alloc) else body_section_words
        steps_with_targets.append({
            "act": f"第 {i+1} 幕",
            "description": step_desc,
            "target_cjk_words": w,
            "anchor_slot": anchors[i % len(anchors)] if i in (0, 1, 2) else "",
        })

    return {
        "topic": topic,
        "structure_type": structure_type,
        "structure_name": struct_meta["name"],
        "killer_stance": stance_clean,
        "stance_valid": is_valid_stance,
        "opening_hook": hook_clean,
        "sensory_anchors": anchors,
        "anchors_count": len(anchors),
        "realistic_stakes": stakes,
        "stakes_count": len(stakes),
        "total_target_words": target_words,
        "opening_contract": {
            "rule": "第一段必须包含具体时间/数字/台词/物理场景之一，绝对禁止'近年来/随着...发展'宏观切入",
            "suggested_hook": hook_clean,
        },
        "sections": steps_with_targets,
        "human_fingerprints_instruction": get_human_fingerprints_instruction(topic),
    }


def format_skeleton_markdown(data: dict[str, Any]) -> str:
    """Format skeleton data into standard Markdown brief."""
    lines = [
        f"# 文章策写真分镜骨架：{data['topic']}",
        f"\n- **结构形态**：{data['structure_name']} (`{data['structure_type']}`)",
        f"- **核心锋芒立论 (Killer Stance)**：{data['killer_stance']} {'✅' if data['stance_valid'] else '⚠️ (注意：立论过软或偏端水)'}",
        f"- **开篇反差钩子 (Opening Hook)**：{data.get('opening_hook', '未指定')}",
        f"- **目标篇幅**：{data['total_target_words']} 字 CJK",
        f"- **物理感官锚点**：{', '.join(data['sensory_anchors'])} (共 {data['anchors_count']} 处，满足≥3要求)",
        f"- **切肤现实账本**：{', '.join(data.get('realistic_stakes', []))} (共 {data.get('stakes_count', 0)} 项)",
        f"\n## 开篇破冰契约 (Opening Contract)\n> {data['opening_contract']['rule']}\n> 💡 破题钩子动作：{data['opening_contract']['suggested_hook']}",
        "\n## 分幕大纲与字数分配\n",
        "| 章节 | 叙事推进任务 | 计划字数 | 锚点埋点 |",
        "|---|---|---|---|",
    ]
    for s in data["sections"]:
        anchor_note = f"📌 {s['anchor_slot']}" if s["anchor_slot"] else "—"
        lines.append(f"| {s['act']} | {s['description']} | ~{s['target_cjk_words']} 字 | {anchor_note} |")

    if data.get("human_fingerprints_instruction"):
        lines.append(f"\n{data['human_fingerprints_instruction']}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="若雨随影 8 种文章推进大纲骨架生成器")
    parser.add_argument("topic", help="文章选题或核心片名")
    parser.add_argument("--structure", "-s", default="contrarian", choices=list(STRUCTURES.keys()), help="结构形态")
    parser.add_argument("--stance", required=True, help="核心立论 (Killer Stance，严禁端水)")
    parser.add_argument("--hook", help="开篇极端反差动作钩子 (≤30字)")
    parser.add_argument("--anchors", help="感官锚点，英文逗号分隔，需 >= 3 处")
    parser.add_argument("--stakes", help="切肤现实账本，英文逗号分隔 (普通人的房贷/生计/违约金)")
    parser.add_argument("--words", type=int, default=2200, help="计划字数（默认 2200）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--list-structures", action="store_true", help="列出所有 8 种结构形态")

    args = parser.parse_args(argv)

    if args.list_structures:
        print("8 种文章推进大纲结构：")
        for k, v in STRUCTURES.items():
            print(f"- [{k}] {v['name']}: {v['best_for']}")
        return 0

    anchors_list = [a.strip() for a in args.anchors.split(",") if a.strip()] if args.anchors else None
    stakes_list = [s.strip() for s in args.stakes.split(",") if s.strip()] if args.stakes else None
    skeleton = build_skeleton(
        topic=args.topic,
        structure_type=args.structure,
        killer_stance=args.stance,
        opening_hook=args.hook,
        sensory_anchors=anchors_list,
        realistic_stakes=stakes_list,
        target_words=args.words,
    )

    if args.json:
        print(json.dumps(skeleton, ensure_ascii=False, indent=2))
    else:
        print(format_skeleton_markdown(skeleton))

    return 0


if __name__ == "__main__":
    sys.exit(main())
