"""Build runs/2026-09-17/daily-009 (two_article_daily).

选题来源：2026-09-17 谈资型发现源分类信号（dailyhot-zhihu）+ 当日微信公众号抓取
（wechat index，2026-09-17 入库 37 篇）。

- art-001 《雍正王朝》（1999）康熙不急、雍正暴躁——知乎热榜当日信号（hot≈63万）。
  1999 年两篇一手报道构成两侧支柱：光明日报写焦晃的康熙"血脉已衰仍然威驭天下"，
  中国电影报记唐国强自评"有的地方感到暴躁的过多了，这都是我本身缺乏的"。
  常青窗口；content_map B（作品深度）。
- art-002 扎克·施奈德"我拍了影史最gay的电影"——2026-09-15 Variety 专访（TIFF 首映
  次日，酒店大堂），中文稿 09-17 传开。原始英文出处 + 三个独立英文来源同日佐证；
  中文二手稿（360娱乐）只作"中文舆论如何转述"的素材，不作事实底本（页内自带的
  "记者愣了三秒""全片没有一句台词"等细节在英文源中查无实据）。
  即时窗口；content_map D（人物争议）。

读者面零自证：不出现来源自证句、不写播出通告句、不把热榜名次写成事实；证据归因
全部落在后台账本。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scripts.generate_daily_001 as base

base.ROOT = Path("runs/2026-09-17/daily-009")
ROOT = base.ROOT
CONTRACT = base.CONTRACT
RUN_ID = "2026-09-17/daily-009"
GROUP_ID = "article-group-2026-09-17-001"
CAPTURED_AT = "2026-09-17T23:55:00+08:00"


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


def ref(path: str, version: str = "1.0") -> dict:
    return {"path": path, "version": version, "sha256": digest(ROOT / path)}


# --------------------------------------------------------------------------
# 0) Discovery radar (R0)
# --------------------------------------------------------------------------

RADAR_RECORDS = [
    ("dailyhot-zhihu", "630000", "《雍正王朝》中为什么康熙总是不急不慢、智珠在握的感觉，而雍正却动不动就发火大喊大叫？", 1),
    ("wechat-mp-taotao", "-", "扎克·施奈德：我拍过影史最Gay的电影", 1),
]


# --------------------------------------------------------------------------
# 1) Sources
# --------------------------------------------------------------------------

SOURCES = {
    "src-gmw-jiaohuang-1999": {
        "source_role": "media_report",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "https://www.gmw.cn/01gmrb/1999-01/21/GB/17944%5EGM6-2116.HTM",
        "source_type": "media_report",
        "artifact_path": "sources/yongzheng-gmw1999-jiaohuang.txt",
        "captured_from": "光明日报 1999-01-21《雍正王朝》报道（焦晃表演方法与评论家评价）",
    },
    "src-sina-tangguoqiang-1999": {
        "source_role": "media_report",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "https://www.sina.com.cn/",
        "source_type": "media_report",
        "artifact_path": "sources/yongzheng-sina1999-tangguoqiang.txt",
        "captured_from": "《中国电影报》1999-02-05 唐国强访谈（新浪存档）：雍正性格定位、勤政数字、表演复盘",
    },
    "src-cctv-drama-intro": {
        "source_role": "official_fact",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "event_exists",
        "capability_levels": ["event_exists", "character_setup"],
        "source_url": "https://tv.cctv.com/",
        "source_type": "official",
        "artifact_path": "sources/yongzheng-cctv-drama-intro.txt",
        "captured_from": "央视网《雍正王朝》节目官网页（简介与主要事件清单）",
    },
    "src-wiki-yongzheng-drama": {
        "source_role": "encyclopedia",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus"],
        "source_capability": "event_exists",
        "capability_levels": ["event_exists", "character_setup"],
        "source_url": "https://zh.wikipedia.org/wiki/雍正王朝",
        "source_type": "encyclopedia",
        "artifact_path": "sources/yongzheng-wiki-drama.txt",
        "captured_from": "维基百科《雍正王朝》（剧集事实、演员表、奖项、剧情大纲）",
    },
    "src-wiki-kangxi-emperor": {
        "source_role": "encyclopedia",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus"],
        "source_capability": "event_exists",
        "capability_levels": ["event_exists"],
        "source_url": "https://zh.wikipedia.org/wiki/康熙帝",
        "source_type": "encyclopedia",
        "artifact_path": "sources/yongzheng-wiki-kangxi-emperor.txt",
        "captured_from": "维基百科「康熙帝」（在位年限等历史事实）",
    },
    "src-comment-kangxi-shenmi": {
        "source_role": "commentary",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["character_setup", "mechanism"],
        "source_url": "https://baijiahao.baidu.com/",
        "source_type": "commentary",
        "artifact_path": "sources/yongzheng-comment-baijiahao-kangxi-buxingyuse.txt",
        "captured_from": "自媒体评论（2018-08-31）：焦晃的康熙喜怒不形于色、真意都在话外",
    },
    "src-comment-acting-rank": {
        "source_role": "commentary",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["character_setup", "mechanism"],
        "source_url": "https://www.163.com/",
        "source_type": "commentary",
        "artifact_path": "sources/yongzheng-comment-netease-acting-ranking.txt",
        "captured_from": "网易号评论（演技排序）：并列另一种口径——雍正\"满分一百零一拿到一百分\"",
    },
    "src-wiki-yongzheng-emperor": {
        "source_role": "encyclopedia",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup"],
        "source_url": "https://zh.wikipedia.org/wiki/雍正帝",
        "source_type": "encyclopedia",
        "artifact_path": "sources/yongzheng-wiki-yongzheng-emperor.txt",
        "captured_from": "维基百科「雍正帝」（即位年龄与在位年限等历史事实）",
    },
    "src-comment-kangxi-diwangzhishu": {
        "source_role": "commentary",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["character_setup", "mechanism"],
        "source_url": "https://www.163.com/",
        "source_type": "commentary",
        "artifact_path": "sources/yongzheng-comment-netease-kangxi-diwangzhishu.txt",
        "captured_from": "网易号评论：康熙的棋盘式处理与弥留之际的观感",
    },
    "src-variety-interview": {
        "source_role": "media_report",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "https://variety.com/2026/film/features/zack-snyder-responds-last-photograph-bad-reviews-fascist-1236862796/",
        "source_type": "media_report",
        "artifact_path": "sources/snyder-variety-archive-today.txt",
        "captured_from": "Variety 专访（Marlow Stern，2026-09-15，多伦多酒店大堂；archive.today 全页快照）",
    },
    "src-avclub": {
        "source_role": "media_report",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "event_exists",
        "capability_levels": ["event_exists", "mechanism"],
        "source_url": "https://www.avclub.com/zack-snyder-last-photograph-interview-says-300-gayest-film-ever-made",
        "source_type": "media_report",
        "artifact_path": "sources/snyder-avclub.txt",
        "captured_from": "AV Club（2026-09-15）独立复述同一句原话与采访者出处",
    },
    "src-ign": {
        "source_role": "media_report",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "event_exists",
        "capability_levels": ["event_exists"],
        "source_url": "https://www.ign.com/articles/zack-snyder-says-300-is-the-gayest-movie-ever-made-defends-the-last-photograph-amid-online-backlash",
        "source_type": "media_report",
        "artifact_path": "sources/snyder-ign.txt",
        "captured_from": "IGN（2026-09-15）逐字引用同一段回答并注明出处",
    },
    "src-vulture": {
        "source_role": "commentary",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["mechanism"],
        "source_url": "https://www.vulture.com/article/zack-snyder-300-fascist-gayest-movie-ever.html",
        "source_type": "commentary",
        "artifact_path": "sources/snyder-vulture.txt",
        "captured_from": "Vulture（2026-09-15）评论：这句话能否当反法西斯挡箭牌",
    },
    "src-wiki-300": {
        "source_role": "encyclopedia",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus"],
        "source_capability": "event_exists",
        "capability_levels": ["event_exists", "mechanism"],
        "source_url": "https://en.wikipedia.org/wiki/300_(film)",
        "source_type": "encyclopedia",
        "artifact_path": "sources/snyder-wiki-300.txt",
        "captured_from": "维基百科 300 (film)：改编来源、阵容、成本与票房、柏林首映、伊朗抗议",
    },
    "src-wiki-lastphotograph": {
        "source_role": "encyclopedia",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus"],
        "source_capability": "event_exists",
        "capability_levels": ["event_exists"],
        "source_url": "https://en.wikipedia.org/wiki/The_Last_Photograph_(2026_film)",
        "source_type": "encyclopedia",
        "artifact_path": "sources/snyder-wiki-lastphotograph-2026.txt",
        "captured_from": "维基百科 The Last Photograph (2026)：主创、首映场合、口碑聚合分数",
    },
    "src-360-yule": {
        "source_role": "commentary",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "event_exists",
        "capability_levels": ["event_exists"],
        "source_url": "https://m.yule.360.com/content/5209350",
        "source_type": "commentary",
        "artifact_path": "sources/snyder-360-yule.html",
        "captured_from": "360娱乐（2026-09-17，自媒体稿）：中文舆论如何转述这句话",
        "usage_note": "自媒体稿，页内自带\"仅代表作者本人观点\"；其中\"现场记者愣了三秒\"\"全片没有一句台词\"等细节在英文来源中查无实据——只用于核验中文转述口径，不作事实底本。",
    },
}


# --------------------------------------------------------------------------
# 2) Candidate pool
# --------------------------------------------------------------------------

CANDIDATES = [
    {
        "candidate_id": "cand-yongzheng-kangxi-steady-001",
        "work": "雍正王朝（1999，胡玫执导）",
        "work_title": "雍正王朝",
        "signal": "知乎热榜：为什么康熙总是不急不慢、智珠在握，雍正却动不动就发火大喊大叫（630000）",
        "signal_source": "dailyhot-zhihu",
        "topic_mode": "revisit",
        "article_mode": "reported_feature",
        "content_map": "B",
        "event_cluster_id": "yongzheng-kangxi-yongzheng-contrast",
        "content_map_label": "作品深度",
        "freshness_window": "revival",
        "remove_timestamp_test": "pass",
        "evidence_readiness": "high",
        "recommendation": "A",
        "editorial_value_score": 8,
        "reader": "看过《雍正王朝》、对康熙与雍正两种\"当家人\"状态有体感的观众",
        "landing": "看懂两个人的差别不在脾气：康熙手上还有牌，雍正的牌就是他自己",
        "emotion": "恍然",
        "social_motive": "表达立场",
        "reader_question": "为什么康熙能不急，雍正却动不动就发火",
        "core_question": "为什么康熙能不急，雍正却动不动就发火",
        "angle": "演员自己在 1999 年就给了答案的一角：唐国强承认暴躁演多了；而康熙的从容来自他手上确实还有牌",
        "source_refs": ["src-sina-tangguoqiang-1999", "src-gmw-jiaohuang-1999"],
        "prior_run_conflict": False,
        "selection_reason": "知乎热榜当日信号 + 常青老剧议题；两侧都有 1999 年一手报道支撑（演员自评 + 评论家落点），并有相反口径评论可并列；无同作品历史批次，五问全过",
    },
    {
        "candidate_id": "cand-snyder-300-gayest-001",
        "work": "扎克·施奈德与《300勇士》",
        "work_title": "300勇士",
        "signal": "微信公众号（桃桃淘电影 2026-09-17）：扎克·施奈德：我拍过影史最Gay的电影",
        "signal_source": "wechat-mp-taotao",
        "topic_mode": "culture",
        "article_mode": "reported_feature",
        "content_map": "D",
        "event_cluster_id": "snyder-300-gayest-remark",
        "content_map_label": "人物争议",
        "freshness_window": "same-day",
        "remove_timestamp_test": "pass",
        "evidence_readiness": "high",
        "recommendation": "A",
        "editorial_value_score": 9,
        "reader": "看过《300勇士》、对\"直男大片里的男性凝视\"这个话题有兴趣的观众",
        "landing": "这句话是被记者追问出来的自辩，却意外说中《300勇士》的底牌：那套英雄叙事的燃料是男人看男人",
        "emotion": "会心",
        "social_motive": "表达立场",
        "reader_question": "施奈德为什么说《300勇士》是影史最gay的电影，他到底什么意思",
        "core_question": "施奈德为什么要说《300勇士》是影史最gay的电影",
        "angle": "名人言论的归属争议：原话、场合、动机与被追问的经过，都比中文转述复杂；而《300勇士》的拍摄选择早就把答案写在画面上",
        "source_refs": ["src-variety-interview", "src-avclub", "src-wiki-300"],
        "prior_run_conflict": False,
        "selection_reason": "归属争议型选题（名人言论）优先级最高；原始英文出处 + 3 个独立英文来源同日佐证，另有维基页面提供影片与伊朗争议的硬事实；中文二手稿仅作转述口径核验；无同作品历史批次，五问全过",
    },
]

REJECTED_PRIOR_WORKS = [
    {"work": "姜文电影 / 还珠格格", "reason": "daily-008 已写，本批不重复"},
    {"work": "兰香如故 / 国产剧起名", "reason": "daily-007 已写，本批不重复"},
    {"work": "2026 国庆档片单", "reason": "材料充分（灯塔/猫眼/新浪多家），但本批组合让位：两篇需象限与事件簇分离，国庆档与施奈德选题同属即时窗口"},
    {"work": "《怦然心动》导演夫妇凶案新进展", "reason": "涉未决司法与悲剧隐私，禁区"},
    {"work": "王鹤棣聊天记录 / 许嵩冯禧恋情 / 姚安娜 / 刘亦菲\"黑料\"", "reason": "隐私八卦类信号，违反选题边界，不入选题"},
    {"work": "女演员心脏骤停后复出", "reason": "健康隐私依赖，边界不清"},
    {"work": "《加勒比海盗》巴博萨演员传闻", "reason": "仅外网传言，无一手可核来源"},
    {"work": "红果短剧日活超四大平台", "reason": "数据密集、口径依赖平台自述，当批未选"},
]

SLOT_DECISIONS = [
    {
        "slot": 1,
        "article_id": "art-001",
        "candidate_id": "cand-yongzheng-kangxi-steady-001",
        "decision": "selected",
        "event_cluster_id": "yongzheng-kangxi-yongzheng-contrast",
    },
    {
        "slot": 2,
        "article_id": "art-002",
        "candidate_id": "cand-snyder-300-gayest-001",
        "decision": "selected",
        "event_cluster_id": "snyder-300-gayest-remark",
    },
]


# --------------------------------------------------------------------------
# 3) Briefs, task cards, task hierarchy
# --------------------------------------------------------------------------

TASK_CARD_REQUIRED_FIELDS = {
    "art-001": (
        "1. **站队点/可转述句**：康熙的从容不是修养好，是他手上还有牌；雍正的暴躁不是脾气差，是他手上只剩自己。\n"
        "2. **读者已知锚点**：《雍正王朝》是公认的历史剧标杆；焦晃的康熙与唐国强的雍正谁更出色，是这部剧二十多年来的老话题。\n"
        "3. **today-hook 理由**：知乎热榜当日把\"康熙不急、雍正暴躁\"重新问了出来；老剧重看议题不依赖单一新闻节点。\n"
        "4. **事实底座**：1999 年 1 月央视一套首播、44 集、胡玫执导、刘和平与二月河编剧、央视一套晚八点档迄今收视率最高；唐国强自评\"有的地方感到暴躁的过多了，这都是我本身缺乏的\"；雍正\"性格急躁、尖刻、记仇\"与\"用雷霆手段行菩萨心肠\"；在位 13 年、平均每天批 40 多个折子；康熙在位六十一年十个月；雍正即位时户部亏空白银二百多万两（来源见后台账本）。\n"
        "5. **最强钩子**：唐国强自评：有的地方感到暴躁的过多了（与 batch.json 的 review_hook 一致）。\n"
        "- **title_promise**：康熙为什么能不急，雍正却动不动就发火\n"
        "- **ending_destination**：康熙手里有牌，可以等；雍正的牌就是他自己，等不起。\n"
        "\n## 文章结构大纲（H2 目录）\n"
        "## 康熙不急，雍正暴躁\n"
        "## 焦晃演的康熙，是一个手上还有牌的人\n"
        "## 唐国强给雍正的定位：急躁、尖刻、记仇\n"
        "## \"有的地方感到暴躁的过多了\"\n"
        "## 雍正的急，是那副牌逼出来的\n"
    ),
    "art-002": (
        "1. **站队点/可转述句**：这句话是被记者追问出来的自辩，却意外说准了《300勇士》的底牌——那套英雄叙事的燃料，本来就是男人看男人。\n"
        "2. **读者已知锚点**：《300勇士》是 2006 年的现象级影片，\"这就是斯巴达\"和满屏腹肌是共同记忆；施奈德是《守望者》《超人：钢铁之躯》的导演。\n"
        "3. **today-hook 理由**：施奈德 9 月 15 日为宣传新片《最后一张照片》接受专访时说出这句话，中文稿 9 月 17 日传开。\n"
        "4. **事实底座**：《300勇士》改编自弗兰克·米勒与 Lynn Varley 1998 年 Dark Horse 漫画；成本 6500 万美元、全球票房 4.688 亿美元；北美首周末 7088 万美元；迈克尔·法斯宾德银幕处女作；伊朗艺术学院向联合国教科文组织提交正式抗议、影片在伊朗被禁；新片《最后一张照片》烂番茄 21%（14 篇）、Metacritic 16 分、只拍了 32 天（来源见后台账本）。\n"
        "5. **最强钩子**：《300勇士》是影史最gay的电影之一；那句\"最gay\"出自他回忆中的柏林记者会（与 batch.json 的 review_hook 一致）。\n"
        "- **title_promise**：施奈德为什么说《300勇士》是影史最gay的电影\n"
        "- **ending_destination**：一部电影能让人带着成见进去、带着别的东西出来，这大概是导演最想要的那件事。\n"
        "\n## 文章结构大纲（H2 目录）\n"
        "## 那句话不是在台上说的\n"
        "## 他为什么要拿\"最gay\"挡\"法西斯\"\n"
        "## 《300勇士》确实是一部关于男性身体的电影\n"
        "## 伊朗抗议过，报纸写\"300对7000万\"\n"
        "## 一句自嘲，说中了他电影的底牌\n"
    ),
}

STRONGEST_HOOKS = {
    "art-001": "唐国强自评：有的地方感到暴躁的过多了",
    "art-002": "《300勇士》是影史最gay的电影之一；那句\"最gay\"出自他回忆中的柏林记者会",
}


# --------------------------------------------------------------------------
# 4) Material packs（by_source 全部逐字取自来源文件）
# --------------------------------------------------------------------------

MATERIAL_SPECS = {
    "art-001": {
        "mode": "reported_feature",
        "role": "media_report",
        "source_ids": [
            "src-sina-tangguoqiang-1999",
            "src-gmw-jiaohuang-1999",
            "src-cctv-drama-intro",
            "src-wiki-yongzheng-drama",
            "src-comment-kangxi-shenmi",
            "src-comment-acting-rank",
            "src-wiki-kangxi-emperor",
            "src-wiki-yongzheng-emperor",
            "src-comment-kangxi-diwangzhishu",
        ],
        "question": "为什么康熙能不急，雍正却动不动就发火",
        "mechanism": "两个人的差别在处境：康熙手上还有牌，可以等、可以让儿子们先表演；雍正接手的是亏空、兄弟与新政，必须自己冲上去，急是那副牌逼出来的",
        "facts": [
            {"text": "有的地方感到暴躁的过多了，这都是我本身缺乏的", "level": "mechanism", "locator": "中国电影报: 唐国强自评暴躁", "source_id": "src-sina-tangguoqiang-1999", "plan_kind": "mechanism"},
            {"text": "雍正有“冷面王”之称，他性格急躁、尖刻、记仇", "level": "character_setup", "locator": "中国电影报: 雍正性格定位", "source_id": "src-sina-tangguoqiang-1999", "plan_kind": "mechanism"},
            {"text": "有人说过，雍正是用雷霆手段行菩萨心肠", "level": "mechanism", "locator": "中国电影报: 雷霆手段", "source_id": "src-sina-tangguoqiang-1999", "plan_kind": "mechanism"},
            {"text": "雍正是历史上最勤政的一个皇帝，在位13年，平均每天批40多个折子", "level": "event_exists", "locator": "中国电影报: 勤政数字", "source_id": "src-sina-tangguoqiang-1999", "plan_kind": "specific_context"},
            {"text": "开始导演想让我演八贤王", "level": "event_exists", "locator": "中国电影报: 角色争取", "source_id": "src-sina-tangguoqiang-1999", "plan_kind": "specific_context"},
            {"text": "58岁就因心肺病去世了。他是苦死、累死的", "level": "event_exists", "locator": "中国电影报: 雍正结局", "source_id": "src-sina-tangguoqiang-1999", "plan_kind": "specific_context"},
            {"text": "大多评论家认为他成功地塑造了一位血脉已衰仍然威驭天下的一代君王形象", "level": "mechanism", "locator": "光明日报: 威驭天下", "source_id": "src-gmw-jiaohuang-1999", "plan_kind": "mechanism"},
            {"text": "我的每一个人物都是从心里长出来的", "level": "character_setup", "locator": "光明日报: 焦晃方法", "source_id": "src-gmw-jiaohuang-1999", "plan_kind": "mechanism"},
            {"text": "唐国强很有深度地刻画了这个“冷面王”复杂的个性和充满矛盾的内心世界", "level": "mechanism", "locator": "光明日报: 冷面王的内心", "source_id": "src-gmw-jiaohuang-1999", "plan_kind": "mechanism"},
            {"text": "康熙皇帝驾崩，继位者为“冷面王”四阿哥", "level": "event_exists", "locator": "央视网: 冷面王继位", "source_id": "src-cctv-drama-intro", "plan_kind": "specific_context"},
            {"text": "铁帽子亲王大殿发难逼宫", "level": "event_exists", "locator": "央视网: 逼宫事件", "source_id": "src-cctv-drama-intro", "plan_kind": "specific_context"},
            {"text": "由唐国强、焦晃、王绘春、杜志国、赵毅、王辉等人主演，全剧共44集，于1999年1月在中央电视台一套晚间剧场首播", "level": "event_exists", "locator": "维基: 阵容与首播", "source_id": "src-wiki-yongzheng-drama", "plan_kind": "specific_context"},
            {"text": "胡玫导演，二月河、刘和平编剧", "level": "event_exists", "locator": "维基: 导演与编剧", "source_id": "src-wiki-yongzheng-drama", "plan_kind": "specific_context"},
            {"text": "该剧是央视一套迄今晚八点电视剧中收视率最高的一部", "level": "event_exists", "locator": "维基: 收视", "source_id": "src-wiki-yongzheng-drama", "plan_kind": "specific_context"},
            {"text": "雍正積勞成疾病倒在滿堆奏摺前，享年五十八歲", "level": "event_exists", "locator": "维基: 剧情结局", "source_id": "src-wiki-yongzheng-drama", "plan_kind": "specific_context"},
            {"text": "雍正在朝堂上怒斥胤禩等人為「阿其那」、「塞思黑」", "level": "event_exists", "locator": "维基: 朝堂怒斥", "source_id": "src-wiki-yongzheng-drama", "plan_kind": "specific_context"},
            {"text": "焦晃的康熙，喜怒不形于色，内心思虑让外人无法猜测甚至其子女", "level": "mechanism", "locator": "评论: 喜怒不形于色", "source_id": "src-comment-kangxi-shenmi", "plan_kind": "mechanism"},
            {"text": "如果说焦晃版康熙是在满分一百分的状况下拿足了一百分，唐版雍正则是在满分一百零一的情况下拿到了一百分", "level": "mechanism", "locator": "评论: 相反口径", "source_id": "src-comment-acting-rank", "plan_kind": "mechanism"},
            {"text": "他不动声色地观察棋盘，设置棋局，了解棋子，打圆场或者收拾残局", "level": "mechanism", "locator": "评论: 棋盘式处理", "source_id": "src-comment-kangxi-diwangzhishu", "plan_kind": "mechanism"},
            {"text": "仿佛这不是一个将死之人，而只是一只装睡的老虎", "level": "mechanism", "locator": "评论: 装睡的老虎", "source_id": "src-comment-kangxi-diwangzhishu", "plan_kind": "mechanism"},
            {"text": "在位六十一年十個月，是中國歷史上在位時間最長的皇帝", "level": "event_exists", "locator": "维基康熙: 在位年限", "source_id": "src-wiki-kangxi-emperor", "plan_kind": "specific_context"},
            {"text": "他读原著，查清史，甚至把剧中所有的台词都做成了卡片，随身携带着，一有空就琢磨", "level": "scene_action", "locator": "光明日报: 台词卡片", "source_id": "src-gmw-jiaohuang-1999", "plan_kind": "specific_context"},
            {"text": "不会喝酒的唐国强极为投入，喝干了一瓶二锅头，醉眼朦胧", "level": "scene_action", "locator": "光明日报: 醉酒戏", "source_id": "src-gmw-jiaohuang-1999", "plan_kind": "specific_context"},
            {"text": "一生滴酒不沾的雍正晚年承受着巨大的痛苦，一天突然想喝酒", "level": "scene_action", "locator": "光明日报: 晚年醉酒", "source_id": "src-gmw-jiaohuang-1999", "plan_kind": "specific_context"},
            {"text": "雍正累積許久的壓力，終於忍耐不住，跪在佛前痛哭失聲。", "level": "event_exists", "locator": "维基: 佛前痛哭", "source_id": "src-wiki-yongzheng-drama", "plan_kind": "specific_context"},
            {"text": "胤禩結合胤禟、胤䄉以及關外四位鐵帽子王進京，意圖與宮內隆科多圖謀發動政變，改立皇三子弘時繼位", "level": "event_exists", "locator": "维基: 逼宫与改立", "source_id": "src-wiki-yongzheng-drama", "plan_kind": "specific_context"},
            {"text": "康熙率眾皇子到熱河行宮圍獵，此時太子已經失寵，眾位阿哥爭相在康熙御前突出自己", "level": "event_exists", "locator": "维基: 热河围猎与太子失宠", "source_id": "src-wiki-yongzheng-drama", "plan_kind": "specific_context"},
            {"text": "但八阿哥暗中更換為一隻死鷹（即暗示詛咒父親將死的意思），康熙當場昏倒", "level": "event_exists", "locator": "维基: 死鹰事件", "source_id": "src-wiki-yongzheng-drama", "plan_kind": "specific_context"},
            {"text": "康熙亦知道自己將會死去，故佈置一切，例如起用一直被打壓的隆科多", "level": "event_exists", "locator": "维基: 布置后事与隆科多", "source_id": "src-wiki-yongzheng-drama", "plan_kind": "specific_context"},
            {"text": "第19屆中國電視劇飛天獎 長篇電視劇 一等獎 《雍正王朝》 獲獎", "level": "event_exists", "locator": "维基: 飞天奖", "source_id": "src-wiki-yongzheng-drama", "plan_kind": "specific_context"},
            {"text": "優秀男演員 焦晃 獲獎", "level": "event_exists", "locator": "维基: 飞天奖优秀男演员", "source_id": "src-wiki-yongzheng-drama", "plan_kind": "specific_context"},
            {"text": "最佳男主角 唐國強 獲獎", "level": "event_exists", "locator": "维基: 金鹰奖最佳男主角", "source_id": "src-wiki-yongzheng-drama", "plan_kind": "specific_context"},
            {"text": "最佳男配角 焦晃 獲獎", "level": "event_exists", "locator": "维基: 金鹰奖最佳男配角", "source_id": "src-wiki-yongzheng-drama", "plan_kind": "specific_context"},
            {"text": "而被列入“奶油小生”行列的唐国强", "level": "character_setup", "locator": "光明日报: 奶油小生", "source_id": "src-gmw-jiaohuang-1999", "plan_kind": "specific_context"},
            {"text": "八阿哥只能在康熙帝死去之時強調康熙帝傳位給「十」四阿哥", "level": "event_exists", "locator": "维基: 十四阿哥之争", "source_id": "src-wiki-yongzheng-drama", "plan_kind": "specific_context"},
            {"text": "雍正在朝堂上怒斥胤禩等人為「阿其那」、「塞思黑」，胤祥積勞成疾，不久後身亡", "level": "event_exists", "locator": "维基: 怒斥与胤祥", "source_id": "src-wiki-yongzheng-drama", "plan_kind": "specific_context"},
            {"text": "雍正累積許久的壓力，終於忍耐不住，跪在佛前痛哭失聲", "level": "event_exists", "locator": "维基: 西北大捷后", "source_id": "src-wiki-yongzheng-drama", "plan_kind": "specific_context"},
            {"text": "剧中有意识地多次表现了雍正在批折子，昼夜如此", "level": "event_exists", "locator": "中国电影报: 批折子", "source_id": "src-sina-tangguoqiang-1999", "plan_kind": "specific_context"},
            {"text": "后来导演对我说，你来吧，就演雍正皇帝", "level": "event_exists", "locator": "中国电影报: 定角经过", "source_id": "src-sina-tangguoqiang-1999", "plan_kind": "specific_context"},
            {"text": "看完剧本后，我对雍正很感兴趣", "level": "event_exists", "locator": "中国电影报: 选角动机", "source_id": "src-sina-tangguoqiang-1999", "plan_kind": "specific_context"},
            {"text": "我提出要试试妆", "level": "event_exists", "locator": "中国电影报: 试妆", "source_id": "src-sina-tangguoqiang-1999", "plan_kind": "specific_context"},
            {"text": "而要着重表现他内心涌动的激情、冲动", "level": "mechanism", "locator": "中国电影报: 表演选择", "source_id": "src-sina-tangguoqiang-1999", "plan_kind": "mechanism"},
            {"text": "仅户部就亏空白银二百多万两", "level": "event_exists", "locator": "维基雍正帝: 户部亏空", "source_id": "src-wiki-yongzheng-emperor", "plan_kind": "specific_context"},
            {"text": "康熙末年吏治松弛，贪污成风，加上诸王皇族同官僚结党营私，致使财政经济从中央到地方混乱不堪", "level": "mechanism", "locator": "维基雍正帝: 积弊甚大", "source_id": "src-wiki-yongzheng-emperor", "plan_kind": "mechanism"},
            {"text": "此時軍機處的大臣也已找到皇上，並親口告知雍正西北大捷一事", "level": "event_exists", "locator": "维基: 西北大捷", "source_id": "src-wiki-yongzheng-drama", "plan_kind": "specific_context"},
            {"text": "“摊丁入亩、火耗归公”、“士绅一体当差、一体纳粮”、“河南罢考案”", "level": "event_exists", "locator": "央视网: 新政事件", "source_id": "src-cctv-drama-intro", "plan_kind": "specific_context"},
            {"text": "由於雍正即位時正處於政治歷練、精神與人格上的成熟階段（45歲）", "level": "event_exists", "locator": "维基雍正帝: 即位年龄", "source_id": "src-wiki-yongzheng-emperor", "plan_kind": "specific_context"},
        ],
        "by_source": {
            "src-sina-tangguoqiang-1999": [
                "有的地方感到暴躁的过多了，这都是我本身缺乏的。",
                "雍正有“冷面王”之称，他性格急躁、尖刻、记仇。",
                "作为演员，我觉得不能过多地表现他的冷面孔，冷仅仅是他表面的壳",
                "有人说过，雍正是用雷霆手段行菩萨心肠。我很赞同这一说法。",
                "雍正是历史上最勤政的一个皇帝，在位13年，平均每天批40多个折子",
                "开始导演想让我演八贤王",
                "58岁就因心肺病去世了。他是苦死、累死的。",
                "剧中有意识地多次表现了雍正在批折子，昼夜如此。",
                "后来导演对我说，你来吧，就演雍正皇帝。",
                "而要着重表现他内心涌动的激情、冲动",
                "看完剧本后，我对雍正很感兴趣",
                "我提出要试试妆",
            ],
            "src-gmw-jiaohuang-1999": [
                "大多评论家认为他成功地塑造了一位血脉已衰仍然威驭天下的一代君王形象。",
                "我的每一个人物都是从心里长出来的。",
                "唐国强很有深度地刻画了这个“冷面王”复杂的个性和充满矛盾的内心世界",
                "他与北京的于是之在话剧界享有“南焦北于”的极大声誉",
                "这次焦晃是舍弃了陈凯歌的影片《荆柯刺秦王》中高渐离一角而走进《雍正王朝》的",
                "而被列入“奶油小生”行列的唐国强",
                "他读原著，查清史，甚至把剧中所有的台词都做成了卡片，随身携带着，一有空就琢磨。",
                "不会喝酒的唐国强极为投入，喝干了一瓶二锅头，醉眼朦胧，涕泗交加，一次又一次重复着台词：“朕真的醉了吗？”",
                "一生滴酒不沾的雍正晚年承受着巨大的痛苦，一天突然想喝酒",
            ],
            "src-cctv-drama-intro": [
                "康熙皇帝驾崩，继位者为“冷面王”四阿哥。",
                "“铁帽子亲王大殿发难逼宫”、“含泪杀亲子”",
                "“摊丁入亩、火耗归公”、“士绅一体当差、一体纳粮”、“河南罢考案”",
            ],
            "src-wiki-yongzheng-drama": [
                "由唐国强、焦晃、王绘春、杜志国、赵毅、王辉等人主演，全剧共44集，于1999年1月在中央电视台一套晚间剧场首播。",
                "《雍正王朝》是1999年由中国中央电视台制作，胡玫导演，二月河、刘和平编剧",
                "该剧是央视一套迄今晚八点电视剧中收视率最高的一部",
                "雍正積勞成疾病倒在滿堆奏摺前，享年五十八歲。",
                "雍正在朝堂上怒斥胤禩等人為「阿其那」、「塞思黑」",
                "雍正累積許久的壓力，終於忍耐不住，跪在佛前痛哭失聲。",
                "胤禩結合胤禟、胤䄉以及關外四位鐵帽子王進京，意圖與宮內隆科多圖謀發動政變，改立皇三子弘時繼位",
                "康熙率眾皇子到熱河行宮圍獵，此時太子已經失寵，眾位阿哥爭相在康熙御前突出自己",
                "但八阿哥暗中更換為一隻死鷹（即暗示詛咒父親將死的意思），康熙當場昏倒",
                "康熙亦知道自己將會死去，故佈置一切，例如起用一直被打壓的隆科多",
                "第19屆中國電視劇飛天獎 長篇電視劇 一等獎 《雍正王朝》 獲獎",
                "最佳男主角 唐國強 獲獎",
                "最佳男配角 焦晃 獲獎",
                "八阿哥只能在康熙帝死去之時強調康熙帝傳位給「十」四阿哥",
                "雍正在朝堂上怒斥胤禩等人為「阿其那」、「塞思黑」，胤祥積勞成疾，不久後身亡",
                "雍正累積許久的壓力，終於忍耐不住，跪在佛前痛哭失聲",
                "此時軍機處的大臣也已找到皇上，並親口告知雍正西北大捷一事",
            ],
            "src-comment-kangxi-shenmi": [
                "焦晃的康熙，喜怒不形于色，内心思虑让外人无法猜测甚至其子女，跟臣下说话时真正要表达的都在话外",
            ],
            "src-comment-acting-rank": [
                "如果说焦晃版康熙是在满分一百分的状况下拿足了一百分，唐版雍正则是在满分一百零一的情况下拿到了一百分。",
            ],
            "src-comment-kangxi-diwangzhishu": [
                "他不动声色地观察棋盘，设置棋局，了解棋子，打圆场或者收拾残局。",
                "仿佛这不是一个将死之人，而只是一只装睡的老虎。",
            ],
            "src-wiki-kangxi-emperor": [
                "在位六十一年十個月，是中國歷史上在位時間最長的皇帝",
            ],
            "src-wiki-yongzheng-emperor": [
                "由於雍正即位時正處於政治歷練、精神與人格上的成熟階段（45歲）",
                "仅户部就亏空白银二百多万两",
                "康熙末年吏治松弛，贪污成风，加上诸王皇族同官僚结党营私，致使财政经济从中央到地方混乱不堪",
            ],
        },
        "audience": "看过《雍正王朝》、对康熙与雍正两种\"当家人\"状态有体感的观众",
    },
    "art-002": {
        "mode": "reported_feature",
        "role": "media_report",
        "source_ids": [
            "src-variety-interview",
            "src-avclub",
            "src-ign",
            "src-wiki-300",
            "src-wiki-lastphotograph",
            "src-vulture",
            "src-360-yule",
        ],
        "question": "施奈德为什么要说《300勇士》是影史最gay的电影",
        "mechanism": "这句话是反法西斯自辩中被记者追问出来的；但它同时说准了《300勇士》的拍摄逻辑——男性身体与凝视原本就是那套英雄叙事的燃料",
        "facts": [
            {"text": "But obviously I’m pro-gay. I made the gayest movie ever made.", "level": "mechanism", "locator": "Variety: 原话", "source_id": "src-variety-interview", "plan_kind": "mechanism"},
            {"text": "is one of the gayest movies ever made", "level": "mechanism", "locator": "Variety: 追问后收窄", "source_id": "src-variety-interview", "plan_kind": "mechanism"},
            {"text": "You think “300” is the gayest movie ever made?", "level": "event_exists", "locator": "Variety: 记者追问", "source_id": "src-variety-interview", "plan_kind": "specific_context"},
            {"text": "Are you pro-gay or pro-NRA? Which are you?", "level": "event_exists", "locator": "Variety: 触发提问", "source_id": "src-variety-interview", "plan_kind": "specific_context"},
            {"text": "It’s the morning after the premiere and I’m sitting across from Snyder in the lobby of his Toronto hotel", "level": "event_exists", "locator": "Variety: 场合", "source_id": "src-variety-interview", "plan_kind": "specific_context"},
            {"text": "everyone booed and walked out", "level": "event_exists", "locator": "Variety: 柏林往事", "source_id": "src-variety-interview", "plan_kind": "specific_context"},
            {"text": "And obviously, I’m not a fascist", "level": "mechanism", "locator": "Variety: 自辩", "source_id": "src-variety-interview", "plan_kind": "mechanism"},
            {"text": "We shot this in 32 days", "level": "event_exists", "locator": "Variety: 新片拍摄", "source_id": "src-variety-interview", "plan_kind": "specific_context"},
            {"text": "Based on the 1998 Dark Horse Comics limited series of the same name by Frank Miller and Lynn Varley", "level": "event_exists", "locator": "维基300: 改编来源", "source_id": "src-wiki-300", "plan_kind": "specific_context"},
            {"text": "Michael Fassbender in his film debut", "level": "event_exists", "locator": "维基300: 法斯宾德处女作", "source_id": "src-wiki-300", "plan_kind": "specific_context"},
            {"text": "Budget $65 million", "level": "event_exists", "locator": "维基300: 成本", "source_id": "src-wiki-300", "plan_kind": "specific_context"},
            {"text": "submitted a formal complaint against the film to UNESCO", "level": "event_exists", "locator": "维基300: 伊朗抗议", "source_id": "src-wiki-300", "plan_kind": "specific_context"},
            {"text": "300 Against 70 Million", "level": "event_exists", "locator": "维基300: 伊朗报纸标题", "source_id": "src-wiki-300", "plan_kind": "specific_context"},
            {"text": "21% of 14 critics' reviews are positive", "level": "event_exists", "locator": "维基新片: 口碑", "source_id": "src-wiki-lastphotograph", "plan_kind": "specific_context"},
            {"text": "world premiere in the \"Special Events\" section of the 2026 Toronto International Film Festival on September 13", "level": "event_exists", "locator": "维基新片: 首映", "source_id": "src-wiki-lastphotograph", "plan_kind": "specific_context"},
            {"text": "The Iranian mission to the United Nations protested the film in a press release", "level": "event_exists", "locator": "维基300: 联合国抗议", "source_id": "src-wiki-300", "plan_kind": "specific_context"},
            {"text": "Iranian embassies protested its screening in France", "level": "event_exists", "locator": "维基300: 使馆抗议", "source_id": "src-wiki-300", "plan_kind": "specific_context"},
            {"text": "The film was banned in Iran", "level": "event_exists", "locator": "维基300: 伊朗禁映", "source_id": "src-wiki-300", "plan_kind": "specific_context"},
            {"text": "American propaganda", "level": "event_exists", "locator": "维基300: 被视为美国宣传", "source_id": "src-wiki-300", "plan_kind": "specific_context"},
            {"text": "Newspapers in Iran featured headlines such as", "level": "event_exists", "locator": "维基300: 伊朗报纸标题", "source_id": "src-wiki-300", "plan_kind": "specific_context"},
            {"text": "Hans Zimmer", "level": "event_exists", "locator": "维基新片: 配乐", "source_id": "src-wiki-lastphotograph", "plan_kind": "specific_context"},
            {"text": "135 minutes", "level": "event_exists", "locator": "维基新片: 片长", "source_id": "src-wiki-lastphotograph", "plan_kind": "specific_context"},
            {"text": "In April 2011, it was reported that Christian Bale and Sean Penn were in talks to star in the film The Last Photograph", "level": "event_exists", "locator": "维基新片: 项目沿革", "source_id": "src-wiki-lastphotograph", "plan_kind": "specific_context"},
            {"text": "Sex in movies is weirdly gone", "level": "mechanism", "locator": "Variety: 性爱消失", "source_id": "src-variety-interview", "plan_kind": "mechanism"},
            {"text": "there are few movies where people come in straight and come out gay", "level": "mechanism", "locator": "Variety: 直着进去弯着出来", "source_id": "src-variety-interview", "plan_kind": "mechanism"},
            {"text": "from a screenplay by Kurt Johnstad", "level": "event_exists", "locator": "维基新片: 编剧", "source_id": "src-wiki-lastphotograph", "plan_kind": "specific_context"},
            {"text": "based on an original story by", "level": "event_exists", "locator": "维基新片: 原创故事", "source_id": "src-wiki-lastphotograph", "plan_kind": "specific_context"},
            {"text": "Stuart Martin as Ethan Black", "level": "event_exists", "locator": "维基新片: 主演", "source_id": "src-wiki-lastphotograph", "plan_kind": "specific_context"},
            {"text": "directed by Niels Arden Oplev", "level": "event_exists", "locator": "维基新片: 2011版导演", "source_id": "src-wiki-lastphotograph", "plan_kind": "specific_context"},
        ],
        "by_source": {
            "src-variety-interview": [
                "But obviously I’m pro-gay. I made the gayest movie ever made.",
                "“300” is one of the gayest movies ever made.",
                "You think “300” is the gayest movie ever made?",
                "Are you pro-gay or pro-NRA? Which are you?",
                "It’s the morning after the premiere and I’m sitting across from Snyder in the lobby of his Toronto hotel.",
                "And obviously, I’m not a fascist.",
                "We shot this in 32 days.",
                "Sex in movies is weirdly gone",
                "there are few movies where people come in straight and come out gay",
            ],
            "src-avclub": [
                "But obviously I’m pro-gay. I made the gayest movie ever made.",
            ],
            "src-ign": [
                "But obviously I’m pro-gay. I made the gayest movie ever made",
            ],
            "src-vulture": [
                "the gayest movie ever made",
            ],
            "src-wiki-300": [
                "Based on the 1998 Dark Horse Comics limited series of the same name by Frank Miller and Lynn Varley",
                "The Iranian mission to the United Nations protested the film in a press release",
                "Iranian embassies protested its screening in France",
                "The film was banned in Iran",
                "American propaganda",
                "Newspapers in Iran featured headlines such as",
                "The film also features Michael Fassbender in his film debut.",
                "Budget $65 million",
                "The Iranian Academy of the Arts submitted a formal complaint against the film to UNESCO",
                "300 Against 70 Million",
            ],
            "src-wiki-lastphotograph": [
                "21% of 14 critics' reviews are positive, with an average rating of 3.7/10.",
                "Hans Zimmer",
                "135 minutes",
                "In April 2011, it was reported that Christian Bale and Sean Penn were in talks to star in the film The Last Photograph",
                "from a screenplay by Kurt Johnstad",
                "based on an original story by",
                "Stuart Martin as Ethan Black",
                "directed by Niels Arden Oplev",
                "The film had its world premiere in the \"Special Events\" section of the 2026 Toronto International Film Festival on September 13.",
            ],
            "src-360-yule": [
                "他表示，《斯巴达300勇士》是影史上最gay的电影之一",
            ],
        },
        "audience": "看过《300勇士》、对\"直男大片里的男性凝视\"这个话题有兴趣的观众",
    },
}


# --------------------------------------------------------------------------
# 5) Bodies
# --------------------------------------------------------------------------

BODIES = {
    "art-001": """## 康熙不急，雍正暴躁

