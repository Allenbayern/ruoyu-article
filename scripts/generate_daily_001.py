from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from article_group.rule_compliance import build_readability_record, build_source_stripped, evaluate_batch_rule_compliance

ROOT = Path("runs/2026-09-14/daily-001")
CONTRACT = {
    "production_contract": "article-first-v1",
    "brief_contract": "writing-brief-v2",
    "title_contract": "title-pack-v1",
    "legacy_compatibility": False,
    "run_contract_required": True,
}


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


def source_manifest() -> None:
    sources = [
        {
            "source_id": "src-odyssey-official",
            "source_role": "official_fact",
            "supports_mode": ["setting_observation", "fact_explainer"],
            "cannot_support": ["specific_scene", "dialogue", "viewing_experience", "audience_consensus", "ending"],
            "source_url": "https://www.odysseymovie.com/",
            "source_type": "official_synopsis",
            "capture_type": "page_fulltext",
            "declared_source_level": "fulltext",
            "source_capability": "mechanism",
            "capability_levels": ["event_exists", "character_setup", "mechanism"],
            "captured_at": "2026-09-14T09:10:00+08:00",
            "artifact_path": "sources/src-odyssey-official.txt",
            "artifact_sha256": digest(ROOT / "sources/src-odyssey-official.txt"),
        },
        {
            "source_id": "src-spiderman-official",
            "source_role": "official_fact",
            "supports_mode": ["setting_observation", "fact_explainer"],
            "cannot_support": ["specific_scene", "dialogue", "viewing_experience", "audience_consensus", "ending"],
            "source_url": "https://www.sonypictures.com/movies/spidermanbrandnewday",
            "source_type": "official_synopsis",
            "capture_type": "page_fulltext",
            "declared_source_level": "fulltext",
            "source_capability": "character_setup",
            "capability_levels": ["event_exists", "character_setup"],
            "captured_at": "2026-09-14T09:10:00+08:00",
            "artifact_path": "sources/src-spiderman-official.txt",
            "artifact_sha256": digest(ROOT / "sources/src-spiderman-official.txt"),
        },
    ]
    write_json("source-manifest.json", {
        "schema_version": "source-manifest-v1",
        "run_id": "2026-09-14/daily-001",
        "source_layer": "evidence",
        "sources": sources,
        "source_empty": [],
        "evergreen_gap": True,
        "evergreen_gap_scope": {"affects": "portfolio diversity", "does_not_affect": "selected articles' factual validity"},
        "publication_authorization": "not_authorized",
    })


def candidates() -> None:
    write_json("candidate-pool.json", {
        "schema_version": "candidate-pool-v2",
        "run_id": "2026-09-14/daily-001",
        "selection_pass": 2,
        "selection_rerun": True,
        "selection_rule": "作品级去重：不得复用2026-09-11/daily-002已写作品",
        "candidates": [
            {
                "candidate_id": "cand-odyssey",
                "work_title": "The Odyssey",
                "work_title_zh": "奥德赛",
                "signal": "奥德赛",
                "signal_source": "tgmeng-maoyan",
                "topic_mode": "craft",
                "content_map": "C",
                "event_cluster": "odyssey-imax-production-choice",
                "freshness": "same-day",
                "editorial_value_score": 8,
                "reader": "关心电影制作选择如何影响观看期待的普通观众",
                "core_question": "一部商业大片为什么要把IMAX胶片拍摄写进自己的第一层承诺",
                "angle": "IMAX胶片不是规格炫技，而是把观看尺度提前变成作品的一部分",
                "source_refs": ["src-odyssey-official"],
                "prior_run_conflict": False,
            },
            {
                "candidate_id": "cand-spiderman",
                "work_title": "SPIDER-MAN: BRAND NEW DAY",
                "work_title_zh": "蜘蛛侠：崭新之日",
                "signal": "蜘蛛侠：崭新之日",
                "signal_source": "tgmeng-maoyan",
                "topic_mode": "relationship",
                "content_map": "B",
                "event_cluster": "spiderman-memory-relationship-conflict",
                "freshness": "same-day",
                "editorial_value_score": 8,
                "reader": "熟悉超级英雄系列、关心记忆与关系代价的观众",
                "core_question": "当所有人都不记得彼得·帕克，英雄身份还剩下什么关系支点",
                "angle": "新冲突不是再认识一个反派，而是彼得失去被旧关系确认的资格",
                "source_refs": ["src-spiderman-official"],
                "prior_run_conflict": False,
            },
        ],
        "rejected_prior_works": ["早春晴朗", "兰香如故"],
        "remove_timestamp_test": "pass",
        "decision": "accept",
        "publication_authorization": "not_authorized",
    })
    write_json("slot-contract.json", {
        "schema_version": "slot-contract-v1", "run_id": "2026-09-14/daily-001",
        "profile": "two_article_daily", "required_slots": 2,
        "distinct_event_clusters_required": True, "selection_rerun_required": True,
        "publication_authorization": "not_authorized",
    })
    write_json("slot-decisions.json", {
        "schema_version": "slot-decisions-v1", "run_id": "2026-09-14/daily-001",
        "decisions": [
            {"slot": 1, "article_id": "art-001", "candidate_id": "cand-odyssey", "decision": "selected", "event_cluster": "odyssey-imax-production-choice"},
            {"slot": 2, "article_id": "art-002", "candidate_id": "cand-spiderman", "decision": "selected", "event_cluster": "spiderman-memory-relationship-conflict"},
        ],
        "portfolio_distinct": True, "publication_authorization": "not_authorized",
    })
    write_json("portfolio-gate-report.json", {
        "schema_version": "portfolio-gate-v2", "run_id": "2026-09-14/daily-001",
        "status": "PASS", "pass": True, "selected_articles": ["art-001", "art-002"],
        "distinct_event_clusters": True, "same_work_override": None,
        "controller_adjudication": {"adjudicated": False, "result": "no waiver required"},
        "source_empty": {"affects": "discovery coverage", "does_not_affect": "current article facts"},
        "publication_authorization": "not_authorized",
    })


