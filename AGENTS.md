# Project Rules: Article Group

## Read first

Before any non-trivial task, read:

1. `/home/allen/Documents/Obsidian Vault/Hermes-Knowledge/AGENTS.md`
2. `/home/allen/Documents/Obsidian Vault/Hermes-Knowledge/20_Hermes/00_System/Agent Context.md`（原 `Codex Context.md`，2026-09-15 更名，旧文件为重定向）
3. `/home/allen/Documents/Obsidian Vault/Hermes-Knowledge/20_Hermes/10_Content_Production/02_Article_Group/Index.md`
4. `Hermes Article Group Operating Rules.md`
5. `Hermes Article Group Workflow.md`

The Vault notes are the canonical content and governance references. Do not infer production rules from old runs alone.

## Working boundary

- Project root: `/home/allen/Projects/ruoyu-film-daily`
- Keep source code, tests, and agent adapter changes in this repository.
- Keep temporary runs and review evidence under `runs/<run-id>/`; do not treat them as canonical rules.
- After each run, write a `RUN-RECORD.md` in the run root following `templates/RUN-RECORD.md` (eight sections). Every gate that did not run or does not apply must be recorded explicitly (`not_run` + reason) — never skipped silently.
- Preserve the existing deterministic gates, evidence manifests, hashes, previews, and final-review behavior.
- Independent review output is evidence only. It cannot authorize publication, merge, deployment, or state promotion.
- Execution model is the agent session model (dsh default `shenwendp/deepseek-v4.1-flash`). L2 adversarial review runs in a separate read-only subagent; record its structured result with `python -m article_group.codex_review --mode l2 --review-json <review.json>` (historical file name, no Codex CLI required).

### Sealed runs and evidence writes (repo-operational, 2026-09-17)

Triggered by a real incident: a demo re-run of the ledger precheck overwrote
`runs/2026-09-16/daily-008/review/art-001/ledger-coverage-precheck.json` on an
already closed and published run, with no backup.

- **Sealing is automatic, reopening is not.** `python -m article_group.close_out
  --run-root <run> --confirm` ends by writing `SEALED` (time, signer, delivery
  hashes). From then on every evidence writer refuses to touch the run.
- **All evidence writes go through `article_group.evidence_write`**: it snapshots
  the previous bytes to `review/.before/<stamp>/<path>`, appends a line to
  `evidence-changelog.jsonl`, and refuses sealed runs unless `--force` is passed
  explicitly. `restore()` puts a file back from its newest snapshot.
- **Rehearse in a sandbox, never on a real run**: `python scripts/run_sandbox.py
  runs/<date>/<run-id> [--label "…"]` copies the run to `/tmp`, renames `SEALED` to
  `SEALED.from-source`, and leaves the source untouched.
- **Reopening a sealed run needs an explicit controller instruction** and uses
  `unseal` (renames `SEALED` → `SEALED.revoked.<stamp>` and logs it); re-seal after
  the change. `--force` on a sealed run is a controller decision, not an agent one.
- These rules are repository-operational. Changing the Vault's canonical notes
  still requires explicit write-back authorization.

## Agent handoff

For any task involving host tooling or retired runtimes, read these project materials after the canonical Vault rules:

- `CODEX-OPS-HANDOFF.md` — historical Codex runtime handoff. Codex is retired: treat it as background, not an execution dependency.
- `docs/codex/skill-tool-migration.md` — Hermes-to-Codex capability mapping and non-migration boundaries (historical).
- `docs/codex/viral-library-migration.md` — 若雨爆款文章库 source map, qualification boundary, and migration status.
- `/home/allen/dsh/OPS-HANDOFF-2026-09-15.md` and `/home/allen/dsh/AUTHORIZED-ACTIONS-2026-09-15*.md` — current host handoff, executions, and open controller decisions.
- `~/.agents/skills/ruoyu-article-production/SKILL.md` — article production execution skill.
- `~/.agents/skills/ruoyu-viral-library/SKILL.md` — read-only workflow for using the 若雨爆款 research library.

These documents contain no credential values. Do not read or copy Hermes session, memory, Gateway, Dashboard, Kanban, `.env`, cookie, token, or authentication-file contents into prompts, project files, logs, or review artifacts.

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
