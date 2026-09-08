# Task 4：V4 缺口优先调度与恢复动作

## PASS

- TDD RED：`.venv/bin/pytest -q tests/test_v4_gap_priority.py tests/test_v4_recovery.py`，退出码 1；两个新模块缺失导致预期的导入失败。
- TDD GREEN：同一命令，退出码 0，9 passed。
- Task 1/Task 3/V3 回归：`.venv/bin/pytest -q tests/test_v4_gap_priority.py tests/test_v4_recovery.py tests/test_v4_contracts.py tests/test_v4_evidence_graph.py tests/test_editorial_pipeline_v3.py`，退出码 0，53 passed。
- 字节码检查：`.venv/bin/python -m py_compile article_group/v4/gap_priority.py article_group/v4/recovery.py`，退出码 0。
- 全量回归：`.venv/bin/pytest`，退出码 0，790 passed。

## 验收映射

- `gap_priority.py` 使用 `GAP_TYPES`，从闭合 evidence-graph envelope 和审计记录映射八类缺口；保留 `affected_nodes`、`failed_source_ids`、`retryable`、`attempts`，按 blocking/impact/risk/confidence/effort/created_at/gap_id 精确排序。
- `record_gap_attempt` 保留尝试证据；第二次连续失败只输出 `switch_topic_recommended`，不改变题目。
- `recovery.py` 使用 `v4-recovery-actions-v1` 闭合 envelope；覆盖来源失效、标题/事实变更、重复题目、材料不足、高风险和两次失败建议。来源失效通过 `trace_impact` 生成 stale 节点更新。
- 每个动作均包含约定字段且 `publication_authorization=not_authorized`；校验器拒绝 `closed`、`R8`、发布或授权状态。
- 输入 envelope、图、审计、事件和动作结构异常时 fail-closed；输出按稳定键排序并保留 evidence refs。

## 缺失 source role

本 Task 是离线缺口/恢复纯函数实现，不执行来源采集；无本次运行的 live source role 可报告，未把 discovery/social signal 当作事实证明。

## Retry / manual 状态

- 可重试缺口保留 `retryable` 与 `attempts`；连续失败两次后仅建议换题，仍由文章组决定。
- `high_risk` 生成 `manual_l2_review`、owner=`controller` 的人工升级动作。
- 历史 `runs/2026-09-07/controlled-002/batch.json` 未显式提供 `topic_card_path`，按 Task 3 fix3 约定应 fail-closed；这是输入缺口/重试要求。使用显式 `topic_card_path` 的只读烟测通过。未修改历史 run，也未恢复约定路径回退。
- 未生成内容状态晋级；恢复动作不授予 `closed`、R8 或发布授权。
