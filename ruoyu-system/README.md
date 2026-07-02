# ruoyu-system｜历史系统资料与案例归档

这个目录保存 2026 年 5 月底到 6 月初的若雨随影旧系统资料，包括早期文章、脚本、培训材料、爆款案例库和流程纪要。

## 当前定位

- `ruoyu-system/` 是历史系统归档和案例参考目录，不是当前生产入口。
- 它不是当前文章组的 agent-ready 主入口。
- 新 agent 不应从这里启动平台抓取、四层验证、approved 白名单或正式成稿桥接。
- 当前主入口在：

```text
projects/ruoyu-article-group/
```

## 里面有什么

```text
articles/      早期文章样例与 HTML 输出
scripts/       早期脚本/素材页面
*.md           旧流程、培训、案例库和复盘文档
```

这些内容可以帮助理解写作标准、案例偏好、选题口味和历史复盘，但不能替代当前验证脚本和 approved 白名单。

## 与当前任务要求的关系

当前任务要求是：下载仓库后，agent 能在最小配置下执行平台信号抓取、生成入口文件、验证四层状态，并把 approved 题目桥接到 Markdown + HTML 成稿。

因此：

| 旧系统资料 | 当前处理方式 |
| --- | --- |
| 旧文章样例 / HTML | 仅作案例参考，不作为今天产物 |
| 旧脚本 / 素材页面 | 不作为默认执行入口；如需复用，先迁移到 `projects/ruoyu-article-group/` 并补验证 |
| 爆款案例库 / 培训材料 | 可人工提炼为写作标准，但不能自动覆盖当前流程 |
| 旧 NAS / 热点猎手流程纪要 | 仅保留历史背景；当前以本仓库 agent-ready 脚本为准 |

## 可以使用

- 参考旧爆款案例、标题/结构经验、总监反馈。
- 作为人工复盘和风格校准材料。
- 手工迁移明确仍有效的规则到 `projects/ruoyu-article-group/` 文档。
- 对比旧流程与当前流程，找出需要补进当前验证链路的规则。

## 不要使用

- 不要把旧文章或旧脚本当作今天的正式产物。
- 不要从 `ruoyu-system/scripts/` 启动当前平台抓取。
- 不要跳过 `validate_article_pipeline.py` 直接发布这里的 HTML/Markdown。
- 不要把旧文档里的内网地址、个人信息、账号线索、cookie/token 复制到新配置、README、PR 正文或公开产物。
- 不要在这个目录新增运行产物；新产物应由当前脚本生成到当前项目约定位置。

## 当前正确入口

```bash
python3 projects/ruoyu-article-group/scripts/collect_platform_signals.py \
  --config projects/ruoyu-article-group/config/platform-sources.local.json \
  --date YYYY-MM-DD

python3 projects/ruoyu-article-group/scripts/validate_article_pipeline.py --date YYYY-MM-DD
python3 projects/ruoyu-article-group/scripts/bridge_approved_to_final.py --date YYYY-MM-DD --index 1 --slot 1
```

没有本地配置时，先复制样例配置；真实 cookie / token 只能留在本机环境变量或未提交的 local 配置里。
