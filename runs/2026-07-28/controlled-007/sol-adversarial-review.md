```yaml
decision: needs_changes
scope_reviewed:
  - review-readiness-packet.md 与 AC1–AC8
  - candidate-pool.json
  - slot-decisions.json
  - slot-contract.json
  - source-manifest.json
  - controlled-run-manifest.json
  - articles/A|B|C/article-draft.md
  - articles/A|B|C/article-plain.txt
  - articles/A|B|C/article-gate.json
  - sources/*.html（重点抽查 A01/A02、B01/B02、C01/C02）
  - controlled-005/controlled-006 manifest 的主核对照
  - 本地 validators 与完整 pytest

findings:
  - id: C7-F01
    severity: major
    target: articles/A/article-draft.md，第27行；article-gate.json 的 claim_coverage=complete
    evidence: >
      正文写“点映开启后，网友留言里反复出现同一类句子：必须和搭子一起去看，
      打工人的发疯图鉴，笑到饮料都拿不稳。”该段未在 A gate 的 A1–A12 中建
      material claim，也没有对应 source_id、source locator 或可审计的样本出处。
      A01 的可核查内容支持官宣、主创与点映时间，但不支持这三类网友留言。
      因而“complete”与实际正文中的外部可验证性主张不一致。
    counterexample_or_failure_mode: >
      读者会将三句并列的具体表达理解为已检索到的真实观众反馈；但现有来源清单
      无法复核其来源、数量或代表性，构成将未留痕社媒样本写成事实性氛围证据。
    required_fix: >
      二选一最小修复：删除/改成不宣称真实留言的纯假设性观众场景；或补入可审计、
      非 AI 的原始公开样本来源，并为该段新增完整 claim mapping（draft_locator、
      source_id、source locator、适当的 attribution/limitation）。
    recheck: >
      重新运行 claim inventory / locator 验证；人工确认 A 的 complete inventory
      覆盖该段，或该段已不再以实际网友留言为事实依据。

  - id: C7-F02
    severity: major
    target: articles/B/article-draft.md，第25、39、43–50行；article-gate.json 的 B12 与 claim_coverage=complete
    evidence: >
      B 文中将“第二周听朋友说动画更好笑，也更想二刷”“评分先稳住，上座率抬头，
      排片再跟着走”“中后段的选票，开始奖励另一种东西”“被安利过两次以上的片子”
      写成对观众行为、口碑传播和排片机制的解释。B12 只登记“它把后半程跑赢了”
      为 inference；B01/B02/B03 能支持两日票房、评分、上座率等点状数据，
      但没有来源支撑上述因果链或“朋友/二刷/安利次数”的具体描述。
    counterexample_or_failure_mode: >
      两日单日反超与一日上座率差异，不能单独推出“口碑→上座率→排片→冠军”的
      连续因果，更不能证明虚构式的观众决策路径；会把合理评论越写成已证实市场机制。
    required_fix: >
      保留“连续两日反超+破7亿”的主核，但将上述机制改为明确的观察/开放问题，
      例如仅称报道同时提到评分、上座率和票房表现，不能据此确认排片或个人推荐的
      因果；删除无来源的“朋友、二刷、安利两次”等具体化行为描写。
      同步把实质保留的推断完整列入 claim inventory，或把 coverage 改为诚实状态。
    recheck: >
      B 的每个保留外部事实、受众行为与因果解释均能逐项映射；重跑 validator 后，
      人工复核不再把相关性叙述成确定机制。

  - id: C7-F03
    severity: major
    target: articles/C/article-draft.md，第21行
    evidence: >
      正文称澎湃写“《争洛阳》……创下追光近年作品最低票房纪录”，但 C gate 仅
      登记 C1–C12，未收录该项“最低票房纪录”主张；source-manifest 中的 C03
      是澎湃来源，却没有任何 C 映射指向 C03。已抽查 C01、C02，二者分别支持撤档、
      8.1、工期、8146.5 万/0.8%及上映日期，不能替代该“近年最低纪录”的来源。
    counterexample_or_failure_mode: >
      “近年最低票房纪录”是对追光作品横向比较的强事实，若不绑定实际 C03 locator，
      无法判断其统计口径、比较范围和原报道是否确有该表述；complete 因此失实。
    required_fix: >
      删除“创下追光近年作品最低票房纪录”，或将其新增为独立、有出处的事实/
      attributed claim，使用 C03 中可匹配的准确 locator，并在正文明确归属澎湃报道。
    recheck: >
      复核 C03 的 `<p>` 正文 locator、draft locator 与新增 mapping；或确认该句已删除，
      再验证 C 的 complete inventory。
      
non_findings:
  - >
    AC1 通过：A/B/C 的 work、event_cluster_id、reader_question 均不同；且 B 是
    “连续两日单日反超+破7亿”，与 controlled-005 A 的“提档上映后的国风动画逆袭”
    不同，未发现同一 lead 的直接复用。
  - >
    AC2 暂通过：8 个 source snapshot 的 SHA-256 均与 source-manifest 一致；本地
    `<p>` 文本扫描未发现“本文由AI生成/人工智能生成/AI生成”，URL 亦无
    synthetic/placeholder 标记。抽查的 A01、B01、C01 均为可定位的媒体页面，
    且能提供核心日期/票房/声明文本。
  - >
    AC3 通过：中文字符数为 A=1824、B=1800、C=1828，均处于 1500–2200 且达到
    首稿目标下限 1800。
  - >
    claim locator 的机械完整性通过：逐项独立检查 A1–A12、B1–B12、C1–C12，
    全部 draft_locator 在各自 md 中存在；所有 fact/attribution 的 source locator
    均在所绑定源 HTML 的 `<p>` 正文中存在。
  - >
    AC5 通过：每篇 article-plain.txt 与 render_plain_text(article-draft.md) 精确相等，
    无残留 Markdown 标记；validate_run_plain_delivery 返回 []。
  - >
    AC6 通过：controlled-run-manifest 仍为 R7 mechanically-verified，
    publication_authorization=not_authorized，未见将机械绿误标为 R8 或发布授权。
  - >
    本地可复现验证通过：validate_batch、validate_run_plain_delivery、
    validate_source_manifest 均返回 []；python3 -m pytest -q 为“182 passed”。

coverage_gaps:
  - >
    未依赖 SearXNG / DailyHotApi 的在线检索结果；按包内要求优先审计本地 HTML，
    因此不把网络可用性或超时当作任何批准依据。
  - >
    本轮没有对每一个外链进行实时重抓，也没有把转载链倒查至票房平台/片方原帖；
    对现有快科技、中华网、华夏时报等二次转载的来源等级，仅作本地快照与文本可核验
    审查。该缺口不影响上述已证实的正文 inventory 缺陷。
```

- 已完成独立 L2 对抗复核：读取全部规定工件、抽查核心源 HTML、运行本地验证与完整测试。
- 结果为 **needs_changes**：三项 major 均是“`claim_coverage=complete` 未诚实覆盖正文中的外部事实/软因果”，可做小范围删改或补证。
- 未修改任何文件；未执行发布、merge 或 push。