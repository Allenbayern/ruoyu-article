import importlib.util
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "scripts" / "run_daily_pipeline.py"


def load_module():
    spec = importlib.util.spec_from_file_location("run_daily_pipeline", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_module_with_backend(backend: str, embedding_enabled: bool = False):
    old_backend = os.environ.get("OPENCLAW_SEMANTIC_BACKEND")
    old_embedding = os.environ.get("OPENCLAW_SEMANTIC_EMBEDDING_ENABLED")
    try:
        os.environ["OPENCLAW_SEMANTIC_BACKEND"] = backend
        os.environ["OPENCLAW_SEMANTIC_EMBEDDING_ENABLED"] = "1" if embedding_enabled else "0"
        return load_module()
    finally:
        if old_backend is None:
            os.environ.pop("OPENCLAW_SEMANTIC_BACKEND", None)
        else:
            os.environ["OPENCLAW_SEMANTIC_BACKEND"] = old_backend
        if old_embedding is None:
            os.environ.pop("OPENCLAW_SEMANTIC_EMBEDDING_ENABLED", None)
        else:
            os.environ["OPENCLAW_SEMANTIC_EMBEDDING_ENABLED"] = old_embedding


def load_module_with_llm_backend(enabled: bool = True):
    old_backend = os.environ.get("OPENCLAW_SEMANTIC_BACKEND")
    old_embedding = os.environ.get("OPENCLAW_SEMANTIC_EMBEDDING_ENABLED")
    old_llm = os.environ.get("OPENCLAW_SEMANTIC_LLM_ENABLED")
    try:
        os.environ["OPENCLAW_SEMANTIC_BACKEND"] = "llm"
        os.environ["OPENCLAW_SEMANTIC_EMBEDDING_ENABLED"] = "0"
        os.environ["OPENCLAW_SEMANTIC_LLM_ENABLED"] = "1" if enabled else "0"
        module = load_module()
        return module
    finally:
        if old_backend is None:
            os.environ.pop("OPENCLAW_SEMANTIC_BACKEND", None)
        else:
            os.environ["OPENCLAW_SEMANTIC_BACKEND"] = old_backend
        if old_embedding is None:
            os.environ.pop("OPENCLAW_SEMANTIC_EMBEDDING_ENABLED", None)
        else:
            os.environ["OPENCLAW_SEMANTIC_EMBEDDING_ENABLED"] = old_embedding
        if old_llm is None:
            os.environ.pop("OPENCLAW_SEMANTIC_LLM_ENABLED", None)
        else:
            os.environ["OPENCLAW_SEMANTIC_LLM_ENABLED"] = old_llm


def make_row(title: str, summary: str = "", source: str = "zhihu", publish_time: str = "2026-06-18") -> dict[str, object]:
    return {
        "title": title,
        "summary": summary,
        "source": source,
        "source_name": source,
        "publish_time": publish_time,
        "rank_date": publish_time,
        "content": summary or title,
    }


def test_gold_cases_pool_expectations():
    mod = load_module()
    cases = [
        (make_row("《凡人修仙传》动画最新两集遭到全网差评，真实原因如何？"), {"S池", "A池"}),
        (make_row("刘昊然、董子健等演员当众求职，程潇坦言档期很空看看我，折射出怎样的影视行业现状？"), {"A池", "S池"}),
        (make_row("26 岁成年人在家做游戏代练被送入戒网瘾机构遭非法拘禁，这件事为什么让人后背发凉？"), {"S池", "A池"}),
        (make_row("马拉松选手猝死后争议不断，责任到底该由谁承担？"), {"S池", "A池"}),
        (make_row("梅西世界杯首秀疑似亮鞋钉踩踏对手小腿，裁判未出牌VAR未介入引争议，这个动作应该被判罚吗？"), {"C池"}),
        (make_row("某剧斩获白玉兰奖，主创发文感谢观众支持"), {"C池"}),
        (make_row("古偶为什么越来越难爆？平台和观众都在抛弃旧套路吗？"), {"C池", "B池"}),
        (make_row("必胜客被卖了，资本腾挪背后释放了什么信号？"), {"C池"}),
        (make_row("SpaceX 上市第三天市值逼近 3 万亿美元，这意味着什么？"), {"C池"}),
    ]
    for row, expected in cases:
        pool, _ = mod.article_pool_decision(row, "2026-06-18")
        assert pool in expected, (row["title"], pool, expected)


def test_admission_gate_expectations():
    mod = load_module()
    jiewangyin = make_row("26 岁成年人在家做游戏代练被送入戒网瘾机构遭非法拘禁，这件事为什么让人后背发凉？")
    pizza = make_row("必胜客被卖了，资本腾挪背后释放了什么信号？")
    jiewangyin_admission = mod.article_admission(jiewangyin, "2026-06-18")
    pizza_admission = mod.article_admission(pizza, "2026-06-18")
    assert jiewangyin_admission["eligible"] is True
    assert jiewangyin_admission["recommended_write_type"]
    assert jiewangyin_admission["mapped_ip"]
    assert pizza_admission["eligible"] is False


def test_today_hook_allowance_expectations():
    mod = load_module()
    jiewangyin = make_row("26 岁成年人在家做游戏代练被送入戒网瘾机构遭非法拘禁，这件事为什么让人后背发凉？")
    pizza = make_row("必胜客被卖了，资本腾挪背后释放了什么信号？")
    assert mod.article_is_today_hook_allowed(jiewangyin, "2026-06-18") is True
    assert mod.article_is_today_hook_allowed(pizza, "2026-06-18") is False


def test_today_hook_blocks_stale_xhs_unix_ms_resonance_sample():
    mod = load_module()
    stale_xhs = make_row(
        "36岁感悟|与其离婚，不如“婚内单身”",
        summary="婚姻 情绪 共鸣 离婚 成年人 故事",
        source="xhs",
        publish_time="1772631333000",
    )
    stale_xhs["rank_date"] = "2026-07-02"

    assert mod.article_parse_publish_datetime(stale_xhs).strftime("%F") == "2026-03-04"
    assert mod.article_freshness_gate(stale_xhs, "2026-07-02") == (False, "超过7天且未标明今日新钩子")
    assert mod.article_has_resonance_core(stale_xhs) is True
    assert mod.article_is_today_hook_allowed(stale_xhs, "2026-07-02") is False


def test_semantic_score_expectations():
    mod = load_module()
    fanren = make_row("《凡人修仙传》动画最新两集遭到全网差评，真实原因如何？")
    meixi = make_row("梅西世界杯首秀疑似亮鞋钉踩踏对手小腿，裁判未出牌VAR未介入引争议，这个动作应该被判罚吗？")
    fanren_semantic = mod.article_semantic_score(fanren)
    meixi_semantic = mod.article_semantic_score(meixi)
    assert fanren_semantic > meixi_semantic
    assert fanren_semantic >= 40


def test_semantic_backend_defaults_to_rules():
    mod = load_module()
    assert mod.get_semantic_backend_name() == "rules"
    row = make_row("《凡人修仙传》动画最新两集遭到全网差评，真实原因如何？")
    scores = mod.article_semantic_signal_scores(row)
    assert scores["backend_unavailable"] == 0
    assert scores["backend_label"] == "rules"
    assert scores["anchor"] >= 12


def test_unknown_semantic_backend_falls_back_to_rules_handler():
    mod = load_module_with_backend("mystery-backend")
    row = make_row("《凡人修仙传》动画最新两集遭到全网差评，真实原因如何？")
    assert mod.get_semantic_backend_name() == "rules"
    scores = mod.article_semantic_signal_scores(row)
    assert scores["backend_label"] == "rules"
    assert scores["backend_unavailable"] == 0


def test_semantic_embedding_backend_available():
    mod = load_module_with_backend("embedding", embedding_enabled=True)
    row = make_row("《凡人修仙传》动画最新两集遭到全网差评，真实原因如何？")
    scores = mod.article_semantic_signal_scores(row)
    assert mod.get_semantic_backend_name() == "embedding"
    assert scores["backend_label"] in {"embedding", "embedding-fallback-rules"}
    assert scores["backend_unavailable"] in {0, 1}
    if scores["backend_unavailable"] == 0:
        assert scores["conflict"] >= 1 or scores["analysis"] >= 1 or scores["emotion"] >= 1


def test_semantic_llm_backend_enabled_falls_back_to_ruleish_scores():
    mod = load_module_with_llm_backend(enabled=True)
    row = make_row("《凡人修仙传》动画最新两集遭到全网差评，真实原因如何？")
    scores = mod.article_semantic_signal_scores(row)
    assert mod.get_semantic_backend_name() == "llm"
    assert scores["backend_label"] in {"llm", "llm-fallback-rules"}
    assert scores["conflict"] >= 10
    assert scores["analysis"] >= 8


def test_semantic_llm_backend_disabled_stays_stubbed():
    mod = load_module_with_llm_backend(enabled=False)
    row = make_row("《凡人修仙传》动画最新两集遭到全网差评，真实原因如何？")
    scores = mod.article_semantic_signal_scores(row)
    assert mod.get_semantic_backend_name() == "rules"
    assert scores["backend_unavailable"] == 0
    assert scores["conflict"] >= 10


def test_openai_embedding_backend_path():
    mod = load_module_with_backend("embedding", embedding_enabled=True)
    row = make_row("《凡人修仙传》动画最新两集遭到全网差评，真实原因如何？")
    assert mod.SEMANTIC_EMBEDDING_CONFIG.get("provider") == "openai"
    assert mod.SEMANTIC_EMBEDDING_CONFIG.get("model")
    scores = mod.article_semantic_signal_scores(row)
    assert scores["backend"] in {0, 1}
    assert scores["backend_unavailable"] in {0, 1}


def test_embedding_adversarial_pairs():
    mod = load_module_with_backend("embedding", embedding_enabled=True)
    pairs = [
        ("某剧扑街了", "某剧糊穿了地心"),
        ("顶流糊了", "影帝查无此人"),
    ]
    rows = []
    for left, right in pairs:
        left_row = make_row(left)
        right_row = make_row(right)
        left_scores = mod.article_semantic_signal_scores(left_row)
        right_scores = mod.article_semantic_signal_scores(right_row)
        rows.append((left, left_scores["conflict"], left_scores["analysis"], left_scores["emotion"]))
        rows.append((right, right_scores["conflict"], right_scores["analysis"], right_scores["emotion"]))
    print("ADVERSARIAL_EMBEDDING_SCORES")
    for title, conflict, analysis, emotion in rows:
        print(f"- {title}\tconflict={conflict}\tanalysis={analysis}\temotion={emotion}")
    assert any(conflict > 0 or analysis > 0 or emotion > 0 for _, conflict, analysis, emotion in rows)


def test_semantic_alias_normalization_keeps_adversarial_phrases_close():
    mod = load_module_with_backend("embedding", embedding_enabled=True)
    left = mod._semantic_embed_text("某剧扑街了", 24)
    right = mod._semantic_embed_text("某剧糊穿了地心", 24)
    distant = mod._semantic_embed_text("新能源车主换回燃油车", 24)
    close_score = mod._semantic_similarity(left, right)
    distant_score = mod._semantic_similarity(left, distant)
    assert close_score > distant_score
    assert close_score >= 0.75


def test_semantic_normalize_text_maps_known_aliases():
    mod = load_module()
    normalized = mod.semantic_normalize_text("顶流糊了，某剧也糊穿了地心，观众都说彻底凉了")
    assert "扑街" in normalized
    assert "糊穿了地心" not in normalized


def test_low_quality_article_candidates_build_executable_retry_request():
    mod = load_module()
    weak_article = make_row(
        "某剧发布普通海报，粉丝表示期待播出",
        summary="常规宣发物料，没有争议、结构或今天非写不可的理由。",
        source="douban",
    )

    retry_plan = mod.build_retry_request([weak_article], [], [], "2026-06-18")

    assert retry_plan["retry_required"] is True
    assert retry_plan["status"] == "retry_request"
    assert retry_plan["targets"]
    assert {"douban_group", "xhs", "zhihu", "wechat"}.issubset(set(retry_plan["runnable_flags"]))
    assert retry_plan["queries"]
    assert any("某剧" in query for query in retry_plan["queries"])



def test_article_lane_retry_request_ignores_story_only_gaps():
    mod = load_module()
    strong_article = make_row(
        "《开推4》最新讨论很热，观众争议不断：站队、反转、荒诞到上头，为什么吵到热搜",
        summary="观众站队和关系冲突很强，平台热度变化明确，评论区高赞观点充分，今天非写不可。",
        source="douban",
    )
    story_candidate = make_row("普通物料，没有真实叙事母本", source="douban")

    retry_plan = mod.build_retry_request([strong_article], [story_candidate], [], "2026-06-18", lane="article")

    assert "B站" not in retry_plan["targets"]
    assert "抖音" not in retry_plan["targets"]
    assert "小红书故事向" not in retry_plan["targets"]
    assert "bilibili" not in retry_plan["runnable_flags"]
    assert "douyin" not in retry_plan["runnable_flags"]


def test_retry_refetch_loop_re_scores_and_keeps_retry_request_when_still_weak():
    mod = load_module()
    weak_article = make_row("某剧发布普通海报，粉丝表示期待播出", source="douban")
    refetched_article = make_row("某剧主演转发海报，继续表示期待", source="xhs")

    result = mod.run_article_retry_loop(
        [weak_article],
        [],
        [],
        "2026-06-18",
        lambda retry_request: [refetched_article],
    )

    assert result["status"] == "retry_request"
    assert result["retry_request"]["retry_required"] is True
    assert result["initial_retry_request"]["retry_required"] is True
    assert result["refetched_count"] == 1
    assert result["article_rows"] == [weak_article, refetched_article]


def test_reference_only_high_score_keeps_risk_reason_but_can_enter_mainline():
    mod = load_module()
    row = make_row(
        "《开推4》最新讨论很热，观众争议不断：站队、反转、荒诞到上头，为什么吵到热搜",
        summary="参考层里热度不错，观众站队和关系冲突很强，普通人代入后又想骂又想看，但还需要补今天为什么写它的证据、平台热度变化和评论区高赞。",
        source="zhihu",
    )
    row.update({
        "routing_tier": "reference_only",
        "fit_article_group": False,
        "article_route_reason": "参考层来源，需补平台/评论/热度证据后再二审",
        "content": "有正文证据",
    })

    admission = mod.article_admission(row, "2026-06-18")
    approved = mod.build_article_approved("2026-06-18", [row])
    structured_review = mod.build_article_structured_review([row], "2026-06-18")
    today_hook_md, today_hook_rows = mod.build_today_hook_dispatch("2026-06-18", [row])

    retry_plan = mod.build_retry_request([row], [], [], "2026-06-18")

    assert admission["risk_reason"]
    profile = mod.candidate_profile(row, "article")
    assert profile["topic_score"] >= 75
    assert mod.article_writer_readiness(row, "2026-06-18") in {"main_article_ready", "write_ready_candidate"}
    assert mod.article_is_whitelist_eligible(row, "2026-06-18") is True
    assert "参考层" in admission["risk_reason"] or "证据" in admission["risk_reason"]
    assert "## 今日文章补证据队列" in approved
    assert "topic_score=" in approved
    assert "## 今日文章角度短名单" in approved
    assert "开推4" in approved
    assert "## S池（基础/生产双高）" in approved
    assert "### 文章候选 1" in structured_review
    assert today_hook_rows
    assert "## 今日钩子候选" in today_hook_md
    assert retry_plan["status"] in {"ok", "retry_request"}


def test_zhihu_403_backfill_marks_retry_request_instead_of_terminal_blocked():
    mod = load_module()
    row = make_row("知乎问题二跳正文待补，评论区也还没抓到", source="zhihu")
    row.update({"url": "https://www.zhihu.com/question/123456789", "candidate_title": row["title"]})

    retry_plan = mod.build_retry_request([row], [], [], "2026-06-18")
    assert retry_plan["retry_required"] is True
    assert "zhihu" in retry_plan["runnable_flags"]
    assert retry_plan["status"] == "retry_request"


def test_incubation_feedback_mentions_second_review_and_evidence_gaps():
    mod = load_module()
    row = make_row(
        "《主角》相关讨论热度上来了，但还缺今天的讨论证据",
        summary="需要补评论区高赞观点和平台热度变化。",
        source="zhihu",
    )
    row.update({
        "routing_tier": "reference_only",
        "fit_article_group": False,
        "article_route_reason": "参考层来源，需补平台/评论/热度证据后再二审",
    })

    approved = mod.build_article_approved("2026-06-18", [row])
    assert "补发布时间或原始出处" not in approved
    assert "补二跳正文、评论区高赞观点或可核验数据" in approved or "补今天为什么写它的理由" in approved
    assert "人工二审 / 补证据后可写" in approved
    assert "《主角》" in approved


def test_article_lane_default_sources_do_not_reopen_video_sources_or_write_video_approved(tmp_path, monkeypatch):
    mod = load_module()
    commands = []

    def fake_run_json_command(name, command, cwd=None):
        commands.append((name, list(command)))
        return mod.StepResult(name=name, status="OK", detail={})

    monkeypatch.setattr(mod, "run_json_command", fake_run_json_command)
    monkeypatch.setattr(
        mod,
        "run_article_retry_loop",
        lambda article_rows, story_rows, media_rows, date, refetch, lane="all": {
            "status": "ok",
            "article_rows": article_rows,
            "retry_request": {"retry_required": False, "targets": [], "reason": ""},
            "refetched_count": 0,
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_daily_pipeline.py",
            "--lane",
            "article",
            "--date",
            "2026-07-02",
            "--output-root",
            str(tmp_path),
            "--dailyhot-article",
            "__DISABLED_FOR_TEST__",
        ],
    )

    assert mod.main() == 0

    command_names = [name for name, _command in commands]
    assert "douban_collect" in command_names
    assert "xhs_note_collect" not in command_names
    assert "zhihu_collect" not in command_names
    assert "video-approved-latest.md" not in {path.name for path in tmp_path.iterdir()}
    assert (tmp_path / "article-approved-latest.md").exists()


if __name__ == "__main__":
    test_gold_cases_pool_expectations()
    test_admission_gate_expectations()
    test_today_hook_allowance_expectations()
    test_semantic_score_expectations()
    test_semantic_backend_defaults_to_rules()
    test_semantic_embedding_backend_available()
    test_semantic_llm_backend_enabled_falls_back_to_ruleish_scores()
    test_semantic_llm_backend_disabled_stays_stubbed()
    test_openai_embedding_backend_path()
    test_embedding_adversarial_pairs()
    test_semantic_alias_normalization_keeps_adversarial_phrases_close()
    test_semantic_normalize_text_maps_known_aliases()
    print("ok")
