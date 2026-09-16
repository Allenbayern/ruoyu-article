"""Build runs/2026-09-16/daily-008 (two_article_daily, article-first lane).

选题来源：今日谈资型发现源分类信号（DailyHotApi 快照 + LLM 分类层，2026-09-16
落地后首期使用）+ NAS 糖果梦热榜交叉验证。两题均过五问检查表（读者/落点/情绪/
删节点测试/社交原动力，机器必填）与作品去重：

- art-001 知乎信号"为什么《一步之遥》《邪不压正》都达不到《让子弹飞》的高度？"
  ——立场宣判型：姜文与观众的错位（2025《你行！你上！》票房口碑为最新数据点）；
- art-002 知乎信号"《还珠格格》一二部完整还是二三部完整"——情绪顿悟型：集体
  记忆的分叉（第三部大换血与"不承认"）。

读者面零自证、无播出日期/平台通告句；证据归因全部在后台账本。知乎问题页
403 未捕获，仅作 R0 信号，正文不把"热榜第几"写成事实。
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

base.ROOT = Path("runs/2026-09-16/daily-008")
ROOT = base.ROOT
CONTRACT = base.CONTRACT
RUN_ID = "2026-09-16/daily-008"
GROUP_ID = "article-group-2026-09-16-003"
CAPTURED_AT = "2026-09-16T09:30:00+08:00"


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
# 0) Discovery radar (R0) — 谈资型发现源分类信号 + NAS 糖果梦热榜
# --------------------------------------------------------------------------

RADAR_RECORDS = [
    ("dailyhot-zhihu", "1020000", "为什么《一步之遥》《邪不压正》都达不到《让子弹飞》的高度？", 1),
    ("dailyhot-zhihu", "-", "你认为《还珠格格》一二部是一个完整的故事，还是二三部是一个完整的故事？", 1),
    ("tgmeng-weibo", "1738008", "优酷2027年度片单", 2),
    ("tgmeng-douban", "34255", "原来红楼梦里大家经常随地小解", 3),
]


# --------------------------------------------------------------------------
# 1) Sources: captured public pages used as evidence
# --------------------------------------------------------------------------

SOURCES = {
    "src-wenwei-nixing": {
        "source_role": "media_report",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "http://www.news.cn/ent/20250722/23c2e510ee8e46ff9a1e8f1891455d8a/c.html",
        "source_type": "media_report",
        "artifact_path": "sources/c01-news-wenwei.html",
        "captured_from": "新华网·文汇报（2025-07-22，十年后《你行！你上！》豆瓣还会是6.7分吗）",
    },
    "src-sohu-jw": {
        "source_role": "commentary",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "https://www.sohu.com/a/917267818_580553",
        "source_type": "commentary",
        "artifact_path": "sources/c02-sohu-jw.html",
        "captured_from": "搜狐·影吹斯汀（2025-07-24，《你行！你上！》为何口碑票房双扑）",
    },
    "src-thepaper-jianpian": {
        "source_role": "commentary",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "https://www.thepaper.cn/newsDetail_forward_31202115",
        "source_type": "commentary",
        "artifact_path": "sources/c03-thepaper-jianpian.html",
        "captured_from": "澎湃新闻·湃客·鉴片工场（2025-07-19，姜文不装了）",
    },
    "src-shobserver-han": {
        "source_role": "commentary",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "https://www.shobserver.com/wx/detail.do?id=950162",
        "source_type": "commentary",
        "artifact_path": "sources/c04-shobserver-han.html",
        "captured_from": "上观新闻·韩浩月（2025-07-21，隐喻失效，姜文该重新认识自己了）",
    },
    "src-sina-caidan": {
        "source_role": "media_report",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "http://ent.sina.com.cn/original/qihua/huanzhucaidan/?from=wap",
        "source_type": "media_report",
        "artifact_path": "sources/d01-sina-caidan.html",
        "captured_from": "新浪娱乐·特别企划（2018-04-26，这是一份《还珠》隐藏彩蛋）",
    },
    "src-sohu-huanzhu3": {
        "source_role": "commentary",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "https://www.sohu.com/a/766749480_121175242",
        "source_type": "commentary",
        "artifact_path": "sources/d02-sohu-huanzhu3.html",
        "captured_from": "搜狐号·老坚果笑不倒（2024-03-26，还珠3演员大换血真相）",
    },
    "src-163-huanzhu3": {
        "source_role": "commentary",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "https://www.163.com/dy/article/DD7620V80517MO4G.html",
        "source_type": "commentary",
        "artifact_path": "sources/d03-163-huanzhu3.html",
        "captured_from": "网易订阅（赵薇苏有朋等人为什么不出演《还珠格格3》）",
    },
    "src-yahoo-zhaowei": {
        "source_role": "commentary",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "https://tw.news.yahoo.com/%E8%B6%99%E8%96%87%E5%AF%A7%E5%90%91%E7%93%8A%E7%91%A4%E6%89%BF%E8%AB%BE4%E5%B9%B4%E4%B8%8D%E6%BC%94%E9%9B%BB%E8%A6%96%E5%8A%87-%E5%A0%85%E6%8C%81%E6%8B%92%E6%BC%94-%E9%82%84%E7%8F%A03-%E5%8E%9F%E5%9B%A0%E6%9B%9D%E5%85%89-120100468.html",
        "source_type": "commentary",
        "artifact_path": "sources/d04-yahoo-zhaowei.html",
        "captured_from": "Yahoo奇摩新聞（趙薇堅持拒演《還珠3》原因曝光）",
    },
    "src-360-huanzhu3": {
        "source_role": "commentary",
        "supports_mode": ["reported_feature"],
        "cannot_support": ["viewing_experience", "audience_consensus", "ending"],
        "source_capability": "mechanism",
        "capability_levels": ["event_exists", "character_setup", "mechanism"],
        "source_url": "https://yule.360.com/detail/309058",
        "source_type": "commentary",
        "artifact_path": "sources/d05-360-huanzhu3.html",
        "captured_from": "360娱乐·橘子娱乐（2018-02-12，为什么我们不承认《还珠格格》第三部）",
    },
}


# --------------------------------------------------------------------------
# 2) Candidate pool（五问字段机器必填，2026-09-16 起）
# --------------------------------------------------------------------------

CANDIDATES = [
    {
        "candidate_id": "cand-jiangwen-divide-001",
        "work": "姜文电影（让子弹飞/一步之遥/邪不压正/你行你上）",
        "work_title": "姜文电影",
        "signal": "知乎热榜：为什么《一步之遥》《邪不压正》都达不到《让子弹飞》的高度？（1020000）",
        "signal_source": "dailyhot-zhihu",
        "topic_mode": "culture",
        "article_mode": "reported_feature",
        "content_map": "C",
        "event_cluster_id": "jiangwen-film-divide",
        "content_map_label": "文化现象",
        "freshness_window": "same-day",
        "remove_timestamp_test": "pass",
        "evidence_readiness": "high",
        "recommendation": "A",
        "editorial_value_score": 8,
        "reader": "看过《让子弹飞》、在姜文新片口碑里找不到当年感觉的观众",
        "landing": "看懂姜文与观众的错位：爽的那一部是巧合，拧巴的才是常态",
        "emotion": "意难平",
        "social_motive": "表达立场",
        "reader_question": "为什么《一步之遥》《邪不压正》都达不到《让子弹飞》的高度",
        "core_question": "为什么《一步之遥》《邪不压正》都达不到《让子弹飞》的高度",
        "angle": "姜文没变，观众和时代变了——《你行！你上！》6.7分与8200万，把这场持续多年的错位摆到了台面上",
        "source_refs": ["src-wenwei-nixing", "src-sohu-jw"],
        "prior_run_conflict": False,
        "selection_reason": "知乎热榜当日信号（老片比较题重新冒头）+长期议题；《你行！你上！》（2025）票房口碑为最新数据点；无同作品历史，五问全过",
    },
    {
        "candidate_id": "cand-huanzhu-memory-001",
        "work": "还珠格格",
        "work_title": "还珠格格",
        "signal": "知乎热榜：你认为《还珠格格》一二部是一个完整的故事，还是二三部是一个完整的故事？",
        "signal_source": "dailyhot-zhihu",
        "topic_mode": "culture",
        "article_mode": "reported_feature",
        "content_map": "B",
        "event_cluster_id": "huanzhu-part3-memory-split",
        "content_map_label": "集体记忆",
        "freshness_window": "same-day",
        "remove_timestamp_test": "pass",
        "evidence_readiness": "high",
        "recommendation": "A",
        "editorial_value_score": 8,
        "reader": "被《还珠》前两部占据过童年、对第三部选择性失忆的观众",
        "landing": "看懂集体记忆的分叉：前两部的圆满是封印，第三部打开的是婚后的日子",
        "emotion": "怀旧",
        "social_motive": "找同类",
        "reader_question": "为什么我们只承认《还珠格格》有两部",
        "core_question": "为什么我们只承认《还珠格格》有两部",
        "angle": "第三部大换血只是导火索——观众不承认的，是前两部刚刚停在了每个人最想停的地方",
        "source_refs": ["src-sina-caidan", "src-sohu-huanzhu3", "src-163-huanzhu3", "src-360-huanzhu3"],
        "prior_run_conflict": False,
        "selection_reason": "知乎热榜当日信号（一二部vs二三部完整性站队）+集体记忆长期议题；换角史实有多个可核验来源；五问全过",
    },
]

REJECTED_PRIOR_WORKS = [
    {"work": "兰香如故", "reason": "daily-007 已写（杜翠雀角度），本批不重复"},
    {"work": "国产剧起名", "reason": "daily-007 已写（剧名同质化），本批不重复"},
    {"work": "红楼梦", "reason": "豆瓣热榜信号（随地小解细节讨论）未成题：讨论帖为主、权威来源不足，落点泛"},
    {"work": "优酷2027片单", "reason": "微博热榜信号未成题：行业片单信号，缺观众向落点与已核验材料"},
    {"work": "杨坤维权", "reason": "涉司法争议当事人边界，不入选题"},
    {"work": "陈建州/佟丽娅/姚安娜", "reason": "隐私八卦类信号，违反选题边界，不入选题"},
]

SLOT_DECISIONS = [
    {
        "slot": 1,
        "article_id": "art-001",
        "candidate_id": "cand-jiangwen-divide-001",
        "decision": "selected",
        "event_cluster_id": "jiangwen-film-divide",
    },
    {
        "slot": 2,
        "article_id": "art-002",
        "candidate_id": "cand-huanzhu-memory-001",
        "decision": "selected",
        "event_cluster_id": "huanzhu-part3-memory-split",
    },
]


# --------------------------------------------------------------------------
# 3) Briefs, task cards, task hierarchy
# --------------------------------------------------------------------------

TASK_CARD_REQUIRED_FIELDS = {
    "art-001": (
        "1. **站队点/可转述句**：让子弹飞之后，姜文的电影一部比一部拧巴——但拧巴的另一面，是他始终没学会骗自己。\n"
        "2. **读者已知锚点**：《让子弹飞》是公认的姜文口碑标杆；《你行！你上！》口碑票房双扑。\n"
        "3. **today-hook 理由**：知乎热榜当日信号：为什么《一步之遥》《邪不压正》都达不到《让子弹飞》的高度？\n"
        "4. **事实底座**：《你行！你上！》以郎朗少年成长经历为蓝本、暌违七年；豆瓣6.7分（与《一步之遥》并列导演作品最低）；公映七天累计票房8200万左右；文汇报称其未达《让子弹飞》《阳光灿烂的日子》口碑高度（来源见后台账本）。\n"
        "5. **最强钩子**：让子弹飞之后，姜文的电影一部比一部拧巴（与 batch.json 的 review_hook 一致）。\n"
        "- **title_promise**：《让子弹飞》之后，姜文为什么一部比一部拧巴\n"
        "- **ending_destination**：这样的导演，观众会生气，但忘不掉。\n"
        "\n## 文章结构大纲（H2 目录）\n"
        "## 那个问题被问了很多年\n"
        "## 6.7分，是姜文导演作品里的最低分\n"
        "## 姜文的电影，从来不是在“讲故事”\n"
        "## 姜文没变，观众和时代变了\n"
        "## 拧巴，是作者的另一种诚实\n"
    ),
    "art-002": (
        "1. **站队点/可转述句**：我们只承认《还珠格格》有两部，不是因为第三部拍得差，而是因为前两部刚好停在了每个人最想停的地方。\n"
        "2. **读者已知锚点**：《还珠格格》一二部是童年经典；第三部《天上人间》主演大换血。\n"
        "3. **today-hook 理由**：知乎热榜当日信号：《还珠格格》一二部完整还是二三部完整。\n"
        "4. **事实底座**：第三部主演大换血、观众无法适应、收视率差；赵薇拒演并承诺4年不演电视剧；琼瑶称大换角是“心头之痛”；《还珠》本不受琼瑶重视（选角细节见新浪娱乐彩蛋企划）（来源见后台账本）。\n"
        "5. **最强钩子**：我们只承认《还珠格格》有两部（与 batch.json 的 review_hook 一致）。\n"
        "- **title_promise**：《还珠格格》第三部为什么像另一部剧\n"
        "- **ending_destination**：吵到最后，大家怀念的是同一段童年。\n"
        "\n## 文章结构大纲（H2 目录）\n"
        "## 你的《还珠》，到第几部为止\n"
        "## 拒绝出演的人，比剧本身更有故事\n"
        "## 前两部，本来也是一场意外\n"
        "## 我们“不承认”的，是被打开的童话\n"
        "## 记忆会分叉，但每个人的童年只有一部\n"
    ),
}

STRONGEST_HOOKS = {
    "art-001": "让子弹飞之后，姜文的电影一部比一部拧巴",
    "art-002": "我们只承认《还珠格格》有两部",
}


# --------------------------------------------------------------------------
# 4) Material packs（账本：by_source 全部逐字取自来源页面）
# --------------------------------------------------------------------------

MATERIAL_SPECS = {
    "art-001": {
        "mode": "reported_feature",
        "role": "media_report",
        "source_ids": ["src-wenwei-nixing", "src-sohu-jw", "src-thepaper-jianpian", "src-shobserver-han"],
        "question": "为什么《一步之遥》《邪不压正》都达不到《让子弹飞》的高度",
        "mechanism": "让子弹飞的“爽”与“表达”只是短暂同频；此后观众要爽、姜文要表达，错位越拉越大",
        "facts": [
            {"text": "以钢琴家郎朗少年成长经历为蓝本，姜文新作《你行！你上！》正式登陆全国院线", "level": "event_exists", "locator": "文汇报: 郎朗蓝本", "source_id": "src-wenwei-nixing", "plan_kind": "specific_context"},
            {"text": "姜文导演暌违七年的新作《你行！你上！》正式登陆全国院线", "level": "event_exists", "locator": "文汇报: 暌违七年", "source_id": "src-wenwei-nixing", "plan_kind": "specific_context"},
            {"text": "截至7月21日，《你行！你上！》该片豆瓣评分稳定在6.7分", "level": "event_exists", "locator": "文汇报: 豆瓣6.7", "source_id": "src-wenwei-nixing", "plan_kind": "specific_context"},
            {"text": "这一分数既未达到姜文过往《让子弹飞》《阳光灿烂的日子》等作品的口碑高度，也未跌入烂片行列", "level": "mechanism", "locator": "文汇报: 口碑高度", "source_id": "src-wenwei-nixing", "plan_kind": "mechanism"},
            {"text": "《你行！你上！》公映七天，累计票房仅为8200万左右，单日票房已经跌到第八名", "level": "event_exists", "locator": "影吹斯汀: 七天8200万", "source_id": "src-sohu-jw", "plan_kind": "specific_context"},
            {"text": "影片豆瓣评分为6.7，是姜文所有导演作品中的最低（和《一步之遥》并列）", "level": "mechanism", "locator": "影吹斯汀: 最低分", "source_id": "src-sohu-jw", "plan_kind": "mechanism"},
            {"text": "姜文没变，观众和时代变了", "level": "mechanism", "locator": "影吹斯汀: 标题判断", "source_id": "src-sohu-jw", "plan_kind": "mechanism"},
            {"text": "姜文新片《你行！你上！》豆瓣开分6.7，成为他导演生涯最低分作品", "level": "event_exists", "locator": "上观新闻: 开分6.7", "source_id": "src-shobserver-han", "plan_kind": "specific_context"},
        ],
        "by_source": {
            "src-wenwei-nixing": [
                "以钢琴家郎朗少年成长经历为蓝本，姜文新作《你行！你上！》正式登陆全国院线",
                "姜文导演暌违七年的新作《你行！你上！》正式登陆全国院线",
                "截至7月21日，《你行！你上！》该片豆瓣评分稳定在6.7分，处于中等偏上区间",
                "这一分数既未达到姜文过往《让子弹飞》《阳光灿烂的日子》等作品的口碑高度，也未跌入烂片行列",
                "这种“撕裂感”恰是影片争议性的直接体现",
                "从影片风格来看，姜文在《你行！你上！》中延续了其标志性的创作元素",
                "影评人“钱德勒”撰文写道：“（导演）自觉或不自觉地几乎将他前作的元素都包进馅儿里。”",
                "比如天台这一意象，在《阳光灿烂的日子》《邪不压正》等作品中多次出现",
                "华东师范大学传播学院副教授、影视创编中心主任刘弢则用“旋转木马式叙事”定义姜文在《你行！你上！》中的表达——“剪得狠、语速快、黑色幽默暗藏机锋",
            ],
            "src-sohu-jw": [
                "《你行！你上！》公映七天，累计票房仅为8200万左右，单日票房已经跌到第八名",
                "影片豆瓣评分为6.7，是姜文所有导演作品中的最低（和《一步之遥》并列）",
                "“看不懂”“放飞自我”“爹味”的差评，不绝如缕",
                "“姜文跌下神坛”，似乎已经成了相当一部分观众的共识",
                "姜文没变，观众和时代变了",
                "七年磨一剑的《你行！你上！》公映后，“姜文跌下神坛”，似乎已经成了相当一部分观众的共识",
                "十多年来，庞大的影迷群体把《让子弹飞》盘到包浆，他们对片中的台词金句如数家珍",
            ],
            "src-thepaper-jianpian": [
                "《你行！你上！》是一场荒诞现实主义的音乐狂想",
                "作为中国电影界最具作者性的导演之一，姜文时隔七年携新作《你行！你上！》重返银幕",
                "姜文不装了！《你行！你上！》不玩隐喻，直接明“刚”",
                "从《让子弹飞》的北洋乱世到《邪不压正》的北平风云，姜文始终擅长在历史褶皱中植入当代社会的镜像",
            ],
            "src-shobserver-han": [
                "姜文新片《你行！你上！》豆瓣开分6.7，成为他导演生涯最低分作品",
                "隐喻失效，姜文该重新认识自己了",
                "重复多了，会给创作打上一个死结，而解开这个死结的唯一办法，就是成为自己的批判者",
            ],
        },
        "audience": "看过《让子弹飞》、在姜文新片口碑里找不到当年感觉的观众",
    },
    "art-002": {
        "mode": "reported_feature",
        "role": "media_report",
        "source_ids": ["src-sina-caidan", "src-sohu-huanzhu3", "src-163-huanzhu3", "src-yahoo-zhaowei", "src-360-huanzhu3"],
        "question": "为什么我们只承认《还珠格格》有两部",
        "mechanism": "前两部的圆满停在观众最想停的地方，第三部把婚后的日子翻开——记忆因此分叉",
        "facts": [
            {"text": "《还珠格格》本不受琼瑶重视", "level": "event_exists", "locator": "新浪娱乐: 本不受重视", "source_id": "src-sina-caidan", "plan_kind": "specific_context"},
            {"text": "赵薇苏有朋第一天见面就拍吻戏", "level": "event_exists", "locator": "新浪娱乐: 拍吻戏", "source_id": "src-sina-caidan", "plan_kind": "specific_context"},
            {"text": "到了第三部的时候，突然来了一次大换血，把主演们几乎全换了", "level": "event_exists", "locator": "搜狐号: 大换血", "source_id": "src-sohu-huanzhu3", "plan_kind": "specific_context"},
            {"text": "琼瑶表示，《还珠格格》经历这样的大换角，是她的心头之痛", "level": "mechanism", "locator": "网易订阅: 心头之痛", "source_id": "src-163-huanzhu3", "plan_kind": "mechanism"},
            {"text": "趙薇還向瓊瑤承諾4年內不演電視劇，選擇轉向電影方向去發展", "level": "event_exists", "locator": "Yahoo奇摩: 承诺4年", "source_id": "src-yahoo-zhaowei", "plan_kind": "specific_context"},
            {"text": "如果说前两部为观众创造了美好的爱情童话，第三部就是送给观众的一巴掌", "level": "mechanism", "locator": "橘子娱乐: 童话与巴掌", "source_id": "src-360-huanzhu3", "plan_kind": "mechanism"},
        ],
        "by_source": {
            "src-sina-caidan": [
                "《还珠格格》本不受琼瑶重视",
                "赵薇苏有朋第一天见面就拍吻戏",
                "林心如差点被“退货”",
                "尔康原属意吴奇隆",
                "令妃被“骗”进剧组",
                "皇阿玛在片场闲得遛鸟",
                "如果不是20年后的今天，观众对着第n次重播的《还珠格格》进行了新一轮的脑洞大开",
                "并就“皇后令妃到底谁更心机”、“容嬷嬷是假邪恶还是真忠心”等一系列神奇的问题展开深度举证和讨论",
                "称霸童年回忆的《还珠》竟然深藏着如此多值得回味和推敲的细节",
            ],
            "src-sohu-huanzhu3": [
                "但是到了第三部的时候，突然来了一次大换血，把主演们几乎全换了",
                "这也让观众们无法适应",
                "结果导致第三部的收视率非常差",
                "第一部和第二部非常经典，因为演员都没有更换，还是原来的演员，林心如赵薇范冰冰也都因为这部剧走红",
                "琼瑶后来直言：后悔了",
            ],
            "src-163-huanzhu3": [
                "琼瑶表示，《还珠格格》经历这样的大换角，是她的心头之痛",
                "当时，林心如接了《半生缘》，而苏有朋则希望拓宽戏路",
                "我不出演《还珠格格3》，琼瑶阿姨是非常失望的。我当时只想开拓自己，不想成为一部又一部戏的赚钱机器。",
                "尽管后来翻拍了李晟、海陆版本的《还珠格格》，但仍然无法超越赵薇、林心如版本",
            ],
            "src-yahoo-zhaowei": [
                "趙薇表示，自己很感激瓊瑤的提拔，但也坦言不想過度消費自己，在拒絕出演《還珠格格3》的時候，趙薇還向瓊瑤承諾4年內不演電視劇，選擇轉向電影方向去發展。",
                "而在趙薇提出不演之後，林心如蘇有朋也因檔期問題無法參演。",
            ],
            "src-360-huanzhu3": [
                "第三部剧情走向完全不同，人设完全崩塌",
                "如果说前两部为观众创造了美好的爱情童话，第三部就是送给观众的一巴掌",
                "小燕子和永琪本来是一部甜到牙疼的甜宠文，两人的缘分从围场狩猎开始",
            ],
        },
        "audience": "被《还珠》前两部占据过童年、对第三部选择性失忆的观众",
    },
}


# --------------------------------------------------------------------------
# 5) Bodies（读者面：零自证、无播出通告句、判断句不伪装事实）
# --------------------------------------------------------------------------

BODIES = {
    "art-001": """## 那个问题被问了很多年

为什么《一步之遥》《邪不压正》都达不到《让子弹飞》的高度？

这个问题没有标准答案，但每一个答案，最后都会绕回同一句话：让子弹飞之后，姜文的电影一部比一部拧巴。

作为中国电影界最具作者性的导演之一，姜文时隔七年携新作《你行！你上！》重返银幕。惋惜是有依据的：以钢琴家郎朗少年成长经历为蓝本的《你行！你上！》，豆瓣评分稳定在6.7分。文汇报的评语写得克制：这一分数既未达到姜文过往《让子弹飞》《阳光灿烂的日子》等作品的口碑高度，也未跌入烂片行列——这种“撕裂感”恰是影片争议性的直接体现。

## 6.7分，是姜文导演作品里的最低分

口碑的另一面是票房。七年磨一剑的《你行！你上！》公映七天，累计票房仅为8200万左右，单日票房已经跌到第八名。影片豆瓣评分为6.7，是姜文所有导演作品中的最低（和《一步之遥》并列）。

“看不懂”“放飞自我”“爹味”的差评，不绝如缕。这三个词拼在一起，几乎就是这些年观众对姜文的全部怨言。

## 姜文的电影，从来不是在“讲故事”

《让子弹飞》是姜文作品序列里最好懂的一部，也是最被记住的一部。但从影片风格来看，姜文在《你行！你上！》中延续了其标志性的创作元素。影评人“钱德勒”说得形象：“（导演）自觉或不自觉地几乎将他前作的元素都包进馅儿里。”

