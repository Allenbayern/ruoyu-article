# Candidate Card

- candidate_id:
- batch_id:
- state: `R1 normalized-candidates`
- scan_at:
- event_time:
- first_seen_at:

## Subject

- work:
- person_or_org:
- event:
- freshness_window: `same-day | fermenting-1-3d | revival`
- content_map:

## Signal

- source_url:
- publisher:
- source_role: `discovery | audience-reaction | confirmed-primary | confirmed-secondary | structured-data`
- independence_group:
- signal_summary:
- source_level: `headline-only | full-text | primary | structured-data`

## Editorial Intake

- potential_primary_atom:
- human_anchor:
- conflict_emotion_gap:
- reader_intent:
- why_now:
- risk_tags:
- denial_or_conflict_status:
- evidence_gap:
- recommendation: `A | B | C | Archive | Reject | Wait`
- reason:

## Five Gates（社会热点必填，影视文章填 N/A）

- five_gates_result: `PASS | CONDITIONAL | FAIL | N/A`
- gate1_news_license: `PASS | CONDITIONAL | FAIL`
- gate2_privacy: `PASS | CONDITIONAL | FAIL`
- gate3_judicial: `PASS | CONDITIONAL | FAIL`
- gate4_copyright: `PASS | CONDITIONAL | FAIL`
- gate5_sensationalism: `PASS | CONDITIONAL | FAIL`
- compliant_angle: （仅 `CONDITIONAL` 且推荐 `A | B | C` 时必填；说明可追溯的改角度/改写约束）
- fail_reason: （`FAIL` 时必填）
- fail_disposition: `Archive | Reject | Wait`（`FAIL` 不得推荐 `A | B | C`；可留档，不连坐整池）
