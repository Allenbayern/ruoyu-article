# 文章组 V5：自适应内容操作系统设计

## 目标

V5 在 V4 的证据、调度和反馈基础上，增加可复核的实验管理、内容生命周期、文章 DNA、失败样本学习、动态配额、版本化策略库和资源预算建议。它回答“这篇内容为什么表现好或不好，以及下一篇具体改变什么”，但不把相关性自动升级为因果结论。

V5 仍属于文章组的离线反馈与候选生产层：文章组控制选题，Luna 负责选题后的标题与初稿，Sol 负责高风险/争议复核，controller 负责最终取舍。V5 不抓取网络、不写 Vault、不生成发布物、不授权发布，也不自动换题。

## 约束与术语

- V3 状态词表保持 `idea → precheck → approved → researching → material_ready → writing → review → closed`，并保留 `returned`。
- `CONTENT_READY` 只表示材料/稿件已达到交给真人处理的状态；`publication_authorization` 固定为 `not_authorized`。
- 发现信号、社交反应和历史草稿可以作为实验输入或待验证信号，不能单独证明事实。
- 指标缺失用 `null + *_status=unavailable` 表示，绝不以零填充。
- 所有建议均是 `auto_apply=false` 的 controller 输入；V5 不自动选题、发布、晋级策略或调整正式配额。
- 实验的“因果证据”是受设计条件约束的证据状态，不是机器对平台真实因果关系的保证。

## 产物边界

每个产物使用封闭 JSON envelope：

```json
{
  "schema_version": "v5-...-v1",
  "run_id": "...",
  "generated_at": "RFC3339",
  "input_hashes": {"input.json": "sha256"},
  "payload": {}
}
```

V5 新增八个版本化 schema，放在 `schemas/editorial-pipeline-v5/`，不修改 V4 的冻结 schema/词表：

| 产物 | schema | 作用 |
|---|---|---|
| `experiment-record.json` | `v5-experiment-record-v1` | 假设、单一变量、控制条件、指标、处理组/对照组和归因结果 |
| `content-lifecycle.json` | `v5-content-lifecycle-v1` | 内容生命周期状态、转移证据和下一动作 |
| `article-dna.json` | `v5-article-dna-v1` | 可比较的题材、标题、正文、时间与平台特征 |
| `failure-samples.json` | `v5-failure-samples-v1` | 失败模式、证据指标和下一步改变 |
| `dynamic-quotas.json` | `v5-dynamic-quotas-v1` | 最近四周的配额建议、上下限和数据充分性 |
| `strategy-library.json` | `v5-strategy-library-v1` | 策略版本、样本、成功条件、失败边界和状态 |
| `resource-plan.json` | `v5-resource-plan-v1` | 按价值、证据就绪度和风险分配抓取/复核预算 |
| `v5-verification.json` | `v5-verification-v1` | 八产物的独立检查、缺口、重试、人工升级和读回结果 |

## 核心模块

### 1. 实验记录与谨慎归因

`build_experiment_record` 要求 `hypothesis`、`changed_variable`、至少一个保持不变的 `controls`、至少一个 `metrics`、题目身份、实验周和处理/对照分组。一个实验记录只能声明一个改变变量；同题不同标题、同类型对照、固定发布时间窗口和平台分发条件作为结构化字段记录。

`assess_experiment` 对观测值只输出：

- `observational`：可比较但未满足受控条件；
- `inconclusive`：样本或指标不足；
- `confounded`：题材、时间、平台或分发条件同时变化；
- `supported_under_design`：满足记录的设计条件、样本最低要求和控制器确认后的受限支持。

任何输出都不使用裸的 `causal=true`，也不把相关性直接写成因果结论。结果必须列出可用指标、缺口和混杂因素。

### 2. 内容生命周期

状态固定为：

```text
draft → published → observing → stable → rising → decaying → evergreen → archived
```

发布状态必须有明确的外部发布事件；观察、稳定、上升和衰减由已记录的指标窗口推导，但 `evergreen` 与 `archived` 必须有 controller 决定。每次转移记录原因、事件引用和下一动作：`rising` 可建议追加相关内容，`decaying` 建议停止重复跟进，`evergreen` 允许进入常青候选池，`archived` 只保留学习记录。

### 3. 文章 DNA

`extract_article_dna` 从显式文章字段和明确标注为 derived 的文本特征中生成稳定特征：题材类型、标题结构、人物/数字/关系冲突/具体场景/片单、情绪方向、字符/段落长度、首屏信息类型、结尾方式、发布时间和平台。每个特征带 `source=explicit|derived|unavailable`；DNA 不承担事实证明，不推断作者意图或因果关系。

### 4. 失败样本

`classify_failure_sample` 在指标足够时分类：`exposure_without_click`、`click_low_completion`、`high_completion_low_exposure`、`high_interaction_low_revenue`、`good_data_high_risk`。输出允许多个类别，但每一类都要有实际指标、阈值和建议改变；指标不足返回 `insufficient_data`，不伪造失败。风险高的样本只建议人工复核或停止复制。

### 5. 动态配额

`derive_dynamic_quotas` 只读取最近四周带日期的结果，按题材/风险汇总样本量、中位 RPM、完成率、失败类型和连续失败次数。它输出带上下限的 `recommended_share`、最低样本量、完成率下限、风险上限、重复主题冷却期和降权因素；数据不足时保持基线并标明原因。正式生效必须由 controller 显式采纳。

### 6. 版本化策略库

策略记录字段固定包含：`strategy_id`、`version`、适用题材、假设、证据样本、成功条件、失败边界、最近验证时间、状态。状态为 `provisional → testing → supported → deprecated → retired`。只有达到最低跨样本/跨时间证据并经过 controller 的 `approve_support` 才能进入 `supported`；相关性观察只能产生建议，不能自动晋级。

### 7. 资源与人机分工

资源计划根据每个已选候选的价值、证据就绪度、潜在流量和争议风险给出建议：高价值/高就绪度 `full_capture`，高价值/低就绪度 `evidence_recovery`，低价值/高风险 `stop`，普通题材 `light_capture`，高潜力/高争议 `sol_review`。计划包含预算、责任人、理由和人工升级，但不会执行抓取或改动题目。

## V3/V4 接口

新增 `validate_v5_transition_context` 作为 V3 状态机的附加 adapter：

- `approved → researching` 必须有文章组确认的实验记录和非 `stop` 资源计划；
- `material_ready → writing` 不能有 `insufficient_data`/高风险未升级、`archived` 或 `retired` 阻塞；
- `review → closed` 仍由现有 V3/controller 门禁决定，V5 不替代审核；
- 所有嵌套产物的授权字段都必须是 `not_authorized`。

## 离线运行与验收

`scripts/article_group_v5.py verify --run-dir <显式运行根> --output-dir <显式输出目录>` 只读 JSON/Markdown 输入，写八个产物并逐一读回。写入采用幂等且拒绝不同内容覆盖；输出目录不写 HTML、cookie、token、API key 或网络响应。

最终报告分别列出：

- `status/decision` 与每个模块的 PASS/BLOCKED；
- 缺失数据/来源角色、重试要求、人工升级项；
- `content_status`；
- `publication_authorization=not_authorized`；
- 每个产物的 hash 和 `read_back=true`。

受控 fixture 使用合成指标，明确标为测试输入，不进入爆款库或永久策略。测试覆盖每个函数的正向、缺失指标、越权状态、混杂归因、越界配额、未经 controller 晋级、资源 stop 和幂等拒绝覆盖。
