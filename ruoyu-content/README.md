# ruoyu-content｜历史本地内容工作区

> 这是 2026 年 5 月底形成的本地内容工作区约定，当前保留为历史兼容资料、旧产物归档和写作案例参考。新 agent 下载仓库后，文章组主入口请使用 `projects/ruoyu-article-group/`，不要从本目录启动新的平台抓取、四层验证或正式成稿流程。

## 当前定位

- `ruoyu-content/` 是历史工作区，不是当前生产入口。
- 这里的三步流水线、旧脚本、旧计划文件只保留为兼容说明和迁移参考。
- 当前任务要求以 `projects/ruoyu-article-group/` 为准：平台源配置、信号抓取、四层验证、approved 白名单和 final 桥接都在那里执行。
- 新 agent 如果需要“下载即用”，应先读根 `README.md` 和 `projects/ruoyu-article-group/README.md`，再执行当前脚本。

## 历史目录说明

```text
00-inbox/                 历史临时投喂资料
01-hotspot-assistant/     旧本地热点助手任务书、规则、运行记录
02-research-daily/        旧每日热点简报和选题池
03-article-corpus/        旧正文语料库
04-plans/HOT_SPOT_PLAN.md 旧硬核大纲交接文件
05-drafts/                旧扩写初稿
06-final/                 旧终稿归档
07-data/                  旧数据表
08-scripts/               旧本地采集脚本和 legacy 配置
09-archive/               旧 NAS / handover 资料归档
10-case-library/          爆款案例库、培训材料、写作标准
```

这些文件可以用于理解历史写作偏好、案例结构和复盘经验，但不能替代当前验证脚本、当前配置样例或 approved 白名单。

## 已废弃/仅兼容的旧三步

历史流程曾经是：

1. OpenClaw 输出选题判断、事实锚点、电影桥段锚点和硬核大纲到 `04-plans/HOT_SPOT_PLAN.md`。
2. Reasonix / DeepSeek-V4-Flash 基于素材和大纲生成 `05-drafts/draft_article.txt`。
3. OpenClaw 终审抛光，输出到 `06-final/`。

这套说法现在只作为历史兼容资料保留。当前 agent 不应把 `04-plans/`、`05-drafts/`、`06-final/` 当成新的默认生产链路。

## 当前迁移映射

| 历史位置 | 当前对应位置 / 动作 |
| --- | --- |
| `08-scripts/` 旧采集脚本 | 使用 `projects/ruoyu-article-group/scripts/collect_platform_signals.py` |
| `04-plans/HOT_SPOT_PLAN.md` | 使用 `handover-hotspot/04-QUALITY-FEEDBACK/directive-latest.md` 和 `latest-feedback.md` |
| `05-drafts/draft_article.txt` | 只在 approved 题目通过后再生成正式任务，不再作为默认入口 |
| `06-final/` | 使用 `projects/ruoyu-article-group/ruoyu-output/final/YYYY-MM-DD/` 的 Markdown + HTML 输出 |
| `10-case-library/` | 仅作为人工风格/案例参考，必要规则应手工迁移到当前项目文档 |

## 当前正确入口

在仓库根目录执行：

```bash
python3 projects/ruoyu-article-group/scripts/collect_platform_signals.py \
  --config projects/ruoyu-article-group/config/platform-sources.local.json \
  --date YYYY-MM-DD

python3 projects/ruoyu-article-group/scripts/validate_article_pipeline.py --date YYYY-MM-DD
python3 projects/ruoyu-article-group/scripts/bridge_approved_to_final.py --date YYYY-MM-DD --index 1 --slot 1
```

没有本地配置时，先复制样例：

```bash
cp projects/ruoyu-article-group/config/platform-sources.example.json \
   projects/ruoyu-article-group/config/platform-sources.local.json
```

真实 cookie / token 只允许放在本机环境变量或本机未提交配置里，不允许写进本目录。

## 禁止事项

- 不要把旧 NAS、旧 OpenClaw、旧热点猎手脚本当作当前可执行主线。
- 不要把旧终稿目录里的文章当作今天的新产物。
- 不要跳过 `validate_article_pipeline.py` 直接发布历史 Markdown / HTML。
- 不要把旧文档中的内网地址、账号线索、cookie、token、私人邮箱、本机路径复制到新 README、配置样例或 PR 正文。
- 不要在本目录新增今天的运行产物；新产物应由当前项目脚本生成到当前项目约定位置。
