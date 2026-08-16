# 若雨随影生产链运行规则（current）

> 本文件是日更生产链 cron（`ruoyu-daily-article-production`）的唯一规则载体：
> cron 每次运行前读取本文件的最新版本；所有 L0 微调（口径、样式、重试策略）
> 直接修改本文件并记入「变更日志」，不修改 cron prompt 本体。
> 结构性改动（新闸门、发布授权变更、代码架构）必须先经 Allen 确认。
>
> 规则基线：`docs/retrospective-013-020.md`（2026-08-16 复盘，M0 产出）
> 契约模板：`ARTICLE_GROUP_OPERATING_CONTRACT_v1_DRAFT.md`、`v2_contract/`
>
> **语义分级（2026-08-16 定，所有条目必须标注，后续新增同规则）：**
> - 🔴 **[MUST] 限制**——红线/闸门，违反即 BLOCKED，不可绕过
> - 🟡 **[SHOULD] 流程**——确定性要求，可审计，违规记台账
> - 🟢 **[MAY] 经验**——参考技法，不阻断不强制；发布回填按实证升级/降级
> - 候选观察一律 🟢 起步，验证后可升 🟡；不得以 research_only 证据写 MUST

## 0. 硬约束（不可违反）

1. 🔴 [MUST] 发布永远手动：`publication_authorization=not_authorized`，止步交付预览，预览 URL 用 `http://192.168.100.168:8765/`（LAN）。
2. 🟡 [SHOULD] 每批目标 2 篇成品；选题失败走「应急单篇」路径（见 §6），不污染正式批次。
3. 🟡 [SHOULD] 每环节重试 ≤1 次；重试仍失败则该环节 fail，记台账，不硬闯。
4. 🟡 [SHOULD] kanban 派发 workspace 必须绝对路径 `dir:/home/allen/Projects/ruoyu-film-daily/runs/<date>/controlled-NNN`；`--skill ruoyu-controlled-production` 仅用于已注册该 skill 的 worker profile。
5. 🔴 [MUST] 未修改 `v2_contract/` 与 `article_group/` 核心代码（本文件外的流程规则变更需 Allen 确认）。
6. 🔴 [MUST] 成品禁：来源自证、审稿腔、流程标识、自我提醒句、无源断言；档期断言须做撤档史版本核验。

## 1. 批次命名（H4 · run_id 唯一化）

- 🟡 [SHOULD] 格式：`controlled-<序号>`，序号全局递增、不得复用；同日多批用 `-a/-b` 后缀区分。
- 🟡 [SHOULD] 预演/演练批：`controlled-<序号>-dryrun`，绝不与正式批共用序号。
- 🟡 [SHOULD] 应急单篇：`controlled-<序号>-emergency`（见 §6）。
- 🔴 [MUST] 目录：`runs/<YYYY-MM-DD>/<batch-id>/`；批次内 `batch.json` 的 `run_id` 与目录名逐字一致。
- 🟡 [SHOULD] 素材同步：选题雷达/candidate 素材落入 `sources/`，并将 `sources/cand-*.md` 同步到 `evidence/`（021 教训：evidence/ 为空则 final_review 证据链观感缺失）。
- 🟡 [SHOULD] 预览 URL：同日多批用 `-a`/`-b` 后缀区分（`ruoyu-art-001-2026-08-16-b.html`，022 教训）；**预览服务一律经 systemd 单元 `ruoyu-preview.service` 管理**（更新 ExecStart 指向 serve_preview.py 后 `daemon-reload && restart`），禁止手工 nohup 启动（端口抢占已复现 2 次）。
- 🔴 [MUST] **预览单元指向「全量映射控制面」**（026 教训升级 025 条目）：单元 ExecStart 必须指向**包含最近全部批次 + 单篇映射的全量 serve_preview.py**（当前 = `niulai-guo-shen/serve_preview.py`），不是「最新批次」自己的脚本——「指向当批」会让后续批次 / 单篇 / 历史批次 URL 404（025 批改指 controlled-025 后实测单篇/020/024 全 404）。映射变更后必须 **curl 全量回归**（本批 7 条 URL 全 200 才收口）；serve_preview.py 行内路径必须带日期段（`ROOT/"2026-08-16"/"<batch>"/"review"/"frozen"/…`，漏日期段即 404）。
- 🔴 [MUST] 禁止：不同日期目录下出现同名批次（`controlled-020` 双目录为历史教训，见复盘 D6）。

