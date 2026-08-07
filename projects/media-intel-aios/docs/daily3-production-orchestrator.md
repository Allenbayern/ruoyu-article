# Daily3 Production Orchestrator

`scripts/daily3_production_orchestrator.py` creates one isolated, non-publishing
candidate run from exactly three explicit allowlisted 1905 raw packets and one
explicit source-input JSON. It never fetches sources, changes cron, fills a
historical quota, publishes content, or authorizes publication.

## Fresh bundle and delivery-ledger boundary

The production entrypoint additionally requires an explicit `--source-bundle`
and isolated `--delivery-ledger`. A source bundle is offline JSON containing a
non-empty `bundle_id`, SHA-256 of the exact source-input bytes, ISO-8601
`created_at`, and the ordered A/B/C `work_identities`. It fails closed (exit
`26`) for missing/invalid bundle data, SHA mismatch, fewer than three distinct
works, or a source/bundle identity mismatch.

The ledger is claimed atomically before it is read or written. A successful
non-publishing candidate commits only after all source, provenance, gate, and
local delivery checks pass. It rejects a reused bundle SHA/content SHA, work
identity, or rendered article delivery hash. A ledger conflict removes the
candidate `delivery/` tree and leaves the ledger unchanged. This boundary is
offline only: it neither fetches, publishes, nor changes cron.

`daily3_shadow_cron_runner.py` intentionally consumes only the historical
controlled fixture, so it exits nonzero as
`SHADOW_FIXTURE_ONLY_NOT_FRESH_DAILY` with `fixture_only=true`; it is not a
fresh-daily success path and creates no candidate.

## Required flow

Each run stages copies of the exact raw packet set and runs these stages in
order:

1. raw packet staging plus SHA-256 inventory
2. source packet provenance verification
3. source-input to gate-packet adapter
4. three-slot structural gate
5. full raw-to-gate provenance verification
6. T1 release HTML rendering and validator check

The T1 renderer remains a non-publishing layer. Its normal lack of a controlled
WeChat-editor preview is retained as `release_acceptance.status=not_accepted`;
it must never become publication authority.

## Offline controlled smoke

```sh
python scripts/daily3_production_orchestrator.py \
  --run-id daily3-real-1905-20260718-candidate-not-final \
  --raw-dir tmp/daily3-real-1905-20260718/raw-packets \
  --source-input tmp/daily3-real-1905-20260718/source-input-draft.json \
  --output-base /tmp/daily3-runs \
  --upstream-root /private/tmp/hermes-gzh-design-3ChZEA/gzh-design-skill \
  --expected-commit ba1f4175519b481cb3566616c9e5178705067904 \
  --expected-validator-sha256 de21aa3decac10c6ef89040bdc4e19930dbed33d6ccf7bc963b744c53da01185
```

`--run-id` must be unique under `--output-base`. Before any pipeline stage, the
orchestrator atomically creates an owner-claim directory for that id. Existing
output or an already-held claim is rejected as `RUN_OUTPUT_ALREADY_EXISTS` with
exit `20` and no traceback. The losing process creates no work directory,
delivery candidate, or hidden temporary candidate; the winning process removes
its claim and temporary directory after atomically retaining the one canonical
run directory.
If any `Exception` during work-directory initialization fails after obtaining the atomic claim, the
orchestrator removes that claim and any temporary work directory, returns the
stable `RUN_INITIALIZATION_FAILED` contract with exit `20`, and leaves the same
`run_id` available for a subsequent retry.
It must also exactly equal the top-level `run_id` of the explicit source-input
JSON. The source input is not rewritten: its raw facts and source identity stay
intact, and the exact matching identity is propagated through source, adapter,
structural-gate, delivery, outer manifest, and audit events.
The resulting run directory contains `manifest.json`, `audit/events.jsonl`,
staged `raw-packets/`, source and adapter inputs, structural-gate artifacts,
provenance reports, and (only when all validation stages pass) `delivery/`.

## Manifest contract

Every manifest includes these explicit booleans:

- `source_packet_verified`
- `three_slot_structural_gate_passed`
- `delivery_html_validated`
- `publication_authorized=false`
- `publication_performed=false`

