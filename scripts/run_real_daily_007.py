"""Build runs/2026-09-16/daily-007 (two_article_daily, article-first lane).

选题来源：按"读者面选题检查表"（读者/落点/情绪/删节点测试/社交原动力）重筛
2026-09-16 热榜。art-001 借"无量仙翁式"选题法（热门剧+空白角色+集体情绪），
art-002 借"借热点赋能"（剧名同质化观察 + 当日热榜讨论）。读者面零自证，
证据归因全部在后台账本。
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

base.ROOT = Path("runs/2026-09-16/daily-007")
ROOT = base.ROOT
CONTRACT = base.CONTRACT
RUN_ID = "2026-09-16/daily-007"
GROUP_ID = "article-group-2026-09-16-002"
CAPTURED_AT = "2026-09-16T02:10:00+08:00"


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
    ("tgmeng-douyin", "9053953", "兰香如故热度破30000", 14),
    ("tgmeng-weibo", "148772", "兰香如故腾讯今年第四部破万剧", 6),
    ("tgmeng-douyin", "8004837", "兰香如故抖音追剧团", 22),
    ("tgmeng-douyin", "7779575", "兰香如故杜翠雀好有心机", 27),
    ("tgmeng-weibo", "99507", "长剧起名 观众已经学杂了", 17),
]


# --------------------------------------------------------------------------
# 1) Sources: captured public pages used as evidence
# --------------------------------------------------------------------------

SOURCES = {
    "src-baijia-zhh": {
        "source_role": "media_report",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "https://baijiahao.baidu.com/s?id=1876114967412390532",
        "source_type": "media_report",
        "artifact_path": "sources/a01-baijia-zhh.html",
        "captured_from": "百家号·落雪欢江离生（2026-09-12，郑合惠子杜翠雀角色解读）",
    },
    "src-sina-peijue": {
        "source_role": "media_report",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "https://finance.sina.cn/2026-09-15/detail-inirwmvy8763487.d.html",
        "source_type": "media_report",
        "artifact_path": "sources/a02-sina-peijue.html",
        "captured_from": "封面新闻（2026-09-15，兰香如故配角CP争议）",
    },
    "src-china-zhh": {
        "source_role": "media_report",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "https://kan.china.com/qd/mkan/article/5040342.html",
        "source_type": "media_report",
        "artifact_path": "sources/a03-china-zhh.html",
        "captured_from": "中国网·网易（2026-09-15，杜翠雀再出圈凭什么）",
    },
    "src-rmrb-yuzhiwei": {
        "source_role": "commentary",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "http://ent.people.com.cn/n1/2026/0331/c1012-40691992.html",
        "source_type": "commentary",
        "artifact_path": "sources/b01-rmrb-yuzhiwei.html",
        "captured_from": "人民日报锐见（2026-03-31，古装偶像剧的预制味）",
    },
    "src-sohu-cuique": {
        "source_role": "media_report",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "https://m.sohu.com/a/1076490178_122744083",
        "source_type": "media_report",
        "artifact_path": "sources/a04-sohu-cuique.html",
        "captured_from": "搜狐（2026-09-15，兰香仅凭画上一株翠雀花保住婚事）",
    },
    "src-sina-renwu": {
        "source_role": "commentary",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "https://www.sina.cn/news/detail/5343073388987850.html",
        "source_type": "commentary",
        "artifact_path": "sources/a05-sina-renwu.html",
        "captured_from": "新浪娱乐（2026-09-14，杜翠雀人物分析与演员微博）",
    },
    "src-sina-rufu": {
        "source_role": "commentary",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "https://www.sina.cn/news/detail/5343038862000341.html",
        "source_type": "commentary",
        "artifact_path": "sources/a06-sina-rufu.html",
        "captured_from": "新浪娱乐（2026-09-14，杜翠雀入府自我介绍分析）",
    },
    "src-xinmin-juming": {
        "source_role": "commentary",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "https://wap.xinmin.cn/newspaper/xmwb/243703.html",
        "source_type": "commentary",
        "artifact_path": "sources/b03-xinmin-juming.html",
        "captured_from": "新民晚报（2026-07-23，好作品不该被怪名字耽误）",
    },
    "src-thepaper-shiyi": {
        "source_role": "commentary",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "https://m.thepaper.cn/newsDetail_forward_32005681",
        "source_type": "commentary",
        "artifact_path": "sources/b04-thepaper-shiyi.html",
        "captured_from": "澎湃新闻·谈心社（2025-11-21，古偶又在诗兴大发）",
    },
    "src-gmw-juming": {
        "source_role": "commentary",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "https://m.gmw.cn/toutiao/2024-10/05/content_1303863298.htm",
        "source_type": "commentary",
        "artifact_path": "sources/b02-gmw-juming.html",
        "captured_from": "光明网（2024-10-05，为什么现在电视剧不爱叫XX传）",
    },
}


# --------------------------------------------------------------------------
# 2) Candidate pool + slots
# --------------------------------------------------------------------------

CANDIDATES = [
    {
        "candidate_id": "cand-lanxiangru-dcque-001",
        "work": "兰香如故",
        "work_title": "兰香如故",
        "signal": "抖音热榜：兰香如故杜翠雀好有心机（7779575）/ 热度破30000（9053953）",
        "signal_source": "tgmeng-douyin",
        "topic_mode": "character",
        "article_mode": "reported_feature",
        "content_map": "D",
        "event_cluster_id": "lanxiangru-dcque-character",
        "content_map_label": "人物争议",
        "freshness_window": "same-day",
        "remove_timestamp_test": "pass",
        "evidence_readiness": "high",
        "recommendation": "A",
        "editorial_value_score": 9,
        "reader": "正在追《兰香如故》、被杜翠雀气得睡不着又在讨论她的观众",
        "landing": "看懂一个疯批女配的坏都有来处：才华被锁死，才是悲剧的起点",
        "emotion": "又气又放不下",
        "social_motive": "表达立场",
        "reader_question": "观众为什么对一个疯批女配又气又放不下",
        "core_question": "观众为什么对一个疯批女配又气又放不下",
        "angle": "她不是天生坏种：军户孤女、考女官路断、寄人篱下——观众气的不是她坏，是她把一身本事用在了最窄的一条路上",
        "source_refs": ["src-baijia-zhh", "src-sina-peijue", "src-china-zhh"],
        "prior_run_conflict": True,
        "selection_reason": "无量仙翁式选题：热门剧（热度破30000）+被热议的空白角色（热榜杜翠雀有心机/野心女子图鉴）+集体情绪（又气又讨论）。作品级去重黄灯：daily-001 写过《兰香如故》开播角度（被退婚的人），本期为不同人物（配角杜翠雀）、不同问题（角色命运）、热播期新数据（配角出圈/CP争议），属实质新角度+新数据",
    },
    {
        "candidate_id": "cand-juming-tongzhi-001",
        "work": "国产剧起名",
        "work_title": "国产剧起名",
        "signal": "微博热榜：长剧起名 观众已经学杂了（99507）",
        "signal_source": "tgmeng-weibo",
        "topic_mode": "culture",
        "article_mode": "reported_feature",
        "content_map": "C",
        "event_cluster_id": "drama-naming-homogeneity",
        "content_map_label": "文化现象",
        "freshness_window": "same-day",
        "remove_timestamp_test": "pass",
        "evidence_readiness": "high",
        "recommendation": "A",
        "editorial_value_score": 8,
        "reader": "追剧的人、被剧名同质化逼出过会心一笑的人",
        "landing": "看懂剧名同质化的商业逻辑：类型被验证后，流水线只敢起安全的名字",
        "emotion": "会心一笑",
        "social_motive": "显摆新知",
        "reader_question": "国产剧名为什么越起越像",
        "core_question": "国产剧名为什么越起越像",
        "angle": "剧名是剧集的第一句台词——当传/记/令/行变成预制标签，观众在点开之前就失去了好奇",
        "source_refs": ["src-rmrb-yuzhiwei", "src-gmw-juming"],
        "prior_run_conflict": False,
        "selection_reason": "借热点赋能：剧名同质化是长期观察（人民日报锐见、光明网盘点），当日热榜讨论是论证案例；身份认同（我早发现剧名都是流水线）+新知（预制逻辑拆解）",
    },
]

REJECTED_PRIOR_WORKS = [
    "交锋", "欢迎来龙餐馆", "空枪", "玩具总动员5",
    "早春晴朗", "兰香如故", "奥德赛", "蜘蛛侠：崭新之日",
    "绝望写手", "生化危机：爆发夜",
]

SLOT_DECISIONS = [
    {
        "slot": 1,
        "article_id": "art-001",
        "candidate_id": "cand-lanxiangru-dcque-001",
        "decision": "selected",
        "event_cluster_id": "lanxiangru-dcque-character",
    },
    {
        "slot": 2,
        "article_id": "art-002",
        "candidate_id": "cand-juming-tongzhi-001",
        "decision": "selected",
        "event_cluster_id": "drama-naming-homogeneity",
    },
]


# --------------------------------------------------------------------------
# 3) Briefs, task cards, task hierarchy
# --------------------------------------------------------------------------

TASK_CARD_REQUIRED_FIELDS = {
    "art-001": (
        "1. **站队点/可转述句**：杜翠雀最让人放不下的，不是她坏，而是她明明有才华，却只被给了一条最窄的路。\n"
        "2. **读者已知锚点**：《兰香如故》正在热播、热度破30000；郑合惠子演的杜翠雀这几天的讨论度很高。\n"
        "3. **today-hook 理由**：杜翠雀相关话题（有心机/野心女子图鉴/追剧团）连续占据抖音热榜，配角CP争议9月15日仍在发酵。\n"
        "4. **事实底座**：郑合惠子饰杜翠雀；军户孤女、寄人篱下；曾想考女官、路走不通；与刘学义继《花间令》后二搭；配角CP冲上热搜；谭松韵主演的大女主剧（来源见后台账本）。\n"
        "5. **最强钩子**：抱着死去的闺蜜痛哭的杜翠雀，人就是她杀的（与 batch.json 的 review_hook 一致）。\n"
        "- **title_promise**：《兰香如故》杜翠雀：抱着闺蜜哭的人，为什么让人恨不起来\n"
        "- **ending_destination**：观众记住的不是“疯批女配”四个字，而是那个抱着闺蜜哭到发抖、心里却在算下一步的姑娘。\n"
        "\n## 文章结构大纲（H2 目录）\n"
        "## 抱着死去的闺蜜痛哭的人，就是凶手\n"
        "## 甜妹脸的壳，藏着什么\n"
        "## 观众为什么对她又气又放不下\n"
        "## 疯批女配真正让人放不下的地方\n"
    ),
    "art-002": (
        "1. **站队点/可转述句**：观众记不住的不是剧名，而是长得一样的剧名背后，长得一样的故事。\n"
        "2. **读者已知锚点**：甄嬛传、陈情令、花间令……每个追剧的人都见过“传/记/令/行”式剧名。\n"
        "3. **today-hook 理由**：“长剧起名 观众已经学杂了”9月16日登上微博热榜。\n"
        "4. **事实底座**：网友总结“一个女人的故事叫《XX传》，一男一女叫《XX行》，两个男人叫《XX令》”；《甄嬛传》《如懿传》《芈月传》《楚乔传》等数十部同风格；《择天记》《承欢记》《珍馐记》为“记家军”；《陈情令》《山河令》《侍神令》《花间令》为“令”字辈；《玫瑰的故事》《墨雨云间》名字新奇抽象；人民日报锐见称“预制味”（来源见后台账本）。\n"
        "5. **最强钩子**：一个女人的故事叫《XX传》，一男一女叫《XX行》，两个男人叫《XX令》（与 batch.json 的 review_hook 一致）。\n"
        "- **title_promise**：国产剧名为什么越起越像\n"
        "- **ending_destination**：希望以后盘点“传”“记”“令”“行”的时候，是当成过去时来笑的。\n"
        "\n## 文章结构大纲（H2 目录）\n"
        "## 剧名是剧集的第一句台词，现在这句台词在量产\n"
        "## 为什么平台和剧方都在用“预制”剧名\n"
        "## 名字像了，观众就记不住了\n"
        "## 别让第一句台词，先说“我和别人一样”\n"
    ),
}

STRONGEST_HOOKS = {
    "art-001": "抱着死去的闺蜜痛哭的杜翠雀，人就是她杀的",
    "art-002": "一个女人的故事叫《XX传》，一男一女叫《XX行》，两个男人叫《XX令》",
}


# --------------------------------------------------------------------------
# 4) Material packs
# --------------------------------------------------------------------------

MATERIAL_SPECS = {
    "art-001": {
        "mode": "reported_feature",
        "role": "media_report",
        "source_ids": ["src-baijia-zhh", "src-sina-peijue", "src-china-zhh", "src-sohu-cuique", "src-sina-renwu", "src-sina-rufu"],
        "question": "观众为什么对一个疯批女配又气又放不下",
        "mechanism": "她的坏每一步都有来处：出身、出路、寄人篱下的每一天——观众气的是手段，放不下的是才华被锁死",
        "facts": [
            {"text": "《兰香如故》剧情更新，郑合惠子特别出演的杜翠雀登场", "level": "event_exists", "locator": "封面新闻: 角色登场", "source_id": "src-sina-peijue", "plan_kind": "specific_context"},
            {"text": "她是个军户孤女，从小没了爹娘，寄人篱下长大", "level": "character_setup", "locator": "百家号: 角色出身", "source_id": "src-baijia-zhh", "plan_kind": "fact"},
            {"text": "原本她打算考取女官，靠着学识走出自己的路，可女官势力衰落，这条路走不通", "level": "mechanism", "locator": "中国网: 女官路断", "source_id": "src-china-zhh", "plan_kind": "mechanism"},
            {"text": "人就是她杀的", "level": "mechanism", "locator": "百家号: 哭戏反转", "source_id": "src-baijia-zhh", "plan_kind": "fact"},
            {"text": "从《花间令》里极致BE的“潘杨之好”，到《兰香如故》中充满试探与拉扯的“纯恨”关系，角色设定一百八十度翻转", "level": "mechanism", "locator": "封面新闻: 二搭反转", "source_id": "src-sina-peijue", "plan_kind": "mechanism"},
            {"text": "围绕配角CP出圈带来的相关讨论仍在持续", "level": "event_exists", "locator": "封面新闻: 讨论持续", "source_id": "src-sina-peijue", "plan_kind": "specific_context"},
            {"text": "郑合惠子好像有一种魔力，出演配角时总能收获大量关注", "level": "character_setup", "locator": "中国网: 配角体质", "source_id": "src-china-zhh", "plan_kind": "fact"},
            {"text": "杜翠雀擅长女红，做了一批彩胜，让丫鬟小莲送些给林锦岐", "level": "event_exists", "locator": "搜狐: 彩胜局", "source_id": "src-sohu-cuique", "plan_kind": "specific_context"},
            {"text": "她不是没有能力改变命运，只是把所有力气都用在了向别人索取认可上，求而不得之后，又把怨气变成了报复", "level": "mechanism", "locator": "新浪: 人物分析", "source_id": "src-sina-renwu", "plan_kind": "mechanism"},
        ],
        "by_source": {
            "src-baijia-zhh": [
                "郑合惠子在《兰香如故》里就这么哭了一场",
                "人就是她杀的",
                "这部剧叫《兰香如故》，郑合惠子在里头演的角色叫杜翠雀",
                "她是个军户孤女，从小没了爹娘，寄人篱下长大",
                "她偏偏又读了书，肚子里有墨水，脑子比谁都清醒",
                "清醒才是最残忍的事",
                "她知道自己有才华，知道自己的谋略不比任何一个男人差",
                "有人刷“我裂开了”",
                "有人说“这反转我CPU烧了”",
                "扎着两个小辫子，笑起来眼睛弯弯的，说话轻声细语，看起来人畜无害",
            ],
            "src-sina-peijue": [
                "《兰香如故》剧情更新，郑合惠子特别出演的杜翠雀登场",
                "这是两人继《花间令》后的第二次合作",
                "从《花间令》里极致BE的“潘杨之好”，到《兰香如故》中充满试探与拉扯的“纯恨”关系，角色设定一百八十度翻转",
                "《兰香如故》是谭松韵主演的大女主剧",
                "围绕配角CP出圈带来的相关讨论仍在持续",
                "与男主角@Mr_刘学义仅有几句寒暄的对手戏",
                "仅仅几秒的客串同框，就带火“CP感玄学”热搜",
                "不少剧粉和主演粉丝认为，《兰香如故》是@谭松韵seven主演的大女主剧，舆论营销过度聚焦配角的非官配CP，网络上还出现拉踩女主以及官配的言论，影响大家的追剧体验",
                "而支持这对CP的网友则认为，CP感是观众自发产生的感受，配角角色出彩，不该直接被贴上“过度营销”的标签",
            ],
            "src-china-zhh": [
                "杜翠雀出身金州军户，自小读书识字，懂女红也通药理",
                "原本她打算考取女官，靠着学识走出自己的路，可女官势力衰落，这条路走不通",
                "收到哥哥的信，她来到金陵林府，寄人篱下",
                "外表温顺、内心藏着野心的角色",
                "郑合惠子好像有一种魔力，出演配角时总能收获大量关注",
                "只用几场戏就冲上热搜",
            ],
            "src-sohu-cuique": [
                "杜翠雀擅长女红，做了一批彩胜，让丫鬟小莲送些给林锦岐",
                "送去的彩胜里，有一株她照自己闺名做的翠雀花胜",
                "故事里却借翠雀谐音，暗嵌娶妾两层意思",
                "人胜日那天，林锦岐觉着那株翠雀花胜精致，随手戴在了头上",
                "当场有人认出花胜暗意，起哄说林锦岐要娶杜翠雀为妾",
                "兰香提议借这些花胜，说成是做多装错，把私意化解",
                "宴会结束，林锦岐找到杜翠雀，严肃说并无娶她为妾的意思",
                "古代女子闺名本不轻传，杜翠雀之名却人人知晓，成了这局的隙",
            ],
            "src-sina-renwu": [
                "她明明有本事，也见过更大的天地，却始终把自己的价值系在嫁进什么人家上",
                "她想要的表面是身份，底下其实是一次被真正看见、被平等对待的机会",
                "她不是没有能力改变命运，只是把所有力气都用在了向别人索取认可上，求而不得之后，又把怨气变成了报复",
                "她的坏并非凭空掉下来。她身上有才华，有野心，也有被环境放大的自卑和虚荣",
                "那朵翠雀花胜最后和她一起烧尽",
                "我叫杜翠雀，翠雀是花，不是鸟。金州军户出身，自小读书识字，也学女红药理。本欲凭一身学识做女官，奈何时移世易，此路难通。哥哥一纸家书，便渡江赴金陵",
                "林锦岐落入杜氏兄妹圈套，许兰香挺身而出，当众拆穿杜翠雀，力保林家声誉",            ],
            "src-sina-rufu": [
                "“我叫杜翠雀，翠雀是花，不是鸟。”",
                "柔里有刺，温里有界",
                "起点越清，后面越疼",
            ],
        },
        "audience": "正在追《兰香如故》、被杜翠雀气得睡不着又在讨论她的观众",
    },
    "art-002": {
        "mode": "reported_feature",
        "role": "media_report",
        "source_ids": ["src-rmrb-yuzhiwei", "src-gmw-juming", "src-xinmin-juming", "src-thepaper-shiyi"],
        "question": "国产剧名为什么越起越像",
        "mechanism": "当类型被验证能赚钱，流水线会向安全的名字靠拢——剧名变成类型标签，观众在点开前失去好奇",
        "facts": [
            {"text": "从“传”“记”“令”“行”一类剧名的泛滥，到相似的人设、桥段、海报，同质化几乎渗透到创作的方方面面", "level": "event_exists", "locator": "人民日报: 同质化渗透", "source_id": "src-rmrb-yuzhiwei", "plan_kind": "specific_context"},
            {"text": "一个女人的故事叫《XX传》，一男一女叫《XX行》，两个男人叫《XX令》", "level": "event_exists", "locator": "光明网: 网友套路总结", "source_id": "src-gmw-juming", "plan_kind": "fact"},
            {"text": "《甄嬛传》外，《如懿传》《芈月传》《楚乔传》《芸汐传》《皓镧传》《云襄传》等数十部电视剧也都是同样的起名风格", "level": "event_exists", "locator": "光明网: 传字辈名单", "source_id": "src-gmw-juming", "plan_kind": "fact"},
            {"text": "今年关注度较高的剧《玫瑰的故事》《墨雨云间》，名字都新奇又“抽象”", "level": "event_exists", "locator": "光明网: 抽象剧名转向", "source_id": "src-gmw-juming", "plan_kind": "fact"},
            {"text": "这种同质化，不能简单地用“创作懒惰”来解释", "level": "mechanism", "locator": "人民日报: 非懒惰", "source_id": "src-rmrb-yuzhiwei", "plan_kind": "mechanism"},
            {"text": "古装偶像剧都处在高商业价值赛道", "level": "mechanism", "locator": "人民日报: 商业赛道", "source_id": "src-rmrb-yuzhiwei", "plan_kind": "mechanism"},
            {"text": "表面看是指人设、桥段层面的跟风，本质上反映的是对观众现实情绪和心理诉求的滞后认知", "level": "mechanism", "locator": "人民日报: 预制味本质", "source_id": "src-rmrb-yuzhiwei", "plan_kind": "mechanism"},
            {"text": "凭借充沛的情感表达和轻喜剧风格，取得不错口碑", "level": "event_exists", "locator": "人民日报: 宝宝仙侠", "source_id": "src-rmrb-yuzhiwei", "plan_kind": "specific_context"},
            {"text": "由于一线导演、编剧团队的不断入局和制作投入的提升，古装偶像剧的制作精良度也在逐年攀升", "level": "mechanism", "locator": "人民日报: 精良度攀升", "source_id": "src-rmrb-yuzhiwei", "plan_kind": "fact"},
            {"text": "《重生之女将星》被改为《锦月如歌》，后者完全看不出女将军的设定", "level": "event_exists", "locator": "新民晚报: 改名失义", "source_id": "src-xinmin-juming", "plan_kind": "fact"},
            {"text": "《康熙王朝》《雍正王朝》，开门见山，点明题材", "level": "event_exists", "locator": "新民晚报: 直白对照", "source_id": "src-xinmin-juming", "plan_kind": "fact"},
            {"text": "《玉茗茶骨》。这四个毫不相干的字凑在一起，有种任你颠来倒去都记不住的破碎感", "level": "event_exists", "locator": "澎湃: 玉茗茶骨", "source_id": "src-thepaper-shiyi", "plan_kind": "specific_context"},
        ],
        "by_source": {
            "src-rmrb-yuzhiwei": [
                "从“传”“记”“令”“行”一类剧名的泛滥，到相似的人设、桥段、海报，同质化几乎渗透到创作的方方面面",
                "这种同质化，不能简单地用“创作懒惰”来解释",
                "古装偶像剧都处在高商业价值赛道",
                "各大长视频平台，往往会为“种子”项目匹配优质创作生产力",
                "由于一线导演、编剧团队的不断入局和制作投入的提升，古装偶像剧的制作精良度也在逐年攀升",
                "表面看是指人设、桥段层面的跟风，本质上反映的是对观众现实情绪和心理诉求的滞后认知",
                "盲目复制、升级爆款剧的“名场面”",
                "全然不顾其背后映射的、彼时彼刻的观众情感需求和价值诉求",
                "让观众在反复、过度甚至无效的逢迎中失去耐心",
                "凭借充沛的情感表达和轻喜剧风格，取得不错口碑",
                "被观众亲切地称为“宝宝仙侠”",
                "把该剧男女主角互换身体、男主角反派化等设置当作“成功配方”",
                "观众口中的“宝宝仙侠”，也从爱称演变成了讽刺",
                "常被网友戏称为“95后小生、小花的‘换乘’恋爱”",
            ],
            "src-gmw-juming": [
                "现在的电视剧不爱叫《xx传》了",
                "今年关注度较高的剧《玫瑰的故事》《墨雨云间》，名字都新奇又“抽象”",
                "一个女人的故事叫《XX传》，一男一女叫《XX行》，两个男人叫《XX令》",
                "《甄嬛传》外，《如懿传》《芈月传》《楚乔传》《芸汐传》《皓镧传》《云襄传》等数十部电视剧也都是同样的起名风格",
                "鹿晗主演的《择天记》、杨紫主演的《承欢记》以及古装美食剧《珍馐记》就都是“记家军”",
                "《陈情令》《山河令》，陈坤、周迅主演的《侍神令》，以及今年年初的《花间令》",
            ],
            "src-xinmin-juming": [
                "光看剧名，到底是个什么题材",
                "不少观众刷到电视剧《野狗骨头》时都犯了嘀咕",
                "这是一部聚焦上世纪90年代南方小城、讲述重组家庭少年双向救赎故事的作品",
                "“野狗”指代男主陈异，他自幼遭受父亲家暴，内心缺爱脆弱，只能用满身叛逆尖刺伪装自己；“骨头”则是女主苗靖，常年寄人篱下，骨子里带着不肯弯折的韧劲",
                "《重生之女将星》被改为《锦月如歌》，后者完全看不出女将军的设定",
                "《康熙王朝》《雍正王朝》，开门见山，点明题材",
                "《编辑部的故事》《父母爱情》《北京人在纽约》，简单几个字，就能清晰概括故事核心",
                "过度刻意堆砌意象、一味追求晦涩高级，反而和大众传播的初衷相悖",
            ],
            "src-thepaper-shiyi": [
                "《玉茗茶骨》。这四个毫不相干的字凑在一起，有种任你颠来倒去都记不住的破碎感",
                "好好的飒爽《女将星》，换成毫无记忆点的四个字，索然无味",
            ],
        },
        "audience": "追剧的人、被剧名同质化逼出过会心一笑的人",
    },
}


# --------------------------------------------------------------------------
# 5) Bodies
# --------------------------------------------------------------------------

BODIES = {
    "art-001": """## 抱着死去的闺蜜痛哭的人，就是凶手

