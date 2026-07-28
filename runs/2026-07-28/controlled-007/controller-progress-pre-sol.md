# controlled-007 controller progress (pre-Sol)

## Status
- mechanical: **R7 mechanically-verified** (not R8)
- publication_authorization: **not_authorized**
- delivery: withheld pending Sol + controller
- full suite: **182 passed**
- Sol delegation: `deleg_5c7fa621` (in flight)

## Slots locked
| Slot | Title | Work | Intent | Chars |
|---|---|---|---|---|
| A | 别人撤档，它提前一周进场 | 年会不能停2提档 | 好奇 | 1824 |
| B | 星爷连坐13天，被动画连掀两天 | 八仙单日反超 | 惊讶 | 1800 |
| C | 8.1分干了三年，还是被挤出影院 | 三国争洛阳撤档 | 心疼 | 1828 |

## Independence vs prior batches
- 005 leads: 八仙提档逆袭 / 功夫女足口碑票房 / 四渡青年
- 006 leads: 群星撤档 / 双撤与提档 / 撤档潮
- 007 leads: 年会提档补位 / 八仙连续两日单日反超 / 三国高口碑低排片撤档

## Mechanical evidence
- validate_batch []
- validate_source_manifest []
- validate_run_plain_delivery []
- validate_candidate_pool / slot_decisions / slot_contract []
- claim inventory + locators [] (fact/attribution only for locator check)

## Next
1. Await Sol structured decision
2. If needs_changes → scoped repair by finding ID only → micro re-review
3. Controller acceptance only after Sol path closes
4. Optional daily-commit of `runs/2026-07-28/controlled-007/` only — **no push / no publish**
