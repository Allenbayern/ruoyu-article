# Editorial Pipeline V5 Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 在文章组仓库新增一个离线、证据优先的 V5 自适应反馈层，记录实验并谨慎归因，学习失败样本，生成受边界约束的生命周期、DNA、配额、策略和资源建议。

**Architecture:** V5 放在独立的 article_group/v5/ 包中，使用自己的封闭 JSON envelope 和 schema，避免改动 V3/V4 的冻结词表。每个纯函数只接收显式 JSON/文本输入并返回可验证产物；一个离线 orchestrator 负责从显式 run 目录组装八个产物、拒绝覆盖并读回。V3 只增加附加 adapter，V5 不替代已有审核或交付授权。

**Tech Stack:** Python 3.14, pytest, jsonschema, pathlib, 标准库 statistics/hashlib/datetime；无网络、无 Vault、无新增依赖。

**Spec:** docs/superpowers/specs/2026-09-09-editorial-pipeline-v5-design.md

## Global Constraints

- V3 状态词表保持 idea → precheck → approved → researching → material_ready → writing → review → closed，并保留 returned。
- CONTENT_READY 只表示材料/稿件已达到交给真人处理的状态；publication_authorization 固定为 not_authorized。
- 发现信号、社交反应和历史草稿不能单独证明事实；V5 不自动选题、换题、发布或晋级策略。
- 指标缺失用 null + *_status=unavailable 表示，绝不以零填充。
- 所有自动建议均为 auto_apply=false 的 controller 输入；正式配额和策略状态必须显式采纳。
- 每个新函数先写一个会失败的测试并运行确认失败，再写最小实现并运行通过；不得修改用户已有的 V4 报告改动。
- 所有运行写入显式 runs/<date>/<run-id>/v5/ 或测试临时目录；不写 Vault，不保存 cookie、token、API key、连接串或 HTML。

## 文件地图

- Create article_group/v5/__init__.py: V5 公开导出。
- Create article_group/v5/contracts.py: V5 词表、封闭 envelope、时间/hash/授权边界。
- Create article_group/v5/experiment.py: 单变量实验记录、处理/对照观察和受限归因。
- Create article_group/v5/lifecycle.py: 内容生命周期和状态转移证据。
- Create article_group/v5/dna.py: 显式/派生文章 DNA 特征。
- Create article_group/v5/failure.py: 失败样本分类和缺失指标处理。
- Create article_group/v5/quota.py: 四周历史的有界动态配额建议。
- Create article_group/v5/strategy.py: 版本化策略记录与 controller 晋级门槛。
- Create article_group/v5/resources.py: 抓取/补证/Sol 复核预算建议。
- Create article_group/v5/integration.py: V3 状态机的 V5 附加 adapter。
- Modify article_group/editorial_pipeline_v3.py: 延迟导出 validate_v5_transition_context，保持旧接口。
- Create article_group/v5/verification.py: 八产物离线编排、验证、幂等写入和读回。
- Create scripts/article_group_v5.py: 八个子命令和显式 run/output 参数。
- Create schemas/editorial-pipeline-v5/v5-artifact.schema.json: V5 envelope schema。
- Create tests/test_v5_contracts.py, tests/test_v5_experiment.py, tests/test_v5_lifecycle.py, tests/test_v5_dna_failure.py, tests/test_v5_quota_strategy.py, tests/test_v5_resources_integration.py, tests/test_article_group_v5_cli.py。
- Create tests/fixtures/v5/controlled-001/: 仅合成、脱敏的 V5 运行输入。
- Create docs/codex/editorial-pipeline-v5.md and update README.zh-CN.md: 使用方式、字段、边界和验收结果。

---

### Task 1: V5 contracts and closed artifact envelope

**Files:**
- Create article_group/v5/__init__.py
- Create article_group/v5/contracts.py
- Create schemas/editorial-pipeline-v5/v5-artifact.schema.json
- Test tests/test_v5_contracts.py