同一部《雍正王朝》里，康熙和雍正像是两种坐法：一个到死都把手按在棋盘上，一个最后倒在堆满奏折的案前。

这两个人的差别，不在脾气，在他们各自接手的那副牌里。

1999年1月，这部剧在央视一套晚间剧场开播。44集，胡玫执导，刘和平与二月河编剧，唐国强、焦晃、王绘春、杜志国、赵毅、王辉主演；它是央视一套晚八点档迄今晚间电视剧中收视率最高的一部。金鹰奖把最佳男主角给了唐国强、最佳男配角给了焦晃，飞天奖把长篇电视剧一等奖和优秀男演员一起给了这部剧和焦晃。

## 焦晃演的康熙，是一个手上还有牌的人

有评论形容焦晃的康熙：喜怒不形于色，内心思虑让外人无法猜测甚至其子女，跟臣下说话时真正要表达的都在话外。另一篇评论写的是他的处理方式：他不动声色地观察棋盘，设置棋局，了解棋子，打圆场或者收拾残局；写到弥留之际的康熙时，那篇评论的形容是——仿佛这不是一个将死之人，而只是一只装睡的老虎。

焦晃本人的说法是"从心里长出来"：创造每一个角色，仿佛都是浇灌一棵正在成长的树，要调动心理机制和生理机制的每一个细胞，把关于人物的假定性的东西化为真实的感受，从而达到表演的沸点。为了康熙这个角色，他推掉了陈凯歌《荆轲刺秦王》里的高渐离。大多评论家认为他塑造的是一位"血脉已衰仍然威驭天下"的君王。

