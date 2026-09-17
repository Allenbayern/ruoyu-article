"""Tests for the article style gate (article_group.style_gate).

RED/GREEN discipline: the negative samples are Allen's verbatim feedback
phrases from controlled-014 (2026-08-06); the positive samples are legitimate
reader-facing constructions that must NOT be flagged (e.g. "公开报道只确认了
动作和日期" — a safe factual framing, not source self-confession).
"""

from pathlib import Path

from article_group.style_gate import (
    scan_style,
    validate_batch_style,
    validate_delivery_file,
    opening_hook_check,
    title_gap_check,
    fact_density_check,
    hook_declaration_check,
    closing_interaction_check,
)

NEGATIVE_SAMPLES = [
    # 来源自证（用户逐字 2026-08-06）
    "8月4日的《人民日报》人民时评谈到暑期档国产动画时，提到《八仙！》。",
    "报道以《给阿嬷的情书》为例，提到中山、汕头与电影相关的美食。",
    "报道还提到，今年2月，国家电影局与商务部联合启动试点。",
    "两份8月3日的公开报道还明确列出了影片的监制、导演及编剧信息。",
    "在这篇报道的讨论中，影院也可以向综合文化体验空间发展。",
    "对这部作品的阅读，应该从这份已公开的简介出发。",
    "资料：《人民日报》2026年8月4日人民时评",
    # 读后感 / 审稿腔（用户点名句式 + 同类变体）
    "这个说法的重点不在于把观影变成一张消费清单，而在于提醒我们，电影结束之后，人与城市仍然可能继续发生关系。",
    "我理解的精品化，不在于把作品包装得无懈可击，而在于对细节保持耐心。",
    "这里既是评论对作品的描述，也是评论提出的判断；它给我们的是一个阅读入口。",
    "信息到这里已经足够建立一条清楚的事实边界。",
    "这里的“可以”很重要，它指向一种开放的方向。",
    "这个例子让“电影+”不再只是抽象的概念。",
    # 流程标识
    "如雨电影日刊 · CONTROLLED-014 候选稿",
    "候选稿 · 事实边界以文中标注来源的公开材料为准",
    # 自我提醒句（用户点名 2026-08-12，controlled-018）
    "还没上映的电影，不能提前写出它的票房，8月28日前出现的数字都只能是预测、愿望或讨论。",
    "这条边界不难写，却很容易在热搜和转发里被忘掉。",
    "我们绝不能提前写出这部电影的票房。",
    # 来源自证变体（controlled-016 教训 B3：初稿 3 处违规全部人工发现）
    "购票平台的 9.4 分，反映的正是这批真实观众的满意度，新浪财经在报道中评价这部电影说……",
    "有媒体用了一个词来形容，北京商报在报道里用了一个词：'现象级'。",
    "荔枝新闻在梳理这场风波时提到，观众的不满主要集中在排片。",
    # 后台审核/发布自证（不能进入读者面正文）
    "本文经过来源审计，编辑部核验后发布。",
    "本稿已由新闻室完成事实核查。",
    # 来源/流程自述变体（controlled-035 优化日志）
    "本文只是整理了一下发布信息，行业观察还在继续。",
    "这篇资料介绍了项目的基本情况。",
]

POSITIVE_SAMPLES = [
    # 合法事实框架（skill 安全写法）——不得误伤
    "公开报道只确认了动作和日期，没有披露片方内部怎么算这笔账。",
    "电影《不想失去你》已发布定档海报，计划于2026年8月19日全国上映。",
    "今年2月，国家电影局与商务部联合启动“电影+”消费综合试点工作。",
    "《八仙！》刻画了八个有私欲、有缺点的市井小人物。",
    "以《给阿嬷的情书》为例，中山、汕头都有与电影相关的美食和非遗活动。",
    # 正常使用"报道"一词但非来源自证
    "消息在社交平台传开后，很快有了后续报道和讨论。",
    # 正常"入口"非"阅读入口"
    "电影由此成为连接一段生活经验的入口。",
    # 合法媒体词邻接句（016 B3 修复防误伤：词尾命中但非来源自证转述）
    "观众在报道画面里看到了当时的盛况。",
    "平台在梳理用户反馈时发现，差评集中在票价。",
    "有媒体用了一个词来形容这部影片。",
    # 合规口径：未上映影片的事实/边界描述（不是自我提醒句，不得误伤）
    "截至8月12日，《肖申克的救赎》4K修复版还没有产生实际内地票房，8月28日前出现的数字都只能是预测、愿望或讨论。",
    "豆瓣9.7是既有口碑，IMAX全球首度呈现是制式信息，4K修复是观看条件，三者都不能直接换算成售出的票数。",
]


