# 选题侦察：怎么跑、产物看哪里、边界在哪

> 状态：**provisional**（agent 整理的运行说明，不是 controller 验收的 canonical 规则）
> 核实日期：2026-09-25
> 来源：`runs/2026-09-23/taboo-topics-001/HOW-TO-RUN.md`、`HOW-TO-USE-TWO-MODES.md`、
> `GAP1-BACKLOG-DONE.md`、`GAP2-CONVERTER-DONE.md`（那批文档在 `runs/` 里，**不进版本库**；
> 2026-09-25 把仍然成立的操作部分整理到这里，`runs/` 里的原件继续作为当时的证据保留）。
> 本文只写**实测跑通**的部分；缺口单独列在第五节，不混进「使用说明」。

## 一、边界（先看这条）

这套东西**只收集与建议**：不选题、不写作、不建批次、不发布、不写 Vault。
圈题永远是 controller 的动作，且**必须有署名**（不署名直接拒绝）。

两条硬规则：

1. **入库自动，表态不自动。** 扫描只会把候选放进 `new`；移动到 `backlog` / `selected` /
   `dropped` 必须 `--by <署名>`。
2. **被放弃的条目不会再复活。** 同一篇文章第二天再被扫到，只累加 `seen_count`、
   更新 `last_seen_at`，状态不变——否则同一批噪音每天早上都会回到你面前。

## 二、模式 1：天天跑，积攒（上游）

```bash
# ① 采集（media-intel）
cd /home/allen/Projects/media-intel-aios
.venv/bin/python scripts/run_article_research_loop.py \
  --once \
  --date $(date +%F) \
  --queue-db run/article-research.sqlite \
  --output-root runs/$(date +%F)/topic-scout \
  --weress-base-url http://192.168.100.1:8001

# ② 出建议卡（本仓库）
cd /home/allen/Projects/ruoyu-film-daily
.venv/bin/python scripts/topic_scout.py \
  --research-run <①输出的 run 目录> \
  --account-pool /home/allen/Projects/media-intel-aios/config/approved_viral_account_pool.json \
  --out-dir runs/$(date +%F)/topic-scout-decision \
  --max-cards 5 --llm

# ③ 入库 + 出人读视图
.venv/bin/python scripts/topic_backlog.py ingest \
  --scout-ledger runs/$(date +%F)/topic-scout-decision/candidate-ledger.jsonl
.venv/bin/python scripts/topic_backlog.py render --out state/topic-backlog.md
```

- `--once` = 跑一轮就退出（**日常用这个**）。`--daemon` 常驻调度**需要单独授权**，
  且要先连续三次手动绿跑。
- `--weress-base-url` 目前仍是**临时垫片**：把 `~/.config/media-intel-aios/article-research.env`
  里的 `WERSS_BASE_URL` 改成 `http://192.168.100.1:8001` 之后才能去掉。
- 跑完按这个顺序看产物（目录形如 `runs/<日期>/topic-scout/<日期>/article-research-<hash>/`）：
  `verification.json`（`cycle_status`）→ `source-health.json`（哪个源失败）→
  `material-shortlist.md`（人读最省事）→ `article-candidates.jsonl`（公众号正文）→
  `retry-state.json`。

## 三、模式 2：挑出来，进批次（下游）

```bash
# ① 表态（必须署名；key 可只给唯一前缀，如 sha256:631cff25）
.venv/bin/python scripts/topic_backlog.py decide \
  --key sha256:631cff25 --state selected --reason "…" --by controller

# ② 建议卡 → 候选池骨架（机器只填能从卡上机械推导的字段）
.venv/bin/python scripts/scout_to_candidate_pool.py \
  --scout-ledger runs/<日期>/topic-scout-decision/candidate-ledger.jsonl \
  --select-file <圈题 id 列表>.json \
  --run-id <日期>/<批次> \
  --out runs/<日期>/<批次>/candidate-pool.json

# ③ 人填「编辑判断」字段（工具刻意留空，见第五节）
# ④ 过闸门
.venv/bin/python -m article_group.portfolio_gate <candidate-pool.json>
```

