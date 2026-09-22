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
  - **Write the record the gate reads**: point `--output` at
    `review/<aid>/independent-review.json` (plus `--article-id/--artifact-path/--body-path/--title-pack-path`).
    That path is the canonical `article-independent-review-v1` record and is written with
    `status=complete`; `--canonical-independent-review` forces the same shape for any output name.
    A record under any other name stays in the `codex-review-contract-1.0` shape (status `PASS`/`FAIL`)
    and the gate does not read it — the tool then records `canonical_record_state` and warns
    (daily-009: an approve that lived only in the sidecar was silently replaced by the generator's
    PENDING placeholder, and nothing in the pipeline could see it).
  - **The review JSON must satisfy `schemas/codex-review-contract.json`** (severity ∈
    `blocker|major|minor`, the fixed finding keys, no extra keys). A review that does not is
    recorded as `UNVERIFIED` with `contract_errors` — never as a verdict — and a `blocker`/`major`
    finding can never be recorded as an approve (the decision is downgraded to `needs_changes`
    and the change is recorded). daily-009's reviewer used self-invented keys
    (`id`/`category`/`location`…), which the old `--review-json` path copied through unchallenged.

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
  explicitly. `restore()` puts a file back from its newest snapshot. Wired today:
  the ledger precheck, `evidence_rebind`, `title_freeze`, `wechat_render`,
  `close_out` (including its `STEP-LOG.md`), `final_review`, `run_record`,
  `scripts/record_controller_acceptance.py`, `codex_review` (L2 record + review
  log), `delivery` (plain copy), `content_delivery` (handoff record), and
  `daily_engine` (its spec helpers are wrapped); `--force` is passed down to the
  subprocess writers so a forced close-out is not half-effective.
- **Create-only artifacts get an anchor, not a before-image**: the viral-research
  package / card batch / distillation report are new-only and carry their own
  per-file SHA-256 (`integrity.json` / `manifest.json`), so there is nothing to
  snapshot; they append one artifact-level line to the run's changelog via
  `evidence_write.anchor_artifact`, which keeps `run_seal` verification able to
  tell "ledgered" from "silent".
- **Measure real operations instead of eyeballing them**: `python
  scripts/with_runs_guard.py -- <command…>` fingerprints `runs/` before and after
  and exits 3 on any unapproved change (`scripts/runs_fingerprint.py print|save|compare`
  for the two-step version; `--hash` also catches a rewrite with size and mtime
  restored). Destructive tools carry their own seal defence: `scripts/purge_quarantine.py`
  refuses any directory containing `SEALED` unless `--allow-sealed --ref "<who approved>"`
  is given, and records the authorization plus the marker hashes in the surviving
  `PURGED.txt`.
- **Rehearse in a sandbox, never on a real run**: `python scripts/run_sandbox.py
  runs/<date>/<run-id> [--label "…"]` copies the run to `/tmp`, renames `SEALED` to
  `SEALED.from-source`, and leaves the source untouched.
- **Reopening a sealed run needs an explicit controller instruction** and uses
  `unseal` (renames `SEALED` → `SEALED.revoked.<stamp>` and logs it); re-seal after
  the change. `--force` on a sealed run is a controller decision, not an agent one.
- **Sealing writes a full manifest**: `seal()` also writes `SEALED.manifest.json` —
  every covered file's size + sha256, plus the `SEALED` marker's own byte hash — so
  "was anything changed after sealing?" is answerable after the fact:
  `python -m article_group.run_seal --run-root <run>` (0 intact / 2 drifted /
  3 unverifiable) recomputes it and separates ledgered `--force` writes from silent
  ones. The append-only logs are checked by prefix (append is fine, rewrite is not).
  Runs sealed before this existed (daily-008) report `unverifiable`; `--backfill`
  records a manifest **and** states it cannot prove the past.