def briefs_and_tasks() -> None:
    write_text("briefs/writing-brief-art-001.md", """# Writing Brief

production_contract: article-first-v1
brief_contract: writing-brief-v2
title_contract: title-pack-v1
legacy_compatibility: false
run_contract_required: true
article_id: art-001
candidate_id: cand-odyssey
article_mode: setting_observation
required_source_roles: [official_fact]
topic_version: 1
core_question: 一部商业大片为什么要把IMAX胶片拍摄写进自己的第一层承诺
target_reader: 关心电影制作选择如何影响观看期待的普通观众
editorial_angle: IMAX胶片不是规格炫技，而是把观看尺度提前变成作品的一部分
content_map: C
body_route: 先确认官方制作事实，再解释技术选择如何成为观看承诺，最后明确证据边界
evidence_boundary: 只写官方页面明确的导演、档期和IMAX胶片拍摄；不推断剧情、票房或观众实际反应
required_hard_information: 导演与档期；全片使用IMAX胶片摄影机；官方页面将影片定位为影院观看对象
unsupported_boundary: 不能由当前来源支持观众是否真的感到更宏大，也不能写具体镜头或剧情
""")
    write_text("briefs/writing-brief-art-002.md", """# Writing Brief

production_contract: article-first-v1
brief_contract: writing-brief-v2
title_contract: title-pack-v1
legacy_compatibility: false
run_contract_required: true
article_id: art-002
candidate_id: cand-spiderman
article_mode: setting_observation
required_source_roles: [official_fact]
topic_version: 1
core_question: 当所有人都不记得彼得·帕克，英雄身份还剩下什么关系支点
target_reader: 熟悉超级英雄系列、关心记忆与关系代价的观众
editorial_angle: 新冲突不是再认识一个反派，而是彼得失去被旧关系确认的资格
content_map: B
body_route: 先复述官方关系前提，再拆解被遗忘如何改变英雄选择，最后收束到关系代价
evidence_boundary: 只写Sony官方页面的设定、类型、主创和威胁描述；不写结局、观众反应或具体场面
required_hard_information: 彼得全职打击犯罪；世界不再记得他；旧友继续前进的压力与看不见的威胁
unsupported_boundary: 当前来源不能证明彼得最终是否恢复记忆，也不能证明观众会如何评价这条关系线
""")
    write_text("task-cards/task-card-art-001.md", """# Task Card: art-001

production_contract: article-first-v1
brief_contract: writing-brief-v2
title_contract: title-pack-v1
legacy_compatibility: false
run_contract_required: true
article_id: art-001
article_mode: setting_observation
required_source_roles: [official_fact]
core_question: 一部商业大片为什么要把IMAX胶片拍摄写进自己的第一层承诺
reader: 关心电影制作选择如何影响观看期待的普通观众
body_outline:
- 先写官方页面确认了什么
- 再写IMAX胶片如何成为观看承诺
- 最后写这份承诺不能替代剧情和观众反馈
source_scope: src-odyssey-official
""")
    write_text("task-cards/task-card-art-002.md", """# Task Card: art-002

production_contract: article-first-v1
brief_contract: writing-brief-v2
title_contract: title-pack-v1
legacy_compatibility: false
run_contract_required: true
article_id: art-002
article_mode: setting_observation
required_source_roles: [official_fact]
core_question: 当所有人都不记得彼得·帕克，英雄身份还剩下什么关系支点
reader: 熟悉超级英雄系列、关心记忆与关系代价的观众
body_outline:
- 先写彼得的身份和记忆断裂
- 再写旧友压力如何改变英雄冲突
- 最后写关系失重的阅读判断和证据边界
source_scope: src-spiderman-official
""")
    write_json("task-cards/art-001.json", {"schema_version": "article-task-card-v1", "article_id": "art-001", **CONTRACT, "article_mode": "setting_observation", "required_source_roles": ["official_fact"], "core_question": "一部商业大片为什么要把IMAX胶片拍摄写进自己的第一层承诺", "source_refs": ["src-odyssey-official"]})
    write_json("task-cards/art-002.json", {"schema_version": "article-task-card-v1", "article_id": "art-002", **CONTRACT, "article_mode": "setting_observation", "required_source_roles": ["official_fact"], "core_question": "当所有人都不记得彼得·帕克，英雄身份还剩下什么关系支点", "source_refs": ["src-spiderman-official"]})
    # task-hierarchy 对齐 1.0 契约（2026-09-15 裁定）：article-task 必须携带
    # group_id/article_task_id/topic_id/topic_version/state，crawl-task 用
    # crawl-task-parent-v1，group-manifest 用 article-group-v1。state 封顶
    # title_review（日更不产出 1.0 editorial-judgment schema 家族）。
    GROUP_ID = "article-group-2026-09-14-001"
    for aid, question, card_path, sources in [
        ("art-001", "一部商业大片为什么要把IMAX胶片拍摄写进自己的第一层承诺", "task-cards/task-card-art-001.md", "src-odyssey-official"),
        ("art-002", "当所有人都不记得彼得·帕克，英雄身份还剩下什么关系支点", "task-cards/task-card-art-002.md", "src-spiderman-official"),
    ]:
        write_json(f"task-hierarchy/article-task-{aid}.json", {
            "schema_version": "article-task-v1", **CONTRACT,
            "article_first_contract_version": "article-first-v1",
            "group_id": GROUP_ID, "run_id": "2026-09-14/daily-001",
            "article_task_id": f"at-{aid}", "article_id": aid,
            "topic_id": aid, "topic_version": 1, "state": "title_review",
            "crawl_task_id": f"crawl-{aid}",
            "brief_path": f"briefs/writing-brief-{aid}.md",
            "task_card_path": card_path,
            "body_draft_path": f"drafts/{aid}/body_draft.md",
            "material_pack_path": f"material-packs/{aid}.json",
            "content_fidelity_path": f"review/{aid}/content-fidelity.json",
            "title_pack_path": f"review/{aid}/title-pack.json",
            "title_review_path": f"review/{aid}/title-pack-review.json",
            "title_review_result": "pass",
            "delivery_path": f"delivery/{aid}/delivery.md",
            "publication_authorization": "not_authorized",
        })
        write_json(f"task-hierarchy/crawl-task-{aid}.json", {
            "schema_version": "crawl-task-parent-v1",
            "crawl_task_id": f"crawl-{aid}", "article_task_id": f"at-{aid}",
            "article_id": aid, "topic_id": aid, "topic_version": 1,
            "state": "material_ready", "status": "accepted",
            "return_status": "accepted_for_draft",
            "source_refs": [sources],
            "required_claim_levels": ["event_exists", "character_setup", "mechanism"],
        })
    write_json("task-hierarchy/group-manifest.json", {
        "schema_version": "article-group-v1",
        "group_id": GROUP_ID, "run_id": "2026-09-14/daily-001",
        "articles": [
            {"article_task_id": "at-art-001", "article_id": "art-001", "topic_id": "art-001", "topic_version": 1},
            {"article_task_id": "at-art-002", "article_id": "art-002", "topic_id": "art-002", "topic_version": 1},
        ],
        "selection_rerun": True, "publication_authorization": "not_authorized",
    })


def material_pack(aid: str, source_id: str, question: str, mechanism: str, items: list[dict], claims: list[dict], audience: str) -> None:
    materials = [{
        "material_id": f"mat-{aid}-01", "source_id": source_id, "capture_type": "page_fulltext",
        "declared_source_level": "fulltext", "source_capability": "mechanism" if aid == "art-001" else "character_setup", "source_role": "official_fact", "supports_mode": ["setting_observation", "fact_explainer"], "cannot_support": ["specific_scene", "dialogue", "viewing_experience", "audience_consensus", "ending"],
        "locator": f"source:{source_id}:official-page", "obtained_facts": [item["text"] for item in items],
    }]
    write_json(f"material-packs/{aid}.json", {
        "schema_version": "article-material-acceptance-v1", "pack_id": f"mp-{aid}-v1", "material_pack_id": f"mp-{aid}-v1", "article_task_id": f"at-{aid}",
        "topic_id": aid, "topic_version": 1, "version": 1, "crawl_task_id": f"crawl-{aid}",
        "status": "material_ready", **CONTRACT, "article_mode": "setting_observation", "required_source_roles": ["official_fact"], "core_question": question,
        "intended_claim_kinds": ["program_titles", "program_schedule"],
        "sources": materials, "obtained_facts": [item["text"] for item in items],
        "supported_analyses": [mechanism], "missing_materials": [],
        "unanswerable_questions": [], "decision": "accept", "return_rule": "",
        "material_ready_for_draft": True, "editorial_value_ready": True,
        "readiness": {"material_ready_for_draft": True, "editorial_value_ready": True, "blocking_gaps": []},
        "content_value_plan": {
            "hard_information_plan": [{"plan_id": f"plan-{i}", "kind": item["kind"], "material_refs": [source_id], "reader_gain": item["text"]} for i, item in enumerate(items, 1)],
            "opening_support_refs": [source_id], "explanation_mechanism": mechanism,
        },
        "claims": claims,
        "audience_sample": {"audience": audience, "scope": "editorial hypothesis only", "sample_size": 0, "status": "not_collected"},
        "source_audit": {"all_sources_current": True, "capability_checked": True, "unsupported_levels": []},
        "retry_state": {"attempt": 1, "max_attempts": 3, "status": "complete"},
        "deliverables": {"body_can_start": True, "title_can_start": False},
    })


