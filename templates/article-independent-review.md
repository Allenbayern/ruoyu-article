# Article Independent Review Attempt

> `schema_version: article-independent-review-v1`。按单篇记录，超时不能当作通过。

- article_task_id:
- article_id:
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