**Interfaces:**
- new_artifact_envelope(schema_version: str, run_id: str, payload: Mapping[str, Any], *, generated_at: str) -> dict[str, Any]
- validate_v5_artifact_envelope(value: Mapping[str, Any], expected_schema: str, *, run_id: str) -> list[str]
- payload_of(value: Mapping[str, Any]) -> Mapping[str, Any]
- Public constants: ARTIFACT_SCHEMA_VERSIONS, LIFECYCLE_STATES, EXPERIMENT_DESIGNS, FAILURE_TYPES, STRATEGY_STATES, PUBLICATION_AUTHORIZATION.

- [ ] Step 1: Write the failing tests

~~~python
def test_v5_envelope_round_trip_and_closed_top_level():
    artifact = new_artifact_envelope(
        "v5-experiment-record-v1", "v5-fixture-001", {"x": 1},
        generated_at="2026-09-09T10:00:00+08:00",
    )
    assert validate_v5_artifact_envelope(
        artifact, "v5-experiment-record-v1", run_id="v5-fixture-001"
    ) == []
    assert "invalid:top_level" in validate_v5_artifact_envelope(
        {**artifact, "publication_authorization": "authorized"},
        "v5-experiment-record-v1", run_id="v5-fixture-001",
    )

def test_v5_constants_keep_publication_and_missing_metric_boundaries():
    assert PUBLICATION_AUTHORIZATION == "not_authorized"
    assert "observational" in EXPERIMENT_DESIGNS
    assert "insufficient_data" in FAILURE_TYPES
    assert STRATEGY_STATES == (
        "provisional", "testing", "supported", "deprecated", "retired"
    )
~~~

- [ ] Step 2: Run the tests to verify they fail

Run: .venv/bin/pytest -q tests/test_v5_contracts.py

Expected: FAIL because the V5 package and constants do not exist.

- [ ] Step 3: Implement the minimal envelope and schema

Use the five exact top-level keys schema_version, run_id, generated_at, input_hashes, payload; reject unknown schema/run/timestamp/hash/top-level values and recursively reject any nested authorization other than not_authorized. Keep V4 contracts untouched.

- [ ] Step 4: Run the tests to verify they pass

Run: .venv/bin/pytest -q tests/test_v5_contracts.py tests/test_v4_contracts.py

Expected: PASS with both V5 and frozen V4 contract tests green.

- [ ] Step 5: Commit

~~~bash
git add article_group/v5/__init__.py article_group/v5/contracts.py schemas/editorial-pipeline-v5/v5-artifact.schema.json tests/test_v5_contracts.py
git commit -m "feat: add v5 artifact contracts"
~~~

### Task 2: Experiment records and cautious attribution

**Files:**
- Create article_group/v5/experiment.py
- Test tests/test_v5_experiment.py

**Interfaces:**
- build_experiment_record(*, experiment_id: str, run_id: str, topic_id: str, topic_version: int, hypothesis: str, changed_variable: str, controls: Sequence[str], metrics: Sequence[str], design: str, treatment_ids: Sequence[str], control_ids: Sequence[str], week_start: str, generated_at: str, fixed_publish_window: Mapping[str, Any] | None = None, distribution_conditions: Mapping[str, Any] | None = None) -> dict[str, Any]
- validate_experiment_record(record: Mapping[str, Any]) -> list[str]
- assess_experiment(record: Mapping[str, Any], observations: Sequence[Mapping[str, Any]], *, controller_decision: str | None = None) -> dict[str, Any]

- [ ] Step 1: Write the failing tests

~~~python
def test_experiment_requires_one_changed_variable_and_controls():
    record = build_experiment_record(
        experiment_id="exp-001", run_id="run-001", topic_id="topic-001",
        topic_version=1, hypothesis="动作冲突提高点击", changed_variable="title_angle",
        controls=["topic", "length", "publish_window"],
        metrics=["ctr", "completion_rate"], design="same_topic_different_title",
        treatment_ids=["a-2"], control_ids=["a-1"], week_start="2026-09-07",
        generated_at="2026-09-09T10:00:00+08:00",
    )
    assert validate_experiment_record(record) == []

