import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "daily_three_article_production.py"


def chinese_body(seed: str) -> str:
    return ("这是一段经过核验的影视观察" + seed) * 130


def packet(packet_id: str, *, topic: str, angle: str, body: str | None = None, approved_evergreen: bool = False) -> dict:
    statement = f"作品{packet_id}已公开发布"
    work_key = f"work-{packet_id}"
    origin_packet_id = f"origin-{packet_id}"
    origin_packet_sha256 = f"sha256:{packet_id}"
    return {
        "id": packet_id,
        "work_key": work_key,
        "origin_packet_id": origin_packet_id,
        "topic_key": topic,
        "angle_key": angle,
        "headline": f"影视观察：{packet_id}",
        "body": body if body is not None else chinese_body(packet_id) + statement,
        "approved_evergreen": approved_evergreen,
        "evidence": {
            "sources": [{
                "source_id": f"source-{packet_id}",
                "url": f"https://evidence.example/{packet_id}",
                "quote": statement,
                "locator": "article > p:nth-of-type(1)",
                "work_key": work_key,
                "origin_packet_id": origin_packet_id,
                "origin_packet_sha256": origin_packet_sha256,
            }],
            "claims": [{
                "claim_id": f"claim-{packet_id}",
                "text": statement,
                "source_id": f"source-{packet_id}",
                "locator": "article > p:nth-of-type(1)",
                "work_key": work_key,
                "origin_packet_id": origin_packet_id,
                "origin_packet_sha256": origin_packet_sha256,
            }],
        },
    }