焦晃在这之前是话剧舞台上的演员，与北京的于是之并称"南焦北于"；唐国强则是从被叫作"奶油小生"的银幕形象里走出来的。两个人的来路不同。

康熙的慢，是他手上确实还有牌。康熙率众皇子到热河行宫围猎时，太子已经失宠，诸位阿哥争着在御前表现；八阿哥把十四阿哥送的寿礼换成一只死鹰，康熙当场昏倒。他自知将死，开始布置一切，包括起用一直被压制的隆科多，最后传位四阿哥。一个还能安排后事的人，不需要大喊大叫。

## 唐国强给雍正的定位：急躁、尖刻、记仇

雍正这个角色是唐国强自己争来的。开始导演想让他演八贤王，他看完剧本对雍正更感兴趣，提出要试妆；后来导演对他说，你来吧，就演雍正皇帝。

他给雍正的性格下的判断很直接：雍正有"冷面王"之称，性格急躁、尖刻、记仇；但作为演员，不能过多地表现他的冷面孔，冷仅仅是他表面的壳，而要着重表现他内心涌动的激情、冲动。他还赞同过一句评价：雍正是用雷霆手段行菩萨心肠。

为了这个人物，他读原著、查清史，把剧中所有台词都做成了卡片随身带着，一有空就琢磨。有一场戏，一生滴酒不沾的雍正晚年承受着巨大的痛苦，一天突然想喝酒；不会喝酒的唐国强喝干了一瓶二锅头，醉眼朦胧，一遍又一遍重复那句"朕真的醉了吗？"

