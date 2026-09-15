# Article Independent Review Attempt

> `schema_version: article-independent-review-v1`。按单篇记录，超时不能当作通过。

`codex-review-contract-1.0` 的 normal 记录是仓库代码审查证据；即使它写入
`status=PASS`、`decision=review_completed`，也不能代替本记录的文章独立复核。文章独立
复核必须另写本 schema，并使用 `approve` 等明确批准决策及当前产物绑定。

- article_task_id:
- article_id:
- artifact_path: （当前被复核的文章 artifact）
- artifact_sha256: （创建复核记录时计算）
- body_path: （当前 body_draft 路径）
- body_sha256: （创建复核记录时计算）
- title_pack_path: （当前 title_pack 路径）
- title_pack_sha256: （创建复核记录时计算）
- created_from_run: （当前 run_id）
- draft_path:
- draft_sha256: （当前稿件版本）
- attempt: `1`
- max_attempts: `3`
- status: `UNVERIFIED | complete`
- decision: `timeout | evidence_insufficient | approve | needs_changes`
- timeout_reason: （仅超时/UNVERIFIED）
- next_step: `resume_single_article | retry_narrowed_review | stop`
- scope: `single_article`
- l2_required: `true | false`
- l2_risk_basis: （只有需要 L2 时填写具体风险，不能只写“按惯例 L2”）
- publication_authorization: `not_authorized`

超时后只续审当前这一篇和当前稿件哈希，不重跑整批。达到次数上限后停止，保持 `UNVERIFIED`。
提交复核时必须重新计算上述 hash；任一路径、run_id 或 hash 不一致均标记为 `stale_review`，不能靠备注放行。
