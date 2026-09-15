"""Build runs/2026-09-16/daily-006 (two_article_daily, article-first lane).

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

base.ROOT = Path("runs/2026-09-16/daily-006")
ROOT = base.ROOT
CONTRACT = base.CONTRACT
RUN_ID = "2026-09-16/daily-006"
GROUP_ID = "article-group-2026-09-16-001"
CAPTURED_AT = "2026-09-16T00:51:00+08:00"


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
    ("tgmeng-douban", "24226", "《绝望写手》女主连续五季艾美奖得奖", 12),
    ("tgmeng-douban", "32141", "《寡妇湾》斩获艾美奖六大奖项", 6),
    ("tgmeng-douyin", "8185112", "电影生化危机爆发夜确认引进", 26),
]


# --------------------------------------------------------------------------
# 1) Sources: captured public pages used as evidence
# --------------------------------------------------------------------------

SOURCES = {
    "src-ithome-aimi": {
        "source_role": "media_report",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "https://m.ithome.com/html/1002521.htm",
        "source_type": "media_report",
        "artifact_path": "sources/b01-ithome-aimi.html",
        "captured_from": "IT之家（2026-09-15 12:34，第78届艾美奖获奖盘点）",
    },
    "src-shangbao-aimi": {
        "source_role": "media_report",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "http://internal.shangbaoindonesia.com/read/2026/09/15/entertainment-1789487782",
        "source_type": "media_report",
        "artifact_path": "sources/b02-shangbao-aimi.html",
        "captured_from": "印尼商报（2026-09-15，第78届艾美奖完整获奖名单）",
    },
    "src-sohu-shenghuaweiji": {
        "source_role": "media_report",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "http://news.sohu.com/a/1076339696_114733",
        "source_type": "media_report",
        "artifact_path": "sources/a01-sohu-shenghuaweiji.html",
        "captured_from": "搜狐娱乐（2026-09-15 15:43，《生化危机：爆发夜》引进官宣通稿）",
    },
    "src-17173-shenghuaweiji": {
        "source_role": "media_report",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "https://news.17173.com/content/09152026/160331055.shtml",
        "source_type": "media_report",
        "artifact_path": "sources/a02-17173-shenghuaweiji.html",
        "captured_from": "17173（2026-09-15 16:03，转引 IT之家：引进确认与导演回应）",
    },
}


# --------------------------------------------------------------------------
# 2) Candidate pool + slots
# --------------------------------------------------------------------------

CANDIDATES = [
    {
        "candidate_id": "cand-aimi-jueshi-001",
        "work": "绝望写手",
        "work_title": "绝望写手",
        "signal": "豆瓣热榜：绝望写手女主连续五季艾美奖得奖（24226）",
        "signal_source": "tgmeng-douban",
        "topic_mode": "culture",
        "article_mode": "reported_feature",
        "content_map": "C",
        "event_cluster_id": "emmys-78-veterans-coronation",
        "content_map_label": "文化现象",
        "freshness_window": "same-day",
        "remove_timestamp_test": "pass",
        "evidence_readiness": "high",
        "recommendation": "A",
        "editorial_value_score": 9,
        "reader": "追美剧、关心奖项背后创作规律的观众",
        "reader_question": "第78届艾美奖为什么成了老面孔的加冕礼",
        "core_question": "第78届艾美奖为什么成了老面孔的加冕礼",
        "angle": "这届艾美奖把最重的大奖都给了演了很多年的人：珍·斯玛特五季五拿、马修·瑞斯双视帝、蕾亚·塞洪四提终圆梦",
        "source_refs": ["src-ithome-aimi", "src-shangbao-aimi"],
        "prior_run_conflict": False,
        "selection_reason": "9月14日晚颁奖、9月15日名单刷屏（豆瓣同簇4条）；有完整获奖名单与历史创造细节两份可回读材料",
    },
    {
        "candidate_id": "cand-shenghuaweiji-yinjin-001",
        "work": "生化危机：爆发夜",
        "work_title": "生化危机：爆发夜",
        "signal": "抖音热榜：电影生化危机爆发夜确认引进（8185112）",
        "signal_source": "tgmeng-douyin",
        "topic_mode": "release_event",
        "article_mode": "reported_feature",
        "content_map": "A",
        "event_cluster_id": "resident-evil-outbreak-night-import",
        "content_map_label": "新片事件",
        "freshness_window": "same-day",
        "remove_timestamp_test": "pass",
        "evidence_readiness": "high",
        "recommendation": "A",
        "editorial_value_score": 8,
        "reader": "看过生化危机系列、关心引进新片的观众",
        "reader_question": "时隔九年重回内地银幕的《生化危机：爆发夜》，为什么把主角换成一名医疗快递员",
        "core_question": "时隔九年重回内地银幕的《生化危机：爆发夜》，为什么把主角换成一名医疗快递员",
        "angle": "新作不复刻任何一版游戏剧情，而是把一个送快递的小人物扔进浣熊市",
        "source_refs": ["src-sohu-shenghuaweiji", "src-17173-shenghuaweiji"],
        "prior_run_conflict": False,
        "selection_reason": "9月15日官宣确认引进；有官宣通稿与导演回应两份可回读材料；兰香如故破30000信号因作品级去重（daily-001已写）不入选",
    },
]

REJECTED_PRIOR_WORKS = [
    "交锋", "欢迎来龙餐馆", "空枪", "玩具总动员5",
    "早春晴朗", "兰香如故", "奥德赛", "蜘蛛侠：崭新之日",
]

SLOT_DECISIONS = [
    {
        "slot": 1,
        "article_id": "art-001",
        "candidate_id": "cand-aimi-jueshi-001",
        "decision": "selected",
        "event_cluster_id": "emmys-78-veterans-coronation",
    },
    {
        "slot": 2,
        "article_id": "art-002",
        "candidate_id": "cand-shenghuaweiji-yinjin-001",
        "decision": "selected",
        "event_cluster_id": "resident-evil-outbreak-night-import",
    },
]


# --------------------------------------------------------------------------
# 3) Briefs, task cards, task hierarchy
# --------------------------------------------------------------------------

TASK_CARD_REQUIRED_FIELDS = {
    "art-001": (
        "1. **站队点/可转述句**：在流媒体拼命上新剧的年份，艾美奖把最多的票投给了耐久性——它奖励的不是新面孔的惊喜，而是老面孔的耐力。\n"
        "2. **读者已知锚点**：艾美奖是美国电视最高奖；珍·斯玛特、马修·瑞斯、蕾亚·塞洪都是被观众记住多年的熟脸。\n"
        "3. **today-hook 理由**：第78届艾美奖当地时间9月14日晚颁奖，9月15日完整获奖名单刷屏。\n"
        "4. **事实底座**：当地时间9月14日晚颁奖；珍·斯玛特凭《绝望写手》五季五拿喜剧视后、创下艾美历史；马修·瑞斯凭《寡妇湾》与《兽藏我心》成为首位同一届拿下两大类最佳男主角的男演员；蕾亚·塞洪凭《同乐者》首夺艾美奖（此前《风骚律师》四提零中）；《寡妇湾》6项；《扣扣熊晚间秀》终结《约翰·奥利弗上周今夜秀》2016年以来连胜（来源：IT之家、印尼商报）。\n"
        "5. **最强钩子**：珍·斯玛特成为首位凭同一部剧每一季都获奖的女演员（与 batch.json 的 review_hook 一致）。\n"
        "- **title_promise**：第78届艾美奖为什么成了老面孔的加冕礼\n"
        "- **ending_destination**：奖项对持续在场的信任，压过了对新鲜登场的好奇；明年的奖单会自己回答这种口味能持续多久。\n"
        "\n## 文章结构大纲（H2 目录）\n"
        "## 第78届艾美奖最值得看的，不是谁拿奖\n"
        "## 珍·斯玛特：同一部剧，五季五拿\n"
        "## 马修·瑞斯和蕾亚·塞洪：等了很多年的人\n"
        "## 老面孔统治，是保守还是耐力\n"
    ),
    "art-002": (
        "1. **站队点/可转述句**：这部生化危机的看点不在怪物更大，而在主角更小——一个送快递的布莱恩，代替了粉丝最熟悉的里昂。\n"
        "2. **读者已知锚点**：《生化危机》是国民级游戏IP；里昂是系列最有名的角色之一；上一部内地公映的系列电影已是九年前。\n"
        "3. **today-hook 理由**：9月15日《生化危机：爆发夜》官宣确认引进，双海报释出。\n"
        "4. **事实底座**：9月15日官宣确认引进并释出“惊魂血夜”“狂暴突围”两版海报；系列时隔九年重返内地大银幕；档期待定；导演扎克·克雷格（《凶器》《野蛮人》）；主演奥斯汀·艾布拉姆斯、保罗·沃尔特·豪泽、扎克·切利、卡莉·瑞斯；主角为医疗快递员布莱恩；时间线大致与《生化危机2》相同；官方提醒未成年人谨慎观看（来源：搜狐娱乐、17173转IT之家）。\n"
        "5. **最强钩子**：导演克雷格回应弃用里昂——不想重讲里昂的故事，也不打算复刻原版游戏剧情（与 batch.json 的 review_hook 一致）。\n"
        "- **title_promise**：《生化危机：爆发夜》确认引进：9年之后，主角换成了送快递的\n"
        "- **ending_destination**：能不能接住九年的等待，要等档期落定、成片上映之后才有答案。\n"
        "\n## 文章结构大纲（H2 目录）\n"
        "## 9年没进内地影院的生化危机，这次带回来的主角不是里昂\n"
        "## 弃用里昂：不重讲老故事，也不复刻游戏\n"
        "## 送快递的人，被扔进浣熊市\n"
        "## 引进确认之后，剩下的问题交给档期\n"
    ),
}

STRONGEST_HOOKS = {
    "art-001": "珍·斯玛特成为首位凭同一部剧每一季都获奖的女演员",
    "art-002": "导演克雷格回应弃用里昂：不想重讲里昂的故事，也不打算复刻原版游戏剧情",
}


# --------------------------------------------------------------------------
# 4) Material packs
# --------------------------------------------------------------------------

MATERIAL_SPECS = {
    "art-001": {
        "mode": "reported_feature",
        "role": "media_report",
        "source_ids": ["src-ithome-aimi", "src-shangbao-aimi"],
        "question": "第78届艾美奖为什么成了老面孔的加冕礼",
        "mechanism": "五连冠、双视帝与四提圆梦共同说明，奖项在奖励演员的持续在场而非新鲜登场",
        "facts": [
            {"text": "当地时间9月14日晚，第78届黄金时段艾美奖颁奖典礼在美国举行", "level": "event_exists", "locator": "IT之家: 颁奖时间", "source_id": "src-ithome-aimi", "plan_kind": "specific_context"},
            {"text": "苹果AppleTV+剧集《寡妇湾》共获得6项奖项", "level": "event_exists", "locator": "IT之家: 寡妇湾6项", "source_id": "src-ithome-aimi", "plan_kind": "fact"},
            {"text": "《绝望写手》的珍•斯玛特五季五拿喜剧视后，创下艾美历史", "level": "mechanism", "locator": "印尼商报: 五季五拿", "source_id": "src-shangbao-aimi", "plan_kind": "mechanism"},
            {"text": "成为首位凭同一部剧每一季都获奖的女演员", "level": "mechanism", "locator": "印尼商报: 历史创造", "source_id": "src-shangbao-aimi", "plan_kind": "mechanism"},
            {"text": "马修•瑞斯以两部剧集同时拿下两个视帝", "level": "character_setup", "locator": "印尼商报: 双视帝", "source_id": "src-shangbao-aimi", "plan_kind": "fact"},
            {"text": "蕾亚•塞洪凭《同乐者》首夺艾美奖，此前她因《风骚律师》四提零中，如今终于圆梦", "level": "character_setup", "locator": "印尼商报: 四提圆梦", "source_id": "src-shangbao-aimi", "plan_kind": "fact"},
            {"text": "《扣扣熊晚间秀》终结了《约翰·奥利弗上周今夜秀》自2016年以来连续获奖的纪录", "level": "mechanism", "locator": "IT之家: 连胜终结", "source_id": "src-ithome-aimi", "plan_kind": "mechanism"},
            {"text": "《寡妇湾》拿下了最佳喜剧类剧集、最佳男主角、最佳男配角、最佳女配角、最佳导演和最佳编剧等奖项", "level": "event_exists", "locator": "IT之家: 六类别枚举", "source_id": "src-ithome-aimi", "plan_kind": "fact"},
            {"text": "剧情类最佳剧集给了《匹兹堡医护前线》，诺亚·怀尔凭该剧拿到剧情类最佳男主角", "level": "event_exists", "locator": "IT之家: 剧情类归属", "source_id": "src-ithome-aimi", "plan_kind": "fact"},
            {"text": "《同乐者》的剧情类最佳编剧给了文斯·吉里根，《流人》的剧情类最佳导演给了索尔·梅茨斯坦", "level": "event_exists", "locator": "IT之家: 编剧导演归属", "source_id": "src-ithome-aimi", "plan_kind": "fact"},
            {"text": "限定剧或单元剧最佳给了《DTF圣路易日记》，真人秀竞赛节目奖由《背叛者》获得", "level": "event_exists", "locator": "IT之家: 限定剧与真人秀", "source_id": "src-ithome-aimi", "plan_kind": "fact"},
        ],
        "by_source": {
            "src-ithome-aimi": [
                "当地时间9月14日晚，第78届黄金时段艾美奖颁奖典礼在美国举行",
                "苹果AppleTV+剧集《寡妇湾》（Widow'sBay）成为当晚最大赢家，共获得6项奖项",
                "拿下了最佳喜剧类剧集、喜剧类最佳男主角、最佳男配角、最佳女配角、最佳喜剧类剧集导演和最佳喜剧类剧集编剧等奖项",
                "剧情类剧集方面，HBOMax剧集《匹兹堡医护前线》（ThePitt）获得最佳剧情类剧集，诺亚·怀尔凭借该剧获得剧情类最佳男主角",
                "文斯·吉里根则获得剧情类最佳编剧奖",
                "索尔·梅茨斯坦凭借《流人》（SlowHorses）成功获得剧情类最佳导演奖",
                "限定剧或单元剧方面，HBOMax的《DTF圣路易日记》获得最佳",
                "真人秀竞赛节目奖由《背叛者》（TheTraitors）获得",
                "马修·瑞斯凭借《寡妇湾》获得喜剧类最佳男主角，并凭借Netflix剧集《兽藏我心》（TheBeastinMe）获得限定剧或单元剧最佳男主角",
                "他成为首位在同一届艾美奖中同时获得这两大类最佳男主角奖的男演员",
                "《绝望写手》（Hacks）凭借第五季也是最终季获得一项奖项，珍·斯马特再次拿下喜剧类最佳女主角",
                "凯特·奥弗林凭借该剧获得喜剧类最佳女配角，这也是她首次获得艾美奖",
                "蕾亚·塞洪凭借该剧拿下剧情类最佳女主角",
                "《扣扣熊晚间秀》（TheLateShowWithStephenColbert）获得最佳综艺类剧集，终结了《约翰·奥利弗上周今夜秀》（LastWeekTonightWithJohnOliver）自2016年以来连续获奖的纪录",
                "莎莉·菲尔德凭借《幸运有八只触手》（RemarkablyBrightCreatures）获得该类别最佳女主角",
            ],
            "src-shangbao-aimi": [
                "新剧《寡妇湾》大赢获六奖",
                "马修•瑞斯以两部剧集同时拿下两个视帝",
                "蕾亚•塞洪凭《同乐者》首夺艾美奖，此前她因《风骚律师》四提零中，如今终于圆梦",
                "《绝望写手》的珍•斯玛特五季五拿喜剧视后，创下艾美历史",
                "成为首位凭同一部剧每一季都获奖的女演员",
                "《匹兹堡医护前线》《头号外交官》《慢马》《特别小组》《幸运有八只触手》等也有斩获",
            ],
        },
        "audience": "追美剧、关心奖项背后创作规律的观众",
    },
    "art-002": {
        "mode": "reported_feature",
        "role": "media_report",
        "source_ids": ["src-sohu-shenghuaweiji", "src-17173-shenghuaweiji"],
        "question": "时隔九年重回内地银幕的《生化危机：爆发夜》，为什么把主角换成一名医疗快递员",
        "mechanism": "弃用里昂和快递员主角共同说明，新作想用世界观讲新故事，而不是复刻旧角色",
        "facts": [
            {"text": "惊悚电影《生化危机：爆发夜》今日官宣确认引进", "level": "event_exists", "locator": "搜狐娱乐: 官宣引进", "source_id": "src-sohu-shenghuaweiji", "plan_kind": "specific_context"},
            {"text": "《生化危机》系列时隔九年再登内地大银幕", "level": "mechanism", "locator": "搜狐娱乐: 时隔九年", "source_id": "src-sohu-shenghuaweiji", "plan_kind": "fact"},
            {"text": "影片讲述了一名医疗快递员布莱恩（奥斯汀·艾布拉姆斯）运送医疗包裹的途中，意外卷入一场生化变异危机", "level": "character_setup", "locator": "搜狐娱乐: 主角设定", "source_id": "src-sohu-shenghuaweiji", "plan_kind": "fact"},
            {"text": "影片由扎克·克雷格执导", "level": "character_setup", "locator": "搜狐娱乐: 导演", "source_id": "src-sohu-shenghuaweiji", "plan_kind": "fact"},
            {"text": "档期待定", "level": "event_exists", "locator": "17173: 档期状态", "source_id": "src-17173-shenghuaweiji", "plan_kind": "specific_context"},
            {"text": "导演扎克·克雷格此前回应了为何弃用里昂，他并不想重讲里昂的故事", "level": "mechanism", "locator": "17173: 弃用里昂", "source_id": "src-17173-shenghuaweiji", "plan_kind": "mechanism"},
            {"text": "发生在《生化危机》世界观的全新故事，时间线大致与《生化危机2》相同", "level": "mechanism", "locator": "17173: 时间线", "source_id": "src-17173-shenghuaweiji", "plan_kind": "mechanism"},
            {"text": "电影官方提醒：未成年人谨慎观看", "level": "event_exists", "locator": "17173: 官方提醒", "source_id": "src-17173-shenghuaweiji", "plan_kind": "fact"},
            {"text": "“惊魂血夜”“狂暴突围”两版海报同步释出", "level": "event_exists", "locator": "搜狐娱乐: 海报双发", "source_id": "src-sohu-shenghuaweiji", "plan_kind": "specific_context"},
            {"text": "全新原创故事", "level": "mechanism", "locator": "17173: 导语定性", "source_id": "src-17173-shenghuaweiji", "plan_kind": "mechanism"},
            {"text": "保罗·沃尔特·豪泽、扎克·切利、卡莉·瑞斯参与主演", "level": "character_setup", "locator": "17173: 主演名单", "source_id": "src-17173-shenghuaweiji", "plan_kind": "fact"},
        ],
        "by_source": {
            "src-sohu-shenghuaweiji": [
                "惊悚电影《生化危机：爆发夜》今日官宣确认引进",
                "“惊魂血夜”“狂暴突围”版海报双发",
                "四周一片漆黑，变异生物拦在车前，在车灯的光亮中展现出诡异扭曲的倒影",
                "车尾灯的红色也增添了一分危险的气息",
                "城市一片寂静，暴风雪中，汽车翻倒、城市轮廓模糊不清，而变异生物已经占领各个建筑，只剩持枪的布莱恩背着快递包裹，孤身闯入诡异又凶险的城市",
                "变异怪物现身城市",
                "影片讲述了一名医疗快递员布莱恩（奥斯汀·艾布拉姆斯）运送医疗包裹的途中，意外卷入一场生化变异危机",
                "《生化危机》系列时隔九年再登内地大银幕",
                "影片由扎克·克雷格执导",
                "扎克·克雷格善于用黑色幽默来放大极致惊悚的紧张氛围",
                "以第一视角镜头",
            ],
            "src-17173-shenghuaweiji": [
                "真人电影《生化危机：爆发夜》今日官宣确认引进",
                "全新原创故事",
                "本片将讲述奉命奔赴浣熊市的医疗速递员布莱恩，却意外深陷全城失控的病毒浩劫的故事",
                "这也是该IP的最新一部院线电影",
                "奥斯汀·艾布拉姆斯、保罗·沃尔特·豪泽、扎克·切利、卡莉·瑞斯参与主演",
                "《生化危机》系列时隔九年，重返内地大银幕",
                "档期待定",
                "导演扎克·克雷格此前回应了为何弃用里昂，他并不想重讲里昂的故事",
                "发生在《生化危机》世界观的全新故事，时间线大致与《生化危机2》相同",
                "电影官方提醒：未成年人谨慎观看",
                "本片根据热门恐怖游戏《生化危机》改编",
                "由《凶器》《野蛮人》导演扎克・克雷格倾力打造",
            ],
        },
        "audience": "看过生化危机系列、关心引进新片的观众",
    },
}


# --------------------------------------------------------------------------
# 5) Bodies
# --------------------------------------------------------------------------

BODIES = {
    "art-001": """## 第78届艾美奖最值得看的，不是谁拿奖

