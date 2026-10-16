# Vendored — yuwen-publish-precheck（发布前审）

本目录是**第三方 skill 的逐字节副本**，不是我们的代码。

| 项 | 值 |
|---|---|
| 上游 | https://github.com/yuwen-cool/yuwen-publish-precheck |
| 固定 commit | `b9efdc6bc1938b40ad1c556fba65c562fc182be0`（2026-10-08 17:53:26 +0800，`docs: preserve license in markdown-only skill registries`） |
| vendor 日期 | 2026-10-15 |
| 许可 | MIT（见 `LICENSE` / `LICENSE.md`；第三方声明见 `THIRD_PARTY_NOTICES.md`） |
| 本地修改 | **无**。本目录与上述 commit 的工作区逐字节相同（仅剔除 `.git`、`__pycache__`、`.pytest_cache`） |
| 引入用途 | 文章组流水线的**补充层**：发布前词面预检 + 官方规则依据 + 保意修复/复盘参考 |

## 为什么 vendor，而不是 submodule 或在线拉取

流水线要可复现、可离线、证据可哈希。每次扫描把 commit 与 `scripts/scan.py`、`scripts/terms.json`
的 sha256 记进证据，"依据哪条规则"才能在日后逐字重放。在线拉取会让同一份报告隔天无法复现。

## 铁律：本目录只读，且不在这里放任何项目数据

- **不往这里写词库、案例、报告。** 上游 `.gitignore` 把 `data/*` 排除在外——在这里沉淀的规则
  既不会被 Git 跟踪（下一个人克隆不到），也会在升级时被上游覆盖。
- 我们的规则数据在 `references/publish-precheck/`（tracked）：
  `profile.md` / `my-rules.md` / `expressions.md` / `wordlists/` / `cases/` / `history/`。
  适配器 `article_group/publish_precheck.py` 调用时把该目录挂进一个临时工作目录的 `data/`，
  这样 `scan.py` 读到的是我们的规则，而 vendor 一个字节都不变。
- 升级 = 重新 vendor 到新 commit + 重算清单，**不手改上游文件**（手改会让下一份报告的依据无法追溯）。

## 完整性校验

```bash
cd third_party/yuwen-publish-precheck && sha256sum -c VENDOR.sha256
```

`VENDOR.sha256` 覆盖本目录全部 vendored 文件（不含 `VENDOR.md` / `VENDOR.sha256` 自身）。

## 上游自测（升级后必跑）

```bash
cd third_party/yuwen-publish-precheck && python3 -m pytest evals -q
```

## 升级流程

1. `git clone --depth 1 https://github.com/yuwen-cool/yuwen-publish-precheck.git /tmp/ypp && git -C /tmp/ypp rev-parse HEAD`
2. 与本文档记录的 commit 比对，读上游 `CHANGELOG.md`（规则包版本、平台包变化）。
3. `rsync -a --delete --exclude .git --exclude __pycache__ --exclude .pytest_cache /tmp/ypp/ third_party/yuwen-publish-precheck/`
4. 重算 `VENDOR.sha256`，更新本文档的 commit 与日期。
5. 回归：`python3 -m pytest tests/test_publish_precheck.py`，以及上游 `evals`。
6. 若 `scripts/terms.json` 的规则编号（`general-community-safety.Gxx` 等）发生改名，
   检查 `references/publish-precheck/my-rules.md` 里是否有引用旧编号的条目。

## 边界（照抄进任何使用说明都不许改写）

这个 skill 自己就写明了：**词面命中不等于违规，零候选不等于安全**；判定靠 LLM 语义判。
因此在本仓库里它只能是**补充层**：

- 它**不是门禁**，不产出 PASS/FAIL，不阻断 run，**不构成任何发布授权**；
- 它的输出必须交给独立只读复核做语义判定，结论落进 `schemas/dsh-review-contract.json` 形状；
- 扫描器坏掉时记录 `error` / `not_run` 与原因，**绝不允许**把"没扫到"当成"干净"。
