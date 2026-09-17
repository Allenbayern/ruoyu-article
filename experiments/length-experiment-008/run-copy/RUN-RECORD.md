# 2026-09-16/daily-008 运行记录（2026-09-16）

> 类型：`two_article_daily`（默认两篇 Markdown 成品，交付终点 `CONTENT_READY`，不发布）
> run 根：`runs/2026-09-16/daily-008`
> 授权边界：`publication_authorization: not_authorized`，全程未发布、未推送、未合并、未写 Vault
> 记录状态：provisional（agent 产出的运行记录，不是 controller 验收）

## 1. 本次任务是什么

按 `Hermes Article Group Workflow` 日更主流程 + **新管线（2026-09-16 P0/P1 落地后
首期全程执行）**：五问预检机器必填 → 机器门禁全绿 → 账本预检修缺口 → L2 →
final_review。选题首次使用谈资型发现源（DailyHotApi 快照 + LLM 分类层）的当日
分类信号，并与 NAS 糖果梦热榜交叉验证。

两篇成稿：
- art-001 《让子弹飞》之后，姜文为什么一部比一部拧巴（立场宣判型，知乎信号）
- art-002 我们只承认《还珠格格》有两部（情绪顿悟型，知乎信号）

## 2. 选题与来源

选题表：

| 篇 | 作品 | 文章模式 | 事件簇 | 核心问题 |
|----|------|---------|--------|---------|
| art-001 | 姜文电影（让子弹飞/一步之遥/邪不压正/你行你上） | 文化现象（作品与观众错位） | jiangwen-film-divide | 为什么《一步之遥》《邪不压正》都达不到《让子弹飞》的高度 |
| art-002 | 还珠格格 | 集体记忆（第三部与记忆分叉） | huanzhu-part3-memory-split | 为什么我们只承认《还珠格格》有两部 |

来源表（全部为本机抓取的公开页面，HTML 存于 run 根 `sources/`）：

| source_id | 来源 | 角色 | 用途 |
|-----------|------|------|------|
| src-wenwei-nixing (c01) | 新华网·文汇报 | media_report | 《你行！你上！》口碑/郎朗蓝本/钱德勒影评 |
| src-sohu-jw (c02) | 搜狐·影吹斯汀 | commentary | 票房数据/最低分/差评关键词 |
| src-thepaper-jianpian (c03) | 澎湃·湃客 | commentary | 荒诞现实主义/明"刚"/历史褶皱镜像 |
| src-shobserver-han (c04) | 上观新闻·韩浩月 | commentary | 开分6.7/隐喻失效/死结批判者 |
| src-sina-caidan (d01) | 新浪娱乐 | media_report | 还珠选角史实与重播讨论 |
| src-sohu-huanzhu3 (d02) | 搜狐号 | commentary | 第三部大换血/收视率 |
| src-163-huanzhu3 (d03) | 网易订阅 | commentary | 琼瑶"心头之痛"/赵薇说法/翻拍 |
| src-yahoo-zhaowei (d04) | Yahoo奇摩 | commentary | 赵薇承诺4年不演电视剧（繁体原文） |
| src-360-huanzhu3 (d05) | 360娱乐·橘子娱乐 | commentary | 人设崩塌/童话与巴掌/围场狩猎 |

跨批查重结论：`portfolio_gate` pass，无 same_work（两作品均无历史批次）。

**新信号源命中（2026-09-16 起记账）：2/2**——两篇选题均来自当日 classified
谈资信号（dailyhot-zhihu 路由）：
- art-001：知乎"为什么《一步之遥》《邪不压正》都达不到《让子弹飞》的高度？"
  （dispute=1，hot=1020000，classified 快照第 5 位）
- art-002：知乎"你认为《还珠格格》一二部是一个完整的故事，还是二三部是一个
  完整的故事？"（dispute=1，classified 快照第 6 位）
知乎问题页 403 未捕获，仅作 R0 信号；正文未把"热榜第几/今天"写成事实。

落选候选（结构化理由，见 candidate-pool.json rejected_prior_works）：
红楼梦（豆瓣信号，讨论帖为主权威不足）；优酷2027片单（行业信号缺观众向落点）；
杨坤维权（涉司法争议边界）；陈建州/佟丽娅/姚安娜（隐私八卦禁区）。

## 3. 两篇成稿