《兰香如故》里有一场哭戏：一个姑娘跪在地上，抱着死去的闺蜜放声痛哭，哭到脖子上的青筋暴起，整个人抖得像筛糠。所有人看完都以为她重情重义。结果，人就是她杀的。

这个姑娘叫杜翠雀，郑合惠子演的。光听名字像小鸟依人，她前期的样子也确实如此——扎两个小辫，笑起来眼睛弯弯，说话轻声细语。可就是这场哭戏之后，弹幕炸了：有人刷“我裂开了”，有人说“这反转我CPU烧了”。

## 甜妹脸的壳，藏着什么

杜翠雀是个军户孤女，从小没了爹娘，寄人篱下长大。她偏偏又读了书，肚子里有墨水，脑子比谁都清醒。清醒才是最残忍的事：她知道自己有才华，知道自己的谋略不比任何一个男人差。

杜翠雀出身金州军户，自小读书识字，懂女红也通药理。原本她想考女官，靠学识走出自己的路。可女官势力衰落，这条路走不通。收到哥哥的信，她来到金陵林府，继续寄人篱下。一个读过书的姑娘，被塞进了一个没有出口的位置。

## 观众为什么对她又气又放不下

她不是天生坏种。追剧的人大概都有过这种体验：为一个角色气得睡不着，第二天又在讨论里替她说话。杜翠雀就是这样——观众气的，是她把一身本事用在了最窄的一条路上：外表温顺，内心藏着野心；每一次示弱都是算计，每一次亲近都标了价。气完之后，又很难真正恨起来，因为她的“坏”每一步都看得见来处：出身、出路、寄人篱下的每一天。

她和刘学义的对手戏只有几句寒暄，仅仅几秒的客串同框，就带火了“CP感玄学”热搜；这是两人继《花间令》后的第二次合作，从极致BE的“潘杨之好”，到充满试探与拉扯的“纯恨”，角色设定一百八十度翻转。配角CP出圈的讨论至今还在继续。

她最出名的一步棋，是花胜。杜翠雀擅长女红，做了一批彩胜，让丫鬟小莲送进林府；里面有一株照自己闺名做的翠雀花胜——借翠雀谐音，暗嵌娶妾两层意思。人胜日那天，林锦岐觉着那株花胜精致，随手戴在了头上，当场有人认出暗意，起哄说林锦岐要娶杜翠雀为妾。这局被拆穿后，宴会结束，林锦岐找到她，说并无娶她为妾的意思。

演杜翠雀的是郑合惠子。甜妹脸演疯批，反差本身就是话题的一半——她好像有一种魔力，出演配角时总能收获大量关注，杜翠雀只用几场戏就冲上热搜。

《兰香如故》里她的开场白就有骨相：“我叫杜翠雀，翠雀是花，不是鸟。金州军户出身，自小读书识字，也学女红药理。本欲凭一身学识做女官，奈何时移世易，此路难通。”柔里有刺，温里有界。起点越清，后面越疼。

