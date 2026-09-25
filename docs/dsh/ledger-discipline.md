# 账本与门禁纪律（Ledger Discipline）

> 2026-09-21 定，来源：daily-010 两篇成品的独立编读复盘 + daily-011 三轮 L2 复核。
> 本文是**受版本控制**的 canonical 说明；`scripts/run_real_daily_0NN.py` 的 docstring 里
> 有一份同样内容的就地清单（spec 被 gitignore，改不到历史版本，故两者并存）。

## 为什么要有这份东西

daily-010/011 暴露的失败模式是同一类：**规则早就有，但没有任何东西读它**。编辑规则写在
`templates/writing-brief.md` 与 `editorial-learning-playbook.md` 里，账本规则写在简报里，
可门禁只校验记录格式；于是"验证充分但难看"的文章照样出门，而"看起来像证据"的产物
（写死的 `preflight.checks.source_manifest="pass"`、三篇同分的评分卡）长期冒充通过。

这份纪律把三条最容易踩的账本规则**变成机械检查**，并写清修复动作。

## 一、派生跨度即时入账（最容易踩的一条）

**规则**：正文写"由已入账年份推出的具体跨度"（七年后／十年前／三年来／两个月后）时，
必须在**写账本的同一趟**登记该跨度本身或其起止年份。

**为什么**：`assertion_ledger_coverage` 按**跨度文本**判定覆盖，只登记起止年份不算覆盖。
2026-09-21 之前，中文数字跨度不匹配 `_SPECIFIC_SPAN_RE`，被静默从 error 降成 warning；
补上正则后，缺口会真判 error。daily-011 art-001 的「七年后」正是这个坑。

**怎么写**（两种任选）：

```python
# ① 直接进 hard（推荐给"来源里就有这句"的情况）
{"information_id": "i3", "text": "影片原版 2019 年首映，2026 年重映，前后相隔七年",
 "kind": "fact", "body_locator": "p2",
 "source_refs": ["src-x"], "source_locators": ["来源: 首映与重映年份"],
 "independence_key": "span-2019-2026"}

# ② 模块级声明，引擎在同一趟自动补进 hard_information（标 derived=True）
DERIVED_SPANS = {
    "art-001": [
        {"text": "影片原版 2019 年首映，2026 年重映，七年后重回大银幕",
         "body_locator": "p2",
         "source_refs": ["src-x"],
         "source_locators": ["来源: 首映年份"],
         "note": "由已入账的首映年份与重映日期推出"},
    ],
}
```

**机械执行**：`scripts/daily_engine.py::content_record` 调用
`assertion_ledger_coverage.apply_derived_spans`，补完仍有缺口就打印可执行的提示
（含 `body_locator`、原文块位置、claim）并 `SystemExit(1)`——在 `content_record` 阶段
当场失败，不等 `gates`。缺口同时写进 `content-fidelity.json` 的 `ledger_span_gaps` 留痕。

**泛化表述不受此限**：这些年／多年来／近年来／一直以来仍是 warning（008 那次校准不变）。

**段号口径**：`body_locator` 只数正文段落（标题不占号）。`assertion_ledger_coverage`
里有两个函数分别对应两种口径，别混：

| 函数 | 口径 | 用途 |
|---|---|---|
| `split_paragraphs()` | 原文块序号（标题、空块占号） | 报告里定位原文 |
| `ledger_paragraphs()` | 只数正文段落 = 账本 `p_n` | 回填 `body_locator` |

## 二、来源抓取等级按来源声明

`SOURCES[src]` 支持 `capture_type` / `declared_source_level`（缺省 `page_fulltext` /
`fulltext`）。正文未渲染、只有检索摘要的来源必须声明为 `page_metadata` / `metadata`——
`material_acceptance` 只在"声明 fulltext 且抓取属于全文类"时放行，等级写高了，它就会
放行这条来源去承载细节级断言（daily-011 L2 反复判 major 的就是这个）。

来源文件被回补／重抓时，在 `SOURCES` 里声明 `recapture_reason` 与
`previous_artifact_sha256`；引擎写进 `source-manifest`。`sources/` 不在 `.before`
快照通道内、也不被 `evidence_rebind` 覆盖，不留痕就无法区分"补录"与"伪造"。

## 三、编辑门禁要的两个定位符 + 编读记录

只对**声明了**的篇硬拦（缺省只报警，避免主观意见泛滥成第二个没人填的栏）：

```python
OWN_ANALYSIS_LOCATORS = {"art-001": "p7"}      # 本文自己的判断段，不能是"他说/在他看来"起句
SUBJECT_CONTENT_LOCATORS = {"art-003": "p4"}   # 让读者知道"这部作品是什么"的那句
EDITORIAL_DECLARATIONS = {
    "art-001": {"own_analysis": True},
    "art-003": {"own_analysis": True, "subject_content": True},
}
```

`editor_read` 阶段排在 `content_record` 之后、`reviews_and_delivery`（冻结）之前：
编辑意见一旦在冻结后提出，每改一句正文都会让标题包 / L2 approve / 渲染的哈希全部失效
（daily-011 因此多跑了两轮 L2）。

## 四、相关机械检查一览（2026-09-21 落地）

| 检查 | 位置 | 不通过会怎样 |
|---|---|---|
| 派生跨度入账 | `content_record` → `apply_derived_spans` | 当场 SystemExit(1)，缺口留痕 |
| 门槛跨度/断言覆盖 | `review/gates/assertion-coverage.json` | 具体跨度缺口 = error |
| 来源清单真比对 | `run_gates.check_source_manifest_integrity` → `preflight-report.json` | `fail`（缺文件/哈希不符；无清单记 `not_run`，不改写整体状态） |
| 来源等级一致 | `material_acceptance` / `claim-source-check` | 等级不足即拒 |
| 编辑质量五项 | `review/gates/editorial-gate.json` | 声明项缺失 = error；其余 = warning |
| 评分卡诚实标注 | `article_group/scoring_card.py` | 卡自述 `measured=false`，`final_review` 记人工裁决项 |

## 五、边界（别越界）

- 这些检查只判**读者面结构与承诺兑现**，不重审证据（那是 L2 的活）。
- 机械检查是**报警器**，判决仍归独立编读（`editor_read`）与 L2；不要用机械规则替代判断。
- 不改已交付批次的产物来"修复"历史：改 content-fidelity 会经 `title-pack.content_fidelity_ref`
  重算标题包哈希，从而作废已记录的 L2 approve。历史批次留给下一批当教训。