当地时间9月14日晚颁出的第78届艾美奖，最值得看的不是谁拿奖，而是奖给谁。《寡妇湾》一家拿走6项，喜剧类最佳剧集、最佳男主角、最佳男配角、最佳女配角、最佳导演、最佳编剧全是它；剧情类最佳剧集给了《匹兹堡医护前线》，诺亚·怀尔凭该剧拿到剧情类最佳男主角。把这些名字放在一起看，答案很清楚：这是一场老面孔的加冕礼。

新面孔不是没有。凯特·奥弗林凭《寡妇湾》拿到喜剧类最佳女配角，这是她第一次获奖。但整晚真正让人记住的，是三个等了很久的名字：珍·斯玛特五季五拿、马修·瑞斯同一晚两个视帝、蕾亚·塞洪四提之后终圆梦。

## 珍·斯玛特：同一部剧，五季五拿

珍·斯玛特凭《绝望写手》第五次拿到喜剧类最佳女主角。把五年的结果连起来看：五季五拿喜剧视后，创下艾美历史；珍·斯玛特成为首位凭同一部剧每一季都获奖的女演员。第五季也是最终季——这部剧从开播到收官，每一季的表演都被认了一遍。

一个演员被同一部剧连着肯定五年，这个事实本身已经足够说明问题。五次获奖连在一起，可以读成对同一种创作耐力的反复确认。

对观众来说，这个纪录最实际的含义是：当你把一部剧从头追到尾，它的每一季都被同一套标准认了一遍。奖项五连，替观众把"要不要看完"这个问题提前回答了。

## 马修·瑞斯和蕾亚·塞洪：等了很多年的人

马修·瑞斯凭《寡妇湾》拿到喜剧类最佳男主角，又凭 Netflix 剧集《兽藏我心》拿到限定剧或单元剧最佳男主角，成为首位在同一届艾美奖中同时拿下这两大类男主角奖的男演员。同一年、两个类别、两个视帝——两个奖写在同一晚，本身就足够罕见。

蕾亚·塞洪凭《同乐者》拿下剧情类最佳女主角。把时间线拉长一点看会更动人：此前她因《风骚律师》四提零中，如今终于圆梦。四提零中到首夺，中间隔了四次陪跑；五次提名连起来看，这个结果呈现出的轨迹是水到渠成。

## 老面孔统治，是保守还是耐力

如果只看奖单，这届艾美奖确实把最高的奖项都给了演了很多年的人。《扣扣熊晚间秀》拿到最佳综艺类剧集，终结了《约翰·奥利弗上周今夜秀》自2016年以来连续获奖的纪录；《同乐者》的剧情类最佳编剧给了文斯·吉里根，《流人》的剧情类最佳导演给了索尔·梅茨斯坦。

