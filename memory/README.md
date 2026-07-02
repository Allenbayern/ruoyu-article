# memory｜历史运行记忆归档

这个目录保留早期 OpenClaw / 若雨随影协作中的运行记忆、梦境/会话片段和阶段性记录。

## 当前定位

- `memory/` 是历史资料库，不是当前生产入口，也不是文章组生产入口。
- 它不代表当前任务状态，也不代表当前 agent 必须继续执行的 todo。
- 新 agent 下载仓库后，不应从这里启动选题、抓取、成稿或发布流程。
- 当前文章组主入口在：

```text
projects/ruoyu-article-group/
```

## 与当前任务要求的关系

当前任务要求是 agent-ready：最小配置、可离线 dry-run、可生成入口文件、可验证四层状态、可把 approved 题目桥接到 Markdown + HTML 成稿。

因此，`memory/` 里的旧会话、旧任务、旧路径和旧自动化设想只作为历史背景；不能绕过当前项目 README、配置样例、验证脚本和 approved 白名单。

## 可以使用

- 回看历史决策、偏好、旧流程背景。
- 查找早期案例、上下文和经验沉淀。
- 人工判断某条旧规则是否仍有参考价值。
- 将仍然有效的规则手工迁移到 `projects/ruoyu-article-group/` 的 README、模板、验证清单或脚本测试里。

## 不要使用

- 不要把这里的片段当作当前最新任务状态。
- 不要把这里的记录自动同步到新 handover。
- 不要让 agent 依据这里的旧 todo 自动继续执行。
- 不要把私人会话、临时记录、内网线索、本机路径、账号线索复制进 README、配置样例、PR 正文或公开产物。
- 不要在这里写入 cookie、token、账号密码、手机号、私人邮箱或本机绝对路径。

## 当前正确入口

如果目标是让 agent 抓取平台信号并生成文章组入口，请使用：

```bash
python3 projects/ruoyu-article-group/scripts/collect_platform_signals.py \
  --config projects/ruoyu-article-group/config/platform-sources.local.json \
  --date YYYY-MM-DD

python3 projects/ruoyu-article-group/scripts/validate_article_pipeline.py --date YYYY-MM-DD
```

如需把历史规则纳入当前流程，先迁移到当前项目文档或测试，再按 `validate_article_pipeline.py` 验证；不要让历史记忆直接成为当前流程的一部分。
