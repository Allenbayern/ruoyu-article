# Codex 本地运维交接

- 交接对象：本机 Linux 上运行的 Codex CLI
- 交接时间：2026-08-25 00:36 CST
- 交接原则：凭证可在运行时使用，但不写入本仓库、Vault、Git、日志、命令行参数或聊天内容。
- 权限边界：Codex 产出是证据或代码变更；不能自行授权发布、合并、部署、配置变更或状态晋级。

## 1. 直接结论

优先使用本机安全桥接命令：

```bash
cd /home/allen/Projects/ruoyu-film-daily
codex-ruoyu doctor --summary
```

`codex-ruoyu` 位于 `/home/allen/.local/bin/codex-ruoyu`，权限应为 `0700`。默认模式只把干净的基础环境交给 Codex，并设置 `CODEX_HOME=/home/allen/.codex`，由 Codex CLI 自己读取其原生登录态 `/home/allen/.codex/auth.json`。

需要使用代理环境文件时，显式使用：

```bash
codex-ruoyu --chaoye doctor --summary
codex-ruoyu --chaoye exec --sandbox workspace-write "在当前仓库完成明确的代码任务"
```

`--chaoye` 模式只从 `/home/allen/.codex/chaoye.env` 导入三个允许的变量名：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL`，并独立于原生 OAuth 文件；文件内容只存在于 Codex 子进程环境中，不进入 argv、项目文件或 wrapper 输出。默认模式不读取该 env 文件。

不要使用 `env`、`set`、`printenv`、调试转储或把凭证放进 prompt/命令参数。子进程环境可被同一用户的调试工具看到，这是运行时授权的边界；不要把 Codex 指向 `/home/allen/.hermes` 或直接要求它读取认证文件内容。

## 2. 主机

| 项目 | 当前值 | 证据状态 |
|---|---|---|
| 主机名 | `allen-standardpc` | 2026-08-25 实测 |
| 系统 | Ubuntu 26.04 LTS | 2026-08-25 实测 |
| 内核 | `7.0.0-29-generic`，x86_64 | 2026-08-25 实测 |
| 虚拟化 | KVM guest | 2026-08-25 实测 |
| LAN 地址 | `192.168.100.168/24`，接口 `ens18` | 2026-08-25 实测 |
| 默认网关 | `192.168.100.1` | 2026-08-25 实测 |
| ZeroTier 地址 | `10.120.184.96/24`，接口 `zt3hhf6uot` | 2026-08-25 实测 |
| 内存 | 23 GiB，总可用约 20 GiB | 2026-08-25 实测 |
| 根盘 | 79 GiB，已用约 46 GiB，约 61% | 2026-08-25 实测 |
| Swap | 1 GiB，已用约 307 MiB | 2026-08-25 实测 |

常用只读检查：

```bash
ip -brief addr
ip route
free -h
df -hT / /home /tmp
ss -lntup
```

## 3. 网络拓扑

| 节点 | 地址 | 用途 | 备注 |
|---|---|---|---|
| iStoreOS | `192.168.100.1` | 网关、OpenClash、New API | New API `:3010` 当前 HTTP 根路径实测 200；代理和 LuCI 操作需单独核验 |
| 当前 VM100 | `192.168.100.168` | Hermes、若雨项目、预览 | 本交接所在主机 |
| PVE | `192.168.100.254` | Proxmox 管理 | `ssh pve true` 免交互实测成功 |
| NAS/VM101 | `192.168.100.123` | fnOS、只读热点聚合、视频处理 | 旧 `.223` 地址属于历史资料，不得继续使用 |
| ZeroTier relay | `10.120.184.96:8265` | 转发 NAS `192.168.100.123:8265` | `socat` 用户服务托管，当前 active |

已知历史运行约定，操作前重新探测：

- OpenClash 管理面/代理相关端口曾使用 `7890`、`9090`；2026-08-24 的既定策略是海外流量收敛到美国节点。此处只保留为运维线索，不视作本次 fresh 验收结果。
- NAS 只读糖果梦热榜聚合器：`http://192.168.100.123:4399`；项目适配器结果只用于发现，不能直接当事实证据。
- ZeroTier 本机用户态 `zerotier-cli` 因不能读取系统 token 会报不可读；不要复制或暴露 `/var/lib/zerotier-one` 下的认证文件。服务和接口状态应通过 systemd、`ip` 或明确授权的 root 只读检查确认。

## 4. 当前用户服务与端口

