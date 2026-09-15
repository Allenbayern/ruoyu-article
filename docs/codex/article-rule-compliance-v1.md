# Article Rule Compliance v1

状态：v1 设计说明与首轮实现已接入生产门禁；当前批次人工可读性待复核  
更新：2026-09-14  
适用范围：文章组新 run；历史 run 只读兼容。

本文定义文章组文体、材料分层、来源能力和可读性规则的证据契约，并记录首轮实现的状态矩阵。它不替代 Vault 内容边界、文章组运行契约、独立复核或发布授权。

## 1. 目标与非目标

本契约必须同时证明两件事：系统按规则执行，当前文章留下了可回读的执行证据。

它负责判断：

- 文章声明的文体是否合法且在所有阶段一致；
- 来源角色是否覆盖该文体的最低材料要求；
- claim 是否超过来源叙事能力或文体权限；
- 删除来源说明后，正文是否仍然具有对象、冲突、事实和判断；
- 人工可读性判断是否绑定当前文章和当前删来源版本。

它不负责保证点击率、预测爆款、替代人工编辑、授权发布或把参考文章变成事实来源。

## 2. 正式文体枚举

`article_mode` 只能是以下四种值：

| 文体 | 最低材料 | 可写范围 | 不得伪装成 |
|---|---|---|---|
| `setting_observation` | `official_fact` 或 `mechanism` | 设定、关系机制、制作选择、宣发观察、读者问题 | 观后感、报道 |
| `viewing_commentary` | `scene` 或 `review`，且有真实观看或独立评论依据 | 场面、动作、对白、观看体验、评论判断 | 官方简介扩写 |
| `reported_feature` | `interview` 或 `现场`，且有原话或现场行为 | 人物、现场、原话、背景和事件推进 | 资料说明 |
| `fact_explainer` | `official_fact`、`cross_check` 或同等事实材料 | 事实整理、背景解释、有限推论 | 观后评论 |

文体不是标题方向。文体必须在选题预检阶段确定，并在 `batch.json`、writing brief、task card、material pack 和 source manifest 中保持一致。

## 3. 材料角色与来源声明

每个来源必须声明：

```json
{
  "source_role": "official_fact",
  "supports_mode": ["setting_observation", "fact_explainer"],
  "cannot_support": ["specific_scene", "dialogue", "viewing_experience", "audience_consensus", "ending"],
  "source_capability": "character_setup"
}
```

正式来源角色：

```text
official_fact
mechanism
scene
review
interview
现场
cross_check
audience_reaction
```

最低覆盖规则：

```yaml
setting_observation: [official_fact|mechanism]
viewing_commentary: [scene|review]
reported_feature: [interview|现场]
fact_explainer: [official_fact, cross_check]
```

缺少 `cannot_support`、`supports_mode` 或 `source_capability` 时，来源声明不完整，不能进入 `rule_compliance: PASS`。

## 4. Claim 权限

Claim 同时受来源能力和文章文体限制：

```yaml
setting_observation:
  allowed: [event_exists, character_setup, mechanism]
  forbidden: [scene_action, dialogue, viewing_experience, audience_consensus, outcome]

viewing_commentary:
  allowed: [event_exists, character_setup, scene_action, dialogue, mechanism, outcome]
  requires: [scene|review]

reported_feature:
  allowed: [event_exists, character_setup, scene_action, dialogue, mechanism, outcome]
  requires: [interview|现场]

fact_explainer:
  allowed: [event_exists, character_setup, mechanism]
  forbidden: [viewing_experience, audience_consensus]
```

每条主要 claim 必须有：

```json
{
  "claim_id": "claim-03",
  "claim_level": "character_setup",
  "body_locator": "p4",
  "source_refs": ["src-001"],
  "source_locators": ["official page: synopsis paragraph 1"]
}
```

失败条件包括：来源能力不足、文体不允许、缺来源定位、claim 无法回到正文，或官方简介被用于支持具体场面、对白、观后感、普遍反应和结局。

## 5. 去来源可读性

系统生成但不覆盖原稿：

```text
review/{article_id}/source-stripped.md
review/{article_id}/source-stripped-readability.json
```

