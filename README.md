# 若雨随影文章组

这是一个给 agent 使用的影视自媒体文章生产最小系统：下载仓库后，agent 可以先抓取平台信号，自动生成文章组入口文件，再做候选验证、总监复评、approved 白名单和 Markdown + HTML 成稿桥接。

它的目标不是保存个人账号，也不是把 cookie 放进仓库，而是把“我们怎么从平台热点里找到可写母本，并写成今日头条 / 微信公众号文章”的链路写清楚、跑起来、验得住。

## 一句话流程

```text
平台热点/讨论页
  → scripts/collect_platform_signals.py
  → handover-hotspot/04-QUALITY-FEEDBACK/*.md
  → scripts/validate_article_pipeline.py
  → scripts/bridge_approved_to_final.py
  → ruoyu-output/final/YYYY-MM-DD/*.md + *.html
```

## 项目入口

主要代码和文档位于：

```text
projects/ruoyu-article-group/
```

新 agent 下载仓库后，默认只从这个目录启动文章组任务。根目录下的 `memory/`、`ruoyu-content/`、`ruoyu-system/` 是历史资料和兼容归档，不是当前生产入口。

核心文件：

```text
projects/ruoyu-article-group/config/platform-sources.example.json
projects/ruoyu-article-group/scripts/collect_platform_signals.py
projects/ruoyu-article-group/scripts/validate_article_pipeline.py
projects/ruoyu-article-group/scripts/bridge_approved_to_final.py
projects/ruoyu-article-group/templates/article-production-task.md
projects/ruoyu-article-group/verification/checklist.md
```

## 抓取哪些平台

默认配置示例抓取的是影视娱乐自媒体常用的“选题信号”，不是最终事实结论：

| 平台 | 用途 | 登录信息 |
| --- | --- | --- |
| 微博 | 热搜、搜索讨论、明星/剧集/电影争议信号 | 可选 `WEIBO_COOKIE` |
| 知乎 | 热榜、问答讨论、长观点母本 | 可选 `ZHIHU_COOKIE` |
| B站 | 排行榜、视频讨论、年轻用户情绪 | 可选 `BILIBILI_COOKIE` |
| 豆瓣电影 | 电影榜单、口碑、评分和影迷讨论入口 | 默认公开访问 |

这些平台信号会被整理为：

```text
handover-hotspot/04-QUALITY-FEEDBACK/directive-latest.md
handover-hotspot/04-QUALITY-FEEDBACK/latest-feedback.md
handover-hotspot/04-QUALITY-FEEDBACK/director-review-latest.md
handover-hotspot/04-QUALITY-FEEDBACK/article-approved-latest.md
```

agent 后续只从 `article-approved-latest.md` 里挑 approved 题目桥接正式稿。

## 使用者需要填写什么

使用者不需要填写姓名、手机号、邮箱、微信号、账号密码或 token。

需要填写/修改的是平台源配置。先复制样例：

```bash
cd projects/ruoyu-article-group
cp config/platform-sources.example.json config/platform-sources.local.json
```

然后在 `config/platform-sources.local.json` 里改这些字段：

| 字段 | 是否必填 | 说明 |
| --- | --- | --- |
| `project` | 是 | 项目名，例如“某某影视文章组” |
| `topic_domain` | 是 | 内容领域，例如“影视娱乐” |
| `publishing_platforms` | 是 | 目标发布平台，例如“今日头条”“微信公众号” |
| `sources[].name` | 是 | 来源名称，给 agent 看 |
| `sources[].platform` | 是 | 平台标识，例如 `weibo`、`zhihu`、`bilibili`、`douban` |
| `sources[].url` | 是 | 要抓取的公开榜单页、热榜页、搜索页或已授权页面 |
| `sources[].mode` | 是 | `public_url` 或 `optional_cookie` |
| `sources[].cookie_env` | 否 | 需要登录态时填写环境变量名，不填真实 cookie |

示例：

```json
{
  "name": "微博热搜公开页",
  "platform": "weibo",
  "mode": "optional_cookie",
  "url": "https://s.weibo.com/top/summary",
  "cookie_env": "WEIBO_COOKIE"
}
```

