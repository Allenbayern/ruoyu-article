# Task 7 report — V4 offline orchestrator and controlled-002 integration

## PASS

Task 7 is implemented as an offline, run-local V4 orchestration lane. The
implementation keeps the Article Group boundary intact: it collects and
verifies evidence for review, but it does not publish, authorize publication,
write Vault state, or contact a platform.

## TDD and verification

- RED: `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_article_group_v4_cli.py` failed before the CLI/verifier implementation (`4 failed, 1 passed`), including the expected missing CLI behavior and incomplete read-back contract.
- Focused CLI suite: `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_article_group_v4_cli.py` — PASS, `7 passed`.
- V4 suite: `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_article_group_v4_cli.py tests/test_v4_*.py` — PASS, `114 passed`.
- Full repository suite: `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q` — PASS, `846 passed`.
- Python compile check for the verifier, CLI, and focused tests — PASS.
- All seven CLI commands were invoked against the sanitized fixture; each produced its expected versioned JSON artifact.

## Contract and boundary coverage

- `plan`, `graph`, `gaps`, `templates`, `effects`, `recover`, and `verify` require an explicit run directory and explicit `--output-dir` or `--output-path`.
- Inputs are read from the supplied run directory through safe relative paths. No network, Vault, HTML, credential, publication, or external-message path is present.
- Each output is a closed V4 envelope. `verify` preflights all destinations, writes six module artifacts plus `v4-verification.json`, reads all seven back, rechecks their hashes and contracts, and refuses a different existing hash. Same-content reruns are idempotent.
- The final report keeps `PASS`, missing source roles, retry requirements, manual escalation, content status, and publication authorization as separate fields.
- The controlled run reports `missing_source_roles=["independent_short_review"]`, one retryable deferred source requirement for `art-001/src-missing`, no manual escalation, `content_status=CONTENT_READY`, and `publication_authorization=not_authorized`.
- The effects fixture contains no metric events. Its output remains `candidate` with zero samples, null medians, no aggregate, and no fabricated baseline or platform result.

## Fixture and scope

- `tests/fixtures/v4/controlled-002/` is a sanitized, run-local copy with explicit per-article topic mappings in both the batch and run manifest.
- Historical `runs/2026-09-07/controlled-002/` was not modified.
- Only the Task 7 implementation, focused test, controlled fixture, and this report are intended for staging. Existing shared-workspace changes remain unstaged.

## Handoff

The exact commit SHA and staged path list are reported with the Task 7 commit
handoff after the final status and scope checks.