## 2. 字数口径（H2 · 统一）

- 🟡 [SHOULD] **官方口径 = style_gate 的 CJK 计数**（`len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", full))`），目标区间 1500–2200 字。
- 🟢 [MAY] prose_pilot 输出仅 advisory：不改变任何 gate 状态、不阻断、不参与字数判定；report 中标注与 style_gate 的计数差异（如有）。
- 🟡 [SHOULD] 任务卡、预检、台账中所有字数一律写 style_gate 口径并注明。

## 3. 冻结规范（H3 · 只留最终版）

- 🔴 [MUST] 冻结动作只发生在最终稿：`review/frozen/<name>.<sha256前12>.html` + `review/sha256-manifest.txt`。
- 🟡 [SHOULD] 冻结前所有迭代副本移入 `review/work/`（不删、不进 frozen、不计入 manifest）。
- 🟡 [SHOULD] frozen 目录每批最终 ≤3 个文件（2 篇成品 + 可选 bundle）；>3 即视为违规，记台账。
- 🔴 [MUST] 冻结副本必须逐字节校验（sha256 重算 MATCH）后才可映射预览。

## 4. prose_pilot 版本管理（H7）

- 🟡 [SHOULD] 批次配置固定文件名 `prose-pilot-batch.yaml`（同批覆盖，不产生 v4/v5/... 后缀）。
- 🟡 [SHOULD] report 内 `revision` 字段记录本次运行序号；覆盖前的旧 report 内容并入 `review/work/`。
- 🟡 [SHOULD] 单批 prose_pilot 运行 ≤3 次；>3 次须记台账说明原因（配置漂移视为缺陷）。

## 5. 机器闸门（随代码演进）

| 闸门 | 性质 | 说明 |
|---|---|---|
| portfolio_gate | 阻断 | 候选池跨批去重；跨批指纹盲区（016–019 命名不入 collect_history）挂 Kanban 评估（H6） |
| run_preflight | 阻断 | 任务卡/候选池一致性；R5→R6 流转合法 |
| style_gate | 阻断(error)/警告 | 格式+红线；已含来源自证变体（B3）、无源断言（B4）、中文数字锚点（A4）——2026-08-16 扩展 |
| prose_pilot | advisory | 材料清单+判断词密度，只提示 |
| editorial_review 四阶段 | 记录 | 立项前/写作前/成稿后/发布前 人工+机械 attestation |
| **final_review 总复核** | **阻断** | 批次验收最后一环：单命令汇总全部闸门证据 → PUBLISHABLE/BLOCKED/PENDING；证据链缺失即 BLOCKED；PENDING 项转人工判定；发布不变量恒检查 |

### 5.1 批次验收（M2 起每批必跑）

- 🔴 [MUST] 每批收尾执行：`python -m article_group.final_review --batch runs/<date>/controlled-NNN`
- 🔴 [MUST] **收尾链路（L2 教训定）**：冻结后 → 对最终 frozen HTML 重跑 `style_gate.py <frozen.html>` 覆盖落盘 `style-gate-art-00X.json`（draft 有修改就必须重跑，禁用手工复制旧报告）→ 再跑 final_review。evidence 时间戳必须晚于冻结时间戳。
- 🔴 [MUST] 验收标准：`PUBLISHABLE` 才允许进入交付预览映射；`BLOCKED` 记台账并回修复环节；`PENDING` 挂人工判定（每周六判定会）。
- 🟢 [MAY] 参考基线（2026-08-16 定）：**丢失文件/证据链不完整的批次无参考意义**（001–012 缺 review/、013–018 无 batch.json、020 编号冲突），不作为对照基线；只有证据完整批次（019/020 少量 + 021 起全部新批）参与对照。

