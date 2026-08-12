# V2 Contract Shadow Validators

This package validates the frozen Ruoyu V2 contract without importing or changing `article_group/`. It is shadow mode: it reads task-card JSON and the frozen state-vocabulary YAML, reports errors, and never publishes, authorizes, writes production batches, or changes workflow state.

## Usage

From the repository root:

```bash
uv run python -m v2_contract.validate_task_card path/to/task-card.json
uv run python -m v2_contract.validate_transition "R7 mechanically-verified" "R7.5 awaiting-independent-review"
```

`validate_task_card` defaults to the frozen v1.1 task-card schema. New task cards must use `schema_version: "1.1"` and include `daily_output_policy`. Existing v1.0 task cards remain supported only when their frozen schema is selected explicitly:

```bash
uv run python -m v2_contract.validate_task_card path/to/v1.0-task-card.json \
  --schema docs/plans/ruoyu-production-v2/2026-08-11-contract-v1.0/task-card-v1.0.schema.json
```

`validate_transition` continues to use the frozen v1.0 state vocabulary by default. Override either validator's frozen inputs for an isolated fixture with `--schema`, `--vocabulary`, or both. Exit codes are:

| Exit code | Meaning |
|---:|---|
| 0 | Input is valid, or the requested transition exists in the vocabulary table. |
| 1 | Input loaded successfully but contract validation failed. The command prints `INVALID` and deterministic error identifiers. |
| 2 | Input/schema/vocabulary could not be loaded or parsed. The command prints `INPUT_ERROR` to stderr. |

## Batch preflight

Before calling the existing batch workflow, materialize the proposed batch as JSON
and run its read-only V2 preflight from the repository root:

```bash
uv run python -m v2_contract.run_preflight \
  --batch path/to/proposed-batch.json \
  --run-dir runs/YYYY-MM-DD/controlled-NNN
```

The required `batch` object contains `run_id`, `manifest_state`, `target_state`,
and `articles`. Each article carries the v1.1 task-card mapping fields: the
`article_id`/`candidate_id`/A-B-C slot and editorial fields, `source_refs`,
`gate_status`, delivery authorization/state, and the three frozen policy objects
including `daily_output_policy`. The command maps only supplied fields, fixes
`schema_version` to `1.1`, validates each mapped card, and validates the requested
`manifest_state -> target_state` using the frozen vocabulary's complete `exits` set.
Every article's `state` must also equal the authoritative `manifest_state`; a
disagreement is reported as `FAIL`/exit 1. Candidate IDs from `candidate-pool.json`
are normalized by trimming, collapsing whitespace, and lowercasing; duplicate
normalized IDs are rejected as `INPUT_ERROR`/exit 2 before any candidate can be
selected by overwrite.

With `--run-dir`, preflight also reads `candidate-pool.json`, `source-manifest.json`,
and `task-cards/task-card-*.md` only to verify that the batch agrees with the
controlled-run evidence. It never writes a task card, manifest, batch, workflow
state, or production artifact. The JSON report uses `PASS`/exit 0, `FAIL`/exit 1,
and `INPUT_ERROR`/exit 2; missing mapping fields are reported as
`preflight.missing_mapping_fields:<article_id>:<field-list>`.

Batch-flow integration point: run this command after a proposed batch JSON is
assembled and before any call to `article_group.workflow.validate_batch` or
`build_controlled_run`. A passing preflight is deterministic evidence only; it does
not authorize the workflow call, independent review, controller acceptance, or
publication.

The Python API returns a list of error strings. An empty list means valid:

```python
from v2_contract.validate_task_card import validate_task_card
from v2_contract.validate_transition import validate_transition

errors = validate_task_card(card)
transition_errors = validate_transition("R6 drafting", "R7 editorial-ready")
```

## Checks

`validate_task_card` performs Draft 2020-12 JSON Schema validation with `jsonschema`, then cross-checks:

- task-card `state` values against the frozen YAML state mapping;
- the schema state enum against the YAML state mapping;
- each schema variant `const` against the corresponding resolved YAML decision point;
- `R8 review-ready` as `publication_authorization=not_authorized` plus `independent_review=approve`;
- `publication-authorized` as `publication_authorization=granted` plus `delivery_state=published`;
- `H4 draft-only` as `publication_authorization=not_authorized`;
- all three frozen variant `const` values, including rejection of `pending_allen`.

`validate_transition` derives its complete direct-transition set exclusively from every
`states[].exits` declaration in the frozen YAML. This exits union is the sole
state-legality authority and corresponds to `article_group/workflow.py`'s executable
`ALLOWED_TRANSITIONS`. The YAML `transitions` table is a narrower, gate-bearing
progression-semantics annotation; it is not consulted to decide whether a direct state
transition is legal. Unknown states and missing exit pairs are reported separately.

## Failure semantics

Validation is fail-closed for the requested contract. Schema failures are reported with `schema.<keyword>:<path>:<message>`. Cross-check failures use stable identifiers such as `r8_publication_authorization_must_be_not_authorized`, `variant_const_mismatch:dr_02_variant:...`, and `invalid_transition:<from>-><to>`. The validators do not attempt repair, infer missing fields, normalize labels, or mutate the input.

The validators are not connected to a production batch runner, scheduler, Vault, Skill, or `article_group/` module. Review and publication decisions remain outside this package.

`uv.lock` is sensitive to the package-resolution index. Re-resolving across indexes can invalidate recorded lockfile digests even when dependency versions are unchanged; run `uv lock --check` before recording evidence, and keep one deterministic index for the lockfile and its evidence snapshot.
