import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_live():
    path = ROOT / "scripts" / "article_production_live_run.py"
    spec = importlib.util.spec_from_file_location("live_1905_editorial_packet", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_batch():
    path = ROOT / "scripts" / "run_experimental_article_candidate_batch.py"
    spec = importlib.util.spec_from_file_location("batch_1905_editorial_packet", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ANCHOR = {"subject_id": "36372941", "title": "森中有林 (2026)", "url": "https://movie.douban.com/subject/36372941/"}
PAGES = [
    ("https://www.1905.com/mdb/film/2258502/info/", "info"),
    ("https://www.1905.com/news/20260413/1758006.shtml", "news"),
    ("https://www.1905.com/news/20260506/1759260.shtml", "news"),
    ("https://www.1905.com/news/20260325/1756861.shtml", "news"),
]


def test_verified_1905_direct_editorial_registry_entries_are_explicit_and_finite():
    mod = load_live()
    expected = {
        "37379599": {
            "url": "https://www.1905.com/mdb/film/2259045/",
            "chinese_title": "10间敢死队",
            "year": "2026",
            "expected_release_dates": ["2026-05-01"],
            "editorial_pages": [
                ("https://www.1905.com/news/20260426/1758826.shtml", "news"),
                ("https://www.1905.com/news/20260428/1758914.shtml", "news"),
                ("https://www.1905.com/news/20260508/1759383.shtml", "news"),
            ],
        },
        "37242440": {
            "url": "https://www.1905.com/mdb/film/2258463/",
            "chinese_title": "惊蛰无声",
            "year": "2026",
            "editorial_pages": [
                ("https://www.1905.com/news/20260219/1755042.shtml", "news"),
                ("https://www.1905.com/news/20260220/1755058.shtml", "news"),
                ("https://www.1905.com/news/20260220/1755067.shtml", "news"),
            ],
        },
    }

    for subject_id, contract in expected.items():
        mapping = mod.SAME_WORK_1905_REGISTRY[subject_id]
        assert mapping["url"] == contract["url"]
        assert mapping["chinese_title"] == contract["chinese_title"]
        assert mapping["year"] == contract["year"]
        if "expected_release_dates" in contract:
            assert mapping["expected_release_dates"] == contract["expected_release_dates"]
        else:
            assert "expected_release_dates" not in mapping
        assert [(page["url"], page["page_type"]) for page in mapping["editorial_pages"]] == contract["editorial_pages"]
        assert len([page for page in mapping["editorial_pages"] if page["page_type"] == "news"]) >= 3


def test_editorial_fact_class_accepts_attributed_creator_national_sentiment_quote_as_theme():
    mod = load_live()

    claim = "张艺谋表示，希望能把这样一个带有家国情怀的好故事，传递给大家。"

    assert mod._1905_editorial_fact_class(claim) == "theme"


def page_html(url: str, page_type: str, *, canonical: str | None = None, identity=True, date="2026-05-01") -> str:
    identity_text = "森中有林 All The Good Eyes 2026 于和伟 韩庚 高圆圆" if identity else "无关作品 2026 于和伟"
    fact_text = [
        "于和伟与韩庚介绍演员阵容和表演选择，提供可核验的表演信息，并说明两人的表演如何推动故事的关键转折与情感冲突。",
        "剧组说明镜头调度、拍摄方法与创作流程，提供可核验的制作信息，并具体交代在森林场景中完成调度和表演配合的工作方法。",
        "报道交代角色关联、叙事冲突与故事推进，提供可核验的剧情信息，并描述人物在森林环境下面临的选择如何影响后续发展。",
        "导演郑执表示：“森林意象服务于人物的情感结构。”报道记录其对自然空间映照人物内心变化的明确说明。",
    ]
    facts = "".join(f"<p>事实{i}：{fact_text[(i - 1) % 4]} 这是第{i}条独立直接报道细节。</p>" for i in range(1, 14))
    work_link = '<a href="https://www.1905.com/mdb/film/2258502/">森中有林</a>'
    root = f'<div class="secondary-wrapper-w1200">{work_link}{facts}</div>' if page_type == "info" else f'<div id="contentNews" class="mod-content"><h1>{identity_text}</h1>{work_link}{facts}</div>'
    return f'<html><head><link rel="canonical" href="{canonical or url}"><meta property="article:published_time" content="{date}T10:00:00+08:00"></head><body>{root}</body></html>'


def test_editorial_packet_scopes_to_unique_roots_and_rejects_noise_and_unclassified_copy(monkeypatch):
    mod = load_live()

    def fake_fetch(url, **_kwargs):
        kind = "info" if "/mdb/" in url else "news"
        body = page_html(url, kind)
        release = "2026年5月23日正式上映" if kind == "info" else "2026年5月1日上映"
        body = body.replace("</div></body>", f"<p>影片将于{release}。</p></div></body>")
        noise = '<footer><p>ICP备案号 返回顶部 fr=footer</p></footer><div class="mod-relNews"><p>相关阅读：宣传夸词震撼来袭，观众一致好评。</p></div>'
        return {"url": url, "html": body.replace("</body>", noise + "</body>")}

    monkeypatch.setattr(mod, "_fetch_html_url", fake_fetch)
    result = mod.fetch_1905_same_work_editorial_packet(ANCHOR)
    assert result["success"] is True
    claims = [atom["claim"] for atom in result["evidence_atoms"]]
    assert not any(token in " ".join(claims) for token in ("ICP备案", "返回顶部", "fr=", "相关阅读", "震撼", "好评"))
    assert all(atom["fact_class"] in {"cast", "production", "plot_character", "release", "theme"} for atom in result["evidence_atoms"])
    assert all({"source_text", "source_locator"} <= atom.keys() for atom in result["evidence_atoms"])


def test_editorial_packet_fails_closed_when_root_is_missing_or_ambiguous(monkeypatch):
    mod = load_live()
    url, kind = PAGES[0]
    valid = page_html(url, kind)
    missing = valid.replace('class="secondary-wrapper-w1200"', 'class="other"')
    monkeypatch.setattr(mod, "_fetch_html_url", lambda _url, **_kwargs: {"url": _url, "html": missing})
    assert mod.fetch_1905_same_work_editorial_packet(ANCHOR)["success"] is False

    ambiguous = valid.replace('</body>', '<div class="secondary-wrapper-w1200"><p>重复正文根</p></div></body>')
    monkeypatch.setattr(mod, "_fetch_html_url", lambda _url, **_kwargs: {"url": _url, "html": ambiguous})
    assert mod.fetch_1905_same_work_editorial_packet(ANCHOR)["success"] is False


def test_release_dates_use_release_sentence_not_published_at(monkeypatch):
    mod = load_live()

    def fake_fetch(url, **_kwargs):
        kind = "info" if "/mdb/" in url else "news"
        release = "2026年5月23日" if kind == "info" else "2026年5月1日"
        html = page_html(url, kind, date="2026-04-13")
        html = html.replace('</div></body>', f'<p>影片将于{release}正式上映。</p></div></body>')
        return {"url": url, "html": html}

    monkeypatch.setattr(mod, "_fetch_html_url", fake_fetch)
    result = mod.fetch_1905_same_work_editorial_packet(ANCHOR)
    assert result["success"] is True
    assert result["conflicting_time_sensitive_fact"] == {"release_date": ["2026-05-01", "2026-05-23"]}
    assert "2026-04-13" not in result["conflicting_time_sensitive_fact"]["release_date"]


def test_release_dates_apply_published_year_only_to_yearless_release_sentences(monkeypatch):
    mod = load_live()

    def fake_fetch(url, **_kwargs):
        kind = "info" if "/mdb/" in url else "news"
        release = "2026年5月23日正式上映" if kind == "info" else "5月1日上映"
        page_date = "2026-04-13" if url.endswith("1758006.shtml") else "2026-05-06"
        html = page_html(url, kind, date=page_date)
        html = html.replace('</div></body>', f'<p>报道发布于2026.04.13，影片将于{release}。</p></div></body>')
        return {"url": url, "html": html}

    monkeypatch.setattr(mod, "_fetch_html_url", fake_fetch)
    result = mod.fetch_1905_same_work_editorial_packet(ANCHOR)
    assert result["success"] is True
    assert result["conflicting_time_sensitive_fact"] == {"release_date": ["2026-05-01", "2026-05-23"]}
    assert "2026-04-13" not in result["conflicting_time_sensitive_fact"]["release_date"]


def test_editorial_packet_fails_closed_for_unmapped_canonical_and_identity(monkeypatch):
    mod = load_live()
    assert mod.fetch_1905_same_work_editorial_packet({"subject_id": "no", "title": "森中有林 (2026)", "url": "https://movie.douban.com/subject/no/"})["success"] is False

    url, kind = PAGES[0]
    monkeypatch.setattr(mod, "_fetch_html_url", lambda _url, **_kwargs: {"url": url, "html": page_html(url, kind, canonical="https://www.1905.com/wrong/")})
    assert mod.fetch_1905_same_work_editorial_packet(ANCHOR)["success"] is False

    monkeypatch.setattr(mod, "_fetch_html_url", lambda _url, **_kwargs: {"url": url, "html": page_html(url, kind, identity=False)})
    assert mod.fetch_1905_same_work_editorial_packet(ANCHOR)["success"] is False


def test_editorial_packet_fails_closed_when_live_release_dates_violate_acceptance_contract(monkeypatch):
    mod = load_live()
    calls = []

    def fake_fetch(url, **_kwargs):
        calls.append(url)
        kind = "info" if "/mdb/" in url else "news"
        # Distinct release-date claims cause the time-sensitive field to be withheld.
        extra = "<p>影片将于2026年5月1日上映。</p>" if url.endswith("1758006.shtml") else "<p>影片将于2026年6月1日上映。</p>"
        return {"url": url, "html": page_html(url, kind).replace("</div></body>", extra + "</div></body>")}

    monkeypatch.setattr(mod, "_fetch_html_url", fake_fetch)
    result = mod.fetch_1905_same_work_editorial_packet(ANCHOR)
    assert result["success"] is False
    assert calls == [url for url, _ in PAGES]
    assert "release-date acceptance contract" in result["error"]


def test_export_and_batch_require_full_direct_editorial_packet_contract(tmp_path):
    live = load_live()
    batch = load_batch()
    atoms = [
        {"claim": f"事实{i}：于和伟和韩庚在第{i}个创作环节讨论角色关系、森林意象、镜头调度与表演方法，形成可引用的具体报道事实。", "url": url, "page_type": kind, "published_at": "2026-05-01", "fact_class": ("cast" if i % 4 == 0 else "production" if i % 4 == 1 else "plot" if i % 4 == 2 else "theme"), "characters": 100}
        for i, (url, kind) in enumerate(PAGES * 4, start=1)
    ][:12]
    packet = {"source_id": "1905_same_work_editorial_packet", "source_name": "1905 editorial", "signal_role": "article_body_signal", "narrative_roles": ["plot_character_context"], "success": True, "live_subject": ANCHOR, "evidence_atoms": atoms, "packet_contract": {"qualifies_long_form": True, "direct_url_count": 4, "news_body_count": 3, "deduped_fact_count": 12, "fact_character_count": sum(a["characters"] for a in atoms), "fact_class_count": 4}}
    rows = live.export_backfill_article_rows([packet])
    assert len(rows) == 12
    assert all(row["evidence_atom"]["url"] == row["url"] for row in rows)
    result = batch.run_batch(tmp_path / "packet.json", live_rows=rows, use_live_evidence=True)
    assert not result["article_candidate_buckets"]["A"]
    candidate = result["article_candidate_buckets"]["C"][0]
    assert candidate["write_readiness"] == "long_form_direct_editorial_packet"
    assert candidate["editorial_packet_ready"] is True
    assert candidate["ready_for_publish"] is False
    assert len(candidate["writer_atoms"]) == 12

    short_rows = rows[:1]
    rejected = batch.run_batch(tmp_path / "short.json", live_rows=short_rows, use_live_evidence=True)
    assert not rejected["article_candidate_buckets"]["A"]
    rejected_candidate = rejected["article_candidate_buckets"]["C"][0]
    assert rejected_candidate["editorial_packet_ready"] is False
    assert rejected_candidate["writer_atoms"] == []


def test_direct_packet_does_not_relax_generic_source_or_role_gates(tmp_path):
    live = load_live()
    batch = load_batch()
    atoms = [
        {"claim": f"事实{i}：于和伟和韩庚讨论角色关系、森林意象、镜头调度与表演方法，形成可引用的具体报道事实。",
         "url": url, "page_type": kind, "published_at": "2026-05-01",
         "fact_class": ("cast" if i % 4 == 0 else "production" if i % 4 == 1 else "plot" if i % 4 == 2 else "theme"),
         "characters": 100}
        for i, (url, kind) in enumerate(PAGES * 4, start=1)
    ][:12]
    packet = {"source_id": "1905_same_work_editorial_packet", "source_name": "1905 editorial", "signal_role": "article_body_signal", "narrative_roles": ["plot_character_context"], "success": True, "live_subject": ANCHOR, "evidence_atoms": atoms, "packet_contract": {"qualifies_long_form": True}}
    rows = live.export_backfill_article_rows([packet])
    result = batch.run_batch(tmp_path / "generic-gates.json", live_rows=rows, use_live_evidence=True)
    candidate = result["article_candidate_buckets"]["C"][0]
    assert "requires_at_least_2_distinct_sources" in candidate["publish_block_reasons"]
    assert "requires_at_least_2_article_body_social_discussion_audience_reaction_roles" in candidate["publish_block_reasons"]


def test_collect_editorial_packet_is_opt_in_and_exact_subject_only(monkeypatch):
    mod = load_live()
    anchor = ANCHOR
    other = {"subject_id": "other", "title": "别的作品 (2026)", "url": "https://movie.douban.com/subject/other/"}
    audience = [
        {"success": True, "source_id": "douban_reviews_discussions", "signal_role": "audience_reaction_signal", "live_subject": anchor, "top_signals": [{"title": "森中有林短评", "description": "这是一条超过二十字的具体观众讨论，用于请求路径测试。", "url": "https://example.test/a"}]},
        {"success": True, "source_id": "douban_reviews_discussions", "signal_role": "audience_reaction_signal", "live_subject": other, "top_signals": [{"title": "别的作品短评", "description": "这是一条超过二十字的具体观众讨论，用于请求路径测试。", "url": "https://example.test/b"}]},
    ]
    calls = []
    monkeypatch.setattr(mod, "fetch_audience_reaction_signals", lambda subject_limit=mod.DOUBAN_LIVE_SUBJECT_LIMIT: audience)
    monkeypatch.setattr(mod, "fetch_bilibili_same_work_enrichment", lambda _subject: {"success": False})
    monkeypatch.setattr(mod, "fetch_1905_same_work_context", lambda _subject: {"success": True})
    monkeypatch.setattr(mod, "fetch_1905_same_work_editorial_packet", lambda subject: calls.append(subject["subject_id"]) or {"success": False})
    for name in ("fetch_article_body_signal", "fetch_weibo_entertainment_hotsearch_signal", "fetch_weibo_topic_search_signal", "fetch_zhihu_movie_hot_topics_signal", "fetch_bilibili_movie_zone_hot_signal", "fetch_xiaohongshu_movie_notes_signal", "fetch_douyin_movie_hot_signal"):
        monkeypatch.setattr(mod, name, lambda: {"success": False})

    mod.collect_live_backfill_rows()
    assert calls == []
    mod.collect_live_backfill_rows(requested_editorial_packet_subject_ids={"36372941"})
    assert calls == ["36372941"]


def test_packet_presence_leaves_generic_candidate_gate_fields_unchanged(tmp_path):
    batch = load_batch()
    ordinary = [
        {"source": "audience", "title": "《森中有林》讨论", "content": "观众围绕人物选择与森林意象出现持续具体的讨论和分歧。", "url": "https://example.test/a", "signal_role": "audience_reaction_signal", "work_key": "douban:36372941", "work_title": "森中有林"},
        {"source": "official", "title": "森中有林", "content": "电影《森中有林》围绕具体人物的关键选择与剧情危机展开。", "url": "https://example.test/o", "signal_role": "article_body_signal", "work_key": "douban:36372941", "work_title": "森中有林"},
    ]
    atom = {"claim": "于和伟与韩庚介绍演员阵容和表演选择，提供可核验的表演信息和具体创作细节。", "url": PAGES[0][0], "page_type": "info", "published_at": "2026-05-01", "fact_class": "cast", "characters": 50}
    packet_row = dict(ordinary[0], source="1905_same_work_editorial_packet", content=atom["claim"], url=atom["url"], evidence_atom=atom, direct_editorial_packet_contract={"qualifies_long_form": True})
    base = batch.run_batch(tmp_path / "base.json", live_rows=ordinary, use_live_evidence=True)["article_candidate_buckets"]["C"][0]
    with_packet = batch.run_batch(tmp_path / "packet.json", live_rows=ordinary + [packet_row], use_live_evidence=True)["article_candidate_buckets"]["C"][0]
    for key in ("tier", "score", "ready_for_publish", "evidence_bundle_status", "publish_block_reasons"):
        assert with_packet[key] == base[key]
