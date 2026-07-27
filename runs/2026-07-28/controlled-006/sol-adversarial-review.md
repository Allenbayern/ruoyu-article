# controlled-006 独立对抗式内容复核（仅本地证据）

- review_scope: 原始任务、A/B/C 的 article-draft.md、article-plain.txt、article-gate.json、evidence-pack.json、writing-brief.json、source-manifest.json、controlled-run-manifest.json、candidate-pool.json、slot-decisions.json 及全部已抓取 HTML。
- verification_method: 仅抽取各 HTML 的 `<p>` 正文并逐项匹配 `claim_mappings.locator`；未访问网络。
- decision: **needs_changes**
- publication: **未授权；本复核不构成发布批准。**

## 批次结论

机械条件基本通过：A/B/C 中文字数（含标题）分别为 1577 / 1614 / 1810，均在 1500–2200；标题分别 20 / 21 / 16 汉字；A/B/C 的 `work`、`primary_atom`、`reader_intent`、`angle` 字段互不重复；`controlled-run-manifest.json` 明示 `publication_authorization: not_authorized`。全部 27 个已登记 locator 都能在相应本地 HTML 的 `<p>` 文本中命中，且文件 SHA-256 与 manifest 一致。

但上述 locator 通过不等于证据包足以支撑“R8 review-ready”。A、B、C 三篇均把有限映射标成 `claim_coverage: complete`，实际正文含有大量未映射的硬事实或把单一报道的判断扩展为因果结论。C 还把来源不明、无原始数据/声明链接的聚合式文章 `src-C01` 作为唯一 `confirmed-primary`，不能承载文章的核心市场结论。以下 blocker 会阻止 R8 接受。

## A

### findings

- id: A-B01
  severity: blocker
  target: `articles/A/article-gate.json` 的 `claim_coverage: complete`，及 `article-draft.md` 的对应正文
  evidence: 已登记 A1–A9 只有 9 条，未覆盖正文中的具体可核事实，包括“7月25日公映”“章笛沙执导”“原定路演和线下活动全部取消、退票妥善处理”“2035年三名航天员返航失联”“跨越65年”“《三国》耗时三年、近千人团队、追光近年最低票房纪录”等。虽然这些大多可在 `src-A01`/`src-A02` 的 `<p>` 找到，却未进入 mappings。
  required_fix: 要么为所有保留的硬事实新增逐条、短且可命中的 source_id/locator 映射；要么删改未映射硬事实，并把 coverage 改为能如实说明剩余覆盖范围的状态。重新运行本地 `<p>` locator 校验。

- id: A-M01
  severity: major
  target: `article-draft.md` 中“市场只看你能不能抢到排片”“因为分数解决不了首周末的排片争夺”“撤档是连‘看完’的机会都先收走”
  evidence: `src-A01` 是撤档声明转载；`src-A02` 仅称《功夫女足》《八仙！》火爆“给不少影片带来压力”。二者均未证明《群星》的撤档由排片、首周末上座或市场“只看”某一指标造成。
  required_fix: 将其明确降为作者感受/可能性（如“从这次撤档可看见档期压力的风险，不能据此断定唯一原因”），或补入本地可核的排片、上座、片方归因原始证据并逐条映射。

- id: A-M02
  severity: major
  target: 标题及开头“撑不过两天”与正文“上映不到两天”
  evidence: `src-A02` 的 `<p>` 是“7月26日深夜……上映仅1天就宣布撤档”，`src-A01` 是“7月25日上映，截至7月26日票房”。标题的“两天”不与文中“仅1天”一致，容易把“跨两个日期”表述为完整时长。
  required_fix: 统一为来源原文“上映仅1天/上映后次日宣布撤档”，避免“两天”这一不精确的硬时长。

## B

### findings

- id: B-B01
  severity: blocker
  target: `articles/B/article-gate.json` 的 `claim_coverage: complete`，及 `article-draft.md` 的对应正文
  evidence: B1–B9 仅映射 9 个锚点；正文另有大量未映射硬事实，如“《长安三万里》原班人马、耗时三年、近千人团队、追光近年最低票房纪录”“黄建新监制”“取消全部路演及线下活动”“董润年执导、完整演员阵容”等。单一 `src-B01` 虽含其中一部分，gate 并未逐条映射。
  required_fix: 按实际保留的硬事实补齐 mappings 并重跑本地正文 locator 校验；无法映射者删除或改为非事实性评论。若不做全覆盖，必须诚实标 `partial` 并列出未覆盖范围，不能保持 R8 的 complete 声称。

