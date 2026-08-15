# Editorial Review Record

> `protocol_version: 1.0`。一篇稿件一条记录；每次产生新判断或修订都递增 `record_revision`，保留上一条记录引用。该记录只证明复核范围、证据和交接，不授予发布权限。

- protocol_version: `1.0`
- record_revision: `1`
- supersedes_record_ref:
- run_id:
- article_id:
- publication_authorization: `not_authorized`（固定值；本记录不得包含非空的授权人、授权时间、授权引用或授权范围字段）

## Required Cards

复核记录只引用同一 run root 内已冻结的 JSON 卡片快照；不能直接引用本 Markdown 卡、摘要或绝对路径。
每个引用对象均为 `{path, version, sha256}`：`path` 是相对 run root 的路径，`version` 必须等于
卡片 JSON 的 `card_version`，`sha256` 是该 JSON 文件的完整 SHA-256。

```json
{
  "card_refs": {
    "topic_card": {
      "path": "review/<article_id>/topic-card.json",
      "version": "1.0",
      "sha256": "<64-char-lowercase-sha256>"
    },
    "fact_card": {
      "path": "review/<article_id>/fact-card.json",
      "version": "1.0",
      "sha256": "<64-char-lowercase-sha256>"
    }
  }
}
```

`record_revision=1` 时 `supersedes_record_ref` 必须为空；后续版本必须以相同的
`{path, version, sha256}` 结构引用同一 `run_id`、`article_id` 的上一修订记录。

## Four Stages

每一阶段只能有一个 `objective`。`round` 是该阶段的递增轮次，不得硬编码为 1。若发现属于更早阶段的问题，必须新建记录并回退到对应阶段；不得在当前轮混修。

| stage_id | label | only solves | must not solve | required evidence |
|---|---|---|---|---|
| `project_precheck` | 立项前 | 文章问题、读者、类型、范围 | 写正文、补未核事实、发布授权 | topic card |
| `prewrite` | 写作前 | 可写事实、来源、限制、动态数据截至时间 | 改文风、猜动机、替片方/人物站队 | fact card |
| `postdraft` | 成稿后 | 结构、观点边界、语气、叙事推进 | 新增未核事实、改变事实边界 | draft + edit note |
| `prepublication` | 发布前 | 标题、首屏、来源、数字、时间、链接、页面清理 | 改核心判断、扩大事实范围、发布授权 | final + checklist |

每个 stage object 必填：

```json
{
  "stage_id": "project_precheck",
  "label": "立项前",
  "round": 1,
  "objective": "define_article_scope",
  "objectives": ["define_article_scope"],
  "review_mode": "human",
  "scope": {
    "scope_id": "topic_definition_only",
    "allowed_actions": [
      "define_core_question",
      "define_target_reader",
      "classify_article_type",
      "declare_scope_exclusions"
    ],
    "forbidden_actions": [
      "write_draft",
      "assert_unsourced_fact",
      "authorize_publication"
    ],
    "reader_facing": false,
    "description": "只定义文章问题、读者、类型和边界。"
  },
  "status": "pass",
  "checks": {
    "core_question": "pass",
    "target_reader": "pass",
    "article_type": "pass",
    "scope_exclusions": "pass"
  },
  "evidence_refs": [{"path": "review/<article_id>/topic-card.json", "version": "1.0", "sha256": "<64-char-lowercase-sha256>"}],
  "completed_by": "<editor identity>",
  "completed_at": "YYYY-MM-DDThh:mm:ss+08:00",
  "handoff_to": "prewrite",
  "decision_note": "范围已确定，进入事实边界复核。"
}
```

四个 `stage_id` 的固定合同如下：

| stage_id | objective | review_mode | handoff_to |
|---|---|---|---|
| `project_precheck` | `define_article_scope` | `human` | `prewrite` |
| `prewrite` | `bound_permitted_claims` | `human_and_mechanical` | `postdraft` |
| `postdraft` | `edit_human_writing` | `human` | `prepublication` |
| `prepublication` | `verify_distribution_and_facts` | `human_and_mechanical` | `controller_review` |

每个 stage 的 `scope`、`checks`、允许动作和禁止动作必须与校验器对应阶段合同逐项一致。
状态为 `not_run` 的阶段仍保留 stage 对象，但其 checks 全部为 `not_run`，且不附证据引用。

## Single-Round Pass Ledger

`draft_passes` 按顺序记录 3–4 个生产目标：

- `facts_draft`：只把允许事实写成底稿；
- `editorial_draft`：只处理结构、观点、语气、叙事；
- `recommender_optimization`：只核对标题、首屏与分发承诺；
- `final_prepublication_review`：只核对来源、数字、时间、链接和页面残留。

每条 pass 必填 `pass_id`、正整数 `round`、单一 `objective`、单元素 `objectives`、`stage_id`、`status`、`decision_note`。
顺序固定为 `facts_draft`、`editorial_draft`、可选的 `recommender_optimization`、`final_prepublication_review`；必须包含前三者中的
`facts_draft`、`editorial_draft` 和 `final_prepublication_review`。复核不能在同一 pass 同时处理多个目标。

## Stop-Draft Rule

满足任一条件即停在草稿或证据补充状态：

- 核心问题或范围未定义；
- 关键事实无可回访来源/定位；
- 冲突、否认或动态数据未处理；
- 推测被写成事实，或替片方/人物猜动机、站队；
- 标题、首屏、正文承诺不一致；
- 数字、时间、来源链接或页面编辑残留未清理；
- 当前轮出现多个目标或跨阶段修改；
- 需要发布授权。

停止记录必须填写如下对象；`stage_id` 必须指向实际为 `fail`、`blocked` 或 `stop` 的阶段，不能指向下游 `not_run` 阶段。

```json
{
  "stop_draft": {
    "triggered": true,
    "stage_id": "prewrite",
    "reason_codes": ["stage_failed"],
    "draft_disposition": "hold | revise | archive | reject",
    "evidence_refs": [{"path": "review/<article_id>/fact-card.json", "version": "1.0", "sha256": "<64-char-lowercase-sha256>"}]
  }
}
```

未触发时，`triggered=false`、`stage_id=null`、`reason_codes=[]`、`draft_disposition="continue"`，且不得附停稿证据。
任何失败阶段之后的阶段和对应下游 pass 必须显式 `not_run`。

## Final Handoff

- status: `ready | blocked`
- from_stage:
- to: `controller_review | evidence_intake`
- handoff_at:
- note:
- evidence_refs:

完整通过时 handoff 固定为 `status="ready"`、`from_stage="prepublication"`、`to="controller_review"`；停稿时固定为
`status="blocked"`、`from_stage=<首个非 pass 阶段>`、`to="evidence_intake"`。两种 handoff 都必须有时间、说明和哈希固定证据引用。

CLI 必须显式传入记录和运行根：

```bash
uv run python -m article_group.editorial_review \
  --record runs/<date>/<run>/review/editorial-review-record.json \
  --run-root runs/<date>/<run>
```

仅 `PASS` 返回 exit `0`；结构违规的 `FAIL` 和结构合法但停稿的 `BLOCKED` 均返回非零。`PASS` 只表示记录结构、引用和阶段边界通过；最终采纳、冻结、发布、合并或授权仍由 controller 单独决定。
