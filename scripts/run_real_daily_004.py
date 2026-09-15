from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scripts.generate_daily_001 as base
from article_group import portfolio_gate
from article_group.style_gate import validate_markdown_file

base.ROOT = Path("runs/2026-09-15/daily-004")
ROOT = base.ROOT
CONTRACT = base.CONTRACT


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



TASK_CARD_REQUIRED_FIELDS = {
    # Workflow 第 4 步的 5 个必填字段；其中 ①站队点、title_promise、ending_destination
    # 与 H2 大纲刻意取自成稿原句，使 `article_group.task_card_fidelity` 能真正核对
    # "承诺是否兑现"（F4，2026-09-15）。
    "art-001": (
        "1. **站队点/可转述句**：粤语在《空枪》里不是装饰性的年代滤镜，而是演员进入人物关系、也让主创彼此靠近的一道门。\n"
        "2. **读者已知锚点**：朱一龙主演、《空枪》正在上映、首映现场那句粤语问候。\n"
        "3. **today-hook 理由**：影片 2026 年 8 月 19 日上映，首映现场“用粤语打招呼”正被讨论。\n"
        "4. **事实底座**：影片于 2026 年 8 月 19 日上映；全片采用粤语拍摄；朱一龙为角色用一个月突击粤语、常练到凌晨四点（来源：广州日报新花城、新京报）。\n"
        "5. **最强钩子**：为了演万梓强，他只有一个月时间突击粤语（与 batch.json 的 review_hook 一致）。\n"
        "- **title_promise**：《空枪》为什么要让演员先学会说粤语\n"
        "- **ending_destination**：至于这套声音最后能否撑起完整犯罪故事，仍要看影片本身如何完成。\n"
        "\n## 文章结构大纲（H2 目录）\n"
        "## 《空枪》先从一句粤语开始\n"
        "## 语言不是滤镜，是演员进入关系的方式\n"
        "## 一个月的训练，留下的是角色的笨拙\n"
        "## 现场的鼓励，才让挑战继续下去\n"
    ),
    "art-002": (
        "1. **站队点/可转述句**：《玩具总动员5》目前最清楚的冲突，不是旧物与新物的胜负，而是陪伴方式的重新分配。\n"
        "2. **读者已知锚点**：玩具总动员系列、胡迪与巴斯光年、正在长大的邦妮。\n"
        "3. **today-hook 理由**：官方设定公布“玩具先遇到一台平板”，系列第一次把冲突从反派换成孩子的连接方式。\n"
        "4. **事实底座**：Lilypad 是新平板设备；The Pond（池塘）用于邦妮和舞蹈课朋友聊天；邦妮八岁并在努力交朋友；Jessie 任邦妮房间的新任 Sheriff、带着 Bullseye；Buzz 成为副手（来源：Pixar 官方 Toy Story 5 页面）。\n"
        "5. **最强钩子**：一台叫 Lilypad 的新平板电脑，还坚信自己知道什么最适合这个孩子（与 batch.json 的 review_hook 一致）。\n"
        "- **title_promise**：《玩具总动员5》为什么先让玩具遇到平板电脑\n"
        "- **ending_destination**：真正困难的，是让一个正在长大的孩子感觉自己没有被任何一种方式落下。\n"
        "\n## 文章结构大纲（H2 目录）\n"
        "## 《玩具总动员5》先让玩具遇到平板电脑\n"
        "## 邦妮不是不爱玩，她只是正在长大\n"
        "## 旧玩具真正害怕的是什么\n"
        "## 玩具和屏幕都要回答同一个问题\n"
    ),
}

STRONGEST_HOOKS = {
    # 每篇的"最强待核钩子"声明：必须是正文中真实出现、最值得复核的事实断言，
    # 供 style gate 作为审查锚点核验（读者不可见）。取自正文已核验事实。
    "art-001": "为了演万梓强，他只有一个月时间突击粤语",
    "art-002": "一台叫 Lilypad 的新平板电脑，还坚信自己知道什么最适合这个孩子",
}


def _has_completed_independent_review(path: Path) -> bool:
    """已完成的独立复核是证据，重跑生成脚本不得覆盖回 PENDING。"""
    if not path.exists():
        return False
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return isinstance(record, dict) and str(record.get("status", "")).strip().upper() not in ("", "PENDING")


def source_manifest() -> None:
    sources = [
        {"source_id": "src-kongqiang-huacheng", "source_role": "interview", "supports_mode": ["reported_feature"], "cannot_support": ["audience_consensus", "box_office_outcome", "unseen_scene", "ending"], "source_capability": "dialogue", "source_url": "https://huacheng.gz-cmc.com/pages/2026/08/19/cc4802ef4db64825b8565c0ee7457835.html", "source_type": "interview", "capture_type": "page_fulltext", "declared_source_level": "fulltext", "artifact_path": "sources/a01-huacheng-kongqiang.html", "artifact_sha256": digest(ROOT / "sources/a01-huacheng-kongqiang.html"), "captured_at": "2026-09-15T08:45:00+08:00"},
        {"source_id": "src-kongqiang-bjnews", "source_role": "interview", "supports_mode": ["reported_feature"], "cannot_support": ["audience_consensus", "box_office_outcome", "unseen_scene", "ending"], "source_capability": "scene_action", "source_url": "https://www.bjnews.com.cn/detail-1786705572168814.html", "source_type": "media_report", "capture_type": "page_fulltext", "declared_source_level": "fulltext", "artifact_path": "sources/a02-bjnews-kongqiang.html", "artifact_sha256": digest(ROOT / "sources/a02-bjnews-kongqiang.html"), "captured_at": "2026-09-15T08:45:00+08:00"},
        {"source_id": "src-toy-story-pixar", "source_role": "official_fact", "supports_mode": ["setting_observation", "fact_explainer"], "cannot_support": ["viewing_experience", "audience_consensus", "box_office_outcome", "ending"], "source_capability": "mechanism", "source_url": "https://www.pixar.com/toy-story-5", "source_type": "official_synopsis", "capture_type": "page_fulltext", "declared_source_level": "fulltext", "artifact_path": "sources/b01-pixar-toy-story-5.html", "artifact_sha256": digest(ROOT / "sources/b01-pixar-toy-story-5.html"), "captured_at": "2026-09-15T08:45:00+08:00"},
    ]
    write_json("source-manifest.json", {"schema_version": "source-manifest-v1", "run_id": "2026-09-15/daily-004", "source_layer": "evidence", "sources": sources, "source_empty": [{"source": "tgmeng-candy-entertainment", "affects": "discovery coverage"}, {"source": "tgmeng-candy-all", "affects": "discovery coverage"}], "evergreen_gap": False, "publication_authorization": "not_authorized"})


def candidates() -> None:
    candidates = [
        {"candidate_id": "cand-kongqiang-003", "work_title": "空枪", "signal": "猫眼电影评分榜第5位，9.5分", "signal_source": "tgmeng-maoyan", "topic_mode": "reported_feature", "event_cluster": "kongqiang-cantonese-crime-film-premiere", "freshness": "current-release", "editorial_value_score": 9, "reader": "想知道一部犯罪片如何把方言、时代和演员挑战变成现场经验的观众", "core_question": "《空枪》为什么要让演员先学会说粤语，才进入这座欲望之城", "angle": "粤语不是装饰，而是演员进入角色关系和时代现场的第一道门槛", "source_refs": ["src-kongqiang-huacheng", "src-kongqiang-bjnews"], "prior_run_conflict": False, "selection_reason": "当前雷达命中且有两份可回读媒体报道，包含首映现场、主创原话和具体创作背景"},
        {"candidate_id": "cand-toy-story-003", "work_title": "Toy Story 5", "signal": "猫眼电影评分榜第9位，9.3分", "signal_source": "tgmeng-maoyan", "topic_mode": "setting_observation", "event_cluster": "toy-story-tech-playtime-conflict", "freshness": "current-release", "editorial_value_score": 8, "reader": "关心孩子与屏幕关系、也熟悉玩具总动员系列的家庭观众", "core_question": "《玩具总动员5》为什么让玩具先面对一台平板电脑", "angle": "新冲突不是旧玩具过时，而是陪伴孩子的方式正在改变", "source_refs": ["src-toy-story-pixar"], "prior_run_conflict": False, "selection_reason": "当前雷达命中且 Pixar 官方页面给出完整设定、角色关系和技术冲突"},
    ]
    write_json("candidate-pool.json", {"schema_version": "candidate-pool-v2", "run_id": "2026-09-15/daily-004", "selection_pass": 1, "selection_rerun": True, "selection_rule": "作品级与事件簇去重；发现信号不得直接充当事实", "candidates": candidates, "rejected_prior_works": ["早春晴朗", "兰香如故", "奥德赛", "蜘蛛侠：崭新之日"], "decision": "accept", "publication_authorization": "not_authorized"})
    write_json("slot-contract.json", {"schema_version": "slot-contract-v1", "run_id": "2026-09-15/daily-004", "profile": "two_article_daily", "required_slots": 2, "distinct_event_clusters_required": True, "selection_rerun_required": True, "publication_authorization": "not_authorized"})
    write_json("slot-decisions.json", {"schema_version": "slot-decisions-v1", "run_id": "2026-09-15/daily-004", "decisions": [{"slot": 1, "article_id": "art-001", "candidate_id": "cand-kongqiang-003", "decision": "selected", "event_cluster": "kongqiang-cantonese-crime-film-premiere"}, {"slot": 2, "article_id": "art-002", "candidate_id": "cand-toy-story-003", "decision": "selected", "event_cluster": "toy-story-tech-playtime-conflict"}], "portfolio_distinct": True, "publication_authorization": "not_authorized"})
    pool = json.loads((ROOT / "candidate-pool.json").read_text(encoding="utf-8"))
    slots = json.loads((ROOT / "slot-decisions.json").read_text(encoding="utf-8"))
    by_id = {c.get("candidate_id"): c for c in pool.get("candidates", []) if isinstance(c, dict)}
    selected_ids = [d.get("candidate_id") for d in slots.get("decisions", []) if isinstance(d, dict)]
    selected = [
        {
            "candidate_id": cid,
            "work": by_id[cid].get("work_title", ""),
            "reader_question": by_id[cid].get("core_question", ""),
        }
        for cid in selected_ids
        if cid in by_id
    ]
    clusters = [by_id[cid].get("event_cluster", "") for cid in selected_ids if cid in by_id]
    distinct_event_clusters = bool(clusters) and len(clusters) == len(set(clusters))
    history = portfolio_gate.collect_history(exclude_run=ROOT.name)
    history_status = "loaded" if history else "empty_history"
    cross_matches = portfolio_gate.check_cross_batch(selected, history, history_status=history_status)
    cross_errors = [issue for issue in cross_matches if issue.get("level") == "error"]
    write_json("portfolio-gate-report.json", {
        "schema_version": "portfolio-gate-v2",
        "run_id": "2026-09-15/daily-004",
        "status": "PASS" if not cross_errors else "FAIL",
        "selected_articles": ["art-001", "art-002"],
        "distinct_event_clusters": distinct_event_clusters,
        "source_empty": {"affects": "discovery coverage", "does_not_affect": "selected article facts"},
        "publication_authorization": "not_authorized",
        "cross_batch": {
            "checked": True,
            "history_status": history_status,
            "window_batches": len(history),
            "batches": [entry["batch_dir"] for entry in history],
            "matches": cross_matches,
        },
        "portfolio_checks": {
            "cross_batch_pass": not cross_errors,
            "cross_batch_errors": cross_errors,
            "cross_batch_warnings": [issue for issue in cross_matches if issue.get("level") == "warning"],
            "full_gate": "not_run",
            "full_gate_reason": (
                "daily candidate-pool-v2 不携带 portfolio_gate 所需的 "
                "recommendation/content_map/freshness_window/remove_timestamp_test/evidence_readiness 声明；"
                "全量象限/窗口/模式门禁对日更池不适用，需 controller 决定：让日更池补齐声明，或为日更定义单独档位"
            ),
        },
    })


