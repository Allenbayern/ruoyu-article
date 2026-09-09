# Codex Project Rules: Article Group

## Read first

Before any non-trivial task, read:

1. `/home/allen/Documents/Obsidian Vault/Hermes-Knowledge/AGENTS.md`
2. `/home/allen/Documents/Obsidian Vault/Hermes-Knowledge/20_Hermes/00_System/Codex Context.md`
3. `/home/allen/Documents/Obsidian Vault/Hermes-Knowledge/20_Hermes/10_Content_Production/02_Article_Group/Index.md`
4. `Hermes Article Group Operating Rules.md`
5. `Hermes Article Group Workflow.md`

The Vault notes are the canonical content and governance references. Do not infer production rules from old runs alone.

## Working boundary

- Project root: `/home/allen/Projects/ruoyu-film-daily`
- Keep source code, tests, and Codex adapter changes in this repository.
- Keep temporary runs and review evidence under `runs/<run-id>/`; do not treat them as canonical rules.
- Preserve the existing deterministic gates, evidence manifests, hashes, previews, and final-review behavior.
- Codex review output is evidence only. It cannot authorize publication, merge, deployment, or state promotion.
- Use `gpt-5.6-luna` for normal execution and review. Use `gpt-5.6-sol` only for L2 adversarial review.

## Codex handoff

For any task involving Codex tooling, read these project handoff materials after the canonical Vault rules:

- `CODEX-OPS-HANDOFF.md` — local Codex runtime, authentication boundary, host/service facts, and safe bridge usage.
- `docs/codex/skill-tool-migration.md` — Hermes-to-Codex capability mapping and non-migration boundaries.
- `docs/codex/viral-library-migration.md` — 若雨爆款文章库 source map, qualification boundary, and migration status.
- `.agents/skills/codex-ops-portable/SKILL.md` — portable evidence-first operating procedure.
- `.agents/skills/ruoyu-viral-library/SKILL.md` — read-only workflow for using the 若雨爆款 research library.

These documents contain no credential values. Do not read or copy Hermes session, memory, Gateway, Dashboard, Kanban, `.env`, cookie, token, or authentication-file contents into Codex prompts, project files, logs, or review artifacts.

## Content safety

For article planning, writing, title revision, and editorial review, read
`docs/codex/editorial-learning-playbook.md` after the canonical notes. It records
the user's confirmed delivery preferences and the project editorial method;
historical examples remain learning evidence, not new factual sources or
automatic publication authority.

The end-to-end handoff between Article Group and targeted crawling is defined in `docs/codex/editorial-pipeline-v2.md`; read it for statuses, ownership, material-pack acceptance, return rules, and case-library levels.

Daily article-group tasks follow the editorial direction in
`docs/codex/editorial-learning-playbook.md`: use a current film topic as an
entry point to write a character situation, relationship conflict, choice, or
shared real-world emotion that readers can discuss, take a side on, and pass on.
Select high-probability topics with a clear reader, concrete object, verifiable
material, and definite reading benefit. Submit at most three materially
different title directions, bind each to evidence and an opening fulfillment
location, and allow the whole topic to be returned when material is weak. Do
not pad the two-article target with weak topics, repeated titles, or unsupported
sensational claims. Report content quality, hit-probability judgment, fact risk,
and unverified items separately; hit probability is an editorial hypothesis,
not a guaranteed result.

- Verify current facts from authoritative sources before writing.
- Do not turn signals, titles, snippets, or historical drafts into verified facts.
- Keep source evidence in metadata/review artifacts; do not expose internal review language in final article copy.
- Historical batches are evidence for learning only, never the current draft or delivery object unless explicitly assigned.

## Vault write-back

Do not modify the Vault by default. When a durable rule or correction is explicitly approved for write-back, update the named canonical note and preserve its frontmatter and wikilinks. Candidate findings belong in a clearly marked provisional note, not directly in canonical rules.

## Verification

Before reporting completion, run the relevant tests and gates, read back generated manifests/review results, verify hashes and preview status where applicable, and distinguish completed, unverified, and blocked items.
