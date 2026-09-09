# Topic Card

> 立项前唯一用途：定义这篇文章要回答的问题。此卡不是事实包，也不是写作提纲。

- card_version: `1.0`
- card_type: `topic_card`
- run_id:
- article_id:
- decided_by:
- decided_at: `YYYY-MM-DDThh:mm:ss+08:00`
- decision: `proceed | hold | waiting_source | reject`
- stop_reasons: `[]`（若 decision 不是 `proceed`，至少填写一项）
- editorial_lessons_ref: `docs/codex/editorial-lessons.md`（历史经验参考；不把历史文章当作当前事实证据）

## Scope

- core_question: （一句话；只允许一个阅读问题）
- target_reader: （具体读者，不写“所有人”）
- article_type: `资讯 | 市场观察 | 人物评论 | 文化评论 | 作品评论 | 其他`
- one_sentence_scope: （本篇只处理什么）
- freshness_window: `same-day | fermenting-1-3d | revival`
- topic_mode: `release_event | character | craft | audience | culture | revisit | market`
- event_cluster_id: （同一事件流/事件簇共享一个 id；不同作品同属一个簇不算独立选题）
- remove_timestamp_test: `pass | risk | fail`
- out_of_scope:
  - （未确认事实、动机、票价、传播数据、人物心理等不得写入正文的项目）

## Intake Decision

- why_now: （为什么现在值得回答，最多三句）
- reader_takeaway: （读者读完能带走什么）
- human_anchor: （人物/作品/具体处境）
- conflict_or_gap: （冲突、反差或信息缺口）
- evidence_gap:
- backup_switch_condition:
- risk_tags:
- current_trigger_or_evergreen_reason: （即时/发酵题记录触发与观察时间；revival 题记录脱离当天热度仍成立的读者问题）

## Historical Topic Dedupe

以下是编辑补充记录，使用实际比较结果填写；不新增机器放行或豁免权限。

- historical_dedupe_ref: （比较同作品、同事件簇和近似标题的历史记录；引用 `docs/codex/editorial-lessons.md` 时同时写明具体 run/path）
- same_work_recent_check: `pass | override | blocked`
- title_near_duplicate_check: `pass | override | blocked`
- new_angle_statement: （本篇新增的事实、具体场景、人物关系或读者问题；只换标题不算新角度）
- override_reason: （仅 `override` 时填写理由、对比批次和核验人）

## Boundary

- discovery_signals: （热榜/搜索/社媒仅作发现入口）
- prohibited_shortcuts:
  - 不把热度或摘要当作事实证据。
  - 不以标题或旧稿替代正文核验。
- editorial_decision_note:
- timing_boundary: （same-day/fermenting 需要当前触发和后续重核；revival 不暗示当下热度，若使用当前事实仍须重核）

## Validator JSON Snapshot

本 Markdown 是供编辑填写的来源卡。进入 `prewrite` 前，必须在同一 run root 下
保留逐字段对应的 JSON 快照，例如
`review/<article_id>/topic-card.json`。校验器只读取该 JSON；复核记录的
`card_refs.topic_card` 必须使用 `{path, version, sha256}` 引用对象，其中 `version`
必须等于该 JSON 的 `card_version`，不能引用本 Markdown 或摘要文字。

```json
{
  "card_version": "1.0",
  "card_type": "topic_card",
  "run_id": "<run_id>",
  "article_id": "<article_id>",
  "core_question": "<一句话核心问题>",
  "target_reader": "<目标读者>",
  "article_type": "<文章类型>",
  "one_sentence_scope": "<只处理什么>",
  "freshness_window": "same-day",
  "topic_mode": "release_event",
  "event_cluster_id": "<事件簇>",
  "remove_timestamp_test": "pass",
  "out_of_scope": ["<不能写的范围>"],
  "decision": "proceed",
  "stop_reasons": [],
  "decided_by": "<编辑身份>",
  "decided_at": "YYYY-MM-DDThh:mm:ss+08:00",
  "current_trigger_or_evergreen_reason": "<即时触发或常青理由>",
  "historical_dedupe_ref": "<比较记录路径>",
  "same_work_recent_check": "pass",
  "title_near_duplicate_check": "pass",
  "new_angle_statement": "<相对历史选题新增的事实/场景/问题>",
  "override_reason": "",
  "title_promise": "<标题承诺>",
  "title_evidence_ref": "<标题事实证据路径/定位>",
  "opening_fulfillment_plan": "<首屏兑现计划>"
}
```

`decision=proceed` 时 `stop_reasons` 必须为空；其他决定必须写入至少一个协议
reason code。上面新增的时效与历史排重字段保持向后兼容；进入批次前应填写并在快照中保留，
但不把历史经验或热榜信号升级为事实证据；这里的 `override` 仅记录编辑判断，不代替机器闸门要求的 controller 裁决。JSON 快照一旦被复核记录引用，不得原地改写；
需要新判断时写新记录并递增 `record_revision`。

当前校验器仍主要机械检查基础 topic-card 字段；时效、历史排重、标题证据和首屏兑现字段
必须在编辑记录与交付清单中显式核对，不能把快照存在本身视为这些检查已通过。

## Stage Handoff

- next_stage: `prewrite | evidence_intake | archive | reject`
- handoff_evidence_ref:
- handoff_note:
- title_promise:
- title_evidence_ref:
- opening_fulfillment_plan: （标题承诺在首屏落到哪个可核验事实/页面细节/人物处境）
