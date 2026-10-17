#!/usr/bin/env python3
"""零 Token 本地规则粗筛模块 (filter.py)
硬性剔除：纯饭圈打榜、纯体育比分、纯数码硬件、涉政公文，
将每次采集的几百条数据零成本压缩到 40~60 条高价值社会/人物/商业议题。
"""
from __future__ import annotations

import re
from typing import Any

# 1. 纯饭圈 / 应援 / 营业 / 美貌
RE_FANDOM = re.compile(
    r"(生日快乐|新歌首发|空降一位|红毯造型|神仙同框|路透图|美貌营业|营业照|打榜|控评|"
    r"大片释出|同框生图|发色|生图|杂志封面|美照|舞台直拍|杀青特辑|开机大吉|粉丝福利|打call)"
)

# 2. 纯体育比分与赛事进程
RE_SPORTS = re.compile(
    r"(\d+[-比]\d+|战胜|险胜|绝杀|晋级八强|无缘四强|总冠军|比分|首发名单|赛程公布|"
    r"逆转取胜|大胜|惨败|夺冠|小组赛|积分榜|欧冠|英超|NBA|西甲|法网|温网|中超|亚冠|男足|女足)"
)

# 3. 纯数码硬件参数与游戏维护
RE_DIGITAL_GAME = re.compile(
    r"(跑分曝光|骁龙|天玑|更新日志|固件推送|配置参数|首发评测|游戏公测|停服维护|"
    r"开箱视频|版本更新|体验服|显卡|内存条|固态硬盘|补丁更新|S16|季前赛)"
)

# 4. 涉政公文、官方文件、时政宏观与楼市通报红线
RE_POLITICAL = re.compile(
    r"(中央政治局|求是杂志|重要文章|考察调研|国务院常务会议|国家发改委|全国人大|"
    r"全国政协|国家网信办|重大会议|总书记|中央纪委|深化改革|专项规划|规划纲要|"
    r"楼市新政|四大一线城市|住建部|宏观政策|部委|新华社文化随笔|政府工作报告|"
    r"外交部|国防部|台办|两岸|台海|军方|演练|阅兵|战备|巡航)"
)

# 5. 微信公域限流/封杀与严重刑事负能量敏感词（公域推荐流断崖归零）
RE_WECHAT_CENSORED_RISK = re.compile(
    r"(19禁|床戏|封杀|死刑|骨灰|枪毙|碎尸|强奸|乱伦|暴毙|大尺度|露骨|色情|低俗)"
)

# 6. 纯非垂直民生纠纷与琐碎维权（非影视垂类，微信公域推荐断流，如保费扣款/物业退费）
RE_CIVILIAN_DISPUTE = re.compile(
    r"(弹窗.*(扣费|扣款|保费|扣钱)|保险.*(扣费|套路|退费|保单)|劳动纠纷|物业费|维权.*(退费|退款)|电信诈骗|消费套路|退还保费|医患纠纷|违章扣分)"
)

# 7. 纯泛科技清谈与软硬件评测（无具体名利场人物与影视作品）
RE_GENERIC_TECH = re.compile(
    r"(AI.*(替代|颠覆|取代|发展|前景|是否会)|如何看待AI|大模型|发布新功能|参数对比|算法评测|算力芯片|数码评测|科技论坛|架构升级|开发框架)"
)

# 8. 日常无聊资讯/天气节气
RE_TRIVIAL = re.compile(
    r"(天气预报|降温提醒|穿衣指南|明日天气|今日立秋|今日处暑|节气快乐|早安|晚安|限行尾号)"
)

# 影视/文娱/演艺/名利场垂直核心关键词（强正向加分 +45）
RE_VERTICAL_ENTERTAINMENT = re.compile(
    r"(电影|电视剧|演员|导演|明星|艺人|老戏骨|名利场|富豪|大佬|对赌|商海|破产|塌房|豪门|票房|上映|角色|演艺|娱乐|手艺人|老艺术家|退市|巨亏|还债|剧组|影帝|影后|神作|烂片|戏骨|替身|配音|通稿|片酬|台词|演技|院线|新片|老片|翻拍|首映)"
)

