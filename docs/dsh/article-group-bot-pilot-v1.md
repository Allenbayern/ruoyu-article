# Article Group Bot Pilot v1

状态：`provisional`。这是已批准的第一版试点实施协议，不是 Vault canonical 规则。

## 目标与边界

- 第一个真实案例是**一篇若雨随影影视长文的完整闭环**；连续完成三个案例后才评估扩展到 `two_article_daily`。
- 执行方式是手动触发的阶段流水线。当前不启用 cron、定时发现、自动选题或自动发布。
- 用户在选题/切口和最终可交付稿处保留人工批准权。
- `run_completed` 与 `artifact_ready` 分栏；`CONTENT_READY` 仍不等于发布授权。
- 项目现有确定性门禁和 L2 复核仍是内容质量权威，本协议不复制或替代它们。

## 角色与边界

| 角色 | 负责 | 不负责 |
|---|---|---|
| Controller | 状态、交接件、推进、停稿、回退、交付记录 | 替用户批准选题或发布 |
| Scout | 热点/作品/事件发现、候选池、证据准备度粗核 | 立项、起草、把热度当事实 |
| Evidence Researcher | 权威来源、事实包、来源映射、待核清单 | 代替人工选题、补造事实 |
| Editorial Planner | 标题、切口、结构、任务卡，标题 `<=30` 字 | 扩大事实边界、绕过待核项 |
| Writer | 依据批准事实包和任务卡起草、定向修订 | 自行补写未核事实、无理由整篇重写 |
| Quality / L2 Reviewer | 确定性门禁、独立只读 L2、finding | 直接改稿、授予发布权 |

角色先作为任务提示和交接契约存在，不依赖不存在的 `~/.agent-presets` 目录；Task Board 卡片未 pin 未确认的 preset。只有在实际 registry 确认可用时才为后续角色绑定 preset。

## 阶段流水线

```text
discovery
  -> topic_gate [human approved]
  -> evidence
  -> planning
  -> draft [pure text, no image dependency]
  -> quality_review [deterministic gates + independent L2 approve]
  -> final_gate [human approved text, optional user-image ingestion as final step]
  -> delivery [content_ready, publication_authorization=not_authorized]
```

`topic_gate` 和 `final_gate` 是人工门。前一阶段失败后，下游只能显式 `not_run`，不能继续写成品或伪造 `PASS`。

### 文章与视觉配图解耦规范（文字先定，最后配图 · 2026-10-13 确立）

- **起草与门禁期纯文本自闭环**：`draft` 与 `quality_review` 阶段专心打磨叙事逻辑、四阶事实、母本呼吸律动与严格断言覆盖，严禁前置依赖图片，严禁伪造任何悬空本地死图；
- **配图是确定好文章后的最后一步收口动作**：只有在文章内容完全确定（到达 `final_gate`）后，才由用户根据定稿内容提供需要的配图；
- **安全加工与微信刷新**：通过 `article_pilot_image` 执行图片安全规格解析与落盘入库，并插入至对应章节；随后刷新 `moyu_green_renderer` 渲染微信图文卡片，绑定最新哈希后完成 `delivery` 与 `seal` 封存。

## 会话纪律与 token 记账（2026-10-13 确立，硬规则）

背景：2026-10-13 复盘发现，case-001…006 全部在**同一个控制会话**里顺序跑完（537 次调用、156.10M raw tokens、缓存重读占 95.6%），把"每篇成本"抬到 26M/例；而独立 L2 复核子会话只占约 8%。同期旧流程单次正常跑的中位是 12.75M（区间 7–24M）。结论：**贵在会话长度，不在角色拆分。**

### 规则

1. **一篇一会话**：每篇长文（每个 case）必须在**独立的 controller 会话**里跑完。禁止在同一会话里连跑多篇；需要批量时，逐篇新建会话。
2. **控制会话只编排**：controller 会话负责阶段推进、交接件、门禁调用与报告，**不得承担正文创作**；正文由 writer 在独立会话产出，避免正文在长会话里被反复重读。
3. **L2 独立会话**：`quality_l2_reviewer` 一律新会话、只读、只给必要文件（draft + evidence-pack + 被复核的交接件）。实测该角色是最省环节（多数 0.1–1.5M/次），必须保持。
4. **设计与 debug 分离**：方案设计、插件安装、排障、对照实验一律放在**非生产会话**，不得与生产 run 共用会话。
5. **每 run 记账**：`quality_review` 与 `final_gate` 之间调用 `article_pilot_usage`（或 `uv run python -m article_group.pilot_contract usage --project-root . --run-root <run>`），把 token 归因落盘到 `metrics/token-usage.json`，**新输入 / 缓存重读 / 输出三项分列**，不混算成本。

### 报告口径

- `RUN-RECORD` 的指标区必须包含 `metrics/token-usage.json` 的三个数（fresh_input / cache_read / output）与 `attributed_session_count`；
- 报告必须写明"保守下限"口径：只归因工具参数命中本 run 路径或 case id 的 step，同会话中的无关步骤不计入；
- 与旧流程对照时，用"每篇 raw tokens"对比，不用"会话总量"对比。

## JSON 交接契约

每个 run 位于 `runs/<YYYY-MM-DD>/dsh-pilot-<case-id>/`，机器权威交接件位于 `handoffs/<stage>.json`，人工摘要位于 `RUN-RECORD.md`。交接件至少保存：

- `contract_version`、`run_id`、`stage`、`revision`、`status`、`owner`
- `input_refs`、`output_refs`、`artifact_refs`
- `blocking_issues`、`next_action`、`not_run_reason`
- `artifact_status`、`publication_authorization`、更新时间
- 质量阶段的 `deterministic_gates`、`l2_decision`、复核产物引用

所有证据写入走 `article_group.evidence_write`，所以会有 before-image、`evidence-changelog.jsonl` 和封存保护。

## 失败路由

- 来源、数字、待核项：退回 `evidence_researcher`。
- 选题、标题、结构、任务卡：退回 `editorial_planner`。
- 局部表达：只退回 `writer` 定向修订，最多两轮。
- L2 `blocker` / `major`：禁止交付，回退到真实问题阶段。
- 失败阶段之后统一 `not_run`；若需重新处理，增加 handoff `revision`，不覆盖审计痕迹。

## 三案例上线门槛

三个案例全部满足以下条件后，才允许另行批准并启用定时发现：

1. 每例有完整 `RUN-RECORD`、阶段交接件、门禁记录和可回读哈希。
2. 没有聊天外批准、静默跳过门禁或伪造 `PASS`。
3. 路径、哈希、独立 L2 和 `content-delivery.json` 一致。
4. 没有未经核验的强断言逃过 L2；单例定向返工不超过两轮。
5. 记录人工介入次数、触发到交付耗时、退回阶段、L2 blocker/major 数量和用户最终修改量。
6. 后两例相对第一例的协调与返工成本目标下降约 30%，且事实门禁不下降。

达标前 Task Board 只创建手动根卡，不设置 schedule；达标后启用 schedule 仍需要单独的用户授权。
