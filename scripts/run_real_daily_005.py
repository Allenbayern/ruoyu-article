"""Build runs/2026-09-15/daily-005 (two_article_daily, article-first lane).

Scope: generate the upstream artifacts, drafts, review evidence and delivery
files for two newly selected works, then let the deterministic gates and the
independent read-only L2 review decide the outcome.  This script never
publishes, never touches the Vault and never writes outside its run root.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scripts.generate_daily_001 as base
from article_group.prose_pilot import analyze_text
from article_group.run_gates import COMPLIANCE_GATE_REASON, run_all_gates
from article_group.style_gate import validate_markdown_file

base.ROOT = Path("runs/2026-09-15/daily-005")
ROOT = base.ROOT
CONTRACT = base.CONTRACT
RUN_ID = "2026-09-15/daily-005"
GROUP_ID = "article-group-2026-09-15-001"
CAPTURED_AT = "2026-09-15T22:35:49+08:00"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: str, value: object) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: str, value: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value.rstrip() + "\n", encoding="utf-8")


def ref(path: str) -> dict:
    return {"path": path, "version": "1.0", "sha256": digest(ROOT / path)}


# --------------------------------------------------------------------------
# 0) Discovery radar (R0) — NAS 糖果梦热榜，记录本轮真实命中
# --------------------------------------------------------------------------

RADAR_RECORDS = [
    ("tgmeng-maoyan", "9.7分", "欢迎来龙餐馆", 2),
    ("tgmeng-tencent", "168316", "交锋", 1),
    ("tgmeng-maoyan", "9.8分", "肖申克的救赎", 0),
    ("tgmeng-tencent", "108977", "花开锦绣", 3),
]


# --------------------------------------------------------------------------
# 1) Sources: captured public pages used as evidence
# --------------------------------------------------------------------------

SOURCES = {
    "src-jiaofeng-1905": {
        "source_role": "interview",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "box_office_outcome", "ending"],
        # 专访明确记录创作方法论（现实调研取代套路、师徒关系的取舍），
        # 属于 mechanism 级捕获：按 source_capability 的保守天花板规则，
        # 仅在来源实际记录更强捕获时抬升 —— 此处专访文本确实记录了。
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "dialogue", "mechanism"],
        "source_url": "https://m.1905.com/m/news/vivo/1765580.shtml",
        "source_type": "interview",
        "artifact_path": "sources/a01-1905-jiaofeng-wangxiaoqiang.html",
        "captured_from": "1905电影网专稿（2026-09-14）",
    },
    "src-jiaofeng-sina": {
        "source_role": "self_media",
        "usage_note": "仅用于开播排播、集数与主创署名事实；不用于收视、热度、口碑等评价性内容",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "event_exists",
        "capability_levels": ["event_exists", "character_setup"],
        "source_url": "https://ent.sina.cn/2026-09-06/detail-iniqwnma6512765.d.html",
        "source_type": "self_media_article",
        "artifact_path": "sources/a03-sina-jiaofeng-kaiBo.html",
        "captured_from": "新浪娱乐（2026-09-06 开播报道）",
    },
    "src-jiaofeng-dzwww": {
        "source_role": "commentary",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["mechanism", "dialogue"],
        "source_url": "https://qingdao.dzwww.com/zfpd/zxbd/202609/t20260914_18112614.htm",
        "source_type": "commentary",
        "artifact_path": "sources/a04-dzwww-jiaofeng-review.htm",
        "captured_from": "大众网评论（段继林，2026-09-13）",
    },
    "src-longcanguan-zuojiawang": {
        "source_role": "interview",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "box_office_outcome", "ending"],
        # 同 1905 专访：片名取舍的完整创作逻辑在专访文本中有据可查，
        # 达到 mechanism 级捕获。
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "dialogue", "scene_action", "mechanism"],
        "source_url": "https://www.chinawriter.com.cn/n1/2026/0907/c404005-40794215.html",
        "source_type": "interview",
        "artifact_path": "sources/b01-renminwenyu-wenmuye.html",
        "captured_from": "人民文娱独家专访（2026-09-07，中国作家网转载）",
    },
    "src-longcanguan-rmrb": {
        "source_role": "commentary",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "box_office_outcome", "ending"],
        "source_capability": "mechanism",
        "source_url": "https://paper.people.com.cn/rmrb/pc/content/202609/08/content_30179859.html",
        "source_type": "commentary",
        "artifact_path": "sources/b02-rmrb-yihaiguanlan.html",
        "captured_from": "人民日报 2026-09-08 第20版（艺海观澜）",
    },
}


# --------------------------------------------------------------------------
# 2) Candidate pool + slots
# --------------------------------------------------------------------------

CANDIDATES = [
    {
        "candidate_id": "cand-jiaofeng-wangxiaoqiang-001",
        "work": "交锋",
        "work_title": "交锋",
        "signal": "糖果梦腾讯热榜第2位，168316",
        "signal_source": "tgmeng-tencent",
        "topic_mode": "character",
        "article_mode": "reported_feature",
        "content_map": "A",
        "event_cluster_id": "jiaofeng-guoxue-drama-creation-choice",
        "content_map_label": "新片事件",
        "freshness_window": "same-day",
        "remove_timestamp_test": "pass",
        "evidence_readiness": "high",
        "recommendation": "A",
        "editorial_value_score": 9,
        "reader": "追着《交锋》更新、想知道这部剧为什么不用谍战套路说话的观众",
        "reader_question": "《交锋》编剧为什么要抗拒自己最不擅长的师徒关系",
        "core_question": "《交锋》编剧为什么要抗拒自己最不擅长的师徒关系",
        "angle": "编剧把主角之间的传承关系从套路变成现实质感，再用它撑起20年的隐蔽战线",
        "source_refs": ["src-jiaofeng-1905", "src-jiaofeng-sina", "src-jiaofeng-dzwww"],
        "prior_run_conflict": False,
        "selection_reason": "雷达命中且在播；有编剧专访原文与当期党报文艺评论两份可回读材料，含场景数、剧本字数、人物关系设计与创作取舍",
    },
    {
        "candidate_id": "cand-longcanguan-jiunian-001",
        "work": "欢迎来龙餐馆",
        "work_title": "欢迎来龙餐馆",
        "signal": "猫眼购票评分榜第3位，9.7分",
        "signal_source": "tgmeng-maoyan",
        "topic_mode": "craft",
        "article_mode": "reported_feature",
        "content_map": "B",
        "event_cluster_id": "longcanguan-nine-year-craft-and-name",
        "content_map_label": "作品深度",
        "freshness_window": "fermenting-1-3d",
        "remove_timestamp_test": "pass",
        "evidence_readiness": "high",
        "recommendation": "A",
        "editorial_value_score": 9,
        "reader": "看过或准备看这部电影、想知道导演为什么用九年和一顿饭讲战争的观众",
        "reader_question": "《欢迎来龙餐馆》为什么要删掉片名里的一个字",
        "core_question": "《欢迎来龙餐馆》为什么要删掉片名里的一个字",
        "angle": "一个字的取舍暴露了这部片处理战争与日常的整套方法：把不能抵达的念想留给普通人",
        "source_refs": ["src-longcanguan-zuojiawang", "src-longcanguan-rmrb"],
        "prior_run_conflict": False,
        "selection_reason": "雷达命中且在上映期内；有导演独家专访全文与当期文艺评论，含创作缘起、采风次数、片名取舍、演员训练与叙事方法解释",
    },
]


# --------------------------------------------------------------------------
# 3) Briefs, task cards, task hierarchy
# --------------------------------------------------------------------------

TASK_CARD_REQUIRED_FIELDS = {
    "art-001": (
        "1. **站队点/可转述句**：《交锋》真正立住人物的地方，不是他破了多少案，而是马憩一直在教何春晓怎么自己捅破那层窗户纸。\n"
        "2. **读者已知锚点**：《交锋》正在央视八套和腾讯视频播出、王凯与彭昱畅演一对国安师徒、剧集被讨论“尺度大”。\n"
        "3. **today-hook 理由**：剧集2026年9月6日开播并持续更新，9月14日编剧专访公开了800多个场景与60万字剧本的创作取舍。\n"
        "4. **事实底座**：40集国安题材剧，2026年9月6日在央视八套、腾讯视频、咪咕视频开播；编剧王小枪，总导演姚晓峰；成稿800多个场景、60万字剧本、5到6个关键角色（来源：1905电影网专稿、人民日报）。\n"
        "5. **最强钩子**：编剧起初非常抗拒写师徒关系（与 batch.json 的 review_hook 一致）。\n"
        "- **title_promise**：《交锋》编剧为什么抗拒写师徒关系\n"
        "- **ending_destination**：观众要看的未必是谁输谁赢，而是一个人在没人知道自己名字的地方，还愿不愿意守同一条规矩。\n"
        "\n## 文章结构大纲（H2 目录）\n"
        "## 《交锋》先把一桩泄密案拍成日常\n"
        "## 编剧原本不想写师徒\n"
        "## 二十年跨度靠什么撑住\n"
        "## 群像不是加法，是替观众分配注意力\n"
    ),
    "art-002": (
        "1. **站队点/可转述句**：片名里删掉的那个“到”字，就是这部片对战争的态度——有些念想未必能抵达，但喊出来仍然算数。\n"
        "2. **读者已知锚点**：文牧野执导、沈腾主演、《欢迎来龙餐馆》正在上映。\n"
        "3. **today-hook 理由**：影片2026年8月上映并进入暑期档口碑讨论，导演专访与当期文艺评论同期公开了创作缘起、采风次数和片名取舍。\n"
        "4. **事实底座**：2026年8月上映；文牧野执导，沈腾饰徐福、蒋奇明饰马俊生；酝酿始于2017年《我不是药神》后期；2019年起前后5次赴中东采风；片名从“欢迎来到龙餐馆”删去“到”字（来源：人民文娱专访、人民日报）。\n"
        "5. **最强钩子**：片名原本是“欢迎来到龙餐馆”，最后删掉了那个“到”字（与 batch.json 的 review_hook 一致）。\n"
        "- **title_promise**：《欢迎来龙餐馆》为什么删掉了片名里的一个字\n"
        "- **ending_destination**：能抵达的是一座餐馆，不能保证抵达的是那句念想；这部片把后半句留给了还在等的人。\n"
        "\n## 文章结构大纲（H2 目录）\n"
        "## 《欢迎来龙餐馆》删掉了一个字\n"
        "## 一顿饭的念头用了九年\n"
        "## 剧本里那些具体的饭\n"
        "## 一个字的取舍，决定了这部片怎么处理战争\n"
    ),
}

STRONGEST_HOOKS = {
    "art-001": "王小枪说，他从一开始就非常抗拒写师徒关系",
    "art-002": "这部电影原来的名字是“欢迎来到龙餐馆”",
}


# --------------------------------------------------------------------------
# 4) Material packs
# --------------------------------------------------------------------------

MATERIAL_SPECS = {
    "art-001": {
        "mode": "reported_feature",
        "role": "interview",
        "role": "interview",
        "source_ids": ["src-jiaofeng-1905", "src-jiaofeng-sina", "src-jiaofeng-dzwww"],
        "question": "《交锋》编剧为什么要抗拒自己最不擅长的师徒关系",
        "mechanism": "编剧用现实调研替换谍战套路，师徒传承因此成为20年跨度的支点",
        "facts": [
            {"text": "《交锋》2026年9月6日在央视八套、腾讯视频、咪咕视频开播，共40集", "level": "event_exists", "locator": "新浪娱乐: 开播信息", "source_id": "src-jiaofeng-sina", "plan_kind": "specific_context"},
            {"text": "编剧王小枪、总导演姚晓峰，成稿800多个场景、60万字剧本、5到6个关键角色", "level": "character_setup", "locator": "1905: 编剧专访", "source_id": "src-jiaofeng-1905", "plan_kind": "fact"},
            {"text": "马憩与何春晓的师徒关系是整部剧的重要支点，编剧起初抗拒写师徒关系", "level": "mechanism", "locator": "1905: 编剧专访", "source_id": "src-jiaofeng-1905", "plan_kind": "mechanism"},
            {"text": "主创把《交锋》概括为一场两岸长达20年的猫鼠游戏", "level": "mechanism", "locator": "大众网评论: 类型目标", "source_id": "src-jiaofeng-dzwww", "plan_kind": "mechanism"},
            {"text": "王凯把马憩与林看山的对手戏形容成下棋，谁先露怯谁就输", "level": "dialogue", "locator": "大众网评论: 关系悬念", "source_id": "src-jiaofeng-dzwww", "plan_kind": "relationship"},
        ],
        "by_source": {
            "src-jiaofeng-1905": [
                "编剧王小枪、总导演姚晓峰，成稿800多个场景、60万字剧本、5到6个关键角色",
                "马憩与何春晓的师徒关系是整部剧的重要支点，编剧起初抗拒写师徒关系",
                "马憩做人的准则被写作国家利益高于一切，同时又带着将在外命令有所不受的性格",
                "蒋在珍（吴越饰）的事件入手",
            ],
            "src-jiaofeng-sina": [
                "《交锋》2026年9月6日在央视八套、腾讯视频、咪咕视频开播，共40集",
                "编剧王小枪",
            ],
            "src-jiaofeng-dzwww": [
                "主创把《交锋》概括为一场两岸长达20年的猫鼠游戏",
                "王凯把马憩与林看山的对手戏形容成下棋，谁先露怯谁就输",
            ],
        },
        "audience": "正在追《交锋》的剧集观众",
    },
    "art-002": {
        "mode": "reported_feature",
        "role": "interview",
        "role": "interview",
        "source_ids": ["src-longcanguan-zuojiawang", "src-longcanguan-rmrb"],
        "question": "《欢迎来龙餐馆》为什么要删掉片名里的一个字",
        "mechanism": "创作缘起、采风经验和片名取舍共同决定这部片把战争写成需要吃饭的日常",
        "facts": [
            {"text": "《欢迎来龙餐馆》2026年8月上映，文牧野执导，沈腾饰徐福、蒋奇明饰马俊生", "level": "event_exists", "locator": "专访: 上映与主创信息", "source_id": "src-longcanguan-zuojiawang", "plan_kind": "specific_context"},
            {"text": "创作念头起于2017年《我不是药神》后期制作期间，2019年起前后5次赴中东采风", "level": "character_setup", "locator": "专访: 创作缘起与采风", "source_id": "src-longcanguan-zuojiawang", "plan_kind": "fact"},
            {"text": "片名原本是“欢迎来到龙餐馆”，最后删掉了“到”字", "level": "mechanism", "locator": "专访: 片名取舍", "source_id": "src-longcanguan-zuojiawang", "plan_kind": "mechanism"},
        ],
        "by_source": {
            "src-longcanguan-zuojiawang": [
                "影片2026年8月上映，文牧野执导",
                "创作念头起于2017年（9年前）《我不是药神》后期制作期间",
                "2019年起前后5次赴中东采风勘景",
                "片名原本是“欢迎来到龙餐馆”，最后删掉了“到”字",
                "片中设计4场极具象征意义的饭，将近50道菜肴搬上银幕",
                "沈腾提前进组，每天练习六七个小时厨艺；奥马尔·谢里夫提前4个月学习",
                "“龙抬头”（松鼠桂鱼）出锅后浇汁的黄金窗口期仅20多秒",
            ],
            "src-longcanguan-rmrb": [
                "人民日报专栏提到沈腾饰演的徐福和蒋奇明饰演的马俊生",
                "该专栏把中国式的“吃饭哲学”视为影片从战争暴力循环里突围的表达",
            ],
        },
        "audience": "看过或准备看这部电影的普通观众",
    },
}


# --------------------------------------------------------------------------
# 5) Bodies
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# 6) Review evidence + delivery
# --------------------------------------------------------------------------

TITLES = {
    "art-001": [
        ("《交锋》编剧为什么抗拒写师徒关系", "创作取舍"),
        ("《交锋》不用枪战和暗号，靠什么撑20年", "类型突破"),
        ("一部国安剧为什么先拍一桩泄密案", "开场设计"),
    ],
    "art-002": [
        ("《欢迎来龙餐馆》为什么删掉了片名里的一个字", "片名取舍"),
        ("九年、5次采风，文牧野把战争收回到一顿饭", "创作过程"),
        ("《欢迎来龙餐馆》里将近50道菜，不是背景板", "叙事符号"),
    ],
}

SOURCE_IDS = {
    "art-001": ["src-jiaofeng-1905", "src-jiaofeng-sina", "src-jiaofeng-dzwww"],
    "art-002": ["src-longcanguan-zuojiawang", "src-longcanguan-rmrb"],
}

MODES = {"art-001": "reported_feature", "art-002": "reported_feature"}

RULE_CLAIMS = {
    "art-001": [
        {"claim_id": "c1", "claim_level": "event_exists", "source_refs": ["src-jiaofeng-sina"], "source_locators": ["新浪娱乐: 9月6日央视八套开播、40集、腾讯视频与咪咕视频同步"]},
        {"claim_id": "c2", "claim_level": "dialogue", "source_refs": ["src-jiaofeng-1905"], "source_locators": ["1905: 编剧专访（抗拒写师徒）"]},
        {"claim_id": "c3", "claim_level": "character_setup", "source_refs": ["src-jiaofeng-1905"], "source_locators": ["1905: 编剧专访（800场景/60万字/5-6个关键角色）"]},
        {"claim_id": "c4", "claim_level": "mechanism", "source_refs": ["src-jiaofeng-dzwww"], "source_locators": ["大众网评论: 20年跨度与关系悬念"]},
    ],
    "art-002": [
        {"claim_id": "c1", "claim_level": "event_exists", "source_refs": ["src-longcanguan-zuojiawang"], "source_locators": ["专访: 上映与主创信息"]},
        {"claim_id": "c2", "claim_level": "dialogue", "source_refs": ["src-longcanguan-zuojiawang"], "source_locators": ["专访: 片名取舍"]},
        {"claim_id": "c3", "claim_level": "scene_action", "source_refs": ["src-longcanguan-zuojiawang"], "source_locators": ["专访: 沈腾厨艺训练与片中菜品"]},
        {"claim_id": "c4", "claim_level": "mechanism", "source_refs": ["src-longcanguan-rmrb"], "source_locators": ["人民日报: 美食与战争平行叙事与吃饭哲学"]},
    ],
}


# --------------------------------------------------------------------------
# 7) Portfolio gate + batch manifest + preflight
# --------------------------------------------------------------------------



# --------------------------------------------------------------------------
# Run data (extracted from generator logic, 2026-09-15)
REJECTED_PRIOR_WORKS = ["空枪", "奥德赛", "蜘蛛侠：崭新之日", "早春晴朗", "兰香如故", "玩具总动员5"]

SLOT_DECISIONS = [
    {
        "slot": 1,
        "article_id": "art-001",
        "candidate_id": "cand-jiaofeng-wangxiaoqiang-001",
        "decision": "selected",
        "event_cluster_id": "jiaofeng-guoxue-drama-creation-choice",
    },
    {
        "slot": 2,
        "article_id": "art-002",
        "candidate_id": "cand-longcanguan-jiunian-001",
        "decision": "selected",
        "event_cluster_id": "longcanguan-nine-year-craft-and-name",
    },
]

# --------------------------------------------------------------------------

BODIES = {
        "art-001": """## 《交锋》先把一桩泄密案拍成日常

