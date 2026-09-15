# Writing Brief

> 本 brief 只负责把文章写成一篇自洽的正文。正式标题不属于写作契约，正文通过
> `content_review` 后，才创建独立的 `title_pack.json`。

- article_id:
- candidate_id:
- production_contract: `article-first-v1`
- brief_contract: `writing-brief-v2`
- title_contract: `title-pack-v1`
- legacy_compatibility: `false`
- article_first_contract_version: `article-first-v1`
- state: `brief_locked | drafting_content | content_review | content_passed`
- run_profile: `two_article_daily | three_slot_controlled`
- slot: `A | B | C`（由 run_profile 决定）
- body_draft_path: `drafts/<article_id>/body_draft.md`
- content_fidelity_path: `review/<article_id>/content-fidelity.json`
- title_pack_path: （仅 `content_passed` 后填写：`review/<article_id>/title_pack.json`）
- delivery_path: （仅选定标题并通过终审后填写：`delivery/<article_id>/delivery.md`）
- editorial_lessons_ref: `docs/codex/editorial-lessons.md`（历史经验参考；不替代当前来源核验）

## Content Contract

- core_object: （具体作品、人物、场面或事件；正文始终指向它）
- reader_question: （文章要回答的一个阅读问题，不是标题承诺）
- target_reader: （具体读者，不写“所有人”）
- article_type: `资讯 | 市场观察 | 人物评论 | 文化评论 | 作品评论 | 其他`
- reference_shape: `workplace_reality_check | relationship_plot_recap | audience_culture_explainer | adaptation_comparison | viewing_commentary | setting_observation`
- reader_gain_floor: `3 | 5`（信息密集型形态为 5；设定观察为 3）
- one_sentence_scope: （本篇只处理什么）
- conflict_or_gap: （人物选择、关系冲突、具体反差或信息缺口）
- reader_value_hypothesis: （写作前的价值假设；成稿获得感以复核记录为准）
- emotion:
- narrative_frame:
- current_trigger_or_evergreen_reason:
- out_of_scope:
  - （未确认事实、动机、票价、传播数据、人物心理等不得写入正文的项目）

## Content Value Spine

正文按“对象 → 证据 → 解释 → 读者判断”展开，不按标题预设答案。

- hard_information_plan:
  - information_id:
  - kind: `fact | scene | action | relationship | mechanism | specific_context`
  - text: （准备写进正文的具体信息，不写空泛感受）
  - material_refs: （来源/材料 ID 与定位）
  - planned_body_locator: （预计进入哪一段；成稿后须改成实际定位）
- opening_support_refs: （能让开头直接落地的事实、场面或动作证据）
- reference_shape_material_fit: （逐条说明当前材料如何满足所选形态；不满足则返回补证或换角度）
- explanation_mechanism: （为什么这些事实会形成当前的人物/关系/现实问题）
- must_prove_claim_ids:
- must_not_say:
- attribution_requirements:
- unsupported_scenario_boundary: （来源没有提供的场景、动机、结果或观众反应）

## Body Structure

- opening_scene: （正文首段用具体对象、动作、场面或事实开始；不先写抽象判断）
- sections:
  - section_id:
  - working_question: （本节推进的子问题）
  - planned_gain_kind: `fact | scene | action | relationship | mechanism | specific_context | judgment`
  - planned_material_refs:
  - planned_body_locator:
- ending_destination: （正文最后回到哪个具体选择、关系或判断）
- ending_interaction_question: `读者互动问句 | 结论性收尾 | 不设问（写明理由）`

正文文件 `body_draft.md` 不写 H1，不放临时标题，也不放标题候选、标题兑现计划或标题自评分。
必要的小节使用 H2；删除任何标题后，读者仍应识别对象、问题、解释和判断。

## Content Review Handoff

- content_review_result: `pass | return_article | return_material`
- content_fidelity_path: `review/<article_id>/content-fidelity.json`
- reader_takeaway: （成稿复核后读者真正能带走的判断；不得提前冒充标题目标）
- reader_takeaway_locator: （正文实际段落定位）
- content_return_reason:
- content_return_route: `content_revision | material_return`
- core_judgment: （正文里读者能转述的一个主判断）
- judgment_basis:
  - locator:
  - fact_or_scene:
  - explanation:
- judgment_strength: `supported | too_strong | too_weak`
- reader_can_repeat: `true | false`
- unsupported_scenario_boundary: （现有材料不能支持的场面、动机、结果或观众反应）
- section_increments: （每个主要段落新增的 `fact | scene | action | relationship | mechanism | specific_context | judgment`）
- section_increment_check: （删掉该段后读者会少知道哪一件事；不能只写“更有共鸣”）

只有 `content_review_result=pass` 才能创建标题包。标题包只能引用已通过的
`body_draft.md` 与已确认材料；如标题需要新增事实，必须退回正文复核或材料验收。

## Post-content Packaging Handoff

- title_pack_path: `review/<article_id>/title_pack.json`
- title_pack_result: `selected | return_article | return_material`
- title_review_path: `review/<article_id>/title-pack-review.json`
- title_review_result: `pass | return_article | return_material`（成标题复核后填写）
- delivery_path: `delivery/<article_id>/delivery.md`
- selected_title_id: （只在标题包选定后填写）
- packaging_return_reason: （标题包返回时必填）

标题包最多保留三条方向，也可以为零条。它不得新增正文事实、修改 body 或要求
自动补写；选定标题与正文组合后，`delivery.md` 才出现正式 H1。

## Topic Timing And History

- freshness_window: `same-day | fermenting-1-3d | revival`
- topic_mode: `release_event | character | craft | audience | culture | revisit | market`
- event_cluster_id:
- remove_timestamp_test: `pass | risk | fail`
- historical_dedupe_ref:
- same_work_recent_check: `pass | override | blocked`
- title_near_duplicate_check: `pass | override | blocked`（只作历史去重，不生成当前标题）
- new_angle_statement: （相对历史选题新增的事实、场面、关系或问题）
- override_reason:

## Evidence Boundaries

- 写作输入只接收结构化 extracts/fact-card；不得把原始 HTML 直接作为写作上下文。
- 热榜、标题、平台标签只能作发现信号，不能证明热度、动机、共识或因果。
- 来源和证据放在 review/material artifacts；正文不写审稿过程、内部状态或来源自证。
- five_gates_ref: `templates/social-topic-five-gates.md`
- five_gates_result: `PASS | CONDITIONAL | FAIL | N/A（影视文章）`
- compliant_angle:
- conditional_writing_controls:
- fail_boundary:
- must_attribution:
- must_disclaimers:
- must_omit_privacy:
- must_not_predetermine_liability:
- original_declaration: `no | yes（仅获授权）`
