# Task 5 report — V4 anti-template guard

## PASS

- TDD RED：`uv run pytest -q tests/test_v4_template_guard.py`，退出码 2；
  按预期因 `article_group.v4.template_guard` 尚不存在而在收集阶段失败。
- TDD GREEN：同一命令，退出码 0，10 passed。
- Task 5 相关独立回归：
  `uv run pytest -q tests/test_v4_template_guard.py tests/test_v4_contracts.py tests/test_v4_portfolio.py tests/test_v4_recovery.py tests/test_editorial_pipeline_v3.py`，退出码 0，61 passed。
- 导入检查：`PYTHONDONTWRITEBYTECODE=1 uv run python -c 'from article_group.v4.template_guard import analyze_template_signals, validate_template_signals; print("import: PASS")'`，PASS。
- `git diff --check -- article_group/v4/template_guard.py tests/test_v4_template_guard.py`，PASS。

## 验收映射

- 实现了 `analyze_template_signals` 和 `validate_template_signals` 两个接口；只比较历史序列最后 `window` 条，默认窗口为 5。
- 归一化了标点、停用词/疑问词、标题书名号和数字占位符、H2 Markdown/HTML 标签及编号，并抽取首屏事实/悬念、H2/段落推进、数字/形容词组合和机械结尾问句。
- 每类信号都输出 `info` 或 `warning`、`evidence`、`matched_history_ids` 与回显的 `threshold`；重复信号只将总体 `decision` 提升到 `manual_review`，不会自动拒稿。单个共享词不构成否决依据。
- 所有报告使用 Task 1 的闭合 envelope：`schema_version=v4-template-signals-v1`，以及 `run_id`、`generated_at`、`input_hashes`、`payload`；输入哈希为当前候选和历史窗口的 SHA-256。
- 校验器拒绝未知顶层字段、错误 envelope、缺失/非法哈希、无效信号结构、阈值不一致、`auto_reject=true` 和任何非 `not_authorized` 的发布授权值。所有分析报告固定 `auto_reject=false`，只生成审计证据，不授予发布权限。
- 未修改 V3 状态机、schema、Vault、来源采集、网络、凭据或其它任务文件。

## V4 contracts / portfolio / evidence / recovery / V3 回归

按用户要求执行：

```text
uv run pytest -q tests/test_v4_template_guard.py tests/test_v4_contracts.py tests/test_v4_portfolio.py tests/test_v4_evidence_graph.py tests/test_v4_recovery.py tests/test_editorial_pipeline_v3.py
```

结果为 78 passed、7 failed。7 个失败全部位于并发中的 Task 3 `tests/test_v4_evidence_graph.py`，涉及 duplicate article id、graph input hashes、output mapping 参数、draft H1/locator、publication boundary 和 source locator；Task 5 文件不在失败栈或修改范围内，未越界修复。

## 全量 pytest

```text
uv run pytest -q
```

结果为 801 passed、7 failed；仍是上述同一组 Task 3 evidence-graph 失败。Task 5 相关独立回归保持 61 passed。

## Missing source roles

本 Task 是离线、纯函数模板信号分析，不执行 live source 采集；本次运行没有可报告的 live source role。没有把 discovery/social signal 当作事实证明。

## Retry / manual

- 命中重复模板时仅要求 `manual_review`，保留逐类证据、匹配历史 ID 和阈值；不自动拒稿、不换题、不推进 V3 状态。
- 输入结构、身份、时间或哈希异常时 fail-closed，并在 payload `errors` 中保留原因。
- 证据图回归的 7 个失败属于并发 Task 3 的 retry/人工处理项；Task 5 自有测试及相关 V4/V3 回归无 retry 要求。
