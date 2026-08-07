# Ruoyu Film Daily

> **中文版：** [README.zh-CN.md](README.zh-CN.md) · **English:** [README.md](README.md)

Controlled-production workflow for the Ruoyu (若雨随影) film article group:
offline gates, source capture, discovery radar, and adversarial-reviewed delivery
batches. All validators are deterministic and fail-closed; nothing in this
repository ever publishes, merges, deploys, or sends messages.

## Current state

- Controlled batches through **controlled-014**: three publish-level drafts
  produced under the adversarial-review Gate (Sol independent review →
  scoped repairs → re-review → controller acceptance). Deliverables are
  frozen single-file HTML with producer provenance seals; no external
  publication is performed.
- 345 offline tests pass (validators, CLI, source capture, discovery radar,
  compliance gates, absorbed offline sample parsers).
- No cron, source registry, publisher integration, image pipeline, or
  publication path is implemented or authorized.
- 2026-08-07: absorbed 8 offline sample parsers from the legacy
  `media-intel-aios` project into `article_group/sources/`; the legacy
  project's automation is backed up read-only under `projects/media-intel-aios/`
  (dormant, not enabled).

## Layout

| Path | Purpose |
|---|---|
| `article_group/workflow.py` | Controlled-run state machine and batch validation (R0–R8, delivery authorization) |
| `article_group/prewrite.py` | Pre-write gates: candidate pools, slots, freshness windows, editorial selection |
| `article_group/compliance_gate.py` | Three-state (PASS/CONDITIONAL/FAIL) social-topic compliance gate with five gates and graded rules |
| `article_group/compliance_cli.py` | Manual CLI: five-gates compliance declaration check (`--pool`/`--candidate`, `--json`) |
| `article_group/sync_compliance.py` | Sync five-gates declarations from candidate JSONs into a Markdown checklist |
| `article_group/toutiao_capture.py` | Public Toutiao article snapshot for evidence (no cookies/JS/anti-bot) |
| `article_group/toutiao_cli.py` | CLI entry point for the Toutiao capture |
| `article_group/yuafeng_hot.py` | Read-only Yuafeng hot-list client (UC, Tencent News, aggregates) |
| `article_group/discovery_radar.py` | Isolated R0 discovery-radar artifact builder |
| `article_group/yuafeng_radar_cli.py` | CLI to build one R0 discovery-only radar JSON |
| `article_group/sources/` | Absorbed offline sample parsers (Douban, Vocus, Xiniu, hotboard, Zhihu backfill, lead routing) — pure stdlib, no network, no credentials, no judgment; absorbed from the legacy `media-intel-aios` project (2026-08-07) |
| `article_group/delivery.py` | Plain-text deliverable derive/validate (Markdown stays canonical) |
| `article_group/git_hygiene.py` | Fail-closed git hygiene gates (never runs git itself) |
| `briefs/` | Per-task contract briefs (authoring, repairs, Sol review/re-review) |
| `templates/` | First-run brief, candidate card, evidence pack, delivery checklist, five gates |
| `runs/` | Per-run roots: sources, drafts, frozen artifacts, review packets, seals |
| `projects/media-intel-aios/` | Read-only legacy backup (code/tests/README snapshot, daily3 automation kept dormant) — never imported or run without explicit authorization |

## Verification

```bash
uv run python3 -m pytest -q
```

Tests use synthetic records only. They verify state transitions, slot and angle
separation, claim-coverage requirements, withheld HTML, freshness windows, the
no-publication boundary, and the compliance surface.

## Manual source capture (Toutiao)

Fetches one explicit public article URL into an explicit local run root. A
successful command writes only `sources/<source-id>.txt` and one
source-manifest entry; it never selects a candidate, creates an article,
advances a workflow state, or publishes.

```bash
uv run python -m article_group.toutiao_cli \
  --url 'https://www.toutiao.com/article/<article-id>/' \
  --run-root runs/2026-08-01/controlled-001 \
  --source-id TT-<article-id> \
  --independence-group toutiao:<article-id>
```

## Discovery radar (Yuafeng)

Read-only trending-list discovery. Every result is discovery-only — never
evidence for factual claims.

```python
from article_group.yuafeng_hot import fetch_uc_hot, fetch_tencent_news, fetch_aggregate

result = fetch_uc_hot()
result = fetch_tencent_news(page=1, type_="hot")
result = fetch_aggregate("微博热榜")  # 知乎热榜/微博热榜/微信热文榜/澎湃热榜/百度热点/知乎日报/今日头条热榜/梨视频总榜
```

The API key is read from the `YUAFENG_API_KEY` environment variable at
call-time; it is never persisted, logged, or included in exception messages.

Build a local R0 radar artifact (discovery-only JSON, caller-addressed):

```bash
uv run python -m article_group.yuafeng_radar_cli \
  --output-path runs/2026-08-05/radar/r0.json \
  --sources '[{"name": "uc"}, {"name": "aggregate", "action": "微博热榜"}]'
```

## Compliance surface

```bash
# Declaration check for a candidate pool or a single candidate
uv run python -m article_group.compliance_cli --pool runs/<run>/candidates.json

# Sync declarations into the Markdown checklist
uv run python -m article_group.sync_compliance \
  --input path/to/candidates.json --output docs/social-compliance.md
```

Exit code 0 means each declaration passes the validator; it does not mean
every candidate's declared grade is PASS.

## Delivery discipline

- Markdown is canonical; `article-plain.txt` is the copy-paste deliverable for
  platforms that do not parse Markdown.
- Publish-level batches freeze a single-file HTML deliverable (inline CSS) and
  record a provenance seal binding `sha256:<digest>` of the frozen artifact;
  the binding is verified before acceptance.
- Batch acceptance requires fresh evidence reviewed by the controller; final
  review is performed independently (Sol route) under the adversarial-review
  Gate, and the controller makes every acceptance decision. Nothing here
  authorizes external publication.

## Boundary

A green local validator confirms only deterministic batch gates — it does not
establish factual truth, article quality, `publish-ready`, or publication
authorization. Factual assertions require verbatim citations in the run's
`citations-ledger.json`.
