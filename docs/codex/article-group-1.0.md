# Article Group 1.0 总控层

Article Group 1.0 按三层运行：Article Group 管理批次，Article Task 管理单篇文章，Crawl Task 管理该篇文章的研究。定向抓取 V3/V4/V5 只属于 Crawl Task。

`article_group.article_task_v1` 提供三层状态与契约校验：`validate_group_manifest`、`validate_article_task`、`validate_crawl_task`、`validate_task_binding` 和 `validate_completion`。它不改变现有抓取状态机。

## 使用

为每个批次建立 `controller-manifest.json`，其中 `articles` 列出唯一 `topic_id`。所有阶段决定追加到 `stage-decisions.jsonl`，不得覆盖历史记录。

```bash
python scripts/article_group_controller.py init --run-dir runs/<run-id> --input manifest.json --output runs/<run-id>/controller-manifest.json
python scripts/article_group_controller.py record --run-dir runs/<run-id> --input decision.json
python scripts/article_group_controller.py verify --run-dir runs/<run-id> --input decision.json --output runs/<run-id>/controller-verification.json
```

`verify` 可附加 `--v4-run-dir <V4输出目录>` 和 `--v5-run-dir <V5输出目录>`，读取现有验证报告，汇总模块状态、缺失来源角色、重试要求、人工升级、内容状态和报告 SHA-256。总控不会重新抓取或生成 V4/V5 产物；缺失、无效或非 PASS 报告使总控返回 BLOCKED/非零退出码。

controller 只做离线契约与记录：它复用 V3 状态检查，并由上层传入 V4/V5 上下文；不联网、不发布、不写 Vault、不自动换题或推进人工决策。`CONTENT_READY`、R8 和发布授权必须分开记录，发布授权固定为 `not_authorized`。

## Article-first 正文与标题顺序

新文章使用以下单篇状态链：

```text
brief_locked
→ drafting_content
→ content_review
→ content_passed
→ title_packaging
→ title_review
→ final_review
→ delivered
```

写作契约只生成三份独立产物：

- `body_draft.md`：只有正文和必要的 H2，不含 H1，也不含标题候选。
- `title_pack.json`：正文通过后创建；只读已确认材料和正文 locator。
- `title-pack-review.json`：标题复核记录；绑定标题包路径和哈希，不能用标题包装结果
  冒充标题复核通过。
- `delivery.md`：标题包选定并复核后，把正式标题与正文组合成最终交付稿。

正文通过条件同时满足：至少三条有正文/来源定位的硬信息；硬信息来自至少两种类型
且不是同一事实改写；每个主要段落新增事实、场面、机制或判断；删除标题后仍能识别
对象、问题、解释和判断。`reader_question` 属于文章问题，`reader_takeaway` 只在成稿
复核后填写。

标题阶段只有三种结果：

| 结果 | 处理 |
|---|---|
| `selected` | 进入标题复核；只能绑定现有正文与来源证据 |
| `return_article` | 回到 `content_review`/`content_revision`，不在标题阶段补写正文 |
| `return_material` | 回到材料验收/`material_return`，不以标题刺激度掩盖缺口 |

`title_promise` 仅供历史产物只读兼容；`title_skeleton` 仅是发现信号，不能进入 brief、
材料验收或写作输入；`title_core_fact` 只在标题包装/标题复核阶段阻断。正文变化会使
标题包的正文哈希失效。`CONTENT_READY` 只能在标题选定、标题复核记录、最终复核和交付稿
哈希均通过后产生，且永远不代表发布授权。

选题从 `candidate` 批准到 `approved` 时必须有 Topic Card；`approved → researching` 继续遵守 V3 的 Topic Card/Crawl Task 契约。题目或版本变化必须新建版本或新 topic_id，并留下决定理由。

## 材料验收与编辑判断

抓爬任务的 `material_ready` 只证明页面被保存下来。Article Task 进入 `material_accepted` 前，必须另写 `article-material-acceptance-v1` 记录，分清：

- 已经拿到的具体事实；
- 这些事实能支撑的分析；
- 仍缺的场面、对话或作品材料；
- 因此无法回答的核心问题。

页面标题、简介、日期和上传者文案属于 `page_metadata`，不得标成 `fulltext`。只有节目标题的材料包，不能支撑嘉宾行为或观众心理分析；材料不够就退回指定缺口或换角度，不能把写长的责任交给主笔。

接受材料后只确认正文可写的事实、场面和解释；标题方向要等正文通过后再进入
`title_pack.json`，最多三条，每条绑定正文与来源定位。只换近义词不算新方向。

四阶段复核记录的 `PASS` 只证明记录结构完整。成稿是否值得进入 `final_review`，要另写 `article-editorial-judgment-v1`：机器检查、模型编辑复核、真人确认分栏；结构通过和编辑判断通过分开；编辑意见必须引用当前稿件段落。字数够但只是同一材料换词复述，可以退回研究。`review_mode=human` 或 `completed_by=editorial-protocol-record` 都不能代替真人确认。

独立复核按单篇记录任务标识、当前稿件哈希、尝试次数、超时原因和下一步。超时保持 `UNVERIFIED`，不能当作通过，也不用重跑整批；可对当前单篇缩小复核包后有限重试。是否需要 L2，必须写下具体风险依据。

跨批去重要区分「已加载但没有历史」和「没有加载历史」。后者，包括只写了空数组的历史文件，不能宣称去重通过。
