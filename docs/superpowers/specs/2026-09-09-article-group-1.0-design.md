# Article Group 1.0 总控层设计

## 目标

建立文章组总控层，统一管理选题、定向抓取、材料验收、写作、复核、交付和效果回填。抓取 V5 作为研究子系统接入，由文章组 controller 保持选题与状态控制权。

## 状态与责任

总控层的编辑阶段为 `idea → precheck → candidate → approved`，研究/交付阶段继续兼容现有 V3 的 `researching → material_ready → writing → review → closed`。`postdraft_review`、`prepublication_review` 和 `revision` 作为 review record 的子阶段，不新增 V3 状态；最终内容状态使用现有规范的 `CONTENT_READY`。`returned`、`material_blocked`、`content_blocked` 为回退/阻断状态。只有 controller 可批准、缩题、换题、接受材料和关闭任务。

## 核心契约

每篇以 `topic_id` 和递增版本贯穿 Candidate Card、Topic Card、Fact Card、Crawl V5 产物、稿件、复核记录和 Delivery Record。Candidate Card 是批次候选层，Topic Card 在 `approved` 时冻结；每个版本保留路径、时间和 SHA-256；修改标题或正文必须刷新绑定证据。总控层不得破坏现有 V3/V4/V5 schema，新增字段通过兼容 envelope 或独立总控 manifest 承载。

## V5 接口

文章组向 Crawl V5 传入冻结的核心问题、读者、范围、材料需求、风险和验收条件。V5 回传材料包、来源审计、缺口、恢复动作、失败样本、资源计划和验证报告。V5 不得自行换题、写稿、发布或推进文章组状态。

## 闸门

选题闸门判断阅读价值、重复和风险；材料闸门判断至少两类具体支撑且能支撑首屏；写作闸门运行任务卡兑现检查；复核记录分别检查事实、结构、风格和交付。V3/V4/V5 的验证结果是证据，controller 负责采纳、回退和冻结；最终只产生 `CONTENT_READY`，不产生发布授权。

## 交付与回填

Delivery Record 记录最终标题、Markdown 路径、哈希、字数、复核结果、缺口、R8 和发布授权。发布后效果数据单独回填为观察证据，不能把单篇结果自动升级为规则。

## 实施范围

第一阶段新增总控 manifest、阶段决策记录和 V3/V4/V5 适配器；第二阶段接入真实日更试运行；第三阶段接入效果回填。保持现有抓取 V5、内容门禁和发布未授权边界，不迁移 Vault 或 Hermes 私有状态。总控层先做离线编排与验收，不直接调用外部发布或自动推进人工决策。

## 验收标准

至少一个真实批次完成全链路；同一 `topic_id` 可追溯至候选、抓取、稿件和交付；旧 V3 状态迁移保持兼容，review 子阶段可映射到现有 `review`；失败可回退到正确阶段；V4/V5 验证产物可读回且哈希一致；所有测试通过；`CONTENT_READY`、R8 和发布授权分栏报告。需补充负向验收：题目漂移、topic/version 不一致、关键证据缺口、哈希变化和自动发布字段均必须 fail-closed。