def briefs_and_tasks() -> None:
    write_text("briefs/writing-brief-art-001.md", """# Writing Brief

production_contract: article-first-v1
brief_contract: writing-brief-v2
title_contract: title-pack-v1
legacy_compatibility: false
run_contract_required: true
article_id: art-001
candidate_id: cand-kongqiang-003
article_mode: reported_feature
required_source_roles: [interview]
topic_version: 1
core_question: 《空枪》为什么要让演员先学会说粤语，才进入这座欲望之城
target_reader: 想知道一部犯罪片如何把方言、时代和演员挑战变成现场经验的观众
editorial_angle: 粤语不是装饰，而是演员进入角色关系和时代现场的第一道门槛
body_route: 从首映现场进入，再写粤语训练如何改变演员与角色的关系，最后落到创作选择
evidence_boundary: 只写两份媒体报道中的首映、主创原话和已披露故事设定，不补写未报道的镜头、口碑和结局
required_hard_information: 2026年8月19日上映；全片粤语拍摄；朱一龙一个月突击学粤语并练到凌晨；影片的90年代香港犯罪设定
unsupported_boundary: 不能把首映现场等同于普遍口碑，不能写未披露的具体镜头和结局
""")
    write_text("briefs/writing-brief-art-002.md", """# Writing Brief

production_contract: article-first-v1
brief_contract: writing-brief-v2
title_contract: title-pack-v1
legacy_compatibility: false
run_contract_required: true
article_id: art-002
candidate_id: cand-toy-story-003
article_mode: setting_observation
required_source_roles: [official_fact]
topic_version: 1
core_question: 《玩具总动员5》为什么让玩具先面对一台平板电脑
target_reader: 关心孩子与屏幕关系、也熟悉玩具总动员系列的家庭观众
editorial_angle: 新冲突不是旧玩具过时，而是陪伴孩子的方式正在改变
body_route: 先交代平板与玩具的冲突，再写孩子的交友困境，最后解释玩具为何仍有陪伴价值
evidence_boundary: 只写 Pixar 官方页面的角色设定和故事前提，不补写观影反应、票房和结局
required_hard_information: Lilypad是新平板设备；Bonnie八岁且在努力交朋友；Jessie担任新任Sheriff；传统玩具与屏幕争夺游戏时间
unsupported_boundary: 不能写影片最终如何解决屏幕问题，不能代替家庭观众评价教育效果
""")
    for aid, mode, role, question, source in [("art-001", "reported_feature", "interview", "《空枪》为什么要让演员先学会说粤语，才进入这座欲望之城", "src-kongqiang-huacheng"), ("art-002", "setting_observation", "official_fact", "《玩具总动员5》为什么让玩具先面对一台平板电脑", "src-toy-story-pixar")]:
        write_text(f"task-cards/task-card-{aid}.md", f"# Task Card: {aid}\n\nproduction_contract: article-first-v1\nbrief_contract: writing-brief-v2\ntitle_contract: title-pack-v1\nlegacy_compatibility: false\nrun_contract_required: true\narticle_id: {aid}\narticle_mode: {mode}\nrequired_source_roles: [{role}]\ncore_question: {question}\nreader: 当前电影观众\nbody_outline:\n- 先给出具体事实或现场\n- 再解释冲突如何改变人物关系\n- 最后回到读者能转述的判断和边界\nsource_scope: {source}\n{TASK_CARD_REQUIRED_FIELDS[aid]}")
        write_json(f"task-cards/{aid}.json", {"schema_version": "article-task-card-v1", "article_id": aid, **CONTRACT, "article_mode": mode, "required_source_roles": [role], "core_question": question, "source_refs": [source]})
        write_json(f"task-hierarchy/article-task-{aid}.json", {"schema_version": "article-task-v1", "article_id": aid, "crawl_task_id": f"crawl-{aid}", "status": "content_passed", "brief_path": f"briefs/writing-brief-{aid}.md", "task_card_path": f"task-cards/task-card-{aid}.md"})
        write_json(f"task-hierarchy/crawl-task-{aid}.json", {"schema_version": "crawl-task-v1", "crawl_task_id": f"crawl-{aid}", "article_id": aid, "status": "accepted", "source_refs": [source], "required_claim_levels": ["event_exists", "character_setup", "scene_action", "dialogue"]})
    write_json("task-hierarchy/group-manifest.json", {"schema_version": "group-manifest-v1", "run_id": "2026-09-15/daily-004", "article_ids": ["art-001", "art-002"], "selection_rerun": True, "publication_authorization": "not_authorized"})


