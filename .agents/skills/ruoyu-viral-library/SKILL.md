---
name: ruoyu-viral-library
description: Use when Codex researches or applies 若雨随影爆款文章案例.
version: 1.0.0
---

# 若雨随影爆款文章库

## When to use

Use this skill when a task asks Codex to search the existing 若雨随影爆款文章库, compare article structures, extract candidate techniques, or use old cases to inform a new article.

This is a research-evidence library. It is not a publication queue, a canonical rule store, or a replacement for current-source fact verification.

## First action

From the repository root, run the read-only inventory before selecting samples:

```bash
python scripts/codex_viral_library_index.py --project-root .
```

Read `docs/codex/viral-library-migration.md` for the source map and migration boundary. The inventory is intentionally content-light: it reports paths, hashes, statuses, and resolvable evidence references without loading the whole article corpus.

## Source layers

1. `ruoyu-content/10-case-library/` is the preferred project entry for the legacy distilled notes.
2. `ruoyu-system/` contains a verified duplicate of the legacy notes for compatibility. Do not count duplicate files as independent evidence.
3. `runs/<run-id>/viral-research/` contains local research evidence when present: cards, clean full-text snapshots, metric records, manifests, and distillation outputs. The current run is ignored by Git, so a fresh clone may not have it.
4. `article_group/case_contract.py` and `article_group/case_distill.py` define the machine-enforced qualification and distillation boundary.
5. The Obsidian Vault remains the canonical governance reference. Do not write to it during ordinary Codex work and do not copy Hermes memory, sessions, credentials, or private control-plane state into the repository.

## Qualification discipline

- `qualified_viral` means the sample has an article-level performance evidence path and a declared platform/window rule. It may be considered for positive pattern research only with the other constraints below.
- `observed_pending` means evidence is incomplete. Use it for observation or follow-up collection, never as standalone support for a positive technique.
- `research_only` means the full text or structure is available without sufficient performance evidence. It is useful for structure comparison or counterexamples, not as proof that an article was viral.
- A qualified sample does not make every extracted technique a verified production rule. Distillation candidates remain provisional until the repository contract and controller review promote them.
- A positive pattern requires multiple shape-matched, cross-account or otherwise genuinely diverse `qualified_viral` samples. A single case, repeated cases from one account, or a Bilibili column/video-style title is not enough for a 若雨 title rule.
- Current facts in a new article must be checked against current authoritative sources. Historical article text is never a substitute for that check.

## Reading order for a research task

1. Run the inventory and check `availability`, `qualification_status`, `snapshot_present`, and `performance_evidence_present`.
2. Select a small, relevant set of sample IDs and read their JSON cards first.
3. Follow only the referenced clean snapshot and performance evidence files. Preserve the recorded SHA-256 in notes or evidence output.
4. Compare title promise, opening hook, conflict, scene detail, structure, and ending as moves. Do not copy wording, facts, or account voice.
5. Treat distillation files as candidate observations. Do not edit canonical rule notes from a single pass.
6. Keep research evidence and internal review language out of the final article body.

## Do not

- Do not call the whole legacy note bank "verified viral articles".
- Do not infer article performance from a title, search ranking, account size, hot-board signal, snippet, or historical draft.
- Do not promote `observed_pending` or `research_only` samples into positive evidence by renaming them.
- Do not turn one article into a universal title, opening, or structure rule.
- Do not copy raw HTML, credentials, cookies, Hermes sessions, memory, or hidden control-plane files into Codex prompts or project artifacts.
- Do not publish, merge, deploy, write to the Vault, or advance any workflow state merely because the inventory or a Codex review succeeds.

## Expected evidence references

A useful internal research note should identify:

- `sample_id`
- `qualification_status`
- `card_ref`
- `snapshot_ref` with its SHA-256 fragment
- `performance_evidence_ref`
- the exact observed technique or counter-pattern
- limitations, including platform and article-shape mismatch

The inventory's `usable_for_positive_patterns` field is a routing aid, not a final editorial or publication decision.