有本事的她，却把价值系在嫁进什么人家上；她不是没有能力改变命运，只是把所有力气都用在了向别人索取认可上——她想要的表面是身份，底下其实是一次被真正看见、被平等对待的机会。求而不得之后，怨气就变成了报复。那朵翠雀花胜最后和她一起烧尽。

## 疯批女配真正让人放不下的地方

《兰香如故》配角CP的讨论还在继续：喜欢的人说她出彩，不喜欢的人说营销过度。可我觉得，能被一边夸出彩、一边骂营销过度，这个角色本身就有得聊。

杜翠雀最让人放不下的，不是她坏，而是她明明有才华，却只被给了一条最窄的路。她的狠，是清醒的人在绝路上能拿出的全部力气。观众记住的也不是“疯批女配”四个字，而是那个抱着闺蜜哭到发抖、心里却在算下一步的姑娘。""",
    "art-002": """## 剧名是剧集的第一句台词，现在这句台词在量产

你有没有发现，现在的国产剧名越来越像了。网友总结过一条起名套路：一个女人的故事叫《XX传》，一男一女叫《XX行》，两个男人叫《XX令》。

这当然是个段子。但段子底下是实打实的名单：《甄嬛传》之外，《如懿传》《芈月传》《楚乔传》《芸汐传》《皓镧传》《云襄传》……数十部剧共用同一种起名风格；《择天记》《承欢记》《珍馐记》是“记家军”；《陈情令》《山河令》《侍神令》《花间令》排成一列“令”字辈。

