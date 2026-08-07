import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "daily3_packet_adapter.py"
GATE = ROOT / "scripts" / "daily_three_article_production.py"


def long_analysis(seed: str) -> str:
    return "【分析】" + ("这是一段围绕叙事结构、人物关系和镜头表达的分析，不把分析判断伪装成可核验事实。" + seed) * 45


def atom(atom_id: str, claim: str) -> dict:
    return {
        "id": atom_id,
        "work_key": f"work-{atom_id}",
        "origin_packet_id": f"origin-{atom_id}",
        "origin_packet_sha256": f"sha256:{atom_id}",
        "claim": claim,
        "source_text": f"报道原文：{claim}。",
        "source_locator": "validated_editorial_root",
        "url": f"https://evidence.example/{atom_id}",
        "page_type": "news",
        "published_at": "2026-07-17T10:00:00+08:00",
        "fact_class": "production",
        "source_metadata": {
            "institution": "Evidence Desk",
            "source_program": None,
            "author": None,
            "reporters": [],
            "editors": [],
            "published_at": "2026-07-17T10:00:00+08:00",
        },
    }


def draft(packet_id: str, topic: str, angle: str, evidence_atom: dict) -> dict:
    claim = evidence_atom["claim"]
    return {
        "id": packet_id,
        "work_key": evidence_atom["work_key"],
        "origin_packet_id": evidence_atom["origin_packet_id"],
        "topic_key": topic,
        "angle_key": angle,
        "headline": f"影视观察：{packet_id}",
        "body": f"【事实】{claim}\n\n{long_analysis(packet_id)}",
        "factual_claims": [{"atom_id": evidence_atom["id"], "text": claim}],
    }