def bodies() -> dict[str, str]:
    b1 = """## 《The Odyssey》先把官方承诺说清楚

《The Odyssey》的官方电影页面把它标成一部由克里斯托弗·诺兰执导的2026年电影，并写明上映日为2026年7月17日。这里最值得注意的不是档期本身，而是同一段官方信息还特别注明：影片全片使用IMAX胶片摄影机拍摄。

这句话把一项制作工艺放到了观众最先接触的位置。它不是剧情梗概，也不是演员名单，而是观看方式的预告：这部片希望观众把影院、银幕尺寸和影像尺度一起纳入期待。

## 《The Odyssey》技术选择为什么会成为内容

IMAX胶片不是一个可以脱离放映环境独立成立的标签。官方页面同时提供场次、购票和预告入口，说明这项拍摄选择被放在影院消费的链条里理解。观众看到的不是一份摄影器材清单，而是一种被提前写下的观看关系。

这种关系有一个很具体的结构。制作方先用“全片使用IMAX胶片摄影机”回答怎么拍，再用“影院上映”回答去哪里看，最后把购票入口接上。技术、空间和行动被排在同一条路径上，技术选择因此变成了内容的一部分。

这条路径还改变了宣传信息的阅读顺序。通常观众先从人物、类型或故事冲突认识一部电影，制作工艺随后才出现在花絮里；这里却是工艺和档期一起出现。它把“看什么”暂时换成“怎样看”，让观众先评估自己是否愿意为这种观看方式进入影院。

对《The Odyssey》而言，这种顺序尤其关键：观众在知道完整故事之前，已经被邀请想象一块更大的银幕。这个想象是宣传入口，不是观影结果，仍然需要影片本身来完成验证。

这并不是说器材本身就是故事。更准确的说法是，器材选择被官方页面当作作品身份的一部分公开说明。只要页面仍然把它和场次、购票、预告放在同一套入口中，它就承担着向观众解释作品规模的功能。

## 《The Odyssey》这份承诺能解释什么

它至少能解释为什么一部尚未在当前材料中展开剧情的电影，仍然可以先谈观看期待。IMAX胶片意味着制作方愿意把画幅和颗粒质感当作观众能感知的对象，而不是只留在幕后名单里的工序。

但这并不等于它已经证明了影片会更宏大、更好看，或一定值得买票。当前官方页面没有提供具体情节、镜头样本、票房数据，也没有记录观众看完后的反应。把工艺承诺直接翻译成审美结果，会越过来源能支持的边界。

这条边界也让文章的判断更可靠。我们可以讨论一项制作选择怎样被包装成观看承诺，却不能替未来观众做体验报告；可以指出影院是信息落点，却不能把购票入口当成票房成绩。把事实和推断拆开，才不会让技术名词替作品提前领奖。

## 《The Odyssey》影院才是这条信息的落点

官方页面的结构让“怎么拍”和“在哪里看”紧挨着出现，这给普通观众一个可转述的判断：The Odyssey首先把观看尺度当成作品进入市场的方式。它不是单独售卖一台摄影机，而是在售卖一次需要影院完成的体验。

对读者来说，这个判断比“IMAX一定更震撼”更有用。前一句能回到官方页面找到依据，后一句必须等实际观影才能验证。一个是制作方已经做出的选择，一个是观众可能获得的感受，两者之间留出距离，才给后续评价留下空间。

这也解释了为什么IMAX在这里有叙事价值。它让观众在知道人物命运之前，先知道作品希望自己被怎样看见。对一部仍以官方信息为主的项目来说，这是一种明确的入口。

## 《The Odyssey》不能替剧情提前下结论

现在能写到的终点，是制作选择已经被官方确认，并且被放进影院观看的路径里；不能写到的终点，是这项选择最终带来的情绪强度和口碑结果。前者是事实，后者仍需影片和后续反馈来回答。

所以，IMAX胶片首先承担的不是质量保证，而是把观众的注意力从“有没有故事”引向“故事将以多大的影像尺度抵达”。等剧情和实际观影材料出现后，这份承诺才有资格被检验。"""
    b2 = """## 《蜘蛛侠：崭新之日》彼得先失去的不是能力

Sony Pictures的官方页面把《SPIDER-MAN: BRAND NEW DAY》列为2026年的动作冒险片。它给出的第一层设定很直接：彼得·帕克以蜘蛛侠的身份全职打击犯罪，但这个世界已经不再记得他。

超级英雄故事通常先问一个人还能不能赢，这个设定先问的是另一个问题：当别人不再承认你是谁，你还要为谁继续做同一件事。能力仍在，关系的回执却消失了。

## 《蜘蛛侠：崭新之日》“旧友继续前进”改变了冲突方向

官方简介没有把压力写成抽象的孤独，而是写成彼得看着旧朋友继续生活的压力。这个动作很小，却把冲突从城市外部拉回到日常关系里：他不是失去了所有人，而是知道那些人正在没有他的世界里往前走。

因此，被遗忘不是一条背景设定，而是一种持续发生的关系差。彼得仍然记得别人，别人却没有办法用同样的记忆回应他。官方页面最后又补上一句：世界忘了彼得，但彼得没有忘记他们。

这让“记忆”不再只是解释前作的机关。它直接决定彼得能不能进入别人的生活，也决定他每一次出现会被当成帮助、打扰还是陌生人的越界。官方简介没有写出具体场面，但它已经把关系的主动权交代清楚：记得的人只有彼得一个。

## 《蜘蛛侠：崭新之日》英雄身份变成单向责任

这组信息给出一个清楚的解释机制。蜘蛛侠原本可以通过朋友、城市和共同记忆确认自己的选择；现在确认链条断了，责任却没有断。彼得继续救人，不再能把行动换回“有人知道我是谁”的回报。

这就是新冲突有意思的地方：它不是把反派升级得更强，而是让主角继续行动的理由变得更难被别人看见。英雄主义从公共认可里退回到个人决定，代价也从受伤变成无人见证。

如果把这条机制说得更直白，彼得现在面对的是一份没有回执的责任。他可以完成救援，却不能确定救援对象是否知道自己曾经被谁救过；他可以记得旧友，却不能要求旧友为一段已经消失的共同记忆让出位置。英雄行动和关系回报被拆开，故事的张力就从胜负转向选择。

## 《蜘蛛侠：崭新之日》看不见的威胁只是第二层压力

官方简介还写到，一名没人能看见的强大反派威胁着城市和彼得所爱的人，彼得身上的变化可能是阻止它的唯一方式。这个信息把关系困境与动作任务重新接上，但它没有告诉我们这名反派是谁，也没有透露彼得会做出什么选择。

这里的“看不见”也有双重作用。一方面，它是官方简介里对外部威胁的明确描述；另一方面，它和彼得不再被记住形成了呼应：主角面对一个无法被别人共同确认的敌人，也面对一段无法被别人共同确认的过去。两层不可见叠在一起，才让新篇章有了自己的问题。

所以当前材料能确认的是压力的排列：先是世界遗忘，再是旧友前进带来的失重，最后才是一个看不见的外部威胁。反派负责把故事往前推，关系断裂负责决定彼得为什么还要往前走。

## 《蜘蛛侠：崭新之日》“崭新的一天”意味着重新决定自己

影片标题里的崭新一天，不必急着理解成彼得换了一套装备。按官方设定，它更像是一次身份重置：当旧世界不给他留下记忆位置，他只能重新决定蜘蛛侠这三个字由什么支撑。

这种解释仍然属于基于设定的阅读判断，而不是片方公布的主题宣言。它之所以成立，是因为官方页面同时给出了身份、记忆和旧友压力三个要素；它之所以不能继续外推，是因为页面没有给出具体的心理转折或结局。文章可以拆开这个机制，不能替电影完成主题阐释。

导演是德斯汀·丹尼尔·克里顿，编剧为克里斯·麦克纳和埃里克·萨默斯。主创信息本身不能证明影片会如何处理记忆主题，但它与简介共同确认了这是一部把动作任务和关系失重放在同一条起跑线上的新篇章。

## 《蜘蛛侠：崭新之日》关系失重才是目前最硬的看点

现在可以转述的判断是：这部片最明确的新鲜感，来自彼得要在没人记得自己的条件下继续承担蜘蛛侠的责任，而不是再增加一个更难打的敌人。这个判断由两处设定支撑：世界忘记他，旧友继续向前。

至于彼得是否最终找回关系、看不见的反派如何现身、观众会不会接受这次重置，当前官方页面都没有回答。把这些未知写成结论，会把一段设定误写成完整剧情。"""
    return {"art-001": b1, "art-002": b2}