《交锋》第1集开场，蒋在珍在会议室墙壁里发现监听设备。接下来她平静地拿着行李走向机场，又快速完成换装；几小时后，她死在飞往中国澳门的航班上。

这是编剧王小枪给这部40集国安剧写的第一段戏。它在几分钟内交代了这个故事所处的环境：在这里，先暴露的人先出局，情绪和动作都得压到最低。剧集2026年9月6日在央视八套、腾讯视频、咪咕视频开播，故事站在1994年起20多年两岸关系的时代背景里。

## 编剧原本不想写师徒

马憩是何春晓的师父，也是《交锋》的核心人物。王小枪说，他从一开始就非常抗拒写师徒关系，因为他想在谍战题材里提供一些以前没有过的人物关系。

调研把这个念头掰了回来。他发现现实生活里本来就有师徒传承，尤其是上世纪90年代，很讲究师父带徒弟。既然写的是现实题材，就没有必要为了极端地推陈出新，不顾真实生活的质感。

于是师徒关系被留下，但写法换了。王小枪说，90年代师父带徒弟有很多有趣的细节：你问1加1等于几，他绝对不直接告诉你等于2，而是绕着说很多种方式，像捅破一层窗户纸那样，让对方自己去感悟。两个人的相处也不只有一种状态，有时候像师徒，有时候像哥们，甚至会像恋人，也有像战友的时候。

