#!/usr/bin/env python3
"""SQLite 数据库与存储层 (topic_pool/topics.db)
管理 events、snapshots 与常青兜底池 evergreen_seeds。
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

DB_PATH = Path("/home/allen/Projects/ruoyu-film-daily/topic_pool/topics.db")

SCHEMA_SQL = """
-- 1. 事件主表
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    canonical_title TEXT NOT NULL,
    core_entities TEXT NOT NULL,               -- JSON array
    first_seen_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    seen_count INTEGER DEFAULT 1,
    cross_platform_count INTEGER DEFAULT 1,
    platforms_involved TEXT NOT NULL,          -- JSON array
    
    -- 生命周期与状态
    lifecycle_stage TEXT NOT NULL DEFAULT 'cold',
    status TEXT NOT NULL DEFAULT 'pending',    -- 'pending' | 'selected' | 'rejected'
    status_updated_at INTEGER NOT NULL,
    cooldown_until INTEGER DEFAULT 0,
    
    -- 微信母体打分与切入点
    safety_tier TEXT NOT NULL DEFAULT 'GREEN', -- 'GREEN' | 'YELLOW' | 'RED'
    safety_reason TEXT,
    resonance_archetype TEXT,
    resonance_score INTEGER DEFAULT 0,
    story_tension_score INTEGER DEFAULT 0,
    overall_score INTEGER DEFAULT 0,
    
    proposed_angle TEXT,
    ledger_summary TEXT,
    published_decay_penalty INTEGER DEFAULT 0,
    penalty_reason TEXT,
    raw_clustering_data TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_recommendation 
ON events(status, cooldown_until, safety_tier, overall_score DESC);

CREATE INDEX IF NOT EXISTS idx_events_lifecycle 
ON events(lifecycle_stage, overall_score DESC);