比如天台这一意象，在《阳光灿烂的日子》《邪不压正》等作品中多次出现。华东师范大学传播学院副教授刘弢用“旋转木马式叙事”形容《你行！你上！》——“剪得狠、语速快、黑色幽默暗藏机锋”。这些招牌手艺都还在，可观众先累了。从《让子弹飞》的北洋乱世到《邪不压正》的北平风云，姜文始终擅长在历史褶皱中植入当代社会的镜像——他拍的不是故事，是自己的看法。《让子弹飞》之所以特别，是那一次他的看法和观众的情绪，撞在了同一个点上。

## 姜文没变，观众和时代变了

有一篇复盘文章的标题就是结论：姜文没变，观众和时代变了。

姜文这次其实“不装了”。澎湃号的影评说，姜文不玩隐喻，直接明“刚”；《你行！你上！》是一场荒诞现实主义的音乐狂想。可话说明白了，观众还是觉得拧巴。上观新闻的影评人把话说得更直：隐喻失效，姜文该重新认识自己了。

## 拧巴，是作者的另一种诚实

“重复多了，会给创作打上一个死结，而解开这个死结的唯一办法，就是成为自己的批判者。”这句话是影评人写给姜文的，也适合每一个被自己的代表作困住的人。

观众怀念《让子弹飞》，怀念的是那部把“爽”和“表达”同时给到位的电影。可那样的同频，在姜文的创作里更像一次巧合：爽，只是他的表达恰好撞上了观众的情绪，而不是他学会了讨好。