def test_observations_do_not_become_causal_without_controlled_confirmation():
    result = assess_experiment(_record(), _same_topic_observations())
    assert result["attribution_status"] == "observational"
    assert result["causal_claims"] == []

def test_confounding_is_reported_when_platform_and_window_change():
    result = assess_experiment(_record(), _confounded_observations())
    assert result["attribution_status"] == "confounded"
    assert "platform" in result["confounders"]
~~~

- [ ] Step 2: Run the tests to verify they fail

Run: .venv/bin/pytest -q tests/test_v5_experiment.py

Expected: FAIL because article_group.v5.experiment is absent.

- [ ] Step 3: Implement one-variable validation and attribution statuses

Require disjoint treatment/control IDs, non-empty controls and metrics, valid week/date and design. Compare only recorded observations. Return observational, inconclusive, confounded, or supported_under_design; use supported_under_design only with the minimum three observations per arm, same topic/type and platform/window/distribution controls, plus approve_causal_support. Never emit a boolean causal claim.

- [ ] Step 4: Run the tests to verify they pass

Run: .venv/bin/pytest -q tests/test_v5_experiment.py tests/test_v5_contracts.py

Expected: PASS.

- [ ] Step 5: Commit

~~~bash
git add article_group/v5/experiment.py tests/test_v5_experiment.py
git commit -m "feat: add v5 controlled experiment attribution"
~~~

### Task 3: Content lifecycle with explicit publication evidence

**Files:**
- Create article_group/v5/lifecycle.py
- Test tests/test_v5_lifecycle.py

**Interfaces:**
- build_content_lifecycle(*, article_id: str, run_id: str, generated_at: str, state: str = "draft") -> dict[str, Any]
- advance_content_lifecycle(record: Mapping[str, Any], events: Sequence[Mapping[str, Any]], *, controller_decision: str | None = None) -> dict[str, Any]
- validate_lifecycle_record(record: Mapping[str, Any]) -> list[str]

- [ ] Step 1: Write the failing tests

~~~python
def test_draft_cannot_become_published_without_external_publication_event():
    result = advance_content_lifecycle(_draft(), [])
    assert result["payload"]["state"] == "draft"
    assert "publication_event_required" in result["payload"]["blockers"]

def test_published_observation_can_become_rising_but_evergreen_needs_controller():
    rising = advance_content_lifecycle(_published(), _rising_events())
    assert rising["payload"]["state"] == "rising"
    evergreen = advance_content_lifecycle(
        rising, _stable_events(), controller_decision="approve_evergreen"
    )
    assert evergreen["payload"]["state"] == "evergreen"

def test_archived_content_has_learning_only_action():
    result = advance_content_lifecycle(
        _published(), [], controller_decision="archive"
    )
    assert result["payload"]["state"] == "archived"
    assert result["payload"]["next_action"] == "retain_learning_only"
~~~

- [ ] Step 2: Run the tests to verify they fail

Run: .venv/bin/pytest -q tests/test_v5_lifecycle.py

Expected: FAIL because the lifecycle module is absent.

- [ ] Step 3: Implement forward-only state transitions

Accept only the eight states. Require an event with event_type=published, published_at, and platform before published; use recorded observation trends for stable, rising, and decaying; require approve_evergreen or archive for terminal semantic states. Return blockers and evidence references rather than silently advancing.

- [ ] Step 4: Run the tests to verify they pass

Run: .venv/bin/pytest -q tests/test_v5_lifecycle.py tests/test_editorial_pipeline_v3.py

Expected: PASS.

- [ ] Step 5: Commit