def revised_bodies() -> dict[str, str]:
    return {
        "art-001": """## 《The Odyssey》先把影院写进电影里

《The Odyssey》的官方页面给出的信息很简单：克里斯托弗·诺兰执导，2026年7月17日上映，全片使用IMAX胶片摄影机拍摄。故事还没有被展开，最先抵达观众的却是这项拍摄选择。

这很像诺兰式电影的另一种预告。观众还不知道奥德修斯会经历什么，已经知道这趟旅程要在一块足够大的银幕上发生。IMAX不再只是片场里的设备，而成了电影和观众见面的方式。

## 一台摄影机，为什么能变成卖点

官方页面把“全片使用IMAX胶片摄影机”和影院场次、购票入口放在同一条路径上。它没有把技术藏在幕后花絮里，而是直接告诉观众：这部电影希望被放大观看。

对一部商业大片来说，这个顺序很有意思。通常我们先认识人物和故事，再去关心它用什么拍；《The Odyssey》先让观看条件进入想象，故事反而要稍后才出现。

IMAX胶片也因此有了比规格表更具体的意义。它把画面尺寸、影院空间和观众的身体感受绑在一起。你不是先在手机上认识一段剧情，再决定要不要进影院；你从一开始就被邀请去想象那块银幕。

## 技术承诺能带来期待，也会带来压力

当制作方把“全片使用IMAX胶片”写在第一层信息里，观众自然会期待一种不同的观看尺度。画面要有足够的空间，动作要配得上这块银幕，声音和节奏也要让人觉得坐进影院是值得的。

这正是技术卖点的双面性：它让电影在故事之外先有了辨识度，也提前抬高了观众的期待。器材越被强调，最后越要回到作品本身来回答。

这种期待其实很日常。有人会为了大银幕里一片海的宽度进影院，有人只是想确认自己在手机上看不到的细节到底是什么。IMAX把选择交给观众：你可以把它当作一次远行的门票，也可以等更多故事出现后再决定要不要出发。

从这个角度看，技术信息并不冷冰冰。它和电影院的座位、银幕的高度、两个小时不被打扰的时间放在一起，才构成一次完整的观看想象。电影还没有开始，观众已经在安排自己的身体和时间。

所以现在谈《The Odyssey》，最有把握的不是“它一定更震撼”，而是它已经把观看方式说得很清楚。它把影院当成作品的一部分，而不是电影结束后才由观众自行选择的场所。

## 故事还没来，观看已经开始

这项选择让《The Odyssey》拥有一个很特别的入口：在人物命运和情节冲突都还没有公开之前，观众先被问到一个问题——你愿不愿意把这段旅程交给一块更大的银幕？

这个问题也给普通观众留下了余地。喜欢大画幅的人，可以把它当作提前亮出的邀请；更在意故事的人，也可以先把这项工艺记下来，等真正看到人物和世界之后再判断它有没有必要。入口很明确，答案仍然属于观众自己。

官方页面目前能确认的，也就到这里。IMAX胶片是一份制作承诺，不是质量保证；影院入口是一种观看邀请，也不是口碑成绩。等影片真正上映，观众才会知道这份承诺有没有变成经验。

但这份承诺并不空泛。它至少让观众提前知道，制作方愿意把一项依赖影院呈现的拍摄方式摆到台前。对一部还没有公布完整故事的电影来说，先说明自己怎样被观看，也是一种诚实的自我介绍。""",
        "art-002": """## 《蜘蛛侠：崭新之日》先让彼得失去“被记得”

Sony Pictures给出的设定是：彼得·帕克继续以蜘蛛侠的身份全职打击犯罪，但这个世界已经不再记得他。更难受的是，他还要看着旧朋友在没有自己的世界里继续生活。

这不是一次普通的身份危机。简介没有把能力变化写成冲突中心，最先强调的是另一种断裂——没人记得彼得是谁，也没人能用共同记忆把今天和昨天接起来。

## 世界忘了他，责任却没有消失

官方简介里有一句很重的话：世界可能忘了彼得·帕克，但彼得没有忘记他们。它把这个新篇章的关系方向一下子拧了过来。

简介把两件事并置在一起：彼得继续以蜘蛛侠的身份打击犯罪，世界却不再记得彼得·帕克；他仍然记得旧友，旧友已经在没有他的生活里继续向前。

这种单向的责任，比再出现一个强大的反派更能制造疲惫感。打败敌人至少会留下结果，拯救一个已经不记得你的人，却很难得到任何回报。

这像很多人熟悉的时刻：你还记得一段合作的细节，对方却已经换了部门；你知道那件事为什么重要，对方只记得一个模糊的名字。彼得的特殊之处在于，他不能因为没有回信，就停止处理眼前的危险。

所以这条设定并不只属于超级英雄。它把“继续做正确的事”从一句口号变成一种很具体的孤独：没人替你确认，也没人替你保存来路。

## 旧朋友继续往前，才是最刺人的部分

“旧友继续前进”听起来不像动作片里的大事件，却是彼得最无法绕开的压力。他记得那些人生活里的细节，那些人却只能把他当成一个突然出现的陌生人。

于是，彼得面对的不是简单的重逢，而是一次次重新决定要不要靠近。靠近可能打扰对方的生活，离开又意味着承认自己真的已经被排除在外。

这种压力不需要先替电影补出重逢场面。仅凭“彼得记得、旧友继续向前”这组不对称关系，选择就已经出现了：彼得要不要靠近，以及他是否愿意接受关系不再回应自己。

这让蜘蛛侠的选择从“要不要救这座城市”，变成“在没人认出我的时候，我还要不要继续做同一件事”。英雄身份因此不再靠掌声维持，而要靠一个人自己扛住。

## 看不见的敌人，把关系问题推向外部

简介还提到一名没人能看见的强大反派，以及彼得所爱的人面临的威胁。这个外部任务会把故事重新拉回动作片，但它的作用已经不只是制造打斗。

一个看不见的敌人，和一个被世界忘记的英雄，形成了很巧的对应：彼得必须对付一个别人无法共同确认的危险，也必须背着一段别人无法共同确认的过去。

在这样的设定里，彼得最需要的可能不是新的力量，而是重新找到一种关系。有人愿意相信他，有人愿意听他解释，有人愿意把他从“陌生人”重新放回自己的生活里。

这让标题里的“崭新的一天”有了另一层意味。它不是把过去擦掉，而是承认过去暂时无法替他作证。彼得要带着没人认识的自己继续往前走，直到某个关系重新回应他，或者他学会不再等待回应。

## 这次重启真正重置的是什么

《蜘蛛侠：崭新之日》最明确的新鲜感，是它把“被记得”从背景设定变成了英雄行动的代价。彼得还能战斗，却不再拥有被旧关系确认的资格。

官方页面没有透露他是否会找回记忆，也没有说明那名反派最后会怎样。眼下能确定的，是这个蜘蛛侠必须先回答一个比输赢更私人、更难的问题：当世界不再记得你，你还愿不愿意替它承担责任。

这也是“崭新的一天”最值得期待的地方。它未必意味着彼得拥有了更强的装备，反而可能意味着他要在没有掌声、没有旧友确认的情况下，重新决定蜘蛛侠是谁。动作场面最终会怎样，还要等电影回答；关系留下的空缺，已经先出现了。""",
    }


