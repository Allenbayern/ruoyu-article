# Article Material Acceptance

> `schema_version: article-material-acceptance-v1`。抓爬交包之后、写作之前，由 Article Task 填写。抓到了不等于够写。

- article_task_id:
- topic_id:
- topic_version:
- core_question:
- intended_claim_kinds: `program_schedule | guest_behavior | audience_psychology | character_motivation | ...`
- decision: `accept | return_research | reselect_angle`
- return_rule: （不接受时必填，写明缺口或换角度）

## Source Capture

每条来源先标抓取形态，再标来源层级。完整保存页面元数据，不等于已经观看视频、取得对话全文或核实场面。

- source_id:
- capture_type: `page_metadata | page_fulltext | video_watched | dialogue_transcript | scene_verified | audience_sample | secondary_discussion`
- declared_source_level: `metadata | scene_notes | fulltext | ...`
- locator:
- obtained_facts:

`page_metadata` 不得标为 `fulltext`。

## Acceptance Split

- obtained_facts: 已经拿到的具体事实
- supported_analyses: 可以据此作出的分析
- missing_materials: `{gap, needed_for}` 仍缺的场面、对话或作品材料
- unanswerable_questions: 因此无法回答的核心问题

只有节目标题的材料，不能支撑嘉宾行为或观众心理。材料不够就退回，不把写长的责任交给主笔。

## Content Value Plan

文章先根据材料确认正文能提供的事实、场面和解释，不提前规定标题方向：

- article_first_contract_version: `article-first-v1`
- content_value_plan:
  - hard_information_plan:
    - plan_id:
    - kind: `fact | scene | action | relationship | mechanism | specific_context`
    - material_refs: （必须回到本记录的 source_id/locator）
  - opening_support_refs: （能进入正文开头的材料定位）
  - explanation_mechanism: （材料能支持的机制，不把推测写成事实）

`reader_question` 是文章要回答的问题；`reader_takeaway` 不在材料验收阶段填写。
`title_directions` 不属于本记录的写作输入，只有 `content_passed` 后的
`title_pack.json` 才能创建标题方向。材料不足时只返回 `return_research` 或
`reselect_angle`，不得用标题刺激度掩盖证据缺口。