- **The guard does not rely on each entry point remembering**: importing
  `article_group` installs a process-wide PEP 578 audit hook (`article_group.runs_guard`)
  that rejects any write/create/delete/rename under a directory containing `SEALED`,
  with `SealedWriteBlocked`. The only way through is `evidence_write(..., force=True)`
  or `unseal()` — both snapshot and log. Appending in place to `step-log.jsonl` /
  `evidence-changelog.jsonl` is allowed by contract; rewriting or deleting them is not.
  **Out-of-process writers** (editor, `rsync`, `git checkout`, a `python -c` that never
  imports the package) are *not* covered by the hook — that is the filesystem-layer /
  hash-manifest gap, not a claim the hook makes.
- The list of modules that can write into a run, plus the debt of those still
  bypassing the snapshot channel, lives in `tests/test_runs_write_coverage.py`;
  the test fails when a new writer appears unclassified or a listed module goes stale.
- These rules are repository-operational. Changing the Vault's canonical notes
  still requires explicit write-back authorization.

### Content gates and incremental review (repo-operational, 2026-09-18)

- **Reader-facing assertions must be backed by the ledger, and this now blocks.**
  `article_group.run_gates.build_assertion_coverage_gate` runs the deterministic half of the
  reader-surface↔ledger check for every article task, writes `review/<aid>/assertion-coverage.json`
  plus `review/gates/assertion-coverage.json`, and fails `run_all_gates` on error-level gaps
  (time-span / audience-action claims with no ledger entry — the two daily-008 majors). Number
  and quote gaps stay warnings. The LLM half remains the advisory
  `scripts/ledger_coverage_precheck.py`. With this gate wired, historical runs are *not* grandfathered:
  daily-009 art-002 alone has four error-level gaps (bare years absent from the ledger).
- **`content_result=PASS` requires an approving L2** (controller ruling 2026-09-18, N2).
  An unfinished or missing L2 no longer shows content `PASS`: it stays governance `PENDING` but the
  content dimension becomes `PENDING`, and a completed non-approve L2 (the `BLOCKED` path) is
  labelled content `FAIL`. Reason: with the old口径 "L2 pending 不阻断", a batch that never ran L2
  scored *better* on the content dimension than one that ran and failed. Human sign-off items are
  unaffected — "人没签字" is still not a content blocker — and historical runs are not re-judged.
- **Evidence paths are run-relative.** `style_gate` (markdown / HTML / unknown) and the preview
  route manifest record their artifact path relative to the run root (absolute only outside a run),
  because an absolute binding breaks the moment the run is copied or moved (sandbox rehearsal,
  backup restore) — `final_review` then blocks the whole batch with `artifact_binding_invalid:path`
  while the evidence itself is fine. The rule lives in `article_group.evidence_paths`:
  - a relative path is written **only when it round-trips** (`(root/rel).resolve() == artifact`);
  - auto-detection accepts only the canonical run shape `…/runs/<YYYY-MM-DD>/<id>` (and the root
    must be a real ancestor). Anything else falls back to the absolute path; callers that know
    their layout (the engine) pass `run_root=` explicitly and are unaffected;
  - legacy absolute records are rebased by the `runs/<date>/<id>/` tail (innermost candidate first,
    purely lexical so a deleted source run still works). The rebase only *finds* the candidate —
    the `sha256` comparison right after it is still what authorizes it, for both style-gate and
    preview evidence.
- **`run_seal.is_run_root` is shape-strict** (tightened 2026-09-18 after L2 falsified the old rule).
  It now scans **every** `runs` component, requires the `<date>` component to be `YYYY-MM-DD`, and
  rejects a candidate that is an existing non-directory. All three were measured, not theoretical:
  `runs/<X>/<file>` (58 such files) made `anchor_artifact` treat the file as a run root and raise
  `FileExistsError`; `runs/radar/dailyhot` and `runs/<day>/quarantine` were counted as run roots;
  and in a "runs before runs" layout the outer directory won while the real run root was never
  recognized (anchors written to the wrong place, writers recording wrong relative paths). On the
  live tree the change reclassifies exactly 3 directories and 58 files. Non-existent paths still
  match by shape (lexical), so deleted-source rebases keep working. `runs_guard` does **not** use
  `is_run_root` (it probes ancestors for `SEALED`), so the sealed-write guard is unaffected.
  Verified end-to-end (2026-09-18) by running the **full 19-stage pipeline** inside
  `…/home/runs/proj/runs/2026-09-18/daily-9n1` (a daily-008 copy + stub renderer): the fixed code
  ledgers `delivery/*` ×2 and `review/*/title-pack.json` ×4 (100 entries) where the pre-fix code
  produced 25 entries and **zero** for those two artifacts (silent plain writes, no outer changelog
  either). In the same layout: seal → `verify` intact → in-process write blocked →
  out-of-process tamper → `drifted` (exit 2). Regression guards live in
  `tests/test_daily_engine_staging.py::test_the_engine_routes_writes_in_a_nested_runs_layout`
  (provably fails under the old rule) and
  `tests/test_run_seal.py::test_a_nested_runs_layout_is_sealed_guarded_and_verified`.