让子弹飞之后，姜文的电影一部比一部拧巴。拧巴的另一面，是他始终没学会骗自己——宁可让你看不懂，也不肯给你一份标准答案。

十多年来，庞大的影迷群体把《让子弹飞》盘到包浆，他们对片中的台词金句如数家珍。观众一边生气，一边等他下一部——这就是姜文和观众之间，永远解不开、又舍不得解开的结。这样的导演，观众会生气，但忘不掉。""",
    "art-002": """## 你的《还珠》，到第几部为止

在很多人心里，《还珠格格》只有两部。我们只承认《还珠格格》有两部——第三部，像是一部同名的另外一部剧。

最常被提起的原因是换演员。第一部和第二部非常经典，因为演员都没有更换，还是原来的演员，林心如赵薇范冰冰也都因为这部剧走红。到了第三部的时候，突然来了一次大换血，把主演们几乎全换了，这也让观众们无法适应，结果导致第三部的收视率非常差。

## 拒绝出演的人，比剧本身更有故事

赵薇当年给的说法是：“我不出演《还珠格格3》，琼瑶阿姨是非常失望的。我当时只想开拓自己，不想成为一部又一部戏的赚钱机器。”她还向琼瑶承诺，4年内不演电视剧，转向电影。

琼瑶把这次大换角称为“心头之痛”。而林心如当时接了《半生缘》，苏有朋则希望拓宽戏路——每个人都有自己的路要走，只是观众的记忆被留在了原地。