| 篇 | 标题 | CJK 字数 | SHA-256 |
|----|------|---------|---------|
| art-001 | 《让子弹飞》之后，姜文为什么一部比一部拧巴 | 1032 | `6a526892ef83892b…`（全文见 delivery 文件） |
| art-002 | 《还珠格格》第三部为什么像另一部剧 | 932 | `4f27395c8ab162bf…`（全文见 delivery 文件；r2 标题级更换后终稿） |

正文：`delivery/art-001/delivery.md`、`delivery/art-002/delivery.md`。

## 4. 门禁与证据

| 门禁 | 产物 | 结果 |
|------|------|------|
| portfolio_gate | portfolio-gate-report.json | pass（无 same_work；象限覆盖 A/B+C ✓） |
| topic_five_questions（五问预检） | review/topic-five-questions.json | pass（两候选五问必填+枚举全过，无 warning） |
| task_hierarchy 1.0 契约 | task-hierarchy-validation-report.json | pass |
| claim_source_provenance | review/gates/claim-source-check.json | pass（46 facts 全锚定，0 未锚定；r1 修复补入 c02"盘到包浆/如数家珍"条目） |
| editorial_protocol | review/gates/editorial-protocol.json | pass |
| style_gate | review/style-gate-markdown-art-001/002.json | pass（0 errors；fact_density 8/13、8/11 ≥1/3） |
| 账本预检（新工序） | review/art-00X/ledger-coverage-precheck.json | 已跑：抓出 2 处真实缺口（《天上人间》剧名、婚后剧情断言）并删改修复；剩余报项全部裁定为作者框架/信号转述 |
| article_rule_compliance | preflight-report.json | PENDING（source_stripped_readability 待人工签署，治理栏非内容阻塞） |
| independent_review ⑧ | review/gates/independent-review.json | L2 进行中 |
| compliance_gate | review/gates/compliance-gate.json | not_run（影视制作题材非 social_topic，显式记录原因） |

## 5. 独立 L2 对抗复核

执行者：两位独立只读子代理（daily-006 起持续合作的资深复核员），按读者面/账本
分离口径逐条核对硬事实与原始页面（字节级锚定）。

| 篇 | 复核链 | 终局 |
|----|--------|------|
| art-001 | r1 needs_changes（3 findings：2 major 未锚定断言 + 1 minor 大纲缺 H2）→ 修复后 r2 增量复核（--base-review 首秀，attempt=2，diff_only） | approve |
| art-002 | r1 approve（0 findings，新管线首轮即过）→ 标题级更换（title_gap 消除）后 r2 增量复核（attempt=2，diff_only，正文哈希逐位一致） | approve |

## 6. 收口状态（分栏）

| 栏 | 状态 | 产物 |
|----|------|------|
| 内容栏 | final_review content_result = PASS，content_status = CONTENT_READY（无 content_blockers） | review/final-review.json、review/content-delivery.json |
| 证据栏 | claim-source 46/0、editorial-protocol pass、L2 两篇 approve（均含 diff-only 增量轮，--base-review 协议生效） | review/gates/*.json |
| 治理栏 | controller_acceptance / human attestation 保持 pending（人签字项，等你验收） | batch.json gate_status |

final review 终局：verdict = PENDING、content_result = PASS、evidence_result = PASS、
governance_result = PENDING（pending 项全部为人工签字/验收项，与 daily-007 验收前
同口径）。`CONTENT_READY` 只表示可交真人复制发布，不等于发布授权；
publication_authorization 全程保持 `not_authorized`，未发布。

## 7. 本轮顺带修掉的工具缺陷（有测试）

1. **账本预检器引号标点容错**：中文引号常把句末标点包进引号内，账本条目按页面
   原文不含该标点——预检器现剥尾部标点再比对，消除纯标点差异误报。
   测试：`tests/test_discovery_scripts.py` 新增 2 例（全量 15 例 passed）。

## 8. 未验证与遗留

- 知乎问题页 403 未捕获，仅作 R0 信号；后续 source 层如需引用知乎讨论内容须
  换可捕获端点或明示；
- d02/d03/d04 的"琼瑶说法/赵薇采访"为自媒体与台媒转述的二手来源，正文已按
  "当年给的说法是/琼瑶把这次大换角称为"口径转述，未写成独立事实；
- 《你行！你上！》票房数据以单一报道（影吹斯汀）为源，与百科口径（累计9196万）
  方向一致但未交叉第二来源；
- art-002 的 CJK 927 贴近下限，源于素材决定篇幅（用户口径：±100 误差，篇幅以
  素材为准）。
