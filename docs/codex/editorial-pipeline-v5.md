# 文章组 V5 离线自适应反馈层

V5 是文章组的证据与候选生产层。文章组先决定选题，V5 再读取该题目的实验、生命周期、文章 DNA、指标失败样本、四周配额、策略版本和资源候选。它不自动选题、换题、抓取、写作、发布、升级爆款库或授予发布权限。

## 运行边界

- 只读取显式 `--run-dir` 下的 JSON/Markdown；路径解析会拒绝逃出运行根的文件和不支持的输入类型。
- 只写显式 `--output-dir` 或 `--output-path` 下的 JSON；写入前拒绝不同内容覆盖，同内容重复运行保持幂等。
- 不联网、不写 Vault、不生成 HTML，不保存 cookie、token、API key 或连接串。
- `CONTENT_READY` 只表示可以交给文章组/controller 复核；`publication_authorization` 始终为 `not_authorized`。
- 受控 fixture 是合成输入，不进入爆款库，也不代表真实事实或发布结果。

## 八个产物

所有产物使用五字段 envelope：`schema_version`、`run_id`、`generated_at`、`input_hashes`、`payload`。

| 文件 | schema | 内容 |
|---|---|---|
| `experiment-record.json` | `v5-experiment-record-v1` | 单一改变变量、控制条件、处理/对照和谨慎归因 |
| `content-lifecycle.json` | `v5-content-lifecycle-v1` | `draft → published → observing → stable → rising → decaying → evergreen → archived` |
| `article-dna.json` | `v5-article-dna-v1` | 题材、标题、人物、数字、场景、长度、平台等描述特征 |
| `failure-samples.json` | `v5-failure-samples-v1` | 失败类型、实际指标、阈值和建议改变 |
| `dynamic-quotas.json` | `v5-dynamic-quotas-v1` | 最近四周的中位数、样本/周门槛、风险上限、冷却和降权 |
| `strategy-library.json` | `v5-strategy-library-v1` | `provisional → testing → supported → deprecated → retired` 的版本化策略 |
| `resource-plan.json` | `v5-resource-plan-v1` | `full_capture`、`evidence_recovery`、`light_capture`、`sol_review`、`stop` 建议 |
| `v5-verification.json` | `v5-verification-v1` | 模块状态、缺失来源角色、重试、人工升级、hash 和读回结果 |

## 受控运行输入

fixture/运行根至少包含：`batch.json`、`experiment.json`、`observations.json`、`article-records.json`、`metric-events.json`、`quota-history.json`、`strategy-input.json`、`strategy-evidence.json`、`resource-candidates.json`、`resource-budget.json`、`source-audit.json` 和一个安全 `draft.md`。来源角色只作审计，不把发现或社交信号自动升级为事实证明。

## CLI

单模块命令支持 `experiment`、`lifecycle`、`dna`、`failures`、`quotas`、`strategy`、`resources`；它们都必须同时给出显式运行根和输出位置：

```bash
.venv/bin/python scripts/article_group_v5.py experiment \
  --run-dir tests/fixtures/v5/controlled-001 \
  --output-path runs/2026-09-09/v5/experiment-record.json
```

整体验证命令会写精确八个 JSON：

```bash
.venv/bin/python scripts/article_group_v5.py verify \
  --run-dir tests/fixtures/v5/controlled-001 \
  --output-dir runs/2026-09-09/v5/controlled-001
```

也可以将 `verify` 的报告指定为 `--output-path <.../v5-verification.json>`，其余七个文件会写入同一父目录。缺少 `--run-dir` 或输出位置时 CLI 返回参数错误；已有不同内容时输出 `refuse_overwrite` 并保持原文件不变。

## 关键规则

实验只改变一个变量；没有受控条件时只能得到 `observational`、`inconclusive` 或 `confounded`。`supported_under_design` 需要跨处理/对照样本、控制条件和 controller 确认，不能写裸 `causal=true`。

生命周期的 `published` 必须绑定具名外部发布事件；观察状态必须有带时间、指标和引用的观察证据；`evergreen`、`archived` 需要 controller 决定。生命周期不会产生发布授权。

DNA 每个特征标记 `explicit`、`derived` 或 `unavailable`，且固定 `fact_proof=false`。失败样本只有在指标真实可用时分类：

- `exposure_without_click`
- `click_low_completion`
- `high_completion_low_exposure`
- `high_interaction_low_revenue`
- `good_data_high_risk`
- 指标不足时 `insufficient_data`，不以零填充

配额只看最近四周，按日中位数再跨日汇总；样本按唯一 `sample_id` 计数，数据不足保留 baseline。`min/max/high-risk cap` 冲突、窗口越界、重复样本和计数不一致均 fail-closed。配额不会自动生效。

策略只有在至少三个可用证据样本跨两周、证据属于策略声明的样本闭集、且 controller 明确 `approve_support` 时才可进入 `supported`。相关性/观察证据即使有 approval 也不能晋级；非法策略成员、辅助状态和 transition 会被拒绝。

资源映射为：高价值/高就绪 `full_capture`，高价值/低就绪 `evidence_recovery`，低价值/高风险 `stop`，普通候选 `light_capture`，高潜力/高争议 `sol_review`。资源计划只给 owner、成本、理由和人工复核建议，不执行动作。

V5 adapter 先检查 V3 状态转移；`approved → researching` 需要 experiment 和非 `stop` 资源计划；`material_ready → writing` 会阻止 archived/retired、高风险和 `insufficient_data`；`review → closed` 仍由 V3 原门禁决定。V4 契约和状态词表保持不变。

## 验收报告

`v5-verification.json` 分开记录：

- `status` / `decision` 与逐模块 PASS/BLOCKED；
- `missing_source_roles`；
- `retry_requirements`；
- `manual_escalations`；
- `content_status=CONTENT_READY|CONTENT_BLOCKED`；
- 八个产物的 hash（报告自身使用明确的 self-hash basis）和 `read_back=true`；
- `publication_authorization=not_authorized`。

最终是否进入写作、改稿、交付或发布，仍由文章组/controller 按 V3/V4 门禁决定。
