# First Controlled Production Run Brief

STATE: `BRIEF_READY`
RUN_PROFILE: `two_article_daily`（默认日更）| `three_slot_controlled`（显式 legacy 对照批次）
REVIEW_SURFACE: `markdown_codex`（默认审阅）| `html_delivery`（显式历史/专门交付）
GATE: `adversarial-review`
OBJECTIVE: Create one real profile-declared article batch that is evidence-backed and review-ready, with a title-free body reviewed before any title packaging; no publication, scheduling, or HTML rendering.
DELIVERABLE: `runs/YYYY-MM-DD/<run-id>/controlled-run-manifest.json` plus profile slot candidates, evidence, body drafts, content-fidelity records, title packs, and delivery artifacts.
IN_SCOPE: One manually initiated batch; source discovery; editorial selection; source capture; claim ledger; body-first writing; content review; post-content title packaging; offline batch validation; independent review handoff.
OUT_OF_SCOPE: Cron, background radar, publisher login/API, WeChat publication, delivery messages, final HTML, image acquisition, live configuration changes, and reuse of legacy article content.
CONSTRAINTS: The batch must declare `run_profile` and `run_profile_contract_version: run-profile-v1`; `two_article_daily` has A/B, `three_slot_controlled` has A/B/C. Each `body_draft.md` uses the style-gate CJK count: 1500-2200 Chinese characters is the usual target, with a 1000-2700 flexible acceptance band when the article is complete and readable; no social/discovery signal is the sole support for a material claim; every article remains `not_authorized` for publication.
ACCEPTANCE:
- Every declared slot has a distinct work, core event/person, Primary Atom, Reader Intent, article reading question, material need, and ending destination. A discovery title signal, if present, is not copied into the brief.
- Each article has a full-text/primary/structured evidence pack with claim mapping for material assertions; the controller record includes at least one non-empty `claim_id → source_id → locator` mapping.
- Each `body_draft.md`, evidence pack, writing brief, and content-fidelity record is non-empty and inside the run root; the body contains no H1 and is actually read.
- Content passes only with at least three independently supported hard-information items from at least two types, a material-backed increment for every major paragraph, and a title-free standalone reading check for object, problem, explanation, and judgment.
- Only after `content_passed` may the run create `title_pack.json`; it may contain at most three directions, and every direction must point back to body and source locators. A selected title is composed with the unchanged body into `delivery.md`.
- Batch and article authorization fields are `not_authorized` with all authorization audit fields blank.
- Offline validator creates a mechanically verified manifest; independent review and controller acceptance are separate later transitions, and no article receives publication authorization.
- Independent review receives the original brief, artifacts, validator result, and coverage gaps.
- Review surface is explicit for `run-profile-v1`: `markdown_codex` requires current Markdown path/size/SHA-256/CJK evidence and does not generate HTML; `html_delivery` is an explicit legacy/专门路径 and retains its historical preview contract.
EVIDENCE: Candidate cards, editorial meeting, evidence packs, claim ledgers, writing briefs, Markdown drafts, delivery checklists, dedupe matrix, validator output, review-readiness packet.
NON_SUCCESS: Fewer than three independently supportable topics; missing full-text/locator for a material assertion; duplicate slots; unresolved conflict/denial; article content below substance gate; request to publish/deliver/render HTML; missing independent review evidence.
STOP: Stop at `R8 review-ready`; wait for independent review and controller acceptance. `publish-ready` and publication authority are not outputs of this run.
