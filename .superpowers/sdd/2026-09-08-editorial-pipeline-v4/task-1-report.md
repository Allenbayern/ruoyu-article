# Task 1 report — V4 contracts and package foundation

## Status

PASS. Task 1 V4 contracts/package foundation is implemented and committed as
`d8aa605` (`feat: add v4 artifact contracts`).

## Files changed

- `article_group/v4/__init__.py`
- `article_group/v4/contracts.py`
- `article_group/v4/errors.py`
- `tests/test_v4_contracts.py`
- `schemas/editorial-pipeline-v4/v4-artifact.schema.json`

Existing unrelated working-tree changes were preserved and were not staged.

## Tests run

- `uv run pytest -q tests/test_v4_contracts.py` — PASS, 11 passed.
- `uv run pytest -q` — PASS, 743 passed.
- Explicit JSON Schema checks for valid, non-object, publication-field, and
  envelope cases — PASS.
- `git diff --check` — PASS.

The focused tests were run once before implementation and failed at collection
with the expected `ModuleNotFoundError: No module named 'article_group.v4'`.

## Self-review

- The envelope includes only `schema_version`, `run_id`, `generated_at`,
  `input_hashes`, and `payload`; no publication field is defined.
- Envelope validation fails closed for missing identity, unknown or mismatched
  schema/run identity, missing payload/hash fields, non-object payloads, and
  malformed SHA-256 values.
- Path resolution rejects absolute paths and traversal outside the supplied run
  root; hashing and JSON parsing are offline and deterministic.
- V4 vocabularies are centralized and exported for later modules.
- No Vault, network, credentials, V3 implementation, or unrelated files were
  modified.

## Concerns

None for Task 1. The checkout remains dirty with pre-existing user changes and
untracked files outside this task; they were intentionally left untouched.

## Fix round 1 report

Status: PASS. Addressed both independent-review findings:

- F-1: `validate_artifact_envelope` now rejects every unknown top-level key,
  including `publication_authorization`, and validates non-empty timezone-aware
  ISO/RFC3339 `generated_at` values. The schema retains its closed top-level
  boundary and now has a deterministic timestamp pattern alongside
  `format: date-time`.
- F-2: Added `Draft202012Validator` with `FormatChecker` regression coverage
  for a valid envelope, non-object input, each required-field omission,
  publication/unknown top-level fields, and invalid timestamps.

Tests and verification:

- `uv run pytest -q tests/test_v4_contracts.py` — PASS, 12 passed.
- `uv run pytest -q` — PASS, 744 passed.
- Direct Python/JSON Schema parity checks for valid, non-object, missing
  required fields, unknown/publication fields, and invalid timestamps — PASS.
- `git diff --check` — PASS.

Self-review: only Task 1 contract implementation, schema, tests, and this
report were changed; V3 behavior, Vault, network, credentials, and unrelated
working-tree changes were untouched. Concern: the checkout remains dirty with
pre-existing user changes and untracked files outside this task.

## Fix round 2 report

Status: PASS. Addressed scoped re-review items F-1/NB-1 and F-2:

- F-1/NB-1: Python and JSON Schema now use the same explicit non-leap-second
  RFC3339 subset: uppercase `T`, two-digit date/time fields, seconds `00-59`,
  optional fractional seconds, and either `Z` or a timezone offset in
  `±HH:MM` form. Timezone is mandatory; space separators, lowercase `t`,
  compact offsets, and leap seconds are rejected by both paths.
- F-2: Schema omission regression now covers all five required fields:
  `schema_version`, `run_id`, `generated_at`, `input_hashes`, and `payload`.

Tests and verification:

- `uv run pytest -q tests/test_v4_contracts.py` after adding regressions —
  expected RED, 1 failed and 12 passed; failure exposed Python accepting the
  space separator.
- `uv run pytest -q tests/test_v4_contracts.py` after implementation — PASS,
  13 passed.
- `uv run pytest -q` — PASS, 745 passed.
- Direct Python/`Draft202012Validator(..., format_checker=FormatChecker())`
  parity matrix for valid fractional/Z/offset timestamps, space separator,
  missing timezone, leap second, lowercase `t`, compact offset, all five
  required-field omissions, and unknown/publication fields — PASS:
  `round 2 parity checks: PASS`.
- `git diff --check` — PASS.

Note: an initial parity shell probe failed because its extra-field assertion
was accidentally inverted; the implementation was unchanged and the corrected
probe passed immediately with the same cases.

Self-review: only `article_group/v4/contracts.py`,
`schemas/editorial-pipeline-v4/v4-artifact.schema.json`,
`tests/test_v4_contracts.py`, and this report were changed in this round.
V3 behavior, Vault, network, credentials, and unrelated working-tree changes
were untouched. Concern: the checkout remains dirty with pre-existing user
changes and untracked files outside this task.

## Fix round 3 report

Status: PASS. Addressed round-2 re-review F-1 and NB-2:

- F-1: Schema timestamp patterns now use an absolute-end `(?![\\s\\S])`
  assertion, matching Python `fullmatch` and rejecting both LF and CRLF.
- NB-2: Python retains `datetime.fromisoformat` semantic validation after the
  strict lexical check. The Schema now deterministically constrains legal
  Gregorian month/day combinations, including only leap-year February 29,
  and legal hour/minute/second ranges. Both paths reject February 30, minute
  60, hour 24, non-leap February 29, and leap second 60.
- The parity regression retains valid fractional/Z/offset cases and now
  covers leap-year dates, invalid calendar/time values, LF, and CRLF.

Tests and verification:

- `uv run pytest -q tests/test_v4_contracts.py` after adding regressions —
  expected RED, 1 failed and 12 passed; failure exposed Python accepting
  `2026-02-30T10:00:00Z`.
- `uv run pytest -q tests/test_v4_contracts.py` after implementation — PASS,
  13 passed.
- `uv run pytest -q` — PASS, 745 passed.
- Independent Python/`Draft202012Validator(..., format_checker=FormatChecker())`
  parity matrix for valid leap/non-leap dates, invalid dates/times, separator,
  timezone, leap-second, LF/CRLF, and offset cases — PASS:
  `round 3 parity checks: PASS`.
- `git diff --check` — PASS.

Self-review: only `article_group/v4/contracts.py`,
`schemas/editorial-pipeline-v4/v4-artifact.schema.json`,
`tests/test_v4_contracts.py`, and this report were changed in this round.
V3 behavior, Vault, network, credentials, and unrelated working-tree changes
were untouched. Concern: the checkout remains dirty with pre-existing user
changes and untracked files outside this task.
