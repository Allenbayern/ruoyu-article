# Article Editorial Judgment

> `schema_version: article-editorial-judgment-v1`。四阶段记录结构通过之后，另做编辑判断。字数不是通过理由。

- article_task_id:
- article_id:
- article_first_contract_version: `article-first-v1`
- body_draft_path: `drafts/<article_id>/body_draft.md`
- body_sha256:
- content_fidelity_ref: `{path, sha256}`
- content_fidelity_result: `pass | return_article | return_material`
- structure_result: 来自四阶段记录
- judgment_result: `pass | return_research | fail`

只有成稿 `body_draft.md` 通过 `article-content-fidelity-v1` 后，才能填写
`reader_takeaway`。它是正文复核后的读者获得判断，不是写作前的标题兑现目标。

## Actor Layers

必须分列，不能互相替代：

- machine_check.by / result
- model_editorial_review.by / result / paragraph_notes[`locator`, `note`]
- human_confirmation.by / result / attestation_ref

`review_mode=human` 或 `completed_by=editorial-protocol-record` 都不是真人确认。真人通过必须有独立签字引用。

## Section Increments

每个正文部分说明：增加了什么材料、推进了什么判断、与上一节有什么不同。

- section_id:
- locator:
- added_material:
- advanced_judgment:
- difference_from_previous:
- increment_kind: `fact | scene | action | relationship | mechanism | specific_context | judgment | restatement`
- supporting_material_ids:

相同事实换词复述写成 `restatement`，不能当作通过。人物动机或观众共识没有材料时不能通过。

## Findings And Scoring

编辑意见必须引用当前稿件段落。允许结论为“材料不足，退回研究”。

- findings: `{locator, defect, basis, action}`
- scoring_evidence.total_score
- scoring_evidence.why_worth_reading: `{locator, argument}`
- reader_takeaway:
- reader_takeaway_locator: （必须回到正文段落）

高分没有段落级“为什么值得读”的论据，不能当作编辑通过。正文不得出现内部核验口吻。