限定剧或单元剧类别里，最佳给了《DTF圣路易日记》，莎莉·菲尔德凭《幸运有八只触手》拿到该类别最佳女主角；真人秀竞赛节目奖由《背叛者》获得。把剧情、喜剧、限定剧、综艺四个板块放在一起看，这届奖单最突出的共同点，是每个板块领跑的赢家都是观众见过很多次的名字。

所以这届艾美奖最值得转述的判断不是谁爆冷，而是：在流媒体拼命上新剧的年份，评委把最多的票投给了耐久性。珍·斯玛特的五连、马修·瑞斯的双视帝、蕾亚·塞洪的圆梦，指向同一个意思——奖项对持续在场的信任，压过了对新鲜登场的好奇。这种口味会不会延续，要看明年的奖单自己怎么回答。""",
    "art-002": """## 9年没进内地影院的生化危机，这次带回来的主角不是里昂

9月15日，《生化危机：爆发夜》官宣确认引进，“惊魂血夜”“狂暴突围”两版海报同步释出，档期待定。系列上一次登上内地大银幕，已经是9年前；这一次带回来的主角不是里昂，而是一名医疗快递员。

这部电影的卖点都押在一个“新”字上：全新原创故事，弃用里昂之后启用新主角。主角布莱恩（奥斯汀·艾布拉姆斯 饰）是一名医疗快递员，运送医疗包裹的途中意外卷入生化变异危机——他奉命奔赴浣熊市，却深陷全城失控的病毒浩劫。

