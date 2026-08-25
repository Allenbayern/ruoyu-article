# 若雨爆款文章库到 Codex 的迁移

更新时间：2026-08-25

## 结论

Codex 不需要继承 Hermes 的 memory、session 或私有知识库。爆款文章库应迁移为项目内可审计的三层资产：

1. **旧库/蒸馏层**：保留已经进入 Git 的若雨案例原则、培训和注意事项文档，作为历史学习材料。
2. **实证层**：在本机存在时读取 `runs/<run-id>/viral-research/` 下的正文快照、文章卡、指标证据、manifest 和蒸馏候选。
3. **契约层**：沿用 `article_group/case_contract.py` 与 `article_group/case_distill.py` 的资格和蒸馏边界，不另造“爆款”判定。

项目级入口是：

- `.agents/skills/ruoyu-viral-library/SKILL.md`
- `scripts/codex_viral_library_index.py`
- 本说明文件
- 根目录 `AGENTS.md` 的 Codex handoff 段落

## 当前源地图

| 层 | Codex 入口 | 当前状态 | 用途 |
|---|---|---|---|
| 旧库清理版 | `ruoyu-content/10-case-library/爆款案例库_清理版.md` | 已在项目 | 历史案例与原则线索，不等于逐篇表现证据 |
| 旧库兼容副本 | `ruoyu-system/爆款案例库_清理版.md` | 已在项目，和上项逐字重复 | 兼容旧路径，不计为第二批样本 |
| 旧库注意事项/培训 | `ruoyu-content/10-case-library/*.md` | 已在项目 | 历史方法与边界，需服从当前 Vault 规则和代码契约 |
| 微信正文快照 | `runs/2026-08-11/viral-research/raw_articles/` | 本机忽略目录，可能缺失 | 真实全文研究证据 |
| 微信文章卡/指标 | `runs/2026-08-11/viral-research/wechat-viral/` | 本机忽略目录，可能缺失 | qualification、结构观察和表现证据 |
| B 站公开指标包 | `runs/2026-08-11/viral-research/bilibili-public-metrics/` | 本机忽略目录，可能缺失 | 数据通道验证/观察层；标题形态不直接作为若雨正向标题样本 |
| 资格与蒸馏代码 | `article_group/case_contract.py`, `article_group/case_distill.py` | 已在项目 | 机械校验和候选生成 |
| Canonical 治理 | Hermes Knowledge Vault | 项目外只读参考 | 生产规则和治理权威，不自动复制或回写 |

## 如何让 Codex 使用

在项目根目录运行：

```bash
python scripts/codex_viral_library_index.py --project-root .
```

脚本输出稳定 JSON，包含：

- 旧库文件的相对路径、字节数和 SHA-256；
- `ruoyu-content/10-case-library/` 与 `ruoyu-system/` 的重复分组；
- 实证包的 `qualification_status` 计数；
- 每个样本的 card、正文快照和表现证据是否能在本机解析；
- 缺失证据和蒸馏候选的数量；
- 不把 `observed_pending`/`research_only` 当作正向爆款证据的机器可读策略。

Codex 的调用顺序由 `.agents/skills/ruoyu-viral-library/SKILL.md` 固定：先索引，再读卡，再按引用读取少量正文和指标，最后才做跨样本比较。

## 资格边界

- `qualified_viral`：文章级表现证据与预声明平台/时间窗口规则可回查；仍须满足多篇、形态匹配、跨账号/题材等条件，才能支持正向技法候选。
- `observed_pending`：证据不完整，只能观察或补证。
- `research_only`：只有全文/结构或其他不足以判定爆文的材料，只能作结构参考或反例。
- 蒸馏输出仍是候选观察，不会因为频次出现就自动变成 canonical 写作规则。
- 任何新文章的片名、人物、档期、票房和其他当前事实，都必须重新核验权威来源；旧文章正文只能提供结构研究材料。

## 这次没有自动做的事情

1. 没有把 Vault 私有资料、Hermes memory、session、Kanban、`.env`、cookie、token 或认证文件复制到项目。
2. 没有把 `runs/` 中的原文和客户端指标强行加入 Git。它们目前是本机忽略的研究证据，跨机器迁移需要单独确定范围、来源授权、体积和恢复点。
3. 没有把单篇案例或历史“清理版”文档升级为当前生产规则。
4. 没有写回 Vault、发布文章、合并、部署或推进任何状态。

## 若要跨机器完整迁移

应另开一个明确范围的迁移任务，先生成证据 manifest 和 SHA-256，再选择以下一种承载方式：

- 将经过筛选的 `clean.md`、文章卡、performance evidence 和 manifest 作为受控项目资产提交；或
- 保留正文/指标在独立只读归档，项目只提交不含正文的索引和哈希。

不得把整个 `runs/` 目录无差别加入仓库，也不得用旧库摘要代替真实全文或文章级表现证据。完成跨机器迁移的验收条件是：每个被声明为 `qualified_viral` 的样本都能解析 card、正文快照、表现证据和哈希；缺失项必须明确显示为 `unavailable`。

## 证据声明

本文件和索引描述的是“Codex 能否找到并正确分层使用库”，不是“所有爆款正文已经迁移完成”。当前项目承载层已建立；本机之外的完整正文证据迁移仍是未完成事项。

## Package contract：crawler capture manifest → package → prepare allow-list → 显式 Codex pass → finalize review packet

这条链路把“抓到材料”“可供语义研究”“候选观察”和“生产/发布授权”严格分开。每一阶段只消费上游的可追溯产物；路径、哈希、身份或修订不一致时 fail-closed，不用口头状态或历史文件补齐证据。

### 1. Crawler capture manifest