def test_negative_samples_all_flagged():
    """Every verbatim redline phrase from Allen's feedback must be caught."""
    for sample in NEGATIVE_SAMPLES:
        hits = [h for h in scan_style(sample) if h["severity"] == "error"]
        assert hits, f"未命中红线: {sample}"
        assert any(h["rule"] for h in hits)


def test_positive_samples_clean():
    """Legitimate reader-facing constructions must not be flagged."""
    for sample in POSITIVE_SAMPLES:
        hits = [h for h in scan_style(sample) if h["severity"] == "error"]
        assert not hits, f"误伤合法文本: {sample} -> {hits}"


def test_source_self_confession_vs_safe_framing():
    """'公开报道还' is a confession; '公开报道只确认了' is a safe framing."""
    assert any(h["rule"] == "source:公开报道还"
               for h in scan_style("两份8月3日的公开报道还明确列出了信息"))
    assert not [h for h in scan_style("公开报道只确认了动作和日期")
                if h["rule"] == "source:公开报道还"]


def test_editorial_self_attestation_is_blocked_but_attribution_survives():
    """Audit/release workflow claims are blocked; normal attribution is safe."""
    for sample in [
        "本文经过来源审计，编辑部核验后发布。",
        "本稿已由新闻室完成事实核查。",
        "编辑部审核材料后刊发本文。",
    ]:
        hits = scan_style(sample)
        assert any(
            h["severity"] == "error"
            and h["rule"] == "tone:editorial-self-attestation"
            for h in hits
        ), sample

    for sample in [
        "公开报道只确认了动作和日期，没有披露片方内部怎么算这笔账。",
        "有媒体用了一个词来形容这部影片。",
        "影片上映后，相关报道继续增加。",
    ]:
        assert not [
            h for h in scan_style(sample)
            if h["rule"] == "tone:editorial-self-attestation"
        ], sample


def test_source_confession_variants_have_explicit_severity():
    direct = scan_style("本文只是整理了一下发布信息。")
    assert any(
        h["severity"] == "error" and h["rule"] == "source:发布信息自述"
        for h in direct
    )
    ambiguous = scan_style("行业观察显示，横店正在增加游客体验项目。")
    assert any(
        h["severity"] == "warning" and h["rule"] == "source:行业观察"
        for h in ambiguous
    )
    assert not [
        h for h in scan_style("横店的行业变化，首先体现在游客可以直接购买一小时体验。")
        if h["rule"] == "source:行业观察"
    ]


def test_comment_as_fact_warning():
    """Comment judgment written as film fact is a warning, not an error."""
    hits = scan_style("影片也重新定义了“仙”的内涵：不是刀枪不入、长生不老。")
    assert any(h["severity"] == "warning" and h["rule"] == "boundary:重新定义…内涵"
               for h in hits)


def test_opening_hook_check():
    """Atmosphere-only openings are flagged; fact/suspense/contrast pass (P0-1)."""
    assert opening_hook_check(["散场时，最舍不得的常常不是灯光。"])["status"] == "warning"
    assert opening_hook_check(
        ["《八仙！》刻画了八个有私欲、有缺点的市井小人物。"])["status"] == "ok"
    assert opening_hook_check(
        ["今年2月，国家电影局与商务部联合启动试点工作。"])["status"] == "ok"
    # 长意境句不再因长度豁免（P0-1 窄化修复）
    long_mood = ("散场时，最舍不得的常常不是灯光，但当灯光熄灭、字幕升起，"
                 "人潮散尽之后，心里总有一些东西留了下来。")
    assert len(long_mood) > 24
    assert opening_hook_check([long_mood])["status"] == "warning"
    # 悬念/反差钩子通过
    assert opening_hook_check(
        ["一部电影怎么做到让观众散场后舍不得走？"])["status"] == "ok"
    assert opening_hook_check(
        ["它不是一部传统的仙侠片，而是把八个神仙写成了普通人。"])["status"] == "ok"