## 前两部，本来也是一场意外

回头翻《还珠》的选角故事，会发现这部神剧从一开始就不按剧本走：《还珠格格》本不受琼瑶重视；赵薇苏有朋第一天见面就拍吻戏；林心如差点被“退货”；尔康原属意吴奇隆；令妃被“骗”进剧组；皇阿玛在片场闲得遛鸟。

如果不是20年后的今天，观众对着第n次重播的《还珠格格》进行了新一轮的脑洞大开，就“皇后令妃到底谁更心机”、“容嬷嬷是假邪恶还是真忠心”这样的问题展开深度举证和讨论，这些细节不会被人反复咂摸。称霸童年回忆的《还珠》竟然深藏着如此多值得回味和推敲的细节。一部不被重视的剧，成了几代人的童年——这本身就是最大的意外。

## 我们“不承认”的，是被打开的童话

第三部的问题，不只是换人。有评论说，第三部剧情走向完全不同，人设完全崩塌；如果说前两部为观众创造了美好的爱情童话，第三部就是送给观众的一巴掌。

小燕子和永琪本来是一部甜到牙疼的甜宠文，两人的缘分从围场狩猎开始。前两部停在“从此幸福地生活在一起”；第三部剧情走向完全不同，人设完全崩塌，偏偏不肯停在原地。小燕子不再是从前的样子，故事也不再甜。观众不是不能接受生活的真相，是不能接受童年被剧透。后来翻拍的版本，仍然无法超越赵薇、林心如版本——新演员演得再用力，也补不上记忆里的那张脸。

## 记忆会分叉，但每个人的童年只有一部

我们只承认《还珠格格》有两部，不是因为第三部拍得差，而是因为前两部刚好停在了每个人最想停的地方。

记忆会分叉：有人觉得一二部才是完整的，有人坚持二三部才是结局。