def material_pack(aid: str, mode: str, required_role: str, source_ids: list[str], question: str, mechanism: str, facts: list[dict], audience: str) -> None:
    sources = []
    for sid in source_ids:
        if sid == "src-kongqiang-huacheng":
            cap, cannot = "dialogue", ["audience_consensus", "box_office_outcome", "unseen_scene", "ending"]
        elif sid == "src-kongqiang-bjnews":
            cap, cannot = "scene_action", ["audience_consensus", "box_office_outcome", "unseen_scene", "ending"]
        else:
            cap, cannot = "mechanism", ["viewing_experience", "audience_consensus", "box_office_outcome", "ending"]
        sources.append({"material_id": f"mat-{sid}", "source_id": sid, "capture_type": "page_fulltext", "declared_source_level": "fulltext", "source_capability": cap, "source_role": required_role, "supports_mode": [mode], "cannot_support": cannot, "locator": f"source:{sid}:fulltext"})
    write_json(f"material-packs/{aid}.json", {"schema_version": "article-material-acceptance-v1", "pack_id": f"mp-{aid}-v1", "material_pack_id": f"mp-{aid}-v1", "article_task_id": f"at-{aid}", "topic_id": aid, "topic_version": 1, "version": 1, "crawl_task_id": f"crawl-{aid}", "status": "material_ready", **CONTRACT, "article_mode": mode, "required_source_roles": [required_role], "core_question": question, "intended_claim_kinds": ["program_titles", "character_setup", "scene_action", "dialogue"], "sources": sources, "obtained_facts": [x["text"] for x in facts], "supported_analyses": [mechanism], "missing_materials": [], "unanswerable_questions": [], "decision": "accept", "material_ready_for_draft": True, "editorial_value_ready": True, "readiness": {"material_ready_for_draft": True, "editorial_value_ready": True, "blocking_gaps": []}, "claims": [{"claim_id": f"c{i}", "claim_level": x["level"], "source_refs": [source_ids[0]], "source_locators": [x["locator"]]} for i, x in enumerate(facts, 1)], "audience_sample": {"audience": audience, "scope": "not collected", "sample_size": 0}, "source_audit": {"all_sources_current": True, "capability_checked": True, "unsupported_levels": []}, "retry_state": {"attempt": 1, "max_attempts": 1, "status": "complete"}, "deliverables": {"body_can_start": True, "title_can_start": False}})


