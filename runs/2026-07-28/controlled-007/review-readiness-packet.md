# controlled-007 Sol L2 Review-Readiness Packet

## Meta
- `original_request_ref`: Allen authorized controlled-007 dry run after P0 six slices; sequential path: 3 independent atoms → mechanical R7 → Sol L2 → controller close; no publish/push
- `run_id`: `2026-07-28/controlled-007`
- `risk_tier`: L2
- `l2_trigger_ids`: [`material_publish_claim`]
- `material_uncertainty`: none beyond normal content/source verification (primary sources are real news HTML snapshots; no synthetic:// primary)
- `non_goals`: publication; push; HTML delivery; unattended daily; rewriting 005/006; elevating mechanical green to R8
- `attack_surface_menu`: content/editorial

## Acceptance criteria
| ID | Criterion | Evidence ref |
|---|---|---|
| AC1 | 3 independent Primary Atoms (work / event_cluster / reader_question distinct) | E-pool, E-contract, E-gates |
| AC2 | No AI/synthetic/placeholder confirmed-primary | E-source-manifest, source HTML |
| AC3 | Chinese char count 1500–2200; first-pass aim ≥1800 | E-md char counts |
| AC4 | Claim inventory v2 complete: material_claim_ids ↔ mappings; draft_locator in md; fact/attribution have source+locator | E-gates + validate_claim_inventory [] |
| AC5 | Plain derive locked to md (single renderer); no residual markers; not stale | E-plain validate_run_plain_delivery [] |
| AC6 | build_controlled_run → only `R7 mechanically-verified`; publication_authorization=not_authorized | E-manifest |
| AC7 | No semantic reuse of 005/006 lead atoms as same cluster lead | E-compare-prior |
| AC8 | Sol finds no blocker on source verifiability / claim honesty / causal overclaim; or ≤1 scoped repair round | this review |

## Criterion evidence / negative paths
- AC1 positive: slot-contract.json + candidate-pool primaries cand-001/002/003 distinct clusters
- AC1 negative: validate_slot_contract [] (would fail on duplicate work/cluster/question)
- AC2 positive: source-manifest roles; validate_source_manifest []
- AC2 negative: gate rejects synthetic:// and 本文由AI生成 on confirmed-primary (Slice1 suite still green 182)
- AC3 positive: A1824 B1800 C1828
- AC4 positive: inv [] loc [] per slot
- AC5 positive: plain []
- AC6 positive: controlled-run-manifest.json state R7 mechanically-verified
- AC7 positive: 005 leads 八仙提档逆袭/功夫女足口碑/四渡; 006 leads 群星撤档/双撤提档/撤档潮; 007 leads 年会提档/八仙单日反超/三国撤档

## Artifact refs (path + sha256-16)
- `controlled-run-manifest.json` `7d2b954fde457c25` (rebuild may change; re-hash at review time)
- `source-manifest.json`
- `candidate-pool.json` / `slot-decisions.json` / `slot-contract.json`
- `articles/{A,B,C}/article-draft.md`
- `articles/{A,B,C}/article-plain.txt`
- `articles/{A,B,C}/article-gate.json`
- `articles/{A,B,C}/evidence-pack.json`
- `articles/{A,B,C}/writing-brief.json`
- `sources/*.html` (8 files)

## Evidence commands (local, no network required for mechanical)
```bash
cd /home/allen/Projects/ruoyu-film-daily
python3 -c "from pathlib import Path; import json; from article_group.workflow import validate_batch; from article_group.delivery import validate_run_plain_delivery; from article_group.prewrite import validate_source_manifest; run=Path('runs/2026-07-28/controlled-007'); batch={'run_id':'2026-07-28/controlled-007','publication_authorization':'not_authorized','articles':[json.loads((run/f'articles/{s}/article-gate.json').read_text()) for s in 'ABC']}; print(validate_batch(batch,run)); print(validate_run_plain_delivery(run)); print(validate_source_manifest(json.loads((run/'source-manifest.json').read_text()),run)); print(json.loads((run/'controlled-run-manifest.json').read_text())['state'])"
python3 -m pytest -q   # 182 passed
```

## Coverage gaps
- DailyHotApi (.168:4001) down; SearXNG on .1:4000 used for discovery
- web_extract blocked private LAN; sources captured via curl UA
- A/C slightly expanded with commentary depth after first short drafts; re-count green
- Historical 005/006 remain unmigrated to claim-inventory v2 (expected fail-closed; not this dry-run scope)

## Controller notes for Sol
- Mechanical green ≠ R8. Do not approve publication.
- Prefer local artifact verification; if SearXNG times out, do not treat timeout as approve.
- Watch especially: soft-causal motive language; claim_coverage honesty; AI/secondary-as-primary; title overextension; 005 semantic near-duplicate on 八仙 (007 B is single-day overtake consecutive, not 005 提档逆袭 lead).