## 二十年跨度靠什么撑住

《交锋》的成稿是800多个场景、60万字剧本、5到6个关键角色。王小枪说，这次创作最大的挑战是节奏：真实情报工作不能慢，慢了会错过线索；也不能太快，快了会引起别人注意。

他和团队为此专门做过调研，抓到过一个细节：很多年轻观众真的喜欢一部剧的时候，是不会用倍速的。倒推回去，不用倍速的剧集需要情节密度高、节奏快，还要有全息结构。

剧里反复出现的阻力也来自这个判断。何春晓和锦兰因为工作和生活要发生大量交集，而这种交集一旦长达几十年，中间不会只有胜利的喜悦。王小枪说，大部分时间其实是漫长的枯燥；某个阶段人也会对自己的工作产生动摇，在成就感迟迟不来的时候，犹豫、无奈、烦躁都会出现。

## 群像不是加法，是替观众分配注意力

《交锋》从一开始就确定了群像结构。王小枪此前在《对手》《黄雀》里也偏爱这种写法。这次以马憩、何春晓、林看山、锦兰、秋天、魏广进、朱应甲等五六个人为核心，其余角色像小珍珠一样散落在周围。

群像的作用不是堆人名，而是替观众分配注意力。王小枪透露，后续剧情在每个节点都会有人物的高光，每个人物身上也都会有大的变化。他说，这可能也彰显了现实生活中反间谍工作的复杂性。之前埋下的很多东西，都是在为某个节点的爆发做准备。