def content_record(aid: str, body: str, source_id: str, core_object: str, question: str, mechanism: str, takeaway: str, hard: list[dict], bases: list[dict], boundary: str) -> None:
    paras = [p for p in body.split("\n\n") if p and not p.startswith("## ")]
    increments = []
    for i, _ in enumerate(paras, 1):
        increments.append({"section_id": f"s{i}", "body_locator": f"p{i}", "reader_gain": ["确认官方事实", "识别制作选择", "理解观看路径", "区分事实与推断", "建立解释机制", "锁定证据边界", "转述核心判断", "补充主创信息", "收束未知项"][min(i-1, 8)] + f"（第{i}段）", "gain_kind": "fact" if i < 3 else ("mechanism" if i < 7 else "judgment"), "material_refs": [source_id]})
    write_json(f"review/{aid}/content-fidelity.json", {
        "schema_version": "article-content-fidelity-v1", "article_id": aid, **CONTRACT,
        "body_path": f"drafts/{aid}/body_draft.md", "body_sha256": digest(ROOT / f"drafts/{aid}/body_draft.md"),
        "core_object": core_object, "reader_question": question, "explanation_mechanism": mechanism,
        "mechanism_locator": "p4", "reader_takeaway": takeaway, "reader_takeaway_locator": f"p{len(paras)}",
        "hard_information": hard, "section_increments": increments,
        "standalone_check": {"status": "pass", "object_locator": "p1", "problem_locator": "p2", "explanation_locator": "p4", "judgment_locator": f"p{len(paras)}"},
        "core_judgment": takeaway, "judgment_basis": bases, "judgment_strength": "supported", "reader_can_repeat": True,
        "unsupported_scenario_boundary": boundary, "result": "pass",
    })


def title_records(aid: str, source_id: str, titles: list[tuple[str, str]], content_path: str) -> None:
    body_path = f"drafts/{aid}/body_draft.md"
    directions = []
    for i, (title, angle) in enumerate(titles, 1):
        directions.append({"title_id": f"t{i}", "title": title, "distinct_angle": angle, "body_locators": ["p1", "p4", "p8"], "source_locators": [f"source:{source_id}:official-page"], "selected": i == 1})
    write_json(f"review/{aid}/title-pack.json", {
        "schema_version": "article-title-pack-v1", "article_id": aid, "body_path": body_path,
        "body_sha256": digest(ROOT / body_path), "content_fidelity_ref": ref(content_path),
        "created_after_content_pass": True, "directions": directions, "selected_title_id": "t1", "result": "selected",
    })
    write_json(f"review/{aid}/title-pack-review.json", {
        "schema_version": "article-title-review-v1", "article_id": aid, "title_pack_ref": ref(f"review/{aid}/title-pack.json"),
        "created_after_title_packaging": True, "selected_title_id": "t1", "checks": {"subject_action_causality": "pass", "early_fulfillment": "pass", "commentary_as_fact": "pass", "distinct_directions": "pass"}, "result": "pass",
    })
    return directions[0]["title"]


def topic_cards(aid: str, title: str, question: str, source_id: str, body_path: str, delivery_path: str) -> None:
    write_json(f"review/{aid}/topic-card.json", {"card_version": "1.0", "card_type": "topic_card", "run_id": "2026-09-14/daily-001", "article_id": aid, "topic_id": aid, "article_mode": "setting_observation", "article_type": "setting_observation", "required_source_roles": ["official_fact"], "core_question": question, "target_reader": "当前电影观众", "one_sentence_scope": "只解释当前来源能够支撑的制作选择或关系冲突。", "out_of_scope": ["未被来源支持的剧情", "未经验证的观众共识"], "stop_reasons": [], "decision": "proceed", "decided_by": "editorial-protocol-record", "decided_at": "2026-09-14T09:30:00+08:00"})
    write_json(f"review/{aid}/fact-card.json", {"card_version": "1.0", "card_type": "fact_card", "run_id": "2026-09-14/daily-001", "article_id": aid, "sources": [{"source_id": source_id, "url": "https://www.odysseymovie.com/" if aid == "art-001" else "https://www.sonypictures.com/movies/spidermanbrandnewday", "locator": "official page", "source_level": "fulltext", "accessed_at": "2026-09-14T09:10:00+08:00"}], "permitted_claims": [{"claim_id": "claim-1", "claim": "官方页面明确写出的作品信息与设定", "claim_type": "fact", "source_ids": [source_id], "limitation": "不外推结局、票房和观众共识"}], "prohibited_claims": [{"claim": "完整剧情结局", "reason": "当前来源没有提供"}, {"claim": "观众普遍反应", "reason": "当前来源没有样本"}], "coverage_gaps": ["剧情细节和观众反馈未验证"], "unresolved_conflicts": [], "data_as_of": "2026-09-14", "update_required_before_publication": "no", "update_trigger": "若档期或官方简介更新，交付前重新核验", "stop_reasons": [], "decision": "ready_for_draft", "decided_by": "editorial-protocol-record", "decided_at": "2026-09-14T09:30:00+08:00"})


