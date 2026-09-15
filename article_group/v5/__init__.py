"""Offline contracts shared by the Article Group V5 modules.

状态：旁路工具层，已冻结为日更门禁（2026-09-15 裁定）。本层只被
scripts/article_group_controller.py 等旁路工具使用，不参与日更判定；
日更现行契约族见 article_group 顶层（article-first-v1 +
schemas/editorial-pipeline-v3）。
"""

from .contracts import (
    ARTIFACT_SCHEMA_VERSIONS,
    EXPERIMENT_DESIGNS,
    FAILURE_TYPES,
    LIFECYCLE_STATES,
    PUBLICATION_AUTHORIZATION,
    STRATEGY_STATES,
    new_artifact_envelope,
    payload_of,
    validate_v5_artifact_envelope,
)

__all__ = [
    "ARTIFACT_SCHEMA_VERSIONS",
    "EXPERIMENT_DESIGNS",
    "FAILURE_TYPES",
    "LIFECYCLE_STATES",
    "PUBLICATION_AUTHORIZATION",
    "STRATEGY_STATES",
    "new_artifact_envelope",
    "payload_of",
    "validate_v5_artifact_envelope",
]
