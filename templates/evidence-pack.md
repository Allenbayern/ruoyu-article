# Evidence Pack（若雨事实证据包 — P1 冻结 2026-08-11）

> **证据域**：`ruoyu_article_fact_evidence`（唯一）
> **唯一用途**：若雨待写/已写文章的事实主张、时效、来源定位与审核。
> **禁止用途**：不得以竞争文章的标题、观点、数字或其表现数据替代独立事实来源；不得携带竞争样本引用或资格词汇（`competitive_sample_refs` / `qualification_status`）。
> **机械校验**：`article_group/case_contract.py` — `validate_fact_evidence_pack`。

- evidence_domain: `ruoyu_article_fact_evidence`
- article_id:
- candidate_id:
- captured_at:
- state: `R4 evidence-ready`
- coverage_gaps: `none | ...`

## Sources

| source_id | level | URL | publisher / author | published_at | accessed_at | independence_group | full-text | sha256 | locator | access / rights |
|---|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | | |

## Claim Ledger

| claim_id | claim | type: fact / attributed view / inference | source_id | extract | locator | permitted wording |
|---|---|---|---|---|---|---|
| | | | | | | |

## Boundaries

- must_not_say:
- rejected_claims:
- conflict_or_denial:
- rumor_or_privacy_rule_applied: `n/a | pass | block`
- evidence_decision: `ready-for-brief | waiting-source | draft-only`

## 边界（违反即作废）

- 每条 claim 必须可定位到独立 `source_snapshot_ref`（含 SHA-256）与 `claim_locator`；不得引用竞争样本快照。
- 事实包禁止携带 `qualification_status`（竞争域词汇，P0-B 校验 `fact_evidence_cannot_carry_qualification`）。
- 事实包禁止引用 `competitive_sample_refs`（P0-B 校验 `fact_evidence_cannot_reference_competitive_samples`）。
- 发布回填（`production_feedback_evidence`）不得满足若雨 claim gate（P0-E5）。
