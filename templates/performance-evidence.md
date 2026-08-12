# Performance Evidence（平台文章级表现档案 — P1 冻结 2026-08-11）

> **证据域**：`competitive_research_evidence`（唯一）— 记录字段：`evidence_domain: competitive_research_evidence`
> **唯一用途**：以同一篇真实文章的平台可见文章级指标，机械判定爆文资格（`qualified_viral` / `observed_pending` / `research_only`）。
> **机械校验**：`article_group/case_contract.py` — `assess_qualification` / `validate_case_card`。
> 本档案属于竞争研究域，不构成若雨正文事实证据或发布授权。

## 必填字段

| 字段 | 语义 | 约束 |
|---|---|---|
| `sample_id` / `article_url` / `platform` | 每篇竞争文章唯一标识、原始 URL、平台 | 三者非空；与全文快照和结构卡可双向定位 |
| `performance_window` | 统计窗口起止、观测时点、平台时区 | 判定前写明；不可事后按结果补选窗口 |
| `metric_plan` | 该平台本次“实际可见且应采集”的文章级指标清单 | 判定前冻结；每项含 `metric` / `visible` / `required` / `source_type` / `capture_window` / `rule_role` |
| `metrics[]` | 每项含 `metric` / `value` / `status` / `source` / `observed_at` / `evidence_ref` | 每个 `metric_plan` 项都有一条记录；不得把未知项省略为“完整” |
| `threshold_or_rank_rule` | 平台、赛道/账号基线、窗口、阈值或排名规则 | 先于资格判定存在；`minimums` / `rank_maximums` 结构化；不可跨平台直接复用绝对数值 |
| `qualification_status` / `qualification_reason` | `qualified_viral` / `observed_pending` / `research_only` + 逐项判定理由 | 状态可由本档案机械复核，不依赖叙述性“爆文”标签 |

## 指标状态四态（availability_state）

- `client_confirmed`：平台客户端/后台确认的原始值
- `not_verifiable_offsite`：平台未公开该字段 → 显式标注，不得填 0 或推算
- `estimated`：估算值；**不得改写成平台精确值**
- `unknown`：尚未取得证据；不得被省略或解释为零

## 平台可见指标最小覆盖（如平台提供）

`read_or_view_count`（触达基线）、`like_count`、`comment_count`、`share_or_repost_count`、`article_rank_or_index`（如有）。

## 负向拒绝清单（任一命中即不得标 `qualified_viral`）

- 账号体量 / 热榜 / 搜索排名 / 榜单排序单独作为高浏览证明
- 单一阅读量（缺其余可见互动字段）
- 0、空值、推算值、“行业常态”补齐缺失字段
- `estimated` 冒充平台实测值
- `metric_plan` 后补（判定前未冻结）
- 绝对数值跨平台套用（微信 10万+ ≠ B站 10万 浏览 ≠ 头条阅读）