- crawler 在 `runs/<run-id>/viral-research/` 内写入 capture manifest，并为每个样本记录 `platform`、`account_id`、`canonical_url`、`published_at`、`capture_status`、`shape` 以及 `raw_ref`、`clean_ref`、`metadata_ref`。capture manifest 是抓取事实和发现层输入，不是 `qualified_viral` 的授权。
- 引用先保持为 run root 内的相对路径；进入 package 后必须规范化为 `relative/path#sha256=<64 位小写十六进制>`。绝对路径、路径穿越、越过 run root 的符号链接、缺失文件和哈希不匹配都必须拒绝。
- `sample_id` 是稳定的逻辑身份：由规范化的 `platform + account_id + canonical_url + published_at` 计算得到。相同身份不得重复计数；同一身份的重新抓取只有在显式提供 `revision` 时才可作为新的不可变观测。

### 2. Immutable package

- package 固定落在 `runs/<run-id>/viral-research/package/`，至少包含 `manifest.json`、`samples.jsonl`、`exclusions.jsonl` 和 `integrity.json`。`exclusions_ref` 必须是指向包内排除清单的带 SHA-256 引用；`integrity.json` 封存三份核心文件的摘要。package 只登记引用、身份、状态和排除原因，不把正文复制进新的 package。
- package 建立后不得覆盖；缺失/部分抓取、非影视内容、重复身份、路径错误和哈希错误进入 exclusions 或阻断状态。只有 manifest 通过校验并达到 `evidence_checked`，才可以进入 prepare；`observed_pending`、`research_only` 和 `blocked` 不得被改名为合格样本。
- 客户端表现证据必须先脱敏再挂载：证据文件需标记 `sanitized: true`，保留可核查的 `evidence_ref#sha256=`、`original_display`、Asia/Shanghai `observed_at`、`confirmer` 和文件哈希；不得包含 token、cookie、session、authorization、密码、API key 或其他凭证值。脱敏失败即拒绝，不能把客户端原始页面、登录态或截图凭证交给 Codex。
- 新的客户端证据写入 `revisions/<revision-id>/`，并在 `revision.json` 记录 `base_package_manifest_sha256`、样本身份和派生状态；不得回写或覆盖原 package。revision 仍是证据修订，不是自动晋级。

### 3. Prepare allow-list

- `prepare` 读取已校验的 package 和明确的 shape criteria，输出 `runs/<run-id>/viral-research/distillation/prepare.json`。它必须选择至少 `5` 个 `qualified_viral` 样本，并且来自至少 `2` 个不同账号；样本还必须形态匹配，不能用重复账号、`observed_pending` 或 `research_only` 凑数。
- prepare 文件是唯一的语义读取清单：逐项列出 `selected_sample_ids`、`account_id`、`card_ref`、带哈希的 `snapshot_ref` 和 `performance_evidence_ref`，并绑定 package manifest/integrity 摘要，声明 `semantic_pass.mode=explicit_codex_trigger_required`。semantic pass 还必须写 `cards/manifest.json`，绑定 prepare/package 摘要和每张 card 的 SHA-256；allow-list 之外的文件、目录、Vault、Hermes 私有状态和未列出的外部页面不属于 pass 输入。
- prepare 失败、样本数不足、账号数不足或任一引用无法解析时，不生成可供 Codex 使用的清单；不得用扩大读取范围的方式绕过门槛。

### 4. Explicit Codex pass

- prepare 不会隐式调用 Codex。必须由 controller/用户显式触发一次只读 pass，并把 prepare 的 allow-list 原样作为读取边界；Codex 只能读取列出的快照、性能证据和 card 引用，输出逐样本的语义观察卡。
- 每张 card 必须保留 `sample_id`、`account_id`、`snapshot_ref` 和 `performance_evidence_ref`，且与 prepare 逐字匹配；不能在 pass 中改写资格、补造当前事实、把标题/摘要/热榜信号当表现证据，或把单一账号的观察推广为规则。
- Codex pass、其日志和结果都是 evidence-only。pass 成功不等于资格晋级、规则采纳、冻结、发布、合并、部署或任何工作流状态推进。
- controller 应把 pass 的当前目录设为本批次 `runs/<run-id>` 隔离目录，并使用 `--skip-git-repo-check`；项目根、Vault、认证目录和其它批次目录不得作为 pass 的可写工作区。`--sandbox workspace-write` 是进程级写入边界，不能替代 controller 在容器/操作系统层提供的目录可见性隔离。

### 5. Finalize review packet

- `finalize` 只接受 `ready_for_distill=true` 的 prepare 文件和每个 selected sample 的可校验 card；它再次检查身份、路径/哈希引用、客户端证据和 case contract，并在写出前校验 review-report schema，然后写入不可覆盖的 `runs/<run-id>/viral-research/review/viral-distill-review.json`。
- 只有得到至少 `2` 个 `qualified_viral` 样本、且至少来自 `2` 个不同账号的同形态支持，候选技法才可进入 `positive_candidates`；其余内容必须留在 `excluded_observations`、`negative_patterns` 或 `coverage_gaps`，不能借频次升级。
- review packet 必须明确写出 `promotion_status: provisional_only` 和 `automatic_publication_authority: false`。本地 `integrity.json` 和跨阶段摘要用于发现意外改写；它们不是外部不可伪造锚点，生产 controller 仍需把最终 manifest 摘要写入独立 append-only receipt。review packet 是带路径、哈希、身份、修订和缺口的审查证据包，不是 canonical 规则、发布包或授权单。

### 不自动发生的动作

这条 package contract 不自动写 Vault，不自动发布文章，不自动合并、部署或推进任何状态，也不把 `provisional_only` 变成 canonical 规则。任何写回、采纳、资格晋级、发布或状态变更，都必须由 controller/Allen 在独立的人工授权流程中决定，并保留相应证据。
