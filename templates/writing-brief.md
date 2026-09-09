# Writing Brief

- article_id:
- candidate_id:
- state: `R5 brief-ready`
- run_profile: `two_article_daily | three_slot_controlled`
- slot: `A | B | C`（由 run_profile 决定）
- editorial_lessons_ref: `docs/codex/editorial-lessons.md`（历史经验参考；不替代当前来源核验或 canonical 规则）

## Narrative Core

- Primary Atom:
- Reader Intent:
- reader_share_expression:
- Human Anchor:
- Conflict:
- Emotion:
- Gap:

## Promise And Route

- title_promise:
- title_candidates:
  - （候选标题：写清具体冲突/反差、人物或画面入口、悬念/问题入口等方向；数量按题材决定，不以凑数为目的）
- title_candidate_matrix:
  - candidate_id:
    - title:
    - distinct_angle: （与其他候选相比新增的事实、人物关系或读者问题；只换措辞不算新角度）
    - evidence_ref: （支持标题对象、动作或数字的 source ID/定位）
    - opening_fulfillment_plan: （首屏如何兑现标题承诺，写出事实锚点或段落功能）
    - selected: `yes | no`
- title_review_target: （最终标题必须兑现的点击承诺；不得靠正文没有的数字或结论；记录首屏兑现位置）
- title_qc_ref:
- title_qc_draft_path:
- title_qc_draft_sha256:
- selected_title_id:
- title_selection_note: （现有独立复核者先看当前正文和隐藏自评分/推荐顺序的候选，再说明推荐及淘汰理由；可以全部退回。分数不代替编辑判断）
- opening_fulfillment_locator:
- Hook:
- Narrative Frame:
- Opening_scene: （首屏用可核验的具体内容开始回答标题；仅复述页面标签、日期或再次提问不算兑现。观众反应仅在有证据时写，禁用通稿式项目自述）
- Reversal_beats: （可选；只填写正文和来源真正支持的转向，不足三项就留空，不为满足数量制造反转）
  - beat_1: （开头反差/第一处信息差；无则留空）
  - beat_2: （中段事实或人物视角转向；无则留空）
  - beat_3: （结尾转向；无则留空）
- Skeleton:
- ending_destination:
- ending_interaction_question: `读者互动问句 | 结论性收尾 | 不设问（写明理由）`（由正文自然收束决定；问句必须承接本文问题，不以评论率或增长目标强制设置）

## Topic Timing And History

- freshness_window: `same-day | fermenting-1-3d | revival`
- topic_mode: `release_event | character | craft | audience | culture | revisit | market`
- event_cluster_id: （与候选卡一致；同一事件流或簇不得借不同作品名重复进入批次）
- current_trigger_or_evergreen_reason: （same-day/fermenting 记录当前触发与观察时间；revival 记录可脱离当天热度仍成立的读者问题）
- remove_timestamp_test: `pass | risk | fail`（删掉日期、热榜或“今天”后仍剩下什么）
- historical_dedupe_ref: （指向历史选题/同作品/同事件簇的比较记录；引用 `docs/codex/editorial-lessons.md` 的相关条目时同时给出具体历史 run/path）
- same_work_recent_check: `pass | override | blocked`
- title_near_duplicate_check: `pass | override | blocked`
- new_angle_statement: （相对历史选题新增的事实、场景、人物关系或读者问题；仅换标题不能作为放行理由）
- override_reason: （仅 `override` 时填写理由、对比批次和核验人）

## Concrete Support Plan

- support_1: （具体人物动作、现场/页面细节、时间线、数字或关系；填写 source ID、locator 和计划写入段落）
- support_2: （与 support_1 类型不同的具体支撑；填写 source ID、locator 和计划写入段落）
- additional_support: （可选；不要为了字数添加同义复述）
- unsupported_scenario_boundary: （来源没有提供的场景、动机、结果或观众反应；明确不写或切换为可证实的事实锚点）

## Style Field

- emotion_valve: `0 | 1 | 2 | 3`
- narrative_distance: `near | middle | far`
- language_density: `high | medium | low`
- conflict_visibility: `explicit | implicit`
- sentence_constraints:

## Evidence Boundaries

- **动笔前核验**：写作前必须 web_search 主题 + 关键实体，回写事实包；信号只作选题入口（2026-08-14 空枪/沈腾案例硬纪律）。
- **写作输入**：worker 只接收结构化 extracts/fact-card；不得把原始 HTML 直接作为写作上下文。
- **标题与首屏关联**：标题候选、最终标题和首屏兑现必须引用同一批当前事实；改稿后重绑 title-qc 的 draft path、SHA-256 与首屏 locator。
- must_prove_claim_ids:
- must_not_say:
- attribution_requirements:
- backup_switch_condition:

## Compliance Boundary

- five_gates_ref: `templates/social-topic-five-gates.md`
- five_gates_result: `PASS | CONDITIONAL | FAIL | N/A（影视文章）`
- compliant_angle: （`CONDITIONAL` 且推荐 `A | B | C` 时，填入候选卡中的可追溯处理说明）
- conditional_writing_controls: （来源/事实核验、隐私最小化、责任表述和标题约束；不得因改写自动视为合规）
- fail_boundary: （`FAIL` 不进入 `A | B | C`，只可 `Archive | Reject | Wait` 留档）
- must_attribution:
- must_disclaimers:
- must_omit_privacy:
- must_not_predetermine_liability:
- title_max_length: `30`
- original_declaration: `no | yes（仅获授权）`
