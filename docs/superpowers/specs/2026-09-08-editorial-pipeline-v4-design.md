# 文章组 V4 生产闭环设计

**状态：** 已获用户确认，2026-09-08 进入实现。

## 目标

V4 在不改变 V3 状态机和“不自动发布”边界的前提下，增加组合级调度、统一证据追踪、缺口优先补材、反模板提醒、发布效果回填和可审计的回滚/人工升级。V4 的目标是提高长期命中率、减少重复判断和无效抓取；它不承诺单篇文章必然爆款。

## 仓库边界

- 主实现仓库：`/home/allen/Projects/ruoyu-film-daily`。这里拥有 Article Group 的 V3 状态机、文章组审核、内容交接和发布授权边界。
- 上游证据仓库：`/home/allen/Projects/media-intel-aios`。它继续负责来源发现、正文/信号采集和候选证据，不接管文章组的选题、审核、交付或发布。
- 两个仓库只通过 run-local JSON/Markdown 产物交接；V4 不跨仓库 import，不读写凭据，不写入 Obsidian Vault。
- V4 默认审阅面仍是 `markdown_codex`；HTML、发布、平台账号和外部消息均不在本次范围内。

## 不变的 V3 规则

- V3 状态仍为：`idea → precheck → approved → researching → material_ready → writing → review → closed`，`returned` 继续作为回退状态。
- 只有文章组确认的 topic 才能生成 crawl task；爬虫不能自行换题。
- 材料不足、证据失效或高风险内容不得绕过写作前门禁。
- `CONTENT_READY` 只表示 Markdown 可交给真人处理；`publication_authorization=not_authorized` 仍是默认且必须保持的值。
- 独立评审只产生证据，控制器才可接受；控制器接受不等于发布授权。

## V4 产物与契约

所有产物写入当前 run 的 `v4/` 目录或明确的 `review/` 子目录，不覆盖历史产物。

| 产物 | 版本 | 用途 |
|---|---|---|
| `v4/portfolio-plan.json` | `v4-portfolio-plan-v1` | 记录每日组合、约束判定、选题理由和缺口 |
| `v4/evidence-graph.json` | `v4-evidence-graph-v1` | 记录 topic、claim、source、material、title、opening、paragraph、review 的节点和有向边 |
| `v4/gap-priority.json` | `v4-gap-priority-v1` | 记录缺口分类、影响、排序、补抓任务、尝试次数和处置 |
| `v4/template-signals.json` | `v4-template-signals-v1` | 记录标题、首屏、结构、数字/形容词和结尾重复提醒 |
| `v4/effect-feedback.json` | `v4-effect-feedback-v1` | 记录真实发布指标、分组中位数和爆款经验生命周期 |
| `v4/recovery-actions.json` | `v4-recovery-actions-v1` | 记录失效、退回、重新核验、人工升级和换题建议 |
| `v4/v4-verification.json` | `v4-verification-v1` | 汇总各模块 PASS/BLOCKED、缺口和重试要求 |

字段必须带 `schema_version`、`run_id`、生成时间和输入哈希。当前批次没有真实发布数据时，效果产物只能是 `candidate`/`adopted` 或 `measured`，不得伪造 `validated`。

## 组件设计

### 1. 组合调度

新增 `article_group/v4/portfolio.py`，只接受文章组已经批准或待预检的候选，不负责发现和抓取。

接口：

```python
build_daily_portfolio(
    candidates: Sequence[Mapping[str, Any]],
    history: Sequence[Mapping[str, Any]],
    *,
    profile: str = "two_article_daily",
    run_id: str,
    planned_at: str,
) -> dict[str, Any]

validate_portfolio(plan: Mapping[str, Any]) -> list[str]
```

`two_article_daily` 必须满足：两篇的 `content_map` 不同；至少一篇是流量/当日入口型，至少一篇是深度或常青/重读型；`event_cluster_id` 不重复；同一作品、人物或事件不能重复占槽；每篇记录 `selection_reason`、`reader_gap`、`content_value_score` 和 `evidence_readiness`。没有合法组合时输出 `needs_controller` 和缺口，不用弱候选凑数。

组合校验是硬门禁；排序分只用于候选优先级，不可覆盖去重和材料约束。

### 2. 统一证据图

新增 `article_group/v4/evidence_graph.py`。节点类型固定为：

```text
topic, claim, source, material, title, opening, paragraph, review
```

每个节点包含 `node_id`、`node_type`、`status`、`artifact_path`、`artifact_sha256`、`source_role`（如适用）和 `claim_type`（如适用）。边包含 `edge_type`、`from`、`to`、`locator` 和 `created_at`。

允许的核心边为：

```text
topic -supports-> claim
claim -supported_by-> source
source -captured_as-> material
claim -materialized_as-> title|opening|paragraph
title|opening|paragraph -reviewed_by-> review
```

接口：

```python
build_evidence_graph(run_root: Path, batch: Mapping[str, Any]) -> dict[str, Any]
validate_evidence_graph(graph: Mapping[str, Any], run_root: Path) -> list[str]
trace_impact(graph: Mapping[str, Any], node_id: str) -> list[str]
invalidate_source(graph: Mapping[str, Any], source_id: str, reason: str) -> dict[str, Any]
```

图必须 fail-closed：缺路径、哈希不一致、未知节点、非法边或孤立的标题/首屏/事实节点均不能通过。`trace_impact` 返回受影响节点的稳定顺序列表，供回滚动作使用。