## 弃用里昂：不重讲老故事，也不复刻游戏

新作在创作选择上刻意与旧系列划清界限。导演扎克·克雷格此前回应了为何弃用里昂：他并不想重讲里昂的故事，也不打算复刻原版游戏剧情。在他看来，全新《生化危机》电影并不是某款游戏或角色剧情的改编，而是发生在《生化危机》世界观里的全新故事，时间线大致与《生化危机2》相同。

弃用里昂这个决定本身就足够醒目。但反过来看，这正是这部引进片最大的信息量——它想证明世界观本身还能讲出新故事，而不是靠熟脸撑住片长。系列粉丝等了9年，等来的不是熟悉的面孔，而是一个全新的浣熊市故事。本片根据热门恐怖游戏《生化危机》改编，也是该IP最新一部院线电影。

## 送快递的人，被扔进浣熊市

主角从粉丝熟悉的里昂换成一名医疗快递员，是这部电影与旧系列最直接的差别：一个送快递的普通人，被扔进了浣熊市。两版海报展现出布莱恩独自面对两种不同处境的惊悚瞬间——“惊魂血夜”版里，四周一片漆黑，变异生物拦在车前，在车灯的光亮中展现出诡异扭曲的倒影，车尾灯的红色也增添了一分危险的气息；“狂暴突围”版里，城市一片寂静，暴风雪中汽车翻倒、城市轮廓模糊不清，变异生物已经占领各个建筑，只剩持枪的布莱恩背着快递包裹，孤身闯入诡异又凶险的城市。

海报里，这个主角的装备就是肩上的快递包裹和手里的枪。没有拯救世界的计划，也没有主角光环式的登场——惊悚的入口从"怎么打败怪物"，换成了"怎么把这一单送到"。

制作层面同样在换打法。影片由扎克·克雷格执导，他此前拍过《凶器》《野蛮人》，善于用黑色幽默放大极致惊悚的紧张氛围，这次会以第一视角镜头呈现——观众和布莱恩共享同一双眼睛，不知道下一个拐角有什么。主演还包括保罗·沃尔特·豪泽、扎克·切利、卡莉·瑞斯。片方也提前打了招呼：未成年人谨慎观看。

## 引进确认之后，剩下的问题交给档期

引进确认、时隔9年、档期待定。海报上变异怪物现身城市的场面、第一视角的惊悚卖点、导演的黑色幽默风格，都已经摆在那里；真正要等的，是档期落定、成片上映。