## "有的地方感到暴躁的过多了"

唐国强自己的复盘是：有的地方感到暴躁的过多了，这都是我本身缺乏的。

这句话说的是表演本身。

同一时期他给雍正的勤政留了数字：在位13年，平均每天批40多个折子，没有哪一朝皇帝能做到；剧中也有意识地多次表现了雍正在批折子，昼夜如此。剧里雍正的结局是积劳成疾病倒在满堆奏折前，五十八岁；西北大捷的消息传来，他累积许久的压力终于忍耐不住，跪在佛前痛哭失声。唐国强形容这个结局：58岁就因心肺病去世了，他是苦死、累死的。

## 雍正的急，是那副牌逼出来的

康熙在位六十一年十个月，是中国历史上在位时间最长的皇帝。他接手的是一个已经稳下来的局面，有时间等，也有资格让儿子们先表演；他要做的是选人，不是自己冲上去。

雍正四十五岁登基，接手的是康熙末年从中央到地方混乱不堪的财政——仅户部就亏空白银二百多万两——还有一群不服气的兄弟，和一整套必须推下去的新政。剧中把这几条线都摆开了：摊丁入亩、火耗归公、士绅一体当差一体纳粮、河南罢考案、铁帽子亲王大殿发难逼宫。康熙驾崩那一刻，八阿哥还在强调传位的是"十四阿哥"；后来他联合九阿哥、十阿哥和关外四位铁帽子王进京，图谋政变改立皇三子弘时，雍正在朝堂上怒斥胤禩等人为"阿其那""塞思黑"。他身边能替他扛的人也不多，十三阿哥胤祥积劳成疾，不久后身亡。