王凯把马憩和林看山的对手戏形容成下棋：“谁先露怯谁就输。”这句话点出了这部剧真正的紧张感来源：双方都知道对方是谁，却要维持表面的社会交往，试探、确认和误导都藏在日常接触里。主创在推介里把这部剧概括成一场两岸长达20年的猫鼠游戏，同时强调它最终是一场关乎国家安全的人性交锋。

这种设计也带来了取舍。蒋在珍的故事在第1集就结束了，观众还在猜她是否会有后续，编剧已经把她写完了。这个处理恰好表现了那个时代背景下情报工作者的处境：没有主角光环，也没有爽文节奏。

## 抗住热度的诱惑，才有可能写长

王小枪提到过一个反复出现的问题：创作时是不是要为了迎合某些观众。他的答案是，刚开始时不要太鸡贼，或者说不要太功利。

他坦言自己有一段时间很反感听到“热度”这个词，觉得这个词好像会影响创作。但他也承认，不光是《交锋》，包括同时期其他播出的长剧，他还是希望热度能够高一些，让盘子更热、市场更丰富，将来才继续会有创作长剧的机会。

所以《交锋》眼下能确认的判断是：它把谍战剧的戏剧渲染换成了现实调研，把师徒关系从套路改写成了具体的人。至于后续每个节点的高光能不能兑现、这套群像能否一直撑住观众的注意力，得看剧集自己怎么走完。观众要看的未必是谁输谁赢，而是一个人在没人知道自己名字的地方，还愿不愿意守同一条规矩。""",
        "art-002": """## 《欢迎来龙餐馆》删掉了一个字