~~~bash
git add article_group/v5/lifecycle.py tests/test_v5_lifecycle.py
git commit -m "feat: add v5 content lifecycle"
~~~

### Task 4: Article DNA and failure samples

**Files:**
- Create article_group/v5/dna.py
- Create article_group/v5/failure.py
- Test tests/test_v5_dna_failure.py

**Interfaces:**
- extract_article_dna(article: Mapping[str, Any], *, draft_text: str | None = None, metric_event: Mapping[str, Any] | None = None, run_id: str = "v5-local", generated_at: str = "1970-01-01T00:00:00Z") -> dict[str, Any]
- validate_article_dna(record: Mapping[str, Any]) -> list[str]
- classify_failure_sample(event: Mapping[str, Any], *, thresholds: Mapping[str, float] | None = None) -> dict[str, Any]
- build_failure_artifact(events: Sequence[Mapping[str, Any]], *, run_id: str, generated_at: str) -> dict[str, Any]
- validate_failure_artifact(record: Mapping[str, Any]) -> list[str]

- [ ] Step 1: Write the failing tests

~~~python
def test_dna_marks_derived_features_and_keeps_explicit_platform():
    dna = extract_article_dna(
        {"article_id": "a-001", "topic_type": "人物", "platform": "wechat",
         "title": "他为什么回头？", "opening_info_type": "具体场景"},
        draft_text="夜里十一点，演员走出片场。",
    )
    assert dna["payload"]["features"]["topic_type"] == {
        "value": "人物", "source": "explicit"
    }
    assert dna["payload"]["features"]["title_structure"]["source"] == "derived"

def test_missing_metrics_are_not_classified_as_zero_failure():
    result = classify_failure_sample({"article_id": "a-001", "impressions": None,
                                      "impressions_status": "unavailable"})
    assert result["categories"] == ["insufficient_data"]

def test_failure_classifier_separates_exposure_without_click_and_low_completion():
    result = classify_failure_sample({"article_id": "a-002", "impressions": 5000,
        "ctr": 0.01, "reads": 300, "completion_rate": 0.2})
    assert "exposure_without_click" in result["categories"]
    assert "click_low_completion" in result["categories"]
~~~

- [ ] Step 2: Run the tests to verify they fail

Run: .venv/bin/pytest -q tests/test_v5_dna_failure.py

Expected: FAIL because both modules are absent.

- [ ] Step 3: Implement deterministic feature extraction and thresholded classification

Give each DNA feature value and source (explicit, derived, or unavailable), keep metrics null when unavailable, and never treat DNA as factual proof. Use named thresholds and actual metric evidence for the five specified failure categories; when required values are absent return only insufficient_data.

- [ ] Step 4: Run the tests to verify they pass

Run: .venv/bin/pytest -q tests/test_v5_dna_failure.py tests/test_v5_contracts.py

Expected: PASS.

- [ ] Step 5: Commit

~~~bash
git add article_group/v5/dna.py article_group/v5/failure.py tests/test_v5_dna_failure.py
git commit -m "feat: add v5 article dna and failure learning"
~~~

### Task 5: Dynamic quotas and versioned strategies

**Files:**
- Create article_group/v5/quota.py
- Create article_group/v5/strategy.py
- Test tests/test_v5_quota_strategy.py

**Interfaces:**
- derive_dynamic_quotas(history: Sequence[Mapping[str, Any]], base_quotas: Mapping[str, Mapping[str, Any]], *, run_id: str, generated_at: str, lookback_weeks: int = 4, min_share: float = 0.05, max_share: float = 0.60, high_risk_cap: float = 0.20) -> dict[str, Any]
- validate_quota_plan(plan: Mapping[str, Any]) -> list[str]
- build_strategy_record(*, strategy_id: str, version: int, run_id: str, applicable_topic_types: Sequence[str], hypothesis: str, evidence_samples: Sequence[str], success_conditions: Sequence[str], failure_boundary: Sequence[str], last_validated_at: str, state: str = "provisional", generated_at: str) -> dict[str, Any]
- advance_strategy_state(strategy: Mapping[str, Any], evidence: Sequence[Mapping[str, Any]], *, controller_decision: str | None = None) -> dict[str, Any]
- build_strategy_library(strategies: Sequence[Mapping[str, Any]], *, run_id: str, generated_at: str) -> dict[str, Any]
- validate_strategy_library(library: Mapping[str, Any]) -> list[str]

