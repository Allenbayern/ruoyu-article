# Hermes 到 Codex 的技能与工具交接

更新时间：2026-08-25

本文只记录不含凭证值的迁移边界。它是若雨项目的 Codex 使用说明，不是 Hermes 的控制面配置，也不把 Hermes 私有状态复制到项目。

## 结论

可脱离 Hermes 私有状态、可审查、可验证的流程已经迁移到项目级 skill：

- `.agents/skills/codex-ops-portable/SKILL.md`
- `scripts/codex_skill_inventory.py`
- `tests/test_codex_skill_inventory.py`

现有若雨 Codex 适配器仍是主要执行入口：

- `article_group/codex_review.py`
- `scripts/codex_review_audit.py`
- `scripts/codex_newrank_watch.py`
- `scripts/codex_daily_article_runner.py`
- `schemas/codex-review-contract.json`

Codex review、脚本输出和审查包都只是证据。它们不能授权发布、合并、部署、远程写入、配置变更或状态晋级。

## 能力矩阵

| Hermes 能力或工具 | Codex 承载方式 | 状态与边界 |
|---|---|---|
| 若雨文章生产规则 | 项目 `AGENTS.md`、现有用户级文章 skill、项目 gates | 已有承载；canonical 规则仍在 Vault，历史批次不能变成当前稿件 |
| 源码/部署同步审计 | `codex-ops-portable`、Git、`systemctl --user`、`readlink /proc/<pid>` | 已迁移为只读优先流程；外部写入需单独授权、恢复点和精确回读 |
| Python CLI 运行验证 | 项目测试、`uv run pytest`、`py_compile`、负向路径测试 | 已迁移；零退出码不是完整验收 |
| 确定性脱敏 | skill 中的 `[REDACTED]` 规则、现有安全启动桥接 | 已迁移为流程；不得读取或复制凭证值 |
| review evidence / adversarial review | `codex review`、`--output-schema`、现有 review contract 和 `codex_review.py` | 已有适配；审查结论是证据，不是授权 |
| Hermes `codex` 委派 skill | Codex 原生 `codex exec`、`codex review`、agents、worktrees | 不复制 Hermes 委派语义；任务仍由当前控制面划界和验收 |
| Hermes Gateway / Dashboard | `systemctl --user status/show`、服务日志、HTTP/端口只读检查 | 不迁移；这是 Hermes 私有运行面，Codex 只能按明确范围观察 |
| Hermes Kanban / dispatcher | 项目 `runs/<run-id>`、manifest、Git、现有测试；必要时外部 tracker MCP | 不做一比一伪迁移；不导入 Kanban 数据，不自行推进状态 |
| Hermes session / memory | Codex 的 `--ephemeral`、`exec resume`、本地会话功能 | 不导入 Hermes session DB 或 memory；跨会话事实放项目文档或明确产物 |
| Hermes cost router / 模型路由 | Codex 的 `-m`、`-p` 和已批准的用户配置 | 不迁移路由权威；Codex 不得自行改 provider、预算或控制面配置 |
| Hermes custom provider | Codex 自身 provider 配置和安全桥接 | 不复制 Hermes provider 文件；运行时只使用已存在的 Codex 登录态或显式白名单环境 |
| Hermes cron | 用户级 `systemd` timer、已有本机 scheduler 或项目脚本 | 不复制 Hermes cron jobs；定时任务必须有明确输出、失败信号和不晋级边界 |
| 邮件、微信、NAS、PVE、OpenWrt、ZeroTier 等远程能力 | 受限本地 CLI、SSH/systemd、或显式配置并审查过的 MCP | 没有默认 Codex 凭证或权限；逐项授权，先只读探测，不自动安装或写远程状态 |
| Obsidian/Vault 操作 | 直接读取 canonical 路径或经审查的本地工具 | Vault 默认只读；不把 Hermes memory、session、cookie、token 或数据库写回 Vault |
| Hermes 专属插件/工具 | Codex plugin、MCP、项目脚本 | 只按具体任务评估；插件/MCP 安装会引入新的权限和供应链边界 |

## 已核实的 Codex 原生能力

本机 Codex CLI 版本为 `0.149.1`。实际命令入口包括：

```bash
codex exec --help
codex review --help
codex mcp list
codex mcp get <name>
codex plugin list
codex plugin marketplace list
codex features list
```

当前观察到：

- MCP 当前没有配置服务器；不要把“支持 MCP”误写成“已经拥有远程系统权限”。
- `visualize` plugin 已安装并启用；其他 marketplace plugin 仍按任务单独评估。
- 官方可安装 skill 清单包含 `pdf`、`playwright`、`security-best-practices`、`security-threat-model`、`gh-*`、`linear`、`notion` 等，但本交接不自动安装它们。
- Codex 原生 skill 发现位置包括用户级 `$CODEX_HOME/skills` 和项目级 `.agents/skills`；项目 skill 通过仓库规则和当前任务加载。

## 推荐命令

### 只读盘点项目与用户级 skill

```bash
python scripts/codex_skill_inventory.py \
  --project-root /home/allen/Projects/ruoyu-film-daily \
  --codex-skills-root /home/allen/.codex/skills
```

该脚本只读取两棵 skill 树下直接的 `*/SKILL.md` frontmatter；不会遍历、读取或打印 `auth.json`、`.env`、cookie、token 或其他凭证文件。

### 只读执行与结构化输出

```bash
codex exec --sandbox read-only --ephemeral \
  --output-schema schemas/codex-review-contract.json \
  -C /home/allen/Projects/ruoyu-film-daily \
  "检查指定文件并返回结构化证据，不要编辑文件或访问凭证。"
```

### 对未提交改动做证据审查

```bash
codex review --uncommitted \
  "只报告可由当前 diff 和测试直接支持的问题；不要把审查结果视为发布或合并授权。"
```

### 本地验证

```bash
uv run pytest -q tests/test_codex_skill_inventory.py
python -m py_compile scripts/codex_skill_inventory.py
```

### 本地调度替代

需要定时运行时使用现有用户级 `systemd` timer 或明确的本地 scheduler。任务应写入 `runs/<run-id>/` 或其他已批准目录，输出稳定，失败可见，不得自动发布、合并、部署或推进状态。

## 凭证边界

Codex 使用自己的登录态和唯一配置入口，不复制 Hermes 的认证文件。已批准的本机桥接是 `/home/allen/.local/bin/codex-ruoyu`；模型、provider 与 base URL 只由 `/home/allen/.codex/config.toml` 管理，Codex CLI 自己读取 `/home/allen/.codex/auth.json`。实际凭证值始终视为 `[REDACTED]`，不得进入 prompt、argv、项目文件、manifest、日志或聊天。

不要 source Hermes 环境，不要把 Codex 指向 `/home/allen/.hermes`，不要读取 `.env`、cookie、token、密钥或认证文件内容。需要外部系统时，Codex 只使用用户已批准的登录态、受限权限文件、交互式安全注入或经过审查的 MCP；不存在默认远程权限这一事实必须保留。

## 不迁移清单

以下内容明确不复制：

- Hermes memory、session 数据库、Kanban 数据和 dispatcher 状态；
- Hermes Gateway、Dashboard、cost-router、模型路由和 provider 控制面配置；
- `.env`、cookie、API key、token、密码、私钥、连接字符串及其原始日志；
- 任何会让 Codex 自动发布、合并、部署、远程写入或晋级状态的隐式钩子。

需要这些能力时，使用上表的 Codex 等价入口，并重新建立任务范围、授权、恢复点、证据和验收条件。