前两部是暑假，是电视机前的全家；第三部像长大后的春节——人还是那些人，味道已经不是那个味道。不承认第三部，其实是不想承认童年结束了。但吵到最后，大家怀念的其实是同一段童年。""",
}



# --------------------------------------------------------------------------
# 6) Titles / source mapping / rules / briefs / content records
# --------------------------------------------------------------------------

TITLES = {
    "art-001": [
        ("《让子弹飞》之后，姜文为什么一部比一部拧巴", "导演比较"),
        ("姜文没变，变的是我们", "判断"),
        ("6.7分之后，姜文还是那个姜文吗", "评分"),
    ],
    "art-002": [
        ("《还珠格格》第三部为什么像另一部剧", "换角"),
        ("我们只承认《还珠格格》有两部", "集体记忆"),
        ("你的童年《还珠》，到哪一集结束", "记忆"),
    ],
}

SOURCE_IDS = {
    "art-001": ["src-wenwei-nixing", "src-sohu-jw", "src-thepaper-jianpian", "src-shobserver-han"],
    "art-002": ["src-sina-caidan", "src-sohu-huanzhu3", "src-163-huanzhu3", "src-yahoo-zhaowei", "src-360-huanzhu3"],
}

MODES = {"art-001": "reported_feature", "art-002": "reported_feature"}

RULE_CLAIMS = {
    "art-001": [
        {"claim_id": "c1", "claim_level": "event_exists", "source_refs": ["src-wenwei-nixing"], "source_locators": ["文汇报: 郎朗蓝本"]},
        {"claim_id": "c2", "claim_level": "event_exists", "source_refs": ["src-wenwei-nixing"], "source_locators": ["文汇报: 豆瓣6.7"]},
        {"claim_id": "c3", "claim_level": "mechanism", "source_refs": ["src-wenwei-nixing"], "source_locators": ["文汇报: 口碑高度"]},
        {"claim_id": "c4", "claim_level": "event_exists", "source_refs": ["src-sohu-jw"], "source_locators": ["影吹斯汀: 七天8200万"]},
    ],
    "art-002": [
        {"claim_id": "c1", "claim_level": "event_exists", "source_refs": ["src-sina-caidan"], "source_locators": ["新浪娱乐: 本不受重视"]},
        {"claim_id": "c2", "claim_level": "event_exists", "source_refs": ["src-sohu-huanzhu3"], "source_locators": ["搜狐号: 大换血"]},
        {"claim_id": "c3", "claim_level": "mechanism", "source_refs": ["src-163-huanzhu3"], "source_locators": ["网易订阅: 心头之痛"]},
        {"claim_id": "c4", "claim_level": "mechanism", "source_refs": ["src-360-huanzhu3"], "source_locators": ["橘子娱乐: 童话与巴掌"]},
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
candidate_id: cand-jiangwen-divide-001
article_mode: reported_feature
required_source_roles: [media_report]
topic_version: 1
content_map: C
reference_shape: viewing_commentary
core_question: 为什么《一步之遥》《邪不压正》都达不到《让子弹飞》的高度
target_reader: 看过《让子弹飞》、在姜文新片口碑里找不到当年感觉的观众
editorial_angle: 姜文没变，观众和时代变了——《你行！你上！》的6.7分与8200万，把这场错位摆上了台面
body_route: 从反复被问的老问题进入，用《你行！你上！》的口碑票房当最新数据点，落到"爽与表达的同频只是巧合"的判断
evidence_boundary: 只写四份来源中的作品信息、评分票房与影评观点；不写来源之外的剧情细节与票房精确值
required_hard_information: 《你行！你上！》郎朗蓝本、暌违七年；豆瓣6.7（与《一步之遥》并列导演作品最低）；公映七天累计票房8200万左右；文汇报称未达《让子弹飞》《阳光灿烂的日子》口碑高度
unsupported_boundary: 不能替观众下整体结论，不写姜文本人未公开表态，不把"热榜第几"写成事实
""",
    "art-002": """# Writing Brief

production_contract: article-first-v1
brief_contract: writing-brief-v2
title_contract: title-pack-v1
legacy_compatibility: false
run_contract_required: true
article_id: art-002
candidate_id: cand-huanzhu-memory-001
article_mode: reported_feature
required_source_roles: [media_report]
topic_version: 1
content_map: B
reference_shape: viewing_commentary
core_question: 为什么我们只承认《还珠格格》有两部
target_reader: 被《还珠》前两部占据过童年、对第三部选择性失忆的观众
editorial_angle: 第三部大换血只是导火索——观众不承认的，是前两部刚停在了每个人最想停的地方
body_route: 从"你的还珠到第几部为止"的记忆问题进入，写换角史实与拒绝出演者的说法，再写前两部的意外，最后落到记忆分叉
evidence_boundary: 只写五份来源中的选角史实、换角说法与评论观点；不写来源之外的剧情细节
required_hard_information: 第三部主演大换血、观众无法适应、收视率差；赵薇拒演并承诺4年不演电视剧；琼瑶称大换角是“心头之痛”；《还珠》本不受琼瑶重视与选角细节
unsupported_boundary: 不能替观众下整体结论，不写演员现状与近况，不把"热榜第几"写成事实
""",
}

BRIEF_SPECS = [
    (
        "art-001",
        "reported_feature",
        "media_report",
        "为什么《一步之遥》《邪不压正》都达不到《让子弹飞》的高度",
        "src-wenwei-nixing",
    ),
    (
        "art-002",
        "reported_feature",
        "media_report",
        "为什么我们只承认《还珠格格》有两部",
        "src-sina-caidan",
    ),
]

