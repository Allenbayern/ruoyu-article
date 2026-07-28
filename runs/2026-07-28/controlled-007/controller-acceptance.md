# controlled-007 Controller Acceptance

## Run
- `run_id`: `2026-07-28/controlled-007`
- `mode`: dry run (controlled, no publication, no push)

## Sol L2 review
- Pass 1: `deleg_5c7fa621` → **needs_changes** (C7-F01/F02/F03 major)
- Scoped repair: F01 A13 attribution to A01; F02 B hedged causality; F03 C13 attribution to C03
- Micro: `deleg_90dbec96` → **approve** (all three fixed)

## Mechanical gates (post-repair)
- validate_batch : []
- validate_source_manifest : []
- validate_run_plain_delivery : []
- claim inventory + locators : []
- full pytest: 182 passed
- char counts: A 1844, B 1821, C 1834

## Controller decision
- **Accepted: R8 review-ready**
- Publication authorization: **not_authorized**
- Delivery: **withheld** — no push, no HTML, no unattended daily

## Independence from 005/006
- 005 leads: 八仙提档逆袭 / 功夫女足口碑票房 / 四渡青年
- 006 leads: 群星撤档 / 双撤与提档 / 撤档潮
- 007 leads: 年会提档补位 / 八仙连续两日单日反超 / 三国高口碑低排片撤档
- No same-lead reuse

## Dry-run assessment
Three independent atoms passed full L2 gate → R8. P0 hardening held: no mechanical green minted R8, no AI/synthetic primary, no causal overclaim, plain locked to md. Next: ready for controlled-008 (or user-directed push) — **still not unattended daily**.