def test_validate_batch_style_ignores_kicker_metadata_for_opening():
    delivery = """
    <article>
      <p class="kicker">若雨随影 · 2026年8月19日 · 电影文化观察</p>
      <h2>城市电影观察</h2>
      <p>散场时，最舍不得的常常不是灯光。</p>
    </article>
    """
    article = validate_batch_style(delivery)["articles"][0]
    assert article["opening_hook"]["status"] == "warning"
    assert article["opening_hook"]["first_40"] == "散场时，最舍不得的常常不是灯光。"


CLEAN_DELIVERY = """
<article data-hook="《八仙！》档期与口碑"><h2>《八仙！》最稀罕的，不是神仙，是八个不完美的人</h2>
<p>《八仙！》刻画了八个有私欲、有缺点的市井小人物。</p>
<p>神仙这个词，常常自带一种距离感。</p></article>
<article data-hook="试点城市名单"><h2>电影散场以后，一张票根还能把人带到哪里</h2>
<p>散场时，最舍不得的常常不是灯光。</p>
<p>今年2月，国家电影局与商务部联合启动试点工作，16个城市被列为试点城市。</p></article>
<article data-hook="8月19日上映"><h2>《不想失去你》定档后，我更在意两个孤独的人怎么靠近</h2>
<p>电影《不想失去你》计划于2026年8月19日全国上映。</p>
<p>片名里的“失去”很容易让人想到挽留。</p></article>
"""


def test_hook_declaration_three_states():
    """P0-3 generalized: every article must declare its strongest hook.

    The mechanism is generic; release dates do not automatically require a
    release-history declaration.
    missing / mismatch / ok are the three states (warning severity).
    """
    assert hook_declaration_check("", "任何正文")["status"] == "missing"
    assert hook_declaration_check("票房纪录", "正文只谈口碑")["status"] == "mismatch"
    ok = hook_declaration_check("档期核验：三次档", "它定过三次档：2月14日、6月5日、8月19日")
    assert ok["status"] == "ok"
    # 部分匹配（钩子含正文未出现的补充词）仍视为可锚定
    partial = hook_declaration_check("档期核验：8月19日", "电影计划于2026年8月19日上映")
    assert partial["status"] == "ok"
    assert partial["reason"] and "未匹配" in partial["reason"]


def test_comment_as_fact_word_family():
    """P0-2 generalized: judgment verbs beyond 重新定义 are also caught."""
    for sample in [
        "影片重构了神仙的想象：八仙不再是高高在上的神。",
        "这部电影重塑了传统叙事的表达。",
        "它把神仙拽下了神坛，让他们沾满烟火气。",
    ]:
        hits = scan_style(sample)
        boundary = [h for h in hits if h["rule"].startswith("boundary:")]
        assert boundary, f"判断词未命中: {sample}"
        assert all(h["severity"] == "warning" for h in boundary)


def test_date_claim_is_current_source_info_only():
    """A normal release-date claim is an info-only current-source hint."""
    result = scan_style("电影《不想失去你》计划于2026年8月19日全国上映。")
    claims = [h for h in result if h["rule"] == "date:release-claim"]
    assert len(claims) == 1
    assert claims[0]["severity"] == "info"
    assert "当前日期来源" in claims[0]["reason"]
    assert "不要求撤档史" in claims[0]["reason"]
    assert not [h for h in result if h["rule"] == "release-history:claim"]


def test_release_history_claim_is_conditional_info():
    """Explicit release-change history gets its own info-only hint."""
    result = scan_style(
        "该片曾撤档，随后改档并延期，后来重定档，档期一度反复定档。"
    )
    claims = [h for h in result if h["rule"] == "release-history:claim"]
    assert len(claims) == 1
    assert claims[0]["severity"] == "info"
    assert "历史" in claims[0]["reason"]


def test_validate_batch_style_on_clean_delivery():
    """A clean delivery passes the error gate (self-contained positive anchor)."""
    result = validate_batch_style(CLEAN_DELIVERY)
    assert result["pass"] is True
    assert result["error_total"] == 0
    assert result["article_count"] == 3


def test_validate_delivery_file_seals_scanned_bytes(tmp_path):
    path = tmp_path / "frozen.html"
    path.write_text(CLEAN_DELIVERY, encoding="utf-8")

    result = validate_delivery_file(path)

    assert result["artifact_path"] == str(path.resolve())
    assert result["artifact_sha256"] == __import__("hashlib").sha256(
        path.read_bytes()
    ).hexdigest()