如果某个平台需要登录态，只在本机环境变量里设置：

```bash
export WEIBO_COOKIE='你的本机 cookie，不提交 Git'
export ZHIHU_COOKIE='你的本机 cookie，不提交 Git'
export BILIBILI_COOKIE='你的本机 cookie，不提交 Git'
```

## 下载后交给 agent 怎么跑

在仓库根目录执行：

```bash
python3 projects/ruoyu-article-group/scripts/collect_platform_signals.py \
  --config projects/ruoyu-article-group/config/platform-sources.local.json \
  --date YYYY-MM-DD
```

如果还没创建 local 配置，也可以先用样例配置试跑：

```bash
python3 projects/ruoyu-article-group/scripts/collect_platform_signals.py \
  --config projects/ruoyu-article-group/config/platform-sources.example.json \
  --date YYYY-MM-DD
```

然后验证四层状态：

```bash
python3 projects/ruoyu-article-group/scripts/validate_article_pipeline.py --date YYYY-MM-DD
```

最后把 approved 白名单中的一条任务桥接到 final：

```bash
python3 projects/ruoyu-article-group/scripts/bridge_approved_to_final.py --date YYYY-MM-DD --index 1 --slot 1
```

桥接脚本会在项目内生成 Markdown 和 HTML：

```text
projects/ruoyu-article-group/ruoyu-output/final/YYYY-MM-DD/
```

## 四层状态

文章组状态必须拆成四层看，不能只说“跑了”：

1. 采集
2. 候选 / 评分
3. NAS 总监复评
4. 正式成稿

验证脚本会围绕这四层检查入口文件、候选质量、approved 白名单、final 成稿一致性、产出任务卡和 HTML 配套情况。

## 安全边界

以下内容禁止写入仓库、README、JSON 样例或生成的 Markdown：

```text
手机号
私人邮箱
微信号
账号密码
cookie
session
token
API key
内网管理地址
本机绝对路径
```

当前 `.gitignore` 已忽略：

```text
config/platform-sources.local.json
.env
*.env
*.secret
*.token
cookies.json
session.json
*.cookies.json
logs/*.md
ruoyu-output/
```

也就是说，真实登录态和运行产物都只留在本机。

## 版本边界

本仓库纳入版本的是文章组 agent-ready 骨架、平台源样例、抓取脚本、验证脚本和桥接脚本。以下内容不进入版本：

```text
projects/ruoyu-article-group/config/platform-sources.local.json
projects/ruoyu-article-group/logs/*.md
projects/ruoyu-article-group/logs/progress.md
projects/ruoyu-article-group/ruoyu-output/
```

验证日志和真实文章产物是运行时输出，不作为代码提交的一部分。

## 历史目录边界

根目录下还有三个历史目录，保留是为了兼容旧资料和方便人工复盘，不代表当前 agent 应从那里启动任务：

| 目录 | 当前定位 | 允许用途 | 禁止用途 |
| --- | --- | --- | --- |
| `memory/` | 历史运行记忆归档 | 回看旧决策、旧偏好、旧上下文 | 当作当前任务状态、复制私人/内网/凭据信息 |
| `ruoyu-content/` | 旧本地内容工作区 | 参考历史文章、旧大纲、案例库 | 启动新抓取、沿用旧三步流水线、发布旧产物 |
| `ruoyu-system/` | 旧系统资料与案例归档 | 人工提炼写作标准、复盘旧系统 | 运行旧脚本、跳过当前验证、复制旧敏感线索 |

如果这三个目录里有规则仍然有效，处理方式不是让 agent 直接按旧文档跑，而是先人工迁移到 `projects/ruoyu-article-group/` 的 README、模板、验证清单或脚本测试里，再按当前验证口径执行。

## 验证口径

验证脚本报告使用四类状态：

- `PASS`：检查通过，可进入下一步人工抽检或交付。
- `INFO`：信息提示，不阻断。
- `WARN`：可继续推进，但需要人工补齐或复核。
- `FAIL`：禁止称为正式产出。

缺少上游输入时，脚本应明确给出 `FAIL`，而不是生成占位稿或假装成功。