也有一种说法把难度算在唐国强这边：如果说焦晃的康熙是在满分一百分的情况下拿足了一百分，唐国强的雍正则是在满分一百零一的情况下拿到了一百分——多出来那一分，是这个人物本身的难度。

一个必须亲自去追、去讨、去得罪所有人的人，很难从容。康熙手里有牌，可以等；雍正的牌就是他自己，等不起。""",
    "art-002": """## 那句话不是在台上说的

扎克·施奈德带着新片《最后一张照片》到多伦多电影节做世界首映。首映第二天早上，他坐在下榻酒店的大堂里接受采访，聊新片的差评，也聊社交媒体上那些把他叫作"法西斯""恐同"的声音。

"最gay"这个说法出现在这段对话里，但不是在台上，也不在这场专访的开头。他先讲的是十九年前柏林的旧事：放映时有人嘘，有人中途离场，记者会上有人质问他是不是拍了一部法西斯电影。他记得那天最经典的一个提问是："你到底是支持同性恋，还是支持全国步枪协会？"

他复述自己当时的回答："说实话，我两边都算一点。"紧接着才是那句被单独摘出来的话："我显然支持同性恋。我拍了影史最gay的电影。"

把这句话收窄成"之一"的，是这场多伦多专访里的追问——你是说《300勇士》？他答："《300勇士》是影史最gay的电影之一。我总说，很少有电影能让人直着进去、弯着出来，《300勇士》就是其中一部。"