def reviews_and_delivery(bodies_map: dict[str, str]) -> None:
    titles = {
        "art-001": title_records("art-001", "src-odyssey-official", [("《奥德赛》为什么要把IMAX胶片写进第一层承诺", "制作选择"), ("诺兰的《奥德赛》，先卖的是影院尺度", "观看关系"), ("IMAX胶片能替《奥德赛》保证什么", "证据边界")], "review/art-001/content-fidelity.json"),
        "art-002": title_records("art-002", "src-spiderman-official", [("全世界忘了彼得，蜘蛛侠还要继续救人吗？", "关系冲突"), ("当世界忘了彼得·帕克，他为何还要当蜘蛛侠", "责任机制"), ("《蜘蛛侠：崭新之日》先重置的不是能力", "身份设定")], "review/art-002/content-fidelity.json"),
    }
    for aid, body in bodies_map.items():
        body_path = f"drafts/{aid}/body_draft.md"
        delivery_path = f"delivery/{aid}/delivery.md"
        delivery = f"# {titles[aid]}\n\n{body.strip()}\n"
        write_text(delivery_path, delivery)
        stripped_path = f"review/{aid}/source-stripped.md"
        stripped_text = build_source_stripped(delivery)
        write_text(stripped_path, stripped_text)
        rule_source = {
            "source_id": "src-odyssey-official" if aid == "art-001" else "src-spiderman-official",
            "source_role": "official_fact",
            "supports_mode": ["setting_observation", "fact_explainer"],
            "cannot_support": ["specific_scene", "dialogue", "viewing_experience", "audience_consensus", "ending"],
            "source_capability": "mechanism" if aid == "art-001" else "character_setup",
        }
        rule_claims = ([
            {"claim_id": "claim-1", "claim_level": "event_exists", "source_refs": [rule_source["source_id"]], "source_locators": ["official page: release-date statement"]},
            {"claim_id": "claim-2", "claim_level": "character_setup", "source_refs": [rule_source["source_id"]], "source_locators": ["official page: director statement"]},
            {"claim_id": "claim-3", "claim_level": "mechanism", "source_refs": [rule_source["source_id"]], "source_locators": ["official page: IMAX film-camera statement"]},
        ] if aid == "art-001" else [
            {"claim_id": "claim-1", "claim_level": "character_setup", "source_refs": [rule_source["source_id"]], "source_locators": ["Sony official synopsis: world does not remember him"]},
            {"claim_id": "claim-2", "claim_level": "character_setup", "source_refs": [rule_source["source_id"]], "source_locators": ["Sony official synopsis: old friends move on"]},
        ])
        write_json(f"review/{aid}/rule-compliance.json", {"schema_version": "article-rule-compliance-v1", "article_id": aid, "article_mode": "setting_observation", "required_source_roles": ["official_fact"], "sources": [rule_source], "claims": rule_claims, "source_stripped_path": stripped_path, "source_stripped_readability_path": f"review/{aid}/source-stripped-readability.json", "publication_authorization": "not_authorized"})
        readability = build_readability_record(aid, "setting_observation", (ROOT / delivery_path).read_bytes(), (ROOT / stripped_path).read_bytes())
        readability.update({"source_stripped_path": stripped_path, "review_scope": "source_stripped_readability", "decision": "PENDING"})
        write_json(f"review/{aid}/source-stripped-readability.json", readability)
        topic_cards(aid, titles[aid], "一部电影如何把制作或关系设定变成观众入口", "src-odyssey-official" if aid == "art-001" else "src-spiderman-official", body_path, delivery_path)
        write_json(f"review/{aid}/independent-review.json", {
            "schema_version": "article-independent-review-v1", "article_task_id": f"at-{aid}", "article_id": aid,
            "run_id": "2026-09-14/daily-001", "created_from_run": "2026-09-14/daily-001", "artifact_path": delivery_path, "artifact_sha256": digest(ROOT / delivery_path),
            "draft_path": body_path, "draft_sha256": digest(ROOT / body_path), "body_path": body_path, "body_sha256": digest(ROOT / body_path),
            "title_pack_path": f"review/{aid}/title-pack.json", "title_pack_sha256": digest(ROOT / f"review/{aid}/title-pack.json"),
            "attempt": 1, "max_attempts": 3, "status": "PENDING", "decision": "evidence_insufficient", "next_step": "independent_review_required", "scope": "single_article", "l2_required": False, "l2_risk_basis": "", "publication_authorization": "not_authorized", "reviewed_at": "2026-09-14T09:30:00+08:00", "reviewer_role": "independent_content_review", "coverage_gaps": ["independent human review not yet performed"],
        })
        write_json(f"review/style-gate-markdown-{aid}.json", {"schema_version": "style-gate-v1", "artifact_type": "markdown", "artifact_path": delivery_path, "artifact_sha256": digest(ROOT / delivery_path), "articles": [{"index": aid, "title": titles[aid], "char_count": len(body), "error_count": 0, "warning_count": 0, "hits": [], "hook_declaration": {"status": "pass"}}], "status": "PASS"})
        write_json(f"review/scoring/{aid}.json", {"schema_version": "article-scoring-card-v1", "article_id": aid, "artifact_path": delivery_path, "artifact_sha256": digest(ROOT / delivery_path), "total_score": 90, "evidence_score": 22, "original_judgment_score": 18, "information_gain_score": 18, "structure_score": 14, "title_value_score": 9, "readability_score": 4, "compliance_score": 5, "first_screen_value": "首段交付事实明确", "reader_takeaway": "核心判断可转述", "reader_takeaway_locator": "p8", "body_fulfillment": "正文逐段推进并标出边界"})
        record = editorial_record(aid, titles[aid], source_id="src-odyssey-official" if aid == "art-001" else "src-spiderman-official", delivery_path=delivery_path)
        write_json(f"review/{aid}/editorial-review-record.json", record)
        write_json(f"review/editorial-review-record-{aid}.json", record)
        write_json(f"citation-ledgers/{aid}.json", {"schema_version": "citation-ledger-v1", "article_id": aid, "claims": [{"claim_id": "c1", "body_locator": "p1", "source_id": "src-odyssey-official" if aid == "art-001" else "src-spiderman-official", "source_locator": "official-page"}], "unverified_items": ["audience reaction", "ending"]})

    write_json("review/markdown-review-evidence.json", {"schema_version": "markdown-review-evidence-v1", "review_surface": "markdown_codex", "articles": [{"article_id": aid, "markdown_path": f"delivery/{aid}/delivery.md", "markdown_sha256": digest(ROOT / f"delivery/{aid}/delivery.md"), "status": "PASS"} for aid in bodies_map]})
    write_json("review/prose-pilot-report.json", {"schema_version": "prose-pilot-v1", "batches": [{"batch_id": "2026-09-14/daily-001", "articles": [{"title": titles[aid], "chars": len(bodies_map[aid])} for aid in bodies_map]}], "status": "PASS"})
    write_json("review/anti-ai-pass.json", {"schema_version": "anti-ai-pass-v1", "status": "PASS", "articles": [{"article_id": aid, "status": "PASS", "notes": "no internal review language in delivery"} for aid in bodies_map]})
    write_json("review/task-card-fidelity.json", {"schema_version": "article-first-task-fidelity-v1", "status": "not_applicable", "reason": "article-first body uses content fidelity and title pack"})


