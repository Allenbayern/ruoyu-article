# 决策备忘：遗留命名（原 codex 字样）的两件待裁决事项

> 状态：**已裁决并已执行（2026-09-25）**——controller 裁定见 §六；§七 是据此执行并**已收口**的执行记录。
> 本文不再是"待裁决的提案"，但也不是 Canonical 规则：它记录的是一次裁决与其后续动作。
> 复核证据不写在本文里：见 `runs/2026-09-25/seal-anchor-bypass/RUN-RECORD.md` §24.4（第五轮）
> 与 §25（针对第五轮收口的重做复核）。
> 日期：2026-09-25（裁决日）
> 背景：`codex→dsh` 标识层改名已落地（提交 `7c9cc21`），边界与逐行分类见
> `runs/2026-09-25/seal-anchor-bypass/RUN-RECORD.md` §11.5。剩下两件事**改的是行为或契约**，
> 按纪律不擅自动，故列此备忘等裁定——现已裁定。

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

## 六、裁决（2026-09-25，controller）

1. **待裁决 1 → A（保持现状）**，并要求在 docstring 注明：
   「该分支自 2026-09-16 起不可达，保留是为了失败时给出准确指引」。
   → 已落地：`article_group/dsh_review.py::run_review` 的 docstring。
2. **待裁决 2 → C（现在只做零成本项）+ B 立项排期**
   → 零成本项已落地（见下）；B **已于 2026-09-25 执行完毕**（四波提交 + 第五轮复核收口），
   实测规模与分族覆盖面见 §七。

**本次实际改动的零成本项**：`.config/systemd/user/ruoyu-film-daily-dsh-article@.service`

- `--output-root .../runs/codex-daily-article/%i` → `.../runs/dsh-daily-article/%i`
  （全仓校验：该路径**只**出现在这个模板里，无任何代码按该名读写；`runs/codex-daily-article/`
  目录**不存在、无内容**，所以没有任何历史产物会被落下）
- 顺带把该 unit 自己的 `Description` 里的 `Codex` 改成 `dsh`（同一文件、同类零成本；已向
  controller 明示）。

## 七、B 迁移：执行清单与**执行记录**（2026-09-25 已执行）

> 立此清单是为了**不忘记**。执行时**独占一轮**，按下列顺序（读端先兼容，写端后改）。
> **本轮不冻结并行写作**：执行前实测工作树干净、无活跃写手（controller 已确认）。
> **状态：已执行完毕**，四波提交 `ff7dfc2` / `da98b39` / `0546a0d` / `9f9c01c`；第五轮复核收口 `0f75615`
> （复核记录：`runs/2026-09-25/seal-anchor-bypass/RUN-RECORD.md` §24.4）。

范围（**执行时按真实产物重新实测**，与立项时的估算有出入，以下为实测值）：

| 目标值 | 原现状 | 落点规模（实测） | 新值 |
|---|---|---|---|
| `review_surface` | `"markdown_codex"` | **73 个真实 `batch.json`**（72 个旧值 + 1 个 `html_delivery`）+ 17 个代码/模板/测试文件 | `markdown_dsh` |
| `preview_mode` | `"local_codex"` | 1 个真实 `batch.json` + 6 个文件 | `local_dsh` |
| L2 复核产物名 | `codex-l2-review*.json` | **86 个文件 / 10 个 run**（以 `codex-l2` 开头者实测；立项时写的"200 个文件"**偏大**） | `dsh-l2-review.json`（新名写、旧名读） |
| 各 `schema_version` | `codex-*-v1` 族 | 真实 `runs/` 里 **5 种**（复核契约 78 份、`codex-l2-review-timeout-v1` 3 份、viral-library index 2 份、context 1 份、daily-article-consumer 1 份） | `dsh-*` |
| 复核契约版本 | `codex-review-contract-1.0` | 8 处测试断言 + AGENTS.md/模板/schemas 引用 | `dsh-review-contract-1.0` |
| 账本原因前缀 | `codex_review:l2` | 历史 `evidence-changelog.jsonl` 行 | `dsh_review:*`（写端已是新值；`codex_review` 保留为**兼容别名**） |
| 消费者 manifest 名 | `codex-daily-article-run.json` | 写端 1 处 + 测试 5 处 | `dsh-daily-article-run.json` |

**执行步骤（顺序未颠倒）**：

1. **读端先兼容**：每处读端接受**新旧两个值**（新值为 `dsh-*`），并加测试钉住"旧值仍可读"。
   落成 `normalize_*` / `is_*` / `ACCEPTED_*` 三件套 + `tests/test_contract_value_migration.py`。
   **但读端的覆盖面是分族的，不能一概而论**（第四轮复核 major 2 逼出来的诚实结论）：

   | 族 | 本仓内有真实读端吗 | 兼容落在哪 |
   |---|---|---|
   | `review_surface` | **有**（`final_review` 11 处、`content_delivery`、`v4/verification`、`human_attestation`、两个 audit 脚本，共 15 个生产调用点） | `is_markdown_surface()`，逐处接线。历史产物可读 = 实测（73 个真实 batch 全部通过校验）**加一条门禁层回归用例**（`test_the_markdown_audit_cli_still_reads_a_historical_surface`，把读端收紧回字面量比较即变红）——2026-09-25 第五轮重做复核指出此前只有**单元**用例在钉，这条是补上的门禁层网 |
   | `preview_mode` | **有**（`final_review`、`preview_contract.validate_preview_evidence`、`preview_route_audit`） | `is_local_preview()` / `normalize_preview_mode()` |
   | L2 产物名 | **有**（`title_freeze`、`evidence_rebind`） | **两处各不相同，别按一行去找**（第六轮复核 minor）：`title_freeze` 走 `resolve_l2_review_record()`（新名优先、回退旧名）；`evidence_rebind.dependent_records()` **自列新旧两个名字**——它要的是"两个候选路径都列上"（好让 reconcile 覆盖两种命名的 run），与"解析出实际存在的那个"不是同一件事，故不复用 helper |
   | `codex-review-contract-1.0` | **没有**（本仓无门禁按 `schema_version` 校验复核记录） | `is_review_contract_record()`：前瞻契约 |
   | viral-library reader/index/context、skill-inventory、review-audit | **没有** | `ACCEPTED_*` 常量：前瞻契约 |
   | 消费者 manifest 名 | **没有**（runner 拒绝往非空输出目录写 → `output_exists`） | `ACCEPTED_CONSUMER_MANIFEST_NAMES`：旧名只对**外部消费者**可见 |

   后三行的常量**不是**被走到的分支，代码里逐处写明了这一点。它们的守卫方式是
   "实测冻结集合"（见下），而不是"有一个读者在读"——不要把它们读成已接线的兼容路径。