| 服务/进程 | 运行方式 | 当前状态 | 端口/路径 |
|---|---|---|---|
| `hermes-gateway.service` | 用户级 systemd；gateway 代码与部署目录需按实际 import path 核验 | active | 内部消息/gateway；dispatcher 在 gateway 运行边界内 |
| `hermes-serve.service` | 用户级 systemd；`hermes serve --host 192.168.100.168 --port 9119 --skip-build` | active | `192.168.100.168:9119`，HTTP 根路径实测 302 |
| `ruoyu-preview.service` | 用户级 systemd | active | `0.0.0.0:8765`，当前 `serve_current_revisions.py` |
| `nas-8265-zerotier-relay.service` | 用户级 systemd + `socat` | active | `10.120.184.96:8265` -> `192.168.100.123:8265` |
| Waydroid container | system process | container running；Waydroid session STOPPED | 需要 Android 自动化时另行启动/核验 |

2026-08-25 fresh HTTP 检查：

```text
http://192.168.100.168:8765/                                  -> 200
http://192.168.100.168:8765/ruoyu-video-topic-plan-2026-08-23.html -> 200
http://192.168.100.168:9119/                                  -> 302
http://192.168.100.1:3010/                                    -> 200
```

服务检查：

```bash
systemctl --user is-active hermes-gateway.service
systemctl --user is-active hermes-serve.service
systemctl --user is-active ruoyu-preview.service
systemctl --user is-active nas-8265-zerotier-relay.service
systemctl --user --failed --no-pager
```

无关当前 Codex/若雨交接的历史异常：`xdg-desktop-portal.service` 和 `xdg-desktop-portal-gtk.service` 当前 failed；不要把它们误判为 Hermes gateway 或预览服务故障。

## 5. Hermes 双树与运行边界

- 开发树：`/home/allen/Projects/hermes-agent`
- Hermes 部署/运行数据树：`/home/allen/.hermes`
- gateway 用户服务：工作目录 `/home/allen/.hermes`，使用 `/home/allen/Projects/hermes-agent/.venv/bin/python` 启动 gateway。
- desktop serve 用户服务：使用 `/home/allen/.local/bin/hermes`，服务端口 `9119`。
- Hermes gateway 与 desktop serve 不是同一个服务；dispatcher 归 gateway 运行边界。
- 改 Hermes 运行代码前必须确认：服务 PID 的 `cwd`、`/proc/<pid>/cgroup`、实际导入模块的 `__file__`，以及对应服务日志。不能仅凭目录名判断哪棵树生效。
- 改开发树代码后，只有在确认 active import path 后才同步部署树并重启对应服务。重启是外部状态变化，须先保留恢复点并做精确验证。

推荐定位命令：

```bash
systemctl --user status hermes-gateway.service hermes-serve.service --no-pager
ps -eo pid,ppid,user,etimes,args | grep -E '[h]ermes|[s]erve'
readlink -f /proc/<PID>/cwd
tr '\\n' ' ' </proc/<PID>/cgroup
```

## 6. 若雨项目

项目根目录：`/home/allen/Projects/ruoyu-film-daily`

- `pyproject.toml`：项目要求 Python `>=3.14`；依赖以 `uv` 管理。
- 当前工具：`uv 0.12.4`；Hermes CLI `0.20.5`；Codex CLI `0.149.1`。
- 推荐验证：

```bash
cd /home/allen/Projects/ruoyu-film-daily
uv run pytest -q
```

- `article_group/codex_review.py` 是证据旁路适配器：它只写 review JSON 和原始日志，不授予发布、合并、部署或状态推进权限。
- 当前预览交付通过 `http://192.168.100.168:8765/`；成品 HTML 需先落盘、重算哈希、更新 manifest/bundle/映射并重新验证预览。
- 当前仓库不是干净树：交接时 `master` 跟踪 `origin/master`，本地领先 26 个提交；HEAD 为 `79d3ef9`；当时有 9 个已修改文件和 16 个未跟踪路径。任何 Codex 任务开始前都必须重新执行 `git status --short --branch`，不得 `reset --hard`、`checkout --`、`clean -fd` 或删除不属于本次任务的文件。
- `AGENTS.md` 要求先读取 Vault canonical 规则；重要入口：
  - `/home/allen/Documents/Obsidian Vault/Hermes-Knowledge/AGENTS.md`
  - `/home/allen/Documents/Obsidian Vault/Hermes-Knowledge/20_Hermes/00_System/Codex Context.md`
  - `/home/allen/Documents/Obsidian Vault/Hermes-Knowledge/20_Hermes/10_Content_Production/02_Article_Group/Index.md`
  - `Hermes Article Group Operating Rules.md`
  - `Hermes Article Group Workflow.md`
- Vault 默认只读；不把 Hermes memory、会话数据库、认证文件、API key、cookie、token 或 SQLite 数据库写进项目/Vault。

## 7. 凭证交接边界

### Codex CLI 自身