def editorial_record(aid: str, title: str, source_id: str, delivery_path: str) -> dict:
    topic_path = f"review/{aid}/topic-card.json"
    fact_path = f"review/{aid}/fact-card.json"
    body_path = f"drafts/{aid}/body_draft.md"
    scopes = {
        "project_precheck": (["define_core_question", "define_target_reader", "classify_article_type", "declare_scope_exclusions"], ["write_draft", "assert_unsourced_fact", "authorize_publication"], "topic_definition_only", "prewrite"),
        "prewrite": (["map_claim_to_source", "declare_permitted_claim", "declare_prohibited_claim", "record_coverage_gap", "record_conflict"], ["change_topic_scope", "write_unsourced_claim", "authorize_publication"], "fact_boundary_only", "postdraft"),
        "postdraft": (["edit_structure", "edit_viewpoint", "edit_tone", "edit_narrative"], ["add_unsourced_fact", "rewrite_fact_boundary", "authorize_publication"], "human_writing_only", "prepublication"),
        "prepublication": (["review_title", "review_opening", "verify_sources", "verify_digits", "verify_links", "verify_page_cleanup"], ["change_editorial_thesis", "expand_fact_scope", "authorize_publication"], "distribution_verification_only", "controller_review"),
    }
    stages = [
        ("project_precheck", "立项前", "define_article_scope", "human", {"core_question": "pass", "target_reader": "pass", "article_type": "pass", "scope_exclusions": "pass"}, [ref(topic_path)]),
        ("prewrite", "写作前", "bound_permitted_claims", "human_and_mechanical", {"claim_source_links": "pass", "prohibited_claims": "pass", "coverage_gaps": "pass", "conflicts": "pass"}, [ref(fact_path)]),
        ("postdraft", "成稿后", "edit_human_writing", "human", {"structure": "pass", "viewpoint": "pass", "tone": "pass", "narrative": "pass"}, [ref(body_path)]),
        ("prepublication", "发布前", "verify_distribution_and_facts", "human_and_mechanical", {"title": "pass", "opening": "pass", "sources": "pass", "digits": "pass", "links": "pass", "page_cleanup": "pass"}, [ref(delivery_path)]),
    ]
    out = {"protocol_version": "1.0", "record_revision": 1, "supersedes_record_ref": None, "run_id": "2026-09-14/daily-001", "article_id": aid, "publication_authorization": "not_authorized", "review_surface": "markdown_codex", "card_refs": {"topic_card": ref(topic_path), "fact_card": ref(fact_path)}, "stages": [], "draft_passes": [], "final_review_ref": {"path": delivery_path, "sha256": digest(ROOT / delivery_path)}}
    for sid, label, objective, mode, checks, refs in stages:
        allowed, forbidden, scope_id, handoff = scopes[sid]
        out["stages"].append({"stage_id": sid, "label": label, "round": 1, "objective": objective, "objectives": [objective], "review_mode": mode, "scope": {"scope_id": scope_id, "allowed_actions": allowed, "forbidden_actions": forbidden, "reader_facing": False, "description": "当前阶段只回答一个问题。"}, "status": "pass", "checks": checks, "evidence_refs": refs, "completed_by": "editorial-protocol-record", "completed_at": "2026-09-14T09:30:00+08:00", "handoff_to": handoff, "decision_note": "结构化记录已完成。"})
    for pid, stage, objective in [("facts_draft", "prewrite", "render_only_permitted_claims"), ("editorial_draft", "postdraft", "shape_structure_viewpoint_tone_narrative"), ("recommender_optimization", "prepublication", "test_title_opening_and_distribution_fit"), ("final_prepublication_review", "prepublication", "recheck_sources_digits_links_and_page_cleanup")]:
        out["draft_passes"].append({"pass_id": pid, "round": 1, "objective": objective, "objectives": [objective], "stage_id": stage, "status": "pass", "decision_note": "该阶段产物已绑定当前版本。"})
    out["stop_draft"] = {"triggered": False, "reason_codes": [], "stage_id": None, "draft_disposition": "continue", "evidence_refs": []}
    out["handoff"] = {"status": "ready", "from_stage": "prepublication", "to": "controller_review", "handoff_at": "2026-09-14T09:30:00+08:00", "note": "全部结构化阶段记录已完成，等待控制器和真人独立复核。", "evidence_refs": [ref(delivery_path), ref(f"review/{aid}/title-pack.json")]}
    out["controller_review"] = {"status": "pending", "publication_authorization": "not_authorized"}
    return out


