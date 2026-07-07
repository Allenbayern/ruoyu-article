# media-intel-aios 文章组分支

这是面向“若雨随影”文章组的影视情报与候选生产分支。当前交付重点不是完整 AIOS 平台，而是两条可本地运行、可审计的文章组链路：

- `article_production_live_run.py`：拉取已登记的影视市场、热度、正文、观众反应和社交讨论信号，生成一篇可检查的 `article.html`，并输出来源审计与质量门禁 JSON。
- `run_daily_pipeline.py --lane article`：运行文章组日度候选池，输出文章候选、总监复评、今日钩子分发和重爬提示。

本分支适合用于 GitHub 上的新分支验收：先确认环境能跑，再看产物是否满足文章组人工复核。

## 当前边界

这不是“自动发布文章”的系统。当前产物用于文章组上游判断和人工复核：

- `article.html` 是生产链路 smoke / 候选稿形态，不等于最终发布稿。
- `canonical_suite_green` 在当前 runner 中固定为 `false`；验证标签只能按 focused/ad-hoc smoke 口径理解。
- 社交讨论信号只用于发现话题、情绪和讨论压力，不能当作事实核验来源。
- 豆瓣短评/讨论属于 `audience_reaction_signal`，会进入完整来源审计；HTML 中的 `social_results` 只收 `social_discussion_signal`。
- 需要登录态或平台风控的 live 来源会安全失败并写入审计，不应被 README 或验收结论包装成稳定直连能力。

## GitHub 更新状态

当前 README 对应 GitHub 分支 `feat/ruoyu-article-group-validation`，PR 为 `#1 feat: add agent-ready platform collection workflow`。

最近一次收口提交为：

```text
44db3be feat: add media intel retry handoff details
```

这次提交边界只包含 `media-intel-aios` 下的文章组日度 lane、测试、README 和最小依赖说明；workspace 中其他未提交/未跟踪文件不属于本轮 GitHub 更新。提交前已用项目 `.venv` 验证：

```bash
./.venv/bin/python -m pytest tests/test_scoring.py -q
```

结果为：

```text
27 passed
```

## 环境准备

需要 Python 3.11。仓库依赖在 `requirements.txt` 中，目前只有运行和测试所需的最小依赖：

```bash
python3.11 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

如果本机没有 `python3.11`，可先用系统里可用的 Python 3.11 解释器创建 `.venv`。不要把私有 Cookie、API key 或本地登录态文件提交到仓库。

## 快速验证

运行文章生产 live smoke：

```bash
./run_article_production_live.sh --output-base /tmp/media-intel-article-live --run-id smoke-readme
```

成功时命令会打印 JSON，关键字段包括：

- `output_dir`：本次产物目录。
- `verification.status`：`PASS` 表示 HTML、来源文件、审计文件和 run summary 通过当前 focused 检查。
- `summary.article_lane`：`self_media_production_candidate` 或 `data_observation`，取决于本轮来源角色覆盖。
- `summary.self_media_ready` / `summary.missing_source_roles`：说明当前来源是否足够支撑自媒体文章候选。

运行文章组日度 lane：

```bash
./run_article_lane_pipeline.sh 2026-07-03
```

这个脚本等价于调用：

```bash
python scripts/run_daily_pipeline.py \
  --lane article \
  --date 2026-07-03 \
  --run-dumou \
  --run-news-fallback \
  --run-guduo \
  --run-vocus \
  --run-xiniu \
  --run-douban \
  --run-hotboard \
  --run-tophub
```

日度 lane 会输出一段 JSON summary，重点看：

- `status` 是否为 `OK`。
- `article_count` 是否大于 0。
- `needs_retry`、`retry_targets`、`retry_reason` 是否提示需要重爬。
- `retry_request.next_actions` 是否给出平台、检索词、补抓取动作和复跑验收方式。
- `source_decisions` 中各来源是 live、sample、skipped 还是 error。

当 `status=OK` 且 `needs_retry=true` 时，优先按内容证据不足处理，不按程序错误处理。此时应查看 `retry_request.next_actions` 或 `latest-feedback.md` 的 `## 重爬处置`，按平台补二跳正文、评论区观点、长文背景或真实用户讨论证据；两者来自同一组重爬动作，前者是 JSON 结构化交接，后者是人工复核视图。补完后复跑 article lane，再检查 `article-approved-latest.md`、`today-hook-dispatch.md` 和 `retry_request.retry_required` 是否改善。

## 主要产物

`article_production_live_run.py` 的默认产物目录由 `--output-base` 和 `--run-id` 组成。每次运行至少关注：