- [ ] Step 1: Write the failing tests

~~~python
def test_quota_recommendation_is_clamped_and_not_auto_applied():
    plan = derive_dynamic_quotas(_four_week_history(), {"人物": {"share": 0.5}},
        run_id="run-001", generated_at="2026-09-09T10:00:00+08:00")
    recommendation = plan["payload"]["recommendations"][0]
    assert 0.05 <= recommendation["recommended_share"] <= 0.60
    assert plan["payload"]["auto_apply"] is False

def test_insufficient_history_keeps_baseline_and_exposes_reason():
    plan = derive_dynamic_quotas([], {"新片": {"share": 0.4}},
        run_id="run-001", generated_at="2026-09-09T10:00:00+08:00")
    assert plan["payload"]["recommendations"][0]["recommended_share"] == 0.4
    assert plan["payload"]["data_sufficiency"] == "insufficient"

def test_strategy_cannot_become_supported_from_correlation_alone():
    result = advance_strategy_state(_testing_strategy(), _successful_correlations())
    assert result["payload"]["state"] == "testing"
    assert result["payload"]["recommended_state"] == "supported"

def test_controller_approval_and_cross_week_samples_support_strategy():
    result = advance_strategy_state(
        _testing_strategy(), _supported_evidence(),
        controller_decision="approve_support",
    )
    assert result["payload"]["state"] == "supported"
~~~

- [ ] Step 2: Run the tests to verify they fail

Run: .venv/bin/pytest -q tests/test_v5_quota_strategy.py

Expected: FAIL because quota and strategy modules are absent.

- [ ] Step 3: Implement bounded recommendations and explicit strategy transitions

Use only the latest four calendar weeks represented by input dates, median metrics, sample counts, risk caps, cooldown days and consecutive-failure downweights. Keep baseline when data is insufficient. Permit provisional → testing only with start_testing; permit testing → supported only with at least three usable samples in at least two weeks and approve_support; never auto-retire or publish.

- [ ] Step 4: Run the tests to verify they pass

Run: .venv/bin/pytest -q tests/test_v5_quota_strategy.py tests/test_v4_effect_feedback.py

Expected: PASS.

- [ ] Step 5: Commit

~~~bash
git add article_group/v5/quota.py article_group/v5/strategy.py tests/test_v5_quota_strategy.py
git commit -m "feat: add v5 quotas and strategy library"
~~~

### Task 6: Resource allocation and V3 adapter

**Files:**
- Create article_group/v5/resources.py
- Create article_group/v5/integration.py
- Modify article_group/editorial_pipeline_v3.py
- Test tests/test_v5_resources_integration.py

**Interfaces:**
- plan_resource_allocation(candidates: Sequence[Mapping[str, Any]], *, budget: float, run_id: str, generated_at: str) -> dict[str, Any]
- validate_resource_plan(plan: Mapping[str, Any]) -> list[str]
- validate_v5_transition_context(from_state: str, to_state: str, *, experiment_record: Mapping[str, Any] | None = None, lifecycle_record: Mapping[str, Any] | None = None, dna_record: Mapping[str, Any] | None = None, failure_report: Mapping[str, Any] | None = None, quota_plan: Mapping[str, Any] | None = None, strategy_library: Mapping[str, Any] | None = None, resource_plan: Mapping[str, Any] | None = None) -> list[str]
- article_group.editorial_pipeline_v3.validate_v5_transition_context exposes the same signature by lazy delegation.