### 5.2 M2 修复节奏（每 5 轮一个 checkpoint）

- 🟡 [SHOULD] 021–040 按「跑 5 轮 → 修复 → 再跑 5 轮 → 修复」循环推进，直至 021–040 结束。
- 🟡 [SHOULD] checkpoint 批次：025、030、035、040（含该批自身）收尾后暂停下一轮启动前，执行：
  1. 汇总本 5 轮 final_review 判定分布（PUBLISHABLE/BLOCKED/PENDING 计数）；
  2. 新缺陷（台账/判定回退/成本超限）逐项定级：L0 直接修（落规则文件或代码+测试），结构性改动挂确认；
  3. 修复落定后更新规则文件变更日志，再进入下 5 轮。
- 🟡 [SHOULD] checkpoint 内不发布任何内容；每 5 轮的成本、判定分布记入台账。

## 6. 应急单篇路径（H9 · emergency-single）

- 🟡 [SHOULD] 触发：自动选题当天候选池不足 2 篇可过 portfolio_gate，或预检 fail 且重试后仍不足。
- 🟡 [SHOULD] 流程：批次标记 `-emergency`；单篇照常走 候选→preflight→写作→style_gate→prose_pilot→冻结→预览；台账注明触发原因与候选池实况。
- 🟡 [SHOULD] 应急批不参与「日更 2 篇」达标统计，但计入复核闭环覆盖率（同样要有总复核判定记录）。

## 7. 变更日志