这部电影原来的名字是“欢迎来到龙餐馆”。定名之前，文牧野把那个“到”字删掉了。一部讲中东战火的电影，为什么先要在片名上做减法。

他给出的理由很具体：“到”带有抵达的确定性，战争年代，很多人心里怀揣念想，却未必能够抵达。而“来”是呼唤，是一份念想，向每一个漂泊流离的人发出邀约。这也是《欢迎来龙餐馆》对战争的态度，一个字的取舍把它说完了。

## 一顿饭的念头用了九年

文牧野最开始想拍这个故事，是在9年前。那时他的第一部长片《我不是药神》刚进入后期制作，他注意到一些新闻纪实：一批远赴海外谋生的华人留在异国开餐馆，靠着灶台烟火打破地域隔阂，在动荡环境里和当地人建立羁绊。

这个念头没有停在想象里。从2019年第一次踏足中东开始，文牧野前后5次奔赴当地采风勘景，最初甚至希望能直接在中东实景拍摄，最大程度还原地域质感。

采风改变了事情的重量。他走进难民营，探访收养战争孤儿的孤儿院，坐下来和当地的大人、孩子平等交谈。有一个失去一只手的孩子语气轻松地和他聊天，说起亲人在轰炸中离去，然后提到自己小小的愿望：“我想要个游戏机。”孩子告诉他，就算只剩一只手，自己依旧可以玩游戏机。