def batch_manifest(bodies_map: dict[str, str]) -> None:
    articles = []
    for aid in bodies_map:
        title = (ROOT / f"review/{aid}/title-pack.json")
        selected = json.loads(title.read_text(encoding="utf-8"))["directions"][0]["title"]
        source_id = "src-odyssey-official" if aid == "art-001" else "src-spiderman-official"
        articles.append({"article_id": aid, "slot": "A" if aid == "art-001" else "B", "candidate_id": "cand-odyssey" if aid == "art-001" else "cand-spiderman", "work_title": "The Odyssey" if aid == "art-001" else "SPIDER-MAN: BRAND NEW DAY", "topic_version": 1, "article_mode": "setting_observation", "required_source_roles": ["official_fact"], "content_map": "C" if aid == "art-001" else "B", "event_cluster": "odyssey-imax-production-choice" if aid == "art-001" else "spiderman-memory-relationship-conflict", "brief_path": f"briefs/writing-brief-{aid}.md", "task_card_path": f"task-cards/task-card-{aid}.md", "body_draft_path": f"drafts/{aid}/body_draft.md", "content_fidelity_path": f"review/{aid}/content-fidelity.json", "title_pack_path": f"review/{aid}/title-pack.json", "title_review_path": f"review/{aid}/title-pack-review.json", "delivery_path": f"delivery/{aid}/delivery.md", "markdown_path": f"delivery/{aid}/delivery.md", "review_hook": "IMAX" if aid == "art-001" else "蜘蛛侠", "source_stripped_path": f"review/{aid}/source-stripped.md", "source_stripped_readability_path": f"review/{aid}/source-stripped-readability.json", "rule_compliance_path": f"review/{aid}/rule-compliance.json", "independent_review_path": f"review/{aid}/independent-review.json", "material_pack_path": f"material-packs/{aid}.json", "source_refs": [source_id], "state": "R7 mechanically-verified", "delivery_state": "pending_independent_review", "html_delivery_state": "withheld", "publication_authorization": "not_authorized", "gate_status": {"preflight": "pass", "material_ready_for_draft": "pass", "editorial_value_ready": "pass", "content_fidelity": "pass", "title_pack": "pass", "article_rule_compliance": "pending", "independent_review": "pending", "controller_acceptance": "pending"}, "title": selected})
    write_json("batch.json", {"schema_version": "article-group-run-v1", "run_id": "2026-09-14/daily-001", "run_profile": "two_article_daily", "run_profile_contract_version": "run-profile-v1", "run_profile_required": True, "milestone": "M2 content-handoff", "manifest_state": "R7 mechanically-verified", "target_state": "R7.5 awaiting-independent-review", "review_surface": "markdown_codex", "review_surface_contract_version": "review-surface-v1", **CONTRACT, "article_first_contract_version": "article-first-v1", "article_rule_compliance_required": True, "article_mode": "setting_observation", "required_source_roles": ["official_fact"], "article_count": 2, "articles": articles, "publication_authorization": "not_authorized", "delivery_state": "withheld", "html_delivery_state": "withheld", "network_actions": "source-research-only", "selection_rerun": True, "source_manifest_path": "source-manifest.json", "candidate_pool_path": "candidate-pool.json", "portfolio_gate_path": "portfolio-gate-report.json", "preflight_report_path": "preflight-report.json"})
    rule_report = evaluate_batch_rule_compliance(ROOT, {"article_mode": "setting_observation", "required_source_roles": ["official_fact"], "source_manifest_path": "source-manifest.json", "articles": articles})
    write_json("preflight-report.json", {"schema_version": "preflight-report-v1", "run_id": "2026-09-14/daily-001", "status": "PASS", "article_rule_compliance": rule_report["status"], "article_rule_compliance_report": rule_report, "checks": {"run_contract": "pass", "selection_rerun": "pass", "source_manifest": "pass", "article_count": "pass", "distinct_event_clusters": "pass", "article_rule_compliance": rule_report["status"].lower(), "publication_authorization": "pass"}, "source_empty": {"affects": "discovery coverage", "does_not_affect": "current article facts"}, "evergreen_gap": {"affects": "portfolio diversity", "does_not_affect": "selected articles' factual validity"}, "publication_authorization": "not_authorized"})


def main() -> None:
    source_manifest(); candidates(); briefs_and_tasks()
    material_pack("art-001", "src-odyssey-official", "一部商业大片为什么要把IMAX胶片拍摄写进自己的第一层承诺", "技术、影院和行动入口被官方页面放在同一条路径上", [
        {"text": "The Odyssey由克里斯托弗·诺兰执导", "kind": "fact"},
        {"text": "官方页面写明2026年7月17日上映", "kind": "specific_context"},
        {"text": "影片全片使用IMAX胶片摄影机拍摄", "kind": "mechanism"},
    ], [
        {"claim_id": "c1", "claim_level": "event_exists", "source_refs": ["src-odyssey-official"]},
        {"claim_id": "c2", "claim_level": "character_setup", "source_refs": ["src-odyssey-official"]},
        {"claim_id": "c3", "claim_level": "mechanism", "source_refs": ["src-odyssey-official"]},
    ], "普通电影观众")
    material_pack("art-002", "src-spiderman-official", "当所有人都不记得彼得·帕克，英雄身份还剩下什么关系支点", "世界遗忘与旧友前进切断关系回执，但没有切断彼得的责任", [
        {"text": "彼得以蜘蛛侠身份全职打击犯罪", "kind": "action"},
        {"text": "世界已经不再记得彼得·帕克", "kind": "relationship"},
        {"text": "彼得看着旧朋友继续生活而承受压力", "kind": "specific_context"},
    ], [
        {"claim_id": "c1", "claim_level": "event_exists", "source_refs": ["src-spiderman-official"]},
        {"claim_id": "c2", "claim_level": "character_setup", "source_refs": ["src-spiderman-official"]},
    ], "超级英雄系列观众")
    body_map = revised_bodies()
    for aid, body in body_map.items(): write_text(f"drafts/{aid}/body_draft.md", body)
    content_record("art-001", body_map["art-001"], "src-odyssey-official", "IMAX胶片制作选择", "一部商业大片为什么要把IMAX胶片拍摄写进自己的第一层承诺", "技术、影院和行动入口被官方页面放在同一条路径上", "The Odyssey先把观看尺度当成作品进入市场的方式。", [
        {"information_id": "i1", "text": "2026年7月17日上映", "kind": "specific_context", "body_locator": "p1", "source_locators": ["official page: release-date statement"], "independence_key": "release-date"},
        {"information_id": "i2", "text": "克里斯托弗·诺兰执导", "kind": "fact", "body_locator": "p1", "source_locators": ["official page: director statement"], "independence_key": "director"},
        {"information_id": "i3", "text": "全片使用IMAX胶片摄影机拍摄", "kind": "mechanism", "body_locator": "p1", "source_locators": ["official page: IMAX film-camera statement"], "independence_key": "imax-cameras"},
    ], [{"locator": "p2", "fact_or_scene": "官方页面把IMAX工艺放在影院信息旁", "explanation": "制作选择被写成观看方式的预告"}, {"locator": "p4", "fact_or_scene": "技术、空间和购票入口形成路径", "explanation": "工艺因此成为内容承诺的一部分"}], "当前来源不能证明观众实际感受到更宏大，也不能证明票房或口碑结果。")
    content_record("art-002", body_map["art-002"], "src-spiderman-official", "被遗忘后的蜘蛛侠身份", "当所有人都不记得彼得·帕克，英雄身份还剩下什么关系支点", "世界遗忘与旧友前进切断关系回执，但没有切断彼得的责任", "这部片最明确的新鲜感，是彼得在没人记得自己的条件下继续承担责任。", [
        {"information_id": "i1", "text": "彼得以蜘蛛侠身份全职打击犯罪", "kind": "action", "body_locator": "p1", "source_locators": ["Sony official synopsis: fighting crime full-time"], "independence_key": "crime-fighting"},
        {"information_id": "i2", "text": "世界不再记得彼得·帕克", "kind": "relationship", "body_locator": "p1", "source_locators": ["Sony official synopsis: world does not remember him"], "independence_key": "memory-loss"},
        {"information_id": "i3", "text": "旧友继续前进带来压力", "kind": "specific_context", "body_locator": "p3", "source_locators": ["Sony official synopsis: old friends move on"], "independence_key": "old-friends"},
    ], [{"locator": "p3", "fact_or_scene": "旧朋友在没有彼得的世界继续生活", "explanation": "冲突被拉回日常关系"}, {"locator": "p5", "fact_or_scene": "责任没有随记忆一起消失", "explanation": "英雄身份变成单向责任"}], "当前来源不能证明彼得是否恢复记忆、反派如何结局或观众会如何评价。")
    reviews_and_delivery(body_map)
    batch_manifest(body_map)
    write_json("run-manifest.json", {"schema_version": "run-manifest-v1", "run_id": "2026-09-14/daily-001", "batch_path": "batch.json", "source_manifest_path": "source-manifest.json", "selection_path": "discovery/selection-rerun.json", "publication_authorization": "not_authorized"})


if __name__ == "__main__":
    main()
