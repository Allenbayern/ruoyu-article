# 文章组验证脚本 Checklist

## P0：入口健康

- [ ] 总纲文件存在：`handover-hotspot/WORKFLOW-RECAST-CONTENT-AND-VIDEO-2026-06-10.md`
- [ ] `directive-latest.md` 存在且非空
- [ ] `latest-feedback.md` 存在且非空
- [ ] `article-approved-latest.md` 存在且非空或明确写明今日无拍板
- [ ] 未把旧 `04-FEEDBACK/` 当正式入口

## P0：四层状态

- [ ] 采集状态明确
- [ ] 候选 / 评分明确
- [ ] NAS 总监复评明确
- [ ] 正式成稿状态明确
- [ ] 汇报含来源标签

## P1：候选质量

- [ ] 候选发布时间明确
- [ ] 72 小时规则检查
- [ ] 超 7 天候选自动降级或 FAIL
- [ ] 影视相关性 / 爆款文章母本价值检查
- [ ] 乱码标题检查
- [ ] 事实硬度检查
- [ ] 展开空间检查
- [ ] 一票否决项检查

## P1：复评字段

每条进入复评的候选必须包含：

- [ ] 题目
- [ ] 发布时间
- [ ] 为什么今天值得写
- [ ] 最适合的写作角度
- [ ] 风险点
- [ ] 结论：主稿 / 备稿 / 放弃

## P1：白名单与 final

- [ ] final 题目来自 `article-approved-latest.md`
- [ ] draft 不误报为 final
- [ ] hold 不误报为 final
- [ ] Markdown 成稿有 HTML 配套
- [ ] 输出目录符合 `projects/ruoyu-article-group/ruoyu-output/final|draft|hold/YYYY-MM-DD/`

## P1：文章产出任务卡

- [ ] 正式写作前已使用 `templates/article-production-task.md`
- [ ] 主平台明确：今日头条 / 微信公众号 / 双平台
- [ ] 标题池不少于 5 个，最终标题 30 字以内优先
- [ ] 标题含具体作品/人物/角色/行业锚点，不写泛化宏大判断
- [ ] 数字、票房、评分、热度、时间来自已核事实，不为点击虚构
- [ ] 开头按主平台进入：头条 150 字内进热闹；公众号 300 字内给判断
- [ ] 正文有证据递进，不用热评拼贴替代论证
- [ ] 本篇禁用标题/开头/结尾套话已列出并避开
- [ ] 核查摘要列明已核事实、降级表述、未使用风险素材
- [ ] Markdown 成稿后同步 HTML 交付

## 报告结论枚举

- PASS：可进入写作 / 可交付
- WARN：可推进但需补证据
- FAIL：禁止成稿或禁止称正式产出
