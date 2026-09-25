# 决策备忘：codex 残留的两件待裁决事项

> 状态：**provisional（待 controller 裁决）**——这是提案，不是规则，也不是 Canonical。
> 日期：2026-09-25
> 背景：`codex→dsh` 标识层改名已落地（提交 `7c9cc21`），边界与逐行分类见
> `runs/2026-09-25/seal-anchor-bypass/RUN-RECORD.md` §11.5。剩下两件事**改的是行为或契约**，
> 按纪律不擅自动，故列此备忘等你裁定。

## 一、现状（已改什么、保留什么）

**已改（标识层）**：9 个 `scripts/codex_*.py` 真身 → `dsh_*`、5 个 `tests/test_codex_*.py`、
`schemas/codex-review-contract.json`、`docs/codex/`→`docs/dsh/`、项目内 3 组 systemd 模板单元、
`.agents/skills/codex-ops-portable`→`dsh-ops-portable`。

**保留（不是遗漏）**：全库仍有 **98 文件、587 行**含 `codex`（2026-09-25 实测，`runs/`、`reviews/`、
`.venv` 除外；这个数字**包含专门讨论该边界的文档本身**——本备忘就在其中）。逐行归类后
**没有一行是"我们自己的模块/目录/单元标识"**：① 数据契约值/产物文件名 **380 行**；
② 退役运行时/史实/外部名 **178 行**；③ 解释兼容面为何保留的注释与讨论 **29 行**。

## 二、待裁决 1：`dsh_review` 仍在调用退役的 `codex` 可执行文件

**代码事实**：`article_group/dsh_review.py:610`
```python
codex = None if external_review is not None else shutil.which("codex")
if external_review is None and codex is None:
    raise SystemExit("codex executable not found in PATH; pass --review-json ...")
```
即：**不传 `--review-json` 时会去找 `codex` 可执行文件**；找不到就 fail-closed 并给出准确指引。
按全局规则，Codex CLI 已于 2026-09-16 退役（不在 `PATH`），所以**这条分支目前不可达**；
现行流程走的是"独立只读子代理产出复核 JSON → `--review-json` 记录"。

| 选项 | 做法 | 好处 | 代价 |
|---|---|---|---|
| **A（我的建议）** | 保持现状，在 docstring 注明"该分支自 2026-09-16 起不可达，保留是为了失败时给出准确指引" | 零改动、零风险；失败信息对操作者有用 | 活动代码里留着一个已退役运行时的引用（但它已 fail-closed，**不构成依赖**） |
| B | 删掉该分支（连带 4 条只测它的用例） | 彻底去依赖、去字样 | 改动 1 个模块 + 若干测试；丢掉"可用外部 CLI 跑复核"这条（已不可用的）能力；收益只是字样 |
| C | 改成调用会话模型（dsh 的 LLM 通道） | 恢复"无 `--review-json` 时自动复核" | 成本最高：要接模型客户端/prompt/超时/错误面；且与现行"L2 由独立只读子代理执行"的流程**功能重复**——等于把两套复核入口并存 |

**建议 A。** 理由：这条路已经 fail-closed 且提示准确；B 只换来字样却要动测试；C 与现行流程冲突，
应另立项而不是顺手做。

## 三、待裁决 2：契约值与产物文件名的成组迁移

这些是**写进磁盘历史产物**的值，改一个就等于让历史记录读不出来：

| 值 / 名字 | 落在哪 | 规模（实测） | 改值的代价 |
|---|---|---|---|
| `review_surface: "markdown_codex"` | 每个 `batch.json`、门禁、模板、夹具 | **72 个既有 batch.json** + 30 个代码/模板/夹具文件 | 72 个批次的门禁全部读不出自己的审阅面；须同时改读端与写端并保留旧值兼容 |
| `preview_mode: "local_codex"` | batch / 预览契约 / 审计脚本 | 同上量级 | 同上 |
| `review/<aid>/codex-l2-review*.json` | 每次 L2 复核的产物文件名 | **200 个文件、10 个 run** | 改文件名 = 这些 run 的复核证据在脚本里找不到；只能"新名 + 读端回退旧名" |
| `schema_version: "codex-*-v1"`（viral-library context/index/reader、skill-inventory、daily-article-consumer、review-audit-manifest） | 各工具写出的产出 | 多个 | 读端要接受新旧两个值 |
| `schema_version: "codex-review-contract-1.0"` | 复核记录（含 canonical 与 legacy 形状） | 13 处断言/引用 | 同上；且 AGENTS.md 拿它当"兼容形状"的判据 |
| `codex_review` / 账本原因前缀 `codex_review:l2` | 兼容别名 + `evidence-changelog.jsonl` 里的历史行 | 既有变更日志 | 历史账目的原因串会与新写的对不上 |
| `codex-daily-article-run.json`（消费者 manifest 文件名） | `scripts/dsh_daily_article_runner.py` | 该文件由本仓写出；media-intel 侧**只在历史 run 文档里提过**，无活代码读取 | 低（但属同一契约族） |
| `runs/codex-daily-article/`（systemd 模板里的输出目录） | `.config/systemd/user/ruoyu-film-daily-dsh-article@.service` | **目录不存在、无内容** | **零成本**——这是唯一现在就能安全改的 |
| `--codex-skills-root` / `CODEX_SKILLS_ROOT` | `scripts/dsh_skill_inventory.py`（指退役运行时的技能根） | 参数名 + 常量 | 改参数名会打断调用方；且它指的是**退役运行时的目录**，属专名 |

| 选项 | 做法 | 评价 |
|---|---|---|
| A | 全部保留现状 | 名字里永远留着 codex；但历史产物零风险 |
| B | **加兼容读旧值后迁移**（读端先接受新旧两个值 → 写端改新值 → 文档更新 → 独立复核一轮） | 正确做法，但这是一次跨 10 个 run / 72 个 batch 的契约迁移，**必须独占一轮**，不能与别的改动混 |
| **C（我的建议）** | **现在只做零成本项**（`runs/codex-daily-article/` 输出目录）；其余立项排期按 B 做 | 立刻可做、风险为零；大迁移不顺手做 |

## 四、不作为的后果

- 选项都不做：`codex` 字样会长期留在契约值与产物名里，下一个人看到 `markdown_codex` 会以为
  它是"给 Codex 用的"，而实际与 Codex 无关——这正是这次改名要消除的误解，只是它藏得更深。
- 若**现在硬做 B**：会让 200 个复核产物与 72 个批次的读端在迁移窗口内失配，而当前还有一个
  并行会话在同一个仓库里写作——迁移期间的失败会与它的改动混在一起，难以归因。

## 五、需要你勾的项

1. 待裁决 1：**A 保持现状 / B 删分支 / C 接会话模型**（建议 A）
2. 待裁决 2：**C 只做零成本项 / B 立项排期迁移 / A 全保留**（建议 C 现在做 + B 排期）
3. 若选 B：迁移期间是否需要**先冻结并行写作**（我建议需要，否则失配与并发改动难以区分）