### 储备池命令一览

| 命令 | 作用 |
|---|---|
| `ingest --scout-ledger <ledger>` | 扫描入库（只进 `new`） |
| `list --state <状态>` | 列出条目（`--json` 给机器读） |
| `decide --key <k> --state backlog/selected/dropped --by <署名>` | 表态 |
| `adopt --key <k> --run-id <批次> --by <署名>` | 记录已进入哪一批 |
| `retract --key <k> --reason … --by <署名>` | 撤销表态（**留痕**：轨迹里是 `retraction` 事件，不抹历史） |
| `render --out state/topic-backlog.md` | 人读视图 |
| `export --out state/topic-backlog.jsonl` | JSONL 文本快照（见第四节） |

**一条硬边界**：`decide --state selected` 时若该条 `risk_unverified`，工具**拒绝**
（`risk_unverified_cannot_be_selected`）。风险尺子按 controller 决定推迟校准，所以未复核的
条目不能借「圈题」溜进批次；标 `backlog` 仍然允许——储存不构成推进。

## 四、状态存哪、坏了怎么办

| 路径 | 内容 | 进版本库？ |
|---|---|---|
| `state/topic-backlog.sqlite` | 二进制库（唯一的权威状态） | **否**（每次 ingest 都变，且无法 diff） |
| `state/topic-backlog.jsonl` | `export` 出的文本快照（含 `data_as_of`） | **是**（二进制库坏了可从它恢复） |
| `state/topic-backlog.md` | `render` 出的人读视图 | **是** |

导出是**显式动作**：`ingest` 不会自动刷新快照。同一份库重复 `export` 逐字节相同
（`data_as_of` 由库内容推导，不是导出墙钟），所以 diff 里只出现真实变化。

## 五、已知缺口（如实列出，不混进说明）

1. **编辑判断字段必须由人填。** 转换器只填机械可推导的字段；`content_map` / `topic_mode` /
   `reader` / `landing` / `angle` / `selection_reason` 等**一律留空**，缺失时闸门会拦
   （`content_map` 缺失是 error）。候选池的 `TODO` 清单由转换器同时产出。
2. **两套不一致的 candidate-pool schema，只有一套是活的。**
   `article_group/prewrite.py::validate_candidate_pool` 要求 ≥10 条候选且字段完全不同，
   **只在测试里被调用**（拿真实批次 daily-013 跑会报 73 个错）；真消费者是
   `article_group/portfolio_gate.py`。转换器按**活的那套**写。这个不一致本身是隐患，
   值得单独处理。
3. **`runs_write_coverage` 的写手识别用变量名启发式**：三个侦察工具做同样的事，
   登记状态却不一致（`topic_scout.py` 因含 `run_dir` 被扫到，另外两个没有）。
   建议把 `RUN_HINTS` 扩到能识别 `--out` / `--out-dir` / `--output` 这类**输出参数**，
   让规则基于行为而非变量名——属改动共享护栏，需 controller 确认。
4. **风险校准推迟中**：见 `runs/2026-09-23/taboo-topics-001/DEFERRED-risk-calibration.md`。
   在此之前风险筛查器当提示器、不当门禁，但「圈题」这一步不许绕过它。
5. **`viral-article-cases` 仍为 0 行**：`account_curated` 被显式判 `eligible_for_case=False`，
   而 controller 已决定「头部账号文章算已验证爆款」——这条要实现需改共享爆款库契约，
   必须单独一次改动 + 独立测试，不能顺手做。

## 六、纪律

- 这套东西**只收集和建议**，不选题、不写作、不发布。
- `--daemon` 常驻调度需**单独授权**。
- 演示真实流程时**不要往真实库里写**，更不要用别人的署名（2026-09-23 出过一次：
  演示用了 `--by controller`，等于伪造署名；事后用 `retract` 全部撤回并留痕，
  `retract` 的 `previous_actor` 字段就是为这类事故留的）。
- 不要跑 `runs/2026-09-17-we-mp-rss-probe/switch_body_source_to_we_mp_rss.py --apply`
  （它会把 env 文件备份进 `runs/`）。
