"""Offline contracts shared by the Article Group V4 modules.

状态：旁路工具层，已冻结为日更门禁（2026-09-15 裁定）。本层只被
scripts/article_group_controller.py 等旁路工具使用，不参与日更判定；
日更现行契约族见 article_group 顶层（article-first-v1 +
schemas/editorial-pipeline-v3）。
"""

from .contracts import (
    ARTIFACT_SCHEMA_VERSIONS,
    EDGE_TYPES,
    EFFECT_STATES,
    GAP_TYPES,
    NODE_TYPES,
    new_artifact_envelope,
    parse_json_object,
    safe_relative_path,
    sha256_file,
    validate_artifact_envelope,
    validate_node_type,
)

__all__ = [
    "ARTIFACT_SCHEMA_VERSIONS",
    "EDGE_TYPES",
    "EFFECT_STATES",
    "GAP_TYPES",
    "NODE_TYPES",
    "new_artifact_envelope",
    "parse_json_object",
    "safe_relative_path",
    "sha256_file",
    "validate_artifact_envelope",
    "validate_node_type",
]