def run_adapter(tmp_path: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    source = tmp_path / "adapter-input.json"
    target = tmp_path / "gate-input.json"
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(source), "--output", str(target)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_adapter_maps_explicit_fact_blocks_to_gate_packets_and_preserves_candidate_pools(tmp_path):
    atoms = [atom(f"atom-{slot}", f"作品{slot}的主创公开说明了第{slot}项制作选择") for slot in "ABC"]
    payload = {
        "run_id": "offline-bridge",
        "evidence_atoms": atoms,
        "slots": {
            slot: [draft(f"{slot}-primary", f"topic-{slot}", f"angle-{slot}", evidence_atom)]
            for slot, evidence_atom in zip("ABC", atoms)
        },
        "approved_evergreen_pool": {
            "B": [{**draft("B-evergreen", "topic-evergreen", "angle-evergreen", atoms[1]), "approved_evergreen": True}],
        },
    }

    result = run_adapter(tmp_path, payload)

    assert result.returncode == 0, result.stderr
    output = json.loads((tmp_path / "gate-input.json").read_text(encoding="utf-8"))
    assert output["run_id"] == "offline-bridge"
    packet = output["slots"]["A"][0]
    assert packet["topic_key"] == "topic-A"
    assert packet["angle_key"] == "angle-A"
    assert packet["evidence"]["claims"] == [{
        "claim_id": "atom-A",
        "text": atoms[0]["claim"],
        "source_id": "atom-A",
        "locator": "validated_editorial_root",
        "work_key": atoms[0]["work_key"],
        "origin_packet_id": atoms[0]["origin_packet_id"],
        "origin_packet_sha256": atoms[0]["origin_packet_sha256"],
    }]
    assert packet["evidence"]["sources"][0] == {
        "source_id": "atom-A",
        "url": atoms[0]["url"],
        "quote": atoms[0]["claim"],
        "locator": "validated_editorial_root",
        "work_key": atoms[0]["work_key"],
        "origin_packet_id": atoms[0]["origin_packet_id"],
        "origin_packet_sha256": atoms[0]["origin_packet_sha256"],
        "source_metadata": atoms[0]["source_metadata"],
    }
    assert output["approved_evergreen_pool"]["B"][0]["approved_evergreen"] is True
    assert "final" not in json.dumps(output).lower()

    gate_input = tmp_path / "gate-input.json"
    gate_output = tmp_path / "gate-run"
    gate = subprocess.run([sys.executable, str(GATE), "--input", str(gate_input), "--output", str(gate_output)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert gate.returncode == 0, gate.stderr


def test_adapter_preserves_unknown_catalog_page_date_as_null(tmp_path):
    atoms = [atom(f"atom-{slot}", f"作品{slot}的主创公开说明了第{slot}项制作选择") for slot in "ABC"]
    atoms[2]["published_at"] = None
    atoms[2]["source_metadata"]["published_at"] = None
    payload = {
        "evidence_atoms": atoms,
        "slots": {
            slot: [draft(f"{slot}-primary", f"topic-{slot}", f"angle-{slot}", evidence_atom)]
            for slot, evidence_atom in zip("ABC", atoms)
        },
    }

    result = run_adapter(tmp_path, payload)

    assert result.returncode == 0, result.stderr
    output = json.loads((tmp_path / "gate-input.json").read_text(encoding="utf-8"))
    assert output["slots"]["C"][0]["evidence"]["sources"][0]["source_metadata"]["published_at"] is None


def test_adapter_rejects_evidence_atom_missing_required_provenance(tmp_path):
    known = atom("atom-known", "主创公开说明了制作选择")
    candidates = [draft(slot, f"topic-{slot}", f"angle-{slot}", known) for slot in "ABC"]
    del known["work_key"]
    payload = {
        "evidence_atoms": [known],
        "slots": {
            slot: [candidate] for slot, candidate in zip("ABC", candidates)
        },
    }

    result = run_adapter(tmp_path, payload)

    assert result.returncode == 1
    assert "INVALID_EVIDENCE_ATOM" in result.stderr
    assert not (tmp_path / "gate-input.json").exists()


def test_adapter_rejects_draft_when_cited_atom_has_different_work_or_origin(tmp_path):
    atoms = [atom(f"atom-{slot}", f"作品{slot}的主创公开说明了制作选择") for slot in "ABC"]
    payload = {
        "evidence_atoms": atoms,
        "slots": {
            slot: [draft(slot, f"topic-{slot}", f"angle-{slot}", evidence_atom)]
            for slot, evidence_atom in zip("ABC", atoms)
        },
    }
    payload["slots"]["A"][0]["work_key"] = "another-work"

    result = run_adapter(tmp_path, payload)

    assert result.returncode == 1
    assert "DRAFT_WORK_ORIGIN_MISMATCH" in result.stderr
    assert not (tmp_path / "gate-input.json").exists()


def test_adapter_rejects_packet_when_an_explicit_fact_has_no_exact_atom_mapping(tmp_path):
    known = atom("atom-known", "主创公开说明了制作选择")
    payload = {
        "evidence_atoms": [known],
        "slots": {
            "A": [draft("A", "topic-A", "angle-A", known)],
            "B": [draft("B", "topic-B", "angle-B", known)],
            "C": [draft("C", "topic-C", "angle-C", known)],
        },
    }
    payload["slots"]["C"][0]["body"] = "【事实】没有证据支持的新事实\n\n" + long_analysis("C")
    payload["slots"]["C"][0]["factual_claims"] = [{"atom_id": "atom-known", "text": "没有证据支持的新事实"}]

    result = run_adapter(tmp_path, payload)

    assert result.returncode == 1
    assert not (tmp_path / "gate-input.json").exists()
    assert "FACT_CLAIM_ATOM_MISMATCH" in result.stderr


def test_adapter_rejects_factual_claims_when_their_order_differs_from_marked_facts(tmp_path):
    first = atom("atom-first", "主创公开说明了第一项制作选择")
    second = atom("atom-second", "主创公开说明了第二项制作选择")
    payload = {
        "evidence_atoms": [first, second],
        "slots": {
            "A": [draft("A", "topic-A", "angle-A", first)],
            "B": [draft("B", "topic-B", "angle-B", first)],
            "C": [draft("C", "topic-C", "angle-C", first)],
        },
    }
    payload["slots"]["A"][0]["body"] = f"【事实】{first['claim']}\n【事实】{second['claim']}\n\n{long_analysis('A')}"
    payload["slots"]["A"][0]["factual_claims"] = [
        {"atom_id": second["id"], "text": second["claim"]},
        {"atom_id": first["id"], "text": first["claim"]},
    ]

    result = run_adapter(tmp_path, payload)

    assert result.returncode == 1
    assert not (tmp_path / "gate-input.json").exists()
    assert "UNMAPPED_OR_UNMARKED_FACTUAL_CLAIM" in result.stderr


def test_adapter_rejects_duplicate_atom_claims_and_writes_no_output(tmp_path):
    known = atom("atom-known", "主创公开说明了制作选择")
    payload = {
        "evidence_atoms": [known],
        "slots": {
            "A": [draft("A", "topic-A", "angle-A", known)],
            "B": [draft("B", "topic-B", "angle-B", known)],
            "C": [draft("C", "topic-C", "angle-C", known)],
        },
    }
    duplicate = draft("A-duplicate", "topic-A", "angle-A-duplicate", known)
    payload["slots"]["A"][0]["body"] = (
        f"【事实】{known['claim']}\n【事实】{known['claim']}\n\n{long_analysis('A')}"
    )
    payload["slots"]["A"][0]["factual_claims"].append(duplicate["factual_claims"][0])

    result = run_adapter(tmp_path, payload)

    assert result.returncode == 1
    assert not (tmp_path / "gate-input.json").exists()
    assert "DUPLICATE_FACTUAL_CLAIM_ATOM_ID" in result.stderr


def test_adapter_removes_preexisting_output_when_payload_is_invalid(tmp_path):
    known = atom("atom-known", "主创公开说明了制作选择")
    payload = {
        "evidence_atoms": [known],
        "slots": {
            "A": [draft("A", "topic-A", "angle-A", known)],
            "B": [draft("B", "topic-B", "angle-B", known)],
            "C": [draft("C", "topic-C", "angle-C", known)],
        },
    }
    target = tmp_path / "gate-input.json"
    target.write_text("OLD_OUTPUT", encoding="utf-8")
    payload["slots"]["C"][0]["factual_claims"] = []

    result = run_adapter(tmp_path, payload)

    assert result.returncode == 1
    assert not target.exists()


def test_adapter_removes_preexisting_output_symlink_when_payload_is_invalid_without_deleting_target(tmp_path):
    source = tmp_path / "adapter-input.json"
    source.write_text("{invalid json", encoding="utf-8")
    old_target = tmp_path / "old-gate-input.json"
    old_target.write_text("STALE-GATE-INPUT", encoding="utf-8")
    target = tmp_path / "gate-input.json"
    target.symlink_to(old_target)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(source), "--output", str(target)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert not target.is_symlink()
    assert old_target.exists()
    assert old_target.read_text(encoding="utf-8") == "STALE-GATE-INPUT"


def test_adapter_rejects_resolved_input_output_path_conflict_before_reading_or_cleanup(tmp_path):
    source = tmp_path / "adapter-input.json"
    original = b"{invalid json that must remain byte-for-byte unchanged"
    source.write_bytes(original)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(source), "--output", str(source.parent / "." / source.name)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert source.exists()
    assert source.read_bytes() == original
    assert "INPUT_OUTPUT_PATH_CONFLICT" in result.stderr


def test_adapter_rejects_existing_output_directory_without_removing_its_contents(tmp_path):
    source = tmp_path / "adapter-input.json"
    source.write_text("{invalid json", encoding="utf-8")
    target = tmp_path / "gate-input"
    target.mkdir()
    old_file = target / "old-output.json"
    old_file.write_text("must remain", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(source), "--output", str(target)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert target.is_dir()
    assert old_file.read_text(encoding="utf-8") == "must remain"
    assert "OUTPUT_PATH_IS_DIRECTORY" in result.stderr


def test_adapter_rejects_unknown_normal_slot_key(tmp_path):
    known = atom("atom-known", "主创公开说明了制作选择")
    payload = {
        "evidence_atoms": [known],
        "slots": {
            "A": [draft("A", "topic-A", "angle-A", known)],
            "B": [draft("B", "topic-B", "angle-B", known)],
            "C": [draft("C", "topic-C", "angle-C", known)],
            "D": [draft("D", "topic-D", "angle-D", known)],
        },
    }

    result = run_adapter(tmp_path, payload)

    assert result.returncode == 1
    assert not (tmp_path / "gate-input.json").exists()
    assert "INVALID_SLOT_KEY" in result.stderr


def test_adapter_persists_only_claim_when_source_text_contains_unmapped_text(tmp_path):
    known = atom("atom-known", "主创公开说明了制作选择")
    known["source_text"] = "未映射的前文。主创公开说明了制作选择。未映射的后文。"
    payload = {
        "evidence_atoms": [known],
        "slots": {
            "A": [draft("A", "topic-A", "angle-A", known)],
            "B": [draft("B", "topic-B", "angle-B", known)],
            "C": [draft("C", "topic-C", "angle-C", known)],
        },
    }

    result = run_adapter(tmp_path, payload)

    assert result.returncode == 0, result.stderr
    output = json.loads((tmp_path / "gate-input.json").read_text(encoding="utf-8"))
    assert output["slots"]["A"][0]["evidence"]["sources"][0]["quote"] == known["claim"]
