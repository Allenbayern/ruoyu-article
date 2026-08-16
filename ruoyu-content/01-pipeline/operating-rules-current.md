# 若雨随影生产链运行规则（current）

> 本文件是日更生产链 cron（`ruoyu-daily-article-production`）的唯一规则载体：
> cron 每次运行前读取本文件的最新版本；所有 L0 微调（口径、样式、重试策略）
> 直接修改本文件并记入「变更日志」，不修改 cron prompt 本体。
> 结构性改动（新闸门、发布授权变更、代码架构）必须先经 Allen 确认。
>
> 规则基线：`docs/retrospective-013-020.md`（2026-08-16 复盘，M0 产出）
> 契约模板：`ARTICLE_GROUP_OPERATING_CONTRACT_v1_DRAFT.md`、`v2_contract/`

## 0. 硬约束（不可违反）

1. 发布永远手动：`publication_authorization=not_authorized`，止步交付预览，预览 URL 用 `http://192.168.100.168:8765/`（LAN）。
2. 每批目标 2 篇成品；选题失败走「应急单篇」路径（见 §6），不污染正式批次。
3. 每环节重试 ≤1 次；重试仍失败则该环节 fail，记台账，不硬闯。
4. kanban 派发 workspace 必须绝对路径 `dir:/home/allen/Projects/ruoyu-film-daily/runs/<date>/controlled-NNN`；`--skill ruoyu-controlled-production` 仅用于已注册该 skill 的 worker profile。
5. 未修改 `v2_contract/` 与 `article_group/` 核心代码（本文件外的流程规则变更需 Allen 确认）。
6. 成品禁：来源自证、审稿腔、流程标识、自我提醒句、无源断言；档期断言须做撤档史版本核验。

## 1. 批次命名（H4 · run_id 唯一化）

- 格式：`controlled-<序号>`，序号全局递增、不得复用；同日多批用 `-a/-b` 后缀区分。
- 预演/演练批：`controlled-<序号>-dryrun`，绝不与正式批共用序号。
- 应急单篇：`controlled-<序号>-emergency`（见 §6）。
- 目录：`runs/<YYYY-MM-DD>/<batch-id>/`；批次内 `batch.json` 的 `run_id` 与目录名逐字一致。
- 素材同步：选题雷达/candidate 素材落入 `sources/`，并将 `sources/cand-*.md` 同步到 `evidence/`（021 教训：evidence/ 为空则 final_review 证据链观感缺失）。
- 预览 URL：同日多批用 `-a`/`-b` 后缀区分（`ruoyu-art-001-2026-08-16-b.html`，022 教训）；**预览服务一律经 systemd 单元 `ruoyu-preview.service` 管理**（更新 ExecStart 指向最新批次 serve_preview.py 后 `daemon-reload && restart`），禁止手工 nohup 启动（端口抢占已复现 2 次）。
- 禁止：不同日期目录下出现同名批次（`controlled-020` 双目录为历史教训，见复盘 D6）。

## 2. 字数口径（H2 · 统一）

- **官方口径 = style_gate 的 CJK 计数**（`len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", full))`），目标区间 1500–2200 字。
- prose_pilot 输出仅 advisory：不改变任何 gate 状态、不阻断、不参与字数判定；report 中标注与 style_gate 的计数差异（如有）。
- 任务卡、预检、台账中所有字数一律写 style_gate 口径并注明。

## 3. 冻结规范（H3 · 只留最终版）

- 冻结动作只发生在最终稿：`review/frozen/<name>.<sha256前12>.html` + `review/sha256-manifest.txt`。
- 冻结前所有迭代副本移入 `review/work/`（不删、不进 frozen、不计入 manifest）。
- frozen 目录每批最终 ≤3 个文件（2 篇成品 + 可选 bundle）；>3 即视为违规，记台账。
- 冻结副本必须逐字节校验（sha256 重算 MATCH）后才可映射预览。

## 4. prose_pilot 版本管理（H7）

- 批次配置固定文件名 `prose-pilot-batch.yaml`（同批覆盖，不产生 v4/v5/... 后缀）。
- report 内 `revision` 字段记录本次运行序号；覆盖前的旧 report 内容并入 `review/work/`。
- 单批 prose_pilot 运行 ≤3 次；>3 次须记台账说明原因（配置漂移视为缺陷）。

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

- 每批收尾执行：`python -m article_group.final_review --batch runs/<date>/controlled-NNN`
- **收尾链路（L2 教训定）**：冻结后 → 对最终 frozen HTML 重跑 `style_gate.py <frozen.html>` 覆盖落盘 `style-gate-art-00X.json`（draft 有修改就必须重跑，禁用手工复制旧报告）→ 再跑 final_review。evidence 时间戳必须晚于冻结时间戳。
- 验收标准：`PUBLISHABLE` 才允许进入交付预览映射；`BLOCKED` 记台账并回修复环节；`PENDING` 挂人工判定（每周六判定会）。
- 参考基线（2026-08-16 定）：**丢失文件/证据链不完整的批次无参考意义**（001–012 缺 review/、013–018 无 batch.json、020 编号冲突），不作为对照基线；只有证据完整批次（019/020 少量 + 021 起全部新批）参与对照。

### 5.2 M2 修复节奏（每 5 轮一个 checkpoint）

- 021–040 按「跑 5 轮 → 修复 → 再跑 5 轮 → 修复」循环推进，直至 021–040 结束。
- checkpoint 批次：025、030、035、040（含该批自身）收尾后暂停下一轮启动前，执行：
  1. 汇总本 5 轮 final_review 判定分布（PUBLISHABLE/BLOCKED/PENDING 计数）；
  2. 新缺陷（台账/判定回退/成本超限）逐项定级：L0 直接修（落规则文件或代码+测试），结构性改动挂确认；
  3. 修复落定后更新规则文件变更日志，再进入下 5 轮。
- checkpoint 内不发布任何内容；每 5 轮的成本、判定分布记入台账。

## 6. 应急单篇路径（H9 · emergency-single）

- 触发：自动选题当天候选池不足 2 篇可过 portfolio_gate，或预检 fail 且重试后仍不足。
- 流程：批次标记 `-emergency`；单篇照常走 候选→preflight→写作→style_gate→prose_pilot→冻结→预览；台账注明触发原因与候选池实况。
- 应急批不参与「日更 2 篇」达标统计，但计入复核闭环覆盖率（同样要有总复核判定记录）。

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

（后续 L0 微调在此追加，保留历史行，不覆盖。）