- [ ] Step 1: Write the failing tests

~~~python
def test_resource_tiers_follow_value_readiness_and_risk():
    plan = plan_resource_allocation(_candidates(), budget=20,
        run_id="run-001", generated_at="2026-09-09T10:00:00+08:00")
    actions = {item["candidate_id"]: item["action"]
               for item in plan["payload"]["allocations"]}
    assert actions["high-ready"] == "full_capture"
    assert actions["high-risk-low-value"] == "stop"
    assert actions["controversial-potential"] == "sol_review"

def test_research_gate_requires_article_group_experiment_and_non_stop_plan():
    errors = validate_v5_transition_context("approved", "researching",
        experiment_record=None, resource_plan=None)
    assert "missing:v5_experiment" in errors
    assert "missing:v5_resource_plan" in errors

def test_v5_never_replaces_review_to_closed_or_grants_authorization():
    assert validate_v5_transition_context("review", "closed") == []
    assert "publication_authorization_must_be_not_authorized" in \
        validate_v5_transition_context("approved", "researching",
            experiment_record={"publication_authorization": "authorized"})
~~~

- [ ] Step 2: Run the tests to verify they fail

Run: .venv/bin/pytest -q tests/test_v5_resources_integration.py

Expected: FAIL because the V5 resource and adapter modules are absent.

- [ ] Step 3: Implement bounded resource recommendations and adapter rules

Use the exact action mapping in the spec; every allocation includes owner, estimated cost, reason, controller_review_required, and auto_apply=false. The adapter checks the existing V3 transition first, requires an experiment and non-stop resource plan for approved → researching, reports V5 blockers before writing, and leaves review → closed to V3. Recursively reject any authorization other than not_authorized.

- [ ] Step 4: Run the tests to verify they pass

Run: .venv/bin/pytest -q tests/test_v5_resources_integration.py tests/test_v4_v3_integration.py tests/test_editorial_pipeline_v3.py

Expected: PASS.

- [ ] Step 5: Commit

~~~bash
git add article_group/v5/resources.py article_group/v5/integration.py article_group/editorial_pipeline_v3.py tests/test_v5_resources_integration.py
git commit -m "feat: add v5 resource planning and v3 adapter"
~~~

### Task 7: Offline V5 orchestrator, CLI, and controlled fixture

**Files:**
- Create article_group/v5/verification.py
- Create scripts/article_group_v5.py
- Create tests/test_article_group_v5_cli.py
- Create tests/fixtures/v5/controlled-001/ with batch.json, experiment.json, observations.json, article-records.json, metric-events.json, quota-history.json, strategy-input.json, strategy-evidence.json, resource-candidates.json, resource-budget.json, source-audit.json, and one safe draft.

**Interfaces:**
- CLI commands: experiment, lifecycle, dna, failures, quotas, strategy, resources, verify.
- run_v5_verification(run_dir: Path, *, output_path: Path) -> dict[str, Any] writes eight artifacts and reads them back.
- validate_v5_artifact(name: str, artifact: Mapping[str, Any], run_dir: Path) -> list[str] and write_v5_artifact(name: str, artifact: Mapping[str, Any], *, output_path: Path) -> Path.

- [ ] Step 1: Write the failing tests

~~~python
def test_verify_writes_eight_v5_artifacts_and_stays_non_authorizing(tmp_path):
    result = invoke("verify", run_dir=FIXTURE, output_dir=tmp_path)
    assert result.returncode == 0, result.stderr or result.stdout
    names = {path.name for path in tmp_path.iterdir()}
    assert names == {"experiment-record.json", "content-lifecycle.json",
        "article-dna.json", "failure-samples.json", "dynamic-quotas.json",
        "strategy-library.json", "resource-plan.json", "v5-verification.json"}
    report = json.loads((tmp_path / "v5-verification.json").read_text())
    assert report["payload"]["read_back"] is True
    assert report["payload"]["publication_authorization"] == "not_authorized"
    assert not list(tmp_path.glob("*.html"))