-- 2. 排名轨迹快照表
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    batch_time INTEGER NOT NULL,
    platform TEXT NOT NULL,
    platform_tier TEXT NOT NULL,               -- 'S' | 'A' | 'B'
    rank_position INTEGER NOT NULL,
    raw_title TEXT NOT NULL,
    url TEXT,
    raw_hot_label TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY(event_id) REFERENCES events(event_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_snapshots_event_batch 
ON snapshots(event_id, batch_time DESC);

CREATE INDEX IF NOT EXISTS idx_snapshots_batch_platform 
ON snapshots(batch_time, platform, rank_position ASC);

-- 3. 常青母题种子/兜底表 (保证推荐3黄金阵型永不落空)
CREATE TABLE IF NOT EXISTS evergreen_seeds (
    seed_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    core_entities TEXT NOT NULL,               -- JSON array
    archetype TEXT NOT NULL,
    ledger_summary TEXT NOT NULL,
    proposed_angle TEXT NOT NULL,
    reference_url TEXT,
    score INTEGER DEFAULT 85,
    status TEXT DEFAULT 'pending',            -- 'pending' | 'selected' | 'rejected'
    cooldown_until INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL
);

-- 4. 历史已发表文章台账表 (落实时间衰减动态负分机制)
CREATE TABLE IF NOT EXISTS published_topics (
    published_id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    core_entities TEXT NOT NULL,               -- JSON array
    published_date TEXT NOT NULL,              -- YYYY-MM-DD
    published_at INTEGER NOT NULL,             -- unix epoch
    total_reads INTEGER DEFAULT 0,
    rec_reads INTEGER DEFAULT 0,
    note TEXT,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_published_topics_date 
ON published_topics(published_at DESC);
"""

# 初始预置高分常青母题种子（覆盖 4 大核心母题：戏骨风骨 vs 内娱遮羞布、灵气演员困境、硬核神作打脸烂片）
INITIAL_EVERGREEN_SEEDS = [
    {
        "seed_id": "evg_wangjinsong",
        "title": "戏骨王劲松手抄30万字台词怒斥‘背台词成了敬业’",
        "core_entities": ["王劲松", "大明王朝1566", "破冰行动", "老戏骨", "手抄台词"],
        "archetype": "A_actor_integrity",
        "ledger_summary": "为演好杨金水手抄全剧台词，公开痛斥内娱‘背台词居然成了炫耀资本’，算透老艺人坚守职业底线的代价。",
        "proposed_angle": "什么时候当演员连背台词都要全网买通稿吹敬业了？王劲松这一刀，直接扯下了流量明星靠提词器和配音招摇撞骗的整张脸皮。",
        "reference_url": "📚 [常青种子库 · 选定后自动启动人物全网信源深挖]",
        "score": 92,
    },
    {
        "seed_id": "evg_fudalong",
        "title": "最穷双料影帝富大龙送外卖也不接烂戏的硬骨头",
        "core_entities": ["富大龙", "大秦帝国", "天狗", "双料影帝", "最穷影帝"],
        "archetype": "B_talent_dilemma",
        "ledger_summary": "拿过金鸡华表双料影帝，无戏可拍时宁可当送水工、当外卖员，也坚决不接粗制滥造的商业烂广告与神剧。",
        "proposed_angle": "内娱天天喊穷的小花小生随手一套千万豪宅，真正的双料影帝却在租房买菜；演艺圈劣币驱逐良币的账，到底该谁来还？",
        "reference_url": "📚 [常青种子库 · 选定后自动启动人物全网信源深挖]",
        "score": 91,
    },
    {
        "seed_id": "evg_jinshijie",
        "title": "剧场教父金士杰60岁为养龙凤胎低头接商业片",
        "core_entities": ["金士杰", "暗恋桃花源", "绣春刀", "兰陵王", "剧场老戏骨"],
        "archetype": "A_actor_integrity",
        "ledger_summary": "台湾剧场界灵魂人物前大半生视金钱如粪土，60岁老来得子，为了奶粉钱与学费开始北上频繁客串古偶与商业片。",
        "proposed_angle": "大半辈子高风亮节的剧场教父，最终也要为了两份奶粉钱向商业片低头；现实账本从不放过任何人，但他在烂片里的几分钟依然能把主角秒成渣。",
        "reference_url": "📚 [常青种子库 · 选定后自动启动人物全网信源深挖]",
        "score": 89,
    },
    {
        "seed_id": "evg_lixuejian",
        "title": "70岁李雪健抗癌20年失声却含水拍戏的演员底色",
        "core_entities": ["李雪健", "焦裕禄", "水浒传", "封神", "抗癌"],
        "archetype": "A_actor_integrity",
        "ledger_summary": "患鼻咽癌20年听力严重受损，拍《封神》时说话吃力，却依然拒绝配音、含水润喉坚持真声实拍，痛批天价片酬买不来好戏。",
        "proposed_angle": "听不见、发音吃力，还要被剧组劝用配音；李雪健偏要戴着助听器真声撕扯，让那些靠脸替身拿几千万的内娱少爷小姐无地自容。",
        "reference_url": "📚 [常青种子库 · 选定后自动启动人物全网信源深挖]",
        "score": 93,
    },
    {
        "seed_id": "evg_haolei",
        "title": "无冕影后郝蕾敢怒斥‘假演员’与内娱流水线戏疯子",
        "core_entities": ["郝蕾", "颐和园", "少年天子", "演技", "戏疯子"],
        "archetype": "B_talent_dilemma",
        "ledger_summary": "有华语顶级大满贯级别的灵气与天赋，却因拒绝讨好圈子、拒绝公关营销，在最黄金的年龄沦为综艺评委和配角。",
        "proposed_angle": "她曾说‘我是一只鹰，你非要把我关在笼子里跟小鸡抢食’；郝蕾的困境不是接不到戏，是当下的内娱根本配不上这种狂妄的真才华。",
        "reference_url": "📚 [常青种子库 · 选定后自动启动人物全网信源深挖]",
        "score": 90,
    },
    {
        "seed_id": "evg_xinzhirei",
        "title": "把想红写在脸上的辛芷蕾：底层野心家十年龙套的狠劲",
        "core_entities": ["辛芷蕾", "繁花", "李李", "野心", "十年龙套"],
        "archetype": "A_actor_integrity",
        "ledger_summary": "因父亲瘫痪早早扛起家庭生计，公开坦言‘我就想红就想挣钱’，在各种恶毒女配里摸爬滚打十年，最终在王家卫镜头下杀出血路。",
        "proposed_angle": "比起内娱那些一边买通稿立佛系人设、一边暗度陈仓撕番位的小花，辛芷蕾这种把欲望写在脸上、用演技当刀的狠角色，才真正配得上掌声。",
        "reference_url": "📚 [常青种子库 · 选定后自动启动人物全网信源深挖]",
        "score": 88,
    },
    {
        "seed_id": "evg_yongmei",
        "title": "49岁柏林封后咏梅：不要修掉我的皱纹",
        "core_entities": ["咏梅", "地久天长", "柏林影后", "白幼瘦", "中年女演员"],
        "archetype": "B_talent_dilemma",
        "ledger_summary": "沉寂多年半隐退状态，49岁凭借《地久天长》夺下柏林影后，公开在金鸡奖呼吁修图师‘不要修掉我的皱纹，那是我好不容易长出来的’。",
        "proposed_angle": "当整个内娱还在沉迷50岁演少女、滤镜磨皮磨掉鼻梁骨的畸形审美时，咏梅脸上的每一条沟壑，都在无情嘲讽这种白幼瘦虚假狂欢。",
        "reference_url": "📚 [常青种子库 · 选定后自动启动人物全网信源深挖]",
        "score": 89,
    },
    {
        "seed_id": "evg_wangchuanjun",
        "title": "出走爱情公寓被骂白眼狼：王传君撕开工业喜剧遮羞布",
        "core_entities": ["王传君", "我不是药神", "爱情公寓", "默杀", "抄袭"],
        "archetype": "A_actor_integrity",
        "ledger_summary": "当年拒绝续演《爱情公寓》被全网网暴‘忘恩负义’，自断生路卡里剩100万失眠，最终在《药神》里靠每天跳绳8000个熬出吕受益。",
        "proposed_angle": "当年所有人都骂他清高砸饭碗，如今回头再看，他跳出的是内娱最大的抄袭工业流水线，砸碎的是假演员躺着数钱的懒骨头。",
        "reference_url": "📚 [常青种子库 · 选定后自动启动人物全网信源深挖]",
        "score": 90,
    },
    {
        "seed_id": "evg_linbaoyi",
        "title": "TVB视帝林保怡租房度日与《白日之下》绝望残暴",
        "core_entities": ["林保怡", "白日之下", "金枝欲孽", "TVB视帝", "港剧戏骨"],
        "archetype": "A_actor_integrity",
        "ledger_summary": "两届TVB当家视帝，晚年在香港依然买不起豪车豪宅，过着普通街坊生活；60岁零片酬支持新导演，演出影史最绝望的残疾院舍院长。",
        "proposed_angle": "内娱十八线偶像保镖开道、住上亿豪宅，TVB顶流视帝出门坐地铁、菜市场买葱；两相对比，才明白什么叫真正的职业演员，什么叫资本寄生虫。",
        "reference_url": "📚 [常青种子库 · 选定后自动启动人物全网信源深挖]",
        "score": 91,
    },
    {
        "seed_id": "evg_daming1566",
        "title": "收视滑铁卢到9.8分封神：《大明王朝1566》打脸古偶",
        "core_entities": ["大明王朝1566", "刘和平", "陈宝国", "黄志忠", "历史剧巅峰"],
        "archetype": "C_hardcore_masterpiece",
        "ledger_summary": "2007年湖南卫视首播收视惨遭滑铁卢被迫腰斩，编剧刘和平字字泣血算透嘉靖王朝财政账本，10年后在网络被奉为无上神作。",
        "proposed_angle": "当年全网喊着看不懂、嫌弃节奏慢，如今在充斥着恋爱脑与五毛特效的古偶时代，才猛然发现：早在十七年前，中国电视剧就已经抵达过世界级的高度。",
        "reference_url": "📚 [常青种子库 · 选定后自动启动人物全网信源深挖]",
        "score": 92,
    },
    {
        "seed_id": "evg_shibingtuji",
        "title": "不请大牌无一女性角色：《士兵突击》凭真诚封神20年",
        "core_entities": ["士兵突击", "王宝强", "张译", "段奕宏", "康洪雷"],
        "archetype": "C_hardcore_masterpiece",
        "ledger_summary": "筹备时无人看好，全剧没有大牌明星、没有一个恋爱女性角色，靠一帮灰头土脸的粗粝汉子，拍出了中国军旅剧前无古人的滚烫灵魂。",
        "proposed_angle": "如今动辄砸两三个亿请流量、疯狂塞工业糖精男女对视慢动作，二十年前那群趴在泥水里啃压缩饼干的汉子，早已把当下的国剧工业底裤扒得干干净净。",
        "reference_url": "📚 [常青种子库 · 选定后自动启动人物全网信源深挖]",
        "score": 91,
    },
    {
        "seed_id": "evg_tian_hua",
        "title": "96岁老艺术家田华全家四人患癌坚决不接烂广告",
        "core_entities": ["田华", "白毛女", "老艺术家", "患癌拒广告"],
        "archetype": "A_actor_integrity",
        "ledger_summary": "家中老伴与子媳相继患癌，沉重医疗开销压身，曾有人出百万请她代言虚假保健品被严词拒绝，宁可微薄主持走穴也不卖晚节。",
        "proposed_angle": "面对全家四张绝症医药费账单，百万虚假广告费递到眼前她一把推开；老一辈手艺人刻在骨子里的清白，比多少亿票房都值钱。",
        "reference_url": "📚 [常青种子库 · 选定后自动启动人物全网信源深挖]",
        "score": 88,
    },
    {
        "seed_id": "evg_youbenchang",
        "title": "老戏骨游本昌半生沉浮与90岁繁花再度封神",
        "core_entities": ["游本昌", "繁花", "济公", "爷叔"],
        "archetype": "A_actor_integrity",
        "ledger_summary": "52岁演济公爆红后沉寂数十年，自掏腰包赔光积蓄办话剧团，90岁坐轮椅演爷叔，算透演员一生对戏的痴与命的代价。",
        "proposed_angle": "五十岁演济公，九十岁演爷叔，中间亏光家当沉寂三十年——他用一辈子证明，不随波逐流的戏骨到底要熬过多少常人受不住的账本。",
        "reference_url": "📚 [常青种子库 · 选定后自动启动人物全网信源深挖]",
        "score": 90,
    }
]

# 近 30 天历史已发表文章台账（用于动态时间衰减负分算法，杜绝近期撞题，但保留老话题新爆发的重估空间）
INITIAL_PUBLISHED_TOPICS = [
    {
        "title": "演了79个龙套，80岁卖房破产：93岁游本昌走了，扯下了整个内娱的遮羞布",
        "core_entities": ["游本昌", "济公", "繁花", "爷叔", "龙套", "卖房破产"],
        "published_date": "2026-09-24",
        "total_reads": 53391,
        "rec_reads": 51690,
        "note": "爆款TOP1 (推荐占比96.8%)"
    },
    {
        "title": "14岁拿金马的天才少女，为什么在内娱接不到好戏了？",
        "core_entities": ["文淇", "血观音", "嘉年华", "金马奖", "天才少女", "接不到戏"],
        "published_date": "2026-09-22",
        "total_reads": 51073,
        "rec_reads": 49926,
        "note": "爆款TOP2 (推荐占比97.8%)"
    },
    {
        "title": "不请巨星不玩情怀，20年烂片IP怎么又拍爽了",
        "core_entities": ["生化危机", "烂片IP", "丧尸片", "保罗安德森", "米拉乔沃维奇"],
        "published_date": "2026-10-07",
        "total_reads": 36904,
        "rec_reads": 35517,
        "note": "爆款TOP3 (推荐占比96.2%)"
    },
    {
        "title": "连咽口饭都要买通稿，内娱到底被谁惯成了这副虚相？",
        "core_entities": ["内娱吃戏", "买通稿", "假吃", "假演", "通稿", "虚相"],
        "published_date": "2026-10-13",
        "total_reads": 16975,
        "rec_reads": 16069,
        "note": "爆款TOP4 (推荐占比94.7%)"
    },
    {
        "title": "七年前的老片！为什么成了中秋档最热的一部",
        "core_entities": ["中秋档", "老片重映", "老片", "中秋档票房"],
        "published_date": "2026-09-22",
        "total_reads": 10194,
        "rec_reads": 9497,
        "note": "爆款TOP5 (推荐占比93.2%)"
    },
    {
        "title": "施奈德为什么说《300勇士》是影史最GAY的电影",
        "core_entities": ["300勇士", "扎克施奈德", "施奈德", "斯巴达"],
        "published_date": "2026-09-18",
        "total_reads": 3565,
        "rec_reads": 3206,
        "note": "类型片深拆"
    },
    {
        "title": "刘欢走了：《甄嬛传》最传奇的原声带，终于在天堂重聚了",
        "core_entities": ["刘欢", "甄嬛传", "原声带", "姚贝娜"],
        "published_date": "2026-09-26",
        "total_reads": 1336,
        "rec_reads": 0,
        "note": "影视音乐纪念"
    },
    {
        "title": "23岁带3子逃离豪门：被全网笑了15年的“弃妇”，如今38岁成了最硬的赢家！",
        "core_entities": ["梁洛施", "李泽楷", "豪门", "弃妇"],
        "published_date": "2026-09-28",
        "total_reads": 675,
        "rec_reads": 0,
        "note": "名利场豪门"
    },
    {
        "title": "击败于和伟拿下飞天视帝：杨幂的班长熬了20年才被看见",
        "core_entities": ["飞天奖", "飞天视帝", "于和伟", "杨幂班长", "张译", "实力派"],
        "published_date": "2026-10-10",
        "total_reads": 650,
        "rec_reads": 0,
        "note": "视帝颁奖"
    },
    {
        "title": "一张票卖到50块，2026最寒酸国庆档，终于把中国观众惹毛了",
        "core_entities": ["国庆档", "票价50", "最寒酸国庆档", "电影票价", "档期冷清"],
        "published_date": "2026-10-01",
        "total_reads": 579,
        "rec_reads": 0,
        "note": "档期观察"
    },
    {
        "title": "全网狂搜的“19禁床戏”！孙艺珍首演恶女",
        "core_entities": ["孙艺珍", "恶女", "19禁", "韩国电影", "大尺度"],
        "published_date": "2026-09-23",
        "total_reads": 559,
        "rec_reads": 0,
        "note": "海外影视"
    },
    {
        "title": "手握战狼李焕英200亿，砸3亿拍敦煌英雄，亏得公司都没了！",
        "core_entities": ["敦煌英雄", "战狼", "李焕英", "亏3亿", "北京文化", "影视投资"],
        "published_date": "2026-10-02",
        "total_reads": 556,
        "rec_reads": 0,
        "note": "影视投资败局"
    },
    {
        "title": "砸1.5亿又扑街：古天乐7连扑背后，这个救市劳模终于撑不住了",
        "core_entities": ["古天乐", "7连扑", "救市劳模", "香港电影", "港片困局"],
        "published_date": "2026-10-04",
        "total_reads": 509,
        "rec_reads": 0,
        "note": "港片巨星困局"
    },
    {
        "title": "当年被全网骂自私小气，17年后观众为什么都替小贝庆幸了？",
        "core_entities": ["蜗居", "小贝", "海藻", "宋思明", "房价"],
        "published_date": "2026-10-06",
        "total_reads": 486,
        "rec_reads": 0,
        "note": "经典国剧重审"
    },
    {
        "title": "当年吹空调抠图拿8000万，如今全剧跌到100万：内娱“假大女主”们，终于被打回原形！",
        "core_entities": ["抠图8000万", "假大女主", "天价片酬", "杨颖", "Angelababy", "抠图"],
        "published_date": "2026-09-25",
        "total_reads": 471,
        "rec_reads": 0,
        "note": "内娱片酬虚火"
    },
    {
        "title": "蔡康永微博清空、全网封杀！深扒他那段不为人知的家族史，果然不简单啊……",
        "core_entities": ["蔡康永", "康熙来了", "家族史", "封杀", "清空微博"],
        "published_date": "2026-10-15",
        "total_reads": 387,
        "rec_reads": 0,
        "note": "台娱艺人"
    },
    {
        "title": "梅艳芳骨灰被盗失踪3个月：一代天后斗不过吸血鬼至亲",
        "core_entities": ["梅艳芳", "遗产", "骨灰", "吸血鬼至亲", "梅妈"],
        "published_date": "2026-10-11",
        "total_reads": 367,
        "rec_reads": 0,
        "note": "港娱往事"
    },
    {
        "title": "4天被转卖3次：演员王星被拐妙瓦底背后，底层戏疯子有多难？",
        "core_entities": ["王星", "妙瓦底", "演员被拐", "底层戏疯子", "群演"],
        "published_date": "2026-10-08",
        "total_reads": 326,
        "rec_reads": 0,
        "note": "底层演员生存"
    },
    {
        "title": "抱着看烂片的心态进场，结果小沈阳夫妇这部喜剧，把全场给笑疯了",
        "core_entities": ["小沈阳", "沈春阳", "喜剧片", "小沈阳夫妇", "国庆档喜剧"],
        "published_date": "2026-10-03",
        "total_reads": 223,
        "rec_reads": 0,
        "note": "喜剧片黑马"
    },
    {
        "title": "两夺金扫帚后押上妻子翻盘，小沈阳在国庆档赌什么？",
        "core_entities": ["小沈阳", "金扫帚", "国庆档", "沈春阳", "喜剧转型"],
        "published_date": "2026-09-30",
        "total_reads": 195,
        "rec_reads": 0,
        "note": "喜剧人转型"
    },
    {
        "title": "六公主重播《楚门的世界》：18年后，全网都在抢着当群演",
        "core_entities": ["楚门的世界", "六公主", "重播", "金凯瑞", "群演"],
        "published_date": "2026-10-09",
        "total_reads": 229,
        "rec_reads": 0,
        "note": "经典电影重温"
    },
    {
        "title": "定档12部却挑不出一部想看的！这个国庆档终于骗不动观众了",
        "core_entities": ["国庆档新片", "定档12部", "骗不动观众", "票房滑铁卢"],
        "published_date": "2026-09-27",
        "total_reads": 188,
        "rec_reads": 0,
        "note": "档期唱衰"
    },
    {
        "title": "4条人命122亿黑金3个死刑：那个叫嚣中国法律来制裁的缅北魏家终于判了！",
        "core_entities": ["缅北魏家", "魏怀仁", "魏榕", "死刑", "电诈", "黑金"],
        "published_date": "2026-10-14",
        "total_reads": 164,
        "rec_reads": 0,
        "note": "跨界社会法制"
    },
    {
        "title": "大婚当夜惨遭灭门：李现新剧把江湖神棍的绝户计拍绝了",
        "core_entities": ["李现", "江湖神棍", "国色芳华", "绝户计", "古装剧"],
        "published_date": "2026-10-12",
        "total_reads": 158,
        "rec_reads": 0,
        "note": "热播新剧"
    },
    {
        "title": "审讯椅上双手被铐：借疯子之口喊出靠爹。说白了，陈飞宇这次终于下凡了",
        "core_entities": ["陈飞宇", "陈凯歌", "靠爹", "下凡", "星二代"],
        "published_date": "2026-10-05",
        "total_reads": 32,
        "rec_reads": 0,
        "note": "星二代困境"
    },
    {
        "title": "《让子弹飞》之后，姜文为什么一部比一部拧巴？",
        "core_entities": ["姜文", "让子弹飞", "拧巴", "邪不压正", "一步之遥"],
        "published_date": "2026-09-17",
        "total_reads": 11,
        "rec_reads": 0,
        "note": "大导演作者性"
    },
    {
        "title": "钟楚曦吃真蝉，吴镇宇拍猪血，《蝉》到底想让谁先失控？",
        "core_entities": ["钟楚曦", "吴镇宇", "蝉", "悬疑片"],
        "published_date": "2026-08-28",
        "total_reads": 4,
        "rec_reads": 0,
        "note": "悬疑类型片"
    },
    {
        "title": "一部被吐槽'宣发骗了'的电影，凭什么9天破12亿",
        "core_entities": ["抓娃娃", "宣发骗了", "沈腾", "马丽"],
        "published_date": "2026-08-21",
        "total_reads": 4,
        "rec_reads": 0,
        "note": "暑期档喜剧"
    }
]


def get_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    """初始化数据库表并注入初始常青种子与历史已发表台账"""
    conn = get_db(db_path)
    with conn:
        conn.executescript(SCHEMA_SQL)
        now = int(time.time())
        # 1. 注入/更新常青种子
        for seed in INITIAL_EVERGREEN_SEEDS:
            conn.execute(
                """
                INSERT OR IGNORE INTO evergreen_seeds 
                (seed_id, title, core_entities, archetype, ledger_summary, proposed_angle, reference_url, score, status, cooldown_until, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?)
                """,
                (
                    seed["seed_id"],
                    seed["title"],
                    json.dumps(seed["core_entities"], ensure_ascii=False),
                    seed["archetype"],
                    seed["ledger_summary"],
                    seed["proposed_angle"],
                    seed.get("reference_url", ""),
                    seed["score"],
                    now,
                ),
            )
        
        # 2. 注入历史近30天已发表台账（用于动态时间衰减负分算法）
        for pub in INITIAL_PUBLISHED_TOPICS:
            pub_date = pub["published_date"]
            # 解析日期转为 unix timestamp
            import datetime as dt_mod
            try:
                pub_ts = int(dt_mod.datetime.strptime(pub_date, "%Y-%m-%d").timestamp())
            except Exception:
                pub_ts = now
            
            # 检查是否已存在同标题记录
            existing = conn.execute("SELECT published_id FROM published_topics WHERE title = ?", (pub["title"],)).fetchone()
            if not existing:
                conn.execute(
                    """
                    INSERT INTO published_topics 
                    (title, core_entities, published_date, published_at, total_reads, rec_reads, note, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pub["title"],
                        json.dumps(pub["core_entities"], ensure_ascii=False),
                        pub_date,
                        pub_ts,
                        pub.get("total_reads", 0),
                        pub.get("rec_reads", 0),
                        pub.get("note", ""),
                        now,
                    ),
                )
    conn.close()


def get_published_topics(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """获取所有历史已发表文章台账"""
    cur = conn.execute(
        """
        SELECT published_id, title, core_entities, published_date, published_at, total_reads, rec_reads, note
        FROM published_topics
        ORDER BY published_at DESC
        """
    )
    topics = []
    for r in cur.fetchall():
        core_ents = json.loads(r["core_entities"]) if isinstance(r["core_entities"], str) else r["core_entities"]
        topics.append({
            "published_id": r["published_id"],
            "title": r["title"],
            "core_entities": core_ents,
            "published_date": r["published_date"],
            "published_at": r["published_at"],
            "total_reads": r["total_reads"],
            "rec_reads": r["rec_reads"],
            "note": r["note"],
        })
    return topics


def add_published_topic(
    conn: sqlite3.Connection,
    title: str,
    core_entities: list[str],
    published_date: str,
    total_reads: int = 0,
    rec_reads: int = 0,
    note: str = "",
) -> int:
    """新增历史已发表长文记录"""
    import datetime as dt_mod
    now = int(time.time())
    try:
        pub_ts = int(dt_mod.datetime.strptime(published_date, "%Y-%m-%d").timestamp())
    except Exception:
        pub_ts = now

    with conn:
        cur = conn.execute(
            """
            INSERT INTO published_topics 
            (title, core_entities, published_date, published_at, total_reads, rec_reads, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                json.dumps(core_entities, ensure_ascii=False),
                published_date,
                pub_ts,
                total_reads,
                rec_reads,
                note,
                now,
            ),
        )
        return cur.lastrowid


def get_active_events_72h(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """查询过去 72 小时内被观测到的活跃事件，供聚类时对齐已存在的 ID（补丁1）"""
    cutoff = int(time.time()) - (72 * 3600)
    cursor = conn.execute(
        """
        SELECT event_id, canonical_title, core_entities, cross_platform_count, 
               overall_score, status, cooldown_until, last_seen_at
        FROM events
        WHERE last_seen_at >= ?
        ORDER BY last_seen_at DESC
        """,
        (cutoff,),
    )
    rows = cursor.fetchall()
    results = []
    for r in rows:
        results.append({
            "event_id": r["event_id"],
            "canonical_title": r["canonical_title"],
            "core_entities": json.loads(r["core_entities"]) if r["core_entities"] else [],
            "cross_platform_count": r["cross_platform_count"],
            "overall_score": r["overall_score"],
            "status": r["status"],
            "cooldown_until": r["cooldown_until"],
            "last_seen_at": r["last_seen_at"],
        })
    return results


def upsert_event(conn: sqlite3.Connection, event: dict[str, Any]) -> None:
    now = int(time.time())
    with conn:
        conn.execute(
            """
            INSERT INTO events (
                event_id, canonical_title, core_entities, first_seen_at, last_seen_at,
                seen_count, cross_platform_count, platforms_involved, lifecycle_stage,
                status, status_updated_at, cooldown_until, safety_tier, safety_reason,
                resonance_archetype, resonance_score, story_tension_score, overall_score,
                proposed_angle, ledger_summary, published_decay_penalty, penalty_reason,
                raw_clustering_data, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                canonical_title = excluded.canonical_title,
                core_entities = excluded.core_entities,
                last_seen_at = excluded.last_seen_at,
                seen_count = events.seen_count + 1,
                cross_platform_count = excluded.cross_platform_count,
                platforms_involved = excluded.platforms_involved,
                lifecycle_stage = excluded.lifecycle_stage,
                safety_tier = excluded.safety_tier,
                safety_reason = excluded.safety_reason,
                resonance_archetype = excluded.resonance_archetype,
                resonance_score = excluded.resonance_score,
                story_tension_score = excluded.story_tension_score,
                overall_score = excluded.overall_score,
                proposed_angle = excluded.proposed_angle,
                ledger_summary = excluded.ledger_summary,
                published_decay_penalty = excluded.published_decay_penalty,
                penalty_reason = excluded.penalty_reason,
                raw_clustering_data = excluded.raw_clustering_data,
                updated_at = excluded.updated_at
            """,
            (
                event["event_id"],
                event["canonical_title"],
                json.dumps(event.get("core_entities", []), ensure_ascii=False),
                event.get("first_seen_at", now),
                now,
                event.get("seen_count", 1),
                event.get("cross_platform_count", 1),
                json.dumps(event.get("platforms_involved", []), ensure_ascii=False),
                event.get("lifecycle_stage", "cold"),
                event.get("status", "pending"),
                event.get("status_updated_at", now),
                event.get("cooldown_until", 0),
                event.get("safety_tier", "GREEN"),
                event.get("safety_reason", ""),
                event.get("resonance_archetype", ""),
                event.get("resonance_score", 0),
                event.get("story_tension_score", 0),
                event.get("overall_score", 0),
                event.get("proposed_angle", ""),
                event.get("ledger_summary", ""),
                event.get("published_decay_penalty", 0),
                event.get("penalty_reason", ""),
                event.get("raw_clustering_data", ""),
                event.get("created_at", now),
                now,
            ),
        )


def insert_snapshot(conn: sqlite3.Connection, snapshot: dict[str, Any]) -> None:
    now = int(time.time())
    with conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                event_id, batch_time, platform, platform_tier, rank_position,
                raw_title, url, raw_hot_label, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot["event_id"],
                snapshot["batch_time"],
                snapshot["platform"],
                snapshot["platform_tier"],
                snapshot["rank_position"],
                snapshot["raw_title"],
                snapshot.get("url", ""),
                snapshot.get("raw_hot_label", ""),
                now,
            ),
        )


def get_event(conn: sqlite3.Connection, event_id: str) -> dict[str, Any] | None:
    """按 event_id 获取事件或常青种子详情"""
    cur = conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
    row = cur.fetchone()
    if row:
        return dict(row)
    cur = conn.execute("SELECT * FROM evergreen_seeds WHERE seed_id = ?", (event_id,))
    s_row = cur.fetchone()
    if s_row:
        d = dict(s_row)
        d["event_id"] = d.get("seed_id")
        d["canonical_title"] = d.get("title")
        d["lifecycle_stage"] = "evergreen"
        d["safety_tier"] = "GREEN"
        d["resonance_archetype"] = d.get("archetype", "D_era_tears")
        d["overall_score"] = d.get("score", 85)
        return d
    return None


def set_event_status(conn: sqlite3.Connection, event_id: str, status: str, days: int = 7) -> bool:
    """人工把关表态：selected 或 rejected，自动加上 7 天冷却期（同时支持 events 与 evergreen_seeds）"""
    now = int(time.time())
    cooldown_until = now + (days * 86400) if status in ("selected", "rejected") else 0
    with conn:
        cur = conn.execute(
            """
            UPDATE events 
            SET status = ?, status_updated_at = ?, cooldown_until = ?, updated_at = ?
            WHERE event_id = ?
            """,
            (status, now, cooldown_until, now, event_id),
        )
        if cur.rowcount > 0:
            return True
        # 若在 events 中未命中，尝试更新常青种子库
        s_cur = conn.execute(
            """
            UPDATE evergreen_seeds
            SET status = ?, cooldown_until = ?
            WHERE seed_id = ?
            """,
            (status, cooldown_until, event_id),
        )
        return s_cur.rowcount > 0


if __name__ == "__main__":
    init_db()
    print("topics.db 初始化成功！")
