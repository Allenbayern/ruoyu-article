# 若雨随影影视日报（Ruoyu Film Daily）

若雨随影影视自媒体文章组的受控生产工作流：离线门禁、来源捕获、发现雷达、对抗性审查交付批次。所有校验器均为确定性且 fail-closed（失败即关闭）；本仓库任何代码都不会对外发布、合并、部署或发送消息。

## 当前状态

- 受控批次已完成至 **controlled-014**：在对抗性审查 Gate（Sol 独立审查 → 限定范围修复 → 复审 → 控制器验收）下产出三篇可发布级成稿。交付物为带来源封条（provenance seal）的冻结单文件 HTML；**不对外发布**。
- 403 个离线测试全部通过（校验器、CLI、来源捕获、发现雷达、合规门禁）。
- 未实现也未授权：cron、来源注册表、发布器集成、图片管线、发布路径。
- 2026-08-11：契约系统落地——`article_group/case_contract.py`（事实/反馈词汇与技法引用校验）、`article_group/bilibili_capture.py`（B站长文公开证据捕获）、`v2_contract/`（任务卡/流转影子校验器，冻结 V2 词表）、`templates/evidence-pack.md` P1 冻结。自宿主糖果梦热榜（tgmeng）作为第二个只读发现雷达接入（影视榜 + AI 聚合糖果指数）。

## 目录结构

| 路径 | 用途 |
|---|---|
| `article_group/workflow.py` | 受控运行状态机与批次校验（R0–R8、交付授权） |
| `article_group/editorial_pipeline_v3.py` | 文章组 V3 选题—抓爬—材料状态机与三类 JSON 契约校验 |
| `article_group/prewrite.py` | 写前门禁：候选池、槽位、新鲜度窗口、编辑选择 |
| `article_group/compliance_gate.py` | 社会话题合规门禁：三态判定（PASS/CONDITIONAL/FAIL），五道门 + 分级规则 |
| `article_group/compliance_cli.py` | 手动 CLI：五道门合规声明检查（`--pool`/`--candidate`，`--json`） |
| `article_group/sync_compliance.py` | 将候选 JSON 的五道门声明同步为 Markdown 清单 |
| `article_group/toutiao_capture.py` | 头条公开文章快照，用于证据（无 cookie/JS/反爬绕过） |
| `article_group/toutiao_cli.py` | 头条捕获的 CLI 入口 |
| `article_group/wechat.py` | 微信公开文章正文抓取与验证码页 fail-closed 解析 |
| `article_group/wechat_capture.py` | 微信正文快照、sidecar 元数据与 CLI 入口 |
| `article_group/yuafeng_hot.py` | 只读玉峰热榜客户端（UC、腾讯新闻、聚合榜） |
| `article_group/discovery_radar.py` | 隔离的 R0 发现雷达产物构建器 |
| `article_group/yuafeng_radar_cli.py` | 构建单个 R0 发现专用雷达 JSON 的 CLI |
| `article_group/tgmeng_hot.py` | 只读糖果梦热榜客户端（自宿主 NAS：9 榜 + 糖果指数 8 类；缓存路径，零 AI 消耗） |
| `article_group/tgmeng_radar.py` | tgmeng 源的隔离 R0 发现雷达构建器 |
| `article_group/tgmeng_radar_cli.py` | 构建单个 tgmeng R0 发现专用雷达 JSON 的 CLI |
| `article_group/case_contract.py` | case 卡契约校验器：事实/反馈词汇与技法引用（`validate_case_card`、`validate_fact_evidence_pack`） |
| `article_group/bilibili_capture.py` | B站长文公开研究证据捕获与校验（依赖 `case_contract`） |
| `v2_contract/` | V2 契约影子校验器：任务卡 JSON + 冻结状态词表 YAML（jsonschema）——绝不导入或改动 `article_group/` |
| `article_group/delivery.py` | 纯文本交付物派生/校验（Markdown 保持为规范稿） |
| `article_group/content_delivery.py` | 将后台 final review 与“可直接交给人复制发布”的内容就绪状态分开 |
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

## 手动来源捕获（微信）

微信桌面请求可能返回 HTTP 200 的“环境异常”页。专用入口会使用公开移动端
文章面、补齐 `scene=25`，并且只有检测到 `#js_content` 正文后才保存；不读取
Cookie 或登录态。

