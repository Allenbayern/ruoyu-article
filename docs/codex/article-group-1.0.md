# Article Group 1.0 总控层

Article Group 1.0 是文章组总控层；定向抓取 V5 是其研究子系统。

## 使用

为每个批次建立 `controller-manifest.json`，其中 `articles` 列出唯一 `topic_id`。所有阶段决定追加到 `stage-decisions.jsonl`，不得覆盖历史记录。

```bash
python scripts/article_group_controller.py init --run-dir runs/<run-id> --input manifest.json --output runs/<run-id>/controller-manifest.json
python scripts/article_group_controller.py record --run-dir runs/<run-id> --input decision.json
python scripts/article_group_controller.py verify --run-dir runs/<run-id> --input decision.json --output runs/<run-id>/controller-verification.json
```

`verify` 可附加 `--v4-run-dir <V4输出目录>` 和 `--v5-run-dir <V5输出目录>`，读取现有验证报告，汇总模块状态、缺失来源角色、重试要求、人工升级、内容状态和报告 SHA-256。总控不会重新抓取或生成 V4/V5 产物；缺失、无效或非 PASS 报告使总控返回 BLOCKED/非零退出码。

controller 只做离线契约与记录：它复用 V3 状态检查，并由上层传入 V4/V5 上下文；不联网、不发布、不写 Vault、不自动换题或推进人工决策。`CONTENT_READY`、R8 和发布授权必须分开记录，发布授权固定为 `not_authorized`。

选题从 `candidate` 批准到 `approved` 时必须有 Topic Card；`approved → researching` 继续遵守 V3 的 Topic Card/Crawl Task 契约。题目或版本变化必须新建版本或新 topic_id，并留下决定理由。