def run_cli(tmp_path: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "run"
    input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(input_path), "--output", str(output_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_all_three_valid_slots_create_only_final_safe_html_with_manifest_and_audit(tmp_path):
    payload = {
        "run_id": "success-run",
        "slots": {
            "A": [packet("a-primary", topic="topic-a", angle="angle-a")],
            "B": [packet("b-bad", topic="topic-b", angle="angle-b", body="太短"), packet("b-evergreen", topic="topic-b2", angle="angle-b2", approved_evergreen=True)],
            "C": [packet("c-primary", topic="topic-c", angle="angle-c")],
        },
    }

    result = run_cli(tmp_path, payload)

    assert result.returncode == 0, result.stderr
    run_dir = tmp_path / "run"
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "final"
    assert manifest["publish_ready"] is True
    assert manifest["slots"]["B"]["selected_id"] == "b-evergreen"
    assert manifest["slots"]["B"]["replacements"] == ["b-bad"]
    assert set(manifest["final_article_ids"]) == {"a-primary", "b-evergreen", "c-primary"}
    for slot in ("A", "B", "C"):
        html = (run_dir / "slots" / slot / "article.html").read_text(encoding="utf-8")
        assert "<script" not in html.lower()
        assert "onerror=" not in html.lower()
        assert (run_dir / "slots" / slot / "evidence.json").exists()
    audit = [json.loads(line) for line in (run_dir / "audit" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(event["event"] == "slot_replaced" and event["slot"] == "B" for event in audit)


def test_approved_evergreen_pool_can_supply_a_slot_replacement(tmp_path):
    payload = {
        "slots": {
            "A": [packet("a-primary", topic="topic-a", angle="angle-a")],
            "B": [packet("b-too-short", topic="topic-b", angle="angle-b", body="太短")],
            "C": [packet("c-primary", topic="topic-c", angle="angle-c")],
        },
        "approved_evergreen_pool": {
            "B": [packet("b-evergreen", topic="topic-b2", angle="angle-b2", approved_evergreen=True)],
        },
    }

    result = run_cli(tmp_path, payload)

    assert result.returncode == 0
    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["slots"]["B"]["selected_id"] == "b-evergreen"
    assert manifest["slots"]["B"]["replacements"] == ["b-too-short"]


def test_unapproved_evergreen_pool_item_cannot_be_used(tmp_path):
    payload = {
        "slots": {
            "A": [packet("a-primary", topic="topic-a", angle="angle-a")],
            "B": [],
            "C": [packet("c-primary", topic="topic-c", angle="angle-c")],
        },
        "approved_evergreen_pool": {
            "B": [packet("b-not-approved", topic="topic-b", angle="angle-b")],
        },
    }

    result = run_cli(tmp_path, payload)

    assert result.returncode == 1
    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text(encoding="utf-8"))
    assert "EVERGREEN_NOT_APPROVED" in manifest["slots"]["B"]["failure_codes"]


def test_any_unqualified_slot_fails_closed_and_never_marks_partial_drafts_final(tmp_path):
    payload = {
        "run_id": "failure-run",
        "slots": {
            "A": [packet("a-primary", topic="topic-a", angle="angle-a")],
            "B": [packet("b-primary", topic="topic-b", angle="angle-b")],
            "C": [packet("c-unmapped", topic="topic-c", angle="angle-c")],
        },
    }
    payload["slots"]["C"][0]["evidence"]["claims"][0]["locator"] = "wrong-locator"

    result = run_cli(tmp_path, payload)

    assert result.returncode == 1
    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["publish_ready"] is False
    assert manifest["final_article_ids"] == []
    assert manifest["slots"]["C"]["status"] == "failed"
    assert "CLAIM_SOURCE_LOCATOR_MISMATCH" in manifest["slots"]["C"]["attempts"][0]["failure_codes"]
    assert not list((tmp_path / "run" / "slots" / "C").glob("article.html"))
    assert (tmp_path / "run" / "slots" / "C" / "draft.json").exists()


def test_duplicate_topic_or_angle_across_selected_slots_fails_closed(tmp_path):
    payload = {
        "slots": {
            "A": [packet("a-primary", topic="same-topic", angle="angle-a")],
            "B": [packet("b-primary", topic="same-topic", angle="angle-b")],
            "C": [packet("c-primary", topic="topic-c", angle="angle-c")],
        },
    }

    result = run_cli(tmp_path, payload)

    assert result.returncode == 1
    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["publish_ready"] is False
    assert manifest["slots"]["B"]["status"] == "failed"
    assert "DUPLICATE_TOPIC_OR_ANGLE" in manifest["slots"]["B"]["failure_codes"]


def test_missing_direct_source_provenance_mapping_fails_closed(tmp_path):
    payload = {
        "slots": {
            "A": [packet("a-primary", topic="topic-a", angle="angle-a")],
            "B": [packet("b-primary", topic="topic-b", angle="angle-b")],
            "C": [packet("c-primary", topic="topic-c", angle="angle-c")],
        },
    }
    del payload["slots"]["B"][0]["evidence"]["sources"][0]["origin_packet_sha256"]

    result = run_cli(tmp_path, payload)

    assert result.returncode == 1
    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["publish_ready"] is False
    assert manifest["final_article_ids"] == []
    assert "MISSING_PROVENANCE_MAPPING" in manifest["slots"]["B"]["failure_codes"]


def test_duplicate_work_key_across_selected_slots_fails_closed(tmp_path):
    payload = {
        "slots": {
            "A": [packet("a-primary", topic="topic-a", angle="angle-a")],
            "B": [packet("b-primary", topic="topic-b", angle="angle-b")],
            "C": [packet("c-primary", topic="topic-c", angle="angle-c")],
        },
    }
    reused_work = payload["slots"]["A"][0]["work_key"]
    for item in (payload["slots"]["B"][0],):
        item["work_key"] = reused_work
        item["evidence"]["sources"][0]["work_key"] = reused_work
        item["evidence"]["claims"][0]["work_key"] = reused_work

    result = run_cli(tmp_path, payload)

    assert result.returncode == 1
    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["publish_ready"] is False
    assert manifest["final_article_ids"] == []
    assert "DUPLICATE_WORK_OR_ATOM_ACROSS_SLOTS" in manifest["slots"]["B"]["failure_codes"]


def test_duplicate_claim_id_across_selected_slots_fails_closed(tmp_path):
    payload = {
        "slots": {
            "A": [packet("a-primary", topic="topic-a", angle="angle-a")],
            "B": [packet("b-primary", topic="topic-b", angle="angle-b")],
            "C": [packet("c-primary", topic="topic-c", angle="angle-c")],
        },
    }
    reused_claim_id = payload["slots"]["A"][0]["evidence"]["claims"][0]["claim_id"]
    payload["slots"]["B"][0]["evidence"]["claims"][0]["claim_id"] = reused_claim_id

    result = run_cli(tmp_path, payload)

    assert result.returncode == 1
    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["publish_ready"] is False
    assert manifest["final_article_ids"] == []
    assert "DUPLICATE_WORK_OR_ATOM_ACROSS_SLOTS" in manifest["slots"]["B"]["failure_codes"]