直接阅读正文：

```bash
uv run python -m article_group.wechat_capture \
  'https://mp.weixin.qq.com/s/<article-key>'
```

保存为 run 内的 `sources/<source-id>.clean.md` 和哈希 sidecar：

```bash
uv run python -m article_group.wechat_capture \
  'https://mp.weixin.qq.com/s/<article-key>' \
  --run-root runs/2026-09-14/controlled-001 \
  --source-id WX-<article-key> \
  --role research-reference \
  --independence-group wechat:<article-key>
```

失败的验证码页、空壳页和网络失败不会进入材料包。完整用法与错误码见
[`docs/codex/wechat-source-capture.md`](docs/codex/wechat-source-capture.md)。

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

## 发现雷达（糖果梦热榜）

第二个只读雷达，基于自宿主糖果梦热榜聚合器（局域网 `http://192.168.100.123:4399`）。结果仅用于发现——绝不作为事实主张的证据；糖果指数为 AI 聚合选题信号，**不得当事实引用**（双源核验不变）。

```bash
# 榜单：weibo zhihu bilibili douyin toutiao baidu maoyan tencent aiqiyi
# 糖果指数类目：all technology finance entertainment car sports game livelihood
uv run python -m article_group.tgmeng_radar_cli \
  --output-path runs/tgmeng/2026-08-11-r0.json \
  --boards "maoyan tencent aiqiyi" \
  --candy "entertainment all"
```

所有请求走服务端缓存路径（零 AI 消耗）；冷缓存窗口表现为稳定的 `source_empty` 错误码，绝不产生伪造数据。

## 契约校验器

```python
# V3：文章组先确认选题，再把同一 topic_id/version 交给抓爬任务
from article_group.editorial_pipeline_v3 import (
    validate_crawl_task,
    validate_material_pack,
    validate_pipeline_transition,
    validate_topic_card,
)

validate_topic_card(topic_card)
validate_crawl_task(crawl_task, topic_card=topic_card)
validate_material_pack(material_pack, topic_card=topic_card, crawl_task=crawl_task)
validate_pipeline_transition(
    "approved", "researching", topic_card=topic_card, crawl_task=crawl_task
)
```

V3 的 Schema 和状态门禁说明见
[`docs/codex/editorial-pipeline-v3.md`](docs/codex/editorial-pipeline-v3.md)。它只校验
文章组已经决定的选题及其材料，不自动选题、换题、写作、建爆款库或发布。

```bash
# V2 影子契约：任务卡 JSON + 冻结状态词表
uv run python -m v2_contract.validate_task_card path/to/task-card.json
uv run python -m v2_contract.validate_transition "R7 mechanically-verified" "R7.5 awaiting-independent-review"
```

```python
# case 卡契约：事实/反馈词汇与技法引用
from article_group.case_contract import validate_case_card, validate_fact_evidence_pack

validate_case_card({"case_id": "C-001", ...})          # 校验失败抛 CaseContractError（稳定错误码）
validate_fact_evidence_pack({"evidence_domain": "ruoyu_article_fact_evidence", ...})
```

`v2_contract/` 为影子模式：只读取冻结契约文件并报告错误，绝不发布、授权或改动工作流状态。

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

- 新批次必须显式声明 `run_profile`：默认日更使用 `two_article_daily`（A/B 两篇），历史三槽对照使用 `three_slot_controlled`（A/B/C）；不得用旧三槽校验器临时绕过 profile。
- Markdown 为规范稿，也是新批次默认的阅读、复核、真人 attestation 与交接对象；`article-plain.txt` 是面向不解析 Markdown 平台的复制粘贴交付物。
- 用户侧的最终交付目标是 `CONTENT_READY`：当前 Markdown 已完成事实、结构、标题、可读性和平台风险检查，可以直接交给真人复制发布；这不等于系统已经发布。
- `R8 review-ready`、`controlled-run-manifest.json`、真人 attestation 和 controller acceptance 属于后台治理/审计层。若用户只要成品文章，不要求发布，这些治理项不应阻塞 `CONTENT_READY` 交付；只有需要正式推进发布治理时才继续处理。
- 新批次必须声明 `review_surface=markdown_codex`，并生成 `review/markdown-review-evidence.json`，绑定当前 Markdown 的路径、字节数、SHA-256 和 CJK 字数；正常路径不生成、不保留 HTML，也不依赖预览服务。
- HTML 冻结与预览只在明确选择 `review_surface=html_delivery` 的历史/专门交付中启用；此时继续使用 `preview_mode=local_codex | canonical_http` 及原有逐路由哈希/HTTP 200 契约。
- 批次验收要求控制器审查新证据；M2 还要求独立人工编辑 attestation、动态事实 publication-time revalidation 和 controller acceptance 分层落盘。终审由独立方（Sol 路由）在对抗性审查 Gate 下执行，控制器做出每项验收决定。仓库内任何内容都不授权对外发布。

