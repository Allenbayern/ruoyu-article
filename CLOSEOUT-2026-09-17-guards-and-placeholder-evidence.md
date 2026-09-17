# 收尾记录：占位符凭证可见化 + 封存护栏（2026-09-17）

- 记录时间：2026-09-17 17:2x CST（`git log -1` 时刻为 16:46:08）
- 记录人：dsh agent（本轮以**独立复核**身份核过全部关键断言）
- 记录原则：本文件只写**亲手复跑验过**的结论；未验证的一律标「未验证」。
- 权威边界：本记录是**状态与证据索引**，不是规则来源。规则仍在 `AGENTS.md` 与 Vault。

## 1. 直接结论

代码这条线**已收完**，不需要再改任何东西。待办只剩一件：**它那 7 个提交等你授权推送**。
另有一条**身份瑕疵已不可回收**（§4.2），建议记录并接受，不要 force-push 修。

## 2. 当前状态

| 项 | 值 | 说明 |
|---|---|---|
| 分支 | `codex/article-pipeline-contract-hardening` | 跟踪 `origin/codex/...` |
| 本地 HEAD | `e2f627d`（2026-09-17 16:46:08） | |
| 工作树 | 干净 | 记录时 `git status --porcelain` 为空 |
| 未推提交 | **7** | `54b2e92 3567ef4 69af0f3 31ec2e8 9c66518 e366ae6 e2f627d` |
| 远端 refs | `origin/main` = `origin/master` = `origin/codex/...` = `c2e146f` | 三个 ref 同 sha |
| 测试规模 | **1602 collected** | 本轮起点 1391（`d320948`） |
| SEALED | 全仓仅 `runs/2026-09-16/daily-008/SEALED` | 目标 run 未封存 |
| 爆款库语料 | 11 卡，mtime 冻结在 **08:49:37** | 本轮唯一一批合格语料 |

## 3. 本轮产出与证据

### 3.1 `df50d54` —— 占位符凭证可见化（warning 级，不阻断）

- 三文件：`article_group/case_contract.py`(+89/−0)、`article_group/case_distill.py`(+17/−3)、`tests/test_client_evidence_placeholder.py`(新增 287 行)。
- **零引用**：`df50d54..HEAD` 之间无人改过这三个文件，逐字节与提交版一致。
- 复跑锚点：`case_contract.py` sha256 = `6a566e0eea17ba07bbca0c5acbc001964a9f37da0b81132a67a405daa08f38b6`；
  测试文件 sha256 = `c7520e6da02716a91ee8699be17b1ffd64cae4f57a8d570a20bb9ae25e9e84b5`。
- **+37 成立**：隔离 worktree 实测 collect `d320948`=1391 → `df50d54`=1428，且两者
  **失败集逐条完全相同**（各 62 条，均为 worktree 环境噪声，见 §5）。37 条新增全过、未带坏既有用例。
- **变异验证（本记录独立重跑）**：隔离 worktree 中禁用 `placeholder_sha256_kind` →
  `27 failed / 7 passed / 3 skipped`；`git checkout` 恢复后哈希回到 `6a566e0e…`，
  同文件 `34 passed / 3 skipped`。证明用例非空转。
  口径说明：`df50d54` 的 worktree 没有 `runs/2026-08-11`，故 3 条真实卡集成用例必然 skip；
  挂上真实语料时该文件为 `28 failed / 9 passed`。两个口径自洽。
- 主树全程未被改动：变异只在隔离 worktree 内进行，前后主树哈希一致。

### 3.2 语料与证据链（11 张卡）

只新增 `client_evidence.sha256_status = placeholder_pending_re_attestation`：

- 11 卡 / 11 份留底（`runs/2026-08-11/viral-research/review/.before/20260917T084937/`）/ 11 条账目
  （`runs/2026-08-11/viral-research/evidence-changelog.jsonl`），三方齐全。