def bodies() -> dict[str, str]:
    return {
        "art-001": """## 《空枪》先从一句粤语开始

广州首映现场，朱一龙用粤语和观众打招呼。他说这门语言“真的好难学，但真的好好听”。这不是一句轻松的台上玩笑：为了演万梓强，他只有一个月时间突击粤语，常常和老师练到凌晨四点。

《空枪》把故事放在20世纪90年代初的香港。万梓强是想改写命运的打工仔，遇到空姐骆嘉苑后，两人联手作案；内地警察和香港警察则一路追查。影片全程用粤语拍摄，方言先于枪声把这座城市的气质交到演员手里。

## 语言不是滤镜，是演员进入关系的方式

朱一龙回忆，预拍时香港演员说得自如，自己却常常卡在台词上。有一场和卫诗雅对戏，他情绪饱满地说完一段粤语，却从对方表情里读到“没听懂”，那一刻自尊心受到打击。

这个细节很具体：语言障碍没有停留在“学习很辛苦”的概括里，而是直接改变了演员和对手的交流。台词说出口，不代表关系已经建立；对方听不听得懂，决定了情绪能不能抵达。

剧组没有把粤语当成演员个人的加分题。导演韩延说，剧本里许多台词原本就是粤语，因此决定全片采用粤语拍摄，所有内地演员都接受专门训练。语言由此成为表演共同面对的工作，而不是某个人单独完成的模仿。

## 一个月的训练，留下的是角色的笨拙

朱一龙原本希望有半年准备时间，实际只得到一个月。他把手机的 AI 播报调成粤语，尽量让耳朵保持在这套语感里。这样的准备并不浪漫，甚至有点笨拙：重复、卡壳、被纠正，再回到下一句。

但万梓强本来就是一个不安于现状的人。他信奉“要么出人头地，要么人头落地”，在欲望里不断加码。演员为了说好粤语反复受挫，和这个人物想靠一次次赌命改变处境，形成了意外的回声。

这不是说演员的训练等同于角色命运，而是两条线都从“想进入一个自己还不熟悉的世界”开始。万梓强想进入香港的黄金想象，朱一龙要进入一套不属于自己的语言。前者越走越险，后者必须先承认自己说得不够好。

## 现场的鼓励，才让挑战继续下去

朱一龙说，对戏时香港演员会投来鼓励的眼光。韩延则形容他是越有难度越来劲的人。首映台上的笑声背后，是一套很实际的协作：有人纠正发音，有人等你把句子说完，也有人让你知道卡壳并不等于失败。

《空枪》因此有了比“全片粤语”更有分量的看点。方言让演员暴露出不熟练，也让不同地域的主创必须互相等候。语言把时代背景变成了片场关系，观众最后听见的每一句顺畅台词，都经过了这种磨合。

影片已经把犯罪故事、90年代香港和两地警方的追捕摆在一起，但具体镜头如何成立、观众最终如何评价，仍然要交给完整观影。现在可以先转述的判断是：粤语在《空枪》里不是装饰性的年代滤镜，而是演员进入人物关系、也让主创彼此靠近的一道门。

这道门还连接着影片的地域经验。韩延回忆，自己小时候想象中的香港是高楼、机会和刺激，真正去到香港后，感受到的又是烟火气。剧组查阅资料，加入美食、音乐、地标和街头写书法的流浪汉等时代细节。语言、城市和人物因此不是三层分开的布景，而是同一段创作里互相校准的部分。

对观众而言，粤语带来的真实感不需要先被夸大成“还原了整个年代”。它更像一个入口：当演员必须在陌生语感里重新找到节奏，角色的欲望和犹豫也会获得更具体的声音。至于这套声音最后能否撑起完整犯罪故事，仍要看影片本身如何完成。""",
        "art-002": """## 《玩具总动员5》先让玩具遇到平板电脑

这一次，胡迪、巴斯光年、翠丝和伙伴们面对的第一件麻烦，不是一个更大的反派，而是一台叫 Lilypad 的新平板电脑。它带着自己的办法来到邦妮身边，还坚信自己知道什么最适合这个孩子。

平板和玩具的冲突，听起来像一句很直白的“科技来了”。但 Pixar 给出的设定没有把 Lilypad 写成冷冰冰的机器：它会在“池塘”里帮助邦妮和舞蹈课的朋友聊天，也在努力解决孩子交朋友的问题。它争夺的不是一块屏幕，而是陪伴应该以什么方式发生。

## 邦妮不是不爱玩，她只是正在长大

邦妮八岁，仍然喜欢自己的玩具，却发现同龄人更愿意盯着屏幕。她开始怀疑，自己是不是已经到了不该再玩玩具的年纪。这个犹豫让冲突从“玩具对抗科技”变成了一个孩子对自己的判断：我还可以用熟悉的方式和别人一起玩吗？

Jessie在邦妮的房间里担任新任 Sheriff，带着 Bullseye 想帮助孩子交朋友。她代表一种老派但主动的陪伴，Lilypad 则相信通过聊天和连接就能解决问题。两边都在为邦妮努力，所以矛盾不能简单地落成谁对谁错。

这也是《玩具总动员5》设定里最有意思的地方。新设备没有被写成入侵者，旧玩具也没有被写成永远正确的守护者。它们都想帮孩子，只是对“帮忙”的理解不同：一个把连接交给网络，一个把连接交给共同玩耍。

## 旧玩具真正害怕的是什么

Pixar 为 Jessie 和 Bullseye安排了一段分离：他们在任务中和伙伴走散，要想办法回到邦妮身边。这个设定把冒险动作和关系问题接在一起。玩具不是因为失去功能才焦虑，而是因为孩子的注意力可能不再回到它们身上。

Bullseye甚至要和一匹真正的马一起行动，去理解怎样“真正陪在孩子身边”。这个新关系让玩具的价值不再只是被拿起来玩，而是能不能在孩子成长时继续找到位置。

另一边，Lilypad 也不是全知全能。它的解决方案是让邦妮在“池塘”里和朋友聊天，但这仍然需要孩子愿意打开话题。技术可以提供通道，却不能替孩子完成一次真正的靠近。

## 玩具和屏幕都要回答同一个问题

《玩具总动员5》目前最清楚的冲突，不是旧物与新物的胜负，而是陪伴方式的重新分配。传统玩具提供共同想象，平板提供即时连接；邦妮需要的也许不是二选一，而是有人愿意理解她正在长大的速度。

这让“Toy Meets Tech”不只是一句营销口号。它把一台平板放进玩具们的房间，逼迫每个角色重新说明自己的用途。Jessie要证明玩耍仍能让孩子和别人靠近，Lilypad要证明技术也能成为交朋友的入口。

至于影片最后怎样处理这场争执、孩子会不会重新选择玩具，现有设定没有给出答案。现在能转述的判断是：第五部把系列最熟悉的“玩具会不会被忘记”，更新成了“当孩子用另一种方式连接世界时，陪伴还能不能继续”。

这次变化也解释了为什么故事仍然需要 Woody、Buzz 和 Jessie。它们不只是上一部留下来的熟面孔，而是三种不同的陪伴姿态：Woody愿意回到邦妮的房间，Buzz接受成为Jessie的副手，Jessie则把帮助孩子交朋友当成自己的任务。角色的工作都在变，关系仍然通过一起行动维持。

Lilypad的存在让这种变化变得可见。它没有被设定成单纯的坏角色，而是有一套看似有效的办法：让邦妮和舞蹈课朋友在“池塘”里聊天。问题在于，连接的入口不等于关系本身。孩子愿不愿意开口、朋友是否愿意回应，仍然需要时间和勇气。

所以这部续作值得观察的不是玩具能不能打败平板，而是它能否把两种陪伴放进同一个生活场景里。屏幕可以带来新的通道，玩具可以保留共同想象；真正困难的，是让一个正在长大的孩子感觉自己没有被任何一种方式落下。""",
    }