## 为什么平台和剧方都在用“预制”剧名

这种同质化，不能简单地用“创作懒惰”来解释。古装偶像剧处在高商业价值赛道，各大长视频平台往往会给“种子”项目匹配优质创作生产力。问题不在没人会起名，而在于：当一个类型被验证能赚钱，整个流水线都会向“安全的名字”靠拢——从“传”“记”“令”“行”的剧名泛滥，到相似的人设、桥段、海报，同质化几乎渗透到创作的方方面面。

更典型的例子是“宝宝仙侠”。某部仙侠剧凭借充沛的情感表达和轻喜剧风格，取得不错口碑，被观众亲切地称为“宝宝仙侠”。随后上马的一批仙侠剧，把该剧男女主角互换身体、男主角反派化等设置当作“成功配方”，结果剧集只剩甜度超标的恋爱——观众口中的“宝宝仙侠”，也从爱称演变成了讽刺。

所以“预制”不是粗制滥造的同义词。一线导演、编剧团队不断入局，制作投入提升，古装偶像剧的制作精良度在逐年攀升。真正的问题是方向：盲目复制、升级爆款剧的“名场面”，全然不顾其背后映射的、彼时彼刻的观众情感需求和价值诉求，让观众在反复、过度甚至无效的逢迎中失去耐心。选角也一样，常被网友戏称为“95后小生、小花的‘换乘’恋爱”。