### 3. 缺口优先调度

新增 `article_group/v4/gap_priority.py`。缺口类型固定为：

```text
title_core_fact, opening_support, key_fact_cross_check,
audience_sample, industry_relevance, source_failure,
dynamic_fact_revalidation, dedupe_context
```

每个缺口记录 `blocking`、`impact`、`risk`、`confidence`、`effort`、`affected_nodes`、`retryable` 和 `attempts`。排序采用可解释的字典序：

```text
blocking desc → impact desc → risk desc → confidence desc
→ effort asc → created_at asc → gap_id asc
```

接口：

```python
derive_gap_tasks(graph: Mapping[str, Any], audits: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]
rank_gap_tasks(gaps: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]
record_gap_attempt(gap: Mapping[str, Any], *, outcome: str, evidence_ref: str | None) -> dict[str, Any]
```

每次材料包更新后重新排序。两次连续失败不再无止境重试，生成 `switch_topic_recommended`，但不自动换题；文章组决定 `returned`、缩小题目或换题。

### 4. 反模板检测

新增 `article_group/v4/template_guard.py`。它比较当前候选与最近历史候选，不对单个词语作否决。

检测面包括：

- 标题句式骨架和疑问词重复；
- 开头是否连续使用同一“事实+悬念”模板；
- H2/段落推进结构是否重复；
- 数字和形容词组合是否异常重复；
- 结尾是否连续使用机械互动问句。

输出 `info`、`warning` 或 `manual_review`，不输出自动拒稿。默认窗口为最近 5 个候选，阈值写入配置并在报告中回显。

### 5. 效果回填与爆款库升级

新增 `article_group/v4/effect_feedback.py`。输入必须是人工或平台导出的真实数据，不直接请求平台。

每条指标事件包含：`article_id`、`published_at`、`platform`、`impressions`、`reads`、`ctr`、`completion_rate`、`read_time_seconds`、`likes`、`comments`、`favorites`、`shares`、`revenue`、`rpm`，缺失平台不提供的指标必须标记为 `unavailable`，不能填 0 冒充。

经验生命周期：

```text
candidate → adopted → measured → validated → reusable_pattern
```

- `candidate`：仅候选角度或结构观察；
- `adopted`：被文章组实际采用；
- `measured`：至少有一条合格发布指标快照；
- `validated`：达到默认验证政策：至少 3 篇已发布样本、至少 2 个不同发布日期、核心可用指标完整，并由控制器确认相对同平台基线的中位数表现；
- `reusable_pattern`：`validated` 后由控制器明确批准进入复用库。

分组比较使用中位数，分组键为 `topic_family`、`title_angle`、`structure_signature` 和 `platform`。小样本只显示观察，不升级为规则。

### 6. 回滚与人工升级

新增 `article_group/v4/recovery.py`。

输入事件与动作关系：

| 事件 | 自动动作 | 需要人工判断 |
|---|---|---|
| 来源失效 | 沿证据图标记 material/claim/title/opening/paragraph/review 为 stale | 是否补抓或缩小题目 |
| 标题变更 | 要求重查标题承诺和首屏兑现位置 | 是否接受新标题 |
| 事实变更 | 要求更新 claim/source/material 绑定及受影响段落 | 是否回退写作阶段 |
| 题目重复 | 退回组合预检 | 是否换角度或换题 |
| 材料不足 | 阻止 `material_ready → writing` | 补材、缩题或退回 |
| 高风险 | 生成 L2/人工升级任务 | 是否继续生产 |
| 同一缺口连续失败两次 | 生成换题建议 | 文章组决定换题 |

动作只能生成状态建议和证据任务，不能直接授予 `closed`、R8 或发布权限。

## 编排入口

新增 `scripts/article_group_v4.py`，提供离线子命令：

```text
plan       生成并校验组合计划
graph      构建并校验证据图
gaps       生成缺口优先队列
templates  生成反模板提醒
effects    校验并汇总效果回填
recover    根据事件生成回滚/升级动作
verify     运行全套 V4 合同并输出 v4-verification.json
```

入口只读已有候选、任务卡、材料包、事实卡、出处账、草稿和人工回填；不抓取、不写 Vault、不发消息、不发布。每个子命令必须要求显式 `--run-dir` 和显式输出路径，拒绝覆盖已有不同版本产物。

## 测试与验收

- 每个 V4 模块先写失败测试，再实现最小行为；测试使用脱敏 fixture，不访问网络。
- 覆盖组合约束、证据图追踪/失效、缺口排序/两次失败、反模板 warning、效果生命周期/中位数、恢复动作和 CLI 输出。
- 增加一个 `controlled-002` 形态的离线 E2E fixture：两篇已通过独立复评的 Markdown 可生成 V4 产物，内容交接仍为 `CONTENT_READY`，发布授权仍为 `not_authorized`。
- 运行原有 V3 及全量测试，任何回归都阻止交付。
- 最终报告分别列出：`PASS`、缺失来源角色、重试要求、人工升级项、内容状态和发布授权。

## 非目标

- 不自动选题替代文章组；
- 不以热榜、社交信号或爆款历史样本直接证明事实；
- 不自动生成或发布 HTML；
- 不自动读取或回填平台后台；
- 不把一次成功升级为复用规律；
- 不修改 Vault canonical rules；
- 不删除或重写 V3 历史运行产物。
