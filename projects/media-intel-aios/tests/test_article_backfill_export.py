from scripts import article_production_live_run as live


def test_export_backfill_article_rows_falls_back_when_query_does_not_match():
    source_results = [
        {
            "source_id": "weibo_entertainment_hotsearch",
            "source_name": "微博文娱热搜 live signal",
            "signal_role": "social_discussion_signal",
            "success": True,
            "top_signals": [
                {
                    "title": "《长安的荔枝》为什么让观众吵起来",
                    "summary": "评论区围绕角色选择和剧情改编出现分裂",
                    "url": "https://example.invalid/topic/1",
                    "rank": 1,
                    "hot_score": 9876,
                }
            ],
        }
    ]

    rows = live.export_backfill_article_rows(source_results, query="完全不匹配的查询")

    assert len(rows) == 1
    assert rows[0]["source"] == "weibo_entertainment_hotsearch"
    assert rows[0]["body_fetch_status"] == "live_signal_backfill"
    assert rows[0]["content"]


def test_export_backfill_article_rows_handles_string_sample_signals():
    source_results = [
        {
            "source_id": "douban_reviews_discussions",
            "source_name": "豆瓣短评/讨论 live signal",
            "signal_role": "audience_reaction_signal",
            "success": True,
            "sample_signals": ["《痴迷》短评样本显示：从始至终最恐怖的其实是男主"],
        }
    ]

    rows = live.export_backfill_article_rows(source_results, query="不存在")

    assert len(rows) == 1
    assert rows[0]["source"] == "douban_reviews_discussions"
    assert rows[0]["title"].startswith("《痴迷》")
    assert rows[0]["rank"] == 1


def test_export_backfill_article_rows_ignores_market_only_sources():
    source_results = [
        {
            "source_id": "maoyan_realtime_boxoffice",
            "source_name": "猫眼专业版实时票房",
            "signal_role": "market_signal",
            "success": True,
            "top_signals": [{"title": "票房第一"}],
        }
    ]

    assert live.export_backfill_article_rows(source_results, query="票房") == []


def test_export_backfill_article_rows_preserves_shared_douban_work_key_for_same_work_context():
    source_results = [
        {
            "source_id": "douban_reviews_discussions",
            "source_name": "豆瓣短评/讨论 live signal",
            "signal_role": "audience_reaction_signal",
            "success": True,
            "live_subject": {"subject_id": "1234567", "title": "痴迷 Obsession(2025)", "url": "https://movie.douban.com/subject/1234567/"},
            "top_signals": [{"title": "《痴迷》短评", "description": "观众围绕角色选择的具体争议持续出现。", "url": "https://movie.douban.com/subject/1234567/comments"}],
        },
        {
            "source_id": "letterboxd_work_context",
            "source_name": "Letterboxd同作品页面剧情上下文",
            "signal_role": "article_body_signal",
            "success": True,
            "live_subject": {"subject_id": "1234567", "title": "痴迷 Obsession(2025)", "url": "https://movie.douban.com/subject/1234567/"},
            "top_signals": [{"title": "Obsession (2025)", "description": "A sufficiently long same-work plot and character description for the article body.", "url": "https://letterboxd.com/film/obsession-2025/"}],
        },
    ]

    rows = live.export_backfill_article_rows(source_results)

    assert {row["work_key"] for row in rows} == {"douban:1234567"}
    assert {row["work_identity"] for row in rows} == {"douban:1234567"}
