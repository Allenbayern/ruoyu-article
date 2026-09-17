# 若雨爆款文章库到 Codex 的迁移

更新时间：2026-08-25（2026-09-17 追加「包通道」一节；其余内容与判断未变）

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
| **批次包（新）** | `runs/<run-id>/viral-research/package/` | 由生产端产出，本机忽略目录 | 规范化、逐文件 SHA-256 锚定的证据包；见下节 |
| 资格与蒸馏代码 | `article_group/case_contract.py`, `article_group/case_distill.py` | 已在项目 | 机械校验和候选生成 |
| Canonical 治理 | Hermes Knowledge Vault | 项目外只读参考 | 生产规则和治理权威，不自动复制或回写 |

## 包通道：`viral-research-package-v1`（2026-09-17 接入）

上面表格前三条是 2026-08-11 那批**手工整理**的 lane 布局。自 2026-09-17 起，同一批证据也可以由
生产端 `scripts/codex_viral_research_package.py` 封成**可复现的包**，消费端会把它作为第三条证据通道读取。

包固定为四个文件：

| 文件 | 内容 |
|---|---|
| `manifest.json` | `schema_version`、`run_id`、`status`、`created_at`、`source_lanes`、`samples[]`、`exclusions_ref`、`errors[]` |
| `samples.jsonl` | 每行一个规范化样本：`sample_id`、`platform`、`account_id`、`title`、`canonical_url`、`published_at`、`capture_status`、`raw_ref`、`clean_ref`、`metadata_ref`、`evidence_cluster`、`shape`、`qualification_status` |
| `exclusions.jsonl` | 被排除的样本及其 `exclusion_reason` |
| `integrity.json` | 上述三个文件的逐个 SHA-256 |

两条硬约束（生产端与消费端都强制）：

1. **证据不得越界**：`--capture-manifest` 与 `--output-root` 必须在批次 `RUN_ROOT` 之内（越界报
   `path_escape`）；产物不可覆盖（`artifact_exists`）。
2. **完整性实校、失败即关闭**：消费端读包时会重算三个文件的 SHA-256。`integrity.json` 缺失记
   `integrity_missing`；任何一项对不上记 `integrity_failed` 并在 `integrity.mismatches` 列出；
   两种情况下列入的样本一律**不计入** `usable_for_positive_patterns`。生产端自述 `status` 不作为
   消费端判定依据 —— 只作为 `package_status` 原样透出供核对。

包内样本的 `raw_ref` / `clean_ref` / `metadata_ref` 相对**批次的 `RUN_ROOT`** 书写，
即 `--evidence-run` 所给目录（`<RUN_ROOT>/viral-research`）的父级。

生产端证据不完整时仍会落包：`status: blocked` + `errors[]` 列出缺口，同时写 `integrity.json` ——
失败同样留痕可审计。

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
- 批次包通道的 `status`（`available` / `integrity_missing` / `integrity_failed` / `invalid`
  / `unavailable`）、`integrity.verified` 与 `integrity.mismatches`；
- 不把 `observed_pending`/`research_only` 当作正向爆款证据的机器可读策略。

带批次包时用 `--evidence-run "$RUN_ROOT/viral-research"`（见 `README.zh-CN.md` 的
「爆款研究库」一节，那里有从建包到 finalize 的完整命令序列）。

Codex 的调用顺序由 `.agents/skills/ruoyu-viral-library/SKILL.md` 固定：先索引，再读卡，再按引用读取少量正文和指标，最后才做跨样本比较。

## 资格边界

- `qualified_viral`：文章级表现证据与预声明平台/时间窗口规则可回查；仍须满足多篇、形态匹配、跨账号/题材等条件，才能支持正向技法候选。
- `observed_pending`：证据不完整，只能观察或补证。
- `research_only`：只有全文/结构或其他不足以判定爆文的材料，只能作结构参考或反例。
- 蒸馏输出仍是候选观察，不会因为频次出现就自动变成 canonical 写作规则。
- 任何新文章的片名、人物、档期、票房和其他当前事实，都必须重新核验权威来源；旧文章正文只能提供结构研究材料。
- **凭证占位符要看得见**（2026-09-17 实测）：本机 14 张 `qualified_viral` 卡的
  `client_evidence.sha256` 是 64 个 0——契约只校验格式，所以"自称合格"一直没人复核。
  现在 `case_contract.case_card_warnings` 把它标成 warning：legacy 索引
  （`scripts/codex_viral_library_index.py`）逐卡输出 `warnings`/`warning_codes` 并在包级给出
  `warning_counts`、`usable_with_warnings_count`；新管线的 package 组装会把降级原因
  随 sample 落盘，卡片信封写进 `case_contract.warnings`。**warning 不改变资格判定**
  （收紧成硬失败会把现有唯一一批合格语料清零）；要修的是凭证本身——重新取证回填，
  该决定属于 controller。

## 这次没有自动做的事情

1. 没有把 Vault 私有资料、Hermes memory、session、Kanban、`.env`、cookie、token 或认证文件复制到项目。
2. 没有把 `runs/` 中的原文和客户端指标强行加入 Git。它们目前是本机忽略的研究证据，跨机器迁移需要单独确定范围、来源授权、体积和恢复点。
3. 没有把单篇案例或历史“清理版”文档升级为当前生产规则。
4. 没有写回 Vault、发布文章、合并、部署或推进任何状态。

## 若要跨机器完整迁移

应另开一个明确范围的迁移任务，先生成证据 manifest 和 SHA-256，再选择以下一种承载方式：

- 将经过筛选的 `clean.md`、文章卡、performance evidence 和 manifest 作为受控项目资产提交；或
- 保留正文/指标在独立只读归档，项目只提交不含正文的索引和哈希。

产物账本归属（2026-09-17 定）：package / cards / distill 报告是 **new-only** 产物，
自带逐文件 SHA-256（`manifest.json` / `integrity.json`，`validate_package_root` 可独立重算），
因此**不留 before-image**；但产物落在 run 内时，run 的 `evidence-changelog.jsonl` 会记一条
产物级锚点（`evidence_write.anchor_artifact`），封存校验据此区分"有账"与"无账"。
产物被复制/迁移时，可验证性跟着它自己走。

不得把整个 `runs/` 目录无差别加入仓库，也不得用旧库摘要代替真实全文或文章级表现证据。完成跨机器迁移的验收条件是：每个被声明为 `qualified_viral` 的样本都能解析 card、正文快照、表现证据和哈希；缺失项必须明确显示为 `unavailable`。

## 证据声明

本文件和索引描述的是“Codex 能否找到并正确分层使用库”，不是“所有爆款正文已经迁移完成”。当前项目承载层已建立；本机之外的完整正文证据迁移仍是未完成事项。