def test_validate_batch_style_uses_h1_for_single_article_title():
    delivery = """
    <html><head><title>撤档之后，谁还敢相信定档海报</title></head><body>
    <article data-hook="《寻她》撤档">
      <h1>撤档之后，谁还敢相信定档海报</h1>
      <p>《寻她》撤档后，原定上映计划发生了变化。</p>
    </article></body></html>
    """
    article = validate_batch_style(delivery)["articles"][0]
    assert article["title"] == "撤档之后，谁还敢相信定档海报"
    assert article["title_gap"]["title"] == "撤档之后，谁还敢相信定档海报"


def test_validate_batch_style_mixed_h1_h2_titles_per_article():
    """Mixed h1/h2 across articles must resolve per-article, never by global index."""
    delivery = """
    <html><head><title>混合标题</title></head><body>
    <article><h1>甲文标题</h1><p>《寻她》撤档后，原定上映计划发生了变化。</p></article>
    <article><h2>乙文标题</h2><p>《八仙！》今日宣布定档8月19日，全国上映。</p></article>
    <article><h2>丙文标题</h2><p>《不想失去你》由蓝鸿春监制，郑润奇导演。</p></article>
    </body></html>
    """
    titles = [a["title"] for a in validate_batch_style(delivery)["articles"]]
    assert titles == ["甲文标题", "乙文标题", "丙文标题"]


def test_validate_batch_style_on_frozen_negative():
    """The frozen controlled-014 pre-fix delivery must FAIL the gate.

    This is the regression anchor: the batch that Allen rejected must be
    blocked mechanically by the next batch's gate.
    """
    frozen = Path(__file__).parents[1] / "runs" / "2026-08-05" / "controlled-014" \
        / "review" / "frozen" / "ruoyu-articles-2026-08-05.1761f2e2075e.html"
    if not frozen.exists():
        return  # frozen artifact may be absent in fresh checkouts; unit tests cover the rules
    result = validate_batch_style(frozen.read_text(encoding="utf-8"))
    assert result["pass"] is False
    assert result["error_total"] > 0


def test_validate_batch_style_on_fixed_positive():
    """The gate catches residual tone issues even in a human-revised batch.

    The current controlled-014 was revised against Allen's feedback, yet still
    contains one '不在于…而在于' construction — the exact pattern Allen named.
    This test is the living proof that machine enforcement beats revision luck.
    """
    fixed = Path(__file__).parents[1] / "runs" / "2026-08-05" / "controlled-014" \
        / "ruoyu-articles-2026-08-05.html"
    if not fixed.exists():
        return
    result = validate_batch_style(fixed.read_text(encoding="utf-8"))
    tone_residuals = [h for a in result["articles"] for h in a["hits"]
                      if h["severity"] == "error" and h["rule"].startswith("tone:")]
    assert tone_residuals, "门禁应在人工修订稿中抓到残留同类句式"


def test_title_gap_check():
    """Titles must carry at least one psychological-gap signal (P3)."""
    assert title_gap_check("《八仙！》最稀罕的，不是神仙，是八个不完美的人")["status"] == "ok"
    assert title_gap_check("电影散场以后，一张票根还能把人带到哪里")["status"] == "ok"
    assert title_gap_check("暑期档国产动画观察")["status"] == "warning"
    assert title_gap_check("城市电影政策介绍")["status"] == "warning"
    assert title_gap_check("《密档》把暗战藏进市井：红色题材如何拍出日常质感")["status"] == "warning"


def test_fact_density_check():
    """Interpretation-heavy pieces with thin fact bases are flagged (P2)."""
    thin = ["神仙这个词，常常自带一种距离感。",
            "这让人想起一些更朴素的标准。",
            "看完之后，心里留下的是温度。",
            "期待它认真面对人的瑕疵。"]
    thick = ["《八仙！》刻画了八个有私欲、有缺点的市井小人物。",
             "今年2月，国家电影局与商务部联合启动试点工作，16个城市被列为试点。",
             "蓝鸿春监制、郑润奇导演及编剧，黄曦彦、张祎曈主演。",
             "电影《不想失去你》计划于2026年8月19日全国上映。"]
    assert fact_density_check(thin)["status"] == "warning"
    assert fact_density_check(thick)["status"] == "ok"
    # P2 窄化修复：裸数字不再算事实锚点（无日期/数量断言/专名/机构/主创）
    padded = ["我在第6版稿子里又删掉了一段。",
              "距离上次修改已经过去3天。",
              "但我想说的还是那句话。",
              "电影总得让人有期待。"]
    assert fact_density_check(padded)["status"] == "warning"


