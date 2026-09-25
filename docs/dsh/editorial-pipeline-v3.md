# 文章组 V3：选题—抓爬—材料状态机

V3 的控制权在文章组。文章组先确认 `topic-card.json`，再创建
`crawl-task.json`；抓爬任务只能围绕已确认的 `topic_id` 和版本补材料，不能
自行换题、写文章或授权发布。

## 状态

```text
idea → precheck → approved → researching → material_ready → writing → review → closed
```

`returned` 是补证、缩小题目、重新预检或关闭任务的回退状态。它不是成功状态，
回交记录必须包含 `return_reasons`。

状态迁移的轻量检查仍由 `validate_transition(from_state, to_state)` 提供。需要把
文件契约一起纳入门禁时，使用：

```python
from article_group.editorial_pipeline_v3 import validate_pipeline_transition

errors = validate_pipeline_transition(
    "approved",
    "researching",
    topic_card=topic_card,
    crawl_task=crawl_task,
)
if errors:
    # 保持在当前状态，按错误码生成补抓或回交动作。
    print(errors)
```

`validate_transition` 传入任意一个 artifact 参数时也会执行对应契约检查；不传
artifact 的两参数调用保留原有的状态词表兼容行为。

## 三类文件契约

JSON Schema 位于：

- `schemas/editorial-pipeline-v3/topic-card-v1.schema.json`
- `schemas/editorial-pipeline-v3/crawl-task-v1.schema.json`
- `schemas/editorial-pipeline-v3/material-pack-v1.schema.json`

对应的 Python 校验入口是：

```python
from article_group.editorial_pipeline_v3 import (
    validate_crawl_task,
    validate_material_pack,
    validate_topic_card,
)

validate_topic_card(topic_card)
validate_crawl_task(crawl_task, topic_card=topic_card)
validate_material_pack(
    material_pack,
    topic_card=topic_card,
    crawl_task=crawl_task,
)
```

校验结果是确定性的错误码列表，空列表表示通过；校验器不会抓取来源、修改
artifact、推进状态或发布文章。

### `topic-card.json`

必须绑定 `schema_version`、`topic_id`、`version`、状态、对象、核心问题、目标
读者、文章类型、去重结果、材料要求和验收要求。进入 `approved` 时还必须有文章
组负责人、决定人、决定时间、截止时间；三项历史去重必须通过或有明确覆盖理由，
并列出正文事实、行业背景、观众反应、复核事实四类材料需求。

### `crawl-task.json`

必须绑定 `topic_id` 和 `topic_version`，并包含四类具体材料要求、来源约束、停止
条件、重试状态和四项交付物。`source_constraints.discovery_is_proof` 与
`raw_html_as_writer_input` 固定为 `false`。只有批准题目才能通过
`approved → researching` 门禁。

### `material-pack.json`

材料包必须有自己的 `version`，并按 `body_facts`、`industry_context`、`audience_reactions`、
`cross_check_facts` 分栏；每条材料都要有来源 URL、证据角色、来源层级、抓取时间、
原文定位、支持内容和不能支持的内容。`claims` 再分为事实、具名/归属观点、观众
反应和推断，避免把推断写成事实。

当 run 声明 `article-first-v1` 契约时，每条材料还要声明
`source_capability`，每条 claim 要声明 `claim_level` 并绑定材料；能力按
`event_exists < character_setup < scene_action < dialogue < audience_reaction < mechanism < outcome`
排序，超过来源上限的 claim 返回 `claim_level_exceeds_source_capability`。验收结果另分
`material_ready_for_draft` 与 `editorial_value_ready`，两项均通过才允许写作。

进入 `material_ready` 至少要满足：

- 保持原核心问题；
- 有两类不同的具体支撑，且有材料支持开头；
- 关键事实可追溯，行业背景与题目直接相关；
- 观众反应有样本范围且禁止无边界概括；
- 重复筛选、失败来源和缺口可见；
- source audit 与 retry state 的版本一致，并且没有未完成的关键重试；
- `blocking_gaps` 为空；一般缺口仍要在 `gaps` 和交接清单中可见；
- 发现信号不能充当事实证明。

不满足时保持 `researching` 或转 `returned`，不得进入写作。

## 文章组调用边界

本模块是离线、只读式的契约校验层。它不会根据热榜生成选题，不会把抓爬发现
自动升级为题目，不会吸收文章进爆款库，也不会生成文章或标题。实际抓爬、爆款
吸收、写作和标题流程必须由文章组在通过相应状态门禁后显式调用。
