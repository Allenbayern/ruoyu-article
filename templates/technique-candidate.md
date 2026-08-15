# Technique Candidate（技巧候选观察页 — P1 冻结 2026-08-11）

> **证据域**：`competitive_research_evidence`（唯一）— 记录字段：`evidence_domain: competitive_research_evidence`
> **状态规则**：本页只允许**观察条目**（`promising` / observation）。正式技巧条目（`verified`）需 P2 蒸馏、≥3 个不同账号、≥3 个不同题材且经 controller 裁决后另行固化；P1 阶段不得生成正式技巧条目。
> **机械校验**：`article_group/case_contract.py` — `validate_technique_candidate` / `validate_feedback_record`。

## 字段

| 字段 | 语义 | 约束 |
|---|---|---|
| `technique_id` | 唯一标识（T 系列） | 非空 |
| `kind` | `title` / `opening` / `structure` / `interaction` | 非空，枚举内 |
| `name` | 技巧名（具体、可操作，非泛写作方法） | 非空 |
| `observation_source` | 来源样本 `sample_id` + `qualification_status` | 必须真实存在；`observed_pending` / `research_only` 样本只能产生观察条目 |
| `qualified_sample_refs[]` | 支撑样本引用 | 客户端路径至少 1 个 `qualified_viral`；混合路径至少 2 个 `vendor_qualified` |
| `evidence_basis` | `client_only` / `mixed_client_vendor` | 混合正式技巧必须显式写 `mixed_client_vendor`; vendor-only 不得升级为正式技巧 |
| `supporting_qualified_samples[]` / `supporting_vendor_samples[]` | 支撑样本及证据引用 | 不得把供应商指标写成客户端指标 |
| `verification_state` | `promising` / `verified` | P1 一律 `promising` |
| `automatic_publication_authority` | 是否有自动发布权 | 必须为 `false`；技巧证据不构成发布授权 |
| `evidence_notes` | 观察依据（引用结构卡字段） | 引用 `fulltext_snapshot_ref` 同篇内容 |
| `reverse_examples` | 反例/边界（可选） | 命中反例模式时填写 |

## 规则（违反即拒绝）

- `observed_pending` / `research_only` / 若雨单篇回填**不得**单独支撑正式正向技巧（P0-A3）。
- 每条 `verified` 客户端技巧必须回链 ≥1 个 `qualified_viral` 样本的全文快照与表现档案（P0-E4）。
- `mixed_client_vendor` 正式技巧必须同时满足：≥1 个 `qualified_viral`、≥2 个 `vendor_qualified`、3 个不同账号、3 个不同题材、`verification_state: verified`、`automatic_publication_authority: false`。
- 发布回填（`production_feedback_evidence`）只能更新 `verification_state`，不得改变竞争样本 `qualification_status`（P0-E5）。
- 分类是为了调用准确，不是脱离爆款来源的泛写作方法。