文牧野说，可能轰炸刚刚过去两天，孩子拿到一颗糖，一边吃糖，一边看着自己残缺的手臂，炮火连天的生活是他的日常。“好好吃饭”这四个字，就是在这里完成意义蜕变的。和平年代，家人通话里随口一句“好好吃饭”是稀松平常的寒暄；在中东，它是强烈、珍贵、遥不可及的愿望。

## 剧本里那些具体的饭

《欢迎来龙餐馆》2026年8月上映，文牧野执导，沈腾饰演厨师徐福，蒋奇明饰演餐馆经理马俊生。为了把将近50道菜肴呈现在银幕上，剧组把大量精力花在制作调研和细节拍摄上，片中四场宴席各自跟随人物的处境变化。

拍摄的细致程度可以从一道菜看出来。片中的“龙抬头”是一道松鼠桂鱼，出锅后浇汁的黄金窗口期只有20多秒，为了抓住食材最鲜活的瞬间，几秒的素材往往要拍上半天。

演员为此付出的练习也是具体的。沈腾提前进组，每天练习六七个小时厨艺，切菜、颠勺、炒菜的大量镜头基本都是本人实拍；饰演孤儿赛夫的埃及演员奥马尔·谢里夫提前4个月开始学习，到拍摄时颠勺、切菜都已不在话下。

文牧野把这组关系概括为美食与战争：一暖一冷，一柔一烈，两股力量并行交织。影片没有把镜头重心放在宏大的战场厮杀上，而是把中华美食当成核心叙事符号。

## 一个字的取舍，决定了这部片怎么处理战争

徐福和马俊生是两种不同的中国人。徐福是为养家还债来到中东的厨师，起初只想赚钱自保，信奉“老外打仗跟我有什么关系”；马俊生是一心想在当地闯出一片天的务工青年，单纯、博爱、坚定，看似柔软实则有棱有角。两人相遇后开出的龙餐馆，成了乱世里短暂隔绝硝烟的飞地。

文牧野在专访里说，全片高潮的转折点出现在马俊生的离去。他解释，马俊生代表人内心最纯粹、感性的那部分自我，当他去世，徐福灵魂深处有一部分感觉也随之而去，同时这份空缺又被马俊生的纯良填补上。徐福走向救人的抉择时没有慷慨激昂的宣言，只留下一句：“我去趟菜店，买菜。”

