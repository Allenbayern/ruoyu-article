# First Controlled Production Run Brief

STATE: `BRIEF_READY`
GATE: `adversarial-review`
OBJECTIVE: Create one real three-article batch that is evidence-backed and review-ready, with no publication, delivery, scheduling, or HTML rendering.
DELIVERABLE: `runs/YYYY-MM-DD/<run-id>/controlled-run-manifest.json` plus A/B/C candidate, evidence, brief, and Markdown-draft artifacts.
IN_SCOPE: One manually initiated batch; source discovery; editorial selection; source capture; claim ledger; writing briefs; Markdown drafts; offline batch validation; independent review handoff.
OUT_OF_SCOPE: Cron, background radar, publisher login/API, WeChat publication, delivery messages, final HTML, image acquisition, live configuration changes, and reuse of legacy article content.
CONSTRAINTS: Three independent slots; 1500-2200 Chinese characters per Markdown draft; one same-day topic when evidence supports it; remaining slots from fermenting or revival candidates; no social/discovery signal used as the sole support for a material claim; every article remains `not_authorized` for publication.
ACCEPTANCE:
- A/B/C have distinct work, core event/person, Primary Atom, Reader Intent, angle, title skeleton, and ending destination.
- Each article has a full-text/primary/structured evidence pack with claim mapping for material assertions; the controller record includes at least one non-empty `claim_id → source_id → locator` mapping.
- Each declared Markdown, evidence pack, and writing brief is non-empty and inside the run root; Markdown is actually read and contains 1500–2200 Chinese characters.
- Each article declares at least two distinct non-empty concrete support types as a list/tuple, not a free-form string.
- Batch and article authorization fields are `not_authorized` with all authorization audit fields blank.
- Offline validator creates a manifest at `R8 review-ready` and no article receives publication authorization.
- Independent review receives the original brief, artifacts, validator result, and coverage gaps.
EVIDENCE: Candidate cards, editorial meeting, evidence packs, claim ledgers, writing briefs, Markdown drafts, delivery checklists, dedupe matrix, validator output, review-readiness packet.
NON_SUCCESS: Fewer than three independently supportable topics; missing full-text/locator for a material assertion; duplicate slots; unresolved conflict/denial; article content below substance gate; request to publish/deliver/render HTML; missing independent review evidence.
STOP: Stop at `R8 review-ready`; wait for independent review and controller acceptance. `publish-ready` and publication authority are not outputs of this run.
