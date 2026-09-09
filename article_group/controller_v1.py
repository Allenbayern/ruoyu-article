"""Offline Article Group 1.0 controller contracts."""
from __future__ import annotations

import hashlib, json
from pathlib import Path
from typing import Any, Mapping

STATES = ("idea","precheck","candidate","approved","researching","material_ready","writing","review","closed")
PUBLICATION_AUTHORIZATION = "not_authorized"

def _digest(value: Any) -> str:
    return hashlib.sha256((json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()).hexdigest()

def validate_controller_manifest(manifest: Mapping[str, Any]) -> list[str]:
    errors=[]
    if manifest.get("schema_version") != "article-group-controller-v1": errors.append("schema_version")
    for key in ("run_id","batch_id","articles"):
        if not manifest.get(key): errors.append(f"missing:{key}")
    if manifest.get("publication_authorization", PUBLICATION_AUTHORIZATION) != PUBLICATION_AUTHORIZATION:
        errors.append("publication_authorization_must_be_not_authorized")
    if not isinstance(manifest.get("articles"), list): errors.append("articles_must_be_list")
    else:
        ids=[]
        for row in manifest["articles"]:
            if not isinstance(row, Mapping) or not row.get("topic_id"): errors.append("article_topic_id_missing")
            else:
                if row["topic_id"] in ids: errors.append("duplicate:topic_id")
                ids.append(row["topic_id"])
    return sorted(set(errors))

def validate_stage_decision(decision: Mapping[str, Any], manifest: Mapping[str, Any]) -> list[str]:
    errors=[]
    if decision.get("schema_version") != "controller-stage-decision-v1": errors.append("schema_version")
    for key in ("topic_id","from_state","to_state","decision","decided_at"):
        if not decision.get(key): errors.append(f"missing:{key}")
    ids={a.get("topic_id") for a in manifest.get("articles",[]) if isinstance(a, Mapping)}
    if decision.get("topic_id") not in ids: errors.append("topic_id_not_in_manifest")
    if decision.get("to_state") not in STATES: errors.append("unknown_to_state")
    if "publication_authorization" in decision and decision["publication_authorization"] != PUBLICATION_AUTHORIZATION:
        errors.append("publication_authorization_must_be_not_authorized")
    return sorted(set(errors))

def append_stage_decision(path: Path, decision: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(dict(decision), ensure_ascii=False, sort_keys=True) + "\n")

def validate_controller_transition(from_state: str, to_state: str, **kwargs: Any) -> list[str]:
    from article_group.editorial_pipeline_v3 import validate_transition
    if from_state == "candidate" and to_state == "approved":
        card=kwargs.get("topic_card")
        return ["missing:topic_card"] if card is None else []
    if from_state == "approved" and to_state == "researching":
        return validate_transition("approved", "researching", topic_card=kwargs.get("topic_card"), crawl_task=kwargs.get("crawl_task"))
    return validate_transition(from_state, to_state, topic_card=kwargs.get("topic_card"), crawl_task=kwargs.get("crawl_task"), material_pack=kwargs.get("material_pack"))

__all__=["STATES","validate_controller_manifest","validate_stage_decision","append_stage_decision","validate_controller_transition"]