## 他为什么要拿"最gay"挡"法西斯"

那几天施奈德要应付的是另一种声音。新片《最后一张照片》在烂番茄只有21%的好评（14篇评论，均分3.7/10），Metacritic 16分，社交媒体上有人直接把他叫作法西斯、恐同。他在采访里先说的是"我显然不是法西斯"，然后才把《300勇士》抬出来。有评论把这一手点破了：拿一部"最gay的电影"来反驳恐同指控，本身就是一种转移。

这句话能被抬出来，是因为柏林那段旧事。他记得的版本是：第一次放给观众看，大家嘘，还有人中途离场，接着记者会上有人质问他是不是拍了一部法西斯电影。事实的另一半是，被嘘的是几个小时前的媒体场；2007年2月14日的正式首映礼上，1700名观众起立鼓掌。

## 《300勇士》确实是一部关于男性身体的电影

2006年的《300勇士》改编自弗兰克·米勒与Lynn Varley 1998年为Dark Horse创作的漫画，杰拉德·巴特勒演列奥尼达，罗德里戈·桑托罗演波斯"神王"薛西斯，琳娜·海蒂和大卫·文翰也在其中。迈克尔·法斯宾德的银幕处女作就在这部片子里。成本6500万美元，全球票房4.688亿美元，北美首周末7088万美元，打破了当年三月开画和春季档的纪录；烂番茄上238篇评论给出61%的好评。

一部讲三百个斯巴达战士的电影，画面里几乎全是男人的身体：披风、盾牌、腹肌。当年影评界的讨论中，"同性张力"是一个反复出现的词。

施奈德对这套张力并不陌生。他承认过，自己刻意把薛西斯塑造成阴柔的样子，为的是让观众席上的年轻直男不舒服——大意是，还有什么比一个想对你为所欲为的巨人神王，更让一个20岁的男孩害怕？

## 伊朗抗议过，报纸的标题写"300对7000万"

《300勇士》上映后最激烈的反应不在影评版。伊朗政府官员公开谴责这部影片；伊朗艺术学院向联合国教科文组织递交正式抗议，称它攻击了伊朗的历史身份；伊朗常驻联合国代表团发新闻稿抗议，伊朗使馆在法国、泰国、土耳其、乌兹别克斯坦抗议影片放映。影片在伊朗被禁，被当成一部美国宣传片。伊朗报纸的标题里有一句"300对7000万"——7000万是当时伊朗的人口。

同一部电影，当年被伊朗方面当成"美国宣传片"，十九年后被它的导演拿来证明自己"不是法西斯"。

## 一句自嘲，说中了他电影的底牌

回到那句话本身。它出现在一场针对"法西斯"指控的自辩里，却意外说准了一件事：《300勇士》那套直男英雄叙事的燃料，本来就是男人看男人。

施奈德在同一个采访里还抱怨过另一件事：电影里的性爱奇怪地消失了，他说他不理解。这句抱怨和"最gay"放在一起看，意思就清楚了——他在意的不是取向，而是电影还敢不敢拍身体和欲望。

至于新片《最后一张照片》，是另一个方向的施奈德：135分钟，只拍了32天，Kurt Johnstad编剧，Stuart Martin和Fra Fee主演，故事由他自己原创，配乐是Hans Zimmer。这个项目早在2011年就传出过克里斯蒂安·贝尔与西恩·潘主演、Niels Arden Oplev执导的版本，拖到今天才拍出来。口碑很差，但它显然不是他用来讨好评委的那部电影。

