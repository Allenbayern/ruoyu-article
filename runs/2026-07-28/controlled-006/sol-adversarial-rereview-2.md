# controlled-006 Sol 微复核（仅 B-M02、C-B01、C-M01；本地证据）

- decision: **approve**
- publication: **未授权；本复核不构成发布批准。**
- scope_reviewed: 仅 `B-M02`、`C-B01`、`C-M01`；检查 `articles/B,C/article-draft.md`、对应 plain/gate/evidence pack、`source-manifest.json` 及本地验证。
- verification_method: 未访问网络。独立运行 `validate_source_manifest`、A/B/C `validate_claim_locators` 与 `validate_batch`，结果均为 `[]`；plain 与当前 draft 的目标表述一致。

## 逐项结论

| ID | 结果 | 一句证据 |
|---|---|---|
| B-M02 | fixed | B 第29行已明确“公开报道只确认了动作和日期，没有披露片方内部怎么算这笔账”，删除了“不是浪漫/档期计算”“更值钱”“往前抢”等将提档归因为已证实内部收益计算的表述。 |
| C-B01 | fixed | C evidence pack 已将 `src-C02`、`src-C03` 标为 `confirmed-primary`、`src-C01` 标为 `attributed-secondary`；正文以 QQ潮新闻与新浪声明交叉承载上映仅1天、5875.9/5866.3、三国16天/8.1/近千人三年/8000万及《年会2》提档等核心事实，并把六部、8145万、0.8%排片和“小透明”等明确限定为汇总报道补充，注明本地无第二份原始排片表。 |
| C-M01 | fixed | C 已删除“集体出逃”“系统性问题”“头部垄断导致没有生存空间”等确定机制，改为窗口稀缺、撤档可读作求生动作及明确标注“不是已被单篇报道证明的铁律”的风险链条。 |

## 非发现与边界

- 未发现这三个既有 finding 在本轮修复后仍需保留的证据性缺陷。
- `src-C01` 中汇总性市场条目仍不应升级为独立产业统计或确定机制；当前正文已作来源归属和本地证据缺口说明，故不构成 C-B01/C-M01 未修复。
- 本轮未新增 finding，未扩大复核范围。

本结论仅为上述三项已修复的独立复核证据；发布、合并或其他不可逆决定仍由控制器负责。
