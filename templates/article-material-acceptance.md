# Article Material Acceptance

> `schema_version: article-material-acceptance-v1`。抓爬交包之后、写作之前，由 Article Task 填写。抓到了不等于够写。

- article_task_id:
- topic_id:
- topic_version:
- production_contract: `article-first-v1`
- brief_contract: `writing-brief-v2`
- title_contract: `title-pack-v1`
- legacy_compatibility: `false`
- core_question:
- reference_shape: `workplace_reality_check | relationship_plot_recap | audience_culture_explainer | adaptation_comparison | viewing_commentary | setting_observation`
- reader_gain_floor: `3 | 5`（与 reference_shape 联动；信息密集型形态为 5）
- intended_claim_kinds: `program_schedule | guest_behavior | audience_psychology | character_motivation | ...`
- decision: `accept | return_research | reselect_angle`
- return_rule: （不接受时必填，写明缺口或换角度）

## Source Capture

每条来源先标抓取形态，再标来源层级。完整保存页面元数据，不等于已经观看视频、取得对话全文或核实场面。

- source_id:
- capture_type: `page_metadata | page_fulltext | video_watched | dialogue_transcript | scene_verified | audience_sample | secondary_discussion`
- declared_source_level: `metadata | scene_notes | fulltext | ...`
- source_capability: `event_exists | character_setup | scene_action | dialogue | audience_reaction | mechanism | outcome`
- locator:
- obtained_facts:

`page_metadata` 不得标为 `fulltext`。

## Acceptance Split

- material_ready_for_draft: `true | false`（事实、定位和来源能力够不够写）
- editorial_value_ready: `true | false`（这些事实能否形成明确读者收益）
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
    - reader_gain: （读者读完能转述的具体信息，不写空泛感受）
  - opening_support_refs: （能进入正文开头的材料定位）
- section_increments: （每个主要段落计划增加的事实/场面/动作/关系/机制/具体背景；至少覆盖正文主要段落）
- explanation_mechanism: （材料能支持的机制，不把推测写成事实）

每条 claim 还要声明 `claim_level` 和 `source_ids`。必须满足
`claim_level <= source_capability`；平台简介不能自动支撑具体场面、对白、观众反应、机制或结果。

`reader_question` 是文章要回答的问题；`reader_takeaway` 不在材料验收阶段填写。
`title_directions` 不属于本记录的写作输入，只有 `content_passed` 后的
`title_pack.json` 才能创建标题方向。材料不足时只返回 `return_research` 或
`reselect_angle`，不得用标题刺激度掩盖证据缺口。
