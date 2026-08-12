# Case Card（结构卡模板 — P1 冻结 2026-08-11）

> **证据域**：`competitive_research_evidence`（唯一）
> **唯一用途**：竞争文章的正文/结构拆解、平台文章级表现、爆文资格及技法归纳（候选）
> **禁止用途**：不得作为若雨正文的事实来源、事实 locator 或 claim 证明；不得承载若雨正文 claim locator。
> **机械校验**：`article_group/case_contract.py`（`validate_case_card`）；模板字段冻结见 v1.1 设计 §1.0.3 / §③。

## 卡头元数据（必填）

| 字段 | 语义 | 来源/约束 |
|---|---|---|
| `evidence_domain` | 固定 `competitive_research_evidence` | 冻结常量，不可改 |
| `sample_id` | 每篇竞争文章唯一标识 | 与 performance_evidence 一致 |
| `article_url` | 原始 URL | 与全文快照一致 |
| `platform` | 平台 | 与 performance_evidence 一致 |
| `discovery_signal` | 发现通道线索（来自 R0 radar / 搜索 / 榜单） | 仅检索线索，不构成表现证据 |
| `fulltext_snapshot_ref` | 全文快照路径 + `#sha256=` | `runs/<date>/viral-research/sources/` |
| `performance_evidence_ref` | 表现档案路径 | `runs/<date>/viral-research/metrics/` |
| `qualification_status` | `qualified_viral` / `observed_pending` / `research_only` | 由 performance_evidence 机械判定，不可手写 |
| `qualification_reason` | 逐项判定理由 | 与表现档案一致 |
| `sample_rank` | 仅 `qualified_viral` 在知识库爆款实证表的序号 | P3 回填时分配，P1/P2 留空 |

## 拆解 9 字段（day1 实证格式，每篇爆文一张卡）

1. **标题承诺**：标题向读者承诺什么、用什么机制（数字/权威/冲突/悬念…）。
2. **开头钩子**：前两段如何入题（热点事件/金句/生活近况/结论先行…），多少秒内建立什么。
3. **结构轮廓**：分段大纲，从钩子到收尾的骨架与顺序。
4. **人物利益冲突**：文中人物/阵营的利益与冲突（谁对谁、为什么）。
5. **读者问题**：读者带着什么疑问进来，正文给出什么答案。
6. **获得感来源**：信息增量 / 新视角 / 情绪价值，至少标注是哪几种。
7. **人味特征**：口语、立场句、细节具象、真人近况等“像人”的特征。
8. **评论切入点**：可直接引发评论区讨论的问题（Allen 用自己的话写）。
9. **可复用技巧**：每条标状态 `promising`（候选）；≥3 篇同向验证且经 controller 裁决才可升 `verified`。

## ⚠️ 负样本提示（可选区，头条等样本卡）

- 命中反例模式时填写（如“关注+免责声明”模板、AI/搬运味特征），供 P2 聚合入反例库。

## 边界（违反即作废）

- 结构卡不得承载或引用若雨正文 claim locator（`claim_locator` 属于 `ruoyu_article_fact_evidence` 域）。
- 拆解内容必须来自 `fulltext_snapshot_ref` 同篇全文；不得凭标题、摘要、账号体量或搜索排序推断。
- 「可复用技巧」在 P2 蒸馏与 controller 裁决前一律 `promising`，本阶段不得生成正式技巧条目。
- `observed_pending` / `research_only` 样本的拆解卡只能作为观察/补采/反例材料，不得支撑正式正向技巧。