所以这部生化危机的看点不在怪物更大，而在主角更小——一个送快递的布莱恩，代替了粉丝最熟悉的里昂。它能不能接住9年的等待，要等档期落定、成片上映之后才有答案。""",
}


# --------------------------------------------------------------------------
# 6) Review evidence + delivery
# --------------------------------------------------------------------------

TITLES = {
    "art-001": [
        ("第78届艾美奖为什么成了老面孔的加冕礼", "奖项叙事"),
        ("珍·斯玛特五连冠背后，艾美奖在奖励什么", "创作耐力"),
        ("同一晚双视帝、四提终圆梦：这届艾美奖的等待者", "人物群像"),
    ],
    "art-002": [
        ("《生化危机：爆发夜》确认引进：9年之后，主角换成了送快递的", "引进信息"),
        ("弃用里昂的新生化危机，想证明世界观本身还能讲新故事", "创作选择"),
        ("确认引进、档期待定：这部生化危机的看点在哪", "档期观察"),
    ],
}

SOURCE_IDS = {
    "art-001": ["src-ithome-aimi", "src-shangbao-aimi"],
    "art-002": ["src-sohu-shenghuaweiji", "src-17173-shenghuaweiji"],
}

MODES = {"art-001": "reported_feature", "art-002": "reported_feature"}

RULE_CLAIMS = {
    "art-001": [
        {"claim_id": "c1", "claim_level": "event_exists", "source_refs": ["src-ithome-aimi"], "source_locators": ["IT之家: 颁奖时间"]},
        {"claim_id": "c2", "claim_level": "mechanism", "source_refs": ["src-shangbao-aimi"], "source_locators": ["印尼商报: 五季五拿创历史"]},
        {"claim_id": "c3", "claim_level": "mechanism", "source_refs": ["src-ithome-aimi"], "source_locators": ["IT之家: 寡妇湾6项与双视帝"]},
        {"claim_id": "c4", "claim_level": "mechanism", "source_refs": ["src-ithome-aimi"], "source_locators": ["IT之家: 扣扣熊终结连胜"]},
    ],
    "art-002": [
        {"claim_id": "c1", "claim_level": "event_exists", "source_refs": ["src-sohu-shenghuaweiji"], "source_locators": ["搜狐娱乐: 官宣引进"]},
        {"claim_id": "c2", "claim_level": "mechanism", "source_refs": ["src-17173-shenghuaweiji"], "source_locators": ["17173: 弃用里昂与时间线"]},
        {"claim_id": "c3", "claim_level": "character_setup", "source_refs": ["src-sohu-shenghuaweiji"], "source_locators": ["搜狐娱乐: 主角设定"]},
        {"claim_id": "c4", "claim_level": "event_exists", "source_refs": ["src-17173-shenghuaweiji"], "source_locators": ["17173: 档期待定"]},
    ],
}


# --------------------------------------------------------------------------
# Run data (extracted from generator logic, 2026-09-15)
# --------------------------------------------------------------------------

BRIEFS = {
    "art-001": """# Writing Brief

production_contract: article-first-v1
brief_contract: writing-brief-v2
title_contract: title-pack-v1
legacy_compatibility: false
run_contract_required: true
article_id: art-001
candidate_id: cand-aimi-jueshi-001
article_mode: reported_feature
required_source_roles: [media_report]
topic_version: 1
content_map: C
reference_shape: viewing_commentary
core_question: 第78届艾美奖为什么成了老面孔的加冕礼
target_reader: 追美剧、关心奖项背后创作规律的观众
editorial_angle: 这届艾美奖把最重的大奖都给了演了很多年的人，奖项在奖励持续在场而非新鲜登场
body_route: 先用颁奖与大奖归属进入，再写三位等待者的个人故事，最后收束到奖项口味判断
evidence_boundary: 只写两份来源中的获奖名单、历史创造细节与纪录表述；不写未出现在来源中的获奖者细节
required_hard_information: 当地时间9月14日晚颁奖；珍·斯玛特五季五拿创历史；马修·瑞斯双视帝第一人；蕾亚·塞洪四提零中终圆梦；寡妇湾6项；扣扣熊终结奥利弗2016年以来连胜
unsupported_boundary: 不能证明艾美奖评委的真实投票动机，不能推断明年奖项趋势，不写观众口碑
""",
    "art-002": """# Writing Brief

