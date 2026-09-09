import json
from article_group.controller_v1 import *

def manifest():
    return {"schema_version":"article-group-controller-v1","run_id":"r1","batch_id":"b1","articles":[{"topic_id":"t1"}],"publication_authorization":"not_authorized"}

def test_manifest_and_decision():
    m=manifest(); assert validate_controller_manifest(m)==[]
    d={"schema_version":"controller-stage-decision-v1","topic_id":"t1","from_state":"idea","to_state":"precheck","decision":"pass","decided_at":"2026-09-09T00:00:00Z"}
    assert validate_stage_decision(d,m)==[]

def test_rejects_publication_and_unknown_topic():
    m=manifest(); m["publication_authorization"]="authorized"
    assert "publication_authorization_must_be_not_authorized" in validate_controller_manifest(m)
    d={"schema_version":"controller-stage-decision-v1","topic_id":"x","from_state":"idea","to_state":"precheck","decision":"pass","decided_at":"x"}
    assert "topic_id_not_in_manifest" in validate_stage_decision(d,manifest())

def test_append_is_jsonl(tmp_path):
    p=tmp_path/"decisions.jsonl"; d={"topic_id":"t1","to_state":"precheck"}; append_stage_decision(p,d); append_stage_decision(p,d)
    assert len(p.read_text().splitlines())==2 and json.loads(p.read_text().splitlines()[0])==d

def test_candidate_approval_requires_card():
    assert validate_controller_transition("candidate","approved")==["missing:topic_card"]

def test_verify_context_reads_layers(tmp_path):
    root=tmp_path/"v5"; root.mkdir(); (root/"v5-verification.json").write_text(json.dumps({"payload":{"status":"PASS","decision":"eligible_for_article_group_review"}}))
    result=verify_context(v5_run_dir=root); assert result["status"]=="PASS" and result["content_status"]=="CONTENT_READY"