## Codex 旁路审查

Codex 审查是证据旁路，不替换本仓库的确定性门禁、`final_review` 或人工发布授权。

```bash
# 普通审查：Codex 原生 review，走 Luna 路由
uv run python -m article_group.codex_review \
  --mode normal \
  --repo . \
  --run-root runs/<date>/<run-id> \
  --output runs/<date>/<run-id>/review/codex-normal.json \
  --request '说明本次变更和验收目标' \
  --acceptance '逐条列出必须满足的验收条件' \
  --risk L1

# L2 对抗审查：只读、Sol high、结构化 review contract
uv run python -m article_group.codex_review \
  --mode l2 \
  --repo . \
  --run-root runs/<date>/<run-id> \
  --output runs/<date>/<run-id>/review/codex-l2.json \
  --request '原始任务请求' \
  --acceptance '逐条列出验收条件' \
  --focus '指定需要独立挑战的边界和负向路径' \
  --risk L2
```

命令只写 JSON 记录和 `.log` 原始输出，记录输出哈希，并固定
`publication_authorization: not_authorized`。L2 结果必须是
`approve`、`needs_changes` 或 `evidence_insufficient`；任何修复、复审、发布或状态推进仍由控制器决定。

在完成三次代表性批次试点并核对旧链结果一致前，不删除旧的 Hermes/Kanban 审查记录。

## 边界

绿色本地校验器只确认确定性批次门禁——它不建立事实真值、文章质量、`publish-ready` 或发布授权。事实断言必须能在该运行根的 `citations-ledger.json` 中找到逐字引文。

## 文章组 V4 离线证据层

V4 只处理文章组已经确定的选题：组合计划、证据图、缺口优先队列、反模板提醒、真实指标回填和恢复动作。它不自行选题或换题，不联网、不写 Vault、不生成 HTML、不发布。

```bash
.venv/bin/python scripts/article_group_v4.py verify \
  --run-dir <当前运行根> \
  --output-dir runs/<日期>/<运行编号>/v4
```

验收结果会分别列出 `PASS`、缺失来源角色、重试要求、人工升级项、`content_status` 和 `publication_authorization`。`CONTENT_READY` 只是 Markdown 可交给真人处理，发布授权始终为 `not_authorized`。详细字段和各子命令见 [`docs/codex/editorial-pipeline-v4.md`](docs/codex/editorial-pipeline-v4.md)。

## 文章组 V5 自适应反馈层

V5 在 V4 的证据、调度和反馈基础上增加实验记录、内容生命周期、文章 DNA、失败样本、四周动态配额、版本化策略库和资源预算建议。它回答“为什么表现好或不好、下一篇具体改变什么”，但不自动选题、换题、发布或把相关性升级成因果结论。

```bash
.venv/bin/python scripts/article_group_v5.py verify \
  --run-dir tests/fixtures/v5/controlled-001 \
  --output-dir runs/2026-09-09/v5/controlled-001
```

该命令只读取显式运行根，写出八个 JSON 并逐一读回；输出拒绝不同内容覆盖，不生成 HTML，不保存凭据。受控 fixture 是合成测试输入。报告独立列出 `PASS`、缺失来源角色、重试要求、人工升级项和 `content_status`；`CONTENT_READY` 只代表交给文章组/controller 复核，`publication_authorization` 始终为 `not_authorized`。完整字段、生命周期、失败分类、配额边界和策略状态见 [`docs/codex/editorial-pipeline-v5.md`](docs/codex/editorial-pipeline-v5.md)。