CONTENT_RECORD_ARGS = [
    {
        "aid": "art-001",
        "mode": "reported_feature",
        "role": "media_report",
        "core_object": "姜文电影口碑票房的分化与观众错位",
        "question": "为什么《一步之遥》《邪不压正》都达不到《让子弹飞》的高度",
        "mechanism": "让子弹飞的爽与表达只是短暂同频；此后观众要爽、姜文要表达，错位越拉越大",
        "takeaway": "让子弹飞之后，姜文的电影一部比一部拧巴；拧巴的另一面，是他始终没学会骗自己。",
        "hard": [
            {"information_id": "i1", "text": "以钢琴家郎朗少年成长经历为蓝本，姜文新作《你行！你上！》正式登陆全国院线", "kind": "specific_context", "body_locator": "p1", "source_refs": ["src-wenwei-nixing"], "source_locators": ["文汇报: 郎朗蓝本"], "independence_key": "langlang"},
            {"information_id": "i2", "text": "姜文导演暌违七年的新作《你行！你上！》正式登陆全国院线", "kind": "specific_context", "body_locator": "p1", "source_refs": ["src-wenwei-nixing"], "source_locators": ["文汇报: 暌违七年"], "independence_key": "seven-years"},
            {"information_id": "i3", "text": "截至7月21日，《你行！你上！》该片豆瓣评分稳定在6.7分", "kind": "fact", "body_locator": "p1", "source_refs": ["src-wenwei-nixing"], "source_locators": ["文汇报: 豆瓣6.7"], "independence_key": "douban-67"},
            {"information_id": "i4", "text": "这一分数既未达到姜文过往《让子弹飞》《阳光灿烂的日子》等作品的口碑高度，也未跌入烂片行列", "kind": "mechanism", "body_locator": "p1", "source_refs": ["src-wenwei-nixing"], "source_locators": ["文汇报: 口碑高度"], "independence_key": "height"},
            {"information_id": "i5", "text": "《你行！你上！》公映七天，累计票房仅为8200万左右，单日票房已经跌到第八名", "kind": "fact", "body_locator": "p2", "source_refs": ["src-sohu-jw"], "source_locators": ["影吹斯汀: 七天8200万"], "independence_key": "box-office"},
            {"information_id": "i6", "text": "影片豆瓣评分为6.7，是姜文所有导演作品中的最低（和《一步之遥》并列）", "kind": "mechanism", "body_locator": "p2", "source_refs": ["src-sohu-jw"], "source_locators": ["影吹斯汀: 最低分"], "independence_key": "lowest"},
            {"information_id": "i7", "text": "姜文没变，观众和时代变了", "kind": "mechanism", "body_locator": "p3", "source_refs": ["src-sohu-jw"], "source_locators": ["影吹斯汀: 标题判断"], "independence_key": "unchanged"},
            {"information_id": "i8", "text": "从《让子弹飞》的北洋乱世到《邪不压正》的北平风云，姜文始终擅长在历史褶皱中植入当代社会的镜像", "kind": "mechanism", "body_locator": "p3", "source_refs": ["src-thepaper-jianpian"], "source_locators": ["澎湃: 历史褶皱"], "independence_key": "mirror"},
            {"information_id": "i9", "text": "隐喻失效，姜文该重新认识自己了", "kind": "mechanism", "body_locator": "p3", "source_refs": ["src-shobserver-han"], "source_locators": ["上观新闻: 重新认识自己"], "independence_key": "relearn"},
            {"information_id": "i10", "text": "重复多了，会给创作打上一个死结，而解开这个死结的唯一办法，就是成为自己的批判者", "kind": "mechanism", "body_locator": "p4", "source_refs": ["src-shobserver-han"], "source_locators": ["上观新闻: 死结"], "independence_key": "knot"},
            {"information_id": "i11", "text": "影评人“钱德勒”撰文写道：“（导演）自觉或不自觉地几乎将他前作的元素都包进馅儿里。”", "kind": "fact", "body_locator": "p3", "source_refs": ["src-wenwei-nixing"], "source_locators": ["文汇报: 钱德勒"], "independence_key": "qiande"},
            {"information_id": "i12", "text": "比如天台这一意象，在《阳光灿烂的日子》《邪不压正》等作品中多次出现", "kind": "specific_context", "body_locator": "p3", "source_refs": ["src-wenwei-nixing"], "source_locators": ["文汇报: 天台意象"], "independence_key": "rooftop"},
            {"information_id": "i13", "text": "十多年来，庞大的影迷群体把《让子弹飞》盘到包浆，他们对片中的台词金句如数家珍", "kind": "fact", "body_locator": "p5", "source_refs": ["src-sohu-jw"], "source_locators": ["影吹斯汀: 盘到包浆"], "independence_key": "quotes"},
        ],
        "bases": [
            {"locator": "p2", "fact_or_scene": "6.7分与8200万", "explanation": "票房口碑双数据把错位置于台面"},
            {"locator": "p3", "fact_or_scene": "北洋乱世到北平风云", "explanation": "姜文一贯拍想法不拍故事，错位有迹可循"},
        ],
        "boundary": "不写来源之外的票房精确值、剧情细节与姜文本人未公开表态；不把热榜信号写成事实。",
        "source_ids": ["src-wenwei-nixing", "src-sohu-jw", "src-thepaper-jianpian", "src-shobserver-han"],
    },
    {
        "aid": "art-002",
        "mode": "reported_feature",
        "role": "media_report",
        "core_object": "《还珠格格》第三部的换角史与观众集体记忆的分叉",
        "question": "为什么我们只承认《还珠格格》有两部",
        "mechanism": "前两部的圆满停在观众最想停的地方，第三部把婚后的日子翻开——记忆因此分叉",
        "takeaway": "我们只承认《还珠格格》有两部，不是因为第三部拍得差，而是因为前两部刚好停在了每个人最想停的地方。",
        "hard": [
            {"information_id": "i1", "text": "《还珠格格》本不受琼瑶重视", "kind": "fact", "body_locator": "p3", "source_refs": ["src-sina-caidan"], "source_locators": ["新浪娱乐: 本不受重视"], "independence_key": "unexpected"},
            {"information_id": "i2", "text": "赵薇苏有朋第一天见面就拍吻戏", "kind": "fact", "body_locator": "p3", "source_refs": ["src-sina-caidan"], "source_locators": ["新浪娱乐: 拍吻戏"], "independence_key": "first-kiss"},
            {"information_id": "i3", "text": "林心如差点被“退货”", "kind": "fact", "body_locator": "p3", "source_refs": ["src-sina-caidan"], "source_locators": ["新浪娱乐: 退货"], "independence_key": "returned"},
            {"information_id": "i4", "text": "尔康原属意吴奇隆", "kind": "fact", "body_locator": "p3", "source_refs": ["src-sina-caidan"], "source_locators": ["新浪娱乐: 尔康人选"], "independence_key": "erkang"},
            {"information_id": "i5", "text": "令妃被“骗”进剧组", "kind": "fact", "body_locator": "p3", "source_refs": ["src-sina-caidan"], "source_locators": ["新浪娱乐: 令妃"], "independence_key": "lingfei"},
            {"information_id": "i6", "text": "皇阿玛在片场闲得遛鸟", "kind": "fact", "body_locator": "p3", "source_refs": ["src-sina-caidan"], "source_locators": ["新浪娱乐: 遛鸟"], "independence_key": "niao"},
            {"information_id": "i7", "text": "如果不是20年后的今天，观众对着第n次重播的《还珠格格》进行了新一轮的脑洞大开", "kind": "fact", "body_locator": "p3", "source_refs": ["src-sina-caidan"], "source_locators": ["新浪娱乐: 重播"], "independence_key": "rerun"},
            {"information_id": "i8", "text": "但是到了第三部的时候，突然来了一次大换血，把主演们几乎全换了", "kind": "fact", "body_locator": "p1", "source_refs": ["src-sohu-huanzhu3"], "source_locators": ["搜狐号: 大换血"], "independence_key": "swap"},
            {"information_id": "i9", "text": "这也让观众们无法适应", "kind": "mechanism", "body_locator": "p1", "source_refs": ["src-sohu-huanzhu3"], "source_locators": ["搜狐号: 无法适应"], "independence_key": "unfit"},
            {"information_id": "i10", "text": "结果导致第三部的收视率非常差", "kind": "mechanism", "body_locator": "p1", "source_refs": ["src-sohu-huanzhu3"], "source_locators": ["搜狐号: 收视率"], "independence_key": "ratings"},
            {"information_id": "i11", "text": "我不出演《还珠格格3》，琼瑶阿姨是非常失望的。我当时只想开拓自己，不想成为一部又一部戏的赚钱机器。", "kind": "fact", "body_locator": "p2", "source_refs": ["src-163-huanzhu3"], "source_locators": ["网易订阅: 赵薇说法"], "independence_key": "zhaowei-quote"},
            {"information_id": "i12", "text": "琼瑶表示，《还珠格格》经历这样的大换角，是她的心头之痛", "kind": "mechanism", "body_locator": "p2", "source_refs": ["src-163-huanzhu3"], "source_locators": ["网易订阅: 心头之痛"], "independence_key": "heartache"},
            {"information_id": "i13", "text": "当时，林心如接了《半生缘》，而苏有朋则希望拓宽戏路", "kind": "fact", "body_locator": "p2", "source_refs": ["src-163-huanzhu3"], "source_locators": ["网易订阅: 各自选择"], "independence_key": "choices"},
            {"information_id": "i14", "text": "趙薇還向瓊瑤承諾4年內不演電視劇，選擇轉向電影方向去發展", "kind": "fact", "body_locator": "p2", "source_refs": ["src-yahoo-zhaowei"], "source_locators": ["Yahoo奇摩: 承诺4年"], "independence_key": "promise-4y"},
            {"information_id": "i15", "text": "第三部剧情走向完全不同，人设完全崩塌", "kind": "mechanism", "body_locator": "p4", "source_refs": ["src-360-huanzhu3"], "source_locators": ["橘子娱乐: 人设崩塌"], "independence_key": "collapse"},
            {"information_id": "i16", "text": "如果说前两部为观众创造了美好的爱情童话，第三部就是送给观众的一巴掌", "kind": "mechanism", "body_locator": "p4", "source_refs": ["src-360-huanzhu3"], "source_locators": ["橘子娱乐: 童话与巴掌"], "independence_key": "slap"},
            {"information_id": "i17", "text": "第一部和第二部非常经典，因为演员都没有更换，还是原来的演员，林心如赵薇范冰冰也都因为这部剧走红", "kind": "fact", "body_locator": "p1", "source_refs": ["src-sohu-huanzhu3"], "source_locators": ["搜狐号: 一二部经典"], "independence_key": "classic-12"},
            {"information_id": "i18", "text": "并就“皇后令妃到底谁更心机”、“容嬷嬷是假邪恶还是真忠心”等一系列神奇的问题展开深度举证和讨论", "kind": "fact", "body_locator": "p3", "source_refs": ["src-sina-caidan"], "source_locators": ["新浪娱乐: 重播讨论"], "independence_key": "debate"},
            {"information_id": "i19", "text": "小燕子和永琪本来是一部甜到牙疼的甜宠文，两人的缘分从围场狩猎开始", "kind": "relationship", "body_locator": "p4", "source_refs": ["src-360-huanzhu3"], "source_locators": ["橘子娱乐: 围场狩猎"], "independence_key": "hunting"},
        ],
        "bases": [
            {"locator": "p1", "fact_or_scene": "第三部大换血与收视率差", "explanation": "记忆分叉的第一个事实层"},
            {"locator": "p3", "fact_or_scene": "选角意外史", "explanation": "前两部的圆满本来就是意外，第三部才是常态"},
        ],
        "boundary": "不写来源之外的剧情细节与演员现状；不把热榜信号写成事实。",
        "source_ids": ["src-sina-caidan", "src-sohu-huanzhu3", "src-163-huanzhu3", "src-yahoo-zhaowei", "src-360-huanzhu3"],
    },
]

BATCH_SPECS = {
    "art-001": (
        "cand-jiangwen-divide-001",
        "姜文电影",
        "jiangwen-film-divide",
        ["src-wenwei-nixing", "src-sohu-jw", "src-thepaper-jianpian", "src-shobserver-han"],
        "A",
        "C",
    ),
    "art-002": (
        "cand-huanzhu-memory-001",
        "还珠格格",
        "huanzhu-part3-memory-split",
        ["src-sina-caidan", "src-sohu-huanzhu3", "src-163-huanzhu3", "src-yahoo-zhaowei", "src-360-huanzhu3"],
        "B",
        "B",
    ),
}


if __name__ == "__main__":
    import sys as _sys

    from scripts.daily_engine import build_run

    build_run(_sys.modules[__name__])
