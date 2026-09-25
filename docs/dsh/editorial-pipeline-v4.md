# 文章组 V4 离线运行手册

V4 是文章组已经决定选题后的证据与候选生产层。它读取一个明确的 `run-dir`，不发现新题、不自行换题、不联网、不写 Vault、不生成 HTML，也不发布。文章组仍是选题、缩题、退回、换题和最终交付治理的控制方。

## 一次完整运行

运行根至少应提供当前批次的 `batch.json`、`run-manifest.json`、候选池、文章组事实卡、出处账、Markdown 草稿、材料包、复评记录，以及需要时的来源审计、重试状态和指标回填。推荐把所有 V4 输出写到当前运行的独立目录：

```bash
.venv/bin/python scripts/article_group_v4.py verify \
  --run-dir tests/fixtures/v4/controlled-002 \
  --output-dir runs/2026-09-09/v4/controlled-002
```

`verify` 会写入并读回七个 JSON：

| 文件 | 作用 |
|---|---|
| `portfolio-plan.json` | 两篇组合、候选资格、去重约束和选择理由 |
| `evidence-graph.json` | topic—claim—source—material—opening/paragraph—content review 追溯图；选定标题包后才增加 title/title-review 分支 |
| `gap-priority.json` | 按缺口影响排序的补证与重试队列 |
| `template-signals.json` | 反模板提醒；只产生提示，不自动拒稿 |
| `effect-feedback.json` | 真实指标回填后的中位数和经验生命周期 |
| `recovery-actions.json` | 来源失效、事实/标题变更、高风险和两次失败的安全动作 |
| `v4-verification.json` | 总体验收、来源角色缺口、重试要求、人工升级和内容状态 |

已有同名文件只有在字节内容完全一致时才会复用；不同内容会拒绝覆盖。每个子命令也可单独运行：

```bash
.venv/bin/python scripts/article_group_v4.py plan      --run-dir <run-dir> --output-dir <output-dir>
.venv/bin/python scripts/article_group_v4.py graph     --run-dir <run-dir> --output-dir <output-dir>
.venv/bin/python scripts/article_group_v4.py gaps      --run-dir <run-dir> --output-dir <output-dir>
.venv/bin/python scripts/article_group_v4.py templates --run-dir <run-dir> --output-dir <output-dir>
.venv/bin/python scripts/article_group_v4.py effects   --run-dir <run-dir> --output-dir <output-dir>
.venv/bin/python scripts/article_group_v4.py recover   --run-dir <run-dir> --output-dir <output-dir>
```

子命令退出码为 0 才表示对应合同通过；即使失败，也会尽量留下可审计的 BLOCKED 产物。

## 如何读验收结果

`v4-verification.json` 的 `payload` 中，以下字段必须分开处理：

- `decision=PASS`：本地确定性合同通过，不代表事实已经被平台或真人批准。
- `missing_source_roles`：缺失的来源角色，例如官方物料、行业背景、观众反应；这是材料缺口，不得静默当作已补齐。
- `retry_requirements`：可重试来源及下一步，不与合同 PASS 混为一谈。
- `manual_escalations`：需要文章组/控制器判断的项，包括高风险、组合资格、换题建议和反模板人工复核。
- `content_status=CONTENT_READY`：标题包已选定、标题复核和最终复核完成，当前 `delivery.md` 可交给真人处理；不等于 `R8`、控制器验收或已发布。
- `publication_authorization=not_authorized`：V4 永远不生成发布授权。

发现榜、热榜和社交讨论可以保留为 `discovery_signal`/`social_signal` 来源节点，但不能生成 `claim --supported_by--> source` 的事实证明边。正文阶段图只要求
`claim → opening`、`claim → paragraph`、`paragraph → content_review`；标题阶段才可选地
增加 `claim → title`、`title → title_review`。没有 `title_pack.json` 不能因为缺 title 节点
生成 `title_core_fact` 缺口；`opening_support` 仍是正文阶段阻断项。来源失效时，恢复动作
沿证据图把受影响节点标为 `stale`；文章组决定补抓、缩小题目、退回或换题。连续两次失败
只生成 `switch_topic_recommended`，不会自动换题。

文章先写成 `body_draft.md`，正文阶段不要求 H1；正式标题只在 `title_packaging` 通过后
生成 `title_pack.json`，标题复核再生成绑定标题包哈希的 `title-pack-review.json`，最后与正文
组合为 `delivery.md`。正文改动会使标题包正文哈希失效，必须重新过内容复核；标题包改动会
使标题复核和交付稿哈希失效。

## V3 接口边界

```python
from article_group.editorial_pipeline_v3 import validate_v4_transition_context

errors = validate_v4_transition_context(
    "material_ready", "writing",
    portfolio_plan=portfolio_plan,
    evidence_graph=evidence_graph,
    gap_report=gap_report,
    recovery_actions=recovery_actions,
)
```

它只在 V3 状态流转外增加 V4 上下文门禁：没有合法组合不能开始研究，有阻塞缺口或 stale 证据不能开始写作。V3 原有状态和严格的文章组复评/控制器门禁仍须由原接口执行；V4 适配器不新增状态，也不替代 `review → closed` 的既有审核。
