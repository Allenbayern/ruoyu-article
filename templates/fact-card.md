# Fact Card

> 写作前唯一用途：规定什么能写、什么不能写。每条可写事实都必须能回到来源和定位；本卡不承担文风修改。

- card_version: `1.0`
- card_type: `fact_card`
- run_id:
- article_id:
- decided_by:
- decided_at: `YYYY-MM-DDThh:mm:ss+08:00`
- decision: `ready_for_draft | waiting_source | draft_only | stop`
- stop_reasons: `[]`

## Confirmed Facts

| claim_id | claim | claim_type | source_ids | limitation |
|---|---|---|---|---|
| claim-001 |  | `fact | attributed_view | inference` |  |  |

## Sources

| source_id | URL | publisher/author | source_level | locator | accessed_at |
|---|---|---|---|---|---|
| src-001 |  |  | `primary | fulltext | structured-data` |  | `YYYY-MM-DDThh:mm:ss+08:00` |

## Permitted And Prohibited

- permitted_claim_ids:
- prohibited_claims:
  - claim:
    reason:
- coverage_gaps:
  - `none` or explicit gap with affected claim
- unresolved_conflicts:
  - `none` or explicit conflict and handling status

## Dynamic Data

- data_as_of: （所有票房、票数、排片、热度等动态数据必须填写截至时间）
- update_required_before_publication: `yes | no`
- update_trigger:

## Boundary Rules

- 事实、他人观点、编辑推论分开记录。
- 可作分析的事实必须明确推断边界，不写成片方意图或人物心理事实。
- 无来源、无定位或冲突未处理的材料不得将 decision 设为 `ready_for_draft`。

## Validator JSON Snapshot

本 Markdown 是事实边界的编辑工作卡。进入 `postdraft` 前，必须在同一 run root 下
保留逐字段对应的 JSON 快照，例如
`review/<article_id>/fact-card.json`。校验器只读取该 JSON；复核记录的
`card_refs.fact_card` 必须使用 `{path, version, sha256}` 引用对象，其中 `version`
必须等于该 JSON 的 `card_version`。

```json
{
  "card_version": "1.0",
  "card_type": "fact_card",
  "run_id": "<run_id>",
  "article_id": "<article_id>",
  "sources": [
    {
      "source_id": "src-001",
      "url": "https://<source>",
      "locator": "<正文定位>",
      "source_level": "primary | fulltext | structured-data",
      "accessed_at": "YYYY-MM-DDThh:mm:ss+08:00"
    }
  ],
  "permitted_claims": [
    {
      "claim_id": "claim-001",
      "claim": "<可写断言>",
      "claim_type": "fact | attributed_view | inference | attribution",
      "source_ids": ["src-001"],
      "limitation": "<不得外推的边界>"
    }
  ],
  "prohibited_claims": [{"claim": "<不能写的断言>", "reason": "<原因>"}],
  "coverage_gaps": [],
  "unresolved_conflicts": [],
  "data_as_of": "YYYY-MM-DDThh:mm:ss+08:00",
  "update_required_before_publication": "yes",
  "update_trigger": "<何时必须重查动态数据>",
  "decision": "ready_for_draft",
  "stop_reasons": [],
  "decided_by": "<事实编辑身份>",
  "decided_at": "YYYY-MM-DDThh:mm:ss+08:00"
}
```

当 `decision=ready_for_draft` 时，`sources` 和 `permitted_claims` 不能为空，
每个可写断言必须回指已有 `source_id`；未解决冲突、无来源或需要停稿时必须改为非
`ready_for_draft` 的决定，并写入至少一个协议 reason code。JSON 快照被引用后不可
原地改写。

## Handoff

- next_stage: `postdraft | evidence_intake | archive | reject`
- handoff_evidence_ref:
- handoff_note:
