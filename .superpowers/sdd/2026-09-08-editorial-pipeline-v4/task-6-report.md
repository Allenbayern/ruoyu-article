# Task 6 report — V4 effect feedback and reusable-pattern lifecycle

## PASS

- TDD RED: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q tests/test_v4_effect_feedback.py` failed during collection with the expected `ModuleNotFoundError` because `article_group.v4.effect_feedback` did not yet exist.
- TDD GREEN: the focused Task 6 suite passed with `18 passed`.
- Task 6 plus Task 1 contracts: `31 passed`.
- New/previous V4 modules plus V3 regression: `109 passed`.
- Import/compile check: `.venv/bin/python -m py_compile article_group/v4/effect_feedback.py` passed.
- Full repository regression: `826 passed`.

## 验收映射

- `validate_metric_event` accepts only caller-supplied manual/platform export records; it requires `article_id`, `published_at`, and `platform`, rejects future or malformed timestamps, rejects negative/non-finite/boolean metrics and rates outside `0..1`, and requires unavailable metrics to be explicit `null` values with an `unavailable` status.
- `aggregate_effects` accepts only the four declared grouping keys (`topic_family`, `title_angle`, `structure_signature`, `platform`), groups deterministically, uses `statistics.median`, and retains sample count, unique article count, distinct publication dates, per-metric available counts, medians, and the supplied baseline reference. Invalid events, groups, or conflicting baselines fail closed without partial summaries.
- `advance_pattern_lifecycle` keeps the explicit `candidate → adopted → measured → validated → reusable_pattern` vocabulary. Validation requires at least three distinct published articles, two distinct publication dates, complete core metrics, a supplied baseline, and controller baseline confirmation. `approve_reuse` is the only decision that promotes a validated pattern to `reusable_pattern`; no metrics or baseline are fabricated.
- Envelope-shaped pattern input returns a closed `v4-effect-feedback-v1` envelope with `run_id`, `generated_at`, deterministic `input_hashes`, payload state, and `publication_authorization=not_authorized`. Plain in-memory pattern calls retain the direct lifecycle result and also carry deterministic identity/hash metadata.
- Malformed mappings, sequences, statuses, controller decisions, and lifecycle inputs fail closed with stable errors; no platform request, source discovery, Vault write, publication, or authorization path was added.

## 缺失 source role

本 Task 是离线效果回填纯函数实现。本次没有 live source role；输入角色仅限人工或平台导出的真实指标事件，discovery/social signal 未被当作事实或效果证明。最终验证未留下并发 evidence-graph 失败。

## Retry / manual 状态

- Retry：没有本 Task 的 live-source retry 要求。少于三篇、少于两个发布日期、核心指标缺失、baseline 缺失/冲突或 malformed event 会保持未验证状态并保留错误，不能用补零或部分样本晋级。
- Manual：controller 必须确认 baseline 才能进入 `validated`；只有明确 `controller_decision=approve_reuse` 才能进入 `reusable_pattern`。这些判断不会自动换题、发布或改变 V3 状态。
- 内容与授权：本 Task 不改变 `CONTENT_READY`；所有效果输出保持 `publication_authorization=not_authorized`。