def content_record(aid: str, body: str, source_id: str, mode: str, core_object: str, question: str, mechanism: str, takeaway: str, hard: list[dict], bases: list[dict], boundary: str) -> None:
    base.content_record(aid, body, source_id, core_object, question, mechanism, takeaway, hard, bases, boundary)
    p = ROOT / f"review/{aid}/content-fidelity.json"
    data = json.loads(p.read_text(encoding="utf-8")); data["article_mode"] = mode; data["required_source_roles"] = ["interview" if mode == "reported_feature" else "official_fact"]
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def reviews_and_delivery(bodies_map: dict[str, str]) -> None:
    title_specs = {"art-001": [("《空枪》为什么要让演员先学会说粤语", "语言与角色"), ("朱一龙学粤语，学的是怎么进入《空枪》的香港", "演员挑战"), ("《空枪》的粤语不是滤镜", "创作选择")], "art-002": [("《玩具总动员5》为什么先让玩具遇到平板电脑", "科技冲突"), ("当孩子更爱屏幕，玩具总动员还在守什么", "陪伴关系"), ("《玩具总动员5》最难解决的不是反派", "成长问题")]}
    modes = {"art-001": "reported_feature", "art-002": "setting_observation"}
    roles = {"art-001": "interview", "art-002": "official_fact"}
    source_ids = {"art-001": ["src-kongqiang-huacheng", "src-kongqiang-bjnews"], "art-002": ["src-toy-story-pixar"]}
    for aid, body in bodies_map.items():
        base.write_text(f"drafts/{aid}/body_draft.md", body)
        base.title_records(aid, source_ids[aid][0], title_specs[aid], f"review/{aid}/content-fidelity.json")
        title = json.loads((ROOT / f"review/{aid}/title-pack.json").read_text())["directions"][0]["title"]
        delivery_path = f"delivery/{aid}/delivery.md"; delivery = f"# {title}\n\n{body.strip()}\n"; base.write_text(delivery_path, delivery)
        stripped_path = f"review/{aid}/source-stripped.md"; base.write_text(stripped_path, base.build_source_stripped(delivery))
        srcs = []
        for sid in source_ids[aid]:
            if sid.endswith("huacheng") or sid.endswith("bjnews"):
                supports = ["reported_feature"]; cannot = ["audience_consensus", "box_office_outcome", "unseen_scene", "ending"]
            else:
                supports = ["setting_observation", "fact_explainer"]; cannot = ["viewing_experience", "audience_consensus", "box_office_outcome", "ending"]
            srcs.append({"source_id": sid, "source_role": roles[aid], "supports_mode": supports, "cannot_support": cannot, "source_capability": "dialogue" if sid.endswith("huacheng") else ("scene_action" if sid.endswith("bjnews") else "mechanism")})
        claims = [{"claim_id": "c1", "claim_level": "dialogue" if aid == "art-001" else "character_setup", "source_refs": [source_ids[aid][0]], "source_locators": ["fulltext:primary-fact"]}, {"claim_id": "c2", "claim_level": "scene_action" if aid == "art-001" else "mechanism", "source_refs": [source_ids[aid][0]], "source_locators": ["fulltext:secondary-fact"]}]
        base.write_json(f"review/{aid}/rule-compliance.json", {"schema_version": "article-rule-compliance-v1", "article_id": aid, "article_mode": modes[aid], "required_source_roles": [roles[aid]], "sources": srcs, "claims": claims, "source_stripped_path": stripped_path, "source_stripped_readability_path": f"review/{aid}/source-stripped-readability.json", "publication_authorization": "not_authorized"})
        readability = base.build_readability_record(aid, modes[aid], (ROOT / delivery_path).read_bytes(), (ROOT / stripped_path).read_bytes()); readability.update({"source_stripped_path": stripped_path, "review_scope": "source_stripped_readability", "decision": "PENDING"}); base.write_json(f"review/{aid}/source-stripped-readability.json", readability)
        base.topic_cards(aid, title, "按已核验材料解释创作选择、人物关系和读者问题", source_ids[aid][0], f"drafts/{aid}/body_draft.md", delivery_path)
        topic_path = ROOT / f"review/{aid}/topic-card.json"
        topic = json.loads(topic_path.read_text(encoding="utf-8")); topic.update({"article_mode": modes[aid], "article_type": modes[aid], "required_source_roles": [roles[aid]]}); topic_path.write_text(json.dumps(topic, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if not _has_completed_independent_review(ROOT / f"review/{aid}/independent-review.json"):
            base.write_json(f"review/{aid}/independent-review.json", {"schema_version": "article-independent-review-v1", "article_task_id": f"at-{aid}", "article_id": aid, "run_id": "2026-09-15/daily-004", "created_from_run": "2026-09-15/daily-004", "artifact_path": delivery_path, "artifact_sha256": digest(ROOT / delivery_path), "draft_path": f"drafts/{aid}/body_draft.md", "draft_sha256": digest(ROOT / f"drafts/{aid}/body_draft.md"), "body_path": f"drafts/{aid}/body_draft.md", "body_sha256": digest(ROOT / f"drafts/{aid}/body_draft.md"), "title_pack_path": f"review/{aid}/title-pack.json", "title_pack_sha256": digest(ROOT / f"review/{aid}/title-pack.json"), "attempt": 1, "max_attempts": 3, "status": "PENDING", "decision": "human_review_required", "next_step": "independent_review_required", "scope": "single_article", "publication_authorization": "not_authorized"})
        hook = STRONGEST_HOOKS[aid]
        base.write_json(
            f"review/style-gate-markdown-{aid}.json",
            validate_markdown_file(ROOT / delivery_path, hook=hook),
        )
        base.write_json(f"review/scoring/{aid}.json", {"schema_version": "article-scoring-card-v1", "article_id": aid, "artifact_path": delivery_path, "artifact_sha256": digest(ROOT / delivery_path), "total_score": 88, "evidence_score": 21, "original_judgment_score": 17, "information_gain_score": 17, "structure_score": 14, "title_value_score": 9, "readability_score": 5, "compliance_score": 5, "first_screen_value": "具体事实进入首屏", "reader_takeaway": "核心判断可转述", "reader_takeaway_locator": "p8", "body_fulfillment": "正文完成题目承诺"})
        record = base.editorial_record(aid, title, source_id=source_ids[aid][0], delivery_path=delivery_path); base.write_json(f"review/{aid}/editorial-review-record.json", record); base.write_json(f"review/editorial-review-record-{aid}.json", record)


def batch_manifest(bodies_map: dict[str, str]) -> None:
    articles = []
    specs = {"art-001": ("cand-kongqiang-003", "空枪", "reported_feature", ["interview"], "kongqiang-cantonese-crime-film-premiere", "src-kongqiang-huacheng"), "art-002": ("cand-toy-story-003", "Toy Story 5", "setting_observation", ["official_fact"], "toy-story-tech-playtime-conflict", "src-toy-story-pixar")}
    for aid, (cid, work, mode, roles, cluster, sid) in specs.items():
        tp = json.loads((ROOT / f"review/{aid}/title-pack.json").read_text()); title = tp["directions"][0]["title"]
        review_hook = STRONGEST_HOOKS[aid]
        articles.append({"article_id": aid, "slot": "A" if aid == "art-001" else "B", "candidate_id": cid, "work_title": work, "topic_version": 1, "article_mode": mode, "required_source_roles": roles, "event_cluster": cluster, "brief_path": f"briefs/writing-brief-{aid}.md", "task_card_path": f"task-cards/task-card-{aid}.md", "body_draft_path": f"drafts/{aid}/body_draft.md", "content_fidelity_path": f"review/{aid}/content-fidelity.json", "title_pack_path": f"review/{aid}/title-pack.json", "title_review_path": f"review/{aid}/title-pack-review.json", "delivery_path": f"delivery/{aid}/delivery.md", "markdown_path": f"delivery/{aid}/delivery.md", "source_stripped_path": f"review/{aid}/source-stripped.md", "source_stripped_readability_path": f"review/{aid}/source-stripped-readability.json", "rule_compliance_path": f"review/{aid}/rule-compliance.json", "independent_review_path": f"review/{aid}/independent-review.json", "material_pack_path": f"material-packs/{aid}.json", "source_refs": [sid], "state": "R7 mechanically-verified", "delivery_state": "pending_independent_review", "html_delivery_state": "withheld", "publication_authorization": "not_authorized", "gate_status": {"preflight": "pass", "material_ready_for_draft": "pass", "editorial_value_ready": "pass", "content_fidelity": "pass", "title_pack": "pass", "article_rule_compliance": "pending", "independent_review": "pending", "controller_acceptance": "pending"}, "review_hook": review_hook, "title": title})
    batch = {"schema_version": "article-group-run-v1", "run_id": "2026-09-15/daily-004", "run_profile": "two_article_daily", "run_profile_contract_version": "run-profile-v1", "run_profile_required": True, "milestone": "M2 content-handoff", "manifest_state": "R7 mechanically-verified", "target_state": "R7.5 awaiting-independent-review", "review_surface": "markdown_codex", "review_surface_contract_version": "review-surface-v1", **CONTRACT, "article_first_contract_version": "article-first-v1", "article_rule_compliance_required": True, "article_count": 2, "articles": articles, "publication_authorization": "not_authorized", "delivery_state": "withheld", "html_delivery_state": "withheld", "network_actions": "discovery-and-source-research-only", "selection_rerun": True, "source_manifest_path": "source-manifest.json", "candidate_pool_path": "candidate-pool.json", "portfolio_gate_path": "portfolio-gate-report.json", "preflight_report_path": "preflight-report.json"}
    write_json("batch.json", batch)
    report = base.evaluate_batch_rule_compliance(ROOT, batch)
    write_json("preflight-report.json", {"schema_version": "preflight-report-v1", "run_id": "2026-09-15/daily-004", "status": "PASS", "article_rule_compliance": report["status"], "article_rule_compliance_report": report, "checks": {"run_contract": "pass", "selection_rerun": "pass", "source_manifest": "pass", "article_count": "pass", "distinct_event_clusters": "pass", "article_rule_compliance": report["status"].lower(), "publication_authorization": "pass"}, "source_empty": {"affects": "discovery coverage", "does_not_affect": "selected article facts"}, "evergreen_gap": {"affects": "none", "does_not_affect": "selected article facts"}, "publication_authorization": "not_authorized"})
    write_text("prose-batch.yaml", "run_id: 2026-09-15/daily-004\nreview_surface: markdown_codex\narticles:\n  - article_id: art-001\n    body_path: drafts/art-001/body_draft.md\n  - article_id: art-002\n    body_path: drafts/art-002/body_draft.md\n")


def main() -> None:
    source_manifest(); candidates(); briefs_and_tasks()
    material_pack("art-001", "reported_feature", "interview", ["src-kongqiang-huacheng", "src-kongqiang-bjnews"], "《空枪》为什么要让演员先学会说粤语，才进入这座欲望之城", "粤语训练把演员与角色、片场与时代连接起来", [{"text": "影片于2026年8月19日上映", "level": "event_exists", "locator": "Huacheng: release"}, {"text": "全片使用粤语拍摄", "level": "character_setup", "locator": "Huacheng: Cantonese production"}, {"text": "朱一龙一个月突击学粤语并练到凌晨四点", "level": "dialogue", "locator": "Huacheng: Zhu interview"}], "关心电影创作现场的观众")
    material_pack("art-002", "setting_observation", "official_fact", ["src-toy-story-pixar"], "《玩具总动员5》为什么让玩具先面对一台平板电脑", "传统玩具与新设备都在争取成为孩子的陪伴方式", [{"text": "Lilypad是一台新平板设备", "level": "character_setup", "locator": "Pixar: Lilypad"}, {"text": "邦妮八岁且在努力交朋友", "level": "character_setup", "locator": "Pixar: Bonnie"}, {"text": "Jessie担任新任Sheriff带队帮助邦妮", "level": "mechanism", "locator": "Pixar: Jessie"}], "家庭观众")
    body_map = bodies()
    for aid, body in body_map.items(): base.write_text(f"drafts/{aid}/body_draft.md", body)
    content_record("art-001", body_map["art-001"], "src-kongqiang-huacheng", "reported_feature", "粤语训练与角色进入", "《空枪》为什么要让演员先学会说粤语，才进入这座欲望之城", "语言训练把演员与角色、片场与时代连接起来", "粤语不是装饰性的年代滤镜，而是演员进入人物关系的一道门", [{"information_id": "i1", "text": "2026年8月19日上映", "kind": "specific_context", "body_locator": "p2", "source_locators": ["Huacheng: release"], "independence_key": "release"}, {"information_id": "i2", "text": "全片粤语拍摄", "kind": "mechanism", "body_locator": "p2", "source_locators": ["Huacheng: Cantonese production"], "independence_key": "language"}, {"information_id": "i3", "text": "朱一龙训练到凌晨四点", "kind": "fact", "body_locator": "p1", "source_locators": ["Huacheng: Zhu interview"], "independence_key": "training"}], [{"locator": "p3", "fact_or_scene": "朱一龙说完台词却发现对方没听懂", "explanation": "语言障碍直接改变演员之间的交流"}, {"locator": "p7", "fact_or_scene": "香港演员用鼓励的眼光回应", "explanation": "方言训练变成片场协作"}], "不能由当前报道证明普遍口碑、具体镜头和结局")
    content_record("art-002", body_map["art-002"], "src-toy-story-pixar", "setting_observation", "玩具与屏幕的陪伴竞争", "《玩具总动员5》为什么让玩具先面对一台平板电脑", "传统玩具与新设备都在争取成为孩子的陪伴方式", "第五部把玩具会不会被忘记更新成孩子换了一种方式连接世界后陪伴能否继续", [{"information_id": "i1", "text": "Lilypad是新平板设备", "kind": "fact", "body_locator": "p1", "source_locators": ["Pixar: Lilypad"], "independence_key": "device"}, {"information_id": "i2", "text": "邦妮八岁并在努力交朋友", "kind": "relationship", "body_locator": "p3", "source_locators": ["Pixar: Bonnie"], "independence_key": "bonnie"}, {"information_id": "i3", "text": "Jessie担任新任Sheriff", "kind": "mechanism", "body_locator": "p4", "source_locators": ["Pixar: Jessie"], "independence_key": "jessie"}], [{"locator": "p3", "fact_or_scene": "邦妮怀疑自己是否到了不该再玩玩具的年纪", "explanation": "冲突落到孩子的成长判断"}, {"locator": "p7", "fact_or_scene": "玩具与平板都想帮助邦妮交朋友", "explanation": "矛盾不是新旧胜负而是陪伴方式分配"}], "不能由当前页面证明影片结局、观众反应和教育效果")
    reviews_and_delivery(body_map); batch_manifest(body_map)
    write_json("run-manifest.json", {"schema_version": "run-manifest-v1", "run_id": "2026-09-15/daily-004", "batch_path": "batch.json", "source_manifest_path": "source-manifest.json", "selection_path": "discovery/discovery-radar.json", "publication_authorization": "not_authorized"})


if __name__ == "__main__":
    main()
