# Candidate Card

- candidate_id:
- batch_id:
- state: `R1 normalized-candidates`
- scan_at:
- event_time:
- first_seen_at:

## Subject

- work:
- person_or_org:
- event:
- freshness_window: `same-day | fermenting-1-3d | revival`
- content_map: `A 新片事件 | B 作品深度 | C 文化现象 | D 人物争议`（批次组合校验用，见 portfolio_gate）
- topic_mode: `release_event | character | craft | audience | culture | revisit | market`（叙事入口，非题材标签）
- event_cluster_id: （同一事件流/事件簇共享一个 id；不同作品同属一个簇不算独立选题）
- reader_question: （去掉时间戳后仍成立的读者问题，即 durable_reader_question）
- remove_timestamp_test: `pass | risk | fail`（删掉“今天/8月5日/热搜第一”等时间与排名信息后，正文还剩什么？剩读者问题/人物/冲突→pass；只剩事件→fail）
- editorial_value_score: `1-5`（内容价值：读者问题×叙事潜力×人物锚点，独立于时效）
- evidence_readiness: `high | medium | low`（当前证据是否足够写；低价值高就绪≠值得写，高价值低就绪≠不值得写）

## Signal

- source_url:
- publisher:
- source_role: `discovery | audience-reaction | confirmed-primary | confirmed-secondary | structured-data`
- independence_group:
- signal_summary:
- source_level: `headline-only | full-text | primary | structured-data`

## Editorial Intake

- potential_primary_atom:
- human_anchor:
- conflict_emotion_gap:
- reader_intent:
- why_now:
- risk_tags:
- denial_or_conflict_status:
- evidence_gap:
- recommendation: `A | B | C | Archive | Reject | Wait`
- reason:

## Five Gates（社会热点必填，影视文章填 N/A）

- five_gates_result: `PASS | CONDITIONAL | FAIL | N/A`
- gate1_news_license: `PASS | CONDITIONAL | FAIL`
- gate2_privacy: `PASS | CONDITIONAL | FAIL`
- gate3_judicial: `PASS | CONDITIONAL | FAIL`
- gate4_copyright: `PASS | CONDITIONAL | FAIL`
- gate5_sensationalism: `PASS | CONDITIONAL | FAIL`
- compliant_angle: （仅 `CONDITIONAL` 且推荐 `A | B | C` 时必填；说明可追溯的改角度/改写约束）
- fail_reason: （`FAIL` 时必填）
- fail_disposition: `Archive | Reject | Wait`（`FAIL` 不得推荐 `A | B | C`；可留档，不连坐整池）

## Batch Portfolio（批次组合校验，见 `article_group/portfolio_gate.py`）

单卡通过不等于批次健康。选中进批后必须满足（机器校验，warning/error 分级）：

- 每批 3 篇覆盖 ≥2 个 `content_map` 象限；同象限 ≤2 篇。
- 同 `event_cluster_id` 每批 ≤1 篇；连续 3 批同一簇为主线 ≤2 批。
- 时间窗口优先组合：`same-day`（即时）1 篇 + `fermenting-1-3d`（发酵）1 篇 + `revival`（常青/翻红）1 篇；无合格候选时允许空缺（记 `evergreen_gap: true`），不强行凑数。
- 每篇必填 `remove_timestamp_test`；`fail`（去掉时间戳只剩事件）不得连续两批占据主稿位。
- 证据就绪 ≠ 值得写：`editorial_value_score` 与 `evidence_readiness` 分开记录；仅就绪高但价值低的候选不得因“好写”入选。