- id: B-M01
  severity: major
  target: “同一天夜里”“几乎同时”“有人连夜撤档”“有人火速提档”
  evidence: `src-B01` `<p>` 只给出《年会不能停2》“于7月26日宣布提档至8月1日”；没有宣布的具体时刻，也没有“连夜/火速”的事实证据。它还表明《三国》为 7月25日撤档，故标题/引言将不同日期的事件压缩为“同一天夜里”。
  required_fix: 改为准确日期叙述（7月25日《三国》撤档、7月26日《群星》撤档及《年会2》宣布提档），删除无来源的时间速度修辞，或提供本地原始时间戳证据。

- id: B-M02
  severity: major
  target: “谁判断自己还能从现有排片里挤出血，谁就留下或冲刺；谁判断自己会成为炮灰，谁就先撤”及“提档到8月1日，不是浪漫，是计算”
  evidence: 唯一来源 `src-B01` 记录档期变动，未载片方的排片判断、止损阈值或提档动机。文章把观察到的结果写成了各片方的决策动机和统一机制。
  required_fix: 改为带不确定性的作者评论，不将其归因给片方；若保留事实归因，须补本地片方声明或可核采访证据并映射。

## C

### findings

- id: C-B01
  severity: blocker
  target: `src-C01` 被列作唯一 `confirmed-primary`，以及由其承担的文章核心事实/结论
  evidence: `source-manifest.json` 中 C 只有 `src-C01`；其 `<p>` 正文是无引文、无数据来源链接、无具名采访的聚合性写法，例如“至少六部”“超过50%的排片空间”“快手用户三派”“多位业内人士”“成功案例说明”。页面作者仅标为“荧幕风物集”，正文未提供可供本地追溯的原始票房、排片、平台评论或片方声明。该来源不是显式 AI 标注，但在本地证据范围内无法核实其关键数据及归因，不能作为 confirmed-primary 支撑“市场结构出了系统性问题”等核心结论。
  required_fix: 用已抓取且可追溯的原始片方公告、票房/排片数据源、具名报道替换或交叉验证 C 的核心事实；更新 manifest/evidence pack/mappings。不能补足前，C 应降为 evidence_insufficient，不能 R8。

- id: C-B02
  severity: blocker
  target: `articles/C/article-gate.json` 的 `claim_coverage: complete`
  evidence: C1–C9 只覆盖 9 项；正文额外断言“7月25日公映、7月26日深夜官宣”“黄建新监制、黄渤吴磊主演”“追光动画出品”“8145万元”“6月30日撤档”“快手话题下三派情绪”“从立项到上映少则两三年、多则四五年”等，均无对应 mappings。且已登记的 C1–C9 都依赖 C-B01 所述的单一不可追溯来源。
  required_fix: 先解决 C-B01；随后对全部保留硬事实补齐独立、可定位的映射。否则把 coverage 改为 partial 并删除/降格未证实事实，但仍不得把 C01 单独视为 confirmed-primary。

- id: C-M01
  severity: major
  target: 标题、导语及多处定性：“电影市场的集体出逃”“不是因为它不好看，是因为影院里已经没有它的位置”“它们不是败给了观众，是败给了排片”“市场结构出了系统性问题”
  evidence: `src-C01` 本身也仅提供概括性“排片空间不足/头部占据超过50%”和用户观点，不能证明每部影片的撤档原因、排除内容质量或营销等因素，更不能证明系统性市场因果。正文将报道/用户意见改写为确定判断。
  required_fix: 改为清楚标示为作者观点，并在结论中保留多因素不确定性；或补齐跨来源的排片、票房、片方归因证据。标题也应避免把“集体出逃”写成已被事实证实的产业结论。

## 非发现（已通过的攻击面）

- 27/27 个登记 locator 在相应 sources HTML 的 `<p>` 文本命中：A 9/9、B 9/9、C 9/9。
- 五份本地源文件均存在；manifest 登记的 SHA-256 均与文件一致。
- 未在 source manifest 中发现 `ai_generated` 字段或其他明确“AI 生成”标记；因此没有把“显式 AI 源”作为事实提出。C 的 blocker 是来源链在本地产物内不可追溯，而非臆断其由 AI 生成。
- 未发现 HTML 交付或发布授权：manifest 中为 `html_delivery_state: not_requested`、`publication_authorization: not_authorized`，符合非目标与权限边界。

## 复核所需证据

1. 每篇更新后的 gate：事实—source—短 locator 的全量映射，及按 `<p>` 解析复跑的成功结果。
2. C 至少两条可本地追溯的独立原始/具名来源，覆盖“六部撤档”、排片份额、票房/排片数值和片方归因；不能以无来源聚合文章单独充当 confirmed-primary。
3. A/B/C 对所有市场机制、因果与动机的降格或新增证据后的逐段对照。

**结论：needs_changes。A-B01、B-B01、C-B01、C-B02 均为 blocker，任一未修复即阻止 R8 接受；不授予任何发布授权。**
