# {{RUN_ID}} 运行记录（{{DATE}}）

> 类型：`two_article_daily`（默认两篇 Markdown 成品，交付终点 `CONTENT_READY`，不发布）
> run 根：`runs/{{DATE}}/{{RUN_ID}}`
> 授权边界：`publication_authorization: not_authorized`，全程未发布、未推送、未合并、未写 Vault
> 记录状态：provisional（agent 产出的运行记录，不是 controller 验收）

## 1. 本次任务是什么

按 `Hermes Article Group Workflow` 的日更主流程，从选题发现一路跑到 final review。
一句话说清本 run 做了什么；上游发现层（R0 雷达）只提供发现信号，不充当事实。

## 2. 选题与来源

- 选题表：篇 / 作品 / 文章模式 / content_map / 事件簇 / 核心问题。
- 来源表：source_id / 来源 / 角色 / 用途；全部为本机抓取的公开页面。
- 跨批查重结论（`portfolio_gate --cross-batch N` 的 same_work 黄灯必须在此解释）。

## 3. 两篇成稿

篇 / 标题 / CJK 字数 / SHA-256 表 + 正文文件路径。

## 4. 门禁与证据

门禁表（门禁 | 产物 | 结果）。**任何未跑或不适用的门禁必须显式记录
`not_run` 及原因，不得静默跳过**（产物：`review/gates/compliance-gate.json`
等；task-hierarchy 1.0 契约门禁产物：`task-hierarchy-validation-report.json`）。
社会话题候选的 compliance_gate 是真校验（声明格式见
`templates/five-gates-declaration.md`）；影视日常按 `not_run` 记录。

## 5. 独立 L2 对抗复核

执行者（独立只读子代理）、复核输入、入库命令
（`python -m article_group.codex_review --mode l2 --review-json <review.json>`）、
结论文件路径。

## 6. 收口状态（分栏）

内容栏 / 证据栏 / 治理栏 三栏表 + final review 终局（verdict / content_result /
evidence_result / governance_result / content_blockers）。
`CONTENT_READY` 只表示可交人复制发布，不等于发布授权。

## 7. 本轮顺带修掉的工具缺陷（有测试）

修复内容 + 验证结果（测试文件与通过数）；本轮无修复则写"无"。

## 8. 未验证与遗留

未做事项与遗留观察逐条记录（供 controller 决定是否回填）。