production_contract: article-first-v1
brief_contract: writing-brief-v2
title_contract: title-pack-v1
legacy_compatibility: false
run_contract_required: true
article_id: art-002
candidate_id: cand-shenghuaweiji-yinjin-001
article_mode: reported_feature
required_source_roles: [media_report]
topic_version: 1
content_map: A
reference_shape: viewing_commentary
core_question: 时隔九年重回内地银幕的《生化危机：爆发夜》，为什么把主角换成一名医疗快递员
target_reader: 看过生化危机系列、关心引进新片的观众
editorial_angle: 新作不复刻任何一版游戏剧情，而是把一个送快递的小人物扔进浣熊市
body_route: 从引进官宣与九年间隔进入，再写弃用里昂的创作选择，接着写快递员主角与制作换法，最后收束到档期悬念
evidence_boundary: 只写两份来源中的引进事实、导演回应与官方口径；不写档期之外的发行细节
required_hard_information: 9月15日官宣确认引进；双海报释出；时隔九年；档期待定；导演扎克·克雷格；主演四人；主角医疗快递员布莱恩；时间线大致与生化危机2相同；官方提醒未成年人谨慎观看
unsupported_boundary: 不能证明档期与成片质量，不能把通稿形容词当作质量结论，不写观众口碑
""",
}

BRIEF_SPECS = [
    (
        "art-001",
        "reported_feature",
        "media_report",
        "第78届艾美奖为什么成了老面孔的加冕礼",
        "src-ithome-aimi",
    ),
    (
        "art-002",
        "reported_feature",
        "media_report",
        "时隔九年重回内地银幕的《生化危机：爆发夜》，为什么把主角换成一名医疗快递员",
        "src-sohu-shenghuaweiji",
    ),
]

CONTENT_RECORD_ARGS = [
    {
        "aid": "art-001",
        "mode": "reported_feature",
        "role": "media_report",
        "core_object": "第78届艾美奖的获奖名单与老面孔叙事",
        "question": "第78届艾美奖为什么成了老面孔的加冕礼",
        "mechanism": "五连冠、双视帝与四提圆梦共同说明，奖项在奖励演员的持续在场而非新鲜登场",
        "takeaway": "在流媒体拼命上新剧的年份，评委把最多的票投给了耐久性。",
        "hard": [
            {"information_id": "i1", "text": "当地时间9月14日晚，第78届黄金时段艾美奖颁奖典礼在美国举行", "kind": "specific_context", "body_locator": "p1", "source_refs": ["src-ithome-aimi"], "source_locators": ["IT之家: 颁奖时间"], "independence_key": "ceremony-date"},
            {"information_id": "i2", "text": "苹果AppleTV+剧集《寡妇湾》共获得6项奖项", "kind": "fact", "body_locator": "p1", "source_refs": ["src-ithome-aimi"], "source_locators": ["IT之家: 寡妇湾6项"], "independence_key": "widows-bay-sweep"},
            {"information_id": "i3", "text": "《绝望写手》的珍•斯玛特五季五拿喜剧视后，创下艾美历史", "kind": "mechanism", "body_locator": "p3", "source_refs": ["src-shangbao-aimi"], "source_locators": ["印尼商报: 五季五拿"], "independence_key": "smart-five"},
            {"information_id": "i4", "text": "成为首位凭同一部剧每一季都获奖的女演员", "kind": "mechanism", "body_locator": "p3", "source_refs": ["src-shangbao-aimi"], "source_locators": ["印尼商报: 历史创造"], "independence_key": "smart-first"},
            {"information_id": "i5", "text": "马修•瑞斯以两部剧集同时拿下两个视帝", "kind": "fact", "body_locator": "p5", "source_refs": ["src-shangbao-aimi"], "source_locators": ["印尼商报: 双视帝"], "independence_key": "rhys-double"},
            {"information_id": "i6", "text": "蕾亚•塞洪凭《同乐者》首夺艾美奖，此前她因《风骚律师》四提零中，如今终于圆梦", "kind": "fact", "body_locator": "p6", "source_refs": ["src-shangbao-aimi"], "source_locators": ["印尼商报: 四提圆梦"], "independence_key": "seehorn-first"},
            {"information_id": "i7", "text": "《扣扣熊晚间秀》终结了《约翰·奥利弗上周今夜秀》自2016年以来连续获奖的纪录", "kind": "mechanism", "body_locator": "p7", "source_refs": ["src-ithome-aimi"], "source_locators": ["IT之家: 连胜终结"], "independence_key": "colbert-streak"},
            {"information_id": "i8", "text": "《寡妇湾》拿下了最佳喜剧类剧集、最佳男主角、最佳男配角、最佳女配角、最佳导演和最佳编剧等奖项", "kind": "fact", "body_locator": "p1", "source_refs": ["src-ithome-aimi"], "source_locators": ["IT之家: 六类别枚举"], "independence_key": "widows-categories"},
            {"information_id": "i9", "text": "剧情类最佳剧集给了《匹兹堡医护前线》，诺亚·怀尔凭该剧拿到剧情类最佳男主角", "kind": "fact", "body_locator": "p1", "source_refs": ["src-ithome-aimi"], "source_locators": ["IT之家: 剧情类归属"], "independence_key": "pitt-drama"},
            {"information_id": "i10", "text": "《同乐者》的剧情类最佳编剧给了文斯·吉里根，《流人》的剧情类最佳导演给了索尔·梅茨斯坦", "kind": "fact", "body_locator": "p7", "source_refs": ["src-ithome-aimi"], "source_locators": ["IT之家: 编剧导演归属"], "independence_key": "writing-directing"},
            {"information_id": "i11", "text": "限定剧或单元剧最佳给了《DTF圣路易日记》", "kind": "fact", "body_locator": "p8", "source_refs": ["src-ithome-aimi"], "source_locators": ["IT之家: 限定剧归属"], "independence_key": "limited-dtf"},
            {"information_id": "i12", "text": "真人秀竞赛节目奖由《背叛者》获得", "kind": "fact", "body_locator": "p8", "source_refs": ["src-ithome-aimi"], "source_locators": ["IT之家: 真人秀归属"], "independence_key": "traitors-reality"},
        ],
        "bases": [
            {"locator": "p3", "fact_or_scene": "第五季也是最终季", "explanation": "每一季都被认可说明奖励的是持续在场"},
            {"locator": "p6", "fact_or_scene": "四提零中到首夺", "explanation": "等待史是评委共识的落地"},
        ],
        "boundary": "当前来源不能证明艾美奖评委的真实投票动机，也不能证明明年的奖项趋势；不写未出现在两页来源中的获奖者细节。",
        "source_ids": ["src-ithome-aimi", "src-shangbao-aimi"],
    },
    {
        "aid": "art-002",
        "mode": "reported_feature",
        "role": "media_report",
        "core_object": "《生化危机：爆发夜》的引进信息与主角选择",
        "question": "时隔九年重回内地银幕的《生化危机：爆发夜》，为什么把主角换成一名医疗快递员",
        "mechanism": "弃用里昂和快递员主角共同说明，新作想用世界观讲新故事，而不是复刻旧角色",
        "takeaway": "这部生化危机的看点不在怪物更大，而在主角更小。",
        "hard": [
            {"information_id": "i1", "text": "惊悚电影《生化危机：爆发夜》今日官宣确认引进", "kind": "specific_context", "body_locator": "p1", "source_refs": ["src-sohu-shenghuaweiji"], "source_locators": ["搜狐娱乐: 官宣引进"], "independence_key": "import-confirm"},
            {"information_id": "i2", "text": "《生化危机》系列时隔九年再登内地大银幕", "kind": "fact", "body_locator": "p1", "source_refs": ["src-sohu-shenghuaweiji"], "source_locators": ["搜狐娱乐: 时隔九年"], "independence_key": "nine-years"},
            {"information_id": "i3", "text": "档期待定", "kind": "specific_context", "body_locator": "p1", "source_refs": ["src-17173-shenghuaweiji"], "source_locators": ["17173: 档期状态"], "independence_key": "date-tbd"},
            {"information_id": "i4", "text": "影片讲述了一名医疗快递员布莱恩（奥斯汀·艾布拉姆斯）运送医疗包裹的途中，意外卷入一场生化变异危机", "kind": "fact", "body_locator": "p2", "source_refs": ["src-sohu-shenghuaweiji"], "source_locators": ["搜狐娱乐: 主角设定"], "independence_key": "courier-hero"},
            {"information_id": "i5", "text": "导演扎克·克雷格此前回应了为何弃用里昂，他并不想重讲里昂的故事", "kind": "mechanism", "body_locator": "p3", "source_refs": ["src-17173-shenghuaweiji"], "source_locators": ["17173: 弃用里昂"], "independence_key": "no-leon"},
            {"information_id": "i6", "text": "时间线大致与《生化危机2》相同", "kind": "fact", "body_locator": "p3", "source_refs": ["src-17173-shenghuaweiji"], "source_locators": ["17173: 时间线"], "independence_key": "re2-timeline"},
            {"information_id": "i7", "text": "影片由扎克·克雷格执导", "kind": "fact", "body_locator": "p6", "source_refs": ["src-sohu-shenghuaweiji"], "source_locators": ["搜狐娱乐: 导演"], "independence_key": "cregger-direct"},
            {"information_id": "i8", "text": "电影官方提醒：未成年人谨慎观看", "kind": "fact", "body_locator": "p6", "source_refs": ["src-17173-shenghuaweiji"], "source_locators": ["17173: 官方提醒"], "independence_key": "minors-warning"},
            {"information_id": "i9", "text": "“惊魂血夜”“狂暴突围”两版海报同步释出", "kind": "fact", "body_locator": "p1", "source_refs": ["src-sohu-shenghuaweiji"], "source_locators": ["搜狐娱乐: 海报双发"], "independence_key": "two-posters"},
            {"information_id": "i10", "text": "全新原创故事", "kind": "fact", "body_locator": "p2", "source_refs": ["src-17173-shenghuaweiji"], "source_locators": ["17173: 导语定性"], "independence_key": "original-story"},
            {"information_id": "i11", "text": "主角奉命奔赴浣熊市，却深陷全城失控的病毒浩劫", "kind": "fact", "body_locator": "p2", "source_refs": ["src-17173-shenghuaweiji"], "source_locators": ["17173: 剧情设定"], "independence_key": "raccoon-outbreak"},
            {"information_id": "i12", "text": "这是该IP最新一部院线电影", "kind": "fact", "body_locator": "p4", "source_refs": ["src-17173-shenghuaweiji"], "source_locators": ["17173: IP院线"], "independence_key": "latest-theatrical"},
            {"information_id": "i13", "text": "主演还包括保罗·沃尔特·豪泽、扎克·切利、卡莉·瑞斯", "kind": "fact", "body_locator": "p6", "source_refs": ["src-17173-shenghuaweiji"], "source_locators": ["17173: 主演名单"], "independence_key": "cast-three"},
            {"information_id": "i14", "text": "海报里只剩持枪的布莱恩背着快递包裹，孤身闯入诡异又凶险的城市", "kind": "fact", "body_locator": "p5", "source_refs": ["src-sohu-shenghuaweiji"], "source_locators": ["搜狐娱乐: 海报画面"], "independence_key": "poster-courier"},
        ],
        "bases": [
            {"locator": "p3", "fact_or_scene": "弃用里昂并声明不复刻游戏", "explanation": "用世界观讲新故事而非靠熟脸"},
            {"locator": "p5", "fact_or_scene": "主角是医疗快递员", "explanation": "小人物主角是最大的信息差"},
        ],
        "boundary": "当前来源不能证明档期、成片质量和观众口碑；不写未出现在两页来源中的剧情细节。",
        "source_ids": ["src-sohu-shenghuaweiji", "src-17173-shenghuaweiji"],
    },
]

BATCH_SPECS = {
    "art-001": (
        "cand-aimi-jueshi-001",
        "绝望写手",
        "emmys-78-veterans-coronation",
        ["src-ithome-aimi", "src-shangbao-aimi"],
        "A",
        "C",
    ),
    "art-002": (
        "cand-shenghuaweiji-yinjin-001",
        "生化危机：爆发夜",
        "resident-evil-outbreak-night-import",
        ["src-sohu-shenghuaweiji", "src-17173-shenghuaweiji"],
        "B",
        "A",
    ),
}


if __name__ == "__main__":
    import sys as _sys

    from scripts.daily_engine import build_run

    build_run(_sys.modules[__name__])