"很少有电影能让人直着进去、弯着出来。"这句解释放在《300勇士》上，比"最gay"三个字更值得琢磨：一部电影能让人带着成见进去、带着别的东西出来，这大概是导演最想要的那件事。""",
}


# --------------------------------------------------------------------------
# 6) Titles / sources / claims
# --------------------------------------------------------------------------

TITLES = {
    "art-001": [
        ("康熙为什么总是不急，雍正却动不动就发火", "反差"),
        ("唐国强自己承认：雍正的暴躁，有些地方演多了", "演员自评"),
        ("同一把龙椅，康熙坐着从容，雍正坐着上火", "对比"),
    ],
    "art-002": [
        ("施奈德为什么说《300勇士》是影史最gay的电影", "言论"),
        ("\"我拍了影史最gay的电影\"：这句话其实是被问出来的", "追问"),
        ("19年后，施奈德自己给《300勇士》贴了个标签", "回看"),
    ],
}

SOURCE_IDS = {
    "art-001": [
        "src-sina-tangguoqiang-1999",
        "src-gmw-jiaohuang-1999",
        "src-cctv-drama-intro",
        "src-wiki-yongzheng-drama",
        "src-comment-kangxi-shenmi",
        "src-comment-kangxi-diwangzhishu",
        "src-comment-acting-rank",
        "src-wiki-kangxi-emperor",
        "src-wiki-yongzheng-emperor",
    ],
    "art-002": [
        "src-variety-interview",
        "src-avclub",
        "src-ign",
        "src-wiki-300",
        "src-wiki-lastphotograph",
        "src-vulture",
        "src-360-yule",
    ],
}

MODES = {"art-001": "reported_feature", "art-002": "reported_feature"}

RULE_CLAIMS = {
    "art-001": [
        {"claim_id": "c1", "claim_level": "mechanism", "source_refs": ["src-sina-tangguoqiang-1999"], "source_locators": ["中国电影报: 唐国强自评暴躁"]},
        {"claim_id": "c2", "claim_level": "character_setup", "source_refs": ["src-sina-tangguoqiang-1999"], "source_locators": ["中国电影报: 雍正性格定位"]},
        {"claim_id": "c3", "claim_level": "mechanism", "source_refs": ["src-gmw-jiaohuang-1999"], "source_locators": ["光明日报: 威驭天下"]},
        {"claim_id": "c4", "claim_level": "event_exists", "source_refs": ["src-wiki-yongzheng-drama"], "source_locators": ["维基: 阵容与集数"]},
        {"claim_id": "c5", "claim_level": "mechanism", "source_refs": ["src-comment-acting-rank"], "source_locators": ["评论: 相反口径"]},
    ],
    "art-002": [
        {"claim_id": "c1", "claim_level": "mechanism", "source_refs": ["src-variety-interview"], "source_locators": ["Variety: 原话"]},
        {"claim_id": "c2", "claim_level": "event_exists", "source_refs": ["src-variety-interview"], "source_locators": ["Variety: 记者追问"]},
        {"claim_id": "c3", "claim_level": "event_exists", "source_refs": ["src-wiki-300"], "source_locators": ["维基300: 改编来源"]},
        {"claim_id": "c4", "claim_level": "event_exists", "source_refs": ["src-wiki-300"], "source_locators": ["维基300: 伊朗抗议"]},
        {"claim_id": "c5", "claim_level": "event_exists", "source_refs": ["src-wiki-lastphotograph"], "source_locators": ["维基新片: 口碑"]},
    ],
}

BRIEFS = {
    "art-001": """# Writing Brief

production_contract: article-first-v1
brief_contract: writing-brief-v2
title_contract: title-pack-v1
legacy_compatibility: false
run_contract_required: true
article_id: art-001
candidate_id: cand-yongzheng-kangxi-steady-001
article_mode: reported_feature
required_source_roles: [media_report]
topic_version: 1
content_map: B
reference_shape: viewing_commentary
core_question: 为什么康熙能不急，雍正却动不动就发火
target_reader: 看过《雍正王朝》、对康熙与雍正两种"当家人"状态有体感的观众
editorial_angle: 差别不在脾气而在处境——康熙手上还有牌，雍正的牌就是他自己；两位演员当年的一手说法把这条线钉住了
body_route: 从两种"坐着的样子"进入，写焦晃的处理与评论家的落点，再写唐国强给雍正的定位和他自己的复盘，最后落到两个人接手的局面
evidence_boundary: 只写来源中的剧集事实、剧情大纲、演员原话与评论观点；历史口径用在位年限、登基年龄与即位时的户部亏空；不写来源之外的情节细节
required_hard_information: 1999年1月央视一套首播、44集、胡玫执导、刘和平与二月河编剧、央视一套晚八点档迄今收视最高；唐国强自评"有的地方感到暴躁的过多了"；雍正"急躁、尖刻、记仇"与"用雷霆手段行菩萨心肠"；在位13年、平均每天批40多个折子；康熙在位六十一年十个月；雍正即位时户部亏空白银二百多万两
unsupported_boundary: 不替观众下整体结论，不写演员近况，不把"热榜第几"写成事实，不把评论观点写成事实
""",
    "art-002": """# Writing Brief

