# Article Group 1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an offline Article Group controller manifest and decision ledger that orchestrates existing V3/V4/V5 contracts without changing their state vocabulary.

**Architecture:** A small controller module validates a batch manifest, records append-only stage decisions, and delegates transition checks to existing V3/V4/V5 adapters. It writes only explicit run artifacts and never publishes or advances external state.

**Tech Stack:** Python 3.14, dataclasses/JSON, pytest, existing jsonschema contracts.

**Spec:** `docs/superpowers/specs/2026-09-09-article-group-1.0-design.md`

## Global Constraints

- Preserve V3/V4/V5 schemas and state transitions.
- Keep `CONTENT_READY`, R8, and publication authorization separate.
- Fail closed on identity, hash, evidence, topic drift, or automatic publication fields.
- Write only under an explicit run directory.

### Task 1: Controller contract and state adapter

**Files:**
- Create: `article_group/controller_v1.py`
- Test: `tests/test_article_group_controller_v1.py`

**Interfaces:**
- `validate_controller_manifest(manifest) -> list[str]`
- `validate_stage_decision(decision, manifest) -> list[str]`
- `append_stage_decision(path, decision) -> None`
- `validate_controller_transition(from_state, to_state, *, topic_card=None, crawl_task=None, material_pack=None, v4_context=None, v5_context=None) -> list[str]`

- [ ] Write tests for valid manifest, invalid identity, forbidden publication authorization, append-only decisions, and V3/V4/V5 delegation.
- [ ] Run focused tests and observe failures.
- [ ] Implement minimal JSON validation, immutable append ledger, and adapter delegation.
- [ ] Run focused tests.
- [ ] Commit `feat: add article group controller contract`.

### Task 2: CLI and read-back verification

**Files:**
- Create: `scripts/article_group_controller.py`
- Test: `tests/test_article_group_controller_cli.py`

**Interfaces:**
- CLI `init`, `record`, and `verify` subcommands with explicit `--run-dir` and output paths.

- [ ] Add negative-path CLI tests for missing run root, malformed JSON, hash mismatch, and overwrite refusal.
- [ ] Implement CLI using argument lists and explicit paths.
- [ ] Verify manifests, decision ledger, hashes, and `publication_authorization=not_authorized` by reading them back.
- [ ] Run focused and full relevant tests.
- [ ] Commit `feat: add article group controller cli`.

### Task 3: Documentation and controlled fixture

**Files:**
- Create: `docs/codex/article-group-1.0.md`
- Create: `tests/fixtures/controller-v1/manifest.json`
- Create: `tests/fixtures/controller-v1/decisions.jsonl`
- Test: `tests/test_workflow.py`

- [ ] Document ownership, lifecycle mapping, V5 handoff, and failure routing.
- [ ] Add a fixture proving one end-to-end offline controller run.
- [ ] Run all controller, V3, V4, and V5 tests and read back generated artifacts.
- [ ] Commit `docs: document article group 1.0 controller`.
