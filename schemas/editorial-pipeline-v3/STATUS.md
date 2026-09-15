# schemas/editorial-pipeline-v3 — 现行 schema 族（日更接入）

状态（2026-09-15 裁定）：**当前接入层**。日更生成器与门禁跑在这一族上。

- 本目录三个 schema（`topic-card-v1` / `crawl-task-v1` / `material-pack-v1`）
  描述 editorial pipeline v3 的产物形状，供 `article_group/editorial_pipeline_v3.py`
  校验。
- 注意：`crawl-task-v1.schema.json` 是 **v3 族的 crawl-task 形状**；它不同于
  `article_group/article_task_v1.py` 所校验的 1.0 parent/child 契约
  `crawl-task-parent-v1`（task-hierarchy 门禁用后者）。两者并存是有意的：
  v3 schema 族描述 pipeline 旁路产物，1.0 契约描述 task-hierarchy 绑定。
- 其他层：`v2_contract/` 已冻结；`article_group/v4`、`article_group/v5`
  为旁路工具层，非日更门禁。