2. **写端改新值**：`DEFAULT_REVIEW_SURFACE`、`DEFAULT_PREVIEW_MODE`、`CONSUMER_MANIFEST_NAME`、
   `schema_version` 写出值、生产引擎 `scripts/daily_engine.py`。
3. **历史产物**：**一份都没重写**。证据：73 个真实 `batch.json` 全部仍通过校验（72 个解析为新值）；
   扫描 `runs/` 下 2534 个 json，历史 `schema_version` 全部落在某个 `ACCEPTED_*` 里。
   **注意 `runs/` 只是部分被跟踪**（`git ls-files runs` = 187 个文件 / 88 个 json），
   所以"扫 `runs/`"这条检查在干净检出里扫不到 `codex` 值——它显式跳过并说明原因，
   守卫改由**冻结集合**承担（`FROZEN_HISTORICAL_SCHEMA_VERSIONS`，字面量钉住实测的 5 个值）。
4. **文档**：`AGENTS.md`、`templates/*`、`schemas/dsh-review-contract.json` 同步；本文档标记已执行。
5. **独立复核一轮**：对象仅限本次迁移 diff（第五轮见 `RUN-RECORD.md` §24.4；针对其收口的重做复核见 §25）。

**执行中发现的两处清单错误（已按实测修正，不是猜测）**：

- `codex-l2-review-timeout-v1`（3 份，`runs/2026-09-04/daily-003/…`）**根本没有登记在册**——
  是"扫描真实产物"那条用例抓出来的。已收进 `LEGACY_SCHEMA_VERSIONS`。
- L2 产物规模"200 个文件"偏大：实测以 `codex-l2` 开头的产物是 **86 个文件 / 10 个 run**
  （"10 个 run"是对的）。同族的 `review/**/*l2*.json` 有 158 个，但那包含 readiness packet 等
  另一类产物，**不属于**本项（它们的名字里没有 `codex`，不需要迁移）。

**明确不做**：不改 `CODEX_HOME`/`CODEX_SKILLS_ROOT`/`--codex-skills-root`——它们指的是**已退役
运行时**的目录，属历史专名，改了会指向不存在的东西并抹掉"这段为什么是死的"。同理保留：
`scripts/dsh_skill_inventory.py` 里的来源标签 `"codex-user"`；`scripts/generate_daily_00{1,2}.py`
与 `run_real_daily_00{3,4}.py` 这几个 **daily-001…004 的史实生成脚本**（它们写的就是当时的值，
改脚本会让"重跑一遍却产出与磁盘不一致的东西"）；`docs/superpowers/**/2026-08-26-conditional-preview-mode*.md`
（当年那次改动的设计/计划存档）。

### 七之二、第五轮重做复核的追加登记（2026-09-25，见 `RUN-RECORD.md` §25）

原清单只登记了**写进磁盘产物的契约值**，漏掉了同批被改名的**机器可读诊断串**。重做复核把它们
挑了出来（minor）；这里补登记，处置**逐条判过**，不是"忘了所以没写"：

| 串 / 键 | 原值 → 现值 | 处置与理由 |
|---|---|---|
| 内容交付 blocker 码 | `content_delivery_requires_markdown_codex` → `..._markdown_surface` | **不改回、不留别名**。它是**运行时诊断码**（门禁当场解释"为什么挡住"），不落进任何产物文件，不属于"历史产物不重写"那一类。两处硬编码（`content_delivery.py` / `v4/verification.py`）保持同源 |
| `markdown_review_audit` 的 stderr 标记 | `INPUT_ERROR:markdown_review_audit_requires_markdown_codex` → `..._markdown_surface` | 同上。判据是"是否作为契约值落盘"；stderr 虽被自动化读，但它描述的是一次即时失败原因 |
| `markdown_style_audit` 的 stderr 标记 | 同上 | 同上 |
| `semantic_pass.mode` 值 | `explicit_codex_trigger_required` | **不改**：运行期诊断值（`viral_research_distill.py`），本仓内只有它自己的测试在读；仓外消费者不可见，登记在案 |
| index / inventory 的键名 | `codex_skill` / `codex_user_skill_count` | **不改**：它们是**写进产物文件的键名**，改名会让既有 index/inventory 的读者读不出——那属于"历史产物不重写 + 读端兼容"的成本，而收益只是清掉一个键名里的字样。登记在案 |

**L2 产物名的解析面**（重做复核 minor）：约定是**裸名 = 最终记录**、`-r*` = 过程留档，所以
`resolve_l2_review_record()` 只让裸名参与"冻结绑定"判定。`evidence_paths.py` 里原来把它写成
"整族"的注释已按实际收窄；让 `-r*` 参与回退反而会把「绑错冻结版本」降级成「绑了另一个版本」。