## 名字像了，观众就记不住了

剧名像，故事就更像。观众真正失去的，是在点开之前的那点好奇：看到《XX传》三个字，能猜出大女主、宅斗、逆袭；看到《XX令》，能猜到双男主、情义、江湖。名字一旦变成类型标签，剧集在开播前就丢掉了一半悬念。

有意思的是，风向正在变。《玫瑰的故事》《墨雨云间》这样关注度高的剧，名字都新奇又“抽象”，反而让人记住了。

也有反例。《野狗骨头》这个名字让不少观众犯嘀咕，光看剧名不知道是什么题材；看过几集才发现，是一部聚焦上世纪90年代南方小城、讲重组家庭少年双向救赎的作品。“野狗”指男主陈异，自幼遭受父亲家暴，用满身叛逆尖刺伪装自己；“骨头”是女主苗靖，寄人篱下，骨子里带着不肯弯折的韧劲——名字抽象，却长在人物身上。

改名失义的例子更多。《重生之女将星》被改成《锦月如歌》，完全看不出女将军的设定；《玉茗茶骨》四个毫不相干的字凑在一起，有种任你颠来倒去都记不住的破碎感。对照之下，《康熙王朝》《雍正王朝》开门见山点明题材，《编辑部的故事》《父母爱情》几个字就概括了故事核心。

观众记不住的不是剧名，而是长得一样的剧名背后，长得一样的故事。

## 别让第一句台词，先说“我和别人一样”

当“预制味”成为古装偶像剧的关键词，剧名只是最容易看见的那一部分。观众点开一部剧，看见的第一句台词就是它的名字——这一句如果都在说“我和别人一样”，后面的故事再用力，也先输了一半。

希望以后盘点“传”“记”“令”“行”的时候，是当成过去时来笑的。""",
}


# --------------------------------------------------------------------------
# 6) Review evidence + delivery
# --------------------------------------------------------------------------

TITLES = {
    "art-001": [
        ("《兰香如故》杜翠雀：抱着闺蜜哭的人，为什么让人恨不起来", "角色解读"),
        ("甜妹脸演疯批：杜翠雀的两副面孔", "反转"),
        ("军户孤女杜翠雀：才华和野心，都困在后宅里", "命运"),
    ],
    "art-002": [
        ("国产剧名为什么越起越像", "剧名现象"),
        ("从《XX传》到《XX令》：剧名的预制味", "套路盘点"),
        ("名字像了，观众就记不住了", "判断"),
    ],
}

SOURCE_IDS = {
    "art-001": ["src-baijia-zhh", "src-sina-peijue", "src-china-zhh", "src-sohu-cuique", "src-sina-renwu", "src-sina-rufu"],
    "art-002": ["src-rmrb-yuzhiwei", "src-gmw-juming", "src-xinmin-juming", "src-thepaper-shiyi"],
}

MODES = {"art-001": "reported_feature", "art-002": "reported_feature"}

RULE_CLAIMS = {
    "art-001": [
        {"claim_id": "c1", "claim_level": "event_exists", "source_refs": ["src-sina-peijue"], "source_locators": ["封面新闻: 角色登场"]},
        {"claim_id": "c2", "claim_level": "character_setup", "source_refs": ["src-baijia-zhh"], "source_locators": ["百家号: 军户孤女"]},
        {"claim_id": "c3", "claim_level": "mechanism", "source_refs": ["src-china-zhh"], "source_locators": ["中国网: 女官路断"]},
        {"claim_id": "c4", "claim_level": "mechanism", "source_refs": ["src-baijia-zhh"], "source_locators": ["百家号: 哭戏反转"]},
    ],
    "art-002": [
        {"claim_id": "c1", "claim_level": "event_exists", "source_refs": ["src-rmrb-yuzhiwei"], "source_locators": ["人民日报: 同质化渗透"]},
        {"claim_id": "c2", "claim_level": "event_exists", "source_refs": ["src-gmw-juming"], "source_locators": ["光明网: 套路总结"]},
        {"claim_id": "c3", "claim_level": "mechanism", "source_refs": ["src-rmrb-yuzhiwei"], "source_locators": ["人民日报: 非懒惰"]},
        {"claim_id": "c4", "claim_level": "mechanism", "source_refs": ["src-gmw-juming"], "source_locators": ["光明网: 抽象剧名转向"]},
    ],
}


# --------------------------------------------------------------------------
# Run data
# --------------------------------------------------------------------------

BRIEFS = {
    "art-001": """# Writing Brief

production_contract: article-first-v1
brief_contract: writing-brief-v2
title_contract: title-pack-v1
legacy_compatibility: false
run_contract_required: true
article_id: art-001
candidate_id: cand-lanxiangru-dcque-001
article_mode: reported_feature
required_source_roles: [media_report]
topic_version: 1
content_map: D
reference_shape: viewing_commentary
core_question: 观众为什么对一个疯批女配又气又放不下
target_reader: 正在追《兰香如故》、被杜翠雀气得睡不着又在讨论她的观众
editorial_angle: 她不是天生坏种——军户孤女、考女官路断、寄人篱下，观众气的不是她坏，是她把一身本事用在了最窄的一条路上
body_route: 从杀闺蜜的哭戏反转进入，再拆甜妹壳下的出身与出路，接着写观众又气又放不下的心理，最后落到命运判断
evidence_boundary: 只写三份来源中的角色设定、剧情反转与讨论现象；不写未出现在来源中的剧情细节
required_hard_information: 郑合惠子饰杜翠雀；军户孤女寄人篱下；考女官路断；杀闺蜜哭戏反转；与刘学义《花间令》二搭；配角CP上热搜；谭松韵主演大女主剧
unsupported_boundary: 不能替观众下整体结论，不写未证实的营销内幕，不写演员本人未公开表态
""",
    "art-002": """# Writing Brief

