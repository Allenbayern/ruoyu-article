# Delivery Checklist

- article_id:
- batch_id:
- state:

## Content

- [ ] Specific work, person, event, or conflict remains central.
- [ ] Primary Atom is singular and fulfilled.
- [ ] At least two types of concrete support appear.
- [ ] Chinese character count is 1500–2200.
- [ ] Title is 30 Chinese characters or fewer and matches the body promise.
- [ ] No internal editorial, source, or growth terminology leaks into reader text.

## Evidence And Originality

- [ ] Every material claim has a permitted claim mapping.
- [ ] Fact, attributed view, and inference remain distinct.
- [ ] Conflict or denial is represented at the required boundary.
- [ ] No source sentence cluster, structure, or exclusive conclusion is copied.

## Presentation

- [ ] Markdown is the approved source text.
- markdown_approval_ref:
- presentation_state: `verified | template-blocked`
- template_path:
- template_version_or_hash:
- render_result:
- mobile_preview_ref:
- html_delivery_state: `generated | withheld`
- markdown_draft_ref:
- [ ] When `presentation_state=template-blocked`, `html_delivery_state=withheld` and `markdown_draft_ref` identifies the retained draft.
- [ ] When `html_delivery_state=generated`, HTML is generated only from the approved Markdown.
- [ ] Generated HTML contains no script, event handler, iframe, form, external stylesheet, or unsafe URL.
- [ ] Images have source and usage-boundary records.

## Review And Controller Status

- [ ] Independent review report is attached.
- [ ] No unresolved blocker or major finding remains.
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