- **Incremental L2 review has a real diff.** `--base-review <previous record>` records
  `base_review_diff`: which binding hashes moved, a unified diff of the delivery against the
  hash-matched `review/.before/<stamp>/…` snapshot, and the base↔current finding pairing
  (`still_open` / `no_longer_reported` / `new`). A missing base snapshot is recorded as
  `snapshot_not_found` ("本轮只按当前稿复核"), never faked; `no_longer_reported` means only
  "not reported again this round", not "fixed".

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

### 批次间内容独立与元继承（controller 2026-09-21 定）

- **文章与人物完全解耦（零跨期关联）**：
  每批次（例如跑 012）的正文、人物、角色、故事、剧情，与历史批次（001～011）**完全独立、零关联、无继承**。
  严禁在正文中做跨批次人物联动、写成连续宇宙、提及“往期/上期某人物”，或把前几期人物拉入新文章作对比。每篇均为自闭环的独立深度单篇。
- **跨批次唯一合法继承（仅限元数据与系统层，绝不渗透至内容）**：
  1. **经验总结与流程优化**：每次跑完，仅在 `RUN-RECORD.md`、`STEP-LOG.md` 或经验手册中沉淀工程与写作经验（门禁排布、断言覆盖、反 AI 腔调优、写作节奏等），用于优化下一次跑批的 pipeline 和模型提示词。
  2. **选题与人物去重台账**：每次跑完，记录已写过的作品名、核心人物/实体、事件簇（`event_cluster_id`），纳入跨批查重历史库（`portfolio_gate` 跨批查重）。后续批次严格去重，坚决防止人物重复与选题撞车。

## Daily topic selection (controller decision 2026-09-21)

选题是**两道门**，不是 agent 自主交接：

1. Agent 先把发现面搜刮干净：R0 雷达快照（`runs/radar/dailyhot/<date>.classified.json`）、
   公众号订阅索引（`wechat_articles_sync` / `wechat_articles_search`）、当日媒体与官方报道；
   并对每个候选做**证据准备度粗核**（有没有一手来源、来源角色够不够撑住落点）。
2. Agent 交出一份**候选清单**——每个候选至少给：作品/事件、事件簇、当日信号与热度、
   读者是谁、落点（读者拿走哪一句话）、content_map 象限、证据准备度、已知风险。
3. **controller 从中选定具体选题**（可以增、删、改向）。选定之后才进入 brief / 起草 /
   门禁 / L2 复核。

规则：**在 controller 选定之前，不立项、不写 spec、不起草**。默认节奏是
「先搜刮 → 给可选项 → 等选定」。反例：daily-010 未经这一步直接成稿，选题被 controller
否定、整批重跑。候选池与证据照旧落 `runs/<run-id>/`；本条只约束**何时开始写**。

## Vault write-back

Do not modify the Vault by default. When a durable rule or correction is explicitly approved for write-back, update the named canonical note and preserve its frontmatter and wikilinks. Candidate findings belong in a clearly marked provisional note, not directly in canonical rules.

## Verification

Before reporting completion, run the relevant tests and gates, read back generated manifests/review results, verify hashes and preview status where applicable, and distinguish completed, unverified, and blocked items.
