# 若雨随影文章组项目流程｜验证脚本阶段

## 阶段定位

当前不是重跑采集阶段，而是先把文章组流水线的“入口、状态、拍板、产出任务、正式成稿”全部脚本化/模板化验证。

验证脚本阶段的目标：

> 任何一天文章组跑完后，Mac 总监不用人工翻几十个文件，就能用脚本判断：四层状态是否完整、候选是否合规、拍板白名单是否存在、正式成稿是否越权；一旦进入写作，产出任务卡能明确服务今日头条和微信公众号，而不是泛平台写稿。

---

# 总项目阶段

## Phase A0：项目立项与规则固化

状态：已启动

交付物：

- `README.md`
- `plans/project-flow.md`
- `verification/checklist.md`
- `logs/progress.md`

验收：

- 项目目录存在。
- 四层状态写入项目规则。
- 验证脚本阶段目标明确。

---

## Phase A1：入口文件验证脚本

目标：先保证读的是对的入口，不再读旧流程噪音。

检查对象：

- `handover-hotspot/WORKFLOW-RECAST-CONTENT-AND-VIDEO-2026-06-10.md`
- `handover-hotspot/04-QUALITY-FEEDBACK/directive-latest.md`
- `handover-hotspot/04-QUALITY-FEEDBACK/latest-feedback.md`（symlink → 当日采集目录）
- `handover-hotspot/04-QUALITY-FEEDBACK/director-review-latest.md`（兼容旧 `nas-director-model-review-latest.md`）
- `handover-hotspot/04-QUALITY-FEEDBACK/article-approved-latest.md`

脚本能力：

1. 检查文件存在。
2. 检查文件非空。
3. 检查更新时间 / 日期是否合理。
4. 检查是否误读旧目录 `04-FEEDBACK/`。
5. 输出入口健康报告。

验收：

- 运行一次脚本能给出 PASS / WARN / FAIL。
- 旧入口出现时必须提示“降级为历史兼容，不作为正式判断”。

---

## Phase A2：四层状态验证脚本

目标：文章组状态必须拆成：采集、候选/评分、NAS 总监复评、正式成稿。

脚本能力：

1. 从 `latest-feedback.md`（symlink → 当日采集）识别文章组区块。
1. 从 `director-review-latest.md` 提取 NAS 总监复评区块，并兼容旧 `nas-director-model-review-latest.md`。
2. 检查是否包含采集状态。
3. 检查是否包含候选 / 评分。
4. 检查是否包含 NAS 总监复评。
5. 检查是否有正式拍板或明确未产出原因。

验收：

- 缺任一层，报告 FAIL。
- 只有“跑了 / 有素材 / 充足”但没四层拆分，报告 FAIL。

---

## Phase A3：候选质量验证脚本

目标：把旧闻、乱码、偏社会、非影视相关且无母本价值、事实不硬的候选提前拦住。

检查规则：

1. 影视相关性 / 母本价值：必须能落到电影、剧集、综艺、演员、角色、作品、行业观察之一，或能成为影视相关爆款文章的有效母本。
2. 时效：默认 72 小时内；超过 72 小时必须标注旧闻新角度；超过 7 天默认 FAIL。
3. 事实硬度：标题里的数字、人物、作品、结果必须可核查。
4. 展开空间：必须有冲突、反差、人物意味、行业意味、表达价值至少之一。
5. 乱码检测：疑似编码错误候选直接 FAIL。

验收：

- 能识别 latest-feedback 里出现的乱码标题。
- 能把纯社会 / 健康 / 民生且无影视相关表达的候选标为非主稿候选。
- 能输出 Top 候选问题清单。

---

## Phase A4：NAS 总监复评字段验证

目标：复评不是空话，必须具备 6 字段。

必需字段：

1. 题目
2. 发布时间
3. 为什么今天值得写
4. 最适合的写作角度
5. 风险点
6. 结论：主稿 / 备稿 / 放弃

验收：

- 每个进入复评的候选都必须有 6 字段。
- 缺字段不得进入正式写作。

---

## Phase A5：拍板白名单与正式成稿一致性验证

目标：防止白名单之外的题进入 final。

检查对象：

- `handover-hotspot/04-QUALITY-FEEDBACK/article-approved-latest.md`
- `projects/ruoyu-article-group/ruoyu-output/final/YYYY-MM-DD/`
- `projects/ruoyu-article-group/ruoyu-output/draft/YYYY-MM-DD/`
- `projects/ruoyu-article-group/ruoyu-output/hold/YYYY-MM-DD/`

脚本能力：

1. 读取当天 article-approved 白名单。
2. 扫描当天 final 成稿。
3. 检查 final 标题是否来自白名单。
4. 检查 draft/hold 是否误报为正式稿。
5. 检查 Markdown 成稿是否同步 HTML。

验收：

- 白名单外 final 直接 FAIL。
- 只有 draft 没有 final 时，正式产出状态必须为“未完成”。
- Markdown 无 HTML 配套，报告 WARN 或 FAIL。

---

## Phase A6：文章产出任务卡

目标：把“今日头条 / 微信公众号是文章组主要收益平台”的约束落到每篇正式写作任务，而不是停在方法文档或采集评分层。

检查对象：

- `templates/article-production-task.md`
- 当天进入 `projects/ruoyu-article-group/ruoyu-output/final/YYYY-MM-DD/` 的 Markdown 成稿
- 当天如存在 draft，也应先有同口径任务卡或在稿首/核查摘要中体现任务卡字段

任务卡必填：

1. 主平台：今日头条 / 微信公众号 / 双平台。
2. 标题池：至少 5 个标题，最终标题 30 字以内优先；数字必须来自已核事实。
3. 开头钩子：头条版前 150 字进入热闹；公众号版前 300 字给出核心判断。
4. 正文结构：头条短段递进；公众号保留可收藏的长文判断。
5. 禁用套话：标题、开头、结尾升华三类都要列出本篇风险。
6. 证据底座：P0/P1A/P1B/P1C 分清，未核事实降级或删除。
7. 二审问题：点击理由、读完收益、证据递进、禁用套路命中。
8. 交付要求：Markdown + HTML，附核查摘要。

验收：

- 每篇正式成稿必须能回溯到一张产出任务卡，或在稿件内部显式包含同等字段。
- 没有任务卡不直接判旧稿 FAIL，但新稿验证报告至少 WARN。
- 任务卡只影响文章组成稿，不扩大采集源，不混入视频组。

---

## Phase A7：日报验证报告

目标：每天自动生成一份文章组验证报告。

输出路径：

- `projects/ruoyu-article-group/logs/YYYY-MM-DD-validation.md`

报告格式：

1. 来源标签：本地镜像 / NAS生产端 / 在线猎手 / 在线总监 / Mac临时复核。
2. 四层状态。
3. 入口文件健康。
4. 候选质量问题。
5. 复评字段完整性。
6. 白名单与 final 一致性。
7. 结论：可进入写作 / 需补采 / 需复评 / 禁止成稿。

---

# 当前优先级

P0：入口文件验证。
P0：四层状态验证。
P1：候选质量验证。
P1：白名单与 final 一致性验证。
P1：文章产出任务卡。
P2：HTML 配套验证。

# 现阶段不做

- 不扩大采集源。
- 不让视频组逻辑混进文章组。
- 不把旧目录结果当成正式判断。