- 深层结构比对：**仅**差 `sha256_status`；`sha256` 原值仍是 64 个 0 且保留（未被快照哈希顶替）。
- 账目 `before_sha256` / `after_sha256` 与「留底文件 / 现文件」**逐条相符**。
- 现役代码复跑：11/11 → `qualified_viral`，各 1 条 `repeated_hex_char:0` warning。

### 3.3 并发工作补齐的两个缺口（**非本轮产出**）

本记录必须写明：前一轮复核提出的两个跟进项，已由**并发的另一批提交**完成，不要重复开工。

1. **占位符 warning 已进生产**（`54b2e92`）：接入 legacy 索引（逐卡 warnings / warning_codes +
   包级 `warning_counts` / `usable_with_warnings_count`）、package 组装降级原因落盘、
   卡片信封 `warnings`；另两条不可达路径改用测试钉死硬拒。
2. **封存护栏已进程级化**（`11f47b6` + 后续）：`article_group/runs_guard.py` 装 audit hook，
   `import article_group` 即生效。实测（沙箱 run，已清理）：
   - 写封存 run 内部 → `SealedWriteBlocked` ✅
   - 写**同级另一个 run** → 放行 ✅（不误伤）
   - 「传上层路径绕过」写法 → **同样被拒** ✅（前一轮报的那个洞已闭合）

## 4. 已知未决项（需要 controller 裁决）

### 4.1 `sha256_status` 不在任何 schema 校验范围

- 全仓唯一引用在测试与本轮脚本里；`schemas/viral-research-case-card.json` **没有**该字段。
- 该 schema 顶层 `additionalProperties: false`，而真实卡的 `client_evidence` / `metric_plan` /
  `metric_plan_frozen_at` 等均不在其属性表内 —— **真实卡本来就不通过这个 schema**，
  这不是本轮加字段造成的。
- 待定：是「承认字段口径」，还是「改 schema」。属治理裁决。

### 4.2 `df50d54` 的 author 身份瑕疵（**已进共享历史，不可回收**）

- 提交时误用 `-c user.email=allen@local`，绕过了仓库配置身份
  `Allen <allen@users.noreply.github.com>`。
- 全仓 177 笔的身份分布：`allen@users.noreply.github.com` 158 笔、
  `Allen@AllenBayern.lan` 17 笔、`Allen@MacBookPro.lan` 1 笔、`allen@local` 1 笔（即本笔）。
  即：**本机身份历史上本就存在**（19 笔），本笔属于"与当前配置身份不一致"，
  而非前所未有的污染。
- 该提交**已推送**：`reflog show origin/... → update by push`，首次进入远端为 **10:00:27**
  那次推送（`00cd1f1`）；现位于 `origin/main` / `origin/master` / feature 分支（`c2e146f`）。
- 远端存的确实是坏身份那版（`git log origin/main --grep=… → df50d54 Allen <allen@local>`），
  但**三个文件的内容无误**（远端 blob 的 sha256 与本地逐字节相同）。
- **处置建议：记录并接受。** 重写本地历史无法将其从共享历史移除；唯一移除手段是
  force-push `main`，风险与收益不成比例。内容正确性不受影响。

### 4.3 `df50d54..HEAD` 的独立复核：**已执行，通过**（见 §7）

## 5. 复跑方法（复现本记录的断言）

```bash
cd /home/allen/Projects/ruoyu-film-daily

# 我的提交是否仍零引用
git log --oneline df50d54..HEAD -- article_group/case_contract.py \
  article_group/case_distill.py tests/test_client_evidence_placeholder.py   # 期望：空

# 文件指纹
sha256sum article_group/case_contract.py tests/test_client_evidence_placeholder.py

# 规模
.venv/bin/python -m pytest --collect-only -q | tail -2

# 封存
find runs -name SEALED                                    # 期望：仅 daily-008 一条

# 变异性复核（务必在隔离 worktree 内做，勿在活树改文件）
git worktree add -f --detach /tmp/wt df50d54
```

**口径警告（本轮踩过的坑）**：`runs/` 是 conftest 只读自检区，且 `git worktree` 只带出被跟踪的
`runs/` 子集（187 个文件 vs 真实 5436 个）。因此 worktree 上跑全量会出现约 62 条**环境失败**
（V4 工具明确 `refuse_symlink` 等），**不是代码回归**。正确判读方式是**失败集差分**，
不是看总数。

