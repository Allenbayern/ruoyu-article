"""Offline validators for the article-group controlled-production workflow.

契约层状态（2026-09-15 裁定，改动前先读此块）
--------------------------------------------
- **现行层（日更接入）**：本包顶层契约族 —— `article_first` 的
  `article-first-v1` + `schemas/editorial-pipeline-v3/` schema 族；
  日更生成器（scripts/run_real_daily_00x.py）与门禁（article_task_v1、
  portfolio_gate、style_gate、prose_pilot、git_hygiene）都跑在这一层。
- **已冻结**：`v2_contract/`（Ruoyu V2 shadow validators，只读历史兼容，
  不接入日更）。
- **旁路工具层（非日更门禁）**：`article_group/v4`、`article_group/v5`
  仅被 scripts/article_group_controller.py 等旁路工具使用；不参与日更
  判定，冻结为门禁。
"""

from .workflow import (
    ALLOWED_TRANSITIONS,
    BatchValidationError,
    build_controlled_run,
    validate_batch,
    validate_delivery_authorization,
    validate_transition,
)
from .editorial_pipeline_v3 import (
    STATES as EDITORIAL_PIPELINE_V3_STATES,
    validate_crawl_task as validate_v3_crawl_task,
    validate_material_pack as validate_v3_material_pack,
    validate_pipeline_transition,
    validate_topic_card as validate_v3_topic_card,
    validate_transition as validate_v3_transition,
)
from .article_first import (
    ARTICLE_FIRST_CONTRACT_VERSION,
    ARTICLE_FIRST_STATES,
    CONTENT_STATES,
    HARD_INFORMATION_TYPES,
    TITLE_PACKAGING_RESULTS,
    TITLE_PACKAGING_ROUTES,
    TITLE_STATES,
    is_article_first_record,
    title_packaging_route,
    validate_article_first_transition,
    validate_phase_field_boundary,
)
from .content_fidelity import (
    CONTENT_FIDELITY_SCHEMA,
    evaluate_content_fidelity,
    validate_content_fidelity,
)
from .material_acceptance import (
    evaluate_material_acceptance,
    validate_material_acceptance_record,
)
from .run_contract import (
    BRIEF_CONTRACT,
    PRODUCTION_CONTRACT,
    REQUIRED_RUN_CONTRACT,
    TITLE_CONTRACT,
    is_strict_run_contract,
    validate_phase_contract_fields,
    validate_referenced_contract_artifacts,
    validate_run_contract,
    validate_run_root_contract,
)
from .source_capability import (
    CAPABILITY_LEVELS,
    DEFAULT_SOURCE_CAPABILITIES,
    source_capability_rank,
    validate_claim_capabilities,
)
from .independent_review import (
    build_independent_review_binding,
    evaluate_independent_review,
    plan_resume,
    validate_independent_review_record,
)
from .title_pack_fidelity import (
    TITLE_PACK_SCHEMA,
    TITLE_REVIEW_SCHEMA,
    evaluate_title_pack,
    evaluate_title_review,
    validate_title_pack,
    validate_title_review,
)
from .rule_compliance import (
    ARTICLE_MODES,
    MODE_ALLOWED_LEVELS,
    build_readability_record,
    build_source_stripped,
    evaluate_article_rule_evidence,
    evaluate_batch_rule_compliance,
    validate_rule_compliance,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "BatchValidationError",
    "build_controlled_run",
    "validate_batch",
    "validate_delivery_authorization",
    "validate_transition",
    "EDITORIAL_PIPELINE_V3_STATES",
    "validate_v3_crawl_task",
    "validate_v3_material_pack",
    "validate_pipeline_transition",
    "validate_v3_topic_card",
    "validate_v3_transition",
    "ARTICLE_FIRST_CONTRACT_VERSION",
    "ARTICLE_FIRST_STATES",
    "CONTENT_STATES",
    "HARD_INFORMATION_TYPES",
    "TITLE_PACKAGING_RESULTS",
    "TITLE_PACKAGING_ROUTES",
    "TITLE_STATES",
    "is_article_first_record",
    "title_packaging_route",
    "validate_article_first_transition",
    "validate_phase_field_boundary",
    "CONTENT_FIDELITY_SCHEMA",
    "evaluate_content_fidelity",
    "validate_content_fidelity",
    "evaluate_material_acceptance",
    "validate_material_acceptance_record",
    "BRIEF_CONTRACT",
    "PRODUCTION_CONTRACT",
    "REQUIRED_RUN_CONTRACT",
    "TITLE_CONTRACT",
    "is_strict_run_contract",
    "validate_phase_contract_fields",
    "validate_referenced_contract_artifacts",
    "validate_run_contract",
    "validate_run_root_contract",
    "CAPABILITY_LEVELS",
    "DEFAULT_SOURCE_CAPABILITIES",
    "source_capability_rank",
    "validate_claim_capabilities",
    "build_independent_review_binding",
    "evaluate_independent_review",
    "plan_resume",
    "validate_independent_review_record",
    "TITLE_PACK_SCHEMA",
    "TITLE_REVIEW_SCHEMA",
    "evaluate_title_pack",
    "evaluate_title_review",
    "validate_title_pack",
    "validate_title_review",
    "ARTICLE_MODES",
    "MODE_ALLOWED_LEVELS",
    "build_readability_record",
    "build_source_stripped",
    "evaluate_article_rule_evidence",
    "evaluate_batch_rule_compliance",
    "validate_rule_compliance",
]
