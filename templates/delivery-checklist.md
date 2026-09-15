# Delivery Checklist

- article_id:
- batch_id:
- state: `brief_locked | drafting_content | content_review | content_passed | title_packaging | title_review | final_review | delivered`
- editorial_lessons_ref: `docs/codex/editorial-lessons.md`（历史经验参考；不替代当前来源、门禁或授权判断）

## Intake And Historical Dedupe

- [ ] Topic-card JSON snapshot is present under the current run root and its path/version/SHA-256 are recorded in the review record.
- [ ] `freshness_window`, `topic_mode`, `event_cluster_id` and `remove_timestamp_test` agree with the candidate card and batch portfolio result.
- [ ] For `same-day`/`fermenting-1-3d`, the current trigger, observation time and revalidation boundary are recorded; for `revival`, the durable reader question and evergreen reason are recorded without implying current heat.
- [ ] Historical comparison covers the same work, event cluster and near-duplicate titles; `new_angle_statement` names a new fact, concrete scene, relationship or reader question. A title wording change alone does not pass. Historical titles are comparison evidence only.
- [ ] A `same_work_recent_check` or `title_near_duplicate_check` marked `override` includes the reason, comparison run/path and verifier; `blocked` does not enter writing.

## Content

- [ ] Specific work, person, event, or conflict remains central.
- [ ] Primary Atom is singular and fulfilled.
- [ ] At least three independently supported hard-information items appear, from at least two of `fact | scene | action | relationship | mechanism | specific_context`; a reader paraphrase is not a hard information item.
- [ ] Each hard-information item has a body locator, source locator, and unique independence key; no item is the same fact rewritten.
- [ ] Chinese character count uses the style-gate CJK count; 1500–2200 is the usual target, with a 1000–2700 flexible acceptance band when the article is complete and readable.
- [ ] Each major paragraph adds a fact, scene, action, relationship, mechanism, specific context, or judgment; repeated conclusions are returned instead of padded.
- [ ] The title-free body identifies the object, problem, explanation, and judgment through body locators; `body_draft.md` contains no H1.
- [ ] `reader_takeaway` is written after content review and points to an actual body locator; it is not a prewrite title target.
- [ ] The outline uses only as many evidence-backed turns as the article needs; empty optional reversal fields are allowed and no third reversal is added for format compliance.
- [ ] The ending is either an evidence-backed reader question, a conclusion, or deliberately has no question; a question is not required for engagement metrics.
- [ ] No internal editorial, source, or growth terminology leaks into reader text.

## Title Packaging After Content Pass

- [ ] `title_pack.json` exists only after `content_passed`; its body hash matches the current `body_draft.md`.
- [ ] There are zero to three title directions. A selected result has exactly one selected direction; a return result has no selected direction and a return reason.
- [ ] Every direction has a distinct angle, body locators, and source locators; `title_core_fact` checks happen here, not during body writing.
- [ ] If a direction needs a new body fact, the package returns to content review; if it needs new evidence, it returns to material intake. Title packaging never appends or requests automatic body text.
- [ ] `title-pack-review.json` binds the selected direction to the current title-pack path and SHA-256.
- [ ] `delivery.md` is composed from the unchanged body and the selected formal H1; it has exactly one H1.

## Evidence And Originality

- [ ] Every material claim has a permitted claim mapping.
- [ ] Fact, attributed view, and inference remain distinct.
- [ ] Any current-news claim has a time boundary and publication-time revalidation; a revival/evergreen article states its durable value and does not use a discovery signal as proof of present interest.
- [ ] Excluded/context-only sources appear only in `exclusion_evidence_refs`, never in current `source_refs`, claim mappings, permitted claims, or current task-card extracts.
- [ ] Dynamic fact cards with `update_required_before_publication=yes` have a fresh `review/<article_id>/revalidation.json` with per-claim source snapshot hash and locator.
- [ ] Conflict or denial is represented at the required boundary.
- [ ] No source sentence cluster, structure, or exclusive conclusion is copied.

## Presentation

- [ ] Markdown is the approved and normally retained reading/review artifact.
- review_surface: `markdown_codex | html_delivery`
- markdown_review_evidence_ref:
- markdown_approval_ref:
- presentation_state: `verified | template-blocked`
- markdown_draft_ref:
- content_delivery_ref: `review/content-delivery.json`
- [ ] `content-delivery.json` reports `content_status=CONTENT_READY` before handing the Markdown to the user.
- [ ] When `review_surface=markdown_codex`, current Markdown path/size/SHA-256/CJK count match `review/markdown-review-evidence.json`.
- html_delivery_state: `not_requested | generated | withheld`
- [ ] When `review_surface=markdown_codex`, `html_delivery_state=not_requested` is normal and no HTML, freeze manifest, route audit, or preview service is required.
- [ ] When `review_surface=html_delivery`, HTML generation/freeze and the historical local/canonical preview contract are explicitly declared and independently bound.
- legacy_preview_mode: `local_codex | canonical_http` (only for `review_surface=html_delivery`)
- legacy_preview_evidence_ref:
- mobile_browser_screenshot_advisory_ref:
- [ ] Images have source and usage-boundary records.

## Review And Controller Status

- content_result: `PASS | FAIL | PENDING | UNKNOWN`
- evidence_result: `PASS | FAIL | PENDING | UNKNOWN`
- governance_result: `PASS | FAIL | PENDING | UNKNOWN`
- publication_authorization: `not_authorized`

- worker_dispatch_ref:
- [ ] Missing requested skill is recorded as fallback only for drafting/title/structure; review/prepublication is blocked.
- [ ] Worker input is a structured extract/fact card, not raw HTML.
- [ ] Independent review report is attached.
- [ ] Strict runs bind independent review to `artifact_path/artifact_sha256`、`body_sha256`、`title_pack_sha256` and `created_from_run`; mismatch is `stale_review`.
- [ ] No unresolved blocker or major finding remains.
- [ ] Content-fidelity, title-pack, title-review, final-review, and content-delivery records identify the same run and current article version, using their respective contract fields. No summary may say `CONTENT_READY` while that run's `content-delivery.json` is `CONTENT_BLOCKED`.
- [ ] If the user only wants a publishable article and no publication action, missing human attestation/controller governance is recorded as a governance note and does not block `CONTENT_READY`.
- [ ] Separate human editor attestation remains required only for the M2 governance/promotion path.
- [ ] Batch dedupe matrix passes.
- controller_package_decision: `publish-ready accepted | draft-only | rejected`
- controller_decision_by:
- controller_decision_at:
- controller_decision_evidence_ref:
- publication_authorization: `not_authorized | granted` (default: `not_authorized`)
- authorization_by: Required only when `publication_authorization=granted`; otherwise blank.
- authorized_at: Required only when `publication_authorization=granted`; otherwise blank.
- authorization_ref: Required only when `publication_authorization=granted`; otherwise blank.
- authorized_publication_scope: Required only when `publication_authorization=granted`; otherwise blank.
- [ ] `controller_package_decision=publish-ready accepted` does not grant publication authority.
- [ ] When `presentation_state=template-blocked`, `markdown_draft_ref` is non-empty and resolves to the retained Markdown draft.