在文牧野的解释里，这句台词解释了片名为什么最后留下了“来”。能抵达的是一座餐馆，不能保证抵达的是那句念想；这部片把后半句留给了还在等的人。片名读起来是一个邀请，而不是一份承诺。

## 九年之后，他把结论交回给普通人

文牧野谈到徐福和马俊生的善举时说，很多后来被世人称作英雄的举动，在发生的瞬间，只是纯粹感性的本能冲动。事后回想可能会害怕，但抉择来临的那一刻，来不及权衡利弊，只遵从心底的善良。

他对“现实主义”的理解也接近这个意思。他说自己只是讲故事的人，现实主义是电影的材质，就像造车时用的铜、钢、铝合金只是材料，车子本身才是核心；就算以后拍科幻片，探讨的依旧是与人相关的现实命题。

所以《欢迎来龙餐馆》目前最清楚的判断不是它拍得多苦，而是它把战争片常用的宏大视角收回到一顿饭上。九年、5次采风、将近50道菜，这些数字最后都指向同一件事：普通人守住心里那点善意，已经是乱世里最不容易的部分。至于它能不能让每个观众都接受这个结论，只有看完电影的人自己知道。""",
}


BRIEFS = {
    "art-001": """# Writing Brief

production_contract: article-first-v1
brief_contract: writing-brief-v2
title_contract: title-pack-v1
legacy_compatibility: false
run_contract_required: true
article_id: art-001
candidate_id: cand-jiaofeng-wangxiaoqiang-001
article_mode: reported_feature
required_source_roles: [interview]
topic_version: 1
content_map: A
reference_shape: viewing_commentary
core_question: 《交锋》编剧为什么要抗拒自己最不擅长的师徒关系
target_reader: 追着《交锋》更新、想知道这部剧为什么不用谍战套路说话的观众
editorial_angle: 编剧把主角之间的传承关系从套路变成现实质感，再用它撑起20年的隐蔽战线
body_route: 先用第一集的具体事件进入，再写编剧对师徒关系的抗拒与调研，最后回到群像结构如何分配注意力
evidence_boundary: 只写编剧专访和当期文艺评论中已公开的创作信息、人物关系设计与剧集事实，不写未观看的后续剧情、结局和观众整体口碑
required_hard_information: 2026年9月6日开播；40集；央视八套、腾讯视频、咪咕视频；编剧王小枪、总导演姚晓峰；800多个场景、60万字剧本、5到6个关键角色
unsupported_boundary: 不能把编剧的创作说明当成剧集质量结论，不能写未公开的后续反转和结局
""",
    "art-002": """# Writing Brief

