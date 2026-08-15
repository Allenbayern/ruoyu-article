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

## Scope

- core_question: （一句话；只允许一个阅读问题）
- target_reader: （具体读者，不写“所有人”）
- article_type: `资讯 | 市场观察 | 人物评论 | 文化评论 | 作品评论 | 其他`
- one_sentence_scope: （本篇只处理什么）
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

## Boundary

- discovery_signals: （热榜/搜索/社媒仅作发现入口）
- prohibited_shortcuts:
  - 不把热度或摘要当作事实证据。
  - 不以标题或旧稿替代正文核验。
- editorial_decision_note:

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
  "out_of_scope": ["<不能写的范围>"],
  "decision": "proceed",
  "stop_reasons": [],
  "decided_by": "<编辑身份>",
  "decided_at": "YYYY-MM-DDThh:mm:ss+08:00"
}
```

`decision=proceed` 时 `stop_reasons` 必须为空；其他决定必须写入至少一个协议
reason code。JSON 快照一旦被复核记录引用，不得原地改写；需要新判断时写新记录并递增
`record_revision`。

## Stage Handoff

- next_stage: `prewrite | evidence_intake | archive | reject`
- handoff_evidence_ref:
- handoff_note:
