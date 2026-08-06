# 若雨随影影视日报（Ruoyu Film Daily）

若雨随影影视自媒体文章组的受控生产工作流：离线门禁、来源捕获、发现雷达、对抗性审查交付批次。所有校验器均为确定性且 fail-closed（失败即关闭）；本仓库任何代码都不会对外发布、合并、部署或发送消息。

## 当前状态

- 受控批次已完成至 **controlled-014**：在对抗性审查 Gate（Sol 独立审查 → 限定范围修复 → 复审 → 控制器验收）下产出三篇可发布级成稿。交付物为带来源封条（provenance seal）的冻结单文件 HTML；**不对外发布**。
- 305 个离线测试全部通过（校验器、CLI、来源捕获、发现雷达、合规门禁）。
- 未实现也未授权：cron、来源注册表、发布器集成、图片管线、发布路径。

## 目录结构

| 路径 | 用途 |
|---|---|
| `article_group/workflow.py` | 受控运行状态机与批次校验（R0–R8、交付授权） |
| `article_group/prewrite.py` | 写前门禁：候选池、槽位、新鲜度窗口、编辑选择 |
| `article_group/compliance_gate.py` | 社会话题合规门禁：三态判定（PASS/CONDITIONAL/FAIL），五道门 + 分级规则 |
| `article_group/compliance_cli.py` | 手动 CLI：五道门合规声明检查（`--pool`/`--candidate`，`--json`） |
| `article_group/sync_compliance.py` | 将候选 JSON 的五道门声明同步为 Markdown 清单 |
| `article_group/toutiao_capture.py` | 头条公开文章快照，用于证据（无 cookie/JS/反爬绕过） |
| `article_group/toutiao_cli.py` | 头条捕获的 CLI 入口 |
| `article_group/yuafeng_hot.py` | 只读玉峰热榜客户端（UC、腾讯新闻、聚合榜） |
| `article_group/discovery_radar.py` | 隔离的 R0 发现雷达产物构建器 |
| `article_group/yuafeng_radar_cli.py` | 构建单个 R0 发现专用雷达 JSON 的 CLI |
| `article_group/delivery.py` | 纯文本交付物派生/校验（Markdown 保持为规范稿） |
| `article_group/git_hygiene.py` | fail-closed 的 git 卫生门禁（自身绝不运行 git） |
| `briefs/` | 各任务契约 brief（写作、修复、Sol 审查/复审） |
| `templates/` | 首次运行 brief、候选卡、证据包、交付清单、五道门 |
| `runs/` | 各运行根：来源、草稿、冻结件、审查包、封条 |

## 验证

```bash
uv run python3 -m pytest -q
```

测试仅使用合成记录。它们验证状态迁移、槽位与角度分离、主张覆盖要求、HTML 扣留、新鲜度窗口、不发布边界与合规面。

## 手动来源捕获（头条）

抓取一条明确的公开文章 URL 到明确的本地运行根。命令成功时只写 `sources/<source-id>.txt` 并打印一条来源清单项；绝不会选择候选、创建文章、推进工作流状态或发布。

```bash
uv run python -m article_group.toutiao_cli \
  --url 'https://www.toutiao.com/article/<article-id>/' \
  --run-root runs/2026-08-01/controlled-001 \
  --source-id TT-<article-id> \
  --independence-group toutiao:<article-id>
```

## 发现雷达（玉峰）

只读热榜发现。所有结果仅用于发现——绝不作为事实主张的证据。

```python
from article_group.yuafeng_hot import fetch_uc_hot, fetch_tencent_news, fetch_aggregate

result = fetch_uc_hot()
result = fetch_tencent_news(page=1, type_="hot")
result = fetch_aggregate("微博热榜")  # 知乎热榜/微博热榜/微信热文榜/澎湃热榜/百度热点/知乎日报/今日头条热榜/梨视频总榜
```

API key 在调用时从 `YUAFENG_API_KEY` 环境变量读取；绝不持久化、记录或出现在异常消息中。

构建本地 R0 雷达产物（仅发现的 JSON，调用方指定路径）：

```bash
uv run python -m article_group.yuafeng_radar_cli \
  --output-path runs/2026-08-05/radar/r0.json \
  --sources '[{"name": "uc"}, {"name": "aggregate", "action": "微博热榜"}]'
```

## 合规面

```bash
# 对候选池或单个候选做声明检查
uv run python -m article_group.compliance_cli --pool runs/<run>/candidates.json

# 将声明同步进 Markdown 清单
uv run python -m article_group.sync_compliance \
  --input path/to/candidates.json --output docs/social-compliance.md
```

退出码 0 表示每条声明通过校验器；不代表每个候选的声明等级都是 PASS。

## 交付纪律

- Markdown 为规范稿；`article-plain.txt` 是面向不解析 Markdown 平台的复制粘贴交付物。
- 可发布级批次冻结单文件 HTML 交付物（内嵌 CSS），并记录绑定冻结件 `sha256:<digest>` 的来源封条；验收前校验绑定。
- 批次验收要求控制器审查新证据；终审由独立方（Sol 路由）在对抗性审查 Gate 下执行，控制器做出每项验收决定。仓库内任何内容都不授权对外发布。

## 边界

绿色本地校验器只确认确定性批次门禁——它不建立事实真值、文章质量、`publish-ready` 或发布授权。事实断言必须能在该运行根的 `citations-ledger.json` 中找到逐字引文。