production_contract: article-first-v1
brief_contract: writing-brief-v2
title_contract: title-pack-v1
legacy_compatibility: false
run_contract_required: true
article_id: art-002
candidate_id: cand-juming-tongzhi-001
article_mode: reported_feature
required_source_roles: [media_report]
topic_version: 1
content_map: C
reference_shape: viewing_commentary
core_question: 国产剧名为什么越起越像
target_reader: 追剧的人、被剧名同质化逼出过会心一笑的人
editorial_angle: 剧名是剧集的第一句台词——当传/记/令/行变成预制标签，观众在点开之前就失去了好奇
body_route: 先下判断（剧名在量产），再解释预制逻辑，接着写名字像了观众记不住，最后落到"第一句台词"的呼吁
evidence_boundary: 只写两份来源中的剧名盘点、网友总结与评论观点；不扩写未点名作品
required_hard_information: 网友起名套路总结；传/记/令家军剧名清单；《玫瑰的故事》《墨雨云间》抽象转向；人民日报锐见"预制味"与商业逻辑
unsupported_boundary: 不能断言平台内部决策，不点名来源之外的剧集，不写剧集质量结论
""",
}

BRIEF_SPECS = [
    (
        "art-001",
        "reported_feature",
        "media_report",
        "观众为什么对一个疯批女配又气又放不下",
        "src-baijia-zhh",
    ),
    (
        "art-002",
        "reported_feature",
        "media_report",
        "国产剧名为什么越起越像",
        "src-rmrb-yuzhiwei",
    ),
]

CONTENT_RECORD_ARGS = [
    {
        "aid": "art-001",
        "mode": "reported_feature",
        "role": "media_report",
        "core_object": "杜翠雀的角色命运与观众的复杂反应",
        "question": "观众为什么对一个疯批女配又气又放不下",
        "mechanism": "她的坏每一步都有来处：出身、出路、寄人篱下的每一天——观众气的是手段，放不下的是才华被锁死",
        "takeaway": "观众记住的不是“疯批女配”四个字，而是那个抱着闺蜜哭到发抖、心里却在算下一步的姑娘。",
        "hard": [
            {"information_id": "i1", "text": "《兰香如故》剧情更新，郑合惠子特别出演的杜翠雀登场", "kind": "specific_context", "body_locator": "p2", "source_refs": ["src-sina-peijue"], "source_locators": ["封面新闻: 角色登场"], "independence_key": "dcque-entry"},
            {"information_id": "i2", "text": "人就是她杀的", "kind": "fact", "body_locator": "p1", "source_refs": ["src-baijia-zhh"], "source_locators": ["百家号: 哭戏反转"], "independence_key": "killer-reveal"},
            {"information_id": "i3", "text": "她是个军户孤女，从小没了爹娘，寄人篱下长大", "kind": "fact", "body_locator": "p3", "source_refs": ["src-baijia-zhh"], "source_locators": ["百家号: 角色出身"], "independence_key": "orphan-origin"},
            {"information_id": "i4", "text": "原本她打算考取女官，靠着学识走出自己的路，可女官势力衰落，这条路走不通", "kind": "mechanism", "body_locator": "p4", "source_refs": ["src-china-zhh"], "source_locators": ["中国网: 女官路断"], "independence_key": "blocked-path"},
            {"information_id": "i5", "text": "从《花间令》里极致BE的“潘杨之好”，到《兰香如故》中充满试探与拉扯的“纯恨”关系，角色设定一百八十度翻转", "kind": "mechanism", "body_locator": "p6", "source_refs": ["src-sina-peijue"], "source_locators": ["封面新闻: 二搭反转"], "independence_key": "second-pairing"},
            {"information_id": "i6", "text": "围绕配角CP出圈带来的相关讨论仍在持续", "kind": "specific_context", "body_locator": "p6", "source_refs": ["src-sina-peijue"], "source_locators": ["封面新闻: 讨论持续"], "independence_key": "cp-debate"},
            {"information_id": "i7", "text": "郑合惠子好像有一种魔力，出演配角时总能收获大量关注", "kind": "fact", "body_locator": "p8", "source_refs": ["src-china-zhh"], "source_locators": ["中国网: 配角体质"], "independence_key": "zhh-magic"},
            {"information_id": "i8", "text": "杜翠雀擅长女红，做了一批彩胜，让丫鬟小莲送些给林锦岐", "kind": "specific_context", "body_locator": "p7", "source_refs": ["src-sohu-cuique"], "source_locators": ["搜狐: 彩胜局"], "independence_key": "cuique-sheng"},
            {"information_id": "i9", "text": "她不是没有能力改变命运，只是把所有力气都用在了向别人索取认可上，求而不得之后，又把怨气变成了报复", "kind": "mechanism", "body_locator": "p10", "source_refs": ["src-sina-renwu"], "source_locators": ["新浪: 人物分析"], "independence_key": "seek-approval"},
        ],
        "bases": [
            {"locator": "p5", "fact_or_scene": "考女官路断后寄人篱下", "explanation": "才华无处安放是她的坏的全部来处"},
            {"locator": "p1", "fact_or_scene": "哭戏反转", "explanation": "先立好人设再反转，是观众情绪被击中的原因"},
        ],
        "boundary": "当前来源不能证明演员本人未公开的表态，也不能证明剧集整体口碑；不写未出现在三份来源中的剧情细节。",
        "source_ids": ["src-baijia-zhh", "src-sina-peijue", "src-china-zhh", "src-sohu-cuique", "src-sina-renwu", "src-sina-rufu"],
    },
    {
        "aid": "art-002",
        "mode": "reported_feature",
        "role": "media_report",
        "core_object": "国产剧名同质化现象及其商业逻辑",
        "question": "国产剧名为什么越起越像",
        "mechanism": "当类型被验证能赚钱，流水线会向安全的名字靠拢——剧名变成类型标签，观众在点开前失去好奇",
        "takeaway": "观众记不住的不是剧名，而是长得一样的剧名背后，长得一样的故事。",
        "hard": [
            {"information_id": "i1", "text": "从“传”“记”“令”“行”一类剧名的泛滥，到相似的人设、桥段、海报，同质化几乎渗透到创作的方方面面", "kind": "specific_context", "body_locator": "p4", "source_refs": ["src-rmrb-yuzhiwei"], "source_locators": ["人民日报: 同质化渗透"], "independence_key": "homogeneity"},
            {"information_id": "i2", "text": "一个女人的故事叫《XX传》，一男一女叫《XX行》，两个男人叫《XX令》", "kind": "fact", "body_locator": "p1", "source_refs": ["src-gmw-juming"], "source_locators": ["光明网: 网友套路总结"], "independence_key": "naming-rule"},
            {"information_id": "i3", "text": "《甄嬛传》外，《如懿传》《芈月传》《楚乔传》《芸汐传》《皓镧传》《云襄传》等数十部电视剧也都是同样的起名风格", "kind": "fact", "body_locator": "p2", "source_refs": ["src-gmw-juming"], "source_locators": ["光明网: 传字辈名单"], "independence_key": "zhuan-list"},
            {"information_id": "i4", "text": "今年关注度较高的剧《玫瑰的故事》《墨雨云间》，名字都新奇又“抽象”", "kind": "fact", "body_locator": "p7", "source_refs": ["src-gmw-juming"], "source_locators": ["光明网: 抽象剧名转向"], "independence_key": "abstract-turn"},
            {"information_id": "i5", "text": "这种同质化，不能简单地用“创作懒惰”来解释", "kind": "mechanism", "body_locator": "p4", "source_refs": ["src-rmrb-yuzhiwei"], "source_locators": ["人民日报: 非懒惰"], "independence_key": "not-laziness"},
            {"information_id": "i6", "text": "古装偶像剧都处在高商业价值赛道", "kind": "mechanism", "body_locator": "p4", "source_refs": ["src-rmrb-yuzhiwei"], "source_locators": ["人民日报: 商业赛道"], "independence_key": "commercial-track"},
            {"information_id": "i7", "text": "凭借充沛的情感表达和轻喜剧风格，取得不错口碑", "kind": "specific_context", "body_locator": "p5", "source_refs": ["src-rmrb-yuzhiwei"], "source_locators": ["人民日报: 宝宝仙侠"], "independence_key": "baobao-origin"},
            {"information_id": "i8", "text": "表面看是指人设、桥段层面的跟风，本质上反映的是对观众现实情绪和心理诉求的滞后认知", "kind": "mechanism", "body_locator": "p6", "source_refs": ["src-rmrb-yuzhiwei"], "source_locators": ["人民日报: 预制味本质"], "independence_key": "lagging-cognition"},
            {"information_id": "i9", "text": "由于一线导演、编剧团队的不断入局和制作投入的提升，古装偶像剧的制作精良度也在逐年攀升", "kind": "mechanism", "body_locator": "p6", "source_refs": ["src-rmrb-yuzhiwei"], "source_locators": ["人民日报: 精良度攀升"], "independence_key": "rising-craft"},
            {"information_id": "i10", "text": "常被网友戏称为“95后小生、小花的‘换乘’恋爱”", "kind": "fact", "body_locator": "p6", "source_refs": ["src-rmrb-yuzhiwei"], "source_locators": ["人民日报: 选角预制"], "independence_key": "casting-turnover"},
            {"information_id": "i11", "text": "《野狗骨头》是一部聚焦上世纪90年代南方小城、讲述重组家庭少年双向救赎故事的作品", "kind": "fact", "body_locator": "p8", "source_refs": ["src-xinmin-juming"], "source_locators": ["新民晚报: 野狗骨头"], "independence_key": "yegugutou"},
            {"information_id": "i12", "text": "《重生之女将星》被改为《锦月如歌》，后者完全看不出女将军的设定", "kind": "fact", "body_locator": "p9", "source_refs": ["src-xinmin-juming"], "source_locators": ["新民晚报: 改名失义"], "independence_key": "jinyueruge"},
            {"information_id": "i13", "text": "《康熙王朝》《雍正王朝》，开门见山，点明题材", "kind": "fact", "body_locator": "p9", "source_refs": ["src-xinmin-juming"], "source_locators": ["新民晚报: 直白对照"], "independence_key": "kangxi"},
            {"information_id": "i14", "text": "《玉茗茶骨》。这四个毫不相干的字凑在一起，有种任你颠来倒去都记不住的破碎感", "kind": "fact", "body_locator": "p9", "source_refs": ["src-thepaper-shiyi"], "source_locators": ["澎湃: 玉茗茶骨"], "independence_key": "yumingchagu"},
        ],
        "bases": [
            {"locator": "p2", "fact_or_scene": "传/记/令家军名单", "explanation": "套路总结有实打实的剧名清单支撑"},
            {"locator": "p7", "fact_or_scene": "玫瑰的故事/墨雨云间抽象剧名", "explanation": "反例说明起名空间没有被锁死"},
        ],
        "boundary": "当前来源不能证明平台内部决策过程，也不能证明剧集质量结论；不点名两份来源之外的剧集。",
        "source_ids": ["src-rmrb-yuzhiwei", "src-gmw-juming", "src-xinmin-juming", "src-thepaper-shiyi"],
    },
]

BATCH_SPECS = {
    "art-001": (
        "cand-lanxiangru-dcque-001",
        "兰香如故",
        "lanxiangru-dcque-character",
        ["src-baijia-zhh", "src-sina-peijue", "src-china-zhh"],
        "A",
        "D",
    ),
    "art-002": (
        "cand-juming-tongzhi-001",
        "国产剧起名",
        "drama-naming-homogeneity",
        ["src-rmrb-yuzhiwei", "src-gmw-juming"],
        "B",
        "C",
    ),
}


if __name__ == "__main__":
    import sys as _sys

    from scripts.daily_engine import build_run

    build_run(_sys.modules[__name__])