| 日期 | 变更 | 级别 | 依据 |
|---|---|---|---|
| 2026-08-16 | 本文件建立：批次命名/字数口径/冻结/prose_pilot/应急单篇 规则 | 流程 | 复盘 M0 + grill 计划 M1 |
| 2026-08-16 | style_gate 扩展：来源自证变体（B3）、无源断言警告（B4）、中文数字锚点（A4） | L0 代码 | 复盘 H1/H5，测试 523 全绿 |
| 2026-08-16 | final_review 总复核层 v1（H8，Allen 确认设计后开发）：§5.1 批次验收 | 代码 | 测试 533 全绿；回放 013–020 复现全部已知缺陷 |
| 2026-08-16 | M2 节奏：§5.2 每 5 轮一个 checkpoint（025/030/035/040）；丢失文件批次无参考意义 | 流程 | Allen 指示（5 轮一修循环） |
| 2026-08-16 | 021 教训：① cron 禁止中途收尾（收尾纪律已入 cron prompt）；② evidence/ 素材同步约定（见 §1）；③ 预览服务 systemd 单元（ruoyu-preview.service）指最新批次 serve_preview.py | 流程 | 021 批实际截断 + 服务占用 8765 |
| 2026-08-16 | 022 教训：① 预览 URL 同日多批 `-a/-b` 后缀（§1）；② 预览服务统一 systemd 管理、禁手工 nohup（§1，端口抢占 2 次）；③ daily-run-report.md 为当日双批汇总结构 | 流程 | 022 批端口抢占复现 + 021 报告被覆盖 |
| 2026-08-16 | 023 教训：① §1 命名约定执行不彻底——cron 侧 HTML 文件名再次无后缀（与 021 撞名），预览映射统一用 `-a/-b/-c` URL + frozen hash 名兜底；② 闸门命令必须 `.venv/bin/python`（系统 python3 缺 jsonschema 等依赖）；③ portfolio_gate 自动窗口仅到 016（H6 盲区），批次内手工补查 017 起 | 流程 | 023 撞名实测 + 依赖报错 + 盲区复现 |
|| 2026-08-16 | 024 教训：① 预览服务 systemd 单元缺失（021 规则落地后未持久化安装，8765 被手工进程占用）——本批安装 `/etc/systemd/system/ruoyu-preview.service`（enable），每批映射前先校验单元存在；② frozen 命名统一 `ruoyu-art-<NN>.<sha12>.html`（本批误生成 `ruoyu-art-art-001`，改名后必须重建 manifest 并重校验）；③ preflight 输入字段须逐字同源：batch.json `why_today` == candidate-pool `why_now`，任务卡 Primary Atom/Reader Intent/站队点 == batch.json 同名字段，生成本批即注入同一字符串 | 流程 | 024 批实测：单元缺失 + 命名失误 + 首轮 preflight FAIL |
| 2026-08-16 | L2 复核教训（首次 Gate，021–024 四批 8 篇）：① **style_gate/frozen 一致性铁律**——style-gate JSON 必须对**最终 frozen HTML** 重跑生成并覆盖落盘（021-art-002 曾锁定修复前旧版 1872 字/fact=warning、022 锁定清除自证前版本，均与最终稿不一致）；draft 修改后禁用手工复制旧报告。② 每批冻结后补一步：`style_gate.py <frozen.html>` 重跑并覆盖 `style-gate-art-00X.json`，再做 final_review（已在 §5.1 收尾链补入）。③ L2 独立复核子代理限时 420s 内读 8 篇全文易超时——拆 2 篇/代理或抽样核验。 | 流程+L2 实证 | 2026-08-16 L2 Gate：2 major findings + 1 minor，修复后 4 批复跑 PUBLISHABLE |
| 2026-08-16 | 025 教训（date:release-claim 误报链）：① 正则 `(定档\|上映\|公映\|开画)+日期` 会把「重映名单列举」（1月30日《闪灵》…上映46年）和「票房口径句」误判为档期断言——**措辞规避首选「首映/放映/重映名单」词族**（不在正则词表、语义等价）；② 档期断言修复只改措辞不动数字；③ 系统级 `ruoyu-preview.service` 单元曾指向遗留目录 `niulai-guo-shen`——每批映射前 `systemctl cat` 校验 ExecStart 指向当批 | 流程 | 025 批 warning 3 处 → L0 拆分清零；单元指向旧批次 |
| 2026-08-16 | 爆文视角复核候选观察（021–025 十篇，research_only 待发布数据验证，见 `docs/reviews/viral-lens-021-025.md`）：① 标题=情绪反转+具体画面（4 篇 A+ 标题模式：极端数字/情绪词/悬念问句）；② 首屏 150 字第二句前给出信息差；③ 人物主动性叙事 > 被动被讨论（王祖贤/王传君范式）；④ 金句须可独立转述（社交货币）；⑤ **数据源决定型题材（如「票房破30亿」）是传播盲区——单批唯一低爆款潜力篇，此类选题标题须挂具体影片/人物**；⑥ 中段每 3-4 段需场景/人物/金句呼吸点（2000+ 字易掉读）；⑦ 结尾可留互动问句提评论率。026 起执行候选建议，发布回填后按爆文实证标准升级/降级 | 流程（候选观察） | docs/reviews/viral-lens-021-025.md 十篇通读评估 |
|| 2026-08-16 | 026 单篇教训（niulai-guo-shen，牛来过审悬案）：① **预览单元指向全量映射控制面**（升级 025「指向当批」条目——本批实测 025 批改指 controlled-025 后单篇/020/024 全部 404；正确姿势：单元指向含最近全部批次 + 单篇映射的 niulai-guo-shen/serve_preview.py，映射后 curl 全量回归 7/7 200 收口，已入 §1 MUST）；② serve_preview.py 行内路径必须含日期段 `ROOT/"2026-08-16"/"<batch>"/…`（ROOT=runs/ 时漏日期段即 404，本批复现定位）；③ **票房口径时效**：素材采集口径（8/16 上午单日225万/累计330万）舆论发酵数小时即过时，发布前须重拉最新（同日 16:30 已 419万/492.8万、微博热搜 8 条），正文锚定时点写「截至X时X分」不写模糊「上午」；④ 交付前检查 `<div class="sources">` 可点击一手链接区存在（Allen 08-15 要求，本批初稿缺失、L2 复核补上）；⑤ 人物引语只放逐字原文，改写/转述内容移出引号（本批周圣崴段原为改写混引，L2 修复） | 流程 | 026 单篇交付实测：404 根因 + 口径过时 + sources 缺失 + 引语边界 |
| 2026-08-16 | 爆文视角复核候选观察（026 两篇，research_only 待发布数据验证，见 `docs/reviews/viral-lens-026.md`）：① 数据型选题挂载人物/影片后潜力回升**双例同向**（022 裸数据=低 → 026 花开锦绣挂剧+角色+反差问=中 → 026 龙餐馆全程挂人物+制作故事=中高，三级递进）；② **候选观察⑦（结尾互动问句）连续两批空转**（021-025 十篇未执行 + 026 两篇未执行）——仅入规则日志不足驱动执行，须把⑦纳入 style_gate/final_review 机械检查点或任务卡写作要求；③ 情绪密度与人物锚「人物原话优先」原则得第 2-3 批次同向证据（龙餐馆有沈腾原话=中高 vs 花开锦绣纯设定拆解=中）；④ 标题问句若正文全收束则张力平（花开锦绣问「口碑为何两极」→ 结尾完全解答无留白，可留 2-3 成悬念或反抛读者侧问题）；⑤ 026 两篇首屏信息差/标题反转/数据挂载全部落地，022 裸数据盲区未重现 | 流程（候选观察） | docs/reviews/viral-lens-026.md 两篇 frozen 版通读评估 |
| 2026-08-16 | **cross_batch 去重盲区修复**（026 final_review BLOCKED 实证 + Allen 确认 A 方案）：① `collect_history` 只收 `ruoyu-articles-*.html`（016 及以前整批合并命名），021 起 frozen 为 `ruoyu-art-00*.html` 单篇 → **021+ 整段漏窗、跨批去重从未生效**（H6 盲区机器侧根源）；修复为优先根目录交付副本、否则聚合 review/frozen 下 `ruoyu-articles-*.html`+`ruoyu-art-00*.html` 全部指纹。② h2 标题反衬句式（「撞上了空降的《欢迎来龙餐馆》」）被 `_extract_titles` 误当专文作品 → 新增 `_split_title_segments` 按反衬连接词（撞上/碰上/空降/同期/对比/让位等）切段，反衬段整体排除，仅主语段作品计入 works。③ final_review 新增控制器豁免注记通道 `_match_adjudication_waiver`：portfolio-gate-report.json 的 `controller_adjudication`（adjudicated=True + 含 confirmed_new_angle/确认豁免 + candidate 匹配）命中时 error 降级为已裁决记录放行（result.adjudicated_waivers）——**人机一致：机器尊重已落盘的控制器裁决，未裁决重复仍 BLOCKED**。④ 教训：批次命名契约变更（整批合并包→单篇 frozen）必须同步审计所有按文件名收集历史的消费者；跨批指纹的 works 必须是「专文主角」不是「标题提及」。测试 535 全绿（含新增用例），026 重跑 PUBLISHABLE，窗口 10 批覆盖 021–025 实证。 | 代码修复 | 026 BLOCKED → 修复后 PUBLISHABLE；窗口 [025..015] 10 批含 021–025 |
| 2026-08-16 | **候选观察⑦落地为机械检查点**（L0 代码）：① `style_gate.closing_interaction_check`——文章末段（不含 .sources）读者互动问句检测（「你会…吗/你还会…吗/大家…？」= ok；结论性收尾 = info 建议不阻断；设问/内容性问号不误判为互动）；② writing-brief 新增 `ending_interaction_question` 字段（任务卡模板要求写明「读者互动问句 | 结论性收尾（写明理由）」）；③ style_gate 每次运行自动产出 `closing_interaction` 单篇字段，final_review 汇总可见 | L0 代码 | 026 复核⑦空转实证 → Allen 确认落地（测试 20 passed） |

（后续 L0 微调在此追加，保留历史行，不覆盖。）