production_contract: article-first-v1
brief_contract: writing-brief-v2
title_contract: title-pack-v1
legacy_compatibility: false
run_contract_required: true
article_id: art-002
candidate_id: cand-longcanguan-jiunian-001
article_mode: reported_feature
required_source_roles: [interview]
topic_version: 1
content_map: B
reference_shape: viewing_commentary
core_question: 《欢迎来龙餐馆》为什么要删掉片名里的一个字
target_reader: 看过或准备看这部电影、想知道导演为什么用九年和一顿饭讲战争的观众
editorial_angle: 一个字的取舍暴露了这部片处理战争与日常的整套方法：把不能抵达的念想留给普通人
body_route: 从片名取舍进入，再写九年酝酿与五次采风，接着写剧本里具体的饭，最后收回到这个字为什么重要
evidence_boundary: 只写导演专访、影片报道与当期文艺评论中已公开的创作信息、上映事实和主创表述，不写未经观看的具体场面细节和观众整体评价
required_hard_information: 2026年8月上映；文牧野执导；沈腾饰徐福、蒋奇明饰马俊生；念头起于2017年；2019年起前后5次赴中东采风；片名删去“到”字
unsupported_boundary: 不能替观众给出观影体验结论，不能把导演阐释写成影片主题的唯一答案
""",
}


BRIEF_SPECS = [
        (
            "art-001",
            "reported_feature",
            "interview",
            "《交锋》编剧为什么要抗拒自己最不擅长的师徒关系",
            "src-jiaofeng-1905",
        ),
        (
            "art-002",
            "reported_feature",
            "interview",
            "《欢迎来龙餐馆》为什么要删掉片名里的一个字",
            "src-longcanguan-zuojiawang",
        ),
]


CONTENT_RECORD_ARGS = [
    {
        "aid": "art-001",
        "mode": "reported_feature",
        "role": "interview",
        "core_object": "《交锋》的编剧取舍与师徒关系",
        "question": "《交锋》编剧为什么要抗拒自己最不擅长的师徒关系",
        "mechanism": "编剧用现实调研替换谍战套路，师徒传承因此成为20年跨度的支点",
        "takeaway": "《交锋》把谍战剧的戏剧渲染换成了现实调研，把师徒关系从套路改写成了具体的人。",
        "hard":         [
            {"information_id": "i1", "text": "2026年9月6日开播，央视八套、腾讯视频、咪咕视频", "kind": "specific_context", "body_locator": "p2", "source_refs": ["src-jiaofeng-sina"], "source_locators": ["新浪娱乐: 9月6日央视八套开播、腾讯视频与咪咕视频同步"], "independence_key": "release"},
            {"information_id": "i2", "text": "800多个场景、60万字剧本、5到6个关键角色", "kind": "fact", "body_locator": "p6", "source_refs": ["src-jiaofeng-1905"], "source_locators": ["1905: 编剧专访（800场景/60万字/5-6个关键角色）"], "independence_key": "script-scale"},
            {"information_id": "i3", "text": "编剧起初抗拒写师徒关系", "kind": "mechanism", "body_locator": "p3", "source_refs": ["src-jiaofeng-1905"], "source_locators": ["1905: 编剧专访（抗拒写师徒）"], "independence_key": "mentor-resistance"},
            {"information_id": "i4", "text": "王凯把马憩与林看山的对手戏形容成下棋", "kind": "fact", "body_locator": "p11", "source_refs": ["src-jiaofeng-dzwww"], "source_locators": ["大众网评论: 关系悬念（下棋/谁先露怯谁就输）"], "independence_key": "chess-metaphor"},
        ],
        "bases":         [
            {"locator": "p4", "fact_or_scene": "调研发现90年代讲究师父带徒弟", "explanation": "现实质感取代了刻意求新"},
            {"locator": "p7", "fact_or_scene": "观众喜欢一部剧时不会用倍速", "explanation": "节奏要求来自观众行为调研"},
        ],
        "boundary": "当前来源不能证明后续剧情质量、结局和观众整体口碑。",
        "source_ids":         ["src-jiaofeng-1905", "src-jiaofeng-sina", "src-jiaofeng-dzwww"],
    },
    {
        "aid": "art-002",
        "mode": "reported_feature",
        "role": "interview",
        "core_object": "《欢迎来龙餐馆》的片名取舍与创作过程",
        "question": "《欢迎来龙餐馆》为什么要删掉片名里的一个字",
        "mechanism": "创作缘起、采风经验和片名取舍共同决定这部片把战争写成需要吃饭的日常",
        "takeaway": "片名删掉的那个字，就是这部片对战争的态度：不能保证抵达，但邀请本身仍然算数。",
        "hard":         [
            {"information_id": "i1", "text": "2026年8月上映，文牧野执导", "kind": "specific_context", "body_locator": "p7", "source_refs": ["src-longcanguan-zuojiawang"], "source_locators": ["专访: 上映与主创信息"], "independence_key": "release"},
            {"information_id": "i2", "text": "2019年起前后5次赴中东采风", "kind": "fact", "body_locator": "p4", "source_refs": ["src-longcanguan-zuojiawang"], "source_locators": ["专访: 创作缘起与采风"], "independence_key": "field-trips"},
            {"information_id": "i3", "text": "片名删掉了“到”字", "kind": "mechanism", "body_locator": "p1", "source_refs": ["src-longcanguan-zuojiawang"], "source_locators": ["专访: 片名取舍"], "independence_key": "title-change"},
        ],
        "bases":         [
            {"locator": "p5", "fact_or_scene": "失去一只手的孩子说想要个游戏机", "explanation": "采风改变了“好好吃饭”的分量"},
            {"locator": "p11", "fact_or_scene": "徐福只留下一句“我去趟菜店，买菜”", "explanation": "人物抉择被写成日常动作"},
        ],
        "boundary": "当前来源不能代替观众给出观影体验结论，也不能证明影片主题只有一种解释。",
        "source_ids":         ["src-longcanguan-zuojiawang", "src-longcanguan-rmrb"],
    }
]


BATCH_SPECS = {
        "art-001": (
            "cand-jiaofeng-wangxiaoqiang-001",
            "交锋",
            "jiaofeng-guoxue-drama-creation-choice",
            ["src-jiaofeng-1905", "src-jiaofeng-sina", "src-jiaofeng-dzwww"],
            "A",
            "A",
        ),
        "art-002": (
            "cand-longcanguan-jiunian-001",
            "欢迎来龙餐馆",
            "longcanguan-nine-year-craft-and-name",
            ["src-longcanguan-zuojiawang", "src-longcanguan-rmrb"],
            "B",
            "B",
        ),
}


if __name__ == "__main__":
    import sys

    from scripts.daily_engine import build_run

    build_run(sys.modules[__name__])
