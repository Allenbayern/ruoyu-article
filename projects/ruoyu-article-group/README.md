# 若雨随影文章组项目

## 项目定位

这是一个给 agent 使用的影视自媒体文章生产最小系统。它把平台热点/讨论信号抓下来，整理成文章组四层入口文件，再通过验证脚本检查候选、复评、approved 白名单和 final 成稿一致性。

目标不是“每天跑一堆素材”，而是让 agent 下载仓库后能按固定入口工作：

```text
平台信号采集 → 候选/评分 → NAS 总监复评 → approved 白名单 → 正式成稿 Markdown + HTML
```

## agent-ready 快速开始

从仓库根目录执行：

```bash
# 1. 准备本地平台源配置；真实配置不提交 Git
cp projects/ruoyu-article-group/config/platform-sources.example.json \
   projects/ruoyu-article-group/config/platform-sources.local.json

# 2. 修改 local 配置里的平台 URL、项目名、目标发布平台
#    如需登录态，只设置环境变量，不要把 cookie 写进 JSON
export WEIBO_COOKIE='可选：只放本机，不提交 Git'
export ZHIHU_COOKIE='可选：只放本机，不提交 Git'
export BILIBILI_COOKIE='可选：只放本机，不提交 Git'

# 3. 抓取平台信号并生成 handover 入口文件
python3 projects/ruoyu-article-group/scripts/collect_platform_signals.py \
  --config projects/ruoyu-article-group/config/platform-sources.local.json \
  --date YYYY-MM-DD

# 4. 验证四层状态
python3 projects/ruoyu-article-group/scripts/validate_article_pipeline.py --date YYYY-MM-DD

# 5. 将 approved 白名单中的第 1 条桥接成正式稿
python3 projects/ruoyu-article-group/scripts/bridge_approved_to_final.py --date YYYY-MM-DD --index 1 --slot 1
```

如果只是让 agent 先 smoke test，可以直接用样例配置跑第 3 步。

## 我们抓取什么平台

默认样例配置见：

```text
config/platform-sources.example.json
```

当前默认覆盖：

| 平台 | 信号用途 | 登录态 |
| --- | --- | --- |
| 微博 | 热搜、搜索讨论、明星/剧集/电影争议信号 | 可选 `WEIBO_COOKIE` |
| 知乎 | 热榜、问答讨论、长观点母本 | 可选 `ZHIHU_COOKIE` |
| B站 | 排行榜、视频讨论、年轻用户情绪 | 可选 `BILIBILI_COOKIE` |
| 豆瓣电影 | 电影榜单、口碑和影迷讨论入口 | 默认公开访问 |

这些平台给的是“选题母本”和“讨论信号”，不是直接事实结论。正式写作前必须核查时间、人物、作品、数据和原始来源。

## 使用者需要填写什么

使用者不需要填写个人身份信息。

需要填写的是：

| 信息 | 填在哪里 | 是否敏感 |
| --- | --- | --- |
| 项目名 | `config/platform-sources.local.json` 的 `project` | 否 |
| 内容领域 | `topic_domain` | 否 |
| 发布平台 | `publishing_platforms`，如今日头条/微信公众号 | 否 |
| 平台源名称 | `sources[].name` | 否 |
| 平台标识 | `sources[].platform` | 否 |
| 抓取 URL | `sources[].url` | 公开 URL 通常不敏感；内网页面需谨慎 |
| 抓取模式 | `sources[].mode`，`public_url` 或 `optional_cookie` | 否 |
| cookie 环境变量名 | `sources[].cookie_env`，如 `WEIBO_COOKIE` | 变量名不敏感 |
| 真实 cookie/token | 本机环境变量或本机 `.env` | 敏感，禁止提交 |

禁止写入 Git 的内容：手机号、邮箱、微信号、账号密码、真实 cookie、session、token、API key、内网管理地址、本机绝对路径。

## 生成的入口文件

`collect_platform_signals.py` 会生成：

```text
handover-hotspot/04-QUALITY-FEEDBACK/directive-latest.md
handover-hotspot/04-QUALITY-FEEDBACK/latest-feedback.md
handover-hotspot/04-QUALITY-FEEDBACK/director-review-latest.md
handover-hotspot/04-QUALITY-FEEDBACK/article-approved-latest.md
```

后续验证和桥接都读这些文件。

## 四层状态

1. 采集
2. 候选 / 评分
3. NAS 总监复评
4. 正式成稿

任何汇报必须按这四层拆开，不得只说“跑了”。

## 当前验证重点

1. 文件入口是否正确。
2. 候选是否满足影视相关性 / 爆款文章母本价值、72 小时、事实硬度、展开空间。
3. NAS 总监复评是否包含 6 字段。
4. 正式成稿是否只来自 `article-approved-latest.md`。
5. final/draft/hold 目录是否按规则使用。
6. 正式写稿任务是否带有“今日头条 / 微信公众号”产出任务卡，而不是只给一个题目就开写。

## 文章产出任务入口

每篇进入正式写作的文章，必须先按 `templates/article-production-task.md` 补齐产出任务卡，再进入正文写作与 HTML 交付。

产出任务卡只服务文章组成稿，不用于采集扩源，也不替代 NAS 总监复评。它的作用是把“今日头条 + 微信公众号”为主收益平台的写作约束落到当篇文章：标题池、开头钩子、正文结构、禁用套话、证据底座、核查摘要。

## 验证命令与报告口径

日常验证：

```bash
python3 projects/ruoyu-article-group/scripts/validate_article_pipeline.py --date YYYY-MM-DD
```

脚本会写入 `projects/ruoyu-article-group/logs/YYYY-MM-DD-validation.md`，并检查入口文件、四层状态、候选质量、approved/final 一致性、文章产出任务卡、内容质量门与 HTML 配套。

报告级别口径：

- `PASS`：检查通过，可进入下一步人工抽检或交付。
- `INFO`：信息提示，不阻断。
- `WARN`：可继续推进但必须人工补齐或复核。
- `FAIL`：禁止称为正式产出。

如果当日尚无真实 `draft/final` 稿件，不创建占位稿、不造假验证；等稿件落入 `projects/ruoyu-article-group/ruoyu-output/draft/YYYY-MM-DD/` 或 `projects/ruoyu-article-group/ruoyu-output/final/YYYY-MM-DD/` 后，复跑同一命令检查任务卡与内容质量门。

## 桥接 approved 到 final

```bash
python3 projects/ruoyu-article-group/scripts/bridge_approved_to_final.py --date YYYY-MM-DD --index 1 --slot 1
```

桥接脚本优先复用仓库根目录的 `scripts/ruoyu_md_to_html.py`；如果新环境没有该渲染器，会使用内置 fallback 生成基础 HTML，确保 Markdown + HTML 产物链路可跑通。

## MVP 验收

文章组项目进入“可日常稳定执行”状态，至少要满足：

- 平台抓取脚本能生成四个入口文件。
- 验证脚本能检查 4 个入口文件是否存在、是否过期、是否为空。
- 验证脚本能检查 latest-feedback + director-review-latest + article-approved-latest 是否按四层状态输出。
- 验证脚本能发现乱码候选、旧闻无新角度、非影视相关且无母本价值候选。
- 验证脚本能检查 approved 白名单与 final 成稿一致性。
- 正式写稿任务模板能约束标题、开头、正文、二审与 HTML 交付，默认服务今日头条和微信公众号。
- 每日运行后能生成一份 `logs/YYYY-MM-DD-validation.md`。
- 桥接脚本能在 `ruoyu-output/final/YYYY-MM-DD/` 生成 Markdown 与 HTML；该目录为运行产物，不进入版本。