| 资源 | 用途 | 当前权限 | 交接方式 |
|---|---|---:|---|
| `/home/allen/.codex/auth.json` | Codex 原生登录态 | `0600` | Codex CLI 自己读取；wrapper 不复制、不打印 |
| `/home/allen/.codex/config.toml` | Codex provider/model/project 配置 | `0600` | 通过 `CODEX_HOME` 使用；不要把值复制到项目 |
| `/home/allen/.codex/chaoye.env` | 可选的 provider env 文件 | `0600` | 仅 `codex-ruoyu --chaoye` 子进程导入允许的三个变量名；不依赖 `auth.json` |
| `/home/allen/.local/bin/codex-ruoyu` | 安全启动桥接 | `0700` | 清空继承环境，避免 Hermes 会话变量进入 Codex |

已验证存在且属当前用户的敏感容器：

- `/home/allen/.codex/auth.json`
- `/home/allen/.codex/config.toml`
- `/home/allen/.codex/chaoye.env`
- `/home/allen/.hermes/auth.json`

### 不交给 Codex 的内容

- Hermes 的 `~/.hermes/auth.json`、`~/.hermes/config.yaml`、session DB、memory、session key、provider secret 以及任何 `HERMES_*` secret/session 环境变量。
- iStoreOS、New API、OpenClash、平台账号和浏览器登录态的密码、cookie、token。
- Vault 中的认证文件、`.env`、cookie、API key 和 token。
- 私钥文件内容。SSH 仅通过现有 host alias 使用，不复制私钥。

### SSH 入口

`/home/allen/.ssh/config` 当前有：

```text
Host pve
  HostName 192.168.100.254
  User root
  IdentityFile ~/.ssh/hermes_pve
```

`ssh pve true` 已免交互成功。当前 SSH agent 没有已加载身份；不要把 `SSH_AUTH_SOCK` 从 Hermes 会话继承给 Codex。Codex 需要访问 PVE 时直接使用：

```bash
ssh pve
ssh pve qm status 100
ssh pve qm status 101
```

### 凭证故障处理

- Codex AI 认证故障：先运行 `codex-ruoyu doctor --summary`；不要打印 auth 文件，不要把 key 写入项目。
- 代理 env 故障：显式运行 `codex-ruoyu --chaoye doctor --summary`；只检查退出码和非敏感诊断。
- PVE SSH 故障：运行 `ssh -G pve` 检查 host、user、identityfile，再用 `ssh -o BatchMode=yes -o ConnectTimeout=4 pve true` 快速失败。
- iStoreOS/NAS/平台需要额外凭证时：由用户授权单次运行时注入；不写入 `~/.codex`、项目、Vault、Git remote、shell history 或日志。

## 8. 运行安全规则

1. 先读 `AGENTS.md`、canonical 规则和当前 `git status`。
2. 先做只读 preflight，再做单一 bounded change；记录恢复点和精确逆操作。
3. 任何凭证、权限、网络暴露、跨系统操作或发布/合并/部署行为都按高风险处理，不能由 Codex 自行最终授权。
4. 不使用 `--yolo` 处理本仓库；优先 `--sandbox read-only` 做审查，代码变更才使用明确的 `--sandbox workspace-write`。
5. 不启动新的远程服务、不改防火墙/OpenClash、不重启 Hermes、不写 Vault，除非任务明确授权且有独立验收条件。
6. 任何文章事实必须回到当前权威来源；热榜、标题、摘要和历史稿不能直接当事实证据。
7. 文章交付仍以最终冻结 HTML、manifest、哈希、门禁结果和预览 HTTP 状态为准；Codex review 只是旁路证据。

## 9. 常用诊断清单

```bash
# Codex credentials without exposing them
codex-ruoyu doctor --summary
codex-ruoyu --chaoye doctor --summary

# Project state
cd /home/allen/Projects/ruoyu-film-daily
git status --short --branch
git log -1 --oneline
uv run pytest -q

# Hermes runtime
systemctl --user status hermes-gateway.service hermes-serve.service --no-pager
journalctl --user -u hermes-gateway.service -n 100 --no-pager
ss -lntup | grep -E ':(8765|9119|8265)'

# LAN/remote reachability
curl -sS -o /dev/null -w '%{http_code} %{time_total}s\\n' http://192.168.100.168:8765/
curl -sS -o /dev/null -w '%{http_code} %{time_total}s\\n' http://192.168.100.1:3010/
ssh -o BatchMode=yes -o ConnectTimeout=4 pve true
```

## 10. 未验证项与停止条件

- 本文没有读取任何 credential value；Codex 的实际业务调用应以 `doctor` 和最小无副作用 `exec` 结果为准。
- OpenClash 当前运行配置、节点选择和 LuCI 状态未在本次交接中重新登录验证；涉及代理/路由改动时必须另做 preflight。
- NAS `:4399` 的业务数据质量、缓存新鲜度和 VM101 的具体任务状态未在本次交接中重新核验；只把地址和项目适配器边界作为入口。
- Hermes gateway 的实际 Python import path 在改代码前仍需按 PID/cgroup/`module.__file__` 三连确认。
- 任何一项无法通过只读证据确认时，停止在 evidence/preflight 阶段，不用猜测补齐。
