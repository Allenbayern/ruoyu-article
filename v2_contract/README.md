# V2 Contract Shadow Validators

This package validates the frozen Ruoyu V2 contract without importing or changing `article_group/`. It is shadow mode: it reads task-card JSON and the frozen state-vocabulary YAML, reports errors, and never publishes, authorizes, writes production batches, or changes workflow state.

## Usage

From the repository root:

```bash
uv run python -m v2_contract.validate_task_card path/to/task-card.json
uv run python -m v2_contract.validate_transition "R7 mechanically-verified" "R7.5 awaiting-independent-review"
```

Both commands use the frozen contract files by default. Override them for an isolated fixture with `--schema`, `--vocabulary`, or both. Exit codes are:

| Exit code | Meaning |
|---:|---|
| 0 | Input is valid, or the requested transition exists in the vocabulary table. |
| 1 | Input loaded successfully but contract validation failed. The command prints `INVALID` and deterministic error identifiers. |
| 2 | Input/schema/vocabulary could not be loaded or parsed. The command prints `INPUT_ERROR` to stderr. |

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

`validate_transition` loads the YAML `transitions` table and accepts only an exact direct `(from, to)` pair. Unknown states and missing transition rows are reported separately.

## Failure semantics

Validation is fail-closed for the requested contract. Schema failures are reported with `schema.<keyword>:<path>:<message>`. Cross-check failures use stable identifiers such as `r8_publication_authorization_must_be_not_authorized`, `variant_const_mismatch:dr_02_variant:...`, and `invalid_transition:<from>-><to>`. The validators do not attempt repair, infer missing fields, normalize labels, or mutate the input.

The validators are not connected to a production batch runner, scheduler, Vault, Skill, or `article_group/` module. Review and publication decisions remain outside this package.

`uv.lock` is sensitive to the package-resolution index. Re-resolving across indexes can invalidate recorded lockfile digests even when dependency versions are unchanged; run `uv lock --check` before recording evidence, and keep one deterministic index for the lockfile and its evidence snapshot.