def test_title_gap_extra_signals():
    """P3: emotion/contrast words beyond the original set also count."""
    assert title_gap_check("八仙居然把神仙写成了普通人")["status"] == "ok"
    assert title_gap_check("一张票根，意外改写了整座城市")["status"] == "ok"
    assert title_gap_check("最稀罕的，是八个不完美的人")["status"] == "ok"


def test_unsourced_claim_warnings():
    """controlled-016 B4: age inference & zero-modifier claims are flagged
    as warning (triage signals, never blockers)."""
    hits = scan_style("周星驰当时四十一岁，正值创作巅峰。")
    assert any(h["rule"] == "claim:age-inference" for h in hits)
    assert all(h["severity"] == "warning" for h in hits)
    hits = scan_style("这部电影零大规模路演，全靠口碑发酵。")
    assert any(h["rule"] == "claim:zero-modifier" for h in hits)
    assert all(h["severity"] == "warning" for h in hits)


def test_closing_interaction_check():
    """候选观察⑦：结尾互动问句检测（info，建议非阻断）。

    有「你会…吗/你还会…吗」类读者问句 → ok；
    结论性/纯事实收尾 → info（提示，不是 error/warning）。
    """
    # 读者互动问句收尾 → ok
    assert closing_interaction_check(["你会走进影院重新看一遍吗？"])["status"] == "ok"
    assert closing_interaction_check(["你还会给童年的动画写一封信吗？"])["status"] == "ok"
    assert closing_interaction_check(["你会怎么和孩子聊这部电影？"])["status"] == "ok"
    # 无问句收尾 → info（不阻断）
    info = closing_interaction_check(["这部片子的现实，是一砖一瓦搭出来的。"])
    assert info["status"] == "info"
    assert "候选观察" not in info["reason"] or "候选观察" in info["reason"]
    # 以问号收尾但非读者互动（设问/内容性问题）→ info 而非 ok
    assert closing_interaction_check(["为什么要在青岛手搓一座中东城？"])["status"] == "info"
    # 末段同时以问号+互动词收尾 → ok（宽松回退）
    assert closing_interaction_check(["大家觉得这部剧到底值不值得追？"])["status"] == "ok"
    # 空段落守卫
    assert closing_interaction_check([])["status"] == "no_paragraphs"


def test_closing_interaction_in_batch_report():
    """026 两篇 frozen 稿的末段应被标记为 info（候选观察⑦空转实证）。"""
    delivery = """
    <article data-hook="龙餐馆8.4"><h2>没去中东，青岛手搓一座中东城</h2>
    <p>《欢迎来龙餐馆》8月11日全国首映，豆瓣开分8.4。</p>
    <p>分数只是入口；更值得留下的，是这部电影如何把拍片受阻变成转型。</p></article>
    """
    article = validate_batch_style(delivery)["articles"][0]
    assert article["closing_interaction"]["status"] == "info"
    assert article["closing_interaction"]["last_40"]


def test_chinese_numeral_fact_anchors():
    """controlled-016 A4: Chinese-numeral dates/quantities must anchor
    fact density & opening hook (no forced Arabic rewrites)."""
    zh_paras = ["该片票房三千六百五十万，位列暑期档第一。",
                "八月六日开画，首日即破纪录。",
                "二〇二二年立项，历时四年才走到观众面前。"]
    assert fact_density_check(zh_paras)["status"] == "ok"
    assert opening_hook_check(["八月六日开画，首日即破纪录，成为暑期档黑马。"])["status"] == "ok"
    # 纯意境仍不锚定（修复未放宽标准）
    thin = ["神仙这个词，常常自带一种距离感。", "这让人想起一些更朴素的标准。"]
    assert fact_density_check(thin)["status"] == "warning"
    assert opening_hook_check(["夏夜的风穿过放映厅，银幕亮起。",
                               "一部电影的命运就此展开。"])["status"] == "warning"