- `article.html`：生成的文章检查页。
- `sources.json`：文章使用的来源摘要、source bucket、source skeleton。
- `fetch_audit.json`：完整抓取审计、来源状态、失败原因和使用边界。
- `source_registry.json`：当前来源注册表。
- `source_health.json`：来源健康计数。
- `source_health_report.md`：来源健康 Markdown 报告。
- `run_summary.json`：本轮运行摘要、质量门禁、来源角色覆盖。
- `verification.json`：focused 输出检查结果。

`run_daily_pipeline.py --lane article` 默认会写入 `handover-hotspot/01-DAILY-RUNS/<date>/media-intel-aios`；传入 `--output-root` 可改到临时目录。主要产物包括：

- `article-approved-latest.md`：文章组候选清单。
- `director-review.md`：总监复评视图。
- `latest-feedback.md`：来源接入、候选层、重爬提示和 `## 重爬处置`。
- `today-hook-dispatch.md` / `today-hook-dispatch.jsonl`：今日钩子分发。
- `reference-candidate-export.jsonl`：候选导出。

在 `--lane article` 模式下，不应生成 `video-approved-latest.md` 作为文章组交付。

## 手动检查脚本

如果只想一次性跑文章组分支验收，可使用：

```bash
./.venv/bin/python scripts/media_intel_article_manual_check.py
```

该脚本会：

1. 在 `~/.hermes/artifacts/media-intel/article-manual/<run-id>/` 下创建本次检查目录。
2. 运行 `article_production_live_run.py` 并检查 `verification.status`。
3. 运行 `run_daily_pipeline.py --lane article` 并检查 `article_count`。
4. 打印 `ARTICLE_HTML` 和最终 JSON summary。

可用环境变量覆盖默认路径：

- `MEDIA_INTEL_ROOT`：仓库根目录。
- `MEDIA_INTEL_PYTHON`：Python 解释器，默认 `.venv/bin/python`。
- `MEDIA_INTEL_ARTIFACT_ROOT`：手动检查产物根目录。
- `MEDIA_INTEL_CRON_OUTPUT_DIR`：只用于 summary 记录，不代表本脚本会写 cron 输出。

## 测试

本分支最小测试命令：

```bash
./.venv/bin/python -m pytest tests/test_article_production_live_run_smoke.py tests/test_scoring.py
```

这组测试覆盖：

- live runner 的 HTML、JSON、审计和质量门禁结构。
- 自媒体候选需要至少两个叙事来源角色的门禁。
- 只有市场/热度信号时降级为 `data_observation`，不冒充最终文章质量验收。
- article lane 不重新打开非请求来源，不向视频组产物泄露。
- article lane 新增显式来源只导出文章组候选。

## 推荐验收顺序

1. 创建 `.venv` 并安装依赖。
2. 运行 pytest 最小测试。
3. 运行 `./run_article_production_live.sh --output-base /tmp/media-intel-article-live --run-id smoke-readme`。
4. 打开输出目录中的 `article.html`，同时检查 `verification.json` 和 `run_summary.json`。
5. 用临时目录运行 article lane，避免污染正式 handover：

```bash
./.venv/bin/python scripts/run_daily_pipeline.py \
  --lane article \
  --date 2026-07-03 \
  --output-root /tmp/media-intel-article-lane \
  --run-dumou \
  --run-guduo \
  --run-vocus \
  --run-douban \
  --run-hotboard \
  --run-tophub \
  --guduo-date 2026-06-09 \
  --guduo-offline-dir samples/guduo \
  --vocus-sample-json article-vault/samples/vocus/vocus_article_sample_01.json \
  --douban-sample-html article-vault/samples/douban/douban_review_sample_01.html \
  --hotboard-sample-json hotboard/samples/hotlist_web_sample_01.json
```

## 目录速查

- `scripts/article_production_live_run.py`：文章生产 live smoke 主入口。
- `scripts/run_daily_pipeline.py`：日度总编排，文章组使用 `--lane article`。
- `scripts/media_intel_article_manual_check.py`：文章组人工检查封装脚本。
- `run_article_production_live.sh`：固定使用项目 `.venv` 的 live runner shell 入口。
- `run_article_lane_pipeline.sh`：文章组 lane shell 入口。
- `tests/test_article_production_live_run_smoke.py`：live runner focused smoke 测试。
- `tests/test_scoring.py`：文章组 lane、评分、路由和隔离测试。
- `article-vault/`：文章组样本和 Article Vault 相关资产。
- `samples/`、`hotboard/samples/`：本地样本输入。

## 提交前检查

提交到 GitHub 前至少确认：

```bash
git status --short
./.venv/bin/python -m pytest tests/test_article_production_live_run_smoke.py tests/test_scoring.py
```

如果运行过 live 或 lane 命令，只提交源码、脚本、测试和 README；不要提交 `/tmp` 产物、`handover-hotspot` 运行产物、私有配置或登录态文件。