# 正向加分关键词（现实人情、利益账本、反差争议、时代眼泪）
RE_BOOST = re.compile(
    r"(破产|清算|退网|人设|豪门|巨亏|还债|欠薪|对赌|翻车|争议|离婚|塌房|老戏骨|"
    r"晚年|演员|票房|导演|解约|索赔|欺诈|停业|撤档|裁员|暴跌|被执行)"
)


def is_noise(title: str, desc: str = "") -> tuple[bool, str]:
    text = f"{title} {desc}".strip()
    if len(title) < 5:
        return True, "title_too_short"
    if RE_POLITICAL.search(text):
        return True, "political_redline"
    if RE_WECHAT_CENSORED_RISK.search(text):
        return True, "wechat_censored_risk"
    if RE_FANDOM.search(text):
        return True, "fandom_pr"
    if RE_SPORTS.search(text):
        return True, "pure_sports"
    if RE_DIGITAL_GAME.search(text):
        return True, "digital_hardware_game"
    if RE_TRIVIAL.search(text):
        return True, "trivial_weather"
    
    # 纯民生维权或科技清谈，且完全不属于影视娱乐垂直领域的，直接初筛剔除
    if RE_CIVILIAN_DISPUTE.search(text) and not RE_VERTICAL_ENTERTAINMENT.search(text):
        return True, "civilian_dispute_irrelevant"
    if RE_GENERIC_TECH.search(text) and not RE_VERTICAL_ENTERTAINMENT.search(text):
        return True, "generic_tech_irrelevant"

    return False, ""


def filter_candidates(raw_items: list[dict[str, Any]], target_min: int = 35, target_max: int = 40) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """对原始数据做零 Token 正则初筛，并按权重与启发式相关度截取 35~40 条最优质社会/文娱/商业议题"""
    cleaned: list[dict[str, Any]] = []
    noise_stats: dict[str, int] = {}

    for item in raw_items:
        title = item["title"]
        desc = item.get("desc", "")
        drop, reason = is_noise(title, desc)
        if drop:
            noise_stats[reason] = noise_stats.get(reason, 0) + 1
            continue

        heuristic_score = 40.0
        # 平台权重加权
        heuristic_score += item.get("weight", 1.0) * 15
        
        # 排名优先（前10名加分）
        rank = item.get("rank_position", 50)
        if rank <= 5:
            heuristic_score += 20
        elif rank <= 15:
            heuristic_score += 12
        elif rank <= 30:
            heuristic_score += 5
        
        # 影视/演艺/名利场垂类强加权 (+45分，确保影视长文核心阵地)
        if RE_VERTICAL_ENTERTAINMENT.search(f"{title} {desc}"):
            heuristic_score += 45
        elif RE_BOOST.search(f"{title} {desc}"):
            heuristic_score += 25
            
        item_copy = dict(item)
        item_copy["heuristic_score"] = heuristic_score
        cleaned.append(item_copy)

    # 排序：按本地启发分降序
    cleaned.sort(key=lambda x: x["heuristic_score"], reverse=True)
    
    # 截取 35~40 条最佳候选送入 LLM
    final_selected = cleaned[:target_max] if len(cleaned) > target_max else cleaned

    stats = {
        "raw_count": len(raw_items),
        "filtered_out_count": len(raw_items) - len(cleaned),
        "noise_breakdown": noise_stats,
        "valid_count": len(cleaned),
        "selected_for_clustering": len(final_selected),
    }

    return final_selected, stats


if __name__ == "__main__":
    from fetcher import fetch_all_core_routes
    raw, fetch_sum = fetch_all_core_routes()
    selected, f_stats = filter_candidates(raw)
    print(f"粗筛完成：原始 {f_stats['raw_count']} 条 ➔ 剔除 {f_stats['filtered_out_count']} 条 ➔ 保留 {f_stats['selected_for_clustering']} 条送入聚类")
    print("噪音剔除明细:", f_stats["noise_breakdown"])
    print("\n精选 Top 5 样本预览:")
    for i, it in enumerate(selected[:5], 1):
        print(f"  {i}. [{it['platform_tier']}:{it['platform']}] #{it['rank_position']} {it['title']} (分: {it['heuristic_score']})")