机器处理固定删除或标记这些元话语：`官方页面`、`官方简介`、`来源`、`材料`、`目前能确认`、`当前资料`、`证据边界`。机器只生成版本、检查结构并计算 hash，不代替语义判断。

人工复核记录必须包含：

```json
{
  "article_id": "art-001",
  "article_mode": "setting_observation",
  "mode_check": "PASS",
  "material_layer_check": "PASS",
  "official_boundary_check": "PASS",
  "source_stripped_readability": "PASS",
  "reviewer_id": "",
  "reviewer_role": "human_editor",
  "reviewed_artifact_sha256": "",
  "reviewed_source_stripped_sha256": "",
  "reviewed_at": "",
  "publication_authorization": "not_authorized"
}
```

人工判断的最低问题是：删掉来源说明后，读者是否仍能识别对象、冲突、至少一条硬事实和文章判断。只剩资料摘要时，必须返回 `evidence_summary_disguised_as_article`。

## 6. 状态矩阵

| 状态 | 声明 | 材料层 | 官方边界 | 删来源机器检查 | 人工可读性 | 是否可进入正文 | 是否可交付 |
|---|---|---|---|---|---|---|---|
| `UNVERIFIED` | 缺失或未执行 | 未知 | 未执行 | 未生成 | 未执行 | 否 | 否 |
| `PASS` | 一致 | 覆盖 | 通过 | 通过 | 通过 | 是 | 仍需其他门禁 |
| `PENDING` | 基本完整 | 基本完整 | 未决 | 已生成 | 待人工 | 否 | 否 |
| `FAIL` | 不一致或非法 | 不覆盖 | 违规 | 失败 | 失败 | 否 | 否 |
| `RETURN_MATERIAL` | 合法但材料不足 | 不足 | 无法判断 | 不适用 | 不适用 | 否 | 否 |
| `CLOSE_AS_UNFIT` | 文体或题目不成立 | 无法补足 | 无法补足 | 不适用 | 不适用 | 否 | 否 |

批次层状态只有在所有文章均为 `PASS` 后才能写入：

```yaml
article_rule_compliance: PASS
```

任一文章为 `UNVERIFIED`、`PENDING`、`FAIL`、`RETURN_MATERIAL` 或 `CLOSE_AS_UNFIT`，批次只能标记对应状态，不能宣称新规则已落实。

## 7. 门禁接入

`preflight` 检查声明一致性、来源角色覆盖、字段完整性和 claim 能力；`final_review` 重新读取当前正文、删来源版本、人工记录和 hash。两处都必须检查，任何一处缺失或漂移均失败关闭。

最终报告拆分：

```yaml
article_rule_compliance: PASS|PENDING|FAIL|UNVERIFIED
content_result: PASS|PENDING|FAIL
evidence_result: PASS|PENDING|FAIL
governance_result: PASS|PENDING|FAIL
publication_authorization: not_authorized
```

`rule_compliance: PASS` 不等于文章已获发布授权。

## 8. 反例测试清单

实现必须拒绝以下输入：

- 非法文体：`craft_observation`、`character_situation`；
- 只有官方简介却声明 `viewing_commentary`；
- 官方简介 claim 写入具体镜头、对白、观众普遍反应或结局；
- 来源缺少 `cannot_support` 或 `supports_mode`；
- brief、task card、batch 和 material pack 的文体不一致；
- 删除来源说明后只剩资料摘要；
- 事实、场面或判断没有来源定位；
- 正文、删来源版本或人工复核记录 hash 漂移；
- 历史 run 缺少新字段却被误判为当前规则通过。

## 9. 当前批次迁移要求

当前两篇文章统一声明为 `setting_observation`。需要补齐来源角色、文体字段、claim 定位、删来源版本和人工复核。涉及彼得的句子必须收窄到官方设定能支持的范围，不能把“世界不再记得彼得”写成“彼得失去记忆”，也不能把关系推演写成已发生的具体场面。

新门禁、反例测试、当前文章 hash 和机器证据已经生成；在人工可读性记录完成前，当前批次只能标记：

```yaml
article_rule_compliance: PENDING
publication_authorization: not_authorized
```