## 6. 证据边界（本记录没做什么）

- **未**在 `runs/` 下写任何新文件：`runs/` 是 conftest 只读自检区，写入会让下一次
  `pytest` 变红（除非 `RUOYU_ALLOW_RUNS_WRITES=1`），且 `runs/` 被 gitignore，沉淀不到远端。
  这也是本记录放在仓库根的原因。
- **未**推送任何东西：推送需单独授权。
- **未**对 `df50d54..HEAD` 的 7 个提交做独立复核（见 §4.3）。
- **未**改 Vault 的 schema 口径（见 §4.1）。
- Vault 侧同步：`b8a063c`（3 文件，`Allen (Hermes)` 身份，**未推**，`mac-backup/main` 仍在 `f8039ae`）。

## 7. 后续独立复核：`df50d54..HEAD`（13 个提交）

复核时间：2026-09-17 17:1x CST。范围 `df50d54..7b6d2cd`，159 文件 / +23201−142。
方法与前一轮同口径：隔离 worktree 失败集差分 + 行为断言实测 + 变异口径。

### 7.1 全量测试

| 口径 | 结果 |
|---|---|
| 活树（真实语料、真实被 ignore 文件） | **1602 passed ×2**，0 failed / 0 skipped |
| 隔离 worktree `df50d54`（基线） | 1366 passed / 62 条环境失败 |
| 隔离 worktree `HEAD` | 1539 passed / 63 条环境失败 |

**失败集差分**：63 − 62 = **新增恰好 1 条**，且为环境噪声（见 7.2）；
**消失 0 条**（没有既有用例被改坏或删掉）。
传递增量 1539 − 1366 = **+173**，与"活树 1602 全绿、worktree 只多 1 条环境失败"完全自洽。

### 7.2 那唯一 1 条新增失败：环境，不是回归

`tests/test_runs_write_coverage.py::test_classification_lists_have_no_stale_entries`
报 9 条"名单过期"，其中 `scripts/mp_fetch.py`、`scripts/sogou_fetch.py`、
`scripts/patches/2026-09-17-mac/patch_*.py` 等经 `git check-ignore` 确认是被
`.gitignore` 忽略的**真实存在**文件，worktree 只带出被跟踪子集，故扫描不到。
活树上同一用例通过。**判读结论：worktree 缺件，非代码问题。**

### 7.3 新增测试模块（20 个）在活树上单跑

**210 passed**——13 个提交引入的全部新用例在真实环境全绿。

### 7.4 行为断言实测（不看自述，亲手跑）

沙箱 run 建在 `runs/.review3-sandbox`（用后即删；语料 mtime 未受影响，仍 08:49:37）：

| 断言 | 结果 |
|---|---|
| 无 token 写封存 run | `SealedWriteBlocked` ✅ |
| 祖先路径写法（前一轮报的洞） | `SealedWriteBlocked` ✅ |
| 写**同级另一个** run | 放行 ✅（不误伤） |
| 持 `sealed_write_token` 写封存 run | 放行 ✅（拦截不是"永远拒绝"） |
| token 退出后再写 | 再次拒绝 ✅ |
| 我的探针直接写 `SEALED.manifest.json` | 被拒 ✅（连复核者也被拦） |
| `run_seal.backfill` 建清单 → `verify` | `intact` ✅ |
| 走留底通道篡改封存文件 → `verify` | `drifted`，exit 2，并报出改动者/时间/authorized ✅ |

「封存 = 全量清单 + 可验证」这条承诺成立：被改过能发现，且能追到谁改的。

### 7.5 复核结论

**通过。** 13 个提交未改动 `runs/`（`git diff --name-only df50d54..HEAD` 中 runs/ 为空集），
未放宽 `.gitignore` 对 `runs/` 的忽略（只新增了 3 个 CLI 脚本的白名单），
全量在真实环境两次全绿，行为断言逐条实测成立。