def test_v5_cli_requires_explicit_run_and_output_and_refuses_overwrite(tmp_path):
    assert invoke("verify", run_dir=None, output_dir=tmp_path).returncode == 2
    output = tmp_path / "experiment-record.json"
    output.write_text("{}\n", encoding="utf-8")
    result = invoke("experiment", run_dir=FIXTURE, output_path=output)
    assert result.returncode != 0
    assert "refuse_overwrite" in result.stdout
~~~

- [ ] Step 2: Run the tests to verify they fail

Run: .venv/bin/pytest -q tests/test_article_group_v5_cli.py

Expected: FAIL because the orchestrator, CLI, and controlled fixture do not exist.

- [ ] Step 3: Implement explicit-input orchestration and read-back

Load only paths below run_dir; use deterministic JSON hashes and idempotent writes; preflight all destinations before writing. Aggregate missing source roles, retry requirements, manual escalations, CONTENT_READY|CONTENT_BLOCKED, artifact hashes, separate module checks, and read_back=true. Do not create HTML or publication state.

- [ ] Step 4: Run the tests to verify they pass

Run: .venv/bin/pytest -q tests/test_article_group_v5_cli.py tests/test_v5_*.py

Expected: PASS.

- [ ] Step 5: Commit

~~~bash
git add article_group/v5/verification.py scripts/article_group_v5.py tests/test_article_group_v5_cli.py tests/fixtures/v5/controlled-001
git commit -m "feat: add v5 offline verification lane"
~~~

### Task 8: Documentation, full regression, and smoke handoff

**Files:**
- Create docs/codex/editorial-pipeline-v5.md
- Modify README.zh-CN.md
- Maintain .superpowers/sdd/2026-09-09-editorial-pipeline-v5/progress.md (created before Task 1 by the SDD controller)

**Interfaces:**
- Document every CLI command, input file, output schema, controller boundary, lifecycle action, failure category, quota bound, strategy state, and the exact smoke command.
- Smoke output: runs/2026-09-09/v5/controlled-001/ with all eight artifacts and read-back report.

- [ ] Step 1: Update the SDD ledger's documentation/acceptance checklist

Record the eight artifact names, the V3/V4 compatibility assertion, the four separate report dimensions (PASS, missing roles, retry, manual escalation), and the non-authorizing boundary in the SDD ledger.

- [ ] Step 2: Run the pre-documentation regression

Run: .venv/bin/pytest -q

Expected: PASS for all tests through Tasks 1–7.

- [ ] Step 3: Write the runbook and README entry

Show:

~~~bash
.venv/bin/python scripts/article_group_v5.py verify \
  --run-dir tests/fixtures/v5/controlled-001 \
  --output-dir runs/2026-09-09/v5/controlled-001
~~~

Explain that the fixture is synthetic and that CONTENT_READY never means publication authorization.

- [ ] Step 4: Run smoke and read back every file

Run the command above, then run .venv/bin/pytest -q again. Read all eight JSON files, verify hashes and read_back=true, and record actual counts/statuses in the ledger and final report.

- [ ] Step 5: Commit

~~~bash
git add docs/codex/editorial-pipeline-v5.md README.zh-CN.md .superpowers/sdd/2026-09-09-editorial-pipeline-v5/progress.md
git commit -m "docs: add v5 runbook and acceptance record"
~~~

## Final verification

- .venv/bin/pytest -q exits 0 and reports zero failures.
- The V3 and V4 focused suites remain green.
- The V5 controlled smoke writes exactly eight JSON artifacts, no HTML, no credentials, and read_back=true.
- The final report separates PASS, missing source/data roles, retry requirements, and manual escalation; publication_authorization remains not_authorized.
- A whole-branch review checks spec coverage, deferred minor findings, and the V4 compatibility boundary before any integration/finish action.