production_contract: article-first-v1
brief_contract: writing-brief-v2
title_contract: title-pack-v1
legacy_compatibility: false
run_contract_required: true
article_id: art-002
candidate_id: cand-snyder-300-gayest-001
article_mode: reported_feature
required_source_roles: [media_report]
topic_version: 1
content_map: D
reference_shape: viewing_commentary
core_question: 施奈德为什么要说《300勇士》是影史最gay的电影
target_reader: 看过《300勇士》、对"直男大片里的男性凝视"这个话题有兴趣的观众
editorial_angle: 原话、场合与动机都比中文转述复杂；这句话是被追问出来的自辩，却说准了影片的拍摄逻辑
body_route: 先还原这句话出现的场合与问答过程，再写他当时的处境与柏林往事，然后回到影片本身的身体叙事与伊朗争议，最后收在"直着进去、弯着出来"
evidence_boundary: 只写英文一手来源与维基页面中的事实；中文自媒体稿只用于核对转述口径，其独有细节不写入正文
required_hard_information: 原话两句（"我拍了影史最gay的电影"与被追问后的"最gay的电影之一"）；场合为多伦多首映次日酒店大堂专访；柏林正式首映1700人起立鼓掌、被嘘的是媒体场；《300勇士》改编自米勒与Lynn Varley漫画、成本6500万美元、全球票房4.688亿美元、法斯宾德处女作；伊朗艺术学院向联合国教科文组织递交抗议、伊朗报纸"300对7000万"；新片烂番茄21%、Metacritic16分、只拍32天
unsupported_boundary: 不写中文自媒体独有的细节（如"记者愣了三秒""全片没有一句台词"），不替导演解释其政治立场，不把评论观点写成事实
""",
}

BRIEF_SPECS = [
    (
        "art-001",
        "reported_feature",
        "media_report",
        "为什么康熙能不急，雍正却动不动就发火",
        "src-sina-tangguoqiang-1999",
    ),
    (
        "art-002",
        "reported_feature",
        "media_report",
        "施奈德为什么要说《300勇士》是影史最gay的电影",
        "src-variety-interview",
    ),
]

CONTENT_RECORD_ARGS = [
    {
        "aid": "art-001",
        "mode": "reported_feature",
        "role": "media_report",
        "core_object": "《雍正王朝》里康熙与雍正两种当家人的状态差别",
        "question": "为什么康熙能不急，雍正却动不动就发火",
        "mechanism": "差别在处境：康熙手上还有牌，可以等；雍正接手的是亏空、兄弟与新政，必须自己冲上去",
        "takeaway": "康熙手里有牌，可以等；雍正的牌就是他自己，等不起。",
        "hard": [
            {"information_id": "i1", "text": "有的地方感到暴躁的过多了，这都是我本身缺乏的。", "kind": "mechanism", "body_locator": "p11", "source_refs": ["src-sina-tangguoqiang-1999"], "source_locators": ["中国电影报: 唐国强自评暴躁"], "independence_key": "self-critique"},
            {"information_id": "i2", "text": "雍正有“冷面王”之称，他性格急躁、尖刻、记仇。", "kind": "mechanism", "body_locator": "p9", "source_refs": ["src-sina-tangguoqiang-1999"], "source_locators": ["中国电影报: 雍正性格定位"], "independence_key": "temper"},
            {"information_id": "i3", "text": "有人说过，雍正是用雷霆手段行菩萨心肠。我很赞同这一说法。", "kind": "mechanism", "body_locator": "p9", "source_refs": ["src-sina-tangguoqiang-1999"], "source_locators": ["中国电影报: 雷霆手段"], "independence_key": "thunder"},
            {"information_id": "i4", "text": "雍正是历史上最勤政的一个皇帝，在位13年，平均每天批40多个折子", "kind": "fact", "body_locator": "p13", "source_refs": ["src-sina-tangguoqiang-1999"], "source_locators": ["中国电影报: 勤政数字"], "independence_key": "memorials"},
            {"information_id": "i5", "text": "开始导演想让我演八贤王", "kind": "fact", "body_locator": "p8", "source_refs": ["src-sina-tangguoqiang-1999"], "source_locators": ["中国电影报: 角色争取"], "independence_key": "casting"},
            {"information_id": "i6", "text": "大多评论家认为他成功地塑造了一位血脉已衰仍然威驭天下的一代君王形象。", "kind": "mechanism", "body_locator": "p5", "source_refs": ["src-gmw-jiaohuang-1999"], "source_locators": ["光明日报: 威驭天下"], "independence_key": "critics"},
            {"information_id": "i7", "text": "我的每一个人物都是从心里长出来的。", "kind": "mechanism", "body_locator": "p5", "source_refs": ["src-gmw-jiaohuang-1999"], "source_locators": ["光明日报: 焦晃方法"], "independence_key": "method"},
            {"information_id": "i8", "text": "由唐国强、焦晃、王绘春、杜志国、赵毅、王辉等人主演，全剧共44集", "kind": "fact", "body_locator": "p3", "source_refs": ["src-wiki-yongzheng-drama"], "source_locators": ["维基: 阵容与集数"], "independence_key": "episodes"},
            {"information_id": "i9", "text": "该剧是央视一套迄今晚八点电视剧中收视率最高的一部", "kind": "fact", "body_locator": "p3", "source_refs": ["src-wiki-yongzheng-drama"], "source_locators": ["维基: 收视"], "independence_key": "ratings"},
            {"information_id": "i10", "text": "雍正積勞成疾病倒在滿堆奏摺前，享年五十八歲。", "kind": "fact", "body_locator": "p13", "source_refs": ["src-wiki-yongzheng-drama"], "source_locators": ["维基: 剧情结局"], "independence_key": "ending"},
            {"information_id": "i11", "text": "康熙皇帝驾崩，继位者为“冷面王”四阿哥。", "kind": "fact", "body_locator": "p7", "source_refs": ["src-cctv-drama-intro"], "source_locators": ["央视网: 冷面王继位"], "independence_key": "succession"},
            {"information_id": "i12", "text": "焦晃的康熙，喜怒不形于色，内心思虑让外人无法猜测甚至其子女", "kind": "mechanism", "body_locator": "p4", "source_refs": ["src-comment-kangxi-shenmi"], "source_locators": ["评论: 喜怒不形于色"], "independence_key": "poker-face"},
            {"information_id": "i13", "text": "如果说焦晃版康熙是在满分一百分的状况下拿足了一百分，唐版雍正则是在满分一百零一的情况下拿到了一百分。", "kind": "mechanism", "body_locator": "p16", "source_refs": ["src-comment-acting-rank"], "source_locators": ["评论: 相反口径"], "independence_key": "counter-view"},
            {"information_id": "i14", "text": "在位六十一年十個月，是中國歷史上在位時間最長的皇帝", "kind": "fact", "body_locator": "p14", "source_refs": ["src-wiki-kangxi-emperor"], "source_locators": ["维基康熙: 在位年限"], "independence_key": "reign-length"},
        ],
        "bases": [
            {"locator": "p5", "fact_or_scene": "1999年1月央视一套首播、44集与主创阵容", "explanation": "把讨论钉在具体作品上，读者知道说的是哪一版"},
            {"locator": "p13", "fact_or_scene": "唐国强自评暴躁演多了", "explanation": "演员本人的复盘，让\"暴躁\"从观众印象变成可核事实"},
            {"locator": "p17", "fact_or_scene": "雍正接手亏空、兄弟与新政", "explanation": "解释\"急\"的来源，把性格问题还原成处境问题"},
        ],
        "boundary": "不写来源之外的剧情细节、演员近况与未公开表态；不把评论观点写成事实；不把热榜名次写成事实。",
        "source_ids": [
            "src-sina-tangguoqiang-1999",
            "src-gmw-jiaohuang-1999",
            "src-cctv-drama-intro",
            "src-wiki-yongzheng-drama",
            "src-comment-kangxi-shenmi",
            "src-comment-acting-rank",
            "src-wiki-kangxi-emperor",
            "src-wiki-yongzheng-emperor",
            "src-comment-kangxi-diwangzhishu",
        ],
    },
    {
        "aid": "art-002",
        "mode": "reported_feature",
        "role": "media_report",
        "core_object": "施奈德\"影史最gay的电影\"这句话的原话、场合与语境",
        "question": "施奈德为什么要说《300勇士》是影史最gay的电影",
        "mechanism": "这句话是反法西斯自辩中被记者追问出来的，却说准了《300勇士》的拍摄逻辑：男性身体与凝视是那套英雄叙事的燃料",
        "takeaway": "一部电影能让人带着成见进去、带着别的东西出来，这大概是导演最想要的那件事。",
        "hard": [
            {"information_id": "i1", "text": "But obviously I’m pro-gay. I made the gayest movie ever made.", "kind": "fact", "body_locator": "p3", "source_refs": ["src-variety-interview"], "source_locators": ["Variety: 原话"], "independence_key": "quote-main"},
            {"information_id": "i2", "text": "“300” is one of the gayest movies ever made.", "kind": "fact", "body_locator": "p4", "source_refs": ["src-variety-interview"], "source_locators": ["Variety: 追问后收窄"], "independence_key": "quote-narrowed"},
            {"information_id": "i3", "text": "You think “300” is the gayest movie ever made?", "kind": "fact", "body_locator": "p4", "source_refs": ["src-variety-interview"], "source_locators": ["Variety: 记者追问"], "independence_key": "followup"},
            {"information_id": "i4", "text": "It’s the morning after the premiere and I’m sitting across from Snyder in the lobby of his Toronto hotel.", "kind": "fact", "body_locator": "p1", "source_refs": ["src-variety-interview"], "source_locators": ["Variety: 场合"], "independence_key": "occasion"},
            {"information_id": "i5", "text": "And obviously, I’m not a fascist.", "kind": "mechanism", "body_locator": "p5", "source_refs": ["src-variety-interview"], "source_locators": ["Variety: 自辩"], "independence_key": "fascist"},
            {"information_id": "i6", "text": "We shot this in 32 days.", "kind": "fact", "body_locator": "p14", "source_refs": ["src-variety-interview"], "source_locators": ["Variety: 新片拍摄"], "independence_key": "32days"},
            {"information_id": "i7", "text": "Based on the 1998 Dark Horse Comics limited series of the same name by Frank Miller and Lynn Varley", "kind": "fact", "body_locator": "p7", "source_refs": ["src-wiki-300"], "source_locators": ["维基300: 改编来源"], "independence_key": "comic"},
            {"information_id": "i8", "text": "The film also features Michael Fassbender in his film debut.", "kind": "fact", "body_locator": "p7", "source_refs": ["src-wiki-300"], "source_locators": ["维基300: 法斯宾德处女作"], "independence_key": "fassbender"},
            {"information_id": "i9", "text": "Budget $65 million", "kind": "fact", "body_locator": "p7", "source_refs": ["src-wiki-300"], "source_locators": ["维基300: 成本"], "independence_key": "budget"},
            {"information_id": "i10", "text": "The Iranian Academy of the Arts submitted a formal complaint against the film to UNESCO", "kind": "fact", "body_locator": "p10", "source_refs": ["src-wiki-300"], "source_locators": ["维基300: 伊朗抗议"], "independence_key": "unesco"},
            {"information_id": "i11", "text": "300 Against 70 Million", "kind": "fact", "body_locator": "p10", "source_refs": ["src-wiki-300"], "source_locators": ["维基300: 伊朗报纸标题"], "independence_key": "headline"},
            {"information_id": "i12", "text": "21% of 14 critics' reviews are positive, with an average rating of 3.7/10.", "kind": "fact", "body_locator": "p5", "source_refs": ["src-wiki-lastphotograph"], "source_locators": ["维基新片: 口碑"], "independence_key": "rt"},
            {"information_id": "i13", "text": "The film had its world premiere in the \"Special Events\" section of the 2026 Toronto International Film Festival on September 13.", "kind": "fact", "body_locator": "p1", "source_refs": ["src-wiki-lastphotograph"], "source_locators": ["维基新片: 首映"], "independence_key": "premiere"},
        ],
        "bases": [
            {"locator": "p2", "fact_or_scene": "原话与被追问的经过", "explanation": "把中文转述里\"台上发言\"的印象校正为一次专访问答"},
            {"locator": "p7", "fact_or_scene": "《300勇士》的成本与票房、法斯宾德处女作", "explanation": "说明这句话谈的是一部什么样的电影"},
            {"locator": "p10", "fact_or_scene": "伊朗的正式抗议与\"300对7000万\"", "explanation": "影片的政治争议与\"法西斯\"标签互为照面"},
        ],
        "boundary": "不写中文自媒体独有的细节；不替导演解释政治立场；不写来源之外的影片情节与评价。",
        "source_ids": [
            "src-variety-interview",
            "src-avclub",
            "src-ign",
            "src-wiki-300",
            "src-wiki-lastphotograph",
            "src-vulture",
            "src-360-yule",
        ],
    },
]

BATCH_SPECS = {
    "art-001": (
        "cand-yongzheng-kangxi-steady-001",
        "雍正王朝",
        "yongzheng-kangxi-yongzheng-contrast",
        [
            "src-sina-tangguoqiang-1999",
            "src-gmw-jiaohuang-1999",
            "src-cctv-drama-intro",
            "src-wiki-yongzheng-drama",
            "src-comment-kangxi-shenmi",
            "src-comment-kangxi-diwangzhishu",
            "src-comment-acting-rank",
            "src-wiki-kangxi-emperor",
            "src-wiki-yongzheng-emperor",
        ],
        "A",
        "B",
    ),
    "art-002": (
        "cand-snyder-300-gayest-001",
        "300勇士",
        "snyder-300-gayest-remark",
        [
            "src-variety-interview",
            "src-avclub",
            "src-ign",
            "src-wiki-300",
            "src-wiki-lastphotograph",
            "src-vulture",
            "src-360-yule",
        ],
        "B",
        "D",
    ),
}


if __name__ == "__main__":
    import sys as _sys

    from scripts.daily_engine import build_run

    build_run(_sys.modules[__name__])