A successful orchestration exit means only that an offline candidate was created
and its local HTML validator passed. It does not mean release acceptance,
controlled WeChat preview, publication authorization, or publication occurred.

On failure, the manifest is retained with `status=failed`, a stable
`failure_code`, and no `delivery/` candidate directory. No prior run is read or
reused.

Before a delivery candidate is retained, the orchestrator validates the full,
bounded T1 output contract, not merely its renderer manifest. It requires
exactly `slots/A`, `slots/B`, and `slots/C`; each slot must contain non-empty
`article.html`, `preview.html`, and `evidence.json`. Article and preview output
must meet the local HTML shape checks, preview must be a complete HTML document,
and each evidence JSON must exactly equal the expected adapter candidate's
evidence. The manifest slot record must bind the expected `candidate_id` and a
validator record with `validated=true`; no missing, extra, contradictory, or
mismatched slot can become a candidate.

The minimal consistent T1 validator record is a JSON object with literal
`validated=true`. If it includes `returncode`, it must be the integer `0`; it
must not include `error`; and its optional string `stderr` or `diagnostics`
must not contain `ERROR` or `WARNING` (case-insensitive). A record violating
any of these conditions is contradictory and fails as
`DELIVERY_ARTIFACT_INVALID` (exit `25`) with delivery cleanup and `run_failed`.

The renderer manifest is also required to be a non-publishing contract: matching
`run_id`, `status=rendered_not_published`, literal `false` for both
`publication_authorized` and `publication_performed`, and a two-field
`release_acceptance`. Renderer exit `2` is valid only with
`{"status":"not_accepted","reason":"WECHAT_PREVIEW_UNVERIFIED"}`. Invalid
JSON, non-object JSON, missing or contradictory fields, and exit/state mismatch
fail closed as `DELIVERY_MANIFEST_INVALID` (exit `25`), append `run_failed` to
the audit, set `delivery_candidate_created=false`, and remove the entire
`delivery/` directory before the failed run is retained. Missing, empty,
invalid, or identity-mismatched delivery artifacts fail as
`DELIVERY_ARTIFACT_INVALID` with the same exit `25` cleanup contract.

## Exit codes

| Exit | Meaning |
| --- | --- |
| `0` | All source, structural, provenance, and local delivery-validator stages completed; candidate remains non-publishing. |
| `20` | Invalid arguments, run id, pre-existing run output, or an atomically held concurrent run-id claim (`RUN_OUTPUT_ALREADY_EXISTS`). |
| `21` | Raw allowlist/staging, source-packet verification, or source `run_id` identity check failed. |
| `22` | Adapter failed. |
| `23` | Three-slot structural gate failed. |
| `24` | Full raw-to-gate provenance verification failed. |
| `25` | T1 delivery HTML validation failed (`DELIVERY_HTML_VALIDATION_FAILED`), the delivery manifest violated the non-publishing contract (`DELIVERY_MANIFEST_INVALID`), or bounded slot artifacts/identity/validator evidence are invalid (`DELIVERY_ARTIFACT_INVALID`). |
| `26` | Fresh source-bundle or isolated delivery-ledger boundary rejected the input or prior delivery identity. |

There is deliberately no success code for publication, authorization, cron
installation, live-fetch fallback, or historical quota fill.

## Shadow no-agent cron

`scripts/daily3_shadow_cron_runner.py` is the scheduler-level shadow wrapper.
It uses the accepted controlled fixture only, gives its copied source input a
fresh shadow `run_id`, writes exclusively below
`/Users/Allen/.hermes/artifacts/media-intel/daily3-shadow/`, and emits one
fresh `shadow-cron-evidence.json` per successful run. It verifies all three
required slots, provenance, delivery artifacts, and literal non-publication
booleans before a zero exit. Any missing contract artifact fails nonzero.

It is not the formal 17:00 job and never changes, invokes, or publishes through
that job. The shadow job is scheduled independently and uses `deliver=local`.
Rollback is deletion of the shadow job only; retain run artifacts for audit.
